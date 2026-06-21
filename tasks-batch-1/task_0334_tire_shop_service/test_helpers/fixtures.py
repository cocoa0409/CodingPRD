"""Composite setup helpers for the Tire Shop & Service test suite.

Each test runs against a freshly launched empty server, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so a setup failure surfaces as a clear error.

Identity threading: Customer is entity-backed, so any ownership-gated call uses
make_customer_headers(customer["id"]). All other roles are opaque operator identities.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
TECH = TEST_USERS["technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]

# Unique-email generator so repeated customer creates in one test never collide.
_email_counter = itertools.count(1)


def _unique_email() -> str:
    return f"cust{next(_email_counter)}-{id(object())}@example.com"


# ---------------------------------------------------------------------------
# Tier 0 — base entity builders
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    # PRD §3.1: email must be unique across all customers. The factory injects a
    # fixed default email, so callers that don't explicitly override it would
    # collide on the second create. Generate a unique email unless the caller
    # passed one explicitly.
    overrides.setdefault("email", _unique_email())
    payload = F.create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, ADVISOR))


def create_vehicle(customer_id, **overrides) -> dict:
    payload = F.create_vehicle_payload(customer_id, **overrides)
    return get_success_data(api_client.create_vehicle(payload, ADVISOR))


def create_tire_model(**overrides) -> dict:
    payload = F.create_tire_model_payload(**overrides)
    return get_success_data(api_client.create_tire_model(payload, INV))


def create_fitment_rule(vehicle_id, tire_model_id, grade="OE_EXACT") -> dict:
    payload = F.create_fitment_rule_payload(vehicle_id, tire_model_id, fitment_grade=grade)
    return get_success_data(api_client.create_fitment_rule(payload, INV))


def create_service_bay(**overrides) -> dict:
    payload = F.create_service_bay_payload(**overrides)
    payload.setdefault("bay_name", f"Bay-{next(_email_counter)}")
    return get_success_data(api_client.create_service_bay(payload, INV))


def create_work_order(customer_id, vehicle_id, **overrides) -> dict:
    payload = F.create_work_order_payload(customer_id, vehicle_id, **overrides)
    return get_success_data(api_client.create_work_order(payload, ADVISOR))


# ---------------------------------------------------------------------------
# Tier 1 — customer + vehicle + fitted tire model
# ---------------------------------------------------------------------------
def setup_customer_vehicle_tire(tire_overrides=None, grade="OE_EXACT",
                                vehicle_overrides=None):
    """Create a Customer, a Vehicle they own, a TireModel, and a FitmentRule
    linking them at the given grade. Returns (customer, vehicle, tire_model)."""
    tire_overrides = tire_overrides or {}
    vehicle_overrides = vehicle_overrides or {}
    customer = create_customer()
    vehicle = create_vehicle(customer["id"], **vehicle_overrides)
    tire = create_tire_model(**tire_overrides)
    create_fitment_rule(vehicle["id"], tire["id"], grade=grade)
    return customer, vehicle, tire


# ---------------------------------------------------------------------------
# Tier 2 — DRAFT work order carrying lines
# ---------------------------------------------------------------------------
def add_tire_line(work_order, tire_model_id, quantity=4, road_hazard_opted=False):
    """Append a TIRE line to a DRAFT order, threading expected_work_order_version.
    Returns the created line dict (which carries the bumped order version)."""
    payload = F.create_tire_line_payload(
        tire_model_id, work_order["version"],
        quantity=quantity, road_hazard_opted=road_hazard_opted,
    )
    line = get_success_data(api_client.add_work_order_line(work_order["id"], payload, ADVISOR))
    work_order["version"] = line["version"]
    return line


def add_service_line(work_order, line_type, quantity=1):
    """Append a non-TIRE service line to a DRAFT order. Returns the created line."""
    payload = F.create_service_line_payload(line_type, work_order["version"], quantity=quantity)
    line = get_success_data(api_client.add_work_order_line(work_order["id"], payload, ADVISOR))
    work_order["version"] = line["version"]
    return line


def setup_draft_order_with_tire_line(quantity=4, road_hazard_opted=False,
                                     tire_overrides=None, grade="OE_EXACT"):
    """Customer + vehicle + fitted tire + DRAFT order + one TIRE line.
    Returns (customer, vehicle, tire, work_order, line)."""
    customer, vehicle, tire = setup_customer_vehicle_tire(
        tire_overrides=tire_overrides, grade=grade)
    work_order = create_work_order(customer["id"], vehicle["id"])
    line = add_tire_line(work_order, tire["id"], quantity=quantity,
                         road_hazard_opted=road_hazard_opted)
    return customer, vehicle, tire, work_order, line


# ---------------------------------------------------------------------------
# Tier 3 — approved / payment / lifecycle shortcuts
# ---------------------------------------------------------------------------
def approve_order(work_order):
    """Approve a DRAFT order, threading its version. Returns the approved order dict."""
    approved = get_success_data(api_client.approve_work_order(
        work_order["id"], {"expected_work_order_version": work_order["version"]}, ADVISOR))
    work_order["version"] = approved["version"]
    return approved


def setup_approved_order_with_tire_line(quantity=4, road_hazard_opted=False,
                                        tire_overrides=None, grade="OE_EXACT",
                                        wo_overrides=None):
    """Build through to an APPROVED order with one TIRE line.
    Returns (customer, vehicle, tire, work_order, line, approved)."""
    tire_overrides = tire_overrides or {}
    wo_overrides = wo_overrides or {}
    customer, vehicle, tire = setup_customer_vehicle_tire(
        tire_overrides=tire_overrides, grade=grade)
    work_order = create_work_order(customer["id"], vehicle["id"], **wo_overrides)
    line = add_tire_line(work_order, tire["id"], quantity=quantity,
                         road_hazard_opted=road_hazard_opted)
    approved = approve_order(work_order)
    return customer, vehicle, tire, work_order, line, approved


def authorize_payment(work_order):
    data = get_success_data(api_client.authorize_payment(work_order["id"], ADVISOR))
    work_order["version"] = data["version"]
    return data


def setup_approved_authorized_order(quantity=4, tire_overrides=None):
    """APPROVED order with payment_status AUTHORIZED.
    Returns (customer, vehicle, tire, work_order, line)."""
    customer, vehicle, tire, work_order, line, _ = setup_approved_order_with_tire_line(
        quantity=quantity, tire_overrides=tire_overrides)
    authorize_payment(work_order)
    return customer, vehicle, tire, work_order, line


# ---------------------------------------------------------------------------
# Tier 4 — appointments / bays
# ---------------------------------------------------------------------------
def book_appointment(work_order, service_bay, scheduled_start, scheduled_end):
    """Book an appointment against a bay, threading expected_service_bay_version.
    Returns the created appointment dict; updates the bay's tracked version."""
    payload = F.create_appointment_payload(
        work_order["id"], service_bay["id"], scheduled_start, scheduled_end,
        service_bay["version"])
    appt = get_success_data(api_client.create_appointment(payload, ADVISOR))
    service_bay["version"] = service_bay["version"] + 1
    return appt


