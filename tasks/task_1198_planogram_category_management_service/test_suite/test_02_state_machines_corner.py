"""State-machine corner tests: initial states, invalid transitions, terminal states."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_audit_payload,
    create_category_payload,
    create_funding_deal_payload,
    create_planogram_payload,
    create_product_payload,
    create_retailer_payload,
    create_store_payload,
    create_supplier_payload,
    setup_active_planogram,
    setup_draft_planogram_with_line,
    setup_planogram_in_review,
    setup_submitted_audit,
    validate_error,
    validate_success,
)


class TestPlanogramStateMachine:
    def test_planogram_initial_state_is_draft(self, api, platform_admin_headers, category_manager_headers):
        """PRD §3.4: "A fresh planogram sits in `DRAFT` with `total_facings`,
        `total_capacity_units`, and `shelf_utilization_pct` all at zero."

        Design: Corner/state_machines/planogram_initial_state_is_draft
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(rid, create_category_payload(code="C"), category_manager_headers),
            expected_status=201,
        )
        cid = cat["id"]
        resp = api.create_planogram(rid, cid, create_planogram_payload(), category_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"

    def test_planogram_activate_from_draft_rejected(self, api, category_manager_headers):
        """PRD §2.8: "Fifth, the target entity must be in a state that permits
        the requested transition, else `ERR_INVALID_STATE`."
        PRD §3.5: "A `CategoryManager` activates an `APPROVED` planogram by
        supplying `expected_category_version`."

        Design: Corner/state_machines/planogram_activate_from_draft_rejected
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        # Read category version for OCC
        cat_now = validate_success(api.get_category(rid, cid, category_manager_headers))
        resp = api.activate_planogram(
            rid, cid, pgid, {"expected_category_version": cat_now["version"]}, category_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_planogram_rejected_terminal_lockdown(self, api, category_manager_headers):
        """PRD §3.5: "Rejection, also a `CategoryManager` action, moves an
        `IN_REVIEW` planogram to `REJECTED` with no further conditions."
        PRD §2.8: "the target entity must be in a state that permits the
        requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/planogram_rejected_terminal_lockdown
        """
        retailer, category, supplier, product, pg, line = setup_planogram_in_review()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        # Drive to REJECTED
        validate_success(api.reject_planogram(rid, cid, pgid, category_manager_headers))
        # Attempt to approve from REJECTED — terminal state
        resp = api.approve_planogram(rid, cid, pgid, category_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAuditTerminalLockdown:
    def test_audit_score_terminal_lockdown(self, api, audit_reviewer_headers):
        """PRD §3.7: "an audit in any other state cannot be scored
        (`ERR_INVALID_STATE`)"."

        Design: Corner/state_machines/audit_score_terminal_lockdown
        """
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100}
        )
        rid, sid, aid = retailer["id"], store["id"], audit["id"]
        # First score — success
        validate_success(api.score_audit(rid, sid, aid, {"matched_facings": 4}, audit_reviewer_headers))
        # Second score attempt — must be rejected
        resp = api.score_audit(rid, sid, aid, {"matched_facings": 5}, audit_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestProductDelistedTerminal:
    def test_product_delisted_terminal(self, api, platform_admin_headers, category_manager_headers):
        """PRD §3.3: "Once the logical clock reaches a `DISCONTINUING` product's
        `discontinuation_effective_date`, the product becomes `DELISTED`."
        PRD §2.8: "the target entity must be in a state that permits the
        requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/product_delisted_terminal
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line(
            product_overrides={"weekly_demand_units": 50}
        )
        rid, pid = retailer["id"], product["id"]
        # Discontinue effective 2026-06-01
        pv = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        validate_success(
            api.discontinue_product(
                rid,
                pid,
                {
                    "discontinuation_effective_date": "2026-06-01T00:00:00Z",
                    "expected_product_version": pv,
                },
                category_manager_headers,
            )
        )
        # Advance clock past effective date → DELISTED
        validate_success(
            api.set_current_utc(rid, {"to_iso8601": "2026-06-02T00:00:00Z"}, platform_admin_headers)
        )
        pv2 = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        # Attempt to discontinue a DELISTED product — invalid state
        resp = api.discontinue_product(
            rid,
            pid,
            {
                "discontinuation_effective_date": "2026-07-01T00:00:00Z",
                "expected_product_version": pv2,
            },
            category_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFundingDealClockTransitions:
    def test_funding_deal_active_via_clock(self, api, platform_admin_headers, retailer_admin_headers):
        """PRD §2.9: "funding deals in `APPROVED` whose window has opened become
        `ACTIVE`."
        PRD §3.8: "when the logical clock reaches `starts_at`, an `APPROVED`
        deal becomes `ACTIVE`."

        Design: Corner/state_machines/funding_deal_active_via_clock
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid, create_category_payload(code="C"), TEST_USERS["category_manager_headers"]
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), retailer_admin_headers),
            expected_status=201,
        )
        sid = supplier["id"]
        deal = validate_success(
            api.create_funding_deal(
                rid,
                create_funding_deal_payload(cid, sid, starts_at="2026-06-01T00:00:00Z", ends_at="2026-07-01T00:00:00Z"),
                retailer_admin_headers,
            ),
            expected_status=201,
        )
        fdid, fdv = deal["id"], deal["version"]
        validate_success(
            api.approve_funding_deal(
                rid, fdid, {"expected_funding_deal_version": fdv}, retailer_admin_headers
            )
        )
        # Advance clock past starts_at
        validate_success(
            api.set_current_utc(rid, {"to_iso8601": "2026-06-02T00:00:00Z"}, platform_admin_headers)
        )
        got = validate_success(api.get_funding_deal(rid, fdid, retailer_admin_headers))
        assert got["status"] == "ACTIVE"
