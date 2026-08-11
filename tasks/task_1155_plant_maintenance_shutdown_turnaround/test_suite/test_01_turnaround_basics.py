"""Turnaround and work-item foundations: creation defaults, listing pagination,
filtering, server-minted system fields, not-found, authentication, and the
test-driving clock."""
from datetime import datetime, timezone

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_turnaround,
    assert_worker,
    validate_error,
    validate_paginated,
    validate_success,
    create_turnaround_payload,
    create_work_item_payload,
    create_contractor_payload,
    create_worker_payload,
    create_shift_payload,
    create_isolation_payload,
    create_laydown_area_payload,
    create_reservation_payload,
    make_supervisor_headers,
)


def test_turnaround_create_returns_system_defaults(api, manager_headers):
    """PRD §3.1: "A new turnaround begins with `status` of `PLANNING`,
    `cost_posture` of `WITHIN_BUDGET`, `committed_cost_cents` and
    `reported_cost_cents` of zero, `critical_path_slip_hours` of zero,
    `schedule_run_index` of zero, and `scope_frozen_at` and `handed_over_at`
    both null."
    PRD §2.5: "`version` (integer): starts at 1 at creation and increments by
    exactly one on every mutation, including mutations caused by cascades
    originating on other resources."

    Design: Corner/entities/turnaround_create_defaults
    """
    resp = api.create_turnaround(
        create_turnaround_payload(
            name="TA-DEF",
            authorized_budget_cents=500000,
            contingency_budget_cents=100000,
        ),
        manager_headers,
    )
    data = validate_success(resp, 201)
    assert_turnaround(data)
    assert data["status"] == "PLANNING"
    assert data["cost_posture"] == "WITHIN_BUDGET"
    assert data["committed_cost_cents"] == 0
    assert data["reported_cost_cents"] == 0
    assert data["critical_path_slip_hours"] == 0
    assert data["schedule_run_index"] == 0
    assert data["version"] == 1
    assert data["scope_frozen_at"] is None
    assert data["handed_over_at"] is None


