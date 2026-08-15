"""Routes: subawards and subaward invoices (closed-interval windows, MTDC cap)."""
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, require_role,
                        sh_dt, sh_int, sh_str)
from response import ok, ok_created, ok_list
from services import (SUBAWARD_MTDC_CAP, find_line, recompute_award,
                      recompute_invoice_chain)

bp = Blueprint("subawards", __name__)

RISK = {"LOW", "MEDIUM", "HIGH"}
SUB_STATUSES = {"DRAFT", "ACTIVE", "CLOSED"}
INV_STATUSES = {"RECEIVED", "UNDER_REVIEW", "PAID", "REJECTED", "RETURNED_FOR_REVISION"}


# ---------------------------------------------------------------------------
# subawards
# ---------------------------------------------------------------------------

@bp.post("/api/subawards")
def create_subaward():
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    name = sh_str(b, "subrecipient_name", sh)
    total = sh_int(b, "total_subaward_cents", sh, min_v=1)
    risk = sh_str(b, "risk_rating", sh)
    if risk is not None and risk not in RISK:
        sh.bad = True
    start = sh_dt(b, "start_date", sh)
    end = sh_dt(b, "end_date", sh)
    if start is not None and end is not None and not (end > start):
        sh.bad = True
    get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    sh.raise_if_bad()
    s = stamp_new({
        "id": new_id(), "award_id": award_id, "subrecipient_name": name,
        "total_subaward_cents": total, "risk_rating": risk,
        "start_date": start, "end_date": end, "status": "DRAFT",
        "invoiced_to_date_cents": 0, "mtdc_consumed_cents": 0,
    })
    STORES["subawards"][s["id"]] = s
    return ok_created(sz.subaward(s))


