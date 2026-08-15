"""Recoupment waterfall, the finalize cascade, amendment reversal, writer
balance rollups, the earnings summary, and amendment-target gating."""
from test_helpers import (
    ApiErrorId,
    assert_advance_principal_invariant,
    create_licensee,
    create_paid_advance,
    create_statement,
    get_work,
    get_writer,
    list_allocation_lines,
    run_statement_pipeline,
    set_clock,
    setup_finalized_statement,
    setup_registered_work,
    statement_line,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, Q1_2026, Q2_2026


def _waterfall_scenario(api):
    """Writer W with PAID advances A1 (3000 @ 10000 bp, paid first) and A2
    (2000 @ 5000 bp, paid one logical day later); REGISTERED work; licensee."""
    ctx = setup_registered_work(title="Waterfall Song")
    writer_id = ctx["writers"][0]["id"]
    a1 = create_paid_advance(writer_id, 3000, recoup_rate_bp=10000,
                             agreement_ref="A1")
    set_clock("2026-08-02T00:00:00Z")
    a2 = create_paid_advance(writer_id, 2000, recoup_rate_bp=5000,
                             agreement_ref="A2")
    licensee = create_licensee()
    ctx.update({"a1": a1, "a2": a2, "licensee": licensee})
    return ctx


def _finalize_statement(api, ctx, title, gross, period):
    statement = create_statement(
        ctx["licensee"]["id"],
        [statement_line(1, title, gross,
                        work_code=ctx["work"]["work_code"])],
        gross, period=period)
    return run_statement_pipeline(statement["id"], through="FINALIZED")


class TestRecoupmentWaterfallMultifactor:
    def test_waterfall_first_statement_hits_earliest_advance(self, api):
        """PRD §3.7: "Starting from the row's `final_amount_cents` as the remaining balance, the server walks the writer's advances that are `PAID` or `RECOUPING`, in ascending `paid_at` order with ties broken by ascending advance `created_at`."

        Design: Difficulty/combinatorial_formula/recoupment_waterfall_multifactor_chain
        """
        ctx = _waterfall_scenario(api)
        _finalize_statement(api, ctx, "Waterfall Song", 2000, Q1_2026)

        a1 = validate_success(api.get_advance(ctx["a1"]["id"], ADMIN))
        # Writer final is 1000; budget floor(1000 * 10000/10000) = 1000,
        # applied min(1000, 3000) = 1000, all to the earliest-paid advance.
        assert a1["status"] == "RECOUPING"
        assert a1["recouped_cents"] == 1000
        assert a1["outstanding_cents"] == 2000
        assert_advance_principal_invariant(a1)

        a2 = validate_success(api.get_advance(ctx["a2"]["id"], ADMIN))
        assert a2["status"] == "PAID", "A2 is untouched while A1 absorbs all"
        assert a2["recouped_cents"] == 0
        assert a2["outstanding_cents"] == 2000

    def test_waterfall_min_of_budget_and_outstanding(self, api):
        """PRD §3.7: "At each advance, the recoupment budget is the remaining balance multiplied by the advance's `recoup_rate_bp` and divided by 10000, rounded down; the amount actually applied is the smaller of that budget and the advance's `outstanding_cents`."
        PRD §3.7: "a `RECOUPING` advance whose `outstanding_cents` reaches exactly zero moves to terminal `RECOUPED`, with the writer's `advance_outstanding_cents` recomputed on each such transition."

        Design: Difficulty/combinatorial_formula/recoupment_waterfall_multifactor_chain
        """
        ctx = _waterfall_scenario(api)
        _finalize_statement(api, ctx, "Waterfall Song", 2000, Q1_2026)
        _finalize_statement(api, ctx, "Waterfall Song Q2", 5000, Q2_2026)

        # Second statement: writer final 2500. A1 budget 2500, applied
        # min(2500, 2000) = 2000 -> exact-zero crossing to RECOUPED.
        a1 = validate_success(api.get_advance(ctx["a1"]["id"], ADMIN))
        assert a1["status"] == "RECOUPED"
        assert a1["recouped_cents"] == 3000
        assert a1["outstanding_cents"] == 0
        assert_advance_principal_invariant(a1)

        # Remaining 500 reaches A2: budget floor(500 * 5000/10000) = 250, NOT
        # the full 500.
        a2 = validate_success(api.get_advance(ctx["a2"]["id"], ADMIN))
        assert a2["status"] == "RECOUPING"
        assert a2["recouped_cents"] == 250
        assert a2["outstanding_cents"] == 1750
        assert_advance_principal_invariant(a2)

        writer = get_writer(ctx["writers"][0]["id"])
        assert writer["payable_balance_cents"] == 250
        assert writer["advance_outstanding_cents"] == 1750


class TestFinalizeCascade:
    def test_finalize_mutates_allocation_and_advance(self, api):
        """PRD §3.5: "The same retention and pool-split machinery as above then produces each allocation row's `final_amount_cents`, and every row moves from `PROVISIONAL` to `FINAL`. Because the two variants treat unmatched income differently, identical statement data yields different per-writer amounts at the two stages; `allocated_total_cents` is recomputed as the sum of the final amounts, and `retained_cents` is recomputed as well. For each `WRITER` allocation row, the recoupment waterfall of §3.7 then runs against the writer's outstanding advances, determining `advance_applied_cents` and `net_payable_cents`, and the writer's `payable_balance_cents` is credited with the net."
        PRD §3.7: "a `RECOUPING` advance whose `outstanding_cents` reaches exactly zero moves to terminal `RECOUPED`"

        Design: Difficulty/transitive_cascade/statement_finalize_recoupment_chain
        """
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        advances=((1000, None),),
                                        title="Cascade Song")
        statement = ctx["statement"]
        assert statement["status"] == "FINALIZED"

        writer_rows = list_allocation_lines(
            statement_id=statement["id"],
            writer_id=ctx["writers"][0]["id"])
        assert len(writer_rows) == 1
        row = writer_rows[0]
        assert row["status"] == "FINAL"
        assert row["final_amount_cents"] == 1000
        assert row["advance_applied_cents"] == 1000
        assert row["net_payable_cents"] == 0

        advance = validate_success(
            api.get_advance(ctx["advances"][0]["id"], ADMIN))
        assert advance["status"] == "RECOUPED", (
            "the exact-zero crossing auto-transitions RECOUPING -> RECOUPED")
        assert advance["recouped_cents"] == 1000
        assert advance["outstanding_cents"] == 0
        assert_advance_principal_invariant(advance)

    def test_finalize_recomputes_writer_and_work_rollups(self, api):
        """PRD §3.5: "Each affected writer's `advance_outstanding_cents` and `lifetime_earned_cents` are recomputed and their `version` incremented; each matched work's `total_collected_cents` is recomputed."
        PRD §3.7: "`lifetime_earned_cents` is the sum of `final_amount_cents` over the writer's allocation rows in `FINAL` status; and `payable_balance_cents` is a running balance credited with each finalize's net, debited with each reversal's net, and debited again with each distribution payout"

        Design: Difficulty/transitive_cascade/statement_finalize_recoupment_chain
        """
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        advances=((1000, None),),
                                        title="Cascade Song 2")
        writer = get_writer(ctx["writers"][0]["id"])
        assert writer["payable_balance_cents"] == 0, "net was fully recouped"
        assert writer["lifetime_earned_cents"] == 1000
        assert writer["advance_outstanding_cents"] == 0

        work = get_work(ctx["work"]["id"])
        assert work["total_collected_cents"] == 2000
        assert work["total_distributed_cents"] == 0


