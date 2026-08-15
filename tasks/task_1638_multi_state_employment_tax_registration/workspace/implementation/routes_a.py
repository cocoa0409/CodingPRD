"""Routes: clock, Employer, TaxAgency, ReciprocityAgreement, WorkLocation,
Employee, NexusCase."""
from flask import Blueprint, request

from core import (
    db,
    err,
    new_record,
    touch,
    ok_object,
    ok_data,
    ok_list,
    body,
    missing,
    require_field,
    get_int,
    get_str,
    get_enum,
    get_bool,
    get_dt,
    lookup,
    require_roles,
    require_owner,
    paginate,
    filter_records,
    parse_bool_arg,
    ALL_ROLES,
    fmt_dt,
)
from domain import (
    recompute_employer,
    recompute_nexus_case,
    auto_assignment,
    terminate_employee,
    agreement_status,
    run_sweep,
    MONITORED_NEXUS_STATUSES,
)

bp = Blueprint("routes_a", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@bp.post("/etax/_clock/set_current_utc")
def set_clock():
    require_roles("TaxDirector")
    b = body()
    to = get_dt(b, "to_iso8601", required=True)
    if to < db.clock:
        err("ERR_INVALID_REQUEST", "The logical clock never moves backward")
    db.clock = to
    run_sweep()
    return ok_data({"current_utc": fmt_dt(db.clock)})


# ---------------------------------------------------------------------------
# Employer (singleton)
# ---------------------------------------------------------------------------
@bp.post("/etax/employers")
def create_employer():
    require_roles("TaxDirector")
    b = body()
    # Priority 11: singleton check precedes general sanity (priority 31)
    if db.employer_id is not None:
        err("ERR_EMPLOYER_ALREADY_EXISTS", "The Employer singleton already exists")
    legal_name = require_field(b, "legal_name")
    fein = require_field(b, "fein")
    home_state = require_field(b, "home_state_code")
    if not isinstance(legal_name, str) or not legal_name.strip():
        err("ERR_INVALID_REQUEST", "legal_name must be a non-empty string")
    if not isinstance(fein, str) or len(fein) != 9 or not fein.isdigit():
        err("ERR_INVALID_REQUEST", "fein must be exactly 9 digits")
    if not isinstance(home_state, str) or not home_state.strip():
        err("ERR_INVALID_REQUEST", "home_state_code must be a non-empty string")
    rec = new_record(
        db.employers,
        {
            "legal_name": legal_name,
            "fein": fein,
            "home_state_code": home_state,
            "compliance_posture": "GOOD_STANDING",
            "open_notice_count": 0,
            "outstanding_penalty_cents": 0,
            "registered_state_count": 0,
        },
    )
    db.employer_id = rec["id"]
    return ok_object(rec, 201)


@bp.get("/etax/employers/<eid>")
def get_employer(eid):
    require_roles(*ALL_ROLES)
    rec = lookup(db.employers, eid)
    return ok_object(rec)


# ---------------------------------------------------------------------------
# TaxAgency catalog
# ---------------------------------------------------------------------------
@bp.post("/etax/tax-agencies")
def create_agency():
    require_roles("TaxDirector")
    b = body()
    # Priority 12 duplicate check (raw triple) precedes general sanity
    kind_raw = b.get("agency_kind")
    state_raw = b.get("state_code")
    locality_raw = b.get("locality_code")
    for ag in db.agencies.values():
        if (
            ag.get("is_active", True)
            and ag["agency_kind"] == kind_raw
            and ag["state_code"] == state_raw
            and ag.get("locality_code") == locality_raw
        ):
            err(
                "ERR_DUPLICATE_AGENCY",
                "An active TaxAgency with the same kind, state and locality exists",
            )
    kind = get_enum(
        b, "agency_kind", ["STATE_WITHHOLDING", "STATE_UI", "LOCAL"], required=True
    )
    state = get_str(b, "state_code", required=True)
    name = get_str(b, "agency_name", required=True)
    locality = b.get("locality_code")
    if locality is not None and not isinstance(locality, str):
        err("ERR_INVALID_REQUEST", "locality_code must be a string or null")
    rec = new_record(
        db.agencies,
        {
            "agency_kind": kind,
            "state_code": state,
            "locality_code": locality,
            "agency_name": name,
            "withholding_rate_bp": get_int(b, "withholding_rate_bp"),
            "resident_rate_bp": get_int(b, "resident_rate_bp"),
            "nonresident_rate_bp": get_int(b, "nonresident_rate_bp"),
            "precedence_rank": get_int(b, "precedence_rank") if not missing(b, "precedence_rank") else 100,
            "new_employer_rate_bp": get_int(b, "new_employer_rate_bp"),
            "solvency_surcharge_bp": get_int(b, "solvency_surcharge_bp") if not missing(b, "solvency_surcharge_bp") else 0,
            "ui_wage_base_cents": get_int(b, "ui_wage_base_cents"),
            "is_active": get_bool(b, "is_active", True),
        },
    )
    return ok_object(rec, 201)


@bp.get("/etax/tax-agencies")
def list_agencies():
    require_roles(*ALL_ROLES)
    is_active = parse_bool_arg("is_active")
    filters = [
        ("agency_kind", request.args.get("agency_kind")),
        ("state_code", request.args.get("state_code")),
    ]
    recs = filter_records(db.agencies, filters)
    if is_active is not None:
        recs = [r for r in recs if r.get("is_active", True) == is_active]
    page, total, limit, offset = paginate(recs)
    return ok_list(page, total, limit, offset)


@bp.get("/etax/tax-agencies/<aid>")
def get_agency(aid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.agencies, aid))


