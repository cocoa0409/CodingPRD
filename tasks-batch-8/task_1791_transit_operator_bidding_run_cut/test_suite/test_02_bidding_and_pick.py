"""Seniority ranking, extra-board sizing, bid submission, and adjudication."""
import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate,
    award_run_to_operator,
    create_bid_entry_payload,
    create_operator,
    create_open_period,
    create_period,
    create_period_with_runs,
    create_picking_period,
    create_run,
    create_run_piece,
    cut_period,
    get_operator,
    get_period,
    get_period_version,
    get_run,
    list_bids,
    list_board_slots,
    lock_period,
    make_operator_headers,
    open_picking_period,
    post_period,
    submit_bid,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_operator_payload
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]


class TestSeniorityRank:
    def test_earlier_hire_created_later_takes_rank_one(self, api):
        """PRD §2.8: "The rank is computed over the full roster excluding
        retired operators — operators in `ACTIVE`, `EXTRA_BOARD`, or
        `SUSPENDED` status are eligible — by ordering the eligible operators by
        `hire_date` ascending with ties broken by `employee_number` ascending,
        then taking the 1-based position in that order."

        Design: Difficulty/dual_variant_calc/seniority_rank_two_orderings
        """
        later = create_operator(employee_number="E100", full_name="Later Hire",
                                hire_date="2010-05-01", vacation_hours_balance=100)
        assert later["seniority_rank"] == 1  # only operator on the roster
        earlier = create_operator(employee_number="E200", full_name="Earlier Hire",
                                  hire_date="2005-03-01", vacation_hours_balance=100)
        assert earlier["seniority_rank"] == 1
        assert get_operator(later["id"])["seniority_rank"] == 2

    def test_rank_recomputed_on_roster_change(self, api):
        """PRD §2.8: "The computation is rerun over the entire roster whenever
        an operator is registered, suspended, reinstated, or retired."

        Design: Difficulty/dual_variant_calc/seniority_rank_two_orderings
        """
        first = create_operator(employee_number="E100", full_name="Later Hire",
                                hire_date="2010-05-01", vacation_hours_balance=100)
        second = create_operator(employee_number="E200", full_name="Earlier Hire",
                                 hire_date="2005-03-01", vacation_hours_balance=100)
        # Re-fetch both after the second registration.
        assert get_operator(first["id"])["seniority_rank"] == 2
        assert get_operator(second["id"])["seniority_rank"] == 1

    def test_equal_hire_date_ties_break_by_employee_number(self, api):
        """PRD §2.8: "by ordering the eligible operators by `hire_date`
        ascending with ties broken by `employee_number` ascending, then taking
        the 1-based position in that order."

        Design: Corner/calculations/seniority_tie_break_by_employee_number
        """
        high = create_operator(employee_number="E9", full_name="High Num", hire_date="2000-01-01")
        low = create_operator(employee_number="E1", full_name="Low Num", hire_date="2000-01-01")
        assert low["seniority_rank"] == 1  # E1 < E9
        assert get_operator(high["id"])["seniority_rank"] == 2


class TestExtraBoardSizing:
    def _seven_posted_period(self, api):
        period = create_period(name="B", extra_board_ratio_pct=20)
        for i in range(1, 8):
            create_run(
                period["id"],
                run_number=f"R{i}",
                service_date=f"2026-09-{6 + i:02d}",
                pieces=[create_run_piece(300, 700, 400)],
            )
        return period

    def test_board_slots_ceiling_of_rational_product(self, api):
        """PRD §3.3: "The number of board slots is the count of runs in
        `POSTED` status multiplied by the period's `extra_board_ratio_pct`,
        divided by one hundred, with any fractional result rounded up to the
        next whole number — a ceiling toward positive infinity taken on the
        product before division."

        Design: Difficulty/combinatorial_formula/extra_board_size_ceil_ordering
        """
        period = self._seven_posted_period(api)
        cut_period(period["id"])
        post_period(period["id"])
        slots = list_board_slots(period["id"])
        assert len(slots) == 2, f"ceil(7*20/100) == 2, got {len(slots)}"

    def test_board_slots_indexed_from_one_and_open(self, api):
        """PRD §3.3: "Each slot belongs to the period through its
        `sign_up_period_id`, receives a 1-based `slot_index` — lower positions
        are called out sooner — and begins `OPEN` with its `operator_id` null
        until an operator is demoted onto it."

        Design: Difficulty/combinatorial_formula/extra_board_size_ceil_ordering
        """
        period = self._seven_posted_period(api)
        cut_period(period["id"])
        post_period(period["id"])
        slots = list_board_slots(period["id"])
        indices = sorted(s["slot_index"] for s in slots)
        assert indices == [1, 2]
        for slot in slots:
            assert slot["status"] == "OPEN"
            assert slot["operator_id"] is None
            assert slot["sign_up_period_id"] == period["id"]


