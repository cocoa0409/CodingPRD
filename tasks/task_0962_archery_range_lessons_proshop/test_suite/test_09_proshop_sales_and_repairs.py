"""Pro-shop sales rounding/stock, and the repair bench quote workflow."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_sale_invariants,
    create_repair_order,
    create_sale_payload,
    create_shop_product,
    get_product_stock,
    get_repair_order,
    make_member_headers,
    quote_repair_order,
    register_member,
    set_clock,
    validate_error,
    validate_success,
)

SHOP_CLERK = TEST_USERS["shop_clerk_headers"]


class TestSaleTotalPinnedRoundingOrder:
    def _setup_products(self, api):
        product_a = create_shop_product("Arrow A", "ARR-A", 333, 100)
        product_b = create_shop_product("Broadhead B", "BRD-B", 777, 100)
        return product_a, product_b

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.9: "The total is computed with a pinned rounding order: first
        each line's gross is the quantity times the product's current
        `unit_price_cents` times one minus the line discount, rounded half up,
        collected in input order as `line_gross_cents`; then `subtotal_cents` is
        the sum of those already-rounded line grosses — per-line rounding first,
        summation second".

        Design: Difficulty/combinatorial_formula/sale_total_per_line_rounding_order
        """
        product_a, product_b = self._setup_products(api)
        resp = api.create_sale(
            create_sale_payload(
                [
                    {"product_id": product_a["id"], "qty": 1,
                     "line_discount_pct": 0.05},
                    {"product_id": product_b["id"], "qty": 1,
                     "line_discount_pct": 0.05},
                ]
            ),
            SHOP_CLERK,
        )
        sale = validate_success(resp, 201)
        # round_half_up(316.35) = 316; round_half_up(738.15) = 738.
        assert sale["line_gross_cents"] == [316, 738]
        # Per-line-then-sum pins 1054; sum-then-round would give 1055.
        assert sale["subtotal_cents"] == 1054

    def test_tax_and_total_on_discounted_base_and_stock_decrement(self, api):
        """PRD §3.9: "then `volume_discount_cents` is 10% of the subtotal
        rounded half up, but only when the subtotal reaches 10000 cents,
        otherwise 0; then `tax_cents` is 8.25% of the taxable base — subtotal
        minus volume discount — rounded half up; and `total_cents` is the
        taxable base plus the tax."
        PRD §3.9: "Stock is decremented per line by its quantity".

        Design: Difficulty/combinatorial_formula/sale_total_per_line_rounding_order
        """
        product_a, product_b = self._setup_products(api)
        resp = api.create_sale(
            create_sale_payload(
                [
                    {"product_id": product_a["id"], "qty": 1,
                     "line_discount_pct": 0.05},
                    {"product_id": product_b["id"], "qty": 1,
                     "line_discount_pct": 0.05},
                ]
            ),
            SHOP_CLERK,
        )
        sale = validate_success(resp, 201)
        assert sale["volume_discount_cents"] == 0, "1054 < 10000 threshold"
        # round_half_up(1054 x 0.0825) = round_half_up(86.955) = 87.
        assert sale["tax_cents"] == 87
        assert sale["total_cents"] == 1141
        assert_sale_invariants(sale)
        assert get_product_stock(product_a["id"]) == 99
        assert get_product_stock(product_b["id"]) == 99


