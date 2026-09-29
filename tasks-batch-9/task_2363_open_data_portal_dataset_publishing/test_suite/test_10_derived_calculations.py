"""
Derived calculations read end to end: the licence permission ladder, the community
demand signal, the three-epoch engagement window, reputation decay, the departmental
risk-point arithmetic, the two issue service-level clocks, and the variant that
decides which demand figure the priority score is built from.
"""

from datetime import datetime, timezone

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    assert_dataset_states,
    assert_money,
    assert_posture,
    assert_priority,
    factories,
    fixtures,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp, tolerating the `Z` suffix and fractional digits."""
    assert value is not None, "Expected an ISO 8601 UTC timestamp, got None"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _utc(year, month, day, hour=0, minute=0):
    """A UTC instant, for comparison against a parsed timestamp."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ─── The licence permission ladder ────────────────────────────────────


def test_share_alike_licence_classifies_as_copyleft_not_noncommercial(api):
    """A share-alike licence reaches the `COPYLEFT` clause before the fallback.

    The PRD: "if attribution is not required, commercial use is allowed and share-alike
    is not required, the class is `UNRESTRICTED`; otherwise, if attribution is required,
    commercial use is allowed and share-alike is not required, the class is
    `ATTRIBUTION`; otherwise, if share-alike is required, the class is `COPYLEFT` — and
    this clause wins even when commercial use is forbidden; otherwise the class is
    `NONCOMMERCIAL`."

    The clause order is itself the contract and the first match decides, so for
    `attribution_required` true, `commercial_use_allowed` false and `share_alike` true
    the arithmetic of the ladder is: clause one fails because attribution is required,
    clause two fails because commercial use is forbidden, clause three matches because
    share-alike is required — giving `COPYLEFT`. The `NONCOMMERCIAL` fallback is never
    reached even though commercial use is forbidden.

    Design: Corner/calculations/license_copyleft_clause_wins_over_noncommercial
    """
    payload = factories.license_payload(
        code="CC-BY-NC-SA-4.0",
        name="Attribution NonCommercial ShareAlike 4.0",
        attribution_required=True,
        commercial_use_allowed=False,
        share_alike=True,
    )

    license_term = validate_success(api.create_license(payload, PORTAL_ADMIN_HEADERS), 201)

    assert license_term["reuse_permission_class"] == "COPYLEFT", (
        "Expected reuse_permission_class COPYLEFT for a share-alike licence, got "
        f"{license_term.get('reuse_permission_class')}"
    )
    assert license_term["reuse_permission_class"] != "NONCOMMERCIAL", (
        "The COPYLEFT clause precedes the NONCOMMERCIAL fallback, so NONCOMMERCIAL is "
        f"wrong here, got {license_term.get('reuse_permission_class')}"
    )
    assert license_term["attribution_required"] is True, (
        f"Expected attribution_required True, got {license_term.get('attribution_required')!r}"
    )
    assert license_term["commercial_use_allowed"] is False, (
        f"Expected commercial_use_allowed False, got {license_term.get('commercial_use_allowed')!r}"
    )
    assert license_term["share_alike"] is True, (
        f"Expected share_alike True, got {license_term.get('share_alike')!r}"
    )
    assert license_term["retired"] is False, (
        f"Expected a new licence to have retired False, got {license_term.get('retired')!r}"
    )


def test_licence_with_no_matching_clause_falls_through_to_noncommercial(api):
    """Three false flags match no clause of the ladder, so the fallback applies.

    The PRD: "if attribution is not required, commercial use is allowed and share-alike
    is not required, the class is `UNRESTRICTED`; otherwise, if attribution is required,
    commercial use is allowed and share-alike is not required, the class is
    `ATTRIBUTION`; otherwise, if share-alike is required, the class is `COPYLEFT` — and
    this clause wins even when commercial use is forbidden; otherwise the class is
    `NONCOMMERCIAL`."

    With `attribution_required` false, `commercial_use_allowed` false and `share_alike`
    false the ladder runs out: clause one fails because commercial use is not allowed,
    clause two fails because attribution is not required, clause three fails because
    share-alike is not required, so the else branch decides and the class is
    `NONCOMMERCIAL` — not the `UNRESTRICTED` that two false flags might suggest.
    Because `attribution_required` is false the `attribution_text_template` may be null.

    Design: Corner/calculations/license_noncommercial_fallback_when_no_clause_matches
    """
    payload = factories.license_payload(
        code="CITY-INTERNAL-1.0",
        name="City Internal Reuse Only",
        attribution_required=False,
        commercial_use_allowed=False,
        share_alike=False,
        attribution_text_template=None,
    )

    license_term = validate_success(api.create_license(payload, PORTAL_ADMIN_HEADERS), 201)

    assert license_term["reuse_permission_class"] == "NONCOMMERCIAL", (
        "Expected reuse_permission_class NONCOMMERCIAL when no clause matches, got "
        f"{license_term.get('reuse_permission_class')}"
    )
    assert license_term["reuse_permission_class"] != "UNRESTRICTED", (
        "UNRESTRICTED requires commercial_use_allowed True, so it is wrong here, got "
        f"{license_term.get('reuse_permission_class')}"
    )
    assert license_term["commercial_use_allowed"] is False, (
        f"Expected commercial_use_allowed False, got {license_term.get('commercial_use_allowed')!r}"
    )


