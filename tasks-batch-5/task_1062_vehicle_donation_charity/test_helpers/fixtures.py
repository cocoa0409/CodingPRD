"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only -- each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_auction_lot_payload,
    create_charity_payload,
    create_donation_payload,
    create_donor_payload,
    create_pickup_order_payload,
    create_remittance_batch_payload,
    create_tax_receipt_payload,
    create_title_record_payload,
    create_tow_vendor_payload,
    create_vehicle_payload,
    create_venue_payload,
)
from .test_users import TEST_USERS, make_donor_headers, make_finance_officer_headers

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_agent_headers"]
CLERK = TEST_USERS["title_clerk_headers"]
AUCTION = TEST_USERS["auction_manager_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# --------------------------------------------------------------------------
# Tier 0: the logical clock and single-record creators
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock and return its answer."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def new_charity(**overrides) -> dict:
    return get_success_data(api.create_charity(create_charity_payload(**overrides), ADMIN))


def new_donor(**overrides) -> dict:
    return get_success_data(api.create_donor(create_donor_payload(**overrides), INTAKE))


def new_vendor(**overrides) -> dict:
    return get_success_data(api.create_tow_vendor(create_tow_vendor_payload(**overrides), ADMIN))


def new_venue(**overrides) -> dict:
    return get_success_data(api.create_venue(create_venue_payload(**overrides), ADMIN))


def new_donation(donor_id: str, charity_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_donation(create_donation_payload(donor_id, charity_id, **overrides), INTAKE)
    )


def new_vehicle(donation_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_vehicle(create_vehicle_payload(donation_id, **overrides), INTAKE)
    )


def inspect_vehicle(vehicle_id: str, **fields) -> dict:
    return get_success_data(api.inspect_vehicle(vehicle_id, fields, AUCTION))


def new_title(donation_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_title_record(create_title_record_payload(donation_id, **overrides), CLERK)
    )


def new_lot(donation_id: str, venue_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_auction_lot(create_auction_lot_payload(donation_id, venue_id, **overrides), AUCTION)
    )


def donation_version(donation_id: str) -> int:
    """Read the donation's current version, as any client would before an
    operation that echoes it back."""
    return get_success_data(api.get_donation(donation_id, INTAKE))["version"]


def read_donation(donation_id: str) -> dict:
    return get_success_data(api.get_donation(donation_id, INTAKE))


def read_charity(charity_id: str) -> dict:
    return get_success_data(api.get_charity(charity_id, ADMIN))


def read_vendor(vendor_id: str) -> dict:
    return get_success_data(api.get_tow_vendor(vendor_id, ADMIN))


def read_donor(donor_id: str) -> dict:
    return get_success_data(api.get_donor(donor_id, ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api.get_auction_lot(lot_id, AUCTION))


def read_title(title_id: str) -> dict:
    return get_success_data(api.get_title_record(title_id, CLERK))


def read_receipt(receipt_id: str) -> dict:
    return get_success_data(api.get_tax_receipt(receipt_id, FINANCE))


def read_batch(batch_id: str, headers=None) -> dict:
    return get_success_data(api.get_remittance_batch(batch_id, headers or FINANCE))


def read_pickup(pickup_id: str) -> dict:
    return get_success_data(api.get_pickup_order(pickup_id, INTAKE))


def donation_ledger(donation_id: str, **params) -> list:
    return get_success_data(
        api.list_donation_ledger_entries(donation_id, FINANCE, params=params or None)
    )


def donation_tasks(donation_id: str, **params) -> list:
    return get_success_data(
        api.list_donation_follow_up_tasks(donation_id, ADMIN, params=params or None)
    )


def batch_ledger(batch_id: str, **params) -> list:
    return get_success_data(api.list_batch_ledger_entries(batch_id, FINANCE, params=params or None))


# --------------------------------------------------------------------------
# Tier 1: state progression on a single donation
# --------------------------------------------------------------------------

def accept(donation_id: str) -> dict:
    return get_success_data(api.accept_donation(donation_id, INTAKE))


def dropoff(donation_id: str) -> dict:
    return get_success_data(api.receive_dropoff(donation_id, INTAKE))


def clear_title(donation_id: str, **overrides) -> dict:
    """Open a title record and walk it DRAFT -> SUBMITTED -> CLEARED."""
    title = new_title(donation_id, **overrides)
    get_success_data(api.submit_title_to_dmv(title["id"], CLERK))
    return get_success_data(
        api.record_dmv_decision(title["id"], {"outcome": "CLEARED"}, CLERK)
    )


def reject_title(donation_id: str, reason: str = "signature mismatch", **overrides) -> dict:
    """Open a title record and walk it DRAFT -> SUBMITTED -> REJECTED."""
    title = new_title(donation_id, **overrides)
    get_success_data(api.submit_title_to_dmv(title["id"], CLERK))
    return get_success_data(
        api.record_dmv_decision(
            title["id"], {"outcome": "REJECTED", "rejection_reason": reason}, CLERK
        )
    )


def sell_lot(lot_id: str, donation_id: str, sale_price_cents: int) -> dict:
    """Read the donation's live version, then record the hammer price."""
    version = donation_version(donation_id)
    return get_success_data(
        api.record_sale(
            lot_id,
            {"sale_price_cents": sale_price_cents, "expected_donation_version": version},
            AUCTION,
        )
    )


# --------------------------------------------------------------------------
# Tier 2: entity hierarchies
# --------------------------------------------------------------------------

def setup_dropoff_in_custody(charity=None, donor=None, **donation_overrides) -> dict:
    """A drop-off donation walked PENDING_REVIEW -> ACCEPTED -> IN_CUSTODY.

    Returns {"charity", "donor", "donation"}.
    """
    charity = charity or new_charity()
    donor = donor or new_donor()
    overrides = {"pickup_required": False}
    overrides.update(donation_overrides)
    donation = new_donation(donor["id"], charity["id"], **overrides)
    accept(donation["id"])
    donation = dropoff(donation["id"])
    return {"charity": charity, "donor": donor, "donation": donation}


def setup_listed_lot(
    charity=None,
    donor=None,
    venue=None,
    reserve_price_cents: int = 1_000,
    with_vehicle: bool = False,
    vehicle_overrides: dict = None,
    clear_the_title: bool = True,
    **donation_overrides,
) -> dict:
    """A drop-off donation IN_CUSTODY with (optionally) a CLEARED title and a
    LISTED lot, ready for a hammer price.

    Returns {"charity", "donor", "venue", "donation", "lot", "title", "vehicle"}.
    """
    base = setup_dropoff_in_custody(charity=charity, donor=donor, **donation_overrides)
    venue = venue or new_venue()
    vehicle = None
    if with_vehicle:
        vehicle = new_vehicle(base["donation"]["id"], **(vehicle_overrides or {}))
    title = clear_title(base["donation"]["id"]) if clear_the_title else None
    lot = new_lot(
        base["donation"]["id"], venue["id"], reserve_price_cents=reserve_price_cents
    )
    return {
        **base,
        "venue": venue,
        "lot": lot,
        "title": title,
        "vehicle": vehicle,
    }


def setup_sold_donation(
    sale_price_cents: int = 60_000,
    charity=None,
    donor=None,
    venue=None,
    reserve_price_cents: int = 1_000,
    with_vehicle: bool = False,
    vehicle_overrides: dict = None,
    **donation_overrides,
) -> dict:
    """A drop-off donation carried all the way to SOLD / ACCRUED.

    Returns the setup_listed_lot bundle plus the refreshed "lot" and "donation".
    """
    bundle = setup_listed_lot(
        charity=charity,
        donor=donor,
        venue=venue,
        reserve_price_cents=reserve_price_cents,
        with_vehicle=with_vehicle,
        vehicle_overrides=vehicle_overrides,
        **donation_overrides,
    )
    lot = sell_lot(bundle["lot"]["id"], bundle["donation"]["id"], sale_price_cents)
    bundle["lot"] = lot
    bundle["donation"] = read_donation(bundle["donation"]["id"])
    return bundle


def setup_accepted_with_vendor(
    charity=None, donor=None, vendor=None, daily_capacity_slots: int = 5, **donation_overrides
) -> dict:
    """An ACCEPTED donation that expects a tow, plus an ACTIVE vendor.

    Returns {"charity", "donor", "vendor", "donation"} where "donation" is the
    accept response, so its "version" is the value a client would echo back.
    """
    charity = charity or new_charity()
    donor = donor or new_donor()
    vendor = vendor or new_vendor(daily_capacity_slots=daily_capacity_slots)
    overrides = {"pickup_required": True, "intake_channel": "PHONE"}
    overrides.update(donation_overrides)
    donation = new_donation(donor["id"], charity["id"], **overrides)
    donation = accept(donation["id"])
    return {"charity": charity, "donor": donor, "vendor": vendor, "donation": donation}


def book_pickup(
    donation_id: str,
    vendor_id: str,
    start: str = "2026-07-06T09:00:00Z",
    end: str = "2026-07-06T11:00:00Z",
    expected_version: int = None,
) -> dict:
    """Reserve a tow window, reading the donation's live version when the caller
    does not supply one."""
    version = expected_version if expected_version is not None else donation_version(donation_id)
    return get_success_data(
        api.create_pickup_order(
            create_pickup_order_payload(
                donation_id,
                vendor_id,
                version,
                scheduled_start_utc=start,
                scheduled_end_utc=end,
            ),
            INTAKE,
        )
    )


def setup_towed_donation(
    tow_cost_cents: int,
    charity=None,
    donor=None,
    vendor=None,
    start: str = "2026-07-06T09:00:00Z",
    end: str = "2026-07-06T11:00:00Z",
) -> dict:
    """An ACCEPTED donation whose tow completed for `tow_cost_cents`, leaving the
    donation IN_CUSTODY.

    Returns {"charity", "donor", "vendor", "donation", "pickup_order"}.
    """
    bundle = setup_accepted_with_vendor(charity=charity, donor=donor, vendor=vendor)
    order = book_pickup(
        bundle["donation"]["id"],
        bundle["vendor"]["id"],
        start=start,
        end=end,
        expected_version=bundle["donation"]["version"],
    )
    order = get_success_data(
        api.complete_pickup(order["id"], {"actual_tow_cost_cents": tow_cost_cents}, INTAKE)
    )
    bundle["pickup_order"] = order
    bundle["donation"] = read_donation(bundle["donation"]["id"])
    return bundle


def setup_pickup_blocked_donation(charity=None, donor=None) -> dict:
    """An ACCEPTED donation driven to PICKUP_BLOCKED by three failed tows.

    Returns {"charity", "donor", "vendor", "donation", "pickup_orders"}.
    """
    bundle = setup_accepted_with_vendor(charity=charity, donor=donor)
    donation_id = bundle["donation"]["id"]
    orders = []
    for day, reason in [
        ("2026-07-06", "vehicle not at address"),
        ("2026-07-07", "keys unavailable"),
        ("2026-07-08", "donor not reachable"),
    ]:
        order = book_pickup(
            donation_id,
            bundle["vendor"]["id"],
            start=f"{day}T09:00:00Z",
            end=f"{day}T11:00:00Z",
        )
        get_success_data(api.fail_pickup(order["id"], {"failure_reason": reason}, INTAKE))
        orders.append(order)
    bundle["pickup_orders"] = orders
    bundle["donation"] = read_donation(donation_id)
    return bundle


# --------------------------------------------------------------------------
# Tier 3: receipts
# --------------------------------------------------------------------------

def draft_receipt(donation_id: str) -> dict:
    return get_success_data(
        api.create_tax_receipt(create_tax_receipt_payload(donation_id), FINANCE)
    )


def issue_receipt(receipt_id: str, headers=None) -> dict:
    return get_success_data(api.issue_receipt(receipt_id, headers or FINANCE))


def setup_issued_receipt(sale_price_cents: int = 60_000, **kwargs) -> dict:
    """A sold donation with a vehicle, carried through to an ISSUED receipt and a
    CLOSED donation.

    Returns the setup_sold_donation bundle plus "receipt".
    """
    kwargs.setdefault("with_vehicle", True)
    bundle = setup_sold_donation(sale_price_cents=sale_price_cents, **kwargs)
    receipt = draft_receipt(bundle["donation"]["id"])
    bundle["receipt"] = issue_receipt(receipt["id"])
    bundle["donation"] = read_donation(bundle["donation"]["id"])
    return bundle


# --------------------------------------------------------------------------
# Tier 4: remittance batches
# --------------------------------------------------------------------------

def open_batch(
    charity_id: str,
    period_start_utc: str = "2026-07-01T00:00:00Z",
    period_end_utc: str = "2026-08-01T00:00:00Z",
    officer: str = "fo-alice",
) -> dict:
    return get_success_data(
        api.create_remittance_batch(
            create_remittance_batch_payload(
                charity_id,
                period_start_utc=period_start_utc,
                period_end_utc=period_end_utc,
            ),
            make_finance_officer_headers(officer),
        )
    )


def close_batch(batch_id: str, officer: str = "fo-alice") -> dict:
    return get_success_data(api.close_batch(batch_id, make_finance_officer_headers(officer)))


def pay_batch(batch_id: str, expected_batch_version: int, reference: str = "ACH-1001",
              officer: str = "fo-bob") -> dict:
    return get_success_data(
        api.pay_batch(
            batch_id,
            {"payment_reference": reference, "expected_batch_version": expected_batch_version},
            make_finance_officer_headers(officer),
        )
    )


def setup_closed_batch(
    sale_price_cents: int = 60_000,
    remittance_fee_pct: float = 0.10,
    officer: str = "fo-alice",
    clock: str = "2026-07-10T00:00:00Z",
    **sale_kwargs,
) -> dict:
    """One sold donation frozen into a CLOSED batch.

    Returns the setup_sold_donation bundle plus "batch" (the close response).
    """
    if clock:
        set_clock(clock)
    charity = new_charity(remittance_fee_pct=remittance_fee_pct)
    bundle = setup_sold_donation(sale_price_cents=sale_price_cents, charity=charity, **sale_kwargs)
    batch = open_batch(charity["id"], officer=officer)
    bundle["batch"] = close_batch(batch["id"], officer=officer)
    return bundle


def setup_multi_member_batch(sale_prices, remittance_fee_pct: float = 0.10,
                             clock: str = "2026-07-10T00:00:00Z") -> dict:
    """Several drop-off donations for one charity, each sold at the given price,
    with an OPEN batch sweeping the whole period.

    Returns {"charity", "donor", "venue", "donations", "batch"}.
    """
    set_clock(clock)
    charity = new_charity(remittance_fee_pct=remittance_fee_pct)
    donor = new_donor()
    venue = new_venue()
    donations = []
    channels = ["WEB", "PHONE", "PARTNER"]
    for index, price in enumerate(sale_prices):
        bundle = setup_sold_donation(
            sale_price_cents=price,
            charity=charity,
            donor=donor,
            venue=venue,
            intake_channel=channels[index % len(channels)],
        )
        donations.append(bundle["donation"])
    batch = open_batch(charity["id"])
    return {
        "charity": charity,
        "donor": donor,
        "venue": venue,
        "donations": donations,
        "batch": batch,
    }


# --------------------------------------------------------------------------
# Tier 5: follow-up tasks
# --------------------------------------------------------------------------

def setup_abandoned_title_task(clock: str = "2026-07-05T00:00:00Z") -> dict:
    """A REJECTED title abandoned by the clerk, raising its TITLE_STALE task.

    Returns {"charity", "donor", "donation", "title", "task"}.
    """
    if clock:
        set_clock(clock)
    charity = new_charity()
    donor = new_donor()
    donation = new_donation(
        donor["id"], charity["id"], declared_condition="POOR", pickup_required=False
    )
    accept(donation["id"])
    title = reject_title(donation["id"], reason="illegible")
    title = get_success_data(
        api.abandon_title(title["id"], {"reason": "cannot be cured"}, CLERK)
    )
    tasks = donation_tasks(donation["id"])
    return {
        "charity": charity,
        "donor": donor,
        "donation": donation,
        "title": title,
        "task": tasks[0] if tasks else None,
    }


def cancel_as_donor(donation_id: str, donor_id: str, reason: str = "donor changed their mind"):
    """Cancel through the donation's own donor, threading the donor id into
    X-User-ID so the ownership check passes."""
    return api.cancel_donation(donation_id, {"reason": reason}, make_donor_headers(donor_id))
