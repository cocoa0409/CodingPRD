"""Program constants, month/date arithmetic and every pure calculation
(PRD 2.6, 3.1, 3.2, 3.4, 3.6, 3.8, 3.9, 3.10)."""

import calendar
import re
from decimal import Decimal, ROUND_HALF_UP

# --- constants --------------------------------------------------------------
PAYMENT_STANDARD_CENTS = {1: 26000, 2: 39000, 3: 49000, 4: 59000, 5: 68000, 6: 76000}
ADDL_PERSON_CENTS = 7000
RATABLE_REDUCTION_FACTOR = Decimal("0.85")
MAX_GRANT_CENTS = 90000
MINIMUM_ISSUANCE_CENTS = 1000
FLAT_EARNED_DISREGARD_CENTS = 12000
EARNED_PCT_DISREGARD = Decimal("0.50")
CHILD_SUPPORT_PASSTHROUGH_CENTS = 5000
RESOURCE_LIMIT_CENTS = 200000
STATE_TIME_LIMIT_MONTHS = 24
FEDERAL_TIME_LIMIT_MONTHS = 60
MAX_HARDSHIP_EXTENSION_MONTHS = 12

REQUIRED_WEEKLY_HOURS = {
    "CHILD_ONLY": 0,
    "SINGLE_PARENT_CHILD_UNDER_6": 20,
    "SINGLE_PARENT": 30,
    "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE": 35,
    "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE": 55,
}
REQUIRED_CORE_WEEKLY_HOURS = {
    "CHILD_ONLY": 0,
    "SINGLE_PARENT_CHILD_UNDER_6": 20,
    "SINGLE_PARENT": 20,
    "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE": 30,
    "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE": 50,
}
WEEKS_PER_REPORT_MONTH = 4
SELF_REPORT_CREDIT_FACTOR = Decimal("0.50")
MAX_SCHEDULED_WEEKLY_HOURS = 60

CORE_CATEGORIES = [
    "UNSUBSIDIZED_EMPLOYMENT", "SUBSIDIZED_EMPLOYMENT", "WORK_EXPERIENCE",
    "ON_THE_JOB_TRAINING", "JOB_SEARCH_READINESS", "COMMUNITY_SERVICE",
    "VOCATIONAL_EDUCATION",
]
NON_CORE_CATEGORIES = [
    "JOB_SKILLS_TRAINING_DIRECT", "EDUCATION_RELATED_TO_EMPLOYMENT", "SECONDARY_SCHOOL",
]
ACTIVITY_CATEGORIES = CORE_CATEGORIES + NON_CORE_CATEGORIES

SANCTION_PCT_BY_LEVEL = {0: Decimal("0.00"), 1: Decimal("0.25"),
                         2: Decimal("0.50"), 3: Decimal("1.00")}
CONCILIATION_DAYS = 30
SUPPORTIVE_CAPS_CENTS = {"TRANSPORTATION": 60000, "CHILD_CARE": 240000,
                         "WORK_EXPENSE": 30000}
SUPPORTIVE_CASE_FY_CAP_CENTS = 300000
DIVERSION_MULTIPLIER = 3
DIVERSION_MAX_CENTS = 200000
DIVERSION_MAX_INELIGIBILITY_MONTHS = 12
RECOUPMENT_PCT_BY_CLAIM = {"AGENCY_ERROR": Decimal("0.05"),
                           "CLIENT_ERROR": Decimal("0.10"),
                           "SUSPECTED_FRAUD": Decimal("0.20")}
FRAUD_SUBSTANTIATED_RECOUPMENT_PCT = Decimal("0.25")
MIN_RECOUPMENT_CENTS = 1000
WPR_STATUTORY_TARGET_ALL_PCT = Decimal("50.00")
WPR_STATUTORY_TARGET_TWO_PARENT_PCT = Decimal("90.00")
CRC_MAX_PCT = Decimal("50.00")
SANCTION_DISREGARD_MAX_MONTHS = 3

FAMILY_TYPES = list(REQUIRED_WEEKLY_HOURS.keys())

# --- rounding ---------------------------------------------------------------

def round_half_up(value, places=0):
    quantum = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    result = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else result


def floor_div(numerator, denominator):
    return numerator // denominator


