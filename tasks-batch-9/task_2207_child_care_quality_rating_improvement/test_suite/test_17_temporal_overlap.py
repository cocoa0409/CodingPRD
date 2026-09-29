"""Interval semantics for the two scarce resources: the observer and the on-site slot.

Observation windows are half-open, so touching endpoints are legal; the same-provider
cool-down turns a geometrically disjoint window into a conflict; coaching intervals are
closed, so touching endpoints do conflict; and the weekly on-site cap is an aggregate
bucket that ignores geometry altogether.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    build_rating_spine,
    create_enrolled_provider,
    create_reliable_observer,
    declare_domains,
    documentation_for,
    make_coach_headers,
    make_provider_headers,
    open_cycle,
    schedule_session,
    schedule_visit,
    set_clock,
    setup_active_allocation,
    submit_self_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    verify_self_assessment,
)

ADMIN = TEST_USERS["admin_headers"]

#: Five equally weighted domains with a block minimum of 1 point, so nothing except the
#: rule under test can refuse a scheduling request.
EQUAL_WEIGHT_DOMAINS = [
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": True,
        "min_composite_for_block": 3.00,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
]

TIER_ONE_POINTS = {
    "LEARNING_ENVIRONMENT": 10,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 8,
    "ADMINISTRATION": 6,
    "CHILD_ASSESSMENT": 7,
}


def _docs_verified_cycle(legal_name, county_code):
    """Enrolled provider with an INITIAL cycle walked to DOCS_VERIFIED.

    Assumes the five standard domains are already declared.
    """
    provider = create_enrolled_provider(
        legal_name=legal_name,
        county_code=county_code,
        region_code="URBAN",
        licensed_capacity=50,
        active_staff_fte=12.00,
        weekly_onsite_cap_hours=12.0,
    )
    cycle = open_cycle(provider["id"])
    self_assessment = submit_self_assessment(
        provider["id"], cycle["id"], claimed=TIER_ONE_POINTS,
        documentation=documentation_for(),
    )
    verify_self_assessment(self_assessment["id"], verified=TIER_ONE_POINTS)
    return provider, cycle


def _tier_one_active_spine(**overrides):
    """Provider ACTIVE at current_tier 1 with a 12.0-hour weekly on-site cap."""
    params = {
        "stop_at": "ACTIVE",
        "domains": EQUAL_WEIGHT_DOMAINS,
        "provider_overrides": {
            "legal_name": "Onsite Test Center",
            "county_code": "DANE",
            "region_code": "URBAN",
            "licensed_capacity": 50,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        "credentials": [],
        "claimed": TIER_ONE_POINTS,
        "verified": TIER_ONE_POINTS,
        "raw_score": 4.0,
        "award_clock": "2026-08-11T00:00:00Z",
        "activation_clock": "2026-09-01T00:00:00Z",
    }
    params.update(overrides)
    return build_rating_spine(**params)


# --- 1. half-open observation windows, no same-provider buffer ----------------


def test_touching_observation_windows_are_legal_but_a_one_second_overlap_is_not(api):
    """PRD §3.4: "Observation windows are treated as half-open intervals that include their
    start and exclude their end, so an existing visit that ends exactly at the new
    `window_start` does not conflict."
    PRD §3.4: "On top of the geometric overlap, a 48-hour cool-down buffer applies only when
    the conflicting existing visit belongs to the same provider: the request is refused when
    the new `window_start` falls earlier than the existing visit's `window_end` plus 48 hours."
    PRD §3.4: "A violation of either the overlap test or the same-provider buffer is
    `ERR_OBSERVER_SCHEDULE_CONFLICT` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/observer_half_open_window_adjacency_across_providers
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_domains(EQUAL_WEIGHT_DOMAINS)
    observer = create_reliable_observer("Obs Alpha", certified_until="2027-06-30")

    _provider_b, cycle_b = _docs_verified_cycle("Center B", "C002")
    visit_b = schedule_visit(
        cycle_b["id"], observer["id"], "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z"
    )
    assert visit_b["status"] == "SCHEDULED"

    _provider_a, cycle_a = _docs_verified_cycle("Center A", "C001")
    _provider_c, cycle_c = _docs_verified_cycle("Center C", "C003")

    # One second of overlap with a visit belonging to a *different* provider, so the
    # 48-hour buffer clause is inert and only the geometry can refuse.
    overlapping = api.create_observation_visit(
        cycle_c["id"],
        {
            "lead_observer_id": observer["id"],
            "window_start": "2026-08-10T16:59:59Z",
            "window_end": "2026-08-11T00:59:59Z",
        },
        ADMIN,
    )
    validate_error(overlapping, "ERR_OBSERVER_SCHEDULE_CONFLICT", 409)
    assert validate_success(
        api.get_rating_cycle(cycle_c["id"], ADMIN)
    )["status"] == "DOCS_VERIFIED"
    cycle_c_visits, _meta = validate_paginated(
        api.list_observation_visits(ADMIN, params={"rating_cycle_id": cycle_c["id"]})
    )
    assert len(cycle_c_visits) == 0, f"no visit may exist for cycle C, got {cycle_c_visits}"

    # Starting at the exact instant the existing visit ends is adjacency, not overlap.
    adjacent = validate_success(
        api.create_observation_visit(
            cycle_a["id"],
            {
                "lead_observer_id": observer["id"],
                "window_start": "2026-08-10T17:00:00Z",
                "window_end": "2026-08-11T01:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"
    assert validate_success(
        api.get_rating_cycle(cycle_a["id"], ADMIN)
    )["status"] == "OBSERVATION_SCHEDULED"

    occupied, _meta = validate_paginated(
        api.list_observation_visits(ADMIN, params={"lead_observer_id": observer["id"]})
    )
    assert len(occupied) == 2, (
        f"only the two admitted visits may name this observer, got {len(occupied)}"
    )


# --- 2. the buffered variant: same provider, disjoint windows still conflict ---


def test_same_provider_cooldown_refuses_a_disjoint_window_until_exactly_48_hours(api):
    """PRD §3.4: "On top of the geometric overlap, a 48-hour cool-down buffer applies only when
    the conflicting existing visit belongs to the same provider: the request is refused when
    the new `window_start` falls earlier than the existing visit's `window_end` plus 48 hours."
    PRD §3.4: "The candidate set is every observation visit naming that observer as lead or as
    secondary whose state is `SCHEDULED`, `IN_PROGRESS`, `SCORES_ENTERED`, `RELIABILITY_CHECK`,
    or `FINALIZED`; a `CANCELLED` visit never conflicts."
    PRD §3.5: "The `expires_on` instant is the `effective_date` advanced by that many calendar
    months and then pulled back by one day, at 23:59:59.999 UTC; because the effective date is
    always the first day of a month, month addition never needs day clamping."

    Design: Difficulty/resource_temporal_overlap/observer_same_provider_48h_cooldown_buffer
    """
    ctx = _tier_one_active_spine(
        provider_overrides={
            "legal_name": "Buffer Test Center",
            "county_code": "DANE",
            "region_code": "URBAN",
            "licensed_capacity": 50,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        window_start="2026-08-30T09:00:00Z",
        window_end="2026-08-30T17:00:00Z",
        award_clock="2026-08-30T12:00:00Z",
    )
    provider_id = ctx["provider"]["id"]
    first_cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert first_cycle["status"] == "ACTIVE"
    assert first_cycle["awarded_tier"] == 1
    assert first_cycle["weighted_total"] == pytest.approx(37.00, abs=0.005)
    assert first_cycle["validity_months"] == 24
    assert first_cycle["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert first_cycle["expires_on"] == "2028-08-31T23:59:59.999Z"
    assert first_cycle["rerating_window_opens_on"] == "2028-06-02T00:00:00.000Z"
    assert validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))[
        "status"
    ] == "FINALIZED", "a FINALIZED visit stays inside the occupation candidate set"
    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["status"] == "ACTIVE"
    assert provider["current_tier"] == 1

    # A REMAND cycle is exempt from the re-rating window, which is what lets the same
    # provider hold a second schedulable cycle within the cool-down period.
    second = open_cycle(provider_id, "REMAND")
    self_assessment = submit_self_assessment(
        provider_id, second["id"], claimed=TIER_ONE_POINTS,
        documentation=documentation_for(),
    )
    verify_self_assessment(self_assessment["id"], verified=TIER_ONE_POINTS)

    # 2026-09-01T08:00 is 39 hours after the first visit ended, so the two windows do not
    # overlap at all, yet it falls before window_end plus 48 hours.
    buffered = api.create_observation_visit(
        second["id"],
        {
            "lead_observer_id": ctx["lead"]["id"],
            "window_start": "2026-09-01T08:00:00Z",
            "window_end": "2026-09-01T16:00:00Z",
        },
        ADMIN,
    )
    validate_error(buffered, "ERR_OBSERVER_SCHEDULE_CONFLICT", 409)
    assert validate_success(api.get_rating_cycle(second["id"], ADMIN))[
        "status"
    ] == "DOCS_VERIFIED"

    # Exactly window_end plus 48 hours is not "earlier than", so the buffer releases.
    accepted = validate_success(
        api.create_observation_visit(
            second["id"],
            {
                "lead_observer_id": ctx["lead"]["id"],
                "window_start": "2026-09-01T17:00:00Z",
                "window_end": "2026-09-02T01:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert validate_success(api.get_rating_cycle(second["id"], ADMIN))[
        "status"
    ] == "OBSERVATION_SCHEDULED"
    second_visits, _meta = validate_paginated(
        api.list_observation_visits(ADMIN, params={"rating_cycle_id": second["id"]})
    )
    assert len(second_visits) == 1, (
        f"only the admitted visit may exist on the second cycle, got {len(second_visits)}"
    )


# --- 3. closed coaching intervals: touching endpoints do conflict --------------


def test_a_coaching_session_starting_when_another_ends_conflicts_but_one_hour_later_does_not(api):
    """PRD §3.9: "Coaching intervals are treated as **closed** intervals that include both
    endpoints, so two sessions that merely touch at an endpoint do conflict — the opposite
    convention from observation windows, and deliberately so, because a coach cannot physically
    leave one classroom and enter another in the same instant."
    PRD §3.9: "The candidate set for the conflict test is every coaching session in `SCHEDULED`
    under any allocation of the same provider that carries the same `coach_user_id`; sessions in
    `DELIVERED` or `CANCELLED` never conflict."
    PRD §3.9: "A failure of either test is `ERR_ONSITE_CAPACITY_CONFLICT` with HTTP 409."
    PRD §3.9: "An accepted session is created in `SCHEDULED`, adds its hours to the allocation's
    `scheduled_hours`, and subtracts them from the allocation's `remaining_hours`."

    Design: Difficulty/resource_temporal_overlap/coaching_site_closed_interval_touching_endpoints
    """
    ctx = _tier_one_active_spine(
        provider_overrides={
            "legal_name": "Closed Interval Center",
            "county_code": "DANE",
            "region_code": "URBAN",
            "licensed_capacity": 50,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        }
    )
    assert validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))["current_tier"] == 1

    _ctx, allocation = setup_active_allocation(
        spine=ctx,
        funding_source="STATE_BASE",
        funding_grant_id=None,
        period_start="2026-09-01",
        period_end="2026-12-31",
        allocated_hours=12.0,
        hourly_rate_cents=9_000,
    )
    assert allocation["status"] == "ACTIVE"
    assert allocation["base_hours_cost_cents"] == 108_000
    assert allocation["admin_fee_cents"] == 9_720
    assert allocation["total_cost_cents"] == 117_720
    assert allocation["spend_cap_cents"] == 500_000

    first = schedule_session(
        allocation["id"], "2026-09-14T09:00:00Z", "2026-09-14T12:00:00Z"
    )
    assert first["status"] == "SCHEDULED"
    assert float(first["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)
    assert first["iso_week_key"] == "2026-W38"

    # Starting at the exact instant the existing session ends: the closed convention makes
    # this an overlap, even though the weekly bucket would only reach 6.0 of 12.0 hours.
    touching = api.create_coaching_session(
        allocation["id"],
        {"scheduled_start": "2026-09-14T12:00:00Z", "scheduled_end": "2026-09-14T15:00:00Z"},
        make_coach_headers(),
    )
    validate_error(touching, "ERR_ONSITE_CAPACITY_CONFLICT", 409)

    unchanged = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(unchanged["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)
    assert float(unchanged["remaining_hours"]) == pytest.approx(9.0, abs=0.05)

    # A one-hour gap clears the closed interval and stays under the weekly cap.
    accepted = validate_success(
        api.create_coaching_session(
            allocation["id"],
            {"scheduled_start": "2026-09-14T13:00:00Z", "scheduled_end": "2026-09-14T16:00:00Z"},
            make_coach_headers(),
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert float(accepted["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)
    assert accepted["iso_week_key"] == "2026-W38"

    after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(after["scheduled_hours"]) == pytest.approx(6.0, abs=0.05)
    assert float(after["delivered_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(after["remaining_hours"]) == pytest.approx(6.0, abs=0.05)

    sessions, _meta = validate_paginated(
        api.list_coaching_sessions(
            ADMIN, params={"coaching_allocation_id": allocation["id"]}
        )
    )
    assert len(sessions) == 2, f"exactly the two admitted sessions may exist, got {sessions}"


# --- 4. the aggregate weekly bucket, independent of geometry -------------------


def test_the_weekly_onsite_bucket_sums_across_allocations_and_rejects_only_above_the_cap(api):
    """PRD §3.9: "Independently of geometry, an aggregate weekly capacity test applies: the sum
    of `scheduled_hours` over all the provider's sessions in `SCHEDULED` plus `delivered_hours`
    over all its sessions in `DELIVERED`, taken across all of that provider's allocations that
    share the new session's `iso_week_key`, plus the new session's own `scheduled_hours`, must
    not be strictly greater than the provider's `weekly_onsite_cap_hours`."
    PRD §3.9: "Three checks then apply, in this order. First, site occupation and weekly
    capacity. ... Third, the hours budget: the allocation's `remaining_hours` must be at least
    the new session's `scheduled_hours`, and a shortfall is refused with
    `ERR_COACHING_HOURS_CAP_EXCEEDED`."
    PRD §3.9: "its `iso_week_key` as the ISO year-and-week of `scheduled_start` in the form of a
    four-digit year, a hyphen, the letter W, and the two-digit week number — for instance the
    thirty-eighth week of 2026 is written `2026-W38`."

    Design: Difficulty/resource_temporal_overlap/onsite_weekly_aggregate_capacity_bucket
    """
    ctx = _tier_one_active_spine(
        provider_overrides={
            "legal_name": "Weekly Bucket Center",
            "county_code": "DANE",
            "region_code": "URBAN",
            "licensed_capacity": 50,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        }
    )
    provider_id = ctx["provider"]["id"]
    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["current_tier"] == 1
    assert float(provider["weekly_onsite_cap_hours"]) == pytest.approx(12.0, abs=0.05)

    allocation_kwargs = {
        "funding_source": "STATE_BASE",
        "funding_grant_id": None,
        "period_start": "2026-09-01",
        "period_end": "2026-12-31",
        "hourly_rate_cents": 9_000,
    }
    _ctx, first_allocation = setup_active_allocation(
        spine=ctx, allocated_hours=10.0, **allocation_kwargs
    )
    assert first_allocation["base_hours_cost_cents"] == 90_000
    assert first_allocation["admin_fee_cents"] == 8_100
    assert first_allocation["total_cost_cents"] == 98_100

    second_allocation = validate_success(
        api.create_coaching_allocation(
            provider_id,
            dict(
                coach_user_id=first_allocation["coach_user_id"],
                allocated_hours=12.0,
                **allocation_kwargs,
            ),
            ADMIN,
        ),
        201,
    )
    second_allocation = validate_success(
        api.accept_coaching_allocation(
            second_allocation["id"], make_provider_headers(provider_id)
        )
    )
    assert second_allocation["status"] == "ACTIVE"
    assert second_allocation["base_hours_cost_cents"] == 108_000
    assert second_allocation["admin_fee_cents"] == 9_720
    assert second_allocation["total_cost_cents"] == 117_720

    # 5.0 hours on Monday under the first allocation, 4.0 on Tuesday under the second:
    # 9.0 of the provider's 12.0 weekly hours are now spoken for in 2026-W38.
    monday = schedule_session(
        first_allocation["id"], "2026-09-14T09:00:00Z", "2026-09-14T14:00:00Z"
    )
    tuesday = schedule_session(
        second_allocation["id"], "2026-09-15T09:00:00Z", "2026-09-15T13:00:00Z"
    )
    assert monday["iso_week_key"] == "2026-W38"
    assert tuesday["iso_week_key"] == "2026-W38"
    assert float(monday["scheduled_hours"]) == pytest.approx(5.0, abs=0.05)
    assert float(tuesday["scheduled_hours"]) == pytest.approx(4.0, abs=0.05)

    # 4.5 more hours on Wednesday overlaps nothing, and the second allocation still has
    # 8.0 remaining hours, so only the aggregate bucket (13.5 > 12.0) can refuse.
    over_cap = api.create_coaching_session(
        second_allocation["id"],
        {"scheduled_start": "2026-09-16T09:00:00Z", "scheduled_end": "2026-09-16T13:30:00Z"},
        make_coach_headers(),
    )
    error = validate_error(over_cap, "ERR_ONSITE_CAPACITY_CONFLICT", 409)
    assert error["error_id"] != "ERR_COACHING_HOURS_CAP_EXCEEDED", (
        "the allocation still has 8.0 remaining hours, so the weekly bucket must be the "
        "reported failure"
    )

    # 3.0 hours lands the bucket on exactly 12.0, which is not strictly greater.
    exactly_at_cap = validate_success(
        api.create_coaching_session(
            second_allocation["id"],
            {"scheduled_start": "2026-09-16T09:00:00Z", "scheduled_end": "2026-09-16T12:00:00Z"},
            make_coach_headers(),
        ),
        201,
    )
    assert exactly_at_cap["status"] == "SCHEDULED"
    assert exactly_at_cap["iso_week_key"] == "2026-W38"
    assert float(exactly_at_cap["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)

    first_after = validate_success(api.get_coaching_allocation(first_allocation["id"], ADMIN))
    assert float(first_after["scheduled_hours"]) == pytest.approx(5.0, abs=0.05)
    assert float(first_after["remaining_hours"]) == pytest.approx(5.0, abs=0.05)

    second_after = validate_success(api.get_coaching_allocation(second_allocation["id"], ADMIN))
    assert float(second_after["scheduled_hours"]) == pytest.approx(7.0, abs=0.05)
    assert float(second_after["remaining_hours"]) == pytest.approx(5.0, abs=0.05)

    week_sessions, _meta = validate_paginated(
        api.list_coaching_sessions(ADMIN, params={"iso_week_key": "2026-W38"})
    )
    assert len(week_sessions) == 3, (
        f"the week bucket must hold exactly three sessions, got {len(week_sessions)}"
    )
