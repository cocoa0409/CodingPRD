"""Second assertions for each difficulty-targeted behavior.

Each test here pins a distinct observable (a different field, side effect,
boundary side, or terminal state) than its sibling test in test_01..test_05, so
every difficulty-targeted behavior is exercised by at least two tests.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    make_clinician_headers,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_in_visit_with_estimate,
    setup_booked_appointment,
    setup_euthanasia_reconciled,
    setup_euthanasia_in_visit,
    setup_completed_exam,
    setup_in_visit,
    create_service_area,
    create_tech,
    create_vet,
    create_van,
    create_patient,
    create_appointment,
    create_route_day,
    book_stop,
    dispense,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# dual_variant_calc / estimate_vs_invoice_total_on_estimate
# ===========================================================================

def test_estimate_status_invoiced_after_close(api):
    """PRD §3.5: "Closing the visit finalizes the estimate, moving it from
    `APPROVED` to `INVOICED`."

    After complete-visit the estimate's status is INVOICED (the divergence between
    estimate_total and invoice_total is realized on the same INVOICED estimate).

    Design: Difficulty/dual_variant_calc/estimate_vs_invoice_total_on_estimate
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[
            {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
            {"code": "VACCINE_DOSE", "label": "Vaccine", "unit_cents": 6500, "qty": 2},
        ],
        approve=True, visit_type="VACCINE", vaccine_doses=1,
        travel_surcharge_cents=2000, vaccine_stock_count=10,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    est = validate_success(api.get_estimate(ctx["estimate"]["id"], clin))
    assert est["status"] == "INVOICED"
    assert est["invoice_total_cents"] == 17500
    assert est["estimate_total_cents"] == 24000


# ===========================================================================
# dual_variant_calc / controlled_running_balance_vs_recount_on_rolling_clinic
# ===========================================================================

def test_reconcile_terminal_posture_after_recount(api):
    """PRD §3.7: "A `ComplianceOfficer` performs the reconciliation, moving the
    route day's `posture` from `LOCKED` to `RECONCILED`."

    The route day reaches the terminal RECONCILED posture once the recount agrees
    (running balance and recount both 42.0 from a 6.0 DISPENSE + 2.0 WASTE on 50.0).

    Design: Difficulty/dual_variant_calc/controlled_running_balance_vs_recount_on_rolling_clinic
    """
    ctx = setup_euthanasia_reconciled(dispense_ml=6.0, waste_ml=2.0, controlled_stock_ml=50)
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], COMPLIANCE))
    assert rd["posture"] == "RECONCILED"
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    assert van["controlled_reconciled_ml"] == 42.0


# ===========================================================================
# combinatorial_formula / estimate_round_per_line_then_sum_order
# ===========================================================================

def test_estimate_total_equals_subtotal_with_zero_surcharge(api):
    """PRD §3.4: "`estimate_total_cents` is the subtotal plus that travel surcharge."

    With travel_surcharge_cents 0 and the per-line-rounded subtotal 334, the
    estimate_total_cents equals the subtotal exactly (334), confirming surcharge 0
    is added, not the un-rounded 333.

    Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
    """
    ctx = setup_booked_appointment(
        visit_type="VACCINE", travel_surcharge_cents=0, vaccine_doses=1,
        species="CAT", weight_kg=4, vaccine_stock_count=5,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [
                 {"code": "SUPPLY", "label": "Half A", "unit_cents": 333, "qty": 0.5},
                 {"code": "SUPPLY", "label": "Half B", "unit_cents": 333, "qty": 0.5},
             ]},
            clin,
        ),
        expected_status=201,
    )
    assert est["estimate_total_cents"] == 334
    assert est["estimate_total_cents"] == est["subtotal_cents"] + est["travel_surcharge_cents"]


# ===========================================================================
# combinatorial_formula / invoice_min_cap_nonlinear_branch
# ===========================================================================

