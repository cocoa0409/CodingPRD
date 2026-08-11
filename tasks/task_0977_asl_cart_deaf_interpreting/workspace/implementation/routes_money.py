"""Routes: invoices, complaints, credit memos, reporting snapshots."""
from decimal import Decimal

from flask import Blueprint

import core
from core import (DB, now, auth_ctx, require_role, check_ownership, get_body,
                  envelope, paginate, sort_by_created, req_str, opt_str,
                  req_enum, req_int, opt_int, req_dt, opt_num, err, new_id)
from domain import (COMPLAINT_CATEGORIES, SEVERITIES, PENALTY,
                    CREDIT_PCT_DEFAULT, ADA_CONTEXTS, touch, rhu, rhu_dec,
                    ser_invoice, ser_complaint, ser_credit_memo, ser_report,
                    get_assignment, get_request, get_invoice, get_complaint,
                    get_memo, get_org, get_report, get_interpreter,
                    encounter_of_assignment, invoice_of_assignment,
                    build_invoice_line_items, recompute_invoice,
                    create_credit_memo)

bp = Blueprint("money", __name__)


# --------------------------------------------------------------------------
# Invoice
# --------------------------------------------------------------------------
@bp.route("/invoices/generate", methods=["POST"])
def generate_invoice():
    auth = auth_ctx()
    body = get_body(allowed_fields={"assignment_id"}, require=True)
    require_role(auth[1], "BillingClerk")
    assignment_id = req_str(body, "assignment_id")
    a = get_assignment(assignment_id)
    req = get_request(a["request_id"])
    if a["status"] != "COMPLETED":
        err(core.E_INVALID, 400,
            "Invoice generation requires a COMPLETED assignment")
    encounter = encounter_of_assignment(a["id"])
    if encounter is None or not encounter["verified"]:
        err(core.E_ENC_NOT_VERIFIED, 409, "Encounter is not verified")
    if invoice_of_assignment(a["id"]) is not None:
        err(core.E_INVOICE_EXISTS, 409,
            "An invoice already exists for this assignment")
    lines = build_invoice_line_items(a, req, encounter)
    subtotal = sum(li["amount_cents"] for li in lines)
    inv = {
        "id": new_id(), "org_id": req["org_id"], "assignment_id": a["id"],
        "encounter_id": encounter["id"],
        "issue_status": "DRAFT", "dispute_status": "NONE",
        "payment_status": "UNPAID", "line_items": lines,
        "subtotal_cents": subtotal, "credits_applied_cents": 0,
        "payments_applied_cents": 0, "amount_due_cents": subtotal,
        "issued_at": None, "dispute_reason": None,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.invoices[inv["id"]] = inv
    return envelope(ser_invoice(inv), code=201)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    auth_ctx()
    args = core.request.args
    items = list(DB.invoices.values())
    for f in ("org_id", "encounter_id", "issue_status", "payment_status",
              "dispute_status"):
        v = args.get(f)
        if v is not None:
            items = [i for i in items if i[f] == v]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_invoice(i) for i in page], pagination=meta)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice_route(iid):
    auth_ctx()
    return envelope(ser_invoice(get_invoice(iid)))


@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "BillingClerk")
    inv = get_invoice(iid)
    if inv["issue_status"] != "DRAFT":
        err(core.E_INV_NOT_DRAFT, 409, "Issue requires invoice status DRAFT")
    inv["issue_status"] = "ISSUED"
    inv["issued_at"] = now()
    touch(inv)
    return envelope(ser_invoice(inv))


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "BillingClerk")
    inv = get_invoice(iid)
    if inv["issue_status"] == "DRAFT":
        inv["issue_status"] = "VOID"
        touch(inv)
        return envelope(ser_invoice(inv))
    if inv["issue_status"] != "ISSUED":
        err(core.E_INVALID, 400, "Invoice cannot be voided from its current state")
    if inv["payments_applied_cents"] != 0 or inv["dispute_status"] == "OPEN":
        err(core.E_INVALID, 400,
            "Void requires zero payments and no open dispute")
    # Reverse every credit-memo application against this invoice
    for memo in DB.credit_memos.values():
        for ap in memo["applications"]:
            if ap["invoice_id"] == inv["id"] and not ap["reversed"]:
                ap["reversed"] = True
                inv["credits_applied_cents"] -= ap["amount_cents"]
                memo["remaining_cents"] += ap["amount_cents"]
                if memo["status"] == "EXHAUSTED":
                    memo["status"] = "OPEN"
                touch(memo)
    inv["issue_status"] = "VOID"
    recompute_invoice(inv)
    return envelope(ser_invoice(inv))


