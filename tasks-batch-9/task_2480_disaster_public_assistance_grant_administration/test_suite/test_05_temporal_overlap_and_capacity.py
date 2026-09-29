"""Interval-occupancy and capacity rules: half-open incident periods, the
labor rest buffer and the aggregate daily equipment-hours cap.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    cost_line_item_payload,
    create_cost_line_item,
    create_equipment_resource,
    create_labor_resource,
    disaster_payload,
    get_force_account_resource,
    make_admin_headers,
    make_applicant_agent_headers,
    setup_declaration,
    setup_drafted_project,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-07-01T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC instant so a comparison survives either
    fractional-second representation of the same moment."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Half-open incident-period occupancy on (state_code, incident_type)
# ---------------------------------------------------------------------------
def _base_flood_declaration():
    """DR-4921: the single TX/FLOOD declaration occupying
    2026-06-10T00:00:00Z through 2026-06-25T00:00:00Z."""
    scenario = setup_declaration(
        CLOCK,
        declaration_number="DR-4921",
        state_code="TX",
        incident_type="FLOOD",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
        population=900000,
        federal_cost_share_pct=0.75,
        small_project_threshold_cents=4000000,
    )
    return scenario["disaster"]


def _encroaching_flood_payload():
    """DR-4922: starts 2026-06-20, five days inside the occupied period."""
    return disaster_payload(
        declaration_number="DR-4922",
        state_code="TX",
        incident_type="FLOOD",
        incident_start_at="2026-06-20T00:00:00Z",
        incident_end_at="2026-07-05T00:00:00Z",
        population=900000,
        federal_cost_share_pct=0.75,
        small_project_threshold_cents=4000000,
    )


def _adjacent_flood_payload():
    """DR-4923: starts exactly at the excluded end instant 2026-06-25."""
    return disaster_payload(
        declaration_number="DR-4923",
        state_code="TX",
        incident_type="FLOOD",
        incident_start_at="2026-06-25T00:00:00Z",
        incident_end_at="2026-07-10T00:00:00Z",
        population=900000,
        federal_cost_share_pct=0.75,
        small_project_threshold_cents=4000000,
    )


def _other_incident_type_payload():
    """DR-4924: the same calendar window as DR-4922 but TX/WILDFIRE."""
    return disaster_payload(
        declaration_number="DR-4924",
        state_code="TX",
        incident_type="WILDFIRE",
        incident_start_at="2026-06-20T00:00:00Z",
        incident_end_at="2026-07-05T00:00:00Z",
        population=900000,
        federal_cost_share_pct=0.75,
        small_project_threshold_cents=4000000,
    )


def test_incident_period_starting_inside_an_occupied_period_is_rejected(api):
    """PRD §3.1: "Second, exclusivity: for a given combination of `state_code` and
    `incident_type`, no two declarations may occupy overlapping periods, where the
    occupied interval is treated as half-open — the start instant is occupied and
    the end instant is not."
    PRD §3.1: "An incoming period whose start is exactly equal to an existing
    period's end is therefore adjacent, not overlapping, and is accepted; any
    genuine intersection is rejected with `ERR_INCIDENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/incident_period_half_open_adjacency_allowed_overlap_rejected
    """
    admin = make_admin_headers()
    _base_flood_declaration()

    response = api.create_disaster(_encroaching_flood_payload(), admin)

    validate_error(response, ApiErrorId.ERR_INCIDENT_PERIOD_OVERLAP, 409)


def test_incident_period_adjacent_at_the_excluded_end_instant_is_accepted(api):
    """PRD §3.1: "An incoming period whose start is exactly equal to an existing
    period's end is therefore adjacent, not overlapping, and is accepted; any
    genuine intersection is rejected with `ERR_INCIDENT_PERIOD_OVERLAP`."
    PRD §3.1: "Declarations of different incident types, or of different states,
    never collide with each other."

    Design: Difficulty/resource_temporal_overlap/incident_period_half_open_adjacency_allowed_overlap_rejected
    """
    admin = make_admin_headers()
    _base_flood_declaration()

    adjacent = validate_success(api.create_disaster(_adjacent_flood_payload(), admin), 201)
    assert _instant(adjacent["incident_start_at"]) == datetime(
        2026, 6, 25, tzinfo=timezone.utc
    ), (
        "Expected the accepted declaration to start at 2026-06-25T00:00:00Z, got "
        f"{adjacent['incident_start_at']}"
    )

    other_type = validate_success(
        api.create_disaster(_other_incident_type_payload(), admin), 201
    )
    assert other_type["incident_type"] == "WILDFIRE", (
        f"Expected incident_type WILDFIRE, got {other_type['incident_type']} — a different "
        "incident type occupies a different resource"
    )


def test_rejected_overlapping_declaration_writes_no_declaration_row(api):
    """PRD §3.1: "An incoming period whose start is exactly equal to an existing
    period's end is therefore adjacent, not overlapping, and is accepted; any
    genuine intersection is rejected with `ERR_INCIDENT_PERIOD_OVERLAP`."
    PRD §3.1: "Declarations of different incident types, or of different states,
    never collide with each other."

    Design: Difficulty/resource_temporal_overlap/incident_period_half_open_adjacency_allowed_overlap_rejected
    """
    admin = make_admin_headers()
    _base_flood_declaration()

    validate_error(
        api.create_disaster(_encroaching_flood_payload(), admin),
        ApiErrorId.ERR_INCIDENT_PERIOD_OVERLAP,
        409,
    )
    validate_success(api.create_disaster(_adjacent_flood_payload(), admin), 201)
    validate_success(api.create_disaster(_other_incident_type_payload(), admin), 201)

    rows, meta = validate_paginated(api.list_disasters(admin))
    assert meta["total_count"] == 3, (
        f"Expected exactly 3 declaration rows, got {meta['total_count']} — the rejected "
        "overlapping period must not have been written"
    )
    numbers = sorted(row["declaration_number"] for row in rows)
    assert numbers == ["DR-4921", "DR-4923", "DR-4924"], (
        f"Expected declarations DR-4921, DR-4923 and DR-4924, got {numbers}"
    )


# ---------------------------------------------------------------------------
# The thirty-minute labor rest buffer on a LABOR force account resource
# ---------------------------------------------------------------------------
def _drafted_project(declaration_number):
    """An ELIGIBLE applicant with a facility and one project still in DRAFT,
    which is a status that admits cost line item creation."""
    return setup_drafted_project(
        CLOCK,
        disaster_overrides={
            "declaration_number": declaration_number,
            "state_code": "TX",
            "incident_type": "FLOOD",
            "incident_start_at": "2026-06-10T00:00:00Z",
            "incident_end_at": "2026-06-25T00:00:00Z",
            "population": 900000,
            "federal_cost_share_pct": 0.75,
            "small_project_threshold_cents": 4000000,
        },
        applicant_overrides={
            "name": "City of Harborview",
            "applicant_type": "LOCAL_GOVERNMENT",
            "population_served": 120000,
        },
        facility_overrides={
            "name": "Riverside Pump Station",
            "facility_type": "WATER_CONTROL",
            "ownership": "PUBLIC",
            "flood_zone": False,
        },
        project_overrides={
            "category": "C",
            "title": "Pump station intake rebuild",
            "scope_of_work": "Rebuild intake structure",
            "estimated_repair_cost_cents": 5000000,
            "mitigation_requested_cents": 0,
        },
    )


def _labor_resource_with_first_shift(declaration_number="DR-4925"):
    """A TEMPORARY labor resource already charged for 2026-06-12T08:00:00Z
    through 2026-06-12T16:00:00Z."""
    scenario = _drafted_project(declaration_number)
    scenario["resource"] = create_labor_resource(
        scenario["applicant"]["id"],
        label="Seasonal Debris Crew Member",
        employee_type="TEMPORARY",
        base_hourly_rate_cents=3000,
        fringe_benefit_pct=0.25,
    )
    scenario["first_line"] = create_cost_line_item(
        scenario["project"]["id"],
        scenario["applicant"]["id"],
        cost_type="FORCE_ACCOUNT_LABOR",
        force_account_resource_id=scenario["resource"]["id"],
        claimed_cents=30000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T16:00:00Z",
        straight_time_hours=8,
        overtime_hours=0,
    )
    return scenario


def _labor_line_payload(scenario, work_start_at):
    return cost_line_item_payload(
        scenario["project"]["id"],
        cost_type="FORCE_ACCOUNT_LABOR",
        force_account_resource_id=scenario["resource"]["id"],
        claimed_cents=10000,
        work_start_at=work_start_at,
        work_end_at="2026-06-12T18:00:00Z",
        straight_time_hours=0,
        overtime_hours=1.5,
    )


def test_labor_line_starting_inside_the_rest_buffer_is_rejected(api):
    """PRD §3.4: "A **labor** line may not overlap another labor line on the same
    resource, and the prohibition is widened by a thirty-minute rest buffer on each
    side: the new line's interval, extended half an hour earlier and half an hour
    later, must not intersect the closed interval of any existing labor line on that
    resource."
    PRD §3.4: "In practice, two back-to-back shifts collide, two shifts exactly
    thirty minutes apart still collide, and a shift starting thirty-one minutes
    after the previous one ended is accepted."
    PRD §3.4: "A collision yields `ERR_LABOR_ENTRY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/force_account_labor_rest_buffer_collision
    """
    scenario = _labor_resource_with_first_shift()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    # 16:20 widens to a buffered window opening at 15:50, inside the 08:00–16:00 shift.
    response = api.create_cost_line_item(
        _labor_line_payload(scenario, "2026-06-12T16:20:00Z"), agent
    )

    validate_error(response, ApiErrorId.ERR_LABOR_ENTRY_OVERLAP, 409)


def test_labor_line_starting_clear_of_the_rest_buffer_is_accepted(api):
    """PRD §3.4: "In practice, two back-to-back shifts collide, two shifts exactly
    thirty minutes apart still collide, and a shift starting thirty-one minutes
    after the previous one ended is accepted."
    PRD §3.4: "A new line is created in `review_status` `SUBMITTED` with
    `eligible_cents` 0, `disallowance_reason` null and `reviewed_at` null."

    Design: Difficulty/resource_temporal_overlap/force_account_labor_rest_buffer_collision
    """
    scenario = _labor_resource_with_first_shift()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    # 16:45 widens to a buffered window opening at 16:15, clear of the 16:00 end.
    line = validate_success(
        api.create_cost_line_item(_labor_line_payload(scenario, "2026-06-12T16:45:00Z"), agent),
        201,
    )

    assert _instant(line["work_start_at"]) == datetime(
        2026, 6, 12, 16, 45, tzinfo=timezone.utc
    ), (
        "Expected the accepted labor line to start at 2026-06-12T16:45:00Z, got "
        f"{line['work_start_at']}"
    )
    assert line["review_status"] == "SUBMITTED", (
        f"Expected review_status SUBMITTED on a new claim, got {line['review_status']}"
    )
    assert line["eligible_cents"] == 0, (
        f"Expected eligible_cents 0 on a new claim, got {line['eligible_cents']}"
    )


def test_rejected_labor_line_leaves_exactly_two_unreviewed_claims(api):
    """PRD §3.4: "A collision yields `ERR_LABOR_ENTRY_OVERLAP`."
    PRD §3.4: "A new line is created in `review_status` `SUBMITTED` with
    `eligible_cents` 0, `disallowance_reason` null and `reviewed_at` null."

    Design: Difficulty/resource_temporal_overlap/force_account_labor_rest_buffer_collision
    """
    scenario = _labor_resource_with_first_shift()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    validate_error(
        api.create_cost_line_item(_labor_line_payload(scenario, "2026-06-12T16:20:00Z"), agent),
        ApiErrorId.ERR_LABOR_ENTRY_OVERLAP,
        409,
    )
    validate_success(
        api.create_cost_line_item(_labor_line_payload(scenario, "2026-06-12T16:45:00Z"), agent),
        201,
    )

    rows, meta = validate_paginated(api.list_cost_line_items(make_admin_headers()))
    assert meta["total_count"] == 2, (
        f"Expected exactly 2 cost line item rows, got {meta['total_count']} — the collided "
        "claim must not have been written"
    )
    for row in rows:
        assert row["review_status"] == "SUBMITTED", (
            f"Expected review_status SUBMITTED on every surviving claim, got "
            f"{row['review_status']}"
        )
        assert row["eligible_cents"] == 0, (
            f"Expected eligible_cents 0 on every surviving claim, got {row['eligible_cents']}"
        )


# ---------------------------------------------------------------------------
# The aggregate sixteen-hour daily cap on an EQUIPMENT force account resource
# ---------------------------------------------------------------------------
def _equipment_resource_with_fifteen_charged_hours(declaration_number="DR-4926"):
    """An equipment resource carrying 10 + 5 equipment_hours on the UTC day
    2026-06-12, i.e. 15 of the sixteen permitted hours."""
    scenario = _drafted_project(declaration_number)
    scenario["resource"] = create_equipment_resource(
        scenario["applicant"]["id"],
        label="CAT 320 Excavator",
        equipment_code="EX-320",
        published_hourly_rate_cents=9000,
        schedule_hourly_rate_cents=8500,
    )
    scenario["first_line"] = create_cost_line_item(
        scenario["project"]["id"],
        scenario["applicant"]["id"],
        cost_type="FORCE_ACCOUNT_EQUIPMENT",
        force_account_resource_id=scenario["resource"]["id"],
        claimed_cents=85000,
        work_start_at="2026-06-12T06:00:00Z",
        work_end_at="2026-06-12T16:00:00Z",
        equipment_hours=10,
    )
    scenario["second_line"] = create_cost_line_item(
        scenario["project"]["id"],
        scenario["applicant"]["id"],
        cost_type="FORCE_ACCOUNT_EQUIPMENT",
        force_account_resource_id=scenario["resource"]["id"],
        claimed_cents=42500,
        work_start_at="2026-06-12T17:00:00Z",
        work_end_at="2026-06-12T22:00:00Z",
        equipment_hours=5,
    )
    return scenario


def _equipment_line_payload(scenario, claimed_cents, work_end_at, equipment_hours):
    return cost_line_item_payload(
        scenario["project"]["id"],
        cost_type="FORCE_ACCOUNT_EQUIPMENT",
        force_account_resource_id=scenario["resource"]["id"],
        claimed_cents=claimed_cents,
        work_start_at="2026-06-12T22:00:00Z",
        work_end_at=work_end_at,
        equipment_hours=equipment_hours,
    )


def test_equipment_daily_hours_above_the_cap_is_rejected(api):
    """PRD §3.4: "An **equipment** line, by contrast, may overlap other equipment
    lines freely — a backhoe can be charged to two tasks in the same hour on paper —
    but the aggregate is capped per day: for every UTC calendar day that the new
    line's interval touches, the sum of `equipment_hours` over that resource's
    existing lines touching that same day, plus the new line's own
    `equipment_hours`, may not exceed sixteen hours."
    PRD §3.4: "A total of exactly sixteen is accepted; anything above it yields
    `ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/force_account_equipment_daily_hours_aggregate_capacity
    """
    scenario = _equipment_resource_with_fifteen_charged_hours()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    # 15 already charged on 2026-06-12 plus 2 more is 17, above the sixteen-hour cap.
    response = api.create_cost_line_item(
        _equipment_line_payload(scenario, 17000, "2026-06-12T23:59:00Z", 2), agent
    )

    validate_error(response, ApiErrorId.ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED, 409)


def test_equipment_daily_hours_exactly_at_the_cap_is_accepted(api):
    """PRD §3.4: "A total of exactly sixteen is accepted; anything above it yields
    `ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED`."
    PRD §3.4: "Every resource starts with `charged_hours_total` at 0; that field is
    the running total of `straight_time_hours` plus `overtime_hours` plus
    `equipment_hours` across every cost line item that references the resource, and
    it is refreshed whenever one of those lines is reviewed."

    Design: Difficulty/resource_temporal_overlap/force_account_equipment_daily_hours_aggregate_capacity
    """
    scenario = _equipment_resource_with_fifteen_charged_hours()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    # 15 already charged on 2026-06-12 plus exactly 1 more is exactly sixteen.
    line = validate_success(
        api.create_cost_line_item(
            _equipment_line_payload(scenario, 8500, "2026-06-12T23:00:00Z", 1), agent
        ),
        201,
    )

    assert line["equipment_hours"] == 1, (
        f"Expected equipment_hours 1 on the line taking the day to exactly sixteen, got "
        f"{line['equipment_hours']}"
    )
    assert line["review_status"] == "SUBMITTED", (
        f"Expected review_status SUBMITTED on a new claim, got {line['review_status']}"
    )
    resource = get_force_account_resource(scenario["resource"]["id"])
    assert resource["charged_hours_total"] == 0, (
        "Expected charged_hours_total 0 while no line has been reviewed, got "
        f"{resource['charged_hours_total']}"
    )


def test_rejected_equipment_line_leaves_exactly_three_claims(api):
    """PRD §3.4: "An **equipment** line, by contrast, may overlap other equipment
    lines freely — a backhoe can be charged to two tasks in the same hour on paper —
    but the aggregate is capped per day: for every UTC calendar day that the new
    line's interval touches, the sum of `equipment_hours` over that resource's
    existing lines touching that same day, plus the new line's own
    `equipment_hours`, may not exceed sixteen hours."
    PRD §3.4: "A total of exactly sixteen is accepted; anything above it yields
    `ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/force_account_equipment_daily_hours_aggregate_capacity
    """
    scenario = _equipment_resource_with_fifteen_charged_hours()
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    validate_error(
        api.create_cost_line_item(
            _equipment_line_payload(scenario, 17000, "2026-06-12T23:59:00Z", 2), agent
        ),
        ApiErrorId.ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED,
        409,
    )
    validate_success(
        api.create_cost_line_item(
            _equipment_line_payload(scenario, 8500, "2026-06-12T23:00:00Z", 1), agent
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_cost_line_items(make_admin_headers()))
    assert meta["total_count"] == 3, (
        f"Expected exactly 3 cost line item rows, got {meta['total_count']} — the claim that "
        "breached the daily cap must not have been written"
    )
    total_hours = sum(row["equipment_hours"] for row in rows)
    assert total_hours == 16, (
        f"Expected the surviving claims to total exactly 16 equipment_hours, got {total_hours}"
    )
