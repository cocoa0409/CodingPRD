"""OperatingAgreement routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_pagination, sort_by_created
from services import access, core, serialize, validation

bp = Blueprint("operating_agreements", __name__)


def _validate_template_type_for_entity(template_type: str, entity_type: str) -> None:
    if template_type not in validation.TEMPLATE_TYPES:
        raise errors.err_template_type_mismatch("template_type not recognized.")
    if entity_type == "CORP":
        raise errors.err_template_type_mismatch("CORP entity does not support OperatingAgreement.")
    if entity_type == "LLC" and template_type not in ("MEMBER_MANAGED", "MANAGER_MANAGED"):
        raise errors.err_template_type_mismatch("LLC must use MEMBER_MANAGED or MANAGER_MANAGED.")
    if entity_type == "LP" and template_type != "LP_GENERAL_LIMITED":
        raise errors.err_template_type_mismatch("LP must use LP_GENERAL_LIMITED.")


@bp.route("/business-entities/<be_id>/operating-agreements", methods=["POST"])
def create_operating_agreement(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    body = parse_json_body_required()
    template_type = body.get("template_type")
    members_json = body.get("members_json")

    if template_type is None:
        raise errors.err_invalid_request("Missing required field: template_type.")
    if members_json is None:
        raise errors.err_invalid_request("Missing required field: members_json.")

    # Priority 55: members_json safety check (fires before template_type per
    # §1.4 priority numbers: 55 < 85)
    validation.validate_members_json(members_json)
    # Priority 85: template_type vs entity_type
    _validate_template_type_for_entity(template_type, be["entity_type"])

    oa = {
        "business_entity_id": be["id"],
        "template_type": template_type,
        "members_json": members_json,
        "status": "DRAFT",
        "executed_at": None,
    }
    core.stamp_create_common(oa)
    db.operating_agreements[oa["id"]] = oa
    return response.success_object(serialize.operating_agreement(oa), status=201)


@bp.route("/business-entities/<be_id>/operating-agreements", methods=["GET"])
def list_operating_agreements(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    items = core.children_operating_agreements(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.operating_agreement(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/operating-agreements/<oa_id>/execute", methods=["POST"])
def execute_operating_agreement(oa_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    oa = access.get_operating_agreement_or_404(oa_id)
    access.require_filer_owns(role, user_id, oa["business_entity_id"])
    be = db.business_entities.get(oa["business_entity_id"])

    # State precondition first per priority 40
    if oa["status"] != "DRAFT":
        raise errors.err_invalid_state(f"OperatingAgreement is in {oa['status']}, not DRAFT.")

    # ENTITY_DISSOLVED priority 45
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Per §1.2 precondition: BusinessEntity.compliance_posture != FROZEN
    if be is not None and be["compliance_posture"] == "FROZEN":
        raise errors.err_invalid_state("Cannot execute against a FROZEN business entity.")

    # Re-validate member list at execute (priority 55)
    validation.validate_members_json(oa["members_json"])

    # Side effect: if prior EXECUTED on same entity, supersede.
    for prior in core.children_operating_agreements(oa["business_entity_id"]):
        if prior["id"] == oa["id"]:
            continue
        if prior["status"] == "EXECUTED":
            prior["status"] = "SUPERSEDED"
            core.stamp_update_common(prior)

    oa["status"] = "EXECUTED"
    oa["executed_at"] = db.iso_format(db.now_utc())
    oa["_executed_at_dt"] = db.now_utc()
    core.stamp_update_common(oa)

    # Possible automatic BE FORMING -> ACTIVE
    if be is not None:
        core.cascade_after_child_change(be)

    return response.success_object(serialize.operating_agreement(oa))
