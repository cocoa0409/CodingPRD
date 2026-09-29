"""Endpoint surfaces: pagination envelope, bulk scans, links and conditional writes."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_4,
    OWNER_5,
    OWNER_6,
    OWNER_7,
    UNKNOWN_ID,
    ApiErrorId,
    assert_cents,
    assert_pagination_meta,
    assert_pct,
    assert_remediation_task,
    factories,
    find_by,
    fixtures,
    make_resource_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_record_list_pages_at_ten_and_refuses_a_limit_outside_its_bounds(api):
    """Eleven rows expose the default page, both limit bounds and a past-the-end offset.

    PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
    may not be lower than 1, and may not be higher than 100. `offset` is the
    number of items to skip and defaults to 0."

    Design: Corner/endpoints/cost_record_listing_honours_the_default_limit_and_rejects_out_of_range_limits
    """
    fixtures.set_clock(api)
    for cents in range(100, 1200, 100):
        fixtures.create_untagged_record(api, cents)

    first_page, meta = validate_paginated(api.list_cost_records(ANALYST_HEADERS))
    assert len(first_page) == 10
    assert_pagination_meta(meta, total_count=11, has_more=True, limit=10, offset=0)

    last_page, last_meta = validate_paginated(
        api.list_cost_records(ANALYST_HEADERS, {"offset": 10})
    )
    assert len(last_page) == 1
    assert_pagination_meta(last_meta, total_count=11, has_more=False, offset=10)

    everything, all_meta = validate_paginated(
        api.list_cost_records(ANALYST_HEADERS, {"limit": 100})
    )
    assert len(everything) == 11
    assert_pagination_meta(all_meta, total_count=11, has_more=False, limit=100)

    over_max = api.list_cost_records(ANALYST_HEADERS, {"limit": 101})
    validate_error(over_max, ApiErrorId.INVALID_REQUEST.value, 400)

    under_min = api.list_cost_records(ANALYST_HEADERS, {"limit": 0})
    validate_error(under_min, ApiErrorId.INVALID_REQUEST.value, 400)

    past_end, past_meta = validate_paginated(
        api.list_cost_records(ANALYST_HEADERS, {"offset": 11})
    )
    assert past_end == []
    assert_pagination_meta(past_meta, total_count=11, has_more=False, offset=11)

    for row in everything:
        assert row["allocation_state"] == "UNALLOCATED"
        assert row["business_unit_id"] is None
        assert_cents(
            row["effective_cost_cents"], row["list_cost_cents"], "effective_cost_cents"
        )


def test_one_idle_sweep_flags_only_the_two_resources_that_clear_both_screens(api):
    """The scan skips the cheap resource and the healthy one, and orders the rest.

    PRD §3.8: "A resource whose `monthly_run_rate_cents` is below 20,000 cents
    is skipped as too small to bother with. Above that floor, utilization
    decides the verdict: a resource whose `utilization_pct` is at or below 5.00
    is idle and draws an `IDLE_TERMINATE` proposal whose
    `projected_savings_cents` is the full `monthly_run_rate_cents`, rounded half
    up to whole cents; a resource whose `utilization_pct` is above 5.00 but at
    or below 30.00 is oversized and draws a `RIGHTSIZE` proposal whose
    `projected_savings_cents` is half of `monthly_run_rate_cents`, rounded half
    up to whole cents; a resource above 30.00 is left alone."

    Design: Corner/endpoints/idle_scan_emits_one_task_per_flagged_resource_and_skips_the_rest
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)

    idle = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_4,
        resource_kind="COMPUTE",
        requested_tags={"team": "ops", "environment": "dev", "application": "batch"},
        monthly_run_rate_cents=1000000,
    )
    fixtures.set_utilization(api, idle["id"], 2.00)

    oversized = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_5,
        resource_kind="DATABASE",
        requested_tags={"team": "ops", "environment": "prod", "application": "ledger"},
        monthly_run_rate_cents=40000,
    )
    fixtures.set_utilization(api, oversized["id"], 20.00)

    too_cheap = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_6,
        resource_kind="STORAGE",
        requested_tags={"team": "ops", "environment": "dev", "application": "logs"},
        monthly_run_rate_cents=10000,
    )
    fixtures.set_utilization(api, too_cheap["id"], 1.00)

    healthy = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_7,
        resource_kind="COMPUTE",
        requested_tags={"team": "ops", "environment": "dev", "application": "api"},
        monthly_run_rate_cents=30000,
    )

    tasks = validate_success(
        api.run_idle_detection_scan({"business_unit_id": unit["id"]}, ANALYST_HEADERS)
    )
    assert len(tasks) == 2

    assert tasks[0]["cloud_resource_id"] == idle["id"]
    assert_remediation_task(
        tasks[0],
        kind="IDLE_TERMINATE",
        status="PROPOSED",
        observed_utilization_pct=2.00,
        projected_savings_cents=1000000,
        waste_score=98.80,
        auto_remediation_eligible=True,
    )

    assert tasks[1]["cloud_resource_id"] == oversized["id"]
    assert_remediation_task(
        tasks[1],
        kind="RIGHTSIZE",
        status="PROPOSED",
        observed_utilization_pct=20.00,
        projected_savings_cents=20000,
        waste_score=49.60,
        auto_remediation_eligible=False,
    )

    resources, _ = validate_paginated(
        api.list_cloud_resources(ANALYST_HEADERS, {"business_unit_id": unit["id"]})
    )
    assert find_by(resources, id=idle["id"])["lifecycle_state"] == "FLAGGED_IDLE"
    assert find_by(resources, id=oversized["id"])["lifecycle_state"] == "RIGHTSIZE_PENDING"
    assert find_by(resources, id=too_cheap["id"])["lifecycle_state"] == "ACTIVE"
    assert find_by(resources, id=healthy["id"])["lifecycle_state"] == "ACTIVE"

    _, cheap_meta = validate_paginated(
        api.list_remediation_tasks(ANALYST_HEADERS, {"cloud_resource_id": too_cheap["id"]})
    )
    assert cheap_meta["total_count"] == 0


