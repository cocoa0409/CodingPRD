"""Routes: UIRate, VoluntaryContribution, LocationChange, FilingObligation,
AgencyNotice, AbatementRequest."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    db,
    err,
    new_record,
    touch,
    ok_object,
    ok_list,
    body,
    missing,
    get_str,
    get_enum,
    get_int,
    get_dt,
    lookup,
    check_occ,
    require_roles,
    require_owner,
    paginate,
    filter_records,
    ALL_ROLES,
    try_parse_dt,
)
from domain import (
    d,
    recompute_employer,
    recompute_ui_rate,
    vc_projection,
    ui_contribution_amount,
    late_penalty,
    compute_severity,
    abatement_eligibility,
    effectuate_location_change,
    reverse_location_change,
    ABATEMENT_WINDOW_DAYS,
)

bp = Blueprint("routes_c", __name__)


# ---------------------------------------------------------------------------
# UIRate
# ---------------------------------------------------------------------------
@bp.post("/etax/ui-rates")
def create_ui_rate():
    require_roles("UISpecialist")
    b = body()
    reg = None
    if not missing(b, "registration_id"):
        reg = lookup(db.registrations, b["registration_id"])
    # Priority 6: registration must be ACTIVE
    if reg is not None and reg["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not ACTIVE")
    # Priority 7: OCC on Registration version
    if missing(b, "expected_registration_version"):
        err("ERR_INVALID_REQUEST", "Missing required field: expected_registration_version")
    if reg is None:
        err("ERR_NOT_FOUND", "registration_id does not resolve to a Registration")
    check_occ(b, "expected_registration_version", reg["version"])
    # Priority 18: kind fitness
    if reg["registration_kind"] != "STATE_UI":
        err("ERR_AGENCY_KIND_MISMATCH", "UIRate intake requires a STATE_UI registration")
    rate_year = get_int(b, "rate_year", required=True)
    exp_rated = b.get("experience_rated")
    if not isinstance(exp_rated, bool):
        err("ERR_INVALID_REQUEST", "experience_rated must be a boolean")
    assigned = get_int(b, "assigned_rate_bp", required=True)
    contrib = get_int(b, "contributions_paid_3yr_cents", required=True, minimum=0)
    benefits = get_int(b, "benefits_charged_3yr_cents", required=True, minimum=0)
    payroll = get_int(b, "taxable_payroll_3yr_cents", required=True)
    if payroll <= 0:
        err("ERR_INVALID_REQUEST", "taxable_payroll_3yr_cents must be greater than zero")
    # Supersede any existing rate for the same registration + rate_year
    for r in db.ui_rates.values():
        if (
            r["registration_id"] == reg["id"]
            and r["rate_year"] == rate_year
            and r["status"] in ("RECEIVED", "UNDER_REVIEW", "CONTESTED", "EFFECTIVE")
        ):
            r["status"] = "SUPERSEDED"
            touch(r)
    rec = new_record(
        db.ui_rates,
        {
            "registration_id": reg["id"],
            "rate_year": rate_year,
            "experience_rated": exp_rated,
            "assigned_rate_bp": assigned,
            "contributions_paid_3yr_cents": contrib,
            "benefits_charged_3yr_cents": benefits,
            "taxable_payroll_3yr_cents": payroll,
            "voluntary_contribution_applied_cents": 0,
            "reserve_ratio_bp": None,
            "final_rate_bp": None,
            "status": "RECEIVED",
            "contest_reason": None,
            "received_date": db.clock,
        },
    )
    recompute_ui_rate(rec)
    # Intake increments the Registration's version by one
    touch(reg)
    return ok_object(rec, 201)


@bp.get("/etax/ui-rates")
def list_ui_rates():
    require_roles(*ALL_ROLES)
    filters = [
        ("registration_id", request.args.get("registration_id")),
        ("rate_year", request.args.get("rate_year")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.ui_rates, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/ui-rates/<rid>")
def get_ui_rate(rid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.ui_rates, rid))


@bp.post("/etax/ui-rates/<rid>/review")
def review_ui_rate(rid):
    require_roles("UISpecialist")
    rate = lookup(db.ui_rates, rid)
    if rate["status"] not in ("RECEIVED", "CONTESTED"):
        err("ERR_INVALID_STATE_TRANSITION", "UIRate is not RECEIVED or CONTESTED")
    rate["status"] = "UNDER_REVIEW"
    touch(rate)
    return ok_object(rate)


@bp.post("/etax/ui-rates/<rid>/contest")
def contest_ui_rate(rid):
    require_roles("UISpecialist")
    rate = lookup(db.ui_rates, rid)
    if rate["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "UIRate is not UNDER_REVIEW")
    b = body()
    reason = get_str(b, "contest_reason", required=True)
    rate["status"] = "CONTESTED"
    rate["contest_reason"] = reason
    touch(rate)
    return ok_object(rate)


@bp.post("/etax/ui-rates/<rid>/make_effective")
def make_effective_ui_rate(rid):
    require_roles("UISpecialist")
    rate = lookup(db.ui_rates, rid)
    if rate["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "UIRate is not UNDER_REVIEW")
    rate["status"] = "EFFECTIVE"
    touch(rate)
    # Recompute SCHEDULED UI_CONTRIBUTION obligations for the rate year
    reg = db.registrations[rate["registration_id"]]
    agency = db.agencies[reg["agency_id"]]
    for o in db.obligations.values():
        if (
            o["registration_id"] == reg["id"]
            and o["obligation_kind"] == "UI_CONTRIBUTION"
            and o["status"] == "SCHEDULED"
            and d(o["period_start"]).year == rate["rate_year"]
        ):
            new_amt = ui_contribution_amount(
                reg, agency, d(o["period_start"]), d(o["period_end"])
            )
            if new_amt != o["amount_due_cents"]:
                o["amount_due_cents"] = new_amt
                touch(o)
    return ok_object(rate)


# ---------------------------------------------------------------------------
# VoluntaryContribution
# ---------------------------------------------------------------------------
@bp.post("/etax/voluntary-contributions")
def create_vc():
    user_id, _role = require_roles("UISpecialist")
    b = body()
    rate = None
    if not missing(b, "ui_rate_id"):
        rate = lookup(db.ui_rates, b["ui_rate_id"])
    # Priority 5: decision_deadline strictly in the future
    deadline = None
    if not missing(b, "decision_deadline"):
        deadline = try_parse_dt(b["decision_deadline"])
        if deadline is None:
            err("ERR_INVALID_REQUEST", "decision_deadline must be an ISO-8601 datetime")
        if deadline <= db.clock:
            err("ERR_INVALID_DATE_RANGE", "decision_deadline must be strictly in the future")
    # Priority 6: rate must be EFFECTIVE
    if rate is not None and rate["status"] != "EFFECTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "UIRate is not EFFECTIVE")
    if rate is None:
        err("ERR_INVALID_REQUEST", "ui_rate_id is required")
    # Priority 22: new-employer accounts reject voluntary contributions
    if not rate["experience_rated"]:
        err(
            "ERR_VC_NOT_ALLOWED_NEW_EMPLOYER",
            "Voluntary contributions are prohibited for new-employer accounts",
        )
    proposed = b.get("proposed_amount_cents")
    if isinstance(proposed, bool) or proposed is not None and not isinstance(proposed, int):
        err("ERR_INVALID_REQUEST", "proposed_amount_cents must be an integer")
    if proposed is not None and proposed <= 0:
        err("ERR_INVALID_REQUEST", "proposed_amount_cents must be greater than zero")
    if proposed is None:
        err("ERR_INVALID_REQUEST", "Missing required field: proposed_amount_cents")
    # Priority 27: projection must yield strictly positive net savings
    reg = db.registrations[rate["registration_id"]]
    agency = db.agencies[reg["agency_id"]]
    r_without, r_with, _wages, savings = vc_projection(rate, reg, agency, proposed)
    if savings <= 0:
        err("ERR_NO_NET_SAVINGS", "Projection yields no positive net savings")
    if deadline is None:
        err("ERR_INVALID_REQUEST", "Missing required field: decision_deadline")
    rec = new_record(
        db.vcs,
        {
            "ui_rate_id": rate["id"],
            "proposed_amount_cents": proposed,
            "decision_deadline": deadline,
            "projected_rate_without_vc_bp": r_without,
            "projected_rate_with_vc_bp": r_with,
            "projected_net_savings_cents": savings,
            "status": "PROPOSED",
            "proposed_by_user_id": user_id,
            "approved_by_user_id": None,
            "remitted_at": None,
        },
    )
    return ok_object(rec, 201)


@bp.get("/etax/voluntary-contributions")
def list_vcs():
    require_roles(*ALL_ROLES)
    filters = [
        ("ui_rate_id", request.args.get("ui_rate_id")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.vcs, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/voluntary-contributions/<vid>")
def get_vc(vid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.vcs, vid))


@bp.post("/etax/voluntary-contributions/<vid>/approve")
def approve_vc(vid):
    user_id, _role = require_roles("TaxDirector")
    vc = lookup(db.vcs, vid)
    if vc["status"] != "PROPOSED":
        err("ERR_INVALID_STATE_TRANSITION", "VoluntaryContribution is not PROPOSED")
    # Priority 9: employer posture gate
    employer = db.employers.get(db.employer_id) if db.employer_id else None
    posture = employer["compliance_posture"] if employer else "GOOD_STANDING"
    if posture == "DELINQUENT":
        err("ERR_COMPANY_POSTURE_DELINQUENT", "Employer compliance posture is DELINQUENT")
    # Priority 10: segregation of duties
    if user_id == vc["proposed_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from proposer")
    vc["status"] = "APPROVED"
    vc["approved_by_user_id"] = user_id
    touch(vc)
    return ok_object(vc)


@bp.post("/etax/voluntary-contributions/<vid>/decline")
def decline_vc(vid):
    require_roles("TaxDirector")
    vc = lookup(db.vcs, vid)
    if vc["status"] not in ("PROPOSED", "APPROVED"):
        err("ERR_INVALID_STATE_TRANSITION", "VoluntaryContribution is not PROPOSED or APPROVED")
    vc["status"] = "DECLINED"
    touch(vc)
    return ok_object(vc)


@bp.post("/etax/voluntary-contributions/<vid>/remit")
def remit_vc(vid):
    require_roles("UISpecialist")
    vc = lookup(db.vcs, vid)
    if vc["status"] != "APPROVED":
        err("ERR_INVALID_STATE_TRANSITION", "VoluntaryContribution is not APPROVED")
    # Priority 24: exact deadline allowed
    if db.clock > vc["decision_deadline"]:
        err("ERR_DEADLINE_PASSED", "The decision deadline has passed")
    vc["status"] = "REMITTED"
    vc["remitted_at"] = db.clock
    touch(vc)
    return ok_object(vc)


@bp.post("/etax/voluntary-contributions/<vid>/apply")
def apply_vc(vid):
    require_roles("UISpecialist")
    vc = lookup(db.vcs, vid)
    if vc["status"] != "REMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "VoluntaryContribution is not REMITTED")
    rate = db.ui_rates[vc["ui_rate_id"]]
    # Priority 23: rate must still be EFFECTIVE
    if rate["status"] != "EFFECTIVE":
        err("ERR_RATE_SUPERSEDED", "The linked UIRate is no longer EFFECTIVE")
    rate["voluntary_contribution_applied_cents"] += vc["proposed_amount_cents"]
    recompute_ui_rate(rate)
    touch(rate)
    # Open UI_CONTRIBUTION obligations for the rate year recompute
    reg = db.registrations[rate["registration_id"]]
    agency = db.agencies[reg["agency_id"]]
    for o in db.obligations.values():
        if (
            o["registration_id"] == reg["id"]
            and o["obligation_kind"] == "UI_CONTRIBUTION"
            and o["status"] in ("SCHEDULED", "DUE")
            and d(o["period_start"]).year == rate["rate_year"]
        ):
            new_amt = ui_contribution_amount(
                reg, agency, d(o["period_start"]), d(o["period_end"])
            )
            if new_amt != o["amount_due_cents"]:
                o["amount_due_cents"] = new_amt
                touch(o)
    vc["status"] = "APPLIED"
    touch(vc)
    return ok_object(vc)


# ---------------------------------------------------------------------------
# LocationChange
# ---------------------------------------------------------------------------
@bp.post("/etax/location-changes")
def create_location_change():
    user_id, role = require_roles("Employee")
    b = body()
    emp = None
    to_loc = None
    if not missing(b, "employee_id"):
        emp = lookup(db.employees, b["employee_id"])
    if not missing(b, "to_work_location_id"):
        to_loc = lookup(db.locations, b["to_work_location_id"])
    # Priority 4: ownership
    require_owner(user_id, b.get("employee_id"))
    # Priority 6 tier: terminated employee
    if emp is not None and emp["status"] != "ACTIVE":
        err("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is TERMINATED")
    if emp is None:
        err("ERR_NOT_FOUND", "employee_id does not resolve to an Employee")
    # Priority 15: one open change per employee
    for lc in db.location_changes.values():
        if lc["employee_id"] == emp["id"] and lc["status"] in ("PENDING_REVIEW", "APPROVED"):
            err(
                "ERR_LOCATION_CHANGE_PENDING",
                "Employee already has a LocationChange in PENDING_REVIEW or APPROVED",
            )
    if to_loc is None:
        err("ERR_INVALID_REQUEST", "to_work_location_id is required")
    if not to_loc.get("is_active", True):
        err("ERR_INVALID_REQUEST", "Target work location is inactive")
    eff = get_dt(b, "effective_date", required=True)
    reason = get_str(b, "reason", required=True)
    cur_loc = db.locations.get(emp["current_work_location_id"])
    snapshot = {
        "work_location_id": emp["current_work_location_id"],
        "state_code": cur_loc["state_code"] if cur_loc else None,
        "label": cur_loc["label"] if cur_loc else None,
    }
    rec = new_record(
        db.location_changes,
        {
            "employee_id": emp["id"],
            "to_work_location_id": to_loc["id"],
            "from_location_snapshot": snapshot,
            "effective_date": eff,
            "reason": reason,
            "status": "PENDING_REVIEW",
            "submitted_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "impact_summary": None,
            "rejection_reason": None,
        },
    )
    return ok_object(rec, 201)


@bp.get("/etax/location-changes")
def list_location_changes():
    require_roles(*ALL_ROLES)
    filters = [
        ("employee_id", request.args.get("employee_id")),
        ("to_work_location_id", request.args.get("to_work_location_id")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.location_changes, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/location-changes/<cid>")
def get_location_change(cid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.location_changes, cid))


@bp.patch("/etax/location-changes/<cid>")
def patch_location_change(cid):
    require_roles("NexusAnalyst")
    lc = lookup(db.location_changes, cid)
    b = body()
    # Body FK existence (priority 3, left to right after path)
    new_loc = None
    if not missing(b, "to_work_location_id"):
        new_loc = lookup(db.locations, b["to_work_location_id"])
    # Priority 6: only PENDING_REVIEW is editable
    if lc["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "LocationChange is not PENDING_REVIEW")
    # Priority 7: OCC on the change's own version
    check_occ(b, "expected_location_change_version", lc["version"])
    if new_loc is not None and not new_loc.get("is_active", True):
        err("ERR_INVALID_REQUEST", "Target work location is inactive")
    if not missing(b, "effective_date"):
        eff = get_dt(b, "effective_date")
        lc["effective_date"] = eff
    if new_loc is not None:
        lc["to_work_location_id"] = new_loc["id"]
    if not missing(b, "reason"):
        reason = b["reason"]
        if not isinstance(reason, str) or not reason.strip():
            err("ERR_INVALID_REQUEST", "reason must be a non-empty string")
        lc["reason"] = reason
    touch(lc)
    return ok_object(lc)


@bp.post("/etax/location-changes/<cid>/approve")
def approve_location_change(cid):
    user_id, _role = require_roles("NexusAnalyst")
    lc = lookup(db.location_changes, cid)
    # Priority 6: from-state first, then employee activity (same tier)
    if lc["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "LocationChange is not PENDING_REVIEW")
    emp = db.employees.get(lc["employee_id"])
    if emp is None:
        err("ERR_NOT_FOUND", "Employee no longer exists")
    if emp["status"] != "ACTIVE":
        err("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is TERMINATED")
    # Priority 10: segregation of duties
    if user_id == lc["submitted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter")
    # General: destination must be active
    to_loc = db.locations.get(lc["to_work_location_id"])
    if to_loc is None or not to_loc.get("is_active", True):
        err("ERR_INVALID_REQUEST", "Target work location is inactive")
    old_state = lc["from_location_snapshot"]["state_code"]
    new_state = to_loc["state_code"]
    if old_state == new_state:
        summary = f"Nexus recompute cascades: {old_state}"
    else:
        summary = f"Nexus recompute cascades: {old_state}, {new_state}"
    lc["status"] = "APPROVED"
    lc["reviewed_by_user_id"] = user_id
    lc["impact_summary"] = summary
    touch(lc)
    return ok_object(lc)


@bp.post("/etax/location-changes/<cid>/reject")
def reject_location_change(cid):
    require_roles("NexusAnalyst")
    lc = lookup(db.location_changes, cid)
    if lc["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "LocationChange is not PENDING_REVIEW")
    b = body()
    reason = get_str(b, "rejection_reason", required=True)
    lc["status"] = "REJECTED"
    lc["rejection_reason"] = reason
    touch(lc)
    return ok_object(lc)


@bp.post("/etax/location-changes/<cid>/cancel")
def cancel_location_change(cid):
    user_id, role = require_roles("Employee")
    lc = lookup(db.location_changes, cid)
    require_owner(user_id, lc["employee_id"])
    if lc["status"] not in ("PENDING_REVIEW", "APPROVED"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "LocationChange is not PENDING_REVIEW or APPROVED",
        )
    lc["status"] = "CANCELLED"
    touch(lc)
    return ok_object(lc)


@bp.post("/etax/location-changes/<cid>/reverse")
def reverse_change(cid):
    require_roles("TaxDirector")
    lc = lookup(db.location_changes, cid)
    if lc["status"] != "EFFECTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "LocationChange is not EFFECTIVE")
    reverse_location_change(lc)
    return ok_object(lc)


# ---------------------------------------------------------------------------
# FilingObligation
# ---------------------------------------------------------------------------
@bp.get("/etax/filing-obligations")
def list_obligations():
    require_roles(*ALL_ROLES)
    filters = [
        ("registration_id", request.args.get("registration_id")),
        ("status", request.args.get("status")),
        ("obligation_kind", request.args.get("obligation_kind")),
    ]
    page, total, limit, offset = paginate(filter_records(db.obligations, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/filing-obligations/<oid>")
def get_obligation(oid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.obligations, oid))


@bp.post("/etax/filing-obligations/<oid>/file")
def file_obligation(oid):
    user_id, _role = require_roles("PayrollComplianceLead")
    ob = lookup(db.obligations, oid)
    if ob["status"] not in ("DUE", "LATE"):
        err("ERR_INVALID_STATE_TRANSITION", "Obligation is not DUE or LATE")
    b = body()
    filed_at = db.clock
    if not missing(b, "filed_at"):
        parsed = try_parse_dt(b["filed_at"])
        if parsed is None:
            err("ERR_INVALID_REQUEST", "filed_at must be an ISO-8601 datetime")
        filed_at = parsed
    if filed_at > db.clock:
        err("ERR_INVALID_REQUEST", "filed_at may not lie in the future")
    was_late = ob["status"] == "LATE"
    # Finalize late_days: 0 when filed on/before due_date
    if filed_at.date() <= d(ob["due_date"]):
        final_late_days = 0
    else:
        final_late_days = (filed_at.date() - d(ob["due_date"])).days
    ob["late_days"] = final_late_days
    ob["amount_paid_cents"] = ob["amount_due_cents"]
    ob["filed_at"] = filed_at
    ob["filed_by_user_id"] = user_id
    ob["status"] = "FILED"
    touch(ob)
    if was_late:
        # Final penalty recompute updates the same notice in place
        notice_id = ob.get("_late_notice_id")
        if notice_id is not None:
            notice = db.notices.get(notice_id)
            if notice is not None:
                penalty = late_penalty(ob["amount_due_cents"], final_late_days)
                if notice["penalty_amount_cents"] != penalty:
                    notice["penalty_amount_cents"] = penalty
                    notice["severity"] = compute_severity(
                        notice["notice_type"], penalty
                    )
                    touch(notice)
        recompute_employer()
    return ok_object(ob)


@bp.post("/etax/filing-obligations/<oid>/confirm")
def confirm_obligation(oid):
    user_id, _role = require_roles("PayrollComplianceLead")
    ob = lookup(db.obligations, oid)
    if ob["status"] != "FILED":
        err("ERR_INVALID_STATE_TRANSITION", "Obligation is not FILED")
    if user_id == ob.get("filed_by_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES", "Confirmer must differ from filer")
    ob["status"] = "CONFIRMED"
    ob["confirmed_by_user_id"] = user_id
    touch(ob)
    return ok_object(ob)


# ---------------------------------------------------------------------------
# AgencyNotice
# ---------------------------------------------------------------------------
NOTICE_TYPES = [
    "PENALTY_ASSESSMENT",
    "RATE_NOTICE",
    "MISSING_RETURN",
    "ACCOUNT_INQUIRY",
    "AUDIT",
]


@bp.post("/etax/agency-notices")
def create_notice():
    require_roles("PayrollComplianceLead")
    b = body()
    # Priority 3: body FK existence
    reg = None
    obl = None
    if not missing(b, "registration_id"):
        reg = lookup(db.registrations, b["registration_id"])
    if not missing(b, "filing_obligation_id"):
        obl = lookup(db.obligations, b["filing_obligation_id"])
    # Priority 5: response_due_date >= received_date
    received = None
    due = None
    if not missing(b, "received_date"):
        received = try_parse_dt(b["received_date"])
        if received is None:
            err("ERR_INVALID_REQUEST", "received_date must be an ISO-8601 date/datetime")
    if not missing(b, "response_due_date"):
        due = try_parse_dt(b["response_due_date"])
        if due is None:
            err(
                "ERR_INVALID_REQUEST",
                "response_due_date must be an ISO-8601 date/datetime",
            )
    if received is not None and due is not None and due < received:
        err(
            "ERR_INVALID_DATE_RANGE",
            "response_due_date must not be earlier than received_date",
        )
    # General sanity
    ntype = get_enum(b, "notice_type", NOTICE_TYPES, required=True)
    if received is None:
        received = get_dt(b, "received_date", required=True)
    if due is None:
        due = get_dt(b, "response_due_date", required=True)
    if reg is None and obl is None:
        err(
            "ERR_INVALID_REQUEST",
            "At least one of registration_id or filing_obligation_id is required",
        )
    penalty = get_int(b, "penalty_amount_cents") if not missing(b, "penalty_amount_cents") else 0
    if penalty < 0:
        err("ERR_INVALID_REQUEST", "penalty_amount_cents must be zero or more")
    rec = new_record(
        db.notices,
        {
            "registration_id": reg["id"] if reg else None,
            "filing_obligation_id": obl["id"] if obl else None,
            "notice_type": ntype,
            "received_date": received,
            "response_due_date": due,
            "penalty_amount_cents": penalty,
            "abated_amount_cents": 0,
            "status": "RECEIVED",
            "severity": compute_severity(ntype, penalty),
            "resolution_notes": None,
        },
    )
    recompute_employer()
    return ok_object(rec, 201)


@bp.get("/etax/agency-notices")
def list_notices():
    require_roles(*ALL_ROLES)
    filters = [
        ("registration_id", request.args.get("registration_id")),
        ("filing_obligation_id", request.args.get("filing_obligation_id")),
        ("status", request.args.get("status")),
        ("notice_type", request.args.get("notice_type")),
    ]
    page, total, limit, offset = paginate(filter_records(db.notices, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/agency-notices/<nid>")
def get_notice(nid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.notices, nid))


@bp.post("/etax/agency-notices/<nid>/triage")
def triage_notice(nid):
    require_roles("PayrollComplianceLead")
    n = lookup(db.notices, nid)
    if n["status"] != "RECEIVED":
        err("ERR_INVALID_STATE_TRANSITION", "Notice is not RECEIVED")
    n["status"] = "TRIAGED"
    touch(n)
    return ok_object(n)


@bp.post("/etax/agency-notices/<nid>/escalate")
def escalate_notice(nid):
    require_roles("PayrollComplianceLead")
    n = lookup(db.notices, nid)
    if n["status"] not in ("TRIAGED", "RESPONSE_IN_PROGRESS"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "Notice is not TRIAGED or RESPONSE_IN_PROGRESS",
        )
    n["status"] = "ESCALATED"
    touch(n)
    recompute_employer()
    return ok_object(n)


@bp.post("/etax/agency-notices/<nid>/resolve")
def resolve_notice(nid):
    require_roles("PayrollComplianceLead")
    n = lookup(db.notices, nid)
    if n["status"] not in ("TRIAGED", "RESPONSE_IN_PROGRESS", "ESCALATED"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "Notice is not TRIAGED, RESPONSE_IN_PROGRESS or ESCALATED",
        )
    # Priority 29: blocked while a linked abatement is non-terminal
    for a in db.abatements.values():
        if a["agency_notice_id"] == n["id"] and a["status"] in (
            "DRAFT",
            "SUBMITTED",
            "UNDER_REVIEW",
        ):
            err("ERR_ABATEMENT_PENDING", "A linked AbatementRequest is non-terminal")
    b = body()
    notes = get_str(b, "resolution_notes", required=True)
    n["status"] = "RESOLVED"
    n["resolution_notes"] = notes
    touch(n)
    recompute_employer()
    return ok_object(n)


@bp.post("/etax/agency-notices/<nid>/close")
def close_notice(nid):
    require_roles("TaxDirector")
    n = lookup(db.notices, nid)
    if n["status"] != "RESOLVED":
        err("ERR_INVALID_STATE_TRANSITION", "Notice is not RESOLVED")
    n["status"] = "CLOSED"
    touch(n)
    recompute_employer()
    return ok_object(n)


# ---------------------------------------------------------------------------
# AbatementRequest
# ---------------------------------------------------------------------------
ABATEMENT_TYPES = ["FIRST_TIME", "REASONABLE_CAUSE", "STATUTORY"]
TERMINAL_NOTICE_STATUSES = {"RESOLVED", "CLOSED"}


@bp.post("/etax/abatement-requests")
def create_abatement():
    user_id, _role = require_roles("PayrollComplianceLead")
    b = body()
    notice = None
    if not missing(b, "agency_notice_id"):
        notice = lookup(db.notices, b["agency_notice_id"])
    if notice is None:
        err("ERR_INVALID_REQUEST", "agency_notice_id is required")
    # Notice must be a PENALTY_ASSESSMENT
    if notice["notice_type"] != "PENALTY_ASSESSMENT":
        err("ERR_INVALID_REQUEST", "Abatements apply only to PENALTY_ASSESSMENT notices")
    # Notice must be non-terminal
    if notice["status"] in TERMINAL_NOTICE_STATUSES:
        err("ERR_INVALID_STATE_TRANSITION", "The linked notice is terminal")
    atype = get_enum(b, "abatement_type", ABATEMENT_TYPES, required=True)
    requested = b.get("requested_amount_cents")
    if isinstance(requested, bool) or requested is not None and not isinstance(requested, int):
        err("ERR_INVALID_REQUEST", "requested_amount_cents must be an integer")
    outstanding = notice["penalty_amount_cents"] - notice["abated_amount_cents"]
    # Priority 26: requested must not exceed the outstanding penalty
    if requested is not None and requested > outstanding:
        err("ERR_AMOUNT_EXCEEDS_PENALTY", "requested_amount_cents exceeds the outstanding penalty")
    if requested is None:
        err("ERR_INVALID_REQUEST", "Missing required field: requested_amount_cents")
    if requested <= 0:
        err("ERR_INVALID_REQUEST", "requested_amount_cents must be greater than zero")
    reason = get_str(b, "reason", required=True)
    if atype == "REASONABLE_CAUSE" and len(reason) < 20:
        err(
            "ERR_INVALID_REQUEST",
            "REASONABLE_CAUSE reason must run at least twenty characters",
        )
    prior_count, eligible = abatement_eligibility(notice, atype)
    rec = new_record(
        db.abatements,
        {
            "agency_notice_id": notice["id"],
            "abatement_type": atype,
            "requested_amount_cents": requested,
            "reason": reason,
            "eligible_amount_cents": eligible,
            "prior_penalty_count_3yr": prior_count,
            "status": "DRAFT",
            "prepared_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "submitted_at": None,
            "decided_at": None,
            "granted_amount_cents": None,
        },
    )
    # Drafting moves the notice to RESPONSE_IN_PROGRESS from RECEIVED or TRIAGED
    if notice["status"] in ("RECEIVED", "TRIAGED"):
        notice["status"] = "RESPONSE_IN_PROGRESS"
        touch(notice)
    return ok_object(rec, 201)


@bp.get("/etax/abatement-requests")
def list_abatements():
    require_roles(*ALL_ROLES)
    filters = [
        ("agency_notice_id", request.args.get("agency_notice_id")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.abatements, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/abatement-requests/<aid>")
def get_abatement(aid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.abatements, aid))


@bp.post("/etax/abatement-requests/<aid>/submit")
def submit_abatement(aid):
    require_roles("PayrollComplianceLead")
    a = lookup(db.abatements, aid)
    if a["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "AbatementRequest is not DRAFT")
    notice = db.notices[a["agency_notice_id"]]
    # Priority 25: sixty-day submission window (day 60 allowed)
    if db.clock.date() > d(notice["received_date"]) + timedelta(days=ABATEMENT_WINDOW_DAYS):
        err("ERR_ABATEMENT_WINDOW_CLOSED", "The sixty-day abatement window has closed")
    # Priority 28: eligibility gate
    if a["eligible_amount_cents"] <= 0:
        err("ERR_ABATEMENT_NOT_ELIGIBLE", "eligible_amount_cents is zero")
    a["status"] = "SUBMITTED"
    a["submitted_at"] = db.clock
    touch(a)
    return ok_object(a)


@bp.post("/etax/abatement-requests/<aid>/review")
def review_abatement(aid):
    user_id, _role = require_roles("TaxDirector")
    a = lookup(db.abatements, aid)
    if a["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "AbatementRequest is not SUBMITTED")
    if user_id == a["prepared_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Reviewer must differ from preparer")
    a["status"] = "UNDER_REVIEW"
    a["reviewed_by_user_id"] = user_id
    touch(a)
    return ok_object(a)


@bp.post("/etax/abatement-requests/<aid>/decide")
def decide_abatement(aid):
    require_roles("TaxDirector")
    a = lookup(db.abatements, aid)
    if a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "AbatementRequest is not UNDER_REVIEW")
    b = body()
    decision = get_enum(b, "decision", ["GRANTED", "PARTIALLY_GRANTED", "DENIED"], required=True)
    granted_present = not missing(b, "granted_amount_cents")
    granted = None
    if decision == "GRANTED":
        if granted_present:
            err(
                "ERR_INVALID_REQUEST",
                "granted_amount_cents must be omitted when decision is GRANTED",
            )
        granted = a["eligible_amount_cents"]
    elif decision == "PARTIALLY_GRANTED":
        if not granted_present:
            err(
                "ERR_INVALID_REQUEST",
                "granted_amount_cents is required for PARTIALLY_GRANTED",
            )
        granted = b["granted_amount_cents"]
        if isinstance(granted, bool) or not isinstance(granted, int):
            err("ERR_INVALID_REQUEST", "granted_amount_cents must be an integer")
        if granted < 1 or granted >= a["eligible_amount_cents"]:
            err(
                "ERR_INVALID_REQUEST",
                "granted_amount_cents must be >= 1 and < eligible_amount_cents",
            )
    else:  # DENIED
        if granted_present:
            err(
                "ERR_INVALID_REQUEST",
                "granted_amount_cents must be omitted when decision is DENIED",
            )
        granted = 0
    a["status"] = decision
    a["granted_amount_cents"] = granted
    a["decided_at"] = db.clock
    touch(a)
    if granted > 0:
        notice = db.notices[a["agency_notice_id"]]
        notice["abated_amount_cents"] += granted
        touch(notice)
        # Linked LATE obligation is waived when the outstanding penalty hits 0
        obl_id = notice.get("filing_obligation_id")
        outstanding = notice["penalty_amount_cents"] - notice["abated_amount_cents"]
        if obl_id and outstanding == 0:
            obl = db.obligations.get(obl_id)
            if obl is not None and obl["status"] == "LATE":
                obl["status"] = "WAIVED"
                touch(obl)
    recompute_employer()
    return ok_object(a)


@bp.post("/etax/abatement-requests/<aid>/withdraw")
def withdraw_abatement(aid):
    require_roles("PayrollComplianceLead")
    a = lookup(db.abatements, aid)
    if a["status"] not in ("DRAFT", "SUBMITTED"):
        err("ERR_INVALID_STATE_TRANSITION", "AbatementRequest is not DRAFT or SUBMITTED")
    a["status"] = "WITHDRAWN"
    touch(a)
    return ok_object(a)
