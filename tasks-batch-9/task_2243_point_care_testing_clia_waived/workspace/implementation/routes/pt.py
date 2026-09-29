"""Proficiency testing and failure investigation (PRD 3.7)."""

from flask import Blueprint

import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("pt", __name__)

READ_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor")


def _refresh_enrollment(enrollment):
    snap = db.snapshot(enrollment)
    enrollment["graded_event_count"] = calc.graded_event_count(enrollment["id"])
    enrollment["fail_count_last_three"] = calc.fail_count_last_three(enrollment["id"])
    db.touch_if_changed(enrollment, snap)


# --------------------------------------------------------------------------
# Enrollments
# --------------------------------------------------------------------------

@route(bp, "/pt-enrollments", ["POST"], ["ProgramAdmin", "QualityCoordinator"])
def enroll(user_id, role):
    payload = valid.body()
    site = valid.resolve_body("sites", payload, "site_id")
    analyte = valid.req_str(payload, "analyte")
    program_year = valid.req_int(payload, "program_year")
    provider = valid.req_str(payload, "program_provider")
    # Rank 69.
    if any(e["site_id"] == site["id"] and e["analyte"] == analyte
           and e["program_year"] == program_year
           for e in db.data["enrollments"].values()):
        raise errors.ApiError("ERR_DUPLICATE_ENROLLMENT", 409)

    row = db.insert("enrollments", {
        "site_id": site["id"],
        "analyte": analyte,
        "program_year": program_year,
        "program_provider": provider,
        "status": "ENROLLED",
        "graded_event_count": 0,
        "fail_count_last_three": 0,
    })
    return response.object_response(serializers.dump("enrollments", row), 201)


@route(bp, "/pt-enrollments/<enrollment_id>", ["GET"], READ_ROLES)
def read_enrollment(user_id, role, enrollment_id):
    row = valid.resolve("enrollments", enrollment_id)
    return response.object_response(serializers.dump("enrollments", row))


