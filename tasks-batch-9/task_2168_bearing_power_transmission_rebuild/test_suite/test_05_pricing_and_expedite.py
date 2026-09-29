# -*- coding: utf-8 -*-
"""The eight-step pricing chain, the emergency lane and its tiered surcharge."""
import pytest

from test_helpers import (
    FOUR_BANDS, PLANNER_1, ApiErrorId, add_approved_part_line,
    api_client as api, assert_quoted_order_arithmetic, create_core, create_order,
    inspect_order, order_action, quote_order, read_order, read_quote, setup_shop,
    validate_error, validate_success,
)


def _graded_and_quoted_world():
    world = setup_shop(account_code="NGM-004", asset_tag="CONV-04-GBX",
                       feature_bands=FOUR_BANDS, serial_no="SN-77004",
                       rebuild_count=1, declared_condition_grade="GRADE_D",
                       labor_hours=6.5)
    quote_order(world)
    inspect_order(world)
    return world


class TestExpediteSurchargeAndCreditCap:

    def test_the_surcharge_tier_is_chosen_on_the_pre_credit_subtotal(self):
        """PRD 3.8: "Fourth comes the emergency surcharge, and its tier is chosen on
        `pre_credit_subtotal_cents` — never on the gross total and never on the quote total."
        PRD 3.8: "An expedited order takes a percentage of the pre-credit subtotal: thirty
        percent when that subtotal is below $1,000.00, twenty-two percent when it is at least
        $1,000.00 but below $5,000.00, and fifteen percent when it is $5,000.00 or above."
        PRD 3.8: "That percentage of the subtotal is rounded half up to whole cents and a flat
        emergency callout of $250.00 is added on top; the sum is `expedite_surcharge_cents`."
        PRD 3.8: "Fifth, `gross_total_cents` is the pre-credit subtotal plus the surcharge."

        Design: Difficulty/combinatorial_formula/expedite_surcharge_tier_then_credit_cap_evaluation_order
        """
        world = _graded_and_quoted_world()
        order_id = world["order"]["id"]

        expedited = validate_success(api.expedite_rebuild_order(
            order_id, {"expedite_reason": "line down", "emergency_ref": "EM-4471"},
            PLANNER_1))
        assert expedited["expedited"] is True

        order = read_order(order_id)
        assert order["pre_credit_subtotal_cents"] == 171250
        assert order["expedite_surcharge_cents"] == 62675, (
            "a 171250-cent subtotal sits in the twenty-two percent band: "
            "37675 plus the 25000 emergency callout"
        )
        assert order["gross_total_cents"] == 233925
        assert order["work_status"] == "QUOTED"

    def test_the_credit_cap_is_floored_on_the_post_surcharge_gross_total(self):
        """PRD 3.8: "Sixth, the exchange-core credit is capped. The cap is forty percent of
        `gross_total_cents`, truncated downward to a whole cent rather than rounded — this is
        the one place in the document where a floor replaces round-half-up on money — and it is
        surfaced on the quote read as `credit_cap_cents`."
        PRD 3.8: "Seventh, the draw-down: `core_credit_applied_cents` is the smaller of the
        account's `total_credit_balance_cents` at that instant and the cap, and
        `quote_total_cents` is the gross total less the applied credit."
        PRD 3.8: "expediting an order already in `QUOTED` re-runs the entire eight-step chain so
        that `expedite_surcharge_cents`, `gross_total_cents`, `core_credit_applied_cents` and
        `quote_total_cents` all move together, and re-snapshots `quoted_part_revision`."

        Design: Difficulty/combinatorial_formula/expedite_surcharge_tier_then_credit_cap_evaluation_order
        """
        world = _graded_and_quoted_world()
        order_id = world["order"]["id"]
        validate_success(api.expedite_rebuild_order(
            order_id, {"expedite_reason": "line down", "emergency_ref": "EM-4471"},
            PLANNER_1))

        quote = read_quote(order_id)
        assert quote["credit_cap_cents"] == 93570, "floor(233925 * 0.40)"

        order = read_order(order_id)
        assert order["core_credit_applied_cents"] == 81450, (
            "the account holds 81450 after grading, which is below the 93570 cap"
        )
        assert order["quote_total_cents"] == 152475
        assert_quoted_order_arithmetic(order)

    def test_the_surcharge_schedule_is_non_monotonic_across_the_first_tier_floor(self):
        """PRD 3.8: "Both tier floors are inclusive, which makes the schedule deliberately
        non-monotonic across the first edge: a subtotal of exactly $1,000.00 is charged at
        twenty-two percent while one cent less is charged at thirty percent."
        PRD 3.2: "the base value is multiplied by the grade multiplier — 1.00 for `GRADE_A`,
        0.75 for `GRADE_B`, 0.45 for `GRADE_C`, 0.20 for `GRADE_D`, and 0.00 for `SCRAP` — and
        that product is rounded half up to whole cents."

        Design: Corner/calculations/expedite_low_tier_applies_thirty_percent_below_the_hundred_thousand_floor
        """
        world = setup_shop(account_code="TIR-001", customer_name="Tier Mill",
                           asset_tag="TIR-01-GBX", serial_no="SN-TIR-1",
                           declared_condition_grade="SCRAP", labor_hours=2.0)
        cust_id, asset_id = world["customer"]["id"], world["asset"]["id"]
        core_hi = create_core(cust_id, world["standard"]["id"], serial_no="SN-TIR-2",
                              declared_condition_grade="SCRAP")
        order_lo = world["order"]
        order_hi = create_order(cust_id, core_hi["id"], asset_id, labor_hours=2.0)

        add_approved_part_line(order_lo["id"], cust_id, part_no="KIT-LO",
                               source_class="OEM", qty=1, unit_cost_cents=70999)
        add_approved_part_line(order_hi["id"], cust_id, part_no="KIT-HI",
                               source_class="OEM", qty=1, unit_cost_cents=71000)
        order_action(order_lo["id"], "QUOTE")
        order_action(order_hi["id"], "QUOTE")

        validate_success(api.expedite_rebuild_order(
            order_lo["id"], {"expedite_reason": "line down"}, PLANNER_1))
        validate_success(api.expedite_rebuild_order(
            order_hi["id"], {"expedite_reason": "line down"}, PLANNER_1))

        lo = read_order(order_lo["id"])
        assert lo["pre_credit_subtotal_cents"] == 99999
        assert lo["expedite_surcharge_cents"] == 55000, "0.30 of 99999 is 30000 plus 25000"
        assert lo["gross_total_cents"] == 154999
        assert lo["quote_total_cents"] == 154999

        hi = read_order(order_hi["id"])
        assert hi["pre_credit_subtotal_cents"] == 100000
        assert hi["expedite_surcharge_cents"] == 47000, "0.22 of 100000 is 22000 plus 25000"
        assert hi["gross_total_cents"] == 147000
        assert hi["quote_total_cents"] == 147000

        assert hi["expedite_surcharge_cents"] < lo["expedite_surcharge_cents"], (
            "a larger job carries the smaller surcharge across the inclusive floor"
        )
        from test_helpers import read_customer
        assert read_customer(cust_id)["total_credit_balance_cents"] == 0
        assert lo["work_status"] == "QUOTED" and lo["expedited"] is True
        assert hi["work_status"] == "QUOTED" and hi["expedited"] is True

    def test_expedite_is_a_one_shot_flag_on_a_draft_order(self):
        """PRD 3.8: "Expediting is how the emergency lane is entered, and it is available only
        once per order and only while the order is in `DRAFT` or `QUOTED` with `expedited` still
        false; any other attempt is `ERR_EXPEDITE_NOT_AVAILABLE` (HTTP 409)."
        PRD 3.8: "What happens next depends on where the order stands: expediting an order still
        in `DRAFT` writes no quote figures at all, because none exist yet, whereas expediting an
        order already in `QUOTED` re-runs the entire eight-step chain"
        PRD 3.7: "A new order starts with `work_status` of `DRAFT`, `approval_status` of
        `PENDING`, `part_revision_counter` at 0, `expedited` false, and `expedite_reason`,
        `emergency_ref`, `quoted_part_revision`, `cancel_reason` and every quote figure"

        Design: Corner/errors/second_expedite_on_the_same_order_is_rejected
        """
        world = setup_shop(account_code="RSH-001", customer_name="Rush Mill",
                           asset_tag="RSH-01-GBX", serial_no="SN-RSH-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        order_id = world["order"]["id"]

        first = validate_success(api.expedite_rebuild_order(
            order_id, {"expedite_reason": "line down", "emergency_ref": "EM-0001"},
            PLANNER_1))
        assert first["expedited"] is True
        assert first["expedite_reason"] == "line down"
        assert first["emergency_ref"] == "EM-0001"

        after_first = read_order(order_id)
        assert after_first["work_status"] == "DRAFT"
        assert after_first["expedite_surcharge_cents"] is None

        validate_error(api.expedite_rebuild_order(
            order_id, {"expedite_reason": "still down"}, PLANNER_1),
            ApiErrorId.ERR_EXPEDITE_NOT_AVAILABLE.value, 409)
        assert read_order(order_id)["expedite_reason"] == "line down"
