"""The declared calculations of the PRD, in their pinned order."""
from decimal import Decimal

import derive
from store import db
from util import (
    date_start, dec, ffloor, fceil, minutes, r2, r4, rcents,
    week_anchor, whole_years_between,
)

# --------------------------------------------------------------------------- #
# 1. selection scoring
# --------------------------------------------------------------------------- #
def income_basis_pair(household, basis):
    if basis == "FINAL":
        return (household.get("verified_annual_income_cents"),
                household.get("verified_housing_cost_cents"))
    return (household.get("self_reported_annual_income_cents"),
            household.get("self_reported_housing_cost_cents"))


def need_points(household, income, housing):
    monthly_gross = ffloor(dec(income or 0) / 12)
    if monthly_gross > 0:
        burden = r4(dec(housing or 0) / dec(monthly_gross))
    else:
        burden = Decimal(0)
    if burden >= Decimal("0.5000"):
        burden_points = 40
    elif burden >= Decimal("0.4000"):
        burden_points = 30
    elif burden >= Decimal("0.3000"):
        burden_points = 20
    else:
        burden_points = 0

    bedrooms = max(1, household.get("current_bedroom_count") or 0)
    crowding = r4(dec(household.get("household_size") or 0) / dec(bedrooms))
    if crowding >= Decimal("2"):
        crowding_points = 30
    elif crowding >= Decimal("1.5"):
        crowding_points = 20
    else:
        crowding_points = 0

    deficiencies = household.get("habitability_deficiency_count") or 0
    if deficiencies >= 2:
        substandard_points = 30
    elif deficiencies == 1:
        substandard_points = 15
    else:
        substandard_points = 0

    return burden_points + crowding_points + substandard_points


def ability_points(household, income):
    monthly_gross = ffloor(dec(income or 0) / 12)
    if monthly_gross > 0:
        dti = r4(dec(household.get("monthly_debt_payment_cents") or 0) / dec(monthly_gross))
    else:
        dti = Decimal(0)
    if dti <= Decimal("0.1300"):
        dti_points = 50
    elif dti <= Decimal("0.2500"):
        dti_points = 35
    elif dti <= Decimal("0.3600"):
        dti_points = 20
    else:
        dti_points = 0

    credit = household.get("credit_score") or 0
    if credit >= 620:
        credit_points = 25
    elif credit >= 580:
        credit_points = 15
    else:
        credit_points = 0

    months = household.get("on_time_housing_payment_months") or 0
    history_points = 25 if months >= 12 else 0

    return dti_points + credit_points + history_points


def composite_score(need, ability, willingness):
    if willingness is None:
        return None
    return r2(Decimal("0.40") * dec(need)
              + Decimal("0.35") * dec(ability)
              + Decimal("0.25") * dec(willingness))


def score_household(household, basis, willingness=None):
    """Write need/ability/ami_pct (and composite when willingness exists)."""
    program = derive.program_of_household(household)
    income, housing = income_basis_pair(household, basis)
    need = need_points(household, income, housing)
    ability = ability_points(household, income)
    median = (program or {}).get("ami_median_income_cents") or 0
    ami_pct = r4(dec(income or 0) / dec(median)) if median else Decimal(0)
    household["need_score"] = need
    household["ability_to_pay_score"] = ability
    household["ami_pct"] = ami_pct
    household["score_basis"] = basis
    household["willingness_score"] = willingness
    household["composite_selection_score"] = composite_score(need, ability, willingness)
    return household


# --------------------------------------------------------------------------- #
# 2. committee quorum, willingness and veto
# --------------------------------------------------------------------------- #
DIMENSIONS = ("NEED", "ABILITY", "WILLINGNESS")


def effective_reviews(household):
    best = {}
    for review in db.reviews.values():
        if review.get("household_id") != household["id"]:
            continue
        if review.get("status") != "SUBMITTED":
            continue
        key = (review.get("reviewer_user_id"), review.get("dimension"))
        current = best.get(key)
        if current is None or (review["created_at"], review["_seq"]) > (
            current["created_at"], current["_seq"]
        ):
            best[key] = review
    return list(best.values())


