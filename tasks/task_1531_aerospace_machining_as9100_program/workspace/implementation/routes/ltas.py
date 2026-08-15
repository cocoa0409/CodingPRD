"""Long-term agreement endpoints."""

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LTA_HAS_OPEN_ORDERS,
    ERR_LTA_NOT_FOUND,
    ERR_STALE_LTA_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import rebate_preview, run_rate_audit
from validate import (
    json_body,
    no_unknown,
    paginate,
    req_int,
    req_num,
    req_str,
    opt_int,
)

bp = Blueprint("ltas", __name__)

CM = "ContractsManager"
QM = "QualityManager"


def _validate_pricing_tiers(v):
    if not isinstance(v, list) or len(v) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "pricing_tiers must be a non-empty array")
    for t in v:
        if not isinstance(t, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "pricing_tiers entries must be objects")
        mq, up = t.get("min_qty"), t.get("unit_price_cents")
        if isinstance(mq, bool) or not isinstance(mq, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "pricing_tiers.min_qty must be an integer")
        if isinstance(up, bool) or not isinstance(up, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "pricing_tiers.unit_price_cents must be an integer")
    if not any(t["min_qty"] == 1 for t in v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "pricing_tiers must include min_qty 1")
    return v


def _validate_rebate_tiers(v):
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "rebate_tiers must be an array")
    for t in v:
        if not isinstance(t, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "rebate_tiers entries must be objects")
        mi, rp = t.get("min_invoiced_cents"), t.get("rebate_pct")
        if isinstance(mi, bool) or not isinstance(mi, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "rebate_tiers.min_invoiced_cents must be an integer")
        if isinstance(rp, bool) or not isinstance(rp, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, "rebate_tiers.rebate_pct must be a number")
    return v


def get_lta(lta_id):
    lta = db.ltas.get(lta_id)
    if lta is None:
        raise ApiError(ERR_LTA_NOT_FOUND, 404, "LTA %s not found" % lta_id)
    return lta


