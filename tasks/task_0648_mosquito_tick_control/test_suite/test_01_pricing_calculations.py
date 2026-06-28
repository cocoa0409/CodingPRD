"""Pricing and charge-calculation tests (per-visit, special-event, seasonal).

Covers Difficulty rules dual_variant_calc and combinatorial_formula, plus the
seasonal volume-discount boundary corner.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_paginated,
    TEST_USERS, make_account_holder_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _per_visit_invoice_for(visit_id):
    data = get_success_data(api_client.list_invoices(BILLING, params={"visit_id": visit_id}))
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data[0] if data else None


def _seasonal_invoice_for(sub_id):
    data = get_success_data(api_client.list_subscription_invoices(sub_id, BILLING))
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return [i for i in data if i["invoice_type"] == "SEASONAL"], data


class TestVisitChargeRecurringVsSpecialEvent:
    """RECURRING vs SPECIAL_EVENT charge divergence on the same property."""

    def _setup(self):
        ctx = create_active_subscription(
            billing_mode="PER_VISIT", region="NE01",
            zones=[{"label": "Backyard", "zone_type": "TURF", "area_sqft": 4000},
                   {"label": "Perimeter", "zone_type": "PERIMETER", "area_sqft": 2000}],
            lot_size_sqft=8000)
        return ctx, create_crew(home_region_code="NE01")

    def test_recurring_visit_charge_equals_7380(self, api):
        """
    PRD 3.6: "The base price, the area surcharge, and the summed zone component are added together, and only this final total is rounded half-up to a whole cent. The result becomes the `amount_cents` of a `PER_VISIT` invoice issued in `ISSUED` status, after which the subscription's `season_balance_cents` is recomputed."

        Design: Difficulty/dual_variant_calc/visit_charge_recurring_vs_special_event_variant
        """
        ctx, crew = self._setup()
        set_clock("2026-05-01T08:00:00Z")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        dispatch_visit(route["id"], rec["id"], route["version"])
        log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(rec["id"], crew["id"])
        inv = _per_visit_invoice_for(rec["id"])
        assert inv is not None, "PER_VISIT invoice issued on completion"
        assert inv["amount_cents"] == 7380, f"expected 7380, got {inv['amount_cents']}"

    def test_special_event_visit_charge_equals_12880(self, api):
        """
    PRD 3.6: "a flat special-event surcharge of 4,000 cents is added to the running total, and the tiered area surcharge is doubled (so the 0 / 1,500 / 3,500 / 6,000-cent tier figure is multiplied by two before being added). As with the standard charge, all components are summed at full precision and rounded half-up once at the end."

        Design: Difficulty/dual_variant_calc/visit_charge_recurring_vs_special_event_variant
        """
        ctx, crew = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-05T08:00:00Z")
        se = get_success_data(api.schedule_special_event(ctx["sub"]["id"], {"scheduled_date": "2026-05-06"}, ah))
        route = create_route(crew["id"], region="NE01", route_date="2026-05-06")
        dispatch_visit(route["id"], se["id"], route["version"])
        log_application(se["id"], ctx["zones"][1]["id"], crew["id"], product_code="TALSTAR", gallons_applied=1.5)
        complete_visit(se["id"], crew["id"])
        inv = _per_visit_invoice_for(se["id"])
        assert inv is not None, "SPECIAL_EVENT bills per visit on completion"
        assert inv["amount_cents"] == 12880, f"expected 12880, got {inv['amount_cents']}"

    def test_special_event_amount_differs_from_recurring(self, api):
        """
    PRD 3.6: "A `SPECIAL_EVENT` visit is billed per visit on completion using the same components as a recurring per-visit charge, with two premium adjustments applied before the single final rounding: a flat special-event surcharge of 4,000 cents is added to the running total, and the tiered area surcharge is doubled (so the 0 / 1,500 / 3,500 / 6,000-cent tier figure is multiplied by two before being added). As with the standard charge, all components are summed at full precision and rounded half-up once at the end."

        Design: Difficulty/dual_variant_calc/visit_charge_recurring_vs_special_event_variant
        """
        ctx, crew = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-01T08:00:00Z")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        r1 = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        dispatch_visit(r1["id"], rec["id"], r1["version"])
        log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(rec["id"], crew["id"])
        rec_inv = _per_visit_invoice_for(rec["id"])
        set_clock("2026-05-05T08:00:00Z")
        se = get_success_data(api.schedule_special_event(ctx["sub"]["id"], {"scheduled_date": "2026-05-06"}, ah))
        r2 = create_route(crew["id"], region="NE01", route_date="2026-05-06")
        dispatch_visit(r2["id"], se["id"], r2["version"])
        log_application(se["id"], ctx["zones"][1]["id"], crew["id"], product_code="TALSTAR", gallons_applied=1.5)
        complete_visit(se["id"], crew["id"])
        se_inv = _per_visit_invoice_for(se["id"])
        assert se_inv["amount_cents"] != rec_inv["amount_cents"], "special-event premium diverges from recurring"
        assert se_inv["amount_cents"] == 12880 and rec_inv["amount_cents"] == 7380


class TestSeasonalVsVisitChargeDomains:
    """Flat seasonal charge (Subscription domain) vs per-visit charge (Visit domain)."""

    def _activate_seasonal(self, tick=True):
        return create_active_subscription(
            billing_mode="SEASONAL", region="SE02",
            zones=[{"label": "Yard", "zone_type": "TURF", "area_sqft": 4000}],
            lot_size_sqft=6000,
            plan_overrides={"tier": "PLUS", "includes_tick_barrier": tick, "seasonal_price_cents": 30000})

    def test_seasonal_invoice_amount_equals_35340(self, api):
        """
    PRD 3.6: "It starts from the plan's `seasonal_price_cents` and adds a tick-barrier add-on of 8,000 cents when the plan's `includes_tick_barrier` is true (and nothing when it is false). A volume discount is then selected from the planned recurring visit count: when there are at least 10 planned recurring visits the discount is 12 percent; when there are at least 6 but fewer than 10 it is 7 percent; otherwise there is no discount."

        Design: Difficulty/dual_variant_calc/seasonal_charge_subscription_vs_visit_charge_visit_domain
        """
        ctx = self._activate_seasonal(tick=True)
        seasonal, _ = _seasonal_invoice_for(ctx["sub"]["id"])
        assert len(seasonal) == 1, "exactly one SEASONAL invoice issued at activation"
        assert seasonal[0]["amount_cents"] == 35340, f"expected 35340, got {seasonal[0]['amount_cents']}"

    def test_seasonal_invoice_is_unique_and_balance_matches(self, api):
        """
    PRD 3.6: "For a `SEASONAL` subscription it is the single seasonal invoice's `amount_cents` once issued, or 0 before issuance."

        Design: Difficulty/dual_variant_calc/seasonal_charge_subscription_vs_visit_charge_visit_domain
        """
        ctx = self._activate_seasonal(tick=True)
        seasonal, _ = _seasonal_invoice_for(ctx["sub"]["id"])
        assert len(seasonal) == 1
        sub = get_success_data(api.get_subscription(ctx["sub"]["id"], BILLING))
        assert sub["season_balance_cents"] == 35340, f"got {sub['season_balance_cents']}"


class TestVisitChargeCombinatorial:
    """visit_charge combines >=3 interacting inputs and pins sum-then-round."""

    def _complete_first_recurring(self, zones, base_price, lot_size_sqft):
        ctx = create_active_subscription(
            billing_mode="PER_VISIT", region="NE01", zones=zones,
            lot_size_sqft=lot_size_sqft, plan_overrides={"per_visit_price_cents": base_price})
        crew = create_crew(home_region_code="NE01")
        set_clock("2026-05-01T08:00:00Z")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        dispatch_visit(route["id"], rec["id"], route["version"])
        log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(rec["id"], crew["id"])
        return _per_visit_invoice_for(rec["id"])

    def test_tiered_nonlinear_charge_equals_7590(self, api):
        """
    PRD 3.6: "It then adds a per-zone application component: for each `ACTIVE` treatment zone of the property, take the zone's `area_sqft` divided by 1,000 and multiply by the zone-type rate per 1,000 square feet — 120 cents for `TURF`, 200 cents for `PERIMETER`, 350 cents for `WATER_FEATURE`, and 280 cents for `WOODLINE` — and accumulate these contributions at full precision."

        Design: Difficulty/combinatorial_formula/visit_charge_tiered_nonlinear_mode_a
        """
        inv = self._complete_first_recurring(
            zones=[{"label": "Turf", "zone_type": "TURF", "area_sqft": 4500},
                   {"label": "Perimeter", "zone_type": "PERIMETER", "area_sqft": 2750}],
            base_price=5000, lot_size_sqft=9000)
        assert inv["amount_cents"] == 7590, f"expected 7590, got {inv['amount_cents']}"

    def test_tiered_area_surcharge_is_step_function(self, api):
        """
    PRD 3.6: "when the treatable area is at most 5,000 square feet the surcharge is 0; when it is greater than 5,000 and at most 10,000 the surcharge is 1,500 cents; when it is greater than 10,000 and at most 20,000 the surcharge is 3,500 cents; and when it exceeds 20,000 the surcharge is 6,000 cents. This is a flat surcharge by tier, not a marginal calculation."

        Design: Difficulty/combinatorial_formula/visit_charge_tiered_nonlinear_mode_a
        """
        inv = self._complete_first_recurring(
            zones=[{"label": "Turf", "zone_type": "TURF", "area_sqft": 4500},
                   {"label": "Perimeter", "zone_type": "PERIMETER", "area_sqft": 2750}],
            base_price=5000, lot_size_sqft=9000)
        assert inv["amount_cents"] == 7590

    def test_sum_then_round_two_water_features_equals_4050(self, api):
        """
    PRD 2.8: "Charge calculations follow a strict **sum-then-round** discipline: every intermediate component is accumulated at full precision and the result is rounded exactly once, at the very end, using the round-half-up method to the nearest whole cent. Per-zone contributions are never rounded individually before summing."

        Design: Difficulty/combinatorial_formula/visit_charge_sum_then_round_mode_b
        """
        inv = self._complete_first_recurring(
            zones=[{"label": "Pond A", "zone_type": "WATER_FEATURE", "area_sqft": 1250},
                   {"label": "Pond B", "zone_type": "WATER_FEATURE", "area_sqft": 1750}],
            base_price=3000, lot_size_sqft=5000)
        assert inv["amount_cents"] == 4050, f"expected 4050, got {inv['amount_cents']}"

    def test_sum_then_round_total_is_integer_cents(self, api):
        """
    PRD 2.8: "All monetary amounts are stored and returned as integer cents."

        Design: Difficulty/combinatorial_formula/visit_charge_sum_then_round_mode_b
        """
        inv = self._complete_first_recurring(
            zones=[{"label": "Pond A", "zone_type": "WATER_FEATURE", "area_sqft": 1250},
                   {"label": "Pond B", "zone_type": "WATER_FEATURE", "area_sqft": 1750}],
            base_price=3000, lot_size_sqft=5000)
        assert isinstance(inv["amount_cents"], int)
        assert inv["amount_cents"] == 4050


def test_seasonal_five_visits_no_discount_equals_30000(api):
    """
    PRD 3.6: "A volume discount is then selected from the planned recurring visit count: when there are at least 10 planned recurring visits the discount is 12 percent; when there are at least 6 but fewer than 10 it is 7 percent; otherwise there is no discount."

    Design: Corner/calculations/seasonal_charge_volume_discount_tier_boundary_five_visits_no_discount
    """
    ctx = create_active_subscription(
        billing_mode="SEASONAL", region="NE01",
        zones=[{"label": "Yard", "zone_type": "TURF", "area_sqft": 4000}],
        season_start="2026-05-01", season_end="2026-07-24",
        plan_overrides={"tier": "PLUS", "includes_tick_barrier": False, "seasonal_price_cents": 30000})
    _, meta = validate_paginated(
        api.list_subscription_visits(ctx["sub"]["id"], make_account_holder_headers(ctx["holder"]["id"])))
    assert meta["total_count"] == 5, f"expected 5 planned visits, got {meta['total_count']}"
    data = get_success_data(api.list_subscription_invoices(ctx["sub"]["id"], BILLING))
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    seasonal = [i for i in data if i["invoice_type"] == "SEASONAL"]
    assert len(seasonal) == 1
    assert seasonal[0]["amount_cents"] == 30000, f"expected 30000, got {seasonal[0]['amount_cents']}"
