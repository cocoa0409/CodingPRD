"""Surveillance recalls and the three-step recall sweep."""

from flask import Blueprint

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import calc, cascades, query, serialize

bp = Blueprint("recalls", __name__)


def _recall(recall_id):
    row = store.get("recalls", recall_id)
    if row is None:
        raise ApiError("ERR_RECALL_NOT_FOUND")
    return row


@bp.route("/surveillance-recalls", methods=["POST"])
@authenticate([constants.ROLE_UROLOGIST])
def create_recall():
    body = validate.get_body()
    patient_id = validate.str_field(body, "patient_id")
    protocol = validate.enum_field(body, "protocol", constants.RECALL_PROTOCOLS)
    risk_tier = validate.enum_field(body, "risk_tier", constants.RISK_TIERS)
    anchor_date = validate.date_field(body, "anchor_date")
    source_specimen_id = validate.str_field(body, "source_specimen_id", required=False, default=None)
    expected_patient_version = validate.int_field(body, "expected_patient_version")

    # Priority 10.
    patient = store.get("patients", patient_id)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    specimen = None
    if source_specimen_id is not None:
        specimen = store.get("specimens", source_specimen_id)
        if specimen is None:
            raise ApiError("ERR_SPECIMEN_NOT_FOUND")
    # Priority 26 — a specimen still in transit or already rejected cannot motivate a recall.
    if specimen is not None and specimen["chain_status"] != "RESULTED":
        raise ApiError("ERR_SOURCE_CASE_NOT_COMPLETED")
    # Priority 30.
    if expected_patient_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")

    row = cascades.open_recall(patient, protocol, risk_tier, anchor_date, source_specimen_id)
    return response.created_response(serialize.dump("recalls", row))


@bp.route("/surveillance-recalls/<recall_id>/close", methods=["POST"])
@authenticate([constants.ROLE_UROLOGIST])
def close_recall(recall_id):
    body = validate.get_body()
    closed_reason = validate.str_field(body, "closed_reason")
    recall = _recall(recall_id)

    # Priority 22 — SATISFIED, SUPERSEDED and CLOSED are all terminal.
    if recall["status"] not in ("SCHEDULED_DUE", "OVERDUE"):
        raise ApiError("ERR_INVALID_RECALL_TRANSITION")

    recall["status"] = "CLOSED"
    recall["closed_reason"] = closed_reason
    db.touch(recall)
    patient = store.get("patients", recall["patient_id"])
    if patient is not None:
        db.touch_once(patient)
    return response.object_response(serialize.dump("recalls", recall))


@bp.route("/recall-sweeps", methods=["POST"])
@authenticate([constants.ROLE_PRACTICE_ADMIN, constants.ROLE_UROLOGIST])
def recall_sweep():
    swept_at = store.now()
    clock_date = swept_at.date()
    dirty = set()
    recomputed = 0
    overdue = 0
    restored = 0
    escalated = 0

    open_recalls = [
        row
        for row in store.all_rows("recalls")
        if row["status"] in ("SCHEDULED_DUE", "OVERDUE")
    ]

    # Step 1 — recompute due_on under the EVENT_ANCHORED variant.
    for recall in open_recalls:
        due_on, due_basis = calc.event_anchored_due_on(recall)
        recomputed += 1
        if recall["due_on"] != due_on or recall["due_basis"] != due_basis:
            recall["due_on"] = due_on
            recall["due_basis"] = due_basis
            dirty.add(recall["id"])

    # Step 2 — reconcile status against the freshly recomputed dates.
    for recall in open_recalls:
        if recall["status"] == "SCHEDULED_DUE" and recall["due_on"] < clock_date:
            recall["status"] = "OVERDUE"
            recall["lapse_days"] = calc.lapse_days_for(recall["due_on"], clock_date)
            dirty.add(recall["id"])
            overdue += 1
        elif recall["status"] == "OVERDUE" and recall["due_on"] >= clock_date:
            recall["status"] = "SCHEDULED_DUE"
            recall["lapse_days"] = 0
            dirty.add(recall["id"])
            restored += 1

    for recall in open_recalls:
        if recall["id"] in dirty:
            db.touch(recall)

    # Step 3 — the notification queue. Escalation is a flag, not an attempt.
    for specimen in store.all_rows("specimens"):
        if specimen["notification_status"] not in ("PENDING", "ATTEMPTED"):
            continue
        due = specimen["escalation_due_at"]
        if due is not None and due < swept_at:
            specimen["notification_status"] = "ESCALATED"
            db.touch(specimen)
            escalated += 1

    return response.object_response(
        {
            "swept_at": util.format_instant(swept_at),
            "recomputed_recall_count": recomputed,
            "overdue_recall_count": overdue,
            "restored_recall_count": restored,
            "escalated_specimen_count": escalated,
        }
    )


@bp.route("/surveillance-recalls/<recall_id>", methods=["GET"])
@authenticate(ALL)
def get_recall(recall_id):
    return response.object_response(serialize.dump("recalls", _recall(recall_id)))


@bp.route("/surveillance-recalls", methods=["GET"])
@authenticate(ALL)
def list_recalls():
    return query.collection(
        "recalls",
        {
            "patient_id": validate.query_str("patient_id"),
            "predecessor_recall_id": validate.query_str("predecessor_recall_id"),
            "source_specimen_id": validate.query_str("source_specimen_id"),
            "satisfying_case_id": validate.query_str("satisfying_case_id"),
            "protocol": validate.query_enum("protocol", constants.RECALL_PROTOCOLS),
            "status": validate.query_enum("status", constants.RECALL_STATUSES),
            "due_basis": validate.query_enum("due_basis", constants.DUE_BASES),
        },
    )
