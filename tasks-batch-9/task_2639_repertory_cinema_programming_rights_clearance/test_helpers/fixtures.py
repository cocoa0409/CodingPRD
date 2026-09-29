"""Composite setup helpers.

Every helper builds its state from scratch through the service's own endpoints,
because each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    auto_schedule_payload,
    booking_payload,
    cinema_offer_payload,
    clearance_payload,
    clock_payload,
    counter_payload,
    dcp_asset_payload,
    distributor_payload,
    donation_payload,
    kdm_key_payload,
    member_payload,
    resolve_settlement_payload,
    settlement_payload,
    showtime_payload,
    special_event_payload,
    ticket_order_payload,
    title_payload,
    venue_payload,
)
from .test_users import TEST_USERS, make_member_headers

PROGRAMMER = TEST_USERS["programmer_headers"]
RIGHTS_MANAGER = TEST_USERS["rights_manager_headers"]
RIGHTS_MANAGER_TWO = TEST_USERS["rights_manager_two_headers"]
TECHNICAL_MANAGER = TEST_USERS["technical_manager_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
EXECUTIVE_DIRECTOR = TEST_USERS["executive_director_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

DEFAULT_SHOWTIME_START = "2026-08-14T12:00:00Z"
DCP_TRAFFIC_CHAIN = ["IN_TRANSIT", "RECEIVED", "INGESTING", "INGESTED", "RETURNED"]


# ─── The logical clock ────────────────────────────────────────────────────

def set_logical_clock(current_utc, headers=None):
    """Move the server's logical clock to an explicit instant."""
    return get_success_data(
        api_client.set_clock(
            clock_payload(current_utc), headers or EXECUTIVE_DIRECTOR
        )
    )


# ─── House, partners and catalogue ────────────────────────────────────────

def register_venue(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_venue(
            venue_payload(**overrides), headers or EXECUTIVE_DIRECTOR
        )
    )


def register_distributor(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_distributor(
            distributor_payload(**overrides), headers or PROGRAMMER
        )
    )


def catalogue_title(distributor_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_title(
            title_payload(distributor_id, **overrides), headers or PROGRAMMER
        )
    )


# ─── Engagements ──────────────────────────────────────────────────────────

def open_engagement(title_id, distributor_id, venue_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_booking(
            booking_payload(title_id, distributor_id, venue_id, **overrides),
            headers or PROGRAMMER,
        )
    )


def booking_version(booking_id, headers=None) -> int:
    return get_success_data(
        api_client.get_booking(booking_id, headers or PROGRAMMER)
    )["version"]


def read_booking(booking_id, headers=None) -> dict:
    return get_success_data(api_client.get_booking(booking_id, headers or PROGRAMMER))


def lodge_counter_round(booking_id, expected_booking_version=None, headers=None,
                       **overrides) -> dict:
    """Record the distributor's counter as the next negotiation round."""
    if expected_booking_version is None:
        expected_booking_version = booking_version(booking_id)
    return get_success_data(
        api_client.counter_booking(
            booking_id,
            counter_payload(expected_booking_version, **overrides),
            headers or PROGRAMMER,
        )
    )


def lodge_cinema_round(booking_id, headers=None, **overrides) -> dict:
    """Answer a distributor counter with a fresh cinema offer."""
    return get_success_data(
        api_client.offer_booking(
            booking_id, cinema_offer_payload(**overrides), headers or PROGRAMMER
        )
    )


def confirm_engagement(booking_id, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_booking(booking_id, headers or EXECUTIVE_DIRECTOR)
    )


def close_engagement(booking_id, headers=None) -> dict:
    return get_success_data(
        api_client.close_booking(booking_id, headers or EXECUTIVE_DIRECTOR)
    )


def withdraw_engagement(booking_id, cancel_reason="DISTRIBUTOR_PULLED",
                        headers=None) -> dict:
    return get_success_data(
        api_client.withdraw_booking(
            booking_id, {"cancel_reason": cancel_reason},
            headers or EXECUTIVE_DIRECTOR,
        )
    )