# ---------------------------------------------------------------------------
# ReciprocityAgreement catalog
# ---------------------------------------------------------------------------
@bp.post("/etax/reciprocity-agreements")
def create_agreement():
    require_roles("TaxDirector")
    b = body()
    from_raw = b.get("effective_from")
    to_raw = b.get("effective_to")
    ef = None
    et = None
    if from_raw is not None:
        from core import try_parse_dt

        ef = try_parse_dt(from_raw)
    if to_raw is not None:
        from core import try_parse_dt

        et = try_parse_dt(to_raw)
    # Priority 5 date sanity: inverted range
    if ef is not None and et is not None and et < ef:
        err("ERR_INVALID_DATE_RANGE", "effective_to must not precede effective_from")
    # Priority 17 closed-interval overlap on the same unordered pair
    sa, sb = b.get("state_a"), b.get("state_b")
    if sa is not None and sb is not None and ef is not None:
        for ag in db.agreements.values():
            if {ag["state_a"], ag["state_b"]} != {sa, sb}:
                continue
            prior_from = ag["effective_from"]
            prior_to = ag["effective_to"]
            new_to = et
            # Disjoint only when new.from > prior.to or new.to < prior.from
            overlaps = True
            if new_to is not None and new_to < prior_from:
                overlaps = False
            if prior_to is not None and ef > prior_to:
                overlaps = False
            if overlaps:
                err(
                    "ERR_AGREEMENT_OVERLAP",
                    "Closed date ranges for the same state pair share a day",
                )
    state_a = get_str(b, "state_a", required=True)
    state_b = get_str(b, "state_b", required=True)
    scope = get_enum(b, "scope", ["FULL", "WAGES_ONLY"], required=True)
    if ef is None:
        ef = get_dt(b, "effective_from", required=True)
    cert = b.get("certificate_form_code")
    if cert is not None and not isinstance(cert, str):
        err("ERR_INVALID_REQUEST", "certificate_form_code must be a string or null")
    rec = new_record(
        db.agreements,
        {
            "state_a": state_a,
            "state_b": state_b,
            "effective_from": ef,
            "effective_to": et,
            "certificate_form_code": cert,
            "scope": scope,
            "status": "SCHEDULED",
        },
    )
    rec["status"] = agreement_status(rec, db.clock)
    return ok_object(rec, 201)


