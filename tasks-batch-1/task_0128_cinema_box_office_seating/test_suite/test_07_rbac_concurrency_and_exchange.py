"""Role-based access control, optimistic-concurrency on showtime version,
exchange wallet crediting, and immediate-consistency of the order-create response.
"""
from test_helpers import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    get_success_data,
    make_distributor_headers,
    make_member_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_showtime_payload

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Corner/rbac/*
# ===========================================================================

def test_member_cannot_schedule_showtime(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/member_cannot_schedule_showtime
    """
    base = fx.setup_base(seat_count=4)
    member = fx.make_member()
    payload = create_showtime_payload(base["film"]["id"], "2026-06-10T20:00:00.000Z",
                                      pricing_profile="STANDARD", base_price_cents=1000)
    resp = api.create_showtime(base["auditorium"]["id"], payload, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_member_cannot_refund_order(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §3.7: "Once an order is PAID, a BoxOfficeAgent may refund it."

    Design: Corner/rbac/member_cannot_refund_others_order
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    member_headers = make_member_headers(member["id"])
    order = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1], as_member=True)
    get_success_data(api.pay_order(order["id"], member_headers))

    resp = api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, member_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of these
    known roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    base = fx.setup_base(seat_count=4)
    # No X-User-Role / X-User-ID on a read of an authenticated endpoint.
    resp = api.get_auditorium(base["auditorium"]["id"], ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_distributor_cannot_read_foreign_settlement(api):
    """PRD §2.1: "Ownership checks on a settlement compare the settlement's
    distributor_id to X-User-ID; a distributor may read only its own films,
    showtimes, and settlements, and acting outside that scope is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/distributor_cannot_read_foreign_settlement_not_owner
    """
    ctx = fx.setup_closed_box_office_showtime(
        base_price_cents=1000, num_seats=1,
        starts_at="2026-06-05T13:00:00.000Z", close_at="2026-06-05T15:00:00.000Z",
    )
    settlement = ctx["settlement"]
    # A second, unrelated distributor.
    d2 = fx.make_distributor(name="D2")
    resp = api.get_settlement(settlement["id"], make_distributor_headers(d2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/*
# ===========================================================================

def test_stale_showtime_version_on_order_create_rejected(api):
    """PRD §2.5: "If another writer has held or sold seats on the same showtime since
    the client last read it — legitimately advancing the showtime's seat counts and
    version — the create is rejected with ERR_STALE_SHOWTIME_VERSION (HTTP 412), and
    no seat is held."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_showtime_version_on_order_create
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000, seat_count=6)
    stale_version = ctx["showtime"]["version"]
    member_a = fx.make_member(email="a@x.com", full_name="A")
    member_b = fx.make_member(email="b@x.com", full_name="B")

    # A creates an order, advancing the showtime version.
    fx.create_held_order(ctx["showtime"], member_a, ctx["seat_ids"][:1])

    # B sends a create still carrying the pre-A (stale) version.
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member_b["id"], "seat_ids": ctx["seat_ids"][1:2],
         "expected_showtime_version": stale_version},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SHOWTIME_VERSION.value)


def test_order_create_with_current_version_increments_showtime(api):
    """PRD §2.5: "When a client creates an order against a showtime, the request must
    carry expected_showtime_version matching that showtime's current version."
    PRD §3.4: "Creating the order increments the showtime's version."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_increments_on_order_create
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    before = ctx["showtime"]["version"]
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member["id"], "seat_ids": ctx["seat_ids"][:1],
         "expected_showtime_version": before},
        AGENT,
    )
    validate_success(resp, 201)
    reread = get_success_data(api.get_showtime(ctx["showtime"]["id"], MANAGER))
    assert reread["version"] == before + 1


def test_exchange_credits_wallet_on_cheaper_target(api):
    """PRD §3.7: "The price difference is settled by comparing the new tickets'
    subtotal to the old: if the new subtotal is greater, the successor order carries
    the delta as the amount due, while if it is smaller, the difference is credited
    to the member's wallet_credit_cents."

    Design: Corner/cross_cutting_complexity_layers/exchange_credits_wallet_on_cheaper_target
    """
    # Source: 2 seats base 2000 (subtotal 4000). Target: take 1 seat (subtotal 2000).
    ctx = fx.setup_two_on_sale_showtimes(
        base_price_cents=2000,
        starts_at_x="2026-06-10T20:00:00.000Z",
        starts_at_y="2026-06-12T20:00:00.000Z",
    )
    member = fx.make_member()
    order = fx.create_paid_order(ctx["showtime_x"], member, ctx["seats_x"][:2])
    assert order["status"] == "PAID"

    exchanged = get_success_data(
        api.exchange_order(
            order["id"],
            {"new_showtime_id": ctx["showtime_y"]["id"], "new_seat_ids": ctx["seats_y"][:1]},
            AGENT,
        )
    )
    assert exchanged["status"] == "EXCHANGED"

    member_now = get_success_data(api.get_member(member["id"], MANAGER))
    assert member_now["wallet_credit_cents"] == 2000  # 4000 old - 2000 new


# ===========================================================================
# Corner/consistency_model/*
# ===========================================================================

def test_order_create_response_reflects_held_state_immediately(api):
    """PRD §3.4: "the order begins in HELD status."
    PRD §3.4: "Each ticket is quoted a provisional price at this moment, stored on
    provisional_price_cents"

    Design: Corner/consistency_model/order_create_response_reflects_held_state_immediately
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member["id"], "seat_ids": ctx["seat_ids"][:1],
         "expected_showtime_version": ctx["showtime"]["version"]},
        AGENT,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "HELD"
    # PRD §3.5 computes tickets_subtotal_cents only "At payment", so a HELD order's
    # subtotal is not PRD-derivable; the provisional price lives on each ticket
    # (PRD §3.4) and is checked elsewhere. Only the HELD-state claim is asserted here.