# ─── Rights clearances ────────────────────────────────────────────────────

def lodge_licence(title_id, booking_id, headers=None, **overrides) -> dict:
    """Lodge a licence; it lands directly in SUBMITTED."""
    return get_success_data(
        api_client.create_clearance(
            clearance_payload(title_id, booking_id, **overrides),
            headers or RIGHTS_MANAGER,
        )
    )


def clear_licence(clearance_id, headers=None) -> dict:
    """Clear a licence as a second operator, satisfying segregation of duties."""
    return get_success_data(
        api_client.clear_clearance(clearance_id, headers or RIGHTS_MANAGER_TWO)
    )


def request_licence_changes(clearance_id, change_request_note="AMEND TERRITORY",
                            headers=None) -> dict:
    return get_success_data(
        api_client.request_clearance_changes(
            clearance_id, {"change_request_note": change_request_note},
            headers or RIGHTS_MANAGER,
        )
    )


def relodge_licence(clearance_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_clearance(clearance_id, headers or RIGHTS_MANAGER)
    )


def revoke_licence(clearance_id, revoked_reason="LICENSOR_WITHDREW",
                   headers=None) -> dict:
    return get_success_data(
        api_client.revoke_clearance(
            clearance_id, {"revoked_reason": revoked_reason},
            headers or RIGHTS_MANAGER,
        )
    )


def clearance_version(clearance_id, headers=None) -> int:
    """Read the licence's live version, which every draw-down increments."""
    return get_success_data(
        api_client.get_clearance(clearance_id, headers or PROGRAMMER)
    )["version"]


def read_clearance(clearance_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_clearance(clearance_id, headers or PROGRAMMER)
    )


# ─── Print traffic, packages and keys ─────────────────────────────────────

def book_asset(title_id, distributor_id, venue_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_dcp_asset(
            dcp_asset_payload(title_id, distributor_id, venue_id, **overrides),
            headers or TECHNICAL_MANAGER,
        )
    )


def advance_asset(asset_id, new_status, headers=None, **extra) -> dict:
    payload = {"new_status": new_status}
    payload.update(extra)
    return get_success_data(
        api_client.traffic_update_dcp_asset(
            asset_id, payload, headers or TECHNICAL_MANAGER
        )
    )


def walk_asset_to(asset_id, target_status, headers=None) -> dict:
    """Advance print traffic one declared step at a time up to target_status."""
    asset = None
    for step in DCP_TRAFFIC_CHAIN:
        asset = advance_asset(asset_id, step, headers)
        if step == target_status:
            return asset
    return asset


def read_asset(asset_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_dcp_asset(asset_id, headers or TECHNICAL_MANAGER)
    )


def issue_kdm(asset_id, venue_id, valid_from, valid_until, headers=None,
              **overrides) -> dict:
    return get_success_data(
        api_client.create_kdm_key(
            kdm_key_payload(asset_id, venue_id, valid_from, valid_until, **overrides),
            headers or TECHNICAL_MANAGER,
        )
    )


def revoke_kdm(key_id, revoked_reason="KEY_COMPROMISED", headers=None) -> dict:
    return get_success_data(
        api_client.revoke_kdm_key(
            key_id, {"revoked_reason": revoked_reason},
            headers or TECHNICAL_MANAGER,
        )
    )


def read_kdm(key_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_kdm_key(key_id, headers or TECHNICAL_MANAGER)
    )


# ─── Screenings ───────────────────────────────────────────────────────────

def place_showtime(world, start_at=DEFAULT_SHOWTIME_START, headers=None,
                   **overrides) -> dict:
    """Schedule one screening by hand against the world's cleared licence.

    The licence version is re-read on every call because each draw-down
    increments it.
    """
    expected = overrides.pop(
        "expected_clearance_version", clearance_version(world["clearance"]["id"])
    )
    payload = showtime_payload(
        overrides.pop("venue_id", world["venue"]["id"]),
        overrides.pop("title_id", world["title"]["id"]),
        overrides.pop("booking_id", world["booking"]["id"]),
        overrides.pop("clearance_id", world["clearance"]["id"]),
        overrides.pop("dcp_asset_id", world["asset"]["id"]),
        start_at,
        expected,
        **overrides,
    )
    return get_success_data(
        api_client.create_showtime(payload, headers or PROGRAMMER)
    )


