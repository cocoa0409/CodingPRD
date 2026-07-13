"""Role-based access control, user-context validation, existence/well-formedness errors,
and list pagination."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Corner: rbac / designer_cannot_create_order_returns_forbidden
# ---------------------------------------------------------------------------
def test_designer_cannot_create_order_returns_forbidden(api):
    """PRD §2.1: "When a role attempts an operation it is not authorized to perform, the request
    is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/designer_cannot_create_order_returns_forbidden
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"])
    resp = api.create_order(payload, th.TEST_USERS["designer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# Corner: rbac / nonowner_customer_cannot_cancel_order_returns_forbidden
# ---------------------------------------------------------------------------
def test_nonowner_customer_cannot_cancel_order_returns_not_resource_owner(api):
    """PRD §2.1: "for customer-scoped writes — cancelling an order, recording a payment, approving
    or requesting changes on a design proof, and requesting a restoration — the acting customer's
    `X-User-ID` must equal the `customer_id` of the owning order, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/nonowner_customer_cannot_cancel_order_returns_forbidden
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust_a = th.make_customer(full_name="Cust A", email="a@example.com")
    cust_b = th.make_customer(full_name="Cust B", email="b@example.com")
    order = th.make_order(cust_a, cem)
    resp = api.cancel_order(order["id"], th.make_customer_headers(cust_b["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ---------------------------------------------------------------------------
# Corner: rbac / order_create_missing_x_user_header_returns_error
# ---------------------------------------------------------------------------
def test_order_create_missing_role_header_returns_missing_user_context(api):
    """PRD §2.1: "A request missing either header, or carrying a header that is malformed, is
    rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/order_create_missing_x_user_header_returns_error
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"])
    # Strip the X-User-Role header — only X-User-ID is supplied.
    resp = api.create_order(payload, {"X-User-ID": cust["id"]})
    th.validate_error(resp, th.ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ---------------------------------------------------------------------------
# Corner: entities / order_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_unknown_order_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/entities/order_not_found_returns_404
    """
    resp = api.get_order(th.NON_EXISTENT_UUID, th.TEST_USERS["admin_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_ORDER_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: entities / order_missing_material_returns_invalid_request
# ---------------------------------------------------------------------------
def test_order_missing_material_returns_invalid_request(api):
    """PRD §2.10: "then request well-formedness — required fields present, enum members valid,
    schedule window valid, and a permit's `cemetery_id` equal to its order's `cemetery_id` —
    surfacing `ERR_INVALID_REQUEST` or `ERR_INVALID_SCHEDULE_WINDOW`".

    Design: Corner/entities/order_missing_material_returns_invalid_request
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"])
    payload.pop("material")
    resp = api.create_order(payload, th.make_customer_headers(cust["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: entities / order_invalid_subject_type_enum_returns_invalid_request
# ---------------------------------------------------------------------------
def test_order_invalid_subject_type_returns_invalid_request(api):
    """PRD §2.10: "then request well-formedness — required fields present, enum members valid,
    schedule window valid, and a permit's `cemetery_id` equal to its order's `cemetery_id` —
    surfacing `ERR_INVALID_REQUEST` or `ERR_INVALID_SCHEDULE_WINDOW`".

    Design: Corner/entities/order_invalid_subject_type_enum_returns_invalid_request
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"], subject_type="ROBOT")
    resp = api.create_order(payload, th.make_customer_headers(cust["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: errors / order_create_unknown_customer_returns_not_found
# ---------------------------------------------------------------------------
def test_order_create_unknown_customer_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/order_create_unknown_customer_returns_not_found
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    payload = th.create_order_payload(th.NON_EXISTENT_UUID, cem["id"])
    resp = api.create_order(payload, th.make_customer_headers(th.NON_EXISTENT_UUID))
    th.validate_error(resp, th.ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: errors / order_create_unknown_cemetery_returns_not_found
# ---------------------------------------------------------------------------
def test_order_create_unknown_cemetery_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/order_create_unknown_cemetery_returns_not_found
    """
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], th.NON_EXISTENT_UUID)
    resp = api.create_order(payload, th.make_customer_headers(cust["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_CEMETERY_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: errors / submit_unknown_proof_returns_not_found
# ---------------------------------------------------------------------------
def test_submit_unknown_proof_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/submit_unknown_proof_returns_not_found
    """
    resp = api.submit_design_proof(th.NON_EXISTENT_UUID, th.TEST_USERS["designer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PROOF_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_orders_pagination_by_customer
# ---------------------------------------------------------------------------
def test_list_orders_pagination_by_customer(api):
    """PRD §2.3: "The `limit` parameter bounds the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100." PRD §2.3: "Every list response carries `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_orders_pagination_by_customer
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    th.make_order(cust, cem)
    th.make_order(cust, cem, height_cm=62, width_cm=42, base_width_cm=52,
                  estimated_line_char_counts=[18, 18])
    data, meta = th.validate_paginated(
        api.list_orders(th.TEST_USERS["admin_headers"], params={"customer_id": cust["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data
