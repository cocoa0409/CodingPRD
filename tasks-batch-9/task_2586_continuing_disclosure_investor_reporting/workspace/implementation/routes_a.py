"""Bond issues, undertakings, content requirements."""
from flask import Blueprint, g

import calc
import domain
from core import (ALL_ROLES, DB, HEADER_USER_ID, Obj, ROLE_DISCLOSURE_OFFICER,
                  ROLE_FINANCE_DIRECTOR, body, clock_date, clock_stamp,
                  endpoint, fail, listing, must_get, new_row, parse_date_str,
                  requirements_of, touch, undertaking_for_issue, vdate, venum,
                  vint, vstr, vbool, fk)

bp = Blueprint("routes_a", __name__)

SECURITY_TYPES = ("GENERAL_OBLIGATION", "REVENUE", "SPECIAL_ASSESSMENT")
RATING_AGENCIES = ("MOODYS", "SP", "FITCH", "KBRA")
REQUIREMENT_KINDS = ("AUDITED_FINANCIALS", "OPERATING_DATA_TABLE", "BUDGET_SUMMARY",
                     "DEBT_SERVICE_SCHEDULE", "ENTERPRISE_STATISTICS")
TIMELINESS_BASES = ("SUBMISSION_BASIS", "CONFIRMATION_BASIS")
PROGRAM_CODE_PATTERN = r"^[A-Z0-9\-]{1,32}$"
FISCAL_YEAR_END_PATTERN = r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"


# ------------------------------------------------------------------ bond issues
@bp.post("/disclosure/bond-issues")
@endpoint([ROLE_FINANCE_DIRECTOR])
def create_bond_issue():
    data = body()
    program_code = vstr(data, "issuer_program_code", max_len=32,
                        pattern=PROGRAM_CODE_PATTERN)
    series = vstr(data, "series_designation", max_len=16)
    security_type = venum(data, "security_type", SECURITY_TYPES)
    dated_date = vdate(data, "dated_date")
    final_maturity_date = vdate(data, "final_maturity_date")
    original_par = vint(data, "original_par_amount_cents", minimum=1)
    if not final_maturity_date > dated_date:
        fail("ERR_INVALID_REQUEST",
             "final_maturity_date must fall strictly after dated_date")
    row = new_row({
        "issuer_program_code": program_code,
        "series_designation": series,
        "security_type": security_type,
        "dated_date": dated_date.isoformat(),
        "final_maturity_date": final_maturity_date.isoformat(),
        "original_par_amount_cents": original_par,
        "outstanding_par_amount_cents": original_par,
        "status": "OUTSTANDING",
        "current_rating": None,
        "current_rating_agency": None,
        "defeasance_type": None,
        "escrow_deposit_cents": 0,
        "defeased_at": None,
        "matured_at": None,
        "open_material_event_count": 0,
    })
    DB.bond_issues[row["id"]] = row
    return Obj(row, 201)


@bp.get("/disclosure/bond-issues/<row_id>")
@endpoint(ALL_ROLES)
def get_bond_issue(row_id):
    return Obj(must_get("bond_issues", row_id))


@bp.get("/disclosure/bond-issues")
@endpoint(ALL_ROLES)
def list_bond_issues():
    return listing(DB.bond_issues.values(),
                   {"issuer_program_code": "issuer_program_code",
                    "status": "status"})


@bp.post("/disclosure/bond-issues/<row_id>/defease")
@endpoint([ROLE_FINANCE_DIRECTOR])
def defease_bond_issue(row_id):
    issue = must_get("bond_issues", row_id)
    data = body()
    defeasance_type = venum(data, "defeasance_type", ("LEGAL", "ECONOMIC"))
    escrow = vint(data, "escrow_deposit_cents", minimum=0)
    occurrence_date = vdate(data, "occurrence_date")
    if issue["status"] != "OUTSTANDING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an OUTSTANDING issue may be defeased")
    floor = issue["outstanding_par_amount_cents"] if defeasance_type == "LEGAL" else 1
    if escrow < floor:
        fail("ERR_ESCROW_INSUFFICIENT",
             "escrow_deposit_cents must be at least %d" % floor)
    domain.terminate_issue(issue, "DEFEASANCE", actor_id=g.user_id,
                           defeasance_type=defeasance_type,
                           escrow_deposit_cents=escrow,
                           occurrence_date=occurrence_date)
    return Obj(issue)


@bp.post("/disclosure/bond-issues/<row_id>/rating-actions")
@endpoint([ROLE_FINANCE_DIRECTOR])
def record_rating_action(row_id):
    issue = must_get("bond_issues", row_id)
    data = body()
    agency = venum(data, "rating_agency", RATING_AGENCIES)
    prior_rating = vstr(data, "prior_rating", max_len=32)
    new_rating = vstr(data, "new_rating", max_len=32)
    occurrence_date = vdate(data, "occurrence_date")
    expected_version = vint(data, "expected_issue_version", minimum=0)
    if expected_version != issue["version"]:
        fail("ERR_ISSUE_VERSION_STALE",
             "expected_issue_version %s does not match the issue's current version %s"
             % (expected_version, issue["version"]))
    if issue["status"] != "OUTSTANDING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "rating actions may only be recorded on an OUTSTANDING issue")
    guard_notice_occurrence(issue["id"], "RATING_CHANGE", occurrence_date)
    notice = domain.create_notice(issue["id"], "RATING_CHANGE", occurrence_date,
                                  g.user_id, per_se=True, rating_agency=agency,
                                  prior_rating=prior_rating, new_rating=new_rating)
    touch(issue)
    issue["current_rating"] = new_rating
    issue["current_rating_agency"] = agency
    domain.recompute_open_material_event_count(issue)
    domain.recompute_open_obligation_count(undertaking_for_issue(issue["id"]))
    return Obj(notice, 201)


