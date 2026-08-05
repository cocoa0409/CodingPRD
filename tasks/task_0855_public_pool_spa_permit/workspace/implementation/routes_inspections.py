"""Inspections, the enforcement axis, and violations."""

from flask import g

import constants as C
import domain
from auth import authenticate, authorize, own_or_403, require_action_role
from clock import LOGICAL_CLOCK, add_days, add_minutes
from errors import ApiError
from helpers import facility_or_404, get_or_404, matches, paged_list
from response import object_response
from serializers import inspection_json, violation_json
from store import DB, base_record, ordered, touch
from validation import (bad, json_body, opt_bool, opt_string, qs, req_datetime,
                        req_enum, req_string)

WORKFLOW_ACTIONS = ("START", "SUBMIT", "FINALIZE", "VOID")
WORKFLOW_ACTION_ROLES = {
    "START": ("Inspector",),
    "SUBMIT": ("Inspector",),
    "FINALIZE": ("HealthAuthorityAdmin",),
    "VOID": ("HealthAuthorityAdmin",),
}
ENFORCEMENT_ACTIONS = ("ISSUE_NOTICE", "ESCALATE", "CLEAR")
ACTIVE_WORKFLOW_STATES = ("SCHEDULED", "IN_PROGRESS", "SUBMITTED", "FINALIZED")


def _invalid_inspection_state():
    raise ApiError("ERR_INVALID_INSPECTION_STATE",
                   "The inspection is not in a state that permits this action.")


def _invalid_enforcement_state():
    raise ApiError("ERR_INVALID_ENFORCEMENT_STATE",
                   "The enforcement axis does not permit this action.")


def _invalid_violation_state():
    raise ApiError("ERR_INVALID_VIOLATION_STATE",
                   "The violation is not in a state that permits this action.")


