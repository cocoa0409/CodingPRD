"""Composite setup helpers for the fractional jet ownership API.

Every helper builds its preconditions from scratch through the public API and
uses the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors. Ownership-gated calls thread the real
Owner.id through make_owner_headers(); FinanceOps segregation-of-duties flows
thread distinct operator identities through make_finance_ops_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLASS_SPECS, DEFAULT_MULTIPLIER_BP
from .factories import (
    create_aircraft_class_payload,
    create_aircraft_payload,
    create_booking_payload,
    create_invoice_payload,
    create_maintenance_event_payload,
    create_owner_payload,
    create_program_payload,
    create_share_payload,
    create_transfer_listing_payload,
)
from .test_users import TEST_USERS, make_finance_ops_headers, make_owner_headers

ADMIN = TEST_USERS["program_admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns the echoed payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def create_program(program_code="FJX-TST", currency="USD",
                   contract_year_start_month=8, peak_day_calendar=None) -> dict:
    payload = create_program_payload(
        program_code=program_code,
        currency=currency,
        contract_year_start_month=contract_year_start_month,
        peak_day_calendar=peak_day_calendar if peak_day_calendar is not None else [],
    )
    return get_success_data(api_client.create_program(payload, ADMIN))


def create_aircraft_class(program_id, class_code="MID", hourly_rate_cents=None,
                          monthly_fee_base_cents=None, seats=None,
                          interchange_upgrade_multiplier_bp=DEFAULT_MULTIPLIER_BP) -> dict:
    spec = CLASS_SPECS.get(class_code, CLASS_SPECS["MID"])
    payload = create_aircraft_class_payload(
        program_id,
        class_code=class_code,
        hourly_rate_cents=hourly_rate_cents if hourly_rate_cents is not None else spec["hourly_rate_cents"],
        monthly_fee_base_cents=monthly_fee_base_cents if monthly_fee_base_cents is not None else spec["monthly_fee_base_cents"],
        seats=seats if seats is not None else spec["seats"],
        interchange_upgrade_multiplier_bp=interchange_upgrade_multiplier_bp,
    )
    return get_success_data(api_client.create_aircraft_class(payload, ADMIN))


def create_owner(program_id, legal_name="Test Owner LLC", initial_deposit_cents=0) -> dict:
    payload = create_owner_payload(
        program_id, legal_name=legal_name, initial_deposit_cents=initial_deposit_cents
    )
    return get_success_data(api_client.create_owner(payload, ADMIN))


def create_share(owner_id, class_id, fraction_numerator=1, fraction_denominator=8,
                 purchase_price_cents=12000000, schedule_method="STRAIGHT_LINE",
                 recovery_years=5) -> dict:
    payload = create_share_payload(
        owner_id, class_id,
        fraction_numerator=fraction_numerator,
        fraction_denominator=fraction_denominator,
        purchase_price_cents=purchase_price_cents,
        schedule_method=schedule_method,
        recovery_years=recovery_years,
    )
    return get_success_data(api_client.create_share(payload, ADMIN))


def activate_share(share_id) -> dict:
    return get_success_data(api_client.activate_share(share_id, ADMIN))


def create_activated_share(owner_id, class_id, **kwargs) -> dict:
    """Create a share and activate it. Returns the ACTIVE share."""
    share = create_share(owner_id, class_id, **kwargs)
    return activate_share(share["id"])


def create_aircraft(program_id, class_id, tail_number="N100TS") -> dict:
    payload = create_aircraft_payload(program_id, class_id, tail_number=tail_number)
    return get_success_data(api_client.create_aircraft(payload, FLEET))


# ---------------------------------------------------------------------------
# Tier 2: reads / version tracking
# ---------------------------------------------------------------------------

def get_share(share_id) -> dict:
    return get_success_data(api_client.get_share(share_id, ADMIN))


def get_owner(owner_id) -> dict:
    return get_success_data(api_client.get_owner(owner_id, ADMIN))


def get_booking(booking_id) -> dict:
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def get_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def get_aircraft(aircraft_id) -> dict:
    return get_success_data(api_client.get_aircraft(aircraft_id, FLEET))


def share_version(share_id) -> int:
    return get_share(share_id)["version"]


# ---------------------------------------------------------------------------
# Tier 3: booking lifecycle
# ---------------------------------------------------------------------------

def create_booking(share_id, owner_id, requested_class_id, scheduled_departure_utc,
                   estimated_block_hours, expected_share_version=None):
    """Raw booking-create call (may fail). Returns the Response."""
    if expected_share_version is None:
        expected_share_version = share_version(share_id)
    payload = create_booking_payload(
        share_id, requested_class_id, expected_share_version,
        scheduled_departure_utc=scheduled_departure_utc,
        estimated_block_hours=estimated_block_hours,
    )
    return api_client.create_booking(payload, make_owner_headers(owner_id))


def create_booking_ok(share_id, owner_id, requested_class_id, scheduled_departure_utc,
                      estimated_block_hours, expected_share_version=None) -> dict:
    resp = create_booking(share_id, owner_id, requested_class_id,
                          scheduled_departure_utc, estimated_block_hours,
                          expected_share_version)
    return get_success_data(resp)


def confirm_booking_ok(booking_id, owner_id) -> dict:
    return get_success_data(api_client.confirm_booking(booking_id, make_owner_headers(owner_id)))


def assign_booking_ok(booking_id, aircraft_id) -> dict:
    return get_success_data(api_client.assign_booking(booking_id, {"aircraft_id": aircraft_id}, FLEET))


def cancel_booking_ok(booking_id, owner_id) -> dict:
    return get_success_data(api_client.cancel_booking(booking_id, make_owner_headers(owner_id)))


def complete_booking_ok(booking_id, actual_block_hours) -> dict:
    """Completes the booking; returns the created FlightLeg."""
    return get_success_data(
        api_client.complete_booking(booking_id, {"actual_block_hours": actual_block_hours}, FLEET)
    )


def create_confirmed_booking(share_id, owner_id, requested_class_id,
                             scheduled_departure_utc="2026-09-10T15:00:00Z",
                             estimated_block_hours=1.00) -> dict:
    """Create + confirm. Returns the CONFIRMED booking."""
    booking = create_booking_ok(share_id, owner_id, requested_class_id,
                                scheduled_departure_utc, estimated_block_hours)
    return confirm_booking_ok(booking["id"], owner_id)


def create_assigned_booking(share_id, owner_id, requested_class_id, aircraft_id,
                            scheduled_departure_utc="2026-09-10T15:00:00Z",
                            estimated_block_hours=1.00) -> dict:
    """Create + confirm + assign. Returns the assigned CONFIRMED booking."""
    booking = create_confirmed_booking(share_id, owner_id, requested_class_id,
                                       scheduled_departure_utc, estimated_block_hours)
    return assign_booking_ok(booking["id"], aircraft_id)


def create_completed_booking(share_id, owner_id, requested_class_id, aircraft_id,
                             scheduled_departure_utc="2026-09-10T15:00:00Z",
                             estimated_block_hours=1.00, actual_block_hours=1.00):
    """Create + confirm + assign + complete. Returns (booking, flight_leg)."""
    booking = create_assigned_booking(share_id, owner_id, requested_class_id, aircraft_id,
                                      scheduled_departure_utc, estimated_block_hours)
    leg = complete_booking_ok(booking["id"], actual_block_hours)
    return get_booking(booking["id"]), leg


# ---------------------------------------------------------------------------
# Tier 3: invoices
# ---------------------------------------------------------------------------

def create_invoice_ok(owner_id, billing_period) -> dict:
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(owner_id, billing_period), FIN)
    )


def issue_invoice_ok(invoice_id, headers=None) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, headers or FIN))


def create_issued_invoice(owner_id, billing_period, issue_clock) -> dict:
    """Create an invoice for a period, advance the clock past period end, issue it."""
    invoice = create_invoice_ok(owner_id, billing_period)
    set_clock(issue_clock)
    return issue_invoice_ok(invoice["id"])


def pay_invoice_ok(invoice_id, owner_id, amount_cents) -> dict:
    return get_success_data(
        api_client.pay_invoice(invoice_id, {"amount_cents": amount_cents},
                               make_owner_headers(owner_id))
    )


def invoice_lines(invoice_id, kind=None) -> list:
    lines = get_success_data(api_client.list_invoice_lines(invoice_id, FIN))
    if isinstance(lines, dict) and "data" in lines:
        lines = lines["data"]
    if kind is not None:
        lines = [ln for ln in lines if ln["line_kind"] == kind]
    return lines


# ---------------------------------------------------------------------------
# Tier 4: composite program scenarios
# ---------------------------------------------------------------------------

def setup_program_with_share(program_code="FJX-TST", class_code="MID",
                             fraction=(1, 8), purchase_price_cents=12000000,
                             initial_deposit_cents=0, peak_day_calendar=None,
                             hourly_rate_cents=None, monthly_fee_base_cents=None,
                             seats=None, owner_name="Test Owner LLC",
                             schedule_method="STRAIGHT_LINE", recovery_years=5) -> dict:
    """Program (ACTIVE) + one class + one GOOD owner + one ACTIVE share."""
    program = create_program(program_code=program_code, peak_day_calendar=peak_day_calendar)
    cls = create_aircraft_class(
        program["id"], class_code=class_code,
        hourly_rate_cents=hourly_rate_cents,
        monthly_fee_base_cents=monthly_fee_base_cents,
        seats=seats,
    )
    owner = create_owner(program["id"], legal_name=owner_name,
                         initial_deposit_cents=initial_deposit_cents)
    share = create_activated_share(
        owner["id"], cls["id"],
        fraction_numerator=fraction[0], fraction_denominator=fraction[1],
        purchase_price_cents=purchase_price_cents,
        schedule_method=schedule_method, recovery_years=recovery_years,
    )
    return {"program": program, "cls": cls, "owner": owner, "share": share}


def setup_owner_with_past_due_invoice(program_code="FJX-PD", class_code="MID",
                                      fraction=(1, 8), purchase_price_cents=12000000,
                                      issue_clock="2026-09-01T00:00:00Z",
                                      sweep_clock="2026-10-02T00:00:00Z") -> dict:
    """Scenario + an issued invoice swept PAST_DUE, leaving the owner DELINQUENT."""
    sc = setup_program_with_share(program_code=program_code, class_code=class_code,
                                  fraction=fraction, purchase_price_cents=purchase_price_cents)
    invoice = create_issued_invoice(sc["owner"]["id"], "2026-08", issue_clock)
    set_clock(sweep_clock)
    sc["invoice"] = invoice
    sc["owner"] = get_owner(sc["owner"]["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 4: transfer listings
# ---------------------------------------------------------------------------

def create_transfer_listing_ok(share_id, seller_owner_id, asking_price_cents=10000000,
                               program_repurchase_flag=False,
                               expected_share_version=None) -> dict:
    if expected_share_version is None:
        expected_share_version = share_version(share_id)
    payload = create_transfer_listing_payload(
        share_id, expected_share_version,
        asking_price_cents=asking_price_cents,
        program_repurchase_flag=program_repurchase_flag,
    )
    return get_success_data(
        api_client.create_transfer_listing(payload, make_owner_headers(seller_owner_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: maintenance events
# ---------------------------------------------------------------------------

def create_maintenance_event_ok(aircraft_id, window_start_utc, window_end_utc,
                                cost_cents=0, unscheduled_flag=False) -> dict:
    payload = create_maintenance_event_payload(
        aircraft_id,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        cost_cents=cost_cents,
        unscheduled_flag=unscheduled_flag,
    )
    return get_success_data(api_client.create_maintenance_event(payload, FLEET))


def start_maintenance_ok(event_id) -> dict:
    return get_success_data(api_client.start_maintenance(event_id, FLEET))


def complete_maintenance_ok(event_id, override_early=None) -> dict:
    payload = {}
    if override_early is not None:
        payload["override_early"] = override_early
    return get_success_data(api_client.complete_maintenance(event_id, payload, FLEET))


# ---------------------------------------------------------------------------
# Tier 5: exit lifecycle
# ---------------------------------------------------------------------------

def open_exit_ok(share_id, owner_id) -> dict:
    return get_success_data(api_client.exit_share(share_id, make_owner_headers(owner_id)))


def value_exit_ok(exit_id, valuer_id="finops-valuer-1") -> dict:
    return get_success_data(api_client.value_exit(exit_id, make_finance_ops_headers(valuer_id)))


def approve_exit_ok(exit_id, approver_id="finops-approver-1") -> dict:
    return get_success_data(api_client.approve_exit(exit_id, make_finance_ops_headers(approver_id)))


def settle_exit_ok(exit_id, settler_id="finops-approver-1") -> dict:
    return get_success_data(api_client.settle_exit(exit_id, make_finance_ops_headers(settler_id)))


def settle_exit_flow(share_id, owner_id, valuer_id="finops-valuer-1",
                     approver_id="finops-approver-1") -> dict:
    """Open an exit on the share and drive it to SETTLED. Returns the settled ExitRequest."""
    exit_req = open_exit_ok(share_id, owner_id)
    value_exit_ok(exit_req["id"], valuer_id)
    approve_exit_ok(exit_req["id"], approver_id)
    return settle_exit_ok(exit_req["id"], approver_id)