def guard_notice_occurrence(issue_id, event_type, occurrence_date):
    """Ladder rules 19, 20 and 21, shared by both notice-minting endpoints."""
    for notice in DB.notices.values():
        if (notice["issue_id"] == issue_id
                and notice["event_type"] == event_type
                and notice["occurrence_date"] == occurrence_date.isoformat()
                and notice["status"] not in ("NOT_MATERIAL", "VOID")):
            fail("ERR_DUPLICATE_EVENT_NOTICE",
                 "a live notice already exists for this issue, event type and date")
    today = clock_date()
    if (today - occurrence_date).days > calc.EVENT_BACKDATE_MAX_DAYS:
        fail("ERR_OCCURRENCE_DATE_STALE",
             "occurrence_date may not be backdated more than %d days"
             % calc.EVENT_BACKDATE_MAX_DAYS)
    if occurrence_date > today:
        fail("ERR_OCCURRENCE_DATE_IN_FUTURE", "occurrence_date may not be in the future")


# ----------------------------------------------------------------- undertakings
@bp.post("/disclosure/undertakings")
@endpoint([ROLE_FINANCE_DIRECTOR])
def create_undertaking():
    data = body()
    issue = fk("bond_issues", data, "issue_id")
    if issue is None:
        fail("ERR_INVALID_REQUEST", "issue_id is required")
    fiscal_year_end = vstr(data, "fiscal_year_end_month_day",
                           pattern=FISCAL_YEAR_END_PATTERN, max_len=5)
    filing_window_days = vint(data, "filing_window_days", required=False,
                              minimum=1, maximum=365,
                              default=calc.DEFAULT_FILING_WINDOW_DAYS)
    timeliness_basis = venum(data, "timeliness_basis", TIMELINESS_BASES,
                             required=False, default="SUBMISSION_BASIS")
    if issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the issue is not OUTSTANDING")
    if undertaking_for_issue(issue["id"]) is not None:
        fail("ERR_UNDERTAKING_ALREADY_EXISTS",
             "an undertaking already exists for this issue")
    row = new_row({
        "issue_id": issue["id"],
        "fiscal_year_end_month_day": fiscal_year_end,
        "filing_window_days": filing_window_days,
        "timeliness_basis": timeliness_basis,
        "status": "ACTIVE",
        "suspended_reason": None,
        "termination_cause": None,
        "compliance_posture": "COMPLIANT",
        "disclosure_risk_score": 0.00,
        "remediation_tier": "TIER_0",
        "late_filing_count": 0,
        "missed_event_count": 0,
        "delinquent_cycle_count": 0,
        "open_obligation_count": 0,
        "content_weight_bp_total": 0,
    })
    DB.undertakings[row["id"]] = row
    return Obj(row, 201)


@bp.get("/disclosure/undertakings/<row_id>")
@endpoint(ALL_ROLES)
def get_undertaking(row_id):
    return Obj(must_get("undertakings", row_id))


@bp.get("/disclosure/undertakings")
@endpoint(ALL_ROLES)
def list_undertakings():
    return listing(DB.undertakings.values(),
                   {"issue_id": "issue_id", "status": "status",
                    "compliance_posture": "compliance_posture"})


@bp.post("/disclosure/undertakings/<row_id>/suspend")
@endpoint([ROLE_FINANCE_DIRECTOR])
def suspend_undertaking(row_id):
    undertaking = must_get("undertakings", row_id)
    data = body()
    reason = vstr(data, "suspended_reason", max_len=500)
    if undertaking["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "only an ACTIVE undertaking may be suspended")
    touch(undertaking)
    undertaking["status"] = "SUSPENDED"
    undertaking["suspended_reason"] = reason
    return Obj(undertaking)


@bp.post("/disclosure/undertakings/<row_id>/reinstate")
@endpoint([ROLE_FINANCE_DIRECTOR])
def reinstate_undertaking(row_id):
    undertaking = must_get("undertakings", row_id)
    if undertaking["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SUSPENDED undertaking may be reinstated")
    touch(undertaking)
    undertaking["status"] = "ACTIVE"
    undertaking["suspended_reason"] = None
    return Obj(undertaking)


# ---------------------------------------------------------- content requirements
@bp.post("/disclosure/content-requirements")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_content_requirement():
    data = body()
    undertaking = fk("undertakings", data, "undertaking_id")
    if undertaking is None:
        fail("ERR_INVALID_REQUEST", "undertaking_id is required")
    kind = venum(data, "kind", REQUIREMENT_KINDS)
    label = vstr(data, "label", max_len=120)
    weight_bp = vint(data, "weight_bp", minimum=1, maximum=10000)
    waivable = vbool(data, "waivable", default=False)
    for existing in requirements_of(undertaking["id"]):
        if existing["kind"] == kind:
            fail("ERR_DUPLICATE_REQUIREMENT",
                 "this undertaking already declares a %s requirement" % kind)
    row = new_row({
        "undertaking_id": undertaking["id"],
        "kind": kind,
        "label": label,
        "weight_bp": weight_bp,
        "waivable": waivable,
        "requires_audit_opinion": kind == "AUDITED_FINANCIALS",
    }, versioned=False)
    DB.content_requirements[row["id"]] = row
    domain.recompute_counters(undertaking)
    return Obj(row, 201)


@bp.get("/disclosure/content-requirements/<row_id>")
@endpoint(ALL_ROLES)
def get_content_requirement(row_id):
    return Obj(must_get("content_requirements", row_id))


@bp.get("/disclosure/content-requirements")
@endpoint(ALL_ROLES)
def list_content_requirements():
    return listing(DB.content_requirements.values(),
                   {"undertaking_id": "undertaking_id", "kind": "kind"})
