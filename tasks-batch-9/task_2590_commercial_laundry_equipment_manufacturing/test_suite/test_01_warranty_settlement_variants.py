"""Warranty settlement on an approved claim: which of the two coverage forms the
selector picks, and the inventory, credit and claim-counter movements the approval
performs on one bearing claim against an accepted on-premises unit.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CHANNEL_MANAGER, WARRANTY_ANALYST


def _approve_claim(api, env):
    """Adjudicate the environment's SUBMITTED claim as APPROVE, presenting the
    part version the analyst just read as the optimistic-concurrency token."""
    payload = f.adjudicate_payload(
        fx.read_part_version(api, env["part"]["id"]), "APPROVE"
    )
    return validate_success(
        api.adjudicate_warranty_claim(env["claim"]["id"], payload, WARRANTY_ANALYST),
        expected_status=200,
    )


class TestWarrantySettlementVariants:
    def test_01_effective_rated_cycles_is_the_single_floored_product(self, api, submitted_claim):
        """A standard-duty failure on an on-premises machine carries the part's rated design life through unchanged.

        PRD: "The two multipliers are multiplied together with the rated design life in a single exact product, and only that product is **truncated downward** to a whole number of cycles — the multipliers are never truncated one at a time, and the result is floored rather than rounded."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        claim = _approve_claim(api, env)

        # STANDARD duty multiplies by 1.00 and ON_PREMISES by 1.00, so the
        # 30000-cycle design life is carried through with no depletion.
        assert claim["effective_rated_cycles"] == 30000

        reread = validate_success(
            api.get_warranty_claim(env["claim"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert reread["effective_rated_cycles"] == 30000

    def test_02_full_replacement_selector_pays_the_whole_unit_price(self, api, submitted_claim):
        """Eight months in service and 8000 cycles is inside the first year and inside half the design life, so the whole part price is settled.

        PRD: "In that case `coverage_variant` is `FULL_REPLACEMENT` and `covered_amount_cents` is the part's full `unit_price_cents`, with no depletion applied at all."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        claim = _approve_claim(api, env)

        assert claim["coverage_variant"] == "FULL_REPLACEMENT"
        a.assert_cents(claim["covered_amount_cents"], 42000)
        # Feeding these same inputs through the depleted form would settle
        # 30800 cents instead; the full-replacement form applies no depletion.
        assert claim["covered_amount_cents"] != 30800

    def test_03_full_replacement_selector_is_not_the_pro_rata_form(self, api, submitted_claim):
        """The claim that clears both full-replacement conditions is never settled by the depleted form.

        PRD: "In every other case the pro-rata form applies: `coverage_variant` is `PRO_RATA` and the settlement is depleted by whichever entitlement has been consumed faster."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        _approve_claim(api, env)

        claim = validate_success(
            api.get_warranty_claim(env["claim"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert claim["coverage_variant"] != "PRO_RATA"
        a.assert_cents(claim["covered_amount_cents"], 42000)
        a.assert_claim_state(claim, "APPROVED")

    def test_04_approval_reserves_one_unit_conserving_the_sum(self, api, submitted_claim):
        """Approving the bearing claim moves one unit from the shelf into reservation without consuming it.

        PRD: "The part's `on_hand_qty` decreases by 1 while its `reserved_qty` increases by 1, so the sum of the two is conserved — a reservation is not a consumption."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        _approve_claim(api, env)

        part = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert part["on_hand_qty"] == 2
        assert part["reserved_qty"] == 1
        a.assert_unit_conservation(part, 3)

    def test_05_reprojected_stock_state_reads_low_at_the_reorder_point(self, api, submitted_claim):
        """Three on hand less the reserved unit lands exactly on the reorder point of two, which reads LOW.

        PRD: "The part's `stock_state` is re-projected from the new on-hand position: it becomes `BACKORDERED` when `on_hand_qty` has reached exactly 0, `LOW` when `on_hand_qty` is above 0 but at or below `reorder_point_qty` — the boundary is inclusive, so an on-hand position exactly equal to the reorder point reads `LOW` and not `IN_STOCK` — and `IN_STOCK` otherwise."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        _approve_claim(api, env)

        part = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        # The boundary is inclusive, so two on hand against a reorder point of
        # two is LOW and not IN_STOCK.
        assert part["stock_state"] == "LOW"
        a.assert_stock_state(part)

    def test_06_approval_credits_the_distributor_by_the_settled_amount(self, api, submitted_claim):
        """The settled full-replacement amount lands on the claiming distributor's credit ledger.

        PRD: "Finally the claiming distributor's `warranty_credit_cents` increases by the `covered_amount_cents` just settled."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        _approve_claim(api, env)

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        a.assert_cents(distributor["warranty_credit_cents"], 42000)

    def test_07_open_claim_count_drops_once_the_claim_leaves_submitted(self, api, submitted_claim):
        """The distributor's open-claim counter is recomputed by the adjudication that emptied its submitted queue.

        PRD: "`open_claim_count` is the number of that distributor's warranty claims currently sitting in `SUBMITTED`, and it is recomputed on every event that could change it."
        Design: Difficulty/dual_variant_calc/warranty_coverage_full_vs_pro_rata_same_claim_data
        """
        env = submitted_claim
        _approve_claim(api, env)

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert distributor["open_claim_count"] == 0
