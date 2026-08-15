"""Report requirements, closeout gating, and the final financial report
(PRD §3.7, §3.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_report_requirement_payload, create_drawdown_request_payload,
    setup_sponsor_pi, create_active_award, post_expenditure, create_drawdown,
    setup_closeout_pending_award, get_award_version,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


class TestReportDoubleSubmit:
    def test_report_double_submit_rejected(self, api):
        """PRD §3.7: "Submission comes from the project side: a
        `PrincipalInvestigator` acting on their own award (the award's `pi_id`
        must equal `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`) or a
        `GrantCoordinator` may submit a `PENDING` or `OVERDUE` requirement —
        other states return `ERR_REPORT_NOT_SUBMITTABLE` — optionally with a
        `submission_note`."

        Design: Corner/state_machines/report_double_submit_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award, _lines = create_active_award(
            sponsor["id"], pi["id"], "SM-005",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        rpt = get_success_data(api.create_report_requirement(
            create_report_requirement_payload(
                award["id"], report_type="MILESTONE",
                due_date="2026-09-01T00:00:00Z"), SPO))
        first = validate_success(api.submit_report(rpt["id"], {}, GC), 200)
        res = api.submit_report(rpt["id"], {}, GC)
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_SUBMITTABLE.value)
        rpt_after = validate_success(api.get_report_requirement(rpt["id"], GA), 200)
        assert rpt_after["submitted_at"] == first["submitted_at"]


class TestCloseoutBeforeEndDate:
    def test_closeout_before_end_date_rejected(self, api):
        """PRD §3.9: "an accountant initiates it only when the logical clock
        has reached `current_end_date` (`ERR_CLOSEOUT_TOO_EARLY`)."

        Design: Corner/errors/closeout_before_end_date_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award, _lines = create_active_award(
            sponsor["id"], pi["id"], "CE-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        res = api.initiate_closeout(award["id"], GA)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_TOO_EARLY.value)
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["status"] == "ACTIVE"


class TestCloseoutGates:
    def test_close_without_accepted_ffr_returns_closeout_incomplete(self, api):
        """PRD §3.9: "Final close is the accountant's last act and is gated on
        everything: the final report must be `ACCEPTED`; no receivable may
        remain `OPEN`, `PARTIALLY_PAID`, or `DISPUTED`; no drawdown may remain
        in `DRAFT` or `SUBMITTED`; no subaward invoice may remain in `RECEIVED`
        or `UNDER_REVIEW`; and every report requirement must be `ACCEPTED` —
        any failure returns `ERR_CLOSEOUT_INCOMPLETE`."

        Design: Corner/state_machines/award_close_without_accepted_ffr_returns_closeout_incomplete
        """
        (_sp, _pi, award, _line, ffr) = setup_closeout_pending_award("CL-001")
        res = api.close_award(award["id"], GA)
        validate_error(res, ApiErrorId.ERR_CLOSEOUT_INCOMPLETE.value)
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["status"] == "CLOSEOUT_PENDING"

    def test_ffr_submit_with_unliquidated_obligations_rejected(self, api):
        """PRD §3.9: "the declared `unliquidated_obligations_cents` must be
        exactly zero (`ERR_UNLIQUIDATED_OBLIGATIONS`); no subaward invoice may
        sit in `RECEIVED` or `UNDER_REVIEW` and no drawdown in `DRAFT` or
        `SUBMITTED` (either case `ERR_CLOSEOUT_INCOMPLETE`)."

        Design: Corner/errors/ffr_submit_with_unliquidated_obligations_rejected
        """
        (_sp, _pi, award, _line, ffr) = setup_closeout_pending_award("UL-001")
        res = api.submit_ffr(ffr["id"], {"unliquidated_obligations_cents": 5000}, GA)
        validate_error(res, ApiErrorId.ERR_UNLIQUIDATED_OBLIGATIONS.value)
        submitted = validate_success(api.submit_ffr(
            ffr["id"], {"unliquidated_obligations_cents": 0}, GA), 200)
        assert submitted["status"] == "SUBMITTED"
        # Nothing drawn: the full obligation is residual.
        assert submitted["residual_cents"] == 150_000


class TestCloseoutHappyPathWithResidualDeobligation:
    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "CC-001",
            [
                {"category": "TRAVEL", "authorized_cents": 100_000},
                {"category": "OTHER_DIRECT", "authorized_cents": 100_000},
            ],
            300_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=100_000, cash_disbursed=True)
        # Pool: 100000 + round(0.5*100000) = 150000; draw it all.
        d = create_drawdown(award["id"], 150_000)
        validate_success(api.submit_drawdown(d["id"], GA), 200)
        validate_success(api.settle_drawdown(d["id"], SO), 200)
        get_success_data(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, ADMIN))
        award = validate_success(api.initiate_closeout(award["id"], GA), 200)
        ffr = validate_success(api.list_final_financial_reports(
            GA, params={"award_id": award["id"]}), 200)[0]
        return award, ffr

    def test_initiate_closeout_creates_draft_ffr(self, api):
        """PRD §3.9: "The award moves `ACTIVE → CLOSEOUT_PENDING`, the
        system creates the award's single `FinalFinancialReport` in `DRAFT` —
        discoverable by filtering the final-financial-reports list by
        `award_id` — posture recomputes with FFR lateness now gating, and the
        award's `version` bumps."

        Design: Corner/state_machines/closeout_happy_path_with_residual_deobligation
        """
        award, ffr = self._setup(api)
        assert award["status"] == "CLOSEOUT_PENDING"
        assert ffr["status"] == "DRAFT"

    def test_submit_accept_close_deobligates_residual(self, api):
        """PRD §3.9: "On submit the system snapshots `total_expenditures_cents`
        as the award's `total_direct_spent_cents` plus `f_and_a_accrued_cents`,
        `residual_cents` as `total_obligated_cents` minus
        `cumulative_drawn_cents`, and `cost_share_shortfall_cents` as the
        greater of zero and `cost_share_committed_cents` minus
        `cost_share_met_cents`." PRD §3.9: "On close the award moves
        `CLOSEOUT_PENDING → CLOSED`, `residual_deobligated_cents` records
        `total_obligated_cents` minus `cumulative_drawn_cents`,
        `total_obligated_cents` is reduced to `cumulative_drawn_cents` (the
        residual is deobligated back to the sponsor)..."

        Design: Corner/state_machines/closeout_happy_path_with_residual_deobligation
        """
        award, ffr = self._setup(api)
        submitted = validate_success(api.submit_ffr(
            ffr["id"], {"unliquidated_obligations_cents": 0}, GA), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_expenditures_cents"] == 150_000  # 100000 + 50000
        assert submitted["residual_cents"] == 150_000
        assert submitted["cost_share_shortfall_cents"] == 0
        validate_success(api.accept_ffr(ffr["id"], SO), 200)
        closed = validate_success(api.close_award(award["id"], GA), 200)
        assert closed["status"] == "CLOSED"
        assert closed["residual_deobligated_cents"] == 150_000
        assert closed["total_obligated_cents"] == 150_000