class TestRecoupReversalInvariant:
    def test_advance_principal_conserved_after_recoupment(self, api):
        """PRD §3.7: "For every advance in `PAID`, `RECOUPING`, or `RECOUPED`, its `amount_cents` always equals `recouped_cents` plus `outstanding_cents` — and this must hold after every reversal replayed under §3.6 as well."

        Design: Difficulty/compensating_invariant/advance_principal_conserved_across_recoup_and_reversal
        """
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        advances=((3000, None),),
                                        title="Invariant Song")
        advance = validate_success(
            api.get_advance(ctx["advances"][0]["id"], ADMIN))
        assert advance["status"] == "RECOUPING"
        assert advance["recouped_cents"] == 1000
        assert advance["outstanding_cents"] == 2000
        assert advance["amount_cents"] == 3000
        assert_advance_principal_invariant(advance)

    def test_advance_principal_restored_after_supersede_reversal(self, api):
        """PRD §3.6: "The recoupment waterfall is replayed in reverse — applications are undone in reverse chronological order of how they were applied: for each reversed row, its `advance_applied_cents` is credited back to the originating advance, decreasing that advance's `recouped_cents` and increasing its `outstanding_cents` by the same amount."
        PRD §3.6: "an advance in `RECOUPED` whose `recouped_cents` is restored above zero (while remaining below its principal) returns to `RECOUPING`, and an advance in `RECOUPING` whose `recouped_cents` falls all the way to zero returns to `PAID`."

        Design: Difficulty/compensating_invariant/advance_principal_conserved_across_recoup_and_reversal
        """
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        advances=((3000, None),),
                                        title="Invariant Song 2")
        s1 = ctx["statement"]
        amendment = create_statement(
            ctx["licensee"]["id"],
            [statement_line(1, "Invariant Song 2", 2000,
                            work_code=ctx["work"]["work_code"])],
            2000, period=Q1_2026, amends_statement_id=s1["id"])
        assert amendment["status"] == "RECEIVED"

        superseded = validate_success(api.get_royalty_statement(s1["id"], ADMIN))
        assert superseded["status"] == "SUPERSEDED"

        advance = validate_success(
            api.get_advance(ctx["advances"][0]["id"], ADMIN))
        assert advance["status"] == "PAID", (
            "a full reversal returns RECOUPING to PAID")
        assert advance["recouped_cents"] == 0
        assert advance["outstanding_cents"] == 3000
        assert_advance_principal_invariant(advance)

        writer = get_writer(ctx["writers"][0]["id"])
        assert writer["payable_balance_cents"] == 0
        assert writer["lifetime_earned_cents"] == 0
        assert writer["advance_outstanding_cents"] == 3000

        work = get_work(ctx["work"]["id"])
        assert work["total_collected_cents"] == 0, (
            "the superseded statement stops contributing to work rollups")


