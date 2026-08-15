"""Vendor scheduling: calendar overlap, adjacency, cure buffer, sequencing,
trade matching, vendor ownership, and the open-assignment count invariant."""
from test_helpers import (
    TC,
    ApiErrorId,
    accept,
    add_scope_item,
    complete,
    create_property,
    create_unit,
    create_vendor,
    decline,
    finalize_turn,
    get_assignment,
    get_item,
    list_assignments,
    make_vendor_headers,
    open_turn,
    schedule,
    setup_scoped_turn,
    validate_error,
    validate_success,
)


def _scoped_turn_with_item(prop, unit_number, category="CLEAN", estimate=5000):
    """A fresh unit of `prop` carrying a SCOPED turn with one PLANNED item."""
    unit = create_unit(prop["id"], unit_number=unit_number)
    turn = open_turn(unit["id"])
    item = add_scope_item(turn["id"], category, estimate)
    finalize_turn(turn["id"])
    return unit, turn, item


# --- per-vendor occupation (Difficulty: vendor_calendar_half_open_overlap_semantics)

def test_identical_window_for_different_vendor_is_allowed(api):
    """PRD §3.4: "the new half-open window may not intersect any other
    `SCHEDULED` or `ACCEPTED` assignment of the same vendor, though pure
    adjacency — one assignment's `end_date` equalling the other's `start_date`
    — is allowed; a colliding request is rejected with `ERR_VENDOR_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/vendor_calendar_half_open_overlap_semantics
    """
    prop = create_property(days_to_ready_target=7)
    _, _, item1 = _scoped_turn_with_item(prop, "101")
    v1 = create_vendor("CleanCo One", "CLEAN")
    v2 = create_vendor("CleanCo Two", "CLEAN")
    schedule(item1["id"], v1["id"], "2026-08-05", "2026-08-08")

    _, _, item2 = _scoped_turn_with_item(prop, "102")
    # Occupation is per-vendor: the identical window for V2 does not collide.
    assignment = schedule(item2["id"], v2["id"], "2026-08-05", "2026-08-08")
    assert assignment["status"] == "SCHEDULED"
    assert assignment["vendor_id"] == v2["id"]


def test_nested_window_for_same_vendor_collides(api):
    """PRD §3.4: "the new half-open window may not intersect any other
    `SCHEDULED` or `ACCEPTED` assignment of the same vendor, though pure
    adjacency — one assignment's `end_date` equalling the other's `start_date`
    — is allowed; a colliding request is rejected with `ERR_VENDOR_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/vendor_calendar_half_open_overlap_semantics
    """
    prop = create_property(days_to_ready_target=7)
    _, _, item1 = _scoped_turn_with_item(prop, "101")
    v1 = create_vendor("CleanCo One", "CLEAN")
    schedule(item1["id"], v1["id"], "2026-08-05", "2026-08-08")

    _, _, item3 = _scoped_turn_with_item(prop, "103")
    # [08-06, 08-07) nests inside V1's [08-05, 08-08) — a collision.
    resp = api.create_vendor_assignment(
        {"scope_item_id": item3["id"], "vendor_id": v1["id"],
         "start_date": "2026-08-06", "end_date": "2026-08-07"}, TC)
    validate_error(resp, ApiErrorId.ERR_VENDOR_OVERLAP, 422)
    assert get_item(item3["id"])["status"] == "PLANNED"


# --- half-open adjacency (Difficulty: vendor_calendar_half_open_adjacency_boundary)

def test_start_equal_to_prior_end_is_allowed_adjacency(api):
    """PRD §3.4: "pure adjacency — one assignment's `end_date` equalling the
    other's `start_date` — is allowed"."

    Design: Difficulty/boundary_precision_check/vendor_calendar_half_open_adjacency_boundary
    """
    prop = create_property(days_to_ready_target=7)
    _, _, item1 = _scoped_turn_with_item(prop, "101")
    vendor = create_vendor("CleanCo", "CLEAN")
    schedule(item1["id"], vendor["id"], "2026-08-05", "2026-08-08")

    _, _, item2 = _scoped_turn_with_item(prop, "102")
    adjacent = schedule(item2["id"], vendor["id"], "2026-08-08", "2026-08-10")
    assert adjacent["status"] == "SCHEDULED", (
        "start == prior end is allowed under half-open [start, end) semantics"
    )


