"""Substitution rules: POST /substitution-rules, GET /substitution-rules."""
from flask import Blueprint, request

from common import new_common_appendonly
from middleware import auth_required
import db
from response import created, list_ok
from pagination import parse_pagination, apply_page
from services import validators as v
from services.views import substitution_rule_view

bp = Blueprint("substitution_rules", __name__)


@bp.route("/substitution-rules", methods=["POST"])
@auth_required("PlatformAdmin")
def create_substitution_rule():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    from_variety = v.require_str(body, "from_variety")
    to_variety = v.require_str(body, "to_variety")
    allowed = v.optional_bool(body, "allowed", default=True)
    max_sub_pct = v.optional_number(body, "max_substitution_pct", default=0.5,
                                    min_value=0, max_value=1)
    quality_floor_grade = v.optional_enum(body, "quality_floor_grade",
                                          v.GRADE_ENUM, default="B")

    r = {
        **new_common_appendonly(),
        "from_variety": from_variety,
        "to_variety": to_variety,
        "allowed": allowed,
        "max_substitution_pct": max_sub_pct,
        "quality_floor_grade": quality_floor_grade,
    }
    db.substitution_rules[r["id"]] = r
    return created(substitution_rule_view(r))


@bp.route("/substitution-rules", methods=["GET"])
@auth_required("PlatformAdmin", "FulfillmentOps")
def list_substitution_rules():
    limit, offset = parse_pagination()
    from_variety = request.args.get("from_variety")

    items = list(db.substitution_rules.values())
    if from_variety is not None:
        items = [r for r in items if r["from_variety"] == from_variety]
    items.sort(key=lambda r: r["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([substitution_rule_view(r) for r in page], limit, offset, total)