# ─── Community demand ─────────────────────────────────────────────────


def test_demand_signal_sums_the_weights_snapshotted_at_each_vote(api):
    """Two weight-2 voters take `weighted_vote_total` to 4 and `demand_signal` to 20.00.

    The PRD: "A new member begins with `accepted_issue_count`, `rejected_issue_count`,
    `approved_showcase_count` and `decay_epochs` all zero, `reputation_score` 50.00,
    `vote_weight` 2, `status` `ACTIVE`, and `last_credited_at` initialised to the
    member's own `created_at`."
    The PRD: "The request starts at `status` `OPEN` with an empty `votes` array,
    `weighted_vote_total` 0, `demand_signal` 0.00, `linked_dataset_id` null and
    `decision_note` null."
    The PRD: "The vote is appended to `votes` as an entry holding the `member_id`, a
    `weight` snapshotting the member's `vote_weight` at the moment of casting, and a
    `cast_at` instant."
    The PRD: "`weighted_vote_total` is then the plain sum of every stored `weight`
    across the whole array with no time window, and `demand_signal` is that total
    multiplied by 5, capped at 100, and rounded half up to two decimal places."

    Both members are fresh, so each snapshots a `vote_weight` of 2. After the first
    vote the total is 2 and the signal is min(100, 5 x 2) = 10.00; after the second the
    total is 2 + 2 = 4 and the signal is min(100, 5 x 4) = 20.00. Voting is not a
    transition, so the request is still `OPEN`: only the review step moves it, and that
    needs a `weighted_vote_total` of at least 4.

    Design: Corner/calculations/request_demand_signal_sums_snapshotted_vote_weights
    """
    fixtures.reset_clock_to_start(api=api)
    first = fixtures.setup_member(api=api)
    second = fixtures.register_member(
        api=api, email="ben@civic.example", display_name="Ben Mapper"
    )

    for member, label in ((first["member"], "first"), (second, "second")):
        assert_money(member["reputation_score"], 50.00, f"{label} member reputation_score")
        assert member["vote_weight"] == 2, (
            f"Expected the {label} member's vote_weight to be 2, got {member.get('vote_weight')}"
        )

    request = fixtures.open_dataset_request(first["member_id"], api=api)
    assert request["weighted_vote_total"] == 0, (
        f"Expected weighted_vote_total 0 before any vote, got {request['weighted_vote_total']}"
    )
    assert_money(request["demand_signal"], 0.00, "demand_signal before any vote")

    fixtures.cast_vote(request["id"], first["member_id"], api=api)
    after_first = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert after_first["weighted_vote_total"] == 2, (
        f"Expected weighted_vote_total 2 after one weight-2 vote, got {after_first['weighted_vote_total']}"
    )
    assert_money(after_first["demand_signal"], 10.00, "demand_signal after one vote")

    fixtures.cast_vote(request["id"], second["id"], api=api)
    after_second = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert after_second["weighted_vote_total"] == 4, (
        f"Expected weighted_vote_total 4 after two weight-2 votes, got {after_second['weighted_vote_total']}"
    )
    assert_money(after_second["demand_signal"], 20.00, "demand_signal after two votes")

    votes = after_second["votes"]
    assert len(votes) == 2, f"Expected 2 stored votes, got {len(votes)}: {votes}"
    for index, vote in enumerate(votes):
        assert vote["weight"] == 2, (
            f"Expected votes[{index}] to have snapshotted weight 2, got {vote.get('weight')}"
        )
    assert after_second["status"] == "OPEN", (
        f"Expected the request to still be OPEN after voting, got {after_second['status']}"
    )


