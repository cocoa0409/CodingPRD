"""Completion certification packets: assembly, district moves, state decision."""

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, NOVICE, STATE, actor, guard, own_site, role,
                  scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, sorted_rows, touch
from validators import (apply_filters, body, enum_field, fk, int_field,
                        path_row, str_field)

bp = Blueprint("packets", __name__)


def _novice_of(row):
    return db.novices.get(row.get("novice_id"))


@bp.post("/completion-certifications")
@guard([ADMIN, LEAD])
def create_packet():
    data = body()
    novice = fk("novices", data, "novice_id")
    str_field(data, "novice_id", 1, None)
    expected = int_field(data, "expected_novice_version")
    if role() == LEAD:
        own_site(novice.get("site_id"))
    if novice.get("program_status") not in ("ACTIVE", "COMPLETION_PENDING"):
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
    if int(novice.get("version") or 0) != expected:
        raise ApiError("ERR_STALE_PARENT_VERSION")
    for packet in domain.packets_of_novice(novice["id"]):
        if packet.get("packet_status") in domain.ACTIVE_PACKET_STATES:
            raise ApiError("ERR_ACTIVE_PACKET_EXISTS")

    row = new_row({
        "novice_id": novice["id"],
        "packet_status": "ASSEMBLING",
        "evidence_milestone_count": 0,
        "base_score": 0.0,
        "retention_bonus": 0.0,
        "completion_score": 0.0,
        "resubmission_count": 0,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "state_file_number": None,
        "return_reason": None,
        "withdrawn_reason": None,
    })
    db.packets[row["id"]] = row
    cascades.rescore_packet(row, novice)
    if novice.get("program_status") == "ACTIVE":
        novice["program_status"] = "COMPLETION_PENDING"
    touch(novice)
    return row_response(row, 201)


@bp.get("/completion-certifications")
@guard([ADMIN, LEAD, NOVICE, STATE])
def list_packets():
    rows = sorted_rows(list(db.packets.values()))
    rows = scope_rows(rows, novice_getter=_novice_of,
                      novice_id_getter=lambda r: r.get("novice_id"))
    rows = apply_filters(rows, {"novice_id": ("novice_id", "str"),
                                "packet_status": ("packet_status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/completion-certifications/<row_id>")
@guard([ADMIN, LEAD, NOVICE, STATE])
def get_packet(row_id):
    row = path_row("packets", row_id)
    novice = _novice_of(row)
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))
    elif role() == NOVICE and row.get("novice_id") != actor():
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    return row_response(row)


def _gating_milestones_attained(novice):
    attained = {a.get("milestone_id") for a in domain.attainments_of_novice(novice["id"])
                if a.get("status") == "ATTAINED"}
    for milestone in domain.milestones_sorted():
        if milestone.get("gates_license_recommendation") and milestone["id"] not in attained:
            return False
    return True


