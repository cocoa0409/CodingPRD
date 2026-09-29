"""Verification tests, the retrofit mandate cascade (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import TECHNICIAN, endpoint, read_endpoint, require_technician_identity
from services import deadlines, guards, ledger, posture

bp = Blueprint("verification_tests", __name__)

ACCEPTING_STATUSES = ("VERIFICATION_PENDING", "VERIFICATION_OVERDUE",
                      "FOLLOWUP_PENDING")


def _close_linked_records(event, closed_at):
    """PRD 3.8: retention is raised, never shortened, when an event closes."""
    horizon = ledger.retention_from(closed_at)
    for record in db.values("service_records"):
        if record["leak_event_id"] != event["id"] or record["voided"]:
            continue
        if record["retention_until"] < horizon:
            snap = db.snapshot(record)
            record["retention_until"] = horizon
            db.commit(record, snap)


@bp.post("/verification-tests")
@endpoint([TECHNICIAN])
def create_verification_test():
    payload = validate.body()
    leak_event_id = validate.req_id(payload, "leak_event_id")
    repair_attempt_id = validate.req_id(payload, "repair_attempt_id")
    technician_id = validate.req_id(payload, "technician_id")
    test_method_code = validate.req_enum(payload, "test_method_code",
                                         constants.TEST_METHOD_CODES)
    performed_at = validate.req_instant(payload, "performed_at")
    result = validate.req_enum(payload, "result", constants.TEST_RESULTS)
    measured_leak_rate_pct = validate.opt_decimal(payload, "measured_leak_rate_pct",
                                                  minimum=Decimal("0"))

    technician = db.require("technicians", technician_id)
    event = db.require("leak_events", leak_event_id)
    attempt = db.require("repair_attempts", repair_attempt_id)

    require_technician_identity(technician_id)
    guards.require_event_not_terminal(event)
    guards.require_state(event["status"] in ACCEPTING_STATUSES)

    guards.require_not_suspended(technician)
    guards.require_certification_current(technician, performed_at)

    from_status = event["status"]
    sequence = ("FOLLOWUP_VERIFICATION" if from_status == "FOLLOWUP_PENDING"
                else "INITIAL_VERIFICATION")
    if technician_id == attempt["technician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VERIFICATION")
    if sequence == "FOLLOWUP_VERIFICATION":
        for existing in deadlines.event_attempts(event["id"]):
            if existing["technician_id"] == technician_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES_VERIFICATION")

    if attempt["leak_event_id"] != event["id"]:
        raise ApiError("ERR_LEAK_EVENT_SYSTEM_MISMATCH")
    current = deadlines.current_attempt(event)
    if current is None or current["id"] != attempt["id"]:
        raise ApiError("ERR_REPAIR_ATTEMPT_NOT_CURRENT")
    guards.require_not_after_clock(performed_at)
    if performed_at < attempt["repair_completed_at"]:
        raise invalid("performed_at must not precede the attempt's repair_completed_at")

    clock = db.now()
    system = db.require("systems", event["system_id"])
    was_late = deadlines.is_overdue(event["verification_deadline"], performed_at)
    if from_status == "VERIFICATION_OVERDUE":
        was_late = True

    test = db.new_entity(versioned=False)
    test.update({
        "leak_event_id": event["id"],
        "repair_attempt_id": attempt["id"],
        "technician_id": technician_id,
        "test_method_code": test_method_code,
        "performed_at": performed_at,
        "result": result,
        "measured_leak_rate_pct": measured_leak_rate_pct,
        "test_sequence": sequence,
        "was_late": was_late,
    })
    db.insert("verification_tests", test)

    event_snap = db.snapshot(event)
    system_touched = False
    rebase_leak_rate = False

    if result == "PASS":
        if sequence == "INITIAL_VERIFICATION":
            attempt["outcome"] = "VERIFIED"
            event["status"] = "FOLLOWUP_PENDING"
            event["verification_deadline"] = util.add_days(
                performed_at, constants.VERIFICATION_WINDOW_DAYS)
        else:
            awaiting = [a for a in deadlines.event_attempts(event["id"])
                        if a["outcome"] == "AWAITING_VERIFICATION"]
            if awaiting:
                awaiting[-1]["outcome"] = "VERIFIED"
            else:
                attempt["outcome"] = "VERIFIED"
            event["status"] = "VERIFIED_CLOSED"
            event["closed_at"] = clock
            _close_linked_records(event, clock)
            system_touched = True
            rebase_leak_rate = True
    else:
        event["failed_verification_count"] = event["failed_verification_count"] + 1
        attempt["outcome"] = "FAILED_VERIFICATION"
        if event["failed_verification_count"] < constants.MAX_FAILED_VERIFICATIONS:
            event["status"] = "VERIFICATION_FAILED"
        else:
            event["status"] = "RETROFIT_MANDATED"
            system_touched = True

    db.commit(event, event_snap)

    if system_touched:
        if rebase_leak_rate:
            ledger.recompute_leak_rate(system)
        posture.system_cascade(system)
    else:
        posture.recompute_store_by_id(system["store_id"])
    return response.created(test)


@bp.get("/verification-tests")
@read_endpoint
def list_verification_tests():
    filters = {
        "leak_event_id": request.args.get("leak_event_id"),
        "repair_attempt_id": request.args.get("repair_attempt_id"),
        "technician_id": request.args.get("technician_id"),
        "result": request.args.get("result"),
        "test_sequence": request.args.get("test_sequence"),
    }
    return response.listing(db.values("verification_tests"), filters)


@bp.get("/verification-tests/<test_id>")
@read_endpoint
def get_verification_test(test_id):
    return response.ok(db.require("verification_tests", test_id))
