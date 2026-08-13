"""Waitlist entry endpoints."""
from flask import Blueprint, request

import db
from errors import (
    bad_request,
    not_found,
    conflict,
    stale_version,
    unprocessable,
    ERR_PATRON_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_ENTRY_NOT_FOUND,
    ERR_ALLOCATION_NOT_WAITLISTING,
    ERR_OFFER_NOT_PENDING,
    ERR_OFFER_EXPIRED,
    ERR_ALREADY_WAITLISTED,
    ERR_PATRON_BLOCKED,
    ERR_INSUFFICIENT_CREDIT,
    payment_required,
)
from middleware import get_caller, require_roles, require_ownership, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    bump_allocation,
    check_patron_eligible,
    compute_permit_fee,
    recompute_fund,
    MAX_REQUEUES,
)
from datetime import timedelta

bp = Blueprint("waitlist", __name__)


def _get_entry_or_404(entry_id: str) -> dict:
    record = db.waitlist_entries.get(entry_id)
    if record is None:
        raise not_found(ERR_ENTRY_NOT_FOUND, "No waitlist entry with the given id")
    return record


def _create_permit_from_allocation(patron: dict, allocation: dict, plate_number,
                                   valid_from, apply_credit_cents):
    """Shared permit creation used by purchase and claim."""
    # Credit check (priority 12) — only when credit requested
    credit_account = None
    if apply_credit_cents is not None:
        for acct in db.incentive_accounts.values():
            if acct["patron_id"] == patron["id"]:
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
        patron_id=patron["id"],
        allocation_id=allocation["id"],
        displaced_from_allocation_id=None,
        plate_number=plate_number,
        valid_from=valid_from.isoformat(),
        valid_to=allocation["_term_end"].isoformat(),
        status="ACTIVE",
        fee_base_cents=fee_base,
        surcharge_cents=surcharge,
        fee_total_cents=fee_total,
        credit_applied_cents=credit_applied,
        fee_paid_cents=fee_paid,
        refund_cents=None,
    )
    record["_valid_from"] = valid_from
    record["_valid_to"] = allocation["_term_end"]
    db.permits[record["id"]] = record

    if credit_account is not None and credit_applied > 0:
        credit_account["credit_balance_cents"] -= credit_applied
        touch(credit_account)

    return record


