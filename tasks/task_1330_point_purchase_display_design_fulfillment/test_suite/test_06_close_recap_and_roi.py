"""Program close-out: the minted recap, its totals, and the two ROI variants."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PROGRAM_MANAGER,
    ApiErrorId,
    api_client,
    approve_claim,
    assert_program_recap,
    close_program,
    create_damage_claim_entity,
    fulfill_claim,
    get_kit,
    get_recap,
    setup_closed_program,
    setup_shipped,
    start_fulfillment,
    validate_error,
    validate_success,
)


class TestRecapRoiVariants:
    """One program, two ROI readings: provisional is captured at the first
    PRODUCED run on committed cost only; final is computed at close on full
    actuals including fulfilled damage replacements."""

    def _close_program_with_fulfilled_claim(self):
        """store_count=200, overage 8 -> qty 216 at 2200 cents = 475200 cents of
        committed production cost. One kit ships, takes a 2-unit damage claim
        (replacement cost 2 * 2200 = 4400 cents), the claim is approved and
        fulfilled, then the program closes."""
        ctx = setup_shipped(store_count=200, overage_pct=8, num_stores=1,
                            program_revenue_cents=12000000)
        ctx["program"] = start_fulfillment(ctx["program"]["id"])
        claim = create_damage_claim_entity(ctx["kit"]["id"],
                                           replacement_quantity=2)
        claim = approve_claim(claim["id"])
        assert claim["replacement_cost_cents"] == 4400
        assert get_kit(ctx["kit"]["id"])["status"] == "DAMAGED"
        claim = fulfill_claim(claim["id"])
        assert claim["status"] == "FULFILLED"
        ctx["program"] = close_program(ctx["program"]["id"])
        assert ctx["program"]["status"] == "CLOSED"
        return ctx

    def test_provisional_and_final_roi_diverge_with_fulfilled_claim(self):
        """PRD §3.7: "The provisional variant, `roi_pct_provisional`, is captured
        the moment the program's first production run reaches `PRODUCED`: it
        subtracts from `program_revenue_cents` the committed production cost —
        the sum of `total_cost_cents` over runs in `PRODUCED` status,
        deliberately excluding damage replacement actuals — divides that
        difference by the same committed cost, and multiplies by one hundred."
        PRD §3.7: "The final variant, `roi_pct_final`, is computed at close on
        the full actuals: it subtracts from `program_revenue_cents` the final
        cost basis — produced runs' `total_cost_cents` plus fulfilled claims'
        `replacement_cost_cents` — divides by that same final cost, and
        multiplies by one hundred."

        Design: Difficulty/dual_variant_calc/program_roi_provisional_vs_final
        """
        ctx = self._close_program_with_fulfilled_claim()
        recap = get_recap(ctx["program"]["id"])
        assert_program_recap(recap)
        assert recap["total_produced"] == 216
        assert recap["total_damaged"] == 1
        assert recap["total_cost_cents"] == 475200 + 4400
        # provisional: committed cost only -> (12000000-475200)/475200*100
        assert recap["roi_pct_provisional"] == pytest.approx(2425.25, abs=0.01)
        # final: adds the fulfilled claim's 4400 -> (12000000-479600)/479600*100
        assert recap["roi_pct_final"] == pytest.approx(2402.09, abs=0.01)
        assert recap["roi_pct_provisional"] != recap["roi_pct_final"]

    def test_roi_variants_coincide_without_fulfilled_claims(self):
        """PRD §3.7: "The final variant, `roi_pct_final`, is computed at close
        on the full actuals: it subtracts from `program_revenue_cents` the final
        cost basis — produced runs' `total_cost_cents` plus fulfilled claims'
        `replacement_cost_cents` — divides by that same final cost, and
        multiplies by one hundred."
        PRD §3.7: "The provisional variant, `roi_pct_provisional`, is captured
        the moment the program's first production run reaches `PRODUCED`".

        Design: Difficulty/dual_variant_calc/program_roi_provisional_vs_final
        """
        # No damage claims at all: the final cost basis equals the committed
        # production cost, so both variants must read identically.
        ctx = setup_closed_program(store_count=200, num_stores=1, overage_pct=8,
                                   program_revenue_cents=12000000)
        assert ctx["run"]["total_cost_cents"] == 475200
        recap = get_recap(ctx["program"]["id"])
        assert_program_recap(recap)
        assert recap["total_cost_cents"] == 475200
        assert recap["roi_pct_provisional"] == pytest.approx(2425.25, abs=0.01)
        assert recap["roi_pct_final"] == pytest.approx(2425.25, abs=0.01)

    def test_provisional_roi_excludes_damage_replacement_actuals(self):
        """PRD §3.7: "it subtracts from `program_revenue_cents` the committed
        production cost — the sum of `total_cost_cents` over runs in `PRODUCED`
        status, deliberately excluding damage replacement actuals — divides that
        difference by the same committed cost, and multiplies by one hundred."

        Design: Corner/calculations/roi_provisional_excludes_damage
        """
        ctx = setup_closed_program(store_count=200, num_stores=1, overage_pct=8,
                                   program_revenue_cents=12000000)
        recap = get_recap(ctx["program"]["id"])
        # round_half_up((12000000 - 475200) / 475200 * 100, 2) == 2425.25
        assert recap["roi_pct_provisional"] == pytest.approx(2425.25, abs=0.01)


class TestRecapTotals:

    def test_recap_after_close_reports_totals_and_final_roi(self):
        """PRD §3.7: "`total_produced` is the sum of `production_quantity`
        across the program's runs that reached `PRODUCED`. `total_delivered`
        counts the program's shipments in `DELIVERED` status. `total_damaged`
        counts the program's damage claims in `FULFILLED` status.
        `total_cost_cents` is the final cost basis: the sum of
        `total_cost_cents` across the program's runs plus the
        `replacement_cost_cents` of its approved-and-fulfilled damage claims."
        PRD §3.7: "A `PlatformAdmin` or `ProgramManager` reads the recap back
        through the program's recap listing once the program is closed."

        Design: Corner/endpoints/computed_read_recap_after_close
        """
        # store_count=3, overage 0 -> qty 3 at 2500 cents = 7500; all three
        # stores' kits shipped and delivered; no damage claims.
        ctx = setup_closed_program(store_count=3, num_stores=3, overage_pct=0,
                                   program_revenue_cents=1000000)
        recap = get_recap(ctx["program"]["id"])
        assert_program_recap(recap)
        assert recap["program_id"] == ctx["program"]["id"]
        assert recap["total_produced"] == 3
        assert recap["total_delivered"] == 3
        assert recap["total_damaged"] == 0
        assert recap["total_cost_cents"] == 7500
        # round_half_up((1000000 - 7500) / 7500 * 100, 2) == 13233.33
        assert recap["roi_pct_final"] == pytest.approx(13233.33, abs=0.01)


class TestClosedProgramLockdown:

    def test_cancel_on_closed_program_rejected(self):
        """PRD §3.1: "Cancelling, by contrast, is available only while the
        program is still young: a program in `DRAFT` or `DESIGN` may move to
        `CANCELLED`".
        PRD §2.9: "4. State — the target resource is in a state that permits the
        requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_on_closed_program
        """
        ctx = setup_closed_program(store_count=3, num_stores=1, overage_pct=0,
                                   program_revenue_cents=1000000)
        assert ctx["program"]["status"] == "CLOSED"
        resp = api_client.cancel_program(ctx["program"]["id"], PROGRAM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_recap_read_for_nonexistent_program_returns_404(self):
        """PRD §2.9: "the request is rejected with `ERR_NOT_FOUND` at the first
        identifier that does not correspond to an existing resource, before any
        later identifier or any business rule is examined."
        PRD §3.7: "The recap is immutable: it carries `id` and `created_at` but,
        as §2.4 notes, no `updated_at` and no `version`."

        Design: Corner/entities/program_recap_has_no_update_endpoint
        """
        resp = api_client.get_program_recap(NON_EXISTENT_UUID, PROGRAM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
