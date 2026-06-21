"""Crew and dock scheduling: half-open crew overlap, closed dock buffer,
material-readiness gate, the validation-priority pairs, material take-off, and
the crew confirm/cancel slot-capacity invariant.

Translates Difficulty/resource_temporal_overlap,
Difficulty/cross_entity_state_dependency (crew requires material order),
Difficulty/priority_pair_validation_conflict,
Difficulty/compensating_invariant (crew slot), and
Corner/calculations/material_takeoff_waste_ceiling.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_approved_project,
    add_confirmed_material_order, add_confirmed_crew_booking,
    FENCE_100_PLAIN, FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20,
)

PM = TEST_USERS["project_manager_headers"]
FT = TEST_USERS["field_tech_headers"]


# ===========================================================================
# resource_temporal_overlap instance 1: crew half-open overlap rejected
# ===========================================================================
def test_crew_booking_overlapping_window_rejected(api):
    """PRD §3.6: "the booking must not collide with any existing `CONFIRMED` booking on the same `crew_id`: two half-open windows conflict when the candidate's start is strictly before the existing window's end and the existing window's start is strictly before the candidate's end."
    PRD §3.6: "A collision is rejected with `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_overlap_rejected
    """
    # Project A confirms CREW_Y for [08:00, 17:00).
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_Y1")
    add_confirmed_crew_booking(pa, crew_id="CREW_Y",
                               window_start="2026-08-01T08:00:00Z",
                               window_end="2026-08-01T17:00:00Z")
    # Project B holds CREW_Y for [10:00, 15:00) — overlaps.
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    add_confirmed_material_order(pb, dock_id="DOCK_Y2",
                                 delivery_window_start="2026-07-02T08:00:00Z",
                                 delivery_window_end="2026-07-02T12:00:00Z")
    cb = get_success_data(api.create_crew_booking(pb, {
        "crew_id": "CREW_Y",
        "window_start": "2026-08-01T10:00:00Z",
        "window_end": "2026-08-01T15:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pb, cb["id"], FT)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)
    bookings = get_success_data(api.list_crew_bookings(pb, FT))
    held = [b for b in bookings if b["id"] == cb["id"]][0]
    assert held["status"] == "HELD"


def test_crew_booking_back_to_back_window_confirms(api):
    """PRD §3.6: "Because the windows are half-open, a booking that starts exactly when another ends (back-to-back) is **not** a conflict."
    A second CREW_Y booking starting exactly at the first's end (17:00) confirms
    cleanly.

    Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_overlap_rejected
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_BB1")
    add_confirmed_crew_booking(pa, crew_id="CREW_BB",
                               window_start="2026-08-01T08:00:00Z",
                               window_end="2026-08-01T17:00:00Z")
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    add_confirmed_material_order(pb, dock_id="DOCK_BB2",
                                 delivery_window_start="2026-07-02T08:00:00Z",
                                 delivery_window_end="2026-07-02T12:00:00Z")
    cb = get_success_data(api.create_crew_booking(pb, {
        "crew_id": "CREW_BB",
        "window_start": "2026-08-01T17:00:00Z",
        "window_end": "2026-08-02T02:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pb, cb["id"], FT)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# resource_temporal_overlap instance 2: dock closed-buffer overlap rejected
# ===========================================================================
def test_material_order_dock_within_buffer_rejected(api):
    """PRD §3.5: "no other material order in `CONFIRMED` or `DELIVERED` status on the **same** `dock_id` may have a delivery window that conflicts once a buffer is applied. The buffer is 4 hours."
    PRD §3.5: "Because the comparison uses closed, inclusive endpoints with the buffer added, windows that merely touch endpoints do conflict, and any gap shorter than 4 hours conflicts."
    PRD §3.5: "A conflict is rejected with `ERR_DOCK_WINDOW_CONFLICT`."
    Project A confirms DOCK_Z [08:00,12:00]; project B's PLACED order
    [14:00,16:00] is only 2h after A's end (inside the 4h buffer).

    Design: Difficulty/resource_temporal_overlap/material_order_dock_closed_buffer_overlap_rejected
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_Z",
                                 delivery_window_start="2026-09-01T08:00:00Z",
                                 delivery_window_end="2026-09-01T12:00:00Z")
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    mo_b = get_success_data(api.create_material_order(pb, {
        "supplier_name": "Acme", "dock_id": "DOCK_Z",
        "delivery_window_start": "2026-09-01T14:00:00Z",
        "delivery_window_end": "2026-09-01T16:00:00Z"}, PM))
    resp = api.confirm_material_order(pb, mo_b["id"], PM)
    validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT.value)
    orders = get_success_data(api.list_material_orders(pb, PM))
    placed = [o for o in orders if o["id"] == mo_b["id"]][0]
    assert placed["status"] == "PLACED"


def test_material_order_dock_outside_buffer_confirms(api):
    """PRD §3.5: "the candidate order's stored closed window is expanded by 4 hours on each side, while each existing order's window is taken as its stored closed window without buffer; the two conflict when the candidate's buffer-expanded start is at or before the existing window's end and the existing window's start is at or before the candidate's buffer-expanded end."
    A second DOCK_Z order beginning well beyond the 4h buffer (next day) does
    not conflict and confirms.

    Design: Difficulty/resource_temporal_overlap/material_order_dock_closed_buffer_overlap_rejected
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_ZZ",
                                 delivery_window_start="2026-09-01T08:00:00Z",
                                 delivery_window_end="2026-09-01T12:00:00Z")
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    mo_b = get_success_data(api.create_material_order(pb, {
        "supplier_name": "Acme", "dock_id": "DOCK_ZZ",
        "delivery_window_start": "2026-09-02T08:00:00Z",
        "delivery_window_end": "2026-09-02T12:00:00Z"}, PM))
    resp = api.confirm_material_order(pb, mo_b["id"], PM)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# cross_entity_state_dependency instance 1: crew confirm requires material ready
# ===========================================================================
def test_crew_confirm_without_ready_material_rejected(api):
    """PRD §3.6: "the project must have at least one material order in `CONFIRMED` or `DELIVERED` status, reflecting that materials are en route before a crew is locked in; otherwise the confirm is rejected with `ERR_MATERIAL_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/crew_confirm_requires_material_order_ready
    """
    ctx = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    # Place but do NOT confirm a material order — it stays PLACED.
    get_success_data(api.create_material_order(pid, {
        "supplier_name": "Acme", "dock_id": "DOCK_C",
        "delivery_window_start": "2026-07-01T08:00:00Z",
        "delivery_window_end": "2026-07-01T12:00:00Z"}, PM))
    cb = get_success_data(api.create_crew_booking(pid, {
        "crew_id": "CREW_C",
        "window_start": "2026-07-12T08:00:00Z",
        "window_end": "2026-07-12T17:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pid, cb["id"], FT)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_READY.value)
    bookings = get_success_data(api.list_crew_bookings(pid, FT))
    held = [b for b in bookings if b["id"] == cb["id"]][0]
    assert held["status"] == "HELD"


def test_crew_confirm_with_confirmed_material_advances_project(api):
    """PRD §3.6: "On a clean confirm, the booking moves from `HELD` to `CONFIRMED` and the project bubbles from `APPROVED` up to `SCHEDULED`."
    Once a material order is CONFIRMED, the readiness gate is satisfied and the
    crew booking confirms.

    Design: Difficulty/cross_entity_state_dependency/crew_confirm_requires_material_order_ready
    """
    ctx = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    add_confirmed_material_order(pid, dock_id="DOCK_CR")
    cb = get_success_data(api.create_crew_booking(pid, {
        "crew_id": "CREW_CR",
        "window_start": "2026-07-12T08:00:00Z",
        "window_end": "2026-07-12T17:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pid, cb["id"], FT)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED"
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["status"] == "SCHEDULED"


# ===========================================================================
# priority_pair_validation_conflict instance 2: crew overlap beats material
# ===========================================================================
def test_crew_confirm_overlap_reported_before_material_readiness(api):
    """PRD §2.9: "they are evaluated in a fixed priority order so that the
    failure a client sees is always the earliest applicable one."
    PRD §2.9: "followed by the domain-specific business gates described throughout §3 (setback, dock-window, crew-overlap, material-readiness, draw-gate and draw-sequence checks)."
    Crew-overlap precedes material-readiness, so when both apply the client sees
    ERR_CREW_DOUBLE_BOOKED.

    Design: Difficulty/priority_pair_validation_conflict/crew_confirm_temporal_overlap_beats_material_referential
    """
    # Project A: APPROVED, material confirmed, CONFIRMED crew on CREW_X [08:00,17:00).
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_A")
    add_confirmed_crew_booking(pa, crew_id="CREW_X",
                               window_start="2026-07-10T08:00:00Z",
                               window_end="2026-07-10T17:00:00Z")
    # Project B: APPROVED but NO material order; HELD crew on CREW_X [10:00,15:00).
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    cb = get_success_data(api.create_crew_booking(pb, {
        "crew_id": "CREW_X",
        "window_start": "2026-07-10T10:00:00Z",
        "window_end": "2026-07-10T15:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pb, cb["id"], FT)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)
    bookings = get_success_data(api.list_crew_bookings(pb, FT))
    held = [b for b in bookings if b["id"] == cb["id"]][0]
    assert held["status"] == "HELD"


def test_crew_confirm_dual_failure_does_not_advance_project(api):
    """PRD §3.6: "On a clean confirm, the booking moves from `HELD` to `CONFIRMED` and the project bubbles from `APPROVED` up to `SCHEDULED`." When the confirm
    is rejected (here for crew-overlap, the earliest of the two applicable §3
    gates), neither the booking nor the project advances — the booking stays
    HELD and the project stays APPROVED.

    Design: Difficulty/priority_pair_validation_conflict/crew_confirm_temporal_overlap_beats_material_referential
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_AX")
    add_confirmed_crew_booking(pa, crew_id="CREW_XX",
                               window_start="2026-07-10T08:00:00Z",
                               window_end="2026-07-10T17:00:00Z")
    # Project B: APPROVED, NO material order, HELD crew on CREW_XX overlapping A.
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    cb = get_success_data(api.create_crew_booking(pb, {
        "crew_id": "CREW_XX",
        "window_start": "2026-07-10T10:00:00Z",
        "window_end": "2026-07-10T15:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pb, cb["id"], FT)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)
    bookings = get_success_data(api.list_crew_bookings(pb, FT))
    held = [b for b in bookings if b["id"] == cb["id"]][0]
    assert held["status"] == "HELD"
    proj_b = get_success_data(api.get_project(pb, PM))
    assert proj_b["status"] == "APPROVED"


# ===========================================================================
# compensating_invariant instance 2: crew confirm then cancel restores slot
# ===========================================================================
def test_crew_cancel_frees_slot_for_same_window(api):
    """PRD §3.6: "A `FieldTech` may cancel a booking while it is `HELD` or `CONFIRMED`, moving it to `CANCELLED` and freeing its slot on the `crew_id`."
    PRD §3.6: "Only `CONFIRMED` bookings on the same crew are considered; `HELD` and `CANCELLED` bookings are ignored, and the comparison spans every project, not just this one." After cancelling project A's CONFIRMED CREW_W booking,
    project B confirms the identical window with no double-book.

    Design: Difficulty/compensating_invariant/crew_confirm_then_cancel_restores_slot_capacity
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_W1")
    cb_a = add_confirmed_crew_booking(pa, crew_id="CREW_W",
                                      window_start="2026-10-01T08:00:00Z",
                                      window_end="2026-10-01T17:00:00Z")
    cancel_resp = api.cancel_crew_booking(pa, cb_a["id"], FT)
    cancelled = validate_success(cancel_resp, expected_status=200)
    assert cancelled["status"] == "CANCELLED"
    # Project B books the identical window on CREW_W.
    ctx_b = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pb = ctx_b["project"]["id"]
    add_confirmed_material_order(pb, dock_id="DOCK_W2",
                                 delivery_window_start="2026-07-02T08:00:00Z",
                                 delivery_window_end="2026-07-02T12:00:00Z")
    cb_b = get_success_data(api.create_crew_booking(pb, {
        "crew_id": "CREW_W",
        "window_start": "2026-10-01T08:00:00Z",
        "window_end": "2026-10-01T17:00:00Z"}, FT))
    resp = api.confirm_crew_booking(pb, cb_b["id"], FT)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED"
    proj_b = get_success_data(api.get_project(pb, PM))
    assert proj_b["status"] == "SCHEDULED"


def test_crew_confirm_then_cancel_lands_cancelled(api):
    """PRD §3.6: "A `FieldTech` may cancel a booking while it is `HELD` or `CONFIRMED`, moving it to `CANCELLED` and freeing its slot on the `crew_id`. `CANCELLED` is the terminal crew-booking state."

    Design: Difficulty/compensating_invariant/crew_confirm_then_cancel_restores_slot_capacity
    """
    ctx_a = setup_approved_project(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pa = ctx_a["project"]["id"]
    add_confirmed_material_order(pa, dock_id="DOCK_WX")
    cb_a = add_confirmed_crew_booking(pa, crew_id="CREW_WX",
                                      window_start="2026-10-05T08:00:00Z",
                                      window_end="2026-10-05T17:00:00Z")
    resp = api.cancel_crew_booking(pa, cb_a["id"], FT)
    cancelled = validate_success(resp, expected_status=200)
    assert cancelled["status"] == "CANCELLED"


# ===========================================================================
# Corner/calculations: material take-off waste ceiling
# ===========================================================================
def test_material_takeoff_uses_measured_units_with_waste_ceiling(api):
    """PRD §3.5: "The take-off walks the project's `APPROVED` site-measure `measured_quantities` — not the estimate quantities — and for each line computes `ordered_units` as the measured units multiplied by one plus `waste_factor_pct` divided by 100, taken to the integer ceiling."
    Measured 132 with default waste 10 -> ceil(132 * 1.10) = ceil(145.2) = 146,
    a value every faithful implementer reaches regardless of decimal/float basis.

    Design: Corner/calculations/material_takeoff_waste_ceiling
    """
    from test_helpers import setup_accepted_estimate
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li, deck_li = ctx["line_items"]
    sm = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [
            {"line_item_id": fence_li["id"], "measured_units": 132},
            {"line_item_id": deck_li["id"], "measured_units": 200}],
        "property_line_note": "clear", "setback_ok": True}, FT))
    get_success_data(api.approve_site_measure(pid, sm["id"], PM))
    mo = get_success_data(api.create_material_order(pid, {
        "supplier_name": "Acme", "dock_id": "DOCK_TK",
        "delivery_window_start": "2026-07-01T08:00:00Z",
        "delivery_window_end": "2026-07-01T12:00:00Z"}, PM))
    resp = api.confirm_material_order(pid, mo["id"], PM)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED"
    by_line = {ol["line_item_id"]: ol["ordered_units"] for ol in confirmed["ordered_lines"]}
    # 132 * 1.10 = 145.2 -> ceil 146 (basis-independent; the 200-line's
    # 220.0-vs-220.00000003 ceiling is float-dependent and not pinned here).
    assert by_line[fence_li["id"]] == 146