def setup_scheduled_appointment(scheduled_start="2026-09-01T09:00:00.000Z",
                                scheduled_end="2026-09-01T10:00:00.000Z",
                                bay_overrides=None, authorize=True, quantity=4):
    """APPROVED (optionally AUTHORIZED) order with a SCHEDULED appointment on an OPEN bay.
    Returns (customer, vehicle, tire, work_order, line, bay, appointment)."""
    bay_overrides = bay_overrides or {}
    customer, vehicle, tire, work_order, line, _ = setup_approved_order_with_tire_line(
        quantity=quantity)
    if authorize:
        authorize_payment(work_order)
    bay = create_service_bay(**bay_overrides)
    appt = book_appointment(work_order, bay, scheduled_start, scheduled_end)
    return customer, vehicle, tire, work_order, line, bay, appt


def setup_checked_in_in_service_order(scheduled_start="2026-09-02T09:00:00.000Z",
                                      scheduled_end="2026-09-02T10:00:00.000Z",
                                      authorize=True):
    """APPROVED + (AUTHORIZED) order, checked-in appointment, service started (IN_SERVICE).
    Returns (customer, vehicle, tire, work_order, line, bay, appointment)."""
    customer, vehicle, tire, work_order, line, bay, appt = setup_scheduled_appointment(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, authorize=authorize)
    get_success_data(api_client.check_in_appointment(appt["id"], TECH))
    started = get_success_data(api_client.start_service(work_order["id"], TECH))
    work_order["version"] = started.get("version", work_order["version"])
    return customer, vehicle, tire, work_order, line, bay, appt


