"""Not-found answers for every one of the twenty-two entity types."""


from test_helpers import (
    ADMIN,
    CLERK,
    COORD,
    UNKNOWN_UUIDS,
    WAREHOUSE,
    ApiErrorId,
    setup_clock_only,
    validate_error,
)


def test_unknown_brokerage_id_answers_err_brokerage_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/brokerage_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_brokerage(UNKNOWN_UUIDS["brokerage"], ADMIN)

    validate_error(resp, ApiErrorId.ERR_BROKERAGE_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_client_id_answers_err_client_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/client_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_client(UNKNOWN_UUIDS["client"], ADMIN)

    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_property_id_answers_err_property_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/property_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_property(UNKNOWN_UUIDS["property"], COORD)

    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_listing_id_answers_err_listing_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/listing_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_listing(UNKNOWN_UUIDS["listing"], COORD)

    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_package_tier_id_answers_err_tier_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/package_tier_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_package_tier(UNKNOWN_UUIDS["tier"], COORD)

    validate_error(resp, ApiErrorId.ERR_TIER_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_vendor_id_answers_err_vendor_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/vendor_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_vendor(UNKNOWN_UUIDS["vendor"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_inventory_item_id_answers_err_item_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/inventory_item_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_inventory_item(UNKNOWN_UUIDS["item"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_consultation_id_answers_err_consultation_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/consultation_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_consultation(UNKNOWN_UUIDS["consultation"], COORD)

    validate_error(resp, ApiErrorId.ERR_CONSULTATION_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_scope_item_id_answers_err_scope_item_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/scope_item_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_scope_item(UNKNOWN_UUIDS["scope_item"], COORD)

    validate_error(resp, ApiErrorId.ERR_SCOPE_ITEM_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_project_id_answers_err_project_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/project_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_project(UNKNOWN_UUIDS["project"], COORD)

    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_pull_id_answers_err_pull_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/pull_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_pull(UNKNOWN_UUIDS["pull"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_PULL_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_pull_line_id_answers_err_pull_line_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/pull_line_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_pull_line(UNKNOWN_UUIDS["pull_line"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_PULL_LINE_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_rental_order_id_answers_err_order_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/rental_order_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_rental_order(UNKNOWN_UUIDS["rental_order"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_install_id_answers_err_install_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/install_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_install(UNKNOWN_UUIDS["install"], COORD)

    validate_error(resp, ApiErrorId.ERR_INSTALL_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_visit_id_answers_err_visit_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/visit_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_visit(UNKNOWN_UUIDS["visit"], COORD)

    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_lease_id_answers_err_lease_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/lease_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_lease(UNKNOWN_UUIDS["lease"], COORD)

    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_extension_id_answers_err_extension_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/extension_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_extension(UNKNOWN_UUIDS["extension"], COORD)

    validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_pickup_id_answers_err_pickup_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/pickup_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_pickup(UNKNOWN_UUIDS["pickup"], COORD)

    validate_error(resp, ApiErrorId.ERR_PICKUP_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_damage_assessment_id_answers_err_assessment_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/damage_assessment_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_damage_assessment(UNKNOWN_UUIDS["assessment"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_photo_shoot_id_answers_err_shoot_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/photo_shoot_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_photo_shoot(UNKNOWN_UUIDS["shoot"], COORD)

    validate_error(resp, ApiErrorId.ERR_SHOOT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_invoice_id_answers_err_invoice_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/invoice_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_invoice(UNKNOWN_UUIDS["invoice"], CLERK)

    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_unknown_deposit_id_answers_err_deposit_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PULL_NOT_FOUND`,
    `ERR_PULL_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSTALL_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SHOOT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`, each answering HTTP 404."

    Design: Corner/entities/deposit_not_found_returns_404
    """
    setup_clock_only()

    resp = api.get_deposit(UNKNOWN_UUIDS["deposit"], CLERK)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"
