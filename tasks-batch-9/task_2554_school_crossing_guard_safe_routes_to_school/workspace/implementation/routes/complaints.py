"""Complaint reads and engineering triage (PRD 3.8)."""
from flask import Blueprint

import domain
import validate as v
from auth import require
from db import touch
from errors import fail
from response import object_response

bp = Blueprint("complaints", __name__)

READ_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor", "SchoolLiaison")
DISPOSITIONS = ("REFER_TO_ENGINEERING", "CLOSE_NO_ACTION")


@bp.get("/srts/complaints/<complaint_id>")
def read_complaint(complaint_id):
    require(*READ_ROLES)
    complaint = domain.get_complaint(complaint_id)
    return object_response(complaint)


@bp.post("/srts/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    user_id, _role = require("TrafficEngineer")
    body = v.body()
    disposition = v.req_enum(body, "disposition", DISPOSITIONS)
    triage_note = v.opt_str(body, "triage_note")
    complaint = domain.get_complaint(complaint_id)

    if complaint["status"] != "RECEIVED":
        fail("ERR_COMPLAINT_NOT_TRIAGEABLE",
             "Only a RECEIVED complaint can be triaged.")

    complaint["disposition"] = disposition
    complaint["triaged_by_user_id"] = user_id
    if triage_note is not None:
        complaint["triage_note"] = triage_note
    if disposition == "REFER_TO_ENGINEERING":
        # A referred complaint is still an open concern: the intersection's
        # open_complaint_count is deliberately unchanged.
        complaint["status"] = "TRIAGED"
        touch(complaint)
    else:
        complaint["status"] = "CLOSED_NO_ACTION"
        touch(complaint)
        intersection = domain.get_intersection(complaint["intersection_id"])
        intersection["open_complaint_count"] -= 1
        touch(intersection)
    return object_response(complaint)
