"""Case lifecycle: required fields, auto-advance posture, close guard, dual-variant spend."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_case, ApiErrorId,
    create_case_payload, create_case, open_request, screen_candidate,
    create_draft_engagement, propose_engagement, sign_engagement, fund_retainer,
    submit_invoice, approve_invoice, pay_invoice, approve_and_pay_invoice,
    create_schedule, confirm_schedule, create_confirmed_schedule, create_report,
    setup_scenario, setup_active_engagement,
    TEST_USERS, make_expert_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
BILLING = TEST_USERS["billing_reviewer_headers"]


class TestCaseCreation:

    def test_missing_budget_returns_invalid_request(self, api):
        """PRD §2.11: "then the request body shape is checked — required fields present,
        types correct, enum members valid — with violations yielding `ERR_INVALID_REQUEST`
        (HTTP 400)".
        PRD §3.2: "A `CaseManager` opens a litigation matter with its `case_number` — unique
        per firm — plus the `court` of venue, a matter `title`, the total expert-spend
        `budget_cents` (strictly positive), the `trial_date`, and the `report_deadline`."

        Design: Corner/entities/case_create_missing_required_budget_returns_invalid_request
        """
        payload = create_case_payload()
        del payload["budget_cents"]
        res = api.create_case(payload, CM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestCaseAutoAdvance:

    def test_case_posture_advances_through_report_phase(self, api):
        """PRD §3.2: "A new matter's `status` begins at `INTAKE`" and "the first request
        created for a case automatically moves the case `INTAKE` → `SOURCING`".
        PRD §3.3: "If the matter is still in `SOURCING`, the first signature automatically
        moves the case `SOURCING` → `ENGAGED`."
        PRD §3.5: "The first report opened on any engagement of a case moves the case
        `ENGAGED` → `DISCOVERY`."

        Design: Corner/state_machines/case_auto_advance_through_report_phase
        """
        sc = setup_scenario(target_state="PROPOSED", fund=False)
        case = sc["case"]
        assert case["status"] == "INTAKE"

        after_request = validate_success(api.get_case(case["id"], CM), 200)
        assert after_request["status"] == "SOURCING"

        sign_engagement(sc["engagement"]["id"], sc["expert"]["id"])
        after_sign = validate_success(api.get_case(case["id"], CM), 200)
        assert after_sign["status"] == "ENGAGED"

        fund_retainer(sc["engagement"]["id"], sc["engagement"]["retainer_cents"])
        create_report(sc["engagement"]["id"])
        after_report = validate_success(api.get_case(case["id"], CM), 200)
        assert after_report["status"] == "DISCOVERY"


class TestCaseCloseGuard:

    def test_case_close_blocked_by_non_terminal_engagement(self, api):
        """PRD §3.8: "A `CaseManager` may close a case from `ENGAGED`, from `DISCOVERY`, or
        from `TRIAL_PREP` — the same preconditions apply at all three — once every
        engagement of the case has reached `CLOSED` or `TERMINATED` and every invoice on
        those engagements has reached `PAID` or `REJECTED`; otherwise the close is rejected
        with `ERR_CASE_NOT_CLOSABLE`."

        Design: Corner/endpoints/case_close_blocked_by_active_engagement
        """
        sc = setup_active_engagement()
        assert sc["engagement"]["status"] == "ACTIVE"

        res = api.close_case(sc["case"]["id"], CM)
        validate_error(res, ApiErrorId.ERR_CASE_NOT_CLOSABLE)


class TestCommittedVsActuals:
    """Dual-variant spend projection on the same case data."""

    def _setup_dual_variant_scenario(self, api):
        """ACTIVE engagement (rate 40000, retainer 300000 funded, expense cap 40000) on a
        2000000-budget case; one 20000 invoice APPROVED→PAID; one CONFIRMED 8h deposition;
        one 680000 invoice left SUBMITTED."""
        sc = setup_active_engagement(
            case_overrides={"budget_cents": 2_000_000},
            engagement_overrides={"hourly_rate_cents": 40_000, "retainer_cents": 300_000,
                                  "expense_cap_cents": 40_000})
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]

        inv_a = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 0.5}], 20_000)
        approve_and_pay_invoice(inv_a["id"])

        create_confirmed_schedule(gid, kind="DEPOSITION",
                                  start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T12:00:00Z",
                                  estimated_hours=8)

        submit_invoice(gid, eid,
                       [{"kind": "PREP", "hours": 10}, {"kind": "TESTIMONY", "hours": 4},
                        {"kind": "TRAVEL_TIME", "hours": 2}],
                       680_000, travel_expense_cents=50_000,
                       period_start="2026-05-09T00:00:00Z", period_end="2026-05-15T00:00:00Z")
        return sc

    def test_actuals_paid_counts_only_paid_invoices(self, api):
        """PRD §2.9: "`actuals_paid_cents` is the chronological, backward-looking variant:
        the sum of `computed_total_cents` over all invoices in `PAID` status on the case's
        engagements." and "`approved_outstanding_cents` is the sum of `computed_total_cents`
        over invoices in `APPROVED` status that have not yet been paid."

        Design: Difficulty/dual_variant_calc/case_budget_committed_vs_actuals
        """
        sc = self._setup_dual_variant_scenario(api)
        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert_case(case)
        assert case["actuals_paid_cents"] == 20_000, "only the PAID invoice counts in actuals"
        assert case["approved_outstanding_cents"] == 0, "the paid invoice is no longer outstanding"

    def test_committed_projection_is_forward_looking(self, api):
        """PRD §2.9: "`committed_cents` is the forward-looking variant: the paid actuals,
        plus the computed totals of approved-but-unpaid invoices, plus the computed totals
        of invoices still in `SUBMITTED` or `DISPUTED`, plus the `retainer_remaining_cents`
        of every engagement of the case currently in `ACTIVE` status, plus the cost estimate
        of every testimony session in `CONFIRMED` status on the case's engagements. A
        confirmed session's estimate is its `estimated_hours` multiplied by the engagement's
        `hourly_rate_cents`, multiplied by one and a quarter, rounded half-up to the nearest
        cent."

        Design: Difficulty/dual_variant_calc/case_budget_committed_vs_actuals
        """
        sc = self._setup_dual_variant_scenario(api)
        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        # 20000 paid + 680000 submitted + 280000 retainer remaining + 8*40000*1.25 = 400000 estimate
        assert case["committed_cents"] == 1_380_000
        assert case["committed_cents"] != case["actuals_paid_cents"], (
            "the two variants must diverge whenever spend is pending")


class TestCommittedExcludesTerminal:

    def test_rejected_invoice_and_cancelled_schedule_excluded(self, api):
        """PRD §2.9: "Rejected invoices and paid-terminal items contribute nothing to the
        forward part beyond the actuals term, and cancelled or completed sessions are
        excluded from it entirely."

        Design: Corner/calculations/committed_projection_excludes_terminal_items
        """
        sc = setup_active_engagement()
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]

        inv = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 0.5}], 20_000)
        validate_success(api.dispute_invoice(inv["id"], {"reason": "bad"}, BILLING), 200)
        settled = validate_success(api.settle_invoice(inv["id"], {"outcome": "REJECTED"}, BILLING), 200)
        assert settled["status"] == "REJECTED"

        sched = create_schedule(gid, estimated_hours=4)
        cancelled = validate_success(api.cancel_schedule(sched["id"], {"reason": "dropped"}, CM), 200)
        assert cancelled["status"] == "CANCELLED"

        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert case["committed_cents"] == 0, "REJECTED invoice and CANCELLED schedule are excluded; retainer is 0"
        assert case["actuals_paid_cents"] == 0
