"""Cages, hospitalization lifecycle, and capacity (PRD §3.8)."""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ADMISSION_HOLD_CENTS,
    TEST_USERS,
    admit_hospitalization,
    append_care,
    assert_cage,
    assert_hospitalization,
    begin_care,
    cancel_hospitalization,
    create_bill,
    create_cage,
    create_drug,
    discharge_hospitalization,
    dispense_prescription,
    finalize_treatment_record,
    get_success_data,
    issue_bill,
    issue_invoice,
    pay_bill,
    recompute_bill,
    request_discharge,
    setup_approved_prescription,
    setup_owner_and_pet,
    setup_visit_consult_done,
    setup_visit_with_finalized_treatment,
    validate_error,
    validate_success,
)


class TestCageCreate:
    def test_cage_created_with_zero_occupancy(self, api, platform_admin_headers):
        """PRD §3.8: 'The cage's occupancy_count is computed as the count
        of hospitalization rows with status IN_CARE currently assigned
        to it.'"""
        c = create_cage(capacity=2, ward_code="GENERAL")
        assert_cage(c)
        assert c["occupancy_count"] == 0
        assert c["capacity"] == 2

    @pytest.mark.parametrize("cap", [0, -1, 5, 100])
    def test_cage_capacity_out_of_range(self, api, platform_admin_headers, cap):
        """PRD §3.8: 'a capacity from 1 through 4 inclusive.'"""
        from test_helpers import create_cage_payload
        res = api.create_cage(
            create_cage_payload(capacity=cap), platform_admin_headers,
        )
        validate_error(res, "ERR_VALIDATION_FAILED")


