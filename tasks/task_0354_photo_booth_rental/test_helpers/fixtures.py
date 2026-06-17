"""Composite setup helpers for multi-step test prerequisites (Photo Booth Rental API).

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "Setup failed" errors, not confusing downstream assertion failures.

IMPORTANT — deposit amounts are read dynamically. The PRD defines deposit_due as
quote_subtotal multiplied by the (symbolic) deposit percentage DEPOSIT_PCT without
stating its numeric value, so a faithful implementation may use any percentage.
Fixtures therefore GET the booking and pay exactly its computed deposit_due rather
than hard-coding a dollar amount — the deposit-payment validation requires the
amount to equal deposit_due exactly (PRD §3.6).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_booth_model_payload, create_package_payload, create_booth_payload,
    create_attendant_payload, create_add_on_payload, create_customer_payload,
    create_booking_payload, create_booking_add_on_payload, create_payment_payload,
    create_finalize_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers,
    make_platform_admin_headers, make_operations_manager_headers,
    make_finance_clerk_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["operations_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]
DEFAULT_CLOCK = "2026-06-14T00:00:00Z"


# ─── Tier 0: Clock + atomic catalog/inventory creators ─────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Pin the server clock (PRD §3.10). Returns the response (data may be empty)."""
    return api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)


def create_booth_model(**overrides):
    return get_success_data(api_client.create_booth_model(create_booth_model_payload(**overrides), ADMIN))


def create_package(booth_model_id, **overrides):
    return get_success_data(
        api_client.create_package(create_package_payload(booth_model_id, **overrides), ADMIN))


def create_booth(booth_model_id, asset_tag="BTH-001", **overrides):
    return get_success_data(
        api_client.create_booth(create_booth_payload(booth_model_id, asset_tag, **overrides), OPS))


def create_attendant(full_name="Sam Staff", **overrides):
    return get_success_data(
        api_client.create_attendant(create_attendant_payload(full_name, **overrides), OPS))


def create_add_on(code="PROPS", name="Prop Box", unit_price=50.00, **overrides):
    return get_success_data(
        api_client.create_add_on(create_add_on_payload(code, name, unit_price, **overrides), ADMIN))


def create_customer(email="c1@x.com", full_name="Cara One", **overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(email, full_name, **overrides),
                                   TEST_USERS["customer_headers"]))


def create_booking(customer_id, package_id, **overrides):
    return get_success_data(
        api_client.create_booking(create_booking_payload(customer_id, package_id, **overrides),
                                  make_customer_headers(customer_id)))


def add_add_on_line(booking_id, customer_id, add_on_id, qty=1):
    return get_success_data(
        api_client.add_booking_add_on(booking_id,
                                      create_booking_add_on_payload(add_on_id, qty),
                                      make_customer_headers(customer_id)))


# ─── Tier 1: Catalog scaffolding (the recurring preamble) ──────────────

def seed_model_and_package(package_overrides=None, model_overrides=None):
    """Create one booth model + one package on it. Returns (model, package)."""
    model = create_booth_model(**(model_overrides or {}))
    package = create_package(model["id"], **(package_overrides or {}))
    return model, package


def seed_base_scenario(package_overrides=None, with_booth=True, asset_tag="BTH-001"):
    """Clock + model + package + (optional) one booth + one customer.
    Returns dict(model, package, booth, customer)."""
    set_clock()
    model, package = seed_model_and_package(package_overrides=package_overrides)
    booth = create_booth(model["id"], asset_tag) if with_booth else None
    customer = create_customer()
    return {"model": model, "package": package, "booth": booth, "customer": customer}


# ─── Tier 2: Money helpers (dynamic deposit) ───────────────────────────

def pay_deposit(booking_id):
    """Read the booking's computed deposit_due and pay exactly it as a DEPOSIT.
    Returns (payment, booking_after)."""
    booking = get_success_data(api_client.get_booking(booking_id, OPS))
    deposit = booking["deposit_due"]
    pay = get_success_data(api_client.create_payment(
        booking_id, create_payment_payload("DEPOSIT", deposit), FINANCE))
    after = get_success_data(api_client.get_booking(booking_id, OPS))
    return pay, after


