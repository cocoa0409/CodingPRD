"""Bin agreement creation rules, OCC-guarded updates, and the advisory
sizing-recommendation calculation (TRAILING vs PROJECTED variants)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_agreement,
    create_bin_agreement_payload,
    create_part,
    create_route,
    create_site,
    create_stop,
    get_success_data,
    run_weekly_scan,
    setup_site_part_agreement,
    setup_sizing_history,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAgreementCreationRules:
    def test_flat_bin_price_required_for_cost_per_bin(self, api):
        """PRD §3.2: "per §2.8 the shape check requires `flat_bin_price_cents`
        exactly when the mode is `COST_PER_BIN`, and a request that omits it
        there (or supplies it under `UNIT_PRICE`) fails with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/bin_agreement_flat_price_required_only_for_cost_per_bin
        """
        site = create_site(api, ship_to_code="CV-1", credit_limit_cents=100000)
        part = create_part(api, sku="CV-P", unit_price_cents=100,
                           total_stock_qty=1000)
        missing_flat = create_bin_agreement_payload(
            site["id"], part["id"], bin_location="L1",
            pricing_mode="COST_PER_BIN", min_qty=1, max_qty=10,
            flat_bin_price_cents=None)
        missing_flat.pop("flat_bin_price_cents")
        resp = api.create_bin_agreement(missing_flat, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        unit_price_ok = create_bin_agreement_payload(
            site["id"], part["id"], bin_location="L2",
            pricing_mode="UNIT_PRICE", min_qty=1, max_qty=10)
        assert "flat_bin_price_cents" not in unit_price_ok
        ok = api.create_bin_agreement(unit_price_ok, ADMIN)
        created = validate_success(ok, 201)
        assert created["pricing_mode"] == "UNIT_PRICE"
        assert created["flat_bin_price_cents"] == 0

    def test_min_qty_equal_max_qty_rejected(self, api):
        """PRD §3.2: "The reorder point must be zero or positive and strictly
        below `max_qty`, which must be at least 1; violations are rejected with
        `ERR_QUANTITY_OUT_OF_BOUNDS`."

        Design: Corner/validations/min_qty_must_be_less_than_max_qty
        """
        site = create_site(api, ship_to_code="MM-1", credit_limit_cents=100000)
        part = create_part(api, sku="MM-P", unit_price_cents=100,
                           total_stock_qty=100)
        resp = api.create_bin_agreement(
            create_bin_agreement_payload(site["id"], part["id"],
                                         bin_location="MM1", min_qty=10,
                                         max_qty=10),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_OUT_OF_BOUNDS, 422)

    def test_duplicate_live_agreement_triple_rejected_then_reusable(self, api):
        """PRD §3.2: "The triple of (`site_id`, `part_id`, `bin_location`) must
        be unique among agreements that are not `RETIRED`; duplicates are
        rejected with `ERR_DUPLICATE`."
        PRD §3.7: "A `RETIRED` bin accepts no new stops and no new orders, and
        it drops out of the live-triple uniqueness check of §3.2, freeing the
        (`site_id`, `part_id`, `bin_location`) combination for reuse."

        Design: Corner/validations/duplicate_live_agreement_triple_rejected
        """
        site = create_site(api, ship_to_code="DA-1", credit_limit_cents=100000)
        part = create_part(api, sku="DA-P", unit_price_cents=100,
                           total_stock_qty=100)
        agr = create_agreement(api, site["id"], part["id"],
                               bin_location="DUP-L", min_qty=1, max_qty=10)
        dup = api.create_bin_agreement(
            create_bin_agreement_payload(site["id"], part["id"],
                                         bin_location="DUP-L", min_qty=2,
                                         max_qty=20),
            ADMIN)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE, 409)

        get_success_data(api.retire_bin_agreement(agr["id"], ADMIN))
        recreated = api.create_bin_agreement(
            create_bin_agreement_payload(site["id"], part["id"],
                                         bin_location="DUP-L", min_qty=2,
                                         max_qty=20),
            ADMIN)
        data = validate_success(recreated, 201)
        assert data["min_qty"] == 2
        assert data["max_qty"] == 20
        assert data["status"] == "ACTIVE"


class TestAgreementUpdateOcc:
    def _agreement(self, api):
        site = create_site(api, ship_to_code="OC2-1", credit_limit_cents=100000)
        part = create_part(api, sku="OC2-P", unit_price_cents=100,
                           total_stock_qty=100)
        return create_agreement(api, site["id"], part["id"],
                                bin_location="OC1", min_qty=10, max_qty=100)

    def test_update_agreement_occ_success(self, api):
        """PRD §3.2: "A successful update increments the agreement's `version`
        and immediately recomputes the posture against the new `max_qty`."
        PRD §2.7: "the bin-agreement update operation — the one that adjusts
        sizing and pricing fields — requires the request body to carry
        `expected_bin_agreement_version`, holding the agreement `version` the
        client last observed."

        Design: Corner/endpoints/update_bin_agreement_occ_success_path
        """
        agr = self._agreement(api)
        before = agr["version"]
        resp = api.update_bin_agreement(
            agr["id"],
            {"expected_bin_agreement_version": before,
             "min_qty": 20, "max_qty": 120},
            ADMIN)
        updated = validate_success(resp, 200)
        assert updated["min_qty"] == 20
        assert updated["max_qty"] == 120
        assert updated["version"] == before + 1, (
            "a successful update increments the agreement version by one"
        )

    def test_update_agreement_stale_version_rejected(self, api):
        """PRD §2.7: "If the agreement's current `version` has advanced beyond
        that value — because a scan submission, an order confirmation, or a
        posture auto-transition has legitimately mutated the agreement since
        the client read it — the update is rejected with `ERR_STALE_VERSION`
        (HTTP 412) rather than allowed to overwrite a state the client never
        saw."

        Design: Corner/endpoints/update_bin_agreement_stale_version_rejected
        """
        agr = self._agreement(api)
        stale_v = agr["version"]
        first = api.update_bin_agreement(
            agr["id"],
            {"expected_bin_agreement_version": stale_v, "min_qty": 15},
            ADMIN)
        assert first.status_code == 200
        resp = api.update_bin_agreement(
            agr["id"],
            {"expected_bin_agreement_version": stale_v, "min_qty": 25},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        current = get_success_data(api.get_bin_agreement(agr["id"], ADMIN))
        assert current["min_qty"] == 15, "first writer's value is retained"


class TestSizingRecommendation:
    def test_sizing_trailing_default_method(self, api):
        """PRD §3.2: "Under the default `TRAILING` method, the usage figures
        are averaged plainly over the four weeks, the average is multiplied by
        a safety factor of one and a half, and the result is rounded up to a
        whole number of pieces to produce `recommended_min`; `recommended_max`
        is three times `recommended_min`."
        PRD §3.2: "It examines the agreement's four most recent `SUBMITTED`
        route stops (selected by `created_at` descending, then processed
        oldest-first so ties resolve by `created_at` ascending). Each stop's
        weekly usage is the previously recorded on-hand quantity minus that
        stop's `counted_qty`, with negative differences — which arise when a
        delivery landed between scans — clamped to zero."

        History: weekly counts 100, 90, 80, 70, 20 (min 25, max 200), so the
        four-stop window has usages 10, 10, 10, 50; only the 20-count week
        generates an order. TRAILING: average 20 x 1.5 = 30, max 90.

        Design: Difficulty/dual_variant_calc/sizing_recommendation_trailing_vs_projected
        """
        ctx = setup_sizing_history(api)
        rec = validate_success(
            api.get_sizing_recommendation(ctx["agreement"]["id"], ADMIN))
        assert rec["method"] == "TRAILING", "TRAILING is the default method"
        assert rec["recommended_min"] == 30
        assert rec["recommended_max"] == 90

    def test_sizing_projected_double_weights_order_weeks(self, api):
        """PRD §3.2: "Under the `PROJECTED` method, weeks whose stop generated
        a replenishment order are weighted double — consumption during a
        stockout-risk week is a stronger signal — so the projected average is
        the sum of each week's weight times its usage divided by the sum of the
        weights; the same safety factor of one and a half is applied and then
        rounded up, and `recommended_max` is again three times the minimum."

        Same history as the TRAILING case (usages 10, 10, 10, 50 with the last
        week order-generating): PROJECTED = ceil((10+10+10+2*50)/5 x 1.5) = 39,
        max 117.

        Design: Difficulty/dual_variant_calc/sizing_recommendation_trailing_vs_projected
        """
        ctx = setup_sizing_history(api)
        rec = validate_success(
            api.get_sizing_recommendation(
                ctx["agreement"]["id"], ADMIN, params={"method": "PROJECTED"}))
        assert rec["method"] == "PROJECTED"
        assert rec["recommended_min"] == 39
        assert rec["recommended_max"] == 117
        assert rec["recommended_min"] != 30, (
            "PROJECTED must differ from TRAILING when the window contains an "
            "order-generating stop and usages are not all equal"
        )

    def test_sizing_excludes_pending_stops(self, api):
        """PRD §3.2: "It examines the agreement's four most recent `SUBMITTED`
        route stops (selected by `created_at` descending, then processed
        oldest-first so ties resolve by `created_at` ascending)."
        PRD §3.2: "The response carries `recommended_min`, `recommended_max`,
        and the `method` that produced them."

        With a single SUBMITTED stop the usage series is empty (usage needs a
        previously recorded on-hand quantity), so every reading of the formula
        yields zero; the unsubmitted PENDING stop must not perturb that.

        Design: Corner/calculations/sizing_recommendation_input_set_excludes_pending_stops
        """
        ctx = setup_site_part_agreement(api, min_qty=25, max_qty=200)
        site_id = ctx["site"]["id"]
        agr_id = ctx["agreement"]["id"]
        run_weekly_scan(api, site_id, agr_id, 3, 100, close=True)
        # Second route left SCHEDULED with a PENDING stop never submitted.
        route2 = create_route(
            api, site_id,
            route_date="2026-08-04T00:00:00Z",
            window_start="2026-08-04T08:00:00Z",
            window_end="2026-08-04T12:00:00Z")
        stop2 = create_stop(api, route2["id"], agr_id)
        assert stop2["status"] == "PENDING"

        rec = validate_success(
            api.get_sizing_recommendation(agr_id, ADMIN,
                                          params={"method": "TRAILING"}))
        assert rec["method"] == "TRAILING"
        assert rec["recommended_min"] == 0
        assert rec["recommended_max"] == 0