def test_invoice_branch_decrements_vaccine_stock(api):
    """PRD §3.5: "When the visit was a vaccination, the van's `vaccine_stock_count`
    is decremented by the administered `vaccine_doses`."

    The same min-cap completion that yields invoice 17500 also decrements vaccine
    stock 10 -> 9 (one dose administered).

    Design: Difficulty/combinatorial_formula/invoice_min_cap_nonlinear_branch
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[
            {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
            {"code": "VACCINE_DOSE", "label": "Vaccine", "unit_cents": 6500, "qty": 2},
        ],
        approve=True, visit_type="VACCINE", vaccine_doses=1,
        travel_surcharge_cents=2000, vaccine_stock_count=10,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], DISPATCHER))
    assert van["vaccine_stock_count"] == 9


# ===========================================================================
# non_linear_state_machine / appointment_branch_refer_vs_complete
# ===========================================================================

def test_refer_branch_drops_stop_count_to_zero(api):
    """PRD §3.6: "if the appointment has a linked route stop that is not already in
    a terminal stop state, that stop flips to `SKIPPED`, and the route day's
    `stop_count` is recomputed."

    The refer branch (distinct from complete-visit) recomputes stop_count to 0 after
    the only stop is SKIPPED.

    Design: Difficulty/non_linear_state_machine/appointment_branch_refer_vs_complete
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
        approve=False, visit_type="EXAM", travel_surcharge_cents=1000,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(
        api.refer_appointment(ctx["appointment"]["id"],
                              {"hospital_name": "City Animal ER", "reason": "acute abdomen"}, clin),
        expected_status=201,
    )
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], clin))
    assert rd["stop_count"] == 0


# ===========================================================================
# non_linear_state_machine / estimate_revise_self_cycle
# ===========================================================================

def test_estimate_revise_keeps_draft_status(api):
    """PRD §3.4: "While an estimate is still `DRAFT`, a clinician may revise it,
    replacing the `line_items` wholesale."

    The revise self-cycle returns the estimate to DRAFT (not a new state) while
    recomputing the total — the cyclic shape on the Estimate entity.

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
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 2


# ===========================================================================
# transitive_cascade / reconcile_cascade_depth3_routeday_vehicle_clinician
# ===========================================================================

def test_reconcile_returns_vehicle_to_depot(api):
    """PRD §3.7: "A successful reconciliation recomputes `controlled_reconciled_ml`,
    returns the vehicle from `DEPLOYED` to `IN_DEPOT`, and returns the clinician
    from `ON_ROUTE` to `AVAILABLE`."

    The first cascade hop: RECONCILED drives the vehicle DEPLOYED -> IN_DEPOT.

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth3_routeday_vehicle_clinician
    """
    ctx = setup_completed_exam(service_date="2026-02-06T00:00:00Z")
    validate_success(api.reconcile_route_day(ctx["route_day"]["id"], COMPLIANCE))
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    assert van["status"] == "IN_DEPOT"


# ===========================================================================
# transitive_cascade / cancel_cascade_depth2_stop_routeday_count
# ===========================================================================

def test_cancel_cascade_drives_appointment_cancelled(api):
    """PRD §3.6: "A `Dispatcher` cancels an appointment that is still `REQUESTED` or
    `SCHEDULED`, driving it to the terminal `CANCELLED` status."

    The cancel origin transition: a SCHEDULED appointment reaches CANCELLED, which
    in turn triggers the stop-skip / stop_count cascade.

    Design: Difficulty/transitive_cascade/cancel_cascade_depth2_stop_routeday_count
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, species="CAT", weight_kg=6)
    appt = validate_success(api.cancel_appointment(ctx["appointment"]["id"], DISPATCHER))
    assert appt["status"] == "CANCELLED"
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], DISPATCHER))
    assert stop["status"] == "SKIPPED"


# ===========================================================================
# priority_pair_validation_conflict / state_beats_safety_on_euthanasia_booking
# ===========================================================================

