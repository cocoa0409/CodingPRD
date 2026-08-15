"""Routes: verification reports and make-goods."""
from flask import Blueprint, request

from core import (
    db, envelope_ok, paginate, sorted_items, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum, req_date, opt_int,
    err_not_found, err_invalid_state, err_invalid_request, err_forbidden,
    err_verification_overlap, err_no_breach, err_unresolved_make_goods,
    err_sod, err_credit_exceeds,
    stamp_new, touch, rate4, ceil_dec, rhu_int,
)
from domain import (
    vr_view, mg_view, get_vr, get_mg, get_li, get_io,
    reports_of_li, make_goods_of_report, fire_fraud_cascade,
)

bp = Blueprint("verify", __name__)

VENDORS = ("MOAT", "IAS", "DOUBLEVERIFY")
MG_KINDS = ("CREDIT", "BONUS_IMPRESSIONS")
MG_ACTIONS = ("APPROVE", "REJECT", "REVISE", "APPLY", "REVERSE")


@bp.route("/verification-reports", methods=["POST"])
def create_report():
    uid, _role = require_role("VerificationAnalyst")
    body = get_body()
    li_id = req_str(body, "line_item_id")
    vendor = req_enum(body, "vendor", VENDORS)
    ps_raw, ps = req_date(body, "period_start")
    pe_raw, pe = req_date(body, "period_end")
    measured = req_int(body, "measured_impressions", minimum=1)
    viewable = req_int(body, "viewable_impressions", minimum=0)
    ivt = req_int(body, "ivt_impressions", minimum=0)
    if pe <= ps:
        raise err_invalid_request("period_end must be strictly after period_start")
    if viewable > measured:
        raise err_invalid_request("viewable_impressions must not exceed measured_impressions")
    if ivt > measured:
        raise err_invalid_request("ivt_impressions must not exceed measured_impressions")

    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    if li["status"] in ("DRAFT", "CANCELLED"):
        raise err_invalid_state("Verification reports are not allowed for DRAFT or CANCELLED line items")
    # Closed-interval overlap: touching boundaries already conflict
    for other in reports_of_li(li_id):
        if other["vendor"] != vendor:
            continue
        if ps <= other["_pe"] and other["_ps"] <= pe:
            raise err_verification_overlap()

    io = get_io(li["io_id"])
    v_rate = rate4(viewable, measured)
    i_rate = rate4(ivt, measured)
    V = io["_v_threshold"]
    I = io["_i_threshold"]
    shortfall = max(0, ceil_dec(V * measured) - viewable)
    max_credit = rhu_int((ivt + shortfall) * li["cpm_rate_cents"], 1000)
    assessment = "BREACH" if (v_rate < V or i_rate > I) else "PASS"

    vr = {
        "line_item_id": li_id,
        "vendor": vendor,
        "period_start": ps_raw,
        "period_end": pe_raw,
        "_ps": ps,
        "_pe": pe,
        "measured_impressions": measured,
        "viewable_impressions": viewable,
        "ivt_impressions": ivt,
        "_viewability_rate": v_rate,
        "_ivt_rate": i_rate,
        "assessment": assessment,
        "make_good_max_credit_cents": max_credit,
        "status": "OPEN",
        "recorded_by_user_id": uid,
    }
    stamp_new(vr)
    db.verification_reports[vr["id"]] = vr

    # Fraud cascade fires only when the IVT rate exceeds the threshold
    if i_rate > I:
        fire_fraud_cascade(li)

    return envelope_ok(vr_view(vr), status=201)


@bp.route("/verification-reports", methods=["GET"])
def list_reports():
    require_role(*ANY_ROLE)
    items = list(db.verification_reports.values())
    li_id = request.args.get("line_item_id")
    if li_id is not None:
        items = [v for v in items if v["line_item_id"] == li_id]
    return paginate([vr_view(v) for v in sorted_items(items)])


@bp.route("/verification-reports/<vid>", methods=["GET"])
def get_one_report(vid):
    require_role(*ANY_ROLE)
    vr = get_vr(vid)
    if vr is None:
        raise err_not_found("Verification report not found")
    return envelope_ok(vr_view(vr), status=200)


