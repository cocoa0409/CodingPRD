"""Pathology: the chain of custody, the result cascade and the notification loop."""

from flask import Blueprint, g

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import calc, cascades, query, serialize

bp = Blueprint("specimens", __name__)


def _specimen(specimen_id):
    row = store.get("specimens", specimen_id)
    if row is None:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND")
    return row


@bp.route("/specimens", methods=["POST"])
@authenticate([constants.ROLE_UROLOGIST, constants.ROLE_PROCEDURE_NURSE])
def collect_specimen():
    body = validate.get_body()
    case_id = validate.str_field(body, "case_id")
    collected_by_provider_id = validate.str_field(body, "collected_by_provider_id")
    container_label = validate.str_field(body, "container_label")
    specimen_type = validate.enum_field(body, "specimen_type", constants.SPECIMEN_TYPES)
    site_code = validate.str_field(body, "site_code")

    # Priority 10.
    case = store.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    if store.get("providers", collected_by_provider_id) is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    # Priority 14.
    if collected_by_provider_id != g.user_id:
        raise ApiError("ERR_ACTOR_IDENTITY_MISMATCH")
    # Priority 18 — unique within a single case_id only.
    for row in store.all_rows("specimens"):
        if row["case_id"] == case_id and row["container_label"] == container_label:
            raise ApiError("ERR_DUPLICATE_CONTAINER_LABEL")
    # Priority 63.
    ptype = store.get("procedure_types", case["procedure_type_id"])
    if ptype is None or not ptype["requires_specimen"]:
        raise ApiError("ERR_SPECIMEN_NOT_EXPECTED")
    if case["schedule_status"] not in ("IN_ROOM", "COMPLETED"):
        raise ApiError("ERR_SPECIMEN_NOT_EXPECTED")

    row = db.new_row(
        "specimens",
        {
            "case_id": case_id,
            "collected_by_provider_id": collected_by_provider_id,
            "container_label": container_label,
            "specimen_type": specimen_type,
            "site_code": site_code,
            "collected_at": store.now(),
            "accession_number": None,
            "received_at": None,
            "condition_on_receipt": None,
            "chain_status": "COLLECTED",
            "pathology_result": None,
            "result_at": None,
            "notification_status": "NOT_REQUIRED",
            "notification_attempt_count": 0,
            "escalation_due_at": None,
            "_notification_anchor_at": None,
        },
    )
    return response.created_response(serialize.dump("specimens", row))


@bp.route("/specimens/<specimen_id>/accession", methods=["POST"])
@authenticate([constants.ROLE_PATHOLOGY_LIAISON])
def accession_specimen(specimen_id):
    body = validate.get_body()
    accession_number = validate.str_field(body, "accession_number")
    received_at = validate.instant_field(body, "received_at")
    condition_on_receipt = validate.enum_field(
        body, "condition_on_receipt", constants.RECEIPT_CONDITIONS
    )
    specimen = _specimen(specimen_id)

    # Priority 22.
    if specimen["chain_status"] != "COLLECTED":
        raise ApiError("ERR_INVALID_SPECIMEN_TRANSITION")
    # Priority 62 — not earlier than collection and no more than 24 hours after it.
    collected_at = specimen["collected_at"]
    latest = util.add_hours(collected_at, constants.SPECIMEN_TRANSIT_HOURS)
    if received_at < collected_at or received_at > latest:
        raise ApiError("ERR_SPECIMEN_TRANSIT_EXPIRED")

    # Both branches record the same three fields.
    specimen["accession_number"] = accession_number
    specimen["received_at"] = received_at
    specimen["condition_on_receipt"] = condition_on_receipt

    if condition_on_receipt == "INTACT":
        specimen["chain_status"] = "ACCESSIONED"
        db.touch(specimen)
        return response.object_response(serialize.dump("specimens", specimen))

    # A compromised container: rejected, and the notification dimension opens.
    now = store.now()
    specimen["chain_status"] = "REJECTED"
    specimen["notification_status"] = "PENDING"
    specimen["_notification_anchor_at"] = now
    calc.recompute_escalation(specimen)
    db.touch(specimen)

    case = store.get("cases", specimen["case_id"])
    patient = store.get("patients", case["patient_id"]) if case is not None else None
    ptype = store.get("procedure_types", case["procedure_type_id"]) if case is not None else None
    # open_notification_count is recomputed for the patient.
    if patient is not None:
        db.touch_once(patient)
        # A ruined prostate core still has to be re-taken.
        if ptype is not None and ptype["code"] == "PROSTATE_BIOPSY":
            cascades.open_recall(patient, "PROSTATE", "INTERMEDIATE", now.date(), specimen["id"])
    return response.object_response(serialize.dump("specimens", specimen))