@bp.get("/etax/reciprocity-agreements")
def list_agreements():
    require_roles(*ALL_ROLES)
    filters = [
        ("state_a", request.args.get("state_a")),
        ("state_b", request.args.get("state_b")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.agreements, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/reciprocity-agreements/<aid>")
def get_agreement(aid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.agreements, aid))


# ---------------------------------------------------------------------------
# WorkLocation
# ---------------------------------------------------------------------------
@bp.post("/etax/work-locations")
def create_location():
    require_roles("NexusAnalyst")
    b = body()
    rec = new_record(
        db.locations,
        {
            "label": get_str(b, "label", required=True),
            "address_line1": get_str(b, "address_line1", required=True),
            "city": get_str(b, "city", required=True),
            "state_code": get_str(b, "state_code", required=True),
            "postal_code": get_str(b, "postal_code", required=True),
            "location_type": get_enum(
                b,
                "location_type",
                ["COMPANY_OFFICE", "REMOTE_HOME", "CLIENT_SITE"],
                required=True,
            ),
            "is_active": get_bool(b, "is_active", True),
        },
    )
    return ok_object(rec, 201)


@bp.get("/etax/work-locations")
def list_locations():
    require_roles(*ALL_ROLES)
    is_active = parse_bool_arg("is_active")
    recs = filter_records(db.locations, [("state_code", request.args.get("state_code"))])
    if is_active is not None:
        recs = [r for r in recs if r.get("is_active", True) == is_active]
    page, total, limit, offset = paginate(recs)
    return ok_list(page, total, limit, offset)


@bp.get("/etax/work-locations/<lid>")
def get_location(lid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.locations, lid))


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
@bp.post("/etax/employees")
def create_employee():
    require_roles("NexusAnalyst")
    b = body()
    # Priority 3: body FK existence
    loc_id = b.get("current_work_location_id")
    if loc_id is not None:
        loc = lookup(db.locations, loc_id)
    else:
        loc = None
    # employee_ref uniqueness (contract-level; no dedicated error id)
    ref = b.get("employee_ref")
    if ref is not None and any(e["employee_ref"] == ref for e in db.employees.values()):
        err("ERR_INVALID_REQUEST", "employee_ref must be unique")
    employee_ref = get_str(b, "employee_ref", required=True)
    full_name = get_str(b, "full_name", required=True)
    resident_state = get_str(b, "resident_state_code", required=True)
    resident_locality = b.get("resident_locality_code")
    if resident_locality is not None and not isinstance(resident_locality, str):
        err("ERR_INVALID_REQUEST", "resident_locality_code must be a string or null")
    hire_date = get_dt(b, "hire_date", required=True)
    wage = get_int(b, "annual_wage_cents", required=True)
    if wage <= 0:
        err("ERR_INVALID_REQUEST", "annual_wage_cents must be greater than zero")
    if loc is None:
        err("ERR_INVALID_REQUEST", "current_work_location_id is required")
    rec = new_record(
        db.employees,
        {
            "employee_ref": employee_ref,
            "full_name": full_name,
            "resident_state_code": resident_state,
            "resident_locality_code": resident_locality,
            "hire_date": hire_date,
            "annual_wage_cents": wage,
            "status": "ACTIVE",
            "current_work_location_id": loc["id"],
            "termination_date": None,
        },
    )
    # Auto-create the initial LocalAssignment (AUTO_GEOCODE from hire_date)
    auto_assignment(rec, loc, hire_date)
    return ok_object(rec, 201)


