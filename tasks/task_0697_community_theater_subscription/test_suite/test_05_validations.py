"""Validation, boundary, overlap, cross-entity state, and OCC tests.

Each test exercises a single decisive validation in isolation so the asserted
error_id is uniquely determined by the PRD's stated precedence and rule.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_patron_headers,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]


# ==========================================================================
# Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_taken_and_soldout_seat
# ==========================================================================
def test_taken_and_soldout_seat_reports_already_taken(api):
    """PRD §2.10: "(6) seat and accessibility constraints, covering
    `ERR_SEAT_NOT_IN_VENUE`, `ERR_SEAT_ALREADY_TAKEN`,
    `ERR_ACCESSIBILITY_UNAVAILABLE`, and `ERR_SEAT_NOT_RENEWABLE`".
    PRD §2.10: "(8) fiscal capacity and credit limits, covering
    `ERR_PERFORMANCE_SOLD_OUT` and `ERR_INSUFFICIENT_CREDIT`".
    PRD §2.10: "Earlier checks always mask later ones".
    PRD §3.5: "must not already carry a non-`VOID` ticket on that performance (else
    `ERR_SEAT_ALREADY_TAKEN`)".

    On a one-seat ON_SALE performance whose only seat is held+paid (available=0), a
    second hold on that same seat violates both priority-6 occupancy and priority-8
    sold-out; the earlier priority-6 ERR_SEAT_ALREADY_TAKEN wins.

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_taken_and_soldout_seat
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "H"}])
    patron_a = th.create_patron(email="pa@example.com")
    patron_b = th.create_patron(email="pb@example.com")
    seat = ctx["seats"][0]
    pa = make_patron_headers(patron_a["id"])
    t1 = th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron_a["id"],
                               ctx["performance_version"], headers=pa)
    get_success_data(api.pay_ticket(t1["id"], pa))
    pv = th.get_performance_version(ctx["performance"]["id"])
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat["id"], patron_b["id"], "SINGLE", pv),
        make_patron_headers(patron_b["id"]))
    validate_error(resp, ApiErrorId.ERR_SEAT_ALREADY_TAKEN.value)


