"""Purchase-limit rules — create, list, delete."""

from __future__ import annotations

from flask import Blueprint, request

from db import db, filter_by_platform, order_by_seq, serialize, serialize_list, stamp_create
from errors import err
from lookups import get_platform, get_rule
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from validate import (
    require_enum,
    require_json,
    require_pos_int,
    require_str_array,
)

bp = Blueprint("rules", __name__)

CONTROL_CATS = {"NONE", "NARCOTIC", "PSYCHOTROPIC_I", "PSYCHOTROPIC_II", "TOXIC"}
ALLOWED_FLAGS = {"PREGNANCY", "MINOR", "RENAL_FAILURE", "GERIATRIC"}


@bp.post("/pharma-platforms/<pid>/purchase-limit-rules")
@require_roles("PlatformAdmin")
def create_rule(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    cat = require_enum(body, "control_category", CONTROL_CATS)
    window_days = require_pos_int(body, "window_days", min_val=1)
    max_units = require_pos_int(body, "max_units_per_window", min_val=1)
    blocks = require_str_array(body, "blocks_special_populations", allow_empty=True)
    for b in blocks:
        if b not in ALLOWED_FLAGS:
            raise err("ERR_INVALID_REQUEST", f"Unknown population flag: {b}")
    row = {
        "platform_id": pid,
        "control_category": cat,
        "window_days": window_days,
        "max_units_per_window": max_units,
        "blocks_special_populations": blocks,
    }
    stamp_create(row, platform)
    db.purchase_limit_rules[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/purchase-limit-rules")
@require_roles("PlatformAdmin", "PrescriptionReviewer", "PharmacistReReviewer")
def list_rules(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.purchase_limit_rules, pid)
    cat = request.args.get("control_category")
    if cat:
        rows = [r for r in rows if r.get("control_category") == cat]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.delete("/pharma-platforms/<pid>/purchase-limit-rules/<rule_id>")
@require_roles("PlatformAdmin")
def delete_rule(pid: str, rule_id: str):
    _, r = get_rule(pid, rule_id)
    db.purchase_limit_rules.pop(r["id"], None)
    return ("", 204)
