"""Report routes: mint, submit-for-review, approve-review, send-back, sign,
issue, recall, reopen, read."""

import base64

from flask import Blueprint, g

from db import DB, new_id, LOCK
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES, ERR_SIGNATORY_SCOPE_MISMATCH,
    ERR_REVIEWER_SCOPE_MISMATCH, ERR_REPORT_BLOCKED_INSTRUMENT_LAPSED,
    raise_error,
)
from middleware import auth_required
from response import success_response
from services.common import get_json_body
from services.serializers import serialize_report
from services.time_util import now_iso, now_dt, parse_iso
from services.calculations import TEMPLATE_CODES
from services.state import touch
from services.audit import emit_audit

bp = Blueprint("reports", __name__)


@bp.post("/tasks/<tid>/report")
@auth_required(["Tester"])
def mint_report(tid):
    task = DB["tasks"].get(tid)
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if task.get("status") != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "Task must be COMPLETED to mint a report")
    if task.get("assigned_tester_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Only the assigned tester may mint the report")
    with LOCK:
        # Enforce exactly-one
        for r in DB["reports"].values():
            if r.get("task_id") == tid:
                raise_error(ERR_INVALID_STATE, "Report already exists for this task")
        now = now_iso()
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "task_id": tid,
            "template_code": TEMPLATE_CODES.get(task["test_method"], "TPL-UNKNOWN-V1"),
            "reviewer_id": None,
            "signatory_id": None,
            "signature_payload": None,
            "status": "DRAFTED",
            "issued_at": None,
        }
        DB["reports"][row["id"]] = row
    return success_response(serialize_report(row), 201)


def _get_report_or_404(rid):
    r = DB["reports"].get(rid)
    if r is None:
        raise_error(ERR_NOT_FOUND, "Report not found")
    return r


def _sample_for_report(report):
    task = DB["tasks"].get(report["task_id"])
    if task is None:
        return None
    return DB["samples"].get(task["sample_id"])


