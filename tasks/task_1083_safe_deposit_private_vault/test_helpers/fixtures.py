"""Composite setup helpers.

These encapsulate the multi-step API sequences required to drive the vault
system into the states that tests assert against. Every helper builds its
preconditions from scratch (the server DB is empty at the start of each test)
using only PRD-declared endpoints, and uses get_success_data() so that a broken
precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as F
from .test_users import (
    make_vault_admin_headers,
    make_billing_clerk_headers,
    make_vault_officer_headers,
    make_compliance_officer_headers,
    TEST_USERS,
)
from .constants import CLOCK_DEFAULT

ADMIN = TEST_USERS["vault_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
OFFICER = TEST_USERS["vault_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

# Distinct opaque identities for segregation-of-duties on drilling (§2.9).
DRILL_REQUESTER = make_vault_admin_headers("admin-1")
DRILL_APPROVER = make_compliance_officer_headers("comp-1")


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def create_branch(api, **overrides) -> dict:
    return get_success_data(api.create_branch(F.create_branch_payload(**overrides), ADMIN))


def create_box_type(api, **overrides) -> dict:
    return get_success_data(api.create_box_type(F.create_box_type_payload(**overrides), ADMIN))


def create_box(api, branch_id: str, box_type_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_box(F.create_box_payload(branch_id, box_type_id, **overrides), ADMIN)
    )


def create_renter(api, verified: bool = True, **overrides) -> dict:
    renter = get_success_data(api.create_renter(F.create_renter_payload(**overrides), ADMIN))
    if verified:
        renter = get_success_data(api.verify_kyc(renter["id"], {"decision": "VERIFY"}, COMPLIANCE))
    return renter


def create_rental(api, box_id: str, renter_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_rental(F.create_rental_payload(box_id, renter_id, **overrides), ADMIN)
    )


def get_first_invoice(api, rental_id: str) -> dict:
    resp = api.list_invoices(ADMIN, params={"rental_id": rental_id})
    data = get_success_data(resp)
    invoices = data if isinstance(data, list) else data.get("data", data)
    assert invoices, f"expected at least one invoice for rental {rental_id}"
    return invoices[0]


# --------------------------------------------------------------------------
# Tier 2/3: Active-rental scenarios
# --------------------------------------------------------------------------
def setup_active_rental(api, box_type_overrides=None, rental_overrides=None,
                        branch_overrides=None) -> dict:
    """Branch + box-type + box + verified renter + ACTIVE rental (first invoice issued).

    Returns a context dict: branch, box_type, box, renter, rental (activated).
    """
    branch = create_branch(api, **(branch_overrides or {}))
    box_type = create_box_type(api, **(box_type_overrides or {}))
    box = create_box(api, branch["id"], box_type["id"])
    renter = create_renter(api)
    rental = create_rental(api, box["id"], renter["id"], **(rental_overrides or {}))
    rental = get_success_data(api.activate_rental(rental["id"], ADMIN))
    return {
        "branch": branch, "box_type": box_type, "box": box,
        "renter": renter, "rental": rental,
    }


def setup_two_active_rentals(api, capacity: int = 2) -> dict:
    """One branch with two boxes and two ACTIVE rentals (distinct verified renters).

    Returns: branch, box_type, box1, box2, rental1, rental2.
    """
    branch = create_branch(api, viewing_room_capacity=capacity)
    box_type = create_box_type(api)
    box1 = create_box(api, branch["id"], box_type["id"])
    box2 = create_box(api, branch["id"], box_type["id"])
    renter1 = create_renter(api)
    renter2 = create_renter(api)
    rental1 = create_rental(api, box1["id"], renter1["id"])
    rental1 = get_success_data(api.activate_rental(rental1["id"], ADMIN))
    rental2 = create_rental(api, box2["id"], renter2["id"])
    rental2 = get_success_data(api.activate_rental(rental2["id"], ADMIN))
    return {
        "branch": branch, "box_type": box_type,
        "box1": box1, "box2": box2,
        "renter1": renter1, "renter2": renter2,
        "rental1": rental1, "rental2": rental2,
    }


def setup_shared_box_two_rentals(api) -> dict:
    """One box; rentalA ACTIVE (box RENTED); rentalB PENDING on the SAME box.

    Returns: branch, box_type, box, rentalA (active), rentalB (pending).
    """
    branch = create_branch(api)
    box_type = create_box_type(api)
    box = create_box(api, branch["id"], box_type["id"])
    renterA = create_renter(api)
    renterB = create_renter(api)
    rentalA = create_rental(api, box["id"], renterA["id"])
    rentalA = get_success_data(api.activate_rental(rentalA["id"], ADMIN))
    rentalB = create_rental(api, box["id"], renterB["id"])
    return {
        "branch": branch, "box_type": box_type, "box": box,
        "renterA": renterA, "renterB": renterB,
        "rentalA": rentalA, "rentalB": rentalB,
    }


def count_rented_boxes(api, branch_id: str) -> int:
    """Count boxes at a branch currently in RENTED status (physical occupancy)."""
    resp = api.list_boxes(ADMIN, params={"branch_id": branch_id, "status": "RENTED"})
    data = get_success_data(resp)
    boxes = data if isinstance(data, list) else data.get("data", data)
    return len(boxes)


def setup_pending_rental(api, box_type_overrides=None, rental_overrides=None,
                         verified: bool = True) -> dict:
    """Branch + box-type + box + renter + PENDING (not activated) rental."""
    branch = create_branch(api)
    box_type = create_box_type(api, **(box_type_overrides or {}))
    box = create_box(api, branch["id"], box_type["id"])
    renter = create_renter(api, verified=verified)
    rental = create_rental(api, box["id"], renter["id"], **(rental_overrides or {}))
    return {
        "branch": branch, "box_type": box_type, "box": box,
        "renter": renter, "rental": rental,
    }


def pay_full_and_clear(api, rental_id: str, amount_cents: int, invoice_id=None):
    """Create a payment for amount_cents and clear it (drives balance / cure cascades)."""
    payload = F.create_payment_payload(rental_id, amount_cents, method="WIRE")
    if invoice_id is not None:
        payload["invoice_id"] = invoice_id
    payment = get_success_data(api.create_payment(payload, CLERK))
    payment = get_success_data(api.clear_payment(payment["id"], CLERK))
    return payment


# --------------------------------------------------------------------------
# Tier 1/4: Delinquency progression
# --------------------------------------------------------------------------
def setup_delinquent_rental(api, clock_iso: str = "2026-06-15T00:00:00Z") -> dict:
    """ACTIVE rental driven to DELINQUENT via the billing cycle at clock_iso.

    Default clock 2026-06-15 → invoice due 2026-05-31 → days_past_due == 15 ==
    grace, so the rental escalates to DELINQUENT (late fee 2500 min-clamped,
    balance 26500) and the box cascades to DELINQUENT.
    """
    ctx = setup_active_rental(api)
    set_clock(api, clock_iso)
    get_success_data(api.run_billing_cycle(ADMIN))
    ctx["rental"] = get_success_data(api.get_rental(ctx["rental"]["id"], ADMIN))
    ctx["box"] = get_success_data(api.get_box(ctx["box"]["id"], ADMIN))
    return ctx


def setup_scheduled_drilling(api, clock_iso: str = "2026-07-10T00:00:00Z",
                             drilling_fee_cents=None, with_grant: bool = False,
                             grant_suspended: bool = False) -> dict:
    """Delinquent rental with a DrillingOrder walked to SCHEDULED (box DRILL_PENDING).

    Requester X-User-ID = admin-1, approver X-User-ID = comp-1 (distinct, so the
    segregation-of-duties gate passes). Optionally attach an ACTIVE (or SUSPENDED)
    CO_RENTER grant before delinquency for cascade tests.
    """
    ctx = setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    box_id = ctx["box"]["id"]

    if with_grant:
        grant = get_success_data(api.create_access_grant(
            F.create_access_grant_payload(rental_id, "CO_RENTER", "Jo Deputy",
                                          dual_control_required=True), ADMIN))
        grant = get_success_data(api.activate_grant(grant["id"], {}, COMPLIANCE))
        if grant_suspended:
            grant = get_success_data(api.suspend_grant(grant["id"], ADMIN))
        ctx["grant"] = grant

    set_clock(api, clock_iso)
    get_success_data(api.run_billing_cycle(ADMIN))

    do_payload = F.create_drilling_order_payload(box_id, rental_id, "DELINQUENCY")
    if drilling_fee_cents is not None:
        do_payload["drilling_fee_cents"] = drilling_fee_cents
    order = get_success_data(api.create_drilling_order(do_payload, DRILL_REQUESTER))
    order = get_success_data(api.approve_drilling_order(order["id"], DRILL_APPROVER))
    order = get_success_data(
        api.schedule_drilling_order(order["id"], {"scheduled_at": "2026-07-11T09:00:00Z"}, ADMIN))
    ctx["order"] = order
    ctx["box"] = get_success_data(api.get_box(box_id, ADMIN))
    ctx["rental"] = get_success_data(api.get_rental(rental_id, ADMIN))
    return ctx


# --------------------------------------------------------------------------
# Appointments
# --------------------------------------------------------------------------
def book_appointment(api, box_id: str, rental_id: str, start: str, end: str, **overrides) -> dict:
    return get_success_data(api.create_appointment(
        F.create_appointment_payload(box_id, rental_id, start, end, **overrides), OFFICER))


def setup_active_rental_with_booked_appointment(
        api, start: str = "2026-05-02T10:00:00Z", end: str = "2026-05-02T11:00:00Z") -> dict:
    """ACTIVE rental plus a BOOKED future appointment on its box."""
    ctx = setup_active_rental(api)
    ctx["appointment"] = book_appointment(api, ctx["box"]["id"], ctx["rental"]["id"], start, end)
    return ctx


def setup_checked_in_appointment(api, start: str = "2026-05-01T10:00:00Z",
                                 end: str = "2026-05-01T11:00:00Z") -> dict:
    """ACTIVE rental with an appointment booked then CHECKED_IN (ready for access-event logging)."""
    ctx = setup_active_rental(api)
    appt = book_appointment(api, ctx["box"]["id"], ctx["rental"]["id"], start, end)
    appt = get_success_data(api.check_in_appointment(appt["id"], OFFICER))
    ctx["appointment"] = appt
    return ctx


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
def declare_precious_metal(api, rental_id: str, declared_value_cents: int,
                           weight_grams: float = 100, purity: float = 0.999, **overrides) -> dict:
    return get_success_data(api.create_inventory_item(
        F.create_precious_metal_payload(rental_id, declared_value_cents,
                                        weight_grams=weight_grams, purity=purity, **overrides),
        OFFICER))
