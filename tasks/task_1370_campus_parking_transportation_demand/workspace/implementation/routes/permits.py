"""Permit endpoints: purchase, list, get, cancel."""
from flask import Blueprint, request

import db
from errors import (
    bad_request,
    not_found,
    conflict,
    stale_version,
    unprocessable,
    payment_required,
    ERR_PATRON_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_PERMIT_NOT_FOUND,
    ERR_ALLOCATION_NOT_OPEN,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_PATRON_BLOCKED,
    ERR_INSUFFICIENT_CREDIT,
)
from middleware import get_caller, require_roles, require_ownership, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    bump_allocation,
    check_patron_eligible,
    check_plate_available,
    compute_permit_fee,
    compute_refund,
    extend_offers,
    recompute_fund,
    parse_iso_date,
    logical_date,
)

bp = Blueprint("permits", __name__)


def _get_permit_or_404(permit_id: str) -> dict:
    record = db.permits.get(permit_id)
    if record is None:
        raise not_found(ERR_PERMIT_NOT_FOUND, "No permit with the given id")
    return record


@bp.post("/parking/permits")
def purchase_permit():
    caller = get_caller()
    require_roles(caller, ["Commuter", "ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    patron_id = body.get("patron_id")
    allocation_id = body.get("allocation_id")
    plate_number = body.get("plate_number")
    valid_from_raw = body.get("valid_from")
    expected = body.get("expected_allocation_version")
    apply_credit_cents = body.get("apply_credit_cents")

    # Ownership (priority 3) — needs patron_id from body
    if not isinstance(patron_id, str) or not patron_id:
        raise bad_request("patron_id is required")
    require_ownership(caller, patron_id)

    # Existence (priority 4), left-to-right: patron, allocation
    patron = db.patrons.get(patron_id)
    if patron is None:
        raise not_found(ERR_PATRON_NOT_FOUND, "No patron with the given id")
    if not isinstance(allocation_id, str) or not allocation_id:
        raise bad_request("allocation_id is required")
    allocation = db.allocations.get(allocation_id)
    if allocation is None:
        raise not_found(ERR_ALLOCATION_NOT_FOUND, "No lot allocation with the given id")

    # OCC (priority 5)
    if expected is None:
        raise bad_request("expected_allocation_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_allocation_version must be an integer")
    if expected != allocation["version"]:
        raise stale_version("expected_allocation_version does not match current version")

    # Request shape (priority 6)
    if not isinstance(plate_number, str) or not plate_number:
        raise bad_request("plate_number is required")
    if apply_credit_cents is not None:
        if not isinstance(apply_credit_cents, int) or isinstance(apply_credit_cents, bool) or apply_credit_cents < 0:
            raise bad_request("apply_credit_cents must be an integer >= 0")

    if valid_from_raw is not None:
        valid_from = parse_iso_date(valid_from_raw, "valid_from")
        if valid_from < allocation["_term_start"] or valid_from > allocation["_term_end"]:
            raise bad_request("valid_from must lie within [term_start, term_end]")
    else:
        valid_from = max(logical_date(), allocation["_term_start"])
    valid_to = allocation["_term_end"]

    # State (priority 7): allocation OPEN
    if allocation["status"] != "OPEN":
        raise conflict(ERR_ALLOCATION_NOT_OPEN, "Permit purchase requires allocation status OPEN")

    # Temporal (priority 9): plate double-booking
    check_plate_available(plate_number, valid_from, valid_to)

    # Eligibility (priority 10)
    check_patron_eligible(patron, allocation)

    # Fiscal (priority 12): standing before credit
    if patron["standing"] != "GOOD_STANDING":
        raise payment_required(ERR_PATRON_BLOCKED, "Patron standing is BLOCKED")

    credit_account = None
    if apply_credit_cents is not None:
        for acct in db.incentive_accounts.values():
            if acct["patron_id"] == patron_id:
                credit_account = acct
                break
        if credit_account is None:
            raise unprocessable(ERR_INSUFFICIENT_CREDIT, "Patron has no incentive account")
        if apply_credit_cents > credit_account["credit_balance_cents"]:
            raise unprocessable(ERR_INSUFFICIENT_CREDIT, "apply_credit_cents exceeds credit balance")

    fee_base, surcharge, fee_total, credit_applied, fee_paid = compute_permit_fee(
        allocation, valid_from, apply_credit_cents
    )

    record = new_record()
    record.update(
        patron_id=patron_id,
        allocation_id=allocation_id,
        displaced_from_allocation_id=None,
        plate_number=plate_number,
        valid_from=valid_from.isoformat(),
        valid_to=valid_to.isoformat(),
        status="ACTIVE",
        fee_base_cents=fee_base,
        surcharge_cents=surcharge,
        fee_total_cents=fee_total,
        credit_applied_cents=credit_applied,
        fee_paid_cents=fee_paid,
        refund_cents=None,
    )
    record["_valid_from"] = valid_from
    record["_valid_to"] = valid_to
    db.permits[record["id"]] = record

    # Allocation counters
    allocation["allocated_count"] += 1
    bump_allocation(allocation)

    # Fund revenue
    for fund in db.funds.values():
        fund["permit_revenue_cents"] += fee_paid
        recompute_fund(fund)
        touch(fund)

    # Debit applied credit
    if credit_account is not None and credit_applied > 0:
        credit_account["credit_balance_cents"] -= credit_applied
        touch(credit_account)

    return success(serialize(record), 201)


@bp.get("/parking/permits")
def list_permits():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    patron_id = request.args.get("patron_id")
    allocation_id = request.args.get("allocation_id")
    displaced_from = request.args.get("displaced_from_allocation_id")
    plate_number = request.args.get("plate_number")
    status = request.args.get("status")

    items = list(db.permits.values())
    if patron_id is not None:
        items = [p for p in items if p["patron_id"] == patron_id]
    if allocation_id is not None:
        items = [p for p in items if p["allocation_id"] == allocation_id]
    if displaced_from is not None:
        items = [p for p in items if p.get("displaced_from_allocation_id") == displaced_from]
    if plate_number is not None:
        items = [p for p in items if p["plate_number"] == plate_number]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(p) for p in page], limit, offset, total)