@bp.post("/completion-certifications/<row_id>/transition")
@guard([ADMIN])
def transition_packet(row_id):
    packet = path_row("packets", row_id)
    data = body()
    action = enum_field(data, "action", ("SUBMIT", "REOPEN", "WITHDRAW"))
    reason = str_field(data, "reason", 1, 1000, required=action == "WITHDRAW")
    novice = _novice_of(packet)
    cohort = db.cohorts.get(novice.get("cohort_id")) if novice else None

    needed = {"SUBMIT": ("ASSEMBLING",),
              "REOPEN": ("RETURNED",),
              "WITHDRAW": ("ASSEMBLING", "RETURNED")}[action]
    if packet.get("packet_status") not in needed:
        raise ApiError("ERR_PACKET_STATE_INVALID")

    if action == "SUBMIT":
        domain.recompute_novice_evidence(novice)
        attained, base, bonus, completion = cascades.rescore_packet(
            packet, novice, persist=False)
        if cohort is None or cohort.get("status") != "CLOSED":
            raise ApiError("ERR_COHORT_STATE_INVALID")
        if novice.get("license_advancement_status") != "RECOMMENDED":
            raise ApiError("ERR_LICENSE_RECOMMENDATION_MISSING")
        if attained < 3 or base < calc.d("75.00"):
            raise ApiError("ERR_MILESTONE_EVIDENCE_INSUFFICIENT")
        if int(novice.get("credited_seminar_sessions") or 0) < int(
                cohort.get("seminar_sessions_required") or 0):
            raise ApiError("ERR_MILESTONE_EVIDENCE_INSUFFICIENT")
        if not _gating_milestones_attained(novice):
            raise ApiError("ERR_MILESTONE_EVIDENCE_INSUFFICIENT")
        cascades.rescore_packet(packet, novice)
        packet["packet_status"] = "SUBMITTED_TO_STATE"
        packet["submitted_by_user_id"] = actor()
        packet["submitted_at"] = iso(now())
        touch(packet)
        return row_response(packet)

    if action == "REOPEN":
        if int(packet.get("resubmission_count") or 0) >= 2:
            raise ApiError("ERR_PACKET_RESUBMISSION_LIMIT_REACHED")
        packet["packet_status"] = "ASSEMBLING"
        packet["return_reason"] = None
        packet["resubmission_count"] = int(packet.get("resubmission_count") or 0) + 1
        touch(packet)
        if novice is not None and novice.get("program_status") == "ACTIVE":
            novice["program_status"] = "COMPLETION_PENDING"
            touch(novice)
        return row_response(packet)

    was_assembling = packet.get("packet_status") == "ASSEMBLING"
    packet["packet_status"] = "WITHDRAWN"
    packet["withdrawn_reason"] = reason
    touch(packet)
    if was_assembling and novice is not None:
        if novice.get("program_status") == "COMPLETION_PENDING":
            novice["program_status"] = "ACTIVE"
            touch(novice)
    return row_response(packet)


@bp.post("/completion-certifications/<row_id>/state-decision")
@guard([STATE])
def state_decision(row_id):
    packet = path_row("packets", row_id)
    data = body()
    decision = enum_field(data, "decision", ("ACCEPT", "RETURN"))
    state_file_number = str_field(data, "state_file_number", 1, 120,
                                  required=decision == "ACCEPT")
    return_reason = str_field(data, "return_reason", 1, 1000,
                             required=decision == "RETURN")
    novice = _novice_of(packet)

    if packet.get("packet_status") != "SUBMITTED_TO_STATE":
        raise ApiError("ERR_PACKET_STATE_INVALID")
    if actor() is not None and actor() == packet.get("submitted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "ACCEPT":
        if novice is None or novice.get("program_status") != "COMPLETION_PENDING":
            raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
        if novice.get("license_advancement_status") != "RECOMMENDED":
            raise ApiError("ERR_LICENSE_RECOMMENDATION_MISSING")
        packet["packet_status"] = "ACCEPTED"
        packet["state_file_number"] = state_file_number
        packet["decided_by_user_id"] = actor()
        packet["decided_at"] = iso(now())
        touch(packet)
        novice["program_status"] = "COMPLETED"
        novice["license_advancement_status"] = "ADVANCED"
        novice["license_stage"] = "CLEAR"
        touch(novice)
        for match in domain.matches_of_novice(novice["id"]):
            if match.get("match_status") in ("ACTIVE", "SUSPENDED"):
                cascades.end_match(match, "PROGRAM_COMPLETED")
        return row_response(packet)

    packet["packet_status"] = "RETURNED"
    packet["return_reason"] = return_reason
    packet["decided_by_user_id"] = actor()
    packet["decided_at"] = iso(now())
    touch(packet)
    if novice is not None and novice.get("program_status") == "COMPLETION_PENDING":
        novice["program_status"] = "ACTIVE"
        touch(novice)
    return row_response(packet)
