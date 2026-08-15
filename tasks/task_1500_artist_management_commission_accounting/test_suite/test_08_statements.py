"""Statement production: basis variants, pinned per-event rounding, the carry
chain, the disbursement threshold, period overlap arithmetic, conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_statement,
    assert_statement_conservation,
    create_and_verify_event,
    create_approved_expense,
    generate_and_issue_statement,
    generate_statement,
    get_success_data,
    issue_statement,
    setup_artist_team,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]


def _setup_accrual_cash_pair(api):
    """Two artists with byte-identical data: one TOURING event gross 200000
    recognized 2026-03-28, VERIFIED; the ACCRUAL artist's Q1 issued under
    ACCRUAL, the CASH artist's Q1 issued under CASH; then both events settle
    with received_date 2026-04-02."""
    pair = {}
    for key, basis in (("acc", "ACCRUAL"), ("csh", "CASH")):
        sc = setup_artist_team(stage_name=f"{key.title()} Act")
        event = create_and_verify_event(sc, gross_amount_cents=200000,
                                        recognition_date="2026-03-28",
                                        source_name="Promoter X")
        q1 = generate_and_issue_statement(sc, "2026-01-01", "2026-03-31", basis)
        pair[key] = {"sc": sc, "event": event, "q1": q1}
    # Settle both after the Q1 issues: the ACCRUAL artist's event latches POSTED.
    for key in ("acc", "csh"):
        pair[key]["event"] = get_success_data(api.settle_income_event(
            pair[key]["event"]["id"],
            {"received_date": "2026-04-02", "received_amount_cents": 200000},
            pair[key]["sc"]["bm_headers"]))
    return pair


class TestStatementBasisVariants:
    def test_accrual_q1_includes_verified_event(self, api):
        """PRD: "under `ACCRUAL`, events in `VERIFIED` or `SETTLED` whose
        `recognition_date` falls inside the period; under `CASH`, only `SETTLED`
        events whose `received_date` falls inside the period."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_period_inclusion
        """
        sc_acc = setup_artist_team(stage_name="Acc Act")
        event_acc = create_and_verify_event(sc_acc, gross_amount_cents=200000,
                                            recognition_date="2026-03-28",
                                            source_name="Promoter X")
        q1_acc = generate_and_issue_statement(sc_acc, "2026-01-01", "2026-03-31",
                                              "ACCRUAL")
        assert q1_acc["gross_total_cents"] == 200000
        assert q1_acc["commission_total_cents"] == 30000
        assert q1_acc["income_net_total_cents"] == 170000
        assert q1_acc["net_payable_cents"] == 170000
        assert_statement_conservation(q1_acc)
        posted = get_success_data(api.get_income_event(event_acc["id"], ADMIN))
        assert posted["status"] == "POSTED"
        assert posted["statement_id"] == q1_acc["id"]

        sc_csh = setup_artist_team(stage_name="Csh Act")
        create_and_verify_event(sc_csh, gross_amount_cents=200000,
                                recognition_date="2026-03-28",
                                source_name="Promoter X")
        q1_csh = generate_and_issue_statement(sc_csh, "2026-01-01", "2026-03-31",
                                              "CASH")
        assert q1_csh["gross_total_cents"] == 0, (
            "The same event, still unsettled inside Q1, is excluded under CASH"
        )
        assert q1_csh["net_payable_cents"] == 0

    def test_cash_april_surfaces_event_accrual_april_empty(self, api):
        """PRD: "an event recognized in one period but settled in the next appears
        on the earlier period's `ACCRUAL` statement but on the later period's
        `CASH` statement, so identical underlying data yields different
        `gross_total_cents`, `commission_total_cents`, and `net_payable_cents`
        between the two bases."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_period_inclusion
        """
        pair = _setup_accrual_cash_pair(api)

        apr_acc = generate_statement(pair["acc"]["sc"], "2026-04-01", "2026-04-30",
                                     "ACCRUAL")
        assert apr_acc["income_net_total_cents"] == 0, (
            "The event was already posted on Q1; its statement_id is set"
        )
        assert apr_acc["gross_total_cents"] == 0

        apr_csh = generate_statement(pair["csh"]["sc"], "2026-04-01", "2026-04-30",
                                     "CASH")
        assert apr_csh["gross_total_cents"] == 200000
        assert apr_csh["commission_total_cents"] == 30000
        assert apr_csh["income_net_total_cents"] == 170000, (
            "Identical inputs surface a month later under CASH"
        )
        assert apr_csh["net_payable_cents"] == 170000

        assert pair["acc"]["q1"]["net_payable_cents"] == 170000
        assert pair["csh"]["q1"]["net_payable_cents"] == 0


class TestPinnedPerEventRounding:
    def _setup_two_publishing_events(self, api):
        """Two PUBLISHING events gross 33333 each @2500bps, both VERIFIED."""
        sc = setup_artist_team(stage_name="Round Act", primary_genre="folk",
                                   income_types=("PUBLISHING",))
        ev1 = create_and_verify_event(sc, gross_amount_cents=33333,
                                      recognition_date="2026-02-05",
                                      income_type="PUBLISHING", source_name="PRO One")
        ev2 = create_and_verify_event(sc, gross_amount_cents=33333,
                                      recognition_date="2026-02-12",
                                      income_type="PUBLISHING", source_name="PRO Two")
        return sc, ev1, ev2

    def test_per_event_rounding_pins_8333(self, api):
        """PRD: "Commissions are computed per income event at verification time
        and rounded half up to whole cents at that moment; statements sum the
        pinned per-event values and never re-round or re-derive them."

        Design: Difficulty/combinatorial_formula/statement_commission_rounding_mode_b
        """
        _sc, ev1, ev2 = self._setup_two_publishing_events(api)
        assert ev1["commission_amount_cents"] == 8333, (
            "Per-event round_half_up of 8333.25 rounds down to 8333"
        )
        assert ev2["commission_amount_cents"] == 8333
        assert ev1["artist_net_cents"] == 25000
        assert ev2["artist_net_cents"] == 25000

    def test_statement_sums_pinned_commissions(self, api):
        """PRD: "commissions were already rounded per event at verify; the
        statement never re-rounds or re-derives them"
        PRD: "`gross_total_cents`, `commission_total_cents`, and
        `income_net_total_cents` sum the gross, commission, and net components of
        the income lines"

        Design: Difficulty/combinatorial_formula/statement_commission_rounding_mode_b
        """
        sc, _ev1, _ev2 = self._setup_two_publishing_events(api)
        statement = generate_statement(sc, "2026-02-01", "2026-02-28", "ACCRUAL")
        assert statement["gross_total_cents"] == 66666
        assert statement["commission_total_cents"] == 16666, (
            "Sum of pinned per-event values (8333 + 8333); the forbidden "
            "sum-then-round order would yield 16667"
        )
        assert statement["income_net_total_cents"] == 50000
        assert statement["net_payable_cents"] == 50000
        assert statement["disbursed_cents"] == 50000
        assert statement["carry_out_cents"] == 0
        assert_statement_conservation(statement)


def _setup_carry_chain_p1(api, stage_name="Carry Act"):
    """P1 [2026-01-01..2026-03-31] ACCRUAL: VERIFIED event 200000 (net 170000)
    plus APPROVED expense 150000 incurred 2026-02-10; P1 issued."""
    sc = setup_artist_team(stage_name=stage_name, bm_cap=500000)
    ev1 = create_and_verify_event(sc, gross_amount_cents=200000,
                                  recognition_date="2026-03-10",
                                  source_name="Promoter C1")
    expense = create_approved_expense(sc, 150000, category="PRODUCTION",
                                      incurred_date="2026-02-10",
                                      description="Stage build")
    assert expense["status"] == "APPROVED"
    p1 = generate_and_issue_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
    return sc, ev1, expense, p1


class TestCarryChainEvaluationOrder:
    def test_p1_below_threshold_carries(self, api):
        """PRD: "A disbursement threshold of 50000 cents ($500) then splits the
        outcome: when `net_payable_cents` is at least the threshold,
        `disbursed_cents` equals the net payable and `carry_out_cents` is 0; when
        it is positive but below the threshold, nothing is disbursed and the
        whole amount carries forward"

        Design: Difficulty/combinatorial_formula/carry_chain_mode_c_evaluation_order
        """
        _sc, _ev1, expense, p1 = _setup_carry_chain_p1(api)
        assert p1["income_net_total_cents"] == 170000
        assert p1["expense_total_cents"] == 150000
        assert p1["net_payable_cents"] == 20000
        assert p1["disbursed_cents"] == 0, "20000 is strictly below the threshold"
        assert p1["carry_out_cents"] == 20000
        assert_statement_conservation(p1)
        swept = get_success_data(api.get_expense(expense["id"], ADMIN))
        assert swept["status"] == "REIMBURSED"
        assert swept["reimbursed_statement_id"] == p1["id"]

    def test_p2_carry_in_lifts_over_threshold(self, api):
        """PRD: "Fifth, `carry_in_cents` is the `carry_out_cents` of the prior
        statement in the chain — recorded on the new statement as
        `prior_statement_id`, the latest non-`DISCARDED` statement of the artist
        ending before this period starts — or zero for the artist's first
        statement."
        PRD: "The bottom line is `net_payable_cents`: income net total minus
        expense total minus recoup total plus adjustment total plus carry-in."

        Design: Difficulty/combinatorial_formula/carry_chain_mode_c_evaluation_order
        """
        sc, _ev1, _expense, p1 = _setup_carry_chain_p1(api)
        ev2 = create_and_verify_event(sc, gross_amount_cents=100000,
                                      recognition_date="2026-05-10",
                                      source_name="Promoter C2")
        assert ev2["artist_net_cents"] == 85000

        p2 = generate_statement(sc, "2026-04-01", "2026-06-30", "ACCRUAL")
        assert p2["prior_statement_id"] == p1["id"]
        assert p2["carry_in_cents"] == 20000, "Read from P1's carry_out at generation"
        assert p2["income_net_total_cents"] == 85000
        assert p2["net_payable_cents"] == 105000, (
            "The 20000 carry_in is applied BEFORE the threshold comparison"
        )
        assert p2["disbursed_cents"] == 105000
        assert p2["carry_out_cents"] == 0
        assert_statement_conservation(p2)


class TestDisbursementThresholdBoundary:
    def _setup_single_event_artist(self, api, stage_name, gross):
        sc = setup_artist_team(stage_name=stage_name, primary_genre="folk",
                                   income_types=("PUBLISHING",))
        event = create_and_verify_event(sc, gross_amount_cents=gross,
                                        recognition_date="2026-02-05",
                                        income_type="PUBLISHING", source_name="PRO")
        return sc, event

    def test_below_disbursement_threshold_carries(self, api):
        """PRD: "when it is positive but below the threshold, nothing is
        disbursed and the whole amount carries forward"

        Design: Difficulty/boundary_precision_check/statement_disbursement_threshold_exact
        """
        sc, event = self._setup_single_event_artist(api, "Low Act", 66666)
        assert event["commission_amount_cents"] == 16667, (
            "round_half_up(16666.5)"
        )
        statement = generate_statement(sc, "2026-02-01", "2026-02-28", "ACCRUAL")
        assert statement["net_payable_cents"] == 49999
        assert statement["disbursed_cents"] == 0
        assert statement["carry_out_cents"] == 49999
        assert_statement_conservation(statement)

    def test_at_disbursement_threshold_disburses(self, api):
        """PRD: "when `net_payable_cents` is at least the threshold,
        `disbursed_cents` equals the net payable and `carry_out_cents` is 0"

        Design: Difficulty/boundary_precision_check/statement_disbursement_threshold_exact
        """
        sc, event = self._setup_single_event_artist(api, "Exact Act", 66667)
        assert event["commission_amount_cents"] == 16667, (
            "round_half_up(16666.75)"
        )
        statement = generate_statement(sc, "2026-02-01", "2026-02-28", "ACCRUAL")
        assert statement["net_payable_cents"] == 50000
        assert statement["disbursed_cents"] == 50000, (
            "The boundary uses >=, so exactly 50000 disburses"
        )
        assert statement["carry_out_cents"] == 0
        assert_statement_conservation(statement)


class TestStatementPeriodOverlap:
    def _setup_issued_empty_p1(self, api, stage_name="Per Act"):
        sc = setup_artist_team(stage_name=stage_name, with_agent=False)
        p1 = generate_and_issue_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
        return sc, p1

    def test_period_sharing_boundary_day_rejected(self, api):
        """PRD: "a new period starting exactly on the previous period's end date
        IS an overlap, and the tightest legal successor starts the day after
        (`ERR_STATEMENT_PERIOD_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/statement_period_closed_interval_no_touch
        """
        sc, _p1 = self._setup_issued_empty_p1(api)
        resp = api.generate_statement(
            {"artist_id": sc["artist"]["id"], "period_start_date": "2026-03-31",
             "period_end_date": "2026-06-30", "basis": "ACCRUAL"},
            sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)

    def test_day_after_successor_allowed(self, api):
        """PRD: "a new period starting exactly on the previous period's end date
        IS an overlap, and the tightest legal successor starts the day after
        (`ERR_STATEMENT_PERIOD_OVERLAP`)"
        PRD: "Fifth, `carry_in_cents` is the `carry_out_cents` of the prior
        statement in the chain — recorded on the new statement as
        `prior_statement_id`"

        Design: Difficulty/resource_temporal_overlap/statement_period_closed_interval_no_touch
        """
        sc, p1 = self._setup_issued_empty_p1(api, "Per Act 2")
        p2 = validate_success(api.generate_statement(
            {"artist_id": sc["artist"]["id"], "period_start_date": "2026-04-01",
             "period_end_date": "2026-06-30", "basis": "ACCRUAL"},
            sc["bm_headers"]), 201)
        assert_statement(p2)
        assert p2["prior_statement_id"] == p1["id"]
        assert p2["carry_in_cents"] == 0


class TestDisburseCarryConservation:
    def test_conservation_across_statement_lifecycle(self, api):
        """PRD: "One invariant holds after every generation, amendment, and
        disbursement: `disbursed_cents` plus `carry_out_cents` always equals
        `net_payable_cents`."
        PRD: "A `BusinessManager` disburses an `ACKNOWLEDGED` statement, moving it
        to the terminal `FINALIZED` state: the pinned `disbursed_cents` is paid
        out, the artist's `lifetime_disbursed_cents` increases by that amount"
        PRD: "every swept income event moves to `POSTED` with `statement_id`
        recorded, every swept expense moves to `REIMBURSED`"

        Design: Difficulty/compensating_invariant/statement_disburse_carry_conservation
        """
        sc = setup_artist_team(stage_name="Conserve Act", bm_cap=500000)
        ev1 = create_and_verify_event(sc, gross_amount_cents=200000,
                                      recognition_date="2026-03-10",
                                      source_name="Promoter Co1")
        expense = create_approved_expense(sc, 150000, category="PRODUCTION",
                                          incurred_date="2026-02-10",
                                          description="Stage build")
        p1 = generate_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
        assert_statement_conservation(p1)  # DRAFT: 0 + 20000 == 20000
        assert p1["disbursed_cents"] == 0
        assert p1["carry_out_cents"] == 20000

        issued = issue_statement(sc, p1["id"])
        assert_statement_conservation(issued)  # ISSUED: totals frozen
        posted = get_success_data(api.get_income_event(ev1["id"], ADMIN))
        assert posted["status"] == "POSTED"
        assert posted["statement_id"] == p1["id"]
        swept_expense = get_success_data(api.get_expense(expense["id"], ADMIN))
        assert swept_expense["status"] == "REIMBURSED"
        assert swept_expense["reimbursed_statement_id"] == p1["id"]

        get_success_data(api.acknowledge_statement(p1["id"], sc["artist_headers"]))
        finalized = validate_success(api.disburse_statement(p1["id"],
                                                            sc["bm_headers"]))
        assert finalized["status"] == "FINALIZED"
        assert_statement_conservation(finalized)
        artist = get_success_data(api.get_artist(sc["artist"]["id"], ADMIN))
        assert artist["lifetime_disbursed_cents"] == 0, (
            "A below-threshold statement disburses nothing"
        )

    def test_second_statement_inherits_carry_and_conserves(self, api):
        """PRD: "One invariant holds after every generation, amendment, and
        disbursement: `disbursed_cents` plus `carry_out_cents` always equals
        `net_payable_cents`."
        PRD: "Fifth, `carry_in_cents` is the `carry_out_cents` of the prior
        statement in the chain"

        Design: Difficulty/compensating_invariant/statement_disburse_carry_conservation
        """
        sc = setup_artist_team(stage_name="Conserve Act 2", bm_cap=500000)
        create_and_verify_event(sc, gross_amount_cents=200000,
                                recognition_date="2026-03-10",
                                source_name="Promoter Co1")
        create_approved_expense(sc, 150000, category="PRODUCTION",
                                incurred_date="2026-02-10", description="Stage build")
        p1 = generate_and_issue_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
        get_success_data(api.acknowledge_statement(p1["id"], sc["artist_headers"]))
        get_success_data(api.disburse_statement(p1["id"], sc["bm_headers"]))
        create_and_verify_event(sc, gross_amount_cents=100000,
                                recognition_date="2026-05-10",
                                source_name="Promoter Co2")

        p2 = generate_statement(sc, "2026-04-01", "2026-06-30", "ACCRUAL")
        assert p2["carry_in_cents"] == 20000
        assert p2["income_net_total_cents"] == 85000
        assert p2["net_payable_cents"] == 105000
        assert p2["disbursed_cents"] == 105000
        assert p2["carry_out_cents"] == 0
        assert_statement_conservation(p2)


class TestStatementLinesAndGenerationGates:
    def test_statement_line_is_append_only_without_version(self, api):
        """PRD: "`StatementLine` is the sole exception: statement lines carry only
        `id` and `created_at`; both `updated_at` and `version` are absent,
        because lines are append-only and never mutated after creation."
        PRD: "Each income line's `amount_cents` is the event's `artist_net_cents`,
        and its `commission_cents` is the event's pinned `commission_amount_cents`"

        Design: Corner/entities/statement_line_is_append_only_without_version
        """
        sc = setup_artist_team(stage_name="Line Act")
        event = create_and_verify_event(sc, gross_amount_cents=200000,
                                        recognition_date="2026-03-10",
                                        source_name="PLn")
        statement = generate_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
        lines, meta = validate_paginated(
            api.list_statement_lines(statement["id"], sc["bm_headers"]))
        assert meta["total_count"] == 1
        line = lines[0]
        assert line["line_type"] == "INCOME"
        assert line["ref_id"] == event["id"]
        assert line["amount_cents"] == 170000
        assert line["commission_cents"] == 30000
        assert "updated_at" not in line
        assert "version" not in line
        assert line["id"]
        assert line["created_at"]

    def test_statement_generate_future_period_rejected(self, api):
        """PRD: "The period is a closed interval: the end must be on or after the
        start (a malformed window fails with `ERR_INVALID_REQUEST`) and may not
        lie after the clock date (`ERR_STATEMENT_PERIOD_FUTURE`)"

        Design: Corner/validations/statement_generate_future_period_rejected
        """
        sc = setup_artist_team(stage_name="Fut Act", with_agent=False)
        resp = api.generate_statement(
            {"artist_id": sc["artist"]["id"], "period_start_date": "2026-08-01",
             "period_end_date": "2026-09-30", "basis": "ACCRUAL"},
            sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_FUTURE)
        _data, meta = validate_paginated(
            api.list_statements(ADMIN, params={"artist_id": sc["artist"]["id"]}))
        assert meta["total_count"] == 0, "No statement may be persisted"

    def test_generate_blocked_while_prior_statement_draft(self, api):
        """PRD: "The carry chain also demands closure: the immediately preceding
        statement — the latest non-`DISCARDED` one whose `period_end_date` falls
        before the new start — must not still be `DRAFT`
        (`ERR_PRIOR_STATEMENT_OPEN`)."
        PRD: "discarded statements drop out of the overlap and carry-chain
        arithmetic entirely."

        Design: Corner/validations/generate_blocked_while_prior_statement_draft
        """
        sc = setup_artist_team(stage_name="Seq Act", with_agent=False)
        p1 = generate_statement(sc, "2026-01-01", "2026-03-31", "ACCRUAL")
        assert p1["status"] == "DRAFT"

        resp = api.generate_statement(
            {"artist_id": sc["artist"]["id"], "period_start_date": "2026-04-01",
             "period_end_date": "2026-06-30", "basis": "ACCRUAL"},
            sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_PRIOR_STATEMENT_OPEN)

        get_success_data(api.discard_statement(p1["id"], sc["bm_headers"]))
        p2 = validate_success(api.generate_statement(
            {"artist_id": sc["artist"]["id"], "period_start_date": "2026-04-01",
             "period_end_date": "2026-06-30", "basis": "ACCRUAL"},
            sc["bm_headers"]), 201)
        assert p2["prior_statement_id"] is None, (
            "The DISCARDED P1 is skipped by the carry chain"
        )
        assert p2["carry_in_cents"] == 0