@bp.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"reason"}, require=True)
    require_role(auth[1], "OrgRequester")
    reason = req_str(body, "reason")
    inv = get_invoice(iid)
    check_ownership(inv["org_id"] == auth[0])
    org = get_org(inv["org_id"])
    if org["status"] != "ACTIVE":
        err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
    if inv["issue_status"] != "ISSUED":
        err(core.E_INV_NOT_ISSUED, 409, "Dispute requires invoice status ISSUED")
    if inv["dispute_status"] != "NONE":
        err(core.E_INVALID, 400, "Dispute requires dispute_status NONE")
    inv["dispute_status"] = "OPEN"
    inv["dispute_reason"] = reason
    touch(inv)
    return envelope(ser_invoice(inv))


@bp.route("/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_dispute(iid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"outcome", "adjustment_cents"}, require=True)
    require_role(auth[1], "BillingClerk")
    outcome = req_enum(body, "outcome", {"UPHELD", "OVERTURNED"})
    adjustment = opt_int(body, "adjustment_cents", None)
    inv = get_invoice(iid)
    if inv["dispute_status"] != "OPEN":
        err(core.E_INV_NOT_DISPUTED, 409, "Resolve requires an OPEN dispute")
    if outcome == "UPHELD":
        inv["dispute_status"] = "RESOLVED_UPHELD"
        touch(inv)
        return envelope(ser_invoice(inv))
    # OVERTURNED
    if adjustment is None or adjustment <= 0:
        err(core.E_INVALID, 400,
            "OVERTURNED resolution requires a positive adjustment_cents")
    if adjustment > inv["amount_due_cents"] + inv["credits_applied_cents"]:
        err(core.E_INVALID, 400,
            "adjustment_cents exceeds amount_due_cents + credits_applied_cents")
    inv["line_items"].append({"kind": "ADJUSTMENT", "quantity": 1,
                              "unit_rate_cents": -adjustment,
                              "amount_cents": -adjustment})
    inv["subtotal_cents"] = sum(li["amount_cents"] for li in inv["line_items"])
    inv["dispute_status"] = "RESOLVED_OVERTURNED"
    recompute_invoice(inv)
    return envelope(ser_invoice(inv))


@bp.route("/invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"amount_cents"}, require=True)
    require_role(auth[1], "BillingClerk")
    amount = req_int(body, "amount_cents", minimum=1)
    inv = get_invoice(iid)
    if inv["issue_status"] != "ISSUED":
        err(core.E_INV_NOT_ISSUED, 409, "Payment requires invoice status ISSUED")
    if amount > inv["amount_due_cents"]:
        err(core.E_OVERPAY, 422, "Payment exceeds amount_due_cents")
    inv["payments_applied_cents"] += amount
    recompute_invoice(inv)
    return envelope(ser_invoice(inv))


# --------------------------------------------------------------------------
# Complaint
# --------------------------------------------------------------------------
@bp.route("/complaints", methods=["POST"])
def create_complaint():
    auth = auth_ctx()
    body = get_body(allowed_fields={"org_id", "assignment_id", "category",
                                    "severity", "narrative"}, require=True)
    require_role(auth[1], "OrgRequester")
    org_id = req_str(body, "org_id")
    check_ownership(org_id == auth[0])
    assignment_id = req_str(body, "assignment_id")
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)
    severity = req_enum(body, "severity", SEVERITIES)
    narrative = req_str(body, "narrative")
    org = get_org(org_id)
    a = get_assignment(assignment_id)
    req = get_request(a["request_id"])
    if org["status"] != "ACTIVE":
        err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
    if req["org_id"] != org_id or a["status"] not in ("COMPLETED", "NO_SHOW"):
        err(core.E_COMPLAINT_STATE, 409,
            "Complaint requires an own-org assignment in COMPLETED or NO_SHOW")
    complaint = {
        "id": new_id(), "org_id": org_id, "assignment_id": a["id"],
        "interpreter_id": a["interpreter_id"], "category": category,
        "severity": severity, "narrative": narrative,
        "status": "FILED", "penalty_points": None, "credit_pct": None,
        "credit_amount_cents": None, "reopen_count": 0,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.complaints[complaint["id"]] = complaint
    return envelope(ser_complaint(complaint), code=201)


@bp.route("/complaints/<cid>", methods=["GET"])
def get_complaint_route(cid):
    auth_ctx()
    return envelope(ser_complaint(get_complaint(cid)))


@bp.route("/complaints/<cid>/begin-review", methods=["POST"])
def begin_review(cid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "QualityReviewer")
    c = get_complaint(cid)
    if c["status"] != "FILED":
        err(core.E_COMPLAINT_STATE, 409, "Begin-review requires status FILED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return envelope(ser_complaint(c))


@bp.route("/complaints/<cid>/adjudicate", methods=["POST"])
def adjudicate(cid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"outcome", "credit_pct_override"}, require=True)
    require_role(auth[1], "QualityReviewer")
    outcome = req_enum(body, "outcome", {"SUBSTANTIATED", "DISMISSED"})
    override = opt_num(body, "credit_pct_override", None, minimum=0, maximum=1)
    c = get_complaint(cid)
    if c["status"] != "UNDER_REVIEW":
        err(core.E_COMPLAINT_STATE, 409, "Adjudicate requires status UNDER_REVIEW")
    if outcome == "DISMISSED":
        c["status"] = "DISMISSED"
        touch(c)
        return envelope(ser_complaint(c))
    # SUBSTANTIATED: penalty + credit + auto memo + waterfall
    c["status"] = "SUBSTANTIATED"
    c["penalty_points"] = PENALTY[c["severity"]]
    pct = (Decimal(str(override)) if override is not None
           else CREDIT_PCT_DEFAULT[c["severity"]])
    c["credit_pct"] = float(pct)
    a = DB.assignments.get(c["assignment_id"])
    base = 0
    if a is not None:
        inv = invoice_of_assignment(a["id"])
        if inv is not None and inv["issue_status"] == "ISSUED":
            base = inv["subtotal_cents"]
        else:
            base = a["estimated_cost_cents"]
    c["credit_amount_cents"] = rhu(pct * Decimal(base))
    touch(c)
    org = DB.orgs.get(c["org_id"])
    if org is not None:
        create_credit_memo(org, c["credit_amount_cents"], complaint_id=c["id"])
    return envelope(ser_complaint(c))


@bp.route("/complaints/<cid>/reopen", methods=["POST"])
def reopen_complaint(cid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "OrgRequester")
    c = get_complaint(cid)
    check_ownership(c["org_id"] == auth[0])
    if c["status"] != "DISMISSED":
        err(core.E_COMPLAINT_STATE, 409, "Reopen requires status DISMISSED")
    if c["reopen_count"] >= 1:
        err(core.E_COMPLAINT_REOPENED, 409, "Complaint was already reopened once")
    c["status"] = "UNDER_REVIEW"
    c["reopen_count"] += 1
    touch(c)
    return envelope(ser_complaint(c))


@bp.route("/complaints/<cid>/credit-memos", methods=["GET"])
def complaint_credit_memos(cid):
    auth_ctx()
    get_complaint(cid)
    items = [m for m in DB.credit_memos.values() if m["complaint_id"] == cid]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_credit_memo(m) for m in page], pagination=meta)


