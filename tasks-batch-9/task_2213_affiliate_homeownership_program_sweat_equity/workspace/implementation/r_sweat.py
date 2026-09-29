"""The sweat equity hour ledger: claim, verify, credit, reverse."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import derive
from common import API, created, get_entry, get_household, get_member, listing, match, okay
from errors import fail
from payload import body, qenum, qid, vdatetime, vdecimal, venum, vstring
from rbac import auth, own_household, scope_by_household
from store import bump, db, fresh, stamp
from util import dec, r2

bp = Blueprint("sweat", __name__)

CATEGORIES = ("CONSTRUCTION", "RESTORE_STORE", "HOMEOWNER_EDUCATION",
              "OTHER_AFFILIATE", "ADVOCACY")
ENTRY_STATES = ("CLAIMED", "VERIFIED", "CREDITED", "REJECTED", "REVERSED")
ENTRY_TERMINALS = ("REVERSED",)
PARTNER_STATES = ("SELECTED", "PARTNERSHIP_ACTIVE")


def _guard_member(entry, member, household):
    if member is None or member.get("household_id") != household["id"]:
        fail("ERR_MEMBER_NOT_ACTIVE")
    if member.get("status") != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE")


def _guard_work_date(household, work_date):
    if work_date is None:
        fail("ERR_WORK_DATE_OUT_OF_RANGE")
    if work_date > db.now():
        fail("ERR_WORK_DATE_OUT_OF_RANGE")
    if work_date < household["created_at"]:
        fail("ERR_WORK_DATE_OUT_OF_RANGE")


@bp.post(API + "/sweat-equity-entries")
def claim_entry():
    actor = auth("Applicant", "FamilyServicesCoordinator")
    data = body()
    raw_household = data.get("household_id")
    household = get_household(raw_household) if isinstance(raw_household, str) and raw_household else None
    raw_member = data.get("member_id")
    member = get_member(raw_member) if isinstance(raw_member, str) and raw_member else None

    household_id = vstring(data, "household_id", 1, None, required=True)
    member_id = vstring(data, "member_id", 1, None, required=True)
    if household is None:
        household = get_household(household_id)
    if member is None:
        member = get_member(member_id)
    own_household(actor, household)

    category = venum(data, "category", CATEGORIES, required=True)
    work_date = vdatetime(data, "work_date", required=True)
    hours = vdecimal(data, "hours_claimed", minimum="0.25", maximum=12, required=True)

    cascade.guard_not_frozen(derive.program_of_household(household))
    _guard_member(None, member, household)
    _guard_work_date(household, work_date)

    row = {
        "household_id": household["id"],
        "member_id": member["id"],
        "shift_assignment_id": None,
        "reversal_of_entry_id": None,
        "category": category,
        "work_date": work_date,
        "hours_claimed": hours,
        "credit_weight": None,
        "hours_credited": None,
        "capped_hours": Decimal("0.00"),
        "claimed_by_user_id": actor.user_id,
        "verified_by_user_id": None,
        "status": "CLAIMED",
    }
    stamp(row)
    db.entries[row["id"]] = row
    return created(derive.public_entry(row))


@bp.get(API + "/sweat-equity-entries")
def list_entries():
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer",
                 "ConstructionManager", "Applicant")
    household_id = qid("household_id")
    member_id = qid("member_id")
    assignment_id = qid("shift_assignment_id")
    reversal_of = qid("reversal_of_entry_id")
    category = qenum("category", CATEGORIES)
    status = qenum("status", ENTRY_STATES)
    rows = [r for r in db.entries.values()
            if match(r, "household_id", household_id)
            and match(r, "member_id", member_id)
            and match(r, "shift_assignment_id", assignment_id)
            and match(r, "reversal_of_entry_id", reversal_of)
            and match(r, "category", category)
            and match(r, "status", status)]
    return listing(scope_by_household(actor, rows), derive.public_entry)


@bp.get(API + "/sweat-equity-entries/<eid>")
def read_entry(eid):
    actor = auth("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer",
                 "ConstructionManager", "Applicant")
    entry = get_entry(eid)
    own_household(actor, db.households.get(entry["household_id"]))
    return okay(derive.public_entry(entry))


@bp.post(API + "/sweat-equity-entries/<eid>/verification")
def verify_entry(eid):
    actor = auth("FamilyServicesCoordinator", "ConstructionManager")
    entry = get_entry(eid)
    data = body()
    decision = venum(data, "decision", ("VERIFIED", "REJECTED"), required=True)
    reason = vstring(data, "rejection_reason", 1, None, default=None, nullable=True)

    cascade.state_gate(entry, "status", ("CLAIMED",), ENTRY_TERMINALS)
    household = db.households.get(entry["household_id"])
    cascade.guard_not_frozen(derive.program_of_household(household) if household else None)

    if actor.user_id == entry.get("claimed_by_user_id"):
        fail("ERR_SELF_VERIFICATION_FORBIDDEN")

    if decision == "VERIFIED":
        member = db.members.get(entry.get("member_id"))
        _guard_member(entry, member, household)
        if entry.get("work_date") is not None and entry["work_date"] > db.now():
            fail("ERR_WORK_DATE_OUT_OF_RANGE")
        entry["status"] = "VERIFIED"
        entry["verified_by_user_id"] = actor.user_id
    else:
        if reason is None:
            fail("ERR_VALIDATION", "rejection_reason is required on a rejection.")
        entry["status"] = "REJECTED"
        entry["verified_by_user_id"] = actor.user_id
        entry["hours_credited"] = Decimal("0.00")

    bump(entry)
    return okay(derive.public_entry(entry))


@bp.post(API + "/sweat-equity-entries/<eid>/resubmit")
def resubmit_entry(eid):
    actor = auth("Applicant")
    entry = get_entry(eid)
    household = db.households.get(entry["household_id"])
    own_household(actor, household)
    data = body()
    hours = vdecimal(data, "hours_claimed", minimum="0.25", maximum=12, required=True)
    work_date = vdatetime(data, "work_date", required=True)

    cascade.state_gate(entry, "status", ("REJECTED",), ENTRY_TERMINALS)
    cascade.guard_not_frozen(derive.program_of_household(household) if household else None)
    if household is None or household.get("selection_status") not in PARTNER_STATES:
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "Only a selected or active partner household may resubmit an entry.")
    _guard_work_date(household, work_date)

    entry["hours_claimed"] = hours
    entry["work_date"] = work_date
    entry["verified_by_user_id"] = None
    entry["status"] = "CLAIMED"
    bump(entry)
    return okay(derive.public_entry(entry))


@bp.post(API + "/sweat-equity-entries/<eid>/credit")
def credit_entry(eid):
    auth("FamilyServicesCoordinator")
    entry = get_entry(eid)
    body()

    cascade.state_gate(entry, "status", ("VERIFIED",), ENTRY_TERMINALS)
    household = db.households.get(entry["household_id"])
    cascade.guard_not_frozen(derive.program_of_household(household) if household else None)
    if household is None or household.get("selection_status") not in PARTNER_STATES:
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "Only a selected or active partner household may receive credit.")

    member = db.members.get(entry.get("member_id"))
    _guard_member(entry, member, household)

    age = calc.member_age_at(member, entry.get("work_date"))
    if age is None or age < 16:
        fail("ERR_MEMBER_INELIGIBLE_FOR_CREDIT")
    minor = age < 18
    category = entry.get("category")
    if minor and category not in calc.MINOR_CATEGORIES:
        fail("ERR_MINOR_CATEGORY_NOT_ALLOWED")

    base = calc.BASE_WEIGHT.get(category, Decimal("1.00"))
    weight = r2(base * (Decimal("0.5") if minor else Decimal("1")))
    gross = r2(dec(entry.get("hours_claimed") or 0) * weight)

    cap = calc.CATEGORY_CAP.get(category, calc.UNCAPPED)
    used = calc.category_used(household, category)
    category_room = r2(max(Decimal(0), cap - used))
    if category_room <= Decimal(0):
        fail("ERR_CATEGORY_CREDIT_CAP_REACHED")

    derive.refresh_household(household)
    family_scoped = calc.is_family_scoped(member)
    if family_scoped:
        allowance = calc.family_allowance(household)
        family_room = r2(max(Decimal(0),
                             allowance - dec(household.get("family_member_credited_hours") or 0)))
        if family_room <= Decimal(0):
            fail("ERR_FAMILY_CREDIT_CAP_REACHED")
    else:
        family_room = calc.UNCAPPED

    credited = min(gross, category_room, family_room)
    if credited <= Decimal(0):
        fail("ERR_CATEGORY_CREDIT_CAP_REACHED")

    entry["credit_weight"] = weight
    entry["hours_credited"] = r2(credited)
    entry["capped_hours"] = r2(gross - credited)
    entry["status"] = "CREDITED"
    bump(entry)

    cascade.after_credit(household, member)
    return okay(derive.public_entry(entry))


@bp.post(API + "/sweat-equity-entries/<eid>/reverse")
def reverse_entry(eid):
    actor = auth("FamilyServicesCoordinator")
    entry = get_entry(eid)
    data = body()
    vstring(data, "reversal_reason", 1, None, default=None, nullable=True)

    cascade.state_gate(entry, "status", ("CREDITED",), ENTRY_TERMINALS)
    household = db.households.get(entry["household_id"])
    cascade.guard_not_frozen(derive.program_of_household(household) if household else None)

    if dec(entry.get("hours_credited") or 0) == Decimal(0):
        fail("ERR_TRANSITION_NOT_ALLOWED", "The entry credited no hours.")
    if entry.get("reversal_of_entry_id") is not None:
        fail("ERR_TRANSITION_NOT_ALLOWED", "A reversal mirror entry may not be reversed.")
    if household is None or household.get("selection_status") == "CLOSED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "The household is already closed.")

    mirror = {
        "household_id": entry["household_id"],
        "member_id": entry["member_id"],
        "shift_assignment_id": None,
        "reversal_of_entry_id": entry["id"],
        "category": entry["category"],
        "work_date": entry["work_date"],
        "hours_claimed": Decimal("0.00"),
        "credit_weight": entry.get("credit_weight"),
        "hours_credited": r2(dec(entry.get("hours_credited") or 0) * Decimal(-1)),
        "capped_hours": Decimal("0.00"),
        "claimed_by_user_id": actor.user_id,
        "verified_by_user_id": actor.user_id,
        "status": "CREDITED",
    }
    stamp(mirror)
    fresh(mirror)
    db.entries[mirror["id"]] = mirror

    entry["status"] = "REVERSED"
    bump(entry)

    member = db.members.get(entry.get("member_id"))
    if member is not None:
        cascade.after_reversal(household, member)
    return okay(derive.public_entry(entry))
