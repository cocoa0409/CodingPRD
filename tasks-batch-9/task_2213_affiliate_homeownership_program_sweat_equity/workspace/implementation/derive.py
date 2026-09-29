"""Derived (source: computed) fields and JSON projection of stored rows."""
from datetime import datetime
from decimal import Decimal

from store import db
from util import dec, iso, r2, r4

LEDGER_STATUSES = ("CREDITED", "REVERSED")
CONFIRMED_SEAT_STATUSES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")
HELD_SEAT_STATUSES = ("RESERVED", "CONFIRMED", "CHECKED_IN", "COMPLETED")


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #
def program_of_household(household):
    return db.programs.get(household.get("program_id"))


def program_of_site(site):
    return db.programs.get(site.get("program_id"))


def program_of_application(application):
    household = db.households.get(application.get("household_id"))
    if household is not None:
        return program_of_household(household)
    site = db.sites.get(application.get("build_site_id"))
    if site is not None:
        return program_of_site(site)
    return None


def site_of_shift(shift):
    return db.sites.get(shift.get("build_site_id"))


def shift_of_assignment(assignment):
    return db.shifts.get(assignment.get("shift_id"))


def site_of_assignment(assignment):
    shift = shift_of_assignment(assignment)
    return site_of_shift(shift) if shift else None


def household_of_assignment(assignment):
    member = db.members.get(assignment.get("household_member_id"))
    if member is None:
        return None
    return db.households.get(member.get("household_id"))


def applications_of_program(program):
    out = []
    for app in db.applications.values():
        prog = program_of_application(app)
        if prog is not None and prog["id"] == program["id"]:
            out.append(app)
    return out


def households_of_program(program):
    return [h for h in db.households.values() if h.get("program_id") == program["id"]]


def sites_of_program(program):
    return [s for s in db.sites.values() if s.get("program_id") == program["id"]]


def entries_of_household(household):
    return [e for e in db.entries.values() if e.get("household_id") == household["id"]]


def members_of_household(household):
    return [m for m in db.members.values() if m.get("household_id") == household["id"]]


def enrollments_of_household(household):
    return [e for e in db.enrollments.values() if e.get("household_id") == household["id"]]


def applications_of_household(household):
    return [a for a in db.applications.values() if a.get("household_id") == household["id"]]


def shifts_of_site(site):
    return [s for s in db.shifts.values() if s.get("build_site_id") == site["id"]]


def assignments_of_shift(shift):
    return [a for a in db.assignments.values() if a.get("shift_id") == shift["id"]]


def assignments_of_volunteer(volunteer):
    return [a for a in db.assignments.values() if a.get("volunteer_id") == volunteer["id"]]


def cost_entries_of_site(site):
    return [c for c in db.cost_entries.values() if c.get("build_site_id") == site["id"]]


def core_enrollment(household):
    """The household's governing HOMEBUYER_CORE enrollment, most recent first."""
    rows = [
        e for e in enrollments_of_household(household)
        if e.get("curriculum_code") == "HOMEBUYER_CORE"
    ]
    if not rows:
        return None
    live = [e for e in rows if e["status"] in ("ENROLLED", "IN_PROGRESS", "COMPLETED")]
    pool = live or rows
    pool.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return pool[-1]


# --------------------------------------------------------------------------- #
# derivations
# --------------------------------------------------------------------------- #
def program_posture(program):
    if program.get("status") == "SUSPENDED":
        return "FROZEN"
    if program_ledger(program)["subsidy_available_cents"] == 0:
        return "SUBSIDY_RESTRICTED"
    return "OPEN"


def program_ledger(program):
    committed = 0
    disbursed = 0
    for app in applications_of_program(program):
        amount = app.get("silent_second_amount_cents") or 0
        if app["status"] in ("APPROVED", "CLEARED_TO_CLOSE"):
            committed += amount
        elif app["status"] == "CLOSED" and app["lien_status"] in (
            "ACTIVE", "FORBEARANCE", "TRANSFER_PENDING"
        ):
            disbursed += amount
    pool = program.get("subsidy_pool_cents", 0)
    return {
        "subsidy_committed_cents": committed,
        "subsidy_disbursed_cents": disbursed,
        "subsidy_available_cents": pool - committed - disbursed,
    }


def program_donated_fmv(program):
    total = 0
    for site in sites_of_program(program):
        total += site_donated_fmv(site)
    return total


def site_donated_fmv(site):
    total = 0
    for line in cost_entries_of_site(site):
        if line["status"] == "RECORDED" and line.get("is_in_kind"):
            total += line.get("fair_market_value_cents") or 0
    return total


