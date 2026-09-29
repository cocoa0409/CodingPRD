"""Homebuyer education enrollments and module outcomes."""
from flask import Blueprint

import cascade
import derive
from common import API, created, get_enrollment, get_household, listing, match, okay
from errors import fail
from payload import body, qenum, qid, venum, vint, vstring
from rbac import auth, own_household, scope_by_household
from store import bump, db, stamp
from util import days

bp = Blueprint("education", __name__)

CURRICULA = ("HOMEBUYER_CORE", "BUDGET_COACHING", "HOME_MAINTENANCE")
ENROLLMENT_STATES = ("ENROLLED", "IN_PROGRESS", "COMPLETED", "FAILED", "EXPIRED")
ENROLLMENT_TERMINALS = ("FAILED", "EXPIRED")
LIVE_STATES = ("ENROLLED", "IN_PROGRESS", "COMPLETED")
PARTNER_STATES = ("SELECTED", "PARTNERSHIP_ACTIVE")
READ_ROLES = ("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer", "Applicant")


@bp.post(API + "/education-enrollments")
def create_enrollment():
    auth("FamilyServicesCoordinator")
    data = body()
    raw = data.get("household_id")
    household = get_household(raw) if isinstance(raw, str) and raw else None

    household_id = vstring(data, "household_id", 1, None, required=True)
    curriculum = venum(data, "curriculum_code", CURRICULA, required=True)
    required = vint(data, "required_module_count", minimum=1, maximum=12, required=True)
    if household is None:
        household = get_household(household_id)

    if household.get("selection_status") not in PARTNER_STATES:
        fail("ERR_HOUSEHOLD_NOT_SELECTED")

    for existing in derive.enrollments_of_household(household):
        if existing.get("curriculum_code") == curriculum and \
                existing.get("status") in LIVE_STATES:
            fail("ERR_DUPLICATE_ENROLLMENT")

    row = {
        "household_id": household["id"],
        "curriculum_code": curriculum,
        "required_module_count": required,
        "passed_module_count": 0,
        "missed_session_count": 0,
        "completed_on": None,
        "expires_on": None,
        "status": "ENROLLED",
        "_modules": [],
    }
    stamp(row)
    db.enrollments[row["id"]] = row

    if curriculum == "HOMEBUYER_CORE" and \
            household.get("partnership_readiness") == "NOT_READY":
        household["partnership_readiness"] = "EDUCATION_IN_PROGRESS"
        bump(household)

    return created(derive.public_enrollment(row))


@bp.get(API + "/education-enrollments")
def list_enrollments():
    actor = auth(*READ_ROLES)
    household_id = qid("household_id")
    curriculum = qenum("curriculum_code", CURRICULA)
    status = qenum("status", ENROLLMENT_STATES)
    rows = [r for r in db.enrollments.values()
            if match(r, "household_id", household_id)
            and match(r, "curriculum_code", curriculum)
            and match(r, "status", status)]
    return listing(scope_by_household(actor, rows), derive.public_enrollment)


@bp.get(API + "/education-enrollments/<eid>")
def read_enrollment(eid):
    actor = auth(*READ_ROLES)
    enrollment = get_enrollment(eid)
    own_household(actor, db.households.get(enrollment.get("household_id")))
    return okay(derive.public_enrollment(enrollment))


@bp.post(API + "/education-enrollments/<eid>/module-completions")
def record_module(eid):
    auth("FamilyServicesCoordinator")
    enrollment = get_enrollment(eid)
    data = body()
    outcome = venum(data, "outcome", ("PASSED", "MISSED"), required=True)
    module_code = vstring(data, "module_code", 1, 40, required=True)

    cascade.state_gate(enrollment, "status", ("ENROLLED", "IN_PROGRESS"),
                       ENROLLMENT_TERMINALS)
    household = db.households.get(enrollment.get("household_id"))
    cascade.guard_not_frozen(derive.program_of_household(household) if household else None)

    enrollment["status"] = "IN_PROGRESS"
    if outcome == "PASSED":
        modules = enrollment.setdefault("_modules", [])
        if module_code not in modules:
            modules.append(module_code)
            enrollment["passed_module_count"] = len(modules)
    else:
        enrollment["missed_session_count"] = (enrollment.get("missed_session_count") or 0) + 1

    core = enrollment.get("curriculum_code") == "HOMEBUYER_CORE"

    if (enrollment.get("missed_session_count") or 0) >= 3:
        enrollment["status"] = "FAILED"
        bump(enrollment)
        if core and household is not None:
            if household.get("partnership_readiness") == "EDUCATION_IN_PROGRESS":
                cascade.readiness_to_not_ready(household)
        return okay(derive.public_enrollment(enrollment))

    if (enrollment.get("passed_module_count") or 0) >= (enrollment.get("required_module_count") or 0):
        now = db.now()
        enrollment["status"] = "COMPLETED"
        enrollment["completed_on"] = now
        enrollment["expires_on"] = now + days(730)
        bump(enrollment)
        if core and household is not None:
            if household.get("partnership_readiness") == "EDUCATION_IN_PROGRESS":
                household["partnership_readiness"] = "EDUCATION_COMPLETE"
                bump(household)
                cascade.try_advance_to_closing_ready(household)
        return okay(derive.public_enrollment(enrollment))

    bump(enrollment)
    return okay(derive.public_enrollment(enrollment))
