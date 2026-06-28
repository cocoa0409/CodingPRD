"""Validation-precedence, cross-entity-dependency, and temporal-overlap tests.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules
`priority_pair_validation_conflict`, `cross_entity_state_dependency`, and
`resource_temporal_overlap`.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_policy_payload,
    create_privacy_consent_payload,
    create_trip_payload,
    create_trip_event_payload,
    create_statement_payload,
    TEST_USERS,
    set_clock,
    create_rate_plan,
    create_driver,
    create_enrollment,
    add_enrollment_trip,
    finalize_scoring,
    create_quote,
    bind_policy,
    driver_headers,
    add_policy_trip,
    get_policy,
    setup_bound_policy,
    setup_ready_quote,
    create_manual_claim,
)
from test_helpers import api_client

UW = TEST_USERS["underwriting_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict
#   instance: trip_not_open_beats_telematics_suspended (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _accepted_trip_then_suspend(clock="2026-06-01T00:00:00Z"):
    """Bound policy + one ACCEPTED policy trip, then driver opts out (policy
    telematics SUSPENDED). The trip is already ACCEPTED. Returns (ctx, trip)."""
    ctx = setup_bound_policy(clock=clock, scoring_day="2026-06-01")
    trip = add_policy_trip(ctx, "2026-06-02T01:00:00Z", "2026-06-02T01:30:00Z", 10.0,
                           events=None, accept=True)
    get_success_data(api_client.create_privacy_consent(
        ctx["driver"]["id"], create_privacy_consent_payload("REVOKE", reason="opt out"),
        ctx["dheaders"]))
    return ctx, trip


def test_state_check_wins_over_telematics_suspended(api):
    """PRD §3.12: "Only then are state-transition preconditions evaluated — a resource
    not in the required state for its requested transition yields the domain-specific
    state error for that transition ... — followed by the referential, safety,
    temporal, constraint, and fiscal business rules described throughout this section."
    PRD §3.5: "Acceptance requires the trip to be `OPEN` (otherwise
    `ERR_TRIP_NOT_OPEN`)".

    Design: Difficulty/priority_pair_validation_conflict/trip_not_open_beats_telematics_suspended
    """
    ctx, trip = _accepted_trip_then_suspend()
    res = api.accept_trip(trip["id"], ctx["dheaders"])
    validate_error(res, "ERR_TRIP_NOT_OPEN", expected_status=409)


def test_both_conditions_hold_state_error_surfaces(api):
    """PRD §3.5: "if it is `SUSPENDED` because the driver opted out, the accept is
    rejected with `ERR_TELEMATICS_SUSPENDED`".
    PRD §3.12: "This ordering ensures, for example, that a stale-version rejection is
    not masked by a later state check".

    Design: Difficulty/priority_pair_validation_conflict/trip_not_open_beats_telematics_suspended
    """
    ctx, trip = _accepted_trip_then_suspend()
    # confirm the business_safety precondition genuinely also holds (policy SUSPENDED)
    assert get_policy(ctx)["telematics_status"] == "SUSPENDED"
    # the lower-numbered state check wins over the safety check
    res = api.accept_trip(trip["id"], ctx["dheaders"])
    validate_error(res, "ERR_TRIP_NOT_OPEN", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict
#   instance: rate_plan_retired_beats_quote_expired_on_bind (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _retired_plan_and_expired_quote():
    """Quote OPEN at 2026-06-01 (expires 2026-06-15); plan retired; clock advanced to
    2026-07-01 so the quote is BOTH past expires_at AND backed by a retired plan.
    Returns ctx (with quote)."""
    ctx = setup_ready_quote(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    get_success_data(api_client.retire_rate_plan(ctx["rate_plan"]["id"], UW))
    get_success_data(api_client.set_clock("2026-07-01T00:00:00Z", UW))
    return ctx


def test_referential_rate_plan_retired_beats_temporal_quote_expired(api):
    """PRD §3.12: "Only then are state-transition preconditions evaluated ... followed
    by the referential, safety, temporal, constraint, and fiscal business rules".
    PRD §3.4: "the rate plan referenced by the quote must still be `ACTIVE` (otherwise
    `ERR_RATE_PLAN_RETIRED`)".

    Design: Difficulty/priority_pair_validation_conflict/rate_plan_retired_beats_quote_expired_on_bind
    """
    ctx = _retired_plan_and_expired_quote()
    res = api.create_policy(create_policy_payload(ctx["quote"]["id"]), UW)
    validate_error(res, "ERR_RATE_PLAN_RETIRED", expected_status=409)


def test_bind_blocked_when_plan_retired_and_quote_expired(api):
    """PRD §3.4: "the clock must be at or before the quote's `expires_at` (otherwise
    `ERR_QUOTE_EXPIRED`)".
    PRD §3.1: "an attempt to quote or bind against a retired plan is rejected with
    `ERR_RATE_PLAN_RETIRED`."

    Design: Difficulty/priority_pair_validation_conflict/rate_plan_retired_beats_quote_expired_on_bind
    """
    ctx = _retired_plan_and_expired_quote()
    # both the referential (retired plan) and temporal (expired quote) preconditions
    # are violated; the referential rule is reported first per §3.12 ordering.
    res = api.create_policy(create_policy_payload(ctx["quote"]["id"]), UW)
    validate_error(res, "ERR_RATE_PLAN_RETIRED", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency
#   instance: policy_cancel_blocked_by_open_claim (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_policy_cancel_blocked_by_open_claim(api):
    """PRD §3.7: "cancellation is blocked while any claim on the policy is in `FNOL`,
    `UNDER_REVIEW`, or `REOPENED` status, in which case it is rejected with
    `ERR_OPEN_CLAIM_BLOCKS_CANCEL`."

    Design: Difficulty/cross_entity_state_dependency/policy_cancel_blocked_by_open_claim
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    create_manual_claim(ctx, reported_severity=2)  # claim opens in FNOL
    res = api.cancel_policy(ctx["policy"]["id"], UW)
    validate_error(res, "ERR_OPEN_CLAIM_BLOCKS_CANCEL", expected_status=409)


