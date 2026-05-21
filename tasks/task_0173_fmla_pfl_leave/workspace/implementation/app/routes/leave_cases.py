"""LeaveCase routes: read, instances, certifications, review, return, restore, cancel."""
from __future__ import annotations

from datetime import date, timedelta
from flask import Blueprint, jsonify, request

from ..audit import emit_audit
from ..auth import ensure_employee_owns, require_roles
from ..clock import format_datetime_ms, get_clock, parse_iso_date, parse_iso_datetime
from ..common import (
    optional_int,
    parse_json_body,
    require_bool,
    require_enum,
    require_int,
    require_str,
    strip_internal,
)
from ..errors import (
    err_cert_deadline_missed,
    err_cert_incomplete,
    err_duplicate_instance_day,
    err_employee_terminated,
    err_instance_not_allowed,
    err_instance_overlap,
    err_invalid_state,
    err_job_restoration_forfeited,
    err_not_found,
    err_quota_exceeded,
    err_validation,
    err_version_conflict,
)
from ..pagination import parse_pagination, slice_page
from ..response import make_array_envelope, make_object_envelope
from ..services import calculations as calc
from ..services.leave_case_service import (
    approve_case,
    bump_version,
    cancel_case,
    deny_case,
    view_case,
)
from ..store import get_store, new_id


bp_leave_cases = Blueprint("leave_cases", __name__)


def _resolve_case(leave_case_id: str, user_id: str, role: str) -> dict:
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    ensure_employee_owns(user_id, role, case["employee_id"])
    return case


# -----------------------------------------------------------------------------
# Read case
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>", methods=["GET"])
@require_roles("Employee", "HRSpecialist", "ComplianceOfficer")
def get_leave_case(user_id: str, role: str, leave_case_id: str):
    case = _resolve_case(leave_case_id, user_id, role)
    return jsonify(make_object_envelope(view_case(case))), 200


# -----------------------------------------------------------------------------
# LeaveInstance: log + delete
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/instances", methods=["POST"])
@require_roles("Employee", "HRSpecialist")
def post_instance(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = _resolve_case(leave_case_id, user_id, role)
    emp = store.employees.get(case["employee_id"])
    if emp is None:
        raise err_not_found("Owning employee not found.")
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()

    # state precondition: case must allow instance posting (not in CANCELLED/DENIED/COMPLETED/JOB_RESTORED)
    if case["case_status"] in {"CANCELLED", "DENIED", "JOB_RESTORED", "COMPLETED"}:
        raise err_invalid_state("Cannot log instances on this case.")

    body = parse_json_body()
    instance_date_str = require_str(body, "instance_date")
    try:
        instance_date = parse_iso_date(instance_date_str)
    except Exception:
        raise err_validation("instance_date must be an ISO 8601 date.")
    hours_used_raw = require_int(body, "hours_used")

    # Pattern legality (priority 16): hours in [1,24] AND only INTERMITTENT/REDUCED_SCHEDULE
    if case["leave_pattern"] == "CONTINUOUS":
        raise err_instance_not_allowed()
    if hours_used_raw < 1 or hours_used_raw > 24:
        raise err_instance_not_allowed()

    # Cross-case overlap (priority 17)
    employer = store.employers.get(emp["employer_id"])
    leave_year_basis = employer["leave_year_basis"] if employer else "CALENDAR"
    win_start_new, win_end_new = calc.window_for_basis(leave_year_basis, instance_date)
    for other in store.leave_instances.values():
        if other["instance_status"] == "VOIDED":
            continue
        if other["leave_case_id"] == case["id"]:
            continue
        # Must belong to same employee
        other_case = store.leave_cases.get(other["leave_case_id"])
        if other_case is None or other_case["employee_id"] != emp["id"]:
            continue
        other_date = parse_iso_date(other["instance_date"])
        if other_date != instance_date:
            continue
        # Same date — does it consume in the same window?
        if win_start_new <= other_date <= win_end_new:
            raise err_instance_overlap()

    # Duplicate-day uniqueness (priority 22) — same case+date
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] == case["id"] and inst["instance_date"] == instance_date_str and inst["instance_status"] != "VOIDED":
            raise err_duplicate_instance_day()

    # Quota check (priority 15) — PRD §3.7: "consumed_hours figure is
    # the sum of `hours_used` across every `LeaveInstance` whose
    # `instance_status` is `APPROVED`, whose owning `LeaveCase` is in a
    # consumed state". PROPOSED instances on a PENDING_CERTIFICATION
    # parent do NOT consume quota; the quota is "decremented when the
    # case is approved". We therefore only enforce the cap at instance
    # logging time when the new instance would auto-become APPROVED
    # (i.e., the parent case is already APPROVED or ACTIVE).
    auto_approved = case["case_status"] in {"APPROVED", "ACTIVE"}
    if auto_approved:
        anchor_date = parse_iso_date(case["requested_start_date"])
        consumed, _remaining, _, _ = calc.remaining_hours_for_employee(
            store, emp["id"], leave_year_basis, anchor_date, exclude_case_id=case["id"],
        )
        # Already-approved instances on this case (these contribute to
        # consumed via remaining_hours_for_employee? No — that helper
        # excludes this case_id. So add APPROVED-on-this-case.)
        on_case_approved = 0
        for inst in store.leave_instances.values():
            if inst["leave_case_id"] == case["id"] and inst["instance_status"] == "APPROVED":
                on_case_approved += int(inst["hours_used"])
        projected = consumed + on_case_approved + hours_used_raw
        if projected > calc.FMLA_ENTITLEMENT_HOURS:
            raise err_quota_exceeded()

    # Create instance
    now_iso = format_datetime_ms(get_clock().get())
    inst_id = new_id()
    inst = {
        "id": inst_id,
        "leave_case_id": case["id"],
        "instance_date": instance_date_str,
        "hours_used": hours_used_raw,
        "instance_status": "APPROVED" if auto_approved else "PROPOSED",
        "created_at": now_iso,
        "_seq": store.next_seq(),
    }
    store.leave_instances[inst_id] = inst

    if auto_approved:
        # Recompute hours_charged
        total = 0
        for i in store.leave_instances.values():
            if i["leave_case_id"] == case["id"] and i["instance_status"] == "APPROVED":
                total += int(i["hours_used"])
        case["hours_charged"] = total
        bump_version(case)
        emit_audit(case["id"], "QUOTA_RECOMPUTED", role, {"hours_charged": total})

    emit_audit(case["id"], "INSTANCE_LOGGED", role, {"instance_id": inst_id, "instance_date": instance_date_str, "hours_used": hours_used_raw})
    return jsonify(make_object_envelope(strip_internal(inst))), 201


