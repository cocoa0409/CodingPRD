"""Appointment lifecycle branches, cascades, and route-slot conservation.

Queue A — non_linear_state_machine, transitive_cascade, compensating_invariant
(route slot). Queue B — state-machine corner claims (invalid transitions, terminal
lockdown, precondition enforcement, guarded transitions, valid transitions).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    make_clinician_headers,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_in_visit,
    setup_in_visit_with_estimate,
    setup_booked_appointment,
    setup_completed_exam,
    create_service_area,
    create_patient,
    create_tech,
    create_appointment,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# non_linear_state_machine / appointment_branch_refer_vs_complete
# ===========================================================================

def test_refer_branch_creates_referral_skips_stop_voids_estimate(api):
    """PRD §3.6: "A successful referral drives the appointment to the terminal
    `REFERRED` status and creates a **Referral** in `OPEN` status. Its cascades
    resolve the rest of the visit: if the appointment has a linked route stop that
    is not already in a terminal stop state, that stop flips to `SKIPPED`, and the
    route day's `stop_count` is recomputed and the route re-sequenced; any `DRAFT`
    or `APPROVED` estimate for the appointment is voided to `VOID`."

    From IN_VISIT, refer forks away from complete-visit: REFERRED + OPEN Referral +
    SKIPPED stop + VOID estimate + stop_count 0.

    Design: Difficulty/non_linear_state_machine/appointment_branch_refer_vs_complete
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
        approve=False, visit_type="EXAM", travel_surcharge_cents=1000,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    ref = validate_success(
        api.refer_appointment(ctx["appointment"]["id"],
                              {"hospital_name": "City Animal ER", "reason": "acute abdomen"},
                              clin),
        expected_status=201,
    )
    assert ref["status"] == "OPEN"
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], clin))
    assert appt["status"] == "REFERRED"
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], clin))
    assert stop["status"] == "SKIPPED"
    est = validate_success(api.get_estimate(ctx["estimate"]["id"], clin))
    assert est["status"] == "VOID"
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], clin))
    assert rd["stop_count"] == 0


def test_complete_visit_branch_invoices_estimate_and_services_stop(api):
    """PRD §3.5: "Closing the visit finalizes the estimate, moving it from
    `APPROVED` to `INVOICED` and computing its `invoice_total_cents` by the invoice
    variant of §3.4."
    PRD §3.5: "The linked route stop flips from `ARRIVED` to `SERVICED`, and the
    route day's `stop_count` is recomputed."

    From IN_VISIT, complete-visit forks the other way: AWAITING_PAYMENT + INVOICED
    estimate + SERVICED stop, with stop_count still counting the serviced stop.

    Design: Difficulty/non_linear_state_machine/appointment_branch_refer_vs_complete
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
        approve=True, visit_type="EXAM", travel_surcharge_cents=0,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    appt = validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    assert appt["status"] == "AWAITING_PAYMENT"
    est = validate_success(api.get_estimate(ctx["estimate"]["id"], clin))
    assert est["status"] == "INVOICED"
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], clin))
    assert stop["status"] == "SERVICED"
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], clin))
    assert rd["stop_count"] == 1


# ===========================================================================
# non_linear_state_machine / estimate_revise_self_cycle
# ===========================================================================

def test_estimate_revise_self_cycle_recomputes_total_and_bumps_version(api):
    """PRD §3.4: "While an estimate is still `DRAFT`, a clinician may revise it,
    replacing the `line_items` wholesale; each revision recomputes `subtotal_cents`
    and `estimate_total_cents` by the same per-line rule and increments the
    estimate's `version`."

    A DRAFT estimate (total 9000, version 1) revised to two lines (9000 + 4500x2)
    becomes total 18000, still DRAFT, version 2.

    Design: Difficulty/non_linear_state_machine/estimate_revise_self_cycle
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, species="CAT", weight_kg=5)
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    assert est["version"] == 1
    revised = validate_success(
        api.revise_estimate(
            est["id"],
            {"line_items": [
                {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
                {"code": "MED", "label": "Meds", "unit_cents": 4500, "qty": 2},
            ]},
            clin,
        )
    )
    assert revised["estimate_total_cents"] == 18000
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 2


# ===========================================================================
# transitive_cascade / reconcile_cascade_depth3_routeday_vehicle_clinician
# ===========================================================================

def test_reconcile_cascade_vehicle_and_clinician_released(api):
    """PRD §3.7: "A successful reconciliation recomputes `controlled_reconciled_ml`,
    returns the vehicle from `DEPLOYED` to `IN_DEPOT`, and returns the clinician
    from `ON_ROUTE` to `AVAILABLE`."

    Reconciling a LOCKED serviced route drives RECONCILED -> vehicle IN_DEPOT ->
    clinician AVAILABLE (depth-3 cascade).

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth3_routeday_vehicle_clinician
    """
    ctx = setup_completed_exam(service_date="2026-02-06T00:00:00Z")
    validate_success(api.reconcile_route_day(ctx["route_day"]["id"], COMPLIANCE))
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], COMPLIANCE))
    assert rd["posture"] == "RECONCILED"
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    assert van["status"] == "IN_DEPOT", "vehicle returns DEPLOYED -> IN_DEPOT"
    clinician = validate_success(api.get_clinician(ctx["clinician_id"], COMPLIANCE))
    assert clinician["status"] == "AVAILABLE", "clinician returns ON_ROUTE -> AVAILABLE"


