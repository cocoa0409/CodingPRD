"""Allocation mathematics: the provisional/final dual variant over unmatched
income, per-line floor-then-remainder pool splitting, sub-publisher retention
selection and rounding, and immediate visibility of recomputed totals."""
from test_helpers import (
    activate_sub_publishing_agreement,
    create_licensee,
    create_statement,
    create_sub_publisher,
    create_sub_publishing_agreement,
    list_allocation_lines,
    run_statement_pipeline,
    setup_registered_work,
    statement_line,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _two_work_scenario(api):
    """Writers W1/W2, works K1/K2 (each with a CONFIRMED 10000bp split set),
    both REGISTERED via distinct PRO societies."""
    ctx1 = setup_registered_work(
        writer_specs=[("Writer One", 10000)], title="Song K1",
        iswc="T-900000001-1", society_code="ASCAP")
    ctx2 = setup_registered_work(
        writer_specs=[("Writer Two", 10000)], title="Song K2",
        iswc="T-900000002-2", society_code="BMI")
    return ctx1, ctx2


class TestDualVariantUnmatchedIncome:
    def _setup_statement(self, api):
        """One statement: 6000 matched to K1, 4000 matched to K2, 2000 with no
        hints (unmatched); header gross 12000. Walked through match."""
        ctx1, ctx2 = _two_work_scenario(api)
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Song K1", 6000,
                            work_code=ctx1["work"]["work_code"]),
             statement_line(2, "Song K2", 4000,
                            work_code=ctx2["work"]["work_code"]),
             statement_line(3, "Unknown Track", 2000)],
            12000)
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))
        return ctx1, ctx2, statement

    def test_provisional_stage_spreads_unmatched_income(self, api):
        """PRD §3.5: "Otherwise each matched line is credited with the unmatched total multiplied by that line's `gross_cents` and divided by the matched total, rounded down; the cents left over are distributed one at a time to matched lines in descending `gross_cents` order, ties broken by ascending line `created_at`. A line's effective gross for this stage is its own `gross_cents` plus its spread."
        PRD §3.5: "`suspense_cents` is zero at this stage because every unmatched cent was provisionally spread, and `allocated_total_cents` is the sum of the provisional allocation amounts."

        Design: Difficulty/dual_variant_calc/unmatched_income_provisional_spread_vs_final_suspense
        """
        ctx1, ctx2, statement = self._setup_statement(api)
        allocated = validate_success(
            api.allocate_royalty_statement(statement["id"], ANALYST))

        # Effective grosses: 6000 + floor(2000*6000/10000) = 7200 and
        # 4000 + 800 = 4800; writer pool is one half of the net, floored.
        w1_rows = list_allocation_lines(statement_id=statement["id"],
                                        writer_id=ctx1["writers"][0]["id"])
        w2_rows = list_allocation_lines(statement_id=statement["id"],
                                        writer_id=ctx2["writers"][0]["id"])
        assert len(w1_rows) == 1 and len(w2_rows) == 1
        assert w1_rows[0]["provisional_amount_cents"] == 3600
        assert w2_rows[0]["provisional_amount_cents"] == 2400
        assert w1_rows[0]["status"] == "PROVISIONAL"
        assert w1_rows[0]["final_amount_cents"] is None, (
            "final_amount_cents stays null until finalization")

        assert allocated["suspense_cents"] == 0
        assert allocated["allocated_total_cents"] == 12000
        assert allocated["retained_cents"] == 0

    def test_final_stage_routes_unmatched_income_to_suspense(self, api):
        """PRD §3.5: "Allocations are recomputed under the final variant: each matched line's effective gross is exactly its `gross_cents` with no spread, and the unmatched gross is no longer distributed — it accumulates instead into the statement's `suspense_cents`, held back until the unmatched lines are resolved by later amendment."
        PRD §3.5: "Because the two variants treat unmatched income differently, identical statement data yields different per-writer amounts at the two stages; `allocated_total_cents` is recomputed as the sum of the final amounts, and `retained_cents` is recomputed as well."

        Design: Difficulty/dual_variant_calc/unmatched_income_provisional_spread_vs_final_suspense
        """
        ctx1, ctx2, statement = self._setup_statement(api)
        validate_success(api.allocate_royalty_statement(statement["id"], ANALYST))
        w1_prov = list_allocation_lines(
            statement_id=statement["id"],
            writer_id=ctx1["writers"][0]["id"])[0]["provisional_amount_cents"]

        finalized = validate_success(
            api.finalize_royalty_statement(statement["id"], ANALYST))
        assert finalized["status"] == "FINALIZED"

        w1_rows = list_allocation_lines(statement_id=statement["id"],
                                        writer_id=ctx1["writers"][0]["id"])
        w2_rows = list_allocation_lines(statement_id=statement["id"],
                                        writer_id=ctx2["writers"][0]["id"])
        assert w1_rows[0]["final_amount_cents"] == 3000
        assert w2_rows[0]["final_amount_cents"] == 2000
        assert w1_rows[0]["status"] == "FINAL"
        assert w1_rows[0]["final_amount_cents"] != w1_prov, (
            "identical statement data yields different per-writer amounts "
            "between the two variants")

        assert finalized["suspense_cents"] == 2000
        assert finalized["allocated_total_cents"] == 10000


