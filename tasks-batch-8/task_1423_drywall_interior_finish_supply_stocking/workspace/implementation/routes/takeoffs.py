"""Takeoff and TakeoffLine endpoints."""
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_ACCOUNT_SUSPENDED, ERR_INVALID_STATE,
    ERR_EMPTY_TAKEOFF, ERR_TAKEOFF_NOT_SUBMITTED, ERR_TAKEOFF_IN_USE,
    ERR_SPECIAL_ORDER_LEAD_TIME, ERR_STALE_VERSION, ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int,
    new_common_fields, touch,
)
from services.calc import (
    effective_waste_pct_bp, compute_waste_sheets, compute_bundle_count,
    compute_line_cents, RATED_KINDS, MIN_FRAMING_PCT_FOR_RATED,
)

bp = Blueprint("takeoffs", __name__)


def _get_takeoff_or_404(tid):
    t = db.takeoffs.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, "Takeoff not found", 404)
    return t


def _get_line_or_404(lid):
    l = db.takeoff_lines.get(lid)
    if l is None:
        raise ApiError(ERR_NOT_FOUND, "TakeoffLine not found", 404)
    return l


def _active_lines(takeoff_id):
    return [
        l for l in db.takeoff_lines.values()
        if l["takeoff_id"] == takeoff_id and l["line_status"] == "ACTIVE"
    ]


