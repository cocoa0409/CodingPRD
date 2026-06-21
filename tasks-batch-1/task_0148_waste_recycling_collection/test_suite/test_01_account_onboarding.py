"""Account onboarding, provisioning, activation, and the account-close cascade.

Covers difficulty rules transitive_cascade (account close) and cross_entity_state_dependency
(plan activation needs a matching cart), plus the entities/state_machines/validations corner
instances that govern account, cart, and plan creation and lifecycle.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_account_payload,
    create_cart_payload,
    create_service_plan_payload,
    assert_account,
    setup_active_account,
    create_account,
    create_active_cart,
    create_cart as fx_create_cart,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Corner / entities — account creation, defaults, retrieval, system fields
# ═══════════════════════════════════════════════════════════════════════════

def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered account begins in `PENDING_SETUP`."
    PRD §2.4: "The `version` field is an integer that starts at 1 when the resource
    is created and increments by exactly one on every mutation".
    PRD §3.7: "Every account exposes a derived `account_balance_cents`, defined as the
    sum of `balance_cents` over the account's invoices in `ISSUED` or `DISPUTED` status,
    minus the sum of `amount_cents` over the account's credits in `APPLIED` status."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    resp = api.create_account(
        create_account_payload(service_address="100 Main St", rate_class="RESIDENTIAL"),
        DISPATCHER,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_SETUP", f"expected PENDING_SETUP, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["account_balance_cents"] == 0, f"expected balance 0, got {data['account_balance_cents']}"
    assert_account(data)


def test_get_account_returns_stored_entity(api):
    """PRD §2.2: "The `data` field contains the resource object". The account's
    `rate_class` "is fixed at registration as the input to every downstream weight charge."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    created = validate_success(
        api.create_account(
            create_account_payload(service_address="101 Main St", rate_class="COMMERCIAL_SMALL"),
            DISPATCHER,
        ),
        201,
    )
    fetched = validate_success(api.get_account(created["id"], DISPATCHER), 200)
    assert fetched["id"] == created["id"]
    assert fetched["rate_class"] == "COMMERCIAL_SMALL", (
        f"expected COMMERCIAL_SMALL, got {fetched['rate_class']}"
    )


def test_get_account_not_found(api):
    """PRD §2.5: "the system validates the existence of each identifier from left to
    right and rejects the request with `ERR_NOT_FOUND` at the *first* path identifier
    that does not resolve to an existing resource."

    Design: Corner/entities/get_account_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_account_system_fields_ignored_on_input(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix; it is identity
    only and is never accepted as a business-decision input."
    PRD §3.1: "A freshly registered account begins in `PENDING_SETUP`."

    Design: Corner/entities/account_system_fields_ignored_on_input
    """
    data = validate_success(
        api.create_account(
            create_account_payload(service_address="106 Main St", rate_class="RESIDENTIAL"),
            DISPATCHER,
        ),
        201,
    )
    assert data["status"] == "PENDING_SETUP"
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert "_" not in data["id"], "id must have no type prefix"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / entities — cart creation, validation, defaults, FK reference
# ═══════════════════════════════════════════════════════════════════════════