# ─── The engagement window ────────────────────────────────────────────


def test_engagement_index_keeps_only_the_three_highest_epoch_indexes(api):
    """A huge epoch 1 stops counting the moment epochs 2, 3 and 4 exist.

    The PRD: "Sort the dataset's `usage_epochs` by `epoch_index` descending and take the
    first three rows — because `epoch_index` is unique per dataset the ordering is total
    and no tie-break is needed, and were two rows ever to tie, the earlier `recorded_at`
    would come first."
    The PRD: "Each selected epoch is valued at 0.60 times its `api_call_count` plus 0.40
    times its `download_count`."
    The PRD: "Those values are then combined positionally, with the highest-indexed
    epoch weighted 0.50, the next 0.30 and the next 0.20."
    The PRD: "The weighted total is divided by 50, rounded half up to two decimal places
    once, and capped at 100.00, giving `engagement_index`; `observed_demand_score` is set
    to the same value."

    Epoch 1 alone is valued at 0.60 x 100000 + 0.40 x 50000 = 80000; weighted 0.50 that
    is 40000, and 40000 / 50 = 800.00, which the cap pulls down to 100.00. Once epochs 2
    (0.60 x 1000 + 0.40 x 200 = 680), 3 (0.60 x 2000 + 0.40 x 500 = 1400) and 4
    (0.60 x 3000 + 0.40 x 1000 = 2200) exist, the window keeps 4, 3 and 2, so the
    weighted total is 0.50 x 2200 + 0.30 x 1400 + 0.20 x 680 = 1100 + 420 + 136 = 1656
    and the index is 1656 / 50 = 33.12. The dataset is `PUBLISHED`, so the demand term
    is the observed figure: 0.45 x 33.12 + 0.35 x 96.00 + 0.20 x 0 = 14.904 + 33.600 =
    48.504, which rounds half up once to 48.50 and falls in `TIER_3`.

    Design: Corner/calculations/engagement_index_keeps_only_three_highest_epoch_indexes
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)

    fixtures.report_usage_epoch(ctx["dataset_id"], 1, 100000, 50000, api=api)
    after_epoch_one = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_money(after_epoch_one["engagement_index"], 100.00, "engagement_index at the cap")
    assert_money(after_epoch_one["observed_demand_score"], 100.00, "observed_demand_score at the cap")

    fixtures.report_usage_epoch(ctx["dataset_id"], 2, 1000, 200, api=api)
    fixtures.report_usage_epoch(ctx["dataset_id"], 3, 2000, 500, api=api)
    fixtures.report_usage_epoch(ctx["dataset_id"], 4, 3000, 1000, api=api)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_money(dataset["engagement_index"], 33.12, "engagement_index")
    assert_money(dataset["observed_demand_score"], 33.12, "observed_demand_score")
    assert len(dataset["usage_epochs"]) == 4, (
        f"Expected all 4 epochs to stay recorded, got {len(dataset['usage_epochs'])}"
    )
    assert_priority(
        dataset,
        priority_score=48.50,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )

    analytics = fixtures.read_analytics(ctx["dataset_id"], api=api)
    assert_money(analytics["engagement_index"], 33.12, "engagement_index on the analytics read")
    assert analytics["usage_epoch_count"] == 4, (
        f"Expected usage_epoch_count 4, got {analytics['usage_epoch_count']}"
    )


# ─── Reputation decay ─────────────────────────────────────────────────


def test_member_reputation_decays_its_distance_from_the_base_after_thirty_days(api):
    """Raw 56.00 becomes 54.80 exactly one thirty-day epoch after the credit.

    The PRD: "The raw figure starts from a base of 50, adds 6 points for each accepted
    issue in `accepted_issue_count`, subtracts 4 points for each rejected issue in
    `rejected_issue_count`, and adds 2 points for each approved showcase in
    `approved_showcase_count`."
    The PRD: "Decay is measured in whole thirty-day epochs: `decay_epochs` is the
    elapsed time from `last_credited_at` to the current logical instant divided by
    thirty days and floored to a whole number, never below zero."
    The PRD: "The distance of the raw figure from the base of 50 is then multiplied by
    0.80 raised to the power of `decay_epochs`, and that shrunken distance is added back
    to the base."
    The PRD: "`vote_weight` follows on inclusive thresholds: 3 when `reputation_score`
    is at least 70.00, 2 when it is at least 40.00 but below 70.00, and 1 below 40.00."
    The PRD: "Reputation is re-derived whenever a member is read individually, whenever
    one of their issues is accepted or rejected, whenever one of their showcase
    submissions is approved, and whenever they cast a vote."

    One accepted issue gives a raw figure of 50 + 6 x 1 = 56, and at the moment of the
    acceptance `last_credited_at` is the current logical instant, so `decay_epochs` is 0
    and the score is 50 + 6 x 0.80^0 = 56.00. Advancing the clock from
    2026-08-01T00:00:00Z to 2026-08-31T00:00:00Z is exactly 30 days, so
    `decay_epochs` is 30 / 30 = 1 and the individual read gives
    50 + 6 x 0.80 = 50 + 4.80 = 54.80. The base itself never decays, and 54.80 sits at
    or above 40.00 and below 70.00, so `vote_weight` stays 2.

    Design: Corner/calculations/member_reputation_decays_one_epoch_after_thirty_days
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"],
        member["member_id"],
        ctx["department_id"],
        severity="MEDIUM",
        category="ACCURACY",
        api=api,
    )
    fixtures.accept_quality_issue(issue["id"], ctx["department_id"], api=api)

    credited = fixtures.read_member(member["member_id"], api=api)
    assert credited["accepted_issue_count"] == 1, (
        f"Expected accepted_issue_count 1, got {credited['accepted_issue_count']}"
    )
    assert credited["decay_epochs"] == 0, (
        f"Expected decay_epochs 0 at the moment of the credit, got {credited['decay_epochs']}"
    )
    assert_money(credited["reputation_score"], 56.00, "reputation_score before any decay")
    assert credited["vote_weight"] == 2, (
        f"Expected vote_weight 2 at 56.00, got {credited['vote_weight']}"
    )

    fixtures.set_clock("2026-08-31T00:00:00Z", api=api)
    decayed = validate_success(api.get_member(member["member_id"], PORTAL_ADMIN_HEADERS))

    assert decayed["decay_epochs"] == 1, (
        f"Expected decay_epochs 1 exactly thirty days after the credit, got {decayed['decay_epochs']}"
    )
    assert_money(decayed["reputation_score"], 54.80, "reputation_score after one decay epoch")
    assert decayed["vote_weight"] == 2, (
        f"Expected vote_weight 2 at 54.80, got {decayed['vote_weight']}"
    )
    assert decayed["accepted_issue_count"] == 1, (
        f"Expected accepted_issue_count 1, got {decayed['accepted_issue_count']}"
    )
    assert decayed["rejected_issue_count"] == 0, (
        f"Expected rejected_issue_count 0, got {decayed['rejected_issue_count']}"
    )
    assert decayed["status"] == "ACTIVE", (
        f"Expected member status ACTIVE, got {decayed['status']}"
    )


