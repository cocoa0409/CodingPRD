"""TechPack endpoints (PRD §3.1, §3.2) incl. review supersede/revoke cascades."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_MERCHANDISER, ROLE_PLANT_MANAGER
from response import success_object
from util import get_body, req_str, req_int, req_list, req_enum, fk_exists
from errors import (
    invalid_request, invalid_state, stale_version, no_operation_specs,
    tech_pack_not_pending_review, sod_self_review,
)
from services.core import (
    base_record, touch, public, get_tech_pack, get_style,
)
from services.calc import size_grading, recompute_domestic_content
from routes.common import list_response, active_filters

bp = Blueprint("tech_packs", __name__)

REVIEW_DECISIONS = {"APPROVE", "REJECT"}


def _validate_measurements(body):
    """base_measurements: [{point, base_value_in}]; grade_rules: [{point,
    per_step_increment_in}] (signed inches)."""
    from decimal import Decimal
    bms = req_list(body, "base_measurements")
    for i, m in enumerate(bms):
        if not isinstance(m, dict):
            raise invalid_request(f"base_measurements[{i}] must be an object")
        point = m.get("point")
        value = m.get("base_value_in")
        if not isinstance(point, str) or not point:
            raise invalid_request(f"base_measurements[{i}].point must be a string")
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise invalid_request(f"base_measurements[{i}].base_value_in must be a number")
        if not isinstance(value, Decimal):
            m["base_value_in"] = Decimal(str(value))
    grs = req_list(body, "grade_rules")
    for i, g in enumerate(grs):
        if not isinstance(g, dict):
            raise invalid_request(f"grade_rules[{i}] must be an object")
        point = g.get("point")
        inc = g.get("per_step_increment_in")
        if not isinstance(point, str) or not point:
            raise invalid_request(f"grade_rules[{i}].point must be a string")
        if isinstance(inc, bool) or not isinstance(inc, (int, float, Decimal)):
            raise invalid_request(
                f"grade_rules[{i}].per_step_increment_in must be a number")
        if not isinstance(inc, Decimal):
            g["per_step_increment_in"] = Decimal(str(inc))
    return bms, grs


@bp.route("/tech-packs", methods=["POST"])
def create_tech_pack():
    _, user_id = require_roles([ROLE_MERCHANDISER])
    body = get_body()
    fk_exists(body, "style_id", store.styles, "Style")
    style_id = req_str(body, "style_id")
    version_no = req_int(body, "version_no", min_v=1)
    base_measurements, grade_rules = _validate_measurements(body)
    labor = req_int(body, "labor_cost_cents_per_unit", min_v=0)
    fabric = req_int(body, "fabric_cost_cents_per_unit", min_v=0)
    # version_no unique per style among non-SUPERSEDED packs
    for p in store.tech_packs.values():
        if (p["style_id"] == style_id and p["version_no"] == version_no
                and p["status"] != "SUPERSEDED"):
            raise invalid_request(
                "version_no must be unique per style among non-SUPERSEDED packs")

    rec = base_record()
    rec.update({
        "style_id": style_id,
        "version_no": version_no,
        "base_measurements": base_measurements,
        "grade_rules": grade_rules,
        "labor_cost_cents_per_unit": labor,
        "fabric_cost_cents_per_unit": fabric,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "reviewed_by_user_id": None,
    })
    store.tech_packs[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/tech-packs", methods=["GET"])
def list_tech_packs():
    require_roles(ALL_ROLES)
    filters = active_filters([("style_id", request.args.get("style_id"))])
    return list_response(store.tech_packs.values(), filters)


@bp.route("/tech-packs/<pack_id>", methods=["GET"])
def get_tech_pack_endpoint(pack_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_tech_pack(pack_id)))


@bp.route("/tech-packs/<pack_id>/graded-measurements", methods=["GET"])
def graded_measurements(pack_id):
    require_roles(ALL_ROLES)
    pack = get_tech_pack(pack_id)
    style = get_style(pack["style_id"])
    return success_object(size_grading(style, pack))


@bp.route("/tech-packs/<pack_id>/submit", methods=["POST"])
def submit_tech_pack(pack_id):
    require_roles([ROLE_MERCHANDISER])
    get_body()
    pack = get_tech_pack(pack_id)
    if pack["status"] != "DRAFT":
        raise invalid_state("tech pack must be DRAFT to submit")
    has_ops = any(o["tech_pack_id"] == pack["id"]
                  for o in store.operation_specs.values())
    if not has_ops:
        raise no_operation_specs(
            "tech pack must have at least one OperationSpec to submit")
    points = {m["point"] for m in pack["base_measurements"]}
    if not pack["base_measurements"] or any(
            g["point"] not in points for g in pack["grade_rules"]):
        raise invalid_request(
            "base_measurements must be non-empty and every grade_rules.point "
            "must appear in base_measurements")
    pack["status"] = "PENDING_APPROVAL"
    touch(pack)
    return success_object(public(pack))


@bp.route("/tech-packs/<pack_id>/review", methods=["POST"])
def review_tech_pack(pack_id):
    _, user_id = require_roles([ROLE_PLANT_MANAGER])
    pack = get_tech_pack(pack_id)
    body = get_body()
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    expected = req_int(body, "expected_style_version")
    style = get_style(pack["style_id"])
    # OCC on Style.version — checked before state (PRD §2.7).
    if expected != style["version"]:
        raise stale_version(
            f"expected_style_version {expected} does not match current style "
            f"version {style['version']}")
    if pack["status"] != "PENDING_APPROVAL":
        raise tech_pack_not_pending_review(
            "tech pack must be PENDING_APPROVAL to review")
    if user_id == pack["created_by_user_id"]:
        raise sod_self_review("reviewer must differ from the pack's creator")

    pack["reviewed_by_user_id"] = user_id
    if decision == "REJECT":
        pack["status"] = "REJECTED"
        touch(pack)
        return success_object(public(pack))

    # APPROVE
    pack["status"] = "APPROVED"
    touch(pack)
    # Supersede any previously APPROVED sibling pack of the same style.
    for other in store.tech_packs.values():
        if (other["style_id"] == style["id"] and other["id"] != pack["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    # Re-point the style and recompute its domestic-content position.
    style["active_tech_pack_id"] = pack["id"]
    recompute_domestic_content(style)
    touch(style)
    # Certification loss cascade (PRD §3.2): a re-point that leaves the style
    # not QUALIFIED_STRICT revokes a live certification (+1 more version bump).
    if (style["certification_status"] == "CERTIFIED"
            and style["content_qualification"] != "QUALIFIED_STRICT"):
        style["certification_status"] = "REVOKED"
        style["certified_by_user_id"] = None
        touch(style)
    return success_object(public(pack))


@bp.route("/tech-packs/<pack_id>/revise", methods=["POST"])
def revise_tech_pack(pack_id):
    require_roles([ROLE_MERCHANDISER])
    get_body()
    pack = get_tech_pack(pack_id)
    if pack["status"] != "REJECTED":
        raise invalid_state("tech pack must be REJECTED to revise")
    pack["status"] = "DRAFT"
    touch(pack)
    return success_object(public(pack))
