"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database and
the logical clock at 2026-08-01T00:00:00Z (PRD §2.4), so each helper builds its
preconditions from scratch using only PRD-declared endpoints. ClinicBuyer calls
are always made with make_clinic_buyer_headers(clinic_id) because that role is
entity-backed by Clinic (PRD §2.1).

Setup calls use get_success_data() so a setup failure surfaces a clear
"Setup step failed" error rather than a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_QUARTER,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    create_authorization_payload,
    create_bundle_program_payload,
    create_clinic_payload,
    create_enrollment_payload,
    create_lot_payload,
    create_order_payload,
    create_product_payload,
    create_shipment_payload,
    create_short_date_credit_payload,
    order_line_spec,
)
from .test_users import TEST_USERS, make_clinic_buyer_headers

ACCOUNT_MANAGER = TEST_USERS["account_manager_headers"]
PLANNER = TEST_USERS["supply_chain_planner_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, SYSADMIN))


# ---------------------------------------------------------------------------
# Clinics (PRD §3.1)
# ---------------------------------------------------------------------------

def create_clinic(**overrides) -> dict:
    """Create a clinic in PENDING_VERIFICATION."""
    return get_success_data(
        api_client.create_clinic(create_clinic_payload(**overrides), ACCOUNT_MANAGER))


def create_active_clinic(**overrides) -> dict:
    """Create a clinic and verify it to ACTIVE. Returns the activated clinic."""
    clinic = create_clinic(**overrides)
    return get_success_data(api_client.activate_clinic(clinic["id"], ACCOUNT_MANAGER))


def get_clinic(clinic_id) -> dict:
    return get_success_data(api_client.get_clinic(clinic_id, ACCOUNT_MANAGER))


# ---------------------------------------------------------------------------
# Products and lots (PRD §3.2)
# ---------------------------------------------------------------------------

def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), PLANNER))


def get_product(product_id) -> dict:
    return get_success_data(api_client.get_product(product_id, ACCOUNT_MANAGER))


def create_lot(product_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(create_lot_payload(product_id, **overrides), PLANNER))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ACCOUNT_MANAGER))


def create_stocked_product(lot_qty=10, lot_expiry="2027-06-30",
                           product_overrides=None) -> tuple:
    """LISTED product plus one AVAILABLE lot. Returns (product, lot)."""
    product = create_product(**(product_overrides or {}))
    lot = create_lot(product["id"], qty_on_hand=lot_qty, expiry_date=lot_expiry)
    return product, lot


# ---------------------------------------------------------------------------
# Manufacturer authorizations (PRD §3.3)
# ---------------------------------------------------------------------------

def create_authorization(clinic_id, **overrides) -> dict:
    """Create an authorization in PENDING."""
    payload = create_authorization_payload(clinic_id, **overrides)
    if payload.get("approved_ship_to_address") is None:
        payload["approved_ship_to_address"] = get_clinic(clinic_id)["ship_to_address"]
    return get_success_data(api_client.create_authorization(payload, OFFICER))


def create_approved_authorization(clinic_id, **overrides) -> dict:
    """Create an authorization and approve it (clinic must be ACTIVE)."""
    auth = create_authorization(clinic_id, **overrides)
    return get_success_data(api_client.approve_authorization(auth["id"], OFFICER))


def get_authorization(authorization_id) -> dict:
    return get_success_data(api_client.get_authorization(authorization_id, OFFICER))


# ---------------------------------------------------------------------------
# Orders and lines (PRD §3.4–§3.6)
# ---------------------------------------------------------------------------

def create_order(clinic_id, lines, *, ship_to_address=None,
                 window_start=DEFAULT_WINDOW_START,
                 window_end=DEFAULT_WINDOW_END) -> dict:
    """Create a DRAFT order as the owning ClinicBuyer. Lines are
    [{product_id, qty_requested}, ...]."""
    if ship_to_address is None:
        ship_to_address = get_clinic(clinic_id)["ship_to_address"]
    payload = create_order_payload(
        clinic_id, lines, ship_to_address=ship_to_address,
        delivery_window_start=window_start, delivery_window_end=window_end)
    return get_success_data(
        api_client.create_order(payload, make_clinic_buyer_headers(clinic_id)))


def submit_order(order_id, clinic_id) -> dict:
    return get_success_data(
        api_client.submit_order(order_id, make_clinic_buyer_headers(clinic_id)))


def approve_order(order_id) -> dict:
    return get_success_data(api_client.approve_order(order_id, ACCOUNT_MANAGER))


def cancel_order(order_id, clinic_id=None) -> dict:
    """Cancel as AccountManager (unscoped role) by default."""
    return get_success_data(api_client.cancel_order(order_id, ACCOUNT_MANAGER))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, ACCOUNT_MANAGER))


def order_lines(order_id) -> list:
    return get_success_data(
        api_client.list_order_lines(ACCOUNT_MANAGER, params={"order_id": order_id}))


