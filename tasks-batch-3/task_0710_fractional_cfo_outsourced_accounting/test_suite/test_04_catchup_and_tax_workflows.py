"""Catch-up project revision cycles, tax-handoff fork-join, offboard cascade."""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    create_client, create_active_client, setup_scoped_catchup,
    create_handoff_in_books_review, create_finalized_close,
    make_client_contact_headers,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestCatchupRevisionCycle:
    def test_two_reject_resubmit_loops_revision_rounds_two(self, api):
        """PRD §3.3: "rejecting the work moves it `CLIENT_REVIEW → REVISION` and
        increments `revision_rounds` by one (this is the cycle entry)"
        PRD §3.3: "`revision_rounds` therefore accumulates across however many
        rejection cycles occur."

        Design: Difficulty/non_linear_state_machine/catchup_revision_cycle_round_counter
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        cp = get_success_data(api.create_catchup_project(
            cid, {"months_behind": 3, "quoted_fee_cents": 400000}, CFO))
        cc = make_client_contact_headers(cid)
        get_success_data(api.scope_catchup_project(cp["id"], CFO))
        get_success_data(api.start_catchup_project(cp["id"], BK))
        get_success_data(api.submit_catchup_for_review(cp["id"], BK))
        get_success_data(api.reject_catchup_project(cp["id"], cc))
        get_success_data(api.submit_catchup_for_review(cp["id"], BK))
        get_success_data(api.reject_catchup_project(cp["id"], cc))
        final = get_success_data(api.submit_catchup_for_review(cp["id"], BK))
        assert final["status"] == "CLIENT_REVIEW"
        assert final["revision_rounds"] == 2

    def test_single_reject_increments_revision_rounds_once(self, api):
        """PRD §3.3: "rejecting the work moves it `CLIENT_REVIEW → REVISION` and
        increments `revision_rounds` by one (this is the cycle entry)"

        Design: Difficulty/non_linear_state_machine/catchup_revision_cycle_round_counter
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        cp = get_success_data(api.create_catchup_project(
            cid, {"months_behind": 3, "quoted_fee_cents": 400000}, CFO))
        cc = make_client_contact_headers(cid)
        get_success_data(api.scope_catchup_project(cp["id"], CFO))
        get_success_data(api.start_catchup_project(cp["id"], BK))
        get_success_data(api.submit_catchup_for_review(cp["id"], BK))
        rejected = get_success_data(api.reject_catchup_project(cp["id"], cc))
        assert rejected["status"] == "REVISION"
        assert rejected["revision_rounds"] == 1


class TestTaxHandoffForkJoin:
    def test_books_signoff_alone_does_not_reach_ready(self, api):
        """PRD §3.9: "A `Bookkeeper` signs off the books branch: permitted while the
        handoff is in `BOOKS_REVIEW` or `ADVISORY_REVIEW` and `books_signoff` is
        still false, it sets `books_signoff` to true, and if `advisory_signoff` was
        already true it advances the handoff to `READY`, otherwise it moves the
        handoff to `ADVISORY_REVIEW` to indicate the still-pending branch."

        Design: Difficulty/non_linear_state_machine/tax_handoff_fork_join_both_signoffs
        """
        cid, th_id = create_handoff_in_books_review(tax_year=2025)
        th = get_success_data(api.books_signoff(th_id, BK))
        assert th["books_signoff"] is True
        assert th["advisory_signoff"] is False
        assert th["status"] == "ADVISORY_REVIEW"

    def test_both_signoffs_reach_ready(self, api):
        """PRD §3.9: "The join is therefore reached — `status` becomes `READY` —
        only once both `books_signoff` and `advisory_signoff` are true."

        Design: Difficulty/non_linear_state_machine/tax_handoff_fork_join_both_signoffs
        """
        cid, th_id = create_handoff_in_books_review(tax_year=2025)
        get_success_data(api.books_signoff(th_id, BK))
        th = get_success_data(api.advisory_signoff(th_id, CFO))
        assert th["books_signoff"] is True
        assert th["advisory_signoff"] is True
        assert th["status"] == "READY"