@bp.route("/api/ltas", methods=["POST"])
def create_lta():
    require_roles(CM)
    data = json_body()
    no_unknown(
        data,
        {
            "customer_name",
            "ceiling_cents",
            "pricing_tiers",
            "committed_monthly_rate_units",
            "escalation_pct_per_year",
            "award_year",
            "rebate_tiers",
        },
    )
    customer_name = req_str(data, "customer_name")
    ceiling = req_int(data, "ceiling_cents", min_val=1)
    pricing = _validate_pricing_tiers(data.get("pricing_tiers"))
    rate = req_int(data, "committed_monthly_rate_units", min_val=1)
    esc = req_num(data, "escalation_pct_per_year")
    award_year = req_int(data, "award_year")
    rebates = _validate_rebate_tiers(data.get("rebate_tiers"))

    rec = base_record(db.new_id())
    rec.update(
        {
            "customer_name": customer_name,
            "ceiling_cents": ceiling,
            "remaining_ceiling_cents": ceiling,
            "pricing_tiers": pricing,
            "escalation_pct_per_year": esc,
            "award_year": award_year,
            "rebate_tiers": rebates,
            "committed_monthly_rate_units": rate,
            "consecutive_not_ready_count": 0,
            "last_audit_month": None,
            "last_audit_result": None,
            "status": "DRAFT",
            "_audit_month_counted": False,
        }
    )
    db.ltas[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/ltas", methods=["GET"])
def list_ltas():
    require_roles(*ALL_ROLES)
    items = list(db.ltas.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/ltas/<ltaId>", methods=["GET"])
def get_one_lta(ltaId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_lta(ltaId)))


@bp.route("/api/ltas/<ltaId>/activate", methods=["POST"])
def activate_lta(ltaId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    lta = get_lta(ltaId)
    if lta["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "LTA activation requires DRAFT")
    if (
        not lta["pricing_tiers"]
        or lta["ceiling_cents"] <= 0
        or lta["committed_monthly_rate_units"] <= 0
    ):
        raise ApiError(ERR_INVALID_REQUEST, 400, "LTA commercial terms are incomplete")
    lta["status"] = "ACTIVE"
    touch(lta)
    return success_object(public(lta))


@bp.route("/api/ltas/<ltaId>/amend", methods=["POST"])
def amend_lta(ltaId):
    require_roles(CM)
    data = json_body()
    no_unknown(
        data,
        {
            "expected_lta_version",
            "pricing_tiers",
            "ceiling_cents",
            "escalation_pct_per_year",
            "rebate_tiers",
            "committed_monthly_rate_units",
        },
    )
    if "expected_lta_version" not in data or data["expected_lta_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: expected_lta_version")
    expected = data["expected_lta_version"]
    updates = {}
    if "pricing_tiers" in data and data["pricing_tiers"] is not None:
        updates["pricing_tiers"] = _validate_pricing_tiers(data["pricing_tiers"])
    if "ceiling_cents" in data and data["ceiling_cents"] is not None:
        updates["ceiling_cents"] = req_int(data, "ceiling_cents", min_val=1)
    if "escalation_pct_per_year" in data and data["escalation_pct_per_year"] is not None:
        updates["escalation_pct_per_year"] = req_num(data, "escalation_pct_per_year")
    if "rebate_tiers" in data and data["rebate_tiers"] is not None:
        updates["rebate_tiers"] = _validate_rebate_tiers(data["rebate_tiers"])
    if "committed_monthly_rate_units" in data and data["committed_monthly_rate_units"] is not None:
        updates["committed_monthly_rate_units"] = req_int(
            data, "committed_monthly_rate_units", min_val=1
        )

    lta = get_lta(ltaId)
    # OCC (priority 4) precedes the state check (priority 5)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != lta["version"]:
        raise ApiError(ERR_STALE_LTA_VERSION, 412, "expected_lta_version is stale")
    if lta["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409, "LTA may only be amended in DRAFT or ACTIVE")

    ceiling_changed = "ceiling_cents" in updates
    lta.update(updates)
    if ceiling_changed:
        committed = sum(
            po["total_cents"]
            for po in db.purchase_orders.values()
            if po["lta_id"] == lta["id"] and po["status"] != "CANCELLED"
        )
        lta["remaining_ceiling_cents"] = lta["ceiling_cents"] - committed
    touch(lta)
    return success_object(public(lta))


@bp.route("/api/ltas/<ltaId>/close", methods=["POST"])
def close_lta(ltaId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    lta = get_lta(ltaId)
    if lta["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409, "LTA close requires ACTIVE or SUSPENDED")
    open_pos = [
        po
        for po in db.purchase_orders.values()
        if po["lta_id"] == lta["id"] and po["status"] in ("RECEIVED", "ACCEPTED", "RELEASED")
    ]
    if open_pos:
        raise ApiError(ERR_LTA_HAS_OPEN_ORDERS, 409, "LTA has open purchase orders")
    lta["status"] = "CLOSED"
    touch(lta)
    return success_object(public(lta))


@bp.route("/api/ltas/<ltaId>/reinstate", methods=["POST"])
def reinstate_lta(ltaId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    lta = get_lta(ltaId)
    if lta["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "LTA reinstate requires SUSPENDED")
    lta["status"] = "ACTIVE"
    lta["consecutive_not_ready_count"] = 0
    lta["_audit_month_counted"] = False
    touch(lta)
    return success_object(public(lta))


@bp.route("/api/ltas/<ltaId>/run-rate-audit", methods=["POST"])
def rate_audit(ltaId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, set())
    lta = get_lta(ltaId)
    run_rate_audit(lta)
    return success_object(public(lta))


@bp.route("/api/ltas/<ltaId>/rebate-preview", methods=["GET"])
def rebate(ltaId):
    require_roles(*ALL_ROLES)
    lta = get_lta(ltaId)
    raw_year = request.args.get("year")
    if raw_year is None:
        year = db.now().year
    else:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "year must be an integer")
        if str(raw_year).strip() != str(year) and not str(raw_year).strip().lstrip("+-").isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "year must be an integer")
    return success_object(rebate_preview(lta, year))
