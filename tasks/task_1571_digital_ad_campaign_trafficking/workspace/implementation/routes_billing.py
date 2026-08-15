"""Routes: reconciliations and wrap reports."""
from flask import Blueprint, request

from core import (
    db, envelope_ok, paginate, sorted_items, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum, req_date,
    err_not_found, err_invalid_state, err_invalid_request,
    err_recon_overlap, err_unresolved_make_goods, err_sod,
    err_recon_not_locked,
    stamp_new, touch,
)
from domain import (
    rec_view, wrap_view, get_rec, get_wrap, get_li, get_io,
    recs_of_li, reports_of_li, make_goods_of_report, delivered,
    reconcile_compute, agency_impressions_for, line_items_of_io,
    compute_attribution, io_applied_credit,
)

bp = Blueprint("billing", __name__)

REC_ACTIONS = ("RECONCILE", "LOCK", "REOPEN")
ATTRIBUTION_MODELS = ("LINEAR_CLICKS", "VIEW_WEIGHTED")


@bp.route("/reconciliations", methods=["POST"])
def create_reconciliation():
    require_role("BillingManager")
    body = get_body()
    li_id = req_str(body, "line_item_id")
    ps_raw, ps = req_date(body, "period_start")
    pe_raw, pe = req_date(body, "period_end")
    tp = req_int(body, "third_party_impressions", minimum=0)
    if pe <= ps:
        raise err_invalid_request("period_end must be strictly after period_start")

    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    # Half-open [start, end): adjacency allowed, true overlap rejected
    for other in recs_of_li(li_id):
        if ps < other["_pe"] and other["_ps"] < pe:
            raise err_recon_overlap()

    rec = {
        "line_item_id": li_id,
        "period_start": ps_raw,
        "period_end": pe_raw,
        "_ps": ps,
        "_pe": pe,
        "third_party_impressions": tp,
        "agency_impressions": agency_impressions_for(li_id, ps, pe),
        "_discrepancy_pct": None,
        "billing_impressions": None,
        "billable_cents": None,
        "status": "OPEN",
        "reconciled_by_user_id": None,
        "locked_by_user_id": None,
    }
    stamp_new(rec)
    db.reconciliations[rec["id"]] = rec
    return envelope_ok(rec_view(rec), status=201)


