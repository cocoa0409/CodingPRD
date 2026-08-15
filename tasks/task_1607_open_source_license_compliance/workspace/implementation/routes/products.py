"""Product endpoints."""

from flask import Blueprint, request

from db import store, base_resource, touch
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_INVALID_DISTRIBUTION_MODEL,
    ERR_PRODUCT_BLOCKED, ERR_INVALID_REQUEST,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine

bp = Blueprint("products", __name__)

ANY_ROLE = ("ComplianceAnalyst", "LegalCounsel", "EngineeringManager",
            "SecurityAnalyst", "ReleaseManager", "CISO", "PlatformAdmin")

DISTRIBUTION_MODELS = {"SaaS", "ON_PREMISE", "EMBEDDED", "MOBILE_APP"}


def product_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


@bp.route("/oss-products", methods=["POST"])
def create_product():
    require_roles("ComplianceAnalyst")
    body = get_json_body()
    product_code = body.get("product_code")
    product_name = body.get("product_name")
    distribution_model = body.get("distribution_model")
    if not product_code or not isinstance(product_code, str):
        raise err(ERR_INVALID_REQUEST, "product_code is required")
    if not product_name or not isinstance(product_name, str):
        raise err(ERR_INVALID_REQUEST, "product_name is required")
    if distribution_model not in DISTRIBUTION_MODELS:
        raise err(ERR_INVALID_DISTRIBUTION_MODEL,
                  "distribution_model must be one of SaaS, ON_PREMISE, EMBEDDED, MOBILE_APP")

    p = base_resource()
    p.update({
        "product_code": product_code,
        "product_name": product_name,
        "distribution_model": distribution_model,
        "compliance_posture": "COMPLIANT",
        "posture_version": 1,
        "total_dependency_count": 0,
        "copyleft_dependency_count": 0,
        "restricted_dependency_count": 0,
        "high_severity_vulnerability_count": 0,
    })
    store.products[p["id"]] = p
    return success_obj(product_view(p), status=201)


@bp.route("/oss-products", methods=["GET"])
def list_products():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.products.values(), key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([product_view(p) for p in page], limit, offset, total)


@bp.route("/oss-products/<productId>", methods=["GET"])
def get_product(productId):
    get_auth()
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    return success_obj(product_view(p))


@bp.route("/oss-products/<productId>/unblock", methods=["POST"])
def unblock_product(productId):
    user_id, _ = require_roles("CISO")
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    body = get_json_body()
    if p["compliance_posture"] != "BLOCKED":
        raise err(ERR_PRODUCT_BLOCKED, "Product must be in BLOCKED state")

    # All PROHIBITED components must have approved RemediationPlans IN_PROGRESS or COMPLETED
    bom = engine.active_bom(p)
    if bom:
        entries = engine._attach_eff(engine.entries_of_bom(bom["id"]))
        prohibited_entries = [e for e in entries if e.get("_effective_classification") == "PROHIBITED"]
        for e in prohibited_entries:
            covered = False
            # Find findings on this entry and their plans
            findings = [f for f in store.findings.values() if f["bom_entry_id"] == e["id"]]
            plan_ok = False
            for plan in store.plans.values():
                if plan["product_id"] != p["id"]:
                    continue
                if plan.get("target_component_id") == e["component_id"] and plan["status"] in ("IN_PROGRESS", "COMPLETED"):
                    plan_ok = True
                    break
                # plan attached to a finding on this entry
                f = store.findings.get(plan.get("finding_id"))
                if f and f["bom_entry_id"] == e["id"] and plan["status"] in ("IN_PROGRESS", "COMPLETED"):
                    plan_ok = True
                    break
            # Also accept a plan whose finding is on the entry OR no findings exist (component-level coverage)
            if not plan_ok:
                # Look for any approved plan for this product covering the component
                for plan in store.plans.values():
                    if plan["product_id"] == p["id"] and plan["status"] in ("IN_PROGRESS", "COMPLETED"):
                        if plan.get("target_component_id") == e["component_id"]:
                            plan_ok = True
                            break
            if not plan_ok and prohibited_entries:
                raise err(ERR_PRODUCT_BLOCKED,
                          "All PROHIBITED components must have approved RemediationPlans in IN_PROGRESS or COMPLETED status")

    p["compliance_posture"] = "AT_RISK"
    p["posture_version"] = int(p.get("posture_version", 1)) + 1
    touch(p)
    return success_obj(product_view(p))