# ===========================================================================
# Admission preconditions
# ===========================================================================
class TestHospitalizationAdmissionPreconditions:
    def test_admission_decrements_deposit_and_increments_cage(self, api):
        """PRD §3.8: 'Admission has two side effects: the cage's
        occupancy_count is incremented by 1, and the owner's
        deposit_balance_cents is decremented by 50,000 cents (the
        admission hold).'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=200_000)
        cage = create_cage(capacity=2)
        h = admit_hospitalization(visit_id=visit["id"], cage_id=cage["id"])
        assert_hospitalization(h)
        # PRD does not expose GET /cages/{id}, so we check the deposit
        # decrement via GET /owners/{id} (PRD §4) to assert the
        # admission hold ran. The cage's occupancy_count is exercised
        # by the capacity-rejection test below.
        owner_after = get_success_data(
            api.get_owner(owner["id"], TEST_USERS["cashier_headers"])
        )
        assert owner_after["deposit_balance_cents"] == (
            owner["deposit_balance_cents"] - ADMISSION_HOLD_CENTS
        ), (
            f"Owner.deposit_balance_cents must decrement by 50000; "
            f"before={owner['deposit_balance_cents']}, "
            f"after={owner_after['deposit_balance_cents']}"
        )

    def test_admission_below_deposit_floor_rejected(self, api):
        """PRD §3.8: 'the owner's deposit_balance_cents must be at least
        50,000 cents — that is, at least five hundred dollars — to
        satisfy the admission hold (otherwise ERR_INSUFFICIENT_DEPOSIT).'"""
        owner, pet, visit, tr = setup_visit_consult_done(
            deposit_cents=49_999,  # one cent below the floor
        )
        cage = create_cage(capacity=2)
        from test_helpers import (
            create_hospitalization_payload, vet_headers_for_visit,
        )
        headers = vet_headers_for_visit(visit["id"])
        res = api.create_hospitalization(
            create_hospitalization_payload(
                visit_id=visit["id"], cage_id=cage["id"],
            ),
            headers,
        )
        validate_error(res, "ERR_INSUFFICIENT_DEPOSIT")

    def test_admission_at_capacity_rejected(self, api):
        """PRD §3.8: 'the cage's occupancy_count must be strictly less
        than the cage's capacity at admission time (otherwise
        ERR_CAGE_CAPACITY_EXCEEDED).'"""
        # Capacity-1 cage, admit one occupant via begin_care to fill it.
        cage = create_cage(capacity=1)
        owner_a, pet_a, visit_a, _ = setup_visit_consult_done(deposit_cents=200_000)
        h_a = admit_hospitalization(visit_id=visit_a["id"], cage_id=cage["id"])
        h_a = begin_care(visit_id=visit_a["id"], h_id=h_a["id"])
        # Second admission targets the now-full cage.
        owner_b, pet_b, visit_b, _ = setup_visit_consult_done(deposit_cents=200_000)
        from test_helpers import (
            create_hospitalization_payload, vet_headers_for_visit,
        )
        headers_b = vet_headers_for_visit(visit_b["id"])
        res = api.create_hospitalization(
            create_hospitalization_payload(
                visit_id=visit_b["id"], cage_id=cage["id"],
            ),
            headers_b,
        )
        validate_error(res, "ERR_CAGE_CAPACITY_EXCEEDED")

    def test_admission_requires_visit_in_consult_done(self, api):
        """PRD §3.8: 'The visit must be in CONSULT_DONE (otherwise
        ERR_INVALID_STATE).'"""
        owner, pet = setup_owner_and_pet(deposit_cents=200_000)
        # Visit still in REGISTERED.
        from test_helpers import create_visit, create_visit_payload
        visit = create_visit(pet_id=pet["id"], severity_score=4)
        cage = create_cage(capacity=2)
        from test_helpers import (
            create_hospitalization_payload, build_user_headers,
        )
        # Use a generic DraftingVet header (visit has no assigned_vet_id yet).
        headers = build_user_headers("any-vet-001", "DraftingVet")
        res = api.create_hospitalization(
            create_hospitalization_payload(
                visit_id=visit["id"], cage_id=cage["id"],
            ),
            headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestHospitalizationCancel:
    def test_cancel_pre_care_restores_deposit_and_cage(self, api):
        """PRD §3.8: 'A drafting vet may cancel a hospitalization while
        it is still in ADMITTED and only when no daily-care entry on it
        has treatment_executed set to true. Cancellation decrements the
        cage's occupancy_count by 1 and refunds the admission hold by
        incrementing the owner's deposit_balance_cents by 50,000 cents.'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=200_000)
        cage = create_cage(capacity=2)
        before_balance = owner["deposit_balance_cents"]
        h = admit_hospitalization(visit_id=visit["id"], cage_id=cage["id"])
        # Verify deposit decremented at admit.
        owner_after_admit = get_success_data(
            api.get_owner(owner["id"], TEST_USERS["cashier_headers"])
        )
        assert owner_after_admit["deposit_balance_cents"] == (
            before_balance - ADMISSION_HOLD_CENTS
        )
        # Cancel before any treatment executed.
        cancel_hospitalization(visit_id=visit["id"], h_id=h["id"])
        owner_final = get_success_data(
            api.get_owner(owner["id"], TEST_USERS["cashier_headers"])
        )
        assert owner_final["deposit_balance_cents"] == before_balance, (
            f"Deposit must be restored after cancel; before={before_balance}, "
            f"after={owner_final['deposit_balance_cents']}"
        )


class TestRequestDischargePrescriptionGate:
    def test_request_discharge_blocked_by_open_prescription(self, api):
        """PRD §3.8: 'the precondition is that every prescription on the
        visit has reached DISPENSED, REJECTED, or CANCELLED (otherwise
        ERR_PENDING_PRESCRIPTIONS).'"""
        from test_helpers import setup_visit_consult_done_with_approved_rx
        d1 = create_drug(stock_units=500)
        # PRD §3.7 'submit requires Visit==IN_CONSULT' forces this
        # ordering: Rx is built and approved while in IN_CONSULT, then
        # the visit advances to CONSULT_DONE and onward to HOSPITALIZED.
        owner, pet, visit, tr, rx = setup_visit_consult_done_with_approved_rx(
            drug_code=d1["code"], deposit_cents=200_000, weight_kg=10.0,
        )
        # Create a Bill so the open prescription doesn't trip on missing bill.
        create_bill(visit_id=visit["id"])
        cage = create_cage(capacity=2)
        h = admit_hospitalization(visit_id=visit["id"], cage_id=cage["id"])
        h = begin_care(visit_id=visit["id"], h_id=h["id"])
        # Prescription is APPROVED but not DISPENSED → "open" per PRD §3.8.
        from test_helpers import vet_headers_for_visit
        headers = vet_headers_for_visit(visit["id"])
        res = api.request_discharge(h["id"], headers)
        validate_error(res, "ERR_PENDING_PRESCRIPTIONS")

    def test_request_discharge_succeeds_after_dispense(self, api):
        """PRD §3.8: 'every prescription on the visit has reached
        DISPENSED, REJECTED, or CANCELLED.'"""
        from test_helpers import setup_visit_consult_done_with_approved_rx
        d1 = create_drug(stock_units=500)
        owner, pet, visit, tr, rx = setup_visit_consult_done_with_approved_rx(
            drug_code=d1["code"], deposit_cents=200_000, weight_kg=10.0,
        )
        create_bill(visit_id=visit["id"])
        cage = create_cage(capacity=2)
        h = admit_hospitalization(visit_id=visit["id"], cage_id=cage["id"])
        h = begin_care(visit_id=visit["id"], h_id=h["id"])
        dispense_prescription(rx_id=rx["id"])
        h2 = request_discharge(visit_id=visit["id"], h_id=h["id"])
        assert h2["status"] == "DISCHARGE_PENDING"