class TestBidSubmission:
    def _period_with_withdrawn_run(self, api):
        """PICKING period that also contains a WITHDRAWN run: the over-spread
        run RX (spread 800 > limit 780) is auto-WITHDRAWN at cut-runs and never
        posted, so it is not biddable."""
        period = create_period(name="XD", spread_limit_minutes=780)
        create_run(period["id"], run_number="R0", service_date="2026-09-06",
                   pieces=[create_run_piece(300, 700, 400)])
        withdrawn = create_run(period["id"], run_number="RX", service_date="2026-09-07",
                               pieces=[create_run_piece(0, 800, 400)])
        cut_period(period["id"])
        assert get_run(withdrawn["id"])["status"] == "WITHDRAWN"
        post_period(period["id"])
        open_picking_period(period["id"])
        return period, withdrawn

    def test_bid_on_unposted_run_rejected_not_biddable(self, api):
        """PRD §3.4: "a `run_id` that does not belong to this sign-up period,
        or that is otherwise not biddable, is rejected with
        `ERR_RUN_NOT_BIDDABLE`"
        PRD §3.3: "Posting is the act that makes runs biddable."

        Design: Difficulty/cross_entity_state_dependency/bid_entry_requires_run_posted
        """
        period, withdrawn = self._period_with_withdrawn_run(api)
        operator = create_operator()
        version = get_period_version(period["id"])
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(operator["id"], withdrawn["id"], 1, version),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_BIDDABLE)

    def test_bid_on_unposted_run_creates_nothing(self, api):
        """PRD §3.4: "a `run_id` that does not belong to this sign-up period,
        or that is otherwise not biddable, is rejected with
        `ERR_RUN_NOT_BIDDABLE`"
        PRD §3.3: "Posting is the act that makes runs biddable."

        Design: Difficulty/cross_entity_state_dependency/bid_entry_requires_run_posted
        """
        period, withdrawn = self._period_with_withdrawn_run(api)
        operator = create_operator()
        version = get_period_version(period["id"])
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(operator["id"], withdrawn["id"], 1, version),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_BIDDABLE)
        bids = list_bids(period["id"], operator_id=operator["id"])
        assert bids == [], f"no bid entry should be persisted, got {bids}"

    def test_bid_with_missing_run_reference_rejected(self, api):
        """PRD §2.5: "Foreign keys supplied in a request body (`run_id`,
        `operator_id`, `sign_up_period_id`, and similar references) are
        resolved after the path; a body reference that does not correspond to
        an existing resource is rejected with `ERR_REFERENCE_NOT_FOUND`, also a
        404."

        Design: Corner/endpoints/bid_entry_requires_reference_run_exists
        """
        period, _runs = create_picking_period()
        operator = create_operator()
        version = get_period_version(period["id"])
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(
                operator["id"],
                "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                1,
                version,
            ),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_duplicate_preference_rank_rejected(self, api):
        """PRD §3.4: "a `preference_rank` the operator already holds on a live
        bid in the same period is rejected with `ERR_DUPLICATE_PREFERENCE`"

        Design: Corner/validations/duplicate_preference_rank_rejected
        """
        period, runs = create_picking_period(
            [{"run_number": "R1", "service_date": "2026-09-07"},
             {"run_number": "R2", "service_date": "2026-09-08"}]
        )
        operator = create_operator()
        submit_bid(period["id"], operator["id"], runs[0]["id"], preference_rank=1)
        version = get_period_version(period["id"])
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(operator["id"], runs[1]["id"], 1, version),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PREFERENCE)

    def test_bid_on_locked_period_reports_state_error_not_business_error(self, api):
        """PRD §3.4: "Submission is accepted only while the period is `OPEN` or
        `PICKING`; against any other period state it fails with
        `ERR_INVALID_STATE`. Three further rejections guard submission, in
        order: a `preference_rank` the operator already holds on a live bid in
        the same period is rejected with `ERR_DUPLICATE_PREFERENCE`"
        PRD §2.6: "then whether the target resource's current state permits the
        operation at all (`ERR_INVALID_STATE`, HTTP 409). Only after those
        gates do the endpoint-specific business rules run"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_bid_on_locked_period
        """
        period, runs = create_picking_period()
        operator = create_operator()
        award_run_to_operator(period["id"], operator["id"], runs[0]["id"])
        lock_period(period["id"])
        assert get_period(period["id"])["status"] == "LOCKED"
        version = get_period_version(period["id"])
        # This bid would duplicate preference_rank 1 if business rules ran,
        # but the state gate fires first.
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(operator["id"], runs[0]["id"], 1, version),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_bid_on_locked_period_persists_nothing(self, api):
        """PRD §3.4: "Submission is accepted only while the period is `OPEN` or
        `PICKING`; against any other period state it fails with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_bid_on_locked_period
        """
        period, runs = create_picking_period()
        operator = create_operator()
        award_run_to_operator(period["id"], operator["id"], runs[0]["id"])
        lock_period(period["id"])
        before = list_bids(period["id"], operator_id=operator["id"])
        version = get_period_version(period["id"])
        resp = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(operator["id"], runs[0]["id"], 1, version),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = list_bids(period["id"], operator_id=operator["id"])
        assert len(after) == len(before), "no new BidEntry should be created"

    def test_stale_version_on_bid_submit(self, api):
        """PRD §2.9: "**Submitting a bid entry** requires the non-optional
        field `expected_sign_up_period_version`, carrying the client's last
        observed `version` of the target sign-up period. If the period's
        current `version` has advanced since the client last read it — the
        canonical case being a mid-pick service change that withdrew previously
        posted runs — the submission is rejected with `ERR_STALE_VERSION` (HTTP
        412)"
        PRD §3.4: "Every accepted submission advances the period's `version` —
        which is exactly what lets the next bidder's stale
        `expected_sign_up_period_version` be detected."

        Design: Corner/errors/stale_version_on_bid_submit
        """
        period, runs = create_picking_period()
        op1 = create_operator(employee_number="E1", full_name="Op One", hire_date="2000-01-01")
        op2 = create_operator(employee_number="E2", full_name="Op Two", hire_date="2005-01-01")
        stale_version = get_period_version(period["id"])
        # First bid at this version succeeds and advances the period version.
        resp1 = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(op1["id"], runs[0]["id"], 1, stale_version),
            make_operator_headers(op1["id"]),
        )
        validate_success(resp1, expected_status=201)
        # Second bid reusing the pre-first-bid version is stale.
        resp2 = api.create_bid_entry(
            period["id"],
            create_bid_entry_payload(op2["id"], runs[0]["id"], 1, stale_version),
            make_operator_headers(op2["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)


class TestAdjudication:
    def _two_operators_one_run(self, api):
        """PICKING period with one POSTED run; senior (rank 1) and junior
        (rank 2) both bid it at preference 1. The default 20% board ratio
        still yields exactly one slot: PRD §3.3 rounds the product up, so
        ceil(1 x 20 / 100) = 1."""
        period, runs = create_picking_period()
        run = runs[0]
        senior = create_operator(employee_number="E1", full_name="Senior", hire_date="2000-01-01")
        junior = create_operator(employee_number="E2", full_name="Junior", hire_date="2005-01-01")
        submit_bid(period["id"], senior["id"], run["id"], preference_rank=1)
        submit_bid(period["id"], junior["id"], run["id"], preference_rank=1)
        return period, run, senior, junior

    def test_award_visible_immediately_after_adjudication(self, api):
        """PRD §3.4: "That operator's sheet is walked in preference order: the
        `SUBMITTED` entry with the smallest `preference_rank` whose run is
        still `POSTED` is awarded — the entry moves from `SUBMITTED` to
        `AWARDED`, and its run moves from `POSTED` to `AWARDED` with
        `awarded_operator_id` set to the operator"

        Design: Corner/consistency_model/immediate_consistency_on_award
        """
        period, runs = create_picking_period()
        operator = create_operator()
        submit_bid(period["id"], operator["id"], runs[0]["id"], preference_rank=1)
        adjudicate(period["id"])
        run = get_run(runs[0]["id"])
        assert run["status"] == "AWARDED"
        assert run["awarded_operator_id"] == operator["id"]

    def test_award_marks_bid_and_run_in_same_step(self, api):
        """PRD §3.4: "the entry moves from `SUBMITTED` to `AWARDED`, and its
        run moves from `POSTED` to `AWARDED` with `awarded_operator_id` set to
        the operator — while every other `SUBMITTED` entry of that operator
        moves to `PASSED`."

        Design: Corner/consistency_model/immediate_consistency_on_award
        """
        period, runs = create_picking_period()
        operator = create_operator()
        bid = submit_bid(period["id"], operator["id"], runs[0]["id"], preference_rank=1)
        adjudicate(period["id"])
        bids = list_bids(period["id"], operator_id=operator["id"])
        by_id = {b["id"]: b for b in bids}
        assert by_id[bid["id"]]["status"] == "AWARDED"

    def test_bidless_operator_demoted_to_extra_board(self, api):
        """PRD §3.4: "When none of the operator's remaining bids reference a
        `POSTED` run, all of them pass and the operator is demoted to the extra
        board: their status becomes `EXTRA_BOARD`, the `OPEN` board slot with
        the lowest `slot_index` moves to `FILLED` with its `operator_id` set,
        and the operator's `board_position` takes that slot's `slot_index`."

        Design: Corner/state_machines/adjudicate_next_demotes_bidless_operator_to_board
        """
        period, run, senior, junior = self._two_operators_one_run(api)
        adjudicate(period["id"])  # senior wins the run
        adjudicate(period["id"])  # junior's only bid passes -> demoted
        junior_after = get_operator(junior["id"])
        assert junior_after["status"] == "EXTRA_BOARD"
        assert junior_after["board_position"] == 1
        slots = list_board_slots(period["id"])
        filled = [s for s in slots if s["status"] == "FILLED"]
        assert len(filled) == 1
        assert filled[0]["operator_id"] == junior["id"]
        assert filled[0]["slot_index"] == 1

    def test_demoted_operators_bids_all_passed(self, api):
        """PRD §3.4: "When none of the operator's remaining bids reference a
        `POSTED` run, all of them pass and the operator is demoted to the extra
        board"

        Design: Corner/state_machines/adjudicate_next_demotes_bidless_operator_to_board
        """
        period, run, senior, junior = self._two_operators_one_run(api)
        adjudicate(period["id"])
        adjudicate(period["id"])
        junior_bids = list_bids(period["id"], operator_id=junior["id"])
        assert len(junior_bids) == 1
        assert junior_bids[0]["status"] == "PASSED"


class TestSuspendCascade:
    def test_suspend_withdraws_submitted_bids(self, api):
        """PRD §3.1: "Suspending an operator cascades: every `SUBMITTED` bid
        entry of that operator in any `OPEN` or `PICKING` sign-up period
        transitions to `WITHDRAWN`."

        Design: Corner/state_machines/operator_suspend_withdraws_submitted_bids
        """
        period, runs = create_picking_period()
        operator = create_operator()
        bid = submit_bid(period["id"], operator["id"], runs[0]["id"], preference_rank=1)
        resp = api.suspend_operator(operator["id"], SO)
        suspended = validate_success(resp)
        assert suspended["status"] == "SUSPENDED"
        bids = list_bids(period["id"], operator_id=operator["id"])
        by_id = {b["id"]: b for b in bids}
        assert by_id[bid["id"]]["status"] == "WITHDRAWN"
