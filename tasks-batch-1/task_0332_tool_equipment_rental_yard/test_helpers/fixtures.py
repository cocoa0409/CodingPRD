"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Every fixture builds its preconditions from scratch via PRD-declared endpoints —
the harness restarts the server (empty DB) before each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_rate_card_payload,
    create_catalog_item_payload,
    create_equipment_unit_payload,
    create_contractor_account_payload,
    create_delivery_truck_payload,
    create_reservation_payload,
    create_dispatch_payload,
    create_return_inspection_payload,
    create_maintenance_ticket_payload,
)
from .test_users import TEST_USERS

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

DEFAULT_CLOCK = "2026-06-01T08:00:00.000Z"


# ─── Clock ────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the simulated yard clock. Returns the YardClock row."""
    return get_success_data(api_client.set_clock(iso, YM))


# ─── Tier 1: Base catalog builders ────────────────────────────────

def create_rate_card(**overrides):
    """Create a RateCard. Returns the card."""
    return get_success_data(
        api_client.create_rate_card(create_rate_card_payload(**overrides), YM))


def create_catalog_item(rate_card_id, **overrides):
    """Create a RentalCatalogItem bound to a rate card. Returns the item."""
    return get_success_data(api_client.create_catalog_item(
        create_catalog_item_payload(rate_card_id, **overrides), YM))


def create_equipment_unit(catalog_item_id, **overrides):
    """Register one EquipmentUnit for a catalog item. Returns the unit."""
    return get_success_data(api_client.create_equipment_unit(
        create_equipment_unit_payload(catalog_item_id, **overrides), YM))


def create_account(**overrides):
    """Open a ContractorAccount. Returns the account."""
    return get_success_data(api_client.create_contractor_account(
        create_contractor_account_payload(**overrides), YM))


def create_truck(**overrides):
    """Register a DeliveryTruck. Returns the truck."""
    return get_success_data(api_client.create_delivery_truck(
        create_delivery_truck_payload(**overrides), YM))


# ─── Tier 2: Common scenario builders ─────────────────────────────

def setup_yard(clock=DEFAULT_CLOCK, rate_card_overrides=None,
               item_overrides=None, unit_overrides=None, account_overrides=None):
    """Clock + rate card + catalog item + one equipment unit + account.

    The single most common preamble. Returns a dict with keys
    rate_card, item, unit, account.
    """
    set_clock(clock)
    rc = create_rate_card(**(rate_card_overrides or {}))
    item = create_catalog_item(rc["id"], **(item_overrides or {}))
    unit = create_equipment_unit(item["id"], **(unit_overrides or {}))
    account = create_account(**(account_overrides or {}))
    return {"rate_card": rc, "item": item, "unit": unit, "account": account}


def create_reservation(account_id, item_id, unit_id=None, **overrides):
    """Create a CONFIRMED reservation. Returns the reservation row.

    Pass unit_id=None to leave equipment_unit_id off (selector policy path).
    """
    extra = dict(overrides)
    if unit_id is not None:
        extra["equipment_unit_id"] = unit_id
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(account_id, item_id, **extra), AGENT))


def find_agreement_for_reservation(reservation_id, headers=AGENT):
    """Return the RentalAgreement opened from a reservation (filtered list)."""
    data, _ = _paginated(
        api_client.list_rental_agreements(
            headers, params={"reservation_id": reservation_id}))
    assert data, f"no agreement found for reservation {reservation_id}"
    return data[0]


def _paginated(response):
    body = response.json()
    return body["data"], body.get("meta", {})


# ─── Tier 3: Lifecycle shortcuts ──────────────────────────────────

def setup_picked_up_agreement(clock=DEFAULT_CLOCK, item_overrides=None,
                              unit_overrides=None, account_overrides=None,
                              reservation_overrides=None):
    """Yard + PICKUP reservation taken on rent. Returns dict adding
    reservation and agreement (ON_RENT). Unit is ON_RENT, fuel full."""
    ctx = setup_yard(clock=clock, item_overrides=item_overrides,
                     unit_overrides=unit_overrides,
                     account_overrides=account_overrides)
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"],
                           ctx["unit"]["id"], **(reservation_overrides or {}))
    get_success_data(api_client.pickup_reservation(r["id"], AGENT))
    ag = find_agreement_for_reservation(r["id"])
    ctx["reservation"] = r
    ctx["agreement"] = ag
    return ctx


def return_agreement(agreement_id, return_clock):
    """Advance the clock then mark the agreement physically returned.
    Returns the agreement row (RETURNED_PENDING_INSPECTION)."""
    set_clock(return_clock)
    return get_success_data(api_client.return_agreement(agreement_id, AGENT))


