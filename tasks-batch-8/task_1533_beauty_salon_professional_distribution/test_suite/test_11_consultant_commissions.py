"""Consultant commission variants: STRAIGHT vs ACCELERATOR (PRD §3.10)."""
from test_helpers import (
    TEST_USERS,
    create_active_salon,
    create_delivered_order,
    make_brand,
    make_consultant,
    make_product,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _deliver_for_consultant(api, commission_model):
    """ACTIVE SILVER salon attributed to a consultant of the given model;
    delivers one order of 10 x RETAIL 10000-cent units (net 100000)."""
    consultant = make_consultant(commission_model=commission_model)
    salon, _ = create_active_salon(consultant=consultant)
    brand = make_brand()
    product = make_product(brand["id"], base_price_cents=10000,
                           weight_grams=100)
    create_delivered_order(
        salon["id"], [{"product_id": product["id"], "quantity": 10}])
    return consultant


class TestCommissionVariants:
    def test_straight_commission_five_percent_of_net(self, api):
        """PRD §3.10: "Commission is attributed when an order reaches
        `DELIVERED`, to the salon's `assigned_consultant_id`; attribution is
        skipped when that field is null or the consultant is `INACTIVE`. The
        base is the delivered order's `net_merch_cents`."
        PRD §3.10: "Under the `STRAIGHT` variant, the commission is 5 percent
        of the base, rounded half-up to integer cents."

        Design: Difficulty/dual_variant_calc/consultant_commission_straight_vs_accelerator
        """
        consultant = _deliver_for_consultant(api, "STRAIGHT")
        refreshed = validate_success(
            api.get_sales_consultant(consultant["id"], ADMIN), 200)
        assert refreshed["commission_accrued_cents"] == 5000, (
            "round_half_up(100000 * 0.05) == 5000")

    def test_accelerator_commission_marginal_first_tier(self, api):
        """PRD §3.10: "Let the consultant's month-to-date delivered volume
        before this order be the running volume; the portion of the order's
        base falling below 1000000 cents of cumulative volume earns 4 percent,
        the portion from 1000000 up to 3000000 cents earns 6 percent, and the
        portion at or beyond 3000000 cents earns 8 percent — the order's base
        can straddle a boundary, in which case each slice earns its own rate."

        Design: Difficulty/dual_variant_calc/consultant_commission_straight_vs_accelerator
        """
        consultant = _deliver_for_consultant(api, "ACCELERATOR")
        refreshed = validate_success(
            api.get_sales_consultant(consultant["id"], ADMIN), 200)
        assert refreshed["commission_accrued_cents"] == 4000, (
            "an empty monthly volume earns 4 percent on all of 100000")
        assert refreshed["commission_month_volume_cents"] == 100000, (
            "the order's base is added to the month-to-date volume")
