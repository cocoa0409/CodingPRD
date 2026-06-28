"""Business logic: calculations, state machines, and cascading side effects.

PRD section 3 (Business Logic & Workflows) is the literal contract here. Every
ordering, precondition, and side-effect below traces to a sentence in the PRD.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
import models
from clock import parse_iso8601
from db import store


# ===========================================================================
# Clinic balance recomputation (PRD 3.1, calc clinic_outstanding_balance)
# ===========================================================================
def recompute_clinic_balance(clinic):
    """outstanding = sum(total_cents over this clinic's ISSUED CLINIC_ACCOUNT invoices);
    account_status derived; balance never negative. This is itself a mutation."""
    total = 0
    for inv in store.invoices.values():
        if (inv["clinic_id"] == clinic["id"]
                and inv["bill_to"] == "CLINIC_ACCOUNT"
                and inv["status"] == "ISSUED"):
            total += inv["total_cents"]
    if total < 0:
        total = 0
    clinic["outstanding_balance_cents"] = total
    clinic["account_status"] = "DELINQUENT" if total > clinic["credit_limit_cents"] else "CURRENT"
    models.touch(clinic)


# ===========================================================================
# cremation charge allocation (PRD 3.9, calc case_cremation_charge)
# ===========================================================================
def allocate_charges_on_fire(batch):
    members = models.batch_members(batch)
    if batch["service_type"] == "PRIVATE":
        # PRIVATE batch holds exactly one member.
        for case in members:
            tier = models.compute_weight_tier(case["weight_lbs"])
            charge = models.PRIVATE_RATE[tier]
            if case["expedited"]:
                charge += models.EXPEDITE_SURCHARGE
            case["cremation_charge_cents"] = charge
        # communal_firing_total_cents stays 0 for PRIVATE.
    else:
        batch["communal_firing_total_cents"] = models.COMMUNAL_FIRING_TOTAL_CENTS
        # order members by created_at ascending (tie-break by creation seq).
        ordered = sorted(members, key=lambda c: (c["created_at"], c["_seq"]))
        total_w = sum(c["weight_lbs"] for c in ordered)
        pooled = models.COMMUNAL_FIRING_TOTAL_CENTS
        shares = []
        if total_w == 0:
            shares = [0 for _ in ordered]
        else:
            for c in ordered:
                raw = Decimal(pooled) * Decimal(c["weight_lbs"]) / Decimal(total_w)
                share = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                shares.append(share)
            remainder = pooled - sum(shares)
            shares[-1] += remainder  # last member (created_at ASC) absorbs remainder
        for c, share in zip(ordered, shares):
            c["cremation_charge_cents"] = share


# ===========================================================================
# invoice total (PRD 3.10, calc invoice_total)
# ===========================================================================
def compute_invoice_amounts(case):
    subtotal = case["cremation_charge_cents"]
    for k in store.keepsake_orders.values():
        if k["case_id"] == case["id"] and k["status"] != "CANCELLED":
            subtotal += k["unit_price_cents"]
    for a in store.memorial_addons.values():
        if a["case_id"] == case["id"] and a["status"] != "CANCELLED":
            subtotal += a["price_cents"]

    if case["bill_to"] == "CLINIC_ACCOUNT":
        handling_fee = 0
    else:  # OWNER
        if subtotal < 20000:
            handling_fee = 2500
        elif subtotal <= 50000:
            handling_fee = 1500
        else:
            handling_fee = 0

    total = subtotal + handling_fee
    return subtotal, handling_fee, total


# ===========================================================================
# Cooler slot release helper
# ===========================================================================
def release_cooler_slot(case):
    """Clear case.cooler_id and mutate the holding cooler. Caller appends COOLER_OUT."""
    cooler_id = case.get("cooler_id")
    case["cooler_id"] = None
    if cooler_id is not None:
        cooler = store.coolers.get(cooler_id)
        if cooler is not None:
            # occupied_count/available/status are computed live from cases, but
            # the cooler is mutated (PRD 2.5): refresh updated_at and bump version.
            models.touch(cooler)


# ===========================================================================
# Case custody transitions
# ===========================================================================
def case_create_intake(case):
    """Append the first INTAKE custody event (custodian = pet owner)."""
    owner = store.petowners.get(case["owner_id"])
    custodian = owner["full_name"] if owner else case["owner_id"]
    models.append_custody_event(case, "INTAKE", custodian)


def case_transition_transport(case, origin_kind, origin_label, driver_name):
    """INTAKE_PENDING -> IN_TRANSIT, creating the first transport leg."""
    if case["custody_status"] != "INTAKE_PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not INTAKE_PENDING")
    leg = models.make_transport_leg(case["id"], origin_kind, origin_label, driver_name)
    case["custody_status"] = "IN_TRANSIT"
    models.append_custody_event(case, "TRANSPORT_PICKUP", driver_name)
    models.touch(case)
    return leg


def case_receive(case):
    """IN_TRANSIT -> RECEIVED. Requires an ARRIVED transport leg."""
    if case["custody_status"] != "IN_TRANSIT":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not IN_TRANSIT")
    has_arrived = any(
        leg["case_id"] == case["id"] and leg["status"] == "ARRIVED"
        for leg in store.transport_legs.values()
    )
    if not has_arrived:
        raise errors.err(errors.ERR_CUSTODY_CHAIN_BROKEN, "No ARRIVED transport leg backs this receive")
    models.append_custody_event(case, "RECEIVED_AT_FACILITY", "facility")
    case["custody_status"] = "RECEIVED"
    if case["billing_status"] == "NOT_BILLABLE":
        case["billing_status"] = "BILLABLE"
    models.touch(case)


def case_store(case, cooler):
    """RECEIVED -> IN_COOLER. Requires cooler AVAILABLE."""
    if case["custody_status"] != "RECEIVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not RECEIVED")
    occupied = models.cooler_occupied_count(cooler)
    if occupied >= cooler["total_capacity"]:
        raise errors.err(errors.ERR_COOLER_FULL, "Cooler is full")
    case["cooler_id"] = cooler["id"]
    case["custody_status"] = "IN_COOLER"
    models.append_custody_event(case, "COOLER_IN", cooler["label"])
    models.touch(case)
    models.touch(cooler)  # cooler mutated (occupancy changed)


def case_ready_return(case, return_method, destination_label):
    """CREMATED -> READY_FOR_RETURN. Requires an ISSUED certificate."""
    if case["custody_status"] != "CREMATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not CREMATED")
    if case["service_type"] != "PRIVATE":
        # COMMUNAL cases are disposed at reconciliation, never returned.
        raise errors.err(errors.ERR_INVALID_STATE, "Only PRIVATE cases may be returned")
    has_cert = any(
        cert["case_id"] == case["id"] and cert["status"] == "ISSUED"
        for cert in store.certificates.values()
    )
    if not has_cert:
        raise errors.err(errors.ERR_INVALID_STATE, "Case has no ISSUED certificate")
    route = models.make_return_route(case["id"], return_method, destination_label)
    case["custody_status"] = "READY_FOR_RETURN"
    models.touch(case)
    return route


def case_finalize_return(case):
    """READY_FOR_RETURN -> RETURNED. Requires a DISPATCHED return route."""
    if case["custody_status"] != "READY_FOR_RETURN":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not READY_FOR_RETURN")
    if case["service_type"] != "PRIVATE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only PRIVATE cases may be returned")
    dispatched = [
        r for r in store.return_routes.values()
        if r["case_id"] == case["id"] and r["status"] == "DISPATCHED"
    ]
    if not dispatched:
        raise errors.err(errors.ERR_INVALID_STATE, "No DISPATCHED return route")
    route = dispatched[0]
    route["status"] = "DELIVERED"
    models.touch(route)
    models.append_custody_event(case, "RETURN_TO_OWNER", "owner")
    case["custody_status"] = "RETURNED"
    case["custody_chain_open"] = False
    models.touch(case)


def case_cancel(case):
    """Cancel a case before cremation, unwinding its footprint."""
    if case["custody_status"] not in ("INTAKE_PENDING", "IN_TRANSIT", "RECEIVED", "IN_COOLER", "STAGED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Case cannot be cancelled in its current state")
    # Cannot cancel a case in a FIRING/COMPLETED batch.
    if case["batch_id"] is not None:
        batch = store.batches.get(case["batch_id"])
        if batch is not None and batch["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Case is in a non-OPEN batch")

    was_in_cooler = case["custody_status"] == "IN_COOLER"
    was_staged = case["custody_status"] == "STAGED"

    if was_in_cooler:
        release_cooler_slot(case)
        # case.custody_status still IN_COOLER until we set CANCELLED; but the
        # cooler occupancy is computed from cases with status==IN_COOLER, so we
        # must flip status before the COOLER_OUT-driven recompute. We set it now.
    former_batch = None
    if was_staged:
        former_batch = store.batches.get(case["batch_id"])
        case["batch_id"] = None

    # Append COOLER_OUT before final CANCELLED if it was in cooler.
    if was_in_cooler:
        # Set status away from IN_COOLER so occupancy recomputes correctly.
        case["custody_status"] = "RECEIVED"
        models.append_custody_event(case, "COOLER_OUT", "facility")

    # PRD 3.13: "Any transport leg not already cancelled is moved to CANCELLED."
    for leg in store.transport_legs.values():
        if leg["case_id"] == case["id"] and leg["status"] != "CANCELLED":
            leg["status"] = "CANCELLED"
            models.touch(leg)

    # Void any ISSUED invoice for this case.
    for inv in store.invoices.values():
        if inv["case_id"] == case["id"] and inv["status"] == "ISSUED":
            inv["status"] = "VOID"
            models.touch(inv)
            if case["billing_status"] == "INVOICED":
                case["billing_status"] = "BILLABLE"
            if inv["bill_to"] == "CLINIC_ACCOUNT" and inv["clinic_id"]:
                clinic = store.clinics.get(inv["clinic_id"])
                if clinic:
                    recompute_clinic_balance(clinic)

    if former_batch is not None:
        models.touch(former_batch)  # member_count/loaded_weight recomputed live

    models.append_custody_event(case, "CANCELLED", "facility")
    case["custody_status"] = "CANCELLED"
    case["custody_chain_open"] = False
    models.touch(case)


# ===========================================================================
# Batch state machine
# ===========================================================================
def batch_assign_case(batch, case):
    """Stage a case into a batch: RECEIVED/IN_COOLER -> STAGED."""
    if case["custody_status"] not in ("RECEIVED", "IN_COOLER"):
        raise errors.err(errors.ERR_INVALID_STATE, "Case must be RECEIVED or IN_COOLER")
    if batch["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not OPEN")
    if case["service_type"] != batch["service_type"]:
        raise errors.err(errors.ERR_SERVICE_TYPE_MISMATCH, "Service type mismatch")
    if batch["service_type"] == "PRIVATE" and models.batch_member_count(batch) >= 1:
        raise errors.err(errors.ERR_SERVICE_TYPE_MISMATCH, "PRIVATE batch already holds a member")

    was_in_cooler = case["custody_status"] == "IN_COOLER"
    case["batch_id"] = batch["id"]
    if was_in_cooler:
        # flip status so cooler occupancy recomputes, then release slot + COOLER_OUT
        cooler = store.coolers.get(case.get("cooler_id"))
        release_cooler_slot(case)
        case["custody_status"] = "RECEIVED"  # transient so occupancy excludes it
        models.append_custody_event(case, "COOLER_OUT", cooler["label"] if cooler else "facility")
    case["custody_status"] = "STAGED"
    models.append_custody_event(case, "STAGED", "facility")
    models.touch(case)
    models.touch(batch)  # member_count/loaded_weight recomputed live


def batch_load(batch):
    if batch["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not OPEN")
    member_count = models.batch_member_count(batch)
    if member_count < 1:
        raise errors.err(errors.ERR_BATCH_EMPTY, "Batch has no members")
    retort = store.retorts.get(batch["retort_id"])
    if retort is not None and models.batch_loaded_weight(batch) > retort["max_load_lbs"]:
        raise errors.err(errors.ERR_RETORT_OVERLOADED, "Loaded weight exceeds retort max load")
    if batch["service_type"] == "PRIVATE" and member_count != 1:
        raise errors.err(errors.ERR_SERVICE_TYPE_MISMATCH, "PRIVATE batch must hold exactly one member")
    batch["status"] = "LOADED"
    models.touch(batch)


def batch_fire(batch):
    if batch["status"] != "LOADED":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not LOADED")
    if models.batch_member_count(batch) < 1:
        raise errors.err(errors.ERR_BATCH_EMPTY, "Batch has no members")
    # Retort window conflict: no other batch FIRING on the same retort with an
    # overlapping half-open window.
    start = parse_iso8601(batch["scheduled_start"])
    end = parse_iso8601(batch["scheduled_end"])
    for other in store.batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["retort_id"] != batch["retort_id"]:
            continue
        if other["status"] != "FIRING":
            continue
        o_start = parse_iso8601(other["scheduled_start"])
        o_end = parse_iso8601(other["scheduled_end"])
        # half-open overlap: [start,end) and [o_start,o_end) overlap iff
        # start < o_end and o_start < end
        if start < o_end and o_start < end:
            raise errors.err(errors.ERR_RETORT_WINDOW_CONFLICT, "Retort firing window conflict")
    allocate_charges_on_fire(batch)
    batch["status"] = "FIRING"
    models.touch(batch)


def batch_complete(batch):
    if batch["status"] != "FIRING":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not FIRING")
    # Cascade: each STAGED member -> CREMATED, append CREMATED event, issue cert.
    for case in models.batch_members(batch):
        if case["custody_status"] == "STAGED":
            models.append_custody_event(case, "CREMATED", "operator")
            models.issue_certificate(case)
            case["custody_status"] = "CREMATED"
            models.touch(case)
    batch["status"] = "COMPLETED"
    models.touch(batch)


def batch_reconcile(batch):
    if batch["status"] != "COMPLETED":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not COMPLETED")
    for case in models.batch_members(batch):
        if case["custody_status"] not in ("CREMATED", "READY_FOR_RETURN", "RETURNED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Not all members reached CREMATED")
    if batch["service_type"] == "COMMUNAL":
        for case in models.batch_members(batch):
            if case["custody_status"] == "CREMATED":
                models.append_custody_event(case, "DISPOSED_COMMUNAL", "facility")
                case["custody_chain_open"] = False
                models.touch(case)
    batch["status"] = "RECONCILED"
    models.touch(batch)


# ===========================================================================
# Transport leg transitions
# ===========================================================================
TRANSPORT_TRANSITIONS = {
    ("ASSIGNED", "EN_ROUTE"),
    ("EN_ROUTE", "ARRIVED"),
    ("ASSIGNED", "CANCELLED"),
    ("EN_ROUTE", "CANCELLED"),
}


def transport_leg_transition(leg, target):
    if (leg["status"], target) not in TRANSPORT_TRANSITIONS:
        raise errors.err(errors.ERR_INVALID_STATE, "Invalid transport leg transition")
    leg["status"] = target
    models.touch(leg)


# ===========================================================================
# Return route transitions
# ===========================================================================
def return_route_dispatch(route):
    if route["status"] != "PLANNED":
        raise errors.err(errors.ERR_INVALID_STATE, "Return route is not PLANNED")
    case = store.cases.get(route["case_id"])
    if case is None or case["custody_status"] != "READY_FOR_RETURN":
        raise errors.err(errors.ERR_INVALID_STATE, "Owning case is not READY_FOR_RETURN")
    route["status"] = "DISPATCHED"
    models.touch(route)


def return_route_cancel(route):
    if route["status"] not in ("PLANNED", "DISPATCHED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Return route cannot be cancelled")
    route["status"] = "CANCELLED"
    models.touch(route)


# ===========================================================================
# Keepsake order transitions
# ===========================================================================
def keepsake_transition(keepsake, target):
    case = store.cases.get(keepsake["case_id"])
    status = keepsake["status"]
    if target == "IN_PRODUCTION":
        if status != "ORDERED":
            raise errors.err(errors.ERR_INVALID_STATE, "Keepsake is not ORDERED")
    elif target == "READY":
        if status != "IN_PRODUCTION":
            raise errors.err(errors.ERR_INVALID_STATE, "Keepsake is not IN_PRODUCTION")
    elif target == "CANCELLED":
        if status not in ("ORDERED", "IN_PRODUCTION"):
            raise errors.err(errors.ERR_INVALID_STATE, "Keepsake cannot be cancelled")
        if case is not None and case_has_issued_invoice(case):
            raise errors.err(errors.ERR_LINE_ITEM_LOCKED, "Case already has an ISSUED invoice")
    else:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid keepsake status")
    keepsake["status"] = target
    models.touch(keepsake)


# ===========================================================================
# Memorial addon transitions
# ===========================================================================
def memorial_transition(addon, target):
    case = store.cases.get(addon["case_id"])
    status = addon["status"]
    if target == "FULFILLED":
        if status != "BOOKED":
            raise errors.err(errors.ERR_INVALID_STATE, "Addon is not BOOKED")
    elif target == "CANCELLED":
        if status != "BOOKED":
            raise errors.err(errors.ERR_INVALID_STATE, "Addon cannot be cancelled")
        if case is not None and case_has_issued_invoice(case):
            raise errors.err(errors.ERR_LINE_ITEM_LOCKED, "Case already has an ISSUED invoice")
    else:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid addon status")
    addon["status"] = target
    models.touch(addon)


# ===========================================================================
# Viewing room scheduling (PRD 3.12)
# ===========================================================================
def check_viewing_room_conflict(room_code, start_iso, end_iso, exclude_id=None):
    """A new viewing window extended by VIEWING_BUFFER_MINUTES on each side must
    not overlap any other non-CANCELLED viewing in the same room (also buffered)."""
    buffer = timedelta(minutes=models.VIEWING_BUFFER_MINUTES)
    new_start = parse_iso8601(start_iso) - buffer
    new_end = parse_iso8601(end_iso) + buffer
    for a in store.memorial_addons.values():
        if a["id"] == exclude_id:
            continue
        if a["addon_type"] != "VIEWING_SESSION":
            continue
        if a["status"] == "CANCELLED":
            continue
        if a["viewing_room_code"] != room_code:
            continue
        if not a["viewing_start"] or not a["viewing_end"]:
            continue
        o_start = parse_iso8601(a["viewing_start"]) - buffer
        o_end = parse_iso8601(a["viewing_end"]) + buffer
        if new_start < o_end and o_start < new_end:
            raise errors.err(errors.ERR_VIEWING_ROOM_CONFLICT, "Viewing room window conflict")


# ===========================================================================
# Invoice helpers
# ===========================================================================
def case_has_issued_invoice(case):
    return any(
        inv["case_id"] == case["id"] and inv["status"] == "ISSUED"
        for inv in store.invoices.values()
    )


def invoice_pay(invoice):
    if invoice["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED")
    invoice["status"] = "PAID"
    models.touch(invoice)
    case = store.cases.get(invoice["case_id"])
    if case is not None and case["billing_status"] == "INVOICED":
        case["billing_status"] = "SETTLED"
        models.touch(case)
    if invoice["bill_to"] == "CLINIC_ACCOUNT" and invoice["clinic_id"]:
        clinic = store.clinics.get(invoice["clinic_id"])
        if clinic:
            recompute_clinic_balance(clinic)


def invoice_void(invoice):
    if invoice["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED")
    invoice["status"] = "VOID"
    models.touch(invoice)
    case = store.cases.get(invoice["case_id"])
    if case is not None and case["billing_status"] == "INVOICED":
        case["billing_status"] = "BILLABLE"
        models.touch(case)
    if invoice["bill_to"] == "CLINIC_ACCOUNT" and invoice["clinic_id"]:
        clinic = store.clinics.get(invoice["clinic_id"])
        if clinic:
            recompute_clinic_balance(clinic)


def issue_invoice(case, expected_case_version):
    """POST /cases/{id}/invoices. Order of checks (PRD 2.10 / 3.10):
    OCC version -> state -> credit fiscal -> create."""
    # OCC (priority 7) checked before state (priority 8).
    if case["version"] != expected_case_version:
        raise errors.err(errors.ERR_STALE_CASE_VERSION, "Case version is stale")
    # State: billing BILLABLE and custody CREMATED.
    if case["billing_status"] != "BILLABLE" or case["custody_status"] != "CREMATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not billable/cremated")

    subtotal, handling_fee, total = compute_invoice_amounts(case)

    clinic = None
    invoice_clinic_id = None
    if case["bill_to"] == "CLINIC_ACCOUNT":
        invoice_clinic_id = case["clinic_id"]
        clinic = store.clinics.get(invoice_clinic_id)
        # Credit limit (priority 15): block if new outstanding would exceed limit.
        if clinic is not None:
            new_outstanding = clinic["outstanding_balance_cents"] + total
            if new_outstanding > clinic["credit_limit_cents"]:
                raise errors.err(errors.ERR_CLINIC_CREDIT_EXCEEDED, "Clinic credit limit exceeded")

    invoice = models.make_invoice(
        case["id"], invoice_clinic_id, case["bill_to"], subtotal, handling_fee, total
    )
    case["billing_status"] = "INVOICED"
    models.touch(case)  # version bump -> stale second issuance
    if clinic is not None:
        recompute_clinic_balance(clinic)
    return invoice


# ===========================================================================
# Clinic statement (PRD 3.14, calc clinic_statement_balance)
# ===========================================================================
ACCRUAL_STATES = {"RECEIVED", "IN_COOLER", "STAGED", "CREMATED", "READY_FOR_RETURN", "RETURNED"}
COMPLETION_STATES = {"CREMATED", "READY_FOR_RETURN", "RETURNED"}


def clinic_statement_balance(clinic, basis):
    states = ACCRUAL_STATES if basis == "ACCRUAL" else COMPLETION_STATES
    total = 0
    for case in store.cases.values():
        if (case["clinic_id"] == clinic["id"]
                and case["bill_to"] == "CLINIC_ACCOUNT"
                and case["custody_status"] in states):
            total += case["cremation_charge_cents"]
    return total