class TestPoolSplitRounding:
    def _setup_rounding_statement(self, api):
        """Work with writers at 3333/3333/3334 bp; one matched line of 9999."""
        ctx = setup_registered_work(
            writer_specs=[("W1", 3333), ("W2", 3333), ("W3", 3334)],
            title="Rounding Song")
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Rounding Song", 9999,
                            work_code=ctx["work"]["work_code"])],
            9999)
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))
        return ctx, statement

    def test_per_line_floor_then_remainder_to_largest_share(self, api):
        """PRD §3.5: "Within each pool, every split line first receives the pool multiplied by its `share_bp` and divided by 10000, rounded down; the pool's leftover cents are then dealt one at a time to that pool's lines in descending `share_bp` order, ties broken by ascending split-line `created_at`, at most one cent per line per pass, repeating passes until nothing remains."
        PRD §3.5: "Allocation rows are created in a pinned order so their `created_at` values are strictly increasing: matched statement lines are processed in ascending line `created_at` order, and within each line the `WRITER`-pool rows are created first in ascending split-line `created_at` order, then the `PUBLISHER`-pool rows."

        Design: Difficulty/combinatorial_formula/split_allocation_per_line_floor_then_remainder
        """
        ctx, statement = self._setup_rounding_statement(api)
        validate_success(api.allocate_royalty_statement(statement["id"], ANALYST))

        rows = list_allocation_lines(statement_id=statement["id"])
        # Writer pool floor(9999/2) = 4999; per-line floor(4999*share/10000)
        # gives 1666 + 1666 + 1666 = 4998, and the 1-cent remainder goes to
        # the largest share (3334 bp, the third writer line).
        assert len(rows) == 4
        writer_rows = [r for r in rows if r["participant_type"] == "WRITER"]
        assert [r["provisional_amount_cents"] for r in writer_rows] == [
            1666, 1666, 1667]
        assert writer_rows[2]["split_line_id"] == ctx["lines"][2]["id"]

    def test_odd_cent_lands_in_publisher_pool(self, api):
        """PRD §3.5: "The net divides into two pools: the writer pool is one half of the net — 5000 of the 10000 basis points — rounded down to a whole cent, and the publisher pool is the remainder of the net, so an odd cent lands in the publisher pool."
        PRD §3.5: "Once allocation completes, the statement's computed totals are refreshed: `retained_cents` carries the summed sub-publisher retention, `suspense_cents` is zero at this stage because every unmatched cent was provisionally spread, and `allocated_total_cents` is the sum of the provisional allocation amounts."

        Design: Difficulty/combinatorial_formula/split_allocation_per_line_floor_then_remainder
        """
        ctx, statement = self._setup_rounding_statement(api)
        allocated = validate_success(
            api.allocate_royalty_statement(statement["id"], ANALYST))

        rows = list_allocation_lines(statement_id=statement["id"])
        publisher_rows = [r for r in rows if r["participant_type"] == "PUBLISHER"]
        assert len(publisher_rows) == 1
        # publisher pool = net - writer_pool = 9999 - 4999 = 5000.
        assert publisher_rows[0]["provisional_amount_cents"] == 5000
        assert publisher_rows[0]["writer_id"] is None

        assert allocated["allocated_total_cents"] == 9999
        assert allocated["retained_cents"] == 0
        assert allocated["suspense_cents"] == 0