def committee_state(household, program):
    rows = effective_reviews(household)
    reviewers = {}
    for review in rows:
        reviewers.setdefault(review["dimension"], set()).add(review["reviewer_user_id"])
    quorum = (program or {}).get("committee_quorum") or 0
    quorum_met = all(len(reviewers.get(dim, set())) >= quorum for dim in DIMENSIONS)
    willingness_rows = [r for r in rows if r["dimension"] == "WILLINGNESS"]
    if willingness_rows:
        total = sum((dec(r["score"]) for r in willingness_rows), Decimal(0))
        willingness = r2(total / dec(len(willingness_rows)))
    else:
        willingness = None
    veto = any(r.get("recommendation") == "VETO_WILLINGNESS" for r in willingness_rows)
    return quorum_met, willingness, veto


# --------------------------------------------------------------------------- #
# 3. frozen sweat equity requirement
# --------------------------------------------------------------------------- #
def frozen_required_hours(program, household):
    base = dec(program.get("sweat_equity_base_hours_required") or 0)
    extra = max(0, (household.get("adult_occupant_count") or 1) - 1)
    total = base + dec(50) * dec(extra)
    return r2(min(total, dec(500)))


# --------------------------------------------------------------------------- #
# 4. waitlist promotion selector
# --------------------------------------------------------------------------- #
def waitlist_pool(program):
    pool = []
    for household in derive.households_of_program(program):
        if household.get("selection_status") != "WAITLISTED":
            continue
        if household.get("partnership_readiness") == "WITHDRAWN":
            continue
        composite = household.get("composite_selection_score")
        if composite is None or dec(composite) < Decimal("55.00"):
            continue
        pool.append(household)
    pool.sort(key=lambda h: (
        -dec(h.get("composite_selection_score") or 0),
        -dec(h.get("need_score") or 0),
        h["created_at"],
        h["_seq"],
    ))
    return pool


def ready_site_capacity(program):
    return len([s for s in derive.sites_of_program(program)
                if s.get("readiness_status") == "READY_TO_BUILD"
                and s.get("assigned_household_id") is None])


# --------------------------------------------------------------------------- #
# 5. sweat equity credit waterfall
# --------------------------------------------------------------------------- #
BASE_WEIGHT = {
    "CONSTRUCTION": Decimal("1.00"),
    "RESTORE_STORE": Decimal("1.00"),
    "HOMEOWNER_EDUCATION": Decimal("1.00"),
    "OTHER_AFFILIATE": Decimal("0.75"),
    "ADVOCACY": Decimal("0.50"),
}
CATEGORY_CAP = {
    "HOMEOWNER_EDUCATION": Decimal("25.00"),
    "ADVOCACY": Decimal("10.00"),
}
UNCAPPED = Decimal("999999.00")
MINOR_CATEGORIES = ("RESTORE_STORE", "ADVOCACY")


def member_age_at(member, work_date):
    birth = date_start(member.get("birth_date"))
    return whole_years_between(birth, work_date)


def category_used(household, category):
    total = Decimal(0)
    for entry in derive.entries_of_household(household):
        if entry.get("category") != category:
            continue
        if entry["status"] not in derive.LEDGER_STATUSES:
            continue
        total += dec(entry.get("hours_credited") or 0)
    return total


def family_allowance(household):
    required = household.get("sweat_equity_required_hours")
    if required is None:
        return Decimal(0)
    return dec(ffloor(dec(required) / dec(2)))


def is_family_scoped(member):
    return member.get("relationship") not in ("APPLICANT", "CO_APPLICANT")


# --------------------------------------------------------------------------- #
# 6. shift geometry
# --------------------------------------------------------------------------- #
SITE_OCCUPYING = ("SCHEDULED", "OPEN", "LOCKED", "COMPLETED")
BUFFER = minutes(60)


def duration_hours(start_at, end_at):
    seconds = dec((end_at - start_at).total_seconds())
    return r2(seconds / dec(3600))


