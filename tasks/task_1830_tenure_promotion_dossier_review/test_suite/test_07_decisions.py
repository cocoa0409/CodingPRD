"""Recommendation score computation, the provost decision gates, notification
and closure windows, and the archive/purge lifecycle (PRD §3.6, §3.7, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_date_eq,
    assert_decimal_eq,
    file_appeal,
    latest_round,
    make_candidate_headers,
    read_candidate,
    read_case,
    record_decision,
    set_logical_clock,
    setup_decided_case,
    setup_provost_review_case,
    validate_error,
    validate_paginated,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]
PO_DECIDER = TEST_USERS["provost_decider_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]

# Every level: 5 members + silent chair, ballots YES x3 / NO x2 -> pct 0.60.
SIXTY_SPECS = {
    level: {"member_count": 5, "ballots": ["YES", "YES", "YES", "NO", "NO"]}
    for level in ("DEPARTMENT", "COLLEGE", "UNIVERSITY")
}
# Every level: 2 members + silent chair, ballots YES/NO -> pct 0.50 (STRICT
# fails the strict-greater-than-half test at every level).
SPLIT_SPECS = {
    level: {"member_count": 2, "ballots": ["YES", "NO"]}
    for level in ("DEPARTMENT", "COLLEGE", "UNIVERSITY")
}
# Weighted-sum specimen: 0.75 / 0.80 / 0.6667, all STRICT-passing.
ALL_PASS_SPECS = {
    "DEPARTMENT": {"member_count": 4, "ballots": ["YES", "YES", "YES", "NO"]},
    "COLLEGE": {"member_count": 5, "ballots": ["YES", "YES", "YES", "YES", "NO"]},
    "UNIVERSITY": {"member_count": 3, "ballots": ["YES", "YES", "NO"]},
}
# Fail-cap specimen: 0.80 / 0.80 / 0.50 with the university round failed.
FAIL_CAP_SPECS = {
    "DEPARTMENT": {"member_count": 5, "ballots": ["YES", "YES", "YES", "YES", "NO"]},
    "COLLEGE": {"member_count": 5, "ballots": ["YES", "YES", "YES", "YES", "NO"]},
    "UNIVERSITY": {"member_count": 2, "ballots": ["YES", "NO"],
                   "recommendation": "NEUTRAL"},
}


def test_sod_decision_recorder_gate(api):
    """PRD §3.7: "The recorder's identity, stored as `recorded_by_user_id`, must
    differ from the case's `created_by_user_id`
    (`ERR_SOD_DECISION_BY_CASE_CREATOR`)."
    PRD §3.7: "On success the decision is created in `RECORDED` status,
    `decided_at` is stamped, and the `notification_deadline` is set ten days
    after `decided_at`."

    Design: Corner/validations/sod_decision_recorder_gate
    """
    ctx = setup_provost_review_case("E9310", email_prefix="ds")
    case_id = ctx["case"]["id"]

    # The case was opened by po_creator; the same officer may not record.
    err = api.create_decision(
        {"case_id": case_id, "decision": "GRANT_TENURE",
         "rationale_text": "Creator tries."},
        PO_HEADERS,
    )
    validate_error(err, ApiErrorId.ERR_SOD_DECISION_BY_CASE_CREATOR)

    decision = record_decision(case_id, "GRANT_TENURE",
                               rationale_text="Independent officer.")
    assert decision["status"] == "RECORDED"
    assert_date_eq(decision["notification_deadline"], "2026-08-11",
                   "notification_deadline (decided_at 2026-08-01 + 10 days)")
    assert read_case(case_id)["stage"] == "DECIDED"


class TestScoreThresholdBoundary:
    def test_score_exactly_060_admits_grant_without_override(self, api):
        """PRD §3.7: "And for any granting decision — `GRANT_TENURE`,
        `GRANT_PROMOTION`, or `GRANT_BOTH` — the case's `recommendation_score`
        must be at least 0.60 unless a non-empty `override_rationale` is
        supplied; a grant below the threshold without an override is rejected
        with `ERR_SCORE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/score_threshold_exact_060_grant_allowed
        """
        ctx = setup_provost_review_case("E1500", level_specs=SIXTY_SPECS,
                                        email_prefix="n")
        # 0.25*0.6 + 0.35*0.6 + 0.40*0.6 lands exactly on the 0.60 threshold.
        assert_decimal_eq(ctx["case"]["recommendation_score"], 0.6,
                          "recommendation_score")
        decision = record_decision(ctx["case"]["id"], "GRANT_TENURE",
                                   rationale_text="Meets threshold.")
        assert decision["status"] == "RECORDED"

    def test_grant_records_decision_and_tenures_candidate(self, api):
        """PRD §3.7: "The case moves from `PROVOST_REVIEW` to `DECIDED` and its
        `version` increments by one. The candidate cascade follows the verdict:
        a `DENY` moves the candidate's `status` to `NOT_RENEWED`, and a
        `GRANT_TENURE` or `GRANT_BOTH` recorded on a case whose `seeking_tenure`
        is true moves the candidate to `TENURED`."

        Design: Difficulty/boundary_precision_check/score_threshold_exact_060_grant_allowed
        """
        ctx = setup_provost_review_case("E1501", level_specs=SIXTY_SPECS,
                                        email_prefix="n2")
        decision = record_decision(ctx["case"]["id"], "GRANT_TENURE",
                                   rationale_text="Meets threshold.")
        assert decision["status"] == "RECORDED"
        assert read_case(ctx["case"]["id"])["stage"] == "DECIDED"
        assert read_candidate(ctx["candidate"]["id"])["status"] == "TENURED"


def test_score_below_threshold_rejected_then_override_allowed(api):
    """PRD §3.7: "And for any granting decision — `GRANT_TENURE`,
    `GRANT_PROMOTION`, or `GRANT_BOTH` — the case's `recommendation_score` must
    be at least 0.60 unless a non-empty `override_rationale` is supplied; a
    grant below the threshold without an override is rejected with
    `ERR_SCORE_BELOW_THRESHOLD`."
    PRD §3.6: "If any of the three selected rounds failed, the stored score is
    the raw sum rounded half-up to four decimal places, capped at 0.49 —
    whichever is smaller".

    Design: Corner/validations/score_below_threshold_rejected_then_override_allowed
    """
    ctx = setup_provost_review_case("E9311", level_specs=SPLIT_SPECS,
                                    email_prefix="ov")
    case_id = ctx["case"]["id"]
    # All three levels failed at 0.50; raw 0.5 is capped to 0.49.
    assert_decimal_eq(ctx["case"]["recommendation_score"], 0.49,
                      "capped recommendation_score")

    err = api.create_decision(
        {"case_id": case_id, "decision": "GRANT_TENURE",
         "rationale_text": "No override given."},
        PO_DECIDER,
    )
    validate_error(err, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD)

    decision = record_decision(
        case_id, "GRANT_TENURE", rationale_text="With override.",
        override_rationale="President's discretion: landmark external letters.",
    )
    assert decision["status"] == "RECORDED", (
        "A non-empty override_rationale lifts the score gate"
    )


class TestRecommendationScoreAllPass:
    def test_recommendation_score_weighted_sum_all_pass(self, api):
        """PRD §3.6: "The raw score is the department percentage weighted at
        0.25, the college percentage at 0.35, and the university percentage at
        0.40, summed."
        PRD §3.6: "For example, percentages of 0.75, 0.80, and 0.6667 with all
        rounds passed yield a raw 0.73418 and a stored 0.7342".

        Design: Difficulty/combinatorial_formula/case_score_weighted_sum_all_pass
        """
        ctx = setup_provost_review_case("E500", level_specs=ALL_PASS_SPECS,
                                        email_prefix="p")
        assert ctx["case"]["stage"] == "PROVOST_REVIEW"
        assert_decimal_eq(ctx["case"]["recommendation_score"], 0.7342,
                          "recommendation_score")

    def test_all_levels_pass_and_percentages_recorded(self, api, reader_headers):
        """PRD §3.6: "For each of the three levels it takes the case's
        `COMPLETED` round at that level — when several exist after a remand, the
        one with the latest `certified_at`, ties broken by latest `created_at` —
        and reads its already-rounded `yes_percentage`."

        Design: Difficulty/combinatorial_formula/case_score_weighted_sum_all_pass
        """
        ctx = setup_provost_review_case("E501", level_specs=ALL_PASS_SPECS,
                                        email_prefix="p2")
        case_id = ctx["case"]["id"]
        expected = {"DEPARTMENT": 0.75, "COLLEGE": 0.80, "UNIVERSITY": 0.6667}
        for level, pct in expected.items():
            round_data = validate_success(
                api.get_round(latest_round(case_id, level=level)["id"],
                              reader_headers)
            )
            assert round_data["passed"] is True, f"{level} round must pass"
            assert_decimal_eq(round_data["yes_percentage"], pct,
                              f"{level} yes_percentage")


class TestRecommendationScoreFailCap:
    def test_failed_university_round_caps_score_at_049(self, api):
        """PRD §3.6: "If any of the three selected rounds failed, the stored
        score is the raw sum rounded half-up to four decimal places, capped at
        0.49 — whichever is smaller; otherwise it is simply the raw sum rounded
        half-up to four decimal places."
        PRD §3.6: "while percentages of 0.80, 0.80, and 0.50 with the university
        round failed yield a raw 0.68 and a stored 0.49".

        Design: Difficulty/combinatorial_formula/case_score_fail_cap_min_branch
        """
        ctx = setup_provost_review_case("E600", level_specs=FAIL_CAP_SPECS,
                                        email_prefix="q")
        assert ctx["case"]["stage"] == "PROVOST_REVIEW"
        assert_decimal_eq(ctx["case"]["recommendation_score"], 0.49,
                          "capped recommendation_score")

    def test_strict_tie_fails_pass_verdict(self, api, reader_headers):
        """PRD §3.6: "Under `STRICT_MAJORITY_OF_CAST`, the round passes when the
        yes-share of cast yes-plus-no ballots is strictly greater than one half —
        an exact tie fails."

        Design: Difficulty/combinatorial_formula/case_score_fail_cap_min_branch
        """
        ctx = setup_provost_review_case("E601", level_specs=FAIL_CAP_SPECS,
                                        email_prefix="q2")
        round_data = validate_success(
            api.get_round(latest_round(ctx["case"]["id"], level="UNIVERSITY")["id"],
                          reader_headers)
        )
        assert_decimal_eq(round_data["yes_percentage"], 0.5, "yes_percentage")
        assert round_data["passed"] is False, "STRICT: 1/2 = 0.5 is NOT > 0.5"


class TestAppealRequiresNotifiedCase:
    def test_appeal_filed_while_decided_rejected(self, api):
        """PRD §3.8: "A candidate who disputes the outcome files an appeal while
        the case is `NOTIFIED` — any other stage is rejected with
        `ERR_CASE_STAGE_FORBIDDEN`".

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_notified_case
        """
        ctx = setup_decided_case("E1700", decision="GRANT_TENURE", email_prefix="h")
        err = api.create_appeal(
            {"case_id": ctx["case"]["id"], "grounds": "PROCEDURAL_ERROR"},
            make_candidate_headers(ctx["candidate"]["id"]),
        )
        validate_error(err, ApiErrorId.ERR_CASE_STAGE_FORBIDDEN)

    def test_rejected_appeal_leaves_no_record(self, api):
        """PRD §3.8: "A candidate who disputes the outcome files an appeal while
        the case is `NOTIFIED` — any other stage is rejected with
        `ERR_CASE_STAGE_FORBIDDEN`"

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_notified_case
        """
        ctx = setup_decided_case("E1701", decision="GRANT_TENURE", email_prefix="h2")
        api.create_appeal(
            {"case_id": ctx["case"]["id"], "grounds": "PROCEDURAL_ERROR"},
            make_candidate_headers(ctx["candidate"]["id"]),
        )
        data, meta = validate_paginated(
            api.list_appeals(READER_HEADERS, {"case_id": ctx["case"]["id"]})
        )
        assert meta["total_count"] == 0 and data == []


def test_notification_window_lapsed(api):
    """PRD §3.7: "A `ProvostOfficer` notifies the candidate only while a
    `RECORDED` decision exists — otherwise `ERR_DECISION_NOT_FOUND` — and only
    while the logical clock has not passed the `notification_deadline`, with
    notification exactly at the deadline still permitted; a late notification is
    rejected with `ERR_NOTIFICATION_WINDOW_LAPSED`."

    Design: Corner/validations/notification_window_lapsed
    """
    ctx = setup_decided_case("E9313", decision="GRANT_TENURE", email_prefix="nl")
    # Decided at 2026-08-01; deadline 2026-08-11; the attempt is one day late.
    set_logical_clock("2026-08-12T00:00:00Z")
    err = api.notify_case(ctx["case"]["id"], PO_HEADERS)
    validate_error(err, ApiErrorId.ERR_NOTIFICATION_WINDOW_LAPSED)
    assert read_case(ctx["case"]["id"])["stage"] == "DECIDED"


def test_decision_to_purge_lifecycle_with_window_boundaries(
    api, appeal_officer_headers, records_officer_headers
):
    """PRD §3.7: "On success `notification_sent_at` is stamped on the decision,
    the case's `appeal_filing_deadline` is set thirty days after the
    notification, the case moves from `DECIDED` to `NOTIFIED`".
    PRD §3.8: "requires the filing to fall on or before the case's
    `appeal_filing_deadline`, with a filing exactly at the deadline permitted —
    a late filing is rejected with `ERR_APPEAL_WINDOW_LAPSED` — and requires
    that no other appeal of the case stands in `FILED` or `UNDER_REVIEW`,
    otherwise `ERR_APPEAL_ALREADY_OPEN`."
    PRD §3.8: "Resolution or review attempted from an incompatible appeal status
    is rejected with `ERR_INVALID_APPEAL_STATE`".
    PRD §3.7: "Closing requires the logical clock to be strictly past the
    `appeal_filing_deadline` — an attempt at or before the deadline is rejected
    with `ERR_APPEAL_WINDOW_OPEN` — and requires that no appeal of the case
    stands in `FILED` or `UNDER_REVIEW` (`ERR_APPEAL_PENDING`). On success
    `closed_at` is stamped, `retention_until` is set 2,555 days after closure —
    seven 365-day years — the case moves from `NOTIFIED` to `CLOSED`".
    PRD §3.9: "Purge is the final act: it is permitted only once the logical
    clock has reached the case's `retention_until`, with a purge exactly at the
    boundary permitted; an earlier attempt is rejected with
    `ERR_RETENTION_NOT_EXPIRED`."

    Design: Corner/validations/decision_to_purge_lifecycle_with_window_boundaries
    """
    ctx = setup_decided_case("E9312", decision="GRANT_TENURE", email_prefix="fp")
    case_id = ctx["case"]["id"]
    candidate_id = ctx["candidate"]["id"]

    # Notify exactly at the notification deadline (2026-08-11): inclusive.
    set_logical_clock("2026-08-11T00:00:00Z")
    notified = validate_success(api.notify_case(case_id, PO_HEADERS))
    assert notified["stage"] == "NOTIFIED"
    assert_date_eq(notified["appeal_filing_deadline"], "2026-09-10",
                   "appeal_filing_deadline (notification + 30 days)")

    # Appeal filed exactly at the appeal deadline: permitted.
    set_logical_clock("2026-09-10T00:00:00Z")
    appeal = file_appeal(case_id, candidate_id, grounds="PROCEDURAL_ERROR")
    assert appeal["status"] == "FILED"

    dup = api.create_appeal(
        {"case_id": case_id, "grounds": "NEW_EVIDENCE"},
        make_candidate_headers(candidate_id),
    )
    validate_error(dup, ApiErrorId.ERR_APPEAL_ALREADY_OPEN)

    premature = api.resolve_appeal(
        appeal["id"],
        {"resolution": "DENIED", "resolution_text": "Too fast."},
        appeal_officer_headers,
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_APPEAL_STATE)

    validate_success(api.begin_review_appeal(appeal["id"], appeal_officer_headers))
    resolved = validate_success(
        api.resolve_appeal(
            appeal["id"],
            {"resolution": "DENIED", "resolution_text": "Reviewed and denied."},
            appeal_officer_headers,
        )
    )
    assert resolved["status"] == "DENIED"

    # Close one day after the appeal window lapsed (strictly past the deadline).
    set_logical_clock("2026-09-11T00:00:00Z")
    closed = validate_success(api.close_case(case_id, PO_HEADERS))
    assert closed["stage"] == "CLOSED"
    assert_date_eq(closed["retention_until"], "2033-09-09",
                   "retention_until (closed_at 2026-09-11 + 2555 days)")

    archived = validate_success(api.archive_case(case_id, records_officer_headers))
    assert archived["stage"] == "ARCHIVED"

    # Purge one day early is refused; exactly at retention_until it passes.
    set_logical_clock("2033-09-08T00:00:00Z")
    err_purge = api.purge_case(case_id, records_officer_headers)
    validate_error(err_purge, ApiErrorId.ERR_RETENTION_NOT_EXPIRED)

    set_logical_clock("2033-09-09T00:00:00Z")
    purged = validate_success(api.purge_case(case_id, records_officer_headers))
    assert purged["stage"] == "PURGED"

    assert read_candidate(candidate_id)["status"] == "TENURED"