@bp.get("/parking/permits/<permitId>")
def get_permit(permitId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_permit_or_404(permitId)
    return success(serialize(record), 200)


@bp.post("/parking/permits/<permitId>/cancel")
def cancel_permit(permitId):
    caller = get_caller()
    require_roles(caller, ["Commuter", "ParkingAdmin"])

    # Path existence (priority 4) — needed to evaluate ownership
    permit = _get_permit_or_404(permitId)

    # Ownership (priority 3)
    require_ownership(caller, permit["patron_id"])

    # State (priority 7)
    if permit["status"] not in ("ACTIVE", "SUSPENDED"):
        raise conflict(ERR_PERMIT_NOT_ACTIVE, "Cancel requires status ACTIVE or SUSPENDED")

    # Refund
    refund = compute_refund(permit)
    permit["refund_cents"] = refund
    permit["status"] = "CANCELLED"
    touch(permit)

    # Fund revenue
    for fund in db.funds.values():
        fund["permit_revenue_cents"] -= refund
        recompute_fund(fund)
        touch(fund)

    # Credit restoration in full
    if permit["credit_applied_cents"] > 0:
        for acct in db.incentive_accounts.values():
            if acct["patron_id"] == permit["patron_id"]:
                acct["credit_balance_cents"] += permit["credit_applied_cents"]
                touch(acct)
                break

    # Allocation counters
    allocation = db.allocations[permit["allocation_id"]]
    allocation["allocated_count"] -= 1
    bump_allocation(allocation)

    # Immediately extend offers on freed seats
    extend_offers(allocation)

    return success(serialize(permit), 200)