class TestSaleImmediateConsistencyAndStock:
    def test_sale_response_contains_computed_totals_immediately(self, api):
        """PRD §3.9: "then `tax_cents` is 8.25% of the taxable base — subtotal
        minus volume discount — rounded half up; and `total_cents` is the
        taxable base plus the tax."
        PRD §3.9: "Stock is decremented per line by its quantity".
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/sale_response_contains_computed_totals_immediately
        """
        product = create_shop_product("Target Face", "TF-1", 1000, 10)
        resp = api.create_sale(
            create_sale_payload([{"product_id": product["id"], "qty": 2}]),
            SHOP_CLERK,
        )
        sale = validate_success(resp, 201)
        assert sale["subtotal_cents"] == 2000
        assert sale["volume_discount_cents"] == 0
        assert sale["tax_cents"] == 165, "round_half_up(2000 x 0.0825)"
        assert sale["total_cents"] == 2165
        assert get_product_stock(product["id"]) == 8

    def test_sale_with_insufficient_stock_rejected(self, api):
        """PRD §3.9: "if any single line exceeds the product's on-hand
        `stock_quantity` the **whole** sale is rejected with
        `ERR_INSUFFICIENT_STOCK` — there are no partial sales."

        Design: Corner/validations/sale_with_insufficient_stock_rejected
        """
        product = create_shop_product("Rare Vanes", "RV-1", 500, 3)
        resp = api.create_sale(
            create_sale_payload([{"product_id": product["id"], "qty": 5}]),
            SHOP_CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        assert get_product_stock(product["id"]) == 3, "stock must be unchanged"
        sales = validate_success(api.list_sales(SHOP_CLERK), 200)
        assert sales == [], "no sale may be persisted"


class TestRepairQuote:
    def test_repair_quote_rush_fee_and_tier_discount(self, api):
        """PRD §3.9: "`parts_total_cents` is the sum of each part's quantity
        times the product's `unit_price_cents` at quote time. Labor is billed in
        30-minute blocks at 1500 cents per block: `labor_minutes` divided by 30
        rounded up gives the block count; the block count times 1500 is
        discounted by the owner's membership tier with round half up; and when
        `promised_hours` is under 48, a rush fee of 25% of the discounted labor,
        rounded half up, is added on top — at 48 hours or more there is no rush
        fee."
        PRD §3.9: "Quoting reserves the parts — decrementing each product's
        `stock_quantity` by the reserved quantity".

        Design: Corner/calculations/repair_quote_rush_fee_and_tier_discount
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("fix@x.com", full_name="Fix Owner", tier="ELITE")
        p1 = create_shop_product("Limbs", "LMB-1", 4000, 5)
        p2 = create_shop_product("String", "STR-1", 1500, 2)
        order = create_repair_order(member["id"], "cracked limb")

        quoted = quote_repair_order(
            order["id"],
            [{"product_id": p1["id"], "qty": 1},
             {"product_id": p2["id"], "qty": 2}],
            labor_minutes=75,
            promised_hours=24,
            expected_version=order["version"],
        )
        assert quoted["parts_total_cents"] == 7000
        # ceil(75/30) = 3 blocks x 1500 = 4500; ELITE 20% -> 3600;
        # rush 25% of 3600 = 900; labor_total 4500.
        assert quoted["labor_total_cents"] == 4500
        assert quoted["quote_total_cents"] == 11500
        assert quoted["status"] == "QUOTED"
        assert get_product_stock(p1["id"]) == 4
        assert get_product_stock(p2["id"]) == 0

    def test_occ_stale_repair_quote_rejected(self, api):
        """PRD §2.7: "Posting a quote against a repair order must carry
        `expected_repair_order_version` holding the client's last observed
        `version` of that repair order. A mismatch with the order's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the
        newer quote legitimately supersedes the older one and the stale writer
        must re-read before quoting."
        PRD §3.9: "Quoting — also `ShopClerk` — is valid from `INTAKE`, or again
        from `QUOTED` to supersede a prior quote".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_repair_quote_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("rq@x.com", full_name="Requote Owner")
        product = create_shop_product("Riser", "RSR-1", 4000, 5)
        order = create_repair_order(member["id"], "bent riser")
        stale_version = order["version"]

        first = quote_repair_order(
            order["id"], [{"product_id": product["id"], "qty": 1}],
            labor_minutes=30, promised_hours=72,
            expected_version=stale_version,
        )
        current_version = first["version"]
        assert current_version == stale_version + 1

        # Replaying the pre-quote version is stale.
        resp = api.quote_repair_order(
            order["id"],
            {
                "parts": [{"product_id": product["id"], "qty": 2}],
                "labor_minutes": 60,
                "promised_hours": 72,
                "expected_repair_order_version": stale_version,
            },
            SHOP_CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # A quote carrying the current version supersedes successfully.
        third = quote_repair_order(
            order["id"], [{"product_id": product["id"], "qty": 2}],
            labor_minutes=60, promised_hours=72,
            expected_version=current_version,
        )
        # parts 2 x 4000 = 8000; labor 2 blocks x 1500 = 3000 (BASIC, no rush).
        assert third["quote_total_cents"] == 11000

    def test_quote_supersede_releases_prior_parts_reservation(self, api):
        """PRD §3.9: "Quoting — also `ShopClerk` — is valid from `INTAKE`, or
        again from `QUOTED` to supersede a prior quote".
        PRD §3.9: "The quote names `parts` — each entry a `product_id` with a
        `qty` of at least 1, recorded on the order as `parts_reserved`".
        PRD §3.9: "Quoting reserves the parts — decrementing each product's
        `stock_quantity` by the reserved quantity (`ERR_INSUFFICIENT_STOCK` if
        any part is short), with the stock held until the order is declined or
        picked up".
        PRD §3.9: "`stock_quantity` thereafter tracks on-hand minus sold minus
        repair-reserved and is never allowed to go negative."

        Design: Corner/cross_cutting_complexity_layers/quote_supersede_releases_prior_parts_reservation
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member("rel@x.com", full_name="Release Owner")
        product = create_shop_product("Cam", "CAM-1", 2000, 5)
        order = create_repair_order(member["id"], "cam timing")

        first = quote_repair_order(
            order["id"], [{"product_id": product["id"], "qty": 1}],
            labor_minutes=30, promised_hours=72,
            expected_version=order["version"],
        )
        assert get_product_stock(product["id"]) == 4, "quote1 holds one unit"

        quote_repair_order(
            order["id"], [{"product_id": product["id"], "qty": 2}],
            labor_minutes=30, promised_hours=72,
            expected_version=first["version"],
        )
        # The superseded quote's hold is gone; only the new 2-unit hold remains.
        assert get_product_stock(product["id"]) == 3


class TestRepairApprovalOwnership:
    def test_member_cannot_approve_others_repair(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        `Member` — a session's creator, a participant's archer, a punch card's
        owner, a rental's renter, a lesson's student, a league entry's entrant,
        a repair order's equipment owner — compare the resource's foreign-key
        field to `X-User-ID`, and a member acting on another member's resource
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.9: "The equipment owner then decides: approving moves `QUOTED` to
        `IN_REPAIR` with the parts remaining reserved, while declining moves
        `QUOTED` to `DECLINED` and releases the reserved stock back to each
        product's `stock_quantity`; both are member actions on their own order".

        Design: Corner/rbac/member_cannot_approve_others_repair
        """
        set_clock("2026-05-01T08:00:00Z")
        owner = register_member("own1@x.com", full_name="Owner One")
        other = register_member("own2@x.com", full_name="Owner Two")
        order = create_repair_order(owner["id"], "loose sight")
        quote_repair_order(
            order["id"], [], labor_minutes=30, promised_hours=72,
            expected_version=order["version"],
        )

        resp = api.approve_repair_order(
            order["id"], make_member_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_repair_order(order["id"])["status"] == "QUOTED"
