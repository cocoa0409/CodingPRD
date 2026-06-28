"""Controlled-med DEA safety gates, dosing boundaries, witness segregation, stock
guards, append-only ledger, and audit trail.

Queue A — boundary_precision_check (dose floor, empty-route lock),
priority_pair_validation_conflict (DEA-beats-stock). Queue B — witness conflict,
insufficient vaccine stock, payment mismatch, append-only ledger, audit listing.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    make_clinician_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_append_only_no_version,
    setup_euthanasia_in_visit,
    setup_in_visit_with_estimate,
    setup_booked_appointment,
    dispense,
    create_tech,
    create_van,
    create_route_day,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# boundary_precision_check / euthanasia_dose_floor_boundary
# ===========================================================================

def test_dispense_below_dose_floor_rejected(api):
    """PRD §3.5: "A `DISPENSE` entry whose `amount_ml` is less than this required
    floor is rejected with `ERR_DOSE_BELOW_MINIMUM`."
    PRD §3.5: "The required volume is the patient's `weight_kg` multiplied by a
    per-kilogram dose of 0.2 milliliters, with a hard floor of 1.0 milliliter."

    For a 30kg dog required_ml == 6.0; a DISPENSE of 5.9 (< 6.0) is rejected.

    Design: Difficulty/boundary_precision_check/euthanasia_dose_floor_boundary
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-02-11T08:00:00Z",
                                    service_date="2026-02-11T00:00:00Z")
    clin = make_clinician_headers(ctx["clinician_id"])
    resp = api.create_euthanasia_log(
        ctx["appointment"]["id"],
        {"rolling_clinic_id": ctx["van"]["id"], "administering_vet_id": ctx["clinician_id"],
         "entry_type": "DISPENSE", "amount_ml": 5.9},
        clin,
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_BELOW_MINIMUM.value)