@bp.route("/supply/takeoffs", methods=["POST"])
def create_takeoff():
    require_roles("EstimatorUser")
    b = body()
    require_fields(b, "project_id")
    project_id = b["project_id"]
    if not isinstance(project_id, str):
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    account = db.contractor_accounts.get(project["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    override = b.get("waste_pct_bp_override")
    if override is not None:
        if not isinstance(override, int) or isinstance(override, bool):
            raise ApiError(ERR_VALIDATION, "waste_pct_bp_override must be an integer or null", 400)
        if override < 0 or override > 2000:
            raise ApiError(ERR_VALIDATION, "waste_pct_bp_override must be in 0..2000", 400)
    t = new_common_fields()
    t.update({
        "project_id": project_id,
        "waste_pct_bp_override": override,
        "base_sheet_count": 0,
        "billable_sheet_count": 0,
        "quoted_subtotal_cents": 0,
        "final_subtotal_cents": None,
        "status": "DRAFT",
    })
    db.takeoffs[t["id"]] = t
    return success(t, status=201)


@bp.route("/supply/takeoffs/<tid>", methods=["GET"])
def get_takeoff(tid):
    require_roles("EstimatorUser", "Foreman", "CreditManager", "ContractorAdmin")
    return success(_get_takeoff_or_404(tid))


@bp.route("/supply/takeoffs", methods=["GET"])
def list_takeoffs():
    require_roles("EstimatorUser", "Foreman", "CreditManager", "ContractorAdmin")
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = list(db.takeoffs.values())
    if project_id is not None:
        items = [t for t in items if t["project_id"] == project_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/takeoffs/<tid>/lines", methods=["POST"])
def add_line(tid):
    require_roles("EstimatorUser")
    t = _get_takeoff_or_404(tid)
    b = body()
    require_fields(b, "product_id", "sheet_count")
    product_id = b["product_id"]
    if not isinstance(product_id, str):
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    sheet_count = require_int(b, "sheet_count", min_val=1)
    if t["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Lines can only be added to a DRAFT takeoff", 409)
    if not product["active"]:
        raise ApiError(ERR_VALIDATION, "Product is deactivated and may not appear on new takeoff lines", 400)
    line = new_common_fields()
    line.update({
        "takeoff_id": tid,
        "product_id": product_id,
        "sheet_count": sheet_count,
        "waste_sheets": 0,
        "bundle_count": 0,
        "quoted_line_cents": 0,
        "final_line_cents": None,
        "line_status": "ACTIVE",
    })
    db.takeoff_lines[line["id"]] = line
    return success(line, status=201)


@bp.route("/supply/takeoff-lines", methods=["GET"])
def list_lines():
    require_roles("EstimatorUser", "Foreman", "CreditManager", "ContractorAdmin")
    limit, offset = parse_pagination()
    takeoff_id = request.args.get("takeoff_id")
    product_id = request.args.get("product_id")
    line_status = request.args.get("line_status")
    items = list(db.takeoff_lines.values())
    if takeoff_id is not None:
        items = [l for l in items if l["takeoff_id"] == takeoff_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if line_status is not None:
        items = [l for l in items if l["line_status"] == line_status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/takeoff-lines/<lid>", methods=["GET"])
def get_line(lid):
    require_roles("EstimatorUser", "Foreman", "CreditManager", "ContractorAdmin")
    return success(_get_line_or_404(lid))


@bp.route("/supply/takeoffs/<tid>/lines/<lid>", methods=["DELETE"])
def cancel_line(tid, lid):
    require_roles("EstimatorUser")
    t = _get_takeoff_or_404(tid)
    l = _get_line_or_404(lid)
    if l["takeoff_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, "TakeoffLine does not belong to this takeoff", 404)
    if t["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Lines can only be cancelled while takeoff is DRAFT", 409)
    if l["line_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Line is already cancelled", 409)
    l["line_status"] = "CANCELLED"
    touch(l)
    return success(l)


@bp.route("/supply/takeoffs/<tid>/submit", methods=["POST"])
def submit_takeoff(tid):
    require_roles("EstimatorUser")
    t = _get_takeoff_or_404(tid)
    # PRD 2.8 priority: path resolution (done) -> account-posture guard
    # (ERR_ACCOUNT_SUSPENDED) -> generic state guards (ERR_INVALID_STATE)
    # -> business rules.
    project = db.projects.get(t["project_id"])
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    account = db.contractor_accounts.get(project["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    if t["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Takeoff must be DRAFT to submit", 409)

    lines = _active_lines(tid)

    # Special-order lead-time check outranks empty-takeoff (per PRD 2.8)
    rated_present = False
    for l in lines:
        p = db.products.get(l["product_id"])
        if p and p["board_kind"] in RATED_KINDS:
            rated_present = True
            break
    if rated_present and project["framing_pct_complete"] < MIN_FRAMING_PCT_FOR_RATED:
        raise ApiError(
            ERR_SPECIAL_ORDER_LEAD_TIME,
            "Rated board lines require framing_pct_complete >= 30",
            422,
        )

    if not lines:
        raise ApiError(ERR_EMPTY_TAKEOFF, "Takeoff has no ACTIVE lines", 422)

    waste_bp = effective_waste_pct_bp(t, account)
    base = 0
    billable = 0
    quoted_total = 0
    for l in lines:
        p = db.products[l["product_id"]]
        ws = compute_waste_sheets(l["sheet_count"], waste_bp)
        bc = compute_bundle_count(l["sheet_count"], ws, p["sheets_per_bundle"])
        qlc = compute_line_cents(bc, p["sheets_per_bundle"], p["unit_price_cents_per_sheet"])
        l["waste_sheets"] = ws
        l["bundle_count"] = bc
        l["quoted_line_cents"] = qlc
        touch(l)
        base += l["sheet_count"]
        billable += l["sheet_count"] + ws
        quoted_total += qlc

    t["base_sheet_count"] = base
    t["billable_sheet_count"] = billable
    t["quoted_subtotal_cents"] = quoted_total
    t["status"] = "SUBMITTED"
    touch(t)
    return success(t)


@bp.route("/supply/takeoffs/<tid>/lock", methods=["POST"])
def lock_takeoff(tid):
    require_roles("EstimatorUser")
    t = _get_takeoff_or_404(tid)
    b = body()
    require_fields(b, "expected_takeoff_version")
    expected = b["expected_takeoff_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_VALIDATION, "expected_takeoff_version must be an integer", 400)
    if t["status"] != "SUBMITTED":
        raise ApiError(ERR_TAKEOFF_NOT_SUBMITTED, "Takeoff must be SUBMITTED to lock", 409)
    if expected != t["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_takeoff_version does not match current version", 412)

    project = db.projects.get(t["project_id"])
    account = db.contractor_accounts.get(project["account_id"]) if project else None
    waste_bp = effective_waste_pct_bp(t, account)

    lines = _active_lines(tid)
    final_total = 0
    for l in lines:
        p = db.products[l["product_id"]]
        ws = compute_waste_sheets(l["sheet_count"], waste_bp)
        bc = compute_bundle_count(l["sheet_count"], ws, p["sheets_per_bundle"])
        flc = compute_line_cents(bc, p["sheets_per_bundle"], p["unit_price_cents_per_sheet"])
        l["waste_sheets"] = ws
        l["bundle_count"] = bc
        l["final_line_cents"] = flc
        touch(l)
        final_total += flc

    t["final_subtotal_cents"] = final_total
    t["status"] = "LOCKED"
    touch(t)
    return success(t)


@bp.route("/supply/takeoffs/<tid>/cancel", methods=["POST"])
def cancel_takeoff(tid):
    require_roles("EstimatorUser")
    t = _get_takeoff_or_404(tid)
    if t["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, "Takeoff cannot be cancelled from its current state", 409)
    if t["status"] == "SUBMITTED":
        in_use = any(
            o["takeoff_id"] == tid and o["status"] in ("SCHEDULED", "DISPATCHED")
            for o in db.stocking_orders.values()
        )
        if in_use:
            raise ApiError(ERR_TAKEOFF_IN_USE, "Takeoff is referenced by an in-flight StockingOrder", 409)
    t["status"] = "CANCELLED"
    touch(t)
    return success(t)
