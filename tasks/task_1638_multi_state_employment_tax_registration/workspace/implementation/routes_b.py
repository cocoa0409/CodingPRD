"""Routes: Registration, WithholdingElection, LocalAssignment."""
from datetime import date, timedelta

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
    get_bool,
    get_dt,
    get_int,
    lookup,
    check_occ,
    require_roles,
    require_owner,
    paginate,
    filter_records,
    ALL_ROLES,
)
from domain import (
    recompute_employer,
    generate_calendar,
    compute_deposit_tier,
    apply_next_day_due_dates,
    classify_frequency,
    quarter_bounds,
    resolve_jurisdiction,
    create_assignment,
    truncate_open_segment,
    OPEN_NOTICE_STATUSES,
)

bp = Blueprint("routes_b", __name__)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@bp.post("/etax/registrations")
def create_registration():
    require_roles("NexusAnalyst")
    b = body()
    # Priority 3: agency FK existence
    agency = None
    if not missing(b, "agency_id"):
        agency = lookup(db.agencies, b["agency_id"])
    # Priority 7: OCC on Employer version
    employer = db.employers.get(db.employer_id) if db.employer_id else None
    if missing(b, "expected_employer_version"):
        err("ERR_INVALID_REQUEST", "Missing required field: expected_employer_version")
    if employer is None:
        err("ERR_NOT_FOUND", "The Employer singleton does not exist")
    check_occ(b, "expected_employer_version", employer["version"])
    # Priority 14: one non-CLOSED registration per agency
    if agency is not None:
        for r in db.registrations.values():
            if r["agency_id"] == agency["id"] and r["status"] != "CLOSED":
                err(
                    "ERR_DUPLICATE_REGISTRATION",
                    "A non-CLOSED Registration for this agency already exists",
                )
    if agency is None:
        err("ERR_INVALID_REQUEST", "agency_id is required")
    projected = get_int(b, "projected_annual_withholding_cents", required=True)
    if projected < 0:
        err(
            "ERR_INVALID_REQUEST",
            "projected_annual_withholding_cents must be zero or more",
        )
    rec = new_record(
        db.registrations,
        {
            "agency_id": agency["id"],
            "registration_kind": agency["agency_kind"],
            "state_code": agency["state_code"],
            "account_number": None,
            "status": "DRAFT",
            "filing_frequency": None,
            "deposit_tier": None,
            "frequency_basis": None,
            "projected_annual_withholding_cents": projected,
            "lookback_liability_cents": 0,
            "rejection_reason": None,
            "submitted_at": None,
            "activated_at": None,
            "closed_at": None,
        },
    )
    # Creation increments the Employer's version by one
    touch(employer)
    recompute_employer()
    return ok_object(rec, 201)


