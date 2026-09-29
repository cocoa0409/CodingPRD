"""
The refusals that guard a run and the reviews around it: a run started before its
slot, a window that would run past midnight, an arming with an empty ledger, a
clearance submitted without a measurement, a publication behind a retired licence,
and the two faces of the departmental posture gate.

Every refusal here is asserted to be total — the target entity keeps its state and
the department's four credit buckets keep their balances.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    PRIVACY_ASSESSOR_HEADERS,
    assert_credit_buckets,
    assert_dataset_states,
    assert_money,
    assert_posture,
    assert_priority,
    assert_scorecard_balanced,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

SLOT_INSIDE_WINDOW = "2026-08-01T09:00:00Z"

TRAFFIC_DATASET = {
    "title": "Weekly Traffic Counts",
    "slug": "weekly-traffic-counts",
    "description": "Weekly Traffic Counts published by the department",
    "public_demand_score": 92,
    "policy_value_score": 96,
}

LIBRARY_DATASET = {
    "title": "Library Circulation Statistics",
    "slug": "library-circulation",
    "description": "Library Circulation Statistics published by the department",
    "public_demand_score": 20,
    "policy_value_score": 20,
}

CRASH_DATASET = {
    "title": "Crash Reports Weekly",
    "slug": "crash-reports-weekly",
    "description": "Crash Reports Weekly published by the department",
    "public_demand_score": 92,
    "policy_value_score": 96,
}


def _carry_sibling_to_published(api, ctx, dataset_overrides, initial_row_count=50000):
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


def test_starting_a_run_nine_hours_before_its_scheduled_instant_is_refused(api):
    """A run whose slot the logical clock has not reached cannot be started.

    Starting is guarded on three counts at once, and only the temporal one is armed
    here: the PRD says "Both paths require that the pipeline's `status` be `ARMED` —
    otherwise `ERR_PIPELINE_NOT_ARMED` — that the runner be `ACTIVE`, and that the
    logical clock have reached or passed `scheduled_for_utc`, a start before its time
    being refused with `ERR_RUN_SCHEDULE_INVALID`."

    The pipeline is `ARMED` on a fresh `ACTIVE` runner and the run sits inside the
    half-open window at minute 540, so the only failing condition is the clock: it
    stands at the portal's starting instant while the slot is nine hours away, and the
    answer must be `ERR_RUN_SCHEDULE_INVALID`.

    The refusal is total. The run keeps the state it was scheduled in — "A new run has
    `status` `SCHEDULED`, `alert_dispatched` false, `rows_ingested` 0, `started_at` and
    `finished_at` and `failure_code` and `skip_reason` all null, and
    `consecutive_failure_index` initialised from the pipeline's current
    `consecutive_failure_count`." — and the 10.00 escrowed at arming stays escrowed,
    because "Arming a pipeline moves credits from balance to escrow; decommissioning
    moves them back; settling a run moves them from escrow and balance into consumed."

    Design: Corner/validations/run_started_before_its_scheduled_instant_returns_4XX
    """
    ctx = fixtures.setup_armed_pipeline(api=api)
    run = fixtures.schedule_run(ctx["pipeline_id"], SLOT_INSIDE_WINDOW, api=api)
    assert run["status"] == "SCHEDULED", (
        f"Expected a freshly scheduled run to be SCHEDULED, got {run['status']}"
    )

    validate_error(
        api.start_run(run["id"], PORTAL_ADMIN_HEADERS),
        "ERR_RUN_SCHEDULE_INVALID",
        422,
    )

    unchanged = fixtures.read_run(run["id"], api=api)
    assert unchanged["status"] == "SCHEDULED", (
        f"Expected the run to stay SCHEDULED after the refusal, got {unchanged['status']}"
    )
    assert unchanged["started_at"] is None, (
        f"Expected started_at to stay null after the refusal, got {unchanged['started_at']!r}"
    )
    assert unchanged["rows_ingested"] == 0, (
        f"Expected rows_ingested to stay 0, got {unchanged['rows_ingested']}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=90.00, escrowed=10.00, consumed=0.00)

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "ARMED", (
        f"Expected the pipeline to stay ARMED, got {pipeline['status']}"
    )
    assert pipeline["consecutive_failure_count"] == 0, (
        f"Expected consecutive_failure_count 0 after a refused start, "
        f"got {pipeline['consecutive_failure_count']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 10.00, "escrowed_credit_units")


def test_configuring_a_pipeline_whose_window_would_run_past_midnight_is_refused(api):
    """A window whose end exceeds 1440 is refused, and landing exactly on 1440 is not.

    The PRD: "The server derives `window_end_minute` as the start plus the duration,
    and refuses the configuration with `ERR_WINDOW_WRAPS_MIDNIGHT` if that sum exceeds
    1440 — windows may not wrap past midnight UTC."

    Minute 1400 with a 120-minute duration would end at 1520, so the configuration is
    refused with `ERR_WINDOW_WRAPS_MIDNIGHT`; both inputs are individually inside their
    declared ranges, so the request-shape check has nothing to say. Nothing is
    persisted, and no money moves either, because "Arming a pipeline moves credits from
    balance to escrow; decommissioning moves them back; settling a run moves them from
    escrow and balance into consumed."

    Shifting the opening to 1320 makes the sum exactly 1440, which does not exceed it,
    so the same request is accepted and lands in the documented initial state: "The new
    pipeline starts at `status` `DRAFT` with `escrowed_credit_units` 0.00,
    `consecutive_failure_count` 0 and `suspend_reason` null."

    Design: Corner/validations/pipeline_window_wrapping_past_midnight_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api)
    runner = fixtures.create_ingest_runner(api=api)

    validate_error(
        api.create_publication_pipeline(
            factories.pipeline_payload(
                ctx["dataset_id"],
                runner["id"],
                fixtures.current_dataset_version(ctx["dataset_id"], api=api),
                window_start_minute=1400,
                window_duration_minutes=120,
            ),
            ctx["coordinator_headers"],
        ),
        "ERR_WINDOW_WRAPS_MIDNIGHT",
        422,
    )

    pipelines, meta = validate_paginated(api.list_publication_pipelines(PORTAL_ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        f"A refused configuration must persist nothing, got total_count {meta['total_count']}"
    )
    assert pipelines == [], f"Expected no pipeline rows, got {pipelines}"

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)

    accepted = validate_success(
        api.create_publication_pipeline(
            factories.pipeline_payload(
                ctx["dataset_id"],
                runner["id"],
                fixtures.current_dataset_version(ctx["dataset_id"], api=api),
                window_start_minute=1320,
                window_duration_minutes=120,
            ),
            ctx["coordinator_headers"],
        ),
        201,
    )
    assert accepted["window_end_minute"] == 1440, (
        f"Expected window_end_minute 1440 at the inclusive maximum, "
        f"got {accepted['window_end_minute']}"
    )
    assert accepted["status"] == "DRAFT", (
        f"Expected the accepted pipeline to start DRAFT, got {accepted['status']}"
    )
    assert_money(accepted["escrowed_credit_units"], 0.00, "escrowed_credit_units")


