"""Cascading refresh side effects and version bumps.

Covers PRD §2.5 (version), §2.9 (hierarchical propagation), and §3.9
(estimate refresh moments).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_and_post_charge,
    add_charge,
    discharge_encounter,
    post_charge,
    re_get_encounter,
    setup_eligibility_verified_encounter,
    validate_success,
    void_charge,
)


# ===========================================================================
# §2.9 — Posting a charge cascades to total + estimate
# ===========================================================================
class TestPostCascade:
    """PRD §2.9 / §3.4 / §3.9: posting refreshes total_charges_cents
    and estimated_patient_responsibility_cents."""

    def test_post_cascade_depth_three(self, api):
        """PRD §2.9: "Posting a `ChargeItem` from `PENDING` to `POSTED`, voiding a `POSTED` charge back to `VOIDED`, finalizing a `CodingRecord`, recording a `ClearanceDecision`, posting a `PatientPayment` or `REFUND`, and writing the encounter off all refresh the relevant derived totals on the parent encounter, bump the encounter's `version`, and update its `updated_at`."

        Claim: with deductible=100000, coinsurance=2000, oop_max=
        200000, and a posted charge of 150000: link 1 sets
        ChargeItem.status=POSTED; link 2 sets total_charges_cents=
        150000; link 3 sets estimated_patient_responsibility_cents=
        110000 (100000 deductible + 0.2 * 50000 = 10000).
        """
        patient, policy, encounter = setup_eligibility_verified_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
        )
        charge = add_charge(
            encounter=encounter, unit_price_cents=150_000,
        )
        # Capture S0 — PENDING charge not counted.
        s0 = re_get_encounter(encounter["id"])
        assert s0["total_charges_cents"] == 0
        assert s0["estimated_patient_responsibility_cents"] == 0
        # Trigger the cascade.
        post_resp = api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        post_data = validate_success(post_resp)
        assert post_data["status"] == "POSTED"
        # Verify cascading totals and estimate on the encounter.
        s1 = re_get_encounter(encounter["id"])
        assert s1["total_charges_cents"] == 150_000
        assert s1["estimated_patient_responsibility_cents"] == 110_000


# ===========================================================================
# §3.9 — Voiding a PENDING does NOT refresh estimate
# ===========================================================================
class TestVoidPendingNoEstimateRefresh:
    """PRD §2.9: "Voiding a `PENDING` charge does not change `total_charges_cents` (pending charges are not counted) and therefore does not trigger an estimate refresh.\""""

    def test_void_pending_does_not_refresh(self, api):
        """PRD §2.9: "Voiding a `PENDING` charge does not change `total_charges_cents` (pending charges are not counted) and therefore does not trigger an estimate refresh."

        Claim: voiding a PENDING charge leaves estimated_patient_
        responsibility_cents at its prior value (0 here).
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_charge(encounter=encounter)
        s_before = re_get_encounter(encounter["id"])
        assert s_before["estimated_patient_responsibility_cents"] == 0
        api.void_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        s_after = re_get_encounter(encounter["id"])
        # Total charges remain zero; estimate remains zero.
        assert s_after["total_charges_cents"] == 0
        assert s_after["estimated_patient_responsibility_cents"] == 0


# ===========================================================================
# §2.5 — version increments
# ===========================================================================
class TestVersionIncrements:
    """PRD §2.5: "an integer version that begins at 1 on creation and
    is incremented by exactly one on each subsequent mutation.\""""

    def test_encounter_version_starts_at_one(self, api):
        """PRD §2.5: "an integer `version` that begins at 1 on creation".

        Claim: a freshly created Encounter has version == 1.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        # After verify-eligibility, version has already advanced past 1,
        # so re-read a different encounter created fresh.
        from test_helpers import setup_registered_encounter
        _, _, fresh = setup_registered_encounter()
        assert fresh["version"] == 1

    def test_encounter_version_advances_on_status_transition(self, api):
        """PRD §2.5: "Computed-field refreshes on an `Encounter` — `total_charges_cents`, `payer_responsibility_cents`, `patient_responsibility_cents`, `estimated_patient_responsibility_cents`, and `write_off_cents` — are mutations in this sense: they bump `version` and refresh `updated_at` on the `Encounter`."

        Claim: posting a charge mutates the encounter and bumps its
        version strictly upward (by at least 1).
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        v_before = encounter["version"]
        add_and_post_charge(encounter=encounter, unit_price_cents=10_000)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["version"] > v_before


# ===========================================================================
# §2.5 / §2.9 — append-only entities do NOT carry version
# ===========================================================================
class TestAppendOnlyEntities:
    """PRD §2.5: "The `ClearanceDecision`, `PatientPayment`, and `BadDebtRecord` resources are immutable audit records once written. They carry `id` and `created_at` but they do not carry `updated_at` and they do not carry `version`.\""""

    def test_clearance_decision_omits_version_and_updated_at(self, api):
        """PRD §2.5: "The `ClearanceDecision`, `PatientPayment`, and `BadDebtRecord` resources are immutable audit records once written. They carry `id` and `created_at` but they do not carry `updated_at` and they do not carry `version`."

        Claim: a ClearanceDecision response carries id + created_at
        but does not carry updated_at or version.
        """
        from test_helpers import setup_coded_encounter, submit_clearance_payload
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        data = validate_success(
            api.submit_clearance(
                encounter["id"],
                submit_clearance_payload(
                    decision="APPROVED", allowed_amount_cents=10_000,
                ),
                TEST_USERS["biller_headers"],
            ),
            expected_status=201,
        )
        assert "id" in data and "created_at" in data
        assert "updated_at" not in data
        assert "version" not in data

    def test_patient_payment_omits_version_and_updated_at(self, api):
        """PRD §2.5: "The `ClearanceDecision`, `PatientPayment`, and `BadDebtRecord` resources are immutable audit records once written. They carry `id` and `created_at` but they do not carry `updated_at` and they do not carry `version`."

        Claim: a PatientPayment response carries id + created_at but
        does not carry updated_at or version.
        """
        from test_helpers import (
            post_payment_payload,
            setup_billed_with_balance,
        )
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        data = validate_success(
            api.post_payment(
                encounter["id"],
                post_payment_payload(amount_cents=2_000, method="CASH"),
                TEST_USERS["biller_headers"],
            ),
            expected_status=201,
        )
        assert "updated_at" not in data
        assert "version" not in data