def test_taken_seat_is_also_soldout_yet_taken_error_wins(api):
    """PRD §3.5: "may not exceed `available_seat_count` (else
    `ERR_PERFORMANCE_SOLD_OUT`)".
    PRD §3.5: "must not already carry a non-`VOID` ticket on that performance (else
    `ERR_SEAT_ALREADY_TAKEN`)".

    On the one-seat performance the held+paid seat drives available_seat_count to 0
    (so the priority-8 sold-out condition is genuinely live), yet a second hold on
    that seat is rejected with the priority-6 ERR_SEAT_ALREADY_TAKEN, not the
    sold-out code.

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_taken_and_soldout_seat
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "H"}])
    patron_a = th.create_patron(email="pa2@example.com")
    patron_b = th.create_patron(email="pb2@example.com")
    seat = ctx["seats"][0]
    pa = make_patron_headers(patron_a["id"])
    t1 = th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron_a["id"],
                               ctx["performance_version"], headers=pa)
    get_success_data(api.pay_ticket(t1["id"], pa))
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["available_seat_count"] == 0, "sold-out condition must be live"
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat["id"], patron_b["id"], "SINGLE", perf["version"]),
        make_patron_headers(patron_b["id"]))
    err = validate_error(resp, ApiErrorId.ERR_SEAT_ALREADY_TAKEN.value)
    assert err["error_id"] == ApiErrorId.ERR_SEAT_ALREADY_TAKEN.value


# ==========================================================================
# Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_notonsale_wrongvenue_hold
# ==========================================================================
def test_notonsale_and_wrongvenue_reports_not_on_sale(api):
    """PRD §2.10: "(4) that the target resource is in a state from which the
    requested transition is defined ... (5) the time-window gates of §2.5; (6) seat
    and accessibility constraints".
    PRD §3.5: "A single-ticket hold is only valid while the performance is
    `ON_SALE` (else `ERR_PERFORMANCE_NOT_ON_SALE`)".

    A hold on a SCHEDULED (not ON_SALE) performance that also names a seat from a
    different venue violates priority-5 on-sale and priority-6 seat-in-venue; the
    earlier ERR_PERFORMANCE_NOT_ON_SALE wins.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_notonsale_wrongvenue_hold
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue_a = th.create_venue(name="Hall-A")
    th.create_seat(venue_a["id"], row_label="I", seat_number=1, price_tier="STANDARD")
    venue_b = th.create_venue(name="Hall-B")
    seat_b = th.create_seat(venue_b["id"], row_label="I", seat_number=1, price_tier="STANDARD")
    perf = th.create_performance(production["id"], venue_a["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    perf = get_success_data(api.schedule_performance(perf["id"], ADMIN))  # SCHEDULED, not ON_SALE
    patron = th.create_patron(email="nv@example.com")
    resp = api.create_ticket(th.create_ticket_payload(
        perf["id"], seat_b["id"], patron["id"], "SINGLE", perf["version"]),
        make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_ON_SALE.value)


def test_notonsale_gate_decisive_even_with_in_venue_seat(api):
    """PRD §3.5: "A single-ticket hold is only valid while the performance is
    `ON_SALE` (else `ERR_PERFORMANCE_NOT_ON_SALE`)".

    A hold on a SCHEDULED (not ON_SALE) performance naming a valid in-venue seat is
    still rejected with ERR_PERFORMANCE_NOT_ON_SALE — confirming the priority-5
    temporal gate is decisive on its own, ahead of any seat constraint.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_notonsale_wrongvenue_hold
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue = th.create_venue(name="Hall-Sched")
    seat = th.create_seat(venue["id"], row_label="I", seat_number=1, price_tier="STANDARD")
    perf = th.create_performance(production["id"], venue["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    perf = get_success_data(api.schedule_performance(perf["id"], ADMIN))  # SCHEDULED only
    patron = th.create_patron(email="sched@example.com")
    resp = api.create_ticket(th.create_ticket_payload(
        perf["id"], seat["id"], patron["id"], "SINGLE", perf["version"]),
        make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_ON_SALE.value)


# ==========================================================================
# Difficulty/boundary_precision_check/donor_level_threshold_at_exactly_25000
# ==========================================================================
def test_donor_friend_at_exactly_25000(api):
    """PRD §3.6: "otherwise `FRIEND` when it is at least 25000 cents, and
    otherwise `NONE`."
    PRD §3.6: "The boundaries are inclusive at the lower edge, so exactly 25000
    cents qualifies as `FRIEND` while 24999 cents remains `NONE`."

    A lifetime FULFILLED total of exactly 25000 yields donor_level=FRIEND.

    Design: Difficulty/boundary_precision_check/donor_level_threshold_at_exactly_25000
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron(email="d25000@example.com")
    donation = get_success_data(api.create_donation(
        th.create_donation_payload(patron["id"], 25000), AGENT))
    data = validate_success(api.fulfill_donation(donation["id"], AGENT), 200)
    assert data["status"] == "FULFILLED"
    patron_after = get_success_data(api.get_patron(patron["id"], ADMIN))
    assert patron_after["lifetime_donation_cents"] == 25000
    assert patron_after["donor_level"] == "FRIEND", (
        f"exactly 25000 must be FRIEND, got {patron_after['donor_level']}")


def test_donor_none_just_below_25000(api):
    """PRD §3.6: "The boundaries are inclusive at the lower edge, so exactly 25000
    cents qualifies as `FRIEND` while 24999 cents remains `NONE`."

    A lifetime FULFILLED total of 24999 (one below the boundary) remains NONE.

    Design: Difficulty/boundary_precision_check/donor_level_threshold_at_exactly_25000
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron(email="d24999@example.com")
    donation = get_success_data(api.create_donation(
        th.create_donation_payload(patron["id"], 24999), AGENT))
    get_success_data(api.fulfill_donation(donation["id"], AGENT))
    patron_after = get_success_data(api.get_patron(patron["id"], ADMIN))
    assert patron_after["lifetime_donation_cents"] == 24999
    assert patron_after["donor_level"] == "NONE", (
        f"24999 must remain NONE, got {patron_after['donor_level']}")


# ==========================================================================
# Difficulty/boundary_precision_check/performance_soldout_at_zero_available
# ==========================================================================
def test_hold_rejected_when_available_is_zero(api):
    """PRD §3.5: "may not exceed `available_seat_count` (else
    `ERR_PERFORMANCE_SOLD_OUT`)".
    PRD §2.8: "`available_seat_count` is the performance `capacity` minus
    `held_seat_count` minus `sold_seat_count`, and is never allowed to fall below
    zero (it is floored at zero)".

    In a two-seat venue both seats held so available_seat_count==0; the next hold
    is rejected with ERR_PERFORMANCE_SOLD_OUT.

    The rejected hold must target a *free* seat: capacity is the seat count
    snapshotted at schedule time (PRD §3.2), so an extra seat added to the venue
    after scheduling is free (carries no ticket) yet beyond the frozen capacity.
    Holding it trips only the priority-8 sold-out check, not the priority-6
    occupancy check (PRD §2.10 priority order; "Earlier checks always mask later
    ones") — a hold on an already-held seat would instead surface
    ERR_SEAT_ALREADY_TAKEN.

    Design: Difficulty/boundary_precision_check/performance_soldout_at_zero_available
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "J", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "J", "seat_number": 2}])
    patron = th.create_patron(email="soldout@example.com")
    seat1, seat2 = ctx["seats"]
    th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron["id"],
                          ctx["performance_version"], headers=AGENT)
    pv1 = th.get_performance_version(ctx["performance"]["id"])
    th.hold_single_ticket(ctx["performance"]["id"], seat2["id"], patron["id"], pv1, headers=AGENT)
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["available_seat_count"] == 0
    pv2 = perf["version"]
    # A free seat added after the capacity snapshot: not yet ticketed, so the
    # occupancy check passes and the sold-out (capacity) check is the one that fires.
    free_seat = th.create_seat(ctx["venue"]["id"], row_label="J", seat_number=3,
                               price_tier="STANDARD")
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], free_seat["id"], patron["id"], "SINGLE", pv2), AGENT)
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_SOLD_OUT.value)


