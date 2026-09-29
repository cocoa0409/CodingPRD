"""Dispositions: the advice itself, its charge-nurse override and its
outcome audit. The row carries two independent state dimensions.
"""
from flask import Blueprint

import lookups
from auth import (ALL_ROLES, CHARGE_NURSE, COMPLIANCE_AUDITOR, PLATFORM_ADMIN,
                  PRACTICE_LIAISON, TRIAGE_NURSE, acting_role, acting_user,
                  authorize)
from calc import (callback_requirement, disposition_recommendation,
                  nurse_has_active_license, outcome_variance_classification)
from cascades import (add_high_risk, cancel_open_tasks, create_callback_task,
                      escalate_variance, release_high_risk, tasks_of_disposition)
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import audit_record_json, disposition_json
from store import base_record, ordered, store, touch
from util import (DISPOSITION_LEVELS, LEVEL_ORDINAL, OUTCOME_SOURCES,
                  OVERRIDE_REASON_CODES, REPORTED_OUTCOMES)
from validators import (body, get_enum, get_int, get_string, get_timestamp,
                        query_enum, query_string)

bp = Blueprint("dispositions", __name__)

ADVICE_STATUSES = ("AUTHORIZED", "OVERRIDDEN", "VOIDED")
AUDIT_STATUSES = ("AWAITING_OUTCOME", "OUTCOME_RECORDED", "CONCORDANT_CLOSED",
                  "VARIANCE_ESCALATED")
OPEN_TASK_STATUSES = ("PENDING", "ATTEMPTED", "REACHED")
NARRATIVE_MIN_CHARS = 40
OVERRIDE_MAX_STEPS = 1


def _override_documentation(data):
    """The override documentation pair. A malformed value is priority 3, but an
    ABSENT or too-short one is priority 27 — a clinical documentation failure
    rather than a schema failure."""
    code = data.get("override_reason_code")
    narrative = data.get("override_narrative")
    if code is not None and (not isinstance(code, str)
                             or code not in OVERRIDE_REASON_CODES):
        raise ApiError("ERR_INVALID_REQUEST", "override_reason_code is invalid.")
    if narrative is not None and not isinstance(narrative, str):
        raise ApiError("ERR_INVALID_REQUEST", "override_narrative must be a string.")
    return code, narrative


def _documentation_is_complete(code, narrative):
    return bool(code) and narrative is not None and len(narrative) >= NARRATIVE_MIN_CHARS


@bp.route("/dispositions", methods=["POST"])
@authorize([TRIAGE_NURSE])
def create_disposition():
    data = body()
    call_id = get_string(data, "call_id")
    assessment_id = get_string(data, "assessment_id")
    final_level = get_enum(data, "final_level", DISPOSITION_LEVELS)
    expected_version = get_int(data, "expected_call_version", minimum=0)
    reason_code, narrative = _override_documentation(data)

    call = lookups.call(call_id)
    assessment = lookups.assessment(assessment_id)
    if acting_role() == TRIAGE_NURSE and call["assigned_nurse_id"] != acting_user():
        raise ApiError("ERR_NOT_ASSIGNED_NURSE")
    if call["status"] != "ASSESSING":
        raise ApiError("ERR_CALL_INVALID_STATE")
    if assessment["status"] == "SUPERSEDED":
        raise ApiError("ERR_ASSESSMENT_SUPERSEDED")
    if expected_version != call["version"]:
        raise ApiError("ERR_STALE_CALL_VERSION")
    if not nurse_has_active_license(acting_user(), call["caller_state_code"]):
        raise ApiError("ERR_NURSE_NOT_LICENSED_IN_STATE")

    protocol = store.protocols.get(assessment["protocol_id"])
    recommended = disposition_recommendation(assessment, protocol, call)

    if final_level != recommended and not _documentation_is_complete(reason_code, narrative):
        raise ApiError("ERR_OVERRIDE_DOCUMENTATION_REQUIRED")
    if LEVEL_ORDINAL[final_level] < LEVEL_ORDINAL[recommended]:
        raise ApiError("ERR_DEESCALATION_REQUIRES_CHARGE_NURSE")
    if assessment["call_id"] != call_id:
        raise ApiError("ERR_ASSESSMENT_CALL_MISMATCH")

    is_override = final_level != recommended
    practice = store.practices.get(call["practice_id"])
    record = base_record()
    requirement = callback_requirement(final_level, call, practice, record["created_at"])
    record.update({
        "call_id": call_id,
        "assessment_id": assessment_id,
        "determined_by_nurse_id": acting_user(),
        "overridden_by_nurse_id": None,
        "recommended_level": recommended,
        "final_level": final_level,
        "is_override": is_override,
        "override_reason_code": reason_code if is_override else None,
        "override_narrative": narrative if is_override else None,
        "requires_callback": requirement["requires_callback"],
        "advice_status": "AUTHORIZED",
        "audit_status": "AWAITING_OUTCOME",
        "callback_verified_at": None,
    })
    store.dispositions[record["id"]] = record

    if requirement["requires_callback"]:
        create_callback_task(record, call, requirement)

    if final_level == "EMERGENCY_911":
        # HOP 1 -> 3: the call needs a warm transfer, which consumes one of the
        # nurse's high-risk slots and can pull them off rotation entirely.
        call["requires_warm_transfer"] = True
        nurse = store.nurses.get(record["determined_by_nurse_id"])
        if nurse is not None:
            add_high_risk(nurse)

    call["status"] = "DISPOSITIONED"
    touch(call)
    return object_response(disposition_json(record), 201)


