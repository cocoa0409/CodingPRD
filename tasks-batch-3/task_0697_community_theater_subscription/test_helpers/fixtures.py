"""Composite setup helpers for the Community Theater Subscription API.

Every test runs against a fresh, empty database (the harness restarts the
server before each test), so every helper builds its preconditions from
scratch using only PRD-declared endpoints. Helpers use get_success_data()
(lenient) internally so setup failures surface as clear "Setup failed" errors.

Identity threading: the Patron role is entity-backed; any ownership-gated call
uses make_patron_headers(patron_id) with the real Patron id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_patron_headers,
    make_artistic_director_headers,
)
from . import factories as f

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]
DIRECTOR = TEST_USERS["artistic_director_headers"]


# --------------------------------------------------------------------------
# Clock helper
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the server logical clock to the given instant (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier-1 primitives — single-step creators returning the resource data dict
# --------------------------------------------------------------------------
def create_season(**overrides) -> dict:
    return get_success_data(api_client.create_season(f.create_season_payload(**overrides), ADMIN))


def create_production(season_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_production(f.create_production_payload(season_id, **overrides), ADMIN)
    )


def announce_production(production_id) -> dict:
    return get_success_data(api_client.announce_production(production_id, ADMIN))


def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(f.create_venue_payload(**overrides), ADMIN))


def create_seat(venue_id, **overrides) -> dict:
    return get_success_data(api_client.create_seat(f.create_seat_payload(venue_id, **overrides), ADMIN))


def create_patron(email="patron@example.com", full_name="Test Patron") -> dict:
    return get_success_data(
        api_client.create_patron(f.create_patron_payload(email=email, full_name=full_name), ADMIN)
    )


def create_performance(production_id, venue_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_performance(
            f.create_performance_payload(production_id, venue_id, **overrides), ADMIN
        )
    )


# --------------------------------------------------------------------------
# Tier-2 / Tier-3 — performances driven to a given state
# --------------------------------------------------------------------------
def setup_announced_production(season_overrides=None, prod_overrides=None):
    """A season + an ANNOUNCED production. Returns (season, production)."""
    season = create_season(**(season_overrides or {}))
    production = create_production(season["id"], **(prod_overrides or {}))
    announce_production(production["id"])
    production = get_success_data(api_client.get_production(production["id"], ADMIN))
    return season, production


def setup_on_sale_performance(
    clock="2026-06-10T00:00:00Z",
    seats=None,
    demand_multiplier=1.0,
    will_call_cutoff_minutes=None,
    starts_at="2026-07-01T19:30:00Z",
    on_sale_at="2026-06-01T00:00:00Z",
    accessibility_offered=None,
    season_overrides=None,
):
    """Full chain to an ON_SALE performance.

    seats: list of dicts, each merged into a seat payload (price_tier, etc).
           Defaults to a single STANDARD seat.
    Returns dict with keys: season, production, venue, seats (list),
    performance, performance_version (current Performance.version).
    """
    if clock is not None:
        set_clock(clock)
    season = create_season(**(season_overrides or {}))
    prod_kwargs = {}
    if accessibility_offered is not None:
        prod_kwargs["accessibility_offered"] = accessibility_offered
    production = create_production(season["id"], **prod_kwargs)
    announce_production(production["id"])
    venue = create_venue()
    if seats is None:
        seats = [{"price_tier": "STANDARD"}]
    seat_objs = []
    for i, seat_spec in enumerate(seats):
        spec = {"row_label": "A", "seat_number": i + 1}
        spec.update(seat_spec)
        seat_objs.append(create_seat(venue["id"], **spec))

    perf_kwargs = {"demand_multiplier": demand_multiplier,
                   "starts_at": starts_at, "on_sale_at": on_sale_at}
    if will_call_cutoff_minutes is not None:
        perf_kwargs["will_call_cutoff_minutes"] = will_call_cutoff_minutes
    performance = create_performance(production["id"], venue["id"], **perf_kwargs)
    get_success_data(api_client.schedule_performance(performance["id"], ADMIN))
    opened = get_success_data(api_client.open_sales(performance["id"], AGENT))
    return {
        "season": season,
        "production": production,
        "venue": venue,
        "seats": seat_objs,
        "performance": opened,
        "performance_version": opened["version"],
    }


def hold_single_ticket(performance_id, seat_id, patron_id, expected_performance_version,
                       headers=None, **overrides) -> dict:
    """Hold one SINGLE-origin ticket; returns the ticket data dict."""
    payload = f.create_ticket_payload(
        performance_id, seat_id, patron_id, "SINGLE", expected_performance_version, **overrides
    )
    hdrs = headers if headers is not None else make_patron_headers(patron_id)
    return get_success_data(api_client.create_ticket(payload, hdrs))


def get_performance_version(performance_id, headers=None) -> int:
    data = get_success_data(api_client.get_performance(performance_id, headers or AGENT))
    return data["version"]


def setup_paid_single_ticket(price_tier="STANDARD", demand_multiplier=1.0,
                             will_call_cutoff_minutes=None,
                             starts_at="2026-07-01T19:30:00Z",
                             clock="2026-06-10T00:00:00Z"):
    """An ON_SALE performance with one PAID/ISSUED single ticket.

    Returns dict adding: patron, ticket (after pay).
    """
    ctx = setup_on_sale_performance(
        clock=clock, seats=[{"price_tier": price_tier}],
        demand_multiplier=demand_multiplier,
        will_call_cutoff_minutes=will_call_cutoff_minutes,
        starts_at=starts_at,
    )
    patron = create_patron(email="paid@example.com", full_name="Paid Patron")
    seat = ctx["seats"][0]
    ticket = hold_single_ticket(
        ctx["performance"]["id"], seat["id"], patron["id"], ctx["performance_version"],
    )
    paid = get_success_data(
        api_client.pay_ticket(ticket["id"], make_patron_headers(patron["id"]))
    )
    ctx["patron"] = patron
    ctx["ticket"] = paid
    return ctx


# --------------------------------------------------------------------------
# Tier-3 — subscriptions driven to ACTIVE / priced
# --------------------------------------------------------------------------
def setup_active_subscription(
    seat_tiers=("STANDARD",),
    base_subscription_fee_cents=20000,
    loyalty_renewal_discount_pct=None,
    clock="2026-04-01T00:00:00Z",
    patron_email="sub@example.com",
):
    """A season + venue + patron + a DRAFT subscription holding the given
    seat tiers, then activated (priced). Returns dict with keys: season,
    venue, seats (list), patron, subscription (ACTIVE), subscription_seats
    (list), season_version (post-activation).
    """
    if clock is not None:
        set_clock(clock)
    season_kwargs = {"base_subscription_fee_cents": base_subscription_fee_cents}
    if loyalty_renewal_discount_pct is not None:
        season_kwargs["loyalty_renewal_discount_pct"] = loyalty_renewal_discount_pct
    season = create_season(**season_kwargs)
    season_version = season["version"]
    venue = create_venue()
    seats = [create_seat(venue["id"], row_label="A", seat_number=i + 1, price_tier=t)
             for i, t in enumerate(seat_tiers)]
    patron = create_patron(email=patron_email, full_name="Sub Patron")
    ph = make_patron_headers(patron["id"])
    subscription = get_success_data(
        api_client.create_subscription(f.create_subscription_payload(season["id"], patron["id"]), ph)
    )
    sub_seats = []
    for seat in seats:
        ss = get_success_data(
            api_client.create_subscription_seat(
                f.create_subscription_seat_payload(subscription["id"], seat["id"]), ph
            )
        )
        sub_seats.append(ss)
    activated = get_success_data(
        api_client.activate_subscription(
            subscription["id"], {"expected_season_version": season_version}, AGENT
        )
    )
    return {
        "season": season,
        "venue": venue,
        "seats": seats,
        "patron": patron,
        "subscription": activated,
        "subscription_seats": sub_seats,
        "season_version": season_version + 1,
    }


def setup_draft_subscription_with_seats(
    seat_tiers=("STANDARD",),
    base_subscription_fee_cents=20000,
    loyalty_renewal_discount_pct=None,
    clock="2026-04-01T00:00:00Z",
    patron_email="draftsub@example.com",
):
    """A DRAFT subscription with the given ASSIGNED seat tiers, NOT yet
    activated. Returns dict: season, season_version, venue, seats, patron,
    subscription (DRAFT), subscription_seats.
    """
    if clock is not None:
        set_clock(clock)
    season_kwargs = {"base_subscription_fee_cents": base_subscription_fee_cents}
    if loyalty_renewal_discount_pct is not None:
        season_kwargs["loyalty_renewal_discount_pct"] = loyalty_renewal_discount_pct
    season = create_season(**season_kwargs)
    venue = create_venue()
    seats = [create_seat(venue["id"], row_label="A", seat_number=i + 1, price_tier=t)
             for i, t in enumerate(seat_tiers)]
    patron = create_patron(email=patron_email, full_name="Draft Sub Patron")
    ph = make_patron_headers(patron["id"])
    subscription = get_success_data(
        api_client.create_subscription(f.create_subscription_payload(season["id"], patron["id"]), ph)
    )
    sub_seats = []
    for seat in seats:
        ss = get_success_data(
            api_client.create_subscription_seat(
                f.create_subscription_seat_payload(subscription["id"], seat["id"]), ph
            )
        )
        sub_seats.append(ss)
    return {
        "season": season,
        "season_version": season["version"],
        "venue": venue,
        "seats": seats,
        "patron": patron,
        "subscription": subscription,
        "subscription_seats": sub_seats,
    }


# --------------------------------------------------------------------------
# Tier-3 — donations / donor levels
# --------------------------------------------------------------------------
def create_patron_at_donor_level(amount_cents, email="donor@example.com"):
    """Register a patron and fulfill one donation of amount_cents so the
    patron's donor_level reflects that lifetime total. Returns the patron
    data dict re-read after fulfillment.
    """
    patron = create_patron(email=email, full_name="Donor Patron")
    donation = get_success_data(
        api_client.create_donation(f.create_donation_payload(patron["id"], amount_cents), AGENT)
    )
    get_success_data(api_client.fulfill_donation(donation["id"], AGENT))
    return get_success_data(api_client.get_patron(patron["id"], ADMIN))


# --------------------------------------------------------------------------
# Tier-3 — auditions
# --------------------------------------------------------------------------
def create_audition(production_id, applicant_name="Applicant", role_applied_for="Lead"):
    return get_success_data(
        api_client.create_audition(
            f.create_audition_payload(production_id, applicant_name, role_applied_for), DIRECTOR
        )
    )