def test_available_drops_to_zero_at_capacity_boundary(api):
    """PRD §2.8: "`available_seat_count` is the performance `capacity` minus
    `held_seat_count` minus `sold_seat_count`, and is never allowed to fall below
    zero (it is floored at zero)".

    In the two-seat venue, holding both seats drives available_seat_count to exactly
    the zero boundary — the empty-inventory edge that the sold-out rejection guards.

    Design: Difficulty/boundary_precision_check/performance_soldout_at_zero_available
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "J", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "J", "seat_number": 2}])
    patron = th.create_patron(email="boundary@example.com")
    seat1, seat2 = ctx["seats"]
    th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron["id"],
                          ctx["performance_version"], headers=AGENT)
    pv1 = th.get_performance_version(ctx["performance"]["id"])
    th.hold_single_ticket(ctx["performance"]["id"], seat2["id"], patron["id"], pv1, headers=AGENT)
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["available_seat_count"] == 0, (
        f"available must hit the zero boundary, got {perf['available_seat_count']}")
    assert perf["held_seat_count"] == 2


# ==========================================================================
# Difficulty/resource_temporal_overlap/seat_point_occupancy_collision_on_performance
# ==========================================================================
def test_second_hold_same_seat_rejected(api):
    """PRD §3.5: "must not already carry a non-`VOID` ticket on that performance
    (else `ERR_SEAT_ALREADY_TAKEN`)".

    A seat admits at most one non-VOID ticket per performance: a second hold on the
    same (seat, performance) is rejected with ERR_SEAT_ALREADY_TAKEN.

    Design: Difficulty/resource_temporal_overlap/seat_point_occupancy_collision_on_performance
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "M", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "M", "seat_number": 2}])
    patron_a = th.create_patron(email="ma@example.com")
    patron_b = th.create_patron(email="mb@example.com")
    seat = ctx["seats"][0]
    th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron_a["id"],
                          ctx["performance_version"], headers=AGENT)
    pv1 = th.get_performance_version(ctx["performance"]["id"])
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat["id"], patron_b["id"], "SINGLE", pv1), AGENT)
    validate_error(resp, ApiErrorId.ERR_SEAT_ALREADY_TAKEN.value)


