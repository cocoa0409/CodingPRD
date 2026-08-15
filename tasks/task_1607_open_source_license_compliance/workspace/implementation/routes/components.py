"""Component catalogue endpoints."""

from flask import Blueprint, request

from db import store, base_resource, touch
from errors import err, ERR_COMPONENT_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine
from services.policy import VALID_CLASSIFICATIONS, effective_classification, determine_obligation

bp = Blueprint("components", __name__)


def component_view(c):
    d = {k: v for k, v in c.items() if not k.startswith("_")}
    d["effective_classification"] = effective_classification(c)
    return d


@bp.route("/oss-components", methods=["POST"])
def create_component():
    require_roles("ComplianceAnalyst")
    body = get_json_body()
    package_url = body.get("package_url")
    component_name = body.get("component_name")
    version = body.get("version")
    declared = body.get("declared_license_spdx")
    if not package_url or not isinstance(package_url, str):
        raise err(ERR_INVALID_REQUEST, "package_url is required")
    if not component_name or not isinstance(component_name, str):
        raise err(ERR_INVALID_REQUEST, "component_name is required")
    if version is None:
        raise err(ERR_INVALID_REQUEST, "version is required")
    if declared is None:
        raise err(ERR_INVALID_REQUEST, "declared_license_spdx is required")

    c = base_resource()
    c.update({
        "package_url": package_url,
        "component_name": component_name,
        "version": version,
        "_rev": 1,  # system revision counter (Component's `version` is the package version)
        "declared_license_spdx": declared,
        "discovered_license_spdx": None,
        "license_policy_classification": None,
        "policy_override_classification": None,
        "source_download_url": body.get("source_download_url"),
        "copyright_notice": body.get("copyright_notice"),
    })
    store.components[c["id"]] = c
    return success_obj(component_view(c), status=201)


@bp.route("/oss-components", methods=["GET"])
def list_components():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.components.values(), key=lambda x: (x["created_at"], x["id"]))
    purl = request.args.get("package_url")
    if purl is not None:
        items = [c for c in items if c["package_url"] == purl]
    eff = request.args.get("effective_classification")
    if eff is not None:
        items = [c for c in items if effective_classification(c) == eff]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([component_view(c) for c in page], limit, offset, total)


@bp.route("/oss-components/<componentId>", methods=["GET"])
def get_component(componentId):
    get_auth()
    c = store.components.get(componentId)
    if not c:
        raise err(ERR_COMPONENT_NOT_FOUND, "Component not found")
    return success_obj(component_view(c))


@bp.route("/oss-components/<componentId>/override-classification", methods=["POST"])
def override_classification(componentId):
    user_id, _ = require_roles("LegalCounsel")
    c = store.components.get(componentId)
    if not c:
        raise err(ERR_COMPONENT_NOT_FOUND, "Component not found")
    body = get_json_body()
    override = body.get("policy_override_classification")
    if override not in VALID_CLASSIFICATIONS:
        raise err(ERR_INVALID_REQUEST,
                  "policy_override_classification must be one of PERMISSIVE, WEAK_COPYLEFT, STRONG_COPYLEFT, RESTRICTED, PROHIBITED")
    rationale = body.get("rationale")
    c["policy_override_classification"] = override
    c["override_rationale"] = rationale
    touch(c)

    # Cross-aggregate cascade: recompute every BomEntry referencing this component,
    # then affected BOM postures, then product counts/posture.
    affected_boms = set()
    affected_products = set()
    for e in store.bom_entries.values():
        if e["component_id"] != c["id"]:
            continue
        bom = store.boms.get(e["bom_id"])
        if not bom:
            continue
        product = store.products.get(bom["product_id"])
        lic = c.get("discovered_license_spdx") or c.get("declared_license_spdx")
        e["obligation_determination"] = determine_obligation(
            effective_classification(c),
            product.get("distribution_model") if product else None,
            e["dependency_scope"],
            lic,
        )
        touch(e)
        affected_boms.add(bom["id"])
        affected_products.add(bom["product_id"])

    for bid in affected_boms:
        bom = store.boms.get(bid)
        if bom:
            engine.recompute_bom_derived(bom)
    for pid in affected_products:
        product = store.products.get(pid)
        if product:
            engine.recompute_product_counts(product)
            engine.reevaluate_product_posture(product)

    return success_obj(component_view(c))
