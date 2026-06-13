"""SalesReport routes (§3.8): create, submit, dispute, reconcile."""
from flask import Blueprint, request

from common import init_common, touch, require_fields, req_str, req_int, round_half_up, paginate
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import derived

bp = Blueprint("sales_reports", __name__)


def _report_vendor_id(report):
    c = db.check_ins.get(report["check_in_id"])
    if not c:
        return None
    asg = db.booth_assignments.get(c["booth_assignment_id"])
    return asg["vendor_id"] if asg else None


def _provisional_commission(report, market):
    return round_half_up(report["gross_sales_cents"] * market["commission_bps"], 10000)


@bp.route("/sales-reports", methods=["POST"])
def create_sales_report():
    user_id, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()
    require_fields(body, ["market_id", "check_in_id", "gross_sales_cents", "tokens_accepted"])
    market_id = req_str(body, "market_id")
    check_in_id = req_str(body, "check_in_id")
    gross = req_int(body, "gross_sales_cents")
    tokens = req_int(body, "tokens_accepted")

    fk_or_404("market", market_id)
    check_in = fk_or_404("check_in", check_in_id)
    if check_in["market_id"] != market_id:
        raise err("ERR_NOT_FOUND", "check_in not in market scope")

    # bounds (priority 4)
    if gross < 0:
        raise err("ERR_INVALID_REQUEST", "gross_sales_cents must be >= 0")
    if tokens < 0:
        raise err("ERR_INVALID_REQUEST", "tokens_accepted must be >= 0")

    # referential: check-in's assignment vendor (§1.4 priority 5).
    asg = db.booth_assignments.get(check_in["booth_assignment_id"])
    if asg is None:
        raise err("ERR_REFERENTIAL_MISMATCH", "check_in has no resolvable assignment")
    # Vendor ownership
    if role == "Vendor" and asg["vendor_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this check-in")

    # uniqueness: one report per check-in (ERR_DUPLICATE)
    for s in db.sales_reports.values():
        if s["check_in_id"] == check_in_id:
            raise err("ERR_DUPLICATE", "A sales report already exists for this check-in")

    report = {
        "market_id": market_id,
        "check_in_id": check_in_id,
        "gross_sales_cents": gross,
        "tokens_accepted": tokens,
        "status": "DRAFT",
        "commission_cents": 0,
        "reconciled_token_count": None,
    }
    init_common(report)
    db.sales_reports[report["id"]] = report
    return success(view(report), 201)


@bp.route("/sales-reports/<sales_report_id>", methods=["GET"])
def get_sales_report(sales_report_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    s = get_or_404("sales_report", sales_report_id)
    return success(view(s), 200)


@bp.route("/sales-reports", methods=["GET"])
def list_sales_reports():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.sales_reports.values())
    for key in ("market_id", "check_in_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/sales-reports/<sales_report_id>/submit", methods=["POST"])
def submit_sales_report(sales_report_id):
    user_id, role = get_auth()
    require_role(role, {"Vendor"})
    report = get_or_404("sales_report", sales_report_id)
    # ownership
    if _report_vendor_id(report) != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this report")
    body = get_json_body()
    # optional corrected figures
    if "gross_sales_cents" in body and body["gross_sales_cents"] is not None:
        gross = req_int(body, "gross_sales_cents")
        if gross < 0:
            raise err("ERR_INVALID_REQUEST", "gross_sales_cents must be >= 0")
        report["gross_sales_cents"] = gross
    if "tokens_accepted" in body and body["tokens_accepted"] is not None:
        tokens = req_int(body, "tokens_accepted")
        if tokens < 0:
            raise err("ERR_INVALID_REQUEST", "tokens_accepted must be >= 0")
        report["tokens_accepted"] = tokens

    # state: DRAFT or DISPUTED
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Report is not DRAFT/DISPUTED")
    # cross-entity: linked check-in must be PRESENT (ERR_SALES_NOT_PRESENT)
    check_in = db.check_ins.get(report["check_in_id"])
    if check_in is None or check_in["status"] != "PRESENT":
        raise err("ERR_SALES_NOT_PRESENT", "Linked check-in is not PRESENT")

    market = db.markets[report["market_id"]]
    report["status"] = "SUBMITTED"
    report["commission_cents"] = _provisional_commission(report, market)
    touch(report)
    return success(view(report), 200)


@bp.route("/sales-reports/<sales_report_id>/dispute", methods=["POST"])
def dispute_sales_report(sales_report_id):
    _, role = get_auth()
    require_role(role, {"MarketManager"})
    report = get_or_404("sales_report", sales_report_id)
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not SUBMITTED")
    report["status"] = "DISPUTED"
    touch(report)
    return success(view(report), 200)


@bp.route("/sales-reports/<sales_report_id>/reconcile", methods=["POST"])
def reconcile_sales_report(sales_report_id):
    _, role = get_auth()
    require_role(role, {"MarketManager"})
    report = get_or_404("sales_report", sales_report_id)
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not SUBMITTED")

    market = db.markets[report["market_id"]]
    check_in = db.check_ins[report["check_in_id"]]
    asg = db.booth_assignments[check_in["booth_assignment_id"]]
    vendor_id = asg["vendor_id"]
    market_day_id = check_in["market_day_id"]

    # cross-entity: all VoucherRedemption rows for same vendor+day must be RECONCILED
    relevant = [r for r in db.voucher_redemptions.values()
                if r["vendor_id"] == vendor_id and r["market_day_id"] == market_day_id]
    for r in relevant:
        if r["status"] == "SUBMITTED":
            raise err("ERR_INVALID_STATE",
                      "All voucher redemptions for this vendor+day must be RECONCILED")

    # token-reconciled basis (§3.8)
    reconciled_tokens = sum(r["token_count"] for r in relevant if r["status"] == "RECONCILED")
    reconciled_token_count = min(report["tokens_accepted"], reconciled_tokens)
    token_backed_sales = reconciled_token_count * market["voucher_face_value_cents"]
    verified_sales = min(report["gross_sales_cents"], token_backed_sales)
    final_commission = round_half_up(verified_sales * market["commission_bps"], 10000)

    report["reconciled_token_count"] = reconciled_token_count
    report["commission_cents"] = final_commission
    report["status"] = "RECONCILED"
    touch(report)
    # ledger sync (§2.9): recompute total_commission_accrued and bump market version
    derived.recompute_market_commission(market, force_bump=True)
    return success(view(report), 200)
