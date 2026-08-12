"""Invoice endpoints."""
from flask import Blueprint, g

import db
from lib import (
    ApiError,
    bad_request,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_int,
    optional_body,
    pagination_params,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_role,
)
from services import compute_invoice, invoice_view, recompute_case

bp = Blueprint("invoices", __name__)

READ_ROLES = ("PlatformAdmin", "CaseManager", "BillingReviewer", "Expert")
LINE_KINDS = ("PREP", "TESTIMONY", "TRAVEL_TIME")


def _validate_line_items(raw):
    if not isinstance(raw, list):
        bad_request("field 'line_items' must be an array")
    items = []
    for li in raw:
        if not isinstance(li, dict):
            bad_request("each line item must be an object")
        kind = li.get("kind")
        if kind not in LINE_KINDS:
            bad_request("line item kind must be one of %s" % list(LINE_KINDS))
        hours = li.get("hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            bad_request("line item hours must be a number")
        hours = float(hours)
        if not hours > 0:
            bad_request("line item hours must be > 0")
        items.append({"kind": kind, "hours": hours})
    return items


def _check_period(b_or_rec, from_body=True):
    if from_body:
        ps = req_dt(b_or_rec, "period_start")
        pe = req_dt(b_or_rec, "period_end")
    else:
        ps, pe = b_or_rec["period_start"], b_or_rec["period_end"]
    if db.parse_iso(pe) < db.parse_iso(ps):
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "period_end must not precede period_start"
        )
    return ps, pe


@bp.post("/litigation/engagements/<eid>/invoices")
def create_invoice(eid):
    b = body_dict()
    period_start, period_end = _check_period(b)
    line_items = _validate_line_items(b.get("line_items"))
    travel = opt_int(b, "travel_expense_cents", 0, minimum=0)
    total = req_int(b, "total_cents", minimum=0)
    require_role("Expert")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may submit invoices")
    computed, allow = compute_invoice(eng, line_items, travel)
    if total != computed:
        raise ApiError(
            "ERR_INVOICE_AMOUNT_MISMATCH",
            422,
            "declared total_cents %d != server recomputation %d" % (total, computed),
        )
    rec = db.base_record()
    rec.update(
        engagement_id=eid,
        period_start=period_start,
        period_end=period_end,
        line_items=line_items,
        travel_expense_cents=travel,
        total_cents=total,
        computed_total_cents=computed,
        status="SUBMITTED",
        dispute_count=0,
        retainer_draw_cents=0,
        billed_to_client_cents=0,
    )
    rec["_expense_allow_cents"] = allow
    db.invoices[rec["id"]] = rec
    recompute_case(eng["case_id"])
    return ok(invoice_view(rec), 201)


@bp.get("/litigation/engagements/<eid>/invoices")
def list_invoices(eid):
    limit, offset = pagination_params()
    require_role(*READ_ROLES)
    eng = get_or_404(db.engagements, eid, "engagement")
    if g.user_role == "Expert" and eng["expert_id"] != g.user_id:
        forbidden("experts may access only their own engagements")
    from flask import request as _req

    status = _req.args.get("status")
    recs = [i for i in db.invoices.values() if i["engagement_id"] == eid]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return list_ok([invoice_view(i) for i in recs], limit, offset)


def _get_invoice(iid):
    inv = get_or_404(db.invoices, iid, "invoice")
    return inv, db.engagements[inv["engagement_id"]]


@bp.post("/litigation/invoices/<iid>/approve")
def approve_invoice(iid):
    optional_body()
    require_role("BillingReviewer")
    inv, eng = _get_invoice(iid)
    if inv["status"] != "SUBMITTED":
        invalid_state("only a SUBMITTED invoice can be approved")
    if eng["status"] != "ACTIVE":
        invalid_state("invoice approval requires an ACTIVE engagement")
    case = db.cases[eng["case_id"]]
    if case["status"] == "CLOSED":
        invalid_state("invoices on a CLOSED case cannot be approved")
    # segregation of duties (before the fiscal boundary)
    if g.user_id == eng["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "the CaseManager who created the engagement cannot approve its invoices",
        )
    # fiscal boundary: equality passes
    remaining_budget = (
        case["budget_cents"]
        - case["actuals_paid_cents"]
        - case["approved_outstanding_cents"]
    )
    if inv["computed_total_cents"] > remaining_budget:
        raise ApiError(
            "ERR_BUDGET_EXCEEDED",
            422,
            "invoice exceeds the case's remaining budget",
        )
    # retainer drawdown, pinned evaluation order
    remaining_retainer = (
        eng["retainer_funded_cents"]
        - eng["retainer_drawn_cents"]
        - eng["retainer_refunded_cents"]
    )
    draw = min(inv["computed_total_cents"], remaining_retainer)
    inv["retainer_draw_cents"] = draw
    inv["billed_to_client_cents"] = inv["computed_total_cents"] - draw
    inv["status"] = "APPROVED"
    db.touch(inv)
    eng["retainer_drawn_cents"] += draw
    eng["expenses_approved_cents"] += inv.get("_expense_allow_cents", 0)
    db.touch(eng)
    recompute_case(case["id"])
    return ok(invoice_view(inv))


@bp.post("/litigation/invoices/<iid>/dispute")
def dispute_invoice(iid):
    b = body_dict()
    req_str(b, "reason")
    require_role("BillingReviewer")
    inv, eng = _get_invoice(iid)
    if inv["status"] != "SUBMITTED":
        invalid_state("only a SUBMITTED invoice can be disputed")
    inv["status"] = "DISPUTED"
    inv["dispute_count"] += 1
    db.touch(inv)
    recompute_case(eng["case_id"])
    return ok(invoice_view(inv))


@bp.post("/litigation/invoices/<iid>/resubmit")
def resubmit_invoice(iid):
    b = body_dict()
    line_items = _validate_line_items(b.get("line_items"))
    travel = opt_int(b, "travel_expense_cents", 0, minimum=0)
    total = req_int(b, "total_cents", minimum=0)
    require_role("Expert")
    inv, eng = _get_invoice(iid)
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may resubmit invoices")
    if inv["status"] != "DISPUTED":
        invalid_state("only a DISPUTED invoice can be resubmitted")
    _check_period(inv, from_body=False)  # interval rule fires first
    computed, allow = compute_invoice(eng, line_items, travel)
    if total != computed:
        raise ApiError(
            "ERR_INVOICE_AMOUNT_MISMATCH",
            422,
            "declared total_cents %d != server recomputation %d" % (total, computed),
        )
    inv["line_items"] = line_items
    inv["travel_expense_cents"] = travel
    inv["total_cents"] = total
    inv["computed_total_cents"] = computed
    inv["_expense_allow_cents"] = allow
    inv["status"] = "SUBMITTED"  # dispute_count unchanged
    db.touch(inv)
    recompute_case(eng["case_id"])
    return ok(invoice_view(inv))


@bp.post("/litigation/invoices/<iid>/settle")
def settle_invoice(iid):
    b = body_dict()
    outcome = req_enum(b, "outcome", ("PAID", "REJECTED"))
    require_role("BillingReviewer")
    inv, eng = _get_invoice(iid)
    if outcome == "PAID":
        if inv["status"] != "APPROVED":
            invalid_state("only an APPROVED invoice can be settled PAID")
    else:
        if inv["status"] != "DISPUTED":
            invalid_state("only a DISPUTED invoice can be settled REJECTED")
    inv["status"] = outcome
    db.touch(inv)
    recompute_case(eng["case_id"])
    return ok(invoice_view(inv))
