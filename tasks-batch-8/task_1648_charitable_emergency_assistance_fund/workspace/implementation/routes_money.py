"""Routes: awards, allocations, payments, replenishment runs."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_INVALID_AWARD_STATE,
    ERR_INVALID_PAYMENT_STATE, ERR_PAYMENTS_OUTSTANDING,
    ERR_PAYMENTS_CLEARED, ERR_VENDOR_MISMATCH,
    ERR_NO_RESERVED_ALLOCATION, ERR_PAYMENT_EXCEEDS_ALLOCATION,
    ERR_SOURCE_PERIOD_CLOSED, ERR_NO_ACTIVE_POLICY,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, require_fields, reject_unknown_fields, req_string,
    req_positive_cents, req_int, req_datetime,
)

bp = Blueprint("money", __name__)

READ_ROLES = ALL_ROLES


def get_award_or_404(aid):
    award = db.awards.get(aid)
    if award is None:
        raise_err(ERR_NOT_FOUND, "AssistanceAward not found")
    return award


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

@bp.get("/assistance/awards/<aid>")
def get_award(aid):
    require_role(READ_ROLES)
    return success_object(get_award_or_404(aid))


@bp.get("/assistance/awards")
def list_awards():
    require_role(READ_ROLES)
    records = list(db.awards.values())
    for param in ("application_id", "policy_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [a for a in records if a[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


def _payment_guards(award):
    """Void/adjust guards, fixed order: ISSUED first, then CLEARED."""
    payments = [p for p in db.payments.values() if p["award_id"] == award["id"]]
    if any(p["status"] == "ISSUED" for p in payments):
        raise_err(ERR_PAYMENTS_OUTSTANDING,
                  "Award void/adjust attempted while a payment is ISSUED")
    if any(p["status"] == "CLEARED" for p in payments):
        raise_err(ERR_PAYMENTS_CLEARED,
                  "Award void/adjust attempted while a payment is CLEARED")


@bp.post("/assistance/awards/<aid>/adjust")
def adjust_award(aid):
    user_id = require_role(["ProgramManager"])
    data = body()
    require_fields(data, ["new_awarded_amount_cents", "expected_award_version"])
    reject_unknown_fields(data, ["new_awarded_amount_cents",
                                 "expected_award_version"])
    new_amount = req_int(data, "new_awarded_amount_cents", minimum=0)
    expected = req_int(data, "expected_award_version")
    award = get_award_or_404(aid)
    # OCC (priority 5) precedes state legality (priority 6).
    if expected != award["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_award_version does not match the award's "
                  "current version")
    if award["status"] != "ACTIVE":
        raise_err(ERR_INVALID_AWARD_STATE,
                  "Adjust attempted on an award not in ACTIVE status")
    _payment_guards(award)
    if new_amount >= award["awarded_amount_cents"]:
        raise_err("ERR_INVALID_REQUEST",
                  "new_awarded_amount_cents must be less than the current "
                  "awarded_amount_cents")

    reduction = award["awarded_amount_cents"] - new_amount
    original_amount = award["awarded_amount_cents"]

    # award_reduction_proration: per-allocation floor first, remainder to the
    # last-ranked allocation.
    allocs = sorted(
        [a for a in db.allocations.values()
         if a["award_id"] == aid and a["status"] == "RESERVED"],
        key=lambda a: a["rank_order"])
    n = len(allocs)
    touched_sources = set()
    if n > 0:
        releases = []
        for i in range(n - 1):
            releases.append(
                (allocs[i]["allocated_cents"] * reduction) // original_amount)
        releases.append(reduction - sum(releases))
        for alloc, release in zip(allocs, releases):
            if release <= 0:
                continue
            alloc["allocated_cents"] -= release
            source = db.funding_sources[alloc["funding_source_id"]]
            svc.recompute_source(source)
            if alloc["allocated_cents"] == 0:
                alloc["status"] = "RELEASED"
            svc.touch(alloc)
            touched_sources.add(source["id"])
    award["awarded_amount_cents"] = new_amount
    svc.touch(award)
    for sid in touched_sources:
        svc.refresh_source_status(db.funding_sources[sid])
    return success_object(award)


@bp.post("/assistance/awards/<aid>/void")
def void_award(aid):
    user_id = require_role(["ProgramManager"])
    award = get_award_or_404(aid)
    if award["status"] not in ("ACTIVE", "PARTIALLY_DISBURSED"):
        raise_err(ERR_INVALID_AWARD_STATE,
                  "Void attempted on an award not in ACTIVE or "
                  "PARTIALLY_DISBURSED status")
    _payment_guards(award)
    touched_sources = set()
    for alloc in db.allocations.values():
        if alloc["award_id"] == aid and alloc["status"] == "RESERVED":
            alloc["status"] = "RELEASED"
            svc.touch(alloc)
            source = db.funding_sources[alloc["funding_source_id"]]
            svc.recompute_source(source)
            touched_sources.add(source["id"])
    for sid in touched_sources:
        svc.refresh_source_status(db.funding_sources[sid])
    award["status"] = "VOIDED"
    svc.touch(award)
    # Application returns to PENDING_DECISION with active_award_id cleared.
    app = db.applications[award["application_id"]]
    app["active_award_id"] = ""
    app["status"] = "PENDING_DECISION"
    svc.touch(app)
    return success_object(award)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

@bp.get("/assistance/allocations/<aid>")
def get_allocation(aid):
    require_role(READ_ROLES)
    rec = db.allocations.get(aid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FundingAllocation not found")
    return success_object(rec)


@bp.get("/assistance/allocations")
def list_allocations():
    require_role(READ_ROLES)
    records = list(db.allocations.values())
    for param in ("award_id", "funding_source_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [a for a in records if a[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def _allocation_remainder(alloc):
    """allocated - consumed - sum of other ISSUED payments on this allocation."""
    issued = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["funding_source_id"] == alloc["funding_source_id"]
        and p["award_id"] == alloc["award_id"]
        and p["status"] == "ISSUED")
    return alloc["allocated_cents"] - alloc["consumed_cents"] - issued


@bp.post("/assistance/awards/<aid>/payments")
def create_payment(aid):
    user_id = require_role(["FinanceOfficer"])
    data = body()
    fields = ["vendor_id", "funding_source_id", "amount_cents",
              "payment_date"]
    require_fields(data, fields)
    reject_unknown_fields(data, fields)
    vendor_id = req_string(data, "vendor_id")
    funding_source_id = req_string(data, "funding_source_id")
    amount = req_positive_cents(data, "amount_cents")
    payment_date = req_datetime(data, "payment_date")

    # Existence, left to right: award (path), vendor, funding source.
    award = get_award_or_404(aid)
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err(ERR_NOT_FOUND, "Vendor not found")
    source = db.funding_sources.get(funding_source_id)
    if source is None:
        raise_err(ERR_NOT_FOUND, "FundingSource not found")

    # Cross-reference compatibility: payee must equal the application's
    # vendor; the named source must hold a RESERVED allocation on this award.
    app = db.applications[award["application_id"]]
    if vendor_id != app["vendor_id"]:
        raise_err(ERR_VENDOR_MISMATCH,
                  "Payment vendor_id differs from the application's vendor")
    alloc = None
    for a in db.allocations.values():
        if a["award_id"] == aid and a["funding_source_id"] == funding_source_id \
                and a["status"] == "RESERVED":
            alloc = a
            break
    if alloc is None:
        raise_err(ERR_NO_RESERVED_ALLOCATION,
                  "Payment's funding_source_id holds no RESERVED allocation "
                  "on this award")

    # Temporal window: payment_date inside [period_start, period_end).
    pay_dt = db.parse_iso(payment_date)
    if not (db.parse_iso(source["period_start"]) <= pay_dt
            < db.parse_iso(source["period_end"])):
        raise_err(ERR_SOURCE_PERIOD_CLOSED,
                  "payment_date falls outside the source's funding period")

    # Structural: amount fits the allocation remainder.
    if amount > _allocation_remainder(alloc):
        raise_err(ERR_PAYMENT_EXCEEDS_ALLOCATION,
                  "Payment amount exceeds the allocation remainder")

    rec = svc.stamp_new({
        "award_id": aid,
        "vendor_id": vendor_id,
        "funding_source_id": funding_source_id,
        "amount_cents": amount,
        "payment_date": payment_date,
        "status": "ISSUED",
        "issued_by": user_id,
        "cleared_at": "",
    })
    db.payments[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/payments/<pid>")
def get_payment(pid):
    require_role(READ_ROLES)
    rec = db.payments.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Payment not found")
    return success_object(rec)


@bp.get("/assistance/payments")
def list_payments():
    require_role(READ_ROLES)
    records = list(db.payments.values())
    for param in ("award_id", "vendor_id", "funding_source_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [p for p in records if p[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


def _get_payment_or_404(pid):
    rec = db.payments.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Payment not found")
    return rec


@bp.post("/assistance/payments/<pid>/clear")
def clear_payment(pid):
    user_id = require_role(["FinanceOfficer"])
    payment = _get_payment_or_404(pid)
    if payment["status"] != "ISSUED":
        raise_err(ERR_INVALID_PAYMENT_STATE,
                  "Only an ISSUED payment may be cleared")
    payment["status"] = "CLEARED"
    payment["cleared_at"] = db.now_iso()
    svc.touch(payment)

    award = db.awards[payment["award_id"]]
    # Find the RESERVED allocation on this award drawn from this source.
    alloc = None
    for a in db.allocations.values():
        if a["award_id"] == award["id"] \
                and a["funding_source_id"] == payment["funding_source_id"] \
                and a["status"] == "RESERVED":
            alloc = a
            break
    if alloc is not None:
        alloc["consumed_cents"] += payment["amount_cents"]
        if alloc["consumed_cents"] == alloc["allocated_cents"]:
            alloc["status"] = "CONSUMED"
        svc.touch(alloc)
    source = db.funding_sources[payment["funding_source_id"]]
    svc.recompute_source(source)
    svc.refresh_source_status(source)

    # Award bubble-up: all allocations consumed -> DISBURSED (+ application
    # APPROVED -> PAID); otherwise ACTIVE -> PARTIALLY_DISBURSED.
    remaining = [a for a in db.allocations.values()
                 if a["award_id"] == award["id"] and a["status"] == "RESERVED"]
    if len(remaining) == 0:
        award["status"] = "DISBURSED"
        svc.touch(award)
        app = db.applications[award["application_id"]]
        if app["status"] == "APPROVED":
            app["status"] = "PAID"
            svc.touch(app)
    elif award["status"] == "ACTIVE":
        award["status"] = "PARTIALLY_DISBURSED"
        svc.touch(award)
    return success_object(payment)


@bp.post("/assistance/payments/<pid>/fail")
def fail_payment(pid):
    user_id = require_role(["FinanceOfficer"])
    payment = _get_payment_or_404(pid)
    if payment["status"] != "ISSUED":
        raise_err(ERR_INVALID_PAYMENT_STATE,
                  "Only an ISSUED payment may be failed")
    payment["status"] = "FAILED"
    svc.touch(payment)
    return success_object(payment)


@bp.post("/assistance/payments/<pid>/reissue")
def reissue_payment(pid):
    user_id = require_role(["FinanceOfficer"])
    payment = _get_payment_or_404(pid)
    if payment["status"] != "FAILED":
        raise_err(ERR_INVALID_PAYMENT_STATE,
                  "Only a FAILED payment may be reissued")
    source = db.funding_sources[payment["funding_source_id"]]
    # Temporal re-validation: payment_date still inside the period.
    pay_dt = db.parse_iso(payment["payment_date"])
    if not (db.parse_iso(source["period_start"]) <= pay_dt
            < db.parse_iso(source["period_end"])):
        raise_err(ERR_SOURCE_PERIOD_CLOSED,
                  "payment_date no longer sits inside the source's funding "
                  "period")
    # Remainder re-validation against current state.
    alloc = None
    for a in db.allocations.values():
        if a["award_id"] == payment["award_id"] \
                and a["funding_source_id"] == payment["funding_source_id"] \
                and a["status"] == "RESERVED":
            alloc = a
            break
    remainder = _allocation_remainder(alloc) if alloc is not None else 0
    if payment["amount_cents"] > remainder:
        raise_err(ERR_PAYMENT_EXCEEDS_ALLOCATION,
                  "Payment amount exceeds the allocation remainder")
    payment["status"] = "ISSUED"
    svc.touch(payment)
    return success_object(payment)


@bp.post("/assistance/payments/<pid>/void")
def void_payment(pid):
    user_id = require_role(["FinanceOfficer"])
    payment = _get_payment_or_404(pid)
    if payment["status"] not in ("ISSUED", "FAILED"):
        raise_err(ERR_INVALID_PAYMENT_STATE,
                  "Only an ISSUED or FAILED payment may be voided")
    payment["status"] = "VOIDED"
    svc.touch(payment)
    return success_object(payment)


# ---------------------------------------------------------------------------
# Replenishment runs (calculation: waitlist_promotion_sweep)
# ---------------------------------------------------------------------------

@bp.post("/assistance/replenishment-runs")
def create_replenishment_run():
    user_id = require_role(["ProgramManager"])
    policy = svc.active_policy()
    if policy is None:
        raise_err(ERR_NO_ACTIVE_POLICY, "No EligibilityPolicy is ACTIVE")

    # Snapshot and order once: waitlisted_at ASC, tie-break created_at ASC.
    candidates = sorted(
        [a for a in db.applications.values() if a["status"] == "WAITLISTED"],
        key=lambda a: (a["waitlisted_at"], a["created_at"]))

    promoted = []
    denied = []
    remaining = 0
    for app in candidates:
        # (a) Re-screen income + caps against the currently ACTIVE policy.
        try:
            svc.check_fiscal_eligibility(app, policy)
        except Exception as exc:
            # Eligibility lapse -> WAITLISTED -> DENIED (ELIGIBILITY_LAPSED).
            from errors import ApiError
            if isinstance(exc, ApiError) and exc.error_id in (
                    "ERR_INCOME_LIMIT_EXCEEDED", "ERR_ANNUAL_CAP_EXCEEDED",
                    "ERR_CATEGORY_CAP_EXCEEDED"):
                app["status"] = "DENIED"
                app["denied_at"] = db.now_iso()
                app["denial_reason"] = "ELIGIBILITY_LAPSED"
                svc.touch(app)
                denied.append(app["id"])
                continue
            raise
        # (b) + (c) Award amount + allocation waterfall against current
        # balances; insufficient funds -> skip-and-continue.
        try:
            award = svc.execute_approval(app, policy)
        except Exception as exc:
            from errors import ApiError
            if isinstance(exc, ApiError) \
                    and exc.error_id == "ERR_FUNDS_EXHAUSTED":
                remaining += 1
                continue
            raise
        # Promote: re-pin policy, APPROVED.
        app["policy_id"] = policy["id"]
        app["status"] = "APPROVED"
        svc.touch(app)
        promoted.append(app["id"])

    rec = svc.stamp_new({
        "run_by": user_id,
        "promoted_count": len(promoted),
        "denied_count": len(denied),
        "remaining_waitlisted_count": remaining,
        "promoted_application_ids": promoted,
        "denied_application_ids": denied,
    }, with_version=False)
    db.replenishment_runs[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/replenishment-runs/<rid>")
def get_replenishment_run(rid):
    require_role(READ_ROLES)
    rec = db.replenishment_runs.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "ReplenishmentRun not found")
    return success_object(rec)
