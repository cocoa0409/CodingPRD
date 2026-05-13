"""Product association ladder, stock reservation, during-broadcast rules.

PRD §3.3 — Product catalog and stock reservation.
"""

import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    setup_open_studio,
    setup_draft_application,
    setup_scheduled_application,
    attach_compatible_product,
    submit_application,
    create_product,
    update_product_payload,
    associate_product_payload,
    fetch_application,
    go_live,
    ERR_STOCK_INSUFFICIENT,
    ERR_PRODUCT_CERT_MISSING,
    ERR_PRODUCT_CATEGORY_MISMATCH,
    ERR_PRODUCT_NOT_ON_SHELF,
    ERR_LIVE_ASSOCIATION_DENIED,
)
from test_helpers.fixtures import get_product


class TestPreApprovalAssociation:
    """PRD §3.3: pre-approval association sets phase PRE_APPROVAL and runs the
    eligibility ladder.
    """

    def test_associate_sets_phase_pre_approval_in_draft(self, api):
        """PRD §3.3: "If the application is still in pre-approval review
        (review_status of DRAFT, OPS_PENDING, or COMPLIANCE_PENDING), the
        resulting ProductAssociation receives association_phase PRE_APPROVAL;
        otherwise the association is recorded with association_phase
        DURING_BROADCAST."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application(declared_product_categories=["FOOD"])
        product = create_product(category="FOOD", available_stock=100)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=5)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["association_phase"] == "PRE_APPROVAL"
        assert data["status"] == "APPROVED"

    def test_stock_decrements_and_reserved_increments(self, api):
        """PRD §3.3: "the server decrements the product's available_stock by
        reserved_quantity and increments its reserved_stock by the same
        amount..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application(declared_product_categories=["FOOD"])
        product = create_product(category="FOOD", available_stock=100)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=30)
        validate_success(api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"])),
                         expected_status=201)
        product_after = get_product(product["id"])
        assert product_after["available_stock"] == 70
        assert product_after["reserved_stock"] == 30


class TestEligibilityLadder:
    """PRD §3.3: 'The product-eligibility ladder is evaluated in strict order,
    and the first failing rule pins the association's reject_reason.'
    """

    def test_off_shelf_product_returns_not_on_shelf_error(self, api):
        """PRD §3.3: "The product must currently be ON_SHELF — if its status is
        OFF_SHELF, the association is rejected with reject_reason NOT_ON_SHELF
        and ERR_PRODUCT_NOT_ON_SHELF (HTTP 422)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application(declared_product_categories=["FOOD"])
        product = create_product(category="FOOD", available_stock=50)
        validate_success(api.update_product(
            product["id"], {"status": "OFF_SHELF", "version": product["version"]}, ADMIN_HEADERS
        ))
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=5)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_PRODUCT_NOT_ON_SHELF, expected_status=422)

    def test_category_mismatch_returns_category_mismatch(self, api):
        """PRD §3.3: "The product's category must appear in the application's
        declared_product_categories — otherwise reject_reason is
        CATEGORY_MISMATCH and the response is ERR_PRODUCT_CATEGORY_MISMATCH
        (HTTP 422)."
        """
        set_clock(DEFAULT_BASE_TIME)
        # Application declares FOOD; product is COSMETICS
        streamer, studio, app = setup_draft_application(declared_product_categories=["FOOD"])
        product = create_product(category="COSMETICS", available_stock=50)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=2)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_PRODUCT_CATEGORY_MISMATCH, expected_status=422)

    def test_missing_cert_returns_cert_missing(self, api):
        """PRD §3.3: "If the product's requires_professional_cert is true, the
        product's category must appear in the streamer's
        professional_cert_categories list — otherwise reject_reason is
        MISSING_CERT and the response is ERR_PRODUCT_CERT_MISSING (HTTP 422)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer(professional_cert_categories=["FOOD"])
        streamer, studio, app = setup_draft_application(
            streamer=streamer,
            declared_product_categories=["COSMETICS"],
        )
        product = create_product(category="COSMETICS", requires_professional_cert=True, available_stock=10)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=2)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_PRODUCT_CERT_MISSING, expected_status=422)

    def test_stock_exceeded_returns_stock_insufficient(self, api):
        """PRD §3.3: "Finally the requested reserved_quantity must not exceed
        the product's current available_stock — otherwise reject_reason is
        STOCK_INSUFFICIENT and the response is ERR_STOCK_INSUFFICIENT
        (HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application(declared_product_categories=["FOOD"])
        product = create_product(category="FOOD", available_stock=3)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=10)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_STOCK_INSUFFICIENT, expected_status=409)


class TestEligibilityLadderOrdering:
    """PRD §2.9: 'the certification check precedes the category-match check,
    which precedes the on-shelf check, which precedes the stock check.'

    Tests pair-by-pair according to §2.9's strict order. Difficulty-design
    Rule 5 instance 2 (business_safety vs business_fiscal) maps here.
    """

    def test_cert_check_precedes_stock_check(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_product_association
        PRD §2.9: "on a product association the certification check precedes
        the category-match check, which precedes the on-shelf check, which
        precedes the stock check."
        """
        set_clock(DEFAULT_BASE_TIME)
        # Streamer lacks COSMETICS cert; product is COSMETICS with low stock;
        # application declares COSMETICS so category matches but cert fails.
        streamer = setup_active_streamer(professional_cert_categories=["FOOD"])
        streamer, studio, app = setup_draft_application(
            streamer=streamer,
            declared_product_categories=["COSMETICS"],
        )
        product = create_product(
            category="COSMETICS",
            requires_professional_cert=True,
            available_stock=2,  # would trigger stock error if reached
        )
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=100)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        # Cert error must win (priority 9) over stock error (priority 15)
        validate_error(resp, ERR_PRODUCT_CERT_MISSING, expected_status=422)


class TestDuringBroadcastAssociation:
    """PRD §3.6: 'A LIVE broadcast may add new product associations on the fly.'"""

    def test_live_association_sets_phase_during_broadcast(self, api):
        """PRD §3.6: "A LIVE broadcast may add new product associations on the
        fly: the request supplies product_id and reserved_quantity, and the
        resulting ProductAssociation records association_phase DURING_BROADCAST."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        # Walk to LIVE
        app = go_live(streamer, app)
        # Now add a product
        product = create_product(category="FOOD", available_stock=10)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=1)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["association_phase"] == "DURING_BROADCAST"

    def test_live_association_with_mismatched_category_rejected(self, api):
        """PRD §3.6: "During-broadcast associations are gated by an extra rule:
        the product's category must already appear in the application's
        declared_product_categories ... Violating either constraint yields
        ERR_LIVE_ASSOCIATION_DENIED (HTTP 422)."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        # Application declared FOOD (default); product is COSMETICS
        product = create_product(category="COSMETICS", available_stock=10)
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=1)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_LIVE_ASSOCIATION_DENIED, expected_status=422)
