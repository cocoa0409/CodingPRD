"""
Arming a publication pipeline: the state and runner gates that precede the money,
the half-open runner window with its cooldown buffer, and the closed-interval
departmental capacity cap.
"""

from test_helpers import (
    PORTAL_ADMIN_HEADERS,
    assert_credit_buckets,
    assert_money,
    fixtures,
    validate_error,
    validate_success,
)

LIBRARY_DATASET = {
    "title": "Library Circulation Statistics",
    "slug": "library-circulation",
    "description": "Library Circulation Statistics published by the department",
    "public_demand_score": 80,
    "policy_value_score": 80,
}

PARKING_DATASET = {
    "title": "Parking Meter Revenue",
    "slug": "parking-meter-revenue",
    "description": "Parking Meter Revenue published by the department",
    "public_demand_score": 75,
    "policy_value_score": 70,
}

AIR_QUALITY_DATASET = {
    "title": "Air Quality Hourly",
    "slug": "air-quality-hourly",
    "description": "Air Quality Hourly published by the department",
    "public_demand_score": 88,
    "policy_value_score": 90,
}

BIKE_DATASET = {
    "title": "Bike Counts Daily",
    "slug": "bike-counts-daily",
    "description": "Bike Counts Daily published by the department",
    "public_demand_score": 70,
    "policy_value_score": 65,
}

CRASH_DATASET = {
    "title": "Crash Reports Weekly",
    "slug": "crash-reports-weekly",
    "description": "Crash Reports Weekly published by the department",
    "public_demand_score": 84,
    "policy_value_score": 88,
}


def _publish_another_dataset(api, ctx, dataset_overrides, initial_row_count):
    """Carry a second dataset of the same department from inventory to PUBLISHED."""
    dataset = fixtures.inventory_dataset(ctx["department_id"], api=api, **dataset_overrides)
    fixtures.screen_dataset(dataset["id"], ctx["department_id"], api=api)
    fixtures.land_accepted_metadata(
        dataset["id"], ctx["license_id"], ctx["department_id"], api=api
    )
    fixtures.land_cleared_assessment(dataset["id"], api=api)
    fixtures.mark_ready(dataset["id"], ctx["department_id"], api=api)
    return fixtures.publish_dataset(
        dataset["id"], ctx["department_id"], initial_row_count=initial_row_count, api=api
    )


def _unpublished_pipeline(api):
    """A READY, never-published dataset with an unfunded department and a DRAFT pipeline."""
    ctx = fixtures.setup_ready_dataset(
        api=api, credit_units=0, dataset_overrides=LIBRARY_DATASET
    )
    runner = fixtures.create_ingest_runner(api=api)
    pipeline = fixtures.configure_pipeline(
        ctx["dataset_id"], runner["id"], ctx["department_id"], api=api
    )
    ctx["runner"] = runner
    ctx["runner_id"] = runner["id"]
    ctx["pipeline"] = pipeline
    ctx["pipeline_id"] = pipeline["id"]
    return ctx


def test_arming_reports_the_publication_gate_before_the_credit_shortfall(api):
    """A pipeline on an unpublished dataset with no credits at all reports the state.

    Arming has several preconditions: the PRD requires "that the dataset's
    `publication_status` be `PUBLISHED`, that the department's posture not be
    `SUSPENDED`, that the runner be `ACTIVE`, that both interval rules below hold, and
    that the department's `credit_balance_units` be greater than or equal to the
    pipeline's `escrow_required_units` — a shortfall is refused with
    `ERR_INSUFFICIENT_CREDITS`."

    They are not weighed simultaneously: "All validations are evaluated in the ascending
    priority order below", where transition legality sits at 13 — "The rejection is
    `ERR_INVALID_STATE_TRANSITION` in the general case, and the more specific
    `ERR_DATASET_NOT_PUBLISHED`, `ERR_PIPELINE_NOT_ARMED` or `ERR_VERSION_NOT_LIVE`
    where the guard is precisely about the dataset being published, the pipeline being
    armed, or the version being live." — while credit sufficiency only arrives at 34:
    "Credit sufficiency, on `POST /open-data/publication-pipelines/{pipelineId}/arm`:
    `ERR_INSUFFICIENT_CREDITS` (402), described in §2.10."

    The department here holds 0.00 credits against a 10.00 escrow, so both guards are
    armed and the answer must be `ERR_DATASET_NOT_PUBLISHED`.

    Design: Difficulty/priority_pair_validation_conflict/arm_state_gate_outranks_credit_shortfall
    """
    ctx = _unpublished_pipeline(api)

    validate_error(
        api.arm_pipeline(ctx["pipeline_id"], ctx["coordinator_headers"]),
        "ERR_DATASET_NOT_PUBLISHED",
        409,
    )