def test_turnaround_get_unknown_id_returns_not_found(api, manager_headers):
    """PRD §2.9: "The first identifier that does not resolve to an existing
    resource produces `ERR_NOT_FOUND` immediately, before any later identifier
    is examined and before any business rule runs."

    Design: Corner/entities/turnaround_get_not_found_returns_404
    """
    resp = api.get_turnaround(NON_EXISTENT_UUID, manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_work_item_create_missing_title_returns_invalid_request(
    api, manager_headers, planner_headers
):
    """PRD §3.1: "Each proposed item carries a `title`, a `system_area` tag, a
    `work_type` of `CORRECTIVE`, `PREVENTIVE`, `INSPECTION`, or
    `DISCOVERY_ADDENDUM`, a `risk_class` of `A`, `B`, or `C` — `A` marking the
    highest risk — a strictly positive `estimated_hours`, a non-negative
    `estimated_cost_cents`, and an optional `requires_permit` flag that
    defaults to false."
    PRD §2.8: "Request shape: required fields are present, enum members are
    valid, quantities are positive where required, and windows start before
    they end; failure yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/work_item_create_missing_required_returns_invalid_request
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-RQ"), manager_headers),
        201,
    )
    payload = create_work_item_payload(system_area="CRU-2-X")
    del payload["title"]
    resp = api.create_work_item(ta["id"], payload, planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_work_item_create_ignores_client_supplied_rank_score(
    api, manager_headers, planner_headers
):
    """PRD §3.1: "A proposed item starts in `PROPOSED` with `rank_score` and
    `rank_position` still null, `is_critical_path` false, and `actual_hours`,
    `planned_shift_id`, and `discovery_id` all null."

    Design: Corner/entities/work_item_create_rank_score_input_ignored
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-CI"), manager_headers),
        201,
    )
    payload = create_work_item_payload(
        title="Gasket swap", risk_class="C", estimated_hours=8,
        estimated_cost_cents=9000,
    )
    payload["rank_score"] = 999999  # computed-only field; must not be honored
    resp = api.create_work_item(ta["id"], payload, planner_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "PROPOSED"
    assert data["rank_score"] is None, "client-supplied rank_score must be ignored"
    assert data["rank_position"] is None


def test_work_items_list_paginates_with_limit_and_offset(
    api, manager_headers, planner_headers
):
    """PRD §2.3: "The `meta` object of every list response carries the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a
    client can always tell how many records exist in total and whether further
    pages remain."

    Design: Corner/entities/work_items_list_pagination
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-PG"), manager_headers),
        201,
    )
    for i, (wt, rc, hrs, cost) in enumerate([
        ("CORRECTIVE", "A", 10, 10000),
        ("PREVENTIVE", "B", 20, 20000),
        ("INSPECTION", "C", 30, 30000),
    ]):
        validate_success(
            api.create_work_item(
                ta["id"],
                create_work_item_payload(
                    title=f"Item {i+1}", system_area=chr(ord("A") + i),
                    work_type=wt, risk_class=rc, estimated_hours=hrs,
                    estimated_cost_cents=cost,
                ),
                planner_headers,
            ),
            201,
        )

    page1, meta1 = validate_paginated(
        api.list_work_items(ta["id"], planner_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_work_items(ta["id"], planner_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 must hold 1 row, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["id"] not in {row["id"] for row in page1}


def test_work_items_list_filters_by_status(api, manager_headers, planner_headers):
    """PRD §4: "List a turnaround's work items; filterable by `status`,
    `work_type`, `is_critical_path`".
    PRD §3.1: "Every item whose `rank_position` is less than or equal to
    `scope_cutoff_count` — the cutoff is inclusive — transitions from
    `PROPOSED` to `FROZEN` and enters the committed scope; all remaining
    `PROPOSED` items become `DEFERRED`."

    Design: Corner/entities/work_items_list_filter_status
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-FL"), manager_headers),
        201,
    )
    wa = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="High risk", system_area="A", work_type="CORRECTIVE",
                risk_class="A", estimated_hours=10, estimated_cost_cents=120000,
            ),
            planner_headers,
        ),
        201,
    )
    wb = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="Low risk", system_area="B", work_type="PREVENTIVE",
                risk_class="C", estimated_hours=20, estimated_cost_cents=40000,
            ),
            planner_headers,
        ),
        201,
    )
    validate_success(
        api.freeze_scope(ta["id"], {"scope_cutoff_count": 1}, manager_headers)
    )

    deferred, meta = validate_paginated(
        api.list_work_items(ta["id"], planner_headers, params={"status": "DEFERRED"})
    )
    assert meta["total_count"] == 1
    assert len(deferred) == 1
    assert deferred[0]["id"] == wb["id"], (
        "the lower-ranked item (rank_position 2 > cutoff 1) must be the DEFERRED one"
    )

    all_items, all_meta = validate_paginated(
        api.list_work_items(ta["id"], planner_headers)
    )
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in all_items} == {wa["id"], wb["id"]}