def auto_place_showtime(world, target_date, earliest_local_time="11:00",
                        latest_local_time="22:00", headers=None, **overrides) -> dict:
    """Ask the optimiser to place one screening on target_date."""
    expected = overrides.pop(
        "expected_clearance_version", clearance_version(world["clearance"]["id"])
    )
    payload = auto_schedule_payload(
        overrides.pop("venue_id", world["venue"]["id"]),
        overrides.pop("title_id", world["title"]["id"]),
        overrides.pop("booking_id", world["booking"]["id"]),
        overrides.pop("clearance_id", world["clearance"]["id"]),
        overrides.pop("dcp_asset_id", world["asset"]["id"]),
        target_date,
        earliest_local_time,
        latest_local_time,
        expected,
        **overrides,
    )
    return get_success_data(
        api_client.auto_schedule_showtime(payload, headers or PROGRAMMER)
    )


def read_showtime(showtime_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_showtime(showtime_id, headers or PROGRAMMER)
    )


def open_showtime_sales(showtime_id, headers=None) -> dict:
    return get_success_data(
        api_client.open_sales(showtime_id, headers or BOX_OFFICE)
    )


def close_showtime_sales(showtime_id, headers=None) -> dict:
    return get_success_data(
        api_client.close_sales(showtime_id, headers or BOX_OFFICE)
    )


def cancel_showtime(showtime_id, cancel_reason="PRINT_UNAVAILABLE",
                    headers=None) -> dict:
    return get_success_data(
        api_client.cancel_showtime(
            showtime_id, {"cancel_reason": cancel_reason}, headers or PROGRAMMER
        )
    )


def verify_booth_playback(showtime_id, result="PASS", headers=None) -> dict:
    return get_success_data(
        api_client.verify_playback(
            showtime_id, {"result": result}, headers or TECHNICAL_MANAGER
        )
    )


def mark_showtime_played(showtime_id, headers=None) -> dict:
    return get_success_data(
        api_client.complete_showtime(showtime_id, headers or BOX_OFFICE)
    )


# ─── Special events ───────────────────────────────────────────────────────

def plan_event(showtime_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_special_event(
            special_event_payload(showtime_id, **overrides), headers or PROGRAMMER
        )
    )


def confirm_event(event_id, displace_conflicts=False, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_special_event(
            event_id, {"displace_conflicts": displace_conflicts},
            headers or EXECUTIVE_DIRECTOR,
        )
    )


def cancel_event(event_id, cancel_reason="GUEST_CANCELLED", headers=None) -> dict:
    return get_success_data(
        api_client.cancel_special_event(
            event_id, {"cancel_reason": cancel_reason}, headers or PROGRAMMER
        )
    )


def read_event(event_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_special_event(event_id, headers or PROGRAMMER)
    )


# ─── Membership ───────────────────────────────────────────────────────────

def enrol_member(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_member(member_payload(**overrides), headers or BOX_OFFICE)
    )


def lodge_donation(member_id, amount_cents, received_at, headers=None) -> dict:
    return get_success_data(
        api_client.create_donation(
            member_id, donation_payload(amount_cents, received_at),
            headers or BOX_OFFICE,
        )
    )


def read_member(member_id, headers=None) -> dict:
    return get_success_data(api_client.get_member(member_id, headers or BOX_OFFICE))


def sweep_memberships(headers=None) -> dict:
    return get_success_data(
        api_client.run_membership_sweep(headers or EXECUTIVE_DIRECTOR)
    )


# ─── Box office ───────────────────────────────────────────────────────────

def sell_seats(showtime_id, quantity=1, headers=None, **overrides) -> dict:
    """Sell seats. Pass member_id plus member headers for a member purchase."""
    payload = ticket_order_payload(showtime_id, quantity, **overrides)
    caller = headers
    if caller is None:
        caller = (
            make_member_headers(payload["member_id"])
            if payload.get("member_id")
            else BOX_OFFICE
        )
    return get_success_data(api_client.create_ticket_order(payload, caller))


