"""Tag rules: vendor x purpose wiring under a banner configuration (PRD §3.3)."""

from flask import Blueprint, request

from db import store, touch
from errors import (
    ApiError,
    ERR_TAG_RULE_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_BANNER_CONFIG_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TAG_RULE_INVALID_TRANSITION,
    ERR_VENDOR_NOT_APPROVED,
    ERR_CROSS_PROPERTY_REFERENCE,
    ERR_DUPLICATE_TAG_RULE,
)
from middleware import require_role
from response import ok, ok_list, parse_pagination, paginate
from services.validation import (
    check_frozen,
    get_json_body,
    new_entity,
    not_found,
    req_enum,
    req_str,
    run_lazy_effects,
)

bp = Blueprint("tag_rules", __name__)

PURPOSE_CATEGORIES = ("ANALYTICS", "ADVERTISING", "SALE_SHARE")
TAG_RULE_STATUSES = ("ENABLED", "DISABLED", "RETIRED")


@bp.post("/v1/tag-rules")
def create_tag_rule():
    require_role("VendorManager")
    body = get_json_body()
    vendor_id = req_str(body, "vendor_id")
    banner_config_id = req_str(body, "banner_config_id")
    purpose_category = req_enum(body, "purpose_category", PURPOSE_CATEGORIES)
    # Rung 3: body-referenced existence, in input order (vendor, then config).
    vendor = store["vendors"].get(vendor_id)
    if vendor is None:
        not_found("vendors", ERR_VENDOR_NOT_FOUND)
    config = store["banner_configs"].get(banner_config_id)
    if config is None:
        not_found("banner_configs", ERR_BANNER_CONFIG_NOT_FOUND)
    # Rung 5: tag rule creation is frozen-gated.
    run_lazy_effects()
    check_frozen(config["property_id"])
    # Rung 10: vendor and banner configuration must live on the same property.
    if vendor.get("property_id") != config.get("property_id"):
        raise ApiError(
            ERR_CROSS_PROPERTY_REFERENCE,
            "Tag rule vendor and banner configuration belong to different properties",
            409,
        )
    # Rung 10.5: the vendor must be APPROVED.
    if vendor.get("status") != "APPROVED":
        raise ApiError(
            ERR_VENDOR_NOT_APPROVED,
            "Tag rule creation requires the vendor in APPROVED status",
            409,
        )
    # Rung 14: unique per (banner_config_id, purpose_category).
    for rule in store["tag_rules"].values():
        if (
            rule.get("banner_config_id") == banner_config_id
            and rule.get("purpose_category") == purpose_category
        ):
            raise ApiError(
                ERR_DUPLICATE_TAG_RULE,
                "A tag rule already exists for this banner configuration and purpose category",
                409,
            )
    rule = new_entity(
        {
            "property_id": config["property_id"],
            "vendor_id": vendor_id,
            "banner_config_id": banner_config_id,
            "purpose_category": purpose_category,
            "status": "ENABLED",
        }
    )
    store["tag_rules"][rule["id"]] = rule
    return ok(rule, 201)


@bp.get("/v1/tag-rules")
def list_tag_rules():
    require_role("Any")
    limit, offset = parse_pagination(request.args)
    items = list(store["tag_rules"].values())
    property_id = request.args.get("property_id")
    vendor_id = request.args.get("vendor_id")
    banner_config_id = request.args.get("banner_config_id")
    status = request.args.get("status")
    if property_id is not None:
        items = [r for r in items if r.get("property_id") == property_id]
    if vendor_id is not None:
        items = [r for r in items if r.get("vendor_id") == vendor_id]
    if banner_config_id is not None:
        items = [r for r in items if r.get("banner_config_id") == banner_config_id]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/tag-rules/<id>")
def get_tag_rule(id):
    require_role("Any")
    rule = store["tag_rules"].get(id)
    if rule is None:
        not_found("tag_rules", ERR_TAG_RULE_NOT_FOUND)
    return ok(rule)


@bp.put("/v1/tag-rules/<id>")
def update_tag_rule(id):
    require_role("VendorManager")
    rule = store["tag_rules"].get(id)
    if rule is None:
        not_found("tag_rules", ERR_TAG_RULE_NOT_FOUND)
    body = get_json_body()
    target = req_enum(body, "status", TAG_RULE_STATUSES)
    # Rung 5: the frozen gate applies to every manual tag-rule transition.
    run_lazy_effects()
    check_frozen(rule["property_id"])
    # Rung 6: transition preconditions. ENABLED <-> DISABLED is a genuine
    # cycle; RETIRED is reachable from either and is terminal.
    current = rule["status"]
    allowed = (
        (current == "ENABLED" and target == "DISABLED")
        or (current == "DISABLED" and target == "ENABLED")
        or (current in ("ENABLED", "DISABLED") and target == "RETIRED")
    )
    if not allowed:
        raise ApiError(
            ERR_TAG_RULE_INVALID_TRANSITION,
            f"Tag rule transition {current} -> {target} is not allowed",
            409,
        )
    # Rung 10.5: re-enabling re-checks the vendor's standing.
    if target == "ENABLED":
        vendor = store["vendors"].get(rule["vendor_id"])
        if vendor is None:
            not_found("vendors", ERR_VENDOR_NOT_FOUND)
        if vendor.get("status") != "APPROVED":
            raise ApiError(
                ERR_VENDOR_NOT_APPROVED,
                "Re-enabling a tag rule requires the vendor in APPROVED status",
                409,
            )
    rule["status"] = target
    touch(rule)
    return ok(rule)
