"""Referee + assignment endpoints."""
from flask import Blueprint, request

import db
from clock import parse_iso, now
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.validation import (
    get_body, require_field, require_str, require_enum, require_country,
    opt_team, check_version,
)


bp = Blueprint("referees", __name__)


VALID_QUALS = {"SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"}
VALID_GRADES = {"A", "B", "C"}


@bp.route("/referees", methods=["POST"])
@require_auth(roles={"Organizer"})
def create_referee():
    body = get_body()
    full_name = require_str(body, "full_name", min_len=1)
    country_code = require_country(body, "country_code")
    team_affiliation = opt_team(body, "team_affiliation")
    require_field(body, "qualifications")
    quals = body["qualifications"]
    if not isinstance(quals, list) or not quals:
        raise err("ERR_VALIDATION", "qualifications must be a non-empty list")
    for q in quals:
        if q not in VALID_QUALS:
            raise err("ERR_VALIDATION", f"invalid qualification: {q}")
    grade = require_enum(body, "grade", VALID_GRADES)
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise err("ERR_VALIDATION", "is_active must be boolean")
    r = {
        "full_name": full_name,
        "country_code": country_code,
        "team_affiliation": team_affiliation,
        "qualifications": list(quals),
        "grade": grade,
        "is_active": is_active,
    }
    db.stamp_create(r, common_fields=True)
    db.referees[r["id"]] = r
    return success(db.public(r), 201)


@bp.route("/referees", methods=["GET"])
@require_auth(roles={"Organizer"})
def list_referees():
    limit, offset = get_pagination()
    qual = request.args.get("qualification")
    is_active = request.args.get("is_active")
    rows = list(db.referees.values())
    if qual:
        rows = [r for r in rows if qual in r["qualifications"]]
    if is_active is not None:
        flag = is_active.lower() in ("1", "true", "yes")
        rows = [r for r in rows if r["is_active"] == flag]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/matches/<match_id>/referee-assignments", methods=["POST"])
@require_auth(roles={"Organizer"})
def assign_referee(match_id):
    m = db.matches.get(match_id)
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    body = get_body()
    require_field(body, "referee_id")
    require_field(body, "role")
    referee_id = body["referee_id"]
    if not isinstance(referee_id, str):
        raise err("ERR_VALIDATION", "referee_id must be a string")
    role = require_enum(body, "role", {"HEAD", "ASSISTANT", "SUBSTITUTE"})
    replaces_assignment_id = body.get("replaces_assignment_id")
    if replaces_assignment_id is not None and not isinstance(replaces_assignment_id, str):
        raise err("ERR_VALIDATION", "replaces_assignment_id must be a string or null")

    ref = db.referees.get(referee_id)
    if not ref:
        raise err("ERR_REFERENCE_NOT_FOUND", "referee not found")
    if replaces_assignment_id is not None and replaces_assignment_id not in db.referee_assignments:
        raise err("ERR_REFERENCE_NOT_FOUND", "replaces_assignment_id not found")
    ev = db.events.get(m["event_id"])
    if not ev:
        raise err("ERR_REFERENCE_NOT_FOUND", "event not found")

    # Conflict-of-interest (priority 9)
    home_p = db.participants.get(m.get("home_participant_id")) if m.get("home_participant_id") else None
    away_p = db.participants.get(m.get("away_participant_id")) if m.get("away_participant_id") else None
    for p in (home_p, away_p):
        if p is None:
            continue
        if ref["country_code"] == p["country_code"]:
            raise err("ERR_CONFLICT_OF_INTEREST", "referee shares country_code with participant")
        if ref.get("team_affiliation") and p.get("team_code") and ref["team_affiliation"] == p["team_code"]:
            raise err("ERR_CONFLICT_OF_INTEREST", "referee shares team affiliation with participant")

    # Qualification (priority 10)
    if ev["event_type"] not in ref["qualifications"]:
        raise err("ERR_REFEREE_NOT_QUALIFIED", "referee not qualified for event_type")

    # Time conflict (priority 11) — referee scheduling rule: half-open intervals,
    # adjacent intervals (one ends == next begins) are allowed.
    new_start = parse_iso(m["scheduled_start_at"])
    new_end = parse_iso(m["scheduled_end_at"])
    for a in db.referee_assignments.values():
        if a["status"] == "REVOKED":
            continue
        if a["referee_id"] != referee_id:
            continue
        if a["match_id"] == match_id:
            continue
        other = db.matches.get(a["match_id"])
        if not other:
            continue
        os = parse_iso(other["scheduled_start_at"])
        oe = parse_iso(other["scheduled_end_at"])
        # half-open overlap: [new_start, new_end) intersects [os, oe)
        if new_start < oe and os < new_end:
            raise err("ERR_REFEREE_TIME_CONFLICT", "referee already assigned to overlapping match")

    a = {
        "match_id": match_id,
        "referee_id": referee_id,
        "role": role,
        "status": "ASSIGNED",
        "replaces_assignment_id": replaces_assignment_id,
    }
    db.stamp_create(a, common_fields=True)
    db.referee_assignments[a["id"]] = a
    return success(db.public(a), 201)


@bp.route("/referee-assignments/<assignment_id>/activate", methods=["POST"])
@require_auth(roles={"Organizer"})
def activate(assignment_id):
    a = db.referee_assignments.get(assignment_id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    body = get_body()
    if a["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "assignment not in ASSIGNED")
    m = db.matches.get(a["match_id"])
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    if now() < parse_iso(m["scheduled_start_at"]):
        raise err("ERR_INVALID_STATE", "now() < match.scheduled_start_at")
    check_version(a, body)
    a["status"] = "ACTIVATED"
    db.stamp_update(a)
    return success(db.public(a), 200)


@bp.route("/referee-assignments/<assignment_id>/revoke", methods=["POST"])
@require_auth(roles={"Organizer"})
def revoke(assignment_id):
    a = db.referee_assignments.get(assignment_id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    body = get_body()
    if a["status"] not in ("ASSIGNED", "ACTIVATED"):
        raise err("ERR_INVALID_STATE", "assignment not revokable")
    m = db.matches.get(a["match_id"])
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    # Revocation from ASSIGNED requires match in SCHEDULED or RESULT_PENDING.
    if a["status"] == "ASSIGNED" and m["status"] not in ("SCHEDULED", "RESULT_PENDING"):
        raise err("ERR_INVALID_STATE", "match not in SCHEDULED/RESULT_PENDING")
    check_version(a, body)
    revoked_role = a["role"]
    a["status"] = "REVOKED"
    db.stamp_update(a)
    # Auto-promote a SUBSTITUTE if HEAD/ASSISTANT was revoked
    if revoked_role in ("HEAD", "ASSISTANT"):
        sub = None
        for cand in db.referee_assignments.values():
            if cand["match_id"] == a["match_id"] and cand["role"] == "SUBSTITUTE" \
                    and cand["status"] == "ASSIGNED":
                sub = cand
                break
        if sub is not None:
            new_a = {
                "match_id": a["match_id"],
                "referee_id": sub["referee_id"],
                "role": revoked_role,
                "status": "ASSIGNED",
                "replaces_assignment_id": a["id"],
            }
            db.stamp_create(new_a, common_fields=True)
            db.referee_assignments[new_a["id"]] = new_a
            # Mark the original substitute slot as revoked (it's been promoted)
            sub["status"] = "REVOKED"
            db.stamp_update(sub)
    return success(db.public(a), 200)
