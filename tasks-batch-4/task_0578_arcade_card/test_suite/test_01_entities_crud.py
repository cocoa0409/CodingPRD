"""Entity CRUD, creation defaults, not-found, required-field, FK resolution,
listing/pagination, and immediate-consistency corners."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_member_payload, create_attraction_payload, create_game_card_payload,
    assert_member, assert_game_card,
)
from test_helpers.fixtures import create_member, issue_card, activate_card

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_member_returns_active_none_tier(api):
    """PRD §3.1: "A new member starts with a `status` of `ACTIVE` (the alternative,
    `SUSPENDED`, is reserved for future administrative action), a `lifetime_spend_cents`
    of 0, and a `membership_tier` of `NONE`."

    Design: Corner/entities/create_member_returns_201_with_fields
    """
    resp = api.create_member(create_member_payload(full_name="New Member", promo_opt_in=True), CASHIER)
    data = validate_success(resp, 201)
    assert_member(data)
    got = validate_success(api.get_member(data["id"], CASHIER))
    assert got["status"] == "ACTIVE"
    assert got["membership_tier"] == "NONE"
    assert got["lifetime_spend_cents"] == 0
    assert got["promo_opt_in"] is True


def test_promo_opt_in_defaults_false(api):
    """PRD §3.1: "an optional `promo_opt_in` flag indicating enrollment in eat-and-play
    promotions, which defaults to false when omitted."

    Design: Corner/entities/default_promo_opt_in_false
    """
    resp = api.create_member(create_member_payload(full_name="Default"), CASHIER)
    data = validate_success(resp, 201)
    got = validate_success(api.get_member(data["id"], CASHIER))
    assert got["promo_opt_in"] is False


def test_new_card_inactive_zero_balances(api):
    """PRD §3.1: "A newly issued card is `INACTIVE` with all three balances —
    `chip_balance_cents`, `bonus_chip_balance_cents`, and `ticket_points_balance` — at zero."

    Design: Corner/entities/new_card_system_fields
    """
    member = create_member(api)
    resp = api.create_game_card(create_game_card_payload(owner_member_id=member["id"]), CASHIER)
    data = validate_success(resp, 201)
    got = validate_success(api.get_game_card(data["id"], CASHIER))
    assert got["status"] == "INACTIVE"
    assert got["chip_balance_cents"] == 0
    assert got["bonus_chip_balance_cents"] == 0
    assert got["ticket_points_balance"] == 0


def test_get_missing_card_returns_not_found(api):
    """PRD §2.10: "The first identifier that resolves to nothing yields the matching
    `ERR_<ENTITY>_NOT_FOUND` (404): `ERR_MEMBER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, ..."

    Design: Corner/entities/card_not_found_returns_404
    """
    resp = api.get_game_card(NONEXISTENT, CASHIER)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_FOUND, 404)


def test_create_attraction_missing_chip_cost_rejected(api):
    """PRD §2.10: "on write endpoints, required fields must be present, enums valid, and
    numeric fields such as `quantity`, `guest_count`, and `amount_cents` strictly positive;
    for bookings, `end_at` must be strictly after `start_at`. A violation is `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_attraction_missing_required_field
    """
    payload = {"name": "NoPrice", "points_award": 10}  # chip_cost_cents omitted
    resp = api.create_attraction(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 422)


def test_issue_card_with_nonexistent_owner_rejected(api):
    """PRD §2.10: "Path identifiers are checked first, left to right, then body foreign keys.
    The first identifier that resolves to nothing yields the matching `ERR_<ENTITY>_NOT_FOUND`
    (404): `ERR_MEMBER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, ..."

    Design: Corner/entities/fk_owner_member_nonexistent_rejected
    """
    resp = api.create_game_card(create_game_card_payload(owner_member_id=NONEXISTENT), CASHIER)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND, 404)


def test_list_cards_filtered_by_owner(api):
    """PRD §3.1: "Cards can be listed and filtered by their owner and by status."

    Design: Corner/entities/fk_reverse_reachability_cards_by_owner
    """
    member = create_member(api)
    issue_card(api, owner_member_id=member["id"])
    issue_card(api, owner_member_id=member["id"])
    resp = api.list_game_cards(CASHIER, params={"owner_member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert all(c["owner_member_id"] == member["id"] for c in data)


def test_list_cards_pagination_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_cards_pagination_envelope
    """
    member = create_member(api)
    for _ in range(3):
        issue_card(api, owner_member_id=member["id"])
    resp = api.list_game_cards(CASHIER, params={"owner_member_id": member["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_reload_response_reflects_new_balance_and_version(api):
    """PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field."
    PRD §2.4: "`version` — an integer that begins at its initial value and increments by one
    on every mutation."

    Design: Corner/consistency_model/reload_reflects_new_balance_same_response
    """
    card = issue_card(api)  # anonymous
    activated = activate_card(api, card["id"])
    v_after_activate = activated["version"]
    resp = api.reload_game_card(card["id"], {"amount_cents": 2500}, CASHIER)
    data = validate_success(resp, 200)
    assert data["chip_balance_cents"] == 2500
    assert data["version"] == v_after_activate + 1
