"""ExclusionRule endpoints (PRD §3.5). Immutable: id + created_at only."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_str,
    require_json_object,
    serialize,
    sort_by_created,
)

bp = Blueprint("exclusion_rules", __name__)


@bp.post("/exclusion-rules")
@require_roles("MerchantAdmin")
def create_exclusion_rule():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        a = require_str(body, "promotion_a_id")
        b = require_str(body, "promotion_b_id")
        # FK existence (priority 4).
        if a not in db.promotions:
            raise err("ERR_FK_NOT_FOUND", "promotion_a_id does not reference a promotion")
        if b not in db.promotions:
            raise err("ERR_FK_NOT_FOUND", "promotion_b_id does not reference a promotion")
        note = body.get("note")
        rec = new_record(
            {
                "promotion_a_id": a,
                "promotion_b_id": b,
                "note": note,
            },
            common=False,
        )
        db.exclusion_rules[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/exclusion-rules/<exclusion_rule_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_exclusion_rule(exclusion_rule_id):
    with db.lock:
        r = db.exclusion_rules.get(exclusion_rule_id)
        if not r:
            raise err("ERR_NOT_FOUND", "Exclusion rule not found")
        return success(serialize(r), 200)


@bp.get("/exclusion-rules")
@require_roles("MerchantAdmin", "Shopper")
def list_exclusion_rules():
    with db.lock:
        limit, offset = paginate(request.args)
        a = request.args.get("promotion_a_id")
        b = request.args.get("promotion_b_id")
        items = list(db.exclusion_rules.values())
        # Filter by each endpoint field literally (§2.10: "using the same field
        # names that define those relationships").
        if a is not None:
            items = [r for r in items if r["promotion_a_id"] == a]
        if b is not None:
            items = [r for r in items if r["promotion_b_id"] == b]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(r) for r in page], limit, offset, total)
