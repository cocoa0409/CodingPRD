"""Discharge gate: ≥1 POSTED charge AND zero PENDING charges.

Covers PRD §3.6 (discharge preconditions and side effects).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_and_post_charge,
    add_charge,
    discharge_encounter,
    re_get_encounter,
    setup_eligibility_verified_encounter,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — discharge happy path
# ===========================================================================
class TestDischargeHappyPath:
    """PRD §3.6: discharge advances ELIGIBILITY_VERIFIED → CHARGES_CAPTURED."""

    def test_discharge_advances_state_and_stamps_discharge_at(self, api):
        """PRD §3.6: "When charge capture is complete, a `RegistrationClerk` discharges the encounter, advancing it from `ELIGIBILITY_VERIFIED` to `CHARGES_CAPTURED` and stamping `discharge_at` to the request instant."

        Claim: a successful discharge sets Encounter.status to
        CHARGES_CAPTURED and stamps discharge_at.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        add_and_post_charge(encounter=encounter, unit_price_cents=10_000)
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_success(res)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CHARGES_CAPTURED"
        assert refreshed.get("discharge_at") is not None


# ===========================================================================
# §3.6 — discharge gate ERR_CHARGES_NOT_READY
# ===========================================================================
class TestDischargeChargesGate:
    """PRD §3.6: "Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`; either condition failing produces `ERR_CHARGES_NOT_READY`."""

    def test_discharge_with_no_posted_charges_rejected(self, api):
        """PRD §3.6: "Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`; either condition failing produces `ERR_CHARGES_NOT_READY`."

        Claim: discharging an encounter with no charges returns
        ERR_CHARGES_NOT_READY.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_CHARGES_NOT_READY")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "ELIGIBILITY_VERIFIED"

    def test_discharge_with_pending_charges_rejected(self, api):
        """PRD §3.6: "Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`; either condition failing produces `ERR_CHARGES_NOT_READY`."

        Claim: an encounter with one POSTED + one PENDING is still
        ERR_CHARGES_NOT_READY (because of the PENDING).
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        add_and_post_charge(encounter=encounter, unit_price_cents=5000)
        # Add a second charge but DO NOT post it — leaves a PENDING.
        add_charge(encounter=encounter, cpt_code="99214")
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_CHARGES_NOT_READY")


# ===========================================================================
# §3.6 — discharge refreshes total_charges_cents and estimate
# ===========================================================================
class TestDischargeRefresh:
    """PRD §3.6: discharge re-runs aggregation and estimate."""

    def test_discharge_refreshes_estimate_using_locked_ledger(self, api):
        """PRD §3.6: "Discharge re-runs `charge_total_aggregation` and re-runs the estimate variant of `patient_responsibility_calc` so that the locked-in ledger snapshot is reflected in `estimated_patient_responsibility_cents` going into coding."

        Claim: with deductible_cents=100000, coinsurance_rate_bps=2000,
        oop_max=200000, and a single POSTED charge of 150000, after
        discharge: total_charges_cents == 150000 AND estimate ==
        100000 + 0.2 * (150000 - 100000) == 110000.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
        )
        add_and_post_charge(
            encounter=encounter, unit_price_cents=150_000,
        )
        api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["total_charges_cents"] == 150_000
        assert refreshed["estimated_patient_responsibility_cents"] == 110_000