def sole_line(order_id) -> dict:
    lines = order_lines(order_id)
    assert len(lines) == 1, f"Setup expected exactly one line on order {order_id}"
    return lines[0]


def get_order_line(line_id) -> dict:
    return get_success_data(api_client.get_order_line(line_id, ACCOUNT_MANAGER))


def backorders_of_line(line_id) -> list:
    return get_success_data(api_client.list_backorder_lines(line_id, ACCOUNT_MANAGER))


def sole_backorder(line_id) -> dict:
    backorders = backorders_of_line(line_id)
    assert len(backorders) == 1, (
        f"Setup expected exactly one backorder on line {line_id}, "
        f"got {len(backorders)}")
    return backorders[0]


def create_submitted_order(clinic_id, product_id, qty=1, *,
                           window_start=DEFAULT_WINDOW_START,
                           window_end=DEFAULT_WINDOW_END,
                           ship_to_address=None) -> dict:
    """DRAFT -> SUBMITTED. Returns the submitted order."""
    order = create_order(clinic_id, [order_line_spec(product_id, qty)],
                         ship_to_address=ship_to_address,
                         window_start=window_start, window_end=window_end)
    return submit_order(order["id"], clinic_id)


def create_approved_order(clinic_id, product_id, qty=1, *,
                          window_start=DEFAULT_WINDOW_START,
                          window_end=DEFAULT_WINDOW_END,
                          ship_to_address=None) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED (requires stock covering the line).
    Returns the approved (or backordered) order."""
    submitted = create_submitted_order(
        clinic_id, product_id, qty, window_start=window_start,
        window_end=window_end, ship_to_address=ship_to_address)
    return approve_order(submitted["id"])


# ---------------------------------------------------------------------------
# Shipments (PRD §3.7)
# ---------------------------------------------------------------------------

def create_shipment(order_id, carrier_name="VETEXPRESS", certified=None) -> dict:
    payload = create_shipment_payload(order_id, carrier_name=carrier_name)
    if certified is not None:
        payload["carrier_cold_chain_certified"] = certified
    return get_success_data(api_client.create_shipment(payload, PLANNER))


def dispatch_shipment(shipment_id) -> dict:
    return get_success_data(api_client.dispatch_shipment(shipment_id, PLANNER))


def deliver_shipment(shipment_id) -> dict:
    return get_success_data(api_client.deliver_shipment(shipment_id, PLANNER))


def get_shipment(shipment_id) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, ACCOUNT_MANAGER))


def post_temperature_reading(shipment_id, temperature_celsius,
                             recorded_at="2026-08-03T14:00:00Z") -> dict:
    return get_success_data(api_client.add_temperature_reading(
        shipment_id,
        {"recorded_at": recorded_at, "temperature_celsius": temperature_celsius},
        PLANNER))


def ship_and_deliver(order_id, carrier_name="VETEXPRESS", certified=None) -> dict:
    """Create -> dispatch -> deliver a shipment for an APPROVED order."""
    shipment = create_shipment(order_id, carrier_name=carrier_name, certified=certified)
    dispatch_shipment(shipment["id"])
    return deliver_shipment(shipment["id"])


def create_delivered_line(*, unit_price=2500, qty=1, lot_qty=10,
                          lot_expiry="2027-06-30", product_type="CONSUMABLE",
                          manufacturer_code="GEN", is_controlled_substance=None,
                          window_start=DEFAULT_WINDOW_START,
                          window_end=DEFAULT_WINDOW_END,
                          clinic_overrides=None) -> dict:
    """Full chain: ACTIVE clinic + product + lot + order APPROVED + shipment
    DELIVERED. Returns dict with clinic, product, lot, order, shipment, line."""
    clinic = create_active_clinic(**(clinic_overrides or {}))
    product_overrides = {
        "product_type": product_type,
        "manufacturer_code": manufacturer_code,
        "unit_price_cents": unit_price,
    }
    if is_controlled_substance is not None:
        product_overrides["is_controlled_substance"] = is_controlled_substance
    product = create_product(**product_overrides)
    lot = create_lot(product["id"], qty_on_hand=lot_qty, expiry_date=lot_expiry)
    order = create_approved_order(clinic["id"], product["id"], qty,
                                  window_start=window_start, window_end=window_end)
    shipment = ship_and_deliver(order["id"],
                                certified=(product_type == "VACCINE"))
    line = sole_line(order["id"])
    return {
        "clinic": get_clinic(clinic["id"]),
        "product": product,
        "lot": lot,
        "order": get_order(order["id"]),
        "shipment": get_shipment(shipment["id"]),
        "line": get_order_line(line["id"]),
    }


# ---------------------------------------------------------------------------
# Bundle programs and enrollments (PRD §3.8)
# ---------------------------------------------------------------------------

def create_bundle_program(**overrides) -> dict:
    """Create a program in DRAFT."""
    return get_success_data(api_client.create_bundle_program(
        create_bundle_program_payload(**overrides), ACCOUNT_MANAGER))


def create_active_program(**overrides) -> dict:
    program = create_bundle_program(**overrides)
    return get_success_data(
        api_client.activate_bundle_program(program["id"], ACCOUNT_MANAGER))


def enroll_clinic(clinic_id, program_id, quarter=DEFAULT_QUARTER) -> dict:
    """Enroll a clinic as its owning ClinicBuyer. The OCC field
    expected_clinic_version is read fresh from the clinic record."""
    current_version = get_clinic(clinic_id)["version"]
    payload = create_enrollment_payload(program_id, current_version, quarter)
    return get_success_data(api_client.create_bundle_enrollment(
        clinic_id, payload, make_clinic_buyer_headers(clinic_id)))


def setup_enrolled_clinic(program_overrides=None, clinic_overrides=None,
                          quarter=DEFAULT_QUARTER) -> tuple:
    """ACTIVE clinic + ACTIVE program + ACTIVE enrollment.
    Returns (clinic, program, enrollment)."""
    clinic = create_active_clinic(**(clinic_overrides or {}))
    program = create_active_program(**(program_overrides or {}))
    enrollment = enroll_clinic(clinic["id"], program["id"], quarter)
    return get_clinic(clinic["id"]), program, enrollment


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(
        api_client.get_bundle_enrollment(enrollment_id, ACCOUNT_MANAGER))


def accruals_for_order(order_id) -> list:
    return get_success_data(
        api_client.list_rebate_accruals(ACCOUNT_MANAGER,
                                        params={"order_id": order_id}))


def sole_accrual_for_order(order_id) -> dict:
    accruals = accruals_for_order(order_id)
    assert len(accruals) == 1, (
        f"Setup expected exactly one accrual for order {order_id}, "
        f"got {len(accruals)}")
    return accruals[0]


def get_accrual(accrual_id) -> dict:
    return get_success_data(api_client.get_rebate_accrual(accrual_id, ACCOUNT_MANAGER))


# ---------------------------------------------------------------------------
# Short-date credits (PRD §3.9)
# ---------------------------------------------------------------------------

def create_short_date_credit(clinic_id, order_line_id, lot_id, qty) -> dict:
    payload = create_short_date_credit_payload(order_line_id, lot_id, qty)
    return get_success_data(api_client.create_short_date_credit(
        payload, make_clinic_buyer_headers(clinic_id)))


def get_short_date_credit(credit_id) -> dict:
    return get_success_data(api_client.get_short_date_credit(credit_id, OFFICER))


# ---------------------------------------------------------------------------
# Rx scenario (PRD §3.5)
# ---------------------------------------------------------------------------

def setup_rx_scenario(*, clinic_overrides=None, product_overrides=None,
                      auth_overrides=None, lot_qty=10,
                      lot_expiry="2027-06-30") -> dict:
    """ACTIVE clinic + LISTED RX_PHARMACEUTICAL product + AVAILABLE lot +
    APPROVED authorization whose approved_ship_to_address equals the clinic's
    ship_to_address. Returns dict(clinic, product, lot, authorization)."""
    clinic = create_active_clinic(**(clinic_overrides or {}))
    product_kw = {"product_type": "RX_PHARMACEUTICAL", "manufacturer_code": "ZOETIS",
                  "unit_price_cents": 10000}
    product_kw.update(product_overrides or {})
    product = create_product(**product_kw)
    lot = create_lot(product["id"], qty_on_hand=lot_qty, expiry_date=lot_expiry)
    auth_kw = {"manufacturer_code": product["manufacturer_code"],
               "approved_ship_to_address": clinic["ship_to_address"]}
    auth_kw.update(auth_overrides or {})
    authorization = create_approved_authorization(clinic["id"], **auth_kw)
    return {"clinic": clinic, "product": product, "lot": lot,
            "authorization": authorization}


def setup_shortage_scenario(*, lot_qty=5, order_qty=5) -> dict:
    """ACTIVE clinic; one stocked product; O1 APPROVED consuming the whole lot;
    O2 approved into shortage -> BACKORDERED with an OPEN backorder.
    Returns dict(clinic, product, lot, order1, order2, line2, backorder2)."""
    clinic = create_active_clinic()
    product, lot = create_stocked_product(lot_qty=lot_qty)
    order1 = create_approved_order(clinic["id"], product["id"], order_qty,
                                   window_start="2026-08-03T13:00:00Z",
                                   window_end="2026-08-03T15:00:00Z")
    order2 = create_approved_order(clinic["id"], product["id"], order_qty,
                                   window_start="2026-08-04T13:00:00Z",
                                   window_end="2026-08-04T15:00:00Z")
    line2 = sole_line(order2["id"])
    backorder2 = sole_backorder(line2["id"])
    return {"clinic": clinic, "product": product, "lot": lot,
            "order1": order1, "order2": get_order(order2["id"]),
            "line2": line2, "backorder2": backorder2}