@bp.route("/specimens/<specimen_id>/result", methods=["POST"])
@authenticate([constants.ROLE_PATHOLOGY_LIAISON])
def result_specimen(specimen_id):
    body = validate.get_body()
    pathology_result = validate.enum_field(body, "pathology_result", constants.PATHOLOGY_RESULTS)
    specimen = _specimen(specimen_id)

    # Priority 22.
    if specimen["chain_status"] != "ACCESSIONED":
        raise ApiError("ERR_INVALID_SPECIMEN_TRANSITION")

    now = store.now()
    # Hop 1 — the result lands on the specimen.
    specimen["pathology_result"] = pathology_result
    specimen["result_at"] = now
    specimen["chain_status"] = "RESULTED"
    specimen["notification_status"] = "PENDING"
    calc.recompute_escalation(specimen)
    db.touch(specimen)

    # Hop 2 — a graded result opens a recall; INSUFFICIENT stops the cascade here.
    if pathology_result in constants.GRADE_TO_RISK_TIER:
        case = store.get("cases", specimen["case_id"])
        patient = store.get("patients", case["patient_id"]) if case is not None else None
        if patient is not None:
            protocol = constants.SPECIMEN_TYPE_TO_PROTOCOL[specimen["specimen_type"]]
            risk_tier = constants.GRADE_TO_RISK_TIER[pathology_result]
            # Hops 3 and 4 run inside open_recall.
            cascades.open_recall(patient, protocol, risk_tier, now.date(), specimen["id"])
    return response.object_response(serialize.dump("specimens", specimen))


@bp.route("/specimens/<specimen_id>/notification-attempt", methods=["POST"])
@authenticate([constants.ROLE_PATHOLOGY_LIAISON, constants.ROLE_PROCEDURE_NURSE])
def notification_attempt(specimen_id):
    body = validate.get_body()
    outcome = validate.enum_field(body, "outcome", constants.NOTIFICATION_OUTCOMES)
    validate.str_field(body, "channel")
    specimen = _specimen(specimen_id)

    # Priority 22 — the notification dimension's own transition code.
    if specimen["notification_status"] not in ("PENDING", "ATTEMPTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_NOTIFICATION_TRANSITION")

    # Either outcome counts the attempt.
    specimen["notification_attempt_count"] += 1
    left_open_set = False
    if outcome == "REACHED":
        specimen["notification_status"] = "ACKNOWLEDGED"
        left_open_set = True
    elif specimen["notification_attempt_count"] >= constants.NOTIFICATION_MAX_ATTEMPTS:
        specimen["notification_status"] = "FAILED"
        calc.recompute_escalation(specimen)
        left_open_set = True
    else:
        specimen["notification_status"] = "ATTEMPTED"
        calc.recompute_escalation(specimen)
    db.touch(specimen)

    if left_open_set:
        case = store.get("cases", specimen["case_id"])
        patient = store.get("patients", case["patient_id"]) if case is not None else None
        if patient is not None:
            db.touch_once(patient)
    return response.object_response(serialize.dump("specimens", specimen))


@bp.route("/specimens/<specimen_id>", methods=["GET"])
@authenticate(ALL)
def get_specimen(specimen_id):
    return response.object_response(serialize.dump("specimens", _specimen(specimen_id)))


@bp.route("/specimens", methods=["GET"])
@authenticate(ALL)
def list_specimens():
    return query.collection(
        "specimens",
        {
            "case_id": validate.query_str("case_id"),
            "collected_by_provider_id": validate.query_str("collected_by_provider_id"),
            "chain_status": validate.query_enum("chain_status", constants.CHAIN_STATUSES),
            "notification_status": validate.query_enum(
                "notification_status", constants.NOTIFICATION_STATUSES
            ),
            "specimen_type": validate.query_enum("specimen_type", constants.SPECIMEN_TYPES),
        },
    )
