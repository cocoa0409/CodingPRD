"""Data-call production, disposition and bulk file review (PRD §3.4, §3.5)."""

from flask import Blueprint

import validation as v
from db import day_diff, now_iso, today_str, touch
from errors import ApiError, invalid
from middleware import (
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_INSURER_RESPONDENT,
    authorize,
)
from response import paginated, success
from routes.common import filter_equals, str_query
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import calculations as calc
from services import derive, serialize, transitions
from services.guards import ensure_exam_subject, ensure_exam_writable, get_call

bp = Blueprint("data_calls", __name__)

DISPOSITIONS = ("ACCEPTED", "REJECTED")
SEVERITIES = ("NONE", "MINOR", "MATERIAL")


def parse_review_fields(payload, label="the review"):
    """error_severity / underpaid_amount_cents / days_to_pay, shared by both reviews."""
    severity = v.get_enum(payload, "error_severity", SEVERITIES)
    underpaid = v.get_int(
        payload, "underpaid_amount_cents", required=False, default=0, minimum=0
    )
    days_to_pay = v.get_int(payload, "days_to_pay", required=False, default=0, minimum=0)
    if severity == "NONE" and underpaid != 0:
        raise invalid(
            "underpaid_amount_cents must be 0 when error_severity is NONE (%s)." % label
        )
    return severity, underpaid, days_to_pay


