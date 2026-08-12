"""Cross-cutting corner tests: OCC success path, derived-field reconciliation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_planogram_payload,
    setup_approved_planogram,
    setup_category_with_listed_product,
    validate_success,
)


class TestOCCSuccess:
    def test_occ_correct_version_succeeds(self, api, category_manager_headers):
        """PRD §2.7: "Each requires a non-optional expected-version field in
        its request body, carrying the caller's last observed `version` of the
        entity the operation acts upon".
        PRD §3.5: "The planogram becomes `ACTIVE` and the category's `version`
        increments by one".

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        retailer, category, supplier, product, pg, line = setup_approved_planogram()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        cat_now = validate_success(api.get_category(rid, cid, category_manager_headers))
        cv = cat_now["version"]
        resp = api.activate_planogram(
            rid, cid, pgid, {"expected_category_version": cv}, category_manager_headers
        )
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"
        # Category version must have incremented by 1 per PRD §3.5
        cat_after = validate_success(api.get_category(rid, cid, category_manager_headers))
        assert cat_after["version"] == cv + 1


class TestDerivedFieldReconciliation:
    def test_derived_fields_recompute_on_line_add_and_delete(self, api, category_manager_headers):
        """PRD §3.4: "`total_facings` is the sum of `facings` across the
        planogram's non-deleted lines, and `total_capacity_units` is the
        corresponding sum of `capacity_units`."
        PRD §3.4: "deletion answers with no content and, like every line
        mutation, triggers a full recomputation of the planogram's derived
        values."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_line_add
        """
        # 10 linear feet = 120 inches. width=6, facings=5 → 30 inches → 25.0%
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"width_in": 6, "weekly_demand_units": 50},
            category_overrides={"total_linear_feet": 10},
        )
        rid, cid = retailer["id"], category["id"]
        # Fresh DRAFT planogram so we control line count from zero.
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG2", variant="BASE"), category_manager_headers),
            expected_status=201,
        )
        pgid = pg["id"]
        # Add a single line — verify totals jump
        line = validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": product["id"], "position_index": 1, "facings": 5, "capacity_units": 50},
                category_manager_headers,
            ),
            expected_status=201,
        )
        pg_after_add = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))
        assert pg_after_add["total_facings"] == 5
        assert pg_after_add["shelf_utilization_pct"] == pytest.approx(25.0, abs=0.01)
        # Delete the line — totals fall back to zero
        resp = api.delete_planogram_line(rid, cid, pgid, line["id"], category_manager_headers)
        assert resp.status_code == 204
        pg_after_del = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))
        assert pg_after_del["total_facings"] == 0
        assert pg_after_del["shelf_utilization_pct"] == pytest.approx(0.0, abs=0.001)
