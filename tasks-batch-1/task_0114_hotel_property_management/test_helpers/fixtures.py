"""Composite setup helpers.

These encapsulate the multi-step setup sequences the test claims require so test
functions can focus on assertions. Every helper builds its preconditions from scratch
(empty DB) using only PRD-declared endpoints, and uses get_success_data() internally so
setup failures surface as clear "Setup step failed" errors.

Identity threading: the only entity_backed role is Guest. Reservation create/cancel by a
Guest is ownership-gated on guest_id == X-User-ID; helpers that act as a Guest call
make_guest_headers(guest_id). All other roles are opaque and use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_guest_headers
from . import factories as F

RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitives (single-entity creates with version capture)
# ---------------------------------------------------------------------------
def create_hotel(name="Test Hotel", current_business_date="2026-07-01",
                 overbooking_allowance_pct=0.0, **overrides) -> dict:
    payload = F.create_hotel_payload(
        name=name,
        current_business_date=current_business_date,
        overbooking_allowance_pct=overbooking_allowance_pct,
        **overrides,
    )
    return get_success_data(api_client.create_hotel(payload, RM))


def create_room_type(hotel_id, code="KING", tier_rank=1, physical_inventory=3,
                     base_rate_cents=20000, **overrides) -> dict:
    payload = F.create_room_type_payload(
        hotel_id, code=code, tier_rank=tier_rank,
        physical_inventory=physical_inventory, base_rate_cents=base_rate_cents,
        **overrides,
    )
    return get_success_data(api_client.create_room_type(payload, RM))


def create_rate_plan(hotel_id, code="BAR", kind="BAR", adjustment_mode="FLAT",
                     adjustment_value=0, no_show_policy="NONE", **overrides) -> dict:
    payload = F.create_rate_plan_payload(
        hotel_id, code=code, kind=kind, adjustment_mode=adjustment_mode,
        adjustment_value=adjustment_value, no_show_policy=no_show_policy,
        **overrides,
    )
    return get_success_data(api_client.create_rate_plan(payload, RM))


def create_corporate_account(hotel_id, name="Test Corp", credit_limit_cents=100000,
                             **overrides) -> dict:
    payload = F.create_corporate_account_payload(
        hotel_id, name=name, credit_limit_cents=credit_limit_cents, **overrides,
    )
    return get_success_data(api_client.create_corporate_account(payload, RM))


def create_guest(hotel_id, full_name="Test Guest", **overrides) -> dict:
    payload = F.create_guest_payload(hotel_id, full_name=full_name, **overrides)
    return get_success_data(api_client.create_guest(payload, FDA))


def create_room(hotel_id, room_type_id, room_number="101", **overrides) -> dict:
    payload = F.create_room_payload(hotel_id, room_type_id, room_number=room_number,
                                    **overrides)
    return get_success_data(api_client.create_room(payload, RM))


def create_group_block(hotel_id, room_type_id, rate_plan_id, **overrides) -> dict:
    payload = F.create_group_block_payload(hotel_id, room_type_id, rate_plan_id,
                                           **overrides)
    return get_success_data(api_client.create_group_block(payload, RM))


# ---------------------------------------------------------------------------
# Tier 1: room state progression
# ---------------------------------------------------------------------------
def create_inspected_room(hotel_id, room_type_id, room_number="101") -> dict:
    """Create a room (CLEAN) then transition CLEAN -> INSPECTED. Returns INSPECTED room."""
    room = create_room(hotel_id, room_type_id, room_number=room_number)
    data = get_success_data(api_client.room_housekeeping(
        room["id"], {"target": "INSPECTED", "expected_room_version": room["version"]}, RM))
    return data


def get_hotel_version(hotel_id) -> int:
    return get_success_data(api_client.get_hotel(hotel_id, NA))["version"]


def get_folio_for_reservation(hotel_id, reservation_id) -> dict:
    data, _ = _list(api_client.list_folios(FDA, params={
        "hotel_id": hotel_id, "reservation_id": reservation_id}))
    assert data, f"no folio found for reservation {reservation_id}"
    return data[0]


def _list(response):
    body = get_success_data_envelope(response)
    return body["data"], body["meta"]


def get_success_data_envelope(response):
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup list failed HTTP {response.status_code}: {response.text}")
    return response.json()


# ---------------------------------------------------------------------------
# Tier 2: standard scaffolding (hotel + type + plan + guest)
# ---------------------------------------------------------------------------
def setup_basic(overbooking_allowance_pct=0.0, current_business_date="2026-07-01",
                base_rate_cents=20000, physical_inventory=3,
                adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE",
                kind="BAR", room_type_code="KING"):
    """Hotel + one room type + one BAR rate plan + one guest. Returns a dict bundle."""
    hotel = create_hotel(current_business_date=current_business_date,
                         overbooking_allowance_pct=overbooking_allowance_pct)
    rt = create_room_type(hotel["id"], code=room_type_code, tier_rank=1,
                         physical_inventory=physical_inventory,
                         base_rate_cents=base_rate_cents)
    plan = create_rate_plan(hotel["id"], kind=kind, adjustment_mode=adjustment_mode,
                           adjustment_value=adjustment_value, no_show_policy=no_show_policy)
    guest = create_guest(hotel["id"])
    return {"hotel": hotel, "room_type": rt, "rate_plan": plan, "guest": guest}


# ---------------------------------------------------------------------------
# Tier 3: reservation lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_reservation(hotel_id, guest_id, room_type_id, rate_plan_id,
                       arrival_date="2026-07-01", departure_date="2026-07-02",
                       headers=None, **overrides) -> dict:
    payload = F.create_reservation_payload(
        hotel_id, guest_id, room_type_id, rate_plan_id,
        arrival_date=arrival_date, departure_date=departure_date, **overrides)
    return get_success_data(api_client.create_reservation(payload, headers or FDA))


def create_held_reservation(bundle, arrival_date="2026-07-01",
                            departure_date="2026-07-02", **overrides) -> dict:
    """Create a HELD reservation from a setup_basic bundle. Returns the reservation."""
    return create_reservation(
        bundle["hotel"]["id"], bundle["guest"]["id"], bundle["room_type"]["id"],
        bundle["rate_plan"]["id"], arrival_date=arrival_date,
        departure_date=departure_date, **overrides)


def create_confirmed_reservation(bundle, arrival_date="2026-07-01",
                                 departure_date="2026-07-02", **overrides) -> dict:
    """Create + confirm. Returns the CONFIRMED reservation."""
    res = create_held_reservation(bundle, arrival_date=arrival_date,
                                  departure_date=departure_date, **overrides)
    return get_success_data(api_client.confirm_reservation(res["id"], FDA))


def create_assigned_reservation(bundle, room_number="101",
                                arrival_date="2026-07-01", departure_date="2026-07-02"):
    """Create + confirm + assign an INSPECTED room. Returns (reservation, room).

    The assigned room is left INSPECTED so the reservation is ready for check-in.
    """
    room = create_inspected_room(bundle["hotel"]["id"], bundle["room_type"]["id"],
                                 room_number=room_number)
    res = create_confirmed_reservation(bundle, arrival_date=arrival_date,
                                       departure_date=departure_date)
    res2 = get_success_data(api_client.assign_room(
        res["id"], {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    return res2, room


def create_checked_in_reservation(bundle, room_number="101",
                                  arrival_date="2026-07-01", departure_date="2026-07-02"):
    """Create + confirm + assign + check-in. Returns (reservation, room).

    Requires arrival_date <= hotel.current_business_date (default 2026-07-01).
    """
    res, room = create_assigned_reservation(bundle, room_number=room_number,
                                            arrival_date=arrival_date,
                                            departure_date=departure_date)
    res2 = get_success_data(api_client.check_in(res["id"], FDA))
    return res2, room


def create_checked_out_reservation(bundle, room_number="101",
                                   arrival_date="2026-07-01", departure_date="2026-07-02"):
    """Full lifecycle through CHECKED_OUT. Returns (reservation, room)."""
    res, room = create_checked_in_reservation(bundle, room_number=room_number,
                                              arrival_date=arrival_date,
                                              departure_date=departure_date)
    res2 = get_success_data(api_client.check_out(res["id"], FDA))
    return res2, room


# ---------------------------------------------------------------------------
# Tier 4: night-audit helpers (open + complete one epoch)
# ---------------------------------------------------------------------------
def open_audit(hotel_id) -> dict:
    """Open a night audit run (posture -> AUDIT_LOCK). Returns the run."""
    hv = get_hotel_version(hotel_id)
    return get_success_data(api_client.create_night_audit_run(
        {"hotel_id": hotel_id, "expected_hotel_version": hv}, NA))


def complete_audit(hotel_id, run_id) -> dict:
    """Complete an in-progress audit run, refreshing the hotel version first.
    Returns the completed run."""
    hv = get_hotel_version(hotel_id)
    return get_success_data(api_client.complete_night_audit_run(
        run_id, {"expected_hotel_version": hv}, NA))


def run_one_audit(hotel_id) -> dict:
    """Open then complete one night audit epoch. Returns the COMPLETED run."""
    run = open_audit(hotel_id)
    return complete_audit(hotel_id, run["id"])


# ---------------------------------------------------------------------------
# Tier 4: corporate ledger / credit setups
# ---------------------------------------------------------------------------
def setup_corporate(credit_limit_cents=100000, base_rate_cents=20000,
                    physical_inventory=5, adjustment_value=0, current_business_date="2026-07-01"):
    """Hotel + KING type + CorporateAccount + CORPORATE rate plan + guest.
    Returns a bundle dict with keys: hotel, room_type, account, rate_plan, guest."""
    hotel = create_hotel(current_business_date=current_business_date,
                         overbooking_allowance_pct=0.0)
    rt = create_room_type(hotel["id"], code="KING", tier_rank=1,
                         physical_inventory=physical_inventory,
                         base_rate_cents=base_rate_cents)
    acct = create_corporate_account(hotel["id"], credit_limit_cents=credit_limit_cents)
    plan = create_rate_plan(hotel["id"], code="CORP", kind="CORPORATE",
                           corporate_account_id=acct["id"], adjustment_mode="FLAT",
                           adjustment_value=adjustment_value, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    return {"hotel": hotel, "room_type": rt, "account": acct,
            "rate_plan": plan, "guest": guest}


def corporate_bundle_as_basic(corp_bundle):
    """Adapt a corporate bundle to the setup_basic shape (rate_plan is the CORP plan)."""
    return {"hotel": corp_bundle["hotel"], "room_type": corp_bundle["room_type"],
            "rate_plan": corp_bundle["rate_plan"], "guest": corp_bundle["guest"]}
