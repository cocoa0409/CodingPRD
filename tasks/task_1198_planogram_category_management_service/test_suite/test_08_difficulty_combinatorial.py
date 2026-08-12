"""Difficulty: combinatorial_formula — labor hours estimate; compliance nested rounding."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_reset_project_payload,
    create_retailer_payload,
    create_store_payload,
    create_supplier_payload,
    make_category_captain_headers,
    setup_submitted_audit,
    validate_success,
)


def _build_active_planogram(api, *, lines_specs, category_overrides=None, retailer_overrides=None):
    """lines_specs: list of dicts {sku, width_in, weekly_demand_units, facings, capacity_units, position_index}.
    Returns (retailer, category, supplier, products, planogram).
    """
    retailer = validate_success(
        api.create_retailer(
            create_retailer_payload(**(retailer_overrides or {"name": "R"})),
            TEST_USERS["platform_admin_headers"],
        ),
        expected_status=201,
    )
    rid = retailer["id"]
    cat = validate_success(
        api.create_category(
            rid,
            create_category_payload(**(category_overrides or {"code": "C", "role": "ROUTINE", "annual_sales_cents": 100_000, "total_linear_feet": 20})),
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
    products = {}
    for spec in lines_specs:
        p = validate_success(
            api.create_product(
                rid,
                create_product_payload(cid, sid, sku=spec["sku"], width_in=spec["width_in"], unit_cost_cents=100, weekly_demand_units=spec["weekly_demand_units"]),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, p["id"], TEST_USERS["category_manager_headers"]))
        products[spec["sku"]] = p
    pg = validate_success(
        api.create_planogram(rid, cid, create_planogram_payload(name="PG", variant="BASE"), TEST_USERS["category_manager_headers"]),
        expected_status=201,
    )
    pgid = pg["id"]
    for spec in lines_specs:
        validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {
                    "product_id": products[spec["sku"]]["id"],
                    "position_index": spec["position_index"],
                    "facings": spec["facings"],
                    "capacity_units": spec["capacity_units"],
                },
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
    captain_headers = make_category_captain_headers(sid)
    validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
    validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
    cat_now = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))
    validate_success(
        api.activate_planogram(rid, cid, pgid, {"expected_category_version": cat_now["version"]}, TEST_USERS["category_manager_headers"])
    )
    return retailer, cat, supplier, products, pg


class TestLaborHoursNonLinear:
    def test_labor_hours_with_two_new_products(self, api):
        """PRD §3.9: "The raw estimate is then the target planogram's
        `total_facings` multiplied by 0.05 hours per facing, plus the
        product-change count multiplied by 0.25 hours per change, and the
        result is rounded half-up to one decimal place."
        PRD §3.9: "the platform counts product changes: the number of lines on
        the target planogram whose `product_id` does not appear on the store's
        currently installed planogram for the category — or every line on the
        target planogram when the store has nothing installed yet."

        Design: Difficulty/combinatorial_formula/labor_hours_estimate_non_linear_inputs
        """
        # PG_A ACTIVE on store with P1(facings=10). PG_B APPROVED with P1+P2+P3
        # total_facings on PG_B = 20, product_changes = 2 (P2, P3 new)
        # raw = 20*0.05 + 2*0.25 = 1.5 → 1.5
        cat_over = {"code": "C", "role": "ROUTINE", "annual_sales_cents": 100_000, "total_linear_feet": 20}
        retailer, category, supplier, products_a, pg_a = _build_active_planogram(
            api,
            lines_specs=[{"sku": "P1", "width_in": 6, "weekly_demand_units": 70, "facings": 10, "capacity_units": 100, "position_index": 1}],
            category_overrides=cat_over,
        )
        rid, cid, sid = retailer["id"], category["id"], supplier["id"]
        # Create store
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        # P2, P3 (LISTED)
        p2 = validate_success(
            api.create_product(rid, create_product_payload(cid, sid, sku="P2", width_in=6, unit_cost_cents=100, weekly_demand_units=35), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, p2["id"], TEST_USERS["category_manager_headers"]))
        p3 = validate_success(
            api.create_product(rid, create_product_payload(cid, sid, sku="P3", width_in=6, unit_cost_cents=100, weekly_demand_units=35), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, p3["id"], TEST_USERS["category_manager_headers"]))
        # PG_B with 3 lines, get to APPROVED
        pg_b = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG_B", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pgb = pg_b["id"]
        for i, (sku, pid) in enumerate([("P1", products_a["P1"]["id"]), ("P2", p2["id"]), ("P3", p3["id"])], start=1):
            validate_success(
                api.create_planogram_line(
                    rid, cid, pgb,
                    {"product_id": pid, "position_index": i, "facings": 10 if sku == "P1" else 5, "capacity_units": 100 if sku == "P1" else 50},
                    TEST_USERS["category_manager_headers"],
                ),
                expected_status=201,
            )
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.submit_planogram(rid, cid, pgb, captain_headers))
        validate_success(api.approve_planogram(rid, cid, pgb, TEST_USERS["category_manager_headers"]))
        # Create reset project — PROPOSED, labor estimate computed at creation
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgb, store["id"], scheduled_start="2026-06-01T08:00:00Z", scheduled_end="2026-06-01T16:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        assert rp["labor_hours_estimated"] == pytest.approx(1.5, abs=0.001)

    def test_labor_hours_with_no_installation_all_lines_new(self, api):
        """PRD §3.9: "the platform counts product changes: the number of lines
        on the target planogram whose `product_id` does not appear on the
        store's currently installed planogram for the category — or every line
        on the target planogram when the store has nothing installed yet."

        Design: Difficulty/combinatorial_formula/labor_hours_estimate_non_linear_inputs
        """
        # Single-planogram scenario: no installed planogram on the store,
        # so every line counts as a product change.
        # PG with P1 facings=4 + P2 facings=4 → total_facings=8, product_changes=2
        # raw = 8*0.05 + 2*0.25 = 0.4 + 0.5 = 0.9
        retailer, category, supplier, products, pg = _build_active_planogram(
            api,
            lines_specs=[
                {"sku": "P1", "width_in": 6, "weekly_demand_units": 70, "facings": 4, "capacity_units": 40, "position_index": 1},
                {"sku": "P2", "width_in": 6, "weekly_demand_units": 70, "facings": 4, "capacity_units": 40, "position_index": 2},
            ],
            category_overrides={"code": "C", "role": "ROUTINE", "annual_sales_cents": 100_000, "total_linear_feet": 20},
        )
        rid, cid = retailer["id"], category["id"]
        # Brand-new store with nothing installed
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="STN", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pg["id"], store["id"], scheduled_start="2026-06-01T08:00:00Z", scheduled_end="2026-06-01T16:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        assert rp["labor_hours_estimated"] == pytest.approx(0.9, abs=0.001)


class TestComplianceScoreNestedRounding:
    def test_floor_applied_before_classification_warn_band(self, api):
        """PRD §3.7: "the platform computes `compliance_score_pct`: zero when
        `total_facings_expected` is zero, otherwise the floor — the greatest
        integer not exceeding the exact quotient — of one hundred times
        `matched_facings` divided by `total_facings_expected`."
        PRD §3.7: "a score below the threshold but greater than or equal to
        ten points under it is a `WARN`."

        Design: Difficulty/combinatorial_formula/compliance_score_nested_rounding
        """
        # total_facings=23, matched=19 → 100*19/23 = 82.608… → floor=82
        # threshold=85; WARN band is [75, 85); 82 in WARN band → WARN.
        # (Round-half-up would have given 83, still WARN; the discriminating case
        # is matched=20 which would round-half-up to 87 → PASS either way. We pin
        # floor through matched=19 → exactly 82.)
        # 12 linear feet = 144in; 23 facings x 6in = 138in → 95.8% utilization,
        # under the §3.5 submission cap of 100%.
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": 23, "capacity_units": 230, "position_index": 1},
            retailer_overrides={"compliance_threshold_pct": 85},
            category_overrides={"total_linear_feet": 12},
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 19}, TEST_USERS["audit_reviewer_headers"])
        data = validate_success(resp)
        assert data["compliance_score_pct"] == 82
        assert data["compliance_outcome"] == "WARN"

    def test_floor_applied_before_classification_pass_band(self, api):
        """PRD §3.7: "a score greater than or equal to the threshold is a
        `PASS` (a score exactly equal to the threshold passes)."

        Design: Difficulty/combinatorial_formula/compliance_score_nested_rounding
        """
        # total_facings=23, matched=20 → 100*20/23 = 86.95… → floor=86
        # threshold=85 → 86 >= 85 → PASS.
        # 12 linear feet = 144in; 23 facings x 6in = 138in → 95.8% utilization,
        # under the §3.5 submission cap of 100%.
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": 23, "capacity_units": 230, "position_index": 1},
            retailer_overrides={"compliance_threshold_pct": 85},
            category_overrides={"total_linear_feet": 12},
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 20}, TEST_USERS["audit_reviewer_headers"])
        data = validate_success(resp)
        assert data["compliance_score_pct"] == 86
        assert data["compliance_outcome"] == "PASS"