def pay_for_order(order_id, headers=None) -> dict:
    return get_success_data(
        api_client.pay_ticket_order(order_id, headers or BOX_OFFICE)
    )


def refund_order(order_id, refund_destination="CASH", headers=None) -> dict:
    return get_success_data(
        api_client.refund_ticket_order(
            order_id, {"refund_destination": refund_destination},
            headers or BOX_OFFICE,
        )
    )


def read_order(order_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_ticket_order(order_id, headers or BOX_OFFICE)
    )


# ─── Settlement ───────────────────────────────────────────────────────────

def draft_settlement(booking_id, variant="PROVISIONAL",
                     expected_booking_version=None, headers=None) -> dict:
    if expected_booking_version is None:
        expected_booking_version = booking_version(booking_id, BOX_OFFICE)
    return get_success_data(
        api_client.create_settlement(
            settlement_payload(booking_id, expected_booking_version, variant),
            headers or BOX_OFFICE,
        )
    )


def submit_settlement(settlement_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_settlement(settlement_id, headers or BOX_OFFICE)
    )


def finalize_settlement(settlement_id, headers=None) -> dict:
    return get_success_data(
        api_client.finalize_settlement(settlement_id, headers or EXECUTIVE_DIRECTOR)
    )


def resolve_settlement(settlement_id, outcome, dispute_note=None, headers=None) -> dict:
    extra = {"dispute_note": dispute_note} if dispute_note is not None else {}
    return get_success_data(
        api_client.resolve_settlement(
            settlement_id, resolve_settlement_payload(outcome, **extra),
            headers or EXECUTIVE_DIRECTOR,
        )
    )


def read_settlement(settlement_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_settlement(settlement_id, headers or BOX_OFFICE)
    )


# ─── Tier 2: the standing programming world ───────────────────────────────

def setup_programming_baseline(
    venue_overrides=None,
    distributor_overrides=None,
    title_overrides=None,
    booking_overrides=None,
    clearance_overrides=None,
    asset_overrides=None,
    confirm=True,
    clear=True,
    asset_target_status=None,
) -> dict:
    """House + distributor + title + engagement + licence + package.

    By default the engagement is CONFIRMED, the licence is CLEARED by a second
    operator and the package sits in REQUESTED. Returns a world dict whose keys
    are venue, distributor, title, booking, clearance and asset.
    """
    venue = register_venue(**(venue_overrides or {}))
    distributor = register_distributor(**(distributor_overrides or {}))
    title = catalogue_title(distributor["id"], **(title_overrides or {}))
    booking = open_engagement(
        title["id"], distributor["id"], venue["id"], **(booking_overrides or {})
    )
    if confirm:
        booking = confirm_engagement(booking["id"])
    clearance = lodge_licence(
        title["id"], booking["id"], **(clearance_overrides or {})
    )
    if clear:
        clearance = clear_licence(clearance["id"])
    asset = book_asset(
        title["id"], distributor["id"], venue["id"], **(asset_overrides or {})
    )
    if asset_target_status:
        asset = walk_asset_to(asset["id"], asset_target_status)
    return {
        "venue": venue,
        "distributor": distributor,
        "title": title,
        "booking": booking,
        "clearance": clearance,
        "asset": asset,
    }


def setup_ingested_package_world(**baseline_kwargs) -> dict:
    """The programming world with an encrypted package already INGESTED."""
    asset_overrides = baseline_kwargs.pop("asset_overrides", None) or {}
    asset_overrides.setdefault("is_encrypted", True)
    return setup_programming_baseline(
        asset_overrides=asset_overrides,
        asset_target_status="INGESTED",
        **baseline_kwargs,
    )


# ─── Tier 3: screenings in later lifecycle stages ─────────────────────────