@bp.route("/verification-reports/<vid>/transition", methods=["POST"])
def report_transition(vid):
    require_role("VerificationAnalyst")
    body = get_body()
    req_enum(body, "action", ("CLOSE_REPORT",))
    vr = get_vr(vid)
    if vr is None:
        raise err_not_found("Verification report not found")
    if vr["status"] != "OPEN":
        raise err_invalid_state("CLOSE_REPORT requires status OPEN")
    for mg in make_goods_of_report(vr["id"]):
        if mg["status"] in ("PROPOSED", "APPROVED"):
            raise err_unresolved_make_goods()
    vr["status"] = "CLOSED"
    touch(vr)
    return envelope_ok(vr_view(vr), status=200)


@bp.route("/make-goods", methods=["POST"])
def create_make_good():
    uid, _role = require_role("VerificationAnalyst")
    body = get_body()
    vr_id = req_str(body, "verification_report_id")
    kind = req_enum(body, "kind", MG_KINDS)
    credit = opt_int(body, "credit_cents", minimum=1, allow_null=True, default=None)
    bonus = opt_int(body, "bonus_impressions", minimum=1, allow_null=True, default=None)
    if kind == "CREDIT" and credit is None:
        raise err_invalid_request("credit_cents is required when kind is CREDIT")
    if kind == "BONUS_IMPRESSIONS" and bonus is None:
        raise err_invalid_request("bonus_impressions is required when kind is BONUS_IMPRESSIONS")

    vr = get_vr(vr_id)
    if vr is None:
        raise err_not_found("Verification report not found")
    if vr["assessment"] != "BREACH" or vr["status"] != "OPEN":
        raise err_no_breach()
    if kind == "CREDIT" and credit > vr["make_good_max_credit_cents"]:
        raise err_credit_exceeds()

    mg = {
        "verification_report_id": vr_id,
        "kind": kind,
        "credit_cents": credit,
        "bonus_impressions": bonus,
        "status": "PROPOSED",
        "proposed_by_user_id": uid,
        "decided_by_user_id": None,
    }
    stamp_new(mg)
    db.make_goods[mg["id"]] = mg
    return envelope_ok(mg_view(mg), status=201)


@bp.route("/make-goods", methods=["GET"])
def list_make_goods():
    require_role(*ANY_ROLE)
    items = list(db.make_goods.values())
    vr_id = request.args.get("verification_report_id")
    status = request.args.get("status")
    if vr_id is not None:
        items = [m for m in items if m["verification_report_id"] == vr_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paginate([mg_view(m) for m in sorted_items(items)])


@bp.route("/make-goods/<mid>", methods=["GET"])
def get_one_make_good(mid):
    require_role(*ANY_ROLE)
    mg = get_mg(mid)
    if mg is None:
        raise err_not_found("Make-good not found")
    return envelope_ok(mg_view(mg), status=200)


@bp.route("/make-goods/<mid>/transition", methods=["POST"])
def make_good_transition(mid):
    uid, role = require_role("BillingManager", "VerificationAnalyst")
    body = get_body()
    action = req_enum(body, "action", MG_ACTIONS)
    # Per-action role gates: REVISE belongs to the analyst, the rest to billing
    if action == "REVISE":
        if role != "VerificationAnalyst":
            raise err_forbidden("REVISE is restricted to VerificationAnalyst")
    else:
        if role != "BillingManager":
            raise err_forbidden("%s is restricted to BillingManager" % action)

    mg = get_mg(mid)
    if mg is None:
        raise err_not_found("Make-good not found")
    status = mg["status"]

    if action == "APPROVE":
        if status != "PROPOSED":
            raise err_invalid_state("APPROVE requires status PROPOSED")
        if uid == mg["proposed_by_user_id"]:
            raise err_sod("Approver must differ from proposer")
        mg["decided_by_user_id"] = uid
        mg["status"] = "APPROVED"
    elif action == "REJECT":
        if status != "PROPOSED":
            raise err_invalid_state("REJECT requires status PROPOSED")
        if uid == mg["proposed_by_user_id"]:
            raise err_sod("Rejecter must differ from proposer")
        mg["decided_by_user_id"] = uid
        mg["status"] = "REJECTED"
    elif action == "REVISE":
        if status != "REJECTED":
            raise err_invalid_state("REVISE requires status REJECTED")
        mg["decided_by_user_id"] = None
        mg["status"] = "PROPOSED"
    elif action == "APPLY":
        if status != "APPROVED":
            raise err_invalid_state("APPLY requires status APPROVED")
        mg["status"] = "APPLIED"
    elif action == "REVERSE":
        if status != "APPLIED":
            raise err_invalid_state("REVERSE requires status APPLIED")
        mg["status"] = "REVERSED"

    touch(mg)
    return envelope_ok(mg_view(mg), status=200)