def test_start_one_day_inside_prior_window_collides(api):
    """PRD §3.4: "the new half-open window may not intersect any other
    `SCHEDULED` or `ACCEPTED` assignment of the same vendor, though pure
    adjacency — one assignment's `end_date` equalling the other's `start_date`
    — is allowed; a colliding request is rejected with `ERR_VENDOR_OVERLAP`."

    Design: Difficulty/boundary_precision_check/vendor_calendar_half_open_adjacency_boundary
    """
    prop = create_property(days_to_ready_target=7)
    _, _, item1 = _scoped_turn_with_item(prop, "101")
    vendor = create_vendor("CleanCo", "CLEAN")
    schedule(item1["id"], vendor["id"], "2026-08-05", "2026-08-08")

    _, _, item3 = _scoped_turn_with_item(prop, "103")
    resp = api.create_vendor_assignment(
        {"scope_item_id": item3["id"], "vendor_id": vendor["id"],
         "start_date": "2026-08-07", "end_date": "2026-08-09"}, TC)
    validate_error(resp, ApiErrorId.ERR_VENDOR_OVERLAP, 422)
    assert get_item(item3["id"])["status"] == "PLANNED", (
        "no assignment may be persisted for the colliding request"
    )


# --- paint-to-carpet cure buffer (Difficulty: paint_carpet_cure_buffer_semantics)

def _setup_completed_paint_with_planned_carpet(api):
    """Turn with PAINT work completed over [2026-08-05, 2026-08-07) and a
    PLANNED CARPET item awaiting scheduling."""
    prop = create_property(days_to_ready_target=7)
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    paint = add_scope_item(turn["id"], "PAINT", 100000, "repaint")
    finalize_turn(turn["id"])
    # 500bp variance — within the 1000bp auto-approve band, so PLANNED.
    carpet = add_scope_item(turn["id"], "CARPET", 5000, "recarpet")
    painter = create_vendor("PaintPros", "PAINT")
    carpeting = create_vendor("CarpetCo", "CARPET")
    paint_asg = schedule(paint["id"], painter["id"], "2026-08-05", "2026-08-07")
    accept(paint_asg["id"], painter["id"])
    complete(paint_asg["id"], painter["id"], 9000)
    return carpet, carpeting


def test_carpet_start_on_paint_end_violates_cure_buffer(api):
    """PRD §3.4: "a `CARPET` assignment whose `start_date` falls before the
    latest same-turn `PAINT` assignment's `end_date` plus one day, while that
    paint work is not yet complete, is rejected with
    `ERR_CURE_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/paint_carpet_cure_buffer_semantics
    """
    carpet, carpeting = _setup_completed_paint_with_planned_carpet(api)
    # Start 2026-08-07 < paint end 2026-08-07 + 1 cure day: rejected even
    # though the two windows share no calendar day.
    resp = api.create_vendor_assignment(
        {"scope_item_id": carpet["id"], "vendor_id": carpeting["id"],
         "start_date": "2026-08-07", "end_date": "2026-08-09"}, TC)
    validate_error(resp, ApiErrorId.ERR_CURE_BUFFER_VIOLATION, 422)
    assert get_item(carpet["id"])["status"] == "PLANNED"


def test_carpet_start_one_day_after_paint_end_satisfies_buffer(api):
    """PRD §3.4: "a `CARPET` assignment whose `start_date` falls before the
    latest same-turn `PAINT` assignment's `end_date` plus one day, while that
    paint work is not yet complete, is rejected with
    `ERR_CURE_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/paint_carpet_cure_buffer_semantics
    """
    carpet, carpeting = _setup_completed_paint_with_planned_carpet(api)
    # Start 2026-08-08 == paint end + 1: the cure day is respected.
    assignment = schedule(carpet["id"], carpeting["id"],
                          "2026-08-08", "2026-08-09")
    assert assignment["status"] == "SCHEDULED"
    assert assignment["scope_item_id"] == carpet["id"]