@bp.get("/api/subawards")
def list_subawards():
    auth()
    filters = {
        lambda s: s["award_id"]: request.args.get("award_id"),
        lambda s: s["status"]: request.args.get("status"),
        lambda s: s["risk_rating"]: request.args.get("risk_rating"),
    }
    items, total, limit, offset = list_page("subawards", sz.subaward, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/subawards/<sid>")
def get_subaward(sid):
    auth()
    return ok(sz.subaward(get_or_404("subawards", sid, "ERR_SUBAWARD_NOT_FOUND")))


@bp.post("/api/subawards/<sid>/activate")
def activate_subaward(sid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    s = get_or_404("subawards", sid, "ERR_SUBAWARD_NOT_FOUND")
    if s["status"] != "DRAFT":
        raise err("ERR_SUBAWARD_NOT_ACTIVE", "Activate requires subaward status DRAFT")
    prime = STORES["awards"].get(s["award_id"])
    if prime is None or prime["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Subaward activation requires the prime award ACTIVE")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(sz.subaward(s))


@bp.post("/api/subawards/<sid>/close")
def close_subaward(sid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    s = get_or_404("subawards", sid, "ERR_SUBAWARD_NOT_FOUND")
    if s["status"] != "ACTIVE":
        raise err("ERR_SUBAWARD_NOT_ACTIVE", "Close requires subaward status ACTIVE")
    if any(i["subaward_id"] == sid and i["status"] in ("RECEIVED", "UNDER_REVIEW")
           for i in STORES["invoices"].values()):
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Invoices are still in flight for this subaward")
    s["status"] = "CLOSED"
    touch(s)
    return ok(sz.subaward(s))


# ---------------------------------------------------------------------------
# subaward invoices
# ---------------------------------------------------------------------------

def _overlap_exists(subaward_id, start, end, exclude_id=None):
    """Closed-interval overlap over non-REJECTED invoices; sharing a boundary day overlaps."""
    for i in STORES["invoices"].values():
        if i["subaward_id"] != subaward_id or i["status"] == "REJECTED" or i["id"] == exclude_id:
            continue
        if start <= i["period_end"] and end >= i["period_start"]:
            return True
    return False


def _duplicate_number(subaward_id, number, exclude_id=None):
    return any(i["subaward_id"] == subaward_id and i["status"] != "REJECTED"
               and i["id"] != exclude_id and i["invoice_number"] == number
               for i in STORES["invoices"].values())


def _ceiling_exceeded(subaward, extra_direct, extra_fna, exclude_id=None):
    total = extra_direct + extra_fna
    for i in STORES["invoices"].values():
        if i["subaward_id"] == subaward["id"] and i["status"] != "REJECTED" and i["id"] != exclude_id:
            total += i["current_period_direct_cents"] + i["current_period_f_and_a_cents"]
    return total > subaward["total_subaward_cents"]


@bp.post("/api/subaward-invoices")
def create_invoice():
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    b = body()
    sh = Shape()
    sub_id = sh_str(b, "subaward_id", sh)
    number = sh_str(b, "invoice_number", sh)
    start = sh_dt(b, "period_start", sh)
    end = sh_dt(b, "period_end", sh)
    if start is not None and end is not None and not (end >= start):
        sh.bad = True
    direct = sh_int(b, "current_period_direct_cents", sh, min_v=0)
    fna = sh_int(b, "current_period_f_and_a_cents", sh, min_v=0)
    audit_ref = sh_str(b, "audit_reference", sh, required=False)
    sub = get_or_404("subawards", sub_id, "ERR_SUBAWARD_NOT_FOUND") if sub_id else None
    if sub is not None:
        # state (6): record against DRAFT or ACTIVE only
        if sub["status"] == "CLOSED":
            raise err("ERR_SUBAWARD_NOT_ACTIVE", "Recording an invoice requires a non-CLOSED subaward")
        # temporal (9): period fully inside the subaward's closed period
        if start is not None and end is not None and not (sub["start_date"] <= start and end <= sub["end_date"]):
            raise err("ERR_INVOICE_PERIOD_OUT_OF_RANGE",
                      "Invoice period must lie fully within [subaward.start_date, subaward.end_date]")
        # structural (10): closed-window overlap, then invoice-number uniqueness
        if start is not None and end is not None and _overlap_exists(sub["id"], start, end):
            raise err("ERR_INVOICE_PERIOD_OVERLAP",
                      "Invoice window overlaps a non-REJECTED invoice of the same subaward")
        if number is not None and _duplicate_number(sub["id"], number):
            raise err("ERR_DUPLICATE_INVOICE_NUMBER", "invoice_number already used within this subaward")
        # fiscal (12): cumulative ceiling including this invoice
        if direct is not None and fna is not None and _ceiling_exceeded(sub, direct, fna):
            raise err("ERR_SUBAWARD_BUDGET_EXCEEDED",
                      "Cumulative invoiced (direct + sub F&A) would exceed total_subaward_cents")
    sh.raise_if_bad()
    i = stamp_new({
        "id": new_id(), "subaward_id": sub_id, "invoice_number": number,
        "period_start": start, "period_end": end,
        "current_period_direct_cents": direct, "current_period_f_and_a_cents": fna,
        "cumulative_direct_cents": 0, "mtdc_portion_cents": 0,
        "audit_reference": audit_ref, "return_reason": None, "status": "RECEIVED",
        "prime_expenditure_id": None,
    })
    STORES["invoices"][i["id"]] = i
    recompute_invoice_chain(sub)
    touch(sub)
    return ok_created(sz.invoice(i))


@bp.get("/api/subaward-invoices")
def list_invoices():
    auth()
    filters = {
        lambda i: i["subaward_id"]: request.args.get("subaward_id"),
        lambda i: i["status"]: request.args.get("status"),
        lambda i: i.get("prime_expenditure_id"): request.args.get("prime_expenditure_id"),
    }
    items, total, limit, offset = list_page("invoices", sz.invoice, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/subaward-invoices/<iid>")
def get_invoice(iid):
    auth()
    return ok(sz.invoice(get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")))


@bp.post("/api/subaward-invoices/<iid>/begin-review")
def begin_review(iid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    i = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if i["status"] != "RECEIVED":
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Begin-review requires status RECEIVED")
    i["status"] = "UNDER_REVIEW"
    touch(i)
    return ok(sz.invoice(i))


@bp.post("/api/subaward-invoices/<iid>/approve")
def approve_invoice(iid):
    uid, role = auth()
    require_role(role, ["SponsoredProgramsOfficer"])
    i = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if i["status"] != "UNDER_REVIEW":
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Approve requires status UNDER_REVIEW")
    sub = STORES["subawards"][i["subaward_id"]]
    # state (6)
    if sub["status"] != "ACTIVE":
        raise err("ERR_SUBAWARD_NOT_ACTIVE", "Invoice approve requires subaward ACTIVE")
    prime = STORES["awards"][sub["award_id"]]
    if prime["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Invoice approve requires the prime award ACTIVE")
    # posture (7)
    if prime["posture"] == "FROZEN":
        raise err("ERR_AWARD_FROZEN", "Prime award posture FROZEN blocks invoice approval")
    b = body()
    sh = Shape()
    audit_ref = sh_str(b, "audit_reference", sh, required=False)
    # compliance (8): HIGH-risk subaward requires an audit reference
    effective_audit = audit_ref if audit_ref is not None else i.get("audit_reference")
    if sub["risk_rating"] == "HIGH" and not effective_audit:
        raise err("ERR_AUDIT_REFERENCE_REQUIRED",
                  "Approving an invoice for a HIGH-risk subaward requires audit_reference")
    amount = i["current_period_direct_cents"] + i["current_period_f_and_a_cents"]
    line = find_line(prime["id"], "SUBAWARDS")
    # fiscal (12): prime SUBAWARDS line fit
    line_auth = line["authorized_cents"] if line is not None else 0
    line_spent = line["spent_cents"] if line is not None else 0
    if line_spent + amount > line_auth:
        raise err("ERR_BUDGET_LINE_EXCEEDED", "Prime SUBAWARDS line would exceed authorized_cents")
    sh.raise_if_bad()
    # effects: prime mirror expenditure (SUBAWARD_PAYMENT), POSTED immediately
    mirror = stamp_new({
        "id": new_id(), "award_id": prime["id"],
        "budget_line_id": line["id"] if line is not None else None,
        "person_id": None, "transferred_from_id": None,
        "expenditure_type": "SUBAWARD_PAYMENT", "amount_cents": amount,
        "fringe_cents": 0, "over_cap_cents": 0,
        "mtdc_eligible_cents": i["mtdc_portion_cents"],
        "effort_pct": None, "period_months": None,
        "transaction_date": i["period_end"], "is_cost_share": False, "cash_disbursed": True,
        "is_allocable": True, "is_reasonable": True, "is_consistent": True,
        "description": None, "status": "POSTED", "disallow_reason": None,
        "posted_at": now_clock(), "invoiced_receivable_id": None,
        "submitted_by_user_id": uid,
    })
    STORES["expenditures"][mirror["id"]] = mirror
    if line is not None:
        line["spent_cents"] += amount
        touch(line)
    recompute_award(prime)
    touch(prime)
    sub["mtdc_consumed_cents"] = min(i["cumulative_direct_cents"], SUBAWARD_MTDC_CAP)
    recompute_invoice_chain(sub)
    touch(sub)
    if audit_ref is not None:
        i["audit_reference"] = audit_ref
    i["prime_expenditure_id"] = mirror["id"]
    i["status"] = "PAID"
    touch(i)
    return ok(sz.invoice(i))


@bp.post("/api/subaward-invoices/<iid>/reject")
def reject_invoice(iid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    i = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if i["status"] != "UNDER_REVIEW":
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Reject requires status UNDER_REVIEW")
    b = body()
    sh = Shape()
    reason = sh_str(b, "return_reason", sh)
    sh.raise_if_bad()
    i["status"] = "REJECTED"  # terminal; excluded from cumulative/overlap checks
    i["return_reason"] = reason
    touch(i)
    sub = STORES["subawards"][i["subaward_id"]]
    recompute_invoice_chain(sub)
    touch(sub)
    return ok(sz.invoice(i))


@bp.post("/api/subaward-invoices/<iid>/return-for-revision")
def return_invoice(iid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    i = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if i["status"] != "UNDER_REVIEW":
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Return-for-revision requires status UNDER_REVIEW")
    b = body()
    sh = Shape()
    reason = sh_str(b, "return_reason", sh)
    sh.raise_if_bad()
    i["status"] = "RETURNED_FOR_REVISION"
    i["return_reason"] = reason
    touch(i)
    return ok(sz.invoice(i))


@bp.post("/api/subaward-invoices/<iid>/resubmit")
def resubmit_invoice(iid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    i = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if i["status"] != "RETURNED_FOR_REVISION":
        raise err("ERR_INVOICE_NOT_REVIEWABLE", "Resubmit requires status RETURNED_FOR_REVISION")
    b = body()
    sh = Shape()
    direct = sh_int(b, "current_period_direct_cents", sh, min_v=0)
    fna = sh_int(b, "current_period_f_and_a_cents", sh, min_v=0)
    start = sh_dt(b, "period_start", sh, required=False)
    end = sh_dt(b, "period_end", sh, required=False)
    new_start = start if start is not None else i["period_start"]
    new_end = end if end is not None else i["period_end"]
    if not (new_end >= new_start):
        sh.bad = True
    sub = STORES["subawards"][i["subaward_id"]]
    # temporal (9)
    if not (sub["start_date"] <= new_start and new_end <= sub["end_date"]):
        raise err("ERR_INVOICE_PERIOD_OUT_OF_RANGE",
                  "Revised period must lie fully within [subaward.start_date, subaward.end_date]")
    # structural (10)
    if new_end >= new_start and _overlap_exists(sub["id"], new_start, new_end, exclude_id=i["id"]):
        raise err("ERR_INVOICE_PERIOD_OVERLAP",
                  "Revised period overlaps another non-REJECTED invoice of the subaward")
    # fiscal (12)
    if direct is not None and fna is not None and _ceiling_exceeded(sub, direct, fna, exclude_id=i["id"]):
        raise err("ERR_SUBAWARD_BUDGET_EXCEEDED",
                  "Revised cumulative (direct + sub F&A) would exceed total_subaward_cents")
    sh.raise_if_bad()
    i["current_period_direct_cents"] = direct
    i["current_period_f_and_a_cents"] = fna
    i["period_start"] = new_start
    i["period_end"] = new_end
    i["status"] = "UNDER_REVIEW"
    touch(i)
    recompute_invoice_chain(sub)
    touch(sub)
    return ok(sz.invoice(i))
