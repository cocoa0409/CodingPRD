"""Knowledge test endpoints (PRD section 3.3)."""
from flask import Blueprint

import db
from db import db as store
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services import calculations as calc
from services.common import (
    new_common, touch, get_json_body, require_fields, require_int,
)
from services.lookup import fetch

bp = Blueprint("knowledge_tests", __name__)


@bp.post("/knowledge-tests")
def schedule_knowledge_test():
    _, role = get_user_context()
    require_role(role, {"KnowledgeProctor", "LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "scheduled_period"])
    driver_record_id = body["driver_record_id"]
    record = fetch(store.driver_records, driver_record_id)
    scheduled_period = require_int(body, "scheduled_period")
    total_questions = 40
    if "total_questions" in body and body["total_questions"] is not None:
        total_questions = require_int(body, "total_questions", minimum=1)
    # field-domain check (priority 3.5): scheduled_period >= current clock.
    if scheduled_period < store.current_period:
        raise err("ERR_SCHEDULED_IN_PAST",
                  "scheduled_period must be at or after the current clock")
    # constraint (priority 11): no other SCHEDULED sitting in same period.
    for t in store.knowledge_tests.values():
        if (t["driver_record_id"] == driver_record_id and t["status"] == "SCHEDULED"
                and t["scheduled_period"] == scheduled_period):
            raise err("ERR_KNOWLEDGE_SITTING_CONFLICT",
                      "Another SCHEDULED sitting exists in this period")
    test = new_common(
        driver_record_id=driver_record_id,
        scheduled_period=scheduled_period,
        total_questions=total_questions,
        correct_answers=None,
        score_pct=None,
        status="SCHEDULED",
        graded_period=None,
    )
    store.knowledge_tests[test["id"]] = test
    return success(serialize.knowledge_test(test), 201, "object")


@bp.post("/knowledge-tests/<tid>/grade")
def grade_knowledge_test(tid):
    _, role = get_user_context()
    require_role(role, {"KnowledgeProctor"})
    test = fetch(store.knowledge_tests, tid)
    body = get_json_body()
    require_fields(body, ["correct_answers"])
    correct = require_int(body, "correct_answers", minimum=0)
    if correct > test["total_questions"]:
        raise err("ERR_INVALID_REQUEST",
                  "correct_answers may not exceed total_questions")
    # state (priority 5)
    if test["status"] != "SCHEDULED":
        raise err("ERR_TEST_NOT_SCHEDULED", "Test is not SCHEDULED")
    # temporal business check
    if store.current_period < test["scheduled_period"]:
        raise err("ERR_TEST_NOT_YET_DUE", "current clock < scheduled_period")
    pct = calc.score_pct(correct, test["total_questions"])
    test["correct_answers"] = correct
    test["score_pct"] = pct
    if pct >= db.KNOWLEDGE_PASS_THRESHOLD:
        test["status"] = "PASSED"
        test["graded_period"] = store.current_period
        touch(test)
        # On first pass in validity window: knowledge_test_passed true;
        # UNLICENSED record -> ELIGIBLE.
        record = store.driver_records.get(test["driver_record_id"])
        if record is not None and record["licensing_status"] == "UNLICENSED":
            record["licensing_status"] = "ELIGIBLE"
            touch(record)
    else:
        test["status"] = "FAILED"
        test["graded_period"] = store.current_period
        touch(test)
    return success(serialize.knowledge_test(test), 200, "object")


@bp.post("/knowledge-tests/<tid>/reschedule")
def reschedule_knowledge_test(tid):
    _, role = get_user_context()
    require_role(role, {"KnowledgeProctor"})
    test = fetch(store.knowledge_tests, tid)
    body = get_json_body()
    require_fields(body, ["scheduled_period"])
    new_period = require_int(body, "scheduled_period")
    # state (priority 5)
    if test["status"] != "FAILED":
        raise err("ERR_TEST_NOT_FAILED", "Reschedule requires a FAILED test")
    # cooldown business check
    if new_period < store.current_period + db.KNOWLEDGE_RETAKE_COOLDOWN:
        raise err("ERR_RETAKE_COOLDOWN",
                  "New scheduled_period earlier than current clock + cooldown")
    test["scheduled_period"] = new_period
    test["status"] = "SCHEDULED"
    test["correct_answers"] = None
    test["score_pct"] = None
    test["graded_period"] = None
    touch(test)
    return success(serialize.knowledge_test(test), 200, "object")
