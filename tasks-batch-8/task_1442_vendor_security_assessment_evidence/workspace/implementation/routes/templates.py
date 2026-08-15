"""QuestionnaireTemplate lifecycle: DRAFT -> PUBLISHED -> RETIRED, plus the
PUBLISHED -> (new DRAFT) revision loop (PRD §3.2).
"""
import copy

from flask import Blueprint, request

import db
import errors
import helpers
from errors import ApiError
from middleware import body, paginate, require_roles
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("templates", __name__, url_prefix="/vsa/questionnaire-templates")

TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")


def _validate_items(items):
    if not isinstance(items, list):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "items must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "each item must be an object")
        for field in ("item_key", "prompt", "weight", "control_domain"):
            if field not in item:
                raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                               "item is missing %s" % field)
        if not isinstance(item["item_key"], str) or not item["item_key"]:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "item_key must be a non-empty string")
        if (not isinstance(item["weight"], (int, float))
                or isinstance(item["weight"], bool)):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "item weight must be a number")


@bp.post("")
@require_roles("RiskAnalyst")
def create_template():
    data = body()
    title = data.get("title")
    applies = data.get("applies_to_tiers")
    items = data.get("items")
    if not isinstance(title, str) or not title:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "title is required")
    if (not isinstance(applies, list) or not applies
            or any(t not in TIERS for t in applies)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "applies_to_tiers must be a list of TIER_1..TIER_4")
    if items is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "items is required")
    _validate_items(items)
    template = {
        "title": title,
        "applies_to_tiers": list(applies),
        "items": copy.deepcopy(items),
        "status": "DRAFT",
        "published_version": 0,
    }
    helpers.stamp_new("templates", template)
    db.templates[template["id"]] = template
    return ok(serialize("template", template), 201)


@bp.get("")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin")
def list_templates():
    items = list(db.templates.values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("template", t) for t in page], limit, offset, total)


@bp.get("/<tid>")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin")
def get_template(tid):
    return ok(serialize("template", helpers.get_template(tid)))


@bp.post("/<tid>/publish")
@require_roles("RiskAnalyst")
def publish_template(tid):
    template = helpers.get_template(tid)
    if template["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a DRAFT template can be published")
    items = template.get("items", [])
    if not items or any(util_weight(i) <= 0 for i in items):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "Publication requires a non-empty item list with positive weights")
    wanted = sorted(set(template["applies_to_tiers"]))
    for other in db.templates.values():
        if (other["id"] != template["id"] and other["status"] == "PUBLISHED"
                and sorted(set(other["applies_to_tiers"])) == wanted):
            raise ApiError(errors.ERR_UNIQUENESS_VIOLATION, 409,
                           "Another PUBLISHED template already covers this tier set")
    template["status"] = "PUBLISHED"
    template["published_version"] += 1
    helpers.touch("templates", template)
    return ok(serialize("template", template))


def util_weight(item):
    try:
        return float(item.get("weight", 0))
    except (TypeError, ValueError):
        return 0.0


@bp.post("/<tid>/retire")
@require_roles("RiskAnalyst")
def retire_template(tid):
    template = helpers.get_template(tid)
    if template["status"] != "PUBLISHED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a PUBLISHED template can be retired")
    for cycle in db.cycles.values():
        if (cycle.get("template_id") == tid
                and cycle["status"] in helpers.NON_TERMINAL_CYCLE):
            raise ApiError(errors.ERR_TEMPLATE_IN_USE, 409,
                           "Non-terminal assessment cycles still reference this template")
    template["status"] = "RETIRED"
    helpers.touch("templates", template)
    return ok(serialize("template", template))


@bp.post("/<tid>/revise")
@require_roles("RiskAnalyst")
def revise_template(tid):
    template = helpers.get_template(tid)
    if template["status"] != "PUBLISHED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a PUBLISHED template can be revised")
    draft = {
        "title": template["title"],
        "applies_to_tiers": list(template["applies_to_tiers"]),
        "items": copy.deepcopy(template["items"]),
        "status": "DRAFT",
        # Revision cycle: inherits the parent's published_version unchanged.
        "published_version": template["published_version"],
    }
    helpers.stamp_new("templates", draft)
    db.templates[draft["id"]] = draft
    helpers.touch("templates", template)
    return ok(serialize("template", draft), 201)


@bp.get("/<tid>/cycles")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin")
def template_cycles(tid):
    helpers.get_template(tid)
    items = [c for c in db.cycles.values() if c.get("template_id") == tid]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("cycle", c) for c in page], limit, offset, total)