# ─── Departmental risk points ─────────────────────────────────────────


def test_department_risk_points_compose_to_six_and_suspend_the_posture(api):
    """One breached dataset, one under remediation and one overdue correction make 6.

    The PRD: "`risk_points` is then three points for each breached dataset, plus two
    points for each stale dataset, plus two points for each dataset under remediation,
    plus one point for each overdue correction."
    The PRD: "From `risk_points` the posture follows on inclusive boundaries: at least 6
    points is `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0
    points is `OPEN`."
    The PRD: "`overdue_correction_count` is the number of quality issues on the
    department's datasets whose `status` is `ACCEPTED` and whose `correction_breached`
    flag is true."
    The PRD: "Second, `days_overdue` is zero whenever `next_due_at` is null or the
    logical clock has not yet passed it, and is otherwise the elapsed seconds from
    `next_due_at` to the current logical instant divided by 86400 and floored to a whole
    number of days."
    The PRD: "Third, a grace allowance is read off the dataset's `priority_tier`: 2 days
    for `TIER_1`, 7 days for `TIER_2`, 14 days for `TIER_3` — the more valuable the
    dataset, the shorter its rope."
    The PRD: "Beyond twice the grace it is `BREACHED` — but only for a dataset whose
    `high_value_committed` flag is true; a dataset without that commitment floors at
    `STALE` and never reaches `BREACHED` however long it is neglected."
    The PRD: "Step four walks the quality issues in ascending `created_at` order,
    inspecting only those whose `status` is `SUBMITTED` or `ACCEPTED`: a
    still-`SUBMITTED` issue whose `triage_due_at` the logical clock has strictly passed
    latches `triage_breached` to true, and a still-`ACCEPTED` issue whose
    `correction_due_at` the logical clock has strictly passed latches
    `correction_breached` to true."
    The PRD: "Step two emits staleness alerting: every dataset that is entering or
    remaining in `STALE` or `BREACHED` emits exactly one alert per sweep, increasing
    `staleness_alert_count` by 1 and setting `last_staleness_alert_at` to the current
    logical instant."

    The dataset is committed as high-value while its stored tier is still the declared
    `TIER_1` (0.45 x 92.00 + 0.35 x 96.00 = 41.40 + 33.60 = 75.00), then published, which
    re-scores it as observed: 0.45 x 0.00 + 0.35 x 96.00 = 33.60, so the stored tier is
    `TIER_3` and the grace allowance is 14 days. Publication at 2026-08-01T00:00:00Z with
    a `WEEKLY` cadence puts `next_due_at` at 2026-08-08T00:00:00Z, so at
    2026-09-06T00:00:00Z `days_overdue` is 29 — beyond twice the grace of 28 — and the
    high-value commitment lets that land on `BREACHED`. The accepted `CRITICAL` issue
    carries a `correction_due_at` of 2026-08-06T00:00:00Z, which the clock has strictly
    passed, so the sweep latches `correction_breached`. The counters then read breached
    1, stale 0, remediation 1, overdue corrections 1, giving
    3 x 1 + 2 x 0 + 2 x 1 + 1 x 1 = 6 risk points — the first value that leaves
    `RESTRICTED` (2 points, from the remediation alone) behind for `SUSPENDED`.

    Design: Corner/calculations/department_posture_suspends_at_six_risk_points
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=0)

    committed = fixtures.commit_high_value(ctx["dataset_id"], api=api)
    assert committed["high_value_committed"] is True, (
        f"Expected high_value_committed True, got {committed.get('high_value_committed')!r}"
    )
    assert_priority(committed, priority_tier="TIER_1")

    published = fixtures.publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=50000, api=api
    )
    assert_priority(
        published,
        priority_score=33.60,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert _instant(published["next_due_at"]) == _utc(2026, 8, 8), (
        f"Expected next_due_at 2026-08-08T00:00:00Z, got {published.get('next_due_at')}"
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
    accepted = fixtures.accept_quality_issue(issue["id"], ctx["department_id"], api=api)
    assert _instant(accepted["correction_due_at"]) == _utc(2026, 8, 6), (
        f"Expected correction_due_at 2026-08-06T00:00:00Z, got {accepted.get('correction_due_at')}"
    )

    before = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(before, risk_points=2, compliance_posture="RESTRICTED", remediation=1)

    report = fixtures.advance_clock_and_sweep("2026-09-06T00:00:00Z", api=api)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["days_overdue"] == 29, (
        f"Expected days_overdue 29 at 2026-09-06, got {dataset['days_overdue']}"
    )
    assert_dataset_states(
        dataset, publication_status="UNDER_REMEDIATION", currency_status="BREACHED"
    )

    swept_issue = validate_success(api.get_quality_issue(issue["id"], ANONYMOUS_HEADERS))
    assert swept_issue["status"] == "ACCEPTED", (
        f"Expected the issue to stay ACCEPTED, got {swept_issue['status']}"
    )
    assert swept_issue["correction_breached"] is True, (
        f"Expected correction_breached True, got {swept_issue.get('correction_breached')!r}"
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

    assert report["datasets_recomputed"] == 1, (
        f"Expected datasets_recomputed 1, got {report['datasets_recomputed']}"
    )
    assert report["currency_transitions"] == 1, (
        f"Expected currency_transitions 1, got {report['currency_transitions']}"
    )
    assert report["staleness_alerts_emitted"] == 1, (
        f"Expected staleness_alerts_emitted 1, got {report['staleness_alerts_emitted']}"
    )
    assert report["issues_correction_breached"] == 1, (
        f"Expected issues_correction_breached 1, got {report['issues_correction_breached']}"
    )
    assert report["postures_changed"] == 1, (
        f"Expected postures_changed 1, got {report['postures_changed']}"
    )


# ─── The issue service-level clocks ───────────────────────────────────


def test_high_severity_issue_takes_the_one_day_and_fourteen_day_allowances(api):
    """A `HIGH` issue is due for triage in 24 hours and for correction in 14 days.

    The PRD: "The issue starts at `status` `SUBMITTED` with `triage_breached` and
    `correction_breached` both false, `resolution_version_id` null, and a
    `triage_due_at` computed as its `created_at` plus a severity-dependent allowance:
    seven days for `LOW`, three days for `MEDIUM`, one day for `HIGH`, and eight hours
    for `CRITICAL`."
    The PRD: "Triage stamps `triaged_at` at the current logical instant and latches
    `triage_breached` to true when the logical clock is strictly past `triage_due_at`;
    arriving exactly at the deadline is on time, not late."
    The PRD: "Hop one records the acceptance: `accepted_at` is stamped at the current
    logical instant, `correction_due_at` is set to `accepted_at` plus a
    severity-dependent allowance of 90 days for `LOW`, 30 days for `MEDIUM`, 14 days for
    `HIGH` and 5 days for `CRITICAL`, the reporter's `accepted_issue_count` increases by
    1, the reporter's `last_credited_at` becomes the current logical instant, and the
    reporter's `reputation_score` and `vote_weight` are re-derived."
    The PRD: "Accepting a quality issue that is both `CRITICAL` in `severity` and
    `PRIVACY` in `category` against a `PUBLISHED` dataset runs four hops: the issue
    moves to `ACCEPTED`, the dataset moves `PUBLISHED → UNDER_REMEDIATION`, that
    dataset's `ARMED` pipeline moves to `SUSPENDED`, and because the pipeline is now
    suspended the dataset's `currency_status` takes a `STALE` floor while its pipeline's
    pending runs are skipped — after which the department's counters, `risk_points` and
    `compliance_posture` are re-derived."

    The two allowances are keyed on the same `severity` in different units. Filed at
    2026-08-01T00:00:00Z, a `HIGH` issue is due for triage one day later at
    2026-08-02T00:00:00Z — not the 8 hours a `CRITICAL` issue would get nor the three
    days a `MEDIUM` one would. Triage at 2026-08-01T06:00:00Z is well before that, so
    `triage_breached` stays false, and the acceptance at that same instant sets
    `correction_due_at` to 2026-08-01T06:00:00Z plus 14 days = 2026-08-15T06:00:00Z, not
    the 5 days of `CRITICAL` or the 30 of `MEDIUM`. The remediation cascade is defined
    for a `CRITICAL` and `PRIVACY` acceptance, so this `HIGH` and `TIMELINESS` one
    leaves the dataset `PUBLISHED`, and the reporter's raw reputation is
    50 + 6 x 1 = 56.00 with no elapsed decay epoch.

    Design: Corner/calculations/quality_issue_sla_clock_applies_severity_constants
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    member = fixtures.setup_member(api=api)

    issue = fixtures.file_quality_issue(
        ctx["dataset_id"],
        member["member_id"],
        severity="HIGH",
        category="TIMELINESS",
        api=api,
        description="The weekly refresh landed three days late",
    )
    assert _instant(issue["triage_due_at"]) == _utc(2026, 8, 2), (
        f"Expected triage_due_at 2026-08-02T00:00:00Z for a HIGH issue, got {issue.get('triage_due_at')}"
    )
    assert issue["triage_breached"] is False, (
        f"Expected triage_breached False on a fresh issue, got {issue.get('triage_breached')!r}"
    )

    fixtures.set_clock("2026-08-01T06:00:00Z", api=api)
    triaged = validate_success(
        api.triage_quality_issue(issue["id"], ctx["coordinator_headers"])
    )
    assert _instant(triaged["triaged_at"]) == _utc(2026, 8, 1, 6), (
        f"Expected triaged_at 2026-08-01T06:00:00Z, got {triaged.get('triaged_at')}"
    )
    assert triaged["triage_breached"] is False, (
        "Triage six hours into a 24-hour allowance is on time, so triage_breached must "
        f"stay False, got {triaged.get('triage_breached')!r}"
    )

    accepted = validate_success(
        api.decide_quality_issue(
            issue["id"], factories.decision_payload("ACCEPT"), ctx["coordinator_headers"]
        )
    )

    assert accepted["status"] == "ACCEPTED", (
        f"Expected status ACCEPTED, got {accepted['status']}"
    )
    assert _instant(accepted["accepted_at"]) == _utc(2026, 8, 1, 6), (
        f"Expected accepted_at 2026-08-01T06:00:00Z, got {accepted.get('accepted_at')}"
    )
    assert _instant(accepted["correction_due_at"]) == _utc(2026, 8, 15, 6), (
        "Expected correction_due_at 2026-08-15T06:00:00Z for a HIGH issue, got "
        f"{accepted.get('correction_due_at')}"
    )
    assert accepted["correction_breached"] is False, (
        f"Expected correction_breached False, got {accepted.get('correction_breached')!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED")

    reporter = fixtures.read_member(member["member_id"], api=api)
    assert reporter["accepted_issue_count"] == 1, (
        f"Expected accepted_issue_count 1, got {reporter['accepted_issue_count']}"
    )
    assert_money(reporter["reputation_score"], 56.00, "reputation_score after one acceptance")