# --- temporal beats sequence (Difficulty: temporal_beats_sequence_on_assignment_create)

def _setup_overlap_and_sequence_conflict(api):
    """Vendor V busy [2026-08-05, 2026-08-08) on turn T1; turn T2 holds a
    PLANNED REPAIR item and a PLANNED PAINT item."""
    prop = create_property(days_to_ready_target=7)
    unit1 = create_unit(prop["id"], unit_number="101")
    turn1 = open_turn(unit1["id"])
    paint1 = add_scope_item(turn1["id"], "PAINT", 10000, "repaint 101")
    finalize_turn(turn1["id"])
    painter = create_vendor("PaintPros", "PAINT")
    schedule(paint1["id"], painter["id"], "2026-08-05", "2026-08-08")

    unit2 = create_unit(prop["id"], unit_number="102")
    turn2 = open_turn(unit2["id"])
    add_scope_item(turn2["id"], "REPAIR", 1000, "repair 102")
    paint2 = add_scope_item(turn2["id"], "PAINT", 2000, "paint 102")
    finalize_turn(turn2["id"])
    return painter, paint2


def test_vendor_overlap_reported_when_sequence_also_violated(api):
    """PRD §2.8: "Every request is evaluated against a fixed, ordered
    validation chain, and the first failing check determines the error returned
    — later checks are never reached once an earlier one fails." (Business
    temporal rules, check 9, run before business constraint rules, check 10.)

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_sequence_on_assignment_create
    """
    painter, paint2 = _setup_overlap_and_sequence_conflict(api)
    # Violates BOTH the vendor calendar (V busy 08-05..08-08) and category
    # sequencing (lower-rank REPAIR item still PLANNED): temporal wins.
    resp = api.create_vendor_assignment(
        {"scope_item_id": paint2["id"], "vendor_id": painter["id"],
         "start_date": "2026-08-06", "end_date": "2026-08-09"}, TC)
    validate_error(resp, ApiErrorId.ERR_VENDOR_OVERLAP, 422)


def test_rejected_dual_violation_persists_no_assignment(api):
    """PRD §3.4: "A created assignment enters `SCHEDULED`, moves its scope item
    from `PLANNED` to `SCHEDULED`, adds one to the vendor's
    `open_assignment_count`, and triggers a recomputation of the turn's
    `projected_ready_date` with commitment risk re-evaluated." — a rejected
    creation therefore leaves the item `PLANNED`.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_sequence_on_assignment_create
    """
    painter, paint2 = _setup_overlap_and_sequence_conflict(api)
    validate_error(
        api.create_vendor_assignment(
            {"scope_item_id": paint2["id"], "vendor_id": painter["id"],
             "start_date": "2026-08-06", "end_date": "2026-08-09"}, TC),
        ApiErrorId.ERR_VENDOR_OVERLAP, 422,
    )
    item = get_item(paint2["id"])
    assert item["status"] == "PLANNED", "no assignment may be persisted"


# --- open-assignment count conservation (Difficulty: vendor_open_assignment_create_decline_conservation)