# ===========================================================================
# transitive_cascade / cancel_cascade_depth2_stop_routeday_count
# compensating_invariant / route_slot_conservation_book_then_cancel
# ===========================================================================

def test_cancel_cascade_skips_stop_and_drops_stop_count(api):
    """PRD §3.6: "A `Dispatcher` cancels an appointment that is still `REQUESTED` or
    `SCHEDULED`, driving it to the terminal `CANCELLED` status. Cancellation mirrors
    the booking cleanup: if a linked route stop is in `PLANNED`, it flips to
    `SKIPPED`, and the route day's `stop_count` is recomputed and the route
    re-sequenced."

    Cancelling a SCHEDULED appointment: CANCELLED -> stop SKIPPED -> stop_count 0.

    Design: Difficulty/transitive_cascade/cancel_cascade_depth2_stop_routeday_count
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, species="CAT", weight_kg=6)
    validate_success(api.cancel_appointment(ctx["appointment"]["id"], DISPATCHER))
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], DISPATCHER))
    assert appt["status"] == "CANCELLED"
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], DISPATCHER))
    assert stop["status"] == "SKIPPED"
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], DISPATCHER))
    assert rd["stop_count"] == 0


def test_route_slot_conserved_after_book_then_cancel(api):
    """PRD §3.3: "The route day's `stop_count` is, at all times, the number of its
    route stops whose status is `PLANNED`, `ARRIVED`, or `SERVICED`; stops in
    `SKIPPED` are excluded from the count."
    PRD §3.6: "if a linked route stop is in `PLANNED`, it flips to `SKIPPED`, and
    the route day's `stop_count` is recomputed."

    Booking (+1) then cancelling (stop -> SKIPPED, excluded) restores stop_count to
    its pre-booking value of 0 — no slot drift.

    Design: Difficulty/compensating_invariant/route_slot_conservation_book_then_cancel
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, species="CAT", weight_kg=5)
    validate_success(api.cancel_appointment(ctx["appointment"]["id"], DISPATCHER))
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], DISPATCHER))
    assert rd["stop_count"] == 0
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], DISPATCHER))
    assert stop["status"] == "SKIPPED"


# ===========================================================================
# Corner / state_machines / arrive_from_requested_invalid_state
# ===========================================================================