def site_window_conflict(site, start_at, end_at, exclude_id=None):
    for shift in derive.shifts_of_site(site):
        if exclude_id is not None and shift["id"] == exclude_id:
            continue
        if shift["status"] not in SITE_OCCUPYING:
            continue
        if start_at < shift["end_at"] + BUFFER and shift["start_at"] < end_at + BUFFER:
            return shift
    return None


def held_seats(volunteer_id, exclude_id=None):
    rows = []
    for seat in db.assignments.values():
        if seat.get("volunteer_id") != volunteer_id:
            continue
        if exclude_id is not None and seat["id"] == exclude_id:
            continue
        if seat["status"] in derive.HELD_SEAT_STATUSES:
            rows.append(seat)
    return rows


def volunteer_overlap(volunteer_id, candidate_shift):
    for seat in held_seats(volunteer_id):
        shift = derive.shift_of_assignment(seat)
        if shift is None:
            continue
        if candidate_shift["start_at"] < shift["end_at"] and \
                shift["start_at"] < candidate_shift["end_at"]:
            return seat
    return None


def weekly_hours(volunteer_id, candidate_shift):
    anchor = week_anchor(candidate_shift["start_at"])
    end = anchor + minutes(60 * 24 * 7)
    total = Decimal(0)
    for seat in held_seats(volunteer_id):
        shift = derive.shift_of_assignment(seat)
        if shift is None:
            continue
        if anchor <= shift["start_at"] < end:
            total += dec(shift.get("duration_hours") or 0)
    return total


def weekly_cap(volunteer):
    return Decimal("16.00") if volunteer.get("is_minor") else Decimal("40.00")


def min_general_confirmations(shift):
    slots = shift.get("volunteer_slots") or 0
    return fceil(Decimal("0.60") * dec(slots))


def seat_count(shift, role):
    return len([a for a in derive.assignments_of_shift(shift)
                if a.get("role") == role and a["status"] in derive.HELD_SEAT_STATUSES])


# --------------------------------------------------------------------------- #
# 7. affordability structure
# --------------------------------------------------------------------------- #
def structure(appraised_value_cents, income_basis_annual_cents):
    appraised = int(appraised_value_cents or 0)
    monthly_gross = ffloor(dec(income_basis_annual_cents or 0) / dec(12))
    tax_monthly = rcents(dec(appraised) * Decimal("0.0125") / dec(12))
    insurance_annual = max(60000, rcents(dec(appraised) * Decimal("0.0035")))
    insurance_monthly = rcents(dec(insurance_annual) / dec(12))
    escrow_monthly = tax_monthly + insurance_monthly
    max_total = ffloor(dec(monthly_gross) * Decimal("0.30"))
    affordable_pi = max_total - escrow_monthly
    provisional = affordable_pi * 360
    if provisional >= rcents(Decimal("0.90") * dec(appraised)):
        term = 240
    elif provisional >= rcents(Decimal("0.70") * dec(appraised)):
        term = 300
    else:
        term = 360
    first = min(affordable_pi * term, appraised)
    silent = max(0, appraised - first)
    return {
        "monthly_gross_cents": monthly_gross,
        "tax_monthly_cents": tax_monthly,
        "insurance_annual_cents": insurance_annual,
        "insurance_monthly_cents": insurance_monthly,
        "escrow_monthly_cents": escrow_monthly,
        "max_total_payment_cents": max_total,
        "affordable_pi_payment_cents": affordable_pi,
        "provisional_principal": provisional,
        "term_months": term,
        "first_mortgage_principal_cents": first,
        "silent_second_amount_cents": silent,
    }


# --------------------------------------------------------------------------- #
# 8. lien forgiveness, recapture, satisfaction
# --------------------------------------------------------------------------- #
def elapsed_lien_months(application, now=None):
    from util import months_of_30_days
    recorded = application.get("lien_recorded_on")
    if recorded is None:
        return 0
    start = date_start(recorded) if isinstance(recorded, str) else recorded
    return months_of_30_days(start, now if now is not None else db.now())


