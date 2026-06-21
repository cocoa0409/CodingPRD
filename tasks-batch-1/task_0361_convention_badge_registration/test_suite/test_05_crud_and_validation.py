"""CRUD creation, request well-formedness, uniqueness, and invalid-state
transitions across conventions, orders, attendees, booths, ticket types, and badges.
"""
from test_helpers import (
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_convention,
    assert_order,
    set_clock,
    create_convention,
    create_attendee,
    create_booth,
    setup_convention_with_ticket_type,
    create_draft_order,
    create_paid_order,
    create_submitted_order,
    convention_version,
    make_attendee_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.factories import create_order_payload, line_item

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_convention_returns_201_open_posture(api):
    """PRD §3.1: "A new convention starts with its `badges_issued_count` at 0 and its `posture` at `OPEN`."

    Design: Corner/entities/create_convention_returns_201_with_open_posture
    """
    res = api.create_convention(
        {"name": "Fresh Con", "event_start_utc": "2026-09-01T00:00:00Z",
         "event_end_utc": "2026-09-03T23:59:59Z", "total_badge_capacity": 50,
         "lottery_open_utc": "2026-06-01T00:00:00Z"}, ADMIN)
    conv = validate_success(res, 201)
    assert_convention(conv)
    assert conv["posture"] == "OPEN"
    assert conv["badges_issued_count"] == 0
    assert conv["version"] == 1


def test_create_order_empty_line_items_rejected(api):
    """PRD §3.3: "An order created with zero line items is rejected with `ERR_EMPTY_ORDER`, as is a submit attempt on an order that has no line items."

    Design: Corner/entities/create_order_missing_line_items_returns_empty_order
    """
    conv = create_convention()
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    res = api.create_order(create_order_payload(conv["id"], att["id"], []), headers)
    validate_error(res, "ERR_EMPTY_ORDER", expected_status=422)


def test_get_convention_nonexistent_returns_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing row causes immediate rejection with `ERR_NOT_FOUND`, before any business rule is evaluated."

    Design: Corner/entities/get_convention_nonexistent_returns_not_found
    """
    res = api.get_convention(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_duplicate_attendee_email_rejected_case_insensitive(api):
    """PRD §3.2: "If the supplied email already belongs to another attendee under a case-insensitive comparison, the registration is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_attendee_email_rejected_case_insensitive
    """
    validate_success(api.create_attendee({"email": "dup@x.com", "full_name": "First"}, ANON), 201)
    res = api.create_attendee({"email": "DUP@x.com", "full_name": "Second"}, ANON)
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_duplicate_booth_code_within_convention_rejected(api):
    """PRD §3.7: "carries a `booth_code` that must be unique within the convention (a duplicate code is rejected with `ERR_DUPLICATE_BOOTH_CODE`)".

    Design: Corner/entities/duplicate_booth_code_within_convention_rejected
    """
    conv = create_convention()
    validate_success(api.create_booth(conv["id"], {"booth_code": "A1", "zone": "STANDARD"}, ADMIN), 201)
    res = api.create_booth(conv["id"], {"booth_code": "A1", "zone": "PREMIUM"}, ADMIN)
    validate_error(res, "ERR_DUPLICATE_BOOTH_CODE", expected_status=409)


def test_convention_end_before_start_rejected(api):
    """PRD §3.9: "any end instant strictly after its corresponding start instant. A malformed body — a missing required field, an illegal enum value, an out-of-range number, or an end at or before its start — is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/convention_end_before_start_rejected
    """
    res = api.create_convention(
        {"name": "Bad Dates", "event_start_utc": "2026-09-03T00:00:00Z",
         "event_end_utc": "2026-09-01T00:00:00Z", "total_badge_capacity": 50,
         "lottery_open_utc": "2026-06-01T00:00:00Z"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_invalid_ticket_tier_enum_rejected(api):
    """PRD §3.9: "enum-valued fields carrying only legal values ... A malformed body
    — a missing required field, an illegal enum value, an out-of-range number, or an
    end at or before its start — is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/invalid_ticket_tier_enum_rejected
    """
    conv = create_convention()
    res = api.create_ticket_type(conv["id"], {"tier": "PLATINUM", "base_price_cents": 1000, "tier_capacity": 10}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_system_fields_server_minted_on_convention(api):
    """PRD §2.4: "Every entity in the system carries a server-minted id formatted as
    a UUID with no type prefix, and a created_at timestamp expressed in ISO 8601 UTC
    with three fractional digits ... an integer version that begins at its initial
    value and increments by exactly one on each mutation of that resource."

    Design: Corner/entities/system_fields_generated_input_ignored_on_convention
    """
    conv = validate_success(api.create_convention(
        {"name": "Sys Fields Con", "event_start_utc": "2026-09-01T00:00:00Z",
         "event_end_utc": "2026-09-03T23:59:59Z", "total_badge_capacity": 50,
         "lottery_open_utc": "2026-06-01T00:00:00Z"}, ADMIN), 201)
    assert is_valid_uuid(conv["id"])
    assert "_" not in conv["id"]  # UUID with no type prefix
    assert conv["version"] == 1
    assert is_iso8601_timestamp(conv["created_at"])


def test_new_order_starts_in_draft(api):
    """PRD §3.3: "The order is born in `DRAFT` with all of its pricing fields at 0."

    Design: Corner/state_machines/new_order_starts_in_draft_state
    """
    conv, tt = setup_convention_with_ticket_type()
    att = create_attendee()
    order = create_draft_order(conv["id"], att["id"], [(tt["id"], 1)])
    assert_order(order)
    assert order["status"] == "DRAFT"
    assert order["ticket_subtotal_cents"] == 0


def test_cancel_paid_order_returns_invalid_state(api):
    """PRD §3.4: "A `DRAFT` or `PENDING_PAYMENT` order may instead be cancelled by its attendee".
    PRD §2.9: "the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_paid_order_returns_invalid_state
    """
    conv, tt = setup_convention_with_ticket_type()
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    paid = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    res = api.cancel_order(paid["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_order(paid["id"], headers), 200)
    assert after["status"] == "PAID"


def test_refund_already_refunded_invalid_state(api):
    """PRD §3.4: "Refunds apply only to a `PAID` order and are performed by a `RegistrationAgent` or `ConventionAdmin`, moving the order to the terminal `REFUNDED` state."
    PRD §2.9: "the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/refund_already_refunded_terminal_lockdown
    """
    conv, tt = setup_convention_with_ticket_type()
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    paid = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    validate_success(api.refund_order(paid["id"], AGENT), 200)
    res = api.refund_order(paid["id"], AGENT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_order(paid["id"], headers), 200)
    assert after["status"] == "REFUNDED"


def test_list_conventions_pagination_envelope(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_conventions_pagination_envelope
    """
    create_convention(name="Page One")
    create_convention(name="Page Two", event_start_utc="2026-10-01T00:00:00Z",
                      event_end_utc="2026-10-03T23:59:59Z", lottery_open_utc="2026-07-01T00:00:00Z")
    body = api.list_conventions(ADMIN, params={"limit": 1, "offset": 0}).json()
    assert body["response_type"] == "array"
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["has_more"] is True
    assert len(body["data"]) == 1


def test_order_line_items_subresource_lists_lines(api):
    """PRD §3.3: "referencing its `order_id` and a `ticket_type_id`, with a `quantity` of one or more badges of that tier".

    Design: Corner/endpoints/order_line_items_subresource_lists_lines
    """
    conv, tt_gen = setup_convention_with_ticket_type(tt_overrides={"tier": "GENERAL", "base_price_cents": 9900})
    tt_vip = validate_success(api.create_ticket_type(
        conv["id"], {"tier": "VIP", "base_price_cents": 49900, "tier_capacity": 50}, ADMIN), 201)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    order = create_draft_order(conv["id"], att["id"], [(tt_gen["id"], 1), (tt_vip["id"], 1)])
    body = api.list_order_line_items(order["id"], headers).json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 2