def test_create_cart_missing_required_field(api):
    """PRD §2.5: "Beyond existence, every create and update endpoint requires its
    mandatory body fields to be present and requires every enum-typed field to carry a
    value within its declared domain; a request with a missing required field, or with
    an enum value outside its allowed set, is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_cart_missing_required_field
    """
    account = create_account(address="103 Main St")
    resp = api.create_cart({"account_id": account["id"], "size_gallons": 65}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_create_cart_invalid_enum_stream(api):
    """PRD §2.5: "Beyond existence, every create and update endpoint requires its
    mandatory body fields to be present and requires every enum-typed field to carry a
    value within its declared domain; a request with a missing required field, or with
    an enum value outside its allowed set, is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_cart_invalid_enum_stream
    """
    account = create_account(address="107 Main St")
    resp = api.create_cart(
        {"account_id": account["id"], "stream": "GLASS", "size_gallons": 65}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_create_cart_invalid_size_gallons(api):
    """PRD §3.1: "its `size_gallons`, which must be one of 35, 65, or 96; an
    out-of-domain size is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_cart_invalid_size_gallons
    """
    account = create_account(address="108 Main St")
    resp = api.create_cart(
        {"account_id": account["id"], "stream": "TRASH", "size_gallons": 50}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 422)


def test_cart_default_tare_zero_and_status_assigned(api):
    """PRD §3.1: "The cart's `tare_weight_lbs` — the empty weight subtracted from every
    gross scale reading — may be supplied and defaults to 0. A cart is born `ASSIGNED`."

    Design: Corner/entities/cart_default_tare_zero_and_status_assigned
    """
    account = create_account(address="104 Main St")
    data = validate_success(
        api.create_cart(create_cart_payload(account["id"], stream="TRASH", size_gallons=65),
                        DISPATCHER),
        201,
    )
    assert data["tare_weight_lbs"] == 0, f"expected tare 0, got {data['tare_weight_lbs']}"
    assert data["status"] == "ASSIGNED", f"expected ASSIGNED, got {data['status']}"


def test_create_cart_reference_not_found_account(api):
    """PRD §2.5: "On any create endpoint that accepts a foreign-key identifier in its
    payload, every such referenced resource must exist; a body that names a non-existent
    resource is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_cart_reference_not_found_account
    """
    resp = api.create_cart(
        {"account_id": NON_EXISTENT_UUID, "stream": "TRASH", "size_gallons": 65}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, 404)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / state_machines — account & cart lifecycle
# ═══════════════════════════════════════════════════════════════════════════

def test_account_initial_state_pending_setup(api):
    """PRD §3.1: "A freshly registered account begins in `PENDING_SETUP`."

    Design: Corner/state_machines/account_initial_state_pending_setup
    """
    data = validate_success(
        api.create_account(
            create_account_payload(service_address="110 Main St", rate_class="RESIDENTIAL"),
            DISPATCHER,
        ),
        201,
    )
    assert data["status"] == "PENDING_SETUP"


def test_activate_account_without_cart_or_plan_invalid_state(api):
    """PRD §3.1: "A `Dispatcher` activates a `PENDING_SETUP` account, transitioning it
    to `ACTIVE`, only once the account has at least one `Cart` in `ASSIGNED` or `ACTIVE`
    status and at least one `ServicePlan` in `ACTIVE` status."

    Design: Corner/state_machines/activate_account_without_cart_or_plan_invalid_state
    """
    account = create_account(address="111 Main St")
    resp = api.activate_account(account["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_cart_activate_from_retired_invalid_transition(api):
    """PRD §3.1: "retire a cart from any of `ASSIGNED`, `ACTIVE`, or `ON_HOLD` to the
    terminal `RETIRED` state."
    PRD §3.7 (general lockdown precedent) — a transition not defined from the current
    state is rejected; PRD §3.1 lists `activate` only from ASSIGNED or ON_HOLD, never
    from the terminal RETIRED state.

    Design: Corner/state_machines/cart_activate_from_retired_invalid_transition
    """
    account = create_account(address="112 Main St")
    cart = fx_create_cart(account["id"], stream="TRASH", size_gallons=65)
    validate_success(api.retire_cart(cart["id"], DISPATCHER), 200)
    resp = api.activate_cart(cart["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / cross_entity_state_dependency — plan activation needs a cart
# ═══════════════════════════════════════════════════════════════════════════

def test_plan_activate_without_matching_cart_rejected(api):
    """PRD §3.1: "Activating a plan — moving it from `DRAFT` to `ACTIVE`, or reviving a
    `PAUSED` plan back to `ACTIVE` — is permitted only when the plan's account owns a
    `Cart` whose `stream` equals the plan's `stream` and whose status is either
    `ASSIGNED` or `ACTIVE`; if no such cart exists the activation is rejected with
    `ERR_NO_MATCHING_CART`."

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_matching_cart_plan_to_cart
    """
    account = create_account(address="25 Beech St")
    # Only a TRASH cart exists; the plan is RECYCLE -> no matching cart.
    create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    plan = validate_success(
        api.create_service_plan(
            create_service_plan_payload(account["id"], stream="RECYCLE", frequency="BIWEEKLY",
                                        base_monthly_fee_cents=800),
            DISPATCHER,
        ),
        201,
    )
    resp = api.activate_service_plan(plan["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NO_MATCHING_CART, 409)
    after = validate_success(api.get_service_plan(plan["id"], DISPATCHER), 200)
    assert after["status"] == "DRAFT", f"plan must stay DRAFT, got {after['status']}"


def test_plan_activate_with_matching_stream_cart_succeeds(api):
    """PRD §3.1: "Activating a plan — moving it from `DRAFT` to `ACTIVE`, or reviving a
    `PAUSED` plan back to `ACTIVE` — is permitted only when the plan's account owns a
    `Cart` whose `stream` equals the plan's `stream` and whose status is either
    `ASSIGNED` or `ACTIVE`; if no such cart exists the activation is rejected with
    `ERR_NO_MATCHING_CART`."

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_matching_cart_plan_to_cart
    """
    account = create_account(address="25b Beech St")
    create_active_cart(account["id"], stream="RECYCLE", size_gallons=96)
    plan = validate_success(
        api.create_service_plan(
            create_service_plan_payload(account["id"], stream="RECYCLE", frequency="BIWEEKLY",
                                        base_monthly_fee_cents=800),
            DISPATCHER,
        ),
        201,
    )
    activated = validate_success(api.activate_service_plan(plan["id"], DISPATCHER), 200)
    assert activated["status"] == "ACTIVE", f"expected ACTIVE, got {activated['status']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / transitive_cascade — account close cascades carts + plans
# ═══════════════════════════════════════════════════════════════════════════

def test_account_close_cascades_carts_retired(api):
    """PRD §3.1: "On close, the account moves to the terminal `CLOSED` state, and the
    system cascades through the account's dependents: every `Cart` for the account in
    `ASSIGNED`, `ACTIVE`, or `ON_HOLD` is driven to `RETIRED`, and every `ServicePlan`
    for the account in `DRAFT`, `ACTIVE`, or `PAUSED` is driven to `TERMINATED`."

    Design: Difficulty/transitive_cascade/account_close_cascades_carts_and_plans_depth3
    """
    account, cart, plan = setup_active_account(address="15 Ash St", stream="TRASH")
    closed = validate_success(api.close_account(account["id"], BILLING), 200)
    assert closed["status"] == "CLOSED", f"expected CLOSED, got {closed['status']}"
    cart_after = validate_success(api.get_cart(cart["id"], DISPATCHER), 200)
    assert cart_after["status"] == "RETIRED", f"cart must be RETIRED, got {cart_after['status']}"


def test_account_close_cascades_plans_terminated(api):
    """PRD §3.1: "On close, the account moves to the terminal `CLOSED` state, and the
    system cascades through the account's dependents: every `Cart` for the account in
    `ASSIGNED`, `ACTIVE`, or `ON_HOLD` is driven to `RETIRED`, and every `ServicePlan`
    for the account in `DRAFT`, `ACTIVE`, or `PAUSED` is driven to `TERMINATED`."

    Design: Difficulty/transitive_cascade/account_close_cascades_carts_and_plans_depth3
    """
    account, cart, plan = setup_active_account(address="15b Ash St", stream="TRASH")
    closed = validate_success(api.close_account(account["id"], BILLING), 200)
    assert closed["status"] == "CLOSED"
    plan_after = validate_success(api.get_service_plan(plan["id"], DISPATCHER), 200)
    assert plan_after["status"] == "TERMINATED", (
        f"plan must be TERMINATED, got {plan_after['status']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Corner / validations — close blocked by open balance
# ═══════════════════════════════════════════════════════════════════════════

def test_close_account_with_open_balance_rejected(api):
    """PRD §3.1: "An account may be closed from either `ACTIVE` or `SUSPENDED`, but only
    when it has no `Invoice` in `ISSUED` or `DISPUTED` status — an open balance blocks
    closure with `ERR_OPEN_BALANCE`."

    Design: Corner/validations/close_account_with_open_balance_rejected
    """
    account, cart, plan = setup_active_account(address="125 Main St", stream="TRASH",
                                               base_monthly_fee_cents=1000)
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    invoice = validate_success(
        api.create_invoice(
            account["id"],
            {"period_start": "2026-05-01T00:00:00Z", "period_end": "2026-06-01T00:00:00Z",
             "expected_account_version": acct["version"]},
            BILLING,
        ),
        201,
    )
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    resp = api.close_account(account["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_OPEN_BALANCE, 409)
