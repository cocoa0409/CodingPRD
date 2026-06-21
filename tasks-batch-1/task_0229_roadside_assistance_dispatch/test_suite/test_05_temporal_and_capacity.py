"""Temporal-overlap, bay-capacity, occupancy-invariant, and dispatch-ranking tests.

Covers the half-open shift-overlap rule (adjacency allowed), the buffered closed-window
aggregate bay-capacity rule, the bay-occupancy conserved quantity (reserve then release),
and the multi-factor dispatch-candidate ranking with the TOW-only capability-count
tie-break.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_depot_with_reservation, make_call_for_candidates, add_provider_with_shift,
    create_provider, create_shift,
    ApiErrorId, TEST_USERS,
)
from test_helpers import set_clock, create_plan, create_member, create_depot, create_call
from test_helpers import factories as F

OP = TEST_USERS["dispatch_operator_headers"]


# =========================================================================
# Queue A — resource_temporal_overlap (provider shift, half-open)
# =========================================================================
def test_shift_positive_overlap_rejected(api):
    """PRD §3.3: "A shift may not be admitted if its half-open window overlaps, with
    positive measure, an existing `SCHEDULED` shift for the same provider; pure
    adjacency, where one shift's `shift_end` exactly equals another's `shift_start`, is
    allowed, but any genuine overlap is rejected with `ERR_SHIFT_OVERLAP`."

    Existing [08:00,16:00); a new [15:00,20:00) overlaps positively.

    Design: Difficulty/resource_temporal_overlap/provider_shift_half_open_overlap_rejected_adjacency_allowed
    """
    set_clock("2026-06-01T07:00:00Z")
    prov = create_provider()
    create_shift(prov["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    resp = api.create_shift(prov["id"],
                            F.create_shift_payload("2026-06-01T15:00:00Z", "2026-06-01T20:00:00Z"), OP)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)


def test_shift_pure_adjacency_allowed(api):
    """PRD §3.3: "pure adjacency, where one shift's `shift_end` exactly equals another's
    `shift_start`, is allowed, but any genuine overlap is rejected with
    `ERR_SHIFT_OVERLAP`."

    Existing [08:00,16:00); a new [16:00,20:00) touches at the boundary and is admitted.

    Design: Difficulty/resource_temporal_overlap/provider_shift_half_open_overlap_rejected_adjacency_allowed
    """
    set_clock("2026-06-01T07:00:00Z")
    prov = create_provider()
    create_shift(prov["id"], "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    data = validate_success(
        api.create_shift(prov["id"],
                         F.create_shift_payload("2026-06-01T16:00:00Z", "2026-06-01T20:00:00Z"), OP),
        201,
    )
    assert data["status"] == "SCHEDULED", f"adjacent shift should be admitted, got {data['status']}"


# =========================================================================
# Queue A — resource_temporal_overlap (depot bay buffered capacity)
# =========================================================================
def test_bay_buffered_capacity_overlap_rejected(api):
    """PRD §3.4: "A new reservation is rejected when, across its own buffered closed
    window, the depot already has a number of `ACTIVE` reservations equal to `bay_count`
    whose buffered windows overlap it — that is, when admitting it would mean more
    concurrently occupied bays than the depot has; this aggregate-capacity conflict is
    rejected with `ERR_NO_BAY_AVAILABLE`."

    bay_count=1, cleanup_buffer=30. Existing [10:00,11:00] buffers to 11:30; a new
    [11:15,12:00] overlaps the buffered block.

    Design: Difficulty/resource_temporal_overlap/depot_bay_buffered_capacity_overlap_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    plan = create_plan()
    member = create_member(plan["id"])
    depot = create_depot(bay_count=1, cleanup_buffer_minutes=30)
    call_a = create_call(member["id"], "TOW")
    call_b = create_call(member["id"], "TOW")
    validate_success(
        api.create_bay_reservation(depot["id"],
                                   F.create_bay_reservation_payload(call_a["id"],
                                                                    "2026-06-01T10:00:00Z",
                                                                    "2026-06-01T11:00:00Z"), OP),
        201,
    )
    resp = api.create_bay_reservation(depot["id"],
                                      F.create_bay_reservation_payload(call_b["id"],
                                                                       "2026-06-01T11:15:00Z",
                                                                       "2026-06-01T12:00:00Z"), OP)
    validate_error(resp, ApiErrorId.ERR_NO_BAY_AVAILABLE.value)


