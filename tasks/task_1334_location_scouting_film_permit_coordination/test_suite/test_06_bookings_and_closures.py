"""Location booking buffer (closed intervals) vs street closure overlap
(half-open intervals), closure permit gating, and segment occupancy."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_location_booking,
    assert_street_closure,
    create_location_booking_payload,
    create_street_closure_payload,
    get_success_data,
    setup_basic_scenario,
    setup_issued_permit,
    setup_production_with_executed_agreement,
    setup_submitted_permit,
    setup_under_review_permit,
    setup_verified_insurance,
    validate_error,
    validate_paginated,
    validate_success,
)


def _issued_lanes2_scenario(api):
    """EXECUTED agreement -> ISSUED permit with closed_lanes 2, hours 8."""
    scenario = setup_production_with_executed_agreement()
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", closed_lanes=2, shoot_hours_per_day=8,
    )
    scenario["permit"] = permit
    return scenario


def _list_closures(api, production_id, permit_id=None):
    params = {"permit_application_id": permit_id} if permit_id else None
    rows, _ = validate_paginated(api.list_street_closures(production_id, LM, params=params))
    return rows


# ---------------------------------------------------------------------------
# Difficulty: half-open closure adjacency is not an overlap
# ---------------------------------------------------------------------------

def test_closure_starting_at_prior_end_approves_but_one_second_earlier_conflicts(api):
    """PRD §3.6: "The overlap test uses half-open interval semantics — the window
    includes `closure_start` and excludes `closure_end` — so a closure starting at
    the exact instant another ends does not collide with it, in deliberate
    contrast to the closed-interval booking buffer of §3.3."
    PRD §3.6: "no other `APPROVED` or `ACTIVE` closure on the same
    `street_segment` may intersect the requested window (else
    `ERR_CLOSURE_OVERLAP`, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/street_closure_half_open_adjacency_not_overlap
    """
    scenario = _issued_lanes2_scenario(api)
    production_id = scenario["production"]["id"]
    permit_id = scenario["permit"]["id"]

    closure_a = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T06:00:00Z", closure_end="2026-08-10T14:00:00Z",
        ),
        LM,
    ))
    get_success_data(api.approve_street_closure(production_id, closure_a["id"], FO))

    # Starts exactly when A ends: half-open adjacency, NOT an overlap.
    closure_b = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T14:00:00Z", closure_end="2026-08-10T20:00:00Z",
        ),
        LM,
    ))
    approved_b = validate_success(api.approve_street_closure(production_id, closure_b["id"], FO))
    assert_street_closure(approved_b)
    assert approved_b["status"] == "APPROVED"

    # 13:59:59 is one second inside A's window: intersects.
    closure_c = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T13:59:59Z", closure_end="2026-08-10T18:00:00Z",
        ),
        LM,
    ))
    resp = api.approve_street_closure(production_id, closure_c["id"], FO)
    validate_error(resp, ApiErrorId.ERR_CLOSURE_OVERLAP)
    by_id = {row["id"]: row for row in _list_closures(api, production_id, permit_id)}
    assert by_id[closure_c["id"]]["status"] == "REQUESTED"


def test_closure_overlap_scoped_to_same_segment_and_reverse_adjacency(api):
    """PRD §3.6: "no other `APPROVED` or `ACTIVE` closure on the same
    `street_segment` may intersect the requested window (else
    `ERR_CLOSURE_OVERLAP`, HTTP 409)."
    PRD §3.6: "a closure starting at the exact instant another ends does not
    collide with it"

    Design: Difficulty/resource_temporal_overlap/street_closure_half_open_adjacency_not_overlap
    """
    scenario = _issued_lanes2_scenario(api)
    production_id = scenario["production"]["id"]
    permit_id = scenario["permit"]["id"]

    closure_a = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T06:00:00Z", closure_end="2026-08-10T14:00:00Z",
        ),
        LM,
    ))
    get_success_data(api.approve_street_closure(production_id, closure_a["id"], FO))

    # Same time window on a DIFFERENT segment: outside the rule's scope.
    other_segment = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, street_segment="ELM-ST-200-BLOCK",
            closure_start="2026-08-10T06:00:00Z", closure_end="2026-08-10T14:00:00Z",
        ),
        LM,
    ))
    approved_other = validate_success(api.approve_street_closure(production_id, other_segment["id"], FO))
    assert approved_other["status"] == "APPROVED"

    # Ends exactly when A starts on the same segment: half-open adjacency.
    before_a = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T02:00:00Z", closure_end="2026-08-10T06:00:00Z",
        ),
        LM,
    ))
    approved_before = validate_success(api.approve_street_closure(production_id, before_a["id"], FO))
    assert approved_before["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: street-segment occupancy invariant (approve/cancel pair)
# ---------------------------------------------------------------------------

def test_segment_occupancy_returns_to_baseline_after_cancel(api):
    """PRD §3.6: "A `LocationManager` may cancel a closure while it is `REQUESTED`
    or `APPROVED`, moving it to `CANCELLED`."
    PRD §3.6: "Either way, cancellation frees the interval on the street segment
    for future approvals."

    Design: Difficulty/compensating_invariant/street_segment_occupancy_approve_cancel_invariant
    """
    scenario = _issued_lanes2_scenario(api)
    production_id = scenario["production"]["id"]
    permit_id = scenario["permit"]["id"]

    closure = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T06:00:00Z", closure_end="2026-08-10T14:00:00Z",
        ),
        LM,
    ))
    approved = validate_success(api.approve_street_closure(production_id, closure["id"], FO))
    assert approved["status"] == "APPROVED"

    probe = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T16:00:00Z", closure_end="2026-08-10T18:00:00Z",
        ),
        LM,
    ))
    cancelled = validate_success(api.cancel_street_closure(production_id, closure["id"], LM))
    assert cancelled["status"] == "CANCELLED"

    # The cancel freed the segment: the probe approves cleanly.
    approved_probe = validate_success(api.approve_street_closure(production_id, probe["id"], FO))
    assert approved_probe["status"] == "APPROVED"


def test_approved_closure_blocks_then_cancel_frees_same_window(api):
    """PRD §3.6: "no other `APPROVED` or `ACTIVE` closure on the same
    `street_segment` may intersect the requested window (else
    `ERR_CLOSURE_OVERLAP`, HTTP 409)."
    PRD §3.6: "Either way, cancellation frees the interval on the street segment
    for future approvals."

    Design: Difficulty/compensating_invariant/street_segment_occupancy_approve_cancel_invariant
    """
    scenario = _issued_lanes2_scenario(api)
    production_id = scenario["production"]["id"]
    permit_id = scenario["permit"]["id"]

    closure = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T06:00:00Z", closure_end="2026-08-10T14:00:00Z",
        ),
        LM,
    ))
    get_success_data(api.approve_street_closure(production_id, closure["id"], FO))

    # While APPROVED, an overlapping window on the same segment is blocked.
    probe = get_success_data(api.create_street_closure(
        production_id,
        create_street_closure_payload(
            permit_id, closure_start="2026-08-10T13:00:00Z", closure_end="2026-08-10T15:00:00Z",
        ),
        LM,
    ))
    validate_error(
        api.approve_street_closure(production_id, probe["id"], FO),
        ApiErrorId.ERR_CLOSURE_OVERLAP,
    )
    # After the compensating cancel, the very same window approves.
    validate_success(api.cancel_street_closure(production_id, closure["id"], LM))
    approved_probe = validate_success(api.approve_street_closure(production_id, probe["id"], FO))
    assert approved_probe["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: closed-interval booking buffer — touching is a conflict
# ---------------------------------------------------------------------------

def test_booking_buffer_touching_is_conflict_and_clear_window_passes(api):
    """PRD §3.3: "the new booking's closed interval, widened on both sides by the
    location's `buffer_days` — that is, from `buffer_days` before
    `booking_start_date` through `buffer_days` after `booking_end_date`, both ends
    included — must not intersect any other `CONFIRMED` booking's own closed
    `booking_start_date`-to-`booking_end_date` interval at the same location."
    PRD §3.3: "Because both intervals are closed, mere adjacency is already a
    conflict: if the widened interval so much as shares one calendar date with an
    existing confirmed booking, creation is rejected with
    `ERR_BOOKING_BUFFER_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/location_booking_closed_interval_buffer_touching_is_conflict
    """
    scenario = setup_basic_scenario()  # location buffer_days 2
    production_id = scenario["production"]["id"]
    location_id = scenario["location"]["id"]

    first = get_success_data(api.create_location_booking(
        production_id, create_location_booking_payload(location_id), LM,
    ))
    assert_location_booking(first)
    assert first["status"] == "CONFIRMED"

    # New [08-14, 08-15] buffered to [08-12, 08-17]: touches existing [08-10, 08-12].
    touching = api.create_location_booking(
        production_id,
        create_location_booking_payload(
            location_id, booking_start_date="2026-08-14", booking_end_date="2026-08-15",
        ),
        LM,
    )
    validate_error(touching, ApiErrorId.ERR_BOOKING_BUFFER_CONFLICT)

    # New [08-15, 08-16] buffered to [08-13, 08-18]: disjoint from [08-10, 08-12].
    clear = api.create_location_booking(
        production_id,
        create_location_booking_payload(
            location_id, booking_start_date="2026-08-15", booking_end_date="2026-08-16",
        ),
        LM,
    )
    clear_data = validate_success(clear, 201)
    assert clear_data["status"] == "CONFIRMED"

    rows, _ = validate_paginated(api.list_location_bookings(production_id, LM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "CONFIRMED", "The existing booking is untouched"


def test_booking_buffer_before_side_boundary_and_release_frees_interval(api):
    """PRD §3.3: "if the widened interval so much as shares one calendar date with
    an existing confirmed booking, creation is rejected with
    `ERR_BOOKING_BUFFER_CONFLICT` (HTTP 409)."
    PRD §3.3: "Releasing a booking is a `LocationManager` action that moves it to
    `RELEASED` and frees its interval for future buffer checks."

    Design: Difficulty/resource_temporal_overlap/location_booking_closed_interval_buffer_touching_is_conflict
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    location_id = scenario["location"]["id"]

    first = get_success_data(api.create_location_booking(
        production_id, create_location_booking_payload(location_id), LM,
    ))

    # Before-side, just clear: [08-07, 08-07] buffered [08-05, 08-09] vs [08-10, 08-12].
    clear_before = api.create_location_booking(
        production_id,
        create_location_booking_payload(
            location_id, booking_start_date="2026-08-07", booking_end_date="2026-08-07",
        ),
        LM,
    )
    assert validate_success(clear_before, 201)["status"] == "CONFIRMED"

    # Before-side, touching: [08-06, 08-08] buffered [08-04, 08-10] meets 08-10.
    touching_before = api.create_location_booking(
        production_id,
        create_location_booking_payload(
            location_id, booking_start_date="2026-08-06", booking_end_date="2026-08-08",
        ),
        LM,
    )
    validate_error(touching_before, ApiErrorId.ERR_BOOKING_BUFFER_CONFLICT)

    # Releasing the first booking frees its interval for future buffer checks.
    released = validate_success(
        api.release_location_booking(production_id, first["id"], LM)
    )
    assert released["status"] == "RELEASED"
    now_clear = api.create_location_booking(
        production_id,
        create_location_booking_payload(
            location_id, booking_start_date="2026-08-11", booking_end_date="2026-08-12",
        ),
        LM,
    )
    assert validate_success(now_clear, 201)["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Difficulty: closure approve gated by the backing permit being ISSUED
# ---------------------------------------------------------------------------

def test_closure_approve_rejected_until_permit_issued(api):
    """PRD §3.6: "Film-office approval is gated twice: the backing permit
    application must be `ISSUED` (else `ERR_PERMIT_NOT_ISSUED`), and no other
    `APPROVED` or `ACTIVE` closure on the same `street_segment` may intersect the
    requested window (else `ERR_CLOSURE_OVERLAP`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/street_closure_approve_gated_by_permit_issued
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit = setup_under_review_permit(scenario, clock="2026-08-03T09:00:00Z")
    closure = get_success_data(api.create_street_closure(
        production_id, create_street_closure_payload(permit["id"]), LM,
    ))

    blocked = api.approve_street_closure(production_id, closure["id"], FO)
    validate_error(blocked, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
    rows = _list_closures(api, production_id)
    assert rows[0]["status"] == "REQUESTED"

    # Once the permit is ISSUED the same approval succeeds.
    setup_verified_insurance(scenario)
    get_success_data(api.decide_permit_application(production_id, permit["id"], "ISSUE", FO))
    approved = validate_success(api.approve_street_closure(production_id, closure["id"], FO))
    assert approved["status"] == "APPROVED"


def test_closure_approve_rejected_while_permit_only_submitted(api):
    """PRD §3.6: "the backing permit application must be `ISSUED` (else
    `ERR_PERMIT_NOT_ISSUED`)"

    Design: Difficulty/cross_entity_state_dependency/street_closure_approve_gated_by_permit_issued
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit = setup_submitted_permit(scenario, clock="2026-08-03T09:00:00Z")
    assert permit["status"] == "SUBMITTED"
    closure = get_success_data(api.create_street_closure(
        production_id, create_street_closure_payload(permit["id"]), LM,
    ))

    resp = api.approve_street_closure(production_id, closure["id"], FO)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
    rows = _list_closures(api, production_id)
    assert rows[0]["status"] == "REQUESTED"
