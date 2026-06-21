"""ForeignQualification routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_pagination, sort_by_created
from services import access, core, serialize, validation

bp = Blueprint("foreign_qualifications", __name__)


def _check_agent_mismatch(agent: dict, foreign_state_code: str) -> None:
    """Raise ERR_FQ_AGENT_MISMATCH if agent isn't ACTIVE or state code differs."""
    if agent["status"] != "ACTIVE":
        raise errors.err_fq_agent_mismatch("Foreign agent is not ACTIVE.")
    if agent["agent_state_code"] != foreign_state_code:
        raise errors.err_fq_agent_mismatch("Foreign agent state code != foreign_state_code.")


def _has_active_qualified_overlap(be_id: str, foreign_state_code: str, now_utc) -> bool:
    """Return True if another QUALIFIED FQ for same (be_id, foreign_state_code)
    has [qualified_at, withdrawn_at) covering current clock UTC.
    """
    for fq in core.children_foreign_qualifications(be_id):
        if fq["status"] != "QUALIFIED":
            continue
        if fq["foreign_state_code"] != foreign_state_code:
            continue
        qa = fq.get("_qualified_at_dt")
        wa = fq.get("_withdrawn_at_dt")
        if qa is None:
            continue
        # half-open [qualified_at, withdrawn_at): covers now if qa <= now and (wa is None or now < wa)
        if qa <= now_utc and (wa is None or now_utc < wa):
            return True
    return False


@bp.route("/business-entities/<be_id>/foreign-qualifications", methods=["POST"])
def create_foreign_qualification(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    body = parse_json_body_required()
    foreign_state_code = body.get("foreign_state_code")
    foreign_registered_agent_id = body.get("foreign_registered_agent_id")
    if foreign_state_code is None:
        raise errors.err_invalid_request("Missing required field: foreign_state_code.")
    if foreign_registered_agent_id is None:
        raise errors.err_invalid_request("Missing required field: foreign_registered_agent_id.")

    validation.validate_state_code(foreign_state_code, "foreign_state_code")

    # PRD §2.10 priority: ERR_NOT_FOUND (FK resolution) is P3, BEFORE
    # ERR_ENTITY_DISSOLVED (P5). PRD §2.5: "Foreign-key fields in request
    # payloads ... an unresolvable reference returns `ERR_NOT_FOUND`, not a
    # downstream validation error." So FK resolution happens before the
    # dissolved-parent gate.
    agent = db.registered_agents.get(foreign_registered_agent_id)
    if agent is None:
        raise errors.err_not_found("foreign_registered_agent_id not found.")

    # Priority 5: dissolved-parent gate (after FK resolution).
    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Priority 60: ERR_FQ_AGENT_MISMATCH (PRD §3.10 — both ACTIVE and
    # agent_state_code constraints are checked at create time).
    _check_agent_mismatch(agent, foreign_state_code)

    # PRD §3.10: overlap check is an APPROVAL-time gate only — "Approval
    # imposes several additional gates beyond the create-time checks ...
    # no other QUALIFIED ForeignQualification ... may exist (overlap is
    # rejected with ERR_FQ_OVERLAP)". So overlap is NOT checked at create.

    # Priority 80: foreign_state_code != formation_state_code
    if foreign_state_code == be["formation_state_code"]:
        raise errors.err_fq_same_state()

    fq = {
        "business_entity_id": be["id"],
        "foreign_state_code": foreign_state_code,
        "foreign_registered_agent_id": foreign_registered_agent_id,
        "status": "PENDING",
        "qualified_at": None,
        "withdrawn_at": None,
    }
    core.stamp_create_common(fq)
    db.foreign_qualifications[fq["id"]] = fq
    return response.success_object(serialize.foreign_qualification(fq), status=201)


@bp.route("/foreign-qualifications/<fq_id>/approve", methods=["POST"])
def approve_foreign_qualification(fq_id: str):
    role, user_id = middleware.require_auth(["StateAdmin"])
    fq = access.get_foreign_qualification_or_404(fq_id)
    be = db.business_entities.get(fq["business_entity_id"])

    # Priority 40
    if fq["status"] != "PENDING":
        raise errors.err_invalid_state(f"FQ is in {fq['status']}; cannot approve.")

    # Priority 45
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Re-verify agent (priority 60)
    agent = db.registered_agents.get(fq["foreign_registered_agent_id"])
    if agent is None:
        raise errors.err_fq_agent_mismatch("Foreign agent no longer exists.")
    _check_agent_mismatch(agent, fq["foreign_state_code"])

    # Priority 72: overlap (exclude self)
    now = db.now_utc()
    for other in core.children_foreign_qualifications(be["id"]):
        if other["id"] == fq["id"]:
            continue
        if other["status"] != "QUALIFIED":
            continue
        if other["foreign_state_code"] != fq["foreign_state_code"]:
            continue
        qa = other.get("_qualified_at_dt")
        wa = other.get("_withdrawn_at_dt")
        if qa is None:
            continue
        if qa <= now and (wa is None or now < wa):
            raise errors.err_fq_overlap()

    # Priority 95: ALL prior AnnualReports for period_year < clock_year MUST be in {FILED, VOIDED}.
    clock_year = now.year
    for ar in core.children_annual_reports(be["id"]):
        if ar["period_year"] < clock_year and ar["status"] not in ("FILED", "VOIDED"):
            raise errors.err_franchise_tax_in_arrears()

    # Compliance posture gate: must be GOOD_STANDING.
    # This check is part of state legality; per scaffold §1.2 precondition.
    # Per PRD §3.10: "the parent's compliance_posture must be GOOD_STANDING ..."
    # When posture is FROZEN/RESTRICTED — that's ERR_INVALID_STATE.
    if be["compliance_posture"] != "GOOD_STANDING":
        raise errors.err_invalid_state("BusinessEntity is not in GOOD_STANDING posture.")

    fq["status"] = "QUALIFIED"
    fq["qualified_at"] = db.iso_format(now)
    fq["_qualified_at_dt"] = now
    core.stamp_update_common(fq)

    core.emit_event(be["id"], "FQ_QUALIFIED", {"foreign_qualification_id": fq["id"],
                                              "foreign_state_code": fq["foreign_state_code"]})
    return response.success_object(serialize.foreign_qualification(fq))


@bp.route("/foreign-qualifications/<fq_id>/withdraw", methods=["POST"])
def withdraw_foreign_qualification(fq_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    fq = access.get_foreign_qualification_or_404(fq_id)
    access.require_filer_owns(role, user_id, fq["business_entity_id"])
    be = db.business_entities.get(fq["business_entity_id"])

    if fq["status"] != "QUALIFIED":
        raise errors.err_invalid_state(f"FQ is in {fq['status']}; cannot withdraw.")
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    now = db.now_utc()
    fq["status"] = "WITHDRAWN"
    fq["withdrawn_at"] = db.iso_format(now)
    fq["_withdrawn_at_dt"] = now
    core.stamp_update_common(fq)
    core.emit_event(be["id"], "FQ_WITHDRAWN", {"foreign_qualification_id": fq["id"]})
    return response.success_object(serialize.foreign_qualification(fq))


@bp.route("/business-entities/<be_id>/foreign-qualifications", methods=["GET"])
def list_foreign_qualifications(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    fsc = request.args.get("foreign_state_code")
    items = core.children_foreign_qualifications(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    if fsc is not None:
        items = [x for x in items if x["foreign_state_code"] == fsc]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.foreign_qualification(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)