def test_dispense_exactly_at_dose_floor_accepted(api):
    """PRD §3.5: "a vet may always draw more than the floor, and the overage is
    later recorded as `WASTE`."
    PRD §3.5: "The required volume is the patient's `weight_kg` multiplied by a
    per-kilogram dose of 0.2 milliliters, with a hard floor of 1.0 milliliter."

    For a 30kg dog required_ml == 6.0; a DISPENSE of exactly 6.0 is accepted
    (boundary X is legal).

    Design: Difficulty/boundary_precision_check/euthanasia_dose_floor_boundary
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-02-11T08:00:00Z",
                                    service_date="2026-02-11T00:00:00Z")
    log = dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    assert log["amount_ml"] == 6.0
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], DISPATCHER))
    assert van["controlled_stock_ml"] == 44.0, "50.0 - 6.0 == 44.0"


# ===========================================================================
# boundary_precision_check / lock_empty_route_zero_count_boundary
# ===========================================================================

def test_lock_empty_route_rejected(api):
    """PRD §3.3: "Locking requires that the route already hold at least one counted
    stop — a `stop_count` of 1 or more — or it is refused with `ERR_ROUTE_EMPTY`."

    Locking a fresh OPEN route with stop_count == 0 -> ERR_ROUTE_EMPTY.

    Design: Difficulty/boundary_precision_check/lock_empty_route_zero_count_boundary
    """
    tech = create_tech("Tech Tilly")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-12")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-02-12T00:00:00Z")
    resp = api.lock_route_day(rd["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY.value)


# ===========================================================================
# priority_pair_validation_conflict / dea_safety_beats_stock_constraint_on_dispense
# ===========================================================================

def test_dea_invalid_beats_insufficient_stock_on_dispense(api):
    """PRD §3.5: "the administering party — and, for waste, the witness — must be a
    `VET` whose `dea_number` is present and whose `dea_expires_on` has not passed
    against the current clock; a non-vet, or a vet with an absent or expired
    registration, is rejected with `ERR_DEA_INVALID`."
    PRD §2.6: "the server consider domain rules — state legality, route posture,
    area coverage, safety, scheduling, stock, fiscal, concurrency."

    A DISPENSE by an expired-DEA vet AND amount_ml exceeding stock returns
    ERR_DEA_INVALID (safety) ahead of ERR_INSUFFICIENT_STOCK (the later stock gate).

    Design: Difficulty/priority_pair_validation_conflict/dea_safety_beats_stock_constraint_on_dispense
    """
    # clock 2026-02-10, vet DEA expired 2026-01-01, vehicle stock only 1.0
    ctx = setup_euthanasia_in_visit_expired_dea()
    clin = make_clinician_headers(ctx["clinician_id"])
    resp = api.create_euthanasia_log(
        ctx["appointment"]["id"],
        {"rolling_clinic_id": ctx["van"]["id"], "administering_vet_id": ctx["clinician_id"],
         "entry_type": "DISPENSE", "amount_ml": 6.0},
        clin,
    )
    validate_error(resp, ApiErrorId.ERR_DEA_INVALID.value)


def setup_euthanasia_in_visit_expired_dea():
    """Local helper: euthanasia IN_VISIT with an expired-DEA VET and a thin stock.

    Mirrors setup_euthanasia_in_visit but registers the lead VET with a DEA that
    expired before the clock, and a vehicle holding only 1.0 mL of stock.
    """
    from test_helpers import (
        set_clock, create_service_area, create_vet, create_van as _van,
        create_patient, create_appointment, create_route_day as _rd, book_stop,
    )
    from test_helpers import api_client as _api
    set_clock("2026-02-10T08:00:00Z")
    create_service_area(euthanasia_allowed=True)
    vet = create_vet(full_name="Dr Expired", dea_number="EX0001112",
                     dea_expires_on="2026-01-01T00:00:00Z")
    van = _van(controlled_stock_ml=1.0, vaccine_stock_count=0, plate="VAN-10")
    pat = create_patient(species="DOG", weight_kg=30)
    appt = create_appointment(pat["id"], visit_type="EUTHANASIA",
                              requested_start="2026-02-10T09:00:00Z",
                              requested_end="2026-02-10T10:00:00Z")
    rd = _rd(vet["id"], van["id"], service_date="2026-02-10T00:00:00Z")
    book_stop(rd["id"], appt["id"], rd["version"],
              window_start="2026-02-10T09:00:00Z", window_end="2026-02-10T10:00:00Z")
    clin = make_clinician_headers(vet["id"])
    get_success_data(_api.lock_route_day(rd["id"], DISPATCHER))
    get_success_data(_api.arrive_appointment(appt["id"], clin))
    return {"clinician_id": vet["id"], "van": van, "appointment": appt, "route_day": rd}


# ===========================================================================
# Corner / validations / waste_witness_conflict_rejected
# ===========================================================================

def test_waste_witness_conflict_rejected(api):
    """PRD §3.5: "On a `WASTE` entry the `witness_vet_id` must differ from the
    `administering_vet_id`, enforcing segregation of duties, or the entry is
    rejected with `ERR_WITNESS_CONFLICT`."

    WASTE where witness_vet_id == administering_vet_id -> ERR_WITNESS_CONFLICT.

    Design: Corner/validations/waste_witness_conflict_rejected
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-03-17T08:00:00Z",
                                    service_date="2026-03-17T00:00:00Z")
    clin = make_clinician_headers(ctx["clinician_id"])
    dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    resp = api.create_euthanasia_log(
        ctx["appointment"]["id"],
        {"rolling_clinic_id": ctx["van"]["id"], "administering_vet_id": ctx["clinician_id"],
         "entry_type": "WASTE", "amount_ml": 2.0, "witness_vet_id": ctx["clinician_id"]},
        clin,
    )
    validate_error(resp, ApiErrorId.ERR_WITNESS_CONFLICT.value)


# ===========================================================================
# Corner / validations / complete_visit_insufficient_vaccine_stock
# ===========================================================================