def pay_balance(booking_id):
    """Read the booking's current balance_due and pay exactly it as a BALANCE.
    Returns (payment, booking_after)."""
    booking = get_success_data(api_client.get_booking(booking_id, OPS))
    balance = booking["balance_due"]
    pay = get_success_data(api_client.create_payment(
        booking_id, create_payment_payload("BALANCE", balance), FINANCE))
    after = get_success_data(api_client.get_booking(booking_id, OPS))
    return pay, after


# ─── Tier 3: Booking lifecycle shortcuts ───────────────────────────────

def create_deposit_paid_booking(scenario=None, booking_overrides=None, add_ons=None):
    """A DRAFT booking with its deposit paid (payment_status DEPOSIT_PAID).
    `add_ons` is a list of (code, name, unit_price, qty, requires_attendant, max_qty)
    spec dicts; lines are added while DRAFT before the deposit is paid.
    Returns dict(scenario, booking, add_on_lines)."""
    sc = scenario or seed_base_scenario()
    customer = sc["customer"]
    booking = create_booking(customer["id"], sc["package"]["id"], **(booking_overrides or {}))
    lines = []
    for spec in (add_ons or []):
        ao = create_add_on(
            code=spec["code"], name=spec.get("name", spec["code"]),
            unit_price=spec["unit_price"],
            **{k: spec[k] for k in ("requires_attendant", "max_qty") if k in spec})
        line = add_add_on_line(booking["id"], customer["id"], ao["id"], spec.get("qty", 1))
        lines.append((ao, line))
    pay_deposit(booking["id"])
    booking = get_success_data(api_client.get_booking(booking["id"], OPS))
    return {"scenario": sc, "booking": booking, "add_on_lines": lines}


def confirm_booking(booking_id, booth_id=None):
    """Confirm a DEPOSIT_PAID DRAFT booking. expected_booth_version is read live from
    the candidate booth (the booth the selector will pick). When booth_id is omitted,
    the version is read from the booking's scenario booth. Returns booking_after."""
    booth_version = get_success_data(api_client.get_booth(booth_id, OPS))["version"]
    get_success_data(api_client.confirm_booking(
        booking_id, {"expected_booth_version": booth_version}, OPS))
    return get_success_data(api_client.get_booking(booking_id, OPS))


def create_confirmed_booking(scenario=None, booking_overrides=None, add_ons=None):
    """Booking driven through to CONFIRMED. Returns dict(scenario, booking, add_on_lines)."""
    built = create_deposit_paid_booking(scenario, booking_overrides, add_ons)
    booth = built["scenario"]["booth"]
    built["booking"] = confirm_booking(built["booking"]["id"], booth["id"])
    return built


def get_event_log_for_booking(booking_id):
    logs = get_success_data(api_client.list_booking_event_logs(booking_id, OPS))
    return logs[0]


def start_service(booking_id):
    """Move CONFIRMED -> IN_SERVICE; creates the OPEN EventLog. Returns (booking, event_log)."""
    get_success_data(api_client.start_service(booking_id, OPS))
    booking = get_success_data(api_client.get_booking(booking_id, OPS))
    log = get_event_log_for_booking(booking_id)
    return booking, log


def create_in_service_booking(scenario=None, booking_overrides=None, add_ons=None):
    """Booking driven through to IN_SERVICE with an OPEN EventLog.
    Returns dict(scenario, booking, add_on_lines, event_log)."""
    built = create_confirmed_booking(scenario, booking_overrides, add_ons)
    booking, log = start_service(built["booking"]["id"])
    built["booking"] = booking
    built["event_log"] = log
    return built


