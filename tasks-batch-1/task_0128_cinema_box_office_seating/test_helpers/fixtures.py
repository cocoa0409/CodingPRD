"""Composite setup helpers.

These encapsulate the multi-step preambles that most interesting test claims
need: a server starts each test against an empty database, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

All setup calls use get_success_data() (lenient) so a setup failure surfaces a
clear "Setup step failed" message rather than a confusing assertion later.

Identity threading: Member is entity-backed, so any member-initiated call uses
make_member_headers(member_id). Distributor reads use make_distributor_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_auditorium_payload,
    create_combo_payload,
    create_distributor_payload,
    create_film_payload,
    create_member_payload,
    create_order_payload,
    create_showtime_payload,
)
from .test_users import TEST_USERS, make_member_headers

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]

# A fixed "now" the fixtures advance the clock to before scheduling. All default
# showtimes start well after this instant.
DEFAULT_NOW = "2026-06-02T09:00:00.000Z"
DEFAULT_STARTS_AT = "2026-06-10T20:00:00.000Z"


# --------------------------------------------------------------------------
# Tier 0: primitive creators (single-call, lenient)
# --------------------------------------------------------------------------

def make_distributor(**overrides) -> dict:
    resp = api_client.create_distributor(create_distributor_payload(**overrides), MANAGER)
    return get_success_data(resp)


def make_film(distributor_id, **overrides) -> dict:
    resp = api_client.create_film(create_film_payload(distributor_id, **overrides), MANAGER)
    return get_success_data(resp)


def make_auditorium(**overrides) -> dict:
    resp = api_client.create_auditorium(create_auditorium_payload(**overrides), MANAGER)
    return get_success_data(resp)


def make_member(**overrides) -> dict:
    resp = api_client.create_member(create_member_payload(**overrides), MANAGER)
    return get_success_data(resp)


def make_combo(**overrides) -> dict:
    resp = api_client.create_combo(create_combo_payload(**overrides), MANAGER)
    return get_success_data(resp)


def advance_clock(to_iso8601: str):
    return get_success_data(api_client.advance_clock(to_iso8601, MANAGER))


# --------------------------------------------------------------------------
# Tier 1: base groundwork — distributor + film + auditorium + clock set
# --------------------------------------------------------------------------

def setup_base(
    *,
    now=DEFAULT_NOW,
    seat_count=4,
    turnaround_minutes=20,
    runtime_minutes=90,
    release_date="2026-06-01T00:00:00.000Z",
    split_schedule=None,
    minimum_guarantee_cents=0,
):
    """Create a distributor, film, and one auditorium, then set the clock.

    Returns dict with keys: distributor, film, auditorium.
    """
    distributor = make_distributor(minimum_guarantee_cents=minimum_guarantee_cents)
    film_overrides = {"runtime_minutes": runtime_minutes, "release_date": release_date}
    if split_schedule is not None:
        film_overrides["split_schedule"] = split_schedule
    film = make_film(distributor["id"], **film_overrides)
    auditorium = make_auditorium(seat_count=seat_count, turnaround_minutes=turnaround_minutes)
    if now is not None:
        advance_clock(now)
    return {"distributor": distributor, "film": film, "auditorium": auditorium}


# --------------------------------------------------------------------------
# Tier 1b: schedule a showtime in an existing auditorium
# --------------------------------------------------------------------------

def schedule_showtime(auditorium_id, film_id, *, starts_at=DEFAULT_STARTS_AT, **overrides) -> dict:
    """Schedule a single showtime (SCHEDULED). Returns the showtime resource."""
    resp = api_client.create_showtime(
        auditorium_id, create_showtime_payload(film_id, starts_at, **overrides), MANAGER
    )
    return get_success_data(resp)


def open_showtime(showtime_id) -> dict:
    """Open (SCHEDULED -> ON_SALE). Returns the updated showtime (carries fresh version)."""
    return get_success_data(api_client.open_showtime(showtime_id, MANAGER))


def get_seat_ids(showtime_id, count=None, occupancy=None) -> list:
    """Return seat ids for a showtime, optionally filtered by occupancy."""
    params = {"limit": 100}
    if occupancy is not None:
        params["occupancy"] = occupancy
    data = get_success_data(api_client.get_showtime_seats(showtime_id, MANAGER, params=params))
    ids = [s["id"] for s in data]
    return ids if count is None else ids[:count]


def current_version(showtime_id) -> int:
    return get_success_data(api_client.get_showtime(showtime_id, MANAGER))["version"]


# --------------------------------------------------------------------------
# Tier 2: an ON_SALE showtime ready for orders
# --------------------------------------------------------------------------

def setup_on_sale_showtime(
    *,
    base_price_cents=1000,
    pricing_profile="STANDARD",
    starts_at=DEFAULT_STARTS_AT,
    seat_count=4,
    turnaround_minutes=20,
    now=DEFAULT_NOW,
    runtime_minutes=90,
    release_date="2026-06-01T00:00:00.000Z",
    split_schedule=None,
    minimum_guarantee_cents=0,
    rental_basis=None,
    private_rental_fee_cents=None,
):
    """Distributor + film + auditorium + scheduled-and-opened showtime.

    Returns dict: distributor, film, auditorium, showtime (post-open, with the
    current version captured), seat_ids (full list).
    """
    base = setup_base(
        now=now,
        seat_count=seat_count,
        turnaround_minutes=turnaround_minutes,
        runtime_minutes=runtime_minutes,
        release_date=release_date,
        split_schedule=split_schedule,
        minimum_guarantee_cents=minimum_guarantee_cents,
    )
    st_overrides = {"pricing_profile": pricing_profile, "base_price_cents": base_price_cents}
    if rental_basis is not None:
        st_overrides["rental_basis"] = rental_basis
    if private_rental_fee_cents is not None:
        st_overrides["private_rental_fee_cents"] = private_rental_fee_cents
    showtime = schedule_showtime(
        base["auditorium"]["id"], base["film"]["id"], starts_at=starts_at, **st_overrides
    )
    opened = open_showtime(showtime["id"])
    seat_ids = get_seat_ids(showtime["id"])
    return {
        "distributor": base["distributor"],
        "film": base["film"],
        "auditorium": base["auditorium"],
        "showtime": opened,
        "seat_ids": seat_ids,
    }


# --------------------------------------------------------------------------
# Tier 3: held / paid orders
# --------------------------------------------------------------------------

def create_held_order(showtime, member, seat_ids, *, as_member=False, **payload_overrides) -> dict:
    """Create a HELD order on an ON_SALE showtime. Uses the showtime's current
    version for expected_showtime_version. Returns the order resource."""
    version = showtime["version"] if "version" in showtime else current_version(showtime["id"])
    headers = make_member_headers(member["id"]) if as_member else AGENT
    payload = create_order_payload(member["id"], seat_ids, version, **payload_overrides)
    resp = api_client.create_order(showtime["id"], payload, headers)
    return get_success_data(resp)


def create_paid_order(showtime, member, seat_ids, *, as_member=False, **payload_overrides) -> dict:
    """Create a HELD order and pay it. Returns the PAID order resource."""
    order = create_held_order(showtime, member, seat_ids, as_member=as_member, **payload_overrides)
    headers = make_member_headers(member["id"]) if as_member else AGENT
    paid = get_success_data(api_client.pay_order(order["id"], headers))
    return paid


def setup_paid_order(
    *,
    base_price_cents=1000,
    num_seats=1,
    pricing_profile="STANDARD",
    starts_at=DEFAULT_STARTS_AT,
    seat_count=4,
    minimum_guarantee_cents=0,
    now=DEFAULT_NOW,
):
    """Full chain to a PAID order on a future ON_SALE showtime.

    Returns dict: distributor, film, auditorium, showtime, member, seat_ids
    (the seats taken by the order), order (PAID).
    """
    ctx = setup_on_sale_showtime(
        base_price_cents=base_price_cents,
        pricing_profile=pricing_profile,
        starts_at=starts_at,
        seat_count=seat_count,
        minimum_guarantee_cents=minimum_guarantee_cents,
        now=now,
    )
    member = make_member()
    taken = ctx["seat_ids"][:num_seats]
    order = create_paid_order(ctx["showtime"], member, taken)
    return {
        "distributor": ctx["distributor"],
        "film": ctx["film"],
        "auditorium": ctx["auditorium"],
        "showtime": ctx["showtime"],
        "member": member,
        "seat_ids": taken,
        "order": order,
    }


# --------------------------------------------------------------------------
# Tier 3b: elevate a member to SILVER (loyalty_points >= 50)
# --------------------------------------------------------------------------

def make_silver_member(auditorium_id, film_id, *, seed_starts_at="2026-06-05T20:00:00.000Z"):
    """Register a member and lift them to SILVER by paying a 5000c-subtotal order
    (2 STANDARD seats at base 2500 -> 50 points) on a throwaway showtime.

    Returns the member resource (re-read so loyalty_points/tier are current).
    """
    member = make_member()
    seed_st = schedule_showtime(
        auditorium_id, film_id, starts_at=seed_starts_at,
        pricing_profile="STANDARD", base_price_cents=2500,
    )
    opened = open_showtime(seed_st["id"])
    seed_seats = get_seat_ids(seed_st["id"], count=2)
    create_paid_order(opened, member, seed_seats)
    return get_success_data(api_client.get_member(member["id"], MANAGER))


# --------------------------------------------------------------------------
# Tier 4: closed showtime + settlement
# --------------------------------------------------------------------------

def setup_closed_box_office_showtime(
    *,
    base_price_cents,
    num_seats,
    starts_at,
    close_at,
    split_schedule=None,
    release_date="2026-06-01T00:00:00.000Z",
    minimum_guarantee_cents=0,
    now=DEFAULT_NOW,
):
    """Build a BOX_OFFICE showtime, sell `num_seats`, advance past ends_at, close.

    Returns dict: distributor, film, auditorium, showtime, member, order, settlement.
    """
    ctx = setup_on_sale_showtime(
        base_price_cents=base_price_cents,
        starts_at=starts_at,
        seat_count=max(num_seats, 4),
        split_schedule=split_schedule,
        release_date=release_date,
        minimum_guarantee_cents=minimum_guarantee_cents,
        now=now,
    )
    member = make_member()
    taken = ctx["seat_ids"][:num_seats]
    order = create_paid_order(ctx["showtime"], member, taken)
    advance_clock(close_at)
    closed = get_success_data(api_client.close_showtime(ctx["showtime"]["id"], MANAGER))
    settlement_list = get_success_data(
        api_client.get_showtime_settlement(ctx["showtime"]["id"], MANAGER)
    )
    return {
        "distributor": ctx["distributor"],
        "film": ctx["film"],
        "auditorium": ctx["auditorium"],
        "showtime": closed,
        "member": member,
        "order": order,
        "settlement": settlement_list[0] if settlement_list else None,
    }


# --------------------------------------------------------------------------
# Tier 5: two-showtime scenarios (member overlap, exchange, seat-not-on-showtime)
# --------------------------------------------------------------------------

def setup_two_on_sale_showtimes(
    *,
    base_price_cents=1000,
    starts_at_x=DEFAULT_STARTS_AT,
    starts_at_y="2026-06-12T20:00:00.000Z",
    seat_count=4,
    now=DEFAULT_NOW,
):
    """Two ON_SALE showtimes of the same film in two DIFFERENT auditoriums.

    Returns dict: film, distributor, auditorium_x, auditorium_y, showtime_x,
    showtime_y, seats_x, seats_y.
    """
    base = setup_base(now=now, seat_count=seat_count)
    auditorium_y = make_auditorium(name="Hall 2", seat_count=seat_count, turnaround_minutes=20)
    st_x = schedule_showtime(
        base["auditorium"]["id"], base["film"]["id"], starts_at=starts_at_x,
        pricing_profile="STANDARD", base_price_cents=base_price_cents,
    )
    st_y = schedule_showtime(
        auditorium_y["id"], base["film"]["id"], starts_at=starts_at_y,
        pricing_profile="STANDARD", base_price_cents=base_price_cents,
    )
    st_x_open = open_showtime(st_x["id"])
    st_y_open = open_showtime(st_y["id"])
    return {
        "distributor": base["distributor"],
        "film": base["film"],
        "auditorium_x": base["auditorium"],
        "auditorium_y": auditorium_y,
        "showtime_x": st_x_open,
        "showtime_y": st_y_open,
        "seats_x": get_seat_ids(st_x["id"]),
        "seats_y": get_seat_ids(st_y["id"]),
    }
