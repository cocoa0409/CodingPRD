"""QA sampling quota and the backlog snapshot (PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    assert_backlog_summary,
    assert_qa_review,
    close_cases_no_sar,
    create_case,
    create_customer,
    create_qa_review_payload,
    create_staff,
    set_clock,
    validate_error,
    validate_success,
)


def _six_closed_cases(staff):
    """Six cases fully closed via the NO_SAR path, all within the default
    logical month 2026-05: six completed work items for the quota pool."""
    customer = create_customer(staff)
    return close_cases_no_sar(staff, customer["id"], 6)


def test_qa_samples_allowed_up_to_computed_quota(api):
    """PRD §3.10: "Second, the monthly quota is that count multiplied by 0.34,
    rounded up to the next integer, then clamped to the range from 1 to 25
    inclusive."
    PRD §3.10: "Creation is permitted only while the sample count remains
    strictly below the quota; exceeding it is `ERR_QA_QUOTA_EXCEEDED`."
    PRD §3.10: "Because step one ignores the samples themselves, creating a
    sample never shrinks the quota within the same month — an implementation
    that subtracts sampled items from the pool before applying the rate is
    non-conformant."

    Six completions give clamp(ceil(6 * 0.34), 1, 25) == 3; the third sample
    succeeding is the order-sensitive assertion (a pool that shrank after
    sampling would recompute ceil(5 * 0.34) == 2 and reject it).

    Design: Difficulty/combinatorial_formula/qa_quota_pool_snapshot_order
    """
    staff = create_staff()
    cases = _six_closed_cases(staff)

    created = []
    for case in cases[:3]:
        review = validate_success(api.create_qa_review(
            create_qa_review_payload(case_id=case["id"]), staff.qa), 201)
        assert_qa_review(review)
        assert review["status"] == "SAMPLED"
        assert review["period_month"] == "2026-05"
        created.append(review)
    assert len(created) == 3, "the third sample must succeed"

    res = api.create_qa_review(
        create_qa_review_payload(case_id=cases[3]["id"]), staff.qa)
    validate_error(res, ApiErrorId.ERR_QA_QUOTA_EXCEEDED)
    assert res.status_code == 422, "sampled_in_month 3 is not strictly below quota 3"


def test_backlog_summary_reports_quota_and_samples(api):
    """PRD §3.10: "The snapshot additionally reports `overdue_sar_count` (SARs
    not yet `FILED` whose `deadline_at` has passed), `stale_alert_count`
    (alerts in `NEW` or `UNDER_TRIAGE` whose age exceeds their scenario's
    `stale_alert_days`), `overdue_review_count` (continuing reviews in
    `SCHEDULED` or `OVERDUE` whose `due_at` has passed), and the QA progress
    pair `qa_samples_this_month` and `qa_quota_this_month`."
    PRD §3.10: "It reports the total count of open cases (those in `OPEN`,
    `ASSIGNED`, `INVESTIGATING`, `ON_HOLD`, `SAR_IN_PROGRESS`, or
    `PENDING_QA`)".

    Design: Difficulty/combinatorial_formula/qa_quota_pool_snapshot_order
    """
    staff = create_staff()
    cases = _six_closed_cases(staff)
    for case in cases[:3]:
        validate_success(api.create_qa_review(
            create_qa_review_payload(case_id=case["id"]), staff.qa), 201)

    summary = validate_success(api.get_backlog_summary(staff.manager), 200)
    assert_backlog_summary(summary)
    assert summary["qa_quota_this_month"] == 3
    assert summary["qa_samples_this_month"] == 3
    assert summary["cases_open"] == 0, "all six cases are CLOSED"


def test_backlog_buckets_move_at_age_16(api):
    """PRD §3.10: "`cases_age_0_15` counts ages from 0 up to but not including
    16 days, `cases_age_16_30` covers 16 up to but not including 31,
    `cases_age_31_60` covers 31 up to but not including 61, and
    `cases_age_61_plus` covers 61 days and beyond."

    A case created at the default clock 2026-05-01 is 15 days old on
    2026-05-16 (first bucket) and 16 days old on 2026-05-17 (second bucket).

    Design: Corner/calculations/backlog_bucket_edge_age_16
    """
    staff = create_staff()
    customer = create_customer(staff)
    create_case(staff, customer["id"])  # OPEN, created 2026-05-01

    set_clock(staff, "2026-05-16T00:00:00Z")  # age exactly 15 days
    summary = validate_success(api.get_backlog_summary(staff.manager), 200)
    assert summary["cases_open"] == 1
    assert summary["cases_age_0_15"] == 1
    assert summary["cases_age_16_30"] == 0

    set_clock(staff, "2026-05-17T00:00:00Z")  # age exactly 16 days
    summary = validate_success(api.get_backlog_summary(staff.manager), 200)
    assert summary["cases_age_0_15"] == 0
    assert summary["cases_age_16_30"] == 1