@bp.route("/reconciliations", methods=["GET"])
def list_reconciliations():
    require_role(*ANY_ROLE)
    items = list(db.reconciliations.values())
    li_id = request.args.get("line_item_id")
    status = request.args.get("status")
    if li_id is not None:
        items = [r for r in items if r["line_item_id"] == li_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([rec_view(r) for r in sorted_items(items)])


@bp.route("/reconciliations/<rid>", methods=["GET"])
def get_one_reconciliation(rid):
    require_role(*ANY_ROLE)
    rec = get_rec(rid)
    if rec is None:
        raise err_not_found("Reconciliation not found")
    return envelope_ok(rec_view(rec), status=200)


@bp.route("/reconciliations/<rid>/transition", methods=["POST"])
def reconciliation_transition(rid):
    uid, _role = require_role("BillingManager")
    body = get_body()
    action = req_enum(body, "action", REC_ACTIONS)
    rec = get_rec(rid)
    if rec is None:
        raise err_not_found("Reconciliation not found")
    status = rec["status"]

    if action == "RECONCILE":
        if status != "OPEN":
            raise err_invalid_state("RECONCILE requires status OPEN")
        reconcile_compute(rec)
        rec["reconciled_by_user_id"] = uid
        rec["status"] = "RECONCILED"

    elif action == "LOCK":
        if status != "RECONCILED":
            raise err_invalid_state("LOCK requires status RECONCILED")
        # Unresolved make-goods on reports of this line item whose closed
        # measurement period overlaps this reconciliation's half-open period
        for vr in reports_of_li(rec["line_item_id"]):
            if vr["_ps"] < rec["_pe"] and rec["_ps"] <= vr["_pe"]:
                for mg in make_goods_of_report(vr["id"]):
                    if mg["status"] in ("PROPOSED", "APPROVED"):
                        raise err_unresolved_make_goods()
        if uid == rec["reconciled_by_user_id"]:
            raise err_sod("Locker must differ from reconciler")
        rec["locked_by_user_id"] = uid
        rec["status"] = "LOCKED"

    elif action == "REOPEN":
        if status != "RECONCILED":
            raise err_invalid_state("REOPEN requires status RECONCILED")
        rec["reconciled_by_user_id"] = None
        rec["status"] = "OPEN"

    touch(rec)
    return envelope_ok(rec_view(rec), status=200)


@bp.route("/wrap-reports", methods=["POST"])
def create_wrap_report():
    require_role("BillingManager")
    body = get_body()
    io_id = req_str(body, "io_id")
    model = req_enum(body, "attribution_model", ATTRIBUTION_MODELS)
    total_conversions = req_int(body, "total_conversions", minimum=0)

    io = get_io(io_id)
    if io is None:
        raise err_not_found("Insertion order not found")
    if io["status"] != "COMPLETED":
        raise err_invalid_state("Wrap report generation requires the insertion order to be COMPLETED")
    for li in line_items_of_io(io_id):
        for rec in recs_of_li(li["id"]):
            if rec["status"] != "LOCKED":
                raise err_recon_not_locked()

    lis = sorted_items([li for li in line_items_of_io(io_id) if li["status"] != "CANCELLED"])
    total_delivered = 0
    total_spend = 0
    for li in lis:
        imps, _clicks, spend = delivered(li["id"])
        total_delivered += imps
        total_spend += spend
    total_billable = 0
    for li in lis:
        for rec in recs_of_li(li["id"]):
            if rec["status"] == "LOCKED" and rec["billable_cents"] is not None:
                total_billable += rec["billable_cents"]
    total_credit = io_applied_credit(io_id)
    net = max(0, total_billable - total_credit)
    attribution = compute_attribution(lis, model, total_conversions)

    w = {
        "io_id": io_id,
        "attribution_model": model,
        "total_conversions": total_conversions,
        "status": "DRAFT",
        "total_delivered_impressions": total_delivered,
        "total_spend_cents": total_spend,
        "total_billable_cents": total_billable,
        "total_applied_credit_cents": total_credit,
        "net_billable_cents": net,
        "attribution": attribution,
    }
    stamp_new(w)
    db.wrap_reports[w["id"]] = w
    return envelope_ok(wrap_view(w), status=201)


@bp.route("/wrap-reports", methods=["GET"])
def list_wrap_reports():
    require_role(*ANY_ROLE)
    items = list(db.wrap_reports.values())
    io_id = request.args.get("io_id")
    if io_id is not None:
        items = [w for w in items if w["io_id"] == io_id]
    return paginate([wrap_view(w) for w in sorted_items(items)])


@bp.route("/wrap-reports/<wid>", methods=["GET"])
def get_one_wrap_report(wid):
    require_role(*ANY_ROLE)
    w = get_wrap(wid)
    if w is None:
        raise err_not_found("Wrap report not found")
    return envelope_ok(wrap_view(w), status=200)


@bp.route("/wrap-reports/<wid>/transition", methods=["POST"])
def wrap_report_transition(wid):
    require_role("BillingManager")
    body = get_body()
    req_enum(body, "action", ("FINALIZE",))
    w = get_wrap(wid)
    if w is None:
        raise err_not_found("Wrap report not found")
    if w["status"] != "DRAFT":
        raise err_invalid_state("FINALIZE requires status DRAFT")
    w["status"] = "FINALIZED"
    touch(w)
    io = get_io(w["io_id"])
    if io is not None and io["status"] == "COMPLETED":
        io["status"] = "CLOSED"
        touch(io)
    return envelope_ok(wrap_view(w), status=200)
