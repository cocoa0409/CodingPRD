"""Shop creation, listing, access control, and not-found surfaces (PRD §2, §3.1).

Covers default config on shop create, pagination envelope, the auth/role/not-found
structural surfaces, and the close-with-open-ticket guard.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_shop,
    create_shop_payload,
    setup_shop_with_active_barber,
    served_walkin_ticket,
    paid_walkin,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_create_shop_applies_defaults(api):
    """PRD §3.1: "A new shop is created `OPEN` with `version` 1 and its
    `gross_service_revenue_cents` and `gross_product_revenue_cents` ledgers at
    zero." "`no_show_strike_limit` (at least 1, default 3) ... `late_grace_minutes`
    (default 10) ... `punch_reward_threshold` (at least 1, default 10)".

    Design: Corner/entities/create_shop_returns_201_with_defaults_applied
    """
    res = api.create_shop(
        create_shop_payload(name="S", tax_rate_pct=5,
                            default_booth_rent_cents=4000, default_commission_pct=30),
        OWNER,
    )
    shop = validate_success(res, 201)
    assert_shop(shop)
    assert shop["status"] == "OPEN", shop
    assert shop["version"] == 1, shop
    assert shop["no_show_strike_limit"] == 3, shop
    assert shop["late_grace_minutes"] == 10, shop
    assert shop["punch_reward_threshold"] == 10, shop
    assert shop["gross_service_revenue_cents"] == 0, shop


def test_list_shops_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object so the client can page deterministically."

    Design: Corner/entities/list_shops_pagination_envelope
    """
    get_success_data(api.create_shop(create_shop_payload(name="S1"), OWNER))
    get_success_data(api.create_shop(create_shop_payload(name="S2"), OWNER))
    data, meta = validate_paginated(api.list_shops(OWNER))
    assert meta["total_count"] >= 2, meta
    assert isinstance(meta["has_more"], bool), meta


def test_missing_user_context_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID` ... and `X-User-Role` ... If either header is missing or
    malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/validations/missing_user_context_header_returns_401
    """
    res = api.list_shops({})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")


def test_shop_not_found(api):
    """PRD §2.8: "the server validates the path left to right and rejects on the
    first identifier that does not resolve, returning that identifier's specific
    not-found error — `ERR_SHOP_NOT_FOUND`".

    Design: Corner/validations/shop_not_found_returns_404
    """
    res = api.get_shop(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_SHOP_NOT_FOUND")


def test_receptionist_cannot_create_shop(api):
    """PRD §2.1: "When a request carries a syntactically valid user context but the
    role is not permitted to perform the requested operation ... the request is
    rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/receptionist_cannot_create_shop_returns_forbidden
    """
    res = api.create_shop(create_shop_payload(name="S"), RECEPTION)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_close_shop_with_open_ticket_rejected(api):
    """PRD §3.1: "The owner may close an `OPEN` shop, transitioning `OPEN →
    CLOSED`, but only when there is no `Appointment` in `CHECKED_IN` and no
    `Ticket` in `OPEN` anywhere in the shop; otherwise the close is refused with
    `ERR_OPEN_TICKETS_EXIST`."

    Design: Corner/errors/close_shop_with_open_ticket_returns_open_tickets_exist
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "S", "tax_rate_pct": 0})
    served_walkin_ticket(ctx)  # leaves an OPEN ticket
    res = api.close_shop(ctx["shop"]["id"], OWNER)
    validate_error(res, "ERR_OPEN_TICKETS_EXIST")
    shop = validate_success(api.get_shop(ctx["shop"]["id"], OWNER), 200)
    assert shop["status"] == "OPEN", shop


def test_get_chair_nonexistent_returns_not_found(api):
    """PRD §2.8: "returning that identifier's specific not-found error —
    `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or
    `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_chair_nonexistent_returns_chair_not_found
    """
    res = api.get_chair(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_CHAIR_NOT_FOUND")


def test_get_settlement_nonexistent_returns_not_found(api):
    """PRD §2.8: "returning that identifier's specific not-found error —
    `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or
    `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_settlement_nonexistent_returns_settlement_not_found
    """
    res = api.get_settlement(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_SETTLEMENT_NOT_FOUND")


def test_filtered_list_tickets_by_barber(api):
    """PRD §4: "GET `/tickets` List tickets (filter by shop_id, customer_id,
    barber_id, appointment_id, queue_ticket_id, business_date)".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object".

    Design: Corner/endpoints/filtered_list_tickets_by_barber
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "S", "tax_rate_pct": 0})
    paid_walkin(ctx)
    data, meta = validate_paginated(
        api.list_tickets(OWNER, params={"barber_id": ctx["barber"]["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert len(data) == 1, data
    assert data[0]["barber_id"] == ctx["barber"]["id"], data[0]