def finalize_event_log(log_id, actual_setup_start, actual_coverage_start,
                       actual_coverage_end, actual_teardown_end, actual_print_count):
    """Finalize the EventLog with the live version. Returns (event_log_after, booking_after)."""
    log = get_success_data(api_client.get_event_log(log_id, OPS))
    booking_id = log["booking_id"]
    payload = create_finalize_payload(
        actual_setup_start, actual_coverage_start, actual_coverage_end,
        actual_teardown_end, actual_print_count, log["version"])
    log_after = get_success_data(api_client.finalize_event_log(log_id, payload, OPS))
    booking_after = get_success_data(api_client.get_booking(booking_id, OPS))
    return log_after, booking_after


def create_finalized_booking(scenario=None, booking_overrides=None, add_ons=None,
                             actuals=None):
    """Booking IN_SERVICE with its EventLog FINALIZED (final_subtotal + balance_due set).
    `actuals` overrides the default zero-overtime/zero-idle/zero-overage timestamps.
    Returns dict(scenario, booking, add_on_lines, event_log)."""
    built = create_in_service_booking(scenario, booking_overrides, add_ons)
    a = {
        "actual_setup_start": "2026-09-12T18:00:00Z",
        "actual_coverage_start": "2026-09-12T18:00:00Z",
        "actual_coverage_end": "2026-09-12T22:00:00Z",
        "actual_teardown_end": "2026-09-12T22:30:00Z",
        "actual_print_count": 200,
    }
    a.update(actuals or {})
    log_after, booking_after = finalize_event_log(
        built["event_log"]["id"], a["actual_setup_start"], a["actual_coverage_start"],
        a["actual_coverage_end"], a["actual_teardown_end"], a["actual_print_count"])
    built["event_log"] = log_after
    built["booking"] = booking_after
    return built


def create_paid_in_full_booking(scenario=None, booking_overrides=None, add_ons=None,
                                actuals=None):
    """Booking IN_SERVICE, finalized, and BALANCE-paid to PAID_IN_FULL.
    Returns dict(scenario, booking, add_on_lines, event_log)."""
    built = create_finalized_booking(scenario, booking_overrides, add_ons, actuals)
    pay_balance(built["booking"]["id"])
    built["booking"] = get_success_data(api_client.get_booking(built["booking"]["id"], OPS))
    return built


def create_completed_booking(scenario=None, booking_overrides=None, add_ons=None,
                             actuals=None):
    """Full lifecycle through COMPLETED (Gallery DRAFT created).
    Returns dict(scenario, booking, add_on_lines, event_log, gallery)."""
    built = create_paid_in_full_booking(scenario, booking_overrides, add_ons, actuals)
    get_success_data(api_client.complete_booking(built["booking"]["id"], OPS))
    built["booking"] = get_success_data(api_client.get_booking(built["booking"]["id"], OPS))
    galleries = get_success_data(api_client.list_booking_galleries(built["booking"]["id"], OPS))
    built["gallery"] = galleries[0]
    return built


# ─── Tier 4: Gallery state shortcuts ───────────────────────────────────

def upload_photos(gallery_id, count):
    return get_success_data(api_client.upload_gallery_photos(gallery_id, {"count": count}, OPS))


def create_published_gallery(scenario=None, photos=12, booking_overrides=None):
    """A COMPLETED/PAID booking whose Gallery has photos uploaded and is PUBLISHED.
    Returns dict(scenario, booking, gallery)."""
    built = create_completed_booking(scenario, booking_overrides)
    upload_photos(built["gallery"]["id"], photos)
    built["gallery"] = get_success_data(api_client.publish_gallery(built["gallery"]["id"], OPS))
    return built


# ─── Tier 5: Cancellation shortcuts ────────────────────────────────────

def cancel_confirmed_booking(booking_id, customer_id):
    """Cancel a CONFIRMED booking as its owning customer. Returns booking_after."""
    get_success_data(api_client.cancel_booking(booking_id, make_customer_headers(customer_id)))
    return get_success_data(api_client.get_booking(booking_id, OPS))