def test_assignment_create_increments_open_count(api):
    """PRD §3.1: "Each vendor carries `open_assignment_count`, the count of its
    assignments currently in `SCHEDULED` or `ACCEPTED` status, initialized to
    zero at registration."
    PRD §3.4: "A created assignment enters `SCHEDULED`, moves its scope item
    from `PLANNED` to `SCHEDULED`, adds one to the vendor's
    `open_assignment_count`, and triggers a recomputation of the turn's
    `projected_ready_date` with commitment risk re-evaluated."

    Design: Difficulty/compensating_invariant/vendor_open_assignment_create_decline_conservation
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    vendor = create_vendor("FixCo", "REPAIR")
    _data, meta0 = list_assignments(
        {"vendor_id": vendor["id"], "status": "SCHEDULED"})
    assert meta0["total_count"] == 0, "zero open assignments at registration"

    assignment = schedule(ctx["item"]["id"], vendor["id"],
                          "2026-08-01", "2026-08-03")
    assert assignment["status"] == "SCHEDULED"
    _data, meta1 = list_assignments(
        {"vendor_id": vendor["id"], "status": "SCHEDULED"})
    assert meta1["total_count"] == 1, "the forward action adds one"
    assert get_item(ctx["item"]["id"])["status"] == "SCHEDULED"


def test_decline_restores_open_count_and_returns_item_to_planned(api):
    """PRD §3.4: "Decline moves a `SCHEDULED` assignment to `DECLINED`: the
    scope item falls back from `SCHEDULED` to `PLANNED`, the vendor's
    `open_assignment_count` drops by one (conserving the count across
    create-and-decline round trips), and the projection is recomputed with
    risk re-evaluated."

    Design: Difficulty/compensating_invariant/vendor_open_assignment_create_decline_conservation
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    vendor = create_vendor("FixCo", "REPAIR")
    assignment = schedule(ctx["item"]["id"], vendor["id"],
                          "2026-08-01", "2026-08-03")
    _data, meta1 = list_assignments(
        {"vendor_id": vendor["id"], "status": "SCHEDULED"})
    assert meta1["total_count"] == 1

    declined = decline(assignment["id"], vendor["id"])
    assert declined["status"] == "DECLINED"
    _data, meta2 = list_assignments(
        {"vendor_id": vendor["id"], "status": "SCHEDULED"})
    assert meta2["total_count"] == 0, "DECLINED is not an open status"
    assert get_item(ctx["item"]["id"])["status"] == "PLANNED"


# --- unit window (Corner: unit_window_overlap_rejected)

def test_same_turn_shared_day_rejected_even_across_vendors(api):
    """PRD §3.4: "the new assignment may not share any calendar day with
    another `SCHEDULED` or `ACCEPTED` assignment on the same turn, a
    day-granularity check distinct from the vendor's interval arithmetic, and
    a violation is rejected with `ERR_UNIT_WINDOW_OVERLAP`."

    Design: Corner/errors/unit_window_overlap_rejected
    """
    prop = create_property(days_to_ready_target=7)
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    item_a = add_scope_item(turn["id"], "REPAIR", 5000, "item A")
    item_b = add_scope_item(turn["id"], "REPAIR", 6000, "item B")
    finalize_turn(turn["id"])
    v1 = create_vendor("FixCo", "REPAIR")
    v2 = create_vendor("OtherCo", "REPAIR")
    schedule(item_a["id"], v1["id"], "2026-08-05", "2026-08-08")

    # Different vendor (vendor calendar passes); equal rank (sequencing
    # passes); shared day 2026-08-06 — one crew in the unit at a time.
    resp = api.create_vendor_assignment(
        {"scope_item_id": item_b["id"], "vendor_id": v2["id"],
         "start_date": "2026-08-06", "end_date": "2026-08-07"}, TC)
    validate_error(resp, ApiErrorId.ERR_UNIT_WINDOW_OVERLAP, 422)
    assert get_item(item_b["id"])["status"] == "PLANNED"


# --- category sequencing (Corner: sequence_violation_rejected)

