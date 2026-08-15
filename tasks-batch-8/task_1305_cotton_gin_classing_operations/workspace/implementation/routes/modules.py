"""ModuleReceipt routes."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_GROWER_NOT_FOUND,
    ERR_MODULE_NOT_FOUND,
    ERR_GIN_SHIFT_NOT_FOUND,
    ERR_DUPLICATE_TICKET_NUMBER,
    ERR_DUPLICATE_MODULE_TAG,
    ERR_DUPLICATE_BALE_TAG,
    ERR_FOREIGN_MATTER_LIMIT_EXCEEDED,
    ERR_MOISTURE_LIMIT_EXCEEDED,
    ERR_SEASON_MISMATCH,
    ERR_MODULE_NOT_QUEUABLE,
    ERR_MODULE_NOT_CONDITIONABLE,
    ERR_MODULE_NOT_GINNABLE,
    ERR_MODULE_NOT_COMPLETABLE,
    ERR_MODULE_NOT_REJECTABLE,
    ERR_SHIFT_NOT_OPEN,
    ERR_FORBIDDEN,
)
from middleware import (
    get_context,
    require_role,
    grower_owns,
    parse_pagination,
    get_json_body,
    require_fields,
    require_number,
)
from response import success_object
from services.core import stamp_new, touch, post_ledger, sorted_entities, paginate
from services.calc import compute_estimates, compute_ginning_charge_cents

bp = Blueprint("modules", __name__)


def module_out(m):
    return {
        "id": m["id"],
        "grower_id": m["grower_id"],
        "season": m["season"],
        "ticket_number": m["ticket_number"],
        "module_tag": m["module_tag"],
        "gross_weight_lbs": m["gross_weight_lbs"],
        "tare_weight_lbs": m["tare_weight_lbs"],
        "net_weight_lbs": m["net_weight_lbs"],
        "moisture_pct": m["moisture_pct"],
        "foreign_matter_pct": m["foreign_matter_pct"],
        "gin_shift_id": m["gin_shift_id"],
        "status": m["status"],
        "est_lint_lbs": m["est_lint_lbs"],
        "est_seed_lbs": m["est_seed_lbs"],
        "actual_lint_lbs": m["actual_lint_lbs"],
        "reconciled_seed_lbs": m["reconciled_seed_lbs"],
        "ginned_at": m["ginned_at"],
        "ginned_by_user_id": m["ginned_by_user_id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/gin-ops/modules", methods=["POST"])
def create_module():
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    body = get_json_body()
    require_fields(body, [
        "grower_id", "season", "ticket_number", "module_tag",
        "gross_weight_lbs", "tare_weight_lbs", "moisture_pct", "foreign_matter_pct",
    ])
    grower_id = body["grower_id"]
    if not isinstance(grower_id, str) or grower_id not in db.growers:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    season = body["season"]
    ticket = body["ticket_number"]
    tag = body["module_tag"]
    if not isinstance(season, str) or not season:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "season must be a non-empty string", status)
    if not isinstance(ticket, str) or not ticket:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "ticket_number must be a non-empty string", status)
    if not isinstance(tag, str) or not tag:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "module_tag must be a non-empty string", status)
    gross = body["gross_weight_lbs"]
    tare = body["tare_weight_lbs"]
    for v, fname in ((gross, "gross_weight_lbs"), (tare, "tare_weight_lbs")):
        if isinstance(v, bool) or not isinstance(v, int):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, f"{fname} must be an integer", status)
    net = gross - tare
    if net < 1:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "net_weight_lbs must be >= 1", status)
    moisture = require_number(body, "moisture_pct")
    fm = require_number(body, "foreign_matter_pct")
    # Body shape checks done. Now contamination safety (priority 5 in scaffold but
    # §2.9 orders state gates before safety; create has no state gate, so safety
    # applies here before uniqueness per §2.9's fixed tier order).
    if fm > 10.0:
        err_id, status = ERR_FOREIGN_MATTER_LIMIT_EXCEEDED
        raise ApiError(err_id, "foreign_matter_pct exceeds 10.0", status)
    # Uniqueness
    for m in db.modules.values():
        if m["grower_id"] == grower_id and m["season"] == season and m["ticket_number"] == ticket:
            err_id, status = ERR_DUPLICATE_TICKET_NUMBER
            raise ApiError(err_id, "ticket_number already exists for this grower and season", status)
    for m in db.modules.values():
        if m["season"] == season and m["module_tag"] == tag:
            err_id, status = ERR_DUPLICATE_MODULE_TAG
            raise ApiError(err_id, "module_tag already exists for this season", status)
    est_lint, est_seed = compute_estimates(net, moisture, fm)
    module = stamp_new({
        "grower_id": grower_id,
        "season": season,
        "ticket_number": ticket,
        "module_tag": tag,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_weight_lbs": net,
        "moisture_pct": moisture,
        "foreign_matter_pct": fm,
        "gin_shift_id": None,
        "status": "RECEIVED",
        "est_lint_lbs": est_lint,
        "est_seed_lbs": est_seed,
        "actual_lint_lbs": 0,
        "reconciled_seed_lbs": None,
        "ginned_at": None,
        "ginned_by_user_id": None,
    })
    db.modules[module["id"]] = module
    return success_object(module_out(module), 201)


@bp.route("/gin-ops/modules/<mid>", methods=["GET"])
def get_module(mid):
    user_id, role = get_context()
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    grower_owns(user_id, role, m["grower_id"])
    return success_object(module_out(m))


@bp.route("/gin-ops/modules", methods=["GET"])
def list_modules():
    user_id, role = get_context()
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.modules.values())
    if role == "Grower":
        items = [m for m in items if m["grower_id"] == user_id]
        if args.get("grower_id") and args["grower_id"] != user_id:
            err_id, status = ERR_FORBIDDEN
            raise ApiError(err_id, "Grower may only access own modules", status)
    if args.get("grower_id"):
        items = [m for m in items if m["grower_id"] == args["grower_id"]]
    if args.get("gin_shift_id"):
        items = [m for m in items if m.get("gin_shift_id") == args["gin_shift_id"]]
    if args.get("season"):
        items = [m for m in items if m["season"] == args["season"]]
    if args.get("status"):
        items = [m for m in items if m["status"] == args["status"]]
    items = sorted_entities(items)
    return paginate([module_out(m) for m in items], limit, offset)


@bp.route("/gin-ops/modules/<mid>/condition", methods=["POST"])
def condition_module(mid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    body = get_json_body()
    require_fields(body, ["moisture_pct"])
    moisture = require_number(body, "moisture_pct")
    if m["status"] not in ("RECEIVED", "CONDITIONING"):
        err_id, status = ERR_MODULE_NOT_CONDITIONABLE
        raise ApiError(err_id, "Module cannot be conditioned from its current state", status)
    m["moisture_pct"] = moisture
    est_lint, est_seed = compute_estimates(m["net_weight_lbs"], moisture, m["foreign_matter_pct"])
    m["est_lint_lbs"] = est_lint
    m["est_seed_lbs"] = est_seed
    if m["status"] == "RECEIVED":
        m["status"] = "CONDITIONING"
    else:  # CONDITIONING
        if moisture <= 12.0:
            m["status"] = "RECEIVED"
        # else stays CONDITIONING (self-loop)
    touch(m)
    return success_object(module_out(m))


@bp.route("/gin-ops/modules/<mid>/queue", methods=["POST"])
def queue_module(mid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    body = get_json_body()
    require_fields(body, ["gin_shift_id"])
    shift_id = body["gin_shift_id"]
    if not isinstance(shift_id, str) or shift_id not in db.gin_shifts:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    shift = db.gin_shifts[shift_id]
    # State gate first
    if m["status"] != "RECEIVED":
        err_id, status = ERR_MODULE_NOT_QUEUABLE
        raise ApiError(err_id, "Module must be RECEIVED to queue", status)
    # Moisture safety (12.0 exactly passes)
    if m["moisture_pct"] > 12.0:
        err_id, status = ERR_MOISTURE_LIMIT_EXCEEDED
        raise ApiError(err_id, "moisture_pct exceeds 12.0", status)
    if shift["status"] != "OPEN":
        err_id, status = ERR_SHIFT_NOT_OPEN
        raise ApiError(err_id, "Gin shift is not OPEN", status)
    if m["season"] != shift["season"]:
        err_id, status = ERR_SEASON_MISMATCH
        raise ApiError(err_id, "Module season does not match shift season", status)
    m["gin_shift_id"] = shift_id
    m["status"] = "QUEUED"
    touch(m)
    return success_object(module_out(m))


@bp.route("/gin-ops/modules/<mid>/start-ginning", methods=["POST"])
def start_ginning(mid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    if m["status"] != "QUEUED":
        err_id, status = ERR_MODULE_NOT_GINNABLE
        raise ApiError(err_id, "Module must be QUEUED to start ginning", status)
    shift = db.gin_shifts.get(m.get("gin_shift_id"))
    if shift is None or shift["status"] != "OPEN":
        err_id, status = ERR_SHIFT_NOT_OPEN
        raise ApiError(err_id, "Gin shift is not OPEN", status)
    m["status"] = "GINNING"
    touch(m)
    return success_object(module_out(m))


@bp.route("/gin-ops/modules/<mid>/complete-ginning", methods=["POST"])
def complete_ginning(mid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    body = get_json_body()
    require_fields(body, ["bales"])
    bales_payload = body["bales"]
    if not isinstance(bales_payload, list):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "bales must be a list", status)
    # State gate
    if m["status"] != "GINNING":
        err_id, status = ERR_MODULE_NOT_COMPLETABLE
        raise ApiError(err_id, "Module must be GINNING to complete", status)
    if len(bales_payload) == 0:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "bales list must be non-empty", status)
    # Validate payload shape
    tags_seen = set()
    for entry in bales_payload:
        if not isinstance(entry, dict):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "Each bale entry must be an object", status)
        require_fields(entry, ["bale_tag", "net_weight_lbs"])
        tag = entry["bale_tag"]
        w = entry["net_weight_lbs"]
        if not isinstance(tag, str) or not tag:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "bale_tag must be a non-empty string", status)
        if isinstance(w, bool) or not isinstance(w, int) or w < 1:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "bale net_weight_lbs must be >= 1", status)
        if tag in tags_seen:
            err_id, status = ERR_DUPLICATE_BALE_TAG
            raise ApiError(err_id, "Duplicate bale_tag within payload", status)
        tags_seen.add(tag)
    # Global tag uniqueness
    existing_tags = {b["bale_tag"] for b in db.bales.values()}
    for tag in tags_seen:
        if tag in existing_tags:
            err_id, status = ERR_DUPLICATE_BALE_TAG
            raise ApiError(err_id, "bale_tag already exists", status)

    # All preconditions pass; commit.
    ginned_at = db.clock_date_str()
    m["status"] = "GINNED"
    m["ginned_at"] = ginned_at
    m["ginned_by_user_id"] = user_id
    total_lint = 0
    for entry in bales_payload:
        bale = stamp_new({
            "module_id": m["id"],
            "bale_tag": entry["bale_tag"],
            "net_weight_lbs": entry["net_weight_lbs"],
            "classing_status": "UNCLASSED",
            "custody_status": "ON_GIN_FLOOR",
            "active_grade_code": None,
            "quality_points": None,
            "adjustment_cents": None,
        })
        db.bales[bale["id"]] = bale
        total_lint += entry["net_weight_lbs"]
    m["actual_lint_lbs"] = total_lint
    # Ginning charge
    charge = compute_ginning_charge_cents(m["grower_id"], m["season"], m)
    post_ledger(m["grower_id"], m["season"], "GINNING_CHARGE", -charge, m["ticket_number"])
    touch(m)
    # Recompute any draft settlements for this grower/season
    from services.calc import recompute_draft_settlements
    recompute_draft_settlements(m["grower_id"], m["season"])
    return success_object(module_out(m))


@bp.route("/gin-ops/modules/<mid>/reject", methods=["POST"])
def reject_module(mid):
    user_id, role = get_context()
    require_role(role, {"GinOperator"})
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    body = get_json_body()
    reason = body.get("reason")
    if m["status"] not in ("RECEIVED", "CONDITIONING"):
        err_id, status = ERR_MODULE_NOT_REJECTABLE
        raise ApiError(err_id, "Module cannot be rejected from its current state", status)
    m["status"] = "REJECTED"
    m["reject_reason"] = reason
    touch(m)
    return success_object(module_out(m))


@bp.route("/gin-ops/modules/<mid>/bales", methods=["GET"])
def list_module_bales(mid):
    user_id, role = get_context()
    m = db.modules.get(mid)
    if m is None:
        err_id, status = ERR_MODULE_NOT_FOUND
        raise ApiError(err_id, "Module not found", status)
    grower_owns(user_id, role, m["grower_id"])
    limit, offset = parse_pagination()
    items = [b for b in db.bales.values() if b["module_id"] == mid]
    items = sorted_entities(items)
    from routes.bales import bale_out
    return paginate([bale_out(b) for b in items], limit, offset)