def test_different_free_seat_holds_while_other_is_taken(api):
    """PRD §3.5: "must not already carry a non-`VOID` ticket on that performance
    (else `ERR_SEAT_ALREADY_TAKEN`)".

    Point-collision is per-seat: with seat 1 already held, a hold on the distinct
    free seat 2 on the same performance succeeds — the occupancy check fires only on
    the exact (seat, performance) point, not the whole performance.

    Design: Difficulty/resource_temporal_overlap/seat_point_occupancy_collision_on_performance
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "M", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "M", "seat_number": 2}])
    patron_a = th.create_patron(email="ma2@example.com")
    patron_b = th.create_patron(email="mb2@example.com")
    seat1, seat2 = ctx["seats"]
    th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron_a["id"],
                          ctx["performance_version"], headers=AGENT)
    pv1 = th.get_performance_version(ctx["performance"]["id"])
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat2["id"], patron_b["id"], "SINGLE", pv1), AGENT)
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "HELD"
    assert data["seat_id"] == seat2["id"]


# ==========================================================================
# Difficulty/resource_temporal_overlap/performance_aggregate_capacity_overlap
# ==========================================================================
def test_aggregate_capacity_full_rejects_further_hold(api):
    """PRD §2.8: "`available_seat_count` is the performance `capacity` minus
    `held_seat_count` minus `sold_seat_count`".
    PRD §3.5: "may not exceed `available_seat_count` (else
    `ERR_PERFORMANCE_SOLD_OUT`)".

    In a one-seat venue (capacity=1) whose only seat is held (available=0), a
    further hold on a *free* seat is rejected with ERR_PERFORMANCE_SOLD_OUT.

    Capacity is the seat count snapshotted at schedule time (PRD §3.2), so a seat
    added to the venue after scheduling is free (carries no ticket) yet beyond the
    frozen capacity-1 ceiling. Holding it trips only the priority-8 sold-out check,
    not the priority-6 occupancy check (PRD §2.10 priority order; "Earlier checks
    always mask later ones") — re-holding the already-held seat would instead
    surface ERR_SEAT_ALREADY_TAKEN.

    Design: Difficulty/resource_temporal_overlap/performance_aggregate_capacity_overlap
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "N"}])
    patron = th.create_patron(email="agg@example.com")
    seat = ctx["seats"][0]
    th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                          ctx["performance_version"], headers=AGENT)
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["capacity"] == 1
    assert perf["available_seat_count"] == 0
    # A free seat added after the capacity snapshot: not yet ticketed, so the
    # occupancy check passes and the sold-out (capacity) check is the one that fires.
    free_seat = th.create_seat(ctx["venue"]["id"], row_label="N", seat_number=2,
                               price_tier="STANDARD")
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], free_seat["id"], patron["id"], "SINGLE", perf["version"]), AGENT)
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_SOLD_OUT.value)