def test_worker_create_generates_system_fields(api, manager_headers, planner_headers):
    """PRD §3.2: "A supervisor registers a worker under their own contractor by
    supplying the worker's `full_name` and `trade`; the new worker's
    `contractor_id` ties them to the employing contractor and their
    `badge_status` begins as `REGISTERED`."
    PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
    assigned at creation."

    Design: Corner/entities/worker_create_system_fields_generated
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-SF"), manager_headers),
        201,
    )
    validate_success(
        api.create_work_item(ta["id"], create_work_item_payload(), planner_headers),
        201,
    )
    validate_success(
        api.freeze_scope(ta["id"], {"scope_cutoff_count": 1}, manager_headers)
    )
    contractor = validate_success(
        api.create_contractor(
            ta["id"],
            create_contractor_payload(headcount_cap=3),
            manager_headers,
        ),
        201,
    )

    resp = api.register_worker(
        contractor["id"],
        create_worker_payload(),
        make_supervisor_headers(contractor["id"]),
    )
    worker = validate_success(resp, 201)
    assert_worker(worker)
    assert worker["badge_status"] == "REGISTERED"
    assert worker["version"] == 1
    assert worker["fatigue_penalty_score"] == 0
    assert worker["ledger_hours"] == 0
    assert worker["total_shift_hours"] == 0
    assert worker["contractor_id"] == contractor["id"]


def test_shift_create_rejects_unknown_shift_type(api, manager_headers, planner_headers):
    """PRD §3.3: "Each shift is defined by its `shift_date` in year-month-day
    form, a `shift_type` of `DAY` or `NIGHT`, its `starts_at` and `ends_at`
    instants — the end must be strictly after the start — and a
    `planned_headcount` of at least one, the maximum number of non-cancelled
    crew the shift will carry."
    PRD §2.8: "Request shape: required fields are present, enum members are
    valid, quantities are positive where required, and windows start before
    they end; failure yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/shift_create_invalid_enum_returns_invalid_request
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-EN"), manager_headers),
        201,
    )
    payload = create_shift_payload(shift_type="MIDDAY", planned_headcount=2)
    resp = api.create_shift(ta["id"], payload, planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_worker_create_under_unknown_contractor_returns_not_found(api):
    """PRD §2.9: "Requests that target nested resources are validated strictly
    left-to-right along the path. The first identifier that does not resolve to
    an existing resource produces `ERR_NOT_FOUND` immediately, before any later
    identifier is examined and before any business rule runs."

    Design: Corner/entities/worker_create_unknown_contractor_not_found
    """
    resp = api.register_worker(
        NON_EXISTENT_UUID,
        create_worker_payload(full_name="Ghost Worker"),
        make_supervisor_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_created_entities_land_in_initial_states(
    api, manager_headers, planner_headers, coordinator_headers
):
    """PRD §3.1: "A new turnaround begins with `status` of `PLANNING`" and "A
    proposed item starts in `PROPOSED`".
    PRD §3.4: "A new isolation is `PLANNED`, and its lifecycle runs `PLANNED`,
    `ISOLATED`, `VERIFIED`, and the terminal `DEISOLATED`."
    PRD §3.2: "An invited contractor begins with `mobilization_status` of
    `INVITED` and `badged_headcount` of zero".
    PRD §3.3: "A shift is born `PLANNED`".
    PRD §3.7: "A successful reservation is created `RESERVED`, the area's
    `occupied_sqm` rises by `area_sqm`, and the area's `version` increments by
    one, recorded on each reservation as `laydown_area_id`."

    Design: Corner/state_machines/initial_states_on_create
    """
    ta = validate_success(
        api.create_turnaround(create_turnaround_payload(name="TA-IN"), manager_headers),
        201,
    )
    assert ta["status"] == "PLANNING"

    item = validate_success(
        api.create_work_item(ta["id"], create_work_item_payload(), planner_headers),
        201,
    )
    assert item["status"] == "PROPOSED"

    validate_success(
        api.freeze_scope(ta["id"], {"scope_cutoff_count": 1}, manager_headers)
    )

    isolation = validate_success(
        api.create_isolation(
            ta["id"],
            create_isolation_payload(
                equipment_tag="V-101", isolated_until="2026-06-20T00:00:00Z"
            ),
            coordinator_headers,
        ),
        201,
    )
    assert isolation["status"] == "PLANNED"

    contractor = validate_success(
        api.create_contractor(
            ta["id"], create_contractor_payload(headcount_cap=3), manager_headers
        ),
        201,
    )
    assert contractor["mobilization_status"] == "INVITED"

    shift = validate_success(
        api.create_shift(ta["id"], create_shift_payload(planned_headcount=2), planner_headers),
        201,
    )
    assert shift["status"] == "PLANNED"

    area = validate_success(
        api.create_laydown_area(
            ta["id"], create_laydown_area_payload(capacity_sqm=300), manager_headers
        ),
        201,
    )
    reservation_payload = create_reservation_payload(
        area_sqm=40, window_until="2026-06-18T00:00:00Z"
    )
    reservation_payload["expected_laydown_area_version"] = area["version"]
    reservation = validate_success(
        api.create_reservation(area["id"], reservation_payload, planner_headers),
        201,
    )
    assert reservation["status"] == "RESERVED"


def test_clock_set_echoes_installed_logical_time(api, manager_headers):
    """PRD §2.4: "A `TurnaroundManager` may move the logical clock through an
    administrative test-driving capability that accepts a `to_iso8601` instant;
    the response echoes the new time as `current_utc`."

    PRD pins the echoed *time* (the installed instant), not a byte-exact
    rendering, so the echo is compared as a parsed instant.

    Design: Corner/endpoints/clock_set_roundtrip
    """
    resp = api.set_clock({"to_iso8601": "2026-06-01T12:30:00Z"}, manager_headers)
    data = validate_success(resp)
    echoed = datetime.fromisoformat(data["current_utc"].replace("Z", "+00:00"))
    assert echoed == datetime(2026, 6, 1, 12, 30, 0, tzinfo=timezone.utc), (
        f"current_utc must echo the installed instant, got {data['current_utc']}"
    )


def test_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    resp = api.create_turnaround(
        create_turnaround_payload(
            name="TA-NA",
            authorized_budget_cents=500000,
            contingency_budget_cents=100000,
        ),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
