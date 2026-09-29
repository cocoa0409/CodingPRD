"""Agency membership standards, financial review and the probation cascade (PRD 3.6)."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate, get_agency, get_review
from envelope import created, filter_int, filter_str, ok, paginate
from errors import ApiError
from store import D, ZERO, base_entity, db, sort_created_asc, touch
from validators import bad, body, get_enum, get_int, get_ratio, get_str

from services import aggregates, calc

bp = Blueprint("agencies", __name__)

PRIORITY_AREAS = ("BASIC_NEEDS", "EDUCATION", "HEALTH", "FINANCIAL_STABILITY")
AUDIT_OPINIONS = ("UNQUALIFIED", "QUALIFIED", "ADVERSE", "NONE")


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@bp.get("/agencies/<agency_id>")
def read_agency(agency_id):
    authenticate(ALL_ROLES)
    return ok(get_agency(agency_id))


@bp.get("/agencies/<agency_id>/designations")
def list_agency_designations(agency_id):
    authenticate(ALL_ROLES)
    get_agency(agency_id)
    rows = [d for d in db.designations.values() if d["agency_id"] == agency_id]
    status = filter_str("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return paginate(sort_created_asc(rows))


@bp.get("/agencies/<agency_id>/reviews")
def list_agency_reviews(agency_id):
    authenticate(ALL_ROLES)
    get_agency(agency_id)
    rows = aggregates.agency_reviews(agency_id)
    status = filter_str("status")
    fiscal_year = filter_int("fiscal_year")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    # PRD 2.3: highest fiscal_year first.
    rows = sorted(
        rows, key=lambda r: (r["fiscal_year"], r["created_at"], r["_seq"]), reverse=True
    )
    return paginate(rows)


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #


@bp.post("/agencies")
def admit_agency():
    authenticate(("UnitedFundAdmin",))
    data = body()
    legal_name = get_str(data, "legal_name", min_len=1, max_len=200)
    ein = get_str(data, "ein", min_len=1)
    if len(ein) != 9 or not ein.isdigit():
        bad("Field 'ein' must be exactly nine digits.")
    priority_area = get_enum(data, "primary_priority_area", PRIORITY_AREAS)
    for existing in db.agencies.values():
        if existing["ein"] == ein:
            bad("Field 'ein' must be globally unique across all agencies.")

    row = base_entity()
    row.update({
        "legal_name": legal_name,
        "ein": ein,
        "primary_priority_area": priority_area,
        "membership_status": "APPLICANT",
        "latest_standing_score": None,
        "designated_passthrough_ytd": ZERO,
        "open_review_count": 0,
        "probation_count": 0,
        "outcome_report_delinquent": False,
    })
    db.agencies[row["id"]] = row
    return created(row)


@bp.post("/agencies/<agency_id>/reviews")
def file_review(agency_id):
    authenticate(("UnitedFundAdmin", "FinanceReviewer", "AgencyRepresentative"))
    data = body()
    fiscal_year = get_int(data, "fiscal_year", minimum=2020, maximum=2100)
    program_ratio = get_ratio(data, "program_expense_ratio", minimum=0, maximum=1)
    admin_ratio = get_ratio(data, "admin_expense_ratio", minimum=0, maximum=1)
    reserve = get_ratio(
        data, "months_operating_reserve", minimum=0, maximum=60, places=2
    )
    governance = get_int(
        data, "governance_checklist_passed_count", minimum=0, maximum=10
    )
    audit_opinion = get_enum(data, "audit_opinion", AUDIT_OPINIONS)
    for existing in db.reviews.values():
        if existing["agency_id"] == agency_id and existing["fiscal_year"] == fiscal_year:
            bad("Field 'fiscal_year' has already been reviewed for this agency.")

    agency = get_agency(agency_id)
    if agency["membership_status"] == "SUSPENDED_MEMBERSHIP":
        raise ApiError("ERR_AGENCY_MEMBERSHIP_TERMINAL")

    review = base_entity()
    review.update({
        "agency_id": agency_id,
        "fiscal_year": fiscal_year,
        "program_expense_ratio": program_ratio,
        "admin_expense_ratio": admin_ratio,
        "months_operating_reserve": reserve,
        "governance_checklist_passed_count": governance,
        "audit_opinion": audit_opinion,
        "audited_program_expense_ratio": None,
        "audited_admin_expense_ratio": None,
        "audited_months_operating_reserve": None,
        "preliminary_score": ZERO,
        "certified_score": None,
        "restatement_penalty_applied": False,
        "standards_met": None,
        "review_basis": "SELF_REPORTED",
        "status": "PENDING",
    })
    score, _ = calc.standing_score(review, "PRELIMINARY")
    review["preliminary_score"] = score
    db.reviews[review["id"]] = review

    agency["membership_status"] = "UNDER_FINANCIAL_REVIEW"
    aggregates.recompute_open_review_count(agency)
    touch("agency", agency)
    return created(review)


def _suspend_requests_for(agency_id):
    """Probation cascade links 3 and 4."""
    touched_cycles = []
    for req in aggregates.agency_requests(agency_id):
        if req["status"] not in ("SUBMITTED", "UNDER_PANEL_REVIEW"):
            continue
        cycle = db.cycles.get(req["cycle_id"])
        if cycle is None or cycle["posture"] not in ("OPEN", "RESTRICTED"):
            continue
        req["status_before_suspension"] = req["status"]
        req["status"] = "SUSPENDED_REVIEW"
        touch("request", req)
        if cycle["id"] not in touched_cycles:
            touched_cycles.append(cycle["id"])
    for cycle_id in touched_cycles:
        aggregates.apply_restriction(db.cycles[cycle_id])


@bp.post("/agencies/<agency_id>/reviews/<review_id>/certify")
def certify_review(agency_id, review_id):
    authenticate(("UnitedFundAdmin", "FinanceReviewer"))
    data = body()
    audited_program = get_ratio(
        data, "audited_program_expense_ratio", minimum=0, maximum=1
    )
    audited_admin = get_ratio(data, "audited_admin_expense_ratio", minimum=0, maximum=1)
    audited_reserve = get_ratio(
        data, "audited_months_operating_reserve", minimum=0, maximum=60, places=2
    )

    agency = get_agency(agency_id)
    review = get_review(review_id)
    if review["agency_id"] != agency_id:
        raise ApiError("ERR_REVIEW_AGENCY_MISMATCH")
    if review["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_ALREADY_CERTIFIED")
    if agency["membership_status"] == "SUSPENDED_MEMBERSHIP":
        raise ApiError("ERR_AGENCY_MEMBERSHIP_TERMINAL")

    # Link 1.
    review["audited_program_expense_ratio"] = audited_program
    review["audited_admin_expense_ratio"] = audited_admin
    review["audited_months_operating_reserve"] = audited_reserve
    review["review_basis"] = "AUDITED"
    score, restated = calc.standing_score(review, "CERTIFIED")
    review["certified_score"] = score
    review["restatement_penalty_applied"] = restated
    review["standards_met"] = score >= calc.STANDARDS_PASS_SCORE
    review["status"] = "CERTIFIED"
    touch("review", review)

    # Link 2: the membership fork on two inclusive lower bounds.
    if score >= calc.STANDARDS_PASS_SCORE:
        agency["membership_status"] = "GOOD_STANDING"
        downgrade = False
    elif score >= calc.PROBATION_FLOOR_SCORE:
        agency["membership_status"] = "PROBATION"
        agency["probation_count"] = agency["probation_count"] + 1
        downgrade = True
    else:
        agency["membership_status"] = "SUSPENDED_MEMBERSHIP"
        downgrade = True
    aggregates.recompute_latest_standing_score(agency)
    aggregates.recompute_open_review_count(agency)
    touch("agency", agency)

    if downgrade:
        _suspend_requests_for(agency_id)
    return ok(review)


@bp.post("/agencies/<agency_id>/reinstate")
def reinstate_agency(agency_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    data = body()
    get_str(data, "justification", min_len=1)

    agency = get_agency(agency_id)
    score = agency.get("latest_standing_score")
    if (agency["membership_status"] != "PROBATION"
            or score is None
            or D(score) < calc.PROBATION_FLOOR_SCORE
            or agency["open_review_count"] != 0):
        raise ApiError("ERR_AGENCY_MEMBERSHIP_TERMINAL")

    agency["membership_status"] = "GOOD_STANDING"
    touch("agency", agency)

    touched_cycles = []
    for req in aggregates.agency_requests(agency_id):
        if req["status"] != "SUSPENDED_REVIEW":
            continue
        restored = req.get("status_before_suspension")
        if restored is None:
            continue
        req["status"] = restored
        req["status_before_suspension"] = None
        touch("request", req)
        if req["cycle_id"] not in touched_cycles:
            touched_cycles.append(req["cycle_id"])
    for cycle_id in touched_cycles:
        cycle = db.cycles.get(cycle_id)
        if cycle is not None:
            aggregates.release_restriction(cycle)
    return ok(agency)
