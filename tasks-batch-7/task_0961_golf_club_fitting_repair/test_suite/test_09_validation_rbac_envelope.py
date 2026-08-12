"""Cross-cutting guards: validation ordering, ownership, RBAC, envelope
shape, the startup clock, and per-transition state errors."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client, NON_EXISTENT_UUID, TEST_USERS,
    set_clock, create_customer, create_specialist, create_technician,
    create_manager, create_instructor, create_bay, book_session,
    create_component_trio, create_component_item, create_draft_spec,
    quote_spec, setup_quoted_spec, get_spec, create_repair_ticket,
    create_lesson_package, customer_headers, staff_headers,
    create_customer_payload, create_component_item_payload,
    make_customer_headers, build_user_headers,
)

ADMIN = TEST_USERS["shop_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: validation-priority pairs and cross-entity state dependency
# ---------------------------------------------------------------------------

def _setup_draft_spec_zero_credit():
    """Customer with no credit; DRAFT spec (never quoted)."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Jan Juniper")
    specialist = create_specialist()
    bay = create_bay()
    session = book_session(customer, bay, specialist)
    items = create_component_trio()
    spec = create_draft_spec(customer, session, items, specialist, labor_cents=15_000)
    return {"customer": customer, "specialist": specialist, "spec": spec}


def test_approve_draft_spec_reports_state_error_not_credit_error(api):
    """PRD §2.10: "Seventh, the per-transition state guards, each carrying its
    own domain error." and "Tenth, fiscal rules before any parts are
    committed — customer standing, credit sufficiency, lesson-credit
    availability, deposit-before-work, payment sequencing, and paid-in-full
    before pickup." PRD §3.4: "Approving a spec that is not in `QUOTED` is
    rejected with `ERR_SPEC_NOT_QUOTED`".

    Design: Difficulty/priority_pair_validation_conflict/approve_draft_spec_state_error_beats_credit_error
    """
    ctx = _setup_draft_spec_zero_credit()
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "CREDIT"},
        customer_headers(ctx["customer"]),
    )
    # The customer has zero credit, so both rules are violated; the state
    # guard (earlier in the fixed order) must surface.
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_QUOTED)


