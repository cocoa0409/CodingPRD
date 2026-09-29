"""
The validation gates that guard the publication path and the community inputs that
feed it: the demand floor on review, member throttling, high-value eligibility,
the open-issue bar on retirement, metadata acceptance conditions, the aggregation
gate that only binds when the assessment asks for it, and the two run-scheduling
checks with the priority order that decides between them.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    assert_assessment_derived,
    assert_component_contributions,
    assert_credit_buckets,
    assert_credit_conservation,
    assert_dataset_states,
    assert_money,
    assert_priority,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

LOW_INTEREST_DATASET = {
    "title": "Surplus Furniture Disposals",
    "slug": "surplus-furniture-disposals",
    "description": "Surplus Furniture Disposals published by the department",
    "public_demand_score": 20,
    "policy_value_score": 20,
}

TRANSIT_DATASET = {
    "title": "Transit Stop Boardings",
    "slug": "transit-stop-boardings",
    "description": "Transit Stop Boardings published by the department",
}


def test_taking_a_request_under_review_below_the_weighted_demand_floor_is_refused(api):
    """A single vote of weight 2 leaves the request four short of the review floor.

    The PRD sets the bar on the weighted total, not the head count: "The programme
    office takes a sufficiently supported request under review, moving it `OPEN →
    UNDER_REVIEW`, which requires `weighted_vote_total` to have reached at least 4 —
    anything below that is refused with `ERR_INSUFFICIENT_DEMAND` — and which stores
    the optional `decision_note` supplied with it."

    A member registered at the starting instant has never had an issue accepted or
    rejected, so their reputation is the base 50.00 and "`vote_weight` follows on
    inclusive thresholds: 3 when `reputation_score` is at least 70.00, 2 when it is at
    least 40.00 but below 70.00, and 1 below 40.00." — weight 2. One vote therefore
    gives "`weighted_vote_total` is then the plain sum of every stored `weight` across
    the whole array with no time window, and `demand_signal` is that total multiplied
    by 5, capped at 100, and rounded half up to two decimal places." — a total of 2
    against a floor of 4, so the answer is `ERR_INSUFFICIENT_DEMAND`, and the refusal
    stores nothing: the request stays `OPEN` with its vote, its total of 2, its
    `demand_signal` of 10.00 and a null `decision_note`.

    Design: Corner/validations/request_review_below_demand_floor_returns_4XX
    """
    fixtures.reset_clock_to_start(api=api)
    member = fixtures.setup_member(api=api)
    request = fixtures.open_dataset_request(member["member_id"], api=api)
    voted = fixtures.cast_vote(request["id"], member["member_id"], api=api)
    assert voted["weighted_vote_total"] == 2, (
        f"Expected weighted_vote_total 2 from one weight-2 vote, "
        f"got {voted['weighted_vote_total']}"
    )

    validate_error(
        api.review_dataset_request(
            request["id"], PORTAL_ADMIN_HEADERS, {"decision_note": "Worth a look."}
        ),
        "ERR_INSUFFICIENT_DEMAND",
        422,
    )

    unchanged = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "OPEN", (
        f"A refused review must leave the request OPEN, got {unchanged['status']}"
    )
    assert unchanged["weighted_vote_total"] == 2, (
        f"Expected weighted_vote_total to stay 2, got {unchanged['weighted_vote_total']}"
    )
    assert_money(unchanged["demand_signal"], 10.00, "demand_signal")
    assert unchanged["decision_note"] is None, (
        f"A refused review must store no decision_note, got {unchanged['decision_note']!r}"
    )
    assert len(unchanged["votes"]) == 1, (
        f"Expected the one stored vote to survive, got {len(unchanged['votes'])} votes"
    )
    assert unchanged["votes"][0]["weight"] == 2, (
        f"Expected the stored vote weight to stay 2, got {unchanged['votes'][0]['weight']}"
    )


def test_a_throttled_reporter_cannot_file_a_fourth_quality_issue(api):
    """Three rejections with nothing accepted throttle the member and close filing.

    Standing is tracked separately from the score: "Independently of the score, a
    member's `status` becomes `THROTTLED` as soon as `rejected_issue_count` minus
    `accepted_issue_count` reaches 3, and is `ACTIVE` otherwise." The score itself
    follows the same counters — "The raw figure starts from a base of 50, adds 6 points
    for each accepted issue in `accepted_issue_count`, subtracts 4 points for each
    rejected issue in `rejected_issue_count`, and adds 2 points for each approved
    showcase in `approved_showcase_count`." — so three rejections and no acceptances
    leave 50 − 12 = 38.00, which under "`vote_weight` follows on inclusive thresholds:
    3 when `reputation_score` is at least 70.00, 2 when it is at least 40.00 but below
    70.00, and 1 below 40.00." drops the weight to 1.

    The fourth filing is then closed by priority 29, "Member standing, on `POST
    /open-data/quality-issues` and `POST /open-data/dataset-requests/{requestId}/votes`:
    a `THROTTLED` member may neither file issues nor vote — `ERR_MEMBER_THROTTLED`
    (422).", and the refusal is total: only the three earlier issues exist.

    Design: Corner/validations/throttled_member_cannot_file_further_quality_issues
    """
    ctx = fixtures.setup_published_dataset(api=api, dataset_overrides=TRANSIT_DATASET)
    member = fixtures.setup_member(api=api)

    for attempt in range(3):
        issue = fixtures.file_quality_issue(
            ctx["dataset_id"],
            member["member_id"],
            severity="MEDIUM",
            category="ACCURACY",
            api=api,
            description=f"Column totals disagree with the published summary, case {attempt}.",
        )
        fixtures.triage_quality_issue(issue["id"], ctx["department_id"], api=api)
        fixtures.reject_quality_issue(issue["id"], ctx["department_id"], api=api)

    throttled = fixtures.read_member(member["member_id"], api=api)
    assert throttled["rejected_issue_count"] == 3, (
        f"Expected rejected_issue_count 3, got {throttled['rejected_issue_count']}"
    )
    assert throttled["accepted_issue_count"] == 0, (
        f"Expected accepted_issue_count 0, got {throttled['accepted_issue_count']}"
    )
    assert_money(throttled["reputation_score"], 38.00, "reputation_score")
    assert throttled["vote_weight"] == 1, (
        f"Expected vote_weight 1 below the 40.00 threshold, got {throttled['vote_weight']}"
    )
    assert throttled["status"] == "THROTTLED", (
        f"Expected status THROTTLED at three net rejections, got {throttled['status']}"
    )

    validate_error(
        api.create_quality_issue(
            factories.quality_issue_payload(
                ctx["dataset_id"],
                member["member_id"],
                severity="MEDIUM",
                category="ACCURACY",
                description="A fourth report from the same throttled reporter.",
            ),
            member["member_headers"],
        ),
        "ERR_MEMBER_THROTTLED",
        422,
    )

    issues, meta = validate_paginated(api.list_quality_issues(PORTAL_ADMIN_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 3, (
        f"The refused filing must persist nothing, expected total_count 3, "
        f"got {meta['total_count']}"
    )
    assert len(issues) == 3, f"Expected 3 stored issues, got {len(issues)}"
    still_throttled = fixtures.read_member(member["member_id"], api=api)
    assert still_throttled["rejected_issue_count"] == 3, (
        f"A refused filing must not move the counters, expected 3, "
        f"got {still_throttled['rejected_issue_count']}"
    )
    assert_money(still_throttled["reputation_score"], 38.00, "reputation_score")


def test_high_value_commitment_refused_on_a_tier_3_dataset(api):
    """A dataset scoring 16.00 sits in `TIER_3` and cannot take the service level.

    The commitment is gated on the tier: "The programme office commits a dataset to the
    high-value currency service level, which requires the dataset's `priority_tier` to
    be `TIER_1` and its `publication_status` to be `READY` or `PUBLISHED`; anything else
    is refused with `ERR_NOT_HIGH_VALUE_ELIGIBLE`."

    Declared scores of 20 and 20 with no community pressure yet weigh out as
    0.45 × 20 + 0.35 × 20 + 0.20 × 0 = 16.00, and "From that score, `priority_tier`
    follows on inclusive thresholds: `TIER_1` at 75.00 or above, `TIER_2` at 50.00 or
    above, and `TIER_3` otherwise." puts the dataset in `TIER_3`. The state limb of the
    guard is satisfied — the dataset is `READY` — so the refusal is precisely
    `ERR_NOT_HIGH_VALUE_ELIGIBLE`, and it commits nothing.

    Design: Corner/validations/high_value_commitment_on_tier3_dataset_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, dataset_overrides=LOW_INTEREST_DATASET)
    before = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_priority(
        before, priority_score=16.00, priority_score_variant="AS_DECLARED", priority_tier="TIER_3"
    )
    assert before["high_value_committed"] is False, (
        f"Expected high_value_committed false before the attempt, "
        f"got {before['high_value_committed']!r}"
    )

    validate_error(
        api.commit_high_value(ctx["dataset_id"], PORTAL_ADMIN_HEADERS),
        "ERR_NOT_HIGH_VALUE_ELIGIBLE",
        422,
    )

    after = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert after["high_value_committed"] is False, (
        f"A refused commitment must leave high_value_committed false, "
        f"got {after['high_value_committed']!r}"
    )
    assert_dataset_states(after, publication_status="READY")
    assert_priority(after, priority_score=16.00, priority_tier="TIER_3")
    assert after["version"] == before["version"], (
        f"A refused commitment must not increment the dataset version, "
        f"expected {before['version']}, got {after['version']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(department)


def test_retiring_a_published_dataset_with_an_open_quality_issue_is_refused(api):
    """One `SUBMITTED` report is enough to hold the dataset in the catalogue.

    The PRD: "From either state, retirement takes an optional `reason`, is refused with
    `ERR_OPEN_ISSUES_BLOCK_RETIRE` when any quality issue on the dataset still sits in
    `SUBMITTED`, `TRIAGED` or `ACCEPTED`, sets `public_access_suspended` to true, and
    increments the dataset's `version`."

    A freshly filed report has not yet been triaged, so it is still `SUBMITTED` and the
    bar applies at the earliest of the three listed states. The refusal must be
    `ERR_OPEN_ISSUES_BLOCK_RETIRE` and must be total: the dataset stays `PUBLISHED` with
    public access open and its version untouched, and the issue is untouched too.

    Design: Corner/validations/retire_with_open_quality_issue_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api, dataset_overrides=TRANSIT_DATASET)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_quality_issue(
        ctx["dataset_id"],
        member["member_id"],
        severity="LOW",
        category="COMPLETENESS",
        api=api,
        description="Three optional columns are blank for the earliest reporting month.",
    )
    assert issue["status"] == "SUBMITTED", (
        f"Expected a freshly filed issue to be SUBMITTED, got {issue['status']}"
    )
    before = fixtures.read_dataset(ctx["dataset_id"], api=api)

    validate_error(
        api.retire_dataset(
            ctx["dataset_id"], ctx["coordinator_headers"], {"reason": "Superseded by a wider feed."}
        ),
        "ERR_OPEN_ISSUES_BLOCK_RETIRE",
        409,
    )

    after = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(after, publication_status="PUBLISHED")
    assert after["public_access_suspended"] is False, (
        f"A refused retirement must leave public_access_suspended false, "
        f"got {after['public_access_suspended']!r}"
    )
    assert after["version"] == before["version"], (
        f"A refused retirement must not increment the dataset version, "
        f"expected {before['version']}, got {after['version']}"
    )
    still_open = validate_success(api.get_quality_issue(issue["id"], PORTAL_ADMIN_HEADERS))
    assert still_open["status"] == "SUBMITTED", (
        f"Expected the blocking issue to stay SUBMITTED, got {still_open['status']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(department)


def test_metadata_acceptance_refused_when_the_attribution_count_is_zero(api):
    """A record that clears the completeness floor still fails the attribution limb.

    Acceptance carries three conditions: "An `ACCEPT` decision moves the record
    `SUBMITTED → ACCEPTED` and is guarded by three conditions: the backing licence's
    `retired` flag must be false, or the record is refused with `ERR_LICENSE_RETIRED`;
    when that licence has `attribution_required` true, `attribution_element_count` must
    be at least 1, or the record is refused with `ERR_ATTRIBUTION_MISSING`; and
    `completeness_score` must be at least 85.00 under the pinned rounding order above,
    or the record is refused with `ERR_METADATA_INCOMPLETE`."

    The record here satisfies every component except attribution — the dictionary covers
    all 9 columns, provenance reaches 24 lines, the contact address is well formed, the
    declared cadence matches the dataset's and the licence is live — so the five
    non-attribution components contribute 30.00, 20.00, 15.00, 15.00 and 10.00 while
    attribution contributes 0.00, and "Their sum is then rounded half up to two decimal
    places again and stored as `completeness_score`." gives 90.00. That clears the 85.00
    floor, so `ERR_METADATA_INCOMPLETE` does not apply and the refusal must be
    `ERR_ATTRIBUTION_MISSING`, leaving the record `SUBMITTED`.

    Design: Corner/validations/metadata_accept_without_attribution_elements_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api, dataset_overrides=TRANSIT_DATASET)
    assert ctx["license"]["attribution_required"] is True, (
        f"The backing licence must require attribution, "
        f"got {ctx['license']['attribution_required']!r}"
    )
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"],
        ctx["license_id"],
        ctx["department_id"],
        api=api,
        attribution_element_count=0,
    )
    submitted = fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    assert_money(submitted["completeness_score"], 90.00, "completeness_score")

    validate_error(
        api.decide_metadata_record(
            record["id"], factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        ),
        "ERR_ATTRIBUTION_MISSING",
        422,
    )

    unchanged = validate_success(api.get_metadata_record(record["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "SUBMITTED", (
        f"A refused acceptance must leave the record SUBMITTED, got {unchanged['status']}"
    )
    assert_money(unchanged["completeness_score"], 90.00, "completeness_score")
    assert_component_contributions(unchanged, [30.00, 20.00, 15.00, 15.00, 10.00, 0.00])
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="SCREENING")


def test_marking_ready_needs_no_aggregation_when_the_assessment_does_not_require_it(api):
    """A low-risk clearance leaves the geography comparison out of the readiness gate.

    The geography gate is conditional: "If that cleared assessment has
    `aggregation_required` true, the geography sufficiency comparison of §3.3 must also
    pass." And the flag itself follows the risk score — "`aggregation_required` is true
    when the score is at least 35.00." — while "And `min_aggregation_geography` names
    the coarsest geography the extract must be rolled up to before publication:
    `COUNTY` when the score is at least 60.00, `TRACT` when the score is at least 35.00
    but below 60.00, and `BLOCK` otherwise." still names a geography at every score.

    Two declared quasi-identifiers give 16 points at 8 points each, a verified smallest
    cell of 20 draws the 0.5 cell-size factor, a population of 100000 leaves the
    clearance population factor at 1.00 and a `PUBLIC` sensitivity multiplies by 0.8:
    16 × 0.5 × 1.00 × 0.8 = 6.40. That is
    below 35.00, so `aggregation_required` is false, the dataset never sets an
    `aggregation_geography`, and marking it ready must still succeed rather than raise
    `ERR_AGGREGATION_UNMET`.

    Design: Corner/validations/mark_ready_skips_aggregation_gate_when_not_required
    """
    ctx = fixtures.setup_screening_dataset(api=api, dataset_overrides=TRANSIT_DATASET)
    fixtures.land_accepted_metadata(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    assessment = fixtures.land_cleared_assessment(ctx["dataset_id"], api=api)
    assert assessment["status"] == "CLEARED", (
        f"Expected a CLEARED assessment, got {assessment['status']}"
    )
    assert_assessment_derived(
        assessment,
        risk_score=6.40,
        k_anonymity_k=20,
        aggregation_required=False,
        min_aggregation_geography="BLOCK",
    )

    ready = validate_success(
        api.mark_dataset_ready(ctx["dataset_id"], ctx["coordinator_headers"])
    )
    assert_dataset_states(ready, publication_status="READY")
    assert_priority(
        ready, priority_score=75.00, priority_score_variant="AS_DECLARED", priority_tier="TIER_1"
    )


def test_a_past_schedule_outranks_the_window_violation_on_the_same_request(api):
    """One request breaks both scheduling rules and must answer with the earlier one.

    Scheduling is guarded twice over: "That instant must not be in the past — the
    logical clock must not yet have passed it, or the request is refused with
    `ERR_RUN_SCHEDULE_INVALID` — and its minute-of-day must fall inside the pipeline's
    half-open window, at or after `window_start_minute` and strictly before
    `window_end_minute`, or the request is refused with `ERR_RUN_OUTSIDE_WINDOW`."

    The order is fixed: "All validations are evaluated in the ascending priority order
    below, and the **first** failing check decides the response; later checks are not
    consulted." Schedule sanity sits at priority 20 — "Run schedule sanity, on `POST
    /open-data/pipeline-runs`, `POST /open-data/pipeline-runs/{runId}/requeue` and `POST
    /open-data/pipeline-runs/{runId}/start`: `ERR_RUN_SCHEDULE_INVALID` (422)." — ahead
    of the window check at priority 21, "Run inside the window, on `POST
    /open-data/pipeline-runs` and `POST /open-data/pipeline-runs/{runId}/requeue`:
    `ERR_RUN_OUTSIDE_WINDOW` (422)."

    With the clock at 09:00Z, a request for 08:00Z is both in the past and at
    minute-of-day 480, well outside the 540-to-660 window. Both guards fire, so the
    lower-numbered `ERR_RUN_SCHEDULE_INVALID` must decide the response and
    `ERR_RUN_OUTSIDE_WINDOW` must not be reached. No run is stored either way.

    Design: Corner/validations/run_scheduled_in_the_past_outranks_window_violation
    """
    ctx = fixtures.setup_armed_pipeline(api=api, dataset_overrides=TRANSIT_DATASET)
    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["window_start_minute"] == 540, (
        f"Expected window_start_minute 540, got {pipeline['window_start_minute']}"
    )
    assert pipeline["window_end_minute"] == 660, (
        f"Expected window_end_minute 660, got {pipeline['window_end_minute']}"
    )
    fixtures.set_clock("2026-08-01T09:00:00Z", api=api)

    validate_error(
        api.create_pipeline_run(
            factories.pipeline_run_payload(ctx["pipeline_id"], "2026-08-01T08:00:00Z"),
            PORTAL_ADMIN_HEADERS,
        ),
        "ERR_RUN_SCHEDULE_INVALID",
        422,
    )

    runs, meta = validate_paginated(api.list_pipeline_runs(PORTAL_ADMIN_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 0, (
        f"A refused scheduling must store no run, expected total_count 0, "
        f"got {meta['total_count']}"
    )
    assert runs == [], f"Expected no run rows, got {runs}"
    after = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert after["status"] == "ARMED", (
        f"A refused scheduling must leave the pipeline ARMED, got {after['status']}"
    )
    assert after["consecutive_failure_count"] == 0, (
        f"Expected consecutive_failure_count 0, got {after['consecutive_failure_count']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=90.00, escrowed=10.00, consumed=0.00)
    assert_credit_conservation(department)


def test_scheduling_at_the_window_end_minute_is_outside_but_the_minute_before_is_inside(api):
    """The window excludes its own closing minute and admits the one before it.

    The PRD makes the window half-open on both limbs of the same sentence: "That instant
    must not be in the past — the logical clock must not yet have passed it, or the
    request is refused with `ERR_RUN_SCHEDULE_INVALID` — and its minute-of-day must fall
    inside the pipeline's half-open window, at or after `window_start_minute` and
    strictly before `window_end_minute`, or the request is refused with
    `ERR_RUN_OUTSIDE_WINDOW`."

    With the window at 540 to 660, a future instant of 11:00Z is minute-of-day 660 —
    exactly the excluded upper endpoint — so the schedule-sanity check at priority 20
    passes and the refusal must be `ERR_RUN_OUTSIDE_WINDOW`. The very same request one
    minute earlier, 10:59Z at minute 659, is strictly below the endpoint and must be
    accepted, creating a run for which "A new run has `status` `SCHEDULED`,
    `alert_dispatched` false, `rows_ingested` 0, `started_at` and `finished_at` and
    `failure_code` and `skip_reason` all null, and `consecutive_failure_index`
    initialised from the pipeline's current `consecutive_failure_count`."

    Design: Corner/validations/run_scheduled_at_window_end_minute_returns_4XX
    """
    ctx = fixtures.setup_armed_pipeline(api=api, dataset_overrides=TRANSIT_DATASET)
    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["window_end_minute"] == 660, (
        f"Expected window_end_minute 660, got {pipeline['window_end_minute']}"
    )

    validate_error(
        api.create_pipeline_run(
            factories.pipeline_run_payload(ctx["pipeline_id"], "2026-08-01T11:00:00Z"),
            PORTAL_ADMIN_HEADERS,
        ),
        "ERR_RUN_OUTSIDE_WINDOW",
        422,
    )

    refused_runs, refused_meta = validate_paginated(
        api.list_pipeline_runs(PORTAL_ADMIN_HEADERS, {"limit": 100})
    )
    assert refused_meta["total_count"] == 0, (
        f"The excluded endpoint must store no run, expected total_count 0, "
        f"got {refused_meta['total_count']}"
    )
    assert refused_runs == [], f"Expected no run rows after the refusal, got {refused_runs}"
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=90.00, escrowed=10.00, consumed=0.00)

    accepted = validate_success(
        api.create_pipeline_run(
            factories.pipeline_run_payload(ctx["pipeline_id"], "2026-08-01T10:59:00Z"),
            PORTAL_ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED", (
        f"Expected the last in-window minute to be accepted as SCHEDULED, "
        f"got {accepted['status']}"
    )
    assert accepted["alert_dispatched"] is False, (
        f"Expected alert_dispatched false on a new run, got {accepted['alert_dispatched']!r}"
    )
    assert accepted["rows_ingested"] == 0, (
        f"Expected rows_ingested 0 on a new run, got {accepted['rows_ingested']}"
    )
    assert accepted["started_at"] is None, (
        f"Expected started_at null on a new run, got {accepted['started_at']!r}"
    )
    assert accepted["consecutive_failure_index"] == 0, (
        f"Expected consecutive_failure_index 0 from a pipeline with no failures, "
        f"got {accepted['consecutive_failure_index']}"
    )