def test_sweep_latches_triage_breach_and_the_late_triage_does_not_clear_it(api):
    """The sweep flags a still-`SUBMITTED` issue, and triage afterwards keeps the flag.

    The PRD: "The issue starts at `status` `SUBMITTED` with `triage_breached` and
    `correction_breached` both false, `resolution_version_id` null, and a
    `triage_due_at` computed as its `created_at` plus a severity-dependent allowance:
    seven days for `LOW`, three days for `MEDIUM`, one day for `HIGH`, and eight hours
    for `CRITICAL`."
    The PRD: "Step four walks the quality issues in ascending `created_at` order,
    inspecting only those whose `status` is `SUBMITTED` or `ACCEPTED`: a
    still-`SUBMITTED` issue whose `triage_due_at` the logical clock has strictly passed
    latches `triage_breached` to true, and a still-`ACCEPTED` issue whose
    `correction_due_at` the logical clock has strictly passed latches
    `correction_breached` to true."
    The PRD: "Both breach flags in this system latch: once true they are never cleared
    by a later observation, and `correction_breached` is cleared only by the correction
    itself."
    The PRD: "`overdue_correction_count` is the number of quality issues on the
    department's datasets whose `status` is `ACCEPTED` and whose `correction_breached`
    flag is true."

    A `MEDIUM` issue filed at 2026-08-01T00:00:00Z is due for triage three days later,
    at 2026-08-04T00:00:00Z. At 2026-08-05T00:00:00Z the clock has strictly passed that
    deadline while the issue is still `SUBMITTED`, so the sweep latches
    `triage_breached` and reports one triage breach and no correction breach — the
    correction clock is anchored on `accepted_at`, which has not happened, so
    `correction_due_at` is unset and `correction_breached` is false. The triage that
    follows stamps `triaged_at` but cannot clear the latched flag. The department earns
    no risk points from it, because only `ACCEPTED` issues flagged
    `correction_breached` feed `overdue_correction_count`, and the dataset is still
    `CURRENT` because 2026-08-05 precedes its `next_due_at` of 2026-08-08T00:00:00Z.

    Design: Corner/calculations/issue_breach_flags_are_stamped_by_the_sweep_before_any_transition
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_quality_issue(
        ctx["dataset_id"],
        member["member_id"],
        severity="MEDIUM",
        category="ACCURACY",
        api=api,
        description="Counts for two corridors disagree with the signal logs",
    )
    assert _instant(issue["triage_due_at"]) == _utc(2026, 8, 4), (
        f"Expected triage_due_at 2026-08-04T00:00:00Z for a MEDIUM issue, got {issue.get('triage_due_at')}"
    )

    report = fixtures.advance_clock_and_sweep("2026-08-05T00:00:00Z", api=api)
    assert report["issues_triage_breached"] == 1, (
        f"Expected issues_triage_breached 1, got {report['issues_triage_breached']}"
    )
    assert report["issues_correction_breached"] == 0, (
        f"Expected issues_correction_breached 0, got {report['issues_correction_breached']}"
    )

    swept = validate_success(api.get_quality_issue(issue["id"], ANONYMOUS_HEADERS))
    assert swept["status"] == "SUBMITTED", (
        f"Expected the issue to still be SUBMITTED after the sweep, got {swept['status']}"
    )
    assert swept["triage_breached"] is True, (
        f"Expected the sweep to latch triage_breached True, got {swept.get('triage_breached')!r}"
    )
    assert swept.get("triaged_at") is None, (
        f"Expected triaged_at to still be null after the sweep, got {swept.get('triaged_at')!r}"
    )

    triaged = validate_success(
        api.triage_quality_issue(issue["id"], ctx["coordinator_headers"])
    )

    assert triaged["status"] == "TRIAGED", (
        f"Expected status TRIAGED, got {triaged['status']}"
    )
    assert _instant(triaged["triaged_at"]) == _utc(2026, 8, 5), (
        f"Expected triaged_at 2026-08-05T00:00:00Z, got {triaged.get('triaged_at')}"
    )
    assert triaged["triage_breached"] is True, (
        "A latched triage_breached is never cleared by a later observation, got "
        f"{triaged.get('triage_breached')!r}"
    )
    assert triaged.get("correction_due_at") is None, (
        "The correction clock is anchored on accepted_at, so correction_due_at must be "
        f"unset before acceptance, got {triaged.get('correction_due_at')!r}"
    )
    assert triaged["correction_breached"] is False, (
        f"Expected correction_breached False, got {triaged.get('correction_breached')!r}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department, risk_points=0, compliance_posture="OPEN", overdue_corrections=0
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="CURRENT")


# ─── Which demand figure the priority score uses ──────────────────────


def test_publish_flips_the_priority_variant_without_new_usage_arriving(api):
    """Traffic recorded at `READY` only reaches the score once the dataset publishes.

    The PRD: "Recording usage is allowed from `SCREENING` onward, because a catalogue
    page draws traffic before the extract itself is published; any earlier state is
    refused with `ERR_DATASET_NOT_PUBLISHED`."
    The PRD: "While the dataset's `publication_status` is `INVENTORIED`, `SCREENING` or
    `READY` — before its catalog page has any traffic worth trusting — the demand term
    is the coordinator's declared `public_demand_score` and the variant is
    `AS_DECLARED`."
    The PRD: "Once the dataset's `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`, the demand term becomes the measured `observed_demand_score`
    and the variant is `AS_OBSERVED`."
    The PRD: "From that score, `priority_tier` follows on inclusive thresholds:
    `TIER_1` at 75.00 or above, `TIER_2` at 50.00 or above, and `TIER_3` otherwise."
    The PRD: "First, `next_due_at` is the dataset's `last_published_at` plus the number
    of days its `update_frequency` implies — 1 day for `DAILY`, 7 for `WEEKLY`, 30 for
    `MONTHLY`, 91 for `QUARTERLY`, 365 for `ANNUAL` — and is null both when
    `update_frequency` is `IRREGULAR` and when the dataset has never been published."

    One epoch of 2000 API calls and 500 downloads is worth 0.60 x 2000 + 0.40 x 500 =
    1200 + 200 = 1400; as the only and therefore highest-indexed epoch it carries the
    0.50 positional weight and nothing else, giving 700 / 50 = 14.00 for both
    `engagement_index` and `observed_demand_score`. While the dataset is `READY` that
    measurement is ignored by the score, which stays the declared
    0.45 x 92.00 + 0.35 x 96.00 + 0.20 x 0 = 41.40 + 33.60 = 75.00 at `TIER_1`. The
    publish transition alone flips the variant, with no new data arriving: the score
    becomes 0.45 x 14.00 + 0.35 x 96.00 = 6.30 + 33.60 = 39.90, which is below 50.00 and
    so lands at `TIER_3`, while the engagement measurement itself is unchanged at 14.00.
    Publication at 2026-08-01T00:00:00Z with a `WEEKLY` cadence sets `next_due_at` to
    2026-08-08T00:00:00Z, which the clock has not passed, so currency is `CURRENT`.

    Design: Corner/calculations/priority_variant_selected_by_publication_status_with_traffic
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=0)
    fixtures.report_usage_epoch(ctx["dataset_id"], 1, 2000, 500, api=api)

    at_ready = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_money(at_ready["engagement_index"], 14.00, "engagement_index at READY")
    assert_money(at_ready["observed_demand_score"], 14.00, "observed_demand_score at READY")
    assert_priority(
        at_ready,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )

    published = fixtures.publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=50000, api=api
    )

    assert_dataset_states(published, publication_status="PUBLISHED", currency_status="CURRENT")
    assert_priority(
        published,
        priority_score=39.90,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert_money(published["engagement_index"], 14.00, "engagement_index after publication")
    assert _instant(published["next_due_at"]) == _utc(2026, 8, 8), (
        f"Expected next_due_at 2026-08-08T00:00:00Z, got {published.get('next_due_at')}"
    )
    assert published["days_overdue"] == 0, (
        f"Expected days_overdue 0 on a freshly published dataset, got {published['days_overdue']}"
    )

    reread = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_priority(reread, priority_score=39.90, priority_tier="TIER_3")
