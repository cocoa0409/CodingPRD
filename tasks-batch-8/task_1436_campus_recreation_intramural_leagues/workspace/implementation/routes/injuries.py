"""Injury reports and participation-hold cascades."""

from flask import Blueprint, g, request

import errors as E
from domain import (injury_out, get_or_404, promote_waitlist_head, HOLD_SEVERITIES,
                    SEVERITIES)
from store import DB
from util import (body_json, req_str, req_enum, envelope_object, list_response,
                  require_role, stamp_new, touch, now)

bp = Blueprint("injuries", __name__)


@bp.route("/v1/injury-reports", methods=["POST"])
def create_injury_report():
    require_role("Member", "FacilityManager")
    body = body_json()
    if g.role == "Member" and body.get("member_id") is not None and body.get("member_id") != g.user_id:
        raise E.err_forbidden("Members may only report injuries for themselves")
    member_id = req_str(body, "member_id")
    if g.role == "Member" and member_id != g.user_id:
        raise E.err_forbidden("Members may only report injuries for themselves")
    member = get_or_404(DB.members, member_id)
    game = None
    game_id = body.get("game_id")
    if game_id is not None:
        game = get_or_404(DB.games, game_id)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    if game is not None:
        on_roster = False
        for r in DB.roster_entries.values():
            if r["member_id"] == member_id and r["status"] == "ACTIVE" and \
               r["team_id"] in (game["home_team_id"], game["away_team_id"]):
                on_roster = True
                break
        if not on_roster:
            raise E.err_injury_game_mismatch()
    report = stamp_new({
        "member_id": member_id,
        "game_id": game_id,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
        "clearance_note": None,
    })
    DB.injury_reports[report["id"]] = report
    if severity in HOLD_SEVERITIES:
        if member["status"] == "ACTIVE":
            member["status"] = "SUSPENDED"
        # Cascade: cancel the member's REGISTERED registrations on future
        # SCHEDULED classes; each cancellation runs waitlist promotion.
        targets = []
        for reg in DB.registrations.values():
            if reg["member_id"] != member_id or reg["status"] != "REGISTERED":
                continue
            fc = DB.fitness_classes.get(reg["fitness_class_id"])
            if fc is None or fc["status"] != "SCHEDULED":
                continue
            if fc["start_at"] is not None and fc["start_at"] > now():
                targets.append((reg, fc))
        targets.sort(key=lambda x: x[0]["_seq"])
        for reg, fc in targets:
            reg["status"] = "CANCELLED"
            touch(reg)
            fc["registered_count"] -= 1
            touch(fc)
            promote_waitlist_head(fc)
        touch(member)
    return envelope_object(injury_out(report), 201)


@bp.route("/v1/injury-reports/<injury_report_id>", methods=["GET"])
def get_injury_report(injury_report_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    report = get_or_404(DB.injury_reports, injury_report_id)
    return envelope_object(injury_out(report))


@bp.route("/v1/injury-reports", methods=["GET"])
def list_injury_reports():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    member_id = request.args.get("member_id")
    game_id = request.args.get("game_id")
    status = request.args.get("status")
    records = [r for r in DB.injury_reports.values()
               if (member_id is None or r["member_id"] == member_id)
               and (game_id is None or r["game_id"] == game_id)
               and (status is None or r["status"] == status)]
    return list_response(records, injury_out)


@bp.route("/v1/injury-reports/<injury_report_id>/clear", methods=["POST"])
def clear_injury_report(injury_report_id):
    require_role("RecAdmin")
    report = get_or_404(DB.injury_reports, injury_report_id)
    body = body_json()
    note = req_str(body, "clearance_note")
    if report["status"] != "REPORTED":
        raise E.err_invalid_state("Only a REPORTED injury report can be cleared")
    report["status"] = "CLEARED"
    report["clearance_note"] = note
    touch(report)
    member = DB.members.get(report["member_id"])
    if member is not None and member["status"] == "SUSPENDED":
        remaining = any(
            r["member_id"] == member["id"] and r["status"] == "REPORTED"
            and r["severity"] in HOLD_SEVERITIES
            for r in DB.injury_reports.values()
        )
        if not remaining:
            member["status"] = "ACTIVE"
            touch(member)
    return envelope_object(injury_out(report))