@bp.route("/dispositions/<disposition_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_disposition(disposition_id):
    return object_response(disposition_json(lookups.disposition(disposition_id)))


@bp.route("/dispositions", methods=["GET"])
@authorize(ALL_ROLES)
def list_dispositions():
    limit, offset = pagination_params()
    call_id = query_string("call_id")
    assessment_id = query_string("assessment_id")
    determined_by = query_string("determined_by_nurse_id")
    overridden_by = query_string("overridden_by_nurse_id")
    advice_status = query_enum("advice_status", ADVICE_STATUSES)
    audit_status = query_enum("audit_status", AUDIT_STATUSES)
    rows = ordered(store.dispositions)
    if call_id is not None:
        rows = [d for d in rows if d["call_id"] == call_id]
    if assessment_id is not None:
        rows = [d for d in rows if d["assessment_id"] == assessment_id]
    if determined_by is not None:
        rows = [d for d in rows if d["determined_by_nurse_id"] == determined_by]
    if overridden_by is not None:
        rows = [d for d in rows if d["overridden_by_nurse_id"] == overridden_by]
    if advice_status is not None:
        rows = [d for d in rows if d["advice_status"] == advice_status]
    if audit_status is not None:
        rows = [d for d in rows if d["audit_status"] == audit_status]
    return list_response(rows, disposition_json, limit, offset)


@bp.route("/dispositions/<disposition_id>/override", methods=["POST"])
@authorize([CHARGE_NURSE])
def override_disposition(disposition_id):
    data = body()
    new_level = get_enum(data, "final_level", DISPOSITION_LEVELS)
    reason_code, narrative = _override_documentation(data)

    disposition = lookups.disposition(disposition_id)
    if disposition["advice_status"] != "AUTHORIZED":
        raise ApiError("ERR_DISPOSITION_INVALID_STATE")
    call = store.calls.get(disposition["call_id"])
    if call is None:
        raise ApiError("ERR_TRIAGE_CALL_NOT_FOUND")
    if call["status"] != "DISPOSITIONED":
        raise ApiError("ERR_CALL_INVALID_STATE")
    if not nurse_has_active_license(acting_user(), call["caller_state_code"]):
        raise ApiError("ERR_NURSE_NOT_LICENSED_IN_STATE")
    if not _documentation_is_complete(reason_code, narrative):
        raise ApiError("ERR_OVERRIDE_DOCUMENTATION_REQUIRED")
    if disposition["recommended_level"] == "EMERGENCY_911" and new_level != "EMERGENCY_911":
        raise ApiError("ERR_EMERGENCY_DEESCALATION_FORBIDDEN")
    previous_level = disposition["final_level"]
    if abs(LEVEL_ORDINAL[new_level] - LEVEL_ORDINAL[previous_level]) > OVERRIDE_MAX_STEPS:
        raise ApiError("ERR_OVERRIDE_STEP_LIMIT")
    if acting_user() == disposition["determined_by_nurse_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    practice = store.practices.get(call["practice_id"])
    disposition["final_level"] = new_level
    disposition["is_override"] = True
    disposition["override_reason_code"] = reason_code
    disposition["override_narrative"] = narrative
    disposition["overridden_by_nurse_id"] = acting_user()
    disposition["advice_status"] = "OVERRIDDEN"

    requirement = callback_requirement(new_level, call, practice, store.clock)
    disposition["requires_callback"] = requirement["requires_callback"]
    touch(disposition)

    live_tasks = [t for t in tasks_of_disposition(disposition_id)
                  if t["status"] in OPEN_TASK_STATUSES]
    softened = LEVEL_ORDINAL[new_level] < LEVEL_ORDINAL[previous_level]
    if not requirement["requires_callback"]:
        cancel_open_tasks(disposition)
    elif live_tasks and softened:
        cancel_open_tasks(disposition)
        create_callback_task(disposition, call, requirement)
    elif not live_tasks:
        create_callback_task(disposition, call, requirement)

    nurse = store.nurses.get(disposition["determined_by_nurse_id"])
    if previous_level == "EMERGENCY_911" and new_level != "EMERGENCY_911":
        call["requires_warm_transfer"] = False
        if nurse is not None:
            release_high_risk(nurse)
    elif new_level == "EMERGENCY_911" and previous_level != "EMERGENCY_911":
        call["requires_warm_transfer"] = True
        if nurse is not None:
            add_high_risk(nurse)

    touch(call)
    return object_response(disposition_json(disposition))


@bp.route("/dispositions/<disposition_id>/audit-records", methods=["POST"])
@authorize([COMPLIANCE_AUDITOR])
def create_audit_record(disposition_id):
    data = body()
    reported_outcome = get_enum(data, "reported_outcome", REPORTED_OUTCOMES)
    outcome_source = get_enum(data, "outcome_source", OUTCOME_SOURCES)
    observed_at = get_timestamp(data, "outcome_observed_at")

    disposition = lookups.disposition(disposition_id)
    existing = [r for r in ordered(store.audit_records)
                if r["disposition_id"] == disposition_id]
    # Priority 19, with the carve-out: once a record exists the request is an
    # already-recorded outcome (49) rather than a bad state.
    if disposition["advice_status"] == "VOIDED":
        raise ApiError("ERR_DISPOSITION_INVALID_STATE")
    if disposition["audit_status"] != "AWAITING_OUTCOME" and not existing:
        raise ApiError("ERR_DISPOSITION_INVALID_STATE")
    if disposition["requires_callback"]:
        open_tasks = [t for t in tasks_of_disposition(disposition_id)
                      if t["status"] in OPEN_TASK_STATUSES]
        if open_tasks:
            raise ApiError("ERR_CALLBACK_NOT_RESOLVED")
    if observed_at < disposition["created_at"]:
        raise ApiError("ERR_OUTCOME_PREDATES_DISPOSITION")
    if existing:
        raise ApiError("ERR_OUTCOME_ALREADY_RECORDED")

    classification = outcome_variance_classification(reported_outcome,
                                                     disposition["final_level"])
    record = base_record(with_version=False)
    record.update({
        "disposition_id": disposition_id,
        "auditor_user_id": acting_user(),
        "reported_outcome": reported_outcome,
        "outcome_source": outcome_source,
        "outcome_observed_at": observed_at,
    })
    record.update(classification)
    store.audit_records[record["id"]] = record

    disposition["audit_status"] = "OUTCOME_RECORDED"
    if classification["variance_class"] == "CONCORDANT":
        disposition["audit_status"] = "CONCORDANT_CLOSED"
        touch(disposition)
    elif classification["variance_class"] == "UNDERTRIAGE":
        escalate_variance(disposition)
    else:
        touch(disposition)
    return object_response(audit_record_json(record), 201)


@bp.route("/dispositions/<disposition_id>/audit-records", methods=["GET"])
@authorize([PLATFORM_ADMIN, COMPLIANCE_AUDITOR, PRACTICE_LIAISON])
def list_audit_records(disposition_id):
    limit, offset = pagination_params()
    lookups.disposition(disposition_id)
    rows = [r for r in ordered(store.audit_records)
            if r["disposition_id"] == disposition_id]
    return list_response(rows, audit_record_json, limit, offset)