def test_a_refused_arming_moves_no_credits_and_reserves_no_window(api):
    """The refused request leaves the escrow unmoved and the runner unreserved.

    Only a successful arming touches the money: the PRD says "On success,
    `escrow_required_units` is subtracted from the department's `credit_balance_units`,
    added to its `credits_escrowed_units`, and recorded as the pipeline's
    `escrowed_credit_units`; the runner's `armed_window_count` increases by 1; and the
    pipeline's `version` increments."

    The pipeline must therefore still be the `DRAFT` it was configured as — "The new
    pipeline starts at `status` `DRAFT` with `escrowed_credit_units` 0.00,
    `consecutive_failure_count` 0 and `suspend_reason` null." — while still advertising
    the 10.00 a `WEEKLY` cadence requires.

    Design: Difficulty/priority_pair_validation_conflict/arm_state_gate_outranks_credit_shortfall
    """
    ctx = _unpublished_pipeline(api)
    validate_error(
        api.arm_pipeline(ctx["pipeline_id"], ctx["coordinator_headers"]),
        "ERR_DATASET_NOT_PUBLISHED",
        409,
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "DRAFT", (
        f"A refused arming must leave the pipeline DRAFT, got {pipeline['status']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")
    assert_money(pipeline["escrow_required_units"], 10.00, "escrow_required_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=0.00, balance=0.00, escrowed=0.00, consumed=0.00)

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"No window may be reserved, got armed_window_count {runner['armed_window_count']}"
    )


def test_arming_refused_while_the_ingest_runner_is_draining(api):
    """A worker taken out of service cannot accept a new armed window.

    The PRD: "Only a runner whose `status` is `ACTIVE` may have a pipeline armed or
    resumed against it, or a run started on it; otherwise the request is refused with
    `ERR_RUNNER_NOT_ACTIVE`." Taking the runner to `DRAINING` therefore blocks the
    arming even though the dataset is published, the department is funded and the window
    is free — and, the refusal being total, no escrow moves.

    Design: Difficulty/cross_entity_state_dependency/arm_requires_active_runner
    """
    ctx = fixtures.setup_published_dataset(api=api)
    runner = fixtures.create_ingest_runner(api=api)
    pipeline = fixtures.configure_pipeline(
        ctx["dataset_id"], runner["id"], ctx["department_id"], api=api
    )
    fixtures.update_ingest_runner(runner["id"], api=api, status="DRAINING")

    validate_error(
        api.arm_pipeline(pipeline["id"], ctx["coordinator_headers"]),
        "ERR_RUNNER_NOT_ACTIVE",
        409,
    )

    unchanged = fixtures.read_pipeline(pipeline["id"], api=api)
    assert unchanged["status"] == "DRAFT", (
        f"Expected the pipeline to stay DRAFT, got {unchanged['status']}"
    )
    assert_money(unchanged["escrowed_credit_units"], 0.00, "escrowed_credit_units")
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, balance=100.00, escrowed=0.00)


