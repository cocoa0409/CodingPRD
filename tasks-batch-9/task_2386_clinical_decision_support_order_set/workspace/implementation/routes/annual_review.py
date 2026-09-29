"""The annual review cycle and sponsor attestation (PRD §3.9)."""
from flask import Blueprint, request

import const
import validate
from common import add_days, now, touch
from db import db
from errors import ApiError
from middleware import authenticate, caller_id, get_task
from response import ok, paginate
from services import domain

bp = Blueprint("annual_review", __name__)


def _governed_artifact(task):
    if task["artifact_kind"] == "ORDER_SET":
        return db.order_sets.get(task.get("order_set_id"))
    return db.alerts.get(task.get("alert_id"))


@bp.get("/cds/annual-review-tasks")
def list_tasks():
    authenticate(const.ANY_ROLE)
    records = list(db.annual_review_tasks.values())
    for field in ("order_set_id", "alert_id", "attested_by_clinician_id", "artifact_kind", "state"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    stale = validate.query_bool("stale_content_triggered")
    if stale is not None:
        records = [r for r in records if r["stale_content_triggered"] is stale]
    cycle_index = validate.query_int("cycle_index")
    if cycle_index is not None:
        records = [r for r in records if r["cycle_index"] == cycle_index]
    return paginate(records)


@bp.get("/cds/annual-review-tasks/<cid>")
def read_task(cid):
    authenticate(const.ANY_ROLE)
    return ok(get_task(cid))


@bp.post("/cds/annual-review-tasks/<cid>/attest")
def attest(cid):
    authenticate(("ClinicalSponsor",))
    task = get_task(cid)

    artifact = _governed_artifact(task)
    content_request = (
        db.content_requests.get(artifact["content_request_id"]) if artifact is not None else None
    )
    sponsor_id = content_request["clinical_sponsor_id"] if content_request is not None else None
    if sponsor_id != caller_id():
        raise ApiError(
            "ERR_ROLE_IDENTITY_MISMATCH",
            "Only the sponsor of the governing content request may attest",
        )

    data = validate.body()
    citations = validate.citations(data, "evidence_citations", required=True, allow_empty=True)
    note = validate.string(data, "attestation_note")

    if task["state"] not in ("PENDING", "OVERDUE"):
        raise ApiError("ERR_REVIEW_TASK_NOT_OPEN", "Annual review task is terminal")

    if len(citations) == 0:
        raise ApiError("ERR_EVIDENCE_INSUFFICIENT", "At least one evidence citation is required")

    is_order_set = task["artifact_kind"] == "ORDER_SET"
    risk_class = (
        artifact["risk_class"] if is_order_set else domain.alert_risk_class(artifact)
    )
    anchor = now()
    due = add_days(anchor, domain.review_interval_days(risk_class))
    expiration = add_days(due, const.GRACE_PERIOD_DAYS)
    archive = add_days(expiration, const.ARCHIVE_AFTER_EXPIRY_DAYS) if is_order_set else None

    task["state"] = "ATTESTED"
    task["attested_at"] = anchor
    task["attestation_note"] = note
    task["attested_by_clinician_id"] = caller_id()
    task["evidence_citations"] = citations
    touch(task)

    if is_order_set:
        domain.apply_schedule_to_order_set(artifact, due, expiration, archive)
        if artifact["publication_state"] == "EXPIRING":
            artifact["publication_state"] = "PUBLISHED"
    else:
        domain.apply_schedule_to_alert(artifact, due, expiration)
    touch(artifact)

    domain.create_annual_task(
        task["artifact_kind"], artifact, due, expiration, archive,
        cycle_index=task["cycle_index"] + 1,
    )

    return ok(task)