def setup_scheduled_screening(start_at=DEFAULT_SHOWTIME_START,
                              showtime_overrides=None, world=None,
                              **baseline_kwargs) -> dict:
    """A SCHEDULED screening with sale_status DRAFT and playback UNVERIFIED."""
    world = world or setup_programming_baseline(**baseline_kwargs)
    world["showtime"] = place_showtime(
        world, start_at, **(showtime_overrides or {})
    )
    return world


def setup_screening_on_sale(start_at=DEFAULT_SHOWTIME_START, world=None,
                            showtime_overrides=None, **baseline_kwargs) -> dict:
    """A SCHEDULED screening whose sale_status has been driven to ON_SALE."""
    world = setup_scheduled_screening(
        start_at, showtime_overrides, world, **baseline_kwargs
    )
    world["showtime"] = open_showtime_sales(world["showtime"]["id"])
    return world


def setup_sold_out_screening(start_at=DEFAULT_SHOWTIME_START,
                             **baseline_kwargs) -> dict:
    """Two paid walk-up orders of four seats each fill all eight sellable seats."""
    world = setup_screening_on_sale(start_at, **baseline_kwargs)
    showtime_id = world["showtime"]["id"]
    first = sell_seats(showtime_id, 4, purchaser_email="w1@example.com")
    pay_for_order(first["id"])
    second = sell_seats(showtime_id, 4, purchaser_email="w2@example.com")
    pay_for_order(second["id"])
    world["orders"] = [read_order(first["id"]), read_order(second["id"])]
    world["showtime"] = read_showtime(showtime_id)
    return world


def setup_key_pending_screening(start_at=DEFAULT_SHOWTIME_START,
                                valid_from="2026-08-14T11:00:00Z",
                                valid_until="2026-08-14T14:30:00Z",
                                world=None, **baseline_kwargs) -> dict:
    """An encrypted, INGESTED package plus a covering key: playback KEY_PENDING."""
    world = world or setup_ingested_package_world(**baseline_kwargs)
    if "showtime" not in world:
        world["showtime"] = place_showtime(world, start_at)
    world["key"] = issue_kdm(
        world["asset"]["id"], world["venue"]["id"], valid_from, valid_until
    )
    world["showtime"] = read_showtime(world["showtime"]["id"])
    return world


def setup_verified_screening(start_at=DEFAULT_SHOWTIME_START, **kwargs) -> dict:
    """A screening whose booth test has passed: playback PLAYBACK_VERIFIED."""
    world = setup_key_pending_screening(start_at, **kwargs)
    world["showtime"] = verify_booth_playback(world["showtime"]["id"], "PASS")
    return world


def complete_screening(showtime_id, complete_clock, close_sales_first=True,
                       verify_playback_first=False) -> dict:
    """Close the box office, pass the booth test, move the clock and complete."""
    if close_sales_first:
        showtime = read_showtime(showtime_id)
        if showtime["sale_status"] == "DRAFT":
            open_showtime_sales(showtime_id)
        if read_showtime(showtime_id)["sale_status"] in ("ON_SALE", "SOLD_OUT"):
            close_showtime_sales(showtime_id)
    if verify_playback_first:
        verify_booth_playback(showtime_id, "PASS")
    set_logical_clock(complete_clock)
    return mark_showtime_played(showtime_id)


def setup_completed_screening(start_at=DEFAULT_SHOWTIME_START,
                              complete_clock="2026-08-14T14:00:00Z",
                              **kwargs) -> dict:
    """One screening driven all the way to COMPLETED."""
    world = setup_verified_screening(start_at, **kwargs)
    world["showtime"] = complete_screening(world["showtime"]["id"], complete_clock)
    world["booking"] = read_booking(world["booking"]["id"])
    return world


# ─── Tier 4: accumulation and threshold targeting ─────────────────────────

def setup_week_with_screenings(starts, world=None, strand="REPERTORY_SERIES",
                               **baseline_kwargs) -> dict:
    """Place one screening per instant in `starts`, all on the same licence."""
    world = world or setup_programming_baseline(**baseline_kwargs)
    world["showtimes"] = [
        place_showtime(world, start_at, strand=strand) for start_at in starts
    ]
    world["clearance"] = read_clearance(world["clearance"]["id"])
    return world


