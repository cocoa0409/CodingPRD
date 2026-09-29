"""Milestone attainment rows and the attest/revoke/reopen decision."""

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, NOVICE, STATE, actor, guard, own_site, role,
                  scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, now, sorted_rows, touch
from validators import (apply_filters, body, enum_field, fk, path_row, str_field)

bp = Blueprint("attainments", __name__)


def _novice_of(row):
    return db.novices.get(row.get("novice_id"))


@bp.post("/milestone-attainments")
@guard([ADMIN, LEAD])
def create_attainment():
    data = body()
    novice = fk("novices", data, "novice_id")
    milestone = fk("milestones", data, "milestone_id")
    str_field(data, "novice_id", 1, None)
    str_field(data, "milestone_id", 1, None)
    evidence_note = str_field(data, "evidence_note", 10, 1000, required=False)
    if role() == LEAD:
        own_site(novice.get("site_id"))
    if novice.get("program_status") != "ACTIVE":
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
    for row in domain.attainments_of_novice(novice["id"]):
        if row.get("milestone_id") == milestone["id"]:
            raise ApiError("ERR_DUPLICATE_ATTAINMENT")
    row = cascades.create_attainment(novice, milestone, evidence_note)
    return row_response(row, 201)


@bp.get("/milestone-attainments")
@guard([ADMIN, LEAD, NOVICE, STATE])
def list_attainments():
    rows = sorted_rows(list(db.attainments.values()))
    rows = scope_rows(rows, novice_getter=_novice_of,
                      novice_id_getter=lambda r: r.get("novice_id"))
    rows = apply_filters(rows, {"novice_id": ("novice_id", "str"),
                                "milestone_id": ("milestone_id", "str"),
                                "status": ("status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/milestone-attainments/<row_id>")
@guard([ADMIN, LEAD, NOVICE, STATE])
def get_attainment(row_id):
    row = path_row("attainments", row_id)
    novice = _novice_of(row)
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))
    elif role() == NOVICE and row.get("novice_id") != actor():
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    return row_response(row)


def _prerequisite_attained(novice, milestone):
    prerequisite_id = milestone.get("prerequisite_milestone_id")
    if not prerequisite_id:
        return True
    for row in domain.attainments_of_novice(novice["id"]):
        if row.get("milestone_id") == prerequisite_id:
            return row.get("status") == "ATTAINED"
    return False


def _verifier_ids(novice):
    ids = set()
    for log in domain.logs_of_novice(novice["id"]):
        if log.get("verification_status") == "VERIFIED" and log.get("verified_by_user_id"):
            ids.add(log.get("verified_by_user_id"))
    return ids


@bp.post("/milestone-attainments/<row_id>/decision")
@guard([ADMIN, LEAD])
def decide_attainment(row_id):
    attainment = path_row("attainments", row_id)
    data = body()
    decision = enum_field(data, "decision", ("ATTAIN", "REVOKE", "REOPEN"))
    evidence_note = str_field(data, "evidence_note", 10, 1000, required=False)
    reason = str_field(data, "reason", 1, 1000, required=False)
    novice = _novice_of(attainment)
    milestone = db.milestones.get(attainment.get("milestone_id"))
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))

    needed = {"ATTAIN": "IN_PROGRESS", "REVOKE": "ATTAINED", "REOPEN": "REVOKED"}[decision]
    if attainment.get("status") != needed:
        raise ApiError("ERR_ATTAINMENT_STATE_INVALID")

    if decision == "ATTAIN" and actor() in _verifier_ids(novice):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision in ("ATTAIN", "REOPEN") and not _prerequisite_attained(novice, milestone):
        raise ApiError("ERR_PREREQUISITE_NOT_ATTAINED")

    domain.recompute_novice_evidence(novice)
    if decision == "ATTAIN" and not cascades.requirements_met(novice, milestone):
        raise ApiError("ERR_MILESTONE_REQUIREMENTS_NOT_MET")
    if decision == "REVOKE" and int(attainment.get("revocation_count") or 0) >= 3:
        raise ApiError("ERR_REVOCATION_LIMIT_REACHED")

    if decision == "ATTAIN":
        held, excused = domain.readiness_inputs(novice)
        attainment["status"] = "ATTAINED"
        if evidence_note is not None:
            attainment["evidence_note"] = evidence_note
        attainment["attained_on"] = iso(now())
        attainment["attested_by_user_id"] = actor()
        attainment["revoked_on"] = None
        attainment["revoke_reason"] = None
        attainment["snapshot_contact_minutes"] = int(
            novice.get("verified_contact_minutes") or 0)
        attainment["snapshot_observation_cycles"] = int(
            novice.get("documented_observation_cycles") or 0)
        attainment["snapshot_credited_seminars"] = int(
            novice.get("credited_seminar_sessions") or 0)
        attainment["snapshot_held_sessions"] = held
        attainment["snapshot_excused_sessions"] = excused
        touch(attainment)
        if (milestone.get("gates_license_recommendation")
                and novice.get("license_advancement_status") == "ELIGIBLE"):
            novice["license_advancement_status"] = "RECOMMENDED"
            novice["license_stage"] = milestone.get("license_stage_unlocked")
        cascades.unlock_dependents(novice, milestone["id"])
        domain.refresh_novice(novice)
    elif decision == "REVOKE":
        attainment["status"] = "REVOKED"
        attainment["revoked_on"] = iso(now())
        attainment["revoke_reason"] = reason
        attainment["revocation_count"] = int(attainment.get("revocation_count") or 0) + 1
        touch(attainment)
        cascades.relock_dependents(novice, milestone["id"])
        if milestone.get("gates_license_recommendation"):
            if cascades.drop_recommendation(novice):
                cascades.return_submitted_packets(novice, "EVIDENCE_REVOKED")
        domain.refresh_novice(novice)
    else:
        attainment["status"] = "IN_PROGRESS"
        attainment["revoke_reason"] = None
        attainment["revoked_on"] = None
        touch(attainment)
    return row_response(attainment)
