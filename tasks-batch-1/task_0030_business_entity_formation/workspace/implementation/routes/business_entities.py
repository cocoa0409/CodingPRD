"""BusinessEntity routes."""
from __future__ import annotations

from flask import Blueprint

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_optional, parse_pagination, sort_by_created
from services import access, core, serialize, validation
from flask import request

bp = Blueprint("business_entities", __name__)


@bp.route("/business-entities", methods=["POST"])
def create_business_entity():
    role, user_id = middleware.require_auth_optional_anonymous(["Anonymous", "Filer"])
    body = parse_json_body_optional()

    legal_name = body.get("legal_name")
    entity_type = body.get("entity_type")
    formation_state_code = body.get("formation_state_code")
    revenue_band = body.get("revenue_band", "ZERO")

    if legal_name is None:
        raise errors.err_invalid_request("Missing required field: legal_name.")
    if entity_type is None:
        raise errors.err_invalid_request("Missing required field: entity_type.")
    if formation_state_code is None:
        raise errors.err_invalid_request("Missing required field: formation_state_code.")

    validation.validate_legal_name(legal_name)
    validation.validate_entity_type(entity_type)
    validation.validate_state_code(formation_state_code, "formation_state_code")
    validation.validate_revenue_band(revenue_band)
    validation.validate_legal_name_unique(legal_name, formation_state_code)

    be = {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "formation_state_code": formation_state_code,
        "revenue_band": revenue_band,
        "status": "FORMING",
        "compliance_posture": "GOOD_STANDING",
        "franchise_tax_paid_through_year": 0,
        "cumulative_franchise_tax_paid_cents": 0,
    }
    core.stamp_create_common(be)
    be["formed_at"] = be["created_at"]
    be["_formed_at_dt"] = be["_created_at_dt"]
    db.business_entities[be["id"]] = be

    return response.success_object(serialize.business_entity(be), status=201)


@bp.route("/business-entities/<be_id>", methods=["GET"])
def get_business_entity(be_id: str):
    middleware.require_auth_optional_anonymous(["Anonymous", "Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)
    return response.success_object(serialize.business_entity(be))


@bp.route("/business-entities", methods=["GET"])
def list_business_entities():
    middleware.require_auth_optional_anonymous(["Anonymous", "Filer", "StateAdmin", "ComplianceOfficer"])
    limit, offset = parse_pagination()
    fsc = request.args.get("formation_state_code")
    et = request.args.get("entity_type")
    st = request.args.get("status")

    items = list(db.business_entities.values())
    if fsc is not None:
        items = [x for x in items if x["formation_state_code"] == fsc]
    if et is not None:
        items = [x for x in items if x["entity_type"] == et]
    if st is not None:
        items = [x for x in items if x["status"] == st]

    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.business_entity(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/business-entities/<be_id>/dissolve", methods=["PATCH"])
def dissolve_business_entity(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    # State precondition: status in {ACTIVE, DELINQUENT}
    if be["status"] not in ("ACTIVE", "DELINQUENT"):
        raise errors.err_invalid_state(f"Cannot dissolve entity in status {be['status']}.")

    # Cross-entity gate: no ForeignQualification with status=QUALIFIED
    for fq in core.children_foreign_qualifications(be["id"]):
        if fq["status"] == "QUALIFIED":
            raise errors.err_invalid_state("Outstanding QUALIFIED foreign qualifications block dissolution.")

    # Transition
    old = be["status"]
    be["status"] = "DISSOLVED"
    core.stamp_update_common(be)

    # Cascade: All AnnualReports in DRAFT or DELINQUENT flip to VOIDED.
    for ar in core.children_annual_reports(be["id"]):
        if ar["status"] in ("DRAFT", "DELINQUENT"):
            ar["status"] = "VOIDED"
            ar["voided_at"] = db.iso_format(db.now_utc())
            ar["_voided_at_dt"] = db.now_utc()
            core.stamp_update_common(ar)
    # All RegisteredAgents in ACTIVE flip to RESIGNED.
    for ra in core.children_registered_agents(be["id"]):
        if ra["status"] == "ACTIVE":
            ra["status"] = "RESIGNED"
            ra["resigned_at"] = db.iso_format(db.now_utc())
            ra["_resigned_at_dt"] = db.now_utc()
            core.stamp_update_common(ra)

    be["compliance_posture"] = "FROZEN"
    core.recompute_be_fiscal_fields(be)
    core.emit_event(be["id"], "STATUS_CHANGED", {"from": old, "to": "DISSOLVED"})

    return response.success_object(serialize.business_entity(be))


@bp.route("/business-entities/<be_id>/reinstate", methods=["POST"])
def reinstate_business_entity(be_id: str):
    role, user_id = middleware.require_auth(["StateAdmin"])
    be = access.get_business_entity_or_404(be_id)

    # State precondition: SUSPENDED
    if be["status"] != "SUSPENDED":
        raise errors.err_invalid_state(f"Cannot reinstate entity in status {be['status']}.")

    # All delinquent AnnualReports for period_year < clock_year must be in {FILED, VOIDED}.
    clock_year = db.now_utc().year
    for ar in core.children_annual_reports(be["id"]):
        if ar["period_year"] < clock_year and ar["status"] not in ("FILED", "VOIDED"):
            raise errors.err_invalid_state("Outstanding delinquent reports block reinstatement.")

    # Exactly one RegisteredAgent in ACTIVE.
    if core.active_registered_agent_count(be["id"]) != 1:
        raise errors.err_invalid_state("Reinstatement requires exactly one ACTIVE RegisteredAgent.")

    old = be["status"]
    be["status"] = "ACTIVE"
    core.stamp_update_common(be)
    be["compliance_posture"] = core.compute_compliance_posture(be["id"])
    core.emit_event(be["id"], "REINSTATED", {"from": old, "to": "ACTIVE"})
    return response.success_object(serialize.business_entity(be))
