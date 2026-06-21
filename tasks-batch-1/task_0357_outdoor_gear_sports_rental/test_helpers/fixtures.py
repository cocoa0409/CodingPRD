"""Composite setup helpers for the Outdoor Gear Rental suite.

Every test starts against an empty database (the harness restarts the server
before each test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) so setup
failures surface as clear "Setup failed" errors.

Identity threading: a Renter is entity_backed:Customer. Any ownership-gated call
(confirm/cancel/addons/dispute on own reservation) uses make_renter_headers(
customer_id) with the real Customer.id — never the shared renter constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_gear_type_payload, create_rate_card_payload, create_season_window_payload,
    create_addon_payload, create_customer_payload, create_gear_unit_payload,
    create_reservation_payload, attach_addon_payload, checkout_payload, checkin_payload,
)
from .test_users import TEST_USERS, make_renter_headers
from .constants import TEST_DEFAULTS

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# --- Clock ---------------------------------------------------------------

def set_clock(iso8601: str):
    """Set the server's logical UTC clock (ShopAdmin only)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# --- Catalog primitives --------------------------------------------------

def create_gear_type(**overrides) -> dict:
    return get_success_data(api_client.create_gear_type(create_gear_type_payload(**overrides), ADMIN))


def create_rate_card(gear_type_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card(create_rate_card_payload(gear_type_id, **overrides), ADMIN))


def create_season_window(**overrides) -> dict:
    return get_success_data(
        api_client.create_season_window(create_season_window_payload(**overrides), ADMIN))


def create_addon(**overrides) -> dict:
    return get_success_data(api_client.create_addon(create_addon_payload(**overrides), ADMIN))


def create_gear_unit(gear_type_id, rate_card_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_gear_unit(create_gear_unit_payload(gear_type_id, rate_card_id, **overrides), ADMIN))


def create_customer(actor=AGENT, **overrides) -> dict:
    # Customer registration is a non-ownership call: a brand-new customer has no
    # prior id, so the 'RENTER' sentinel resolves to the shared Renter identity
    # (PRD: ShopAdmin, RentalAgent, Renter may all register a customer).
    if actor == "RENTER":
        actor = TEST_USERS["renter_headers"]
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), actor))


# --- Catalog bundle: type + rate card + unit + customer ------------------

def setup_catalog(category="KAYAK", gear_type_overrides=None, rate_card_overrides=None,
                  unit_overrides=None, customer_overrides=None, customer_actor=AGENT,
                  asset_tag="UNIT-1"):
    """Active gear type + rate card + one AVAILABLE unit + one customer.

    Returns dict with keys: gear_type, rate_card, gear_unit, customer.
    The unit's id and current version are convenient via gear_unit["id"]/["version"].
    """
    gt = create_gear_type(category=category, **(gear_type_overrides or {}))
    rc = create_rate_card(gt["id"], **(rate_card_overrides or {}))
    unit = create_gear_unit(gt["id"], rc["id"], asset_tag=asset_tag, **(unit_overrides or {}))
    cust = create_customer(actor=customer_actor, **(customer_overrides or {}))
    return {"gear_type": gt, "rate_card": rc, "gear_unit": unit, "customer": cust}


# --- Reservation lifecycle shortcuts -------------------------------------

def _renter_or_agent_headers(actor, customer_id):
    """If actor is the renter sentinel string 'RENTER', thread the real id."""
    if actor == "RENTER":
        return make_renter_headers(customer_id)
    return actor


def create_reservation(customer_id, gear_unit_id, expected_gear_unit_version,
                       pickup_at, due_at, actor=AGENT, **overrides) -> dict:
    """Create (quote) a reservation. actor may be AGENT, or 'RENTER' to act as the
    owning renter with threaded identity."""
    headers = _renter_or_agent_headers(actor, customer_id)
    payload = create_reservation_payload(
        customer_id, gear_unit_id, expected_gear_unit_version, pickup_at, due_at, **overrides)
    return get_success_data(api_client.create_reservation(payload, headers))


