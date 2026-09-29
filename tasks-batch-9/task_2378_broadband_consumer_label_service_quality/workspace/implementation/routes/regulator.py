"""Regulator dockets and their two evidence filings (PRD §3.9)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (COMPLAINT_ANALYST, COMPLIANCE_OFFICER,
                        NETWORK_ENGINEER, REGULATORY_LIAISON, authorize)

bp = Blueprint("regulator", __name__)

FILING_TYPES = ("TECHNICAL_PACKET", "RESOLUTION_REPORT")
READ_ROLES = (COMPLIANCE_OFFICER, NETWORK_ENGINEER, COMPLAINT_ANALYST,
              REGULATORY_LIAISON)
COMPLAINT_TERMINAL = ("UPHELD", "DISMISSED", "WITHDRAWN")


@bp.route("/regulator-inquiries", methods=["POST"])
def create_regulator_inquiry():
    authorize(REGULATORY_LIAISON)
    body = validators.json_body()

    complaint_ref = validators.get_id_ref(body, "complaint_id")
    docket_number = validators.get_str(body, "docket_number", 1, 32)
    regulator_code = validators.get_str(body, "regulator_code", 1, 16)
    due_raw = validators.get_datetime(body, "response_due_at")
    if not db.parse_iso(due_raw) > db.now():
        validators.bad("Field 'response_due_at' must be after the current "
                       "logical clock.")

    complaint = lookup.complaint(complaint_ref)

    for existing in db.store.regulator_inquiries.values():
        if existing["docket_number"] == docket_number:
            fail(errors.ERR_DUPLICATE_DOCKET_NUMBER)

    inquiry = db.new_record()
    inquiry.update({
        "complaint_id": complaint["id"],
        "docket_number": docket_number,
        "regulator_code": regulator_code,
        "response_due_at": due_raw,
        "state": "RECEIVED",
        "technical_packet_filed_at": None,
        "resolution_report_filed_at": None,
        "technical_evidence_ref": None,
        "resolution_report_ref": None,
        "filed_late": False,
        "closure_note": None,
        "closed_at": None,
    })
    db.store.regulator_inquiries[inquiry["id"]] = inquiry
    return response.success(serializers.regulator_inquiry(inquiry), 201)


@bp.route("/regulator-inquiries/<inquiry_id>", methods=["GET"])
def read_regulator_inquiry(inquiry_id):
    authorize(*READ_ROLES)
    inquiry = lookup.regulator_inquiry(inquiry_id)
    return response.success(serializers.regulator_inquiry(inquiry), 200)


@bp.route("/regulator-inquiries", methods=["GET"])
def list_regulator_inquiries():
    authorize(*READ_ROLES)
    validators.pagination_params()
    complaint_id = request.args.get("complaint_id")
    state = request.args.get("state")
    rows = [i for i in db.store.regulator_inquiries.values()
            if (complaint_id is None or i["complaint_id"] == complaint_id)
            and (state is None or i["state"] == state)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.regulator_inquiry)
    return response.success_list(items, meta, 200)


@bp.route("/regulator-inquiries/<inquiry_id>/filings", methods=["POST"])
def file_inquiry_response(inquiry_id):
    authorize(REGULATORY_LIAISON)
    body = validators.json_body()
    filing_type = validators.get_enum(body, "filing_type", FILING_TYPES)
    evidence_ref = validators.get_str(body, "evidence_ref", 1, None)
    validators.get_str(body, "summary", 1, None)

    inquiry = lookup.regulator_inquiry(inquiry_id)

    if inquiry["state"] in ("RESPONSE_COMPLETE", "CLOSED"):
        fail(errors.ERR_INQUIRY_INVALID_STATE)

    branch = ("technical_packet_filed_at"
              if filing_type == "TECHNICAL_PACKET"
              else "resolution_report_filed_at")
    if inquiry[branch] is not None:
        fail(errors.ERR_INQUIRY_INVALID_STATE)

    complaint = db.store.complaints.get(inquiry["complaint_id"])
    if filing_type == "TECHNICAL_PACKET":
        label = None
        if complaint is not None:
            label = db.store.label_versions.get(
                complaint["disputed_label_version_id"])
        if (label is None or label["attestation_id"] is None
                or label["substantiation_status"] != "SUBSTANTIATED"):
            fail(errors.ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING)
        inquiry["technical_evidence_ref"] = evidence_ref
        inquiry["technical_packet_filed_at"] = db.now_iso()
    else:
        if complaint is None or complaint["state"] not in COMPLAINT_TERMINAL:
            fail(errors.ERR_COMPLAINT_NOT_TERMINAL)
        inquiry["resolution_report_ref"] = evidence_ref
        inquiry["resolution_report_filed_at"] = db.now_iso()

    if (inquiry["technical_packet_filed_at"] is not None
            and inquiry["resolution_report_filed_at"] is not None):
        inquiry["state"] = "RESPONSE_COMPLETE"
        technical = db.dt_of(inquiry, "technical_packet_filed_at")
        resolution = db.dt_of(inquiry, "resolution_report_filed_at")
        latest = technical if technical > resolution else resolution
        inquiry["filed_late"] = latest > db.dt_of(inquiry, "response_due_at")
    else:
        inquiry["state"] = "EVIDENCE_ASSEMBLY"

    db.touch(inquiry)
    return response.success(serializers.regulator_inquiry(inquiry), 200)


@bp.route("/regulator-inquiries/<inquiry_id>/close", methods=["POST"])
def close_regulator_inquiry(inquiry_id):
    authorize(REGULATORY_LIAISON)
    body = validators.json_body()
    note = validators.get_str(body, "closure_note", 1, None)

    inquiry = lookup.regulator_inquiry(inquiry_id)
    if inquiry["state"] in ("RECEIVED", "EVIDENCE_ASSEMBLY"):
        fail(errors.ERR_INQUIRY_FILINGS_INCOMPLETE)
    if inquiry["state"] != "RESPONSE_COMPLETE":
        fail(errors.ERR_INQUIRY_INVALID_STATE)

    inquiry["state"] = "CLOSED"
    inquiry["closure_note"] = note
    inquiry["closed_at"] = db.now_iso()
    db.touch(inquiry)
    return response.success(serializers.regulator_inquiry(inquiry), 200)
