"""Dispatch routing, double-booking, daily capacity, the priority SLA, and visit windows.

Covers Difficulty queue: resource_temporal_overlap (double-booked minute-grain + daily
capacity date-grain), boundary_precision_check (SLA inclusive boundary), and the
referential-beats-safety priority pair on refrigerant posting; plus corner validations
and state-machine transitions on visits.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    TEST_USERS,
    make_technician_headers,
    dispatch_payload,
    create_service_visit_payload,
    create_refrigerant_log_payload,
    ApiErrorId,
    setup_active_membership_with_tech,
    setup_active_membership_with_equipment_and_tech,
    create_and_activate_membership,
    book_visit,
    dispatch_visit,
    get_visit,
)

ADMIN = TEST_USERS["contract_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty / resource_temporal_overlap
# ===========================================================================
def test_dispatch_overlapping_window_double_booked(api):
    """PRD §3.6: "the dispatched window may not overlap, under half-open interval
    semantics, any other non-terminal visit already in `DISPATCHED`, `EN_ROUTE`, or
    `ON_SITE` status for the same technician."
    PRD §3.6: "any genuine intersection is rejected with `ERR_TECH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/tech_double_booked_half_open_minute_grain_overlap
    """
    ctx = setup_active_membership_with_tech(tech_overrides={"daily_visit_capacity": 5})
    tech_id = ctx["technician"]["id"]
    va = book_visit(ctx["membership"], window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T11:00:00Z")
    dispatch_visit(va["id"], tech_id)
    vb = book_visit(ctx["membership"], window_start="2026-07-02T10:00:00Z", window_end="2026-07-02T12:00:00Z")
    # vb's [10:00, 12:00) genuinely intersects va's already-dispatched [09:00, 11:00).
    validate_error(
        api.dispatch_service_visit(vb["id"], dispatch_payload(tech_id), DISPATCHER),
        ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value,
    )


def test_dispatch_touching_windows_do_not_overlap(api):
    """PRD §3.6: "Half-open means the interval runs from `window_start` up to but not
    including `window_end`, so two visits whose endpoints merely touch (one ending exactly
    when the next begins) do not overlap; any genuine intersection is rejected with
    `ERR_TECH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/tech_double_booked_half_open_minute_grain_overlap
    """
    ctx = setup_active_membership_with_tech(tech_overrides={"daily_visit_capacity": 5})
    tech_id = ctx["technician"]["id"]
    va = book_visit(ctx["membership"], window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T11:00:00Z")
    dispatch_visit(va["id"], tech_id)
    vb = book_visit(ctx["membership"], window_start="2026-07-02T11:00:00Z", window_end="2026-07-02T13:00:00Z")
    # vb begins exactly when va ends -> touching, not overlapping -> dispatch succeeds.
    dispatched = validate_success(api.dispatch_service_visit(vb["id"], dispatch_payload(tech_id), DISPATCHER), 200)
    assert dispatched["status"] == "DISPATCHED", "touching endpoints do not double-book"


def test_daily_capacity_exceeded_same_calendar_date(api):
    """PRD §3.6: "a technician may carry no more `SCHEDULED` plus `DISPATCHED` visits whose
    `window_start` falls on a given UTC calendar date than the technician's
    `daily_visit_capacity` allows."
    PRD §3.6: "This capacity check buckets visits by calendar date rather than by
    minute-level interval, and it is applied at booking, at reschedule, and at dispatch;
    exceeding the cap is rejected with `ERR_TECH_DAILY_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/tech_daily_capacity_calendar_date_grain_aggregate_overlap
    """
    ctx = setup_active_membership_with_tech(tech_overrides={"daily_visit_capacity": 1})
    tech_id = ctx["technician"]["id"]
    va = book_visit(ctx["membership"], window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T10:00:00Z")
    dispatch_visit(va["id"], tech_id)
    # Second visit on the SAME date (non-overlapping minutes) names the tech up front; the
    # date-grain capacity (1) is already met for 2026-07-02.
    payload = create_service_visit_payload(
        ctx["membership"]["id"], ctx["membership"]["version"],
        window_start="2026-07-02T14:00:00Z", window_end="2026-07-02T15:00:00Z",
        technician_id=tech_id,
    )
    validate_error(api.create_service_visit(payload, DISPATCHER), ApiErrorId.ERR_TECH_DAILY_CAPACITY.value)


def test_daily_capacity_visits_on_distinct_dates_allowed(api):
    """PRD §3.6: "a technician may carry no more `SCHEDULED` plus `DISPATCHED` visits whose
    `window_start` falls on a given UTC calendar date than the technician's
    `daily_visit_capacity` allows. This capacity check buckets visits by calendar date
    rather than by minute-level interval."

    Design: Difficulty/resource_temporal_overlap/tech_daily_capacity_calendar_date_grain_aggregate_overlap
    """
    ctx = setup_active_membership_with_tech(tech_overrides={"daily_visit_capacity": 1})
    tech_id = ctx["technician"]["id"]
    va = book_visit(ctx["membership"], window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T10:00:00Z")
    dispatch_visit(va["id"], tech_id)
    # A second visit on a DIFFERENT calendar date (2026-07-03) is within the per-date cap.
    payload = create_service_visit_payload(
        ctx["membership"]["id"], ctx["membership"]["version"],
        window_start="2026-07-03T09:00:00Z", window_end="2026-07-03T10:00:00Z",
        technician_id=tech_id,
    )
    visit_b = validate_success(api.create_service_visit(payload, DISPATCHER), 201)
    assert visit_b["status"] == "SCHEDULED", "distinct-date visit does not exceed the daily cap"


# ===========================================================================
# Difficulty / boundary_precision_check — SLA inclusive boundary
# ===========================================================================
def test_priority_sla_met_at_exactly_response_hours(api):
    """PRD §3.6: "sets `sla_met` to true when that latency is less than or equal to the
    plan's `sla_response_hours`, and to false when the latency is greater. The boundary is
    inclusive: a latency exactly equal to `sla_response_hours` counts as met."

    Design: Difficulty/boundary_precision_check/sla_inclusive_boundary_exactly_four_hours_is_met
    """
    ctx = create_and_activate_membership(plan_overrides={"sla_response_hours": 4})
    # requested 09:00, window_start 13:00 => latency exactly 4h => met (inclusive).
    visit = book_visit(
        ctx["membership"], visit_kind="PRIORITY",
        requested_at="2026-07-01T09:00:00Z",
        window_start="2026-07-01T13:00:00Z", window_end="2026-07-01T15:00:00Z",
    )
    assert visit["sla_met"] is True, f"latency exactly 4h <= 4 is met, got sla_met={visit['sla_met']}"


def test_priority_sla_met_just_under_boundary(api):
    """PRD §3.6: "sets `sla_met` to true when that latency is less than or equal to the
    plan's `sla_response_hours`, and to false when the latency is greater."

    Design: Difficulty/boundary_precision_check/sla_inclusive_boundary_exactly_four_hours_is_met
    """
    ctx = create_and_activate_membership(plan_overrides={"sla_response_hours": 4})
    # requested 09:00, window_start 12:59 => latency 3h59m < 4h => met.
    visit = book_visit(
        ctx["membership"], visit_kind="PRIORITY",
        requested_at="2026-07-01T09:00:00Z",
        window_start="2026-07-01T12:59:00Z", window_end="2026-07-01T15:00:00Z",
    )
    assert visit["sla_met"] is True, f"latency 3h59m < 4 is met, got sla_met={visit['sla_met']}"


def test_priority_sla_breach_just_over_boundary(api):
    """PRD §3.6: "sets `sla_met` to true when that latency is less than or equal to the
    plan's `sla_response_hours`, and to false when the latency is greater."
    PRD §3.6: "A breach does not block the booking — the visit is still created with
    `sla_met` recorded as false."

    Design: Corner/calculations/sla_breach_variant_records_false_does_not_reject
    """
    ctx = create_and_activate_membership(plan_overrides={"sla_response_hours": 4})
    payload = create_service_visit_payload(
        ctx["membership"]["id"], ctx["membership"]["version"],
        visit_kind="PRIORITY",
        requested_at="2026-07-01T09:00:00Z",
        window_start="2026-07-01T13:01:00Z", window_end="2026-07-01T15:00:00Z",
    )
    visit = validate_success(api.create_service_visit(payload, DISPATCHER), 201)
    assert visit["sla_met"] is False, f"latency 4h1m > 4 is a breach, got sla_met={visit['sla_met']}"


# ===========================================================================
# Difficulty / priority_pair_validation_conflict — referential beats safety
# ===========================================================================
def test_refrigerant_post_to_non_onsite_visit_fails_state_before_cert(api):
    """PRD §2.9: "The remaining business rules — referential, safety, temporal, fiscal,
    and the stale-version guard — are described alongside the workflows they protect in
    Section 3."
    PRD §3.7: "The visit must be `ON_SITE` when the log is posted, or the post is rejected
    with `ERR_MEMBERSHIP_NOT_ACTIVE` (the same code guards both
    visit-create-against-inactive-membership and refrigerant/part posting against a
    non-`ON_SITE` visit)."

    Design: Difficulty/priority_pair_validation_conflict/refrigerant_post_visit_state_referential_beats_cert_safety
    """
    # Non-EPA tech, visit only DISPATCHED (not ON_SITE): the referential visit-state guard
    # is ordered before the safety cert guard, so the rejection is ERR_MEMBERSHIP_NOT_ACTIVE.
    ctx = setup_active_membership_with_equipment_and_tech(
        equipment_overrides={"refrigerant_type": "R410A"},
        tech_overrides={"epa_certified": False},
    )
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    dispatch_visit(visit["id"], ctx["technician"]["id"])
    validate_error(
        api.post_refrigerant_log(visit["id"], create_refrigerant_log_payload(ctx["equipment"]["id"], "ADD", 100),
                                 make_technician_headers(ctx["technician"]["id"])),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value,
    )


def test_refrigerant_post_onsite_by_non_certified_tech_fails_cert(api):
    """PRD §3.7: "Posting refrigerant is a regulated activity: the posting technician must
    hold EPA 608 certification, that is the assigned technician's `epa_certified` flag must
    be true, or the post is rejected with `ERR_TECH_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/refrigerant_post_visit_state_referential_beats_cert_safety
    """
    # Same non-EPA tech, but now the visit is ON_SITE so the higher-priority visit-state
    # referential check passes; the lower-priority safety cert check is reached and fires.
    ctx = setup_active_membership_with_equipment_and_tech(
        equipment_overrides={"refrigerant_type": "R410A"},
        tech_overrides={"epa_certified": False},
    )
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    tech_id = ctx["technician"]["id"]
    dispatch_visit(visit["id"], tech_id)
    tech_headers = make_technician_headers(tech_id)
    validate_success(api.depart_service_visit(visit["id"], tech_headers), 200)
    validate_success(api.arrive_service_visit(visit["id"], tech_headers), 200)  # now ON_SITE
    validate_error(
        api.post_refrigerant_log(visit["id"], create_refrigerant_log_payload(ctx["equipment"]["id"], "ADD", 100),
                                 tech_headers),
        ApiErrorId.ERR_TECH_NOT_CERTIFIED.value,
    )


# ===========================================================================
# Corner / validations — windows
# ===========================================================================
def test_visit_window_end_not_after_start_rejected(api):
    """PRD §3.5: "The window itself must be well-formed: `window_end` must be strictly
    later than `window_start`, both at booking and at reschedule, or the request fails
    with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window_end_before_start_rejected
    """
    ctx = create_and_activate_membership()
    payload = create_service_visit_payload(
        ctx["membership"]["id"], ctx["membership"]["version"],
        window_start="2026-07-02T11:00:00Z", window_end="2026-07-02T09:00:00Z",
    )
    validate_error(api.create_service_visit(payload, DISPATCHER), ApiErrorId.ERR_INVALID_WINDOW.value)


def test_priority_visit_requested_after_window_start_rejected(api):
    """PRD §3.5: "A priority booking carries an additional temporal rule — its
    `requested_at` may not fall after its `window_start` (one cannot book a window that
    begins before the request instant) — and a violation of this also yields
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/priority_visit_requested_after_window_start_invalid_window
    """
    ctx = create_and_activate_membership()
    payload = create_service_visit_payload(
        ctx["membership"]["id"], ctx["membership"]["version"],
        visit_kind="PRIORITY",
        requested_at="2026-07-02T12:00:00Z",
        window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T11:00:00Z",
    )
    validate_error(api.create_service_visit(payload, DISPATCHER), ApiErrorId.ERR_INVALID_WINDOW.value)


# ===========================================================================
# Corner / state_machines — visit transitions
# ===========================================================================
def test_recall_dispatched_visit_returns_to_scheduled_and_clears_tech(api):
    """PRD §3.5: "A dispatched visit can be recalled by a `Dispatcher`, a
    `DISPATCHED → SCHEDULED` revert that clears the assigned `technician_id` and returns
    the visit to the unassigned pool."

    Design: Corner/state_machines/visit_recall_returns_to_scheduled_and_clears_tech
    """
    ctx = setup_active_membership_with_tech()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    dispatch_visit(visit["id"], ctx["technician"]["id"])
    recalled = validate_success(api.recall_service_visit(visit["id"], DISPATCHER), 200)
    assert recalled["status"] == "SCHEDULED", f"recall returns to SCHEDULED, got {recalled['status']}"
    assert recalled["technician_id"] is None, f"recall clears technician_id, got {recalled['technician_id']!r}"


def test_depart_scheduled_visit_rejected(api):
    """PRD §3.7: "From `DISPATCHED` the assigned technician departs
    (`DISPATCHED → EN_ROUTE`), then arrives (`EN_ROUTE → ON_SITE`); each step requires the
    acting technician's id to equal the visit's `technician_id`."
    PRD §2.9: "where a state transition is involved the system confirms the target
    resource currently sits in a state from which that transition is defined, rejecting
    otherwise with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/depart_from_scheduled_visit_returns_invalid_state
    """
    ctx = setup_active_membership_with_tech()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")  # still SCHEDULED, never dispatched
    validate_error(
        api.depart_service_visit(visit["id"], make_technician_headers(ctx["technician"]["id"])),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_cancel_completed_visit_terminal_lockdown(api):
    """PRD §3.5: "A visit's `status` advances through `SCHEDULED`, `DISPATCHED`,
    `EN_ROUTE`, `ON_SITE`, and `COMPLETED`, with `CANCELLED` and `NO_SHOW` as alternative
    terminal outcomes."
    PRD §2.9: "where a state transition is involved the system confirms the target
    resource currently sits in a state from which that transition is defined, rejecting
    otherwise with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_visit_terminal_lockdown
    """
    from test_helpers import setup_visit_on_site
    ctx = setup_visit_on_site(with_equipment=False)
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    validate_success(api.complete_service_visit(ctx["visit"]["id"], tech_headers), 200)
    validate_error(api.cancel_service_visit(ctx["visit"]["id"], DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)


def test_mark_no_show_before_window_end_rejected(api):
    """PRD §3.5: "A `Dispatcher` may mark a `DISPATCHED` visit as a no-show, a
    `DISPATCHED → NO_SHOW` transition that is permitted only once the current clock has
    reached or passed the visit's `window_end` (the window has elapsed without the
    technician departing)."

    Design: Corner/state_machines/mark_no_show_before_window_end_returns_invalid_state
    """
    ctx = setup_active_membership_with_tech()
    # Clock is pinned at 2026-07-01; the visit window is 2026-07-02 09:00-11:00 (future).
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL",
                       window_start="2026-07-02T09:00:00Z", window_end="2026-07-02T11:00:00Z")
    dispatch_visit(visit["id"], ctx["technician"]["id"])
    validate_error(api.mark_no_show_service_visit(visit["id"], DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)
