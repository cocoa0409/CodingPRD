"""AuditWorkOrder routes: reads, actions, and work-order-scoped lists."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from db import (
    policies, auditors, class_codes, work_orders, records_requests,
    appointments, allocations, exposures, results, disputes, mod_revisions,
)
from errors import raise_err, validation
from middleware import (
    Ctx, authenticate, require_role, get_body, check_allowed,
    req_str, req_int, opt_int, req_enum, req_dt, opt_bool, parse_pagination,
)
from response import ok, created, ok_list

bp = Blueprint("workorders", __name__)

WO_STATUSES = {
    "SELECTED", "RECORDS_REQUESTED", "APPOINTMENT_SCHEDULED", "FIELD_WORK_DONE",
    "RESULT_DRAFTED", "BILLED", "DISPUTED", "NONCOMPLIANT_PENDING",
    "ESTIMATED_BILLED", "CLOSED", "SUPERSEDED_BY_REAUDIT", "CANCELLED",
}
REQUEST_TYPES = {
    "PAYROLL_SUMMARY", "TAX_FILINGS", "SUBCONTRACTOR_LIST",
    "CERTIFICATES_OF_INSURANCE", "SALES_LEDGER",
}
LOCATION_TYPES = {"INSURED_PREMISES", "VIRTUAL", "AUDITOR_OFFICE"}


def load_wo(wo_id):
    wo = work_orders.get(wo_id)
    if wo is None:
        raise_err("ERR_WORK_ORDER_NOT_FOUND", "AuditWorkOrder id does not exist")
    return wo


def insured_owns(wo):
    """Scope check for Insured callers against the work order's policy."""
    if Ctx.role == "Insured" and wo["policy_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Insured may only access own policy graph")


def auditor_assigned(wo):
    if wo["assigned_auditor_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Auditor may only mutate assigned work orders")


# --- list / get -------------------------------------------------------------------

