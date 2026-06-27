"""Role-based access control and authentication.

Queue B (corner) — rbac section.
"""
from test_helpers import (
    validate_success, validate_error,
    create_variety_payload, TEST_USERS,
    make_broker_headers, make_role_headers,
    setup_broker_owned_draft_order, setup_published_lot, create_broker, create_draft_order,
)

PT = TEST_USERS["production_tech_headers"]


def test_production_tech_cannot_create_variety(api):
    """PRD 2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/production_tech_cannot_create_variety
    """
    resp = api.create_variety(create_variety_payload(
        common_name="X", cultivar_code="XXX1"), PT)
    validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


def test_broker_cannot_confirm_order(api):
    """PRD 2.1: "A broker may create and edit its own draft orders and lines and read
    its own commercial data, but it cannot confirm or ship."

    Design: Corner/rbac/broker_cannot_confirm_order
    """
    s = setup_broker_owned_draft_order(api, quantity=10)
    bh = make_broker_headers(s["broker"]["id"])
    ov = validate_success(api.get_order(s["order"]["id"], bh))["version"]
    resp = api.confirm_order(s["order"]["id"], {"expected_order_version": ov}, bh)
    validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


def test_broker_cannot_add_line_to_other_brokers_order(api):
    """PRD 2.1: "when a `Broker` acts on an order, that order's `broker_id` must equal
    `X-User-ID`, and any certificate or order foreign-key target named in the request
    must belong to the same broker; a violation of this ownership rule is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/broker_cannot_act_on_other_brokers_order
    """
    lot = setup_published_lot(api, unit_price_cents=300, sourced=30, started=30, cultivar_code="OWR1")
    broker_a = create_broker(api, ship_to_state="OR", company_name="A")
    broker_b = create_broker(api, ship_to_state="OR", company_name="B")
    order_a = create_draft_order(api, broker_a["id"], headers=make_broker_headers(broker_a["id"]))
    resp = api.add_order_line(
        order_a["id"], {"availability_entry_id": lot["entry"]["id"], "quantity": 10},
        make_broker_headers(broker_b["id"]))
    validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


def test_unknown_role_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_varieties(make_role_headers("u1", "NoSuchRole"))
    validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)