@bp.get("/data-calls/<call_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_data_call(call_id):
    call = get_call(call_id)
    ensure_exam_subject(derive.exam_of_call(call))
    return success(serialize.data_call(call))


@bp.post("/data-calls/<call_id>/respond")
@authorize(ROLE_INSURER_RESPONDENT)
def respond_data_call(call_id):
    call = get_call(call_id)
    exam = ensure_exam_subject(derive.exam_of_call(call))
    payload = v.body()
    records_received = v.get_int(payload, "records_received", minimum=0)
    submitted_by_contact = v.get_str(payload, "submitted_by_contact", min_len=1)

    ensure_exam_writable(exam)
    if call["status"] not in ("ISSUED", "OVERDUE"):
        raise ApiError(
            "ERR_DATA_CALL_NOT_AWAITING_RESPONSE",
            "The data call is %s and is not awaiting a production." % call["status"],
        )
    if exam is not None and exam["status"] not in ("DATA_CALL", "FIELDWORK"):
        raise ApiError(
            "ERR_DATA_CALL_NOT_AWAITING_RESPONSE",
            "The owning examination is %s and cannot receive a production."
            % exam["status"],
        )
    if records_received > call["records_requested"]:
        raise ApiError(
            "ERR_RECORDS_EXCEED_REQUEST",
            "records_received may not exceed records_requested.",
        )

    response_date = today_str()
    days_late = max(0, day_diff(response_date, call["response_due_date"]))
    completeness, effective = calc.data_call_completeness(
        records_received, call["records_requested"], days_late
    )
    call["records_received"] = records_received
    call["submitted_by_contact"] = submitted_by_contact
    call["responded_at"] = now_iso()
    call["days_late"] = days_late
    call["is_late"] = days_late >= 1
    call["completeness_pct"] = completeness
    call["effective_completeness_pct"] = effective
    call["status"] = "RESPONDED"
    touch(call)
    return success(serialize.data_call(call))


@bp.post("/data-calls/<call_id>/disposition")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def disposition_data_call(call_id):
    call = get_call(call_id)
    exam = derive.exam_of_call(call)
    area = derive.area_of_call(call)
    payload = v.body()
    disposition = v.get_enum(payload, "disposition", DISPOSITIONS)
    disposition_reason = v.get_str(
        payload, "disposition_reason", required=False, min_len=None
    )

    ensure_exam_writable(exam)
    if call["status"] != "RESPONDED":
        raise ApiError(
            "ERR_DATA_CALL_NOT_RESPONDED",
            "Only a RESPONDED data call can be dispositioned; this call is %s."
            % call["status"],
        )
    if (
        disposition == "ACCEPTED"
        and call["effective_completeness_pct"] < calc.ACCEPTANCE_COMPLETENESS_PCT
    ):
        raise ApiError(
            "ERR_RESPONSE_INCOMPLETE",
            "Acceptance requires an effective_completeness_pct of at least 95.00.",
        )

    call["disposition_reason"] = disposition_reason
    if disposition == "ACCEPTED":
        call["status"] = "ACCEPTED"
        transitions.draw_samples(call, area)
        touch(call)
        if area is not None:
            if area["status"] == "PLANNED":
                area["status"] = "FIELDWORK"
            touch(area)
        if exam is not None:
            transitions.exam_first_acceptance(exam)
    else:
        call["status"] = "REJECTED"
        touch(call)
        if area is not None and area["status"] == "FIELDWORK":
            if derive.area_metrics(area)["reviewed_sample_count"] == 0:
                transitions.area_revert_to_planned(area)
    return success(serialize.data_call(call))


@bp.get("/data-calls/<call_id>/file-samples")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_file_samples(call_id):
    call = get_call(call_id)
    ensure_exam_subject(derive.exam_of_call(call))
    rows = derive.file_samples_of_call(call["id"])
    rows = filter_equals(rows, "review_status", str_query("review_status"))
    rows = filter_equals(rows, "error_severity", str_query("error_severity"))
    return paginated(rows, serialize.file_sample)


@bp.post("/data-calls/<call_id>/bulk-review")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def bulk_review(call_id):
    call = get_call(call_id)
    exam = derive.exam_of_call(call)
    area = derive.area_of_call(call)
    payload = v.body()
    entries = _parse_reviews(payload)

    ensure_exam_writable(exam)
    if call["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_DATA_CALL_NOT_RESPONDED",
            "Bulk review requires an ACCEPTED data call; this call is %s."
            % call["status"],
        )

    samples = {s["file_reference"]: s for s in derive.file_samples_of_call(call["id"])}
    applied_count = 0
    skipped_references = []
    for entry in entries:
        sample = samples.get(entry["file_reference"])
        if sample is None or sample["review_status"] != "UNREVIEWED":
            skipped_references.append(entry["file_reference"])
            continue
        transitions.apply_sample_review(
            sample,
            entry["error_severity"],
            entry["underpaid_amount_cents"],
            entry["days_to_pay"],
        )
        applied_count += 1

    if applied_count and area is not None:
        transitions.area_after_review(area)

    metrics = derive.area_metrics(area) if area is not None else {}
    return success(
        {
            "applied_count": applied_count,
            "skipped_count": len(skipped_references),
            "skipped_file_references": skipped_references,
            "scope_area_status": area["status"] if area is not None else None,
            "reviewed_sample_count": metrics.get("reviewed_sample_count", 0),
            "error_count": metrics.get("error_count", 0),
            "error_rate_pct": derive.as_float(metrics.get("error_rate_pct")),
            "material_error_rate_pct": derive.as_float(
                metrics.get("material_error_rate_pct")
            ),
            "tolerance_breached": metrics.get("tolerance_breached", False),
            "escalation_required": metrics.get("escalation_required", False),
        }
    )


def _parse_reviews(payload):
    if not v.present(payload, "reviews"):
        raise invalid("Field reviews is required.")
    raw = payload["reviews"]
    if not isinstance(raw, list) or not raw:
        raise invalid("Field reviews must be a non-empty array.")
    entries = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise invalid("Each reviews entry must be an object.")
        file_reference = v.get_str(item, "file_reference", min_len=1)
        if file_reference in seen:
            raise invalid("reviews contains a duplicate file_reference.")
        seen.add(file_reference)
        severity, underpaid, days_to_pay = parse_review_fields(
            item, "file_reference %s" % file_reference
        )
        entries.append(
            {
                "file_reference": file_reference,
                "error_severity": severity,
                "underpaid_amount_cents": underpaid,
                "days_to_pay": days_to_pay,
            }
        )
    return entries