def test_euthanasia_booking_in_allowed_area_succeeds_then_state_blocks_rebook(api):
    """PRD §3.3: "This single operation drives the appointment from `REQUESTED` to
    `SCHEDULED` and is gated by a layered set of preconditions."
    PRD §2.6: "Only after these three gates does the server consider domain rules —
    state legality, route posture, area coverage, safety, scheduling, stock,
    fiscal, concurrency, and finally body well-formedness."

    The first euthanasia booking into an allowed area succeeds (SCHEDULED);
    re-booking the now-SCHEDULED appointment fails on state, confirming the state
    gate is what is being hit (not a missing-area gate).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_euthanasia_booking
    """
    create_service_area(zip_code="11201", name="Allowed", travel_surcharge_cents=0,
                        euthanasia_allowed=True)
    vet = create_vet(full_name="Dr Vet C", dea_number="CV1112223")
    van = create_van(controlled_stock_ml=50, vaccine_stock_count=0, plate="VAN-9")
    pat = create_patient(owner_name="Owner G", species="DOG", weight_kg=25, home_zip="11201")
    appt = create_appointment(pat["id"], visit_type="EUTHANASIA",
                              requested_start="2026-02-08T09:00:00Z",
                              requested_end="2026-02-08T10:00:00Z")
    rd1 = create_route_day(vet["id"], van["id"], service_date="2026-02-08T00:00:00Z")
    first = validate_success(
        api.create_stop(
            rd1["id"],
            {"appointment_id": appt["id"],
             "window_start": "2026-02-08T09:00:00Z", "window_end": "2026-02-08T10:00:00Z",
             "expected_route_day_version": rd1["version"]},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert first["status"] == "PLANNED"
    booked = validate_success(api.get_appointment(appt["id"], DISPATCHER))
    assert booked["status"] == "SCHEDULED"
    rd2 = create_route_day(vet["id"], van["id"], service_date="2026-02-09T00:00:00Z")
    resp = api.create_stop(
        rd2["id"],
        {"appointment_id": appt["id"],
         "window_start": "2026-02-09T09:00:00Z", "window_end": "2026-02-09T10:00:00Z",
         "expected_route_day_version": rd2["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# priority_pair_validation_conflict / dea_safety_beats_stock_constraint_on_dispense
# ===========================================================================

def test_valid_dea_dispense_succeeds_isolating_the_dea_gate(api):
    """PRD §3.5: "The administering party — and, for waste, the witness — must be a
    `VET` whose `dea_number` is present and whose `dea_expires_on` has not passed
    against the current clock; a non-vet, or a vet with an absent or expired
    registration, is rejected with `ERR_DEA_INVALID`."

    With a valid (non-expired) DEA and ample stock, the DISPENSE succeeds — isolating
    that the expired-DEA rejection in the paired test is the DEA gate, not stock.

    Design: Difficulty/priority_pair_validation_conflict/dea_safety_beats_stock_constraint_on_dispense
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-02-10T08:00:00Z",
                                    service_date="2026-02-10T00:00:00Z")
    log = dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 6.0)
    assert log["entry_type"] == "DISPENSE"
    assert log["amount_ml"] == 6.0


# ===========================================================================
# boundary_precision_check / euthanasia_dose_floor_boundary
# (second test lives in test_04 as test_dispense_exactly_at_dose_floor_accepted;
#  here we add the >5kg vs floor distinction at exactly the 30kg required dose.)
# ===========================================================================

def test_dispense_above_dose_floor_accepted(api):
    """PRD §3.5: "a vet may always draw more than the floor, and the overage is later
    recorded as `WASTE`."

    For a 30kg dog (required 6.0), a DISPENSE of 7.0 (> required) is accepted — the
    X+1 side of the boundary.

    Design: Difficulty/boundary_precision_check/euthanasia_dose_floor_boundary
    """
    ctx = setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                                    clock="2026-02-11T08:00:00Z",
                                    service_date="2026-02-11T00:00:00Z")
    log = dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 7.0)
    assert log["amount_ml"] == 7.0


# ===========================================================================
# boundary_precision_check / lock_empty_route_zero_count_boundary
# ===========================================================================

def test_lock_route_with_one_stop_succeeds(api):
    """PRD §3.3: "Locking requires that the route already hold at least one counted
    stop — a `stop_count` of 1 or more — or it is refused with `ERR_ROUTE_EMPTY`."
    PRD §3.3: "Locking freezes the stop set so that no further stops may be created
    while the route is `LOCKED`, moves the vehicle from `IN_DEPOT` to `DEPLOYED`,
    and moves the clinician to `ON_ROUTE`."

    The X+1 side of the stop_count >= 1 boundary: a route with exactly one stop
    locks successfully (posture LOCKED).

    Design: Difficulty/boundary_precision_check/lock_empty_route_zero_count_boundary
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, weight_kg=12)
    locked = validate_success(api.lock_route_day(ctx["route_day"]["id"], DISPATCHER))
    assert locked["posture"] == "LOCKED"


# ===========================================================================
# cross_entity_state_dependency / stop_booking_requires_active_service_area
# ===========================================================================

def test_booking_succeeds_when_service_area_active(api):
    """PRD §3.3: "The appointment's resolved service area — found from the patient's
    `home_zip` — must be `ACTIVE`, or the booking is refused with
    `ERR_AREA_NOT_COVERED`."
    PRD §3.3: "A successful booking creates the route stop in `PLANNED` status,
    advances the appointment to `SCHEDULED`, recomputes the route day's
    `stop_count`, recomputes the `sequence` of every stop on the route, and
    increments the route day's `version` by 1."

    With the resolved area ACTIVE (not suspended), the booking succeeds — isolating
    that the suspended-area rejection in the paired test is the coverage gate.

    Design: Difficulty/cross_entity_state_dependency/stop_booking_requires_active_service_area
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, weight_kg=22)
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], DISPATCHER))
    assert appt["status"] == "SCHEDULED"
    assert ctx["stop"]["status"] == "PLANNED"


# ===========================================================================
# cross_entity_state_dependency / estimate_approve_requires_appointment_visit_phase
# ===========================================================================

def test_estimate_approve_succeeds_when_appointment_scheduled(api):
    """PRD §3.4: "approval is only allowed while the linked appointment is in
    `SCHEDULED` or `IN_VISIT`."
    PRD §3.4: "A clinician approves a `DRAFT` estimate to move it to `APPROVED`."

    When the appointment is SCHEDULED, approving its DRAFT estimate succeeds
    (APPROVED) — isolating that the REQUESTED rejection in the paired test is the
    visit-phase gate.

    Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_appointment_visit_phase
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, weight_kg=4, species="CAT")
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    approved = validate_success(api.approve_estimate(est["id"], clin))
    assert approved["status"] == "APPROVED"


# ===========================================================================
# resource_temporal_overlap / clinician_route_buffered_touching_conflict
# ===========================================================================

def test_clinician_buffered_gap_beyond_buffer_books_successfully(api):
    """PRD §3.3: "two windows conflict not only when they overlap but also when the
    gap between them is smaller than the travel buffer of 30 minutes."

    A second stop starting 30+ minutes after the first ends (09:00-10:00 then
    10:30-11:30, gap == 30) does NOT conflict on the same route — confirming the
    rejection in the paired touching test is the buffer rule, not a blanket
    same-route ban.

    Design: Difficulty/resource_temporal_overlap/clinician_route_buffered_touching_conflict
    """
    create_service_area(travel_surcharge_cents=0)
    tech = create_tech("Tech Two")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-14b")
    pat1 = create_patient(owner_name="Owner L1", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner L2", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-02-15T09:00:00Z",
                               requested_end="2026-02-15T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-02-15T10:30:00Z",
                               requested_end="2026-02-15T11:30:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-02-15T00:00:00Z")
    book_stop(rd["id"], appt1["id"], rd["version"],
              window_start="2026-02-15T09:00:00Z", window_end="2026-02-15T10:00:00Z")
    rd_now = validate_success(api.get_route_day(rd["id"], DISPATCHER))
    second = validate_success(
        api.create_stop(
            rd["id"],
            {"appointment_id": appt2["id"],
             "window_start": "2026-02-15T10:30:00Z", "window_end": "2026-02-15T11:30:00Z",
             "expected_route_day_version": rd_now["version"]},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert second["status"] == "PLANNED"


# ===========================================================================
# resource_temporal_overlap / vehicle_zerobuffer_overlap_across_routes
# ===========================================================================

def test_vehicle_touching_across_routes_allowed(api):
    """PRD §3.3: "Here touching exactly at an endpoint — proposed start equal to the
    other's end — does not conflict, because the van can be handed off instantly."

    Same van on two RouteDays same date; route-1 has 09:00-10:00, route-2 books a
    touching 10:00-11:00 (zero-buffer, distinct from the clinician check) and is
    allowed.

    Design: Difficulty/resource_temporal_overlap/vehicle_zerobuffer_overlap_across_routes
    """
    create_service_area(travel_surcharge_cents=0)
    techA = create_tech("Tech A")
    techB = create_tech("Tech B")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-15b")
    pat1 = create_patient(owner_name="Owner M1", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner M2", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-02-16T09:00:00Z",
                               requested_end="2026-02-16T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-02-16T10:00:00Z",
                               requested_end="2026-02-16T11:00:00Z")
    rd1 = create_route_day(techA["id"], van["id"], service_date="2026-02-16T00:00:00Z")
    book_stop(rd1["id"], appt1["id"], rd1["version"],
              window_start="2026-02-16T09:00:00Z", window_end="2026-02-16T10:00:00Z")
    rd2 = create_route_day(techB["id"], van["id"], service_date="2026-02-16T00:00:00Z")
    second = validate_success(
        api.create_stop(
            rd2["id"],
            {"appointment_id": appt2["id"],
             "window_start": "2026-02-16T10:00:00Z", "window_end": "2026-02-16T11:00:00Z",
             "expected_route_day_version": rd2["version"]},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert second["status"] == "PLANNED"


# ===========================================================================
# compensating_invariant / controlled_drug_conservation_dispense_waste
# ===========================================================================

def test_drug_conservation_recount_equals_running_balance(api):
    """PRD §3.7: "Reconciliation passes only if this independent recount equals the
    running `controlled_stock_ml` balance the day's side effects produced."

    The two independently-derived figures are equal (controlled_reconciled_ml ==
    controlled_stock_ml == 42.0), the observable form of the conservation invariant.

    Design: Difficulty/compensating_invariant/controlled_drug_conservation_dispense_waste
    """
    ctx = setup_euthanasia_reconciled(dispense_ml=6.0, waste_ml=2.0, controlled_stock_ml=50)
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    assert van["controlled_reconciled_ml"] == van["controlled_stock_ml"] == 42.0


# ===========================================================================
# compensating_invariant / route_slot_conservation_book_then_cancel
# ===========================================================================

def test_route_slot_book_then_cancel_skips_stop(api):
    """PRD §3.3: "stops in `SKIPPED` are excluded from the count."
    PRD §3.6: "if a linked route stop is in `PLANNED`, it flips to `SKIPPED`."

    Book then cancel leaves the stop SKIPPED (the mechanism that restores
    stop_count to its pre-booking value of 0).

    Design: Difficulty/compensating_invariant/route_slot_conservation_book_then_cancel
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0, species="CAT", weight_kg=5)
    validate_success(api.cancel_appointment(ctx["appointment"]["id"], DISPATCHER))
    stop = validate_success(api.get_route_stop(ctx["stop"]["id"], DISPATCHER))
    assert stop["status"] == "SKIPPED"