class TestDerivedFieldReconciliation:
    def test_derived_fields_reconciled_after_amendment_supersede(self, api):
        """PRD §3.6: "Superseding moves the referenced statement from `FINALIZED` to `SUPERSEDED` and unwinds every financial effect it produced. Each of its allocation rows in `FINAL` status moves to `REVERSED`."
        PRD §3.6: "On every affected writer, `payable_balance_cents` is debited by the reversed rows' `net_payable_cents`, and `advance_outstanding_cents` and `lifetime_earned_cents` are recomputed from source records. Each matched work's `total_collected_cents` is recomputed under the rollup rule of §3.5, so the superseded statement stops contributing."

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_after_amendment_supersede
        """
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        title="Reconcile Song")
        s1 = ctx["statement"]
        writer = get_writer(ctx["writers"][0]["id"])
        assert writer["payable_balance_cents"] == 1000
        assert writer["lifetime_earned_cents"] == 1000
        assert get_work(ctx["work"]["id"])["total_collected_cents"] == 2000

        create_statement(
            ctx["licensee"]["id"],
            [statement_line(1, "Reconcile Song", 2000,
                            work_code=ctx["work"]["work_code"])],
            2000, period=Q1_2026, amends_statement_id=s1["id"])

        rows = list_allocation_lines(statement_id=s1["id"])
        assert len(rows) == 2
        assert all(r["status"] == "REVERSED" for r in rows), (
            "every FINAL allocation row of the superseded statement reverses")

        writer = get_writer(ctx["writers"][0]["id"])
        assert writer["payable_balance_cents"] == 0
        assert writer["lifetime_earned_cents"] == 0
        assert get_work(ctx["work"]["id"])["total_collected_cents"] == 0


