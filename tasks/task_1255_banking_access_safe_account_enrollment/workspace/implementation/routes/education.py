"""EducationPairing endpoints."""

from datetime import timedelta

import db
from errors import (
    err_not_found, err_invalid_state, err_unauthorized, raise_err,
    ERR_COACH_CASELOAD_FULL, ERR_FOLLOW_UP_NOT_DUE,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_enum
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch
from flask import request

COURSE_CODES = {"FOUNDATIONS", "CREDIT_BASICS", "SAVINGS"}
MAX_ACTIVE_PAIRINGS_PER_COACH = 3


def _serialize(p):
    return dict(p)


def register(bp):
    @bp.route("/education-pairings", methods=["POST"])
    def create_pairing():
        user_id, role = require_roles("CoalitionAdmin", "FinancialCoach")
        body = get_json_body()
        require_fields(body, ["participant_id", "coach_id", "course_code"])
        check_string(body["participant_id"], "participant_id")
        check_string(body["coach_id"], "coach_id")
        check_enum(body["course_code"], COURSE_CODES, "course_code")
        if role == "FinancialCoach" and body["coach_id"] != user_id:
            err_unauthorized("FinancialCoach may only create pairings for their own coach_id")

        participant = db.participants.get(body["participant_id"])
        if participant is None:
            err_not_found("Participant not found")

        active_load = sum(
            1 for p in db.education_pairings.values()
            if p["coach_id"] == body["coach_id"] and p["status"] == "ACTIVE"
        )
        if active_load >= MAX_ACTIVE_PAIRINGS_PER_COACH:
            raise_err(ERR_COACH_CASELOAD_FULL, "Coach already has 3 ACTIVE pairings")

        pairing = new_entity()
        pairing.update({
            "participant_id": participant["id"],
            "coach_id": body["coach_id"],
            "course_code": body["course_code"],
            "status": "ACTIVE",
            "completed_at": None,
            "follow_up_due_at": None,
            "follow_up_logged_at": None,
        })
        db.education_pairings[pairing["id"]] = pairing
        return success_object(_serialize(pairing), status=201)

    @bp.route("/education-pairings", methods=["GET"])
    def list_pairings():
        require_roles("CoalitionAdmin", "FinancialCoach", "AgencyNavigator")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.education_pairings.values(), key=lambda x: db.parse_dt(x["created_at"]))
        pid = request.args.get("participant_id")
        cid = request.args.get("coach_id")
        st = request.args.get("status")
        if pid is not None:
            items = [p for p in items if p["participant_id"] == pid]
        if cid is not None:
            items = [p for p in items if p["coach_id"] == cid]
        if st is not None:
            items = [p for p in items if p["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(p) for p in page], limit, offset, total)

    @bp.route("/education-pairings/<pid>", methods=["GET"])
    def get_pairing(pid):
        require_roles("CoalitionAdmin", "FinancialCoach", "AgencyNavigator")
        pairing = db.education_pairings.get(pid)
        if pairing is None:
            err_not_found("EducationPairing not found")
        return success_object(_serialize(pairing))

    @bp.route("/education-pairings/<pid>/complete", methods=["POST"])
    def complete_pairing(pid):
        user_id, _ = require_roles("FinancialCoach")
        pairing = db.education_pairings.get(pid)
        if pairing is None:
            err_not_found("EducationPairing not found")
        if user_id != pairing["coach_id"]:
            err_unauthorized("Only the pairing's coach may complete it")
        if pairing["status"] != "ACTIVE":
            err_invalid_state("Pairing must be ACTIVE to complete")
        now = db.parse_dt(db.get_clock())
        pairing["completed_at"] = db.now_iso()
        pairing["follow_up_due_at"] = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        pairing["status"] = "COMPLETED"
        touch(pairing)
        return success_object(_serialize(pairing))

    @bp.route("/education-pairings/<pid>/log-follow-up", methods=["POST"])
    def log_follow_up(pid):
        user_id, _ = require_roles("FinancialCoach")
        pairing = db.education_pairings.get(pid)
        if pairing is None:
            err_not_found("EducationPairing not found")
        if user_id != pairing["coach_id"]:
            err_unauthorized("Only the pairing's coach may log the follow-up")
        if pairing["status"] == "COMPLETED":
            raise_err(ERR_FOLLOW_UP_NOT_DUE, "Follow-up is not yet due")
        if pairing["status"] != "FOLLOW_UP_DUE":
            err_invalid_state("Pairing must be FOLLOW_UP_DUE to log the follow-up")
        pairing["follow_up_logged_at"] = db.now_iso()
        pairing["status"] = "FOLLOW_UP_DONE"
        touch(pairing)
        return success_object(_serialize(pairing))
