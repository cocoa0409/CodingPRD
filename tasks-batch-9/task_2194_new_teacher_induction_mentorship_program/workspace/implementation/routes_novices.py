"""Novice enrolment, readiness read, withdrawal and retention outcome."""

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, MENTOR, NOVICE, STATE, guard, own_novice_row,
                  own_site, role, scope_rows)
from envelope import list_response, object_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field, fk,
                        int_field, path_row, str_field)

bp = Blueprint("novices", __name__)

WITHDRAWABLE = ("ENROLLED", "MATCHED", "ACTIVE", "COMPLETION_PENDING")


@bp.post("/novice-teachers")
@guard([ADMIN, LEAD])
def enrol_novice():
    data = body()
    site = fk("sites", data, "site_id")
    cohort = fk("cohorts", data, "cohort_id")
    str_field(data, "site_id", 1, None)
    str_field(data, "cohort_id", 1, None)
    full_name = str_field(data, "full_name", 1, 120)
    subject_area = enum_field(data, "subject_area", calc.SUBJECTS)
    induction_year = int_field(data, "induction_year", 1, 2)
    own_site(site["id"])
    if site.get("status") != "OPEN":
        raise ApiError("ERR_SITE_CLOSED")
    if cohort.get("status") not in ("FORMING", "RUNNING"):
        raise ApiError("ERR_COHORT_STATE_INVALID")
    row = new_row({
        "site_id": site["id"],
        "cohort_id": cohort["id"],
        "full_name": full_name,
        "subject_area": subject_area,
        "induction_year": induction_year,
        "license_stage": "PRELIMINARY",
        "program_status": "ENROLLED",
        "license_advancement_status": "NOT_ELIGIBLE",
        "retention_outcome": "UNKNOWN",
        "retention_observed_on": None,
        "withdrawn_reason": None,
        "verified_contact_minutes": 0,
        "documented_observation_cycles": 0,
        "credited_seminar_sessions": 0,
        "attained_milestone_count": 0,
        "readiness_index_live": 0.0,
        "readiness_index_snapshot": 0.0,
    })
    db.novices[row["id"]] = row
    for milestone in domain.milestones_sorted():
        cascades.create_attainment(row, milestone)
    domain.recompute_cohort_enrolment(cohort)
    touch(cohort)
    return row_response(row, 201)


@bp.get("/novice-teachers")
@guard([ADMIN, LEAD, STATE])
def list_novices():
    rows = sorted_rows(list(db.novices.values()))
    rows = scope_rows(rows, site_getter=lambda r: r.get("site_id"),
                      novice_id_getter=lambda r: r.get("id"))
    rows = apply_filters(rows, {
        "site_id": ("site_id", "str"),
        "cohort_id": ("cohort_id", "str"),
        "program_status": ("program_status", "str"),
        "license_advancement_status": ("license_advancement_status", "str"),
    })
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/novice-teachers/<row_id>")
@guard([ADMIN, LEAD, MENTOR, NOVICE, STATE])
def get_novice(row_id):
    row = path_row("novices", row_id)
    own_novice_row(row)
    return row_response(row)


@bp.get("/novice-teachers/<row_id>/readiness")
@guard([ADMIN, LEAD, NOVICE])
def get_readiness(row_id):
    novice = path_row("novices", row_id)
    own_novice_row(novice)
    domain.recompute_novice_evidence(novice)
    live = domain.readiness_live(novice)
    snapshot, source_id = domain.readiness_snapshot(novice)
    novice["readiness_index_live"] = float(live["index"])
    novice["readiness_index_snapshot"] = float(snapshot)
    data = {
        "novice_id": novice["id"],
        "readiness_index_live": float(live["index"]),
        "readiness_index_snapshot": float(snapshot),
        "contact_component": calc.as_float(live["contact_component"], 4),
        "observation_component": calc.as_float(live["observation_component"], 4),
        "seminar_component": calc.as_float(live["seminar_component"], 4),
        "held_sessions": live["held_sessions"],
        "excused_sessions": live["excused_sessions"],
        "seminar_denominator": live["seminar_denominator"],
        "snapshot_source_attainment_id": source_id,
        "meets_readiness_gate": live["index"] >= calc.READINESS_GATE,
    }
    return object_response(data)


@bp.post("/novice-teachers/<row_id>/withdraw")
@guard([ADMIN])
def withdraw_novice(row_id):
    novice = path_row("novices", row_id)
    data = body()
    reason = str_field(data, "reason", 1, 1000)
    if novice.get("program_status") not in WITHDRAWABLE:
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")

    novice["program_status"] = "WITHDRAWN"
    novice["withdrawn_reason"] = reason
    novice["license_advancement_status"] = "NOT_ELIGIBLE"
    touch(novice)

    for match in domain.matches_of_novice(novice["id"]):
        status = match.get("match_status")
        if status == "PROPOSED":
            cascades.end_match(match, "NOVICE_WITHDRAWN", status="REJECTED")
        elif status in ("ACTIVE", "SUSPENDED"):
            cascades.end_match(match, "NOVICE_WITHDRAWN")

    for packet in domain.packets_of_novice(novice["id"]):
        if packet.get("packet_status") in ("ASSEMBLING", "RETURNED"):
            packet["packet_status"] = "WITHDRAWN"
            packet["withdrawn_reason"] = "NOVICE_WITHDRAWN"
            touch(packet)

    cohort = db.cohorts.get(novice.get("cohort_id"))
    domain.recompute_cohort_enrolment(cohort)
    touch(cohort)
    return row_response(novice)


@bp.post("/novice-teachers/<row_id>/retention-outcome")
@guard([ADMIN])
def set_retention(row_id):
    novice = path_row("novices", row_id)
    data = body()
    outcome = enum_field(data, "retention_outcome", calc.RETENTION_OUTCOMES)
    observed_on = datetime_field(data, "observed_on")
    novice["retention_outcome"] = outcome
    novice["retention_observed_on"] = iso(observed_on)
    touch(novice)
    for packet in domain.packets_of_novice(novice["id"]):
        if packet.get("packet_status") == "ASSEMBLING":
            cascades.rescore_packet(packet, novice)
    return row_response(novice)
