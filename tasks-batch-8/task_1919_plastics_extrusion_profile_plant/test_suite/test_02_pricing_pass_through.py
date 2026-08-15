"""Resin index, pass-through pricing, OCC on commercial writes (PRD §2.7, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, DEFAULT_INDEX_POINTS,
    create_customer, create_profile, create_formulation, create_die,
    create_order, confirm_order, publish_index_points, set_clock,
    two_basis_orders_scene, get_customer, get_order, plant_base,
)

PM = TEST_USERS["plant_manager_headers"]
SE = TEST_USERS["sales_engineer_headers"]


def _create_standard_order(api, cust, prof, die, form, **over):
    payload = {"customer_id": cust["id"], "profile_id": prof["id"],
               "formulation_id": form["id"], "die_id": die["id"],
               "ordered_length_m": 5000, "cut_length_mm": 2000,
               "pieces_per_bundle": 25, "base_unit_price_cents_per_m": 1000}
    payload.update(over)
    return api.create_work_order(payload, SE)


class TestPassThroughDualBasis:
    def test_monthly_avg_basis_reprices_over_window_mean(self, api):
        """PRD §3.4: "Under `MONTHLY_AVG`, the basis is the arithmetic mean of
        the current `index_cents_per_kg` of every index point whose month falls
        between the order's `quote_month` and the current clock month, inclusive
        at both ends, the mean itself rounded half-up to two decimal places; any
        month in that window lacking a point rejects the evaluation with
        `ERR_RESIN_INDEX_MISSING`."
        PRD §3.4: "The adjustment `pass_through_adj_cents_per_m` is then the
        basis index minus the snapshotted `quote_index_cents_per_kg`, the
        difference multiplied by the profile's `resin_content_kg_per_m` and by
        the pass-through factor 0.85, rounded half-up to two decimal places —
        negative when the index has fallen, positive when it has risen."

        Design: Difficulty/dual_variant_calc/pass_through_monthly_avg_vs_shipment_date
        """
        scene = two_basis_orders_scene()
        wo_ma = scene["wo_ma"]
        resp = api.reprice_work_order(
            wo_ma["id"], {"expected_work_order_version": wo_ma["version"]}, SE)
        data = validate_success(resp, 200)
        # Window {2026-06, 2026-07, 2026-08} -> mean(100, 120, 140) = 120.00;
        # adj = (120.00 - 100.00) * 0.8 * 0.85 = 13.60.
        assert data["pass_through_adj_cents_per_m"] == pytest.approx(13.60, abs=0.001)
        assert data["current_unit_price_cents_per_m"] == pytest.approx(1013.60, abs=0.001)
        assert data["status"] == "QUOTED", "Reprice from QUOTED recalculates in place"

    def test_shipment_date_basis_uses_current_month_point(self, api):
        """PRD §3.4: "Under `SHIPMENT_DATE`, the basis is the single index point
        whose month equals the current clock month, and its absence is likewise
        `ERR_RESIN_INDEX_MISSING`."
        PRD §3.4: "The adjustment `pass_through_adj_cents_per_m` is then the
        basis index minus the snapshotted `quote_index_cents_per_kg`, the
        difference multiplied by the profile's `resin_content_kg_per_m` and by
        the pass-through factor 0.85, rounded half-up to two decimal places —
        negative when the index has fallen, positive when it has risen."

        Design: Difficulty/dual_variant_calc/pass_through_monthly_avg_vs_shipment_date
        """
        scene = two_basis_orders_scene()
        # Reprice the MONTHLY_AVG order too, so both bases observe identical history.
        resp_ma = api.reprice_work_order(
            scene["wo_ma"]["id"],
            {"expected_work_order_version": scene["wo_ma"]["version"]}, SE)
        adj_ma = validate_success(resp_ma, 200)["pass_through_adj_cents_per_m"]

        resp = api.reprice_work_order(
            scene["wo_sd"]["id"],
            {"expected_work_order_version": scene["wo_sd"]["version"]}, SE)
        data = validate_success(resp, 200)
        # Current clock month 2026-08 -> basis 140.00; adj = (140-100)*0.8*0.85 = 27.20.
        assert data["pass_through_adj_cents_per_m"] == pytest.approx(27.20, abs=0.001)
        assert data["current_unit_price_cents_per_m"] == pytest.approx(1027.20, abs=0.001)
        assert data["status"] == "QUOTED"
        assert data["pass_through_adj_cents_per_m"] != pytest.approx(adj_ma, abs=0.0001), (
            "The two basis variants must diverge on the same trending index history")


class TestWorkOrderCreation:
    def test_work_order_initial_states(self, api):
        """PRD §3.4: "A new order starts in `QUOTED` status with `billing_status`
        `UNBILLED`, a `pass_through_adj_cents_per_m` of zero, and a
        `current_unit_price_cents_per_m` equal to the base price;
        `produced_good_length_m` starts at zero, and `billed_length_m` and
        `invoice_total_cents` stay unset until invoicing."

        Design: Corner/state_machines/work_order_initial_states
        """
        publish_index_points((("2026-08", 140.0),))
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        form = create_formulation(prof["id"])
        resp = _create_standard_order(api, cust, prof, die, form)
        data = validate_success(resp, 201)
        assert data["status"] == "QUOTED"
        assert data["billing_status"] == "UNBILLED"
        assert data["pass_through_adj_cents_per_m"] == pytest.approx(0, abs=0.001)
        assert data["current_unit_price_cents_per_m"] == pytest.approx(1000, abs=0.001)
        assert data["produced_good_length_m"] == pytest.approx(0, abs=0.001)
        assert data.get("billed_length_m") is None
        assert data.get("invoice_total_cents") is None

    def test_work_order_create_without_quote_month_index_fails(self, api):
        """PRD §3.4: "Creation also pins the quote in time: `quote_month` takes
        the logical clock's current month, and `quote_index_cents_per_kg`
        snapshots the index value published for that month — if no point exists
        for the quote month, creation fails with `ERR_RESIN_INDEX_MISSING`."

        Design: Corner/errors/resin_index_missing_on_create
        """
        # No index points published; logical clock untouched (default 2026-08-01).
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        form = create_formulation(prof["id"])
        resp = _create_standard_order(api, cust, prof, die, form)
        validate_error(resp, ApiErrorId.ERR_RESIN_INDEX_MISSING)


class TestWorkOrderListing:
    def test_work_orders_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, accepts a minimum of 1, and accepts a maximum of 100."
        PRD §2.3: "The `meta` object of every list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.4: "Work-order listings support reverse lookups by `customer_id`,
        `profile_id`, `formulation_id`, and `die_id`."

        Design: Corner/entities/work_orders_list_pagination
        """
        publish_index_points((("2026-08", 140.0),))
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        form = create_formulation(prof["id"])
        for _ in range(2):
            validate_success(_create_standard_order(api, cust, prof, die, form), 201)

        page1, meta1 = validate_paginated(
            api.list_work_orders(SE, params={"customer_id": cust["id"], "limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2 and meta1["has_more"] is True
        assert len(page1) == 1

        page2, meta2 = validate_paginated(
            api.list_work_orders(SE, params={"customer_id": cust["id"], "limit": 1, "offset": 1}))
        assert meta2["has_more"] is False and len(page2) == 1
        assert page1[0]["id"] != page2[0]["id"], "Pages must return distinct orders"


class TestResinIndexPoints:
    def test_duplicate_index_month_rejected(self, api):
        """PRD §3.4: "Months are unique: a second publish against a month that
        already has a point is rejected with `ERR_INDEX_MONTH_EXISTS`, and the
        intended remedy is restatement."

        Design: Corner/validations/duplicate_index_month_rejected
        """
        publish_index_points((("2026-08", 140.0),))
        resp = api.create_resin_index_point({"month": "2026-08", "index_cents_per_kg": 145.0}, PM)
        validate_error(resp, ApiErrorId.ERR_INDEX_MONTH_EXISTS)
        point = get_success_data(api.get_resin_index_point("2026-08", PM))
        assert point["index_cents_per_kg"] == pytest.approx(140.0), (
            "Rejected duplicate publish must not change the stored value")


class TestOptimisticConcurrency:
    def test_reprice_stale_work_order_version_rejected(self, api):
        """PRD §2.7: "Repricing a work order requires the request to carry
        `expected_work_order_version`, the client's last observed `version` of
        that order. If another writer has advanced the order's `version` since
        the client last read it, the reprice is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from repricing an
        order it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_reprice_stale_version
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        wo = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        stale_version = wo["version"]
        validate_success(api.confirm_work_order(wo["id"], SE), 200)  # advances version

        resp = api.reprice_work_order(wo["id"], {"expected_work_order_version": stale_version}, SE)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_order(wo["id"])["status"] == "CONFIRMED", (
            "Rejected reprice must not mutate the order")

    def test_restate_stale_index_point_version_rejected(self, api):
        """PRD §2.7: "Restating a resin index point requires
        `expected_index_point_version`, compared against the point's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_restate_stale_version
        """
        points = publish_index_points((("2026-08", 140.0),))
        observed = points["2026-08"]["version"]
        ok = api.restate_resin_index_point(
            "2026-08", {"index_cents_per_kg": 145.0, "expected_index_point_version": observed}, PM)
        data = validate_success(ok, 200)
        assert data["index_cents_per_kg"] == pytest.approx(145.0)
        assert data["version"] == observed + 1

        stale = api.restate_resin_index_point(
            "2026-08", {"index_cents_per_kg": 150.0, "expected_index_point_version": observed}, PM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        point = get_success_data(api.get_resin_index_point("2026-08", PM))
        assert point["index_cents_per_kg"] == pytest.approx(145.0)

    def test_restate_cascade_recomputes_prices_and_exposure(self, api):
        """PRD §3.4: "Restatement is never free of consequence — it cascades,
        recomputing the pass-through on every work order whose `billing_status`
        is `UNBILLED` and whose production `status` is not `CANCELLED`, provided
        the order's basis references the restated month: for a `MONTHLY_AVG`
        customer, any restated month inside the window from the order's
        `quote_month` through the current clock month inclusive; for a
        `SHIPMENT_DATE` customer, only when the restated month is the current
        clock month."
        PRD §3.4: "After the affected orders are repriced, each affected
        customer's `open_exposure_cents` is recomputed."

        Design: Corner/cross_cutting_complexity_layers/restate_cascade_recomputes_exposure
        """
        set_clock("2026-06-01T00:00:00Z")
        points = publish_index_points(DEFAULT_INDEX_POINTS)
        idx_version = points["2026-08"]["version"]
        cust = create_customer()  # MONTHLY_AVG
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        form = create_formulation(prof["id"])
        wo = create_order(cust["id"], prof["id"], form["id"], die["id"])
        validate_success(api.confirm_work_order(wo["id"], SE), 200)
        assert get_customer(cust["id"])["open_exposure_cents"] == 5000000
        set_clock("2026-08-01T00:00:00Z")

        resp = api.restate_resin_index_point(
            "2026-08", {"index_cents_per_kg": 160.0, "expected_index_point_version": idx_version}, PM)
        validate_success(resp, 200)

        wo_after = get_order(wo["id"])
        # Window mean = (100 + 120 + 160) / 3 = 126.67; adj = 26.67 * 0.8 * 0.85 = 18.14.
        assert wo_after["pass_through_adj_cents_per_m"] == pytest.approx(18.14, abs=0.001)
        assert wo_after["current_unit_price_cents_per_m"] == pytest.approx(1018.14, abs=0.001)
        cust_after = get_customer(cust["id"])
        assert cust_after["open_exposure_cents"] == 5090700, (
            f"Exposure must follow the repriced order: 5000 x 1018.14 = 5090700, "
            f"got {cust_after['open_exposure_cents']}")
