"""Difficulty: dual_variant_calc — provisional vs finalized dos; space-to-sales modes."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_retailer_payload,
    create_supplier_payload,
    make_category_captain_headers,
    setup_active_planogram,
    setup_category_with_listed_product,
    validate_success,
)


def _build_approved_planogram_with_line(
    api,
    *,
    weekly_demand_units: int,
    capacity_units: int,
    facings: int = 4,
    width_in: int = 12,
    total_linear_feet: int = 10,
):
    """Build an APPROVED planogram containing one line; return (rid, cid, pgid, lid, provisional_dos)."""
    retailer = validate_success(
        api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
        expected_status=201,
    )
    rid = retailer["id"]
    cat = validate_success(
        api.create_category(
            rid,
            create_category_payload(code="CAT1", role="ROUTINE", annual_sales_cents=1_000_000, total_linear_feet=total_linear_feet),
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    cid = cat["id"]
    supplier = validate_success(
        api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
        expected_status=201,
    )
    sid = supplier["id"]
    prod = validate_success(
        api.create_product(
            rid,
            create_product_payload(cid, sid, sku="SKU1", width_in=width_in, unit_cost_cents=100, weekly_demand_units=weekly_demand_units),
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    pid = prod["id"]
    validate_success(api.list_product_cut_in(rid, pid, TEST_USERS["category_manager_headers"]))
    pg = validate_success(
        api.create_planogram(rid, cid, create_planogram_payload(name="PG1", variant="BASE"), TEST_USERS["category_manager_headers"]),
        expected_status=201,
    )
    pgid = pg["id"]
    line = validate_success(
        api.create_planogram_line(
            rid,
            cid,
            pgid,
            {"product_id": pid, "position_index": 1, "facings": facings, "capacity_units": capacity_units},
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    lid = line["id"]
    provisional_dos = line["days_of_supply"]
    # Submit as captain, approve as manager
    captain_headers = make_category_captain_headers(sid)
    validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
    validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
    return rid, cid, pgid, lid, provisional_dos


class TestDosProvisionalVsFinalized:
    def test_dos_snapped_down_on_approval(self, api):
        """PRD §3.5: "every line's `days_of_supply` is recomputed into its
        finalized form — snapped down to the greatest half-day boundary that
        does not exceed the raw value, so a line's approved figure can be
        smaller than, but never larger than, its provisional one, with the
        9999.0 sentinel preserved untouched".

        Design: Difficulty/dual_variant_calc/dos_provisional_vs_finalized_on_planogram_approval
        """
        # weekly=20 → daily=20/7. capacity=29 → raw dos = 29/(20/7) = 10.15 → snap to 10.0
        rid, cid, pgid, lid, provisional = _build_approved_planogram_with_line(
            api, weekly_demand_units=20, capacity_units=29, width_in=12
        )
        assert provisional == pytest.approx(10.15, abs=0.01), (
            f"provisional dos should be 10.15 before approval, got {provisional}"
        )
        line_now = validate_success(
            api.get_planogram_line(rid, cid, pgid, lid, TEST_USERS["category_manager_headers"])
        )
        finalized = line_now["days_of_supply"]
        assert finalized == pytest.approx(10.0, abs=0.001), (
            f"finalized dos should snap down to 10.0, got {finalized}"
        )
        assert finalized < provisional

    def test_dos_finalized_leq_provisional_at_half_step(self, api):
        """PRD §3.5: "a line's approved figure can be smaller than, but never
        larger than, its provisional one".

        Design: Difficulty/dual_variant_calc/dos_provisional_vs_finalized_on_planogram_approval
        """
        # weekly=14 → daily=2. capacity=30 → raw dos = 15.0 already on 0.5 grid.
        # finalized must equal provisional (no snap-down needed) and never larger.
        rid, cid, pgid, lid, provisional = _build_approved_planogram_with_line(
            api, weekly_demand_units=14, capacity_units=30, width_in=12
        )
        assert provisional == pytest.approx(15.0, abs=0.001)
        line_now = validate_success(
            api.get_planogram_line(rid, cid, pgid, lid, TEST_USERS["category_manager_headers"])
        )
        finalized = line_now["days_of_supply"]
        assert finalized == pytest.approx(15.0, abs=0.001)
        assert finalized <= provisional


class TestSpaceToSalesModes:
    def _setup_two_product_active_planogram(self, api):
        """Category ROUTINE, 10 linear ft; P1 weekly=70 width=12 facings=3; P2 weekly=30 width=12 facings=1.
        ACTIVE planogram with both lines. Returns (rid, cid)."""
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid,
                create_category_payload(code="CAT1", role="ROUTINE", annual_sales_cents=1_000_000, total_linear_feet=10),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        sid = supplier["id"]
        p1 = validate_success(
            api.create_product(
                rid,
                create_product_payload(cid, sid, sku="P1", width_in=12, unit_cost_cents=100, weekly_demand_units=70),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        p2 = validate_success(
            api.create_product(
                rid,
                create_product_payload(cid, sid, sku="P2", width_in=12, unit_cost_cents=100, weekly_demand_units=30),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, p1["id"], TEST_USERS["category_manager_headers"]))
        validate_success(api.list_product_cut_in(rid, p2["id"], TEST_USERS["category_manager_headers"]))
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pgid = pg["id"]
        l1 = validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": p1["id"], "position_index": 1, "facings": 3, "capacity_units": 60},
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        l2 = validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": p2["id"], "position_index": 2, "facings": 1, "capacity_units": 20},
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
        cat_now = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))
        validate_success(
            api.activate_planogram(
                rid, cid, pgid,
                {"expected_category_version": cat_now["version"]},
                TEST_USERS["category_manager_headers"],
            )
        )
        return rid, cid, p1["id"], p2["id"]

    def test_space_to_sales_default_mode_absolute_gap(self, api):
        """PRD §3.6: "`gap_pct` is the signed percentage-point difference —
        space share minus sales share — so a positive gap marks a product
        holding more shelf than its demand justifies."
        PRD §3.6: "Each per-line value is rounded half-up to two decimal places
        before any aggregate check is applied to the column."

        Design: Difficulty/dual_variant_calc/space_to_sales_absolute_vs_indexed_mode
        """
        rid, cid, p1_id, p2_id = self._setup_two_product_active_planogram(api)
        resp = api.get_space_to_sales(rid, cid, TEST_USERS["category_manager_headers"])
        data = validate_success(resp)
        lines = data["lines"] if isinstance(data, dict) and "lines" in data else data
        by_product = {entry["product_id"]: entry for entry in lines}
        # P1: space = 36/48 * 100 = 75.0; sales = 70/100 * 100 = 70.0; gap = 5.0
        # P2: space = 12/48 * 100 = 25.0; sales = 30/100 * 100 = 30.0; gap = -5.0
        assert by_product[p1_id]["gap_pct"] == pytest.approx(5.0, abs=0.01)
        assert by_product[p2_id]["gap_pct"] == pytest.approx(-5.0, abs=0.01)

    def test_space_to_sales_indexed_mode_gap_ratio(self, api):
        """PRD §3.6: "A caller who supplies the query parameter `mode` with the
        value `indexed` receives a different fourth measure in place of the
        gap: `gap_ratio`, defined as `space_share_pct` divided by
        `sales_share_pct`, where 1.0 marks a perfectly balanced line."

        Design: Difficulty/dual_variant_calc/space_to_sales_absolute_vs_indexed_mode
        """
        rid, cid, p1_id, p2_id = self._setup_two_product_active_planogram(api)
        resp = api.get_space_to_sales(
            rid, cid, TEST_USERS["category_manager_headers"], params={"mode": "indexed"}
        )
        data = validate_success(resp)
        lines = data["lines"] if isinstance(data, dict) and "lines" in data else data
        by_product = {entry["product_id"]: entry for entry in lines}
        # P1: 75.0/70.0 ≈ 1.07 ; P2: 25.0/30.0 ≈ 0.83
        assert by_product[p1_id]["gap_ratio"] == pytest.approx(1.07, abs=0.01)
        assert by_product[p2_id]["gap_ratio"] == pytest.approx(0.83, abs=0.01)
