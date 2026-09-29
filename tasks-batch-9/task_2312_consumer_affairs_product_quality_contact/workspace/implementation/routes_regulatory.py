"""Regulatory escalation, determination and agency filing."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    ROLE_REGULATORY_OFFICER,
    authorize,
    check_required,
    err,
    get_body,
    must_get,
    now,
    pagination,
    paginated,
    q_bool,
    q_str,
    sort_records,
    store,
    success,
    touch,
    v_enum,
    v_string,
)

bp = Blueprint("regulatory", __name__)

REPORT_KINDS = ("ADVERSE_EVENT", "ILLNESS_CLUSTER", "FOREIGN_MATERIAL_INJURY")
DETERMINATIONS = ("REPORTABLE", "NOT_REPORTABLE")


@bp.post("/regulatory-reports")
def create_report():
    authorize([ROLE_REGULATORY_OFFICER, ROLE_QUALITY_LEAD])
    body = get_body()
    if "complaint_id" in body and body["complaint_id"] is not None:
        must_get("complaints", body["complaint_id"])
    check_required(body, ["complaint_id", "report_kind"])
    complaint_id = v_string(body, "complaint_id", 1)
    report_kind = v_enum(body, "report_kind", REPORT_KINDS)

    complaint = store.complaints[complaint_id]
    if complaint["handling_status"] == "DUPLICATE":
        raise err(
            "ERR_REGULATORY_STATE_INVALID", "a duplicate complaint cannot be escalated"
        )
    if svc.active_report_of_complaint(complaint_id) is not None:
        raise err(
            "ERR_REPORT_ALREADY_OPEN", "a non-withdrawn report already exists for this complaint"
        )
    if complaint["regulatory_status"] != "NOT_APPLICABLE":
        raise err(
            "ERR_REGULATORY_STATE_INVALID",
            "the complaint's regulatory_status does not permit a fresh escalation",
        )

    report = svc.open_regulatory_report(complaint, report_kind)
    return success(ser.regulatory_report(report), 201)


@bp.get("/regulatory-reports")
def list_reports():
    authorize([ROLE_REGULATORY_OFFICER, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    limit, offset = pagination()
    complaint_id = q_str("complaint_id")
    status = q_str("status")
    report_kind = q_str("report_kind")
    submitted_late = q_bool("submitted_late")
    items = []
    for rec in sort_records(list(store.regulatory_reports.values())):
        if complaint_id is not None and rec["complaint_id"] != complaint_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if report_kind is not None and rec["report_kind"] != report_kind:
            continue
        if submitted_late is not None and rec.get("submitted_late") != submitted_late:
            continue
        items.append(ser.regulatory_report(rec))
    return paginated(items, limit, offset)


@bp.get("/regulatory-reports/<record_id>")
def get_report(record_id):
    authorize([ROLE_REGULATORY_OFFICER, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    rec = must_get("regulatory_reports", record_id)
    return success(ser.regulatory_report(rec))


@bp.post("/regulatory-reports/<record_id>/determine")
def determine_report(record_id):
    actor = authorize([ROLE_REGULATORY_OFFICER])
    rec = must_get("regulatory_reports", record_id)
    body = get_body()
    check_required(body, ["determination"])
    determination = v_enum(body, "determination", DETERMINATIONS)
    determination_note = v_string(body, "determination_note", 0)

    complaint = store.complaints.get(rec["complaint_id"])
    if complaint is not None and complaint["regulatory_status"] != "ESCALATED":
        raise err(
            "ERR_REGULATORY_STATE_INVALID",
            "the complaint's regulatory_status does not permit a determination",
        )
    if rec["status"] != "OPEN":
        raise err("ERR_REPORT_STATE_INVALID", "only an OPEN report may be determined")
    if determination == "NOT_REPORTABLE" and calc.effective_band(complaint or {}) == "S1":
        raise err(
            "ERR_S1_MUST_BE_REPORTABLE",
            "an S1 complaint can never be determined non-reportable",
        )

    rec["status"] = (
        "DETERMINED_REPORTABLE" if determination == "REPORTABLE" else "DETERMINED_NOT_REPORTABLE"
    )
    rec["determination_note"] = determination_note
    rec["determined_by_ref"] = actor.user_id
    touch(rec)

    if complaint is not None:
        complaint["regulatory_status"] = determination
        touch(complaint)
    return success(ser.regulatory_report(rec))


@bp.post("/regulatory-reports/<record_id>/submit")
def submit_report(record_id):
    actor = authorize([ROLE_REGULATORY_OFFICER])
    rec = must_get("regulatory_reports", record_id)
    body = get_body()
    check_required(body, ["agency_reference"])
    agency_reference = v_string(body, "agency_reference", 1)

    complaint = store.complaints.get(rec["complaint_id"])
    if complaint is not None and complaint["regulatory_status"] != "REPORTABLE":
        raise err(
            "ERR_REGULATORY_STATE_INVALID",
            "the complaint's regulatory_status does not permit a filing",
        )
    if rec["status"] != "DETERMINED_REPORTABLE":
        raise err(
            "ERR_REPORT_STATE_INVALID", "only a DETERMINED_REPORTABLE report may be filed"
        )
    if actor.user_id == rec.get("determined_by_ref"):
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the filing officer may not be the determining officer",
        )

    submitted_at = now()
    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = submitted_at
    rec["submitted_by_ref"] = actor.user_id
    rec["agency_reference"] = agency_reference
    rec["submitted_late"] = submitted_at > rec["due_at"]
    touch(rec)

    if complaint is not None:
        complaint["regulatory_status"] = "SUBMITTED"
        touch(complaint)
    return success(ser.regulatory_report(rec))


@bp.post("/regulatory-reports/<record_id>/withdraw")
def withdraw_report(record_id):
    authorize([ROLE_REGULATORY_OFFICER])
    rec = must_get("regulatory_reports", record_id)
    body = get_body()
    v_string(body, "reason", 0)

    complaint = store.complaints.get(rec["complaint_id"])
    if complaint is not None and complaint["regulatory_status"] == "SUBMITTED":
        raise err(
            "ERR_REGULATORY_STATE_INVALID", "a filed regulatory dimension cannot be withdrawn"
        )
    if rec["status"] in ("SUBMITTED", "WITHDRAWN"):
        raise err("ERR_REPORT_STATE_INVALID", "the report is already terminal")

    rec["status"] = "WITHDRAWN"
    touch(rec)
    if complaint is not None:
        complaint["regulatory_status"] = "NOT_APPLICABLE"
        touch(complaint)
    return success(ser.regulatory_report(rec))