def pct(value):
    """Render a stored percentage/rate as a two-decimal number."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- month / date arithmetic (PRD 2.6) --------------------------------------
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def is_month(value):
    return isinstance(value, str) and bool(MONTH_RE.match(value))


def is_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    year, month, day = int(value[0:4]), int(value[5:7]), int(value[8:10])
    return day <= calendar.monthrange(year, month)[1]


def month_index(month):
    return int(month[0:4]) * 12 + int(month[5:7]) - 1


def month_from_index(index):
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def month_add(month, count):
    return month_from_index(month_index(month) + count)


def month_first_day(month):
    return month + "-01"


def month_last_day(month):
    year, mon = int(month[0:4]), int(month[5:7])
    return "%s-%02d" % (month, calendar.monthrange(year, mon)[1])


def fiscal_year_of_date(date_str):
    year, month = int(date_str[0:4]), int(date_str[5:7])
    return year + 1 if month >= 10 else year


def quarter_months(fiscal_year, quarter):
    if quarter == 1:
        return ["%04d-10" % (fiscal_year - 1), "%04d-11" % (fiscal_year - 1),
                "%04d-12" % (fiscal_year - 1)]
    starts = {2: 1, 3: 4, 4: 7}
    first = starts[quarter]
    return ["%04d-%02d" % (fiscal_year, first + offset) for offset in range(3)]


def fiscal_year_months(fiscal_year):
    months = ["%04d-%02d" % (fiscal_year - 1, m) for m in (10, 11, 12)]
    months += ["%04d-%02d" % (fiscal_year, m) for m in range(1, 10)]
    return months


# --- household classification (PRD 3.1) ------------------------------------

def derive_family_type(adult_count, has_subsidized_child_care, youngest_child_age_months):
    if adult_count == 0:
        return "CHILD_ONLY"
    if adult_count >= 2 and has_subsidized_child_care:
        return "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE"
    if adult_count >= 2:
        return "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE"
    if youngest_child_age_months < 72:
        return "SINGLE_PARENT_CHILD_UNDER_6"
    return "SINGLE_PARENT"


def required_hours(family_type):
    weekly = REQUIRED_WEEKLY_HOURS[family_type]
    core_weekly = REQUIRED_CORE_WEEKLY_HOURS[family_type]
    return {
        "required_weekly_hours": weekly,
        "required_core_weekly_hours": core_weekly,
        "required_monthly_hours": weekly * WEEKS_PER_REPORT_MONTH,
        "required_core_monthly_hours": core_weekly * WEEKS_PER_REPORT_MONTH,
    }


# --- benefit and income (PRD 3.2) -------------------------------------------

def payment_standard(household_size):
    if household_size <= 6:
        return PAYMENT_STANDARD_CENTS[household_size]
    return PAYMENT_STANDARD_CENTS[6] + (household_size - 6) * ADDL_PERSON_CENTS


def benefit_amount(household_size, countable_income_cents, sanction_pct):
    std = payment_standard(household_size)
    deficit = max(0, std - countable_income_cents)
    pre_sanction = round_half_up(Decimal(deficit) * RATABLE_REDUCTION_FACTOR)
    capped = min(pre_sanction, MAX_GRANT_CENTS)
    sanction_cut = round_half_up(Decimal(capped) * Decimal(sanction_pct))
    after_sanction = capped - sanction_cut
    if after_sanction < MINIMUM_ISSUANCE_CENTS:
        return 0
    return after_sanction


def countable_income(income_sources, budgeting_method):
    if budgeting_method == "PROSPECTIVE":
        included = [s for s in income_sources
                    if s["verification_status"] == "VERIFIED" and s["is_recurring"]]
        monthly = {s["id"]: s["gross_monthly_cents"] for s in included}
    else:
        included = [s for s in income_sources
                    if s["verification_status"] in ("VERIFIED", "UNVERIFIED")]
        monthly = {}
        for source in included:
            total = (source["month_1_cents"] + source["month_2_cents"]
                     + source["month_3_cents"])
            # floored per source first (PRD 3.2: the rounding order is pinned);
            # Python's // already truncates toward negative infinity.
            monthly[source["id"]] = total // 3
    gross_earned = sum(monthly[s["id"]] for s in included
                       if s["source_type"] == "EARNED")
    gross_unearned = sum(monthly[s["id"]] for s in included
                         if s["source_type"] != "EARNED")
    child_support_total = sum(monthly[s["id"]] for s in included
                             if s["source_type"] == "UNEARNED_CHILD_SUPPORT")
    after_flat = max(0, gross_earned - FLAT_EARNED_DISREGARD_CENTS)
    countable_earned = round_half_up(Decimal(after_flat) * EARNED_PCT_DISREGARD)
    countable_unearned = gross_unearned - min(child_support_total,
                                              CHILD_SUPPORT_PASSTHROUGH_CENTS)
    return countable_earned + countable_unearned


def resource_countable_value(gross_value_cents, encumbrance_cents, exclusion_type):
    if exclusion_type != "NONE":
        return 0
    return max(0, gross_value_cents - encumbrance_cents)


# --- diversion (PRD 3.3) ----------------------------------------------------

def diversion_figures(basis_cents, application_month):
    lump_sum = min(basis_cents * DIVERSION_MULTIPLIER, DIVERSION_MAX_CENTS)
    months = -(-lump_sum // basis_cents)
    months = min(DIVERSION_MAX_INELIGIBILITY_MONTHS, months)
    return {
        "lump_sum_cents": lump_sum,
        "ineligibility_months": months,
        "ineligibility_end_month": month_add(application_month, months - 1),
    }


# --- participation (PRD 3.6) ------------------------------------------------

def credited_hours(raw_hours, verification_source):
    factor = SELF_REPORT_CREDIT_FACTOR if verification_source == "SELF_REPORT" \
        else Decimal("1")
    product = Decimal(raw_hours) * factor
    return int(product.to_integral_value(rounding="ROUND_FLOOR"))


def participation_predicate(month_core, month_non_core, required_core_monthly,
                            required_monthly):
    countable_non_core = month_non_core if month_core >= required_core_monthly else 0
    return (month_core >= required_core_monthly
            and (month_core + countable_non_core) >= required_monthly)


# --- overpayment (PRD 3.9) --------------------------------------------------

def established_amount(gross_amount_cents, offsetting_underpayment_cents,
                       computation_method):
    if computation_method == "GROSS":
        return gross_amount_cents
    return max(0, gross_amount_cents - offsetting_underpayment_cents)


def monthly_recoupment(benefit_amount_cents, claim_type, fraud_referral_status):
    if fraud_referral_status == "SUBSTANTIATED":
        percentage = FRAUD_SUBSTANTIATED_RECOUPMENT_PCT
    else:
        percentage = RECOUPMENT_PCT_BY_CLAIM[claim_type]
    sized = round_half_up(Decimal(benefit_amount_cents) * percentage)
    return max(MIN_RECOUPMENT_CENTS, sized)
