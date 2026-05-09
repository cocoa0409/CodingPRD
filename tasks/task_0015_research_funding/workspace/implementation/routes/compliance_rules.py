"""ComplianceRule endpoints."""

from flask import Blueprint

from common import get_json_body, paginate_list, parse_pagination
from middleware import require_roles
from response import paginated, success
from services.compliance_rule import (
    create_rule,
    get_rule_or_404,
    list_rules,
    patch_rule,
    serialize_rule,
)


bp = Blueprint("compliance_rules", __name__)


@bp.route("/compliance-rules", methods=["POST"])
@require_roles("ResearchAdmin")
def post_rule():
    body = get_json_body()
    r = create_rule(body)
    return success(serialize_rule(r), 201)


@bp.route("/compliance-rules", methods=["GET"])
@require_roles("Any")
def get_rules():
    limit, offset = parse_pagination()
    items = list_rules()
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_rule(r) for r in page], limit, offset, total)


@bp.route("/compliance-rules/<rule_id>", methods=["PATCH"])
@require_roles("ResearchAdmin")
def patch_rule_route(rule_id):
    get_rule_or_404(rule_id)
    body = get_json_body()
    r = patch_rule(rule_id, body)
    return success(serialize_rule(r), 200)
