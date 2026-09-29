"""
Per-endpoint behaviour: the runner update, the licence retirement action, the
portal sweep's own report, the foreign-key resolution on request fulfilment, the
per-dataset analytics projection, and the high-value commitment.

Each test drives one endpoint against a precondition built entirely through the
public API and pins the observable result the PRD assigns to that call.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    ERR_DATASET_NOT_FOUND,
    NON_EXISTENT_UUID,
    PORTAL_ADMIN_HEADERS,
    assert_common_fields,
    assert_dataset_states,
    assert_money,
    assert_posture,
    assert_priority,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

MONTHLY_DATASET = {
    "title": "Library Circulation Statistics",
    "slug": "library-circulation",
    "description": "Monthly circulation totals by branch.",
    "update_frequency": "MONTHLY",
    "public_demand_score": 20,
    "policy_value_score": 20,
}

AGING_SWEEP_INSTANT = "2026-08-20T00:00:00Z"
STALE_SWEEP_INSTANT = "2026-08-25T00:00:00Z"


def test_runner_patch_updates_status_and_cooldown_and_bumps_the_row_version(api):
    """Updating a runner writes both optional fields and leaves its reservation count alone.

    The PRD: "A new runner has `status` `ACTIVE` and `armed_window_count` 0." and
    "The office may later update the runner's `status` — to `DRAINING` or `OFFLINE`
    to take it out of service, or back to `ACTIVE` — and may adjust
    `cooldown_minutes`; a cooldown change re-scopes future overlap checks only and
    never retroactively invalidates a pipeline that is already armed."

    One `PATCH` supplying both fields must therefore land both, and because
    "`version` (integer): a counter that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row, including mutations the server performs
    on its own initiative as a cascade from some other resource's transition." the
    single mutation moves the runner from `version` 1 to `version` 2. No pipeline was
    ever armed against this runner, so its `armed_window_count` stays 0, and a
    subsequent read returns the persisted values rather than the originals.

    Design: Corner/endpoints/runner_patch_updates_status_and_cooldown
    """
    fixtures.reset_clock_to_start(api=api)

    runner = fixtures.create_ingest_runner(api=api)
    assert runner["status"] == "ACTIVE", (
        f"Expected a new runner to be ACTIVE, got {runner['status']}"
    )
    assert runner["cooldown_minutes"] == 15, (
        f"Expected cooldown_minutes 15, got {runner['cooldown_minutes']}"
    )
    assert runner["armed_window_count"] == 0, (
        f"Expected armed_window_count 0 on a new runner, got {runner['armed_window_count']}"
    )
    assert_common_fields(runner, expected_version=1)

    updated = validate_success(
        api.update_ingest_runner(
            runner["id"],
            factories.runner_update_payload(status="DRAINING", cooldown_minutes=30),
            PORTAL_ADMIN_HEADERS,
        )
    )
    assert updated["status"] == "DRAINING", (
        f"Expected status DRAINING after the update, got {updated['status']}"
    )
    assert updated["cooldown_minutes"] == 30, (
        f"Expected cooldown_minutes 30 after the update, got {updated['cooldown_minutes']}"
    )
    assert updated["armed_window_count"] == 0, (
        f"An update must not touch armed_window_count, got {updated['armed_window_count']}"
    )
    assert_common_fields(updated, expected_version=2)

    reread = validate_success(api.get_ingest_runner(runner["id"], PORTAL_ADMIN_HEADERS))
    assert reread["status"] == "DRAINING", (
        f"Expected the persisted status DRAINING, got {reread['status']}"
    )
    assert reread["cooldown_minutes"] == 30, (
        f"Expected the persisted cooldown_minutes 30, got {reread['cooldown_minutes']}"
    )
    assert reread["version"] == 2, (
        f"Expected the persisted version 2, got {reread['version']}"
    )


def test_license_retirement_flips_the_retired_flag_and_preserves_its_permission_terms(api):
    """Retirement is a one-field action: `retired` becomes true and nothing else moves.

    The PRD: "A new licence has `retired` false. Retiring a licence sets `retired` to
    true; metadata records already accepted against it keep the reference, but no
    further record may be accepted against it and no dataset backed by it may be
    published." The action names exactly one field, so the licence's `code`, `name`
    and its three permission booleans must survive it untouched, and so must the
    class those booleans derive: with attribution required, commercial use allowed
    and share-alike not required, "otherwise, if attribution is required, commercial
    use is allowed and share-alike is not required, the class is `ATTRIBUTION`;"

    The retirement is one mutation of one row, and "`version` (integer): a counter
    that starts at 1 on creation and increments by exactly 1 on every mutation of
    that row, including mutations the server performs on its own initiative as a
    cascade from some other resource's transition." puts the licence at `version` 2.

    Design: Corner/endpoints/license_retire_action_flips_retired_flag_only
    """
    fixtures.reset_clock_to_start(api=api)

    license_term = fixtures.create_license(api=api)
    assert license_term["retired"] is False, (
        f"Expected a new licence to have retired false, got {license_term['retired']!r}"
    )
    assert license_term["reuse_permission_class"] == "ATTRIBUTION", (
        f"Expected reuse_permission_class ATTRIBUTION, "
        f"got {license_term['reuse_permission_class']}"
    )
    assert_common_fields(license_term, expected_version=1)

    retired = validate_success(api.retire_license(license_term["id"], PORTAL_ADMIN_HEADERS))
    assert retired["retired"] is True, (
        f"Retirement must set retired to true, got {retired['retired']!r}"
    )
    assert_common_fields(retired, expected_version=2)
    assert retired["code"] == "CC-BY-4.0", (
        f"Retirement must preserve code CC-BY-4.0, got {retired['code']}"
    )
    assert retired["name"] == "Creative Commons Attribution 4.0", (
        f"Retirement must preserve the licence name, got {retired['name']!r}"
    )
    assert retired["attribution_required"] is True, (
        f"Retirement must preserve attribution_required true, "
        f"got {retired['attribution_required']!r}"
    )
    assert retired["commercial_use_allowed"] is True, (
        f"Retirement must preserve commercial_use_allowed true, "
        f"got {retired['commercial_use_allowed']!r}"
    )
    assert retired["share_alike"] is False, (
        f"Retirement must preserve share_alike false, got {retired['share_alike']!r}"
    )
    assert retired["reuse_permission_class"] == "ATTRIBUTION", (
        f"Retirement must preserve reuse_permission_class ATTRIBUTION, "
        f"got {retired['reuse_permission_class']}"
    )

    reread = validate_success(api.get_license(license_term["id"], ANONYMOUS_HEADERS))
    assert reread["retired"] is True, (
        f"Expected the persisted retired flag to be true, got {reread['retired']!r}"
    )
    assert reread["reuse_permission_class"] == "ATTRIBUTION", (
        f"Expected the persisted reuse_permission_class ATTRIBUTION, "
        f"got {reread['reuse_permission_class']}"
    )


def test_ops_sweep_recomputes_every_published_dataset_and_reports_its_per_sweep_counters(api):
    """One sweep walks both published datasets and reports the counters it earned.

    The PRD pins what a sweep touches and what it says about it: "Step one recomputes
    `days_overdue` and `currency_status` for every non-retired published dataset by
    the derivation above, which is where the clock-driven transitions
    `CURRENT → AGING`, `AGING → STALE` and `STALE → BREACHED` all happen; a dataset
    only participates when its `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`, and the `CURRENT → AGING` step additionally requires
    `next_due_at` to be non-null." and "Step two emits staleness alerting: every
    dataset that is entering or remaining in `STALE` or `BREACHED` emits exactly one
    alert per sweep, increasing `staleness_alert_count` by 1 and setting
    `last_staleness_alert_at` to the current logical instant. A dataset that merely
    became `AGING` emits nothing." and "Step five walks the departments in ascending
    `created_at` order — deliberately after every dataset has been recomputed in step
    one — re-deriving each department's four counters, its `risk_points` and its
    `compliance_posture`." The report itself is named: "The sweep reports what it did:
    a count of `datasets_recomputed`, a count of `currency_transitions`, a count of
    `staleness_alerts_emitted`, counts of `issues_triage_breached` and
    `issues_correction_breached`, and a count of `departments_recomputed` alongside
    `postures_changed`."

    Both datasets are published on 2026-08-01. The weekly one falls due on 2026-08-08
    and, re-scored at publication under the observed variant with no usage epochs at
    all, stands at 33.60 and `TIER_3`, so "Third, a grace allowance is read off the
    dataset's `priority_tier`: 2 days for `TIER_1`, 7 days for `TIER_2`, 14 days for
    `TIER_3` — the more valuable the dataset, the shorter its rope." gives it 14 days
    of rope. The monthly one is not due until 2026-08-31. A sweep on 2026-08-20 finds
    the weekly dataset 12 days overdue and the monthly dataset not due, and "It is
    `AGING` when `days_overdue` is greater than zero but no greater than the grace
    allowance; the boundary is inclusive, so a `days_overdue` exactly equal to the
    grace is still `AGING` and one day beyond it is `STALE`. It is `STALE` when
    `days_overdue` exceeds the grace but does not exceed twice the grace." makes that
    one currency transition and no alert. A sweep on 2026-08-25 finds it 17 days
    overdue and therefore `STALE`: one more transition, one alert, and one posture
    change, because "`risk_points` is then three points for each breached dataset,
    plus two points for each stale dataset, plus two points for each dataset under
    remediation, plus one point for each overdue correction." scores two points, and
    "From `risk_points` the posture follows on inclusive boundaries: at least 6 points
    is `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0 points
    is `OPEN`." reads that as `RESTRICTED`. A second sweep at the same instant
    transitions nothing and changes no posture, yet still re-alerts the stale dataset
    exactly once.

    Design: Corner/endpoints/ops_run_sweeps_every_dataset_and_reports_per_sweep_counts
    """
    ctx = fixtures.setup_published_dataset(api=api)
    weekly_id = ctx["dataset_id"]
    assert_priority(
        ctx["dataset"],
        priority_score=33.60,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert str(ctx["dataset"]["next_due_at"]).startswith("2026-08-08T00:00:00"), (
        f"Expected next_due_at 2026-08-08T00:00:00Z for the weekly dataset, "
        f"got {ctx['dataset']['next_due_at']!r}"
    )

    monthly = fixtures.inventory_dataset(ctx["department_id"], api=api, **MONTHLY_DATASET)
    monthly_id = monthly["id"]
    fixtures.screen_dataset(monthly_id, ctx["department_id"], api=api)
    fixtures.land_accepted_metadata(
        monthly_id,
        ctx["license_id"],
        ctx["department_id"],
        api=api,
        declared_update_frequency="MONTHLY",
    )
    fixtures.land_cleared_assessment(monthly_id, api=api)
    fixtures.mark_ready(monthly_id, ctx["department_id"], api=api)
    monthly = fixtures.publish_dataset(
        monthly_id, ctx["department_id"], initial_row_count=12000, api=api
    )
    assert str(monthly["next_due_at"]).startswith("2026-08-31T00:00:00"), (
        f"Expected next_due_at 2026-08-31T00:00:00Z for the monthly dataset, "
        f"got {monthly['next_due_at']!r}"
    )

    fixtures.set_clock(AGING_SWEEP_INSTANT, api=api)
    aging_report = validate_success(api.run_ops_sweep(PORTAL_ADMIN_HEADERS))
    assert aging_report["datasets_recomputed"] == 2, (
        f"Expected datasets_recomputed 2, got {aging_report['datasets_recomputed']}"
    )
    assert aging_report["currency_transitions"] == 1, (
        f"Expected currency_transitions 1, got {aging_report['currency_transitions']}"
    )
    assert aging_report["staleness_alerts_emitted"] == 0, (
        f"An AGING dataset must emit no alert, "
        f"got staleness_alerts_emitted {aging_report['staleness_alerts_emitted']}"
    )
    assert aging_report["departments_recomputed"] == 1, (
        f"Expected departments_recomputed 1, got {aging_report['departments_recomputed']}"
    )
    assert aging_report["postures_changed"] == 0, (
        f"Expected postures_changed 0, got {aging_report['postures_changed']}"
    )

    aging = fixtures.read_dataset(weekly_id, api=api)
    assert aging["days_overdue"] == 12, (
        f"Expected days_overdue 12 for the weekly dataset, got {aging['days_overdue']}"
    )
    assert_dataset_states(aging, publication_status="PUBLISHED", currency_status="AGING")
    assert aging["staleness_alert_count"] == 0, (
        f"Expected staleness_alert_count 0 while AGING, got {aging['staleness_alert_count']}"
    )
    untouched = fixtures.read_dataset(monthly_id, api=api)
    assert untouched["days_overdue"] == 0, (
        f"Expected days_overdue 0 for the not-yet-due monthly dataset, "
        f"got {untouched['days_overdue']}"
    )
    assert_dataset_states(untouched, currency_status="CURRENT")
    assert_posture(
        fixtures.read_department(ctx["department_id"], api=api),
        breached=0,
        stale=0,
        risk_points=0,
        compliance_posture="OPEN",
    )

    fixtures.set_clock(STALE_SWEEP_INSTANT, api=api)
    stale_report = validate_success(api.run_ops_sweep(PORTAL_ADMIN_HEADERS))
    assert stale_report["datasets_recomputed"] == 2, (
        f"Expected datasets_recomputed 2, got {stale_report['datasets_recomputed']}"
    )
    assert stale_report["currency_transitions"] == 1, (
        f"Expected currency_transitions 1, got {stale_report['currency_transitions']}"
    )
    assert stale_report["staleness_alerts_emitted"] == 1, (
        f"Expected staleness_alerts_emitted 1, "
        f"got {stale_report['staleness_alerts_emitted']}"
    )
    assert stale_report["departments_recomputed"] == 1, (
        f"Expected departments_recomputed 1, got {stale_report['departments_recomputed']}"
    )
    assert stale_report["postures_changed"] == 1, (
        f"Expected postures_changed 1, got {stale_report['postures_changed']}"
    )

    stale = fixtures.read_dataset(weekly_id, api=api)
    assert stale["days_overdue"] == 17, (
        f"Expected days_overdue 17 for the weekly dataset, got {stale['days_overdue']}"
    )
    assert_dataset_states(stale, currency_status="STALE")
    assert stale["staleness_alert_count"] == 1, (
        f"Expected exactly one alert on entering STALE, got {stale['staleness_alert_count']}"
    )
    assert str(stale["last_staleness_alert_at"]).startswith("2026-08-25T00:00:00"), (
        f"Expected last_staleness_alert_at 2026-08-25T00:00:00Z, "
        f"got {stale['last_staleness_alert_at']!r}"
    )
    assert_posture(
        fixtures.read_department(ctx["department_id"], api=api),
        breached=0,
        stale=1,
        risk_points=2,
        compliance_posture="RESTRICTED",
    )

    repeat_report = validate_success(api.run_ops_sweep(PORTAL_ADMIN_HEADERS))
    assert repeat_report["datasets_recomputed"] == 2, (
        f"Expected datasets_recomputed 2, got {repeat_report['datasets_recomputed']}"
    )
    assert repeat_report["currency_transitions"] == 0, (
        f"A dataset remaining STALE is no transition, "
        f"got currency_transitions {repeat_report['currency_transitions']}"
    )
    assert repeat_report["staleness_alerts_emitted"] == 1, (
        f"A dataset remaining STALE re-alerts once per sweep, "
        f"got staleness_alerts_emitted {repeat_report['staleness_alerts_emitted']}"
    )
    assert repeat_report["postures_changed"] == 0, (
        f"Expected postures_changed 0 on the repeated sweep, "
        f"got {repeat_report['postures_changed']}"
    )

    re_alerted = fixtures.read_dataset(weekly_id, api=api)
    assert re_alerted["staleness_alert_count"] == 2, (
        f"Expected staleness_alert_count 2 after the second STALE sweep, "
        f"got {re_alerted['staleness_alert_count']}"
    )
    assert_dataset_states(re_alerted, currency_status="STALE")
    quiet = fixtures.read_dataset(monthly_id, api=api)
    assert quiet["staleness_alert_count"] == 0, (
        f"The not-yet-due monthly dataset must never alert, "
        f"got {quiet['staleness_alert_count']}"
    )
    assert_dataset_states(quiet, currency_status="CURRENT")


def test_fulfilling_a_request_with_an_unknown_dataset_is_refused_and_leaves_the_link_null(api):
    """The body's `dataset_id` must resolve, and a request that fails on it keeps its state.

    The PRD makes body foreign keys their own gate: "Body foreign keys, on
    `POST /open-data/datasets`, `POST /open-data/metadata-records`,
    `POST /open-data/privacy-assessments`, `POST /open-data/publication-pipelines`,
    `POST /open-data/pipeline-runs`, `POST /open-data/dataset-versions`,
    `POST /open-data/quality-issues`, `POST /open-data/dataset-requests`,
    `POST /open-data/dataset-requests/{requestId}/votes`,
    `POST /open-data/dataset-requests/{requestId}/fulfill`,
    `POST /open-data/quality-issues/{issueId}/link-correction` and
    `POST /open-data/datasets/{datasetId}/showcase-apps`: every foreign key supplied
    in the body resolves to an existing row — otherwise the corresponding 404 from
    the same family as priority 3 (`ERR_DEPARTMENT_NOT_FOUND`,
    `ERR_DATASET_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_RUNNER_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_VERSION_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND` or
    `ERR_PIPELINE_NOT_FOUND`)." No dataset has ever been created here, so the
    fulfilment names a dataset that cannot resolve and is refused with
    `ERR_DATASET_NOT_FOUND` at 404.

    Because the link is written only by a successful fulfilment — "The request moves
    `ACCEPTED → FULFILLED`, its `linked_dataset_id` is set to that dataset, and the
    linked dataset's community-pressure input and `priority_score` are recomputed
    under whichever variant its current `priority_score_variant` names." — the
    refused call leaves the request in `ACCEPTED` with `linked_dataset_id` still null,
    and it leaves the vote arithmetic exactly where the two votes left it. Each voter
    is fresh, and "A new member begins with `accepted_issue_count`,
    `rejected_issue_count`, `approved_showcase_count` and `decay_epochs` all zero,
    `reputation_score` 50.00, `vote_weight` 2, `status` `ACTIVE`, and
    `last_credited_at` initialised to the member's own `created_at`." so each vote
    snapshots a weight of 2; then "`weighted_vote_total` is then the plain sum of
    every stored `weight` across the whole array with no time window, and
    `demand_signal` is that total multiplied by 5, capped at 100, and rounded half up
    to two decimal places." gives 4 and 20.00.

    Design: Corner/endpoints/fulfill_with_unknown_dataset_returns_not_found
    """
    fixtures.reset_clock_to_start(api=api)

    first_member = fixtures.register_member(api=api)
    second_member = fixtures.register_member(
        api=api, email="ben@civic.example", display_name="Ben Mapper"
    )
    assert first_member["vote_weight"] == 2, (
        f"Expected a new member to carry vote_weight 2, got {first_member['vote_weight']}"
    )
    assert second_member["vote_weight"] == 2, (
        f"Expected a new member to carry vote_weight 2, got {second_member['vote_weight']}"
    )

    request = fixtures.open_dataset_request(first_member["id"], api=api)
    fixtures.cast_vote(request["id"], first_member["id"], api=api)
    voted = fixtures.cast_vote(request["id"], second_member["id"], api=api)
    assert voted["weighted_vote_total"] == 4, (
        f"Expected weighted_vote_total 4 after two weight-2 votes, "
        f"got {voted['weighted_vote_total']}"
    )

    fixtures.review_request(request["id"], api=api)
    accepted = fixtures.decide_request(request["id"], "ACCEPT", api=api)
    assert accepted["status"] == "ACCEPTED", (
        f"Expected the request to be ACCEPTED before fulfilment, got {accepted['status']}"
    )

    validate_error(
        api.fulfill_dataset_request(
            request["id"], factories.fulfill_payload(NON_EXISTENT_UUID), PORTAL_ADMIN_HEADERS
        ),
        ERR_DATASET_NOT_FOUND,
    )

    unchanged = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "ACCEPTED", (
        f"A refused fulfilment must leave the request ACCEPTED, got {unchanged['status']}"
    )
    assert unchanged["linked_dataset_id"] is None, (
        f"A refused fulfilment must leave linked_dataset_id null, "
        f"got {unchanged['linked_dataset_id']!r}"
    )
    assert unchanged["weighted_vote_total"] == 4, (
        f"Expected weighted_vote_total 4, got {unchanged['weighted_vote_total']}"
    )
    assert_money(unchanged["demand_signal"], 20.00, "demand_signal")


def test_dataset_analytics_read_reports_both_priority_variants_side_by_side(api):
    """The analytics projection shows the declared and observed scores for one row.

    The PRD names the whole projection: "A per-dataset analytics capability exposes
    all of that in one computed read, answering with the `dataset_id`,
    `engagement_index`, `observed_demand_score`, `priority_score`,
    `priority_score_variant`, `priority_tier`, both variants side by side as
    `priority_score_as_declared` and `priority_score_as_observed`, a
    `usage_epoch_count`, the `approved_showcase_count` of approved showcase entries
    on the dataset, an `open_issue_count`, and the currency picture as
    `currency_status`, `days_overdue` and `next_due_at`."

    One epoch of 2000 API calls and 500 downloads is worth 1400, since "Each selected
    epoch is valued at 0.60 times its `api_call_count` plus 0.40 times its
    `download_count`. Those values are then combined positionally, with the
    highest-indexed epoch weighted 0.50, the next 0.30 and the next 0.20." and "a
    dataset with a single epoch keeps only the 0.50 weight and the remaining 0.50 is
    simply lost." leaves 700, which "The weighted total is divided by 50, rounded half
    up to two decimal places once, and capped at 100.00, giving `engagement_index`;
    `observed_demand_score` is set to the same value." turns into 14.00.

    The two variants then diverge on the demand term alone, because "The score has
    three weighted terms. The first is a demand term weighted at 0.45. The second is
    `policy_value_score` weighted at 0.35." and no community request is linked: the
    declared figure is 0.45 times 92 plus 0.35 times 96, or 75.00, and the observed
    figure is 0.45 times 14.00 plus 0.35 times 96, or 39.90. The dataset is published,
    so "Once the dataset's `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`, the demand term becomes the measured `observed_demand_score`
    and the variant is `AS_OBSERVED`." makes the headline score the observed one, and
    "From that score, `priority_tier` follows on inclusive thresholds: `TIER_1` at
    75.00 or above, `TIER_2` at 50.00 or above, and `TIER_3` otherwise." reads 39.90
    as `TIER_3`. Published weekly on 2026-08-01, its currency picture follows from
    "First, `next_due_at` is the dataset's `last_published_at` plus the number of days
    its `update_frequency` implies — 1 day for `DAILY`, 7 for `WEEKLY`, 30 for
    `MONTHLY`, 91 for `QUARTERLY`, 365 for `ANNUAL` — and is null both when
    `update_frequency` is `IRREGULAR` and when the dataset has never been published."

    Design: Corner/endpoints/dataset_analytics_read_exposes_both_priority_variants
    """
    ctx = fixtures.setup_published_dataset(api=api)
    fixtures.report_usage_epoch(ctx["dataset_id"], 1, 2000, 500, api=api)

    analytics = validate_success(
        api.get_dataset_analytics(ctx["dataset_id"], ANONYMOUS_HEADERS)
    )

    assert analytics["dataset_id"] == ctx["dataset_id"], (
        f"Expected dataset_id {ctx['dataset_id']}, got {analytics['dataset_id']}"
    )
    assert_money(analytics["engagement_index"], 14.00, "engagement_index")
    assert_money(analytics["observed_demand_score"], 14.00, "observed_demand_score")
    assert_money(
        analytics["priority_score_as_declared"], 75.00, "priority_score_as_declared"
    )
    assert_money(
        analytics["priority_score_as_observed"], 39.90, "priority_score_as_observed"
    )
    assert_priority(
        analytics,
        priority_score=39.90,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert analytics["usage_epoch_count"] == 1, (
        f"Expected usage_epoch_count 1, got {analytics['usage_epoch_count']}"
    )
    assert analytics["approved_showcase_count"] == 0, (
        f"Expected approved_showcase_count 0, got {analytics['approved_showcase_count']}"
    )
    assert analytics["open_issue_count"] == 0, (
        f"Expected open_issue_count 0, got {analytics['open_issue_count']}"
    )
    assert analytics["currency_status"] == "CURRENT", (
        f"Expected currency_status CURRENT, got {analytics['currency_status']}"
    )
    assert analytics["days_overdue"] == 0, (
        f"Expected days_overdue 0, got {analytics['days_overdue']}"
    )
    assert str(analytics["next_due_at"]).startswith("2026-08-08T00:00:00"), (
        f"Expected next_due_at 2026-08-08T00:00:00Z, got {analytics['next_due_at']!r}"
    )


def test_high_value_commitment_is_accepted_for_a_tier_one_dataset_still_in_ready(api):
    """A `TIER_1` dataset sitting in `READY` may be committed to the strictest service level.

    The PRD: "The programme office commits a dataset to the high-value currency
    service level, which requires the dataset's `priority_tier` to be `TIER_1` and its
    `publication_status` to be `READY` or `PUBLISHED`; anything else is refused with
    `ERR_NOT_HIGH_VALUE_ELIGIBLE`. The commitment sets `high_value_committed` to true,
    which both enables the `BREACHED` state for that dataset and exposes its
    department to the heaviest risk weight in §2.9."

    This dataset has not been published yet, so "While the dataset's
    `publication_status` is `INVENTORIED`, `SCREENING` or `READY` — before its catalog
    page has any traffic worth trusting — the demand term is the coordinator's
    declared `public_demand_score` and the variant is `AS_DECLARED`." keeps its score
    at 0.45 times 92 plus 0.35 times 96, or 75.00, and "From that score,
    `priority_tier` follows on inclusive thresholds: `TIER_1` at 75.00 or above,
    `TIER_2` at 50.00 or above, and `TIER_3` otherwise." puts it exactly on the
    `TIER_1` boundary. Declaring readiness did not disturb that, since "The transition
    increments the dataset's `version` and changes nothing else." — so the eligibility
    gate sees `TIER_1` and `READY` and the commitment lands.

    Design: Corner/endpoints/high_value_commitment_accepted_for_tier1_ready_dataset
    """
    ctx = fixtures.setup_ready_dataset(api=api)
    ready = ctx["dataset"]
    assert_dataset_states(ready, publication_status="READY", currency_status="CURRENT")
    assert_priority(
        ready, priority_score=75.00, priority_score_variant="AS_DECLARED", priority_tier="TIER_1"
    )
    assert ready["high_value_committed"] is False, (
        f"Expected high_value_committed false before the commitment, "
        f"got {ready['high_value_committed']!r}"
    )

    committed = validate_success(api.commit_high_value(ctx["dataset_id"], PORTAL_ADMIN_HEADERS))

    assert committed["high_value_committed"] is True, (
        f"The commitment must set high_value_committed true, "
        f"got {committed['high_value_committed']!r}"
    )
    assert_dataset_states(committed, publication_status="READY")
    assert_priority(
        committed,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )

    reread = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert reread["high_value_committed"] is True, (
        f"Expected the persisted high_value_committed to be true, "
        f"got {reread['high_value_committed']!r}"
    )