@bp_leave_cases.route("/leave-cases/<leave_case_id>/instances/<instance_id>", methods=["DELETE"])
@require_roles("HRSpecialist")
def void_instance(user_id: str, role: str, leave_case_id: str, instance_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    inst = store.leave_instances.get(instance_id)
    if inst is None or inst["leave_case_id"] != leave_case_id:
        raise err_not_found("LeaveInstance not found under this case.")

    if case["case_status"] not in {"APPROVED", "ACTIVE"}:
        raise err_invalid_state("Instance can only be voided on APPROVED or ACTIVE cases.")
    inst["instance_status"] = "VOIDED"
    # Recompute hours_charged
    total = 0
    for i in store.leave_instances.values():
        if i["leave_case_id"] == case["id"] and i["instance_status"] == "APPROVED":
            total += int(i["hours_used"])
    case["hours_charged"] = total
    bump_version(case)
    emit_audit(case["id"], "INSTANCE_VOIDED", role, {"instance_id": instance_id})
    emit_audit(case["id"], "QUOTA_RECOMPUTED", role, {"hours_charged": total})
    return ("", 204)


# -----------------------------------------------------------------------------
# Certification: submit + review
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/certifications", methods=["POST"])
@require_roles("Employee")
def post_certification(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = _resolve_case(leave_case_id, user_id, role)
    emp = store.employees.get(case["employee_id"])
    if emp is None:
        raise err_not_found("Owning employee not found.")
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()
    if case["case_status"] != "PENDING_CERTIFICATION":
        raise err_invalid_state("Certification can only be submitted on PENDING_CERTIFICATION cases.")
    # Cure window: cert_deadline + 7 days
    now_dt = get_clock().get()
    cure_end = parse_iso_datetime(case["cert_deadline"]) + timedelta(days=7)
    if now_dt > cure_end:
        raise err_invalid_state("Cure window has expired.")

    body = parse_json_body()
    serious = require_bool(body, "serious_health_condition")
    freq = optional_int(body, "estimated_frequency_per_month", default=0, minimum=0)
    dur = optional_int(body, "estimated_duration_hours", default=0, minimum=0)

    now_iso = format_datetime_ms(get_clock().get())
    cert_id = new_id()
    cert = {
        "id": cert_id,
        "leave_case_id": case["id"],
        "submitted_at": now_iso,
        "serious_health_condition": serious,
        "estimated_frequency_per_month": freq,
        "estimated_duration_hours": dur,
        "review_outcome": "PENDING",
        "created_at": now_iso,
        "_seq": store.next_seq(),
    }
    store.medical_certifications[cert_id] = cert

    case["certification_status"] = "RECEIVED"
    bump_version(case)
    emit_audit(case["id"], "CERTIFICATION_SUBMITTED", role, {"cert_id": cert_id})
    return jsonify(make_object_envelope(strip_internal(cert))), 201


@bp_leave_cases.route("/leave-cases/<leave_case_id>/certifications/<cert_id>/review", methods=["POST"])
@require_roles("HRSpecialist")
def review_certification(user_id: str, role: str, leave_case_id: str, cert_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    cert = store.medical_certifications.get(cert_id)
    if cert is None or cert["leave_case_id"] != leave_case_id:
        raise err_not_found("MedicalCertification not found under this case.")

    body = parse_json_body()
    decision = require_enum(body, "decision", {"ACCEPT", "INSUFFICIENT", "REJECT"})

    if cert["review_outcome"] != "PENDING":
        raise err_invalid_state("Certification has already been reviewed.")
    if case["certification_status"] != "RECEIVED":
        raise err_invalid_state("Parent case certification_status must be RECEIVED to review.")

    if decision == "ACCEPT":
        if not cert["serious_health_condition"]:
            raise err_invalid_state("Cannot ACCEPT when provider attestation is false.")
        cert["review_outcome"] = "ACCEPTED"
        case["certification_status"] = "COMPLETE"
    elif decision == "INSUFFICIENT":
        cert["review_outcome"] = "INSUFFICIENT"
        case["certification_status"] = "INSUFFICIENT"
    else:  # REJECT
        if cert["serious_health_condition"]:
            raise err_invalid_state("REJECT is reserved for false attestations.")
        cert["review_outcome"] = "REJECTED"
        case["certification_status"] = "INSUFFICIENT"

    bump_version(case)
    emit_audit(case["id"], "CERTIFICATION_REVIEWED", role, {"cert_id": cert_id, "decision": decision})
    return jsonify(make_object_envelope(strip_internal(cert))), 200


# -----------------------------------------------------------------------------
# Approve / Deny
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/review", methods=["POST"])
@require_roles("HRSpecialist")
def review_case(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    emp = store.employees.get(case["employee_id"])
    if emp is None:
        raise err_not_found("Owning employee not found.")
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()
    if case["case_status"] != "PENDING_CERTIFICATION":
        raise err_invalid_state("Case must be PENDING_CERTIFICATION to be reviewed.")

    body = parse_json_body()
    # OCC version
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or body["version"] != int(case["version"]):
            raise err_version_conflict()
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})

    now_dt = get_clock().get()
    cert_deadline_dt = parse_iso_datetime(case["cert_deadline"])

    if decision == "APPROVE":
        # priority 13: cert deadline missed
        if case["certification_status"] == "AWAITING_DOC" and now_dt > cert_deadline_dt:
            raise err_cert_deadline_missed()
        # priority 14: certification incomplete
        if case["certification_status"] in {"AWAITING_DOC", "INSUFFICIENT"}:
            raise err_cert_incomplete()
        if case["certification_status"] not in {"COMPLETE", "NOT_REQUIRED"}:
            raise err_cert_incomplete()
        # priority 15: quota check
        employer = store.employers.get(emp["employer_id"])
        leave_year_basis = employer["leave_year_basis"] if employer else "CALENDAR"
        anchor_date = parse_iso_date(case["requested_start_date"])
        consumed, _, _, _ = calc.remaining_hours_for_employee(
            store, emp["id"], leave_year_basis, anchor_date, exclude_case_id=case["id"],
        )
        proposed_total = 0
        for inst in store.leave_instances.values():
            if inst["leave_case_id"] == case["id"] and inst["instance_status"] == "PROPOSED":
                proposed_total += int(inst["hours_used"])
        if consumed + proposed_total > calc.FMLA_ENTITLEMENT_HOURS:
            raise err_quota_exceeded()
        approve_case(case, role)
    else:
        # DENY allowed when certification_status == INSUFFICIENT OR (AWAITING_DOC AND past deadline)
        cs = case["certification_status"]
        past_deadline = now_dt > cert_deadline_dt
        if cs == "INSUFFICIENT" or (cs == "AWAITING_DOC" and past_deadline):
            deny_case(case, role)
        else:
            raise err_invalid_state("DENY requires certification_status INSUFFICIENT or AWAITING_DOC past deadline.")

    return jsonify(make_object_envelope(view_case(case))), 200


# -----------------------------------------------------------------------------
# Return + Restore
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/return", methods=["POST"])
@require_roles("Employee", "HRSpecialist")
def return_case(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = _resolve_case(leave_case_id, user_id, role)
    emp = store.employees.get(case["employee_id"])
    if emp is None:
        raise err_not_found("Employee not found.")
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()
    if case["case_status"] != "ACTIVE":
        raise err_invalid_state("Return is only allowed from ACTIVE.")
    now_dt = get_clock().get()
    req_start_dt = parse_iso_datetime(case["requested_start_date"])
    if now_dt < req_start_dt:
        raise err_invalid_state("Current time precedes requested_start_date.")

    if case["leave_pattern"] != "CONTINUOUS":
        # All instances accounted for; no PROPOSED remaining
        approved_total = 0
        for inst in store.leave_instances.values():
            if inst["leave_case_id"] == case["id"]:
                if inst["instance_status"] == "PROPOSED":
                    raise err_invalid_state("Outstanding PROPOSED instances exist.")
                if inst["instance_status"] == "APPROVED":
                    approved_total += int(inst["hours_used"])
        if case["hours_charged"] != approved_total:
            # Force recompute
            case["hours_charged"] = approved_total

    case["case_status"] = "COMPLETED"
    bump_version(case)
    return jsonify(make_object_envelope(view_case(case))), 200


@bp_leave_cases.route("/leave-cases/<leave_case_id>/restore-job", methods=["POST"])
@require_roles("HRSpecialist")
def restore_job(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    if case["case_status"] != "COMPLETED":
        raise err_invalid_state("Restore-job requires case_status == COMPLETED.")
    if case["job_restoration_status"] != "PROTECTED":
        raise err_job_restoration_forfeited()
    # Outstanding forfeited invoice on this case?
    for inv in store.benefit_invoices.values():
        if inv["leave_case_id"] == case["id"] and inv["invoice_status"] == "FORFEITED":
            raise err_job_restoration_forfeited()
    emp = store.employees.get(case["employee_id"])
    if emp is None:
        raise err_not_found("Owning employee not found.")
    if emp["employment_status"] not in {"ON_LEAVE", "ACTIVE"}:
        raise err_invalid_state("Employee employment_status must be ON_LEAVE or ACTIVE.")
    case["case_status"] = "JOB_RESTORED"
    bump_version(case)
    emp["employment_status"] = "RESTORED"
    bump_version(emp)
    emit_audit(case["id"], "JOB_RESTORATION_REQUESTED", role, {})
    return jsonify(make_object_envelope(view_case(case))), 200


# -----------------------------------------------------------------------------
# Cancel
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>", methods=["DELETE"])
@require_roles("Employee")
def delete_case(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    ensure_employee_owns(user_id, role, case["employee_id"])
    # OCC via body (PRD §2.4) — read version BEFORE the state check so
    # the validation ordering of §2.6 (ERR_VERSION_CONFLICT immediately
    # below ERR_INVALID_STATE) is honored only when the state allows
    # cancellation. State-precondition first, then version.
    if case["case_status"] not in {"DRAFT", "PENDING_CERTIFICATION"}:
        raise err_invalid_state("Cancellation only allowed from DRAFT or PENDING_CERTIFICATION.")
    body = parse_json_body() if request.data else {}
    # Also accept version from query string (?version=) for clients that
    # cannot send DELETE bodies cleanly.
    if "version" not in body or body.get("version") is None:
        qver = request.args.get("version")
        if qver is not None:
            try:
                body["version"] = int(qver)
            except (TypeError, ValueError):
                raise err_validation("version must be an integer.")
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or body["version"] != int(case["version"]):
            raise err_version_conflict()
    cancel_case(case, "Employee")
    return ("", 204)


# -----------------------------------------------------------------------------
# Benefit invoices listing under a case
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/benefit-invoices", methods=["GET"])
@require_roles("Employee", "HRSpecialist")
def list_invoices_under_case(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    ensure_employee_owns(user_id, role, case["employee_id"])
    limit, offset = parse_pagination()
    rows = [i for i in store.benefit_invoices.values() if i["leave_case_id"] == leave_case_id]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(rows)
    page = slice_page(rows, limit, offset)
    items = [strip_internal(r) for r in page]
    return jsonify(make_array_envelope(items, limit=limit, offset=offset, total_count=total)), 200


# -----------------------------------------------------------------------------
# Audit events
# -----------------------------------------------------------------------------
@bp_leave_cases.route("/leave-cases/<leave_case_id>/audit-events", methods=["GET"])
@require_roles("HRSpecialist", "ComplianceOfficer")
def list_audit_events(user_id: str, role: str, leave_case_id: str):
    store = get_store()
    case = store.leave_cases.get(leave_case_id)
    if case is None:
        raise err_not_found("LeaveCase not found.")
    limit, offset = parse_pagination()
    rows = [e for e in store.audit_events.values() if e["leave_case_id"] == leave_case_id]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(rows)
    page = slice_page(rows, limit, offset)
    items = [strip_internal(r) for r in page]
    return jsonify(make_array_envelope(items, limit=limit, offset=offset, total_count=total)), 200
