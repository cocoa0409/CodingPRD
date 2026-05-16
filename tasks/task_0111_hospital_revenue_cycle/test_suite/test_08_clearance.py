"""Payer clearance: decision, payload validation, and waterfall handoff.

Covers PRD §3.6 (clearance submission + payer_clearance_calc).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_clearance_decision,
    re_get_encounter,
    setup_coded_encounter,
    setup_charges_captured_encounter,
    submit_clearance_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Clearance happy path: CODED → CLEARED
# ===========================================================================
class TestClearanceHappyPath:
    """PRD §3.6: A Biller submits the payer's adjudication decision."""

    def test_approved_decision_advances_encounter_to_cleared(self, api):
        """PRD §3.6: "The transition from `CODED` to `CLEARED` runs the payer-clearance calculation and then the final variant of the patient-responsibility waterfall."

        Claim: a successful APPROVED clearance advances Encounter to
        CLEARED.
        """
        patient, policy, encounter, posted = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=10_000,
            ),
            TEST_USERS["biller_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_clearance_decision(data)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CLEARED"


# ===========================================================================
# §3.6 — clearance preconditions
# ===========================================================================
class TestClearancePreconditions:
    """PRD §3.6: "The encounter must already have a `FINALIZED` coding record.\""""

    def test_clearance_before_coding_rejected(self, api):
        """PRD §3.6: "The encounter must already have a `FINALIZED` coding record."

        Claim: clearance on a CHARGES_CAPTURED (not yet coded)
        encounter returns ERR_INVALID_STATE.
        """
        patient, policy, encounter, _ = setup_charges_captured_encounter()
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED",
                allowed_amount_cents=encounter["total_charges_cents"],
            ),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.6 — allowed_amount_cents bounds
# ===========================================================================
class TestAllowedAmountBounds:
    """PRD §3.6: "must not exceed the encounter's current `total_charges_cents` (over-allowance is rejected with `ERR_ALLOWED_EXCEEDS_CHARGES`)"""

    def test_allowed_amount_exceeding_total_charges_rejected(self, api):
        """PRD §3.6: "must not exceed the encounter's current `total_charges_cents` (over-allowance is rejected with `ERR_ALLOWED_EXCEEDS_CHARGES`)"

        Claim: allowed_amount_cents > total_charges_cents returns
        ERR_ALLOWED_EXCEEDS_CHARGES.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=20_000,
            ),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_ALLOWED_EXCEEDS_CHARGES")

    def test_allowed_amount_equal_total_charges_accepted(self, api):
        """PRD §3.6: "must not exceed the encounter's current `total_charges_cents`".

        Claim: allowed_amount_cents == total_charges_cents is
        accepted.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=10_000,
            ),
            TEST_USERS["biller_headers"],
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.6 — DENIED payload validation
# ===========================================================================
class TestDeniedPayloadValidation:
    """PRD §3.6: "must be exactly 0 when `decision` is `DENIED`.\""""

    def test_denied_with_nonzero_allowed_rejected(self, api):
        """PRD §3.6: "missing or inconsistent payloads — including a `DENIED` decision with a non-zero `allowed_amount_cents` — are rejected with `ERR_INVALID_CLEARANCE_PAYLOAD`."

        Claim: decision=DENIED with allowed_amount_cents=500 returns
        ERR_INVALID_CLEARANCE_PAYLOAD.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=500,
                denial_reason_code="CO-50",
            ),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_CLEARANCE_PAYLOAD")

    def test_denied_without_denial_reason_code_rejected(self, api):
        """PRD §3.6: "A `denial_reason_code` is required when `decision` is `DENIED` and is also required when `decision` is `PARTIAL`"

        Claim: decision=DENIED without denial_reason_code returns
        ERR_INVALID_CLEARANCE_PAYLOAD.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=0,
            ),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_CLEARANCE_PAYLOAD")

    def test_partial_without_denial_reason_code_rejected(self, api):
        """PRD §3.6: "A `denial_reason_code` is required when `decision` is `DENIED` and is also required when `decision` is `PARTIAL`"

        Claim: decision=PARTIAL without denial_reason_code returns
        ERR_INVALID_CLEARANCE_PAYLOAD.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="PARTIAL", allowed_amount_cents=5_000,
            ),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_CLEARANCE_PAYLOAD")


# ===========================================================================
# §3.6 — payer_clearance_calc DENIED branch
# ===========================================================================
class TestPayerClearanceCalcDenied:
    """PRD §3.6: "When `decision` is `DENIED`, `payer_responsibility_cents` is set to 0."""

    def test_denied_with_contractual_writedown_sets_payer_zero(self, api):
        """PRD §3.6: "When `decision` is `DENIED`, `payer_responsibility_cents` is set to 0."
        PRD §3.6: "is treated as a contractual write-down and is **not** billed to the patient, with one specific exception"

        Claim: decision=DENIED with a NON-patient-responsibility
        denial code (e.g., CO-50) yields
        payer_responsibility_cents == 0 AND
        patient_responsibility_cents == 0 (contractual write-down).
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            unit_price_cents=10_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=0,
                denial_reason_code="CO-50",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["payer_responsibility_cents"] == 0
        assert refreshed["patient_responsibility_cents"] == 0

    def test_denied_with_pr1_code_bypass_routes_to_patient(self, api):
        """PRD §3.6: "when `denial_reason_code` equals one of the patient-responsibility reason codes (`PR-1`, `PR-2`, or `PR-3`), the unallowed portion bypasses the deductible / coinsurance / OOP waterfall entirely and flows into `patient_responsibility_cents` in full."

        Claim: decision=DENIED, denial_reason_code='PR-1', with
        total_charges_cents=10000, yields
        patient_responsibility_cents == 10000 AND
        payer_responsibility_cents == 0.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=10_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=0,
                denial_reason_code="PR-1",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["payer_responsibility_cents"] == 0
        assert refreshed["patient_responsibility_cents"] == 10_000
