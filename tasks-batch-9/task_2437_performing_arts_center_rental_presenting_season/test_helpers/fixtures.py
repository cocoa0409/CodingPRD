"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only the endpoints the PRD declares. Setup
calls use the lenient success validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure.

The helpers are layered:
  * thin registration wrappers (a single POST),
  * workflow steps (one action endpoint each),
  * composite scenarios that walk a booking to a late lifecycle stage.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_CLOCK_UTC
from .factories import (
    assess_risk_payload,
    cancel_engagement_payload,
    counter_fee_negotiation_payload,
    create_artist_payload,
    create_education_program_payload,
    create_equipment_item_payload,
    create_equipment_line_payload,
    create_labor_call_payload,
    create_performance_space_payload,
    create_presented_engagement_payload,
    create_price_tier_payload,
    create_rental_client_payload,
    create_rental_engagement_payload,
    create_reserve_ledger_entry_payload,
    create_subscription_package_payload,
    create_ticket_sale_payload,
    create_union_department_payload,
    open_fee_negotiation_payload,
    reconcile_expenses_payload,
    record_deposit_payload,
    report_labor_hours_payload,
    revise_fee_offer_payload,
    sell_subscription_orders_payload,
    submit_tech_rider_payload,
)
from .test_users import (
    TEST_USERS,
    make_artist_representative_headers,
    make_finance_controller_headers,
    make_rental_client_contact_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ─── The logical season clock ─────────────────────────

def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Reposition the logical clock. Returns the clock response payload."""
    return get_success_data(
        api_client.set_logical_clock(to_iso8601, headers or ADMIN))


def reset_clock_to_season_default(headers: Optional[dict] = None) -> dict:
    """Reposition the clock back onto the instant it reads before any client
    moves it."""
    return set_clock(DEFAULT_LOGICAL_CLOCK_UTC, headers)


# ─── Season infrastructure ────────────────────────────

def register_hall(headers: Optional[dict] = None, **overrides) -> dict:
    """Register a hall. Defaults describe a 1,200-seat house with a 120-minute
    changeover buffer, a 5,000 kg grid, 400 A of house power and 4 DMX
    universes."""
    return get_success_data(api_client.create_performance_space(
        create_performance_space_payload(**overrides), headers or ADMIN))


def register_artist(headers: Optional[dict] = None, **overrides) -> dict:
    """Register a touring artist with a 200,000-cent guarantee floor, a 0.8
    historical sell-through and a September-to-December routing window."""
    return get_success_data(api_client.create_artist(
        create_artist_payload(**overrides), headers or DIRECTOR))


def register_rental_client(headers: Optional[dict] = None, **overrides) -> dict:
    """Register a rental client; credit grade A and not a nonprofit by default."""
    return get_success_data(api_client.create_rental_client(
        create_rental_client_payload(**overrides), headers or RENTAL_MANAGER))


def register_union_department(headers: Optional[dict] = None, **overrides) -> dict:
    """Register one union rate card; STAGEHANDS at 5,000 cents an hour with a
    roster of 10 by default."""
    return get_success_data(api_client.create_union_department(
        create_union_department_payload(**overrides), headers or ADMIN))


def register_equipment_item(headers: Optional[dict] = None, **overrides) -> dict:
    """Register one rental inventory item."""
    return get_success_data(api_client.create_equipment_item(
        create_equipment_item_payload(**overrides), headers or ADMIN))


def append_reserve_entry(entry_type: str, amount_cents: int,
                         memo: str = "Season reserve movement",
                         engagement_id: Optional[str] = None,
                         headers: Optional[dict] = None) -> dict:
    """Append a center-level reserve movement."""
    return get_success_data(api_client.create_reserve_ledger_entry(
        create_reserve_ledger_entry_payload(entry_type, amount_cents, memo,
                                            engagement_id),
        headers or ADMIN))


def open_reserve_balance(amount_cents: int,
                         memo: str = "Season opening balance",
                         headers: Optional[dict] = None) -> dict:
    """Seed the capital reserve with an opening balance."""
    return append_reserve_entry("OPENING_BALANCE", amount_cents, memo,
                                headers=headers)


def list_reserve_entries(headers: Optional[dict] = None,
                         params: Optional[dict] = None) -> list:
    """Read the whole ledger in created_at ascending order."""
    body = get_success_data(api_client.list_reserve_ledger_entries(
        headers or ADMIN, params or {"limit": 100}))
    return body


# ─── Booking ──────────────────────────────────────────

def book_presented_engagement(space_id: str, artist_id: str,
                              headers: Optional[dict] = None,
                              **overrides) -> dict:
    """Book a presented engagement (defaults to a single October 11 2026
    performance)."""
    return get_success_data(api_client.create_engagement(
        create_presented_engagement_payload(space_id, artist_id, **overrides),
        headers or DIRECTOR))


def book_rental_engagement(space_id: str, rental_client_id: str,
                           headers: Optional[dict] = None, **overrides) -> dict:
    """Book a rental engagement (defaults to a single October 2 2026 event)."""
    return get_success_data(api_client.create_engagement(
        create_rental_engagement_payload(space_id, rental_client_id, **overrides),
        headers or RENTAL_MANAGER))


def read_engagement(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id,
                                                      headers or DIRECTOR))


def engagement_version(engagement_id: str, headers: Optional[dict] = None) -> int:
    """Read the engagement's live version, which the two version-pinned
    operations must be given."""
    return read_engagement(engagement_id, headers)["version"]


def setup_presented_booking(hall_overrides: Optional[dict] = None,
                            artist_overrides: Optional[dict] = None,
                            engagement_overrides: Optional[dict] = None) -> dict:
    """Hall + artist + one DRAFT presented engagement.

    Returns {"space", "artist", "engagement"}.
    """
    space = register_hall(**(hall_overrides or {}))
    artist = register_artist(**(artist_overrides or {}))
    engagement = book_presented_engagement(space["id"], artist["id"],
                                           **(engagement_overrides or {}))
    return {"space": space, "artist": artist, "engagement": engagement}


def setup_rental_booking(hall_overrides: Optional[dict] = None,
                         client_overrides: Optional[dict] = None,
                         engagement_overrides: Optional[dict] = None) -> dict:
    """Hall + rental client + one DRAFT rental engagement.

    Returns {"space", "client", "engagement"}.
    """
    space = register_hall(**(hall_overrides or {}))
    client = register_rental_client(**(client_overrides or {}))
    engagement = book_rental_engagement(space["id"], client["id"],
                                        **(engagement_overrides or {}))
    return {"space": space, "client": client, "engagement": engagement}


def cancel(engagement_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(api_client.cancel_engagement(
        engagement_id, cancel_engagement_payload(**overrides),
        headers or RENTAL_MANAGER))


# ─── Fee negotiation ──────────────────────────────────

def open_negotiation_round(engagement_id: str, offered_fee_cents: int,
                           offered_artist_share_pct: float,
                           expected_engagement_version: Optional[int] = None,
                           headers: Optional[dict] = None) -> dict:
    """Open a round; the version pin defaults to the engagement's live version."""
    if expected_engagement_version is None:
        expected_engagement_version = engagement_version(engagement_id)
    return get_success_data(api_client.open_fee_negotiation(
        engagement_id,
        open_fee_negotiation_payload(offered_fee_cents, offered_artist_share_pct,
                                     expected_engagement_version),
        headers or DIRECTOR))


def counter_round(negotiation_id: str, artist_id: str, counter_fee_cents: int,
                  counter_artist_share_pct: float) -> dict:
    """Counter the standing offer as the artist's own representative."""
    return get_success_data(api_client.counter_fee_negotiation(
        negotiation_id,
        counter_fee_negotiation_payload(counter_fee_cents,
                                        counter_artist_share_pct),
        make_artist_representative_headers(artist_id)))


def revise_round(negotiation_id: str, offered_fee_cents: int,
                 offered_artist_share_pct: float,
                 headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.revise_fee_offer(
        negotiation_id,
        revise_fee_offer_payload(offered_fee_cents, offered_artist_share_pct),
        headers or DIRECTOR))


def accept_round_as_artist(negotiation_id: str, artist_id: str) -> dict:
    """A round sitting at OFFERED is accepted by the artist representative."""
    return get_success_data(api_client.accept_fee_negotiation(
        negotiation_id, make_artist_representative_headers(artist_id)))


def accept_round_as_director(negotiation_id: str,
                             headers: Optional[dict] = None) -> dict:
    """A round sitting at COUNTERED is accepted by the programming director."""
    return get_success_data(api_client.accept_fee_negotiation(
        negotiation_id, headers or DIRECTOR))


def negotiate_and_accept_fee(engagement_id: str, artist_id: str,
                             offered_fee_cents: int,
                             offered_artist_share_pct: float) -> dict:
    """Open one round and have the agency accept the standing offer.

    Returns the ACCEPTED negotiation round.
    """
    round_data = open_negotiation_round(engagement_id, offered_fee_cents,
                                        offered_artist_share_pct)
    return accept_round_as_artist(round_data["id"], artist_id)


# ─── Technical rider and additional equipment ─────────

def submit_rider(engagement_id: str, owner_headers: dict, **overrides) -> dict:
    """Submit the rider. ``owner_headers`` must belong to the engagement's own
    counterparty: the artist representative of a presented engagement or the
    client contact of a rental."""
    return get_success_data(api_client.submit_tech_rider(
        engagement_id, submit_tech_rider_payload(**overrides), owner_headers))


def review_rider(rider_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.review_tech_rider(
        rider_id, headers or TECH_DIRECTOR))


def reserve_equipment_line(rider_id: str, equipment_item_id: str,
                           headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(api_client.create_equipment_line(
        rider_id, create_equipment_line_payload(equipment_item_id, **overrides),
        headers or TECH_DIRECTOR))


def clear_rider(rider_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.clear_tech_rider(
        rider_id, headers or TECH_DIRECTOR))


def submit_review_and_clear_rider(engagement_id: str, owner_headers: dict,
                                  **rider_overrides) -> dict:
    """Submit a rider the hall can already serve, review it to CAPABLE and
    clear it. Returns the CLEARED rider."""
    rider = submit_rider(engagement_id, owner_headers, **rider_overrides)
    review_rider(rider["id"])
    return clear_rider(rider["id"])


def clear_presented_rider(engagement_id: str, artist_id: str,
                          **rider_overrides) -> dict:
    """The presented-side rider is filed by the artist's representative."""
    return submit_review_and_clear_rider(
        engagement_id, make_artist_representative_headers(artist_id),
        **rider_overrides)


def clear_rental_rider(engagement_id: str, rental_client_id: str,
                       **rider_overrides) -> dict:
    """The rental-side rider is filed by the client's contact."""
    return submit_review_and_clear_rider(
        engagement_id, make_rental_client_contact_headers(rental_client_id),
        **rider_overrides)


# ─── Union labor ──────────────────────────────────────

def call_crew(engagement_id: str, union_department_id: str,
              headers: Optional[dict] = None, **overrides) -> dict:
    """Call union crew for a window inside the engagement's occupancy."""
    return get_success_data(api_client.create_labor_call(
        engagement_id, create_labor_call_payload(union_department_id, **overrides),
        headers or TECH_DIRECTOR))


def report_hours(labor_call_id: str, actual_hours: float,
                 meal_break_taken: bool, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.report_labor_hours(
        labor_call_id, report_labor_hours_payload(actual_hours, meal_break_taken),
        headers or TECH_DIRECTOR))


# ─── Risk, deposits and confirmation ──────────────────

def assess_risk(engagement_id: str,
                expected_engagement_version: Optional[int] = None,
                headers: Optional[dict] = None, **overrides) -> dict:
    """Run the risk assessment; the version pin defaults to the live version."""
    if expected_engagement_version is None:
        expected_engagement_version = engagement_version(engagement_id)
    return get_success_data(api_client.assess_risk(
        engagement_id,
        assess_risk_payload(expected_engagement_version, **overrides),
        headers or FINANCE))


def record_deposit(engagement_id: str, amount_cents: int,
                   headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.record_deposit(
        engagement_id, record_deposit_payload(amount_cents),
        headers or RENTAL_MANAGER))


def confirm(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.confirm_engagement(
        engagement_id, headers or DIRECTOR))


# ─── Ticketing ────────────────────────────────────────

def add_price_tier(engagement_id: str, headers: Optional[dict] = None,
                   **overrides) -> dict:
    return get_success_data(api_client.create_price_tier(
        engagement_id, create_price_tier_payload(**overrides),
        headers or BOX_OFFICE))


def read_price_tier(tier_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_price_tier(tier_id,
                                                      headers or BOX_OFFICE))


def put_on_sale(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.put_engagement_on_sale(
        engagement_id, headers or BOX_OFFICE))


def sell_tickets(tier_id: str, qty: int = 1, channel: str = "WEB",
                 headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.create_ticket_sale(
        tier_id, create_ticket_sale_payload(qty, channel), headers or BOX_OFFICE))


def sell_tickets_until_sold_qty(tier_id: str, target_sold_qty: int,
                                chunk: int = 1) -> dict:
    """Drive a tier's sold_qty up to an exact figure so a sell-through band
    boundary can be hit by the next sale. Returns the tier as it then stands."""
    tier = read_price_tier(tier_id)
    while tier["sold_qty"] < target_sold_qty:
        remaining = target_sold_qty - tier["sold_qty"]
        sell_tickets(tier_id, min(chunk, remaining))
        tier = read_price_tier(tier_id)
    return tier


def create_subscription_package(included_engagement_ids: list,
                                headers: Optional[dict] = None,
                                **overrides) -> dict:
    return get_success_data(api_client.create_subscription_package(
        create_subscription_package_payload(included_engagement_ids, **overrides),
        headers or BOX_OFFICE))


def sell_subscription_orders(package_id: str, order_qty: int = 1,
                             headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.sell_subscription_orders(
        package_id, sell_subscription_orders_payload(order_qty),
        headers or BOX_OFFICE))


def read_box_office_statement(engagement_id: str,
                              headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_box_office_statement(
        engagement_id, headers or BOX_OFFICE))


# ─── Education programs ───────────────────────────────

def attach_education_program(engagement_id: str, headers: Optional[dict] = None,
                             **overrides) -> dict:
    return get_success_data(api_client.create_education_program(
        engagement_id, create_education_program_payload(**overrides),
        headers or DIRECTOR))


# ─── Settlement ───────────────────────────────────────

def open_settlement(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.open_settlement(engagement_id,
                                                       headers or FINANCE))


def reconcile_expenses(settlement_id: str, actual_marketing_cents: int = 0,
                       headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.reconcile_settlement_expenses(
        settlement_id, reconcile_expenses_payload(actual_marketing_cents),
        headers or FINANCE))


def finalize_settlement(settlement_id: str,
                        headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.finalize_settlement(
        settlement_id, headers or FINANCE))


def finalize_settlement_as(settlement_id: str, user_id: str) -> dict:
    """Finalize as a named finance controller, so a test can keep the
    finalizing identity distinct from the one that accepted the fee."""
    return get_success_data(api_client.finalize_settlement(
        settlement_id, make_finance_controller_headers(user_id)))


# ─── Composite scenarios ──────────────────────────────

def setup_presented_engagement_ready_to_confirm(
    hall_overrides: Optional[dict] = None,
    artist_overrides: Optional[dict] = None,
    engagement_overrides: Optional[dict] = None,
    tier_overrides: Optional[dict] = None,
    offered_fee_cents: int = 200_000,
    offered_artist_share_pct: float = 0.10,
    rider_overrides: Optional[dict] = None,
) -> dict:
    """Walk a presented booking up to the instant before confirmation.

    Hall + artist + DRAFT engagement + one ACTIVE price tier + an ACCEPTED
    negotiation round + a CLEARED technical rider + a risk assessment. With the
    defaults the assessment lands on a LOW tier, so the clearance dimension
    reads CLEARED and confirmation's six preconditions all hold.

    Returns {"space", "artist", "engagement", "tier", "negotiation", "rider"}.
    """
    base = setup_presented_booking(hall_overrides, artist_overrides,
                                   engagement_overrides)
    engagement_id = base["engagement"]["id"]
    tier_defaults = {
        "tier_name": "ORCH",
        "seats_allocated": 1_000,
        "base_price_cents": 20_000,
        "price_ceiling_cents": 30_000,
        "dynamic_pricing_enabled": False,
        "subscription_eligible": True,
    }
    tier_defaults.update(tier_overrides or {})
    tier = add_price_tier(engagement_id, **tier_defaults)
    negotiation = negotiate_and_accept_fee(engagement_id, base["artist"]["id"],
                                           offered_fee_cents,
                                           offered_artist_share_pct)
    rider = clear_presented_rider(engagement_id, base["artist"]["id"],
                                  **(rider_overrides or {}))
    engagement = assess_risk(engagement_id)
    return {
        "space": base["space"],
        "artist": base["artist"],
        "engagement": engagement,
        "tier": tier,
        "negotiation": negotiation,
        "rider": rider,
    }


def setup_confirmed_presented_engagement(**kwargs) -> dict:
    """As ``setup_presented_engagement_ready_to_confirm`` but CONFIRMED."""
    scenario = setup_presented_engagement_ready_to_confirm(**kwargs)
    scenario["engagement"] = confirm(scenario["engagement"]["id"])
    return scenario


def setup_presented_engagement_on_sale(**kwargs) -> dict:
    """A CONFIRMED presented engagement whose box office is ON_SALE."""
    scenario = setup_confirmed_presented_engagement(**kwargs)
    scenario["engagement"] = put_on_sale(scenario["engagement"]["id"])
    scenario["tier"] = read_price_tier(scenario["tier"]["id"])
    return scenario


def setup_rental_engagement_ready_to_confirm(
    hall_overrides: Optional[dict] = None,
    client_overrides: Optional[dict] = None,
    engagement_overrides: Optional[dict] = None,
    rider_overrides: Optional[dict] = None,
    pay_deposit: bool = True,
) -> dict:
    """Walk a rental booking up to the instant before confirmation.

    Hall + client + DRAFT rental engagement + a CLEARED rider + a risk
    assessment, and (by default) a deposit that covers the requirement exactly.

    Returns {"space", "client", "engagement", "rider"}.
    """
    base = setup_rental_booking(hall_overrides, client_overrides,
                                engagement_overrides)
    engagement_id = base["engagement"]["id"]
    rider = clear_rental_rider(engagement_id, base["client"]["id"],
                               **(rider_overrides or {}))
    engagement = assess_risk(engagement_id)
    if pay_deposit:
        outstanding = (engagement["deposit_required_cents"]
                       - engagement["deposit_paid_cents"])
        if outstanding > 0:
            engagement = record_deposit(engagement_id, outstanding)
    return {
        "space": base["space"],
        "client": base["client"],
        "engagement": engagement,
        "rider": rider,
    }


def setup_confirmed_rental_engagement(**kwargs) -> dict:
    """As ``setup_rental_engagement_ready_to_confirm`` but CONFIRMED."""
    scenario = setup_rental_engagement_ready_to_confirm(**kwargs)
    scenario["engagement"] = confirm(scenario["engagement"]["id"],
                                     RENTAL_MANAGER)
    return scenario


def setup_performed_presented_engagement(clock_after_curtain_down: str =
                                         "2026-10-12T00:00:00Z", **kwargs) -> dict:
    """A presented engagement carried to PERFORMED with a DRAFT settlement.

    The logical clock is moved past the engagement's ``performance_end_utc``
    first, because opening the settlement is what marks the engagement as
    performed.

    Adds {"settlement"} to the on-sale scenario mapping.
    """
    scenario = setup_presented_engagement_on_sale(**kwargs)
    set_clock(clock_after_curtain_down)
    scenario["settlement"] = open_settlement(scenario["engagement"]["id"])
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_reconciled_presented_settlement(actual_marketing_cents: int = 0,
                                          **kwargs) -> dict:
    """A presented engagement whose settlement reads EXPENSES_RECONCILED."""
    scenario = setup_performed_presented_engagement(**kwargs)
    scenario["settlement"] = reconcile_expenses(scenario["settlement"]["id"],
                                                actual_marketing_cents)
    return scenario


def setup_performed_rental_engagement(clock_after_curtain_down: str =
                                      "2026-10-03T00:00:00Z", **kwargs) -> dict:
    """A rental engagement carried to PERFORMED with a DRAFT settlement."""
    scenario = setup_confirmed_rental_engagement(**kwargs)
    set_clock(clock_after_curtain_down)
    scenario["settlement"] = open_settlement(scenario["engagement"]["id"])
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_reconciled_rental_settlement(actual_marketing_cents: int = 0,
                                       **kwargs) -> dict:
    """A rental engagement whose settlement reads EXPENSES_RECONCILED."""
    scenario = setup_performed_rental_engagement(**kwargs)
    scenario["settlement"] = reconcile_expenses(scenario["settlement"]["id"],
                                                actual_marketing_cents)
    return scenario


def setup_two_presented_engagements_on_sale(
    tier_name: str = "ORCH",
    first_tier_overrides: Optional[dict] = None,
    second_tier_overrides: Optional[dict] = None,
) -> dict:
    """Two presented engagements in the same hall, both ON_SALE, each carrying
    a subscription-eligible tier of the same name — the shape a season
    subscription package spans.

    The second booking is placed far enough from the first that neither the
    hall's changeover buffer nor the artist's routing minimum is disturbed;
    each engagement uses its own artist.

    Returns {"space", "first", "second"} where each side is itself a mapping
    with "artist", "engagement" and "tier".
    """
    space = register_hall()
    first_artist = register_artist(legal_name="Cadence Quartet")
    second_artist = register_artist(legal_name="Harbour Winds")
    first_tier_defaults = {
        "tier_name": tier_name,
        "seats_allocated": 100,
        "base_price_cents": 7_000,
        "price_ceiling_cents": 10_000,
        "dynamic_pricing_enabled": False,
        "subscription_eligible": True,
    }
    first_tier_defaults.update(first_tier_overrides or {})
    second_tier_defaults = {
        "tier_name": tier_name,
        "seats_allocated": 200,
        "base_price_cents": 12_000,
        "price_ceiling_cents": 20_000,
        "dynamic_pricing_enabled": False,
        "subscription_eligible": True,
    }
    second_tier_defaults.update(second_tier_overrides or {})

    first = _walk_presented_engagement_to_on_sale(
        space["id"], first_artist["id"], first_tier_defaults,
        {
            "title": "Cadence Quartet in Recital",
            "load_in_start_utc": "2026-10-10T08:00:00Z",
            "performance_start_utc": "2026-10-11T19:00:00Z",
            "performance_end_utc": "2026-10-11T22:00:00Z",
            "load_out_end_utc": "2026-10-12T02:00:00Z",
        })
    second = _walk_presented_engagement_to_on_sale(
        space["id"], second_artist["id"], second_tier_defaults,
        {
            "title": "Harbour Winds Season Opener",
            "load_in_start_utc": "2026-10-20T08:00:00Z",
            "performance_start_utc": "2026-10-21T19:00:00Z",
            "performance_end_utc": "2026-10-21T22:00:00Z",
            "load_out_end_utc": "2026-10-22T02:00:00Z",
        })
    first["artist"] = first_artist
    second["artist"] = second_artist
    return {"space": space, "first": first, "second": second}


def _walk_presented_engagement_to_on_sale(space_id: str, artist_id: str,
                                          tier_payload: dict,
                                          engagement_overrides: dict) -> dict:
    """Book a presented engagement in an existing hall and carry it to ON_SALE.

    Returns {"engagement", "tier", "negotiation", "rider"}.
    """
    engagement = book_presented_engagement(space_id, artist_id,
                                           **engagement_overrides)
    tier = add_price_tier(engagement["id"], **tier_payload)
    negotiation = negotiate_and_accept_fee(engagement["id"], artist_id,
                                           200_000, 0.10)
    rider = clear_presented_rider(engagement["id"], artist_id)
    assess_risk(engagement["id"])
    confirm(engagement["id"])
    engagement = put_on_sale(engagement["id"])
    return {
        "engagement": engagement,
        "tier": read_price_tier(tier["id"]),
        "negotiation": negotiation,
        "rider": rider,
    }


def setup_rental_engagement_with_crew_and_equipment(
    hall_overrides: Optional[dict] = None,
    client_overrides: Optional[dict] = None,
    engagement_overrides: Optional[dict] = None,
    department_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
    call_overrides: Optional[dict] = None,
) -> dict:
    """A DRAFT rental engagement that already carries one ESTIMATED labor call
    and one registered inventory item, plus a rider parked at GAP_IDENTIFIED so
    equipment lines may be reserved against it.

    The rider requests more amperage than the hall supplies, which is what puts
    it on the gap branch of the review fork.

    Returns {"space", "client", "engagement", "department", "item", "call",
    "rider"}.
    """
    base = setup_rental_booking(hall_overrides, client_overrides,
                                engagement_overrides)
    engagement_id = base["engagement"]["id"]
    department = register_union_department(**(department_overrides or {}))
    item = register_equipment_item(**(item_overrides or {}))
    call = call_crew(engagement_id, department["id"], **(call_overrides or {}))
    rider_kwargs = {"requested_power_amps":
                    base["space"]["house_power_amps"] + 100}
    rider = submit_rider(engagement_id,
                         make_rental_client_contact_headers(base["client"]["id"]),
                         **rider_kwargs)
    rider = review_rider(rider["id"])
    return {
        "space": base["space"],
        "client": base["client"],
        "engagement": read_engagement(engagement_id),
        "department": department,
        "item": item,
        "call": call,
        "rider": rider,
    }


__all__ = [
    "ADMIN",
    "DIRECTOR",
    "RENTAL_MANAGER",
    "TECH_DIRECTOR",
    "BOX_OFFICE",
    "FINANCE",
    "set_clock",
    "reset_clock_to_season_default",
    "register_hall",
    "register_artist",
    "register_rental_client",
    "register_union_department",
    "register_equipment_item",
    "append_reserve_entry",
    "open_reserve_balance",
    "list_reserve_entries",
    "book_presented_engagement",
    "book_rental_engagement",
    "read_engagement",
    "engagement_version",
    "setup_presented_booking",
    "setup_rental_booking",
    "cancel",
    "open_negotiation_round",
    "counter_round",
    "revise_round",
    "accept_round_as_artist",
    "accept_round_as_director",
    "negotiate_and_accept_fee",
    "submit_rider",
    "review_rider",
    "reserve_equipment_line",
    "clear_rider",
    "submit_review_and_clear_rider",
    "clear_presented_rider",
    "clear_rental_rider",
    "call_crew",
    "report_hours",
    "assess_risk",
    "record_deposit",
    "confirm",
    "add_price_tier",
    "read_price_tier",
    "put_on_sale",
    "sell_tickets",
    "sell_tickets_until_sold_qty",
    "create_subscription_package",
    "sell_subscription_orders",
    "read_box_office_statement",
    "attach_education_program",
    "open_settlement",
    "reconcile_expenses",
    "finalize_settlement",
    "finalize_settlement_as",
    "setup_presented_engagement_ready_to_confirm",
    "setup_confirmed_presented_engagement",
    "setup_presented_engagement_on_sale",
    "setup_rental_engagement_ready_to_confirm",
    "setup_confirmed_rental_engagement",
    "setup_performed_presented_engagement",
    "setup_reconciled_presented_settlement",
    "setup_performed_rental_engagement",
    "setup_reconciled_rental_settlement",
    "setup_two_presented_engagements_on_sale",
    "setup_rental_engagement_with_crew_and_equipment",
]
