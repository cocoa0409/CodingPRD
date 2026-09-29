"""Applicant households, screening, the selection decision, and members."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import derive
from common import (
    API, created, get_household, get_member, get_program, listing, match, okay,
)
from errors import fail
from payload import (
    body, qenum, qid, vbool, vdatetime, vdecimal, venum, vint, vstring,
)
from rbac import auth, own_household, scope_by_household, scope_households
from store import bump, db, stamp

bp = Blueprint("households", __name__)

SELECTION_STATES = ("DRAFT", "SUBMITTED", "SCREENING", "COMMITTEE_REVIEW", "SELECTED",
                    "WAITLISTED", "DENIED", "PARTNERSHIP_ACTIVE", "CLOSED")
READINESS_STATES = ("NOT_READY", "EDUCATION_IN_PROGRESS", "EDUCATION_COMPLETE",
                    "CLOSING_READY", "WITHDRAWN")
SELECTION_TERMINALS = ("DENIED", "CLOSED")
RELATIONSHIPS = ("APPLICANT", "CO_APPLICANT", "DEPENDENT", "EXTENDED_FAMILY",
                 "FRIEND_OF_FAMILY")


def _fk(data, field, resolver):
    """Position 6: resolve a body foreign key when one was supplied."""
    raw = data.get(field)
    if isinstance(raw, str) and raw:
        return resolver(raw)
    return None


# --------------------------------------------------------------------------- #
# households
# --------------------------------------------------------------------------- #
@bp.post(API + "/households")
def create_household():
    auth("FamilyServicesCoordinator")
    data = body()
    program = _fk(data, "program_id", get_program)

    program_id = vstring(data, "program_id", 1, None, required=True)
    name = vstring(data, "household_name", 1, 120, required=True)
    size = vint(data, "household_size", minimum=1, maximum=12, required=True)
    bedrooms = vint(data, "current_bedroom_count", minimum=0, maximum=10, required=True)
    deficiencies = vint(data, "habitability_deficiency_count",
                        minimum=0, maximum=10, required=True)
    income = vint(data, "self_reported_annual_income_cents", minimum=0, required=True)
    housing = vint(data, "self_reported_housing_cost_cents", minimum=0, required=True)
    debt = vint(data, "monthly_debt_payment_cents", minimum=0, required=True)
    credit = vint(data, "credit_score", minimum=300, maximum=850, required=True)
    months = vint(data, "on_time_housing_payment_months", minimum=0, maximum=120,
                  required=True)
    if program is None:
        program = get_program(program_id)

    cascade.guard_not_frozen(program)

    row = {
        "program_id": program["id"],
        "household_name": name,
        "household_size": size,
        "adult_occupant_count": 1,
        "current_bedroom_count": bedrooms,
        "habitability_deficiency_count": deficiencies,
        "self_reported_annual_income_cents": income,
        "self_reported_housing_cost_cents": housing,
        "verified_annual_income_cents": None,
        "verified_housing_cost_cents": None,
        "monthly_debt_payment_cents": debt,
        "credit_score": credit,
        "on_time_housing_payment_months": months,
        "documentation_status": "INCOMPLETE",
        "ami_pct": None,
        "need_score": None,
        "ability_to_pay_score": None,
        "willingness_score": None,
        "composite_selection_score": None,
        "score_basis": None,
        "sweat_equity_required_hours": None,
        "sweat_equity_credited_hours": Decimal("0.00"),
        "family_member_credited_hours": Decimal("0.00"),
        "sweat_equity_satisfied": False,
        "selection_status": "DRAFT",
        "partnership_readiness": "NOT_READY",
        "closing_date": None,
        "denial_reason_code": None,
    }
    stamp(row)
    db.households[row["id"]] = row
    return created(derive.public_household(row))


@bp.get(API + "/households")
def list_households():
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "SelectionCommitteeMember",
                 "MortgageOfficer")
    program_id = qid("program_id")
    selection_status = qenum("selection_status", SELECTION_STATES)
    readiness = qenum("partnership_readiness", READINESS_STATES)
    score_basis = qenum("score_basis", ("PRELIMINARY", "FINAL"))
    rows = [r for r in db.households.values()
            if match(r, "program_id", program_id)
            and match(r, "selection_status", selection_status)
            and match(r, "partnership_readiness", readiness)
            and match(r, "score_basis", score_basis)]
    return listing(scope_households(actor, rows), derive.public_household)


@bp.get(API + "/households/<hid>")
def read_household(hid):
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "SelectionCommitteeMember",
                 "MortgageOfficer", "Applicant")
    household = get_household(hid)
    own_household(actor, household)
    return okay(derive.public_household(household))


@bp.post(API + "/households/<hid>/submit")
def submit_household(hid):
    actor = auth("Applicant", "FamilyServicesCoordinator")
    household = get_household(hid)
    own_household(actor, household)
    data = body()
    vbool(data, "attestation_signed", required=True)

    cascade.state_gate(household, "selection_status", ("DRAFT",), SELECTION_TERMINALS)
    cascade.guard_not_frozen(derive.program_of_household(household))

    members = derive.members_of_household(household)
    active = [m for m in members if m["status"] == "ACTIVE"]
    if not any(m["relationship"] == "APPLICANT" for m in active):
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "The household needs an active APPLICANT member before submission.")
    if (household.get("household_size") or 0) < len(active):
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "household_size is smaller than the number of active members.")

    household["selection_status"] = "SUBMITTED"
    household["documentation_status"] = "SUBMITTED"
    derive.refresh_household(household)
    bump(household)
    return okay(derive.public_household(household))


@bp.post(API + "/households/<hid>/screen")
def screen_household(hid):
    auth("FamilyServicesCoordinator")
    household = get_household(hid)
    data = body()
    documents = vbool(data, "income_documents_received", required=True)
    verified_income = vint(data, "verified_annual_income_cents", minimum=0, default=None)
    verified_housing = vint(data, "verified_housing_cost_cents", minimum=0, default=None)
    vstring(data, "screening_notes", 1, None, default=None, nullable=True)

    cascade.state_gate(household, "selection_status", ("SUBMITTED",), SELECTION_TERMINALS)
    cascade.guard_not_frozen(derive.program_of_household(household))

    if verified_income is not None:
        household["verified_annual_income_cents"] = verified_income
    if verified_housing is not None:
        household["verified_housing_cost_cents"] = verified_housing
    if verified_income is not None and verified_housing is not None and documents:
        household["documentation_status"] = "VERIFIED"

    household["selection_status"] = "SCREENING"
    calc.score_household(household, "PRELIMINARY", willingness=None)
    derive.refresh_household(household)
    bump(household)
    return okay(derive.public_household(household))


@bp.post(API + "/households/<hid>/committee-referral")
def refer_household(hid):
    auth("FamilyServicesCoordinator")
    household = get_household(hid)
    data = body()
    vstring(data, "referral_memo", 1, None, default=None, nullable=True)

    cascade.state_gate(household, "selection_status", ("SCREENING",), SELECTION_TERMINALS)
    program = derive.program_of_household(household)
    cascade.guard_not_frozen(program)

    if household.get("documentation_status") != "VERIFIED":
        fail("ERR_DOCUMENTATION_INCOMPLETE")

    median = (program or {}).get("ami_median_income_cents") or 0
    income = household.get("verified_annual_income_cents") or 0
    from util import dec, r4
    ami_pct = r4(dec(income) / dec(median)) if median else Decimal(0)
    if ami_pct < Decimal("0.3000") or ami_pct > Decimal("0.8000"):
        fail("ERR_INCOME_OUT_OF_BAND")

    derive.refresh_household(household)
    household["sweat_equity_required_hours"] = calc.frozen_required_hours(program, household)
    household["selection_status"] = "COMMITTEE_REVIEW"
    derive.refresh_household(household)
    bump(household)
    return okay(derive.public_household(household))


@bp.post(API + "/households/<hid>/return-to-screening")
def return_to_screening(hid):
    auth("FamilyServicesCoordinator")
    household = get_household(hid)
    data = body()
    vstring(data, "reason", 1, None, default=None, nullable=True)

    cascade.state_gate(household, "selection_status", ("COMMITTEE_REVIEW",),
                       SELECTION_TERMINALS)
    cascade.guard_not_frozen(derive.program_of_household(household))

    household["selection_status"] = "SCREENING"
    household["composite_selection_score"] = None
    household["willingness_score"] = None
    household["score_basis"] = "PRELIMINARY"
    bump(household)
    return okay(derive.public_household(household))


@bp.post(API + "/households/<hid>/selection-decision")
def selection_decision(hid):
    auth("ProgramAdmin")
    household = get_household(hid)
    data = body()
    vstring(data, "decision_minutes", 1, None, default=None, nullable=True)

    cascade.state_gate(household, "selection_status", ("COMMITTEE_REVIEW",),
                       SELECTION_TERMINALS)
    program = derive.program_of_household(household)
    cascade.guard_not_frozen(program)

    quorum_met, willingness, veto = calc.committee_state(household, program)
    if not quorum_met:
        fail("ERR_COMMITTEE_QUORUM_NOT_MET")

    calc.score_household(household, "FINAL", willingness=willingness)
    composite = household.get("composite_selection_score")
    composite = Decimal(0) if composite is None else composite

    if veto or composite < Decimal("55.00"):
        household["selection_status"] = "DENIED"
        household["denial_reason_code"] = "WILLINGNESS_VETO" if veto else "SCORE_BELOW_WAITLIST"
        cascade.deny_household(household)
    elif composite >= Decimal("70.00"):
        household["selection_status"] = "SELECTED"
    else:
        household["selection_status"] = "WAITLISTED"

    derive.refresh_household(household)
    bump(household)
    return okay(derive.public_household(household))


# --------------------------------------------------------------------------- #
# household members
# --------------------------------------------------------------------------- #
@bp.post(API + "/household-members")
def create_member():
    actor = auth("FamilyServicesCoordinator", "Applicant")
    data = body()
    household = _fk(data, "household_id", get_household)

    household_id = vstring(data, "household_id", 1, None, required=True)
    if household is None:
        household = get_household(household_id)
    own_household(actor, household)

    full_name = vstring(data, "full_name", 1, 120, required=True)
    relationship = venum(data, "relationship", RELATIONSHIPS, required=True)
    birth_date = vdatetime(data, "birth_date", required=True)
    is_adult = vbool(data, "is_adult_occupant", default=False)

    row = {
        "household_id": household["id"],
        "full_name": full_name,
        "relationship": relationship,
        "birth_date": birth_date,
        "is_adult_occupant": bool(is_adult),
        "credited_hours_to_date": Decimal("0.00"),
        "status": "ACTIVE",
    }
    stamp(row)
    db.members[row["id"]] = row

    derive.refresh_household(household)
    bump(household)
    return created(derive.public_member(row))


@bp.get(API + "/household-members")
def list_members():
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "SelectionCommitteeMember",
                 "MortgageOfficer", "ConstructionManager", "Applicant")
    household_id = qid("household_id")
    relationship = qenum("relationship", RELATIONSHIPS)
    status = qenum("status", ("ACTIVE", "REMOVED"))
    rows = [r for r in db.members.values()
            if match(r, "household_id", household_id)
            and match(r, "relationship", relationship)
            and match(r, "status", status)]
    return listing(scope_by_household(actor, rows), derive.public_member)


@bp.get(API + "/household-members/<mid>")
def read_member(mid):
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer",
                 "ConstructionManager", "Applicant")
    member = get_member(mid)
    own_household(actor, db.households.get(member["household_id"]))
    return okay(derive.public_member(member))