def test_complete_visit_insufficient_vaccine_stock(api):
    """PRD §3.5: "For a vaccine visit carrying a positive `vaccine_doses`, the van
    must hold at least that many doses in `vaccine_stock_count`, failing which the
    stock guard `ERR_INSUFFICIENT_STOCK` applies."

    complete-visit on a VACCINE appt (vaccine_doses=3) where the vehicle holds only
    1 dose -> ERR_INSUFFICIENT_STOCK.

    Design: Corner/validations/complete_visit_insufficient_vaccine_stock
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "VACCINE_DOSE", "label": "Vax", "unit_cents": 6500, "qty": 3}],
        approve=True, visit_type="VACCINE", vaccine_doses=3, vaccine_stock_count=1,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    resp = api.complete_visit(ctx["appointment"]["id"], clin)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ===========================================================================
# Corner / validations / payment_amount_mismatch_rejected
# ===========================================================================

def test_payment_amount_mismatch_rejected(api):
    """PRD §3.5: "the tendered `amount_cents` must equal the estimate's
    `invoice_total_cents` exactly — no overpayment or underpayment — or the payment
    is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Estimate invoice_total 9000, payment 9001 -> ERR_PAYMENT_AMOUNT_MISMATCH.

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
        approve=True, visit_type="EXAM", travel_surcharge_cents=0,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    resp = api.create_payment(
        {"estimate_id": ctx["estimate"]["id"], "amount_cents": 9001, "method": "CARD"},
        clin,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


# ===========================================================================
# Corner / cross_cutting / derived_vaccine_stock_reconciles_after_completion
# ===========================================================================

def test_vaccine_stock_decrements_after_completion(api):
    """PRD §3.5: "When the visit was a vaccination, the van's `vaccine_stock_count`
    is decremented by the administered `vaccine_doses`, cascading the vehicle
    inventory."

    vaccine_stock_count drops 10 -> 8 after a VACCINE visit with vaccine_doses=2.

    Design: Corner/cross_cutting_complexity_layers/derived_vaccine_stock_reconciles_after_completion
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "VACCINE_DOSE", "label": "Vax", "unit_cents": 6500, "qty": 2}],
        approve=True, visit_type="VACCINE", vaccine_doses=2, vaccine_stock_count=10,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], DISPATCHER))
    assert van["vaccine_stock_count"] == 8, \
        f"vaccine_stock_count 10 - 2 == 8, got {van['vaccine_stock_count']}"


# ===========================================================================
# Corner / entities / controlled_med_log_is_append_only_no_version
# ===========================================================================

def test_controlled_med_log_is_append_only(api):
    """PRD §2.4: "A `ControlledMedLog` entry is an append-only record: it carries
    only an `id` and a `created_at` and has neither an `updated_at` nor a
    `version`, because it is never modified after it is written."

    A DISPENSE entry exposes id/created_at/amount_ml/entry_type but no version.

    Design: Corner/entities/controlled_med_log_is_append_only_no_version
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-03-02T08:00:00Z",
                                    service_date="2026-03-02T00:00:00Z")
    log = dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    assert log["amount_ml"] == 6.0
    assert log["entry_type"] == "DISPENSE"
    assert_append_only_no_version(log)


# ===========================================================================
# Corner / endpoints / controlled_logs_audit_trail_listable_by_vehicle
# ===========================================================================

def test_vehicle_controlled_logs_audit_trail_listable(api):
    """PRD §3.9: "A `ComplianceOfficer` or a `Dispatcher` may pull the full
    `ControlledMedLog` history for a particular vehicle, or the subset of entries
    in which a particular clinician acted as the administering or witnessing vet,
    supporting per-vehicle and per-vet DEA audits."

    After one DISPENSE on a vehicle, GET /rolling-clinics/{id}/controlled-logs
    returns an array with total_count 1.

    Design: Corner/endpoints/controlled_logs_audit_trail_listable_by_vehicle
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-03-22T08:00:00Z",
                                    service_date="2026-03-22T00:00:00Z")
    dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    resp = api.list_vehicle_controlled_logs(ctx["van"]["id"], COMPLIANCE)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected 1 audit entry, got {meta['total_count']}"
