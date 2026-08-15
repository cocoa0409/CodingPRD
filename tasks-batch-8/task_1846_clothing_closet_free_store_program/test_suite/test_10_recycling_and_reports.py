"""Textile recycling: sweep ordering, provisional vs final settlement, seal
guards; and the trailing-28-day impact report with its two turnover bases."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_lines,
    assert_recycling_batch,
    checkin_visit,
    get_item,
    open_recycling_batch,
    pickup_recycling_batch,
    register_client,
    seal_recycling_batch,
    setup_stocked_items,
    setup_swept_recycling_batch,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

REJECT_CHILDRENS = {"category": "CHILDRENS", "season": "ALL_SEASON",
                    "quality_grade": "REJECT"}
REJECT_ACCESSORIES = {"category": "ACCESSORIES", "season": "ALL_SEASON",
                      "quality_grade": "REJECT"}
REJECT_COATS = {"category": "COATS", "season": "WINTER", "quality_grade": "REJECT"}
GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}


class TestProvisionalVsFinalCredit:
    def test_recycling_credit_provisional_and_final_variants_diverge(self, api):
        """PRD: "For each assigned item, its estimated weight is multiplied by
        its category's rate and the result rounded half up to a whole cent;
        `provisional_credit_cents` is the sum of those per-item amounts, and
        `est_weight_kg` is the sum of the estimated weights at two decimal
        places."
        PRD: "The final settlement blends composition away and prices the scale
        weight at a single tiered rate: below 100 kilograms the rate is 40 cents
        per kilogram; from 100 kilograms up to but not including 500 kilograms
        the rate is 44; at 500 kilograms and above the rate is 50 — boundaries
        are inclusive upward. `final_credit_cents` is the actual weight
        multiplied by the applicable tier rate, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/recycling_credit_provisional_vs_final
        """
        env = setup_swept_recycling_batch(
            [dict(REJECT_CHILDRENS), dict(REJECT_CHILDRENS), dict(REJECT_CHILDRENS),
             dict(REJECT_ACCESSORIES), dict(REJECT_ACCESSORIES)],
            capacity_kg=50)
        batch = env["recycling_batch"]
        assert batch["item_count"] == 5

        sealed = seal_recycling_batch(batch["id"], admin_user_id="admin-1")
        assert_recycling_batch(sealed)
        assert sealed["est_weight_kg"] == pytest.approx(1.30, abs=0.001)
        assert sealed["provisional_credit_cents"] == 45, (
            "3 * round_half_up(0.30 * 38) + 2 * round_half_up(0.20 * 30) = 33 + 12")

        picked = pickup_recycling_batch(batch["id"], 1.60, admin_user_id="admin-2")
        assert picked["status"] == "PICKED_UP"
        assert picked["final_credit_cents"] == 64, (
            "round_half_up(1.60 * 40); 1.60 kg is below the 100 kg tier")
        assert picked["provisional_credit_cents"] != picked["final_credit_cents"], (
            "the two variants value the same five items differently")

    def test_recycling_credit_seal_moves_items_and_stamps_operator(self, api):
        """PRD: "Sealing also moves every assigned item from `REJECTED` to
        `RECYCLED` and records the operator in `sealed_by_user_id`."
        PRD: "The operator is recorded in `picked_up_by_user_id`, and the batch
        moves to `PICKED_UP`."

        Design: Difficulty/dual_variant_calc/recycling_credit_provisional_vs_final
        """
        env = setup_swept_recycling_batch(
            [dict(REJECT_CHILDRENS), dict(REJECT_CHILDRENS), dict(REJECT_CHILDRENS),
             dict(REJECT_ACCESSORIES), dict(REJECT_ACCESSORIES)],
            capacity_kg=50)
        batch = env["recycling_batch"]

        sealed = seal_recycling_batch(batch["id"], admin_user_id="admin-1")
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_user_id"] == "admin-1"
        assert sealed["est_weight_kg"] == pytest.approx(1.30, abs=0.001)
        assert sealed["provisional_credit_cents"] == 45
        for item in env["items"]:
            assert get_item(item["id"])["status"] == "RECYCLED"

        picked = pickup_recycling_batch(batch["id"], 1.60, admin_user_id="admin-2")
        assert picked["picked_up_by_user_id"] == "admin-2"
        assert picked["final_credit_cents"] == 64


class TestPerItemRoundingOrder:
    def test_provisional_credit_rounds_per_item_then_sums(self, api):
        """PRD: "For each assigned item, its estimated weight is multiplied by
        its category's rate and the result rounded half up to a whole cent;
        `provisional_credit_cents` is the sum of those per-item amounts"
        PRD: "Estimated textile weights are kept at two decimal places of
        kilograms. Recycling credits are integer cent amounts; every credit
        computation rounds half up to a whole cent."

        Design: Difficulty/combinatorial_formula/recycling_credit_per_item_rounding_order
        """
        env = setup_swept_recycling_batch(
            [dict(REJECT_CHILDRENS) for _ in range(3)], capacity_kg=50)

        sealed = seal_recycling_batch(env["recycling_batch"]["id"],
                                      admin_user_id="admin-1")
        assert sealed["provisional_credit_cents"] == 33, (
            "per-item rounding pinned: 3 * round_half_up(11.4) = 33, "
            "not round_half_up(34.2) = 34")

    def test_provisional_estimated_weight_two_dp(self, api):
        """PRD: "`est_weight_kg` is the sum of the estimated weights at two
        decimal places."
        PRD: "Estimated weights are fixed per category: an `ADULT_TOPS` item is
        estimated at 0.40 kg, `ADULT_BOTTOMS` at 0.60 kg, `CHILDRENS` at 0.30 kg,
        `COATS` at 1.50 kg, `INTERVIEW_ATTIRE` at 0.80 kg, and `ACCESSORIES` at
        0.20 kg."

        Design: Difficulty/combinatorial_formula/recycling_credit_per_item_rounding_order
        """
        env = setup_swept_recycling_batch(
            [dict(REJECT_CHILDRENS) for _ in range(3)], capacity_kg=50)

        sealed = seal_recycling_batch(env["recycling_batch"]["id"],
                                      admin_user_id="admin-1")
        assert sealed["est_weight_kg"] == pytest.approx(0.90, abs=0.001)
        assert sealed["item_count"] == 3
        assert sealed["status"] == "SEALED"


class TestSweep:
    def test_sweep_capacity_chronological_stop(self, api):
        """PRD: "Candidates are items in `REJECTED` status whose
        `recycling_batch_id` is still null, processed in creation order, oldest
        first, with no identifier tie-break ever applied. Starting from the
        batch's current `est_weight_kg`, the sweep considers each candidate in
        turn: if adding the item's estimated weight would push the running total
        beyond the batch's `capacity_kg`, the sweep stops immediately — it does
        not skip ahead to a lighter item; otherwise the item's
        `recycling_batch_id` is set to the batch and its estimated weight joins
        the running total."

        Design: Corner/calculations/sweep_capacity_chronological_stop
        """
        env = setup_swept_recycling_batch(
            [dict(REJECT_COATS) for _ in range(3)], capacity_kg=2.0)
        batch = env["recycling_batch"]
        assert batch["item_count"] == 1, "the second 1.5 kg coat would exceed 2.0 kg"
        assert batch["est_weight_kg"] == pytest.approx(1.50, abs=0.001)

        second = get_item(env["items"][1]["id"])
        assert second["recycling_batch_id"] is None, (
            "unassigned items keep recycling_batch_id null")

    def test_recycling_seal_empty_rejected(self, api):
        """PRD: "Sealing the batch — which requires the batch to be
        `ACCUMULATING` (otherwise `ERR_INVALID_STATE`) and then to hold at least
        one assigned item (otherwise `ERR_RECYCLING_EMPTY`)"

        Design: Corner/validations/recycling_seal_empty_rejected
        """
        batch = open_recycling_batch("TexCycle", 10)
        resp = api.seal_recycling_batch(batch["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECYCLING_EMPTY)
        reread = validate_success(api.get_recycling_batch(batch["id"], ADMIN), 200)
        assert reread["status"] == "ACCUMULATING"


class TestImpactReport:
    def _setup_zone_with_two_distributions(self, api):
        """Zone (cap 100) with 4 GOOD ADULT_TOPS stocked, then 2 distributed to
        one client in a single visit, all inside the trailing 28-day window."""
        env = setup_stocked_items([dict(GOOD_TOPS) for _ in range(4)],
                                  zone_code="ZA", capacity_items=100)
        headers = env["staff"]["headers"]
        client = register_client("Client A", 3, None, headers)
        visit = checkin_visit(client["id"], headers)
        add_lines(visit["id"], [env["items"][0]["id"], env["items"][1]["id"]], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)
        return env

    def test_turnover_current_and_average_basis_diverge(self, api):
        """PRD: "Two turnover ratios are reported: `turnover_current_basis`
        divides `window_distributed` by the live `current_stock`, substituting a
        denominator of 1 when the shelf stands empty; `turnover_average_basis`
        divides `window_distributed` by the mean of `stock_at_window_start` and
        `current_stock` rounded half up to a whole number, again substituting 1
        when that mean is zero."
        PRD: "Both ratios are reported at four decimal places, rounded half up"

        Design: Difficulty/dual_variant_calc/zone_turnover_current_vs_average_basis
        """
        env = self._setup_zone_with_two_distributions(api)

        report = validate_success(api.get_impact_report(env["zone"]["id"], ADMIN), 200)
        assert report["zone_id"] == env["zone"]["id"]
        assert report["window_distributed"] == 2
        assert report["turnover_current_basis"] == pytest.approx(1.0, abs=1e-4), (
            "2 / max(1, 2)")
        assert report["turnover_average_basis"] == pytest.approx(2.0, abs=1e-4), (
            "2 / round_half_up((0 + 2) / 2)")
        assert report["turnover_current_basis"] != pytest.approx(
            report["turnover_average_basis"]), (
            "the two bases diverge for identical underlying data")

    def test_turnover_window_components(self, api):
        """PRD: "For the addressed zone, `window_distributed` counts items whose
        `distributed_from_zone_id` names the zone and whose `distributed_at`
        falls inside the window; `window_stocked` counts items whose `stocked_at`
        falls inside the window and which either still name the zone in
        `storage_zone_id` or left it via distribution — an item stocked into the
        zone and distributed within the window counts on both sides. From those,
        `stock_at_window_start` is the zone's live `current_stock` plus
        `window_distributed` minus `window_stocked`."

        Design: Difficulty/dual_variant_calc/zone_turnover_current_vs_average_basis
        """
        env = self._setup_zone_with_two_distributions(api)

        report = validate_success(api.get_impact_report(env["zone"]["id"], ADMIN), 200)
        assert report["current_stock"] == 2
        assert report["window_distributed"] == 2
        assert report["window_stocked"] == 4, "all four stocked in-window, two also left"
        assert report["stock_at_window_start"] == 0, "2 + 2 - 4"

    def test_reports_impact_global_totals(self, api):
        """PRD: "The same response carries network-wide totals:
        `items_distributed_total`, `unique_clients_served`,
        `recycled_items_total`, `recycling_provisional_credit_cents_total`, and
        `recycling_final_credit_cents_total`."

        Design: Corner/endpoints/reports_impact_global_totals
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="ZRP", capacity_items=5)
        headers = env["staff"]["headers"]
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        add_lines(visit["id"], [env["items"][0]["id"]], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)

        report = validate_success(api.get_impact_report(env["zone"]["id"], ADMIN), 200)
        assert report["items_distributed_total"] == 1
        assert report["unique_clients_served"] == 1
        assert report["recycled_items_total"] == 0
        assert report["recycling_provisional_credit_cents_total"] == 0
        assert report["recycling_final_credit_cents_total"] == 0