@bp.get("/etax/employees")
def list_employees():
    require_roles(*ALL_ROLES)
    filters = [
        ("status", request.args.get("status")),
        ("resident_state_code", request.args.get("resident_state_code")),
        ("current_work_location_id", request.args.get("current_work_location_id")),
    ]
    page, total, limit, offset = paginate(filter_records(db.employees, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/employees/<eid>")
def get_employee(eid):
    user_id, role = require_roles(*ALL_ROLES)
    rec = lookup(db.employees, eid)
    if role == "Employee":
        require_owner(user_id, rec["id"])
    return ok_object(rec)


@bp.post("/etax/employees/<eid>/terminate")
def terminate(eid):
    require_roles("NexusAnalyst")
    emp = lookup(db.employees, eid)
    # Priority 6: from-state
    if emp["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "Employee is not ACTIVE")
    # Priority 15: open location change blocks termination
    for lc in db.location_changes.values():
        if lc["employee_id"] == emp["id"] and lc["status"] in (
            "PENDING_REVIEW",
            "APPROVED",
        ):
            err(
                "ERR_LOCATION_CHANGE_PENDING",
                "Employee has a LocationChange in PENDING_REVIEW or APPROVED",
            )
    b = body()
    term_date = get_dt(b, "termination_date", required=True)
    terminate_employee(emp, term_date)
    return ok_object(emp)


# ---------------------------------------------------------------------------
# NexusCase
# ---------------------------------------------------------------------------
@bp.post("/etax/nexus-cases")
def create_nexus_case():
    require_roles("NexusAnalyst")
    b = body()
    state_raw = b.get("state_code")
    # Priority 13 duplicate check precedes general sanity
    if state_raw is not None:
        for c in db.nexus_cases.values():
            if c["state_code"] == state_raw and c["status"] in MONITORED_NEXUS_STATUSES:
                err(
                    "ERR_DUPLICATE_NEXUS_CASE",
                    "A NexusCase for this state already exists in a monitored status",
                )
    state = get_str(b, "state_code", required=True)
    rec = new_record(
        db.nexus_cases,
        {
            "state_code": state,
            "status": "WATCH",
            "employee_days_ytd": 0,
            "employee_days_trailing_90d": 0,
            "wages_ytd_cents": 0,
            "threshold_basis": "NONE",
            "established_date": None,
            "exempt_reason": None,
            "last_recomputed_at": db.clock,
        },
    )
    # Initial recompute (may enter THRESHOLD_MET immediately)
    recompute_nexus_case(rec)
    return ok_object(rec, 201)


@bp.get("/etax/nexus-cases")
def list_nexus_cases():
    require_roles(*ALL_ROLES)
    filters = [
        ("state_code", request.args.get("state_code")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.nexus_cases, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/nexus-cases/<cid>")
def get_nexus_case(cid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.nexus_cases, cid))


@bp.post("/etax/nexus-cases/<cid>/recompute")
def recompute_case(cid):
    require_roles("NexusAnalyst")
    case = lookup(db.nexus_cases, cid)
    recompute_nexus_case(case)
    return ok_object(case)


@bp.post("/etax/nexus-cases/<cid>/confirm")
def confirm_case(cid):
    require_roles("NexusAnalyst")
    case = lookup(db.nexus_cases, cid)
    if case["status"] != "THRESHOLD_MET":
        err("ERR_INVALID_STATE_TRANSITION", "NexusCase is not THRESHOLD_MET")
    case["status"] = "CONFIRMED"
    case["established_date"] = db.clock
    touch(case)
    recompute_employer()
    return ok_object(case)


@bp.post("/etax/nexus-cases/<cid>/exempt")
def exempt_case(cid):
    require_roles("TaxDirector")
    case = lookup(db.nexus_cases, cid)
    if case["status"] not in ("WATCH", "THRESHOLD_MET"):
        err("ERR_INVALID_STATE_TRANSITION", "NexusCase is not WATCH or THRESHOLD_MET")
    b = body()
    reason = get_str(b, "exempt_reason", required=True)
    case["status"] = "EXEMPT"
    case["exempt_reason"] = reason
    touch(case)
    recompute_employer()
    return ok_object(case)