def test_policy_stays_active_when_cancel_blocked_by_claim(api):
    """PRD §3.7: "Both transitions require the policy to currently be `ACTIVE`, otherwise
    `ERR_POLICY_NOT_ACTIVE`."
    PRD §3.7: "cancellation is blocked while any claim on the policy is in `FNOL`,
    `UNDER_REVIEW`, or `REOPENED` status".

    Design: Difficulty/cross_entity_state_dependency/policy_cancel_blocked_by_open_claim
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    create_manual_claim(ctx, reported_severity=2)
    api.cancel_policy(ctx["policy"]["id"], UW)
    policy = get_policy(ctx)
    assert policy["lifecycle_status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency
#   instance: quote_bind_blocked_by_retired_rate_plan (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_quote_bind_blocked_by_retired_rate_plan(api):
    """PRD §3.4: "the rate plan referenced by the quote must still be `ACTIVE`
    (otherwise `ERR_RATE_PLAN_RETIRED`)."

    Design: Difficulty/cross_entity_state_dependency/quote_bind_blocked_by_retired_rate_plan
    """
    ctx = setup_ready_quote(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    get_success_data(api.retire_rate_plan(ctx["rate_plan"]["id"], UW))
    res = api.create_policy(create_policy_payload(ctx["quote"]["id"]), UW)
    validate_error(res, "ERR_RATE_PLAN_RETIRED", expected_status=409)


def test_quote_remains_open_when_bind_blocked_by_retired_plan(api):
    """PRD §3.1: "an attempt to quote or bind against a retired plan is rejected with
    `ERR_RATE_PLAN_RETIRED`."
    PRD §3.4: "On a successful bind the quote transitions from `OPEN` to the terminal
    `BOUND` state".

    Design: Difficulty/cross_entity_state_dependency/quote_bind_blocked_by_retired_rate_plan
    """
    ctx = setup_ready_quote(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    get_success_data(api.retire_rate_plan(ctx["rate_plan"]["id"], UW))
    api.create_policy(create_policy_payload(ctx["quote"]["id"]), UW)
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], UW))
    assert quote["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap
#   instance: trip_event_occurred_at_half_open_interval (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _open_enrollment_trip(clock="2026-06-01T00:00:00Z",
                          started="2026-06-01T01:00:00Z", ended="2026-06-01T01:30:00Z"):
    set_clock(clock)
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    hdr = driver_headers(driver)
    trip = get_success_data(api_client.create_trip(
        create_trip_payload(started, ended, 10.0, enrollment_id=enrollment["id"]), hdr))
    return trip, hdr


def test_event_at_trip_end_instant_rejected(api):
    """PRD §3.5: "The `occurred_at` instant must fall within the half-open interval
    that starts at the trip's `started_at` (inclusive) and ends at the trip's
    `ended_at` (exclusive) — that is, at or after the start and strictly before the
    end; an event outside that interval is rejected with `ERR_EVENT_OUTSIDE_TRIP`."

    Design: Difficulty/resource_temporal_overlap/trip_event_occurred_at_half_open_interval
    """
    trip, hdr = _open_enrollment_trip()
    res = api.create_trip_event(
        trip["id"], create_trip_event_payload("HARD_BRAKE", 2, "2026-06-01T01:30:00Z"), hdr)
    validate_error(res, "ERR_EVENT_OUTSIDE_TRIP", expected_status=422)


def test_event_at_trip_start_instant_accepted(api):
    """PRD §3.5: "The `occurred_at` instant must fall within the half-open interval that
    starts at the trip's `started_at` (inclusive) ... that is, at or after the start and
    strictly before the end". PRD §3.5: "Attaching an event increments the trip's
    counter for that event type."

    Design: Difficulty/resource_temporal_overlap/trip_event_occurred_at_half_open_interval
    """
    trip, hdr = _open_enrollment_trip()
    res = api.create_trip_event(
        trip["id"], create_trip_event_payload("HARD_BRAKE", 2, "2026-06-01T01:00:00Z"), hdr)
    validate_success(res, 201)
    refreshed = get_success_data(api.get_trip(trip["id"], hdr))
    assert refreshed["hard_brake_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap
#   instance: statement_period_window_membership_by_billed_period (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_statement_billed_miles_aggregates_period_trips(api):
    """PRD §3.6: "`billed_miles` is the sum of `distance_miles` over the accepted policy
    trips whose `billed_period_index` equals the policy's current `period_index` — the
    period pin stamped at accept time, which removes any clock-window ambiguity."

    Design: Difficulty/resource_temporal_overlap/statement_period_window_membership_by_billed_period
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    add_policy_trip(ctx, "2026-06-05T01:00:00Z", "2026-06-05T06:00:00Z", 600.0,
                    events=None, accept=True)
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    assert statement["billed_miles"] == 600.0
    assert statement["period_index"] == 0


def test_statement_overage_zero_when_under_included_miles(api):
    """PRD §3.6: "Then `overage_miles` is the greater of zero and `billed_miles` minus
    the plan's `included_miles_per_period`."

    Design: Difficulty/resource_temporal_overlap/statement_period_window_membership_by_billed_period
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    add_policy_trip(ctx, "2026-06-05T01:00:00Z", "2026-06-05T06:00:00Z", 600.0,
                    events=None, accept=True)
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    # 600 billed miles < 1000 included -> overage 0
    assert statement["overage_miles"] == 0