@bp.post("/parking/waitlist-entries")
def join_waitlist():
    caller = get_caller()
    require_roles(caller, ["Commuter", "ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    patron_id = body.get("patron_id")
    allocation_id = body.get("allocation_id")
    if not isinstance(patron_id, str) or not patron_id:
        raise bad_request("patron_id is required")
    if not isinstance(allocation_id, str) or not allocation_id:
        raise bad_request("allocation_id is required")

    # Ownership (priority 3)
    require_ownership(caller, patron_id)

    # Existence (priority 4), left-to-right: patron, then allocation
    patron = db.patrons.get(patron_id)
    if patron is None:
        raise not_found(ERR_PATRON_NOT_FOUND, "No patron with the given id")
    allocation = db.allocations.get(allocation_id)
    if allocation is None:
        raise not_found(ERR_ALLOCATION_NOT_FOUND, "No lot allocation with the given id")

    # State (priority 7): allocation must be WAITLISTING
    if allocation["status"] != "WAITLISTING":
        raise conflict(
            ERR_ALLOCATION_NOT_WAITLISTING,
            "Waitlist join requires allocation status WAITLISTING",
        )

    # Eligibility (priority 10)
    check_patron_eligible(patron, allocation)

    # Uniqueness (priority 11): at most one WAITING/OFFERED entry per (patron, allocation)
    for e in db.waitlist_entries.values():
        if (
            e["patron_id"] == patron_id
            and e["allocation_id"] == allocation_id
            and e["status"] in ("WAITING", "OFFERED")
        ):
            raise conflict(
                ERR_ALREADY_WAITLISTED,
                "Patron already has a WAITING or OFFERED entry on this allocation",
            )

    record = new_record()
    now = db.now()
    record.update(
        allocation_id=allocation_id,
        patron_id=patron_id,
        status="WAITING",
        waiting_since=db.iso_now(),
        offered_at=None,
        offer_expires_at=None,
        decline_count=0,
        requeue_count=0,
    )
    record["_waiting_since"] = now
    record["_offered_at"] = None
    record["_offer_expires_at"] = None
    db.waitlist_entries[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/waitlist-entries")
def list_entries():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    allocation_id = request.args.get("allocation_id")
    patron_id = request.args.get("patron_id")
    status = request.args.get("status")

    items = list(db.waitlist_entries.values())
    if allocation_id is not None:
        items = [e for e in items if e["allocation_id"] == allocation_id]
    if patron_id is not None:
        items = [e for e in items if e["patron_id"] == patron_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.get("/parking/waitlist-entries/<entryId>")
def get_entry(entryId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_entry_or_404(entryId)
    return success(serialize(record), 200)


@bp.post("/parking/waitlist-entries/<entryId>/claim")
def claim_offer(entryId):
    caller = get_caller()
    require_roles(caller, ["Commuter"])
    body = request.get_json(silent=True) or {}

    # Existence (priority 4): entry
    entry = _get_entry_or_404(entryId)
    allocation = db.allocations.get(entry["allocation_id"])
    # allocation must exist; it was validated at join time
    patron = db.patrons[entry["patron_id"]]

    # Ownership (priority 3) — must come before existence of body FKs but after
    # path-id existence? PRD validation order puts ownership at 3 and existence
    # at 4. Path ids must resolve to know the owner... The natural reading is
    # that path-id resolution is needed to even evaluate ownership. The
    # scaffold orders path-id existence at priority 4; ownership at 3 is about
    # body FK references. To resolve a path-id-based ownership check we must
    # first load the resource — the 404 on a missing path id wins.
    require_ownership(caller, entry["patron_id"])

    # OCC (priority 5): expected_allocation_version required
    expected = body.get("expected_allocation_version")
    if expected is None:
        raise bad_request("expected_allocation_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_allocation_version must be an integer")
    if expected != allocation["version"]:
        raise stale_version("expected_allocation_version does not match current version")

    # Request shape (priority 6)
    apply_credit_cents = body.get("apply_credit_cents")
    if apply_credit_cents is not None:
        if not isinstance(apply_credit_cents, int) or isinstance(apply_credit_cents, bool) or apply_credit_cents < 0:
            raise bad_request("apply_credit_cents must be an integer >= 0")

    # State (priority 7): entry must be OFFERED
    if entry["status"] != "OFFERED":
        raise conflict(ERR_OFFER_NOT_PENDING, "Claim requires entry status OFFERED")

    # Temporal (priority 9): offer expiry
    now = db.now()
    if now > entry["_offer_expires_at"]:
        # Transition OFFERED -> EXPIRED then requeue branch
        entry["status"] = "EXPIRED"
        allocation["offers_outstanding"] -= 1
        if entry["requeue_count"] < MAX_REQUEUES:
            entry["requeue_count"] += 1
            entry["decline_count"] += 1
            entry["status"] = "WAITING"
            entry["waiting_since"] = db.iso_now()
            entry["_waiting_since"] = now
            entry["offered_at"] = None
            entry["offer_expires_at"] = None
            entry["_offered_at"] = None
            entry["_offer_expires_at"] = None
        else:
            entry["status"] = "WITHDRAWN"
            entry["decline_count"] += 1
        touch(entry)
        bump_allocation(allocation)
        raise unprocessable(ERR_OFFER_EXPIRED, "Offer has expired")

    # Eligibility (priority 10)
    check_patron_eligible(patron, allocation)

    # Fiscal (priority 12): standing before credit
    if patron["standing"] != "GOOD_STANDING":
        raise payment_required(ERR_PATRON_BLOCKED, "Patron standing is BLOCKED")

    # Credit check (priority 12) via helper, then fee + create
    valid_from = max(db.now().date(), allocation["_term_start"])
    permit = _create_permit_from_allocation(patron, allocation, None, valid_from, apply_credit_cents)

    # Entry transition OFFERED -> CLAIMED
    entry["status"] = "CLAIMED"
    touch(entry)

    # Allocation counters
    allocation["offers_outstanding"] -= 1
    allocation["allocated_count"] += 1
    bump_allocation(allocation)

    # Fund revenue: permits/claims credit the revenue ledger of every fund?
    # SCAFFOLD: fund.permit_revenue_cents += fee_paid_cents at purchase/claim.
    # There is no fund FK on permit or allocation; PRD §3.10 treats the fund
    # ledger as a global revenue sink. Apply to all funds.
    for fund in db.funds.values():
        fund["permit_revenue_cents"] += permit["fee_paid_cents"]
        recompute_fund(fund)
        touch(fund)

    return success(serialize(permit), 201)


@bp.post("/parking/waitlist-entries/<entryId>/withdraw")
def withdraw_entry(entryId):
    caller = get_caller()
    require_roles(caller, ["Commuter"])

    entry = _get_entry_or_404(entryId)
    allocation = db.allocations.get(entry["allocation_id"])

    # Ownership (priority 3)
    require_ownership(caller, entry["patron_id"])

    # State (priority 7): WAITING or OFFERED
    if entry["status"] not in ("WAITING", "OFFERED"):
        raise conflict(ERR_OFFER_NOT_PENDING, "Withdraw requires status WAITING or OFFERED")

    if entry["status"] == "OFFERED":
        entry["decline_count"] += 1
        allocation["offers_outstanding"] -= 1
        bump_allocation(allocation)
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return success(serialize(entry), 200)