@bp.get("/etax/registrations")
def list_registrations():
    require_roles(*ALL_ROLES)
    filters = [
        ("agency_id", request.args.get("agency_id")),
        ("status", request.args.get("status")),
        ("state_code", request.args.get("state_code")),
    ]
    page, total, limit, offset = paginate(filter_records(db.registrations, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/registrations/<rid>")
def get_registration(rid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.registrations, rid))


@bp.post("/etax/registrations/<rid>/submit")
def submit_registration(rid):
    require_roles("NexusAnalyst")
    reg = lookup(db.registrations, rid)
    # Priority 6: from-state
    if reg["status"] not in ("DRAFT", "REJECTED"):
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not DRAFT or REJECTED")
    # Priority 8: nexus must be CONFIRMED for the registration's state
    confirmed = any(
        c["state_code"] == reg["state_code"] and c["status"] == "CONFIRMED"
        for c in db.nexus_cases.values()
    )
    if not confirmed:
        err(
            "ERR_NEXUS_NOT_CONFIRMED",
            "The NexusCase for this state is not CONFIRMED",
        )
    reg["status"] = "SUBMITTED"
    reg["submitted_at"] = db.clock
    reg["rejection_reason"] = None
    touch(reg)
    return ok_object(reg)


@bp.post("/etax/registrations/<rid>/reject")
def reject_registration(rid):
    require_roles("NexusAnalyst")
    reg = lookup(db.registrations, rid)
    if reg["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not SUBMITTED")
    b = body()
    reason = get_str(b, "rejection_reason", required=True)
    reg["status"] = "REJECTED"
    reg["rejection_reason"] = reason
    touch(reg)
    return ok_object(reg)


@bp.post("/etax/registrations/<rid>/activate")
def activate_registration(rid):
    require_roles("NexusAnalyst")
    reg = lookup(db.registrations, rid)
    if reg["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not SUBMITTED")
    b = body()
    account = get_str(b, "account_number", required=True)
    reg["account_number"] = account
    reg["activated_at"] = db.clock
    reg["status"] = "ACTIVE"
    # Provisional deposit schedule (STATE_UI forced QUARTERLY)
    if reg["registration_kind"] == "STATE_UI":
        reg["filing_frequency"] = "QUARTERLY"
    else:
        reg["filing_frequency"] = classify_frequency(
            reg["projected_annual_withholding_cents"]
        )
    reg["frequency_basis"] = "PROVISIONAL"
    generate_calendar(reg, db.clock)
    reg["deposit_tier"] = compute_deposit_tier(reg)
    if reg["deposit_tier"] == "NEXT_DAY":
        apply_next_day_due_dates(reg)
    touch(reg)
    recompute_employer()
    return ok_object(reg)


@bp.post("/etax/registrations/<rid>/close")
def close_registration(rid):
    require_roles("TaxDirector")
    reg = lookup(db.registrations, rid)
    if reg["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not ACTIVE")
    # Priority 30: settled book
    for o in db.obligations.values():
        if o["registration_id"] == reg["id"] and o["status"] in (
            "SCHEDULED",
            "DUE",
            "LATE",
        ):
            err(
                "ERR_REGISTRATION_NOT_SETTLED",
                "Registration has obligations in SCHEDULED, DUE or LATE",
            )
    reg_obligation_ids = {
        o["id"] for o in db.obligations.values() if o["registration_id"] == reg["id"]
    }
    for n in db.notices.values():
        linked = n.get("registration_id") == reg["id"] or (
            n.get("filing_obligation_id") in reg_obligation_ids
        )
        if linked and n["status"] in OPEN_NOTICE_STATUSES:
            err(
                "ERR_REGISTRATION_NOT_SETTLED",
                "Registration has unresolved notices",
            )
    reg["status"] = "CLOSED"
    reg["closed_at"] = db.clock
    touch(reg)
    recompute_employer()
    return ok_object(reg)


@bp.post("/etax/registrations/<rid>/recompute_schedule")
def recompute_schedule(rid):
    require_roles("NexusAnalyst")
    reg = lookup(db.registrations, rid)
    now_d = db.clock.date()
    # LOOKBACK variant: trailing 4 closed calendar quarters
    qs_cur, _qe_cur = quarter_bounds(now_d)
    start_month = ((qs_cur.month - 1) // 3) * 3 + 1  # first month of current quarter
    start_year = qs_cur.year
    # four closed quarters immediately preceding the current one
    end_year, end_month = start_year, start_month - 1
    if end_month == 0:
        end_year -= 1
        end_month = 12
    # last day of the quarter ending at (end_year, end_month)
    from domain import last_day_of_month

    lb_end = last_day_of_month(end_year, end_month)
    # start of 4 quarters back
    s_year, s_month = start_year, start_month - 12
    while s_month <= 0:
        s_month += 12
        s_year -= 1
    lb_start = date(s_year, s_month, 1)
    lookback = 0
    for o in db.obligations.values():
        if o["registration_id"] != reg["id"]:
            continue
        if o["obligation_kind"] not in ("WITHHOLDING_DEPOSIT", "WITHHOLDING_RETURN"):
            continue
        if o["status"] not in ("DUE", "LATE", "FILED", "CONFIRMED", "WAIVED"):
            continue
        pe = o["period_end"].date()
        if lb_start <= pe <= lb_end:
            lookback += o["amount_due_cents"]
    reg["lookback_liability_cents"] = lookback
    if reg["registration_kind"] == "STATE_UI":
        new_freq = "QUARTERLY"
    else:
        new_freq = classify_frequency(lookback)
    old_freq = reg.get("filing_frequency")
    reg["filing_frequency"] = new_freq
    reg["frequency_basis"] = "LOOKBACK"
    if old_freq is not None and new_freq != old_freq:
        # Frequency change: waive future SCHEDULED rows and regenerate
        for o in db.obligations.values():
            if o["registration_id"] == reg["id"] and o["status"] == "SCHEDULED":
                o["status"] = "WAIVED"
                o["_waive_reason"] = "FREQUENCY_CHANGE"
                touch(o)
        generate_calendar(reg, now_d)
    new_tier = compute_deposit_tier(reg)
    old_tier = reg.get("deposit_tier")
    reg["deposit_tier"] = new_tier
    if new_tier == "NEXT_DAY" and old_tier != "NEXT_DAY":
        apply_next_day_due_dates(reg)
    touch(reg)
    return ok_object(reg)


# ---------------------------------------------------------------------------
# WithholdingElection
# ---------------------------------------------------------------------------
ELECTION_TYPES = ["RECIPROCITY_EXEMPTION", "COURTESY_RESIDENT", "COURTESY_WORK"]


def _half_open_overlap(a_from, a_to, b_from, b_to):
    """[from, to) overlap; None 'to' is open-ended. Adjacency is allowed."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    if a_end is not None and a_end <= b_from:
        return False
    if b_end is not None and b_end <= a_from:
        return False
    return True


@bp.post("/etax/withholding-elections")
def create_election():
    user_id, role = require_roles("Employee", "NexusAnalyst")
    b = body()
    # Priority 3: employee FK existence
    emp = None
    if not missing(b, "employee_id"):
        emp = lookup(db.employees, b["employee_id"])
    # Priority 4: Employee-role ownership
    if role == "Employee":
        require_owner(user_id, b.get("employee_id"))
    # Priority 5: date sanity (half-open: effective_to strictly later)
    ef = None
    et = None
    if not missing(b, "effective_from"):
        from core import try_parse_dt

        ef = try_parse_dt(b["effective_from"])
    if not missing(b, "effective_to"):
        from core import try_parse_dt

        et = try_parse_dt(b["effective_to"])
        if et is None:
            err("ERR_INVALID_REQUEST", "effective_to must be an ISO-8601 date/datetime")
    if ef is not None and et is not None and et <= ef:
        err("ERR_INVALID_DATE_RANGE", "effective_to must be strictly later than effective_from")
    # Priority 7: OCC on Employee version
    if missing(b, "expected_employee_version"):
        err("ERR_INVALID_REQUEST", "Missing required field: expected_employee_version")
    if emp is None:
        err("ERR_NOT_FOUND", "employee_id does not resolve to an Employee")
    check_occ(b, "expected_employee_version", emp["version"])
    etype_raw = b.get("election_type")
    supersede = get_bool(b, "supersede_existing", False)
    # Priority 16: half-open overlap (same employee + type, active-ish statuses)
    if ef is not None and etype_raw is not None and not supersede:
        for el in db.elections.values():
            if (
                el["employee_id"] == emp["id"]
                and el["election_type"] == etype_raw
                and el["status"] in ("SUBMITTED", "VALIDATED", "ACTIVE")
                and _half_open_overlap(ef, et, el["effective_from"], el.get("effective_to"))
            ):
                err(
                    "ERR_ELECTION_OVERLAP",
                    "Overlaps a same-type election in SUBMITTED, VALIDATED or ACTIVE",
                )
    # Priority 19: work/resident semantics at creation
    work_state_raw = b.get("work_state_code")
    if work_state_raw is not None:
        if work_state_raw == emp["resident_state_code"]:
            err("ERR_INVALID_REQUEST", "work_state_code must differ from resident state")
        loc = db.locations.get(emp["current_work_location_id"])
        if loc is not None and work_state_raw != loc["state_code"]:
            err(
                "ERR_INVALID_REQUEST",
                "work_state_code must equal the state of the current work location",
            )
    # General sanity
    etype = get_enum(b, "election_type", ELECTION_TYPES, required=True)
    work_state = get_str(b, "work_state_code", required=True)
    if ef is None:
        ef = get_dt(b, "effective_from", required=True)
    cert = b.get("certificate_form_code")
    if cert is not None and not isinstance(cert, str):
        err("ERR_INVALID_REQUEST", "certificate_form_code must be a string or null")
    rec = new_record(
        db.elections,
        {
            "employee_id": emp["id"],
            "election_type": etype,
            "work_state_code": work_state,
            "resident_state_code": emp["resident_state_code"],
            "certificate_form_code": cert,
            "effective_from": ef,
            "effective_to": et,
            "status": "SUBMITTED",
            "supersedes_election_id": None,
            "submitted_by_user_id": user_id,
            "rejection_reason": None,
        },
    )
    if supersede:
        priors = [
            el
            for el in db.elections.values()
            if el["employee_id"] == emp["id"]
            and el["election_type"] == etype
            and el["status"] in ("VALIDATED", "ACTIVE")
            and el["id"] != rec["id"]
        ]
        priors.sort(key=lambda el: el["_seq"])
        for el in priors:
            el["status"] = "SUPERSEDED"
            touch(el)
        if priors:
            rec["supersedes_election_id"] = priors[-1]["id"]
    # Creation increments the Employee's version by one
    touch(emp)
    return ok_object(rec, 201)


@bp.get("/etax/withholding-elections")
def list_elections():
    require_roles(*ALL_ROLES)
    filters = [
        ("employee_id", request.args.get("employee_id")),
        ("status", request.args.get("status")),
        ("election_type", request.args.get("election_type")),
        ("supersedes_election_id", request.args.get("supersedes_election_id")),
    ]
    page, total, limit, offset = paginate(filter_records(db.elections, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/withholding-elections/<eid>")
def get_election(eid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.elections, eid))


@bp.post("/etax/withholding-elections/<eid>/validate")
def validate_election(eid):
    require_roles("NexusAnalyst")
    el = lookup(db.elections, eid)
    # Priority 6: from-state
    if el["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Election is not SUBMITTED")
    emp = db.employees.get(el["employee_id"])
    if emp is None:
        err("ERR_NOT_FOUND", "Employee no longer exists")
    # Priority 19: work/resident semantics
    if el["work_state_code"] == emp["resident_state_code"]:
        err("ERR_INVALID_REQUEST", "work_state_code must differ from resident state")
    loc = db.locations.get(emp["current_work_location_id"])
    if loc is None or el["work_state_code"] != loc["state_code"]:
        err(
            "ERR_INVALID_REQUEST",
            "work_state_code must equal the state of the current work location",
        )
    # Priority 20/21: per-type guards
    if el["election_type"] == "RECIPROCITY_EXEMPTION":
        covering = None
        for ag in db.agreements.values():
            if {ag["state_a"], ag["state_b"]} != {
                el["work_state_code"],
                emp["resident_state_code"],
            }:
                continue
            if ag["status"] != "ACTIVE":
                continue
            if ag["effective_from"] > el["effective_from"]:
                continue
            if ag["effective_to"] is not None and el["effective_from"] > ag["effective_to"]:
                continue
            covering = ag
            break
        if covering is None:
            err(
                "ERR_RECIPROCITY_NOT_AVAILABLE",
                "No ACTIVE ReciprocityAgreement covers the work/resident pair at effective_from",
            )
        if covering.get("certificate_form_code"):
            if el.get("certificate_form_code") != covering["certificate_form_code"]:
                err(
                    "ERR_INVALID_REQUEST",
                    "certificate_form_code does not match the covering agreement",
                )
    elif el["election_type"] in ("COURTESY_RESIDENT", "COURTESY_WORK"):
        target_state = (
            emp["resident_state_code"]
            if el["election_type"] == "COURTESY_RESIDENT"
            else el["work_state_code"]
        )
        found = False
        for r in db.registrations.values():
            if r["status"] != "ACTIVE":
                continue
            ag = db.agencies.get(r["agency_id"])
            if (
                ag is not None
                and ag["agency_kind"] == "STATE_WITHHOLDING"
                and ag["state_code"] == target_state
            ):
                found = True
                break
        if not found:
            err(
                "ERR_REGISTRATION_NOT_ACTIVE",
                "No ACTIVE STATE_WITHHOLDING registration for the target state",
            )
    if el["effective_from"] > db.clock:
        el["status"] = "VALIDATED"
    else:
        el["status"] = "ACTIVE"
    touch(el)
    return ok_object(el)


@bp.post("/etax/withholding-elections/<eid>/reject")
def reject_election(eid):
    require_roles("NexusAnalyst")
    el = lookup(db.elections, eid)
    if el["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Election is not SUBMITTED")
    b = body()
    reason = get_str(b, "rejection_reason", required=True)
    el["status"] = "REJECTED"
    el["rejection_reason"] = reason
    touch(el)
    return ok_object(el)


@bp.post("/etax/withholding-elections/<eid>/revoke")
def revoke_election(eid):
    user_id, role = require_roles("Employee", "NexusAnalyst")
    el = lookup(db.elections, eid)
    # Priority 4 ownership before state legality
    if role == "Employee":
        require_owner(user_id, el["employee_id"])
    if el["status"] not in ("VALIDATED", "ACTIVE"):
        err("ERR_INVALID_STATE_TRANSITION", "Election is not VALIDATED or ACTIVE")
    el["status"] = "REVOKED"
    touch(el)
    return ok_object(el)


# ---------------------------------------------------------------------------
# LocalAssignment
# ---------------------------------------------------------------------------
@bp.post("/etax/local-assignments/resolve")
def resolve_assignment():
    require_roles("NexusAnalyst")
    b = body()
    emp = None
    loc = None
    if not missing(b, "employee_id"):
        emp = lookup(db.employees, b["employee_id"])
    if not missing(b, "work_location_id"):
        loc = lookup(db.locations, b["work_location_id"])
    if emp is None:
        err("ERR_INVALID_REQUEST", "employee_id is required")
    if loc is None:
        err("ERR_INVALID_REQUEST", "work_location_id is required")
    if not loc.get("is_active", True):
        err("ERR_INVALID_REQUEST", "Target work location is inactive")
    ef = get_dt(b, "effective_from", required=True)
    rec = None
    work_id, resident_id, trace = resolve_jurisdiction(emp, loc)
    truncate_open_segment(emp["id"], ef)
    rec = create_assignment(emp, loc, ef, "AUTO_GEOCODE", work_id, resident_id, trace)
    return ok_object(rec, 201)


@bp.post("/etax/local-assignments/override")
def override_assignment():
    require_roles("TaxDirector")
    b = body()
    emp = None
    loc = None
    resident_ag = None
    work_ag = None
    if not missing(b, "employee_id"):
        emp = lookup(db.employees, b["employee_id"])
    if not missing(b, "work_location_id"):
        loc = lookup(db.locations, b["work_location_id"])
    if not missing(b, "resident_agency_id"):
        resident_ag = lookup(db.agencies, b["resident_agency_id"])
    if not missing(b, "work_agency_id"):
        work_ag = lookup(db.agencies, b["work_agency_id"])
    # Priority 7: OCC on Employee version
    if missing(b, "expected_employee_version"):
        err("ERR_INVALID_REQUEST", "Missing required field: expected_employee_version")
    if emp is None:
        err("ERR_NOT_FOUND", "employee_id does not resolve to an Employee")
    check_occ(b, "expected_employee_version", emp["version"])
    # Priority 18: named agencies must be LOCAL
    for ag in (resident_ag, work_ag):
        if ag is not None and ag["agency_kind"] != "LOCAL":
            err("ERR_AGENCY_KIND_MISMATCH", "Override agencies must be LOCAL")
    if loc is None:
        err("ERR_INVALID_REQUEST", "work_location_id is required")
    if not loc.get("is_active", True):
        err("ERR_INVALID_REQUEST", "Target work location is inactive")
    reason = get_str(b, "override_reason", required=True)
    ef = get_dt(b, "effective_from", required=True)
    truncate_open_segment(emp["id"], ef)
    rec = create_assignment(
        emp,
        loc,
        ef,
        "MANUAL_OVERRIDE",
        work_ag["id"] if work_ag else None,
        resident_ag["id"] if resident_ag else None,
        "MANUAL_OVERRIDE",
        override_reason=reason,
    )
    # Override increments the Employee's version by one
    touch(emp)
    return ok_object(rec, 201)


@bp.get("/etax/local-assignments")
def list_assignments():
    require_roles(*ALL_ROLES)
    filters = [
        ("employee_id", request.args.get("employee_id")),
        ("work_location_id", request.args.get("work_location_id")),
        ("resident_agency_id", request.args.get("resident_agency_id")),
        ("work_agency_id", request.args.get("work_agency_id")),
        ("status", request.args.get("status")),
    ]
    page, total, limit, offset = paginate(filter_records(db.assignments, filters))
    return ok_list(page, total, limit, offset)


@bp.get("/etax/local-assignments/<aid>")
def get_assignment(aid):
    require_roles(*ALL_ROLES)
    return ok_object(lookup(db.assignments, aid))