# ---------------------------------------------------------------------------
# Tier 5 — store-credit seeding & claims
# ---------------------------------------------------------------------------
def seed_store_credit_2500(customer, vehicle, tire):
    """Seed exactly 2500 cents of store credit via a PAID STORE_CREDIT mileage claim.

    Uses a tire priced 15000 with warranty 30000, miles 25000:
    remaining = 1 - 25000/30000 = 1/6, per_tire = round_half_up(15000/6=2500) = 2500,
    qty 1 -> 2500. Requires the supplied tire to have unit_price 15000 & warranty 30000.
    """
    wo = create_work_order(customer["id"], vehicle["id"])
    line = add_tire_line(wo, tire["id"], quantity=1)
    approve_order(wo)
    claim = get_success_data(api_client.create_mileage_claim(
        F.create_mileage_claim_payload(line["id"], tire["id"],
                                       measured_tread_32nds=2, miles_driven=25000,
                                       payout_method="STORE_CREDIT", claim_quantity=1),
        ADVISOR))
    get_success_data(api_client.approve_mileage_claim(claim["id"], ADVISOR))
    get_success_data(api_client.pay_mileage_claim(claim["id"], ADVISOR))


def setup_submitted_mileage_claim(measured_tread_32nds=2, miles_driven=10000,
                                  payout_method="REFUND", claim_quantity=4,
                                  tire_overrides=None, quantity=4):
    """APPROVED order with a TIRE line (COMMITTED), then a SUBMITTED MileageWarrantyClaim
    on that line. Returns (customer, vehicle, tire, work_order, line, claim)."""
    customer, vehicle, tire, work_order, line, _ = setup_approved_order_with_tire_line(
        quantity=quantity, tire_overrides=tire_overrides)
    claim = get_success_data(api_client.create_mileage_claim(
        F.create_mileage_claim_payload(
            line["id"], tire["id"],
            measured_tread_32nds=measured_tread_32nds, miles_driven=miles_driven,
            payout_method=payout_method, claim_quantity=claim_quantity),
        ADVISOR))
    return customer, vehicle, tire, work_order, line, claim


def setup_special_order(requested_quantity=4, tire_overrides=None):
    """DRAFT order with a TIRE line for an out-of-stock tire, plus an ORDERED SpecialOrder
    against that line. Returns (customer, vehicle, tire, work_order, line, special_order)."""
    overrides = {"stock_qty": 0}
    if tire_overrides:
        overrides.update(tire_overrides)
    customer, vehicle, tire = setup_customer_vehicle_tire(tire_overrides=overrides)
    work_order = create_work_order(customer["id"], vehicle["id"])
    line = add_tire_line(work_order, tire["id"], quantity=requested_quantity)
    so = get_success_data(api_client.create_special_order(
        F.create_special_order_payload(line["id"], tire["id"],
                                       requested_quantity=requested_quantity), ADVISOR))
    return customer, vehicle, tire, work_order, line, so
