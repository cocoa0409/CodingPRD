"""BillingRule endpoints (draft / publish / list)."""
from flask import Blueprint, request, g

import db
from clock import iso, now
from errors import err
from middleware import require_auth
from response import success, success_list


bp = Blueprint("billing_rules", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _require_int(d, key, lo=None, hi=None):
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_BAD_REQUEST", f"{key} must be an integer")
    if lo is not None and v < lo:
        raise err("ERR_BAD_REQUEST", f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        raise err("ERR_BAD_REQUEST", f"{key} must be <= {hi}")
    return v


def _check_equipment_owner(eq):
    lab = db.labs.get(eq["lab_id"])
    if lab is None or lab["contact_user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the lab owner of this equipment")


@bp.post("/equipment/<equipment_id>/billing-rules")
@require_auth(roles={"LabOwner"})
def create_billing_rule(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    _check_equipment_owner(eq)
    body = _get_body()
    mode = body.get("mode")
    if mode not in ("BY_TIME", "BY_SAMPLE", "HYBRID"):
        raise err("ERR_BAD_REQUEST", "mode must be BY_TIME|BY_SAMPLE|HYBRID")

    fields = [
        "internal_rate_per_hour_cents",
        "external_rate_per_hour_cents",
        "inter_school_rate_per_hour_cents",
        "internal_rate_per_sample_cents",
        "external_rate_per_sample_cents",
        "inter_school_rate_per_sample_cents",
        "peak_multiplier_bps",
        "consumables_flat_cents",
        "platform_fee_bps",
    ]
    parsed = {}
    for f in fields:
        parsed[f] = _require_int(body, f, lo=0)
    if parsed["platform_fee_bps"] > 10000:
        raise err("ERR_BAD_REQUEST", "platform_fee_bps must be <= 10000")

    rule = {
        "id": db.gen_id(),
        "equipment_id": equipment_id,
        "rule_version": None,
        "mode": mode,
        **parsed,
        "status": "DRAFT",
        "published_at": None,
        "created_at": iso(now()),
        "_seq": db.next_seq(),
    }
    db.billing_rules[rule["id"]] = rule
    return success(db.public(rule), status=201)


@bp.post("/equipment/<equipment_id>/billing-rules/<rule_id>/publish")
@require_auth(roles={"LabOwner"})
def publish_billing_rule(equipment_id, rule_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    rule = db.billing_rules.get(rule_id)
    if rule is None or rule["equipment_id"] != equipment_id:
        raise err("ERR_NOT_FOUND", "billing rule not found")
    _check_equipment_owner(eq)
    if rule["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "rule is not in DRAFT")

    lab = db.labs[eq["lab_id"]]
    # ERR_FEE_SPLIT_INVALID
    if rule["platform_fee_bps"] + lab["revenue_share_bps"] > 10000:
        raise err("ERR_FEE_SPLIT_INVALID", "platform_fee_bps + revenue_share_bps > 10000")

    # Supersede previous PUBLISHED rule for the same equipment
    max_version = 0
    for r in db.billing_rules.values():
        if r["equipment_id"] != equipment_id:
            continue
        if r["rule_version"] is not None and r["rule_version"] > max_version:
            max_version = r["rule_version"]
        if r["status"] == "PUBLISHED":
            r["status"] = "SUPERSEDED"
    rule["rule_version"] = max_version + 1
    rule["status"] = "PUBLISHED"
    rule["published_at"] = iso(now())
    eq["active_billing_rule_id"] = rule["id"]
    db.stamp_update(eq)
    return success(db.public(rule))


@bp.get("/equipment/<equipment_id>/billing-rules")
@require_auth(roles={"PlatformAdmin", "LabOwner"})
def list_billing_rules(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    from middleware import get_pagination
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    items = [r for r in db.billing_rules.values() if r["equipment_id"] == equipment_id]
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([db.public(x) for x in page], limit, offset, total)
