"""Letter-of-credit drawdowns: posture gates, the clock-driven overdue ->
posture -> drawdown-cancel cascade, and pool conservation (PRD §2.9, §3.6,
§3.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_report_requirement_payload, create_drawdown_request_payload,
    setup_sponsor_pi, create_active_award, post_expenditure, create_drawdown,
    get_award_version,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def _setup_pool_award(api, award_number):
    """ACTIVE LOC award (TRAVEL 100000, obligated 150000) with 100000 posted
    cash-disbursed -> eligible pool 150000."""
    sponsor, pi = setup_sponsor_pi()
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number,
        [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
    post_expenditure(award["id"], lines["TRAVEL"]["id"], amount_cents=100_000,
                     cash_disbursed=True)
    return pi, award, lines["TRAVEL"]


class TestDrawdownSubmitGatedByAwardPosture:
    """Difficulty instance: same submit succeeds at OPEN, fails at RESTRICTED."""

    def _setup(self, api):
        pi, award, travel = _setup_pool_award(api, "DG-001")
        get_success_data(api.create_report_requirement(
            create_report_requirement_payload(
                award["id"], report_type="MILESTONE",
                due_date="2026-08-05T00:00:00Z"), SPO))
        return pi, award

    def test_submit_succeeds_while_posture_open(self, api):
        """PRD §3.6: "Submitting the draw requires the award `ACTIVE` or
        `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_ACTIVE`) with posture `OPEN`
        (`ERR_AWARD_RESTRICTED` when restricted, `ERR_AWARD_FROZEN` when
        frozen), and the amount must not exceed `available_draw_pool_cents`
        (`ERR_DRAWDOWN_EXCEEDS_ELIGIBLE`)."
        PRD §3.6: "On submit the request moves `DRAFT → SUBMITTED`, the amount
        moves from available to reserved (`reserved_draw_cents` up,
        `available_draw_pool_cents` down), and `eligible_pool_at_submission`
        snapshots the pool for audit while `submitted_at` records the clock."

        Design: Difficulty/cross_entity_state_dependency/drawdown_submit_gated_by_award_posture
        """
        pi, award = self._setup(api)
        d1 = create_drawdown(award["id"], 50_000)
        submitted = validate_success(api.submit_drawdown(d1["id"], GA), 200)
        assert submitted["status"] == "SUBMITTED"

    def test_submit_rejected_after_posture_restricted(self, api):
        """PRD §2.9: "Otherwise it is `RESTRICTED` when any report
        requirement is `OVERDUE`, or when the FFR is past due by at least one
        day."
        PRD §2.9: "The posture gates financial writes: expenditure create and
        drawdown submit require posture `OPEN` (a `RESTRICTED` award returns
        `ERR_AWARD_RESTRICTED`, a `FROZEN` award returns `ERR_AWARD_FROZEN`);
        expenditure post, cost-transfer approve and countersign, and
        subaward-invoice approve require posture other than `FROZEN`
        (`ERR_AWARD_FROZEN`)."

        Design: Difficulty/cross_entity_state_dependency/drawdown_submit_gated_by_award_posture
        """
        pi, award = self._setup(api)
        d1 = create_drawdown(award["id"], 50_000)
        validate_success(api.submit_drawdown(d1["id"], GA), 200)
        # MILESTONE report lapses: clock 2026-08-06 -> OVERDUE -> RESTRICTED.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-06T00:00:00Z"}, ADMIN))
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["posture"] == "RESTRICTED"
        d2 = validate_success(api.create_drawdown_request(
            create_drawdown_request_payload(
                award["id"], 50_000, award_after["version"]), GA), 201)
        res = api.submit_drawdown(d2["id"], GA)
        validate_error(res, ApiErrorId.ERR_AWARD_RESTRICTED.value)
        d2_after = validate_success(api.get_drawdown_request(d2["id"], GA), 200)
        assert d2_after["status"] == "DRAFT"


class TestClockOverduePostureFrozenDrawdownCascade:
    """Difficulty instance: clock -> OVERDUE -> posture -> drawdown cancel."""

    def _setup(self, api):
        pi, award, travel = _setup_pool_award(api, "D-001")
        rpt = get_success_data(api.create_report_requirement(
            create_report_requirement_payload(
                award["id"], report_type="FINAL_TECHNICAL",
                due_date="2026-08-10T00:00:00Z"), SPO))
        d1 = create_drawdown(award["id"], 50_000)              # stays DRAFT
        d2 = create_drawdown(award["id"], 100_000)
        validate_success(api.submit_drawdown(d2["id"], GA), 200)
        return pi, award, rpt, d1, d2

    def test_overdue_drives_restricted_without_cancelling_draws(self, api):
        """PRD §3.7: "The overdue sweep runs on every logical-clock
        advance: when the clock passes a `PENDING` requirement's `due_date`,
        the requirement moves to `OVERDUE`, its `days_overdue` recomputes as
        whole days from `due_date` to the clock, and the award's posture
        recomputes per §2.9 — the first cascade link drops the award to
        `RESTRICTED`, and a `FINAL_TECHNICAL` requirement more than 30 days
        overdue pushes it to `FROZEN`, which in turn cancels every `DRAFT` or
        `SUBMITTED` drawdown and releases its reservation."

        Design: Difficulty/transitive_cascade/clock_overdue_posture_frozen_drawdown_cascade
        """
        pi, award, rpt, d1, d2 = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, ADMIN))
        rpt_after = validate_success(api.get_report_requirement(rpt["id"], GA), 200)
        assert rpt_after["status"] == "OVERDUE"
        assert rpt_after["days_overdue"] == 1
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["posture"] == "RESTRICTED"
        assert award_after["reserved_draw_cents"] == 100_000  # no cancel yet

    def test_frozen_cancels_draft_and_submitted_draws(self, api):
        """PRD §2.9: "An award is `FROZEN` when any `FINAL_TECHNICAL`
        report requirement has `days_overdue` greater than 30, or when the FFR
        itself is more than 30 days past its due date while the award is in
        `CLOSEOUT_PENDING` with the FFR not yet `ACCEPTED`."
        PRD §2.9: "On entering `FROZEN`, every drawdown request of the award in
        `DRAFT` or `SUBMITTED` status is cancelled and any reservation is
        released back to the available pool."

        Design: Difficulty/transitive_cascade/clock_overdue_posture_frozen_drawdown_cascade
        """
        pi, award, rpt, d1, d2 = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, ADMIN))
        rpt_after = validate_success(api.get_report_requirement(rpt["id"], GA), 200)
        assert rpt_after["days_overdue"] == 31
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["posture"] == "FROZEN"
        d1_after = validate_success(api.get_drawdown_request(d1["id"], GA), 200)
        d2_after = validate_success(api.get_drawdown_request(d2["id"], GA), 200)
        assert d1_after["status"] == "CANCELLED"
        assert d2_after["status"] == "CANCELLED"
        assert award_after["reserved_draw_cents"] == 0
        assert award_after["available_draw_pool_cents"] == 150_000


class TestDrawdownPoolConservationAcrossSettleAndReject:
    """Difficulty instance: eligible pool partition invariant across the
    drawdown lifecycle."""

    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "L9-001",
            [
                {"category": "TRAVEL", "authorized_cents": 100_000},
                {"category": "MATERIALS_SUPPLIES", "authorized_cents": 50_000},
                {"category": "EQUIPMENT", "authorized_cents": 200_000},
            ],
            425_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=100_000, cash_disbursed=True)
        post_expenditure(award["id"], lines["MATERIALS_SUPPLIES"]["id"],
                         expenditure_type="SUPPLIES", amount_cents=50_000,
                         cash_disbursed=False)
        post_expenditure(award["id"], lines["EQUIPMENT"]["id"],
                         expenditure_type="EQUIPMENT", amount_cents=200_000,
                         cash_disbursed=True)
        # Eligible pool: cash directs 300000 + round(0.5 * MTDC_cash 100000)
        # = 350000 (equipment contributes no MTDC; undisbursed excluded).
        d1 = create_drawdown(award["id"], 200_000)
        validate_success(api.submit_drawdown(d1["id"], GA), 200)
        return award, d1

    def _draw_fields(self, api, award_id):
        a = validate_success(api.get_award(award_id, GA), 200)
        return (a["cumulative_drawn_cents"], a["reserved_draw_cents"],
                a["available_draw_pool_cents"])

    def test_submit_then_settle_moves_reserved_to_drawn(self, api):
        """PRD §2.8: "Second, on letter-of-credit awards the eligible draw
        pool partitions exactly: `eligible_pool` equals
        `cumulative_drawn_cents` plus `reserved_draw_cents` plus
        `available_draw_pool_cents` at every instant; submitting a draw moves
        amount from available to reserved, settling moves it from reserved to
        drawn, rejecting or cancelling moves it from reserved back to
        available, and posting an expenditure adds the amount plus its F&A
        share to both eligible and available."

        Design: Difficulty/compensating_invariant/drawdown_pool_conservation_across_settle_and_reject
        """
        award, d1 = self._setup(api)
        drawn, res, avail = self._draw_fields(api, award["id"])
        assert (drawn, res, avail) == (0, 200_000, 150_000)
        validate_success(api.settle_drawdown(d1["id"], SO), 200)
        drawn, res, avail = self._draw_fields(api, award["id"])
        assert (drawn, res, avail) == (200_000, 0, 150_000)

    def test_over_pool_submit_fails_and_reject_releases_reservation(self, api):
        """PRD §3.6: "the amount must not exceed `available_draw_pool_cents`
        (`ERR_DRAWDOWN_EXCEEDS_ELIGIBLE`)."
        PRD §2.8: "submitting a draw moves amount from available to reserved,
        settling moves it from reserved to drawn, rejecting or cancelling moves
        it from reserved back to available, and posting an expenditure adds the
        amount plus its F&A share to both eligible and available."

        Design: Difficulty/compensating_invariant/drawdown_pool_conservation_across_settle_and_reject
        """
        award, d1 = self._setup(api)
        validate_success(api.settle_drawdown(d1["id"], SO), 200)
        d2 = create_drawdown(award["id"], 150_001)
        res = api.submit_drawdown(d2["id"], GA)
        validate_error(res, ApiErrorId.ERR_DRAWDOWN_EXCEEDS_ELIGIBLE.value)
        d3 = create_drawdown(award["id"], 150_000)
        validate_success(api.submit_drawdown(d3["id"], GA), 200)
        drawn, res, avail = self._draw_fields(api, award["id"])
        assert (drawn, res, avail) == (200_000, 150_000, 0)
        validate_success(api.reject_drawdown(
            d3["id"], {"reject_reason": "sponsor cash-management review"}, SO), 200)
        drawn, res, avail = self._draw_fields(api, award["id"])
        assert (drawn, res, avail) == (200_000, 0, 150_000)


class TestDrawdownSettleFromDraft:
    def test_settle_from_draft_rejected(self, api):
        """PRD §3.6: "Drawdown actions attempted from the wrong state return
        `ERR_DRAWDOWN_NOT_ACTIONABLE`."

        Design: Corner/state_machines/drawdown_settle_from_draft_rejected
        """
        pi, award, _travel = _setup_pool_award(api, "SM-002")
        d1 = create_drawdown(award["id"], 50_000)
        res = api.settle_drawdown(d1["id"], SO)
        validate_error(res, ApiErrorId.ERR_DRAWDOWN_NOT_ACTIONABLE.value)
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["cumulative_drawn_cents"] == 0
        assert award_after["reserved_draw_cents"] == 0