def test_arming_a_pipeline_with_an_unfunded_department_is_refused_for_credits(api):
    """A department that was never granted a credit cannot escrow a weekly window.

    The PRD: "The transition `DRAFT → ARMED` requires that the acting coordinator own
    the dataset's department, that the dataset's `publication_status` be `PUBLISHED`,
    that the department's posture not be `SUSPENDED`, that the runner be `ACTIVE`, that
    both interval rules below hold, and that the department's `credit_balance_units` be
    greater than or equal to the pipeline's `escrow_required_units` — a shortfall is
    refused with `ERR_INSUFFICIENT_CREDITS`."

    Every other precondition holds: the dataset is `PUBLISHED`, the runner is the only
    one on the portal and therefore free, and "A freshly registered department starts
    with all four credit buckets at 0.00, all four risk counters at zero, `risk_points`
    at 0 and `compliance_posture` at `OPEN`." — so the posture is `OPEN` and the sole
    failing condition is the money, giving `ERR_INSUFFICIENT_CREDITS`.

    The weekly cadence asks for 10.00: five runs fit the thirty-day horizon and "That
    run count is multiplied by 2 credits per run, and the product is capped at 60
    credits, giving `escrow_required_units`." Against a 0.00 balance that is a
    shortfall, and after the refusal the runner is still unbooked — "A new runner has
    `status` `ACTIVE` and `armed_window_count` 0." — while the scorecard still reports
    "a boolean `credit_ledger_balanced` asserting that the conservation invariant of
    §2.10 currently holds."

    Design: Corner/validations/arm_without_any_credit_grant_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    runner = fixtures.create_ingest_runner(api=api)
    pipeline = fixtures.configure_pipeline(
        ctx["dataset_id"], runner["id"], ctx["department_id"], api=api
    )
    assert_money(pipeline["escrow_required_units"], 10.00, "escrow_required_units")

    validate_error(
        api.arm_pipeline(pipeline["id"], ctx["coordinator_headers"]),
        "ERR_INSUFFICIENT_CREDITS",
        402,
    )

    refused = fixtures.read_pipeline(pipeline["id"], api=api)
    assert refused["status"] == "DRAFT", (
        f"An unaffordable arming must leave the pipeline DRAFT, got {refused['status']}"
    )
    assert_money(refused["escrow_required_units"], 10.00, "escrow_required_units")
    assert_money(refused["escrowed_credit_units"], 0.00, "escrowed_credit_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=0.00, balance=0.00, escrowed=0.00, consumed=0.00)

    runner_after = validate_success(api.get_ingest_runner(runner["id"], PORTAL_ADMIN_HEADERS))
    assert runner_after["armed_window_count"] == 0, (
        f"No window may be reserved by a refused arming, "
        f"got armed_window_count {runner_after['armed_window_count']}"
    )

    assert_scorecard_balanced(fixtures.read_scorecard(ctx["department_id"], api=api))


def test_privacy_assessment_cannot_be_submitted_before_the_cell_size_is_measured(api):
    """The clearance pass needs a measured cell size, so submission is gated on it.

    The PRD: "Submitting the assessment moves it `DRAFT → SUBMITTED` and requires two
    things: `verified_smallest_cell_size` must have been measured, or the submission is
    refused with `ERR_VERIFIED_CELL_SIZE_MISSING`, and the dataset's
    `publication_status` must be exactly `SCREENING`."

    The dataset here is in `SCREENING`, so the only failing condition is the missing
    measurement and the answer must be `ERR_VERIFIED_CELL_SIZE_MISSING`. The assessment
    was opened and never revised, and "The server stamps `assessor_user_id` with the
    authoring reviewer's `X-User-ID`, leaves `verified_smallest_cell_size` and
    `decided_by_user_id` null, and sets `status` to `DRAFT`."

    Its screening figure is already computed: two declared quasi-identifier columns at
    8 points each give 16, a declared cell size of 20 is 11 or greater and so scores
    0.5, the screening pass forces the population factor to 1.00, and a `PUBLIC`
    extract multiplies by 0.8. "All four are multiplied together, the product is
    rounded half up to two decimal places exactly once, and the result is then capped
    at 100.00." — that is 6.40, and "Its result is stored in `screening_risk_score`,
    and while the assessment's `status` is `DRAFT` the assessment's headline
    `risk_score` mirrors it." The refused submission changes none of that; recording
    the measurement afterwards makes the very same call succeed.

    Design: Corner/validations/assessment_submit_without_measured_cell_size_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api)
    assessment = fixtures.open_privacy_assessment(ctx["dataset_id"], api=api)
    assert assessment["status"] == "DRAFT", (
        f"Expected a newly opened assessment to be DRAFT, got {assessment['status']}"
    )
    assert assessment["verified_smallest_cell_size"] is None, (
        f"Expected verified_smallest_cell_size to start null, "
        f"got {assessment['verified_smallest_cell_size']!r}"
    )

    validate_error(
        api.submit_privacy_assessment(assessment["id"], PRIVACY_ASSESSOR_HEADERS),
        "ERR_VERIFIED_CELL_SIZE_MISSING",
        422,
    )

    unchanged = validate_success(
        api.get_privacy_assessment(assessment["id"], PRIVACY_ASSESSOR_HEADERS)
    )
    assert unchanged["status"] == "DRAFT", (
        f"Expected the assessment to stay DRAFT after the refusal, got {unchanged['status']}"
    )
    assert unchanged["verified_smallest_cell_size"] is None, (
        f"Expected verified_smallest_cell_size to stay null, "
        f"got {unchanged['verified_smallest_cell_size']!r}"
    )
    assert_money(unchanged["screening_risk_score"], 6.40, "screening_risk_score")
    assert_money(unchanged["risk_score"], 6.40, "risk_score")

    fixtures.revise_privacy_assessment(assessment["id"], api=api, verified_smallest_cell_size=20)
    submitted = validate_success(
        api.submit_privacy_assessment(assessment["id"], PRIVACY_ASSESSOR_HEADERS)
    )
    assert submitted["status"] == "SUBMITTED", (
        f"Expected SUBMITTED once the cell size is measured, got {submitted['status']}"
    )
    assert submitted["verified_smallest_cell_size"] == 20, (
        f"Expected verified_smallest_cell_size 20, "
        f"got {submitted['verified_smallest_cell_size']}"
    )


