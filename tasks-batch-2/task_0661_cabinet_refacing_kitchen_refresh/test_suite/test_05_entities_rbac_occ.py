"""Entity CRUD basics, RBAC enforcement, and optimistic-concurrency on quotes.

Queue B: entities, rbac, and cross_cutting_complexity_layers (OCC) corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    is_valid_uuid,
    TEST_USERS,
    make_customer_headers,
    build_user_headers,
    fixtures as fx,
)

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]


# ===========================================================================
# Queue B — entities corner instances
# ===========================================================================

def test_create_project_returns_lead_with_version_one(api):
    """PRD §3.1: "a freshly created project begins life in the `LEAD` state."
    PRD §2.4: "an integer `version` that begins at the resource's creation value and
    increments by one on every modification."

    Design: Corner/entities/create_project_returns_201_with_lead_status
    """
    cust = fx.create_customer()
    # api.create_project(payload, headers): the body carries customer_id +
    # address_line, and a SalesRep registers the project (PRD §3.1).
    resp = api.create_project({"customer_id": cust["id"], "address_line": "E1 Way"}, _SALES)
    # validate_success defaults to 200; creation returns 201.
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "LEAD", f"expected LEAD, got {data['status']}"
    assert data["version"] == 1, f"expected version 1 at creation, got {data['version']}"


def test_get_unknown_project_returns_not_found(api):
    """PRD §2.6: "the server validates them from left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve to an existing entity."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project("11111111-1111-4111-8111-111111111111", _SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_customer_missing_email_rejected(api):
    """PRD §3.1: "A `SalesRep` (or a `PlatformAdmin`) registers a homeowner by
    supplying their `email`, `full_name`, two-letter `state_code`, and self-reported
    `annual_income_cents`. The `email` must be non-empty and unique across all
    customers".
    PRD §3.13: "General body-shape validation — required fields present, enum values
    in range, and numeric constraints ... is reported as `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_customer_missing_required_field_returns_422
    """
    resp = api.create_customer(
        {"full_name": "No Email", "state_code": "CA", "annual_income_cents": 9_000_000}, _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_addon_invalid_kind_rejected(api):
    """PRD §3.6: "A `SalesRep` proposes an add-on against a quote by supplying its
    `kind` — either `HARDWARE` or `COUNTERTOP`".
    PRD §3.13: "General body-shape validation — required fields present, enum values
    in range ... is reported as `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_addon_invalid_enum_kind_returns_422
    """
    cust, proj, meas, quote = fx.setup_draft_quote()
    resp = api.create_addon(
        quote["id"], {"kind": "PLUMBING", "unit_price_cents": 100, "quantity": 2}, _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_measure_complete_copies_dimensions_to_project(api):
    """PRD §3.2: "the measured `linear_feet` and `door_count` are copied onto the
    parent project's `linear_feet` and `door_count`. If the project was in `LEAD`,
    completing the measure bubbles it up `LEAD → MEASURED`".

    Design: Corner/entities/project_computed_dimensions_set_on_measure_complete
    """
    cust, proj = fx.create_customer_and_project()
    meas = fx.schedule_measure(proj["id"])
    fx.complete_measure(proj["id"], meas["id"], linear_feet=25, door_count=18,
                        finish_code="WOOD_VENEER")
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    assert proj_read["linear_feet"] == 25, f"expected linear_feet 25, got {proj_read['linear_feet']}"
    assert proj_read["door_count"] == 18, f"expected door_count 18, got {proj_read['door_count']}"
    assert proj_read["status"] == "MEASURED", \
        f"expected project MEASURED after complete, got {proj_read['status']}"


def test_list_projects_paginated_envelope(api):
    """PRD §2.3: "List responses report their pagination state in the `meta` object
    using the fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    cust = fx.create_customer()
    fx.create_project(cust["id"], address_line="E6 Way")
    data, meta = validate_paginated(api.list_projects(_SALES, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1, f"expected at least 1 project, got {meta['total_count']}"
    assert "has_more" in meta, "meta must carry has_more"


def test_customer_id_is_uuid_with_version_one(api):
    """PRD §2.4: "carries a system-managed `id` formatted as a UUID with no type
    prefix ... The `id` is minted by the server; clients never supply it."
    PRD §2.4: "an integer `version` that begins at the resource's creation value
    and increments by one on every modification."

    Design: Corner/entities/customer_id_is_system_minted_uuid
    """
    cust = validate_success(api.create_customer(
        {"email": fx.f.unique_email(), "full_name": "C E7", "state_code": "CA",
         "annual_income_cents": 9_000_000}, _SALES), expected_status=201)
    assert cust["version"] == 1, f"expected version 1, got {cust['version']}"
    assert is_valid_uuid(cust["id"]), f"id must be a UUID without prefix, got {cust['id']!r}"


# ===========================================================================
# Queue B — rbac corner instances
# ===========================================================================

def test_scheduler_cannot_approve_quote(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the `POST /quotes/{id}/approve` endpoint is authorized for `Customer`.

    Design: Corner/rbac/scheduler_cannot_approve_quote_forbidden
    """
    cust, proj, meas, quote = fx.setup_quoted_quote()
    resp = api.approve_quote(quote["id"], {"expected_quote_version": quote["version"]}, _SCHED)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_not_owner_cannot_approve_quote(api):
    """PRD §2.1: "A customer who attempts a customer-scoped action against a project
    they do not own is rejected with `ERR_NOT_PROJECT_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_not_owner_cannot_approve_quote
    """
    cust_owner, proj, meas, quote = fx.setup_quoted_quote()
    other = fx.create_customer()
    resp = api.approve_quote(
        quote["id"], {"expected_quote_version": quote["version"]},
        make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    stranger_headers = build_user_headers("nobody-1", "Stranger")
    resp = api.get_project("22222222-2222-4222-8222-222222222222", stranger_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (OCC) corner instances
# ===========================================================================

def test_approve_with_stale_version_after_reopen_cycle_rejected(api):
    """PRD §2.9: "A quote that has been reopened and re-issued advances its
    `version` on each step and thereby changes its firm price; if the supplied
    `expected_quote_version` does not match the quote's current `version`, the
    approval is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412), so the customer
    never approves a price they did not see."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_quote_version_after_reopen_cycle
    """
    cust, proj, meas, quote = fx.setup_quoted_quote()
    stale_version = quote["version"]
    validate_success(api.reopen_quote(quote["id"], _SALES))
    validate_success(api.issue_quote(quote["id"], _SALES))  # version now advanced.
    resp = api.approve_quote(quote["id"], {"expected_quote_version": stale_version},
                             make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_QUOTE_VERSION.value)


def test_approve_with_current_version_succeeds(api):
    """PRD §2.9: "When a customer approves a quote, the request must carry
    `expected_quote_version` equal to the quote's current `version`."
    PRD §3.5: "On a successful approval the project bubbles up `QUOTED → SOLD` ...
    and the quote's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_approve_succeeds
    """
    cust, proj, meas, quote = fx.setup_quoted_quote()
    approved = validate_success(api.approve_quote(
        quote["id"], {"expected_quote_version": quote["version"]},
        make_customer_headers(cust["id"])))
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    assert proj_read["status"] == "SOLD", f"expected project SOLD, got {proj_read['status']}"
