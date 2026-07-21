"""Inventory & aging: projected vs actual shrink, ready-at-min-aging boundary, over-shrink
discard cascade, fulfill-depletes-lot cascade, receive system fields, cave usage, capacity."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_product, create_cave, receive_lot, create_ready_lot,
    setup_paid_retail_order, create_lot_payload, TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── dual_variant_calc / lot_shrink_projected_vs_actual_on_lot ─────────────
class TestLotShrinkProjectedVsActual:
    def _age_lot(self, api):
        set_clock("2026-07-01T00:00:00Z")
        product = create_product(name="Tomme", price_per_kg_cents=3000,
                                 target_aging_days=180, shrink_pct_per_day=0.001)
        cave = create_cave(name="Cave 2")
        lot = receive_lot(product["id"], cave["id"], 1000)
        set_clock("2026-09-29T00:00:00Z")   # +90 days
        api.rotate_cave(cave["id"], SM)
        set_clock("2026-12-28T00:00:00Z")   # +180 days
        api.rotate_cave(cave["id"], SM)
        return get_success_data(api.get_lot(lot["id"], SM))

    def test_actual_shrink_accumulates_on_diminishing_weight(self, api):
        """PRD §3.2: "The realized per-run shrink for a lot is its **current** weight multiplied
        by the product's daily shrink rate multiplied by the number of days aged since the last
        run — that is, the difference between the lot's present `aging_days` and its stored
        `last_aged_days` — rounded half up to whole grams."

        Design: Difficulty/dual_variant_calc/lot_shrink_projected_vs_actual_on_lot
        """
        lot = self._age_lot(api)
        # run1: round(1000*0.001*90)=90 -> current 910; run2: round(910*0.001*90)=82 -> current 828.
        assert lot["current_weight_g"] == 828
        assert lot["cumulative_shrink_g"] == 172

    def test_projected_ready_weight_is_one_shot_on_received(self, api):
        """PRD §3.2: "At the moment of receipt the system also computes a one-shot **projected
        ready weight**, `projected_ready_weight_g`: the received weight multiplied by one minus
        the product's daily shrink rate times the product's target aging days, rounded half up
        to whole grams."

        Design: Difficulty/dual_variant_calc/lot_shrink_projected_vs_actual_on_lot
        """
        lot = self._age_lot(api)
        # round(1000*(1 - 0.001*180)) = round(820) = 820, distinct from the realized 828.
        assert lot["projected_ready_weight_g"] == 820
        assert lot["projected_ready_weight_g"] != lot["current_weight_g"]


# ─── boundary_precision_check / lot_ready_at_exact_min_aging_days ───────────
class TestLotReadyAtExactMinAging:
    def _rotate_at_120(self, api):
        set_clock("2026-07-01T00:00:00Z")
        product = create_product(name="Aged Alpine", min_aging_days=120,
                                 target_aging_days=180, shrink_pct_per_day=0)
        cave = create_cave(name="Cave 11")
        lot = receive_lot(product["id"], cave["id"], 1000)
        set_clock("2026-10-29T00:00:00Z")   # exactly +120 days
        api.rotate_cave(cave["id"], SM)
        return get_success_data(api.get_lot(lot["id"], SM))

    def test_flips_ready_at_exact_min_aging(self, api):
        """PRD §3.2: "an `AGING` lot whose `aging_days` has reached its product's
        `min_aging_days` — the boundary is inclusive, so a lot exactly at the minimum flips —
        and whose cumulative shrink is still strictly below the 35-percent ceiling transitions
        `AGING → READY` and becomes sellable."

        Design: Difficulty/boundary_precision_check/lot_ready_at_exact_min_aging_days
        """
        lot = self._rotate_at_120(api)
        assert lot["aging_days"] == 120
        assert lot["status"] == "READY"

    def test_aging_days_reported_exactly_at_boundary(self, api):
        """PRD §2.5: "A lot's age in whole days, `aging_days`, is the number of complete days
        between its `aging_start_date` and the current clock instant — that is, the elapsed
        time floored to whole days."

        Design: Difficulty/boundary_precision_check/lot_ready_at_exact_min_aging_days
        """
        lot = self._rotate_at_120(api)
        assert lot["aging_days"] == 120
        assert lot["status"] == "READY"


# ─── transitive_cascade / rotation_shrink_discards_lot_updates_cave ────────
class TestRotationDiscardsOverShrunkLot:
    def _rotate_to_discard(self, api):
        set_clock("2026-07-01T00:00:00Z")
        product = create_product(name="Fresh Chevre", milk_type="GOAT",
                                 target_aging_days=30, shrink_pct_per_day=0.02)
        cave = create_cave(name="Cave 8")
        lot = receive_lot(product["id"], cave["id"], 1000)
        set_clock("2026-07-21T00:00:00Z")   # +20 days
        api.rotate_cave(cave["id"], SM)
        return lot, cave

    def test_over_shrunk_lot_discarded(self, api):
        """PRD §3.2: "If the lot's cumulative shrink has reached or exceeded 35 percent of its
        received weight (`LOT_MAX_SHRINK_PCT` = 0.35), the lot is over-shrunk and transitions
        to `DISCARDED`, leaving inventory."

        Design: Difficulty/transitive_cascade/rotation_shrink_discards_lot_updates_cave
        """
        lot, _ = self._rotate_to_discard(api)
        result = get_success_data(api.get_lot(lot["id"], SM))
        # round(1000*0.02*20) = 400 >= 0.35*1000 = 350 -> DISCARDED.
        assert result["cumulative_shrink_g"] == 400
        assert result["status"] == "DISCARDED"

    def test_discarded_lot_excluded_from_cave_usage(self, api):
        """PRD §2.8: "A cave's `used_g` is the sum of `current_weight_g` across the lots it
        holds whose `status` is either `AGING` or `READY`; lots that are `DEPLETED` or
        `DISCARDED` are excluded from that sum."

        Design: Difficulty/transitive_cascade/rotation_shrink_discards_lot_updates_cave
        """
        _, cave = self._rotate_to_discard(api)
        result = get_success_data(api.get_cave(cave["id"], SM))
        assert result["used_g"] == 0


# ─── transitive_cascade / fulfill_order_depletes_lot_updates_cave ──────────
class TestFulfillDepletesLot:
    def _fulfill_full_lot(self, api):
        sc = setup_paid_retail_order(price_per_kg_cents=3000, requested_weight_g=500,
                                     received_weight_g=500)
        api.fulfill_order(sc["order"]["id"],
                          {"line_actuals": [{"line_id": sc["line"]["id"], "actual_cut_weight_g": 500}]}, CS)
        return sc

    def test_full_consumption_depletes_lot(self, api):
        """PRD §3.5: "As a cascade, any lot whose `available_weight_g` reaches zero after this
        consumption transitions `READY → DEPLETED`, and the affected cave's `used_g` and
        `available_g` are recomputed."

        Design: Difficulty/transitive_cascade/fulfill_order_depletes_lot_updates_cave
        """
        sc = self._fulfill_full_lot(api)
        lot = get_success_data(api.get_lot(sc["lot"]["id"], CS))
        assert lot["status"] == "DEPLETED"
        assert lot["current_weight_g"] == 0
        assert lot["consumed_weight_g"] == 500

    def test_cave_usage_recomputed_to_zero(self, api):
        """PRD §2.8: "A cave's `used_g` is the sum of `current_weight_g` across the lots it
        holds whose `status` is either `AGING` or `READY`; lots that are `DEPLETED` or
        `DISCARDED` are excluded from that sum."

        Design: Difficulty/transitive_cascade/fulfill_order_depletes_lot_updates_cave
        """
        sc = self._fulfill_full_lot(api)
        cave = get_success_data(api.get_cave(sc["cave"]["id"], SM))
        assert cave["used_g"] == 0


# ─── Corner: entities / corner_lot_receive_sets_system_fields ──────────────
def test_lot_receive_sets_system_fields(api):
    """PRD §3.2: "At receipt the lot is stamped `AGING`, its `aging_start_date` is set to the
    current clock instant, its `current_weight_g` is set to the received weight, its
    `cumulative_shrink_g` is 0, and its `last_aged_days` is 0."

    Design: Corner/entities/corner_lot_receive_sets_system_fields
    """
    set_clock("2026-07-01T00:00:00Z")
    product = create_product(name="Recv Cheese", target_aging_days=100, shrink_pct_per_day=0.001)
    cave = create_cave(name="Cave R")
    res = api.receive_lot(create_lot_payload(product["id"], cave["id"], 1000), SM)
    lot = validate_success(res, 201)
    assert lot["current_weight_g"] == 1000
    assert lot["status"] == "AGING"
    # round(1000*(1 - 0.001*100)) = round(900) = 900.
    assert lot["projected_ready_weight_g"] == 900


# ─── Corner: calculations / corner_cave_usage_after_receive ────────────────
def test_cave_usage_after_receive(api):
    """PRD §2.8: "A cave's `available_g` is its `capacity_g` minus `used_g`, never allowed to
    fall below zero."

    Design: Corner/calculations/corner_cave_usage_after_receive
    """
    product = create_product(name="Usage Cheese", form="BLOCK")
    cave = create_cave(name="Cave U", capacity_g=10000)
    receive_lot(product["id"], cave["id"], 4000)
    result = get_success_data(api.get_cave(cave["id"], SM))
    assert result["used_g"] == 4000
    assert result["available_g"] == 6000


# ─── Corner: validations / corner_receive_lot_exceeds_cave_capacity ────────
def test_receive_lot_exceeds_cave_capacity(api):
    """PRD §3.2: "Receiving is refused if it would push the cave over capacity — that is, the
    received weight must not exceed the cave's `available_g` — otherwise the receipt is rejected
    with `ERR_CAVE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_receive_lot_exceeds_cave_capacity
    """
    product = create_product(name="CC Cheese")
    cave = create_cave(name="Small Cave", capacity_g=500)
    res = api.receive_lot(create_lot_payload(product["id"], cave["id"], 1000), SM)
    validate_error(res, "ERR_CAVE_CAPACITY_EXCEEDED")
