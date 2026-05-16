"""Insurance eligibility verification — both branches and plan-year gate.

Covers PRD §3.3 (eligibility verification) plus PRD §2.11 (clock).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock_in_plan_year_2026,
    create_encounter,
    create_patient,
    create_policy,
    is_iso8601_timestamp,
    re_get_encounter,
    setup_patient_with_policy,
    setup_registered_encounter,
    validate_error,
    validate_success,
    verify_eligibility_payload,
)


# ===========================================================================
# §3.3 — eligible branch: Encounter REGISTERED → ELIGIBILITY_VERIFIED
# ===========================================================================
class TestEligibleBranch:
    """PRD §3.3: When the payer reports the policy as eligible …"""

    def test_eligible_branch_advances_encounter_status(self, api):
        """PRD §3.3: "When the payer reports the policy as eligible (the `policy_eligible=true` branch), the policy transitions from `UNVERIFIED` to `ELIGIBLE` and the encounter transitions from `REGISTERED` to `ELIGIBILITY_VERIFIED`."

        Claim: a successful verify-eligibility (policy_eligible=true)
        sets Encounter.status to ELIGIBILITY_VERIFIED.
        """
        patient, policy, encounter = setup_registered_encounter()
        res = api.verify_eligibility(
            encounter["id"], verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_success(res)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "ELIGIBILITY_VERIFIED"

    def test_eligible_branch_seeds_estimate_to_zero(self, api):
        """PRD §3.3: "The estimate variant of the patient-responsibility waterfall runs on the pre-service `total_charges_cents` (which is 0 at this point), so the encounter's `estimated_patient_responsibility_cents` is seeded to 0."

        Claim: after verify-eligibility succeeds, the encounter's
        estimated_patient_responsibility_cents is 0.
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"], verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["estimated_patient_responsibility_cents"] == 0


# ===========================================================================
# §3.3 — INELIGIBLE branch
# ===========================================================================
class TestIneligibleBranch:
    """PRD §3.3: ineligible branch leaves Encounter at REGISTERED."""

    def test_ineligible_branch_leaves_encounter_at_registered(self, api):
        """PRD §3.3: "When the payer reports the policy as not eligible (the `policy_eligible=false` branch), the policy transitions from `UNVERIFIED` to `INELIGIBLE` — a terminal status for the policy — and the encounter remains in `REGISTERED` so that registration can re-route to a different policy via the metadata update."

        Claim: verify-eligibility (policy_eligible=false) leaves
        Encounter.status at REGISTERED.
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=False),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "REGISTERED"


# ===========================================================================
# §3.3 — preconditions: encounter must be REGISTERED
# ===========================================================================
class TestEligibilityPreconditions:
    """PRD §3.3: "Two preconditions guard both branches.\""""

    def test_verify_on_already_verified_encounter_rejected(self, api):
        """PRD §3.3: "the encounter must be in the `REGISTERED` status — verifying eligibility on an encounter that has already advanced is rejected with `ERR_INVALID_STATE`."

        Claim: a second verify-eligibility call on an already
        ELIGIBILITY_VERIFIED encounter returns ERR_INVALID_STATE.
        """
        patient, policy, encounter = setup_registered_encounter()
        # First verify advances to ELIGIBILITY_VERIFIED.
        api.verify_eligibility(
            encounter["id"], verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        # Second call must fail.
        res = api.verify_eligibility(
            encounter["id"], verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.3 / §2.11 — plan_year must equal current calendar year
# ===========================================================================
class TestPlanYearGate:
    """PRD §3.3: "the policy's `plan_year` must equal the current calendar year derived from the server clock; a stale plan-year produces `ERR_PLAN_YEAR_EXPIRED`."
    """

    def test_stale_plan_year_rejected(self, api):
        """PRD §3.3: "the policy's `plan_year` must equal the current calendar year derived from the server clock; a stale plan-year produces `ERR_PLAN_YEAR_EXPIRED`."

        Claim: a policy with plan_year=2025 against the clock anchored
        to 2026 returns ERR_PLAN_YEAR_EXPIRED on verify-eligibility.
        """
        anchor_clock_in_plan_year_2026()
        patient = create_patient()
        policy = create_policy(patient=patient, plan_year=2025)
        encounter = create_encounter(patient=patient, policy=policy)
        res = api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_PLAN_YEAR_EXPIRED")
        # And encounter must remain REGISTERED.
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "REGISTERED"

    def test_future_plan_year_rejected(self, api):
        """PRD §3.3: "the policy's `plan_year` must equal the current calendar year derived from the server clock; a stale plan-year produces `ERR_PLAN_YEAR_EXPIRED`."

        Claim: a policy with plan_year=2027 against the clock anchored
        to 2026 returns ERR_PLAN_YEAR_EXPIRED on verify-eligibility.
        """
        anchor_clock_in_plan_year_2026()
        patient = create_patient()
        policy = create_policy(patient=patient, plan_year=2027)
        encounter = create_encounter(patient=patient, policy=policy)
        res = api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_PLAN_YEAR_EXPIRED")


# ===========================================================================
# §3.3 — verified_at stamped on both branches
# ===========================================================================
class TestVerifiedAtStamp:
    """PRD §3.3: "Regardless of branch, `verified_at` on the underlying policy is set to the request instant.\""""

    def test_verified_at_set_on_eligible_branch(self, api):
        """PRD §3.3: "Regardless of branch, `verified_at` on the underlying policy is set to the request instant."

        Claim: after a successful eligible verify, the policy carries a
        non-null verified_at timestamp.
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        from test_helpers import re_get_policy
        refreshed_policy = re_get_policy(patient["id"], policy["id"])
        assert refreshed_policy.get("verified_at") is not None
        assert is_iso8601_timestamp(refreshed_policy["verified_at"])
        assert refreshed_policy["status"] == "ELIGIBLE"

    def test_ineligible_branch_sets_policy_to_ineligible(self, api):
        """PRD §3.3: "When the payer reports the policy as not eligible (the `policy_eligible=false` branch), the policy transitions from `UNVERIFIED` to `INELIGIBLE` — a terminal status for the policy"

        Claim: after policy_eligible=false, the policy carries
        status='INELIGIBLE'.
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=False),
            TEST_USERS["registration_clerk_headers"],
        )
        from test_helpers import re_get_policy
        refreshed_policy = re_get_policy(patient["id"], policy["id"])
        assert refreshed_policy["status"] == "INELIGIBLE"
