"""Routes: ForeignQualification create/confirm/withdrawal cycle."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_JURISDICTION_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND,
    ERR_QUALIFICATION_NOT_FOUND, ERR_ENTITY_ALREADY_DISSOLVED,
    ERR_POSTURE_NOT_GOOD_STANDING, ERR_REQUIRED_RESOLUTION_MISSING,
    ERR_AGENT_COVERAGE_GAP, ERR_QUALIFICATION_EXISTS,
    ERR_QUALIFICATION_NOT_PENDING, ERR_QUALIFICATION_NOT_QUALIFIED,
    ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING, ERR_EXIT_CLEARANCE_FAILED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_entities import get_entity_or_404

bp = Blueprint("qualifications", __name__)

CS = ["CorporateSecretary"]


@bp.route("/api/entities/<entityId>/qualifications", methods=["POST"])
def create_qualification(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    body = get_body()
    # Priority 3: body FK existence
    jurisdiction_id = body.get("jurisdiction_id")
    if jurisdiction_id is not None and jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    appointment_id = body.get("agent_appointment_id")
    if appointment_id is not None and appointment_id not in store.agent_appointments:
        raise_err(ERR_APPOINTMENT_NOT_FOUND)
    # Priority 4: schema
    if jurisdiction_id is None:
        raise_err(ERR_INVALID_REQUEST, "jurisdiction_id is required")
    if appointment_id is None:
        raise_err(ERR_INVALID_REQUEST, "agent_appointment_id is required")
    if jurisdiction_id == entity["formation_jurisdiction_id"]:
        raise_err(ERR_INVALID_REQUEST,
                  "Qualification jurisdiction must differ from the formation jurisdiction")
    # Priority 5: parent not DISSOLVED
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    # Priority 6: posture gate (freshly computed)
    svc.lazy_eval_entity(entity, auto_deny=False)
    if entity["compliance_posture"] != "GOOD_STANDING":
        raise_err(ERR_POSTURE_NOT_GOOD_STANDING,
                  "Entity compliance posture is not GOOD_STANDING")
    # Priority 7: authorizing resolution, then agent coverage
    if svc.find_authorizing_resolution(
            entity["id"], "AUTHORIZE_QUALIFICATION",
            {"jurisdiction_id": jurisdiction_id}) is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE AUTHORIZE_QUALIFICATION resolution for this jurisdiction")
    appt = store.agent_appointments[appointment_id]
    if (appt["entity_id"] != entity["id"] or appt["jurisdiction_id"] != jurisdiction_id
            or appt["status"] != "ACTIVE"):
        raise_err(ERR_AGENT_COVERAGE_GAP,
                  "Agent appointment does not actively cover this entity and jurisdiction")
    # Priority 8: no duplicate open qualification
    if any(q for q in svc.quals_of(entity["id"])
           if q["jurisdiction_id"] == jurisdiction_id
           and q["status"] in ("PENDING", "QUALIFIED", "WITHDRAWAL_PENDING")):
        raise_err(ERR_QUALIFICATION_EXISTS,
                  "An open qualification already exists for this jurisdiction")
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "jurisdiction_id": jurisdiction_id,
        "agent_appointment_id": appointment_id,
        "qualified_date": None,
        "status": "PENDING",
    })
    store.qualifications[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/qualifications", methods=["GET"])
def list_qualifications():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.qualifications.values()))
    for param, field in (("entity_id", "entity_id"), ("jurisdiction_id", "jurisdiction_id"),
                         ("status", "status"), ("agent_appointment_id", "agent_appointment_id")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_qualification_or_404(qualificationId):
    rec = store.qualifications.get(qualificationId)
    if rec is None:
        raise_err(ERR_QUALIFICATION_NOT_FOUND)
    return rec


@bp.route("/api/qualifications/<qualificationId>", methods=["GET"])
def get_qualification(qualificationId):
    require_roles(ALL_ROLES)
    return ok_object(svc.serialize(get_qualification_or_404(qualificationId)))


@bp.route("/api/qualifications/<qualificationId>/confirm", methods=["POST"])
def confirm_qualification(qualificationId):
    require_roles(CS)
    rec = get_qualification_or_404(qualificationId)
    get_body()
    if rec["status"] != "PENDING":
        raise_err(ERR_QUALIFICATION_NOT_PENDING, "confirm requires status == PENDING")
    rec["status"] = "QUALIFIED"
    rec["qualified_date"] = svc.fmt_date(store.today())
    store.touch(rec)
    entity = store.entities[rec["entity_id"]]
    jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
    period = svc.qualification_first_period(entity, jurisdiction)
    svc.generate_filings(entity, jurisdiction, period)
    return ok_object(svc.serialize(rec))


@bp.route("/api/qualifications/<qualificationId>/commence-withdrawal", methods=["POST"])
def commence_withdrawal(qualificationId):
    require_roles(CS)
    rec = get_qualification_or_404(qualificationId)
    get_body()
    if rec["status"] != "QUALIFIED":
        raise_err(ERR_QUALIFICATION_NOT_QUALIFIED,
                  "commence-withdrawal requires status == QUALIFIED")
    if svc.find_authorizing_resolution(
            rec["entity_id"], "AUTHORIZE_WITHDRAWAL",
            {"jurisdiction_id": rec["jurisdiction_id"]}) is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE AUTHORIZE_WITHDRAWAL resolution for this jurisdiction")
    rec["status"] = "WITHDRAWAL_PENDING"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/qualifications/<qualificationId>/abort-withdrawal", methods=["POST"])
def abort_withdrawal(qualificationId):
    require_roles(CS)
    rec = get_qualification_or_404(qualificationId)
    get_body()
    if rec["status"] != "WITHDRAWAL_PENDING":
        raise_err(ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING,
                  "abort-withdrawal requires status == WITHDRAWAL_PENDING")
    rec["status"] = "QUALIFIED"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/qualifications/<qualificationId>/finalize-withdrawal", methods=["POST"])
def finalize_withdrawal(qualificationId):
    require_roles(CS)
    rec = get_qualification_or_404(qualificationId)
    get_body()
    if rec["status"] != "WITHDRAWAL_PENDING":
        raise_err(ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING,
                  "finalize-withdrawal requires status == WITHDRAWAL_PENDING")
    entity = store.entities[rec["entity_id"]]
    # Lazy evaluation so past-due filings flip to OVERDUE before exit clearance
    svc.lazy_eval_entity(entity)
    open_filings = [f for f in svc.filings_of(entity["id"])
                    if f["jurisdiction_id"] == rec["jurisdiction_id"]
                    and f["status"] in ("OVERDUE", "SUBMITTED", "REJECTED")]
    if open_filings:
        raise_err(ERR_EXIT_CLEARANCE_FAILED,
                  "Filings in this jurisdiction are not clear for exit")
    rec["status"] = "WITHDRAWN"
    store.touch(rec)
    for f in svc.filings_of(entity["id"]):
        if (f["jurisdiction_id"] == rec["jurisdiction_id"]
                and f["status"] in ("SCHEDULED", "PREPARED")):
            f["status"] = "WITHDRAWN"
            store.touch(f)
            svc.append_event(entity["id"], "FILING_WITHDRAWN", {"filing_id": f["id"]})
    svc.recompute_posture(entity)
    return ok_object(svc.serialize(rec))