def test_a_manual_adjustment_is_missed_from_the_path_and_from_the_body(api):
    """An unknown run and an unknown unit fail at different rungs with different ids.

    PRD §2.10: "Every foreign reference supplied in a request body must resolve
    to an existing row, and the failure carries the matching 404 for the
    referenced entity."

    Design: Corner/endpoints/manual_adjustment_needs_both_the_run_and_the_unit_to_exist
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    record = fixtures.create_untagged_record(api, 2000)
    built = fixtures.shared_pool_run(
        api, [unit["id"]], [record["id"]], mode="SHOWBACK", do_seal=False
    )
    run_version = built["run"]["version"]

    unknown_run = api.create_manual_adjustment(
        UNKNOWN_ID,
        factories.manual_adjustment_payload(run_version, unit["id"], 500),
        CONTROLLER_HEADERS,
    )
    validate_error(unknown_run, ApiErrorId.ALLOCATION_RUN_NOT_FOUND.value, 404)

    unknown_unit = api.create_manual_adjustment(
        built["run"]["id"],
        factories.manual_adjustment_payload(run_version, UNKNOWN_ID, 500),
        CONTROLLER_HEADERS,
    )
    validate_error(unknown_unit, ApiErrorId.BUSINESS_UNIT_NOT_FOUND.value, 404)

    created = validate_success(
        api.create_manual_adjustment(
            built["run"]["id"],
            factories.manual_adjustment_payload(run_version, unit["id"], 500),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert created["allocation_run_id"] == built["run"]["id"]
    assert created["business_unit_id"] == unit["id"]
    assert created["line_kind"] == "MANUAL_ADJUSTMENT"
    assert_cents(created["allocated_cents"], 500, "allocated_cents")
    assert created["memo"] == "true-up"

    lines, meta = validate_paginated(
        api.list_allocation_lines(
            CONTROLLER_HEADERS,
            {"allocation_run_id": built["run"]["id"], "business_unit_id": unit["id"]},
        )
    )
    assert meta["total_count"] == 2
    shared_line = find_by(lines, line_kind="SHARED")
    assert_cents(shared_line["allocated_cents"], 2000, "allocated_cents")

    run = validate_success(api.get_allocation_run(built["run"]["id"], CONTROLLER_HEADERS))
    assert_cents(run["total_allocated_cents"], 2000, "total_allocated_cents")


def test_telemetry_revives_a_resized_resource_only_above_the_rightsizing_ceiling(api):
    """The same endpoint records 20.00 without moving and restores service at 40.00.

    PRD §3.8: "A resized resource is not stranded. When telemetry later reports
    a submitted `utilization_pct` strictly above 30.00, the resource moves
    `RESIZED → ACTIVE` and the new utilization is stored — at which point a
    later scan may flag it all over again."

    Design: Corner/endpoints/telemetry_returns_a_resized_resource_to_active_only_above_the_rightsizing_threshold
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    built = fixtures.flag_idle_resource(
        api,
        unit["id"],
        policy["id"],
        OWNER_5,
        utilization_pct=20.00,
        monthly_run_rate_cents=40000,
        resource_kind="DATABASE",
        requested_tags={"team": "ops", "environment": "prod", "application": "ledger"},
    )
    task_id = built["task"]["id"]
    resource_id = built["resource"]["id"]
    assert built["task"]["kind"] == "RIGHTSIZE"

    validate_success(api.notify_owner(task_id, ANALYST_HEADERS))
    validate_success(
        api.approve_remediation_task(task_id, make_resource_owner_headers(OWNER_5))
    )
    validate_success(api.run_remediation_window_sweep(ANALYST_HEADERS))

    executed = validate_success(api.get_remediation_task(task_id, ANALYST_HEADERS))
    assert executed["status"] == "EXECUTED"
    assert_cents(executed["realized_savings_cents"], 20000, "realized_savings_cents")

    resized = validate_success(api.get_cloud_resource(resource_id, ANALYST_HEADERS))
    assert resized["lifecycle_state"] == "RESIZED"
    assert_cents(resized["monthly_run_rate_cents"], 20000, "monthly_run_rate_cents")

    still_resized = validate_success(
        api.patch_cloud_resource_telemetry(
            resource_id, {"utilization_pct": 20.00}, ADMIN_HEADERS
        )
    )
    assert_pct(still_resized["utilization_pct"], 20.00, "utilization_pct")
    assert still_resized["lifecycle_state"] == "RESIZED"

    revived = validate_success(
        api.patch_cloud_resource_telemetry(
            resource_id, {"utilization_pct": 40.00}, ADMIN_HEADERS
        )
    )
    assert_pct(revived["utilization_pct"], 40.00, "utilization_pct")
    assert revived["lifecycle_state"] == "ACTIVE"

    owner_unit = validate_success(api.get_business_unit(unit["id"], ADMIN_HEADERS))
    assert_cents(owner_unit["tracked_run_rate_cents"], 20000, "tracked_run_rate_cents")
    assert owner_unit["resource_count"] == 1
