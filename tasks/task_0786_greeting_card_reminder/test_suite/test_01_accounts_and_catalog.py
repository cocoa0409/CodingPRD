"""Account provisioning, catalog basics, existence/validation errors, and listing.

Translates queue-B (corner) instances covering entity creation defaults,
required-field and not-found validation, the PRO credit grant, and the paginated
order-listing envelope.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_account_payload, create_order_payload,
    assert_account, ApiErrorId,
    TEST_USERS, holder, new_account, new_contact, new_card,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STUDIO = TEST_USERS["studio_operator_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_account_create_returns_defaults(api):
    """PRD §3.1: "A freshly created account is `ACTIVE` (accounts are otherwise
    `SUSPENDED`), begins with a `card_credit_balance` of zero, and takes
    `version` 1."

    Design: Corner/entities/account_create_returns_201_with_defaults
    """
    data = validate_success(api.create_account(create_account_payload(), ADMIN), 201)
    assert_account(data)
    assert data["status"] == "ACTIVE"
    assert data["card_credit_balance"] == 0, "new account starts at zero credits"
    assert data["version"] == 1, "new account takes version 1"


def test_pro_subscription_grants_balance_12(api):
    """PRD §3.1: "the `monthly_card_credits` granted each cycle (0 for `FREE`, 4
    for `PLUS`, 12 for `PRO`)".
    PRD §3.1: "Creating the subscription grants the tier's full monthly credits
    immediately".

    Design: Corner/entities/subscription_pro_grant_sets_balance_12
    """
    account = new_account()
    validate_success(api.create_subscription(account["id"], {"tier": "PRO"}, ADMIN), 201)
    refreshed = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert refreshed["card_credit_balance"] == 12, "PRO grants the full 12 monthly credits"


def test_order_create_defaults_font_style_script(api):
    """PRD §3.4: "a `font_style` of `SCRIPT` (the default), `PRINT`, or `CASUAL`".

    Design: Corner/entities/order_create_defaults_font_style_script
    """
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    payload = create_order_payload(account["id"], contact["id"], card["id"])
    data = validate_success(api.create_order(payload, holder(account["id"])), 201)
    assert data["font_style"] == "SCRIPT", "font_style defaults to SCRIPT when omitted"


def test_order_create_missing_card_id_returns_validation(api):
    """PRD §2.9: "A syntactically malformed body, a missing required field, or an
    invalid enum or type value is a bad request and yields `ERR_VALIDATION`."

    Design: Corner/entities/order_create_missing_card_id_returns_400
    """
    account = new_account()
    contact = new_contact(account["id"])
    payload = {
        "account_id": account["id"],
        "contact_id": contact["id"],
        "message_text": "hi",
        "scheduled_send_at": "2026-04-01T00:00:00Z",
    }  # card_id omitted
    validate_error(api.create_order(payload, holder(account["id"])), ApiErrorId.ERR_VALIDATION.value)


def test_order_create_unknown_contact_returns_not_found(api):
    """PRD §2.9: "every resource named by a path segment or a foreign-key body
    field must resolve, and path identifiers are validated left to right so that
    the first unresolved identifier in the path determines which not-found error
    is returned — `ERR_ACCOUNT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
    `ERR_CONTACT_NOT_FOUND`".

    Design: Corner/entities/order_create_unknown_contact_returns_404
    """
    account = new_account()
    card = new_card()
    payload = create_order_payload(account["id"], NON_EXISTENT, card["id"])
    validate_error(api.create_order(payload, holder(account["id"])), ApiErrorId.ERR_CONTACT_NOT_FOUND.value)


def test_order_get_nonexistent_returns_not_found(api):
    """PRD §2.9: "every resource named by a path segment or a foreign-key body
    field must resolve" — an order id that does not resolve returns
    `ERR_ORDER_NOT_FOUND`.

    Design: Corner/entities/order_get_nonexistent_returns_404
    """
    validate_error(api.get_order(NON_EXISTENT, ADMIN), ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_verify_nonexistent_contact_returns_not_found(api):
    """PRD §2.9: "every resource named by a path segment or a foreign-key body
    field must resolve" — verifying a contact that does not resolve returns
    `ERR_CONTACT_NOT_FOUND`.

    Design: Corner/errors/verify_nonexistent_contact_returns_404
    """
    validate_error(
        api.verify_address(NON_EXISTENT, {"result": "VERIFIED"}, STUDIO),
        ApiErrorId.ERR_CONTACT_NOT_FOUND.value,
    )


def test_orders_list_pagination_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned".

    Design: Corner/endpoints/orders_list_pagination_envelope
    """
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    ah = holder(account["id"])
    validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card["id"], message_text="a"), ah), 201)
    validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card["id"], message_text="b"), ah), 201)

    resp = api.list_orders(ah, params={"account_id": account["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, "limit=1 caps the page to one item"
    assert meta["total_count"] == 2, "two orders exist for this account"
    assert meta["has_more"] is True, "a second page remains"
