"""
Remediation and the published record: the four-hop cascade a critical privacy
acceptance sets off, the corrective version that lifts it, the escrow released by
decommissioning, and the retraction that restores a predecessor version.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    assert_credit_buckets,
    assert_credit_conservation,
    assert_dataset_states,
    assert_exactly_one_live_version,
    assert_money,
    assert_posture,
    assert_scorecard_balanced,
    find_version_by_index,
    fixtures,
    validate_error,
    validate_success,
)

SLOT = "2026-08-01T09:00:00Z"
PRIVACY_DEFECT = "Geocoded columns permit household reidentification"
REMEDIATION_DEFECT = "Published extract still contains household-level coordinates"


def _accepted_privacy_issue(api, description):
    """An armed pipeline with a pending run, and a triaged CRITICAL PRIVACY issue."""
    ctx = fixtures.setup_armed_pipeline(api=api)
    ctx["run"] = fixtures.schedule_run(ctx["pipeline_id"], SLOT, api=api)
    ctx["run_id"] = ctx["run"]["id"]
    ctx.update(fixtures.setup_member(api=api))
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"],
        ctx["member_id"],
        ctx["department_id"],
        severity="CRITICAL",
        category="PRIVACY",
        api=api,
        description=description,
    )
    ctx["issue"] = issue
    ctx["issue_id"] = issue["id"]
    return ctx


def test_accepting_a_critical_privacy_issue_cascades_to_pipeline_run_and_currency(api):
    """One acceptance moves the issue, the dataset, the pipeline, its run and the clock floor.

    The PRD: "Hop one records the acceptance: `accepted_at` is stamped at the current
    logical instant, `correction_due_at` is set to `accepted_at` plus a
    severity-dependent allowance of 90 days for `LOW`, 30 days for `MEDIUM`, 14 days for
    `HIGH` and 5 days for `CRITICAL`, …". Hop two then fires because the issue is
    critical, its category is privacy and the dataset is published: "the dataset
    transitions `PUBLISHED → UNDER_REMEDIATION`, `public_access_suspended` becomes true
    and `remediation_opened_at` is stamped at the current logical instant". Hop three:
    "every pipeline of that dataset whose `status` is `ARMED` transitions to `SUSPENDED`
    with `suspend_reason` `REMEDIATION_HOLD`." And hop four: "the pipeline's `SCHEDULED`
    and `RETRY_QUEUED` runs become `SKIPPED` with `skip_reason` `PIPELINE_SUSPENDED`, and
    the dataset's `currency_status` takes the `STALE` floor."

    Suspension is not a refund — "`escrowed_credit_units` are retained and remain counted
    in the department's `credits_escrowed_units`; the runner's `armed_window_count`
    decreases by 1 while the window itself stays reserved against the cooldown buffer".

    Design: Difficulty/transitive_cascade/issue_accept_privacy_remediation_four_hop_chain
    """
    ctx = _accepted_privacy_issue(api, PRIVACY_DEFECT)

    issue = fixtures.accept_quality_issue(ctx["issue_id"], ctx["department_id"], api=api)

    assert issue["status"] == "ACCEPTED", f"Expected ACCEPTED, got {issue['status']}"
    assert str(issue["accepted_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected accepted_at 2026-08-01T00:00:00Z, got {issue['accepted_at']!r}"
    )
    assert str(issue["correction_due_at"]).startswith("2026-08-06T00:00:00"), (
        f"Expected correction_due_at five days on at 2026-08-06T00:00:00Z, "
        f"got {issue['correction_due_at']!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(
        dataset, publication_status="UNDER_REMEDIATION", currency_status="STALE"
    )
    assert dataset["public_access_suspended"] is True, (
        f"Expected public_access_suspended true, got {dataset['public_access_suspended']!r}"
    )
    assert str(dataset["remediation_opened_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected remediation_opened_at stamped at the current instant, "
        f"got {dataset['remediation_opened_at']!r}"
    )
    assert dataset["staleness_alert_count"] == 1, (
        f"Expected staleness_alert_count 1, got {dataset['staleness_alert_count']}"
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "SUSPENDED", f"Expected SUSPENDED, got {pipeline['status']}"
    assert pipeline["suspend_reason"] == "REMEDIATION_HOLD", (
        f"Expected suspend_reason REMEDIATION_HOLD, got {pipeline['suspend_reason']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 10.00, "escrowed_credit_units")

    run = fixtures.read_run(ctx["run_id"], api=api)
    assert run["status"] == "SKIPPED", f"Expected SKIPPED, got {run['status']}"
    assert run["skip_reason"] == "PIPELINE_SUSPENDED", (
        f"Expected skip_reason PIPELINE_SUSPENDED, got {run['skip_reason']}"
    )

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"Expected armed_window_count 0 after the suspension, "
        f"got {runner['armed_window_count']}"
    )


def test_the_acceptance_credits_the_reporter_and_re_derives_the_department(api):
    """The same acceptance pays the reporter and re-prices the department's posture.

    The PRD: "The raw figure starts from a base of 50, adds 6 points for each accepted
    issue in `accepted_issue_count`, subtracts 4 points for each rejected issue in
    `rejected_issue_count`, and adds 2 points for each approved showcase in
    `approved_showcase_count`." With no elapsed decay epoch the reporter lands on 56.00,
    and "`vote_weight` follows on inclusive thresholds: 3 when `reputation_score` is at
    least 70.00, 2 when it is at least 40.00 but below 70.00, and 1 below 40.00."

    On the department side the dataset now counts twice over — once under remediation and
    once stale — since "`risk_points` is then three points for each breached dataset,
    plus two points for each stale dataset, plus two points for each dataset under
    remediation, plus one point for each overdue correction." Four points is
    `RESTRICTED`, and the retained escrow keeps the ledger balanced.

    Design: Difficulty/transitive_cascade/issue_accept_privacy_remediation_four_hop_chain
    """
    ctx = _accepted_privacy_issue(api, PRIVACY_DEFECT)

    fixtures.accept_quality_issue(ctx["issue_id"], ctx["department_id"], api=api)

    member = fixtures.read_member(ctx["member_id"], api=api)
    assert member["accepted_issue_count"] == 1, (
        f"Expected accepted_issue_count 1, got {member['accepted_issue_count']}"
    )
    assert_money(member["reputation_score"], 56.00, "reputation_score")
    assert member["vote_weight"] == 2, f"Expected vote_weight 2, got {member['vote_weight']}"
    assert str(member["last_credited_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected last_credited_at at the acceptance instant, "
        f"got {member['last_credited_at']!r}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department,
        remediation=1,
        stale=1,
        breached=0,
        risk_points=4,
        compliance_posture="RESTRICTED",
    )
    assert_credit_buckets(
        department, issued=100.00, balance=90.00, escrowed=10.00, consumed=0.00
    )
    assert_credit_conservation(department)


def test_linking_a_corrective_version_returns_the_dataset_to_published(api):
    """A `CORRECTION` version attached to the issue lifts remediation but not the stale floor.

    The PRD: "It sets the issue's `resolution_version_id` to that version, sets that
    version's own `correction_issue_id` back to the issue, moves the issue `ACCEPTED →
    CORRECTED`, and clears `correction_breached`." and "When the dataset is sitting in
    `UNDER_REMEDIATION` and no *other* quality issue on that dataset is still `ACCEPTED`
    with `severity` `CRITICAL` and `category` `PRIVACY`, the same request returns the
    dataset `UNDER_REMEDIATION → PUBLISHED`: …" — while "the `STALE` floor imposed by a
    still-suspended pipeline continues to apply for as long as that pipeline stays
    suspended."

    Design: Difficulty/non_linear_state_machine/dataset_remediation_and_return_to_published_cycle
    """
    ctx = _accepted_privacy_issue(api, REMEDIATION_DEFECT)
    fixtures.accept_quality_issue(ctx["issue_id"], ctx["department_id"], api=api)
    before = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(
        before, publication_status="UNDER_REMEDIATION", currency_status="STALE"
    )

    correction = fixtures.publish_version(
        ctx["dataset_id"],
        ctx["department_id"],
        "CORRECTION",
        51000,
        api=api,
        correction_issue_id=ctx["issue_id"],
        notes="Coordinates generalised to census tract centroids",
    )
    assert correction["status"] == "LIVE", f"Expected LIVE, got {correction['status']}"
    assert correction["version_index"] == 2, (
        f"Expected version_index 2, got {correction['version_index']}"
    )
    assert correction["change_type"] == "CORRECTION", (
        f"Expected change_type CORRECTION, got {correction['change_type']}"
    )

    issue = fixtures.link_correction(
        ctx["issue_id"], ctx["department_id"], correction["id"], api=api
    )
    assert issue["status"] == "CORRECTED", f"Expected CORRECTED, got {issue['status']}"
    assert issue["resolution_version_id"] == correction["id"], (
        f"Expected resolution_version_id {correction['id']}, "
        f"got {issue['resolution_version_id']!r}"
    )
    assert issue["correction_breached"] is False, (
        f"Expected correction_breached false, got {issue['correction_breached']!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="STALE")
    assert dataset["public_access_suspended"] is False, (
        f"Expected public_access_suspended false, got {dataset['public_access_suspended']!r}"
    )
    assert dataset["remediation_opened_at"] is None, (
        f"Expected remediation_opened_at cleared, got {dataset['remediation_opened_at']!r}"
    )


def test_resuming_the_pipeline_lifts_the_stale_floor_and_clears_the_posture(api):
    """Resumption re-derives currency from the clock alone and empties the risk counters.

    The PRD: "It sets `consecutive_failure_count` back to 0, clears `suspend_reason`,
    increases the runner's `armed_window_count` by 1, lifts the `STALE` floor so that the
    dataset's `currency_status` is re-derived purely from the logical clock, …". The
    corrective version had already reset the publication instant, so with the floor gone
    the dataset reads `CURRENT` at the corrected row count, and the department — no
    longer counting a remediation or a stale dataset — falls back to `OPEN`.

    Design: Difficulty/non_linear_state_machine/dataset_remediation_and_return_to_published_cycle
    """
    ctx = _accepted_privacy_issue(api, REMEDIATION_DEFECT)
    fixtures.accept_quality_issue(ctx["issue_id"], ctx["department_id"], api=api)
    correction = fixtures.publish_version(
        ctx["dataset_id"],
        ctx["department_id"],
        "CORRECTION",
        51000,
        api=api,
        correction_issue_id=ctx["issue_id"],
        notes="Coordinates generalised to census tract centroids",
    )
    fixtures.link_correction(ctx["issue_id"], ctx["department_id"], correction["id"], api=api)

    pipeline = fixtures.resume_pipeline(ctx["pipeline_id"], ctx["department_id"], api=api)

    assert pipeline["status"] == "ARMED", f"Expected ARMED, got {pipeline['status']}"
    assert pipeline["suspend_reason"] is None, (
        f"Expected suspend_reason cleared, got {pipeline['suspend_reason']!r}"
    )
    assert pipeline["consecutive_failure_count"] == 0, (
        f"Expected consecutive_failure_count 0, got {pipeline['consecutive_failure_count']}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="CURRENT")
    assert dataset["live_row_count"] == 51000, (
        f"Expected live_row_count 51000, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 2, (
        f"Expected version_index_high_water 2, got {dataset['version_index_high_water']}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department,
        remediation=0,
        stale=0,
        breached=0,
        risk_points=0,
        compliance_posture="OPEN",
    )


def test_decommissioning_an_armed_pipeline_returns_the_escrow_to_the_balance(api):
    """Escrow held against a window comes back whole when the window is given up.

    The PRD: "From `ARMED`, `ARMED → DECOMMISSIONED` releases the escrow — the pipeline's
    current `escrowed_credit_units` are added back to the department's
    `credit_balance_units` and subtracted from its `credits_escrowed_units`, and the
    pipeline's `escrowed_credit_units` is set to 0.00 —".

    The reconciliation must hold on both sides of the release, since the scorecard carries
    "a boolean `credit_ledger_balanced` asserting that the conservation invariant of
    §2.10 currently holds": 100.00 issued reads 90.00 / 10.00 / 0.00 while armed and
    100.00 / 0.00 / 0.00 once released.

    Design: Difficulty/compensating_invariant/escrow_release_on_decommission_restores_credit_conservation
    """
    ctx = fixtures.setup_armed_pipeline(api=api)

    while_armed = fixtures.read_scorecard(ctx["department_id"], api=api)
    assert_credit_buckets(
        while_armed, issued=100.00, balance=90.00, escrowed=10.00, consumed=0.00
    )
    assert_scorecard_balanced(while_armed)

    fixtures.decommission_pipeline(ctx["pipeline_id"], ctx["department_id"], api=api)

    after_release = fixtures.read_scorecard(ctx["department_id"], api=api)
    assert_credit_buckets(
        after_release, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00
    )
    assert_scorecard_balanced(after_release)


def test_decommissioned_pipeline_keeps_its_requirement_and_frees_the_runner(api):
    """The released pipeline still advertises what it would cost to arm again.

    The same transition that releases the escrow also hands the window back, since it
    "moves every `SCHEDULED` or `RETRY_QUEUED` run to `SKIPPED` with a `skip_reason` of
    `PIPELINE_DECOMMISSIONED`, decreases the runner's `armed_window_count` by 1, and
    increments the pipeline's `version`." The cadence-derived requirement is untouched by
    the release, because
    "That run count is multiplied by 2 credits per run, and the product is capped at 60
    credits, giving `escrow_required_units`." A decommissioned pipeline also imposes no
    freshness floor — "Pipelines in `DRAFT` or `DECOMMISSIONED` impose no floor." — so
    the dataset stays `CURRENT`.

    Design: Difficulty/compensating_invariant/escrow_release_on_decommission_restores_credit_conservation
    """
    ctx = fixtures.setup_armed_pipeline(api=api)

    pipeline = fixtures.decommission_pipeline(
        ctx["pipeline_id"], ctx["department_id"], api=api
    )

    assert pipeline["status"] == "DECOMMISSIONED", (
        f"Expected DECOMMISSIONED, got {pipeline['status']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")
    assert_money(pipeline["escrow_required_units"], 10.00, "escrow_required_units")

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"Expected armed_window_count 0, got {runner['armed_window_count']}"
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="CURRENT")


def test_retracting_the_live_version_restores_its_predecessor_exactly(api):
    """Retraction hands the public record back to the previous version without reusing indices.

    The PRD: "On success the version moves `LIVE → RETRACTED` with `retracted_at`
    stamped, and its predecessor moves `SUPERSEDED → LIVE` with `superseded_at` cleared
    back to null." The row count follows the restored version — "The dataset's
    `live_row_count` is restored to the predecessor's `row_count`" — while the index
    high-water mark does not rewind, and "At any moment a dataset that has been published
    at least once and never fully retracted has exactly one version in `LIVE`."

    Design: Difficulty/compensating_invariant/version_retract_restores_live_row_count_with_monotonic_high_water
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    second = fixtures.publish_version(
        ctx["dataset_id"],
        ctx["department_id"],
        "SCHEMA_CHANGE",
        61000,
        api=api,
        notes="Added vehicle-class breakdown columns",
    )
    before = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert before["live_row_count"] == 61000, (
        f"Expected live_row_count 61000 before the retraction, got {before['live_row_count']}"
    )
    assert before["version_index_high_water"] == 2, (
        f"Expected version_index_high_water 2, got {before['version_index_high_water']}"
    )

    retracted = validate_success(
        api.retract_dataset_version(
            second["id"],
            ctx["coordinator_headers"],
            {"reason": "Vehicle-class columns leaked an internal code list"},
        )
    )
    assert retracted["status"] == "RETRACTED", (
        f"Expected RETRACTED, got {retracted['status']}"
    )
    assert str(retracted["retracted_at"]).startswith("2026-08-01T00:00:00"), (
        f"Expected retracted_at at the current logical instant, "
        f"got {retracted['retracted_at']!r}"
    )

    versions = fixtures.versions_of_dataset(ctx["dataset_id"], api=api)
    restored = find_version_by_index(versions, 1)
    assert restored["status"] == "LIVE", (
        f"Expected the first version restored to LIVE, got {restored['status']}"
    )
    assert restored["superseded_at"] is None, (
        f"Expected superseded_at cleared, got {restored['superseded_at']!r}"
    )
    live = assert_exactly_one_live_version(versions)
    assert live["version_index"] == 1, (
        f"Expected the restored version to be the only LIVE one, "
        f"got version_index {live['version_index']}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 50000, (
        f"Expected live_row_count restored to 50000, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 2, (
        f"The high-water mark must not decrease, "
        f"got {dataset['version_index_high_water']}"
    )


def test_retracting_the_restored_first_version_is_refused(api):
    """There is nothing behind version 1 to restore, so the compensation stops there.

    The PRD: "Retracting the `LIVE` version takes an optional `reason` and requires a
    predecessor to restore: the version's `version_index` must be at least 2 and the
    immediately preceding version must currently be `SUPERSEDED`, or the request is
    refused with `ERR_NO_PREDECESSOR_VERSION`." The first version fails the index test
    outright, and the refusal must leave it `LIVE` and the dataset's row count where the
    restoration put it.

    Design: Difficulty/compensating_invariant/version_retract_restores_live_row_count_with_monotonic_high_water
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    second = fixtures.publish_version(
        ctx["dataset_id"],
        ctx["department_id"],
        "SCHEMA_CHANGE",
        61000,
        api=api,
        notes="Added vehicle-class breakdown columns",
    )
    validate_success(
        api.retract_dataset_version(
            second["id"],
            ctx["coordinator_headers"],
            {"reason": "Vehicle-class columns leaked an internal code list"},
        )
    )
    first = find_version_by_index(
        fixtures.versions_of_dataset(ctx["dataset_id"], api=api), 1
    )

    validate_error(
        api.retract_dataset_version(
            first["id"],
            ctx["coordinator_headers"],
            {"reason": "Attempt to retract the restored first version"},
        ),
        "ERR_NO_PREDECESSOR_VERSION",
        409,
    )

    unchanged = validate_success(api.get_dataset_version(first["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "LIVE", (
        f"The refused retraction must leave version 1 LIVE, got {unchanged['status']}"
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 50000, (
        f"Expected live_row_count 50000, got {dataset['live_row_count']}"
    )
