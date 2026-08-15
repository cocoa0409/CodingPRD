"""Nonrenewal path: content coverage at approval, the mailing deadline
boundary, and period bucketing of completed nonrenewals in volume reports.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_nonrenewal,
    assert_nonrenewal_case,
    create_active_profile,
    create_holder,
    dispatch_nonrenewal_notices,
    issue_policy,
    open_nonrenewal_case,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]


class TestNonrenewalContentCoverage:
    def test_nonrenewal_content_codes_incomplete_rejected(self, api):
        """PRD §3.6: "The twist is content: the case's `content_codes_present`
        must cover every code in the pinned profile's
        `nonrenewal_content_codes`, and a notice program missing required
        content is rejected with `ERR_NONRENEWAL_CONTENT_INCOMPLETE`."

        Design: Corner/validations/nonrenewal_content_codes_incomplete_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile(
            "MN", nonrenewal_content_codes=["SPECIFIC_REASON", "FAIR_PLAN_INFO"]
        )
        holder = create_holder(full_name="Mn Insured", email="mn@x.com")
        policy = issue_policy(
            profile["id"], holder["id"], "P-MN-1",
            term_start_date="2026-01-01", term_end_date="2026-12-31",
            total_premium_cents=10000,
        )
        case = open_nonrenewal_case(
            policy["id"], reason_code="RISK_INELIGIBLE", reason_text="Brush zone",
            content_codes_present=["SPECIFIC_REASON"],
        )

        resp = api.approve_nonrenewal_case(case["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NONRENEWAL_CONTENT_INCOMPLETE)

        current = fx.get_nonrenewal_case(case["id"])
        assert current["status"] == "PENDING_APPROVAL"
        assert fx.get_policy(policy["id"])["status"] == "ACTIVE"


class TestNonrenewalDeadlineBoundary:
    def _approved_pair(self):
        """Two UT policies with APPROVED nonrenewal cases (deadline 2026-11-01)."""
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("UT")
        holder1 = create_holder(full_name="Ut One", email="ut1@x.com")
        holder2 = create_holder(full_name="Ut Two", email="ut2@x.com")
        policy1 = issue_policy(
            profile["id"], holder1["id"], "P-UT-1",
            term_start_date="2026-01-01", term_end_date="2026-12-31",
            total_premium_cents=24000,
        )
        policy2 = issue_policy(
            profile["id"], holder2["id"], "P-UT-2",
            term_start_date="2026-01-01", term_end_date="2026-12-31",
            total_premium_cents=24000,
        )
        case1 = open_nonrenewal_case(
            policy1["id"], reason_code="UNDERWRITING_GUIDELINES", reason_text="Guideline change"
        )
        case2 = open_nonrenewal_case(
            policy2["id"], reason_code="LOSS_HISTORY", reason_text="Three losses"
        )
        approve_nonrenewal(case1["id"])
        approve_nonrenewal(case2["id"])
        return case1, case2

    def test_notice_mailed_exactly_on_deadline_is_timely(self, api):
        """PRD §3.6: "The statutory clock differs from cancellation, though:
        every notice's `mailed_on_date` must be on or before the case's
        `notice_deadline_date`. Mailing exactly on the deadline is on time;
        mailing one day later is late, and a late set fails with
        `ERR_NONRENEWAL_NOTICE_LATE`." For a 2026-12-31 term end and 60 days
        of notice the deadline is 2026-11-01.

        Design: Difficulty/boundary_precision_check/nonrenewal_notice_mailed_exactly_on_deadline_is_timely
        """
        case1, _case2 = self._approved_pair()
        assert case1["notice_deadline_date"] == "2026-11-01", (
            f"deadline = term_end 2026-12-31 - 60 days; got {case1['notice_deadline_date']}"
        )

        fx.set_clock("2026-11-01T00:00:00Z")
        notices = dispatch_nonrenewal_notices(case1["id"], "2026-11-01", tracking_prefix="T-UT-1")
        assert all(n["status"] == "MAILED" for n in notices)
        current = fx.get_nonrenewal_case(case1["id"])
        assert current["status"] == "NOTICE_SENT"

    def test_notice_mailed_one_day_after_deadline_is_late(self, api):
        """PRD §3.6: "The statutory clock differs from cancellation, though:
        every notice's `mailed_on_date` must be on or before the case's
        `notice_deadline_date`. Mailing exactly on the deadline is on time;
        mailing one day later is late, and a late set fails with
        `ERR_NONRENEWAL_NOTICE_LATE`."

        Design: Difficulty/boundary_precision_check/nonrenewal_notice_mailed_exactly_on_deadline_is_timely
        """
        _case1, case2 = self._approved_pair()
        assert case2["notice_deadline_date"] == "2026-11-01"

        # Clock on the mailing date itself so only the deadline rule can fire.
        fx.set_clock("2026-11-02T00:00:00Z")
        resp = api.dispatch_nonrenewal_notices(
            case2["id"], {"notices": [{"recipient_kind": "POLICYHOLDER",
                                       "mailed_on_date": "2026-11-02",
                                       "tracking_code": "T-UT-2"}]},
            TEST_USERS["underwriter_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NONRENEWAL_NOTICE_LATE)

        current = fx.get_nonrenewal_case(case2["id"])
        assert current["status"] == "APPROVED", "a late dispatch must not advance the case"


class TestNonrenewalVolumeBucketing:
    def test_nonrenewal_volume_counts_completed_only_in_period(self, api):
        """PRD §2.10: "The `nonrenewal_count` counts nonrenewal cases that
        reached `COMPLETED` against policies pinned to that profile whose
        `term_end_date` falls within the period." and "A period runs from the
        first day of its month, inclusive, up to the first day of the
        following month, exclusive — a left-closed, right-open window — and
        counting is order-insensitive."
        PRD §3.6: "when the current clock date reaches the policy's
        `term_end_date` with the case in `NOTICE_SENT`, the case moves
        `NOTICE_SENT → COMPLETED`, the policy moves `NONRENEWAL_PENDING →
        EXPIRED`, and the `nonrenewal_count` for the pinned profile and the
        month containing the `term_end_date` is incremented — auto-creating
        the `OPEN` report row if none exists."

        Design: Corner/calculations/nonrenewal_volume_counts_completed_only_in_period
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        profile = create_active_profile("RI")
        holder1 = create_holder(full_name="Ri One", email="ri1@x.com")
        holder2 = create_holder(full_name="Ri Two", email="ri2@x.com")
        policy_a = issue_policy(
            profile["id"], holder1["id"], "P-RI-A",
            term_start_date="2025-09-01", term_end_date="2026-08-31",
            total_premium_cents=10000,
        )
        policy_b = issue_policy(
            profile["id"], holder2["id"], "P-RI-B",
            term_start_date="2025-09-02", term_end_date="2026-09-01",
            total_premium_cents=10000,
        )
        case_a = open_nonrenewal_case(policy_a["id"], reason_text="G")
        case_b = open_nonrenewal_case(policy_b["id"], reason_text="G")
        approve_nonrenewal(case_a["id"])
        approve_nonrenewal(case_b["id"])

        # Mail on 2026-06-01 with the clock on the same date: on or before
        # both deadlines (2026-07-02 and 2026-07-03) and not in the future.
        fx.set_clock("2026-06-01T00:00:00Z")
        dispatch_nonrenewal_notices(case_a["id"], "2026-06-01", tracking_prefix="T-RI-A")
        dispatch_nonrenewal_notices(case_b["id"], "2026-06-01", tracking_prefix="T-RI-B")

        fx.set_clock("2026-09-02T00:00:00Z")

        report_aug = fx.find_report(profile["id"], "2026-08")
        assert report_aug["nonrenewal_count"] == 1, (
            "policy A's term_end 2026-08-31 falls inside the left-closed August window"
        )
        assert report_aug["status"] == "OPEN"

        report_sep = fx.find_report(profile["id"], "2026-09")
        assert report_sep["nonrenewal_count"] == 1, (
            "policy B's term_end 2026-09-01 belongs to September (right-open boundary)"
        )
        assert report_sep["status"] == "OPEN"

        assert fx.get_policy(policy_a["id"])["status"] == "EXPIRED"
        assert fx.get_policy(policy_b["id"])["status"] == "EXPIRED"
        assert fx.get_nonrenewal_case(case_a["id"])["status"] == "COMPLETED"
        assert fx.get_nonrenewal_case(case_b["id"])["status"] == "COMPLETED"