def test_arrive_on_requested_appointment_rejected(api):
    """PRD §3.5: "a `Clinician` records arrival, which is legal only while the
    appointment is `SCHEDULED` and its linked route stop is `PLANNED`."
    PRD §2.6: "State-legality failures, where the target resource is not in a status
    from which the requested transition is allowed, surface as `ERR_INVALID_STATE`."

    Arriving on a never-booked REQUESTED appointment -> ERR_INVALID_STATE.

    Design: Corner/state_machines/arrive_from_requested_invalid_state
    """
    create_service_area()
    patient = create_patient(species="DOG", weight_kg=10)
    tech = create_tech("Tech Tx")
    appt = create_appointment(patient["id"], visit_type="EXAM",
                              requested_start="2026-03-04T09:00:00Z",
                              requested_end="2026-03-04T10:00:00Z")
    resp = api.arrive_appointment(appt["id"], make_clinician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / state_machines / cancel_terminal_completed_appointment_rejected
# ===========================================================================

def test_cancel_completed_appointment_rejected(api):
    """PRD §3.6: "A `Dispatcher` cancels an appointment that is still `REQUESTED` or
    `SCHEDULED`, driving it to the terminal `CANCELLED` status."
    PRD §2.6: "State-legality failures, where the target resource is not in a
    status from which the requested transition is allowed, surface as
    `ERR_INVALID_STATE`."

    Cancelling a fully COMPLETED (paid) appointment -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_terminal_completed_appointment_rejected
    """
    ctx = setup_completed_exam(service_date="2026-03-05T00:00:00Z")
    resp = api.cancel_appointment(ctx["appointment"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / state_machines / refer_euthanasia_blocked
# ===========================================================================

def test_refer_euthanasia_appointment_blocked(api):
    """PRD §3.6: "Referral is forbidden for a euthanasia visit — an `EUTHANASIA`
    appointment cannot be referred, and the attempt is rejected with
    `ERR_EUTHANASIA_NOT_REFERABLE`."

    Design: Corner/state_machines/refer_euthanasia_blocked
    """
    from test_helpers import setup_euthanasia_in_visit
    ctx = setup_euthanasia_in_visit(weight_kg=28, controlled_stock_ml=50,
                                    clock="2026-03-06T08:00:00Z",
                                    service_date="2026-03-06T00:00:00Z")
    clin = make_clinician_headers(ctx["clinician_id"])
    resp = api.refer_appointment(ctx["appointment"]["id"],
                                 {"hospital_name": "ER", "reason": "n/a"}, clin)
    validate_error(resp, ApiErrorId.ERR_EUTHANASIA_NOT_REFERABLE.value)


# ===========================================================================
# Corner / state_machines / complete_visit_no_approved_estimate
# ===========================================================================

def test_complete_visit_without_approved_estimate_rejected(api):
    """PRD §3.5: "Closing requires that an `APPROVED` estimate exist for the
    appointment, or it fails with `ERR_NO_APPROVED_ESTIMATE`."

    complete-visit on an IN_VISIT appointment with only a DRAFT estimate ->
    ERR_NO_APPROVED_ESTIMATE.

    Design: Corner/state_machines/complete_visit_no_approved_estimate
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
        approve=False, visit_type="EXAM",
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    resp = api.complete_visit(ctx["appointment"]["id"], clin)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_ESTIMATE.value)


# ===========================================================================
# Corner / state_machines / complete_euthanasia_visit_log_incomplete
# ===========================================================================

def test_complete_euthanasia_visit_without_waste_log_rejected(api):
    """PRD §3.5: "For a euthanasia visit, the controlled-med ledger must be complete
    — both a `DISPENSE` entry and a `WASTE` entry must exist for the appointment —
    or closing fails with `ERR_EUTHANASIA_LOG_INCOMPLETE`."

    DISPENSE logged but no WASTE, APPROVED estimate present -> incomplete ledger.

    Design: Corner/state_machines/complete_euthanasia_visit_log_incomplete
    """
    from test_helpers import setup_euthanasia_in_visit, dispense
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-03-08T08:00:00Z",
                                    service_date="2026-03-08T00:00:00Z")
    clin = make_clinician_headers(ctx["clinician_id"])
    dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [{"code": "EUTH_FEE", "label": "Euth", "unit_cents": 30000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    validate_success(api.approve_estimate(est["id"], clin))
    resp = api.complete_visit(ctx["appointment"]["id"], clin)
    validate_error(resp, ApiErrorId.ERR_EUTHANASIA_LOG_INCOMPLETE.value)


# ===========================================================================
# Corner / state_machines / reconcile_with_open_stops_rejected
# ===========================================================================

def test_reconcile_with_open_stop_rejected(api):
    """PRD §3.7: "A locked route can only be reconciled once every one of its stops
    has reached a terminal stop state — every route stop in `SERVICED` or `SKIPPED`
    — otherwise reconciliation is refused with `ERR_STOPS_OPEN`."

    A LOCKED route with one stop still PLANNED -> ERR_STOPS_OPEN.

    Design: Corner/state_machines/reconcile_with_open_stops_rejected
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, weight_kg=10)
    validate_success(api.lock_route_day(ctx["route_day"]["id"], DISPATCHER))
    resp = api.reconcile_route_day(ctx["route_day"]["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_STOPS_OPEN.value)


# ===========================================================================
# Corner / state_machines / referral_acknowledge_happy_path
# ===========================================================================

def test_referral_acknowledge_moves_open_to_acknowledged(api):
    """PRD §3.6: "A `ComplianceOfficer` later acknowledges a referral, moving it
    from `OPEN` to `ACKNOWLEDGED`."

    Design: Corner/state_machines/referral_acknowledge_happy_path
    """
    ctx = setup_in_visit(visit_type="EXAM", travel_surcharge_cents=0, weight_kg=19)
    clin = make_clinician_headers(ctx["clinician_id"])
    ref = validate_success(
        api.refer_appointment(ctx["appointment"]["id"],
                              {"hospital_name": "Metro Vet ER", "reason": "fracture"}, clin),
        expected_status=201,
    )
    acked = validate_success(api.acknowledge_referral(ref["id"], COMPLIANCE))
    assert acked["status"] == "ACKNOWLEDGED"


# ===========================================================================
# Corner / state_machines / lock_route_with_maintenance_vehicle_rejected
# ===========================================================================

def test_lock_route_with_maintenance_vehicle_rejected(api):
    """PRD §3.3: "The assigned vehicle must not be in `MAINTENANCE`, or the lock is
    refused with `ERR_VEHICLE_UNAVAILABLE`."

    A route with a stop, but its vehicle PATCHed to MAINTENANCE -> lock rejected.

    Design: Corner/state_machines/lock_route_with_maintenance_vehicle_rejected
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, weight_kg=11)
    van = ctx["van"]
    validate_success(api.patch_rolling_clinic(
        van["id"],
        {"status": "MAINTENANCE", "expected_rolling_clinic_version": van["version"]},
        DISPATCHER,
    ))
    resp = api.lock_route_day(ctx["route_day"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_UNAVAILABLE.value)


# ===========================================================================
# Corner / state_machines / specimen_deliver_before_transit_invalid
# Corner / endpoints / specimen_transit_then_deliver_happy_path
# ===========================================================================

def test_specimen_deliver_before_transit_rejected(api):
    """PRD §3.8: "The clinician then moves it to `IN_TRANSIT` and finally to the
    terminal `DELIVERED` status, each step requiring the specimen to be in the
    immediately preceding state."
    PRD §2.6: "State-legality failures, where the target resource is not in a
    status from which the requested transition is allowed, surface as
    `ERR_INVALID_STATE`."

    deliver while still COLLECTED (skipping IN_TRANSIT) -> ERR_INVALID_STATE.

    Design: Corner/state_machines/specimen_deliver_before_transit_invalid
    """
    create_service_area()
    tech = create_tech("Tech Td")
    patient = create_patient(species="CAT", weight_kg=4)
    appt = create_appointment(patient["id"], visit_type="EXAM",
                              requested_start="2026-03-10T09:00:00Z",
                              requested_end="2026-03-10T10:00:00Z")
    clin = make_clinician_headers(tech["id"])
    spec = validate_success(
        api.create_specimen_pickup({"appointment_id": appt["id"], "specimen_type": "BLOOD"}, clin),
        expected_status=201,
    )
    resp = api.deliver_specimen(spec["id"], clin)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_specimen_transit_then_deliver_happy_path(api):
    """PRD §3.8: "it begins in `COLLECTED` status. The clinician then moves it to
    `IN_TRANSIT` and finally to the terminal `DELIVERED` status, each step requiring
    the specimen to be in the immediately preceding state."

    COLLECTED -> transit -> IN_TRANSIT -> deliver -> DELIVERED.

    Design: Corner/endpoints/specimen_transit_then_deliver_happy_path
    """
    create_service_area()
    tech = create_tech("Tech Tl")
    patient = create_patient(species="CAT", weight_kg=4)
    appt = create_appointment(patient["id"], visit_type="EXAM",
                              requested_start="2026-03-21T09:00:00Z",
                              requested_end="2026-03-21T10:00:00Z")
    clin = make_clinician_headers(tech["id"])
    spec = validate_success(
        api.create_specimen_pickup({"appointment_id": appt["id"], "specimen_type": "URINE"}, clin),
        expected_status=201,
    )
    validate_success(api.transit_specimen(spec["id"], clin))
    delivered = validate_success(api.deliver_specimen(spec["id"], clin))
    assert delivered["status"] == "DELIVERED"
