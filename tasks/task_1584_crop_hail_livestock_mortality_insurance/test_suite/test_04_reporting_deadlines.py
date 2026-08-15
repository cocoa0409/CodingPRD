"""Acreage/head reporting deadlines, lateness, and claim notice windows
(PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_acreage_report,
    file_hail_claim,
    make_policyholder_headers,
    set_clock,
    setup_active_paid_crop_hail_policy,
    submit_planting_report,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


def _setup_policy_at_deadline(api):
    """Policy effective 2026-08-02 (acreage deadline 2026-08-23), bound, with two
    one-acre units; clock advanced to exactly 2026-08-23T00:00:00Z."""
    ctx = setup_active_paid_crop_hail_policy(
        acres_list=(1, 1), activate_clock=None,
        effective_date="2026-08-02T00:00:00Z",
        expiration_date="2026-12-31T00:00:00Z",
    )
    set_clock(ctx["carrier_id"], "2026-08-23T00:00:00Z")
    return ctx


class TestAcreageDeadlineBoundary:
    def test_report_at_exact_deadline_is_timely(self, api):
        """PRD §3.5: "A planting report is timely when submitted on or before the
        `acreage_report_deadline`; a harvest report when submitted on or before
        the `harvest_report_deadline`; an initial head report when submitted on
        or before the `head_report_deadline`."
        PRD §3.5: "A timely report sets `is_timely` true, leaves `lateness_days`
        and `coverage_reduction_pct` at zero, and — when the unit is still
        waiting on its first report — moves it from `PENDING_REPORT` to
        `REPORTED`."
        The acreage deadline is effective+21d = 2026-08-23T00:00:00Z; submitting
        at exactly that instant is timely (inclusive boundary).

        Design: Difficulty/boundary_precision_check/acreage_report_lateness_exactly_at_deadline_is_timely
        """
        ctx = _setup_policy_at_deadline(api)
        cu_a = ctx["units"][0]
        res = api.create_acreage_report(
            ctx["carrier_id"], ctx["policy_id"], cu_a["id"],
            {"report_kind": "PLANTING", "reported_acres": 1},
            make_policyholder_headers(ctx["grower_id"]),
        )
        report = validate_success(res, 201)
        assert_acreage_report(report)
        assert report["is_timely"] is True
        assert report["lateness_days"] == 0
        assert report["coverage_reduction_pct"] == 0

    def test_report_one_second_past_deadline_is_late(self, api):
        """PRD §3.5: "A late planting, harvest, or initial head report instead
        counts `lateness_days` as the whole days past the deadline, with any
        partial day rounded up to the next whole day, and sets
        `coverage_reduction_pct` to five percent per late day, capped at one
        hundred percent; a unit whose first report arrives late falls from
        `PENDING_REPORT` to `LAPSED_REPORT`, as it also does when the deadline
        passes with no report at all, or when the policy expires while the unit
        is still `PENDING_REPORT`."
        PRD §3.5: "a unit whose first report arrives late falls from
        `PENDING_REPORT` to `LAPSED_REPORT`, as it also does when the deadline
        passes with no report at all, or when the policy expires while the unit
        is still `PENDING_REPORT`."
        One second past the 2026-08-23T00:00:00Z deadline rounds up to one whole
        late day, hence a five-percent reduction.

        Design: Difficulty/boundary_precision_check/acreage_report_lateness_exactly_at_deadline_is_timely
        """
        ctx = _setup_policy_at_deadline(api)
        cu_b = ctx["units"][1]
        set_clock(ctx["carrier_id"], "2026-08-23T00:00:01Z")
        res = api.create_acreage_report(
            ctx["carrier_id"], ctx["policy_id"], cu_b["id"],
            {"report_kind": "PLANTING", "reported_acres": 1},
            make_policyholder_headers(ctx["grower_id"]),
        )
        report = validate_success(res, 201)
        assert_acreage_report(report)
        assert report["is_timely"] is False
        assert report["lateness_days"] == 1, (
            "any partial day of lateness rounds up to the next whole day"
        )
        assert report["coverage_reduction_pct"] == 5


class TestClaimNoticeWindow:
    def _setup_two_reported_units(self, api):
        ctx = setup_active_paid_crop_hail_policy(acres_list=(2, 2))
        for unit in ctx["units"]:
            submit_planting_report(
                ctx["carrier_id"], ctx["policy_id"], unit["id"],
                ctx["grower_id"], reported_acres=2,
            )
        return ctx

    def test_late_notification_penalty_72h_boundary_crop_hail(self, api):
        """PRD §3.7: "a hail claim reported within seventy-two hours of the loss,
        or a livestock claim reported within twenty-four hours, sets
        `reported_within_window` true and carries no penalty; notice past the
        window but within seven days of the loss draws a ten-percent
        `late_notification_penalty_pct`; notice past seven days but within thirty
        days draws twenty-five percent. The boundaries are inclusive — a report
        exactly seventy-two or twenty-four hours after the loss is within the
        window, and one exactly seven days past draws the ten-percent tier."
        Loss at 2026-08-04T00:00:00Z: reporting at exactly +72h carries no
        penalty; reporting one second past +72h draws ten percent.

        Design: Corner/calculations/late_notification_penalty_72h_boundary_crop_hail
        """
        ctx = self._setup_two_reported_units(api)
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        cu1, cu2 = ctx["units"]

        set_clock(cid, "2026-08-07T00:00:00Z")  # exactly loss + 72h
        claim_a = file_hail_claim(cid, pid, gid, cu1["id"])
        assert claim_a["late_notification_penalty_pct"] == 0
        assert claim_a["reported_within_window"] is True, (
            "a report exactly seventy-two hours after the loss is within the window"
        )

        set_clock(cid, "2026-08-07T00:00:01Z")  # one second past +72h
        claim_b = file_hail_claim(cid, pid, gid, cu2["id"])
        assert claim_b["late_notification_penalty_pct"] == 10
        assert claim_b["reported_within_window"] is False

    def test_late_notice_over_30d_rejected_at_intake(self, api):
        """PRD §3.7: "Second, notice given more than thirty days after the loss
        is non-payable by rule and is refused at intake with
        `ERR_LATE_NOTICE_OVER_30D` (HTTP 422); the coverage-window check runs
        first, so an out-of-coverage loss surfaces as
        `ERR_LOSS_DATE_OUT_OF_COVERAGE` rather than being masked by the
        late-notice rule."

        Design: Corner/validations/late_notice_over_30d_rejected_at_intake
        """
        ctx = setup_active_paid_crop_hail_policy(acres_list=(1,))
        cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
        submit_planting_report(cid, pid, ctx["units"][0]["id"], gid, reported_acres=1)
        set_clock(cid, "2026-09-10T00:00:00Z")  # 37 days after the loss
        res = api.create_claim(
            cid, pid,
            {"coverage_unit_id": ctx["units"][0]["id"],
             "loss_date": "2026-08-04T00:00:00Z", "percent_damage_estimate_pct": 10},
            make_policyholder_headers(gid),
        )
        validate_error(res, ApiErrorId.ERR_LATE_NOTICE_OVER_30D)