def setup_quoted_reservation(category="KAYAK", pickup_at="2026-04-01T08:00:00Z",
                             due_at="2026-04-01T10:00:00Z", clock=None, customer_actor=AGENT,
                             reservation_actor=AGENT, customer_overrides=None,
                             rate_card_overrides=None, gear_type_overrides=None,
                             reservation_overrides=None, asset_tag="UNIT-1"):
    """Full setup to a QUOTED reservation. Sets the clock, builds catalog + customer,
    then creates the reservation.

    Returns dict: gear_type, rate_card, gear_unit, customer, reservation.
    """
    if clock is not None:
        set_clock(clock)
    cat = setup_catalog(category=category, gear_type_overrides=gear_type_overrides,
                        rate_card_overrides=rate_card_overrides,
                        customer_overrides=customer_overrides, customer_actor=customer_actor,
                        asset_tag=asset_tag)
    res = create_reservation(cat["customer"]["id"], cat["gear_unit"]["id"],
                             cat["gear_unit"]["version"], pickup_at, due_at,
                             actor=reservation_actor, **(reservation_overrides or {}))
    cat["reservation"] = res
    return cat


def confirm_reservation(reservation_id, customer_id=None, actor=AGENT) -> dict:
    headers = _renter_or_agent_headers(actor, customer_id)
    return get_success_data(api_client.confirm_reservation(reservation_id, headers))


def checkout_reservation(reservation_id, condition_rating="GOOD") -> dict:
    return get_success_data(
        api_client.checkout_reservation(reservation_id, checkout_payload(condition_rating), AGENT))


def checkin_reservation(reservation_id, condition_rating="GOOD") -> dict:
    return get_success_data(
        api_client.checkin_reservation(reservation_id, checkin_payload(condition_rating), AGENT))


def settle_reservation(reservation_id) -> dict:
    return get_success_data(api_client.settle_reservation(reservation_id, AGENT))


def cancel_reservation(reservation_id, customer_id=None, actor=AGENT) -> dict:
    headers = _renter_or_agent_headers(actor, customer_id)
    return get_success_data(api_client.cancel_reservation(reservation_id, headers))


def setup_confirmed_reservation(category="KAYAK", pickup_at="2026-04-01T08:00:00Z",
                                due_at="2026-04-01T10:00:00Z", clock="2026-04-01T08:00:00Z",
                                customer_overrides=None, rate_card_overrides=None,
                                reservation_overrides=None, asset_tag="UNIT-1"):
    """Setup to CONFIRMED (deposit held). Returns the same dict plus reservation in
    CONFIRMED state."""
    s = setup_quoted_reservation(category=category, pickup_at=pickup_at, due_at=due_at,
                                 clock=clock, customer_overrides=customer_overrides,
                                 rate_card_overrides=rate_card_overrides,
                                 reservation_overrides=reservation_overrides, asset_tag=asset_tag)
    s["reservation"] = confirm_reservation(s["reservation"]["id"], actor=AGENT)
    return s


def setup_picked_up_reservation(category="KAYAK", pickup_at="2026-04-01T08:00:00Z",
                                due_at="2026-04-01T10:00:00Z", clock="2026-04-01T08:00:00Z",
                                checkout_rating="GOOD", customer_overrides=None,
                                rate_card_overrides=None, reservation_overrides=None,
                                asset_tag="UNIT-1"):
    """Setup to PICKED_UP (checked out). Returns dict with reservation in PICKED_UP."""
    s = setup_confirmed_reservation(category=category, pickup_at=pickup_at, due_at=due_at,
                                    clock=clock, customer_overrides=customer_overrides,
                                    rate_card_overrides=rate_card_overrides,
                                    reservation_overrides=reservation_overrides, asset_tag=asset_tag)
    s["reservation"] = checkout_reservation(s["reservation"]["id"], checkout_rating)
    return s


