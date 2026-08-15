"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Identity threading: entity-backed roles always build
headers from the created entity's id via make_driver_headers /
make_fleet_manager_headers.
"""
import datetime

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_amenity_product_payload,
    create_booking_amenity_payload,
    create_booking_payload,
    create_driver_authorization_payload,
    create_driver_payload,
    create_fleet_account_payload,
    create_incident_payload,
    create_site_payload,
    create_stall_payload,
    create_waitlist_entry_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_fleet_manager_headers,
    make_site_operator_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
OP_ALICE = TEST_USERS["site_operator_headers"]
OP_BOB = make_site_operator_headers("op-bob")


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


def _date_plus(date_str, days):
    return (datetime.date.fromisoformat(date_str)
            + datetime.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Tier 1 — clock, sites, stalls, drivers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (inert by itself; no sweeps run implicitly)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def create_site(name="S", base_nightly_rate_cents=5000, **overrides):
    resp = api_client.create_site(
        create_site_payload(name=name,
                            base_nightly_rate_cents=base_nightly_rate_cents,
                            **overrides),
        ADMIN,
    )
    return _ok("create_site", resp)


def create_stall(site_id, stall_number, stall_class="STANDARD",
                 is_reservable=True):
    resp = api_client.create_stall(
        site_id,
        create_stall_payload(stall_number, stall_class=stall_class,
                             is_reservable=is_reservable),
        ADMIN,
    )
    return _ok("create_stall", resp)


def create_site_with_stalls(num_reservable=1, num_first_come=0, base=5000,
                            name="S", reservable_prefix="R",
                            first_come_prefix="F", **site_overrides):
    """Create a site plus stalls. Returns dict(site, reservable, first_come)."""
    site = create_site(name=name, base_nightly_rate_cents=base,
                       **site_overrides)
    reservable = [
        create_stall(site["id"], f"{reservable_prefix}{i:02d}",
                     is_reservable=True)
        for i in range(1, num_reservable + 1)
    ]
    first_come = [
        create_stall(site["id"], f"{first_come_prefix}{i:02d}",
                     is_reservable=False)
        for i in range(1, num_first_come + 1)
    ]
    return {"site": site, "reservable": reservable, "first_come": first_come,
            "stalls": reservable + first_come}


def register_driver(cdl_number, full_name="Test Driver"):
    resp = api_client.register_driver(
        create_driver_payload(cdl_number, full_name), ANON)
    return _ok("register_driver", resp)


def register_drivers(count, cdl_prefix):
    """Register `count` drivers with unique CDL numbers. Returns driver list."""
    return [
        register_driver(f"{cdl_prefix}-{i}", f"Driver {cdl_prefix}-{i}")
        for i in range(1, count + 1)
    ]


def create_amenity_product(site_id, code, price_cents, name=None,
                           nightly_capacity=None):
    payload = create_amenity_product_payload(code, name=name,
                                             price_cents=price_cents)
    if nightly_capacity is not None:
        payload["nightly_capacity"] = nightly_capacity
    resp = api_client.create_amenity_product(site_id, payload, ADMIN)
    return _ok("create_amenity_product", resp)


# ---------------------------------------------------------------------------
# Tier 2 — bookings and the stay lifecycle
# ---------------------------------------------------------------------------

def create_reserved_booking(driver_id, site_id, arrival_date, night_count=1,
                            payment_mode="DRIVER_DIRECT", **overrides):
    resp = api_client.create_booking(
        create_booking_payload(driver_id, site_id, arrival_date,
                               night_count=night_count,
                               booking_kind="RESERVED",
                               payment_mode=payment_mode, **overrides),
        make_driver_headers(driver_id),
    )
    return _ok("create_reserved_booking", resp)


def create_walkin_booking(driver_id, site_id, arrival_date, night_count=1,
                          payment_mode="DRIVER_DIRECT", **overrides):
    resp = api_client.create_booking(
        create_booking_payload(driver_id, site_id, arrival_date,
                               night_count=night_count,
                               booking_kind="WALK_IN",
                               payment_mode=payment_mode, **overrides),
        make_driver_headers(driver_id),
    )
    return _ok("create_walkin_booking", resp)


def check_in(booking_id, driver_id):
    resp = api_client.check_in_booking(booking_id, make_driver_headers(driver_id))
    return _ok("check_in", resp, expected="CHECKED_IN")


def check_out(booking_id, driver_id):
    resp = api_client.check_out_booking(booking_id, {},
                                        make_driver_headers(driver_id))
    return _ok("check_out", resp, expected="CHECKED_OUT")


def settle_booking(booking_id, driver_id, arrival_date, night_count=1,
                   checkin_time="15:30:00", checkout_time="10:00:00"):
    """Drive a booking through check-in and check-out at the given clock
    instants. Returns the CHECKED_OUT booking."""
    set_clock(f"{arrival_date}T{checkin_time}Z")
    check_in(booking_id, driver_id)
    checkout_date = _date_plus(arrival_date, night_count)
    set_clock(f"{checkout_date}T{checkout_time}Z")
    return check_out(booking_id, driver_id)


def add_amenity_line(booking_id, driver_id, amenity_product_id, quantity=1):
    resp = api_client.add_booking_amenity(
        booking_id,
        create_booking_amenity_payload(amenity_product_id, quantity=quantity),
        make_driver_headers(driver_id),
    )
    return _ok("add_amenity_line", resp, expected="RESERVED")


def run_site_ops(site_id, as_headers=None):
    resp = api_client.run_site_ops(site_id, as_headers or ADMIN)
    return _ok("run_site_ops", resp)


# ---------------------------------------------------------------------------
# Tier 3 — fleet accounts, authorizations, invoices
# ---------------------------------------------------------------------------

def create_fleet_account(company_name="Fleet Co",
                         credit_limit_cents=10_000_000,
                         payment_terms_days=30):
    resp = api_client.create_fleet_account(
        create_fleet_account_payload(
            company_name=company_name,
            credit_limit_cents=credit_limit_cents,
            payment_terms_days=payment_terms_days,
        ),
        ADMIN,
    )
    return _ok("create_fleet_account", resp)


def request_authorization(driver_id, fleet_account_id,
                          spend_cap_per_night_cents=None):
    payload = create_driver_authorization_payload(driver_id, fleet_account_id)
    if spend_cap_per_night_cents is not None:
        payload["spend_cap_per_night_cents"] = spend_cap_per_night_cents
    resp = api_client.create_driver_authorization(
        payload, make_driver_headers(driver_id))
    return _ok("request_authorization", resp, expected="PENDING")


def transition_authorization(auth_id, fleet_account_id, to):
    resp = api_client.transition_driver_authorization(
        auth_id, {"to": to}, make_fleet_manager_headers(fleet_account_id))
    return _ok("transition_authorization", resp)


def create_active_authorization(driver_id, fleet_account_id,
                                spend_cap_per_night_cents=None):
    """Driver requests + fleet manager approves. Returns the ACTIVE auth."""
    auth = request_authorization(driver_id, fleet_account_id,
                                 spend_cap_per_night_cents)
    return transition_authorization(auth["id"], fleet_account_id, "ACTIVE")


def setup_fleet_with_active_auth(base=5000, num_reservable=1,
                                 credit_limit_cents=10_000_000,
                                 payment_terms_days=30,
                                 spend_cap_per_night_cents=None,
                                 cdl_number="CDL-FLEET-1"):
    """Site with stalls + fleet account + driver with an ACTIVE authorization.

    Returns dict(site, stalls, fleet, driver, auth).
    """
    ctx = create_site_with_stalls(num_reservable=num_reservable, base=base)
    fleet = create_fleet_account(credit_limit_cents=credit_limit_cents,
                                 payment_terms_days=payment_terms_days)
    driver = register_driver(cdl_number)
    auth = create_active_authorization(driver["id"], fleet["id"],
                                       spend_cap_per_night_cents)
    return {"site": ctx["site"], "stalls": ctx["stalls"], "fleet": fleet,
            "driver": driver, "auth": auth}


def close_billing_period(fleet_account_id, period):
    resp = api_client.close_billing_period(fleet_account_id, {"period": period},
                                           ADMIN)
    return _ok("close_billing_period", resp, expected="ISSUED")


def setup_invoiced_fleet_booking(base=5000, arrival_date="2026-08-03",
                                 night_count=1, period="2026-08",
                                 invoice_clock="2026-09-01T00:00:00Z",
                                 credit_limit_cents=10_000_000,
                                 payment_terms_days=30,
                                 cdl_number="CDL-INV-1"):
    """Full fleet pipeline: site + fleet + ACTIVE auth + a FLEET_BILL booking
    checked in and out inside `period`, then close-billing-period.

    Returns dict(site, stalls, fleet, driver, auth, booking, invoice).
    """
    ctx = setup_fleet_with_active_auth(
        base=base, credit_limit_cents=credit_limit_cents,
        payment_terms_days=payment_terms_days, cdl_number=cdl_number)
    site, fleet, driver = ctx["site"], ctx["fleet"], ctx["driver"]
    set_clock("2026-08-01T00:00:00Z")
    booking = create_reserved_booking(
        driver["id"], site["id"], arrival_date, night_count=night_count,
        payment_mode="FLEET_BILL", fleet_account_id=fleet["id"])
    settled = settle_booking(booking["id"], driver["id"], arrival_date,
                             night_count=night_count)
    set_clock(invoice_clock)
    invoice = close_billing_period(fleet["id"], period)
    return {"site": site, "stalls": ctx["stalls"], "fleet": fleet,
            "driver": driver, "auth": ctx["auth"], "booking": settled,
            "invoice": invoice}


def pay_invoice_exact(invoice_id, fleet_account_id, amount_cents):
    resp = api_client.pay_invoice(invoice_id, {"amount_cents": amount_cents},
                                  make_fleet_manager_headers(fleet_account_id))
    return _ok("pay_invoice_exact", resp)


# ---------------------------------------------------------------------------
# Tier 4 — incidents
# ---------------------------------------------------------------------------

def create_incident(site_id, category, severity, description,
                    reporter_driver_id=None, as_headers=None):
    payload = create_incident_payload(category, severity, description)
    if reporter_driver_id is not None:
        payload["reporter_driver_id"] = reporter_driver_id
        headers = make_driver_headers(reporter_driver_id)
    else:
        headers = as_headers or OP_ALICE
    resp = api_client.create_incident(site_id, payload, headers)
    return _ok("create_incident", resp, expected="OPEN")


def acknowledge_incident(incident_id, as_headers=None):
    resp = api_client.transition_incident(incident_id, {"to": "ACKNOWLEDGED"},
                                          as_headers or OP_ALICE)
    return _ok("acknowledge_incident", resp, expected="ACKNOWLEDGED")


def investigate_incident(incident_id, as_headers=None):
    resp = api_client.transition_incident(incident_id, {"to": "INVESTIGATING"},
                                          as_headers or OP_ALICE)
    return _ok("investigate_incident", resp, expected="INVESTIGATING")


def resolve_incident(incident_id, as_headers=None):
    resp = api_client.transition_incident(incident_id, {"to": "RESOLVED"},
                                          as_headers or OP_BOB)
    return _ok("resolve_incident", resp, expected="RESOLVED")


def setup_investigating_incident(category="SECURITY", severity="HIGH",
                                 ack_headers=None, site_name="S"):
    """Site + one incident acknowledged and under investigation by
    `ack_headers` (default op-alice). Returns dict(site, incident)."""
    site = create_site(name=site_name)
    set_clock("2026-08-10T00:00:00Z")
    inc = create_incident(site["id"], category, severity, "report")
    ack = ack_headers or OP_ALICE
    acknowledge_incident(inc["id"], ack)
    investigate_incident(inc["id"], ack)
    return {"site": site, "incident": inc, "ack_headers": ack}


# ---------------------------------------------------------------------------
# Tier 5 — waitlist offer setups
# ---------------------------------------------------------------------------

def setup_offered_waitlist_entry(arrival_date="2026-08-10", night_count=1,
                                 stall_class="STANDARD"):
    """One-stall site; an owner booking occupies the window; a waiter joins
    the queue; the owner cancels inside the free window, so the entry is
    OFFERED the freed stall. Clock ends at 2026-08-01T00:00:00Z.

    Returns dict(site, stall, owner_driver, owner_booking, waiter_driver,
    entry).
    """
    ctx = create_site_with_stalls(num_reservable=1)
    site, stall = ctx["site"], ctx["reservable"][0]
    owner = register_driver("CDL-WL-OWNER", "Owner")
    waiter = register_driver("CDL-WL-WAITER", "Waiter")
    set_clock("2026-08-01T00:00:00Z")
    owner_booking = create_reserved_booking(owner["id"], site["id"],
                                            arrival_date, night_count)
    entry = _ok(
        "create_waitlist_entry",
        api_client.create_waitlist_entry(
            create_waitlist_entry_payload(
                waiter["id"], site["id"], arrival_date,
                night_count=night_count, stall_class=stall_class),
            make_driver_headers(waiter["id"])),
        expected="QUEUED",
    )
    _ok("cancel_owner_booking",
        api_client.cancel_booking(owner_booking["id"],
                                  make_driver_headers(owner["id"])),
        expected="CANCELLED")
    offered = _ok(
        "get_waitlist_entry",
        api_client.get_waitlist_entry(entry["id"], ADMIN),
        expected="OFFERED",
    )
    return {"site": site, "stall": stall, "owner_driver": owner,
            "owner_booking": owner_booking, "waiter_driver": waiter,
            "entry": offered}