def test_scheduling_paint_while_repair_planned_rejected(api):
    """PRD §3.4: "category sequencing requires that no same-turn item with a
    lower `sequence_rank` still sits in `PLANNED`, `PENDING_APPROVAL`, or
    `SCHEDULED` when the assignment is created — repairs before appliances,
    appliances before fixtures, fixtures before paint, paint before carpet,
    carpet before cleaning — and a violation is rejected with
    `ERR_SEQUENCE_VIOLATION`."

    Design: Corner/errors/sequence_violation_rejected
    """
    prop = create_property(days_to_ready_target=7)
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    add_scope_item(turn["id"], "REPAIR", 5000, "first")
    paint = add_scope_item(turn["id"], "PAINT", 8000, "second")
    finalize_turn(turn["id"])
    painter = create_vendor("PaintPros", "PAINT")

    resp = api.create_vendor_assignment(
        {"scope_item_id": paint["id"], "vendor_id": painter["id"],
         "start_date": "2026-08-05", "end_date": "2026-08-07"}, TC)
    validate_error(resp, ApiErrorId.ERR_SEQUENCE_VIOLATION, 422)
    assert get_item(paint["id"])["status"] == "PLANNED"


# --- trade matching (Corner: vendor_trade_mismatch_rejected)

def test_paint_vendor_cannot_take_repair_item(api):
    """PRD §3.1: "a scope item in category `REPAIR`, `PAINT`, `CARPET`, or
    `CLEAN` accepts only a vendor of exactly that trade, while items in
    category `APPLIANCE`, `FIXTURE`, or `OTHER` are handled by `REPAIR`-trade
    vendors; any other pairing is rejected with `ERR_VENDOR_TRADE_MISMATCH`."

    Design: Corner/validations/vendor_trade_mismatch_rejected
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    painter = create_vendor("PaintPros", "PAINT")
    resp = api.create_vendor_assignment(
        {"scope_item_id": ctx["item"]["id"], "vendor_id": painter["id"],
         "start_date": "2026-08-01", "end_date": "2026-08-03"}, TC)
    validate_error(resp, ApiErrorId.ERR_VENDOR_TRADE_MISMATCH, 422)
    assert get_item(ctx["item"]["id"])["status"] == "PLANNED"


# --- vendor ownership (Corner: vendor_not_assigned_forbidden)

def test_other_vendor_cannot_accept_assignment(api):
    """PRD §2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of
    the acting `Vendor` entity; ownership checks on any vendor assignment
    compare the assignment's `vendor_id` field against `X-User-ID`, and a
    mismatch is rejected with `ERR_VENDOR_NOT_ASSIGNED`."

    Design: Corner/errors/vendor_not_assigned_forbidden
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    v1 = create_vendor("FixCo", "REPAIR")
    v2 = create_vendor("OtherCo", "REPAIR")
    assignment = schedule(ctx["item"]["id"], v1["id"],
                          "2026-08-01", "2026-08-03")

    resp = api.accept_assignment(assignment["id"], make_vendor_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ASSIGNED, 403)
    assert get_assignment(assignment["id"])["status"] == "SCHEDULED"


# --- complete requires ACCEPTED (Corner: complete_unaccepted_assignment_returns_invalid_state)

def test_complete_on_unaccepted_assignment_rejected(api):
    """PRD §3.4: "The assigned vendor completes an `ACCEPTED` assignment by
    reporting the invoiced `actual_cost_cents`; the assignment becomes
    `COMPLETED`, the vendor's `open_assignment_count` drops by one, and the
    scope item moves from `SCHEDULED` to `COMPLETED` with its own
    `actual_cost_cents` set from the assignment."
    PRD §3.4: "Acceptance moves a `SCHEDULED` assignment to `ACCEPTED` (any
    other starting status yields `ERR_INVALID_STATE`)."
    PRD §3.4: "Until that moment, `actual_cost_cents` is null on both the
    assignment and the scope item."

    Design: Corner/state_machines/complete_unaccepted_assignment_returns_invalid_state
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    vendor = create_vendor("FixCo", "REPAIR")
    assignment = schedule(ctx["item"]["id"], vendor["id"],
                          "2026-08-01", "2026-08-03")

    resp = api.complete_assignment(
        assignment["id"], {"actual_cost_cents": 4000},
        make_vendor_headers(vendor["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_assignment(assignment["id"])["status"] == "SCHEDULED"
    assert get_item(ctx["item"]["id"])["actual_cost_cents"] is None