def test_bay_capacity_block_extends_by_cleanup_buffer(api):
    """PRD §3.4: "The effective block on a bay runs from `reserved_from` through
    `reserved_until` plus the depot's `cleanup_buffer_minutes`."

    A second assertion of the buffered-window geometry: with bay_count=1 and a 30-minute
    buffer, a window starting at 11:15 (inside the 11:30 buffered block) is rejected.

    Design: Difficulty/resource_temporal_overlap/depot_bay_buffered_capacity_overlap_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    plan = create_plan()
    member = create_member(plan["id"])
    depot = create_depot(bay_count=1, cleanup_buffer_minutes=30)
    call_a = create_call(member["id"], "TOW")
    call_b = create_call(member["id"], "TOW")
    validate_success(
        api.create_bay_reservation(depot["id"],
                                   F.create_bay_reservation_payload(call_a["id"],
                                                                    "2026-06-01T10:00:00Z",
                                                                    "2026-06-01T11:00:00Z"), OP),
        201,
    )
    resp = api.create_bay_reservation(depot["id"],
                                      F.create_bay_reservation_payload(call_b["id"],
                                                                       "2026-06-01T11:15:00Z",
                                                                       "2026-06-01T12:00:00Z"), OP)
    validate_error(resp, ApiErrorId.ERR_NO_BAY_AVAILABLE.value)


# =========================================================================
# Queue A — compensating_invariant (bay occupancy reserve -> release -> 0)
# =========================================================================
def test_reserve_then_release_returns_occupied_bays_to_zero(api):
    """PRD §3.4: "Releasing a reservation moves it from `ACTIVE` to `RELEASED` and
    decrements the depot's `occupied_bays` by one, freeing the bay; the release
    advances the reservation's `version`."

    bay_count=2, buffer=0. One ACTIVE reservation makes occupied_bays=1; releasing it
    returns occupied_bays to 0.

    Design: Difficulty/compensating_invariant/bay_occupancy_invariant_reserve_then_release_returns_to_zero
    """
    ctx = setup_depot_with_reservation(bay_count=2, cleanup_buffer_minutes=0)
    resv = validate_success(api.release_bay_reservation(ctx["depot"]["id"], ctx["reservation"]["id"], OP))
    assert resv["status"] == "RELEASED", f"expected RELEASED, got {resv['status']}"
    depot = validate_success(api.get_depot(ctx["depot"]["id"], OP))
    assert depot["occupied_bays"] == 0, f"occupied_bays should return to 0, got {depot['occupied_bays']}"


def test_reserve_increments_then_release_compensates_occupancy(api):
    """PRD §3.4: "Admitting a reservation increments the depot's `occupied_bays` by
    one."

    The forward action: an ACTIVE reservation sets occupied_bays to 1 before the
    compensating release returns it to 0.

    Design: Difficulty/compensating_invariant/bay_occupancy_invariant_reserve_then_release_returns_to_zero
    """
    ctx = setup_depot_with_reservation(bay_count=2, cleanup_buffer_minutes=0)
    depot_before = validate_success(api.get_depot(ctx["depot"]["id"], OP))
    assert depot_before["occupied_bays"] == 1, \
        f"reserve should set occupied_bays to 1, got {depot_before['occupied_bays']}"
    validate_success(api.release_bay_reservation(ctx["depot"]["id"], ctx["reservation"]["id"], OP))
    depot_after = validate_success(api.get_depot(ctx["depot"]["id"], OP))
    assert depot_after["occupied_bays"] == 0


# =========================================================================
# Queue A — combinatorial_formula (multi-factor ranking, TOW tie-break)
# =========================================================================
def test_dispatch_candidate_tow_tiebreak_prefers_fewer_capabilities(api):
    """PRD §3.6: "The third key applies only when the call's `service_type` is `TOW`:
    among providers still tied, those with fewer entries in their `capabilities` list
    are preferred, favoring specialists for tows; for non-tow calls this key is skipped
    entirely."

    Two equally-rated (4.5), equally-distant (both at (0,0.05)) TOW providers: the
    specialist with [TOW] (len 1, registered first) ranks ahead of [TOW,JUMP] (len 2).

    Design: Difficulty/combinatorial_formula/dispatch_candidate_multifactor_ranking_with_tow_conditional_tiebreak
    """
    ctx = make_call_for_candidates(service_type="TOW")
    spec = add_provider_with_shift(0.0, 0.05, ["TOW"], 4.5, "Spec Tow")
    gen = add_provider_with_shift(0.0, 0.05, ["TOW", "JUMP"], 4.5, "Gen Tow")
    data, meta = validate_paginated(api.get_dispatch_candidates(ctx["call"]["id"], OP))
    assert len(data) == 2, f"both providers should be eligible, got {len(data)}"
    assert data[0]["id"] == spec["id"], "specialist ([TOW]) should rank first on the TOW tie-break"
    assert data[1]["id"] == gen["id"], "generalist ([TOW,JUMP]) should rank second"


def test_dispatch_candidate_ranking_returns_full_eligible_pool(api):
    """PRD §3.6: "The eligible providers are then ranked by a sequence of keys applied
    in order. The first key is `rating`, highest first."

    A second assertion of the ranked-pool output: both equally-rated TOW providers
    appear, with the fewer-capability specialist ordered ahead of the generalist.

    Design: Difficulty/combinatorial_formula/dispatch_candidate_multifactor_ranking_with_tow_conditional_tiebreak
    """
    ctx = make_call_for_candidates(service_type="TOW")
    spec = add_provider_with_shift(0.0, 0.05, ["TOW"], 4.5, "Spec Tow")
    gen = add_provider_with_shift(0.0, 0.05, ["TOW", "JUMP"], 4.5, "Gen Tow")
    data, meta = validate_paginated(api.get_dispatch_candidates(ctx["call"]["id"], OP))
    ids = [p["id"] for p in data]
    assert ids == [spec["id"], gen["id"]], f"expected [spec, gen] order, got {ids}"