def test_publication_is_refused_when_the_backing_licence_has_been_retired(api):
    """Retiring the licence leaves the accepted record alone but closes publication.

    The PRD: "Retiring a licence sets `retired` to true; metadata records already
    accepted against it keep the reference, but no further record may be accepted
    against it and no dataset backed by it may be published." The gate is named
    explicitly for this endpoint: "Licence still current, on
    `POST /open-data/metadata-records/{metadataRecordId}/decide` and
    `POST /open-data/datasets/{datasetId}/publish`: the backing licence has `retired`
    false — otherwise `ERR_LICENSE_RETIRED` (409)."

    Readiness carries no such gate, so the retirement lands between the two calls:
    `mark-ready` still succeeds and only the publish attempt is refused with
    `ERR_LICENSE_RETIRED`. The refusal is total — publication is what would have
    started the dataset's history, since "On the dataset, `version_index_high_water`
    becomes 1, `live_row_count` becomes the initial row count, and `last_published_at`
    becomes the current logical instant." — so the dataset stays `READY` with no
    version behind it and the accepted record keeps its licence reference.

    Design: Corner/validations/publish_of_retired_license_dataset_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api, dataset_overrides=TRAFFIC_DATASET)
    record = fixtures.land_accepted_metadata(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    fixtures.land_cleared_assessment(ctx["dataset_id"], api=api)

    retired_license = fixtures.retire_license(ctx["license_id"], api=api)
    assert retired_license["retired"] is True, (
        f"Expected the licence to report retired true, got {retired_license['retired']!r}"
    )

    ready = fixtures.mark_ready(ctx["dataset_id"], ctx["department_id"], api=api)
    assert_dataset_states(ready, publication_status="READY")

    validate_error(
        api.publish_dataset(
            ctx["dataset_id"], factories.publish_payload(50000), ctx["coordinator_headers"]
        ),
        "ERR_LICENSE_RETIRED",
        409,
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(unchanged, publication_status="READY", currency_status="CURRENT")
    assert unchanged["last_published_at"] is None, (
        f"A refused publication must leave last_published_at null, "
        f"got {unchanged['last_published_at']!r}"
    )
    assert unchanged["version_index_high_water"] == 0, (
        f"Expected version_index_high_water 0, got {unchanged['version_index_high_water']}"
    )
    assert unchanged["live_row_count"] == 0, (
        f"Expected live_row_count 0, got {unchanged['live_row_count']}"
    )
    assert fixtures.versions_of_dataset(ctx["dataset_id"], api=api) == [], (
        "A refused publication must mint no version"
    )

    kept = validate_success(api.get_metadata_record(record["id"], ANONYMOUS_HEADERS))
    assert kept["status"] == "ACCEPTED", (
        f"The already-accepted record must stay ACCEPTED, got {kept['status']}"
    )
    assert kept["license_id"] == ctx["license_id"], (
        f"Expected the record to keep licence {ctx['license_id']}, got {kept['license_id']}"
    )


def test_publishing_a_tier_three_dataset_under_a_restricted_posture_is_refused(api):
    """A sibling's remediation hardens the posture and shuts out the low-priority work.

    The gate lives on the department, not on the dataset. Accepting a privacy defect on
    a sibling is what moves the aggregate: "Accepting a quality issue that is both
    `CRITICAL` in `severity` and `PRIVACY` in `category` against a `PUBLISHED` dataset
    runs four hops: the issue moves to `ACCEPTED`, the dataset moves
    `PUBLISHED → UNDER_REMEDIATION`, that dataset's `ARMED` pipeline moves to
    `SUSPENDED`, and because the pipeline is now suspended the dataset's
    `currency_status` takes a `STALE` floor while its pipeline's pending runs are
    skipped — after which the department's counters, `risk_points` and
    `compliance_posture` are re-derived."

    One dataset under remediation is two points: "`risk_points` is then three points
    for each breached dataset, plus two points for each stale dataset, plus two points
    for each dataset under remediation, plus one point for each overdue correction.
    Datasets that are `RETIRED` or that have not yet been published never contribute.
    From `risk_points` the posture follows on inclusive boundaries: at least 6 points is
    `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0 points is
    `OPEN`."

    The dataset under test is untouched and perfectly ready, but it is cheap work:
    0.45 x 20 plus 0.35 x 20 with no community pressure is 16.00, and "From that score,
    `priority_tier` follows on inclusive thresholds: `TIER_1` at 75.00 or above,
    `TIER_2` at 50.00 or above, and `TIER_3` otherwise."

    Publication reads that stored tier: "The department must not be `SUSPENDED`, and if
    it is `RESTRICTED` the dataset's stored `priority_tier` at the start of the request
    must be `TIER_1` or `TIER_2`." The gate answers with one of two identifiers —
    "Departmental posture gate, on `POST /open-data/datasets/{datasetId}/screen`,
    `POST /open-data/datasets/{datasetId}/mark-ready`,
    `POST /open-data/datasets/{datasetId}/publish`,
    `POST /open-data/publication-pipelines/{pipelineId}/arm` and
    `POST /open-data/quality-issues/{issueId}/decide`: `ERR_DEPARTMENT_SUSPENDED` or
    `ERR_RESTRICTED_POSTURE_TIER` (403), described in §2.9." — and since "A `SUSPENDED`
    posture blocks all five outright with `ERR_DEPARTMENT_SUSPENDED` (403)." applies
    only to `SUSPENDED`, a `RESTRICTED` department refusing `TIER_3` work must answer
    `ERR_RESTRICTED_POSTURE_TIER`, not `ERR_DEPARTMENT_SUSPENDED`.

    Design: Corner/validations/publish_of_tier3_dataset_under_restricted_posture_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, dataset_overrides=LIBRARY_DATASET)
    assert_dataset_states(ctx["dataset"], publication_status="READY")
    assert_priority(
        ctx["dataset"],
        priority_score=16.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_3",
    )

    sibling = _carry_sibling_to_published(api, ctx, TRAFFIC_DATASET)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_and_triage_issue(
        sibling["id"],
        member["member_id"],
        ctx["department_id"],
        severity="CRITICAL",
        category="PRIVACY",
        api=api,
    )
    fixtures.accept_quality_issue(issue["id"], ctx["department_id"], api=api)

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department,
        risk_points=2,
        compliance_posture="RESTRICTED",
        breached=0,
        stale=0,
        remediation=1,
        overdue_corrections=0,
    )

    validate_error(
        api.publish_dataset(
            ctx["dataset_id"], factories.publish_payload(50000), ctx["coordinator_headers"]
        ),
        "ERR_RESTRICTED_POSTURE_TIER",
        403,
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(unchanged, publication_status="READY", currency_status="CURRENT")
    assert_priority(
        unchanged,
        priority_score=16.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_3",
    )
    assert unchanged["last_published_at"] is None, (
        f"A refused publication must leave last_published_at null, "
        f"got {unchanged['last_published_at']!r}"
    )
    assert fixtures.versions_of_dataset(ctx["dataset_id"], api=api) == [], (
        "A refused publication must mint no version"
    )

    remediating = fixtures.read_dataset(sibling["id"], api=api)
    assert_dataset_states(remediating, publication_status="UNDER_REMEDIATION")
    assert remediating["public_access_suspended"] is True, (
        f"Expected the remediating sibling to have public_access_suspended true, "
        f"got {remediating['public_access_suspended']!r}"
    )


def test_screening_a_new_dataset_under_a_suspended_posture_is_refused(api):
    """At six risk points the gate is unconditional, even for brand-new TIER_1 work.

    The department is driven to six points by one dataset and one issue. Its published
    dataset is committed to the strictest currency tier and then neglected, and
    "It is `STALE` when `days_overdue` exceeds the grace but does not exceed twice the
    grace. Beyond twice the grace it is `BREACHED` — but only for a dataset whose
    `high_value_committed` flag is true; a dataset without that commitment floors at
    `STALE` and never reaches `BREACHED` however long it is neglected."

    The grace is read off the tier the dataset actually holds: "Third, a grace
    allowance is read off the dataset's `priority_tier`: 2 days for `TIER_1`, 7 days
    for `TIER_2`, 14 days for `TIER_3` — the more valuable the dataset, the shorter its
    rope." Publication re-scores the dataset as measured — "Once the dataset's
    `publication_status` is `PUBLISHED` or `UNDER_REMEDIATION`, the demand term becomes
    the measured `observed_demand_score` and the variant is `AS_OBSERVED`." — so a
    dataset declared at 75.00 falls to 33.60 with no traffic recorded and buys the
    14-day rope. Weekly cadence makes the next publication due seven days after the
    first, and "Second, `days_overdue` is zero whenever `next_due_at` is null or the
    logical clock has not yet passed it, and is otherwise the elapsed seconds from
    `next_due_at` to the current logical instant divided by 86400 and floored to a
    whole number of days." — 29 days by the last sweep, past twice the grace of 28.

    Two of the three sweeps therefore alert: "Step two emits staleness alerting: every
    dataset that is entering or remaining in `STALE` or `BREACHED` emits exactly one
    alert per sweep, increasing `staleness_alert_count` by 1 and setting
    `last_staleness_alert_at` to the current logical instant. A dataset that merely
    became `AGING` emits nothing."

    The accepted privacy issue misses its own deadline along the way: "Step four walks
    the quality issues in ascending `created_at` order, inspecting only those whose
    `status` is `SUBMITTED` or `ACCEPTED`: a still-`SUBMITTED` issue whose
    `triage_due_at` the logical clock has strictly passed latches `triage_breached` to
    true, and a still-`ACCEPTED` issue whose `correction_due_at` the logical clock has
    strictly passed latches `correction_breached` to true."

    The four counters then read 1, 0, 1 and 1:
    "`breached_dataset_count` is the number of the department's datasets whose
    `currency_status` is `BREACHED` and whose `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`."
    "`stale_dataset_count` is the number of the department's datasets whose
    `currency_status` is `STALE` and whose `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`."
    "`remediation_dataset_count` is the number of the department's datasets whose
    `publication_status` is `UNDER_REMEDIATION`."
    "`overdue_correction_count` is the number of quality issues on the department's
    datasets whose `status` is `ACCEPTED` and whose `correction_breached` flag is true."

    That is 3 + 0 + 2 + 1 points, because "`risk_points` is then three points for each
    breached dataset, plus two points for each stale dataset, plus two points for each
    dataset under remediation, plus one point for each overdue correction. Datasets
    that are `RETIRED` or that have not yet been published never contribute. From
    `risk_points` the posture follows on inclusive boundaries: at least 6 points is
    `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0 points is
    `OPEN`."

    At that point the gate is absolute: "The posture gate then bites on five operations
    — moving a dataset into screening, declaring it ready, publishing it, arming one of
    its pipelines, and deciding a quality issue on it. A `SUSPENDED` posture blocks all
    five outright with `ERR_DEPARTMENT_SUSPENDED` (403)." A freshly inventoried
    `TIER_1` dataset is therefore refused with `ERR_DEPARTMENT_SUSPENDED` and not with
    the tier-sensitive `ERR_RESTRICTED_POSTURE_TIER`, and it stays in `INVENTORIED`.

    Design: Corner/validations/screen_under_suspended_posture_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, dataset_overrides=TRAFFIC_DATASET)
    assert_priority(ctx["dataset"], priority_score=75.00, priority_tier="TIER_1")

    committed = fixtures.commit_high_value(ctx["dataset_id"], api=api)
    assert committed["high_value_committed"] is True, (
        f"Expected high_value_committed true, got {committed['high_value_committed']!r}"
    )

    published = fixtures.publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=50000, api=api
    )
    assert_priority(
        published,
        priority_score=33.60,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )

    member = fixtures.setup_member(api=api)
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"],
        member["member_id"],
        ctx["department_id"],
        severity="CRITICAL",
        category="PRIVACY",
        api=api,
    )
    fixtures.accept_quality_issue(issue["id"], ctx["department_id"], api=api)

    fixtures.advance_clock_and_sweep("2026-08-20T00:00:00Z", api=api)
    fixtures.advance_clock_and_sweep("2026-08-25T00:00:00Z", api=api)
    fixtures.advance_clock_and_sweep("2026-09-06T00:00:00Z", api=api)

    neglected = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(
        neglected, publication_status="UNDER_REMEDIATION", currency_status="BREACHED"
    )
    assert neglected["days_overdue"] == 29, (
        f"Expected days_overdue 29 at 2026-09-06, got {neglected['days_overdue']}"
    )
    assert neglected["staleness_alert_count"] == 2, (
        f"Expected one alert on entering STALE and one on entering BREACHED, "
        f"got staleness_alert_count {neglected['staleness_alert_count']}"
    )

    breached_issue = validate_success(api.get_quality_issue(issue["id"], ANONYMOUS_HEADERS))
    assert breached_issue["status"] == "ACCEPTED", (
        f"Expected the issue to still be ACCEPTED, got {breached_issue['status']}"
    )
    assert breached_issue["correction_breached"] is True, (
        f"Expected correction_breached to be latched true, "
        f"got {breached_issue['correction_breached']!r}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department,
        risk_points=6,
        compliance_posture="SUSPENDED",
        breached=1,
        stale=0,
        remediation=1,
        overdue_corrections=1,
    )

    fresh = fixtures.inventory_dataset(ctx["department_id"], api=api, **CRASH_DATASET)
    assert_priority(fresh, priority_score=75.00, priority_tier="TIER_1")

    validate_error(
        api.screen_dataset(fresh["id"], ctx["coordinator_headers"]),
        "ERR_DEPARTMENT_SUSPENDED",
        403,
    )

    still_inventoried = fixtures.read_dataset(fresh["id"], api=api)
    assert_dataset_states(
        still_inventoried, publication_status="INVENTORIED", currency_status="CURRENT"
    )
    assert_priority(
        still_inventoried,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )
