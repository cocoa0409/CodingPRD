"""Validation corner tests: window, discontinuation date, audit range, line rules, archive."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_planogram_payload,
    create_reset_project_payload,
    setup_approved_planogram,
    setup_category_with_listed_product,
    setup_draft_planogram_with_line,
    setup_planogram_in_review,
    setup_submitted_audit,
    validate_error,
    validate_success,
)


class TestResetWindowValidation:
    def test_violation_reset_window_inverted(self, api, reset_coordinator_headers):
        """PRD §3.9: "The window itself must be sound: `scheduled_start`
        strictly earlier than `scheduled_end`, and no overlap with any other
        project at the same store that is currently `SCHEDULED` or
        `IN_PROGRESS`. ... any violation of these window rules is rejected
        with `ERR_RESET_WINDOW_CONFLICT`."

        Design: Corner/validations/violation_reset_window_inverted
        """
        from test_helpers import create_store_payload
        retailer, category, supplier, product, pg, line = setup_approved_planogram(
            product_overrides={"weekly_demand_units": 100}
        )
        rid, cid = retailer["id"], category["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        # inverted window: start > end
        resp = api.create_reset_project(
            rid,
            cid,
            create_reset_project_payload(
                pg["id"],
                store["id"],
                scheduled_start="2026-06-01T12:00:00Z",
                scheduled_end="2026-06-01T10:00:00Z",
            ),
            reset_coordinator_headers,
        )
        # The PRD allows ERR_RESET_WINDOW_CONFLICT for window-rule violations;
        # if the implementer classifies a start>=end payload as malformed, ERR_INVALID_REQUEST
        # is also faithful to PRD §2.8. We accept either to honor unique derivability.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(resp, [ApiErrorId.ERR_RESET_WINDOW_CONFLICT, ApiErrorId.ERR_INVALID_REQUEST])


class TestDiscontinuationDate:
    def test_violation_discontinuation_date_in_past(self, api, platform_admin_headers, category_manager_headers):
        """PRD §3.3: "That write carries two inputs: `discontinuation_effective_date`,
        which must lie strictly in the future at the moment of the call — a past
        or present date is rejected with `ERR_DISCONTINUATION_DATE_PAST`."

        Design: Corner/validations/violation_discontinuation_date_in_past
        """
        from test_helpers import create_retailer_payload, create_category_payload, create_supplier_payload, create_product_payload
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        # Move clock forward to 2026-05-15
        validate_success(
            api.set_current_utc(rid, {"to_iso8601": "2026-05-15T00:00:00Z"}, platform_admin_headers)
        )
        cat = validate_success(
            api.create_category(rid, create_category_payload(code="C"), category_manager_headers),
            expected_status=201,
        )
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        prod = validate_success(
            api.create_product(
                rid,
                create_product_payload(cat["id"], supplier["id"], sku="P", weekly_demand_units=50),
                category_manager_headers,
            ),
            expected_status=201,
        )
        pid = prod["id"]
        validate_success(api.list_product_cut_in(rid, pid, category_manager_headers))
        pv = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        # discontinuation_effective_date in the past (clock is 2026-05-15)
        resp = api.discontinue_product(
            rid,
            pid,
            {
                "discontinuation_effective_date": "2026-05-01T00:00:00Z",
                "expected_product_version": pv,
            },
            category_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DISCONTINUATION_DATE_PAST)


class TestAuditScoreRange:
    def test_violation_audit_score_out_of_range(self, api, audit_reviewer_headers):
        """PRD §3.7: "the count itself must lie between zero and
        `total_facings_expected` inclusive, else `ERR_AUDIT_SCORE_RANGE`."

        Design: Corner/validations/violation_audit_score_out_of_range
        """
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": 10, "capacity_units": 100, "position_index": 1},
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        # planogram total_facings == 10; matched=99 out of range
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 99}, audit_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_SCORE_RANGE)


class TestPlanogramLineValidation:
    def test_violation_line_capacity_less_than_facings(self, api, category_manager_headers):
        """PRD §3.4: "`facings` must be at least one, `capacity_units` must be
        at least the line's `facings`, and `position_index` must not collide
        with another line in the same planogram — with any violation rejected
        as `ERR_LINE_INVALID`."

        Design: Corner/validations/violation_line_capacity_less_than_facings
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        resp = api.create_planogram_line(
            rid,
            cid,
            pgid,
            {"product_id": product["id"], "position_index": 2, "facings": 10, "capacity_units": 3},
            category_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_INVALID)


class TestCategoryArchiveBlocked:
    def test_violation_category_archive_with_open_work(self, api, category_manager_headers):
        """PRD §3.1: "a `CategoryManager` may move an `OPEN` category to
        `ARCHIVED` only when no planogram for the category remains in `DRAFT`,
        `IN_REVIEW`, `APPROVED`, or `ACTIVE`, and no reset project for the
        category remains in `PROPOSED`, `SCHEDULED`, or `IN_PROGRESS`;
        otherwise the archive is rejected with `ERR_CATEGORY_HAS_OPEN_WORK`."

        Design: Corner/validations/violation_category_archive_with_open_work
        """
        from test_helpers import create_retailer_payload, create_category_payload, create_supplier_payload, create_planogram_payload
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(rid, create_category_payload(code="C"), category_manager_headers),
            expected_status=201,
        )
        cid = cat["id"]
        validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        # Planogram in DRAFT under the category → archive must be blocked
        validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(), category_manager_headers),
            expected_status=201,
        )
        resp = api.archive_category(rid, cid, category_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_HAS_OPEN_WORK)
