"""
Concurrency tokens and immediate visibility: the optimistic-concurrency guard on
the two creates that carry `expected_dataset_version`, the exact set of writes
that move the dataset's own `version` counter, the event that resets a pipeline's
failure streak, and the acceptance cascade that is readable without a sweep.
"""

from test_helpers import (
    PORTAL_ADMIN_HEADERS,
    assert_common_fields,
    assert_credit_buckets,
    assert_credit_conservation,
    assert_dataset_states,
    assert_exactly_one_live_version,
    assert_money,
    assert_posture,
    assert_settlement,
    factories,
    find_version_by_index,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

SLOT = "2026-08-01T09:00:00Z"
PRIVACY_DEFECT = "Published extract exposes household-level coordinates"


def test_stale_expected_dataset_version_on_a_manual_version_is_refused_and_mints_no_row(api):
    """A version token captured before publication can no longer mint a manual version.

    The PRD makes the token mandatory and pins the refusal: "Creating a `DatasetVersion`
    requires a non-optional `expected_dataset_version` field in the request body, carrying
    the `version` value of the target dataset that the client last observed. If that value
    does not equal the dataset's current `version`, the request is rejected with
    `ERR_STALE_DATASET_VERSION` (412)." The token is not decorative: "No other endpoint in
    this system takes a version field. Operations that are not one of those two creates do
    not accept `expected_dataset_version` and perform no concurrency comparison."

    Publication itself moves the counter the token names — "On the dataset,
    `version_index_high_water` becomes 1, `live_row_count` becomes the initial row count,
    and `last_published_at` becomes the current logical instant." and "The owning
    department's `risk_points` and `compliance_posture` are re-derived. The dataset's
    `version` increments." — so a token read at `READY` is exactly one behind afterwards.
    The refused request must leave the published record untouched: the only asserted error
    is `ERR_STALE_DATASET_VERSION`, and the dataset keeps the single `INITIAL` version and
    the 50000-row figure publication left behind. Retried with the token the dataset now
    reports, the same body succeeds and "The new version takes `version_index` equal to the
    dataset's `version_index_high_water` plus one, a matching `version_label`, `status`
    `LIVE`, `published_at` at the current logical instant, and `supersedes_version_id`
    pointing at the previously `LIVE` version, which moves to `SUPERSEDED` with
    `superseded_at` stamped." The accepted retry is what rolls the dataset forward:
    "On the dataset, `live_row_count` becomes the supplied `row_count`,
    `version_index_high_water` becomes the new index, `last_published_at` becomes the
    current logical instant, and `next_due_at`, `days_overdue` and `currency_status` are
    re-derived." and, closing that same paragraph,
    "and it does not by itself lift remediation. The dataset's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_dataset_version_on_manual_version_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=0)

    stale_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)
    assert stale_token == 3, (
        f"Expected the READY dataset at version 3 (create, screen, mark-ready), "
        f"got {stale_token}"
    )

    fixtures.publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=50000, api=api
    )
    fresh_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)
    assert fresh_token == 4, (
        f"Expected publication to carry the dataset to version 4, got {fresh_token}"
    )

    refused = api.create_dataset_version(
        factories.dataset_version_payload(
            ctx["dataset_id"],
            "SCHEMA_CHANGE",
            51000,
            stale_token,
            notes="Adds a signal_id column to the weekly extract",
        ),
        ctx["coordinator_headers"],
    )
    validate_error(refused, "ERR_STALE_DATASET_VERSION", 412)

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert unchanged["version"] == 4, (
        f"A refused create must not move the dataset's version, got {unchanged['version']}"
    )
    assert unchanged["live_row_count"] == 50000, (
        f"Expected live_row_count to stay 50000, got {unchanged['live_row_count']}"
    )
    assert unchanged["version_index_high_water"] == 1, (
        f"Expected version_index_high_water to stay 1, "
        f"got {unchanged['version_index_high_water']}"
    )

    rows = fixtures.versions_of_dataset(ctx["dataset_id"], api=api)
    assert len(rows) == 1, (
        f"Expected the refusal to mint no version row, got {len(rows)}: "
        f"{[(row.get('version_index'), row.get('status')) for row in rows]}"
    )
    assert rows[0]["change_type"] == "INITIAL", (
        f"Expected the sole surviving row to be the INITIAL version, "
        f"got {rows[0]['change_type']}"
    )

    accepted = validate_success(
        api.create_dataset_version(
            factories.dataset_version_payload(
                ctx["dataset_id"],
                "SCHEMA_CHANGE",
                51000,
                fresh_token,
                notes="Adds a signal_id column to the weekly extract",
            ),
            ctx["coordinator_headers"],
        ),
        201,
    )
    assert_common_fields(accepted, expected_version=1)
    assert accepted["version_index"] == 2, (
        f"Expected version_index 2 on the retry, got {accepted['version_index']}"
    )
    assert accepted["version_label"] == "v2", (
        f"Expected version_label 'v2', got {accepted['version_label']!r}"
    )
    assert accepted["status"] == "LIVE", f"Expected LIVE, got {accepted['status']}"
    assert accepted["row_count"] == 51000, (
        f"Expected row_count 51000, got {accepted['row_count']}"
    )
    assert accepted["supersedes_version_id"] == rows[0]["id"], (
        f"Expected supersedes_version_id to name the INITIAL version {rows[0]['id']}, "
        f"got {accepted['supersedes_version_id']!r}"
    )

    after = fixtures.versions_of_dataset(ctx["dataset_id"], api=api)
    assert len(after) == 2, f"Expected two version rows after the retry, got {len(after)}"
    live = assert_exactly_one_live_version(after)
    assert live["version_index"] == 2, (
        f"Expected the LIVE version to be v2, got v{live['version_index']}"
    )
    predecessor = find_version_by_index(after, 1)
    assert predecessor["status"] == "SUPERSEDED", (
        f"Expected the predecessor SUPERSEDED, got {predecessor['status']}"
    )
    assert str(predecessor["superseded_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected superseded_at stamped at the current instant, "
        f"got {predecessor['superseded_at']!r}"
    )

    rolled = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert rolled["live_row_count"] == 51000, (
        f"Expected live_row_count 51000 after the accepted retry, "
        f"got {rolled['live_row_count']}"
    )
    assert rolled["version_index_high_water"] == 2, (
        f"Expected version_index_high_water 2, got {rolled['version_index_high_water']}"
    )
    assert rolled["version"] == 5, (
        f"Expected the accepted create to move the dataset to version 5, "
        f"got {rolled['version']}"
    )


def test_stale_expected_dataset_version_on_pipeline_configuration_is_refused_and_reserves_nothing(api):
    """The same token guards pipeline configuration, and a refusal reserves no escrow.

    The PRD extends the guard to the second create: "Creating a `PublicationPipeline`
    likewise requires a non-optional `expected_dataset_version` field carrying the client's
    last observed dataset `version`, and a value that does not equal the dataset's current
    `version` is rejected with the same `ERR_STALE_DATASET_VERSION` (412)." Its reason is
    the supersession this create performs: "Here the protection exists because configuring a
    pipeline decommissions the dataset's previous non-decommissioned pipeline and records it
    as `superseded_pipeline_id`; a stale writer would discard a configuration it never
    observed."

    The token goes stale on publication. Configuring a pipeline is itself a dataset write —
    "The dataset's own `version` increments as part of the create." — but it is not the only
    one, and a token read at `READY` is a publication behind by the time it is spent.
    `ERR_STALE_DATASET_VERSION` is the only error this test asserts, and after it the
    pipeline collection is still empty and the department's ledger is exactly what the grant
    left: "Only a grant changes it, and a grant raises the issued total and the balance by
    the same amount, leaving escrow and consumed untouched." Retried with the current token
    the create lands: "The new pipeline starts at `status` `DRAFT` with
    `escrowed_credit_units` 0.00, `consecutive_failure_count` 0 and `suspend_reason` null."
    Its price is fixed by cadence alone — "That run count is multiplied by 2 credits per
    run, and the product is capped at 60 credits, giving `escrow_required_units`." — five
    weekly runs over the thirty-day horizon at 2 credits each, so 10.00, and none of that is
    taken until arming.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_dataset_version_on_pipeline_create_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=100.00)
    runner = fixtures.create_ingest_runner(api=api)

    stale_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)
    assert stale_token == 3, (
        f"Expected the READY dataset at version 3, got {stale_token}"
    )

    fixtures.publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=50000, api=api
    )
    fresh_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)
    assert fresh_token == 4, (
        f"Expected publication to carry the dataset to version 4, got {fresh_token}"
    )

    refused = api.create_publication_pipeline(
        factories.pipeline_payload(ctx["dataset_id"], runner["id"], stale_token),
        ctx["coordinator_headers"],
    )
    validate_error(refused, "ERR_STALE_DATASET_VERSION", 412)

    _, meta = validate_paginated(
        api.list_publication_pipelines(PORTAL_ADMIN_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"A refused configuration must persist no pipeline, got {meta['total_count']}"
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert unchanged["version"] == 4, (
        f"A refused create must not move the dataset's version, got {unchanged['version']}"
    )

    before = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(before, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(before)

    pipeline = validate_success(
        api.create_publication_pipeline(
            factories.pipeline_payload(ctx["dataset_id"], runner["id"], fresh_token),
            ctx["coordinator_headers"],
        ),
        201,
    )
    assert_common_fields(pipeline, expected_version=1)
    assert pipeline["status"] == "DRAFT", f"Expected DRAFT, got {pipeline['status']}"
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")
    assert_money(pipeline["escrow_required_units"], 10.00, "escrow_required_units")
    assert pipeline["consecutive_failure_count"] == 0, (
        f"Expected consecutive_failure_count 0, got {pipeline['consecutive_failure_count']}"
    )
    assert pipeline["suspend_reason"] is None, (
        f"Expected suspend_reason null, got {pipeline['suspend_reason']!r}"
    )

    after = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(after, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(after)

    _, after_meta = validate_paginated(
        api.list_publication_pipelines(PORTAL_ADMIN_HEADERS, params={"limit": 100})
    )
    assert after_meta["total_count"] == 1, (
        f"Expected exactly the retried pipeline to exist, got {after_meta['total_count']}"
    )


def test_the_dataset_version_counter_moves_only_on_writes_to_the_dataset_row_itself(api):
    """Screening, readiness and publication move the dataset's counter; the artefacts do not.

    The counter is defined per row: "`version` (integer): a counter that starts at 1 on
    creation and increments by exactly 1 on every mutation of that row, including mutations
    the server performs on its own initiative as a cascade from some other resource's
    transition." and the PRD is explicit that the unit is the row, not the call — "a single
    request routinely increments the `version` of more than one resource — and it does so
    once per mutated row, not once per request."

    Three dataset writes are declared along the way to publication. Screening "re-scores
    `priority_score` under the `AS_DECLARED` variant and stamps `priority_score_variant`
    accordingly, makes the dataset eligible for catalog-page usage reporting, and increments
    the dataset's `version`." Readiness is narrower still:
    "The transition increments the dataset's `version` and changes nothing else."
    Publication closes with "The owning
    department's `risk_points` and `compliance_posture` are re-derived. The dataset's
    `version` increments."

    The metadata and privacy chains in between mutate their own rows only. On the record,
    "Every one of these transitions increments the record's `version`."; on the assessment,
    "While the assessment is still `DRAFT`, the reviewer records measurements and corrects
    declarations against it" and then
    "`screening_risk_score` is recomputed and the assessment's `version` increments.", while
    on the decision "Both outcomes stamp `decided_by_user_id` with the deciding reviewer's
    `X-User-ID`, both require that this identifier differ from the recorded
    `assessor_user_id`, and both increment the assessment's `version`". Submission mutates
    that row in its own right under the counter rule above. So the record reaches 3 and the
    assessment reaches 4 while the dataset stands still at 2.

    Design: Corner/cross_cutting_complexity_layers/dataset_version_increments_only_on_declared_dataset_writes
    """
    ctx = fixtures.setup_funded_department(api=api, credit_units=0)

    dataset = fixtures.inventory_dataset(ctx["department_id"], api=api)
    assert_common_fields(dataset)
    assert dataset["version"] == 1, (
        f"Expected version 1 on creation, got {dataset['version']}"
    )
    dataset_id = dataset["id"]

    screened = fixtures.screen_dataset(dataset_id, ctx["department_id"], api=api)
    assert screened["version"] == 2, (
        f"Expected screening to take the dataset to version 2, got {screened['version']}"
    )
    assert screened["priority_score_variant"] == "AS_DECLARED", (
        f"Expected priority_score_variant AS_DECLARED, got {screened['priority_score_variant']}"
    )

    record = fixtures.draft_metadata_record(
        dataset_id, ctx["license_id"], ctx["department_id"], api=api
    )
    assert record["version"] == 1, (
        f"Expected the metadata record at version 1 on creation, got {record['version']}"
    )
    submitted = fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    assert submitted["version"] == 2, (
        f"Expected the metadata record at version 2 after submission, got {submitted['version']}"
    )
    accepted = fixtures.accept_metadata_record(record["id"], api=api)
    assert accepted["version"] == 3, (
        f"Expected the metadata record at version 3 after acceptance, got {accepted['version']}"
    )

    assessment = fixtures.open_privacy_assessment(dataset_id, api=api)
    assert assessment["version"] == 1, (
        f"Expected the assessment at version 1 on creation, got {assessment['version']}"
    )
    revised = fixtures.revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=20
    )
    assert revised["version"] == 2, (
        f"Expected the assessment at version 2 after the revision, got {revised['version']}"
    )
    submitted_assessment = fixtures.submit_privacy_assessment(assessment["id"], api=api)
    assert submitted_assessment["version"] == 3, (
        f"Expected the assessment at version 3 after submission, "
        f"got {submitted_assessment['version']}"
    )
    cleared = fixtures.clear_privacy_assessment(assessment["id"], api=api)
    assert cleared["version"] == 4, (
        f"Expected the assessment at version 4 after the clearance, got {cleared['version']}"
    )

    untouched = fixtures.read_dataset(dataset_id, api=api)
    assert untouched["version"] == 2, (
        f"The artefact chain must not move the dataset's counter, expected 2, "
        f"got {untouched['version']}"
    )
    assert_dataset_states(untouched, publication_status="SCREENING")

    ready = fixtures.mark_ready(dataset_id, ctx["department_id"], api=api)
    assert ready["version"] == 3, (
        f"Expected readiness to take the dataset to version 3, got {ready['version']}"
    )
    assert_dataset_states(ready, publication_status="READY")

    published = validate_success(
        api.publish_dataset(
            dataset_id,
            factories.publish_payload(initial_row_count=50000),
            ctx["coordinator_headers"],
        )
    )
    assert published["version"] == 4, (
        f"Expected publication to take the dataset to version 4, got {published['version']}"
    )
    assert_dataset_states(published, publication_status="PUBLISHED", currency_status="CURRENT")
    assert published["version_index_high_water"] == 1, (
        f"Expected version_index_high_water 1, got {published['version_index_high_water']}"
    )
    assert published["priority_score_variant"] == "AS_OBSERVED", (
        f"Expected priority_score_variant AS_OBSERVED, got {published['priority_score_variant']}"
    )


def test_two_failed_runs_leave_the_pipeline_armed_and_one_success_resets_the_streak_to_zero(api):
    """The streak climbs to 2 on failures and is cleared by the very next successful run.

    Each failure charges for its alert alone: "Hop one records the outcome: `failure_code` is
    stored, `alert_dispatched` is set to true and an alert is dispatched to the pipeline's
    `alert_email`, `rows_ingested` stays 0, the pipeline's `consecutive_failure_count`
    increases by 1 and that new value is copied into the run's `consecutive_failure_index`,
    and the alert-only charge is settled through the same waterfall." With no rows, "A failed
    run has `rows_ingested` of 0, so its `compute_credits` is 0.00." and "Step two computes
    `alert_credits`: 3 credits when `alert_dispatched` is true, and 0.00 when it is false."
    Step four leaves that 3.00 subtotal undiscounted, so each failure consumes 3.00 out of
    the 10.00 escrow via the waterfall — "`escrow_drawn_units` is the lesser of the
    pipeline's current `escrowed_credit_units` and `total_charge_credits`;
    `balance_drawn_units` is whatever remains of the charge after that."

    Two failures stay under the limit, because
    "Hop two fires when `consecutive_failure_count` has reached 3", so the pipeline is still
    `ARMED` at a count of 2. The third run succeeds and
    "The pipeline's `consecutive_failure_count` resets to 0. The department's counters,
    `risk_points` and `compliance_posture` are re-derived." Its own settlement is priced from
    scratch: 45000 rows are 5 compute units at 4 credits, and
    "Step three adds the two into `subtotal_credits`. Step four keys
    `reliability_discount_pct` on that subtotal and on nothing else: 0.10 when
    `subtotal_credits` is 40 or more, 0.05 when it is 20 or more but below 40, and 0.00 below
    20.", then "Step five computes `discount_credits` as `subtotal_credits` multiplied by
    `reliability_discount_pct`, rounded half up to two decimal places." and "Step six
    computes `total_charge_credits` as `subtotal_credits` minus `discount_credits`,
    again rounded half up to two decimal places." — 20.00 subtotal, 0.05, 1.00 off, 19.00
    charged, drawing the last 4.00 of escrow and 15.00 of balance. The success also rolls the
    dataset:
    "On the dataset, `live_row_count` becomes `rows_ingested`, `version_index_high_water`
    increases by one and supplies the new version's `version_index`, `last_published_at`
    becomes the current logical instant, and `next_due_at`, `days_overdue` and
    `currency_status` are re-derived" and "First, `next_due_at` is the dataset's
    `last_published_at` plus the number of days its `update_frequency` implies — 1 day for
    `DAILY`, 7 for `WEEKLY`, 30 for `MONTHLY`, 91 for `QUARTERLY`, 365 for `ANNUAL`".

    Design: Corner/cross_cutting_complexity_layers/failure_streak_counter_resets_after_a_successful_run
    """
    ctx = fixtures.setup_running_run(api=api, scheduled_for_utc=SLOT)
    second = fixtures.schedule_run(ctx["pipeline_id"], SLOT, api=api)["id"]
    third = fixtures.schedule_run(ctx["pipeline_id"], SLOT, api=api)["id"]

    first_failure = fixtures.report_failure(ctx["run_id"], failure_code="TIMEOUT", api=api)
    assert first_failure["status"] == "FAILED", (
        f"Expected FAILED, got {first_failure['status']}"
    )
    assert first_failure["alert_dispatched"] is True, (
        f"Expected alert_dispatched true, got {first_failure['alert_dispatched']!r}"
    )
    assert first_failure["rows_ingested"] == 0, (
        f"Expected rows_ingested 0 on a failure, got {first_failure['rows_ingested']}"
    )
    assert first_failure["consecutive_failure_index"] == 1, (
        f"Expected consecutive_failure_index 1, "
        f"got {first_failure['consecutive_failure_index']}"
    )
    assert_settlement(
        first_failure,
        compute_credits=0.00,
        alert_credits=3.00,
        subtotal_credits=3.00,
        reliability_discount_pct=0.00,
        discount_credits=0.00,
        total_charge_credits=3.00,
        escrow_drawn_units=3.00,
        balance_drawn_units=0.00,
    )

    after_one = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert after_one["consecutive_failure_count"] == 1, (
        f"Expected consecutive_failure_count 1, got {after_one['consecutive_failure_count']}"
    )
    assert after_one["status"] == "ARMED", f"Expected ARMED, got {after_one['status']}"

    fixtures.start_run(second, api=api)
    second_failure = fixtures.report_failure(second, failure_code="SCHEMA_DRIFT", api=api)
    assert second_failure["consecutive_failure_index"] == 2, (
        f"Expected consecutive_failure_index 2, "
        f"got {second_failure['consecutive_failure_index']}"
    )
    assert_settlement(second_failure, total_charge_credits=3.00, escrow_drawn_units=3.00)

    after_two = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert after_two["consecutive_failure_count"] == 2, (
        f"Two failures must sit below the limit of 3, "
        f"got {after_two['consecutive_failure_count']}"
    )
    assert after_two["status"] == "ARMED", f"Expected ARMED, got {after_two['status']}"
    assert after_two["suspend_reason"] is None, (
        f"Expected suspend_reason null at a count of 2, got {after_two['suspend_reason']!r}"
    )
    assert_money(after_two["escrowed_credit_units"], 4.00, "escrowed_credit_units")

    mid = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(mid, issued=100.00, balance=90.00, escrowed=4.00, consumed=6.00)
    assert_credit_conservation(mid)

    fixtures.start_run(third, api=api)
    succeeded = validate_success(
        api.report_run_success(third, factories.run_success_payload(45000), PORTAL_ADMIN_HEADERS)
    )
    assert succeeded["status"] == "SUCCEEDED", (
        f"Expected SUCCEEDED, got {succeeded['status']}"
    )
    assert succeeded["rows_ingested"] == 45000, (
        f"Expected rows_ingested 45000, got {succeeded['rows_ingested']}"
    )
    assert_settlement(
        succeeded,
        compute_credits=20.00,
        alert_credits=0.00,
        subtotal_credits=20.00,
        reliability_discount_pct=0.05,
        discount_credits=1.00,
        total_charge_credits=19.00,
        escrow_drawn_units=4.00,
        balance_drawn_units=15.00,
    )

    reset = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert reset["consecutive_failure_count"] == 0, (
        f"A success must reset the streak to 0, got {reset['consecutive_failure_count']}"
    )
    assert reset["status"] == "ARMED", f"Expected ARMED, got {reset['status']}"
    assert reset["suspend_reason"] is None, (
        f"Expected suspend_reason null, got {reset['suspend_reason']!r}"
    )
    assert_money(reset["escrowed_credit_units"], 0.00, "escrowed_credit_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(
        department, issued=100.00, balance=75.00, escrowed=0.00, consumed=25.00
    )
    assert_credit_conservation(department)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 45000, (
        f"Expected live_row_count 45000, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 2, (
        f"Expected version_index_high_water 2, got {dataset['version_index_high_water']}"
    )
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="CURRENT")
    assert dataset["days_overdue"] == 0, (
        f"Expected days_overdue 0 after a fresh success, got {dataset['days_overdue']}"
    )
    assert str(dataset["next_due_at"]).startswith("2026-08-08T09:00:00"), (
        f"Expected next_due_at one weekly period on at 2026-08-08T09:00:00Z, "
        f"got {dataset['next_due_at']!r}"
    )


def test_accepting_a_critical_privacy_issue_is_visible_without_running_the_portal_sweep(api):
    """The acceptance response already carries the cascade, and every follow-up read agrees.

    The PRD settles the whole chain inside the deciding request: "An `ACCEPT` decision moves
    the issue `TRIAGED → ACCEPTED`, is blocked when the department's posture is `SUSPENDED`,
    and heads a four-hop cascade." Hop one is in the response body itself — "Hop one records
    the acceptance: `accepted_at` is stamped at the current logical instant,
    `correction_due_at` is set to `accepted_at` plus a severity-dependent allowance of 90
    days for `LOW`, 30 days for `MEDIUM`, 14 days for `HIGH` and 5 days for `CRITICAL`, the
    reporter's `accepted_issue_count` increases by 1, the reporter's `last_credited_at`
    becomes the current logical instant, and the reporter's `reputation_score` and
    `vote_weight` are re-derived." Hop two takes the dataset out of public service: "the
    dataset transitions `PUBLISHED → UNDER_REMEDIATION`, `public_access_suspended` becomes
    true and `remediation_opened_at` is stamped at the current logical instant". And the
    department follows in the same breath:
    "Finally the department's `remediation_dataset_count` and its other counters,
    `risk_points` and `compliance_posture` are re-derived."

    Nothing here waits for the sweep, so this test never runs one and never moves the clock.
    Reading the dataset, the scorecard and the reporter straight afterwards must show the
    settled figures: "`remediation_dataset_count` is the number of the department's datasets
    whose `publication_status` is `UNDER_REMEDIATION`.", "`risk_points` is then three points
    for each breached dataset, plus two points for each stale dataset, plus two points for
    each dataset under remediation, plus one point for each overdue correction." and "From
    `risk_points` the posture follows on inclusive boundaries: at least 6 points is
    `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0 points is `OPEN`."
    — two points, so `RESTRICTED`. The reporter is repriced the same way: "The raw figure
    starts from a base of 50, adds 6 points for each accepted issue in
    `accepted_issue_count`, subtracts 4 points for each rejected issue in
    `rejected_issue_count`, and adds 2 points for each approved showcase in
    `approved_showcase_count`." with no decay yet, since "The distance of the raw figure from
    the base of 50 is then multiplied by 0.80 raised to the power of `decay_epochs`, and that
    shrunken distance is added back to the base." — 56.00, and "`vote_weight` follows on
    inclusive thresholds: 3 when `reputation_score` is at least 70.00, 2 when it is at least
    40.00 but below 70.00, and 1 below 40.00."

    Design: Corner/consistency_model/issue_acceptance_cascade_is_visible_in_the_same_response
    """
    ctx = fixtures.setup_published_dataset(api=api)
    ctx.update(fixtures.setup_member(api=api))
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"],
        ctx["member_id"],
        ctx["department_id"],
        severity="CRITICAL",
        category="PRIVACY",
        api=api,
        description=PRIVACY_DEFECT,
    )

    decided = validate_success(
        api.decide_quality_issue(
            issue["id"],
            factories.decision_payload("ACCEPT"),
            ctx["coordinator_headers"],
        )
    )

    assert decided["status"] == "ACCEPTED", (
        f"The deciding response must already read ACCEPTED, got {decided['status']}"
    )
    assert str(decided["accepted_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected accepted_at at the current logical instant 2026-08-01T00:00:00Z, "
        f"got {decided['accepted_at']!r}"
    )
    assert str(decided["correction_due_at"]).startswith("2026-08-06T00:00:00"), (
        f"Expected correction_due_at five days on at 2026-08-06T00:00:00Z, "
        f"got {decided['correction_due_at']!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="UNDER_REMEDIATION")
    assert dataset["public_access_suspended"] is True, (
        f"Expected public_access_suspended true immediately, "
        f"got {dataset['public_access_suspended']!r}"
    )
    assert str(dataset["remediation_opened_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected remediation_opened_at stamped at 2026-08-01T00:00:00Z, "
        f"got {dataset['remediation_opened_at']!r}"
    )

    scorecard = fixtures.read_scorecard(ctx["department_id"], api=api)
    assert_posture(
        scorecard,
        risk_points=2,
        compliance_posture="RESTRICTED",
        breached=0,
        stale=0,
        remediation=1,
        overdue_corrections=0,
    )

    member = fixtures.read_member(ctx["member_id"], api=api)
    assert member["accepted_issue_count"] == 1, (
        f"Expected accepted_issue_count 1, got {member['accepted_issue_count']}"
    )
    assert member["rejected_issue_count"] == 0, (
        f"Expected rejected_issue_count 0, got {member['rejected_issue_count']}"
    )
    assert_money(member["reputation_score"], 56.00, "reputation_score")
    assert member["vote_weight"] == 2, (
        f"Expected vote_weight 2 at a reputation of 56.00, got {member['vote_weight']}"
    )
    assert str(member["last_credited_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected last_credited_at at 2026-08-01T00:00:00Z, "
        f"got {member['last_credited_at']!r}"
    )