# --------------------------------------------------------------------------
# CreditMemo
# --------------------------------------------------------------------------
@bp.route("/credit-memos", methods=["POST"])
def create_memo_route():
    auth = auth_ctx()
    body = get_body(allowed_fields={"org_id", "amount_cents",
                                    "expected_org_version", "complaint_id"},
                    require=True)
    require_role(auth[1], "QualityReviewer", "BillingClerk")
    org_id = req_str(body, "org_id")
    amount = req_int(body, "amount_cents", minimum=1)
    expected = req_int(body, "expected_org_version")
    complaint_id = body.get("complaint_id")
    if complaint_id is not None and not isinstance(complaint_id, str):
        err(core.E_INVALID, 400, "Field 'complaint_id' must be a string")
    org = get_org(org_id)
    if complaint_id is not None:
        get_complaint(complaint_id)
    if expected != org["version"]:
        err(core.E_STALE_ORG, 412,
            "expected_org_version does not match the org's current version")
    memo = create_credit_memo(org, amount, complaint_id=complaint_id)
    return envelope(ser_credit_memo(memo), code=201)


@bp.route("/credit-memos/<mid>", methods=["GET"])
def get_memo_route(mid):
    auth_ctx()
    return envelope(ser_credit_memo(get_memo(mid)))


