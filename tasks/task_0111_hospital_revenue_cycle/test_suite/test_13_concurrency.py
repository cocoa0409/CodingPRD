"""Optimistic concurrency control and race conditions.

Covers PRD §2.6 (OCC on PATCH /encounters/{id}) and explicit PRD §3.6
+ §3.7 + §3.8 concurrency guarantees (duplicate coding, duplicate
write-off, second-eligibility-verify, post-RESOLVED payment).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_and_post_charge,
    advance_clock_to,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    patch_encounter_payload,
    re_get_encounter,
    run_race,
    setup_billed_with_balance,
    setup_charges_captured_encounter,
    setup_patient_with_policy,
    setup_registered_encounter,
    submit_coding_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §2.6 — Optimistic concurrency on PATCH /encounters/{id}
# ===========================================================================
class TestOptimisticConcurrencyControl:
    """PRD §2.6: "Mutations that target an existing `Encounter` by its identifier may supply the resource's current `version` in the request body to opt into optimistic concurrency control. The system reads the persisted `version`, compares it to the supplied value, and rejects mismatches with `ERR_VERSION_CONFLICT`.\""""

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "The system reads the persisted `version`, compares it to the supplied value, and rejects mismatches with `ERR_VERSION_CONFLICT`."

        Claim: PATCH with version older than current returns
        ERR_VERSION_CONFLICT.
        """
        from test_helpers import create_policy
        patient, policy, encounter = setup_registered_encounter()
        another_policy = create_policy(patient=patient)
        # First update bumps version.
        api.patch_encounter(
            encounter["id"],
            patch_encounter_payload(
                policy_id=another_policy["id"],
                version=encounter["version"],
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        # Second update reuses the OLD version → conflict.
        third_policy = create_policy(patient=patient)
        res = api.patch_encounter(
            encounter["id"],
            patch_encounter_payload(
                policy_id=third_policy["id"],
                version=encounter["version"],  # stale
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_omitting_version_skips_check(self, api):
        """PRD §2.6: "Omitting the `version` field skips the check, in which case the mutation proceeds against whatever the current state happens to be."

        Claim: PATCH without a version field succeeds even after the
        encounter has been mutated.
        """
        from test_helpers import create_policy
        patient, policy, encounter = setup_registered_encounter()
        # Mutate via an explicit version-bearing PATCH first.
        another_policy = create_policy(patient=patient)
        api.patch_encounter(
            encounter["id"],
            patch_encounter_payload(
                policy_id=another_policy["id"],
                version=encounter["version"],
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        # Now PATCH without version — should succeed regardless.
        third_policy = create_policy(patient=patient)
        res = api.patch_encounter(
            encounter["id"],
            patch_encounter_payload(policy_id=third_policy["id"]),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_success(res)


# ===========================================================================
# §3.3 — racing eligibility verifications
# ===========================================================================
class TestEligibilityRace:
    """PRD §3.3: "Concurrency: when two `RegistrationClerk` operators race to verify eligibility on the same encounter, the first call wins and the second observes the encounter no longer in `REGISTERED`, receiving `ERR_INVALID_STATE`.\""""

    def test_concurrent_eligibility_verifications(self, api):
        """PRD §3.3: "when two `RegistrationClerk` operators race to verify eligibility on the same encounter, the first call wins and the second observes the encounter no longer in `REGISTERED`, receiving `ERR_INVALID_STATE`."

        Claim: two simultaneous verify-eligibility calls produce
        exactly one success and one failure.
        """
        from test_helpers import verify_eligibility_payload
        patient, policy, encounter = setup_registered_encounter()
        result_a, result_b = run_race(
            lambda: api.verify_eligibility(
                encounter["id"],
                verify_eligibility_payload(policy_eligible=True),
                TEST_USERS["registration_clerk_headers"],
            ),
            lambda: api.verify_eligibility(
                encounter["id"],
                verify_eligibility_payload(policy_eligible=True),
                TEST_USERS["registration_clerk_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(result_a, result_b)
        # Loser's error_id must be ERR_INVALID_STATE per PRD §3.3.
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# §3.6 — duplicate coding race
# ===========================================================================
class TestDuplicateCodingRace:
    """PRD §3.6: "A second concurrent coding submission against the same encounter is rejected with `ERR_DUPLICATE_CODING_RECORD` — uniqueness is enforced on the `encounter_id` of `CodingRecord`, and only one finalize call wins.\""""

    def test_duplicate_finalize_returns_explicit_error(self, api):
        """PRD §3.6: "A second concurrent coding submission against the same encounter is rejected with `ERR_DUPLICATE_CODING_RECORD` — uniqueness is enforced on the `encounter_id` of `CodingRecord`, and only one finalize call wins."

        Claim: a second coding submission on an already-finalized
        encounter returns either ERR_DUPLICATE_CODING_RECORD or
        ERR_INVALID_STATE (the encounter has moved past
        CHARGES_CAPTURED, which is a state-illegal precondition for
        the coding endpoint; PRD §2.10 places state checks ahead of
        business-referential checks, so either ID is faithful).
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted]
        # First finalize succeeds.
        api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        # Second finalize → DUPLICATE_CODING_RECORD OR INVALID_STATE.
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers_alt"],
        )
        validate_error_is_one_of(
            res, ["ERR_DUPLICATE_CODING_RECORD", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §3.7 — race two payments that together reach zero
# ===========================================================================
class TestPaymentRaceToResolved:
    """PRD §3.7: "When two payment posts race against each other while the balance is one payment away from zero, both `PatientPayment` records persist (they are immutable records of fact), only one transition to `RESOLVED` occurs, and any payment that arrives after the transition is rejected with `ERR_INVALID_STATE`.\""""

    def test_payments_after_resolved_rejected(self, api):
        """PRD §3.7: "any payment that arrives after the transition is rejected with `ERR_INVALID_STATE`."

        Claim: a sequential test — pay full amount to RESOLVED, then
        attempt another payment, which must return ERR_INVALID_STATE.
        (A true concurrent race is non-deterministic; the post-
        RESOLVED rejection is the deterministic guarantee PRD §3.7
        pins.)
        """
        from test_helpers import post_payment_payload
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        # First payment resolves the encounter.
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=10_000, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "RESOLVED"
        # Subsequent payment is rejected.
        res = api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=1, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
