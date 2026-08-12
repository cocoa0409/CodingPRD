"""Consent banner configurations and OCC-guarded publication (PRD §3.2, §2.7)."""

from flask import Blueprint, request

from clock import get_now
from db import store, touch, now_iso
from errors import (
    ApiError,
    ERR_BANNER_CONFIG_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_PROPERTY_VERSION,
    ERR_BANNER_CONFIG_NOT_PUBLISHABLE,
    ERR_NO_ACTIVE_POLICY,
    ERR_POLICY_OUTSIDE_COVERAGE_WINDOW,
)
from middleware import require_role
from response import ok, ok_list, parse_pagination, paginate
from services.validation import (
    active_policies_for,
    check_frozen,
    get_json_body,
    new_entity,
    not_found,
    policy_window_contains,
    req_list,
    req_str,
    run_lazy_effects,
)

bp = Blueprint("banner_configs", __name__)

CATEGORIES_SHOWN_ENUM = ("ANALYTICS", "ADVERTISING", "SALE_SHARE")
PUBLISHABLE_FROM = ("DRAFT", "SUPPRESSED")


@bp.post("/v1/banner-configs")
def create_banner_config():
    require_role("PrivacyAdmin")
    body = get_json_body()
    property_id = req_str(body, "property_id")
    jurisdiction_code = req_str(body, "jurisdiction_code")
    categories_shown = req_list(body, "categories_shown", item_enum=CATEGORIES_SHOWN_ENUM)
    config_label = req_str(body, "config_label")
    if property_id not in store["properties"]:
        not_found("properties", ERR_PROPERTY_NOT_FOUND)
    # Rung 5: banner configuration creation is frozen-gated (PRD §2.6).
    run_lazy_effects()
    check_frozen(property_id)
    config = new_entity(
        {
            "property_id": property_id,
            "jurisdiction_code": jurisdiction_code,
            "categories_shown": categories_shown,
            "config_label": config_label,
            "status": "DRAFT",
            "published_at": None,
        }
    )
    store["banner_configs"][config["id"]] = config
    return ok(config, 201)


@bp.get("/v1/banner-configs")
def list_banner_configs():
    require_role("Any")
    limit, offset = parse_pagination(request.args)
    items = list(store["banner_configs"].values())
    property_id = request.args.get("property_id")
    jurisdiction_code = request.args.get("jurisdiction_code")
    status = request.args.get("status")
    if property_id is not None:
        items = [c for c in items if c.get("property_id") == property_id]
    if jurisdiction_code is not None:
        items = [c for c in items if c.get("jurisdiction_code") == jurisdiction_code]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/banner-configs/<id>")
def get_banner_config(id):
    require_role("Any")
    config = store["banner_configs"].get(id)
    if config is None:
        not_found("banner_configs", ERR_BANNER_CONFIG_NOT_FOUND)
    return ok(config)


@bp.post("/v1/banner-configs/<id>/publish")
def publish_banner_config(id):
    require_role("PrivacyAdmin")
    # Rung 3: existence.
    config = store["banner_configs"].get(id)
    if config is None:
        not_found("banner_configs", ERR_BANNER_CONFIG_NOT_FOUND)
    body = get_json_body()
    expected = body.get("expected_property_version")
    if (
        expected is None
        or not isinstance(expected, int)
        or isinstance(expected, bool)
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'expected_property_version' is required and must be an integer",
            400,
        )
    run_lazy_effects()
    prop = store["properties"].get(config["property_id"])
    if prop is None:
        not_found("properties", ERR_PROPERTY_NOT_FOUND)

    # Rung 4: optimistic concurrency — before every state/business rule (§2.7).
    if expected != prop["version"]:
        raise ApiError(
            ERR_STALE_PROPERTY_VERSION,
            f"expected_property_version {expected} is stale; property version is {prop['version']}",
            412,
        )
    # Rung 5: posture gate.
    check_frozen(prop["id"])
    # Rung 6: publishable only from DRAFT or SUPPRESSED.
    if config["status"] not in PUBLISHABLE_FROM:
        raise ApiError(
            ERR_BANNER_CONFIG_NOT_PUBLISHABLE,
            f"Configuration in status {config['status']} cannot be published",
            409,
        )
    # Rung 9: an ACTIVE policy must exist for the config's jurisdiction.
    policies = active_policies_for(config["property_id"], config["jurisdiction_code"])
    if not policies:
        raise ApiError(
            ERR_NO_ACTIVE_POLICY,
            "No ACTIVE jurisdiction policy for the configuration's jurisdiction_code",
            409,
        )
    # Rung 11: the logical clock must fall inside the policy's coverage window.
    now = get_now()
    if not any(policy_window_contains(p, now) for p in policies):
        raise ApiError(
            ERR_POLICY_OUTSIDE_COVERAGE_WINDOW,
            "Current clock is outside the ACTIVE policy's coverage window",
            409,
        )

    # Supersede the currently PUBLISHED config of the same (property,
    # jurisdiction); its ENABLED tag rules drop to DISABLED.
    for other in list(store["banner_configs"].values()):
        if (
            other["id"] != config["id"]
            and other.get("property_id") == config["property_id"]
            and other.get("jurisdiction_code") == config["jurisdiction_code"]
            and other.get("status") == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
            for rule in list(store["tag_rules"].values()):
                if rule.get("banner_config_id") == other["id"] and rule.get("status") == "ENABLED":
                    rule["status"] = "DISABLED"
                    touch(rule)

    config["status"] = "PUBLISHED"
    config["published_at"] = now_iso()
    touch(config)
    # Publication is the property's commit point: version += 1 (exactly one).
    touch(prop)
    return ok(config)


@bp.post("/v1/banner-configs/<id>/archive")
def archive_banner_config(id):
    require_role("PrivacyAdmin")
    config = store["banner_configs"].get(id)
    if config is None:
        not_found("banner_configs", ERR_BANNER_CONFIG_NOT_FOUND)
    # Rung 5: archival is frozen-gated (PRD §2.6).
    run_lazy_effects()
    check_frozen(config["property_id"])
    # Rung 6: archival applies only to DRAFT configurations.
    if config["status"] != "DRAFT":
        raise ApiError(
            ERR_BANNER_CONFIG_NOT_PUBLISHABLE,
            f"Configuration in status {config['status']} cannot be archived",
            409,
        )
    config["status"] = "ARCHIVED"
    touch(config)
    return ok(config)