class TestSubPublisherRetention:
    def _setup_retention_statement(self, api, activate_agreement):
        """Registered work + a US/PERFORMANCE agreement at 1500 bp covering
        [2026-01-01, 2027-01-01); one matched line of 3333 (Q1 period)."""
        ctx = setup_registered_work(title="Retention Song")
        sub = create_sub_publisher(name="US Sub", home_territory_code="US")
        agreement = create_sub_publishing_agreement(
            sub["id"], territory_codes=["US"], income_types=["PERFORMANCE"],
            retention_bp=1500)
        if activate_agreement:
            activate_sub_publishing_agreement(agreement["id"])
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Retention Song", 3333,
                            work_code=ctx["work"]["work_code"])],
            3333)
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))
        return ctx, statement

    def test_retention_floor_rounding_per_line(self, api):
        """PRD §3.5: "Otherwise the retention is the line's effective gross multiplied by the agreement's `retention_bp` and divided by 10000, rounded down to a whole cent. Retention is computed per line and summed into the statement's `retained_cents`."
        PRD §3.5: "From each matched line's effective gross, the line's retention is subtracted to yield the net."

        Design: Corner/calculations/retention_floor_rounding_per_line
        """
        ctx, statement = self._setup_retention_statement(
            api, activate_agreement=True)
        allocated = validate_success(
            api.allocate_royalty_statement(statement["id"], ANALYST))

        # floor(3333 * 1500 / 10000) = floor(499.95) = 499 — not 500.
        assert allocated["retained_cents"] == 499
        # net 2834; writer pool floor(2834/2) = 1417; publisher pool 1417.
        rows = list_allocation_lines(statement_id=statement["id"])
        assert [r["provisional_amount_cents"] for r in rows] == [1417, 1417]
        assert allocated["allocated_total_cents"] == 2834
        assert 499 + 2834 + allocated["suspense_cents"] == 3333, (
            "gross is conserved across retention, allocation, and suspense")

    def test_retention_selector_ignores_draft_agreements(self, api):
        """PRD §3.5: "The server selects the sub-publishing agreement that applies to this line: an agreement that is `ACTIVE` (lazily excluding expired ones per §2.5), whose `territory_codes` contain the statement's `territory_code`, whose `income_types` contain the statement's `income_type`, and whose half-open coverage window contains the statement's `period_end` — `effective_from` on or before `period_end`, and `period_end` strictly before `effective_to`. At most one such agreement can exist; if none applies, retention for the line is zero."

        Design: Corner/calculations/retention_selector_ignores_draft_agreements
        """
        ctx, statement = self._setup_retention_statement(
            api, activate_agreement=False)
        allocated = validate_success(
            api.allocate_royalty_statement(statement["id"], ANALYST))

        assert allocated["retained_cents"] == 0, (
            "a DRAFT agreement is outside the ACTIVE-only selector")
        assert allocated["allocated_total_cents"] == 3333


class TestProvisionalSpreadRemainder:
    def test_provisional_spread_remainder_to_earliest_line(self, api):
        """PRD §3.5: "Otherwise each matched line is credited with the unmatched total multiplied by that line's `gross_cents` and divided by the matched total, rounded down; the cents left over are distributed one at a time to matched lines in descending `gross_cents` order, ties broken by ascending line `created_at`."

        Design: Corner/calculations/provisional_spread_remainder_to_earliest_line
        """
        ctx1, ctx2 = _two_work_scenario(api)
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Spread One", 5000,
                            work_code=ctx1["work"]["work_code"]),
             statement_line(2, "Spread Two", 5000,
                            work_code=ctx2["work"]["work_code"]),
             statement_line(3, "Mystery", 1003)],
            11003)
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))
        allocated = validate_success(
            api.allocate_royalty_statement(statement["id"], ANALYST))

        # Each matched line floors to 501 of spread; the 1-cent remainder
        # breaks the gross tie by ascending line created_at -> line 1.
        # Effective grosses 5502 and 5501; writer pools floor(E/2).
        w1 = list_allocation_lines(statement_id=statement["id"],
                                   writer_id=ctx1["writers"][0]["id"])[0]
        w2 = list_allocation_lines(statement_id=statement["id"],
                                   writer_id=ctx2["writers"][0]["id"])[0]
        assert w1["provisional_amount_cents"] == 2751
        assert w2["provisional_amount_cents"] == 2750
        assert allocated["allocated_total_cents"] == 11003
        assert allocated["suspense_cents"] == 0


class TestImmediateConsistency:
    def test_immediate_visibility_in_finalize_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.5: "Allocations are recomputed under the final variant: each matched line's effective gross is exactly its `gross_cents` with no spread, and the unmatched gross is no longer distributed — it accumulates instead into the statement's `suspense_cents`, held back until the unmatched lines are resolved by later amendment."

        Design: Corner/consistency_model/immediate_visibility_in_finalize_response
        """
        ctx = setup_registered_work(title="Immediate Song")
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Immediate Song", 2000,
                            work_code=ctx["work"]["work_code"]),
             statement_line(2, "Mystery", 1000)],
            3000)
        run_statement_pipeline(statement["id"], through="ALLOCATED")

        finalized = validate_success(
            api.finalize_royalty_statement(statement["id"], ANALYST))
        # The finalize response body itself carries the recomputed totals.
        assert finalized["status"] == "FINALIZED"
        assert finalized["suspense_cents"] == 1000
        assert finalized["allocated_total_cents"] == 2000