def test_capacity_snapshot_from_one_seat_venue(api):
    """PRD §3.2: "at that moment the system snapshots `capacity` as the count of
    seats in the venue and sets `available_seat_count` equal to that capacity."

    A one-seat venue snapshots capacity=1 at schedule time, and once that single
    pooled slot is held the aggregate is full (available=0) — the pooled
    capacity ceiling that the sold-out rejection enforces.

    Design: Difficulty/resource_temporal_overlap/performance_aggregate_capacity_overlap
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "N"}])
    perf_before = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf_before["capacity"] == 1, f"capacity snapshot must be 1, got {perf_before['capacity']}"
    patron = th.create_patron(email="agg2@example.com")
    seat = ctx["seats"][0]
    th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                          ctx["performance_version"], headers=AGENT)
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["available_seat_count"] == 0, "pooled aggregate must be full"


# ==========================================================================
# Difficulty/cross_entity_state_dependency/performance_schedule_requires_production_announced
# ==========================================================================
def test_schedule_rejected_when_production_draft(api):
    """PRD §3.2: "Scheduling the performance, which a `SeasonAdmin` performs,
    advances it from `DRAFT` to `SCHEDULED`, but only if the bound production is
    already `ANNOUNCED` and the bound venue has at least one seat".

    Scheduling while the bound Production is still DRAFT is rejected with
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/performance_schedule_requires_production_announced
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])  # left DRAFT
    venue = th.create_venue()
    th.create_seat(venue["id"], row_label="K", seat_number=1, price_tier="STANDARD")
    perf = th.create_performance(production["id"], venue["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    assert production["status"] == "DRAFT"
    validate_error(api.schedule_performance(perf["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_schedule_succeeds_once_production_announced(api):
    """PRD §3.2: "Scheduling the performance, which a `SeasonAdmin` performs,
    advances it from `DRAFT` to `SCHEDULED`, but only if the bound production is
    already `ANNOUNCED` and the bound venue has at least one seat; at that moment
    the system snapshots `capacity` as the count of seats in the venue".

    The same schedule call that failed while the production was DRAFT succeeds once
    the production is ANNOUNCED — pinning the Performance->Production dependency.

    Design: Difficulty/cross_entity_state_dependency/performance_schedule_requires_production_announced
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    venue = th.create_venue()
    th.create_seat(venue["id"], row_label="K", seat_number=1, price_tier="STANDARD")
    perf = th.create_performance(production["id"], venue["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    th.announce_production(production["id"])
    data = validate_success(api.schedule_performance(perf["id"], ADMIN), 200)
    assert data["status"] == "SCHEDULED"
    assert data["capacity"] == 1


# ==========================================================================
# Corner/validations/ticket_accessibility_service_unavailable_rejected
# ==========================================================================
def test_accessibility_service_not_offered_rejected(api):
    """PRD §3.5: "any requested `accessibility_service` other than `NONE` must be
    present in the production's `accessibility_offered` set (else
    `ERR_ACCESSIBILITY_UNAVAILABLE`)".

    Requesting ASL on a production offering only AUDIO_DESCRIPTION is rejected with
    ERR_ACCESSIBILITY_UNAVAILABLE.

    Design: Corner/validations/ticket_accessibility_service_unavailable_rejected
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "V", "is_accessible": True}],
        accessibility_offered=["AUDIO_DESCRIPTION"])
    patron = th.create_patron(email="acc@example.com")
    seat = ctx["seats"][0]
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat["id"], patron["id"], "SINGLE", ctx["performance_version"],
        accessibility_service="ASL"), make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_UNAVAILABLE.value)


