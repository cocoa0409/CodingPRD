"""Deductions against payables, recovery allocations and cash application
(PRD 3.9)."""

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    ROLE_AP_ACCOUNTANT,
    ApiError,
    authenticate,
    body_dict,
    clock,
    new_record,
    object_response,
    req_int,
    req_str,
    store,
    touch,
)
from derive import (
    allocations_of_deduction,
    recompute_chargeback,
    recompute_deduction,
    reconcile_vendor,
)

bp = Blueprint("money", __name__)

ACCOUNTANT = (ROLE_AP_ACCOUNTANT,)
POSTABLE_DISPUTE_STATES = ("NONE", "UPHELD", "PARTIALLY_REVERSED")


# ---------------------------------------------------------------------------
# Deduction documents
# ---------------------------------------------------------------------------


@bp.post("/compliance/deductions")
def create_deduction():
    authenticate(ACCOUNTANT)
    body = body_dict()
    vendor_id = req_str(body, "vendor_id")
    invoice_reference = req_str(body, "invoice_reference", 1, 32)
    expected_vendor_version = req_int(body, "expected_vendor_version", 1)

    vendor = lookup.vendor(vendor_id)
    if vendor["version"] != expected_vendor_version:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_vendor_version does not match the vendor's current version.",
        )

    deduction = new_record(
        vendor_id=vendor["id"],
        invoice_reference=invoice_reference,
        status="DRAFT",
        amount_cents=0,
        allocation_count=0,
        over_allocated_cents=0,
        posted_at=None,
        posted_by_user_id=None,
        reversed_at=None,
        reversal_reason=None,
    )
    store.deductions[deduction["id"]] = deduction

    reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.deduction_out(deduction), 201)


@bp.post("/compliance/deductions/<identifier>/allocations")
def create_allocation(identifier):
    user_id, _role = authenticate(ACCOUNTANT)
    body = body_dict()
    chargeback_id = req_str(body, "chargeback_id")
    allocated_cents = req_int(body, "allocated_cents", 1)

    deduction = lookup.deduction(identifier)
    chargeback = lookup.chargeback(chargeback_id)
    if chargeback["vendor_id"] != deduction["vendor_id"]:
        # A deduction may only net its own supplier's chargebacks.
        raise ApiError("ERR_CHARGEBACK_NOT_FOUND")
    if deduction["status"] != "DRAFT":
        raise ApiError(
            "ERR_DEDUCTION_NOT_DRAFT", "Allocations may only be earmarked against a draft."
        )
    if allocated_cents > chargeback["outstanding_cents"]:
        raise ApiError(
            "ERR_ALLOCATION_EXCEEDS_OUTSTANDING",
            "allocated_cents may not exceed the chargeback's outstanding_cents.",
        )

    allocation = new_record(
        chargeback_id=chargeback["id"],
        deduction_id=deduction["id"],
        source_type="DEDUCTION",
        allocated_cents=allocated_cents,
        remittance_reference=None,
        effective_status="PENDING",
        applied_by_user_id=user_id,
        applied_at=None,
    )
    store.allocations[allocation["id"]] = allocation

    recompute_deduction(deduction)
    return object_response(ser.allocation_out(allocation), 201)