def setup_returned_pending_inspection(clock=DEFAULT_CLOCK,
                                      return_clock="2026-06-10T09:00:00.000Z",
                                      item_overrides=None, unit_overrides=None,
                                      account_overrides=None,
                                      reservation_overrides=None):
    """Full preamble through RETURNED_PENDING_INSPECTION. Returns dict with
    rate_card, item, unit, account, reservation, agreement."""
    ctx = setup_picked_up_agreement(
        clock=clock, item_overrides=item_overrides, unit_overrides=unit_overrides,
        account_overrides=account_overrides,
        reservation_overrides=reservation_overrides)
    ctx["agreement"] = return_agreement(ctx["agreement"]["id"], return_clock)
    return ctx


def inspect(agreement_id, **inspection_overrides):
    """Create a ReturnInspection (closes the agreement, settles). Returns it."""
    return get_success_data(api_client.create_return_inspection(
        create_return_inspection_payload(agreement_id, **inspection_overrides),
        INSPECTOR))


def setup_closed_agreement(clean=True, clock=DEFAULT_CLOCK,
                           return_clock="2026-06-10T09:00:00.000Z",
                           inspection_overrides=None, **setup_kwargs):
    """Full lifecycle through a closed agreement. Returns dict with
    rate_card, item, unit, account, reservation, agreement, inspection."""
    ctx = setup_returned_pending_inspection(
        clock=clock, return_clock=return_clock, **setup_kwargs)
    ins = inspect(ctx["agreement"]["id"], **(inspection_overrides or {}))
    ctx["inspection"] = ins
    ctx["agreement"] = get_success_data(
        api_client.get_rental_agreement(ctx["agreement"]["id"], YM))
    ctx["unit"] = get_success_data(
        api_client.get_equipment_unit(ctx["unit"]["id"], YM))
    return ctx


# ─── Tier 4: Maintenance / out-of-service ─────────────────────────

def pull_unit_out_of_service(unit_id, reason="SCHEDULED_SERVICE"):
    """Open a MaintenanceTicket on an AVAILABLE unit (moves it OUT_OF_SERVICE).
    Returns the ticket."""
    return get_success_data(api_client.create_maintenance_ticket(
        create_maintenance_ticket_payload(unit_id, reason=reason), YM))


def setup_out_of_service_unit(clock=DEFAULT_CLOCK, account_overrides=None):
    """Yard with its single unit pulled OUT_OF_SERVICE via a maintenance ticket.
    Returns dict with rate_card, item, unit, account, ticket."""
    ctx = setup_yard(clock=clock, account_overrides=account_overrides)
    ctx["ticket"] = pull_unit_out_of_service(ctx["unit"]["id"])
    ctx["unit"] = get_success_data(
        api_client.get_equipment_unit(ctx["unit"]["id"], YM))
    return ctx


# ─── Tier 5: Delivery / truck dispatch ────────────────────────────

def setup_dispatched_delivery(clock=DEFAULT_CLOCK, buffer_minutes=60):
    """Truck + delivery item + two units, with reservation rA dispatched onto a
    09:00-10:00Z window and reservation rB still CONFIRMED on a second unit.

    Returns dict with rate_card, item, truck, unit_a, unit_b, account,
    reservation_a (DISPATCHED/ON_RENT), reservation_b (CONFIRMED).
    """
    set_clock(clock)
    rc = create_rate_card()
    item = create_catalog_item(rc["id"], requires_delivery=True)
    unit_a = create_equipment_unit(item["id"], asset_tag="EU-1")
    unit_b = create_equipment_unit(item["id"], asset_tag="EU-2")
    truck = create_truck(buffer_minutes=buffer_minutes)
    account = create_account()
    r_a = create_reservation(account["id"], item["id"], unit_a["id"],
                             fulfillment_method="DELIVERY",
                             rental_start_date="2026-06-01",
                             rental_end_date="2026-06-05")
    r_b = create_reservation(account["id"], item["id"], unit_b["id"],
                             fulfillment_method="DELIVERY",
                             rental_start_date="2026-06-01",
                             rental_end_date="2026-06-05")
    get_success_data(api_client.dispatch_reservation(
        r_a["id"],
        create_dispatch_payload(truck["id"],
                                "2026-06-01T09:00:00.000Z",
                                "2026-06-01T10:00:00.000Z"),
        AGENT))
    return {
        "rate_card": rc, "item": item, "truck": truck,
        "unit_a": unit_a, "unit_b": unit_b, "account": account,
        "reservation_a": r_a, "reservation_b": r_b,
    }