def setup_returned_reservation(category="KAYAK", pickup_at="2026-04-01T08:00:00Z",
                               due_at="2026-04-01T10:00:00Z", clock="2026-04-01T08:00:00Z",
                               return_clock="2026-04-01T09:30:00Z", checkout_rating="GOOD",
                               checkin_rating="GOOD", customer_overrides=None,
                               rate_card_overrides=None, reservation_overrides=None,
                               asset_tag="UNIT-1"):
    """Setup to RETURNED (checked in). The return_clock is set before check-in so
    late/final are computed against it. Returns dict with reservation in RETURNED."""
    s = setup_picked_up_reservation(category=category, pickup_at=pickup_at, due_at=due_at,
                                    clock=clock, checkout_rating=checkout_rating,
                                    customer_overrides=customer_overrides,
                                    rate_card_overrides=rate_card_overrides,
                                    reservation_overrides=reservation_overrides, asset_tag=asset_tag)
    if return_clock is not None:
        set_clock(return_clock)
    s["reservation"] = checkin_reservation(s["reservation"]["id"], checkin_rating)
    return s


# --- Damage assessment helpers -------------------------------------------

def get_assessment_for_reservation(reservation_id) -> dict:
    """Return the (sole) DamageAssessment for a reservation via list filter."""
    data, _ = _paginated(api_client.list_damage_assessments(AGENT, params={"reservation_id": reservation_id}))
    assert data, f"no damage assessment found for reservation {reservation_id}"
    return data[0]


def get_ledger_for_reservation(reservation_id) -> list:
    """Return all ledger entries for a reservation."""
    data, _ = _paginated(api_client.list_ledger_entries(AGENT, params={"reservation_id": reservation_id}))
    return data


def _paginated(response):
    """Lenient paginated extractor for use inside fixtures: returns (data, meta)."""
    body = response.json() if hasattr(response, "json") else response
    return body.get("data", []), body.get("meta", {})


def setup_disputed_assessment(category="SKI", clock="2026-05-07T08:00:00Z",
                              pickup_at="2026-05-07T08:00:00Z", due_at="2026-05-07T10:00:00Z",
                              return_clock="2026-05-07T09:30:00Z", checkin_rating="DAMAGED",
                              asset_tag="UNIT-DA"):
    """Setup a RETURNED reservation whose DamageAssessment the owning renter has moved
    to DISPUTED. Returns dict: gear_type, rate_card, gear_unit, customer, reservation,
    assessment (in DISPUTED).
    """
    s = setup_returned_reservation(category=category, clock=clock, pickup_at=pickup_at,
                                   due_at=due_at, return_clock=return_clock,
                                   checkin_rating=checkin_rating,
                                   reservation_overrides={"damage_waiver_opted": False},
                                   asset_tag=asset_tag)
    assessment = get_assessment_for_reservation(s["reservation"]["id"])
    cust_id = s["customer"]["id"]
    disputed = get_success_data(api_client.dispute_damage_assessment(
        assessment["id"], {"expected_damage_assessment_version": assessment["version"]},
        make_renter_headers(cust_id)))
    s["assessment"] = disputed
    return s


# --- Suspended-customer builder ------------------------------------------

def setup_suspended_customer(category="KAYAK", clock="2026-05-12T08:00:00Z",
                             asset_tag1="SUSP-1"):
    """Drive a customer to SUSPENDED standing by completing one rental that is LOST
    (posts an unsettled LOSS_FEE). Returns dict: gear_type, rate_card, customer,
    lost_unit, lost_reservation. The customer's standing is SUSPENDED after settle.
    """
    set_clock(clock)
    gt = create_gear_type(category=category)
    rc = create_rate_card(gt["id"])
    unit = create_gear_unit(gt["id"], rc["id"], asset_tag=asset_tag1)
    cust = create_customer(actor=AGENT, skill_level="EXPERT", email="susp@x.com")
    res = create_reservation(cust["id"], unit["id"], unit["version"],
                             clock, "2026-05-12T10:00:00Z", actor=AGENT,
                             damage_waiver_opted=False)
    confirm_reservation(res["id"], actor=AGENT)
    checkout_reservation(res["id"], "GOOD")
    set_clock("2026-05-12T09:30:00Z")
    checkin_reservation(res["id"], "LOST")
    settle_reservation(res["id"])
    return {"gear_type": gt, "rate_card": rc, "customer": cust,
            "lost_unit": unit, "lost_reservation": res}
