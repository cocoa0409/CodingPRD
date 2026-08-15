"""CapitalCall / CapitalCallAssessment / Distribution routes."""
from flask import Blueprint, request

import db
from middleware import get_auth, require_roles, check_ownership
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_ASSESSMENT_NOT_PAYABLE, ERR_OVERPAYMENT,
)
from services.core import (
    get_body, check_unknown_fields, new_entity, touch, get_or_404,
    pagination_params, paginate, serialize_call, serialize_assessment,
    serialize_distribution, recompute_call,
)

bp = Blueprint("calls_distributions", __name__)
ALL_ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")


# ---------------- CapitalCall ----------------

@bp.get("/governance/capital-calls")
def list_calls():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.capital_calls.values())
    f_motion = request.args.get("motion_id")
    f_status = request.args.get("status")
    if f_motion is not None:
        items = [c for c in items if c["motion_id"] == f_motion]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_call(c) for c in page], limit, offset, total)


@bp.get("/governance/capital-calls/<cid>")
def get_call(cid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    c = get_or_404(db.capital_calls, cid, "CapitalCall")
    return success_object(serialize_call(c))


@bp.post("/governance/capital-calls/<cid>/bill")
def bill_call(cid):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    c = get_or_404(db.capital_calls, cid, "CapitalCall")
    if c["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "CapitalCall is not APPROVED")

    # snapshot shareholders: partnership_status == SHAREHOLDER exactly, any standing
    billed = [p for p in db.physicians.values()
              if p["partnership_status"] == "SHAREHOLDER"]
    total_shares = sum(p["shares_held"] for p in billed)
    from decimal import Decimal
    raw = {}
    for p in billed:
        if total_shares > 0:
            amt = (Decimal(c["total_amount_cents"]) * Decimal(p["shares_held"])
                   / Decimal(total_shares))
            raw[p["id"]] = int(amt.to_integral_value(rounding="ROUND_FLOOR"))
        else:
            raw[p["id"]] = 0
    residual = c["total_amount_cents"] - sum(raw.values())
    # PRD §3.5: residual pennies to largest holders, ties by created_at asc.
    # Under the pinned logical clock created_at can tie; the stable sort then
    # keeps insertion (creation) order — the same deterministic refinement the
    # distribution pro-rata split uses — never a random id tie-break.
    order = sorted(billed, key=lambda p: (-p["shares_held"], p["created_at"]))
    i = 0
    while residual > 0 and i < len(order):
        raw[order[i]["id"]] += 1
        residual -= 1
        i += 1

    for p in billed:
        new_entity(db.assessments, {
            "capital_call_id": c["id"],
            "physician_id": p["id"],
            "shares_at_billing": p["shares_held"],
            "assessed_cents": raw[p["id"]],
            "late_fee_cents": 0,
            "paid_cents": 0,
            "status": "BILLED",
        })

    c["status"] = "BILLED"
    recompute_call(c)
    touch(c)
    return success_object(serialize_call(c))


@bp.get("/governance/capital-calls/<cid>/assessments")
def list_call_assessments(cid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.capital_calls, cid, "CapitalCall")
    items = [a for a in db.assessments.values() if a["capital_call_id"] == cid]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.get("/governance/physicians/<pid>/assessments")
def list_physician_assessments(pid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.physicians, pid, "Physician")
    items = [a for a in db.assessments.values() if a["physician_id"] == pid]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.post("/governance/capital-call-assessments/<aid>/pay")
def pay_assessment(aid):
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["amount_cents"])
    require_roles(role, ("Physician", "BoardAdmin"))
    a = get_or_404(db.assessments, aid, "CapitalCallAssessment")
    amount = body.get("amount_cents")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    check_ownership(role, user_id, a["physician_id"])

    if a["status"] in ("PAID", "DEFAULTED"):
        raise_err(ERR_ASSESSMENT_NOT_PAYABLE,
                  "Assessment is not payable")

    total_due = a["assessed_cents"] + a["late_fee_cents"]
    remaining = total_due - a["paid_cents"]
    if amount > remaining:
        raise_err(ERR_OVERPAYMENT, "Payment exceeds remaining due")

    a["paid_cents"] += amount
    if a["paid_cents"] == total_due:
        a["status"] = "PAID"
    else:
        a["status"] = "PARTIAL"
    touch(a)

    phys = db.physicians.get(a["physician_id"])
    if phys is not None:
        phys["capital_account_balance_cents"] += amount
        touch(phys)

    call = db.capital_calls.get(a["capital_call_id"])
    if call is not None:
        recompute_call(call)
        touch(call)

    return success_object(serialize_assessment(a))


# ---------------- Distribution ----------------

@bp.get("/governance/distributions")
def list_distributions():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.distributions.values())
    f_motion = request.args.get("motion_id")
    f_status = request.args.get("status")
    if f_motion is not None:
        items = [d for d in items if d["motion_id"] == f_motion]
    if f_status is not None:
        items = [d for d in items if d["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_distribution(d) for d in page], limit, offset, total)


@bp.get("/governance/distributions/<did>")
def get_distribution(did):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    d = get_or_404(db.distributions, did, "Distribution")
    return success_object(serialize_distribution(d))


@bp.post("/governance/distributions/<did>/allocations/<physician_id>/pay")
def pay_allocation(did, physician_id):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    d = get_or_404(db.distributions, did, "Distribution")
    alloc = next((a for a in d["allocations"]
                  if a["physician_id"] == physician_id), None)
    if alloc is None:
        raise_err(ERR_NOT_FOUND, "Allocation not found")
    if d["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Distribution is not APPROVED")
    if alloc["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Allocation is not PENDING")

    alloc["status"] = "PAID"
    phys = db.physicians.get(physician_id)
    if phys is not None:
        phys["capital_account_balance_cents"] -= alloc["allocated_cents"]
        touch(phys)

    if all(a["status"] == "PAID" for a in d["allocations"]):
        d["status"] = "PAID"
    touch(d)
    return success_object(serialize_distribution(d))


@bp.post("/governance/distributions/<did>/void")
def void_distribution(did):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    d = get_or_404(db.distributions, did, "Distribution")
    if d["status"] not in ("APPROVED", "PAID"):
        raise_err(ERR_INVALID_STATE, "Distribution cannot be voided")
    for alloc in d["allocations"]:
        if alloc["status"] == "PENDING":
            alloc["status"] = "CANCELLED"
        elif alloc["status"] == "PAID":
            alloc["status"] = "CLAWED_BACK"
            phys = db.physicians.get(alloc["physician_id"])
            if phys is not None:
                phys["capital_account_balance_cents"] += alloc["allocated_cents"]
                touch(phys)
    d["status"] = "VOIDED"
    touch(d)
    return success_object(serialize_distribution(d))
