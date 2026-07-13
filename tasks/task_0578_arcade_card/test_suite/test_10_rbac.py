"""Role-based access control: role denial, entity-backed Member ownership, and
authentication of the request headers."""
from test_helpers import validate_error, ApiErrorId, TEST_USERS, make_member_headers
from test_helpers.fixtures import (
    create_member, issue_card, activate_card, reload_card, create_attraction,
    create_room, create_package, create_booking,
)

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# --- Corner: member_cannot_create_attraction ---
def test_member_cannot_create_attraction(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_attraction
    """
    member = create_member(api)
    resp = api.create_attraction(
        {"name": "X", "chip_cost_cents": 100, "points_award": 10},
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


# --- Corner: cashier_cannot_confirm_booking ---
def test_cashier_cannot_confirm_booking(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_confirm_booking
    """
    room = create_room(api, capacity=20, hourly_rate_cents=8_000)
    package = create_package(api, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    booking = create_booking(api, room["id"], package["id"], host["id"],
                             "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 2)
    resp = api.confirm_party_booking(booking["id"], CASHIER)  # confirm is Coordinator-only
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


# --- Corner: member_cannot_play_on_unowned_card ---
def test_member_cannot_play_on_unowned_card(api):
    """PRD §2.1: "when a `Member` plays an attraction or reserves a redemption against a game
    card, that card's `owner_member_id` must equal `X-User-ID` ... An ownership failure is an
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_play_on_unowned_card
    """
    attraction = create_attraction(api, chip_cost_cents=100, points_award=10)
    m1 = create_member(api)
    m2 = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=m1["id"])["id"])
    reload_card(api, card["id"], 500)
    resp = api.create_game_play(
        {"card_id": card["id"], "attraction_id": attraction["id"]},
        make_member_headers(m2["id"]))  # m2 does not own the card
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


# --- Corner: missing_auth_headers_unauthenticated ---
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    member = create_member(api)
    resp = api.get_member(member["id"], {})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
