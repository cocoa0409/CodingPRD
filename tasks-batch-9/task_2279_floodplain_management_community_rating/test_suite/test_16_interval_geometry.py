"""Interval geometry: three families of records occupy time intervals, and each
family uses a different, deliberately specified geometry.

Panel succession is strictly increasing on a single instant, recertification
coverage windows are closed on both ends, and inspection sweep windows are
compared only after a seven-day buffer expansion.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_panel,
    assert_days_after,
    create_effective_panel,
    lapse_cycle,
    open_cycle,
    parse_instant,
    read_cycle,
    register_community,
    run_sweep,
    set_clock,
    setup_structure,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR_HEADERS = TEST_USERS["coordinator_headers"]
ADMIN_HEADERS = TEST_USERS["administrator_headers"]

PANEL_NUMBER = "48001C0100"


def _panel_payload(community_id, suffix, effective_date, base_flood_elevation_ft):
    return {
        "community_id": community_id,
        "panel_number": PANEL_NUMBER,
        "suffix": suffix,
        "flood_zone": "AE",
        "effective_date": effective_date,
        "base_flood_elevation_ft": base_flood_elevation_ft,
    }


def _read_panel(api, panel_id):
    return validate_success(api.get_firm_panel(panel_id, COORDINATOR_HEADERS), 200)


def _cycle_payload(community_id, cycle_year, start, end, due):
    return {
        "community_id": community_id,
        "cycle_year": cycle_year,
        "cycle_start_date": start,
        "cycle_end_date": end,
        "due_at": due,
    }


def _sweep_payload(declaration_code, event_date, inspection_window_days=30):
    return {
        "declaration_code": declaration_code,
        "event_date": event_date,
        "inspection_window_days": inspection_window_days,
    }


# ==========================================================================
# FIRM panel succession: strictly increasing effective dates
# ==========================================================================

def test_panel_filing_tying_the_incumbent_effective_date_is_rejected(api):
    """PRD §2.11: "A panel may be filed or activated only when no other panel
    sharing its `community_id` and `panel_number` is currently `EFFECTIVE` with an
    `effective_date` at or after the candidate's `effective_date`; a candidate whose
    date ties or precedes the incumbent's is rejected with
    `ERR_PANEL_EFFECTIVE_DATE_OVERLAP`."

    PRD §2.11: "Zero-length coverage — a successor sharing the incumbent's exact
    effective date — is therefore forbidden."

    Design: Difficulty/resource_temporal_overlap/panel_effective_date_must_be_strictly_after_incumbent
    """
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=1.5, cumulative_period_years=10
    )
    incumbent = create_effective_panel(
        community["id"], panel_number=PANEL_NUMBER, suffix="H", flood_zone="AE",
        effective_date="2026-06-01T00:00:00Z", base_flood_elevation_ft=12.0,
    )
    assert incumbent["status"] == "EFFECTIVE"

    response = api.file_firm_panel(
        _panel_payload(community["id"], "J", "2026-06-01T00:00:00Z", 14.0), COORDINATOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_PANEL_EFFECTIVE_DATE_OVERLAP)

    assert _read_panel(api, incumbent["id"])["status"] == "EFFECTIVE"
    _, meta = validate_paginated(
        api.list_firm_panels(COORDINATOR_HEADERS, params={"panel_number": PANEL_NUMBER})
    )
    assert meta["total_count"] == 1


def test_panel_dated_one_day_later_is_accepted_and_activates(api):
    """PRD §2.11: "A panel may be filed or activated only when no other panel
    sharing its `community_id` and `panel_number` is currently `EFFECTIVE` with an
    `effective_date` at or after the candidate's `effective_date`; a candidate whose
    date ties or precedes the incumbent's is rejected with
    `ERR_PANEL_EFFECTIVE_DATE_OVERLAP`."

    PRD §3.2: "Activation moves the panel from `PENDING_REVISION` to `EFFECTIVE`,
    stamps `activated_at` with the current logical clock, and records in
    `supersedes_panel_id` the identifier of the panel that was `EFFECTIVE` for the
    same `community_id` and `panel_number` at that moment — null when this is the
    community's first panel for that number."

    Design: Difficulty/resource_temporal_overlap/panel_effective_date_must_be_strictly_after_incumbent
    """
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=1.5, cumulative_period_years=10
    )
    incumbent = create_effective_panel(
        community["id"], panel_number=PANEL_NUMBER, suffix="H", flood_zone="AE",
        effective_date="2026-06-01T00:00:00Z", base_flood_elevation_ft=12.0,
    )

    response = api.file_firm_panel(
        _panel_payload(community["id"], "K", "2026-06-02T00:00:00Z", 14.0), COORDINATOR_HEADERS
    )
    successor = validate_success(response, 201)
    assert successor["status"] == "PENDING_REVISION"
    assert parse_instant(successor["effective_date"]) == parse_instant("2026-06-02T00:00:00Z")

    activated = activate_panel(successor["id"])
    assert activated["status"] == "EFFECTIVE"
    assert activated["supersedes_panel_id"] == incumbent["id"]
    assert activated["activated_at"] is not None
    assert _read_panel(api, incumbent["id"])["status"] == "SUPERSEDED"

    _, meta = validate_paginated(
        api.list_firm_panels(COORDINATOR_HEADERS, params={"panel_number": PANEL_NUMBER})
    )
    assert meta["total_count"] == 2


# ==========================================================================
# Recertification cycles: closed intervals, a shared endpoint is an overlap
# ==========================================================================

def test_shared_cycle_endpoint_is_an_overlap(api):
    """PRD §2.11: "A candidate interval running from `cycle_start_date` through
    `cycle_end_date` inclusive may not intersect the closed interval of any cycle of
    the same community whose `status` is `OPEN`, `SUBMITTED`, `UNDER_VERIFICATION`,
    `CERTIFIED`, or `RETROGRADED`; only `LAPSED` cycles are ignored."

    PRD §2.11: "An intersection, including one that touches at a single instant, is
    rejected with `ERR_CYCLE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crs_cycle_windows_are_closed_so_shared_endpoint_is_an_overlap
    """
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=1.5, cumulative_period_years=10
    )
    cycle_2026 = open_cycle(
        community["id"], cycle_year=2026, cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z", due_at="2026-09-30T00:00:00Z",
    )
    assert cycle_2026["status"] == "OPEN"

    response = api.create_crs_cycle(
        _cycle_payload(community["id"], 2027, "2026-12-31T00:00:00Z",
                       "2027-12-31T00:00:00Z", "2027-09-30T00:00:00Z"),
        COORDINATOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

    assert read_cycle(cycle_2026["id"])["status"] == "OPEN"
    _, meta = validate_paginated(
        api.list_crs_cycles(COORDINATOR_HEADERS, params={"community_id": community["id"]})
    )
    assert meta["total_count"] == 1


def test_cycle_starting_the_day_after_the_incumbent_ends_is_accepted(api):
    """PRD §2.11: "A candidate interval running from `cycle_start_date` through
    `cycle_end_date` inclusive may not intersect the closed interval of any cycle of
    the same community whose `status` is `OPEN`, `SUBMITTED`, `UNDER_VERIFICATION`,
    `CERTIFIED`, or `RETROGRADED`; only `LAPSED` cycles are ignored."

    PRD §3.9: "A new cycle has `status` `OPEN`, `total_claimed_points` and
    `total_verified_points` 0, `version` 1, and `verification_visit_required`
    computed from its `cycle_year`."

    Design: Difficulty/resource_temporal_overlap/crs_cycle_windows_are_closed_so_shared_endpoint_is_an_overlap
    """
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=1.5, cumulative_period_years=10
    )
    cycle_2026 = open_cycle(
        community["id"], cycle_year=2026, cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z", due_at="2026-09-30T00:00:00Z",
    )

    response = api.create_crs_cycle(
        _cycle_payload(community["id"], 2027, "2027-01-01T00:00:00Z",
                       "2027-12-31T00:00:00Z", "2027-09-30T00:00:00Z"),
        COORDINATOR_HEADERS,
    )
    cycle_2027 = validate_success(response, 201)

    assert parse_instant(cycle_2027["cycle_start_date"]) == parse_instant("2027-01-01T00:00:00Z")
    assert cycle_2027["status"] == "OPEN"
    assert cycle_2027["total_claimed_points"] == 0
    assert cycle_2027["total_verified_points"] == 0
    assert read_cycle(cycle_2026["id"])["status"] == "OPEN"

    _, meta = validate_paginated(
        api.list_crs_cycles(COORDINATOR_HEADERS, params={"community_id": community["id"]})
    )
    assert meta["total_count"] == 2


def test_lapsed_cycle_window_is_ignored_by_the_overlap_test(api):
    """PRD §2.11: "A candidate interval running from `cycle_start_date` through
    `cycle_end_date` inclusive may not intersect the closed interval of any cycle of
    the same community whose `status` is `OPEN`, `SUBMITTED`, `UNDER_VERIFICATION`,
    `CERTIFIED`, or `RETROGRADED`; only `LAPSED` cycles are ignored."

    PRD §3.9: "A lapse, recorded by the coordinator on a cycle still `OPEN` while
    the logical clock is strictly past `due_at` — else `ERR_CYCLE_NOT_PAST_DUE` —
    moves the cycle to the terminal `LAPSED` and resets the community's `crs_class`
    to 10."

    Design: Difficulty/resource_temporal_overlap/crs_cycle_windows_are_closed_so_shared_endpoint_is_an_overlap
    """
    community = register_community(
        name="Bayou City", state_code="TX", freeboard_ft=1.5, cumulative_period_years=10
    )
    cycle_2026 = open_cycle(
        community["id"], cycle_year=2026, cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z", due_at="2026-08-05T00:00:00Z",
    )
    set_clock("2026-08-06T00:00:00Z")
    lapsed = lapse_cycle(cycle_2026["id"])
    assert lapsed["status"] == "LAPSED"

    response = api.create_crs_cycle(
        _cycle_payload(community["id"], 2027, "2026-12-31T00:00:00Z",
                       "2027-12-31T00:00:00Z", "2027-09-30T00:00:00Z"),
        COORDINATOR_HEADERS,
    )
    cycle_2027 = validate_success(response, 201)

    assert cycle_2027["status"] == "OPEN"
    assert parse_instant(cycle_2027["cycle_start_date"]) == parse_instant("2026-12-31T00:00:00Z")
    assert read_cycle(cycle_2026["id"])["status"] == "LAPSED"


# ==========================================================================
# Inspection sweeps: intersection tested after buffer expansion
# ==========================================================================

def test_sweep_conflicts_only_after_the_seven_day_buffer_expansion(api):
    """PRD §2.11: "A candidate sweep's window is expanded to run from 7 days before
    its event date to 7 days after its event date plus its `inspection_window_days`,
    and that expanded window may not intersect the closed window running from any
    existing sweep's `disaster_event_date` through that sweep's `deadline_at`."

    PRD §2.11: "A conflict is rejected with `ERR_SWEEP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspection_sweep_windows_conflict_after_buffer_expansion
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"structure_use": "RESIDENTIAL", "pre_firm": True,
                             "construction_year": 1971, "market_value_usd": 180_000.00,
                             "highest_adjacent_grade_ft": 10.0},
    )
    first = run_sweep(
        scenario["community"]["id"], declaration_code="DR-4700-TX",
        event_date="2026-06-01T00:00:00Z", inspection_window_days=30,
    )
    assert first["inspections_created"] == 1

    response = api.open_inspection_sweep(
        scenario["community"]["id"], _sweep_payload("DR-4711-TX", "2026-07-05T00:00:00Z"),
        ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SWEEP_WINDOW_CONFLICT)

    _, conflicted = validate_paginated(
        api.list_inspections(ADMIN_HEADERS, params={"declaration_code": "DR-4711-TX"})
    )
    assert conflicted["total_count"] == 0
    _, per_structure = validate_paginated(
        api.list_inspections(
            ADMIN_HEADERS, params={"structure_id": scenario["structure"]["id"]}
        )
    )
    assert per_structure["total_count"] == 1