@bp.post("/compliance/deductions/<identifier>/post")
def post_deduction(identifier):
    user_id, _role = authenticate(ACCOUNTANT)
    body_dict()

    deduction = lookup.deduction(identifier)
    if deduction["status"] != "DRAFT":
        raise ApiError(
            "ERR_DEDUCTION_ALREADY_POSTED",
            "Only a draft deduction may be posted against payables.",
        )

    rows = allocations_of_deduction(deduction["id"])
    if not rows:
        raise ApiError(
            "ERR_DEDUCTION_NO_ALLOCATIONS", "A deduction must hold at least one allocation."
        )

    targets = []
    seen = set()
    for allocation in rows:
        chargeback = store.chargebacks.get(allocation["chargeback_id"])
        if chargeback is None:
            continue
        if chargeback["dispute_status"] not in POSTABLE_DISPUTE_STATES:
            raise ApiError(
                "ERR_CHARGEBACK_DISPUTE_OPEN",
                "An allocated chargeback is under an open dispute.",
            )
        if chargeback["id"] not in seen:
            seen.add(chargeback["id"])
            targets.append(chargeback)

    vendor = store.vendors.get(deduction["vendor_id"])
    exposure = vendor["open_chargeback_cents"] if vendor is not None else 0
    if deduction["amount_cents"] > exposure:
        raise ApiError(
            "ERR_DEDUCTION_EXCEEDS_EXPOSURE",
            "The deduction may not net more than the vendor currently owes.",
        )

    instant = clock.now()

    # Cascade link 1.
    deduction["status"] = "POSTED"
    deduction["posted_at"] = instant
    deduction["posted_by_user_id"] = user_id

    # Cascade link 2.
    for allocation in rows:
        if allocation["effective_status"] != "PENDING":
            continue
        allocation["effective_status"] = "EFFECTIVE"
        allocation["applied_at"] = instant
        touch(allocation)

    recompute_deduction(deduction, bump=False)
    touch(deduction)

    # Cascade link 3.
    for chargeback in targets:
        recompute_chargeback(chargeback, force_bump=True)

    # Cascade link 4.
    if vendor is not None:
        reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.deduction_out(deduction))


@bp.post("/compliance/deductions/<identifier>/reverse")
def reverse_deduction(identifier):
    authenticate(ACCOUNTANT)
    body = body_dict()
    reversal_reason = req_str(body, "reversal_reason", 1)

    deduction = lookup.deduction(identifier)
    if deduction["status"] != "POSTED":
        raise ApiError(
            "ERR_DEDUCTION_NOT_POSTED", "Only a posted deduction may be reversed."
        )

    rows = allocations_of_deduction(deduction["id"])
    targets = []
    seen = set()
    for allocation in rows:
        if allocation["effective_status"] == "EFFECTIVE":
            allocation["effective_status"] = "REVERSED"
            touch(allocation)
        chargeback = store.chargebacks.get(allocation["chargeback_id"])
        if chargeback is not None and chargeback["id"] not in seen:
            seen.add(chargeback["id"])
            targets.append(chargeback)

    deduction["status"] = "REVERSED"
    deduction["reversed_at"] = clock.now()
    deduction["reversal_reason"] = reversal_reason
    recompute_deduction(deduction, bump=False)
    deduction["over_allocated_cents"] = 0
    touch(deduction)

    for chargeback in targets:
        recompute_chargeback(chargeback, force_bump=True)

    vendor = store.vendors.get(deduction["vendor_id"])
    if vendor is not None:
        reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.deduction_out(deduction))


# ---------------------------------------------------------------------------
# Cash application
# ---------------------------------------------------------------------------


@bp.post("/compliance/chargebacks/<identifier>/cash-applications")
def apply_cash(identifier):
    user_id, _role = authenticate(ACCOUNTANT)
    body = body_dict()
    remittance_reference = req_str(body, "remittance_reference", 1)
    amount_cents = req_int(body, "amount_cents", 1)
    expected_chargeback_version = req_int(body, "expected_chargeback_version", 1)

    chargeback = lookup.chargeback(identifier)
    if chargeback["version"] != expected_chargeback_version:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_chargeback_version does not match the chargeback's current version.",
        )
    if chargeback["settlement_status"] == "WRITTEN_OFF":
        raise ApiError(
            "ERR_CHARGEBACK_WRITTEN_OFF",
            "Cash may not be applied to a written-off chargeback.",
        )
    if amount_cents > chargeback["outstanding_cents"]:
        raise ApiError(
            "ERR_OVER_APPLICATION",
            "amount_cents may not exceed the chargeback's outstanding_cents.",
        )

    allocation = new_record(
        chargeback_id=chargeback["id"],
        deduction_id=None,
        source_type="CASH",
        allocated_cents=amount_cents,
        remittance_reference=remittance_reference,
        effective_status="EFFECTIVE",
        applied_by_user_id=user_id,
        applied_at=clock.now(),
    )
    store.allocations[allocation["id"]] = allocation

    recompute_chargeback(chargeback, force_bump=True)
    vendor = store.vendors.get(chargeback["vendor_id"])
    if vendor is not None:
        reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.allocation_out(allocation), 201)
