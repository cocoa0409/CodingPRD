"""Per-entity not-found codes for identifiers that were never issued.

Each single-resource read is mounted directly under `/colocation`, so the only path
identifier it carries is the entity's own; a syntactically valid identifier that names
no stored row must report that entity's own 404 code rather than a shared one.
"""

from test_helpers import ApiErrorId, NON_EXISTENT_UUID, fixtures as fx, validate_error


def test_cabinet_read_with_an_unissued_identifier_reports_the_cabinet_code(
    api, facility_manager_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/cabinet_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_cabinet(NON_EXISTENT_UUID, facility_manager_headers),
        ApiErrorId.ERR_CABINET_NOT_FOUND,
    )


def test_power_circuit_read_with_an_unissued_identifier_reports_the_circuit_code(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/power_circuit_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_power_circuit(NON_EXISTENT_UUID, provisioning_engineer_headers),
        ApiErrorId.ERR_CIRCUIT_NOT_FOUND,
    )


def test_patch_panel_port_read_with_an_unissued_identifier_reports_the_port_code(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/patch_panel_port_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_patch_panel_port(NON_EXISTENT_UUID, provisioning_engineer_headers),
        ApiErrorId.ERR_PORT_NOT_FOUND,
    )


def test_cross_connect_order_read_with_an_unissued_identifier_reports_its_own_code(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/cross_connect_order_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_cross_connect_order(NON_EXISTENT_UUID, provisioning_engineer_headers),
        ApiErrorId.ERR_CROSS_CONNECT_ORDER_NOT_FOUND,
    )


def test_remote_hands_ticket_read_with_an_unissued_identifier_reports_the_ticket_code(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/remote_hands_ticket_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_remote_hands_ticket(NON_EXISTENT_UUID, provisioning_engineer_headers),
        ApiErrorId.ERR_TICKET_NOT_FOUND,
    )


def test_access_visit_read_with_an_unissued_identifier_reports_the_visit_code(
    api, security_officer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/access_visit_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_access_visit(NON_EXISTENT_UUID, security_officer_headers),
        ApiErrorId.ERR_VISIT_NOT_FOUND,
    )


def test_decommission_order_read_with_an_unissued_identifier_reports_its_own_code(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/decommission_order_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_decommission_order(NON_EXISTENT_UUID, provisioning_engineer_headers),
        ApiErrorId.ERR_DECOMMISSION_ORDER_NOT_FOUND,
    )


def test_invoice_line_read_with_an_unissued_identifier_reports_the_ledger_code(
    api, billing_operator_headers
):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."
    PRD §2.10: "Path identifiers are nonetheless resolved left to right, and the first identifier that does not resolve decides the 404 code — `customer_id`, `contract_id`, `row_id`, `cabinet_id`, `circuit_id`, `port_id`, `order_id`, `ticket_id`, `contact_id`, `visit_id` and `invoice_line_id` each map to their own not-found code as listed in §2.5."

    Design: Corner/errors/invoice_line_get_with_unissued_uuid_returns_not_found
    """
    fx.set_clock(api)
    validate_error(
        api.get_invoice_line(NON_EXISTENT_UUID, billing_operator_headers),
        ApiErrorId.ERR_INVOICE_LINE_NOT_FOUND,
    )
