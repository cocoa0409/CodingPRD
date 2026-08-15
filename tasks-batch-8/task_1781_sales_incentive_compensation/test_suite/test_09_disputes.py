"""Disputes: filing guards and their ladder order, the window boundary, the
branching resolution fork with divergent side effects, and role denial."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_CURVE_TIERS,
    TEST_USERS,
    advance_periods,
    assert_dispute,
    book_transaction,
    close_period,
    create_rep,
    file_dispute,
    get_only_credit_entry,
    get_success_data,
    list_adjustments,
    list_disputes,
    make_rep_headers,
    setup_accepted_assignment,
    setup_assignment,
    setup_posted_credit,
    setup_program_with_plan,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]


def _dispute_scenario(api, prefix, amount=200000, **kwargs):
    """Accepted rep with `amount` posted in period 1."""
    return setup_posted_credit(program_name=f"Prog {prefix}",
                               plan_name=f"Plan {prefix}",
                               rep_name=f"Rep {prefix}",
                               employee_ref=f"{prefix}-R1",
                               amount_cents=amount,
                               external_ref=f"{prefix}-T1", **kwargs)


class TestFilingGuards:
    def test_second_active_dispute_rejected_then_allowed(self, api):
        """PRD §3.6: "then the single-active-dispute rule — another dispute of
        the same assignment and period in `SUBMITTED` or `UNDER_REVIEW` blocks
        the filing with `ERR_DISPUTE_ALREADY_ACTIVE`"
        PRD §3.6: "`APPROVED`, `REJECTED`, and `WITHDRAWN` are all terminal."

        Design: Corner/validations/dispute_duplicate_active_rejected
        """
        sc = _dispute_scenario(api, "DA")
        first = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 1,
                             "CREDIT_AMOUNT", 10000)
        assert first["status"] == "SUBMITTED"

        blocked = api.create_dispute(
            {"assignment_id": sc["assignment"]["id"], "period_index": 1,
             "reason": "OTHER", "requested_amount_cents": 5000},
            make_rep_headers(sc["rep"]["id"]))
        validate_error(blocked, ApiErrorId.ERR_DISPUTE_ALREADY_ACTIVE, 409)

        validate_success(api.reject_dispute(first["id"], MANAGER), 200)
        second = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 1,
                              "OTHER", 5000)
        assert_dispute(second)
        assert second["status"] == "SUBMITTED"

    def test_dispute_amount_above_credited_rejected(self, api):
        """PRD §3.6: "and finally the amount — `requested_amount_cents` must be
        positive and no greater than the credited amount for that period,
        computed as the sum of the assignment's `POSTED` and `LOCKED` credits
        whose `posted_period_index` equals the target period
        (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`)."

        Design: Corner/validations/dispute_amount_exceeds_credited_rejected
        """
        sc = _dispute_scenario(api, "DE")  # 200000 credited in period 1
        resp = api.create_dispute(
            {"assignment_id": sc["assignment"]["id"], "period_index": 1,
             "reason": "CREDIT_AMOUNT", "requested_amount_cents": 300000},
            make_rep_headers(sc["rep"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT, 409)

    def test_dispute_credit_entry_mismatch_rejected(self, api):
        """PRD §3.6: "then referential coherence — a supplied `credit_entry_id`
        must belong to the disputed assignment
        (`ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`)"

        Design: Corner/validations/dispute_credit_entry_mismatch_rejected
        """
        sc = setup_program_with_plan(program_name="Prog DM", plan_name="Plan DM")
        rep_a = create_rep(sc["program"]["id"], "DM A", "DM-RA")
        rep_b = create_rep(sc["program"]["id"], "DM B", "DM-RB")
        asg_a = setup_assignment(sc["program"], sc["plan"], rep_a, accept=True)
        setup_assignment(sc["program"], sc["plan"], rep_b, accept=True)
        book_transaction(sc["program"]["id"], "DM-T1", 200000,
                         [{"rep_id": rep_a["id"], "split_bps": 10000}])
        txn_b = book_transaction(sc["program"]["id"], "DM-T2", 300000,
                                 [{"rep_id": rep_b["id"], "split_bps": 10000}])
        foreign_credit = get_only_credit_entry(transaction_id=txn_b["id"],
                                               rep_id=rep_b["id"])

        resp = api.create_dispute(
            {"assignment_id": asg_a["id"], "period_index": 1,
             "credit_entry_id": foreign_credit["id"],
             "reason": "CREDIT_AMOUNT", "requested_amount_cents": 10000},
            make_rep_headers(rep_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_CREDIT_ENTRY_MISMATCH, 409)


class TestResolutionFork:
    def _three_disputes(self, api):
        """D1 approved after review, D2 rejected from SUBMITTED, D3 withdrawn
        from UNDER_REVIEW — sequential, since only one active dispute may
        exist per (assignment, period) at a time."""
        sc = _dispute_scenario(api, "Disp",
                               plan_overrides={"curve_tiers": CANONICAL_CURVE_TIERS})
        rep_id = sc["rep"]["id"]
        asg_id = sc["assignment"]["id"]

        d1 = file_dispute(asg_id, rep_id, 1, "CREDIT_AMOUNT", 30000)
        validate_success(api.start_review_dispute(d1["id"], MANAGER), 200)
        approved = validate_success(
            api.approve_dispute(d1["id"], {"approved_amount_cents": 30000},
                                MANAGER), 200)

        d2 = file_dispute(asg_id, rep_id, 1, "DRAW_ERROR", 20000)
        rejected = validate_success(api.reject_dispute(d2["id"], MANAGER), 200)

        d3 = file_dispute(asg_id, rep_id, 1, "OTHER", 10000)
        validate_success(api.start_review_dispute(d3["id"], MANAGER), 200)
        withdrawn = validate_success(
            api.withdraw_dispute(d3["id"], make_rep_headers(rep_id)), 200)

        return sc, (d1, d2, d3), (approved, rejected, withdrawn)

    def test_dispute_approval_branch_creates_adjustment(self, api):
        """PRD §3.6: "Approval is possible only from `UNDER_REVIEW` and takes
        an `approved_amount_cents` that must be positive and no greater than
        the dispute's `requested_amount_cents`
        (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`); approval sets
        `approved_amount_cents`, moves the dispute to `APPROVED`, and
        immediately creates the compensating adjustment — `source` equal to
        `DISPUTE`, `amount_cents` equal to the approved amount, `status`
        already `APPROVED`, `period_index` set to the current open period, and
        `dispute_id` linking back to the dispute."

        Design: Difficulty/non_linear_state_machine/dispute_branching_fork_with_divergent_side_effects
        """
        _sc, (d1, _d2, _d3), (approved, _r, _w) = self._three_disputes(api)
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 30000

        adjustments = list_adjustments(dispute_id=d1["id"])
        assert len(adjustments) == 1
        adj = adjustments[0]
        assert adj["amount_cents"] == 30000
        assert adj["source"] == "DISPUTE"
        assert adj["status"] == "APPROVED"
        assert adj["period_index"] == 1, "the current open period absorbs it"

    def test_dispute_reject_and_withdraw_branches_create_no_adjustment(self, api):
        """PRD §3.6: "Rejection is available from either `SUBMITTED` or
        `UNDER_REVIEW`, carries an optional `note`, moves the dispute to
        `REJECTED`, and creates no adjustment."
        PRD §3.6: "The owning rep may withdraw their own dispute from either
        `SUBMITTED` or `UNDER_REVIEW` — again with ownership hiding as
        `ERR_NOT_FOUND` — moving it to `WITHDRAWN`, likewise with no
        adjustment."

        Design: Difficulty/non_linear_state_machine/dispute_branching_fork_with_divergent_side_effects
        """
        _sc, (_d1, d2, d3), (_a, rejected, withdrawn) = self._three_disputes(api)
        assert rejected["status"] == "REJECTED"
        assert withdrawn["status"] == "WITHDRAWN"
        assert list_adjustments(dispute_id=d2["id"]) == []
        assert list_adjustments(dispute_id=d3["id"]) == []


class TestWindowBoundary:
    def _window_scenario(self, api):
        """Current period 4: T1 200000 in period 1, T2 300000 in period 2,
        then an empty period 3."""
        sc = setup_accepted_assignment(program_name="Prog Win",
                                       plan_name="Plan W", rep_name="Rep W",
                                       employee_ref="W-R1",
                                       plan_overrides={
                                           "curve_tiers": CANONICAL_CURVE_TIERS})
        pid = sc["program"]["id"]
        book_transaction(pid, "W-T1", 200000,
                         [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])
        close_period(pid)
        book_transaction(pid, "W-T2", 300000,
                         [{"rep_id": sc["rep"]["id"], "split_bps": 10000}],
                         transaction_date="2026-03-01")
        advance_periods(pid, 2)
        program = get_success_data(api.get_program(pid, ADMIN))
        assert program["current_period_index"] == 4
        return sc

    def test_dispute_window_two_periods_back_inclusive(self, api):
        """PRD §3.6: "then the filing window — the target period may be no
        earlier than two periods before the program's current period and no
        later than the current period, anything older or in the future rejected
        with `ERR_DISPUTE_WINDOW_CLOSED`"

        Design: Difficulty/boundary_precision_check/dispute_window_exactly_two_periods_back
        """
        sc = self._window_scenario(api)
        dispute = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 2,
                               "CREDIT_MISSING", 10000)
        assert_dispute(dispute)
        assert dispute["status"] == "SUBMITTED", (
            "distance exactly 2 is the inclusive lower bound of the window"
        )

    def test_dispute_window_three_periods_back_rejected(self, api):
        """PRD §3.6: "then the filing window — the target period may be no
        earlier than two periods before the program's current period and no
        later than the current period, anything older or in the future rejected
        with `ERR_DISPUTE_WINDOW_CLOSED`"

        Design: Difficulty/boundary_precision_check/dispute_window_exactly_two_periods_back
        """
        sc = self._window_scenario(api)
        resp = api.create_dispute(
            {"assignment_id": sc["assignment"]["id"], "period_index": 1,
             "reason": "CREDIT_MISSING", "requested_amount_cents": 10000},
            make_rep_headers(sc["rep"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409)


class TestPriorityPairs:
    def _rejected_dispute(self, api):
        sc = _dispute_scenario(api, "PC1",
                               plan_overrides={"curve_tiers": CANONICAL_CURVE_TIERS})
        dispute = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 1,
                               "CREDIT_AMOUNT", 30000)
        validate_success(api.reject_dispute(dispute["id"], MANAGER), 200)
        return sc, dispute

    def test_approve_rejected_dispute_reports_state_error(self, api):
        """PRD §2.9: "Requests are validated against a fixed ladder of nine
        priority tiers, and the ordering is observable: when a request would
        fail checks in more than one tier, the error returned is always from
        the earliest tier that fails."
        PRD §3.6: "Approval is possible only from `UNDER_REVIEW` and takes an
        `approved_amount_cents` that must be positive and no greater than the
        dispute's `requested_amount_cents`
        (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`)"

        Approving a REJECTED dispute with an amount (50000) above the requested
        bound (30000) violates both the state tier and the money-sanity tier;
        the state tier reports first.

        Design: Difficulty/priority_pair_validation_conflict/dispute_approve_state_vs_fiscal
        """
        _sc, dispute = self._rejected_dispute(api)
        resp = api.approve_dispute(dispute["id"],
                                   {"approved_amount_cents": 50000}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_approve_rejected_dispute_leaves_no_side_effects(self, api):
        """PRD §2.9: "**State preconditions** — the target resource is in a
        valid from-state for the requested transition. Where a dedicated code
        exists it is used — `ERR_PLAN_NOT_PUBLISHED` on assignment creation and
        acceptance, `ERR_TRANSACTION_ALREADY_CANCELLED` on a repeat cancel —
        and all other illegal transitions, including acting on terminal states,
        surface `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/priority_pair_validation_conflict/dispute_approve_state_vs_fiscal
        """
        _sc, dispute = self._rejected_dispute(api)
        resp = api.approve_dispute(dispute["id"],
                                   {"approved_amount_cents": 50000}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_dispute(dispute["id"], ADMIN))
        assert after["status"] == "REJECTED"
        assert list_adjustments(dispute_id=dispute["id"]) == [], (
            "a rejected approval attempt creates no adjustment"
        )

    def _two_rep_window_scenario(self, api):
        """RA (200000 in period 1) and RB (300000 in period 2); current
        period 4; RB's period-2 credit id captured."""
        sc = setup_program_with_plan(program_name="Prog PC2",
                                     plan_name="Plan PC2",
                                     curve_tiers=CANONICAL_CURVE_TIERS)
        rep_a = create_rep(sc["program"]["id"], "Rep PC2A", "PC2-RA")
        rep_b = create_rep(sc["program"]["id"], "Rep PC2B", "PC2-RB")
        asg_a = setup_assignment(sc["program"], sc["plan"], rep_a, accept=True)
        setup_assignment(sc["program"], sc["plan"], rep_b, accept=True)
        pid = sc["program"]["id"]
        book_transaction(pid, "PC2-TA", 200000,
                         [{"rep_id": rep_a["id"], "split_bps": 10000}])
        close_period(pid)
        txn_b = book_transaction(pid, "PC2-TB", 300000,
                                 [{"rep_id": rep_b["id"], "split_bps": 10000}],
                                 transaction_date="2026-03-01")
        credit_b = get_only_credit_entry(transaction_id=txn_b["id"],
                                         rep_id=rep_b["id"])
        advance_periods(pid, 2)
        return sc, rep_a, asg_a, credit_b

    def test_dispute_window_error_precedes_credit_mismatch(self, api):
        """PRD §3.6: "Filing checks fire in ladder order: ownership first; then
        the filing window — the target period may be no earlier than two
        periods before the program's current period and no later than the
        current period, anything older or in the future rejected with
        `ERR_DISPUTE_WINDOW_CLOSED`; then the single-active-dispute rule —
        another dispute of the same assignment and period in `SUBMITTED` or
        `UNDER_REVIEW` blocks the filing with `ERR_DISPUTE_ALREADY_ACTIVE`;
        then referential coherence — a supplied `credit_entry_id` must belong
        to the disputed assignment (`ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`); and
        finally the amount — `requested_amount_cents` must be positive and no
        greater than the credited amount for that period, computed as the sum
        of the assignment's `POSTED` and `LOCKED` credits whose
        `posted_period_index` equals the target period
        (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_create_temporal_vs_referential
        """
        _sc, rep_a, asg_a, credit_b = self._two_rep_window_scenario(api)
        resp = api.create_dispute(
            {"assignment_id": asg_a["id"], "period_index": 1,
             "credit_entry_id": credit_b["id"],
             "reason": "CREDIT_AMOUNT", "requested_amount_cents": 10000},
            make_rep_headers(rep_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409)

    def test_window_violation_creates_no_dispute(self, api):
        """PRD §3.6: "Filing checks fire in ladder order: ownership first; then
        the filing window — the target period may be no earlier than two
        periods before the program's current period and no later than the
        current period, anything older or in the future rejected with
        `ERR_DISPUTE_WINDOW_CLOSED`; then the single-active-dispute rule —
        another dispute of the same assignment and period in `SUBMITTED` or
        `UNDER_REVIEW` blocks the filing with `ERR_DISPUTE_ALREADY_ACTIVE`;
        then referential coherence — a supplied `credit_entry_id` must belong
        to the disputed assignment (`ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`); and
        finally the amount — `requested_amount_cents` must be positive and no
        greater than the credited amount for that period, computed as the sum
        of the assignment's `POSTED` and `LOCKED` credits whose
        `posted_period_index` equals the target period
        (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_create_temporal_vs_referential
        """
        _sc, rep_a, asg_a, credit_b = self._two_rep_window_scenario(api)
        resp = api.create_dispute(
            {"assignment_id": asg_a["id"], "period_index": 1,
             "credit_entry_id": credit_b["id"],
             "reason": "CREDIT_AMOUNT", "requested_amount_cents": 10000},
            make_rep_headers(rep_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409)
        assert list_disputes(assignment_id=asg_a["id"]) == [], (
            "a rejected filing leaves no dispute row behind"
        )


class TestDisputeRbac:
    def test_analyst_cannot_approve_dispute(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_FORBIDDEN_FOR_ROLE`
        error."
        PRD §3.6: "Review is a fork-join managed by a `CompManager`."

        Design: Corner/roles/analyst_cannot_approve_dispute
        """
        sc = _dispute_scenario(api, "AD2")
        dispute = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 1,
                               "CREDIT_AMOUNT", 10000)
        validate_success(api.start_review_dispute(dispute["id"], MANAGER), 200)

        resp = api.approve_dispute(dispute["id"],
                                   {"approved_amount_cents": 10000}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        after = get_success_data(api.get_dispute(dispute["id"], ADMIN))
        assert after["status"] == "UNDER_REVIEW"