@route(bp, "/pt-enrollments", ["GET"], READ_ROLES)
def list_enrollments(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    items = [e for e in db.rows("enrollments")
             if site_id is None or e["site_id"] == site_id]
    return response.list_response(
        serializers.dump_many("enrollments", valid.page(items, limit, offset)),
        limit, offset, len(items))


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

@route(bp, "/pt-events", ["POST"], ["ProgramAdmin", "QualityCoordinator"])
def register_event(user_id, role):
    payload = valid.body()
    enrollment = valid.resolve_body("enrollments", payload, "enrollment_id")
    shipment_number = valid.req_int(payload, "shipment_number", 1, 3)
    due_date = valid.req_date(payload, "due_date")
    if any(e["enrollment_id"] == enrollment["id"]
           and e["shipment_number"] == shipment_number
           for e in db.data["pt_events"].values()):
        raise errors.invalid_request(
            "shipment_number must be unique for this enrollment.")
    # Rank 46.
    if enrollment["status"] != "ENROLLED":
        raise errors.ApiError("ERR_PT_ENROLLMENT_STATUS_INVALID", 409)

    row = db.insert("pt_events", {
        "enrollment_id": enrollment["id"],
        "shipment_number": shipment_number,
        "due_date": due_date.isoformat(),
        "score_pct": None,
        "graded_on": None,
        "outcome": None,
        "status": "PENDING",
        "root_cause": None,
        "corrective_action": None,
        "investigation_round": 0,
    })
    return response.object_response(serializers.dump("pt_events", row), 201)


@route(bp, "/pt-events/<event_id>", ["GET"], READ_ROLES)
def read_event(user_id, role, event_id):
    row = valid.resolve("pt_events", event_id)
    return response.object_response(serializers.dump("pt_events", row))


@route(bp, "/pt-events", ["GET"], READ_ROLES)
def list_events(user_id, role):
    limit, offset = valid.pagination()
    enrollment_id = valid.arg("enrollment_id")
    outcome = valid.arg("outcome")
    items = [e for e in db.rows("pt_events")
             if (enrollment_id is None or e["enrollment_id"] == enrollment_id)
             and (outcome is None or e["outcome"] == outcome)]
    return response.list_response(
        serializers.dump_many("pt_events", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/pt-events/<event_id>/score", ["POST"],
       ["QualityCoordinator", "ProgramAdmin"])
def score_event(user_id, role, event_id):
    event = valid.resolve("pt_events", event_id)
    payload = valid.body()
    score_pct = valid.req_num(payload, "score_pct", 0, 100)
    graded_on = valid.req_date(payload, "graded_on")
    # Rank 45.
    if event["status"] != "PENDING":
        raise errors.ApiError("ERR_PT_EVENT_ALREADY_GRADED", 409)

    enrollment = db.get("enrollments", event["enrollment_id"])
    outcome = calc.pt_event_outcome(score_pct)

    snap = db.snapshot(event)
    event["score_pct"] = score_pct
    event["graded_on"] = graded_on.isoformat()
    event["outcome"] = outcome
    # The event being graded is already part of the window (it now carries an
    # outcome), so the three-shipment window is taken after the write.
    fail_count = calc.fail_count_last_three(event["enrollment_id"])

    if outcome == "PASS":
        event["status"] = "PASSED"
    elif fail_count < 2:
        event["status"] = "INVESTIGATION_OPEN"
    else:
        event["status"] = "UNSUCCESSFUL_LOCKED"
    db.touch_if_changed(event, snap)

    if event["status"] == "UNSUCCESSFUL_LOCKED" and enrollment is not None:
        esnap = db.snapshot(enrollment)
        enrollment["status"] = "UNSUCCESSFUL_PARTICIPATION"
        db.touch_if_changed(enrollment, esnap)
        for device in derive.devices_of(enrollment["site_id"]):
            if device["status"] != "ACTIVE":
                continue
            if device["analyte"] != enrollment["analyte"]:
                continue
            dsnap = db.snapshot(device)
            device["status"] = "QC_LOCKED"
            device["qc_lock_reason"] = "PT_UNSUCCESSFUL"
            db.touch_if_changed(device, dsnap)

    if enrollment is not None:
        _refresh_enrollment(enrollment)
        derive.recompute_site_by_id(enrollment["site_id"])
    return response.object_response(serializers.dump("pt_events", event))


@route(bp, "/pt-events/<event_id>/investigation", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def submit_investigation(user_id, role, event_id):
    event = valid.resolve("pt_events", event_id)
    payload = valid.body()
    root_cause = valid.req_str(payload, "root_cause")
    corrective_action = valid.req_str(payload, "corrective_action")
    # Rank 50.
    if event["status"] not in ("INVESTIGATION_OPEN", "UNSUCCESSFUL_LOCKED"):
        raise errors.invalid_state(
            "An investigation can only be filed against a failed shipment.")

    event["status"] = "INVESTIGATION_SUBMITTED"
    event["root_cause"] = root_cause
    event["corrective_action"] = corrective_action
    event["investigation_round"] = int(event["investigation_round"] or 0) + 1
    db.touch(event)
    return response.object_response(serializers.dump("pt_events", event))


@route(bp, "/pt-events/<event_id>/investigation-decision", ["POST"],
       ["LabDirector"])
def decide_investigation(user_id, role, event_id):
    event = valid.resolve("pt_events", event_id)
    payload = valid.body()
    decision = valid.req_enum(payload, "decision", ("ACCEPT", "REJECT"))
    valid.opt_str(payload, "note")
    # Rank 50.
    if event["status"] != "INVESTIGATION_SUBMITTED":
        raise errors.invalid_state("The investigation is not awaiting a decision.")

    snap = db.snapshot(event)
    if decision == "ACCEPT":
        # Terminal.  Instruments locked with PT_UNSUCCESSFUL stay locked.
        event["status"] = "INVESTIGATION_ACCEPTED"
    else:
        event["status"] = "INVESTIGATION_OPEN"
    db.touch_if_changed(event, snap)

    enrollment = db.get("enrollments", event["enrollment_id"])
    if enrollment is not None:
        derive.recompute_site_by_id(enrollment["site_id"])
    return response.object_response(serializers.dump("pt_events", event))
