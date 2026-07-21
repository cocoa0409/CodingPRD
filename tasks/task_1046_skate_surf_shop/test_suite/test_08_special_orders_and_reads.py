"""Special-order OCC + state guard, authentication/validation/existence guards,
reverse-reachability listings, and entity-backed instructor ownership.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, NO_AUTH_HEADERS, get_success_data, make_instructor_headers,
    create_member, create_active_product, create_draft_build, create_booked_lesson,
    create_open_event, create_event_with_registration, create_quoted_special_order,
    create_member_payload, create_rental_unit_payload, create_special_order_payload,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_requote_stale_version_412(api):
    """PRD §2.11: "A quote request must carry `expected_special_order_version`, and the
    server compares it against the special order's current `version`. If they do not
    match — because another quote has already advanced the order's version since the
    client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    preventing the client from superseding a quote it never observed."

    Design: Corner/cross_cutting_complexity_layers/special_order_requote_stale_version_returns_412
    """
    order, member, v0 = create_quoted_special_order(api, quoted_price_cents=12000)
    resp = api.quote_special_order(
        order["id"],
        {"quoted_price_cents": 13000, "expected_special_order_version": v0}, ASSOC)
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_deposit_before_quote_invalid_state(api):
    """PRD §3.7: "Collecting a deposit is allowed only from `QUOTED`, recording the
    supplied `deposit_cents` and moving the order to `DEPOSIT_PAID`."

    Design: Corner/state_machines/special_order_deposit_before_quote_returns_invalid_state
    """
    member = create_member(api)
    order = get_success_data(api.create_special_order(
        create_special_order_payload(member["id"], product_name="Custom fin"), ASSOC))
    resp = api.deposit_special_order(order["id"], {"deposit_cents": 500}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_create_member_missing_auth(api):
    """PRD §2.1: "If either header is missing or the role is not one the system
    recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/create_member_missing_auth_returns_unauthenticated
    """
    resp = api.create_member(create_member_payload(), NO_AUTH_HEADERS)
    assert resp.status_code == 401
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_create_rental_unit_invalid_kind(api):
    """PRD §2.5: "4. **Body well-formedness** — required fields present, enum values
    valid, constrained integers non-negative, quantities strictly greater than zero,
    and any interval's start strictly before its end, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_rental_unit_invalid_kind_returns_validation
    """
    payload = create_rental_unit_payload(kind="CANOE")
    resp = api.create_rental_unit(payload, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_nonexistent_member_returns_404(api):
    """PRD §2.5: "3. **Existence** — the path identifier and every body foreign key
    resolve to an existing resource, checked left to right, otherwise the matching
    `ERR_<ENTITY>_NOT_FOUND` (404)."

    Design: Corner/entities/get_member_nonexistent_returns_404
    """
    resp = api.get_member(NON_EXISTENT, SM)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_list_board_builds_by_member(api):
    """PRD §3.3: "Builds can be fetched individually or listed by `member_id` and `status`."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_board_builds_by_member_reverse_reachability
    """
    member = create_member(api)
    product = create_active_product(api, unit_price_cents=6000, stock_on_hand=3)
    build = create_draft_build(
        api, member_id=member["id"],
        component_lines=[{"product_id": product["id"], "qty": 1}])
    resp = api.list_board_builds(ASSOC, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert any(b["id"] == build["id"] for b in data)
    assert "total_count" in meta and "has_more" in meta


def test_list_event_registrations_by_event(api):
    """PRD §3.8: "Registrations can be fetched individually or listed by `event_id`,
    `member_id`, and `status`."

    Design: Corner/entities/list_event_registrations_by_event_reverse_reachability
    """
    event, reg, member = create_event_with_registration(api, capacity=10, entry_points_cost=0)
    resp = api.list_event_registrations(ASSOC, params={"event_id": event["id"]})
    data, meta = validate_paginated(resp)
    assert any(r["id"] == reg["id"] for r in data)


def test_instructor_confirms_own_lesson(api):
    """PRD §3.5: "Confirming a lesson is an `Instructor`-or-`ShopManager` action
    allowed only from `BOOKED`, and it additionally requires that every rental linked
    to this lesson be in `RESERVED` or `CHECKED_OUT` status, else `ERR_RENTAL_NOT_READY`;
    on success `confirmed_at` is stamped."

    Design: Corner/rbac/instructor_confirms_own_lesson_succeeds
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SURF", fee_cents=5000,
        start_at="2026-07-12T10:00:00Z", end_at="2026-07-12T11:00:00Z")
    resp = api.confirm_lesson(lesson["id"], make_instructor_headers(instructor["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"
