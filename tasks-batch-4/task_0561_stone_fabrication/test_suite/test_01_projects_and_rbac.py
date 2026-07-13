"""Project intake defaults, validation of the create payload, and role-based access control."""
import pytest

from test_helpers import (
    validate_success, validate_error, build_user_headers, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_project_payload, create_fabrication_order_payload,
    setup_priced_project,
)


def test_project_create_defaults_and_system_fields(api, salesrep_headers):
    """PRD §3.1: "A new project lands in `INTAKE` posture with `payment_status` of `UNPAID`."
    PRD §3.1: "Its financial fields — `quoted_total_cents`, `final_invoice_cents`,
    `amount_paid_cents`, and `balance_due_cents` — are all derived; `amount_paid_cents`
    starts at 0 and `final_invoice_cents` remains null until an approved template is priced."
    PRD §2.4: "an integer `version` that begins at 1 and increments by one on each mutation."

    Design: Corner/entities/project_create_defaults_and_system_fields
    """
    resp = api.create_project(
        create_project_payload(customer_name="Ann", address="1 A St", material_grade="STANDARD"),
        salesrep_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "INTAKE"
    assert data["payment_status"] == "UNPAID"
    assert data["amount_paid_cents"] == 0
    assert data["version"] == 1
    assert data["id"]
    assert resp.json()["response_type"] == "object"
    assert resp.json()["meta"]["api_request_id"]


def test_project_create_missing_required_field_returns_validation(api, salesrep_headers):
    """PRD §2.9: "A missing required field, a value of the wrong type, or an invalid enum
    value is reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/project_create_missing_required_field_returns_validation
    """
    resp = api.create_project({"customer_name": "Bo", "address": "2 B St"}, salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_project_create_invalid_enum_returns_validation(api, salesrep_headers):
    """PRD §2.9: "A missing required field, a value of the wrong type, or an invalid enum
    value is reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/project_create_invalid_enum_returns_validation
    """
    resp = api.create_project(
        create_project_payload(customer_name="Cy", address="3 C St", material_grade="MARBLE"),
        salesrep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_project_not_found_returns_404(api, salesrep_headers):
    """PRD §2.9: "Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then
    authorization (`ERR_UNAUTHORIZED`, 403), then the existence of every resource referenced
    by the path or body." — a missing project id resolves to `ERR_PROJECT_NOT_FOUND`.

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project(NON_EXISTENT_UUID, salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)


def test_installer_cannot_create_project_returns_unauthorized(api, installer_headers):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`SalesRep` owns projects, quotes, payments and refunds, and change-order creation."

    Design: Corner/rbac/installer_cannot_create_project_returns_unauthorized
    """
    resp = api.create_project(
        create_project_payload(customer_name="Ty", address="20 T St", material_grade="PREMIUM"),
        installer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_salesrep_cannot_create_fab_order_returns_unauthorized(api, salesrep_headers):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`Fabricator` owns slab intake, templates, cutouts, template approval, and the
    full fabrication-order lifecycle."

    Design: Corner/rbac/salesrep_cannot_create_fab_order_returns_unauthorized
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    from test_helpers import new_slab, new_bay
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"],
        pieces=[{"label": "A", "sqft": 25}],
    )
    resp = api.create_fabrication_order(payload, salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_fabricator_cannot_approve_change_order_returns_unauthorized(api, fabricator_headers):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`ShopManager` owns configuration (bays, crews, and slab intake) and
    change-order approval, and additionally acts as a hierarchical override."

    Design: Corner/rbac/fabricator_cannot_approve_change_order_returns_unauthorized
    """
    from test_helpers import setup_project_with_quote, add_change_order
    ctx = setup_project_with_quote()
    co = add_change_order(ctx["p_id"], delta_cents=1000, reopens_template=False)
    resp = api.approve_change_order(co["id"], fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or names a role outside this set, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    anon_headers = build_user_headers("test-anon-1", "Anonymous")
    resp = api.create_project(
        create_project_payload(customer_name="Wu", address="23 W St", material_grade="PREMIUM"),
        anon_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