def test_sweep_clearing_the_expanded_window_by_one_day_is_accepted(api):
    """PRD §2.11: "A candidate sweep's window is expanded to run from 7 days before
    its event date to 7 days after its event date plus its `inspection_window_days`,
    and that expanded window may not intersect the closed window running from any
    existing sweep's `disaster_event_date` through that sweep's `deadline_at`."

    PRD §3.7: "Every `Structure` of every eligible property is swept in ascending
    `created_at` order, and each produces one `PostDisasterInspection` with `status`
    `SCHEDULED`, the sweep's `declaration_code`, `disaster_event_date` equal to the
    sweep's `event_date`, and `deadline_at` equal to that date plus
    `inspection_window_days`."

    Design: Difficulty/resource_temporal_overlap/inspection_sweep_windows_conflict_after_buffer_expansion
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"structure_use": "RESIDENTIAL", "pre_firm": True,
                             "construction_year": 1971, "market_value_usd": 180_000.00,
                             "highest_adjacent_grade_ft": 10.0},
    )
    run_sweep(
        scenario["community"]["id"], declaration_code="DR-4700-TX",
        event_date="2026-06-01T00:00:00Z", inspection_window_days=30,
    )

    response = api.open_inspection_sweep(
        scenario["community"]["id"], _sweep_payload("DR-4712-TX", "2026-07-09T00:00:00Z"),
        ADMIN_HEADERS,
    )
    sweep = validate_success(response, 201)

    assert sweep["inspections_created"] == 1
    assert len(sweep["inspection_ids"]) == 1

    inspection = validate_success(
        api.get_inspection(sweep["inspection_ids"][0], ADMIN_HEADERS), 200
    )
    assert inspection["status"] == "SCHEDULED"
    assert inspection["declaration_code"] == "DR-4712-TX"
    assert inspection["structure_id"] == scenario["structure"]["id"]
    assert parse_instant(inspection["disaster_event_date"]) == parse_instant(
        "2026-07-09T00:00:00Z"
    )
    assert_days_after(
        inspection["deadline_at"], "2026-07-09T00:00:00Z", 30, "inspection deadline_at"
    )

    _, accepted = validate_paginated(
        api.list_inspections(ADMIN_HEADERS, params={"declaration_code": "DR-4712-TX"})
    )
    assert accepted["total_count"] == 1
    _, per_structure = validate_paginated(
        api.list_inspections(
            ADMIN_HEADERS, params={"structure_id": scenario["structure"]["id"]}
        )
    )
    assert per_structure["total_count"] == 2