@bp.post("/reports/<rid>/submit-for-review")
@auth_required(["Tester"])
def submit_for_review(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "DRAFTED":
        raise_error(ERR_INVALID_STATE, "Report must be DRAFTED to submit for review")
    task = DB["tasks"].get(row["task_id"])
    if task is None or task.get("assigned_tester_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Only the authoring tester may submit for review")
    with LOCK:
        row["status"] = "UNDER_REVIEW"
        touch(row)
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/approve-review")
@auth_required(["Reviewer"])
def approve_review(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Report must be UNDER_REVIEW")
    reviewer = DB["reviewers"].get(g.user_id)
    if reviewer is None:
        raise_error(ERR_NOT_FOUND, "Reviewer not found")
    sample = _sample_for_report(row)
    if sample is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    if sample["material_category"] not in (reviewer.get("scope_categories") or []):
        raise_error(ERR_REVIEWER_SCOPE_MISMATCH, "Reviewer scope mismatch")
    with LOCK:
        row["reviewer_id"] = reviewer["id"]
        touch(row)
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/send-back")
@auth_required(["Reviewer"])
def send_back(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Report must be UNDER_REVIEW")
    reviewer = DB["reviewers"].get(g.user_id)
    if reviewer is None:
        raise_error(ERR_NOT_FOUND, "Reviewer not found")
    sample = _sample_for_report(row)
    if sample is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    if sample["material_category"] not in (reviewer.get("scope_categories") or []):
        raise_error(ERR_REVIEWER_SCOPE_MISMATCH, "Reviewer scope mismatch")
    with LOCK:
        row["status"] = "DRAFTED"
        row["reviewer_id"] = None
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = now_iso()
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/sign")
@auth_required(["Signatory"])
def sign_report(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Report must be UNDER_REVIEW to be signed")
    if not row.get("reviewer_id"):
        raise_error(ERR_INVALID_STATE, "Reviewer has not approved the report")
    signatory = DB["signatories"].get(g.user_id)
    if signatory is None:
        raise_error(ERR_NOT_FOUND, "Signatory not found")
    task = DB["tasks"].get(row["task_id"])
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    sample = DB["samples"].get(task["sample_id"])
    if sample is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    # Segregation: signatory id != reviewer id AND != any test-record tester id under this task.
    tester_ids = {r.get("tester_id") for r in DB["records"].values()
                  if r.get("task_id") == task["id"]}
    if signatory["id"] == row.get("reviewer_id") or signatory["id"] in tester_ids:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Signatory cannot be reviewer or tester")
    # Signatory scope (priority 8)
    if sample["material_category"] not in (signatory.get("scope_categories") or []):
        raise_error(ERR_SIGNATORY_SCOPE_MISMATCH, "Signatory scope mismatch")
    with LOCK:
        row["signatory_id"] = signatory["id"]
        cert = signatory["signature_certificate_id"]
        payload_src = f"{rid}:{cert}:{row.get('version', 1)}"
        row["signature_payload"] = base64.b64encode(payload_src.encode("utf-8")).decode("ascii")
        row["status"] = "SIGNED"
        touch(row)
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/issue")
@auth_required(["Signatory"])
def issue_report(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "SIGNED":
        raise_error(ERR_INVALID_STATE, "Report must be SIGNED to be issued")
    if not row.get("signature_payload"):
        raise_error(ERR_INVALID_STATE, "Signature missing")
    task = DB["tasks"].get(row["task_id"])
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    # Calibration validity check on every non-superseded record under this task
    records = [r for r in DB["records"].values()
               if r.get("task_id") == task["id"] and r.get("status") != "SUPERSEDED"]
    for rec in records:
        # Find the instrument used at the time the record was created. We resolve
        # via the task.instrument_booking_id (the booking links instrument).
        bid = task.get("instrument_booking_id")
        if not bid:
            continue
        booking = DB["bookings"].get(bid)
        if booking is None:
            continue
        instrument = DB["instruments"].get(booking["instrument_id"])
        if instrument is None:
            continue
        cvt = parse_iso(instrument["calibration_valid_to"]) if isinstance(instrument["calibration_valid_to"], str) else instrument["calibration_valid_to"]
        rec_dt = parse_iso(rec["created_at"]) if isinstance(rec["created_at"], str) else rec["created_at"]
        if cvt < rec_dt:
            raise_error(ERR_REPORT_BLOCKED_INSTRUMENT_LAPSED,
                        "Instrument calibration lapsed before record was captured")
    # Invoice must exist for the underlying task with status in {ISSUED, PAID}
    invoice_ok = False
    for inv in DB["invoices"].values():
        if inv.get("status") not in ("ISSUED", "PAID"):
            continue
        if any(li.get("task_id") == task["id"] for li in inv.get("line_items", [])):
            invoice_ok = True
            break
    if not invoice_ok:
        raise_error(ERR_INVALID_STATE, "Invoice must exist (ISSUED or PAID) before issuing report")
    with LOCK:
        row["status"] = "ISSUED"
        row["issued_at"] = now_iso()
        touch(row)
        emit_audit("REPORT_ISSUED", "Report", rid, g.user_role, g.user_id,
                   {"version": row.get("version", 1)})
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/recall")
@auth_required(["Signatory"])
def recall_report(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "ISSUED":
        raise_error(ERR_INVALID_STATE, "Report must be ISSUED to be recalled")
    issued_at = row.get("issued_at")
    if issued_at:
        issued_dt = parse_iso(issued_at) if isinstance(issued_at, str) else issued_at
        from datetime import timedelta
        if now_dt() >= issued_dt + timedelta(days=30):
            raise_error(ERR_INVALID_STATE, "Recall window has closed")
    with LOCK:
        row["status"] = "RECALLED"
        row["signature_payload"] = None
        touch(row)
        emit_audit("REPORT_RECALLED", "Report", rid, g.user_role, g.user_id, {})
    return success_response(serialize_report(row), 200)


@bp.post("/reports/<rid>/reopen")
@auth_required(["LabManager"])
def reopen_report(rid):
    row = _get_report_or_404(rid)
    if row.get("status") != "RECALLED":
        raise_error(ERR_INVALID_STATE, "Report must be RECALLED to be reopened")
    with LOCK:
        row["status"] = "DRAFTED"
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = now_iso()
    return success_response(serialize_report(row), 200)


@bp.get("/reports/<rid>")
@auth_required(["LabManager", "LabClerk", "Reviewer", "Signatory", "Tester"])
def read_report(rid):
    row = _get_report_or_404(rid)
    return success_response(serialize_report(row), 200)