def test_approve_draft_spec_leaves_no_order(api):
    """PRD §3.4: "Approving a spec that is not in `QUOTED` is rejected with
    `ERR_SPEC_NOT_QUOTED`" and "Component orders are never created directly.
    Each one is born as a side effect of a customer approving a build spec"
    (§3.3).

    Design: Difficulty/priority_pair_validation_conflict/approve_draft_spec_state_error_beats_credit_error
    """
    ctx = _setup_draft_spec_zero_credit()
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "CREDIT"},
        customer_headers(ctx["customer"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_QUOTED)

    spec = get_spec(ctx["spec"]["id"], staff_headers(ctx["specialist"]))
    assert spec["status"] == "DRAFT", (
        f"failed approval must leave the spec DRAFT, got {spec['status']}"
    )
    manager = create_manager()
    orders = get_success_data(
        api_client.list_component_orders(staff_headers(manager),
                                         params={"build_spec_id": ctx["spec"]["id"]})
    )
    assert orders == [], f"no component order may exist for a rejected approve, got {orders}"


def _setup_quoted_spec_then_suspend():
    ctx = setup_quoted_spec(complete_session=False, labor_cents=15_000)
    manager = create_manager()
    get_success_data(
        api_client.set_customer_status(ctx["customer"]["id"],
                                       {"target_status": "SUSPENDED"},
                                       staff_headers(manager))
    )
    return ctx


def test_suspended_customer_cannot_approve_spec(api):
    """PRD §3.4: "approving while `SUSPENDED` is rejected with
    `ERR_CUSTOMER_SUSPENDED`." PRD §3.1: "suspension does not delete history,
    but it blocks the customer's spend and booking actions elsewhere in the
    system with `ERR_CUSTOMER_SUSPENDED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/suspended_customer_cannot_approve_spec
    """
    ctx = _setup_quoted_spec_then_suspend()
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "EXTERNAL"},
        customer_headers(ctx["customer"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)


def test_suspended_customer_approval_leaves_spec_quoted(api):
    """PRD §3.4: "approving while `SUSPENDED` is rejected with
    `ERR_CUSTOMER_SUSPENDED`." and "Component orders are never created
    directly. Each one is born as a side effect of a customer approving a
    build spec" (§3.3).

    Design: Difficulty/cross_entity_state_dependency/suspended_customer_cannot_approve_spec
    """
    ctx = _setup_quoted_spec_then_suspend()
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "EXTERNAL"},
        customer_headers(ctx["customer"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

    spec = get_spec(ctx["spec"]["id"], staff_headers(ctx["specialist"]))
    assert spec["status"] == "QUOTED", (
        f"rejected approval must leave the spec QUOTED, got {spec['status']}"
    )
    manager = create_manager()
    orders = get_success_data(
        api_client.list_component_orders(staff_headers(manager),
                                         params={"build_spec_id": ctx["spec"]["id"]})
    )
    assert orders == [], f"no component order may be created, got {orders}"


# ---------------------------------------------------------------------------
# Corner: entity shape / defaults / not-found
# ---------------------------------------------------------------------------

def test_customer_create_missing_email_rejected(api):
    """PRD §3.1: "registers a customer with a `full_name` and an `email`".
    PRD §2.10: "Third, request body shape — required fields present, enum
    values valid, a session's `starts_at` strictly earlier than its `ends_at`,
    the warranty-subject exclusive-or respected, market comparables present
    when the offer basis requires them, a denial reason present when a claim
    is denied — all under `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/customer_create_missing_email_rejected
    """
    resp = api_client.create_customer({"full_name": "No Email"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_customer_create_computed_credit_input_ignored(api):
    """PRD §2.8: "A customer's `credit_balance_cents` is always exactly the
    sum of `amount_cents` over every ledger entry for that customer; the
    ledger is the only mechanism that ever mutates the balance".

    Design: Corner/entities/customer_create_computed_credit_input_ignored
    """
    payload = create_customer_payload(full_name="Uma Ulm")
    payload["credit_balance_cents"] = 9_999
    resp = api_client.create_customer(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["credit_balance_cents"] == 0, (
        f"a fresh customer has no ledger entries, so the balance must be 0 "
        f"regardless of client input, got {data['credit_balance_cents']}"
    )


def test_get_nonexistent_spec_returns_not_found(api):
    """PRD §2.4: "An unresolvable reference is rejected with the corresponding
    not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_BAY_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`,
    `ERR_SPEC_NOT_FOUND`, `ERR_COMPONENT_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_APPRAISAL_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    or `ERR_CLAIM_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/get_nonexistent_spec_returns_not_found
    """
    manager = create_manager()
    resp = api_client.get_build_spec(NON_EXISTENT_UUID, staff_headers(manager))
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: auth, roles, ownership
# ---------------------------------------------------------------------------

def test_request_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value
    for either, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_headers_unauthenticated
    """
    resp = api_client.list_component_items(headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_customer_role_cannot_create_component_item(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized
    list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST
    /golf-shop/component-items is authorized for "ShopManager, ShopAdmin".

    Design: Corner/validations/customer_role_cannot_create_component_item
    """
    customer = create_customer("Pat Plain")
    resp = api_client.create_component_item(
        create_component_item_payload("HEAD", unit_cost_cents=100,
                                      msrp_cents=200, initial_stock=1),
        customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_customer_cannot_approve_others_spec(api):
    """PRD §2.1: "ownership checks on any resource that references a
    `Customer` compare the resource's `customer_id` field to `X-User-ID`, and
    a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/customer_cannot_approve_others_spec
    """
    ctx = setup_quoted_spec(complete_session=False, labor_cents=15_000)
    other = create_customer("Bob B")
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "EXTERNAL"}, customer_headers(other),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    spec = get_spec(ctx["spec"]["id"], staff_headers(ctx["specialist"]))
    assert spec["status"] == "QUOTED"


def test_customer_cannot_pay_others_ticket(api):
    """PRD §2.1: "Ownership scoping for customers applies to every
    owner-scoped action in this document — approving builds and tickets,
    paying tickets, accepting or declining offers, appealing claims, reserving
    or purchasing listings, cancelling one's own sessions, specs, and tickets
    — and to customer self-reads of owned resources."

    Design: Corner/validations/customer_cannot_pay_others_ticket
    """
    set_clock("2026-05-10T09:00:00Z")
    owner = create_customer("Ann A")
    other = create_customer("Bob B")
    ticket = create_repair_ticket(owner, "REGRIP", False, club_description="7-iron")
    resp = api_client.pay_ticket(
        ticket["id"], {"kind": "DEPOSIT", "method": "EXTERNAL"},
        customer_headers(other),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    ticket = get_success_data(
        api_client.get_repair_ticket(ticket["id"], customer_headers(owner))
    )
    assert ticket["payment_status"] == "UNPAID"


# ---------------------------------------------------------------------------
# Corner: shape validations
# ---------------------------------------------------------------------------

def test_warranty_claim_xor_rejected(api):
    """PRD §3.7: "The owning customer files a claim with a `description` and
    exactly one subject: a `build_spec_id` or a `repair_ticket_id`, never both
    and never neither — violating that exclusive-or fails shape validation."
    PRD §2.10: body shape is checked third, before existence (fourth).

    Design: Corner/validations/warranty_claim_xor_rejected
    """
    payload = {
        "description": "both",
        "build_spec_id": NON_EXISTENT_UUID,
        "repair_ticket_id": "7b2d0c1a-3e5f-4b82-8d7c-23f8c7b1e2a3",
    }
    resp = api_client.create_warranty_claim(
        payload, make_customer_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2")
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_component_type_mismatch_rejected(api):
    """PRD §3.4: "Each component choice must actually be what its slot claims
    — the head a `HEAD`, the shaft a `SHAFT`, the grip a `GRIP` — or creation
    fails with `ERR_COMPONENT_TYPE_MISMATCH` (HTTP 400)."

    Design: Corner/validations/component_type_mismatch_rejected
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Sue Slough")
    specialist = create_specialist()
    bay = create_bay()
    session = book_session(customer, bay, specialist)
    grip = create_component_item("GRIP", 800, 1_500, 5)
    shaft = create_component_item("SHAFT", 12_000, 18_000, 5)
    payload = {
        "customer_id": customer["id"],
        "fitting_session_id": session["id"],
        "head_item_id": grip["id"],   # GRIP item in the head slot
        "shaft_item_id": shaft["id"],
        "grip_item_id": grip["id"],
        "length_inches": 45.5, "loft_deg": 10.5, "lie_deg": 58,
        "labor_cents": 15_000,
    }
    resp = api_client.create_build_spec(payload, staff_headers(specialist))
    validate_error(resp, ApiErrorId.ERR_COMPONENT_TYPE_MISMATCH)


# ---------------------------------------------------------------------------
# Corner: RBAC exclusivity
# ---------------------------------------------------------------------------

def test_technician_cannot_quote_spec(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized
    list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST
    /golf-shop/build-specs/{id}/quote is authorized for "FittingSpecialist".

    Design: Corner/rbac/technician_cannot_quote_spec
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Ken Kove")
    specialist = create_specialist()
    technician = create_technician()
    bay = create_bay()
    session = book_session(customer, bay, specialist)
    items = create_component_trio()
    spec = create_draft_spec(customer, session, items, specialist, labor_cents=15_000)
    resp = api_client.quote_build_spec(
        spec["id"], {"expected_build_spec_version": spec["version"]},
        staff_headers(technician),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    spec = get_spec(spec["id"], staff_headers(specialist))
    assert spec["status"] == "DRAFT"


def test_instructor_reads_but_cannot_create_package(api):
    """PRD §2.1: "An `Instructor` has read-only visibility into lesson
    packages and fitting sessions." and "A request whose role is not on the
    endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/instructor_cannot_create_package_forbidden
    """
    customer = create_customer("Lea Loom")
    instructor = create_instructor()
    package = create_lesson_package(customer, total_credits=4, price_cents=30_000)

    resp = api_client.get_lesson_package(package["id"], staff_headers(instructor))
    data = validate_success(resp)
    assert data["id"] == package["id"]

    resp = api_client.create_lesson_package(
        {"customer_id": customer["id"], "total_credits": 2,
         "price_cents": 15_000, "expires_at": "2027-01-01T00:00:00Z"},
        staff_headers(instructor),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Corner: envelope, startup clock, per-transition state guard
# ---------------------------------------------------------------------------

def test_envelope_shape_success_and_error(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format" with meta.api_request_id,
    meta.api_request_timestamp, response_type, and data; and "All error API
    responses (4xx status codes) follow this standard envelope format" with
    response_type "error" and data.error_id / data.message.

    Design: Corner/endpoints/envelope_shape_success_and_error
    """
    manager = create_manager()
    mh = staff_headers(manager)
    customer = create_customer("Env Elope")

    ok = api_client.get_customer(customer["id"], mh)
    body = ok.json()
    assert ok.status_code == 200
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["id"] == customer["id"]

    err = api_client.get_customer(NON_EXISTENT_UUID, mh)
    ebody = err.json()
    assert err.status_code == 404
    assert ebody["response_type"] == "error"
    assert ebody["data"]["error_id"] == "ERR_CUSTOMER_NOT_FOUND"
    assert isinstance(ebody["data"]["message"], str) and ebody["data"]["message"]


def test_clock_default_startup_time(api):
    """PRD §2.5: "At startup the clock reads exactly 2026-05-01T00:00:00Z, and
    it never falls back to wall-clock time; every `created_at`, `updated_at`,
    and business timestamp in the system is stamped from it."

    Design: Corner/complexity_layers/clock_default_startup_time
    """
    # The clock is never set in this test.
    data = validate_success(
        api_client.create_customer(create_customer_payload(full_name="Pia Pell"), ADMIN),
        expected_status=201,
    )
    assert data["created_at"].startswith("2026-05-01T00:00:00"), (
        f"created_at must be stamped from the startup clock 2026-05-01T00:00:00Z, "
        f"got {data['created_at']}"
    )


def test_mark_ready_before_build_rejected(api):
    """PRD §3.4: "a `RepairTechnician` marks an `IN_BUILD` spec ready —
    anything else earns `ERR_SPEC_NOT_IN_BUILD`".

    Design: Corner/state_machines/mark_ready_before_build_rejected
    """
    ctx = setup_quoted_spec(complete_session=False, labor_cents=15_000)
    resp = api_client.mark_ready_build_spec(
        ctx["spec"]["id"], staff_headers(ctx["technician"])
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_IN_BUILD)
    spec = get_spec(ctx["spec"]["id"], staff_headers(ctx["specialist"]))
    assert spec["status"] == "QUOTED"