class TestOffboardCascade:
    def test_offboard_cancels_catchup_and_clears_flag(self, api):
        """PRD §3.1: "A successful offboard sets `engagement_status` to `OFFBOARDED`
        and, as a cascade, transitions every one of the client's catch-up projects
        in `DRAFT`, `SCOPED`, `IN_PROGRESS`, `CLIENT_REVIEW`, or `REVISION` to
        `CANCELLED`."
        PRD §3.3: "Reaching `COMPLETED` and reaching `CANCELLED` each clear the
        client's `catchup_active` flag back to false, unless the client still owns
        another catch-up project in `SCOPED` or `IN_PROGRESS` that keeps the flag
        true; in either case the client's `version` is incremented as part of the
        reconciliation, and the scope transition into `SCOPED` likewise increments
        it."

        Design: Difficulty/transitive_cascade/offboard_cancels_catchup_clears_active_flag
        """
        client = create_active_client(retainer_tier="GROWTH")
        cid = client["id"]
        cp = setup_scoped_catchup(cid, months_behind=5, quoted_fee_cents=700000)
        offboarded = get_success_data(api.offboard(cid, CFO))
        assert offboarded["engagement_status"] == "OFFBOARDED"
        project = get_success_data(api.get_catchup_project(cp["id"], CFO))
        assert project["status"] == "CANCELLED"
        client_after = get_success_data(api.get_client(cid, CFO))
        assert client_after["catchup_active"] is False

    def test_offboard_sets_engagement_offboarded(self, api):
        """PRD §3.1: "A successful offboard sets `engagement_status` to
        `OFFBOARDED`"

        Design: Difficulty/transitive_cascade/offboard_cancels_catchup_clears_active_flag
        """
        client = create_active_client(retainer_tier="GROWTH")
        cid = client["id"]
        setup_scoped_catchup(cid)
        offboarded = get_success_data(api.offboard(cid, CFO))
        assert offboarded["engagement_status"] == "OFFBOARDED"


class TestCatchupActiveFlagInvariant:
    def test_scope_then_cancel_restores_flag_false(self, api):
        """PRD §3.3: "Scoping the project — a `CFO` action permitted only from
        `DRAFT` — moves it to `SCOPED` and sets the owning client's `catchup_active`
        flag to true (reconciled per §2.5)."
        PRD §3.3: "A `CFO` may cancel the project from any non-terminal state —
        `DRAFT`, `SCOPED`, `IN_PROGRESS`, `CLIENT_REVIEW`, or `REVISION` — moving it
        to `CANCELLED`."
        PRD §3.3: "Reaching `COMPLETED` and reaching `CANCELLED` each clear the
        client's `catchup_active` flag back to false, unless the client still owns
        another catch-up project in `SCOPED` or `IN_PROGRESS` that keeps the flag
        true; in either case the client's `version` is incremented as part of the
        reconciliation, and the scope transition into `SCOPED` likewise increments
        it."

        Design: Difficulty/compensating_invariant/catchup_active_flag_invariant_scope_then_cancel
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        cp = get_success_data(api.create_catchup_project(
            cid, {"months_behind": 2, "quoted_fee_cents": 300000}, CFO))
        get_success_data(api.scope_catchup_project(cp["id"], CFO))
        before = get_success_data(api.get_client(cid, CFO))
        assert before["catchup_active"] is True
        cancelled = get_success_data(api.cancel_catchup_project(cp["id"], CFO))
        assert cancelled["status"] == "CANCELLED"
        after = get_success_data(api.get_client(cid, CFO))
        assert after["catchup_active"] is False

    def test_scope_sets_flag_true(self, api):
        """PRD §3.3: "Scoping the project — a `CFO` action permitted only from
        `DRAFT` — moves it to `SCOPED` and sets the owning client's `catchup_active`
        flag to true (reconciled per §2.5)."

        Design: Difficulty/compensating_invariant/catchup_active_flag_invariant_scope_then_cancel
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        cp = setup_scoped_catchup(cid, months_behind=2, quoted_fee_cents=300000)
        assert cp["status"] == "SCOPED"
        after = get_success_data(api.get_client(cid, CFO))
        assert after["catchup_active"] is True


class TestTaxHandoffDecemberDependency:
    def test_start_reviews_requires_finalized_december_close(self, api):
        """PRD §3.9: "the client's `MonthlyClose` for the December period — that is,
        for `period_year` equal to `tax_year` and `period_month` 12 — must be
        `FINALIZED`, and a start attempted before that December close is finalized
        is rejected with `ERR_DECEMBER_CLOSE_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/tax_handoff_requires_finalized_december_close
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        # December close exists but is only READY_FOR_REVIEW, not finalized.
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2025, "period_month": 12, "txn_count": 40}, BK))
        task = get_success_data(api.create_close_task(
            close["id"], {"name": "Reconcile", "weight": 1}, BK))
        get_success_data(api.transition_close_task(task["id"], {"to_status": "DONE"}, BK))
        th = get_success_data(api.create_tax_handoff(cid, {"tax_year": 2025}, CFO))
        resp = api.start_tax_reviews(th["id"], CFO)
        validate_error(resp, ApiErrorId.ERR_DECEMBER_CLOSE_NOT_FINAL.value)

    def test_start_reviews_succeeds_after_december_finalized(self, api):
        """PRD §3.9: "Starting the reviews forks the workflow, moving it
        `PREPARING → BOOKS_REVIEW` and opening both review branches at once."

        Design: Difficulty/cross_entity_state_dependency/tax_handoff_requires_finalized_december_close
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        create_finalized_close(
            client_id=cid, period_year=2025, period_month=12, txn_count=40)
        th = get_success_data(api.create_tax_handoff(cid, {"tax_year": 2025}, CFO))
        started = get_success_data(api.start_tax_reviews(th["id"], CFO))
        assert started["status"] == "BOOKS_REVIEW"