def register(app):

    # ------------------------------------------------------------------
    # inspections
    # ------------------------------------------------------------------
    @app.route("/inspections", methods=["POST"])
    def create_inspection():
        authenticate()
        authorize("Inspector")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        inspection_type = req_enum(body, "inspection_type", C.INSPECTION_TYPES)
        scheduled_start_at = req_datetime(body, "scheduled_start_at")
        scheduled_end_at = req_datetime(body, "scheduled_end_at")
        prior_inspection_id = opt_string(body, "prior_inspection_id")
        if scheduled_end_at <= scheduled_start_at:
            bad("scheduled_end_at must be strictly after scheduled_start_at.")

        facility = facility_or_404(facility_id)
        prior = None
        if prior_inspection_id is not None:
            prior = get_or_404(DB.inspections, prior_inspection_id,
                               "ERR_INSPECTION_NOT_FOUND")
            if inspection_type == "REINSPECTION":
                if (prior["facility_id"] != facility["id"]
                        or prior["workflow_status"] != "FINALIZED"):
                    raise ApiError("ERR_PRIOR_INSPECTION_MISMATCH",
                                   "The prior inspection does not qualify.")

        buffer_delta = C.INSPECTION_BUFFER_MINUTES
        for other in DB.inspections.values():
            if other["facility_id"] != facility["id"]:
                continue
            if other["workflow_status"] not in ACTIVE_WORKFLOW_STATES:
                continue
            other_end = add_minutes(other["scheduled_end_at"], buffer_delta)
            other_start = add_minutes(other["scheduled_start_at"], -buffer_delta)
            if scheduled_start_at <= other_end and scheduled_end_at >= other_start:
                raise ApiError("ERR_INSPECTION_WINDOW_CONFLICT",
                               "The requested visit window conflicts with another.")

        if inspection_type == "ROUTINE" and facility["is_seasonal"]:
            start_date = scheduled_start_at.date()
            if not (facility["season_start_date"] <= start_date
                    <= facility["season_end_date"]):
                raise ApiError("ERR_OUT_OF_SEASON",
                               "A routine visit must fall inside the season window.")

        if inspection_type == "REINSPECTION":
            if prior_inspection_id is None:
                raise ApiError("ERR_INSPECTION_TYPE_REQUIRES_PRIOR",
                               "A reinspection requires prior_inspection_id.")
        elif prior_inspection_id is not None:
            raise ApiError("ERR_INSPECTION_TYPE_REQUIRES_PRIOR",
                           "Only a reinspection may carry prior_inspection_id.")

        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "prior_inspection_id": prior_inspection_id,
            "inspection_type": inspection_type,
            "inspector_user_id": g.user_id,
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
            "workflow_status": "SCHEDULED",
            "enforcement_status": "NONE",
            "started_at": None,
            "submitted_at": None,
            "finalized_at": None,
            "critical_demerits": None,
            "noncritical_demerits": None,
            "score": None,
            "result": None,
            "reinspection_due_on": None,
            "voided_at": None,
        })
        DB.inspections[rec["id"]] = rec
        return object_response(inspection_json(rec), 201)

    @app.route("/inspections/<inspection_id>", methods=["GET"])
    def read_inspection(inspection_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        rec = get_or_404(DB.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
        return object_response(inspection_json(rec))

    @app.route("/inspections", methods=["GET"])
    def list_inspections():
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        f_facility = qs("facility_id")
        f_prior = qs("prior_inspection_id")
        f_type = qs("inspection_type")
        f_workflow = qs("workflow_status")
        f_enforcement = qs("enforcement_status")
        rows = [i for i in DB.inspections.values()
                if matches(i["facility_id"], f_facility)
                and matches(i["prior_inspection_id"], f_prior)
                and matches(i["inspection_type"], f_type)
                and matches(i["workflow_status"], f_workflow)
                and matches(i["enforcement_status"], f_enforcement)]
        return paged_list(rows, inspection_json)

    @app.route("/inspections/<inspection_id>/transition", methods=["POST"])
    def transition_inspection(inspection_id):
        authenticate()
        authorize("Inspector", "HealthAuthorityAdmin")
        insp = get_or_404(DB.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
        body = json_body()
        action = req_enum(body, "action", WORKFLOW_ACTIONS)
        require_action_role(action, WORKFLOW_ACTION_ROLES)
        facility = DB.facilities.get(insp["facility_id"])

        if action == "START":
            if insp["workflow_status"] != "SCHEDULED":
                _invalid_inspection_state()
            if g.user_id != insp["inspector_user_id"]:
                _invalid_inspection_state()
            insp["workflow_status"] = "IN_PROGRESS"
            insp["started_at"] = LOGICAL_CLOCK.now()
        elif action == "SUBMIT":
            if insp["workflow_status"] != "IN_PROGRESS":
                _invalid_inspection_state()
            if g.user_id != insp["inspector_user_id"]:
                _invalid_inspection_state()
            insp["workflow_status"] = "SUBMITTED"
            insp["submitted_at"] = LOGICAL_CLOCK.now()
        elif action == "FINALIZE":
            if insp["workflow_status"] != "SUBMITTED":
                _invalid_inspection_state()
            _finalize(insp, facility)
        else:  # VOID
            if insp["workflow_status"] == "VOIDED":
                _invalid_inspection_state()
            _void(insp, facility)

        touch(insp)
        return object_response(inspection_json(insp))

    def _finalize(insp, facility):
        insp["workflow_status"] = "FINALIZED"
        insp["finalized_at"] = LOGICAL_CLOCK.now()
        critical, noncritical, score, result = domain.score_inspection(insp)
        insp["critical_demerits"] = critical
        insp["noncritical_demerits"] = noncritical
        insp["score"] = score
        insp["result"] = result
        if result in ("CONDITIONAL", "FAIL"):
            insp["reinspection_due_on"] = add_days(insp["finalized_at"].date(),
                                                   C.REINSPECTION_DUE_DAYS)
        else:
            insp["reinspection_due_on"] = None

        # hop 1 — the facility's open demerit total now includes this inspection
        domain.bump_facility(facility)

        # hop 2 — a failing inspection auto-issues the notice and charges the fee
        if result == "FAIL":
            insp["enforcement_status"] = "NOTICE_ISSUED"
            domain.post_ledger_entry(facility["operator_id"], "REINSPECTION_FEE",
                                     C.REINSPECTION_FEE_CENTS, permit_id=None)
            # hop 3 + 4 — an open imminent hazard suspends the permit and closes
            if _has_open_imminent(insp):
                domain.suspend_issued_permit_for_hazard(facility)

    def _void(insp, facility):
        insp["workflow_status"] = "VOIDED"
        insp["voided_at"] = LOGICAL_CLOCK.now()
        for v in domain.violations_of_inspection(insp["id"]):
            if v["status"] != "VOIDED":
                v["status"] = "VOIDED"
                touch(v)
        domain.bump_facility(facility)
        if insp["enforcement_status"] in ("NOTICE_ISSUED", "ESCALATED"):
            insp["enforcement_status"] = "CLEARED"

    def _has_open_imminent(insp):
        return any(v["severity"] == "IMMINENT_HEALTH_HAZARD" and v["status"] == "OPEN"
                   for v in domain.violations_of_inspection(insp["id"]))

    @app.route("/inspections/<inspection_id>/enforcement", methods=["POST"])
    def inspection_enforcement(inspection_id):
        authenticate()
        authorize("HealthAuthorityAdmin")
        insp = get_or_404(DB.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
        body = json_body()
        action = req_enum(body, "action", ENFORCEMENT_ACTIONS)
        note = opt_string(body, "note")
        facility = DB.facilities.get(insp["facility_id"])

        if action == "ISSUE_NOTICE":
            if insp["workflow_status"] != "FINALIZED":
                _invalid_enforcement_state()
            if insp["enforcement_status"] != "NONE":
                _invalid_enforcement_state()
            if insp["result"] not in ("CONDITIONAL", "FAIL"):
                _invalid_enforcement_state()
            insp["enforcement_status"] = "NOTICE_ISSUED"
            if _has_open_imminent(insp):
                domain.suspend_issued_permit_for_hazard(facility)
        elif action == "ESCALATE":
            if insp["workflow_status"] != "FINALIZED":
                _invalid_enforcement_state()
            if insp["enforcement_status"] != "NOTICE_ISSUED":
                _invalid_enforcement_state()
            if not any(v["status"] == "OPEN"
                       for v in domain.violations_of_inspection(insp["id"])):
                _invalid_enforcement_state()
            insp["enforcement_status"] = "ESCALATED"
            domain.create_closure_order(facility, "PERMIT_ACTION", g.user_id,
                                        "HealthAuthorityAdmin", note=note)
        else:  # CLEAR
            if insp["workflow_status"] != "FINALIZED":
                _invalid_enforcement_state()
            if insp["enforcement_status"] not in ("NOTICE_ISSUED", "ESCALATED"):
                _invalid_enforcement_state()
            if any(v["status"] == "OPEN"
                   for v in domain.violations_of_inspection(insp["id"])):
                _invalid_enforcement_state()
            insp["enforcement_status"] = "CLEARED"

        touch(insp)
        return object_response(inspection_json(insp))

    # ------------------------------------------------------------------
    # violations
    # ------------------------------------------------------------------
    @app.route("/inspections/<inspection_id>/violations", methods=["POST"])
    def create_violation(inspection_id):
        authenticate()
        authorize("Inspector")
        insp = get_or_404(DB.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
        body = json_body()
        code = req_string(body, "code", min_len=1, max_len=32)
        severity = req_enum(body, "severity", C.SEVERITIES)
        description = req_string(body, "description", min_len=1)
        corrected_on_site = opt_bool(body, "corrected_on_site", default=False)

        if insp["workflow_status"] != "IN_PROGRESS":
            _invalid_inspection_state()
        if g.user_id != insp["inspector_user_id"]:
            _invalid_inspection_state()

        rec = base_record()
        rec.update({
            "inspection_id": insp["id"],
            "code": code,
            "severity": severity,
            "description": description,
            "corrected_on_site": corrected_on_site,
            "points_assessed": domain.violation_points(severity, corrected_on_site),
            "status": "OPEN",
            "corrected_at": None,
            "verified_at": None,
            "rejection_count": 0,
        })
        DB.violations[rec["id"]] = rec
        return object_response(violation_json(rec), 201)

    @app.route("/inspections/<inspection_id>/violations", methods=["GET"])
    def list_violations(inspection_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        insp = get_or_404(DB.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
        f_status = qs("status")
        rows = [v for v in DB.violations.values()
                if v["inspection_id"] == insp["id"]
                and matches(v["status"], f_status)]
        return paged_list(rows, violation_json)

    @app.route("/violations/<violation_id>/correct", methods=["POST"])
    def correct_violation(violation_id):
        authenticate()
        authorize("Operator")
        violation = get_or_404(DB.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
        body = json_body()
        opt_string(body, "correction_note")
        insp = DB.inspections.get(violation["inspection_id"])
        facility = DB.facilities.get(insp["facility_id"]) if insp else None
        own_or_403(facility["operator_id"] if facility else None)

        if violation["status"] != "OPEN":
            _invalid_violation_state()
        if insp is None or insp["workflow_status"] != "FINALIZED":
            _invalid_violation_state()

        violation["status"] = "CORRECTED"
        violation["corrected_at"] = LOGICAL_CLOCK.now()
        touch(violation)
        domain.bump_facility(facility)
        return object_response(violation_json(violation))

    @app.route("/violations/<violation_id>/verify", methods=["POST"])
    def verify_violation(violation_id):
        authenticate()
        authorize("Inspector")
        violation = get_or_404(DB.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
        body = json_body()
        outcome = req_enum(body, "outcome", ("VERIFIED", "REJECTED"))

        if violation["status"] != "CORRECTED":
            _invalid_violation_state()

        insp = DB.inspections.get(violation["inspection_id"])
        facility = DB.facilities.get(insp["facility_id"]) if insp else None

        if outcome == "VERIFIED":
            violation["status"] = "VERIFIED"
            violation["verified_at"] = LOGICAL_CLOCK.now()
            touch(violation)
        else:
            violation["status"] = "OPEN"
            violation["rejection_count"] += 1
            touch(violation)
            if facility is not None:
                domain.bump_facility(facility)
        return object_response(violation_json(violation))
