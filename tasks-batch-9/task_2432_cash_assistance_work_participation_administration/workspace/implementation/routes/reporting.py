"""Federal reporting periods, participation rates and the caseload reduction
credit (PRD 3.10)."""

from decimal import Decimal

from flask import Blueprint

import guards
from calc import (CRC_MAX_PCT, SANCTION_DISREGARD_MAX_MONTHS,
                  WPR_STATUTORY_TARGET_ALL_PCT, fiscal_year_months,
                  quarter_months, round_half_up)
from domain import (case_month_participated, lookup, rows_where)
from errors import fail
from guards import Fields, raw_body, require, require_different_actor
from respond import created, listing, ok, pagination
from store import db, new_record, touch

bp = Blueprint("reporting", __name__)

TWO_PARENT_TYPES = ("TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE",
                    "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE")


def _period(period_id):
    return lookup("reporting_periods", period_id, "ERR_REPORTING_PERIOD_NOT_FOUND")


def _two_places(value):
    return float(round_half_up(value, 2))


def _rate(numerator, denominator):
    if denominator == 0:
        return 0.00
    return _two_places(Decimal(numerator) * 100 / Decimal(denominator))


def _sanctioned_as_of(case_id, month):
    """A case-month counts as sanctioned per PRD 3.10 stage two."""
    for episode in rows_where("compliance_episodes", case_id=case_id):
        imposed = episode.get("sanction_imposed_month")
        if imposed and imposed <= month and \
                episode["status"] in ("SANCTION_IMPOSED", "CURE_PENDING"):
            return True
    return False


def _denominators(fiscal_year):
    """Stage one (raw) and stage two (adjusted) monthly denominators."""
    months = fiscal_year_months(fiscal_year)
    issued = {}
    for row in db.time_limit_months.values():
        if not row.get("assistance_issued"):
            continue
        issued.setdefault(row["benefit_month"], set()).add(row["case_id"])
    raw = {}
    for month in months:
        members = []
        for case_id in issued.get(month, ()):  # deterministic order below
            case = db.cases.get(case_id)
            if case is None or case["family_type"] == "CHILD_ONLY":
                continue
            members.append(case_id)
        raw[month] = set(members)

    adjusted = {month: set(raw[month]) for month in months}
    case_ids = set()
    for month in months:
        case_ids |= raw[month]
    for case_id in case_ids:
        disregarded = 0
        for month in months:
            if case_id not in raw[month]:
                continue
            if not _sanctioned_as_of(case_id, month):
                continue
            if disregarded < SANCTION_DISREGARD_MAX_MONTHS:
                adjusted[month].discard(case_id)
                disregarded += 1
    return raw, adjusted


@bp.post("/reporting-periods")
def open_period():
    require(guards.ANALYST)
    fields = Fields(raw_body())
    fields.integer("fiscal_year")
    fields.integer("quarter", minimum=1, maximum=4)
    fields.number("prior_year_caseload", minimum=0)
    fields.number("eligibility_change_caseload_effect", minimum=0)

    period = new_record({
        "fiscal_year": fields["fiscal_year"],
        "quarter": fields["quarter"],
        "prior_year_caseload": fields["prior_year_caseload"],
        "eligibility_change_caseload_effect":
            fields["eligibility_change_caseload_effect"],
        "current_caseload": 0.00,
        "wpr_all_families_pct": 0.00,
        "wpr_two_parent_pct": 0.00,
        "caseload_reduction_credit_pct": 0.00,
        "adjusted_target_all_families_pct": 50.00,
        "target_met": False,
        "status": "OPEN",
        "calculated_by_user_id": None,
        "certified_by_user_id": None,
    })
    db.reporting_periods[period["id"]] = period
    return created(period)


@bp.get("/reporting-periods/<period_id>")
def read_period(period_id):
    require(*guards.STAFF_ROLES)
    return ok(_period(period_id))


@bp.post("/reporting-periods/<period_id>/calculate")
def calculate(period_id):
    actor = require(guards.ANALYST)
    period = _period(period_id)
    if period["status"] not in ("OPEN", "CALCULATED"):
        fail("ERR_INVALID_PERIOD_STATE",
             "A CERTIFIED period may not be recalculated.")
    fiscal_year = period["fiscal_year"]
    months = quarter_months(fiscal_year, period["quarter"])
    raw, adjusted = _denominators(fiscal_year)

    all_denominator = 0
    all_numerator = 0
    two_denominator = 0
    two_numerator = 0
    raw_total = 0
    for month in months:
        raw_total += len(raw.get(month, ()))
        for case_id in adjusted.get(month, ()):
            case = db.cases[case_id]
            two_parent = case["family_type"] in TWO_PARENT_TYPES
            participated = case_month_participated(case, month)
            all_denominator += 1
            if two_parent:
                two_denominator += 1
            if participated:
                all_numerator += 1
                if two_parent:
                    two_numerator += 1

    wpr_all = _rate(all_numerator, all_denominator)
    wpr_two = _rate(two_numerator, two_denominator)
    current_caseload = _two_places(Decimal(raw_total) / Decimal(3))

    prior = Decimal(str(period["prior_year_caseload"]))
    if prior == 0:
        raw_decline = Decimal("0.00")
    else:
        raw_decline = round_half_up(
            (prior - Decimal(str(current_caseload))) * 100 / prior, 2)
    effect = Decimal(str(period["eligibility_change_caseload_effect"]))
    credit = round_half_up(Decimal(raw_decline) - effect, 2)
    if credit < 0:
        credit = Decimal("0.00")
    if credit > CRC_MAX_PCT:
        credit = CRC_MAX_PCT
    target = WPR_STATUTORY_TARGET_ALL_PCT - credit
    if target < 0:
        target = Decimal("0.00")

    period["current_caseload"] = current_caseload
    period["wpr_all_families_pct"] = wpr_all
    period["wpr_two_parent_pct"] = wpr_two
    period["caseload_reduction_credit_pct"] = _two_places(credit)
    period["adjusted_target_all_families_pct"] = _two_places(target)
    period["target_met"] = Decimal(str(wpr_all)) >= target
    period["status"] = "CALCULATED"
    period["calculated_by_user_id"] = actor.user_id
    touch(period)
    return ok(period)


@bp.post("/reporting-periods/<period_id>/certify")
def certify(period_id):
    actor = require(guards.ANALYST)
    period = _period(period_id)
    require_different_actor(actor, period["calculated_by_user_id"])
    if period["status"] != "CALCULATED":
        fail("ERR_INVALID_PERIOD_STATE",
             "Only a CALCULATED period may be certified.")
    months = quarter_months(period["fiscal_year"], period["quarter"])
    for report in db.participation_reports.values():
        if report["status"] == "SUBMITTED" and report["report_month"] in months:
            fail("ERR_UNVERIFIED_REPORTS_IN_QUARTER",
                 "Participation reports in this quarter are still unverified.")
    period["status"] = "CERTIFIED"
    period["certified_by_user_id"] = actor.user_id
    touch(period)
    return ok(period)