def site_cash_cost(site):
    total = site.get("acquisition_cost_cents", 0)
    for line in cost_entries_of_site(site):
        if line["status"] == "RECORDED" and not line.get("is_in_kind"):
            total += line.get("amount_cents") or 0
    return total


def households_served_count(program):
    return len([h for h in households_of_program(program)
                if h.get("selection_status") == "CLOSED"])


def refresh_program(program):
    ledger = program_ledger(program)
    program.update(ledger)
    program["donated_material_fmv_cents"] = program_donated_fmv(program)
    program["households_served_count"] = households_served_count(program)
    program["program_posture"] = program_posture(program)
    return program


def refresh_site(site):
    site["cash_cost_cents"] = site_cash_cost(site)
    site["total_development_cost_cents"] = site_cash_cost(site) + site_donated_fmv(site)
    site["safety_posture"] = "HOLD" if site["readiness_status"] == "SAFETY_HOLD" else "CLEAR"
    return site


def refresh_shift(shift):
    seats = assignments_of_shift(shift)
    general = len([a for a in seats
                   if a["role"] == "GENERAL_VOLUNTEER"
                   and a["status"] in CONFIRMED_SEAT_STATUSES])
    trade = len([a for a in seats
                 if a["role"] == "SKILLED_TRADE"
                 and a["status"] in CONFIRMED_SEAT_STATUSES])
    shift["confirmed_general_count"] = general
    shift["confirmed_trade_count"] = trade
    slots = shift.get("volunteer_slots", 0)
    if not slots:
        shift["fill_ratio"] = Decimal(0)
    else:
        shift["fill_ratio"] = r4(dec(general) / dec(slots))
    return shift


def refresh_volunteer(volunteer):
    committed = Decimal(0)
    strikes = 0
    for seat in assignments_of_volunteer(volunteer):
        shift = shift_of_assignment(seat)
        if seat["status"] in HELD_SEAT_STATUSES and shift is not None:
            committed += dec(shift.get("duration_hours") or 0)
        if seat["status"] == "NO_SHOW":
            strikes += 1
    volunteer["assigned_hours_committed"] = r2(committed)
    volunteer["no_show_strikes"] = strikes
    return volunteer


def refresh_member(member):
    total = Decimal(0)
    for entry in db.entries.values():
        if entry.get("member_id") != member["id"]:
            continue
        if entry["status"] in LEDGER_STATUSES:
            total += dec(entry.get("hours_credited") or 0)
    member["credited_hours_to_date"] = r2(total)
    return member


def adult_occupant_count(household):
    count = len([m for m in members_of_household(household)
                 if m["status"] == "ACTIVE" and m.get("is_adult_occupant")])
    return max(1, count)


def refresh_household(household):
    household["adult_occupant_count"] = adult_occupant_count(household)
    total = Decimal(0)
    family = Decimal(0)
    for entry in entries_of_household(household):
        if entry["status"] not in LEDGER_STATUSES:
            continue
        hours = dec(entry.get("hours_credited") or 0)
        total += hours
        member = db.members.get(entry.get("member_id"))
        if member is not None and member.get("relationship") not in ("APPLICANT", "CO_APPLICANT"):
            family += hours
    household["sweat_equity_credited_hours"] = r2(total)
    household["family_member_credited_hours"] = r2(family)
    required = household.get("sweat_equity_required_hours")
    if required is None:
        household["sweat_equity_satisfied"] = False
    else:
        household["sweat_equity_satisfied"] = r2(total) >= dec(required)
    return household


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    return value


def jsonable(value):
    """Decimals -> JSON numbers, datetimes -> ISO 8601 with three fractional digits."""
    return _convert(value)


def project(row):
    return {k: _convert(v) for k, v in row.items() if not k.startswith("_")}


def public_program(program):
    return project(refresh_program(program))


def public_household(household):
    return project(refresh_household(household))


def public_member(member):
    return project(refresh_member(member))


def public_review(review):
    return project(review)


def public_entry(entry):
    return project(entry)


def public_site(site):
    return project(refresh_site(site))


def public_shift(shift):
    return project(refresh_shift(shift))


def public_volunteer(volunteer):
    return project(refresh_volunteer(volunteer))


def public_assignment(assignment):
    return project(assignment)


def public_enrollment(enrollment):
    return project(enrollment)


def public_application(application):
    return project(application)


def public_cost_entry(entry):
    return project(entry)


def public_grant(grant):
    return project(grant)
