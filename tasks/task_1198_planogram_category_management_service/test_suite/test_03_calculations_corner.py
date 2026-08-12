"""Calculation corner tests: dos sentinel, shelf utilization, compliance score."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_retailer_payload,
    setup_active_planogram,
    setup_category_with_listed_product,
    setup_draft_planogram_with_line,
    setup_submitted_audit,
    validate_error,
    validate_success,
)


class TestDosZeroDemandSentinel:
    def test_dos_zero_demand_sentinel(self, api, category_manager_headers):
        """PRD §2.6: "A days-of-supply computation facing a product with zero
        weekly demand reports the sentinel 9999.0 rather than an infinite or
        missing value."
        PRD §3.4: "one lasting strictly more than 21.0 days is flagged
        `OVERSTOCK`."

        Design: Corner/calculations/dos_zero_demand_sentinel
        """
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"sku": "P", "weekly_demand_units": 0},
        )
        rid, cid = retailer["id"], category["id"]
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(), category_manager_headers),
            expected_status=201,
        )
        resp = api.create_planogram_line(
            rid,
            cid,
            pg["id"],
            {"product_id": product["id"], "position_index": 1, "facings": 2, "capacity_units": 10},
            category_manager_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["days_of_supply"] == 9999.0
        assert data["dos_flag"] == "OVERSTOCK"


class TestShelfUtilization:
    def test_shelf_utilization_computed_correctly(self, api, category_manager_headers):
        """PRD §3.4: "`shelf_utilization_pct` measures footprint: it is one
        hundred times the total shelf inches consumed — the sum, across lines
        whose product is `LISTED` or `DISCONTINUING`, of each line's `facings`
        multiplied by its product's `width_in` — divided by the category's
        total shelf inches, which is its `total_linear_feet` multiplied by
        twelve; the result is rounded half-up to one decimal place."

        Design: Corner/calculations/shelf_utilization_computed_correctly
        """
        # 10 linear feet → 120 inches. Line1: 5 facings × 6in = 30 in.
        # Line2: 5 facings × 12in = 60 in. Total 90/120 = 75.0%.
        retailer, category, supplier, p1 = setup_category_with_listed_product(
            product_overrides={"sku": "P1", "width_in": 6, "weekly_demand_units": 50},
            category_overrides={"code": "C", "total_linear_feet": 10},
        )
        rid, cid, sid = retailer["id"], category["id"], supplier["id"]
        # second product width 12
        from test_helpers import create_product_payload
        p2_resp = api.create_product(
            rid,
            create_product_payload(cid, sid, sku="P2", width_in=12, weekly_demand_units=50),
            category_manager_headers,
        )
        p2 = validate_success(p2_resp, expected_status=201)
        validate_success(api.list_product_cut_in(rid, p2["id"], category_manager_headers))

        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(), category_manager_headers),
            expected_status=201,
        )
        validate_success(
            api.create_planogram_line(
                rid, cid, pg["id"],
                {"product_id": p1["id"], "position_index": 1, "facings": 5, "capacity_units": 50},
                category_manager_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_planogram_line(
                rid, cid, pg["id"],
                {"product_id": p2["id"], "position_index": 2, "facings": 5, "capacity_units": 50},
                category_manager_headers,
            ),
            expected_status=201,
        )
        pg_now = validate_success(api.get_planogram(rid, cid, pg["id"], category_manager_headers))
        assert pg_now["shelf_utilization_pct"] == pytest.approx(75.0, abs=0.01)


class TestComplianceScoreEdgeCases:
    def test_compliance_score_zero_facings(self, api, audit_reviewer_headers):
        """PRD §3.7: "the platform computes `compliance_score_pct`: zero when
        `total_facings_expected` is zero, otherwise the floor — the greatest
        integer not exceeding the exact quotient — of one hundred times
        `matched_facings` divided by `total_facings_expected`."

        Design: Corner/calculations/compliance_score_zero_facings
        """
        # Planogram with total_facings=1 (facings=1). Score with matched=0 → 0.
        # capacity_units=50 keeps dos = 50/(100/7) = 3.5 → OK, so the line
        # clears the §3.5 understock screen at approval (ROUTINE category).
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": 1, "capacity_units": 50, "position_index": 1},
            retailer_overrides={"compliance_threshold_pct": 85},
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 0}, audit_reviewer_headers)
        data = validate_success(resp)
        # matched=0 / expected=1 → floor(0) == 0, no divide-by-zero crash
        assert data["compliance_score_pct"] == 0
        assert isinstance(data["compliance_score_pct"], int)

    def test_compliance_outcome_boundary_at_threshold(self, api, audit_reviewer_headers):
        """PRD §3.7: "a score greater than or equal to the threshold is a
        `PASS` (a score exactly equal to the threshold passes); a score below
        the threshold but greater than or equal to ten points under it is a
        `WARN`; anything lower is a `FAIL`."

        Design: Corner/calculations/compliance_outcome_boundary_at_threshold
        """
        # 17/20 = 85 → floor=85 → == threshold 85 → PASS (>=, not >).
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": 20, "capacity_units": 200, "position_index": 1},
            retailer_overrides={"compliance_threshold_pct": 85},
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 17}, audit_reviewer_headers)
        data = validate_success(resp)
        assert data["compliance_score_pct"] == 85
        assert data["compliance_outcome"] == "PASS"