def test_arming_succeeds_once_the_runner_returns_to_active(api):
    """Returning the worker to service makes the same request legal and moves the escrow.

    The PRD: "The office may later update the runner's `status` — to `DRAINING` or
    `OFFLINE` to take it out of service, or back to `ACTIVE` — and may adjust
    `cooldown_minutes`". With the runner `ACTIVE` again the arming succeeds, and the
    10.00 a `WEEKLY` cadence escrows moves out of the balance into the escrow bucket
    while the runner books its window.

    Design: Difficulty/cross_entity_state_dependency/arm_requires_active_runner
    """
    ctx = fixtures.setup_published_dataset(api=api)
    runner = fixtures.create_ingest_runner(api=api)
    pipeline = fixtures.configure_pipeline(
        ctx["dataset_id"], runner["id"], ctx["department_id"], api=api
    )
    fixtures.update_ingest_runner(runner["id"], api=api, status="DRAINING")
    validate_error(
        api.arm_pipeline(pipeline["id"], ctx["coordinator_headers"]),
        "ERR_RUNNER_NOT_ACTIVE",
        409,
    )

    reactivated = fixtures.update_ingest_runner(runner["id"], api=api, status="ACTIVE")
    assert reactivated["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {reactivated['status']}"
    )

    armed = validate_success(api.arm_pipeline(pipeline["id"], ctx["coordinator_headers"]))
    assert armed["status"] == "ARMED", f"Expected ARMED, got {armed['status']}"
    assert_money(armed["escrowed_credit_units"], 10.00, "escrowed_credit_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=90.00, escrowed=10.00)
    runner_after = validate_success(api.get_ingest_runner(runner["id"], PORTAL_ADMIN_HEADERS))
    assert runner_after["armed_window_count"] == 1, (
        f"Expected armed_window_count 1, got {runner_after['armed_window_count']}"
    )


def test_window_starting_inside_the_cooldown_buffer_conflicts_on_the_runner(api):
    """The occupant's reservation runs past its own window by the runner's cooldown.

    The PRD: "Each occupant on the same runner — meaning every other pipeline on that
    runner whose `status` is `ARMED` or `SUSPENDED`, since a suspended pipeline keeps
    its reservation — occupies the span from its own `window_start_minute` up to but
    excluding its own `window_end_minute` plus the runner's `cooldown_minutes`." and "If
    the candidate's span and any occupant's span share even one minute, the request is
    refused with `ERR_RUNNER_WINDOW_CONFLICT`."

    The armed occupant runs 540 to 660 on a runner with a 15-minute cooldown, so it
    holds minutes 540 through 674. A candidate opening at 670 shares five of those
    minutes and must be refused, leaving its own escrow unmoved.

    Design: Difficulty/resource_temporal_overlap/runner_window_half_open_with_cooldown_buffer_adjacency
    """
    ctx = fixtures.setup_armed_pipeline(api=api)
    second = _publish_another_dataset(api, ctx, PARKING_DATASET, 30000)
    candidate = fixtures.configure_pipeline(
        second["id"], ctx["runner_id"], ctx["department_id"], api=api, window_start_minute=670
    )

    validate_error(
        api.arm_pipeline(candidate["id"], ctx["coordinator_headers"]),
        "ERR_RUNNER_WINDOW_CONFLICT",
        409,
    )

    refused = fixtures.read_pipeline(candidate["id"], api=api)
    assert refused["status"] == "DRAFT", (
        f"The conflicting candidate must stay DRAFT, got {refused['status']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, balance=90.00, escrowed=10.00)


def test_window_opening_exactly_at_the_buffer_boundary_is_armed(api):
    """Exact-boundary adjacency after the cooldown is legal, and reconfiguring supersedes.

    The PRD: "Because both spans exclude their upper endpoint, a candidate that begins
    at exactly the minute where an occupant's window plus cooldown ends is accepted:
    exact-boundary adjacency after the buffer is legal."

    Reconfiguring the second dataset at 675 also replaces its refused pipeline, because
    "Configuring a pipeline also supersedes whatever configuration the dataset had: any
    existing pipeline of that dataset in `DRAFT`, `ARMED` or `SUSPENDED` is moved to
    `DECOMMISSIONED` with its escrow released, and the new pipeline records that
    predecessor's identifier in `superseded_pipeline_id`." Two armed windows on the one
    runner then leave it counting two reservations and the department holding 20.00 in
    escrow.

    Design: Difficulty/resource_temporal_overlap/runner_window_half_open_with_cooldown_buffer_adjacency
    """
    ctx = fixtures.setup_armed_pipeline(api=api)
    second = _publish_another_dataset(api, ctx, PARKING_DATASET, 30000)
    first_candidate = fixtures.configure_pipeline(
        second["id"], ctx["runner_id"], ctx["department_id"], api=api, window_start_minute=670
    )
    validate_error(
        api.arm_pipeline(first_candidate["id"], ctx["coordinator_headers"]),
        "ERR_RUNNER_WINDOW_CONFLICT",
        409,
    )

    replacement = fixtures.configure_pipeline(
        second["id"], ctx["runner_id"], ctx["department_id"], api=api, window_start_minute=675
    )
    assert replacement["superseded_pipeline_id"] == first_candidate["id"], (
        f"Expected the refused pipeline to be recorded as superseded, "
        f"got {replacement['superseded_pipeline_id']!r}"
    )
    assert replacement["window_end_minute"] == 795, (
        f"Expected window_end_minute 795, got {replacement['window_end_minute']}"
    )
    superseded = fixtures.read_pipeline(first_candidate["id"], api=api)
    assert superseded["status"] == "DECOMMISSIONED", (
        f"Expected the predecessor DECOMMISSIONED, got {superseded['status']}"
    )

    armed = validate_success(api.arm_pipeline(replacement["id"], ctx["coordinator_headers"]))
    assert armed["status"] == "ARMED", f"Expected ARMED, got {armed['status']}"

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 2, (
        f"Expected armed_window_count 2, got {runner['armed_window_count']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=80.00, escrowed=20.00, consumed=0.00)


def test_third_departmental_window_touching_at_one_minute_breaches_capacity(api):
    """Under the departmental rule a single shared endpoint minute already collides.

    The PRD: "Here each of the same department's `ARMED` pipelines is treated as
    covering the closed span of minutes from its `window_start_minute` through its
    `window_end_minute` inclusive, and the candidate is treated the same way." and
    "Counting the candidate together with all of those, no single minute may be covered
    by more than two windows — that is, at most one other armed pipeline of the
    department may share any minute with the candidate."

    Two windows are already armed on separate runners, 540 to 660 and 600 to 720. A
    candidate at 660 to 780 sits on a third, entirely free runner, so the runner rule
    has nothing to say; minute 660 would nevertheless be covered three times, and the
    refusal must be `ERR_DEPARTMENT_WINDOW_CAPACITY` rather than
    `ERR_RUNNER_WINDOW_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/department_window_closed_interval_capacity_cap
    """
    ctx = fixtures.setup_armed_pipeline(
        api=api,
        dataset_overrides=AIR_QUALITY_DATASET,
        runner_overrides={"name": "ingest-runner-a"},
    )
    bike = _publish_another_dataset(api, ctx, BIKE_DATASET, 20000)
    runner_b = fixtures.create_ingest_runner(api=api, name="ingest-runner-b")
    pipeline_b = fixtures.configure_pipeline(
        bike["id"], runner_b["id"], ctx["department_id"], api=api, window_start_minute=600
    )
    validate_success(api.arm_pipeline(pipeline_b["id"], ctx["coordinator_headers"]))

    crash = _publish_another_dataset(api, ctx, CRASH_DATASET, 40000)
    runner_c = fixtures.create_ingest_runner(api=api, name="ingest-runner-c")
    candidate = fixtures.configure_pipeline(
        crash["id"], runner_c["id"], ctx["department_id"], api=api, window_start_minute=660
    )

    validate_error(
        api.arm_pipeline(candidate["id"], ctx["coordinator_headers"]),
        "ERR_DEPARTMENT_WINDOW_CAPACITY",
        409,
    )

    refused = fixtures.read_pipeline(candidate["id"], api=api)
    assert refused["status"] == "DRAFT", (
        f"The over-capacity candidate must stay DRAFT, got {refused['status']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, balance=80.00, escrowed=20.00)


def test_shifting_the_candidate_one_minute_past_the_touch_point_arms(api):
    """Opening at 661 leaves every minute covered at most twice.

    The PRD: "Because these spans include both endpoints, two windows that merely touch
    at a single minute *do* collide under this rule, unlike the runner rule." Moving the
    candidate to 661 to 781 hands minute 660 back to the two windows that already share
    it and keeps the candidate's own span paired with only one of them, so the third
    arming succeeds and the department's escrow reaches 30.00.

    Design: Difficulty/resource_temporal_overlap/department_window_closed_interval_capacity_cap
    """
    ctx = fixtures.setup_armed_pipeline(
        api=api,
        dataset_overrides=AIR_QUALITY_DATASET,
        runner_overrides={"name": "ingest-runner-a"},
    )
    bike = _publish_another_dataset(api, ctx, BIKE_DATASET, 20000)
    runner_b = fixtures.create_ingest_runner(api=api, name="ingest-runner-b")
    pipeline_b = fixtures.configure_pipeline(
        bike["id"], runner_b["id"], ctx["department_id"], api=api, window_start_minute=600
    )
    validate_success(api.arm_pipeline(pipeline_b["id"], ctx["coordinator_headers"]))

    crash = _publish_another_dataset(api, ctx, CRASH_DATASET, 40000)
    runner_c = fixtures.create_ingest_runner(api=api, name="ingest-runner-c")
    first_candidate = fixtures.configure_pipeline(
        crash["id"], runner_c["id"], ctx["department_id"], api=api, window_start_minute=660
    )
    validate_error(
        api.arm_pipeline(first_candidate["id"], ctx["coordinator_headers"]),
        "ERR_DEPARTMENT_WINDOW_CAPACITY",
        409,
    )

    replacement = fixtures.configure_pipeline(
        crash["id"], runner_c["id"], ctx["department_id"], api=api, window_start_minute=661
    )
    assert replacement["superseded_pipeline_id"] == first_candidate["id"], (
        f"Expected the refused pipeline recorded as superseded, "
        f"got {replacement['superseded_pipeline_id']!r}"
    )

    armed = validate_success(api.arm_pipeline(replacement["id"], ctx["coordinator_headers"]))
    assert armed["status"] == "ARMED", f"Expected ARMED, got {armed['status']}"
    assert_money(armed["escrowed_credit_units"], 10.00, "escrowed_credit_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=70.00, escrowed=30.00, consumed=0.00)
    runner_after = validate_success(api.get_ingest_runner(runner_c["id"], PORTAL_ADMIN_HEADERS))
    assert runner_after["armed_window_count"] == 1, (
        f"Expected armed_window_count 1 on the third runner, "
        f"got {runner_after['armed_window_count']}"
    )