class TestEarningsSummary:
    def test_earnings_summary_computed_read(self, api):
        """PRD §3.1: "Each writer's financial position is available as a computed read, the earnings summary, returning `writer_id`, `status`, `payable_balance_cents`, `advance_outstanding_cents`, and `lifetime_earned_cents`."
        PRD §3.7: "`advance_outstanding_cents` is the sum of `outstanding_cents` over the writer's advances in `PAID` or `RECOUPING`; `lifetime_earned_cents` is the sum of `final_amount_cents` over the writer's allocation rows in `FINAL` status"

        Design: Corner/endpoints/earnings_summary_computed_read
        """
        ctx = setup_finalized_statement(line_grosses=(8000,),
                                        advances=((1000, None),),
                                        title="Summary Song")
        writer_id = ctx["writers"][0]["id"]
        summary = validate_success(api.get_earnings_summary(writer_id, ADMIN))
        # Writer final 4000; recoupment applies 1000; net payable 3000.
        assert summary["writer_id"] == writer_id
        assert summary["status"] == "ACTIVE"
        assert summary["payable_balance_cents"] == 3000
        assert summary["advance_outstanding_cents"] == 0
        assert summary["lifetime_earned_cents"] == 4000


class TestAmendmentGating:
    def test_statement_amend_requires_final_and_not_superseded(self, api):
        """PRD §3.6: "The amendment reference must resolve (else `ERR_NOT_FOUND`), and two state checks then apply in a fixed order — first, if the referenced statement is already `SUPERSEDED`, the create is rejected with `ERR_STATEMENT_ALREADY_SUPERSEDED`; second, if it is anything other than `FINALIZED`, the create is rejected with `ERR_AMENDED_STATEMENT_NOT_FINAL`. Only a `FINALIZED` statement may be amended, because only finalized money needs reversing."

        Design: Corner/state_machines/statement_amend_requires_final_and_not_superseded
        """
        ctx = setup_registered_work(title="Amend Song")
        work = ctx["work"]
        licensee = create_licensee()
        s1 = create_statement(
            licensee["id"],
            [statement_line(1, "Amend Song", 2000,
                            work_code=work["work_code"])],
            2000, period=Q1_2026)
        run_statement_pipeline(s1["id"], through="FINALIZED")
        s2 = create_statement(
            licensee["id"],
            [statement_line(1, "Amend Song Q2", 4000,
                            work_code=work["work_code"])],
            4000, period=Q2_2026)
        run_statement_pipeline(s2["id"], through="ALLOCATED")
        # S3 amends S1, moving S1 to SUPERSEDED.
        create_statement(
            licensee["id"],
            [statement_line(1, "Amend Song", 2500,
                            work_code=work["work_code"])],
            2500, period=Q1_2026, amends_statement_id=s1["id"])

        def _amend(target_id, period, gross):
            return api.create_royalty_statement(
                {"source_type": "LICENSEE", "source_id": licensee["id"],
                 "income_type": "PERFORMANCE", "territory_code": "US",
                 "period_start": period[0], "period_end": period[1],
                 "gross_amount_cents": gross, "amends_statement_id": target_id,
                 "lines": []},
                ANALYST)

        resp1 = _amend(s2["id"], Q2_2026, 4000)
        validate_error(resp1, ApiErrorId.ERR_AMENDED_STATEMENT_NOT_FINAL)

        resp2 = _amend(s1["id"], Q1_2026, 2500)
        validate_error(resp2, ApiErrorId.ERR_STATEMENT_ALREADY_SUPERSEDED)
