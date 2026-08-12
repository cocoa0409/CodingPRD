"""Revenue division bases, pinned rounding order, basis shape rules,
uniqueness per waybill, and the settle cascade back onto the waybill
(PRD §2.7, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_customer,
    create_railcar,
    create_waybill,
    setup_arrived_movement,
    setup_rated_waybill,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _rated_grain_through_pair():
    """Two identical RATED GRAIN 100-ton through waybills (our 87 of 241 miles)."""
    customer = create_customer(name="Lake Grain Coop", billing_email="ap@lakegrain.example")
    rc1 = create_railcar(reporting_mark="GNWR 6001", car_type="HOPPER")
    rc2 = create_railcar(reporting_mark="GNWR 6002", car_type="HOPPER")
    wb1 = create_waybill(rc1["id"], customer["id"], destination="CSX Buffalo Frontier Yard",
                         commodity="GRAIN", weight_tons=100, through_route=True,
                         our_miles=87, total_miles=241)
    wb1 = validate_success(api_client.rate_waybill(wb1["id"], CLERK))
    wb2 = create_waybill(rc2["id"], customer["id"], destination="CSX Buffalo Frontier Yard",
                         commodity="GRAIN", weight_tons=100, through_route=True,
                         our_miles=87, total_miles=241)
    wb2 = validate_success(api_client.rate_waybill(wb2["id"], CLERK))
    return wb1, wb2


class TestDivisionBases:
    def test_division_mileage_prorate_split(self, api, settlement_clerk_headers):
        """PRD §3.5: "Under `MILEAGE_PRORATE`, `our_share_cents` is the total
        charge times `our_miles` divided by `total_miles`, rounded half up to
        whole cents. Under `AGREED_PERCENTAGE`, `our_share_cents` is the total
        charge times `agreed_pct`, rounded half up to whole cents — identical
        waybill data yields a different split under the two bases. In both bases,
        `connecting_share_cents` is the total charge minus our rounded share; the
        connecting road's share is never rounded independently."

        Design: Difficulty/dual_variant_calc/revenue_division_prorate_vs_agreed
        """
        wb1, _wb2 = _rated_grain_through_pair()
        div = validate_success(
            api.create_revenue_division({"waybill_id": wb1["id"], "basis": "MILEAGE_PRORATE"},
                                        settlement_clerk_headers),
            expected_status=201,
        )
        assert div["total_charge_cents"] == 3850000
        assert div["our_share_cents"] == 1389834, (
            f"round_half_up(3850000 * 87 / 241) must yield 1389834, got {div['our_share_cents']}"
        )
        assert div["connecting_share_cents"] == 2460166, (
            f"3850000 - 1389834 must yield 2460166, got {div['connecting_share_cents']}"
        )
        assert div["our_share_cents"] + div["connecting_share_cents"] == 3850000

    def test_division_agreed_percentage_split(self, api, settlement_clerk_headers):
        """PRD §3.5: "Under `MILEAGE_PRORATE`, `our_share_cents` is the total
        charge times `our_miles` divided by `total_miles`, rounded half up to
        whole cents. Under `AGREED_PERCENTAGE`, `our_share_cents` is the total
        charge times `agreed_pct`, rounded half up to whole cents — identical
        waybill data yields a different split under the two bases. In both bases,
        `connecting_share_cents` is the total charge minus our rounded share; the
        connecting road's share is never rounded independently."

        Design: Difficulty/dual_variant_calc/revenue_division_prorate_vs_agreed
        """
        _wb1, wb2 = _rated_grain_through_pair()
        div = validate_success(
            api.create_revenue_division(
                {"waybill_id": wb2["id"], "basis": "AGREED_PERCENTAGE", "agreed_pct": 0.35},
                settlement_clerk_headers,
            ),
            expected_status=201,
        )
        assert div["our_share_cents"] == 1347500, (
            f"round_half_up(3850000 * 0.35) must yield 1347500, got {div['our_share_cents']}"
        )
        assert div["connecting_share_cents"] == 2502500, (
            f"3850000 - 1347500 must yield 2502500, got {div['connecting_share_cents']}"
        )
        assert div["our_share_cents"] != 1389834, (
            "identical waybill economics must split differently under the two bases"
        )
        assert div["our_share_cents"] + div["connecting_share_cents"] == 3850000


class TestDivisionRoundingOrder:
    def test_division_rounds_our_share_first(self, api, settlement_clerk_headers):
        """PRD §2.7: "In a revenue division, our railroad's share is rounded to
        whole cents first, and the connecting road receives the unrounded
        remainder — the two shares are never rounded independently."
        PRD §3.5: "Under `MILEAGE_PRORATE`, `our_share_cents` is the total charge
        times `our_miles` divided by `total_miles`, rounded half up to whole
        cents."

        Design: Difficulty/combinatorial_formula/revenue_division_rounding_order_mode_b
        """
        customer = create_customer(name="Short Line Shipper", billing_email="billing@sls.example")
        railcar = create_railcar(reporting_mark="GNWR 6010", car_type="BOX")
        waybill = create_waybill(railcar["id"], customer["id"], destination="NS Erie",
                                 commodity="GRAIN", weight_tons=3, through_route=True,
                                 our_miles=1, total_miles=8)
        validate_success(api.rate_waybill(waybill["id"], settlement_clerk_headers))
        div = validate_success(
            api.create_revenue_division({"waybill_id": waybill["id"], "basis": "MILEAGE_PRORATE"},
                                        settlement_clerk_headers),
            expected_status=201,
        )
        assert div["our_share_cents"] == 14438, (
            f"round_half_up(115500 / 8) = round_half_up(14437.5) must yield 14438, "
            f"got {div['our_share_cents']}"
        )

    def test_division_connecting_share_is_unrounded_remainder(self, api, settlement_clerk_headers):
        """PRD §2.7: "In a revenue division, our railroad's share is rounded to
        whole cents first, and the connecting road receives the unrounded
        remainder — the two shares are never rounded independently."
        PRD §3.5: "In both bases, `connecting_share_cents` is the total charge
        minus our rounded share; the connecting road's share is never rounded
        independently."

        Design: Difficulty/combinatorial_formula/revenue_division_rounding_order_mode_b
        """
        customer = create_customer(name="Short Line Shipper", billing_email="billing@sls.example")
        railcar = create_railcar(reporting_mark="GNWR 6010", car_type="BOX")
        waybill = create_waybill(railcar["id"], customer["id"], destination="NS Erie",
                                 commodity="GRAIN", weight_tons=3, through_route=True,
                                 our_miles=1, total_miles=8)
        validate_success(api.rate_waybill(waybill["id"], settlement_clerk_headers))
        div = validate_success(
            api.create_revenue_division({"waybill_id": waybill["id"], "basis": "MILEAGE_PRORATE"},
                                        settlement_clerk_headers),
            expected_status=201,
        )
        assert div["connecting_share_cents"] == 101062, (
            f"the connecting road receives the unrounded remainder 115500 - 14438 = 101062 "
            f"(not an independently rounded 101063), got {div['connecting_share_cents']}"
        )
        assert div["our_share_cents"] + div["connecting_share_cents"] == 115500, (
            "the pinned rounding order conserves the total charge"
        )


class TestDivisionShape:
    def test_division_agreed_pct_required(self, api, settlement_clerk_headers):
        """PRD §3.5: "The `AGREED_PERCENTAGE` basis requires an `agreed_pct`
        strictly between zero and one and forbids it for `MILEAGE_PRORATE`; a
        missing, out-of-range, or misplaced `agreed_pct` also fails as
        `ERR_DIVISION_BASIS_INVALID`."

        Design: Corner/validations/division_agreed_pct_required
        """
        ctx = setup_rated_waybill(commodity="CHEMICALS", weight_tons=20, through_route=True,
                                  our_miles=40, total_miles=400)
        resp = api.create_revenue_division(
            {"waybill_id": ctx["waybill"]["id"], "basis": "AGREED_PERCENTAGE"}, settlement_clerk_headers
        )
        validate_error(resp, ApiErrorId.ERR_DIVISION_BASIS_INVALID)

    def test_division_duplicate_for_waybill_rejected(self, api, settlement_clerk_headers):
        """PRD §3.5: "A **RevenueDivision** exists at most once per waybill:
        creating a second division for the same waybill is refused with
        `ERR_DIVISION_EXISTS`."

        Design: Corner/endpoints/division_duplicate_for_waybill_rejected
        """
        ctx = setup_rated_waybill(commodity="GRAIN", weight_tons=10, through_route=True,
                                  our_miles=10, total_miles=100)
        wb_id = ctx["waybill"]["id"]
        validate_success(
            api.create_revenue_division({"waybill_id": wb_id, "basis": "MILEAGE_PRORATE"},
                                        settlement_clerk_headers),
            expected_status=201,
        )
        resp = api.create_revenue_division(
            {"waybill_id": wb_id, "basis": "AGREED_PERCENTAGE", "agreed_pct": 0.5}, settlement_clerk_headers
        )
        validate_error(resp, ApiErrorId.ERR_DIVISION_EXISTS)


class TestDivisionSettleCascade:
    def test_division_settle_cascades_waybill_settled(self, api, settlement_clerk_headers):
        """PRD §3.5: "A division moves `DRAFT` → `AGREED` on clerk agreement,
        `AGREED` → `DISPUTED` on dispute, `DISPUTED` → `AGREED` on renewed
        agreement, and `AGREED` → `SETTLED` on settlement — at which point the
        waybill itself steps from `BILLED` to `SETTLED`."

        Design: Corner/endpoints/division_settle_cascades_waybill_settled
        """
        customer = create_customer(name="Cascade Co", billing_email="ca@x.example")
        ctx = setup_arrived_movement(symbol="GW-906")
        railcar = create_railcar(reporting_mark="GNWR 6801", car_type="HOPPER")
        waybill = create_waybill(
            railcar["id"], customer["id"], movement_id=ctx["movement"]["id"],
            destination="CSX Buffalo", commodity="GRAIN", weight_tons=100,
            through_route=True, our_miles=87, total_miles=241,
        )
        validate_success(api.rate_waybill(waybill["id"], settlement_clerk_headers))
        validate_success(api.settle_train_movement(ctx["movement"]["id"], settlement_clerk_headers))

        divisions, meta = validate_paginated(
            api.list_revenue_divisions(settlement_clerk_headers, params={"waybill_id": waybill["id"]})
        )
        assert meta["total_count"] == 1
        div_id = divisions[0]["id"]
        validate_success(api.agree_revenue_division(div_id, settlement_clerk_headers))

        settled = validate_success(api.settle_revenue_division(div_id, settlement_clerk_headers))
        assert settled["status"] == "SETTLED", f"the agreed division must settle, got {settled['status']}"
        wb = validate_success(api.get_waybill(waybill["id"], settlement_clerk_headers))
        assert wb["status"] == "SETTLED", (
            f"settling the division must step the waybill from BILLED to SETTLED, got {wb['status']}"
        )