@bp.route("/credit-memos/<mid>/void", methods=["POST"])
def void_memo(mid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "BillingClerk")
    memo = get_memo(mid)
    if memo["status"] not in ("OPEN", "EXHAUSTED"):
        err(core.E_MEMO_NOT_OPEN, 409,
            "Void requires memo status OPEN or EXHAUSTED")
    memo["status"] = "VOID"
    # Reverse every application on its invoices
    for ap in memo["applications"]:
        if ap["reversed"]:
            continue
        ap["reversed"] = True
        inv = DB.invoices.get(ap["invoice_id"])
        if inv is not None:
            inv["credits_applied_cents"] -= ap["amount_cents"]
            recompute_invoice(inv)
    memo["remaining_cents"] = memo["amount_cents"]
    touch(memo)
    org = DB.orgs.get(memo["org_id"])
    if org is not None:
        touch(org)
    return envelope(ser_credit_memo(memo))


# --------------------------------------------------------------------------
# ReportingSnapshot
# --------------------------------------------------------------------------
@bp.route("/reports/generate", methods=["POST"])
def generate_report():
    auth = auth_ctx()
    body = get_body(allowed_fields={"window_start", "window_end", "org_id"},
                    require=True)
    require_role(auth[1], "PlatformAdmin")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    org_id = opt_str(body, "org_id")
    if window_end <= window_start:
        err(core.E_INVALID, 400, "window_end must be later than window_start")
    if org_id is not None:
        get_org(org_id)

    def in_window(dt):
        return window_start <= dt < window_end

    requests = [r for r in DB.requests.values()
                if in_window(r["scheduled_start"])
                and (org_id is None or r["org_id"] == org_id)]
    total = len(requests)
    filled = sum(1 for r in requests
                 if r["status"] in ("CONFIRMED", "IN_PROGRESS", "COMPLETED", "CLOSED"))
    unfilled = sum(1 for r in requests if r["status"] == "UNFILLED")
    cancelled = sum(1 for r in requests if r["status"] == "CANCELLED")
    denom = total - cancelled
    fulfillment = float(rhu_dec(Decimal(filled) / Decimal(denom), 4)) if denom > 0 else 0.0

    req_ids = {r["id"] for r in requests}
    no_show = 0
    response_samples = []
    for a in DB.assignments.values():
        a_req = DB.requests.get(a["request_id"])
        if a_req is None:
            continue
        if org_id is not None and a_req["org_id"] != org_id:
            continue
        if a["status"] == "NO_SHOW" and in_window(a_req["scheduled_start"]):
            no_show += 1
        if a["accepted_at"] is not None and in_window(a["offered_at"]):
            response_samples.append(
                (a["accepted_at"] - a["offered_at"]).total_seconds() / 60.0)
    if response_samples:
        avg_response = float(rhu_dec(
            Decimal(sum(response_samples)) / Decimal(len(response_samples)), 2))
    else:
        avg_response = 0.0

    total_billed = 0
    for inv in DB.invoices.values():
        if (inv["issue_status"] == "ISSUED" and inv["issued_at"] is not None
                and in_window(inv["issued_at"])
                and (org_id is None or inv["org_id"] == org_id)):
            total_billed += inv["subtotal_cents"]

    complaints = [c for c in DB.complaints.values()
                  if in_window(c["created_at"])
                  and (org_id is None or c["org_id"] == org_id)]
    complaint_count = len(complaints)
    substantiated = sum(1 for c in complaints if c["status"] == "SUBSTANTIATED")

    mix = {ctx: 0 for ctx in sorted(ADA_CONTEXTS)}
    for r in requests:
        mix[r["ada_context"]] += 1

    report = {
        "id": new_id(), "org_id": org_id,
        "window_start": window_start, "window_end": window_end,
        "generated_at": now(),
        "total_requests": total, "filled_count": filled,
        "unfilled_count": unfilled, "cancelled_count": cancelled,
        "fulfillment_rate": fulfillment, "no_show_count": no_show,
        "avg_response_minutes": avg_response,
        "total_billed_cents": total_billed,
        "complaint_count": complaint_count,
        "substantiated_count": substantiated,
        "ada_context_mix": mix,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.reports[report["id"]] = report
    return envelope(ser_report(report), code=201)


@bp.route("/reports", methods=["GET"])
def list_reports():
    auth_ctx()
    org_id = core.request.args.get("org_id")
    items = list(DB.reports.values())
    if org_id is not None:
        items = [r for r in items if r["org_id"] == org_id]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_report(r) for r in page], pagination=meta)


@bp.route("/reports/<rid>", methods=["GET"])
def get_report_route(rid):
    auth_ctx()
    return envelope(ser_report(get_report(rid)))