def forgiveness(application, now=None):
    silent = application.get("silent_second_amount_cents") or 0
    months = elapsed_lien_months(application, now)
    if months < 60:
        forgiven = 0
    elif months >= 240:
        forgiven = silent
    else:
        forgiven = rcents(dec(silent) * dec(months - 60) / dec(180))
    outstanding = max(0, silent - forgiven)
    return forgiven, outstanding, months


def refresh_lien(application, now=None):
    if application.get("status") != "CLOSED":
        return application
    if application.get("lien_status") not in ("ACTIVE", "FORBEARANCE", "TRANSFER_PENDING"):
        return application
    forgiven, outstanding, _ = forgiveness(application, now)
    changed = (application.get("forgiven_amount_cents") != forgiven
               or application.get("lien_outstanding_cents") != outstanding)
    application["forgiven_amount_cents"] = forgiven
    application["lien_outstanding_cents"] = outstanding
    return changed


def shared_appreciation_pct(application, months):
    restriction = application.get("resale_restriction_months") or 240
    if months < 60:
        return Decimal("0.75")
    if months < 120:
        return Decimal("0.50")
    if months < restriction:
        return Decimal("0.25")
    return Decimal("0.00")


def recapture_total(application, sale_price_cents, now=None):
    forgiven, outstanding, months = forgiveness(application, now)
    appraised = application.get("appraised_value_cents") or 0
    appreciation = max(0, int(sale_price_cents or 0) - appraised)
    share = rcents(dec(appreciation) * shared_appreciation_pct(application, months))
    return outstanding + share, share


# --------------------------------------------------------------------------- #
# 9. impact report
# --------------------------------------------------------------------------- #
def impact_report(grant, program):
    from util import date_end
    period_start = date_start(grant.get("period_start"))
    period_end = date_end(grant.get("period_end"))
    served = []
    for household in derive.households_of_program(program):
        if household.get("selection_status") != "CLOSED":
            continue
        closing = household.get("closing_date")
        closing_dt = date_start(closing) if isinstance(closing, str) else closing
        if closing_dt is None:
            continue
        if period_start is not None and closing_dt < period_start:
            continue
        if period_end is not None and closing_dt > period_end:
            continue
        served.append(household)
    served.sort(key=lambda h: (h.get("closing_date") or h["created_at"], h["created_at"], h["_seq"]))

    full_basis = bool(grant.get("restricted_to_in_kind_reporting"))
    basis = "FULL_FMV_BASIS" if full_basis else "CASH_BASIS"

    households_served = len(served)
    persons_served = sum((h.get("household_size") or 0) for h in served)
    hours = Decimal(0)
    cost_total = 0
    subsidy_total = 0
    for household in served:
        derive.refresh_household(household)
        hours += dec(household.get("sweat_equity_credited_hours") or 0)
        for application in derive.applications_of_household(household):
            if application.get("status") != "CLOSED":
                continue
            subsidy_total += application.get("silent_second_amount_cents") or 0
            site = db.sites.get(application.get("build_site_id"))
            if site is None:
                continue
            derive.refresh_site(site)
            if full_basis:
                cost_total += site.get("total_development_cost_cents") or 0
            else:
                cost_total += site.get("cash_cost_cents") or 0

    if households_served:
        cost_per = rcents(dec(cost_total) / dec(households_served))
        subsidy_per = rcents(dec(subsidy_total) / dec(households_served))
        sweat_hours = r2(hours)
    else:
        cost_per = 0
        subsidy_per = 0
        sweat_hours = 0

    return {
        "households_served": households_served,
        "persons_served": persons_served,
        "sweat_equity_hours": sweat_hours,
        "basis": basis,
        "cost_total_cents": cost_total,
        "subsidy_total_cents": subsidy_total,
        "cost_per_household_cents": cost_per,
        "subsidy_per_household_cents": subsidy_per,
        "target_variance": households_served - (grant.get("households_served_target") or 0),
        "households": [derive.public_household(h) for h in served],
    }
