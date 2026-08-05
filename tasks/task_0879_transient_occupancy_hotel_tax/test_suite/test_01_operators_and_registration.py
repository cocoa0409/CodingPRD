"""Operator registration & lifecycle, jurisdiction config, auth, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_operator, assert_jurisdiction,
    TEST_USERS, anonymous_headers, make_operator_headers,
    create_jurisdiction_payload, create_operator_payload,
    create_jurisdiction, create_active_operator, open_audit, get_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ---- Corner: entities/operator_create_returns_pending_no_certificate ----
def test_operator_created_pending_no_certificate_zero_balance(api):
    """PRD 3.2: "A freshly registered operator starts in `PENDING` status with an
    `account_balance_cents` of zero and no `certificate_number` (the field is null
    until activation)."

    Design: Corner/entities/operator_create_returns_pending_no_certificate
    """
    jur = create_jurisdiction(api)
    payload = create_operator_payload(jur["id"], legal_name="New Op", filing_frequency="QUARTERLY")
    data = validate_success(api.create_operator(payload, ADMIN), 201)
    assert_operator(data)
    assert data["status"] == "PENDING"
    assert data["certificate_number"] is None
    assert data["account_balance_cents"] == 0


# ---- Corner: entities/jurisdiction_defaults_applied ----
def test_jurisdiction_optional_fields_default(api):
    """PRD 3.1: "`interest_rate_monthly_bps`, the monthly delinquency interest rate,
    defaults to 100 (that is, 1% per month); `refund_interest_monthly_bps`, the
    monthly interest paid on overpayments being refunded, defaults to 50 (0.5% per
    month); `lien_threshold_cents`, the delinquent-balance ceiling a lien requires
    the balance to strictly exceed, defaults to 500000 (five thousand dollars); and
    `exemption_min_stay_nights`, the minimum consecutive nights that qualify a stay
    as a long-term exemption, defaults to 30."

    Design: Corner/entities/jurisdiction_defaults_applied
    """
    payload = create_jurisdiction_payload(name="JDef", tax_rate_bps=1000)
    data = validate_success(api.create_jurisdiction(payload, ADMIN), 201)
    assert_jurisdiction(data)
    assert data["interest_rate_monthly_bps"] == 100
    assert data["refund_interest_monthly_bps"] == 50
    assert data["lien_threshold_cents"] == 500000
    assert data["exemption_min_stay_nights"] == 30


# ---- Corner: entities/operator_not_found_returns_404 ----
def test_get_unknown_operator_not_found(api):
    """PRD 2.9: "the server validates identifiers left-to-right along the path and
    rejects the first one that does not resolve with `ERR_NOT_FOUND` before
    considering anything further to the right or any request body."

    Design: Corner/entities/operator_not_found_returns_404
    """
    resp = api.get_operator("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---- Corner: entities/operator_create_missing_required_filing_frequency ----
def test_operator_missing_filing_frequency_rejected(api):
    """PRD 2.9: "(13) general well-formedness of the body — required fields present,
    amounts non-negative, enums valid (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/operator_create_missing_required_filing_frequency
    """
    jur = create_jurisdiction(api)
    resp = api.create_operator({"jurisdiction_id": jur["id"], "legal_name": "NoFreq"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---- Corner: state_machines/operator_activate_twice_returns_invalid_state ----
def test_activate_already_active_operator_rejected(api):
    """PRD 3.2: "Activation is a `TaxAdmin` action that moves the operator from
    `PENDING` to `ACTIVE`; it is permitted only while the operator is in `PENDING`,
    and any other starting state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/operator_activate_twice_returns_invalid_state
    """
    op = create_active_operator(api)
    resp = api.activate_operator(op["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- Corner: validations/close_operator_with_open_audit_rejected ----
def test_close_operator_with_open_audit_rejected(api):
    """PRD 3.2: "there must be no audit still in progress — that is, no audit in
    `OPENED`, `FIELDWORK`, `PROPOSED`, or `RESPONSE` status — otherwise it is
    rejected with `ERR_AUDIT_IN_PROGRESS`."

    Design: Corner/validations/close_operator_with_open_audit_rejected
    """
    op = create_active_operator(api)
    open_audit(api, op["id"])
    resp = api.close_operator(op["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUDIT_IN_PROGRESS.value)
    assert get_operator(api, op["id"])["status"] == "ACTIVE"


# ---- Corner: rbac/unauthenticated_missing_headers_rejected ----
def test_missing_role_header_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or carrying an unrecognized role,
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_missing_headers_rejected
    """
    resp = api.create_jurisdiction(create_jurisdiction_payload(name="J13"), anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---- Corner: rbac/operator_role_forbidden_on_register_operator ----
def test_operator_role_cannot_register_operator(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/operator_role_forbidden_on_register_operator
    """
    op = create_active_operator(api)
    resp = api.create_operator(
        create_operator_payload(op["jurisdiction_id"], legal_name="Sneaky"),
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---- Corner: endpoints/list_operators_pagination ----
def test_list_operators_pagination_meta(api):
    """PRD 2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_operators_pagination
    """
    jur = create_jurisdiction(api)
    api.create_operator(create_operator_payload(jur["id"], legal_name="Op A"), ADMIN)
    api.create_operator(create_operator_payload(jur["id"], legal_name="Op B"), ADMIN)
    resp = api.list_operators(ADMIN, params={"jurisdiction_id": jur["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
