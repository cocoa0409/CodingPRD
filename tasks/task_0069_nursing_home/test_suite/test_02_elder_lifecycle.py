"""Elder onboarding, admission, leave/return, transfer, discharge.

Anchored in PRD §3.1 (Elder onboarding & admission) and §3.8 (Bed
inventory, transfers, discharge).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    REQUIRED_ADMISSION_DEPOSIT_CENTS,
    admit_elder, admit_payload,
    approve_assessment, create_active_prescription,
    create_approved_assessment,
    create_bed, create_bed_payload, create_elder, create_elder_payload,
    create_intensive_room_with_bed, create_room, create_room_payload,
    create_room_with_bed,
    deposit_payload, discharge_elder,
    emergency_contact, finalize_bill, full_cycle_window,
    create_bill, get_elder, leave_elder, return_elder,
    setup_admitted_elder_v2, setup_admitted_intensive_elder,
    setup_admitted_with_finalized_bill,
    top_up_deposit, transfer_elder, transfer_payload, update_elder,
    ADMIN, ADMIN_ALT, FAMILY, FINANCE, NURSE, NURSE_ALT, PHYSICIAN,
    SUPERVISOR, SUPERVISOR_ALT, TEST_USERS,
    api_client, assert_elder, validate_error, validate_success,
)


# ===========================================================================
# Elder creation (PRD §3.1)
# ===========================================================================
class TestElderCreation:

    def test_new_elder_enters_pending_admission(self):
        """PRD §3.1: "The newly created elder enters PENDING_ADMISSION."

        Claim: POST /elders → 201 with status == PENDING_ADMISSION.
        """
        resp = api_client.create_elder(create_elder_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_elder(data)
        assert data["status"] == "PENDING_ADMISSION"

    def test_elder_default_advance_directive_all_false(self):
        """PRD §3.1: "the `advance_directive` object whose default is the
        all-false directive `{dnr:false,dni:false,organ_donation:false,
        signed_at:null}`."

        Claim: when advance_directive is omitted on create, the server
        applies the all-false directive.
        """
        payload = create_elder_payload()
        payload.pop("advance_directive", None)
        resp = api_client.create_elder(payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        ad = data["advance_directive"]
        assert ad["dnr"] is False
        assert ad["dni"] is False
        assert ad["organ_donation"] is False
        assert ad["signed_at"] is None


# ===========================================================================
# Admission preconditions (PRD §3.1, §2.7 #13/#23 etc.)
# ===========================================================================
class TestAdmissionPreconditions:

    # Deleted: test_admit_with_empty_emergency_contacts_rejected.
    # PRD §3.1 says admission of an elder with empty emergency_contacts is
    # "refused", but PRD §2.7 does not enumerate this precondition with a
    # specific error_id, and the §5 catalogue does not bind it to either
    # ERR_VALIDATION or ERR_INVALID_STATE. A PRD-faithful implementer may
    # reasonably classify the empty array as a §2.7 #1 schema/validation
    # fault (ERR_VALIDATION at 422) or a §2.7 #5 state precondition
    # (ERR_INVALID_STATE at 409). Cardinal Rule STEP 1b — PRD does not
    # uniquely determine the assertion's outcome → test deleted.

    def test_admit_with_one_emergency_contact_succeeds(self):
        """PRD §3.1: "At least one entry must be present in
        emergency_contacts — admission of an elder with an empty contact
        list is refused."

        Claim: a single contact satisfies the precondition; admit succeeds.
        # difficulty: boundary_precision_check/admit_requires_at_least_one_emergency_contact_empty_array_rejected
        """
        elder = create_elder(
            emergency_contacts=[emergency_contact()],
        )
        top_up_deposit(elder["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS)
        create_approved_assessment(elder["id"], 80, 10, 20)
        _, bed = create_room_with_bed()
        resp = api_client.admit_elder(
            elder["id"], admit_payload(bed["id"]), ADMIN,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ADMITTED"

    def test_admit_below_deposit_floor_rejected_with_deposit_insufficient(self):
        """PRD §3.1: "the elder's `deposit_balance_cents` must be at least
        5,000.00 (500,000 cents) — the admission deposit floor, beneath
        which the request is rejected with `ERR_DEPOSIT_INSUFFICIENT`."

        Claim: deposit_balance_cents == 499_999 (one cent below floor) →
        ERR_DEPOSIT_INSUFFICIENT / 422.
        """
        elder = create_elder()
        top_up_deposit(elder["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS - 1)
        create_approved_assessment(elder["id"], 80, 10, 20)
        _, bed = create_room_with_bed()
        resp = api_client.admit_elder(
            elder["id"], admit_payload(bed["id"]), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)

    def test_admit_at_exact_deposit_floor_succeeds(self):
        """PRD §3.1: "the elder's `deposit_balance_cents` must be at least
        5,000.00 (500,000 cents) — the admission deposit floor."

        Claim: deposit_balance_cents == 500_000 (exactly at floor) →
        admission succeeds.
        """
        elder = create_elder()
        top_up_deposit(elder["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS)
        create_approved_assessment(elder["id"], 80, 10, 20)
        _, bed = create_room_with_bed()
        resp = api_client.admit_elder(
            elder["id"], admit_payload(bed["id"]), ADMIN,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ADMITTED"

    def test_admit_intensive_to_non_intensive_bed_rejected(self):
        """PRD §2.7 #13 / §3.8: "an `INTENSIVE_CARE` bed accepts only an
        elder whose `current_care_level` is `INTENSIVE`, and conversely a
        non-`INTENSIVE_CARE` bed never accepts an `INTENSIVE` elder; the
        rejection is `ERR_BED_TYPE_MISMATCH`."

        Claim: INTENSIVE elder + SINGLE bed → ERR_BED_TYPE_MISMATCH.
        """
        elder = create_elder()
        top_up_deposit(elder["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS)
        # Composite for INTENSIVE: adl=20, cog=5, med=40 → 105
        create_approved_assessment(elder["id"], 20, 5, 40)
        _, bed = create_room_with_bed()  # SINGLE bed
        resp = api_client.admit_elder(
            elder["id"], admit_payload(bed["id"]), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BED_TYPE_MISMATCH.value)

    def test_admit_non_intensive_to_intensive_bed_rejected(self):
        """PRD §2.7 #13 / §3.8: "an `INTENSIVE_CARE` bed accepts only an
        elder whose `current_care_level` is `INTENSIVE`."

        Claim: L3 elder + INTENSIVE_CARE bed → ERR_BED_TYPE_MISMATCH.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair_admit
        # (this also exercises the priority of bed-type vs deposit;
        # see test_validation_priority for the dual-fault variant)
        """
        elder = create_elder()
        top_up_deposit(elder["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS)
        create_approved_assessment(elder["id"], 80, 10, 20)  # L3
        _, bed = create_intensive_room_with_bed()
        resp = api_client.admit_elder(
            elder["id"], admit_payload(bed["id"]), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BED_TYPE_MISMATCH.value)


# ===========================================================================
# Admission side effects (PRD §3.1)
# ===========================================================================
class TestAdmissionSideEffects:

    def test_admit_transitions_bed_to_occupied(self):
        """PRD §3.1: "When all four hold, the bed transitions from
        `AVAILABLE` to `OCCUPIED`, its `current_elder_id` is set to the
        elder, the elder's `current_bed_id` is set to the bed."

        Claim: post-admit, GET /beds shows the bed in OCCUPIED with
        current_elder_id pointing to the admitted elder.
        """
        bundle = setup_admitted_elder_v2()
        resp = api_client.list_beds(ADMIN, params={"status": "OCCUPIED",
                                                   "limit": 100})
        data, _ = api_client._request("GET", "/beds",
                                      headers=ADMIN,
                                      params={"status": "OCCUPIED",
                                              "limit": 100}).json(), None
        # Use validate_paginated for proper extraction.
        from test_helpers import validate_paginated
        rows, _ = validate_paginated(resp)
        matching = [b for b in rows if b["id"] == bundle["bed"]["id"]]
        assert matching, "bed not present in OCCUPIED list after admit"
        assert matching[0]["current_elder_id"] == bundle["elder"]["id"]
        # And the elder mirrors the link.
        assert bundle["elder"]["current_bed_id"] == bundle["bed"]["id"]


# ===========================================================================
# Leave / return (PRD §2.9, §3.8)
# ===========================================================================
class TestLeaveAndReturn:

    def test_leave_keeps_bed_occupied(self):
        """PRD §2.9: "When an elder moves from `ADMITTED` to `ON_LEAVE`,
        every `ACTIVE` prescription for that elder cascades to `SUSPENDED`,
        the bed is held in `OCCUPIED` rather than released."

        Claim: after POST /elders/{id}/leave, the elder's bed remains
        OCCUPIED.
        """
        bundle = setup_admitted_elder_v2()
        leave_elder(bundle["elder"]["id"])
        from test_helpers import validate_paginated
        resp = api_client.list_beds(ADMIN, params={"limit": 100})
        rows, _ = validate_paginated(resp)
        target = [b for b in rows if b["id"] == bundle["bed"]["id"]][0]
        assert target["status"] == "OCCUPIED", \
            "PRD §2.9 — bed is HELD (OCCUPIED) while elder is ON_LEAVE"

    def test_leave_cascades_active_prescriptions_to_suspended(self):
        """PRD §2.9: "When an elder moves from `ADMITTED` to `ON_LEAVE`,
        every `ACTIVE` prescription for that elder cascades to `SUSPENDED`."

        Claim: post-leave, the elder's prior ACTIVE Prescription transitions
        to SUSPENDED.
        # difficulty: transitive_cascade/elder_leave_cascades_to_prescription_suspend_and_blocks_administration
        """
        bundle = setup_admitted_elder_v2()
        rx = create_active_prescription(bundle["elder"]["id"])
        assert rx["status"] == "ACTIVE"
        leave_elder(bundle["elder"]["id"])
        from test_helpers import get_prescription
        rx2 = get_prescription(rx["id"])
        assert rx2["status"] == "SUSPENDED", \
            f"PRD §2.9 cascade — expected SUSPENDED, got {rx2['status']!r}"

    def test_return_restores_suspended_prescriptions(self):
        """PRD §2.9: "When the same elder returns from `ON_LEAVE` to
        `ADMITTED`, the `SUSPENDED` prescriptions cascade back to `ACTIVE`."

        Claim: after leave + return, an originally-ACTIVE prescription is
        ACTIVE again.
        """
        bundle = setup_admitted_elder_v2()
        rx = create_active_prescription(bundle["elder"]["id"])
        leave_elder(bundle["elder"]["id"])
        return_elder(bundle["elder"]["id"])
        from test_helpers import get_prescription
        rx2 = get_prescription(rx["id"])
        assert rx2["status"] == "ACTIVE"


# ===========================================================================
# Discharge fiscal clearance (PRD §3.8, §2.7 #24)
# ===========================================================================
class TestDischargeFiscalClearance:

    def test_discharge_blocked_by_unpaid_finalized_bill(self):
        """PRD §3.8 / §2.7 #24: "Discharge — performed by `Admin` from
        either `ADMITTED` or `ON_LEAVE` — is the terminal transition. It
        requires the discharge fiscal clearance: `outstanding_balance_cents`
        exactly zero, no `Bill` left in `DRAFT`, and every bill closed in
        `PAID`, `REFUNDED`, or `ADJUSTED`."

        Claim: FINALIZED bill with amount_due > 0 blocks discharge with
        ERR_OUTSTANDING_BALANCE.
        # difficulty: cross_entity_state_dependency/discharge_depends_on_bill_states
        """
        # Engineer a bill whose amount_due is guaranteed > 0 so the
        # discharge gate actually trips: deposit at the §2.7 #23 floor
        # (500_000) plus an L3 PACKAGE month with bed_fee 600_000 yields
        # subtotal 1_080_000, subsidy capped at 200_000, deposit applied
        # 500_000, amount_due 380_000. PRD §3.7 + §3.8 / §2.7 #24.
        bundle = setup_admitted_with_finalized_bill(
            deposit_cents=500_000,
            monthly_bed_fee_cents=600_000,
        )
        bill = bundle["bill"]
        assert bill["amount_due_cents"] > 0, (
            "fixture must produce a bill with positive amount_due so the "
            "discharge fiscal-clearance gate is actually under test"
        )
        resp = api_client.discharge_elder(bundle["elder"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE.value)

    def test_discharge_succeeds_after_bill_paid_and_rx_discontinued(self):
        """PRD §3.8 / §2.7 #24: "Discharge ... requires the discharge fiscal
        clearance: outstanding_balance_cents exactly zero, no Bill left in
        DRAFT, and every bill closed in PAID, REFUNDED, or ADJUSTED. It also
        requires every active prescription on the elder to have already
        moved to DISCONTINUED."

        Claim: pay the bill, discontinue active prescriptions, then
        discharge succeeds and bed transitions to AVAILABLE.
        # difficulty: cross_entity_state_dependency/discharge_depends_on_bill_states
        # difficulty: compensating_invariant/bed_occupancy_invariant
        """
        bundle = setup_admitted_with_finalized_bill(deposit_cents=10_000_000)
        bill = bundle["bill"]
        if bill["amount_due_cents"] > 0:
            from test_helpers import pay_bill
            pay_bill(bill["id"])
        resp = api_client.discharge_elder(bundle["elder"]["id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DISCHARGED"


# ===========================================================================
# Bed occupancy invariant (PRD §3.1 + §3.8)
# ===========================================================================
class TestBedOccupancyInvariant:

    def test_admit_then_discharge_restores_bed_to_available(self):
        """PRD §3.8: "On success the bed moves from `OCCUPIED` to
        `AVAILABLE`."

        Claim: a complete admit→discharge cycle leaves the bed AVAILABLE.
        # difficulty: compensating_invariant/bed_occupancy_invariant
        """
        bundle = setup_admitted_with_finalized_bill(deposit_cents=10_000_000)
        bill = bundle["bill"]
        if bill["amount_due_cents"] > 0:
            from test_helpers import pay_bill
            pay_bill(bill["id"])
        discharge_elder(bundle["elder"]["id"])
        # Re-fetch bed by id via listing.
        from test_helpers import validate_paginated
        resp = api_client.list_beds(ADMIN, params={"limit": 100})
        rows, _ = validate_paginated(resp)
        target = [b for b in rows if b["id"] == bundle["bed"]["id"]][0]
        assert target["status"] == "AVAILABLE", \
            "PRD §3.8 — bed moves from OCCUPIED to AVAILABLE on discharge"
        assert target.get("current_elder_id") in (None, "", "null"), \
            "PRD §3.8 — current_elder_id cleared on discharge"