@bp.route("/audit-work-orders", methods=["GET"])
def list_work_orders():
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    limit, offset = parse_pagination()
    policy_f = request.args.get("policy_id")
    run_f = request.args.get("selection_run_id")
    auditor_f = request.args.get("assigned_auditor_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in WO_STATUSES:
        validation("invalid status filter")
    if Ctx.role == "Insured":
        if policy_f is not None and policy_f != Ctx.user_id:
            raise_err("ERR_FORBIDDEN_SCOPE",
                      "Insured policy_id filter must equal X-User-ID")
        policy_f = Ctx.user_id
    items = list(work_orders.values())
    if policy_f:
        items = [w for w in items if w["policy_id"] == policy_f]
    if run_f:
        items = [w for w in items if w["selection_run_id"] == run_f]
    if auditor_f:
        items = [w for w in items if w["assigned_auditor_id"] == auditor_f]
    if status_f:
        items = [w for w in items if w["status"] == status_f]
    items = [db.serialize(w) for w in db.by_created(items)]
    return ok_list(items, limit, offset)


@bp.route("/audit-work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    wo = load_wo(wo_id)
    insured_owns(wo)
    return ok(db.serialize(wo))


def _scoped_list(wo_id, items):
    wo = load_wo(wo_id)
    insured_owns(wo)
    limit, offset = parse_pagination()
    out = [db.serialize(x) for x in db.by_created(items)]
    return ok_list(out, limit, offset)


@bp.route("/audit-work-orders/<wo_id>/reaudits", methods=["GET"])
def list_reaudits(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter")
    wo = load_wo(wo_id)
    insured_owns(wo)
    limit, offset = parse_pagination()
    items = [w for w in work_orders.values()
             if w["reaudit_of_work_order_id"] == wo["id"]]
    items = [db.serialize(w) for w in db.by_created(items)]
    return ok_list(items, limit, offset)


@bp.route("/audit-work-orders/<wo_id>/mod-revisions", methods=["GET"])
def list_wo_mod_revisions(wo_id):
    authenticate()
    require_role("AuditManager", "Underwriter")
    wo = load_wo(wo_id)
    limit, offset = parse_pagination()
    items = [m for m in mod_revisions.values()
             if m["source_work_order_id"] == wo["id"]]
    items = [db.serialize(m) for m in db.by_created(items)]
    return ok_list(items, limit, offset)


@bp.route("/audit-work-orders/<wo_id>/records-requests", methods=["GET"])
def list_wo_records(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    return _scoped_list(wo_id, services.records_of_wo(wo_id) if wo_id in work_orders else [])


@bp.route("/audit-work-orders/<wo_id>/appointments", methods=["GET"])
def list_wo_appointments(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    return _scoped_list(wo_id, services.appointments_of_wo(wo_id) if wo_id in work_orders else [])


@bp.route("/audit-work-orders/<wo_id>/payroll-allocations", methods=["GET"])
def list_wo_allocations(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    return _scoped_list(wo_id, services.allocations_of_wo(wo_id) if wo_id in work_orders else [])


@bp.route("/audit-work-orders/<wo_id>/subcontractor-exposures", methods=["GET"])
def list_wo_exposures(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager")
    return _scoped_list(wo_id, services.exposures_of_wo(wo_id) if wo_id in work_orders else [])


@bp.route("/audit-work-orders/<wo_id>/result", methods=["GET"])
def get_wo_result(wo_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    wo = load_wo(wo_id)
    insured_owns(wo)
    limit, offset = parse_pagination()
    res = services.result_of_wo(wo)
    items = [db.serialize(res)] if res else []
    return ok_list(items, limit, offset)


# --- actions ----------------------------------------------------------------------

@bp.route("/audit-work-orders/<wo_id>/assign", methods=["POST"])
def assign_auditor(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"auditor_id"})
    auditor_id = req_str(body, "auditor_id")
    require_role("AuditManager")
    wo = load_wo(wo_id)
    auditor = auditors.get(auditor_id)
    if auditor is None:
        raise_err("ERR_AUDITOR_NOT_FOUND", "Auditor id does not exist")
    if wo["status"] not in ("SELECTED", "RECORDS_REQUESTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Assignment allowed only from SELECTED or RECORDS_REQUESTED")
    policy = policies.get(wo["policy_id"])
    if policy and policy["state_code"] not in auditor["territory_states"]:
        raise_err("ERR_AUDITOR_TERRITORY_MISMATCH",
                  "Auditor territory does not include the policy state")
    wo["assigned_auditor_id"] = auditor_id
    db.touch(wo)
    return ok(db.serialize(wo))


@bp.route("/audit-work-orders/<wo_id>/records-requests", methods=["POST"])
def create_records_request(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"request_type"})
    rtype = req_enum(body, "request_type", REQUEST_TYPES)
    require_role("AuditManager")
    wo = load_wo(wo_id)
    if wo["status"] not in ("SELECTED", "RECORDS_REQUESTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Records requests allowed only from SELECTED or RECORDS_REQUESTED")
    for rr in services.records_of_wo(wo["id"]):
        if rr["request_type"] == rtype and rr["status"] in ("OPEN", "OVERDUE"):
            raise_err("ERR_DUPLICATE_RECORDS_REQUEST",
                      "A non-terminal request of this type exists")
    requested = db.now_iso()
    due = db.fmt_dt(db.clock_now() + timedelta(days=services.RECORDS_DUE_DAYS))
    rr = db.new_entity({
        "audit_work_order_id": wo["id"],
        "request_type": rtype,
        "status": "OPEN",
        "requested_at": requested,
        "due_at": due,
        "received_at": None,
    })
    records_requests[rr["id"]] = rr
    if wo["status"] == "SELECTED":
        wo["status"] = "RECORDS_REQUESTED"
    db.touch(wo)
    return created(db.serialize(rr))


@bp.route("/audit-work-orders/<wo_id>/appointments", methods=["POST"])
def create_appointment(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"scheduled_start", "scheduled_end", "location_type",
                         "expected_work_order_version"})
    start_s = req_dt(body, "scheduled_start")
    end_s = req_dt(body, "scheduled_end")
    location = req_enum(body, "location_type", LOCATION_TYPES)
    expected_version = req_int(body, "expected_work_order_version")
    start = db.parse_dt(start_s)
    end = db.parse_dt(end_s)
    if end <= start:
        validation("scheduled_end must be strictly after scheduled_start")
    require_role("Auditor")
    wo = load_wo(wo_id)
    auditor_assigned(wo)
    if wo["status"] not in ("RECORDS_REQUESTED", "APPOINTMENT_SCHEDULED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Appointments allowed only from RECORDS_REQUESTED or "
                  "APPOINTMENT_SCHEDULED")
    if wo["audit_type"] not in ("PHYSICAL", "REAUDIT"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only PHYSICAL or REAUDIT work orders take appointments")
    if expected_version != wo["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_work_order_version does not match current version")
    period_end = db.parse_dt(wo["audit_period_end"])
    window_end = period_end + timedelta(days=services.APPOINTMENT_WINDOW_DAYS)
    if not (start > period_end and start <= window_end):
        raise_err("ERR_APPOINTMENT_OUTSIDE_WINDOW",
                  "scheduled_start not within (audit_period_end, "
                  "audit_period_end + 60 days]")
    if wo["no_show_count"] >= 2:
        raise_err("ERR_RESCHEDULE_LIMIT_EXCEEDED",
                  "Reschedule limit reached (no_show_count >= 2)")
    auditor_id = wo["assigned_auditor_id"]
    for appt in appointments.values():
        if appt["auditor_id"] != auditor_id:
            continue
        if appt["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if appt["audit_work_order_id"] == wo["id"]:
            continue  # incumbent is superseded, not a conflict
        ex_start = db.parse_dt(appt["scheduled_start"])
        ex_end = db.parse_dt(appt["scheduled_end"])
        if start < ex_end and ex_start < end:
            raise_err("ERR_APPOINTMENT_OVERLAP",
                      "Overlaps another active appointment of this auditor")
    for appt in services.appointments_of_wo(wo["id"]):
        if appt["status"] in ("SCHEDULED", "CONFIRMED"):
            appt["status"] = "CANCELLED"
            db.touch(appt)
    ent = db.new_entity({
        "audit_work_order_id": wo["id"],
        "auditor_id": auditor_id,
        "scheduled_start": start_s,
        "scheduled_end": end_s,
        "location_type": location,
        "status": "SCHEDULED",
    })
    appointments[ent["id"]] = ent
    wo["status"] = "APPOINTMENT_SCHEDULED"
    db.touch(wo)
    return created(db.serialize(ent))


@bp.route("/audit-work-orders/<wo_id>/payroll-allocations", methods=["POST"])
def create_allocation(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, {
        "class_code_id", "period_start", "period_end", "gross_payroll_dollars",
        "overtime_excess_dollars", "overtime_documented", "severance_dollars",
        "other_exclusions_dollars", "expected_work_order_version",
    })
    class_code_id = req_str(body, "class_code_id")
    period_start_s = req_dt(body, "period_start")
    period_end_s = req_dt(body, "period_end")
    gross = req_int(body, "gross_payroll_dollars", min_value=0)
    overtime_excess = opt_int(body, "overtime_excess_dollars", 0, min_value=0)
    overtime_documented = opt_bool(body, "overtime_documented", False)
    severance = opt_int(body, "severance_dollars", 0, min_value=0)
    other_excl = opt_int(body, "other_exclusions_dollars", 0, min_value=0)
    expected_version = req_int(body, "expected_work_order_version")
    if db.parse_dt(period_start_s) >= db.parse_dt(period_end_s):
        validation("period_start must be strictly before period_end")
    require_role("Auditor")
    wo = load_wo(wo_id)
    auditor_assigned(wo)
    cc = class_codes.get(class_code_id)
    if cc is None:
        raise_err("ERR_CLASS_CODE_NOT_FOUND",
                  "ClassificationCode id does not exist")
    policy = policies.get(wo["policy_id"])
    if policy and cc["coverage_line"] != policy["coverage_line"]:
        validation("class code coverage_line must equal the policy coverage_line")
    if wo["status"] not in services.ALLOC_MUTATION_WO_STATES:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Allocations not allowed in the work order's current state")
    if expected_version != wo["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_work_order_version does not match current version")
    new_start = db.parse_dt(period_start_s)
    new_end = db.parse_dt(period_end_s)
    for a in services.allocations_of_wo(wo["id"]):
        if a["class_code_id"] != class_code_id or a["status"] == "REJECTED":
            continue
        ex_start = db.parse_dt(a["period_start"])
        ex_end = db.parse_dt(a["period_end"])
        if new_start <= ex_end and ex_start <= new_end:
            raise_err("ERR_ALLOCATION_PERIOD_OVERLAP",
                      "Overlapping period for the same class code")
    excludable_ot = overtime_excess if overtime_documented else 0
    auditable = max(gross - excludable_ot - severance - other_excl, 0)
    ent = db.new_entity({
        "audit_work_order_id": wo["id"],
        "class_code_id": class_code_id,
        "period_start": period_start_s,
        "period_end": period_end_s,
        "gross_payroll_dollars": gross,
        "overtime_excess_dollars": overtime_excess,
        "overtime_documented": overtime_documented,
        "severance_dollars": severance,
        "other_exclusions_dollars": other_excl,
        "auditable_payroll_dollars": auditable,
        "status": "DRAFT",
    })
    allocations[ent["id"]] = ent
    db.touch(wo)
    services.recompute_wo_base(wo)
    return created(db.serialize(ent))


@bp.route("/audit-work-orders/<wo_id>/subcontractor-exposures", methods=["POST"])
def create_exposure(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"subcontractor_name", "payments_dollars",
                         "governing_class_code_id"})
    name = req_str(body, "subcontractor_name")
    payments = req_int(body, "payments_dollars", min_value=0)
    governing_id = req_str(body, "governing_class_code_id")
    require_role("Auditor")
    wo = load_wo(wo_id)
    auditor_assigned(wo)
    cc = class_codes.get(governing_id)
    if cc is None:
        raise_err("ERR_CLASS_CODE_NOT_FOUND",
                  "ClassificationCode id does not exist")
    if wo["status"] not in services.ALLOC_MUTATION_WO_STATES:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Exposures not allowed in the work order's current state")
    ent = db.new_entity({
        "audit_work_order_id": wo["id"],
        "subcontractor_name": name,
        "payments_dollars": payments,
        "governing_class_code_id": governing_id,
        "included_dollars": payments,
        "status": "INCLUDED",
    })
    exposures[ent["id"]] = ent
    services.recompute_wo_base(wo)
    return created(db.serialize(ent))


@bp.route("/audit-work-orders/<wo_id>/submit-draft", methods=["POST"])
def submit_draft(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Auditor")
    wo = load_wo(wo_id)
    auditor_assigned(wo)
    if wo["audit_type"] in ("PHYSICAL", "REAUDIT"):
        if wo["status"] != "FIELD_WORK_DONE":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "PHYSICAL/REAUDIT orders draft from FIELD_WORK_DONE")
    else:
        if wo["status"] != "RECORDS_REQUESTED":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "VOLUNTARY_REPORT orders draft from RECORDS_REQUESTED")
    for rr in services.records_of_wo(wo["id"]):
        if rr["status"] in ("OPEN", "OVERDUE"):
            raise_err("ERR_OPEN_RECORDS_REQUESTS",
                      "All records requests must be RECEIVED or WAIVED")
    figures = services.compute_figures(wo, "provisional")
    ent = db.new_entity({
        "audit_work_order_id": wo["id"],
        "variant": "STANDARD",
        "status": "PRELIMINARY",
        "total_payroll_dollars": figures["total_payroll_dollars"],
        "manual_premium_cents": figures["manual_premium_cents"],
        "mod_factor_applied": figures["mod_factor_applied"],
        "earned_premium_cents": figures["earned_premium_cents"],
        "adjustment_cents": None,
        "drafted_by_user_id": Ctx.user_id,
        "issued_by_user_id": None,
        "issued_at": None,
    })
    results[ent["id"]] = ent
    wo["status"] = "RESULT_DRAFTED"
    db.touch(wo)
    return created(db.serialize(ent))


@bp.route("/audit-work-orders/<wo_id>/issue-result", methods=["POST"])
def issue_result(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    wo = load_wo(wo_id)
    if wo["status"] != "RESULT_DRAFTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Issuance allowed only from RESULT_DRAFTED")
    for a in services.allocations_of_wo(wo["id"]):
        if a["status"] == "DRAFT":
            raise_err("ERR_DRAFT_ALLOCATIONS_PENDING",
                      "Resolve DRAFT payroll allocations before issuance")
    policy = policies.get(wo["policy_id"])
    result = services.result_of_wo(wo)
    if result is None:
        raise_err("ERR_INVALID_STATE_TRANSITION", "No draft result exists")
    figures = services.compute_figures(wo, "final")
    result["total_payroll_dollars"] = figures["total_payroll_dollars"]
    result["manual_premium_cents"] = figures["manual_premium_cents"]
    result["mod_factor_applied"] = figures["mod_factor_applied"]
    result["earned_premium_cents"] = figures["earned_premium_cents"]
    result["adjustment_cents"] = \
        figures["earned_premium_cents"] - policy["estimated_annual_premium_cents"]
    result["status"] = "ISSUED"
    result["issued_by_user_id"] = Ctx.user_id
    result["issued_at"] = db.now_iso()
    db.touch(result)
    services.create_billing_for_result(result, policy)
    services.maybe_create_mod_revision(result, wo, policy)
    wo["status"] = "BILLED"
    db.touch(wo)
    return ok(db.serialize(result))


@bp.route("/audit-work-orders/<wo_id>/mark-noncompliant", methods=["POST"])
def mark_noncompliant(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    wo = load_wo(wo_id)
    if wo["status"] not in ("RECORDS_REQUESTED", "APPOINTMENT_SCHEDULED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Non-compliance flag allowed only from RECORDS_REQUESTED or "
                  "APPOINTMENT_SCHEDULED")
    if not any(rr["status"] == "OVERDUE"
               for rr in services.records_of_wo(wo["id"])):
        raise_err("ERR_NO_NONCOMPLIANCE_BASIS",
                  "No OVERDUE records request on this work order")
    wo["status"] = "NONCOMPLIANT_PENDING"
    wo["marked_noncompliant_by_user_id"] = Ctx.user_id
    db.touch(wo)
    return ok(db.serialize(wo))


@bp.route("/audit-work-orders/<wo_id>/approve-estimated", methods=["POST"])
def approve_estimated(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    wo = load_wo(wo_id)
    if wo["marked_noncompliant_by_user_id"] is not None and \
            Ctx.user_id == wo["marked_noncompliant_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "Approver must differ from the non-compliance marker")
    if wo["status"] != "NONCOMPLIANT_PENDING":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Estimated approval allowed only from NONCOMPLIANT_PENDING")
    policy = policies.get(wo["policy_id"])
    from decimal import Decimal
    earned = services.round_half_up(
        Decimal(policy["estimated_annual_premium_cents"])
        * services.ESTIMATED_AUDIT_MULTIPLIER)
    ent = db.new_entity({
        "audit_work_order_id": wo["id"],
        "variant": "ESTIMATED_NONCOMPLIANCE",
        "status": "ISSUED",
        "total_payroll_dollars": 0,
        "manual_premium_cents": 0,
        "mod_factor_applied": policy["experience_mod_factor"],
        "earned_premium_cents": earned,
        "adjustment_cents": earned - policy["estimated_annual_premium_cents"],
        "drafted_by_user_id": None,
        "issued_by_user_id": Ctx.user_id,
        "issued_at": db.now_iso(),
    })
    results[ent["id"]] = ent
    services.create_billing_for_result(ent, policy)
    wo["status"] = "ESTIMATED_BILLED"
    db.touch(wo)
    return ok(db.serialize(ent))


@bp.route("/audit-work-orders/<wo_id>/close", methods=["POST"])
def close_work_order(wo_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    wo = load_wo(wo_id)
    if wo["status"] not in ("BILLED", "ESTIMATED_BILLED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Close allowed only from BILLED or ESTIMATED_BILLED")
    result = services.result_of_wo(wo)
    if result is not None:
        for b in services.billings_of_result(result["id"]):
            if b["status"] not in ("PAID", "APPLIED"):
                raise_err("ERR_INVALID_STATE_TRANSITION",
                          "Billing transactions must be settled before close")
        deadline = db.parse_dt(result["issued_at"]) + \
            timedelta(days=services.DISPUTE_WINDOW_DAYS)
        if not db.clock_now() > deadline:
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Dispute window has not elapsed")
    wo["status"] = "CLOSED"
    db.touch(wo)
    policy = policies.get(wo["policy_id"])
    if policy is not None and policy["status"] == "AUDIT_PENDING":
        still_open = any(
            other["policy_id"] == policy["id"]
            and other["status"] not in services.WO_TERMINAL
            for other in work_orders.values())
        if not still_open:
            policy["status"] = "AUDIT_FINALIZED"
            db.touch(policy)
    return ok(db.serialize(wo))