def setup_member_at_tier(tier="SUPPORTER", world=None, **member_overrides) -> dict:
    """A member whose rolling giving puts effective_tier at the named tier.

    The single gift is stamped 2026-03-01, inside the trailing 365 days of the
    startup clock but before the fiscal year opens, so the rolling figure is
    what carries the tier.
    """
    amounts = {
        "PROSPECT": 0,
        "BASIC": 6000,
        "SUPPORTER": 20000,
        "DONOR_CIRCLE": 50000,
    }
    member = enrol_member(**member_overrides)
    if amounts[tier]:
        member = lodge_donation(
            member["id"], amounts[tier], TEST_DEFAULTS["SUPPORTER_DONATION_AT"]
        )
    if world is not None:
        world["member"] = member
        return world
    return member


def setup_member_with_credit(world=None, quantity=3, **baseline_kwargs) -> dict:
    """A SUPPORTER member holding refund credit from a reversed paid order.

    Three seats at 1450 with a 0.15 discount price at 1233 each, so the order
    totals 4149 cents and that whole figure crosses into member credit.
    """
    world = world or setup_screening_on_sale(**baseline_kwargs)
    member = setup_member_at_tier("SUPPORTER")
    order = sell_seats(
        world["showtime"]["id"], quantity,
        purchaser_email=TEST_DEFAULTS["MEMBER_EMAIL"], member_id=member["id"],
    )
    pay_for_order(order["id"])
    refund_order(order["id"], "MEMBER_CREDIT")
    world["member"] = read_member(member["id"])
    world["refunded_order"] = read_order(order["id"])
    world["showtime"] = read_showtime(world["showtime"]["id"])
    return world


# ─── Tier 5: closure, settlement and terminal states ─────────────────────

def setup_closed_engagement(start_at=DEFAULT_SHOWTIME_START,
                            complete_screening_first=False,
                            complete_clock="2026-08-14T14:00:00Z",
                            **kwargs) -> dict:
    """An engagement priced through close, with or without a played screening."""
    if complete_screening_first:
        world = setup_completed_screening(start_at, complete_clock, **kwargs)
    else:
        world = setup_scheduled_screening(start_at, **kwargs)
    world["booking"] = close_engagement(world["booking"]["id"])
    return world


def setup_drafted_settlement(variant="PROVISIONAL", **kwargs) -> dict:
    """A CLOSED engagement carrying one DRAFT settlement in the named variant."""
    world = setup_closed_engagement(**kwargs)
    world["settlement"] = draft_settlement(world["booking"]["id"], variant)
    world["booking"] = read_booking(world["booking"]["id"])
    return world


def setup_submitted_settlement(variant="PROVISIONAL", **kwargs) -> dict:
    world = setup_drafted_settlement(variant, **kwargs)
    world["settlement"] = submit_settlement(world["settlement"]["id"])
    return world


def setup_reconciled_settlement(variant="PROVISIONAL", **kwargs) -> dict:
    world = setup_submitted_settlement(variant, **kwargs)
    world["settlement"] = finalize_settlement(world["settlement"]["id"])
    return world


def setup_planned_event(start_at=DEFAULT_SHOWTIME_START, event_overrides=None,
                        world=None, **kwargs) -> dict:
    """A PLANNED special event wrapped around a SCHEDULED screening."""
    world = world or setup_scheduled_screening(start_at, **kwargs)
    world["event"] = plan_event(
        world["showtime"]["id"], **(event_overrides or {})
    )
    return world


def setup_confirmed_event(start_at=DEFAULT_SHOWTIME_START, displace_conflicts=False,
                          event_overrides=None, **kwargs) -> dict:
    """A CONFIRMED special event, so the screening's block has already grown."""
    world = setup_planned_event(start_at, event_overrides, **kwargs)
    world["event"] = confirm_event(world["event"]["id"], displace_conflicts)
    world["showtime"] = read_showtime(world["showtime"]["id"])
    return world