# ==========================================================================
# Corner/validations/ticket_seat_not_in_venue_rejected
# ==========================================================================
def test_seat_not_in_performance_venue_rejected(api):
    """PRD §3.5: "the requested seat must belong to the performance's venue (else
    `ERR_SEAT_NOT_IN_VENUE`)".

    Design: Corner/validations/ticket_seat_not_in_venue_rejected
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue_a = th.create_venue(name="VenueA")
    th.create_seat(venue_a["id"], row_label="W", seat_number=1, price_tier="STANDARD")
    venue_b = th.create_venue(name="VenueB")
    seat_b = th.create_seat(venue_b["id"], row_label="W", seat_number=1, price_tier="STANDARD")
    perf = th.create_performance(production["id"], venue_a["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf["id"], ADMIN))
    perf = get_success_data(api.open_sales(perf["id"], AGENT))
    patron = th.create_patron(email="sniv@example.com")
    resp = api.create_ticket(th.create_ticket_payload(
        perf["id"], seat_b["id"], patron["id"], "SINGLE", perf["version"]),
        make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_IN_VENUE.value)


# ==========================================================================
# Corner/validations/exchange_target_seat_mismatch_rejected
# ==========================================================================
def test_exchange_target_seat_mismatch_rejected(api):
    """PRD §3.7: "the target seat to belong to the target performance's venue
    (otherwise `ERR_TARGET_SEAT_MISMATCH`)".

    An exchange whose target_seat lives in a venue other than the target
    performance's venue is rejected with ERR_TARGET_SEAT_MISMATCH.

    Design: Corner/validations/exchange_target_seat_mismatch_rejected
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue_a = th.create_venue(name="MV-A")
    seat_a1 = th.create_seat(venue_a["id"], row_label="Y", seat_number=1, price_tier="STANDARD")
    th.create_seat(venue_a["id"], row_label="Y", seat_number=2, price_tier="STANDARD")
    venue_b = th.create_venue(name="MV-B")
    seat_b1 = th.create_seat(venue_b["id"], row_label="Y", seat_number=1, price_tier="STANDARD")
    perf1 = th.create_performance(production["id"], venue_a["id"],
                                  starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf1["id"], ADMIN))
    perf1 = get_success_data(api.open_sales(perf1["id"], AGENT))
    perf2 = th.create_performance(production["id"], venue_a["id"],
                                  starts_at="2026-07-02T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf2["id"], ADMIN))
    get_success_data(api.open_sales(perf2["id"], AGENT))
    patron = th.create_patron(email="mismatch@example.com")
    ph = make_patron_headers(patron["id"])
    orig = th.hold_single_ticket(perf1["id"], seat_a1["id"], patron["id"], perf1["version"], headers=ph)
    get_success_data(api.pay_ticket(orig["id"], ph))
    exch = get_success_data(api.create_exchange(
        th.create_exchange_payload(orig["id"], perf2["id"], seat_b1["id"], "PAID_EXCHANGE"), ph))
    validate_error(api.complete_exchange(exch["id"], AGENT), ApiErrorId.ERR_TARGET_SEAT_MISMATCH.value)


# ==========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_performance_version_on_ticket_hold
# ==========================================================================
def test_stale_performance_version_on_hold_rejected(api):
    """PRD §2.7: "a hold request must carry `expected_performance_version`,
    compared against the target `Performance`'s current `version`. If a prior hold
    has legitimately claimed inventory and advanced the performance's `version`
    since the client last observed it, the client's view of `available_seat_count`
    is stale and the new hold is rejected with `ERR_STALE_PERFORMANCE_VERSION`
    (HTTP 412)."

    A second hold carrying the now-stale pre-hold version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_performance_version_on_ticket_hold
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "AD", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "AD", "seat_number": 2}])
    patron = th.create_patron(email="occ@example.com")
    seat1, seat2 = ctx["seats"]
    stale_version = ctx["performance_version"]
    th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron["id"],
                          stale_version, headers=AGENT)
    resp = api.create_ticket(th.create_ticket_payload(
        ctx["performance"]["id"], seat2["id"], patron["id"], "SINGLE", stale_version), AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_PERFORMANCE_VERSION.value)
