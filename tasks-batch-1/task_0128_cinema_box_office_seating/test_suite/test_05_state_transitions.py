"""Showtime/order/film state-machine transitions: initial states, valid/invalid
transitions, terminal lockdown, side-effect bubble-up, hold expiry, and close.
"""
from test_helpers import TEST_USERS, get_success_data, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


def test_newly_created_showtime_initial_state_scheduled(api):
    """PRD §3.2: "A newly scheduled showtime starts in SCHEDULED status."

    Design: Corner/state_machines/newly_created_showtime_initial_state_scheduled
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])
    assert showtime["status"] == "SCHEDULED"


def test_open_already_on_sale_showtime_invalid_state(api):
    """PRD §3.2: "Opening is permitted only when the showtime is currently SCHEDULED
    and the film is in BOOKING or RUNNING status"

    Design: Corner/state_machines/open_showtime_from_already_on_sale_invalid_state
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    resp = api.open_showtime(ctx["showtime"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_showtime_invalid_state(api):
    """PRD §3.8: "Cancellation is rejected with ERR_INVALID_STATE if the screening is
    in any other status."
    PRD §3.8: "The screening moves to CANCELLED, a terminal status, and the
    consequences differ by where it started."

    Design: Corner/state_machines/cancel_already_cancelled_showtime_invalid_state
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])
    first = get_success_data(
        api.cancel_showtime(showtime["id"], {"expected_showtime_version": showtime["version"]}, MANAGER)
    )
    resp = api.cancel_showtime(
        showtime["id"], {"expected_showtime_version": first["version"]}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_first_showtime_bubbles_film_to_running(api):
    """PRD §3.2: "The first time any screening of a film is opened, the film bubbles
    up from BOOKING to RUNNING as a side effect, and opening increments the
    showtime's version."

    Design: Corner/state_machines/open_first_showtime_bubbles_film_to_running
    """
    base = fx.setup_base(seat_count=4)
    assert base["film"]["status"] == "BOOKING"
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])
    fx.open_showtime(showtime["id"])

    film = get_success_data(api.get_film(base["film"]["id"], MANAGER))
    assert film["status"] == "RUNNING"


def test_held_order_expires_after_ttl_releases_seats(api):
    """PRD §3.6: "When the current time reaches or passes that instant while the
    order is still HELD, the order auto-expires: it moves to EXPIRED, each of its
    tickets is VOIDED, each held seat returns to FREE occupancy, and the showtime's
    version is incremented."

    Design: Corner/state_machines/held_order_expires_after_ttl_releases_seats
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000, now="2026-06-02T09:00:00.000Z")
    member = fx.make_member()
    seat0 = ctx["seat_ids"][0]
    order = fx.create_held_order(ctx["showtime"], member, [seat0])

    # Advance 30 minutes past creation (TTL is 15m).
    fx.advance_clock("2026-06-02T09:30:00.000Z")

    reread = get_success_data(api.get_order(order["id"], MANAGER))
    assert reread["status"] == "EXPIRED"

    seats = get_success_data(api.get_showtime_seats(ctx["showtime"]["id"], MANAGER, params={"limit": 100}))
    target = next(s for s in seats if s["id"] == seat0)
    assert target["occupancy"] == "FREE"


def test_cancel_held_order_releases_seats(api):
    """PRD §3.6: "Cancellation is permitted only while the order is HELD; it moves
    the order to CANCELLED, voids each ticket, returns each seat to FREE, and
    increments the showtime's version."

    Design: Corner/state_machines/cancel_held_order_releases_seats
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    seat0 = ctx["seat_ids"][0]
    order = fx.create_held_order(ctx["showtime"], member, [seat0])

    cancelled = get_success_data(api.cancel_order(order["id"], AGENT))
    assert cancelled["status"] == "CANCELLED"

    seats = get_success_data(api.get_showtime_seats(ctx["showtime"]["id"], MANAGER, params={"limit": 100}))
    target = next(s for s in seats if s["id"] == seat0)
    assert target["occupancy"] == "FREE"


def test_close_creates_box_office_settlement(api):
    """PRD §3.9: "Closing creates exactly one Settlement for the screening and
    increments the showtime's version."
    PRD §3.9: "For a BOX_OFFICE screening, the settlement's gross_receipts_cents is
    a snapshot of the showtime's gross receipts at close."

    Design: Corner/state_machines/close_creates_box_office_settlement
    """
    ctx = fx.setup_closed_box_office_showtime(
        base_price_cents=1000, num_seats=2,
        starts_at="2026-06-05T13:00:00.000Z", close_at="2026-06-05T15:00:00.000Z",
    )
    assert ctx["showtime"]["status"] == "CLOSED"
    settlements = get_success_data(api.get_showtime_settlement(ctx["showtime"]["id"], MANAGER))
    assert len(settlements) == 1
    s = settlements[0]
    assert s["gross_receipts_cents"] == 2000
    assert s["applied_distributor_pct"] == 0.70
    assert s["distributor_share_cents"] == 1400  # round(2000 * 0.70)


def test_close_before_ends_at_rejected(api):
    """PRD §3.9: "Closing is permitted only when the screening is ON_SALE, the
    current time is at or past its ends_at, and no order on the screening is still
    HELD; an attempt before the screening is over or while a held order remains is
    rejected with ERR_SHOWTIME_NOT_OVER."

    Design: Corner/state_machines/close_before_ends_at_rejected
    """
    # Showtime starts far in the future; clock still well before ends_at.
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000, starts_at="2026-06-10T20:00:00.000Z")
    resp = api.close_showtime(ctx["showtime"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_SHOWTIME_NOT_OVER.value)
