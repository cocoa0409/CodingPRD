"""The seven pinned calculations of the specification."""

import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import fail
from shapes import to_date
import lookups as lk

# ---- constants -------------------------------------------------------------
ALE_THRESHOLD = 50
FTE_HOURS_DIVISOR = 120
SEASONAL_EXCEPTION_MAX_MONTHS = 4
MONTHLY_FT_HOURS_THRESHOLD = 130
WAITING_PERIOD_MONTHS = 2
EXCLUSION_EMPLOYEES = 30
REHIRE_BREAK_DAYS = 91
CORRECTION_CYCLE_LIMIT = 3
TIER1_MAX_DAYS = 30
TIER1_CENTS = 6000
TIER2_CENTS = 12000
TIER3_CENTS = 31000
TIER4_CENTS = 63000

LINE15_CODES = ("1B", "1C", "1D", "1E", "1K")


# --------------------------------------------------------------------------- #
# rounding
# --------------------------------------------------------------------------- #
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    return int(math.floor(dec(value)))


def as_number(value):
    """Two-decimal Decimal rendered as a JSON number."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# 1. aggregate_fte_month_and_ale_status
# --------------------------------------------------------------------------- #
def headcount_index(members, count_year):
    index = {}
    for member in members:
        for row in lk.headcounts_of_member(member, count_year):
            index[(member["id"], row["month"])] = row
    return index


def aggregate_fte_and_status(counted_members):
    """Returns the determination outputs; the caller has already checked
    headcount completeness."""
    index = headcount_index(counted_members, "PRIOR_YEAR")

    monthly_group_fte = []
    for month in range(1, 13):
        total = Decimal(0)
        for member in counted_members:
            row = index[(member["id"], month)]
            member_fte = dec(row["full_time_employee_count"]) + round_half_up(
                dec(row["part_time_hours_total"]) / FTE_HOURS_DIVISOR, 2
            )
            total += member_fte
        monthly_group_fte.append(floor_int(round_half_up(total, 2)))

    annual_raw = round_half_up(dec(sum(monthly_group_fte)) / 12, 2)
    annual_average_fte = floor_int(annual_raw)

    months_over = [m for m in range(1, 13) if monthly_group_fte[m - 1] > ALE_THRESHOLD]
    seasonal_ok = len(months_over) <= SEASONAL_EXCEPTION_MAX_MONTHS
    if seasonal_ok:
        for month in months_over:
            excess = sum(
                index[(member["id"], month)].get("seasonal_excess_count") or 0
                for member in counted_members
            )
            if monthly_group_fte[month - 1] - excess > ALE_THRESHOLD:
                seasonal_ok = False
                break

    if annual_average_fte >= ALE_THRESHOLD and not (len(months_over) >= 1 and seasonal_ok):
        state, reason, applied = "DETERMINED_ALE", "THRESHOLD_MET", False
    elif annual_average_fte >= ALE_THRESHOLD:
        state, reason, applied = "DETERMINED_NON_ALE", "SEASONAL_EXCEPTION", True
    else:
        state, reason, applied = "DETERMINED_NON_ALE", "BELOW_THRESHOLD", False

    return {
        "monthly_group_fte": monthly_group_fte,
        "annual_average_fte_raw": as_number(annual_raw),
        "annual_average_fte": annual_average_fte,
        "determination_state": state,
        "ale_reason": reason,
        "seasonal_exception_applied": applied,
    }


def reporting_year_ft_months(member):
    return sum(
        row["full_time_employee_count"]
        for row in lk.headcounts_of_member(member, "REPORTING_YEAR")
        if 1 <= row["month"] <= 12
    )


def reporting_year_monthly_ft_counts(member):
    by_month = {}
    for row in lk.headcounts_of_member(member, "REPORTING_YEAR"):
        by_month[row["month"]] = row["full_time_employee_count"]
    return [by_month.get(m, 0) for m in range(1, 13)]


# --------------------------------------------------------------------------- #
# 2. full_time_month_determination
# --------------------------------------------------------------------------- #
def effective_method(employee):
    if employee.get("measurement_method_override"):
        return employee["measurement_method_override"]
    member = lk.member_of_employee(employee)
    return member["measurement_method"] if member else "LOOK_BACK"


def governing_cycle(employee):
    """The employee's own INITIAL cycle, else the member's STANDARD cycle."""
    initial = initial_cycle(employee)
    if initial is not None:
        return initial
    from db import rows

    standard = [
        c
        for c in rows("measurement_cycles")
        if c["cycle_type"] == "STANDARD"
        and c["group_member_id"] == employee["group_member_id"]
        and not c.get("employee_id")
    ]
    if not standard:
        return None
    return max(standard, key=lambda c: c["_seq"])


def initial_cycle(employee):
    from db import rows

    candidates = [
        c
        for c in rows("measurement_cycles")
        if c["cycle_type"] == "INITIAL" and c.get("employee_id") == employee["id"]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["_seq"])


def year_pinned_months(employee, tax_year):
    hire = to_date(employee["hire_date"])
    if hire.year == tax_year:
        hire_month = hire.month
    elif hire.year < tax_year:
        hire_month = 0
    else:
        hire_month = 13

    term_month = None
    if employee.get("termination_date"):
        term = to_date(employee["termination_date"])
        if term.year == tax_year:
            term_month = term.month
        elif term.year < tax_year:
            term_month = 0
        else:
            term_month = 13
    return hire_month, term_month


def _hours_by_month(employee, year):
    out = {}
    for row in lk.hours_of_employee(employee):
        if row["measurement_year"] == year:
            out[row["month"]] = row
    return out


def full_time_determination(employee, season):
    """Returns (full_time flags, ft sources, measured_average_hours as Decimal|None).

    Raises ERR_MEASUREMENT_METHOD_CONFLICT / ERR_NO_HOURS_DATA per the ladder.
    """
    tax_year = season["tax_year"]
    method = effective_method(employee)
    reporting_hours = _hours_by_month(employee, tax_year)

    full_time = [False] * 12
    sources = ["MONTHLY_ACTUAL"] * 12
    average = None

    if method == "MONTHLY":
        for month in range(1, 13):
            row = reporting_hours.get(month)
            counted = row["counted_hours"] if row else 0
            full_time[month - 1] = counted >= MONTHLY_FT_HOURS_THRESHOLD
            sources[month - 1] = "MONTHLY_ACTUAL"
    else:
        cycle = governing_cycle(employee)
        if cycle is None:
            fail("ERR_MEASUREMENT_METHOD_CONFLICT", "No governing measurement cycle for this employee.")
        m_start = to_date(cycle["measurement_start_date"])
        m_end = to_date(cycle["measurement_end_date"])
        counted_rows = []
        for row in lk.hours_of_employee(employee):
            first = date(row["measurement_year"], row["month"], 1)
            if m_start <= first <= m_end and not row["excluded_from_denominator"]:
                counted_rows.append(row)
        if not counted_rows:
            fail("ERR_NO_HOURS_DATA", "The look-back denominator is empty.")
        total = sum(row["counted_hours"] for row in counted_rows)
        average = round_half_up(dec(total) / len(counted_rows), 2)
        stable_verdict = average >= dec(cycle["hours_threshold_monthly"])
        s_start = to_date(cycle["stability_start_date"])
        s_end = to_date(cycle["stability_end_date"])
        for month in range(1, 13):
            first = date(tax_year, month, 1)
            if s_start <= first <= s_end:
                full_time[month - 1] = bool(stable_verdict)
                sources[month - 1] = "LOOK_BACK_STABILITY"
            else:
                row = reporting_hours.get(month)
                counted = row["counted_hours"] if row else 0
                full_time[month - 1] = counted >= MONTHLY_FT_HOURS_THRESHOLD
                sources[month - 1] = "MONTHLY_ACTUAL"

    hire_month, term_month = year_pinned_months(employee, tax_year)
    for month in range(1, 13):
        if month < hire_month or (term_month is not None and month > term_month):
            full_time[month - 1] = False
            sources[month - 1] = "NOT_EMPLOYED"

    return full_time, sources, average


# --------------------------------------------------------------------------- #
# 3 + 4. affordability and the twelve monthly codes
# --------------------------------------------------------------------------- #
def fpl_threshold_cents(season):
    pct = dec(season["affordability_pct"])
    return rhu_cents(dec(season["mainland_fpl_annual_cents"]) * pct / 12)


def governing_offer(offers, month):
    candidates = [o for o in offers if month in (o.get("covered_months") or [])]
    if not candidates:
        return None
    return max(candidates, key=lambda o: (o["effective_start_date"], o["_seq"]))


def covered_months_for(start, end, tax_year):
    """Months of `tax_year` entirely inside the half-open interval."""
    start_date = to_date(start)
    end_date = to_date(end)
    months = []
    for month in range(1, 13):
        first = date(tax_year, month, 1)
        next_first = date(tax_year + 1, 1, 1) if month == 12 else date(tax_year, month + 1, 1)
        if first >= start_date and next_first <= end_date:
            months.append(month)
    return months


def select_safe_harbor(employee, season, preference, offered_month_count):
    pct = dec(season["affordability_pct"])
    if preference == "NONE":
        return "NONE", None

    w2_wages = employee.get("w2_box1_wages_cents") or 0
    w2_available = w2_wages > 0 and offered_month_count > 0
    if employee["is_hourly"]:
        rate_available = (employee.get("hourly_rate_cents") or 0) > 0
    else:
        rate_available = (employee.get("monthly_salary_cents") or 0) > 0

    order = [preference] + [h for h in ("W2", "RATE_OF_PAY", "FPL") if h != preference]
    for harbor in order:
        if harbor == "W2" and w2_available:
            return "W2", rhu_cents(dec(w2_wages) * pct / offered_month_count)
        if harbor == "RATE_OF_PAY" and rate_available:
            if employee["is_hourly"]:
                value = dec(employee["hourly_rate_cents"]) * MONTHLY_FT_HOURS_THRESHOLD * pct
            else:
                value = dec(employee["monthly_salary_cents"]) * pct
            return "RATE_OF_PAY", rhu_cents(value)
        if harbor == "FPL":
            return "FPL", fpl_threshold_cents(season)
    return "NONE", None


def compute_lines(employee, season, form_plan_preference):
    """Runs the pinned seven-step order and returns (line dicts, roll-ups)."""
    tax_year = season["tax_year"]
    full_time, sources, average = full_time_determination(employee, season)
    offers = lk.offers_of_employee(employee)
    hire_month, term_month = year_pinned_months(employee, tax_year)
    cycle = initial_cycle(employee)
    fpl_cents = fpl_threshold_cents(season)

    lines = []
    for month in range(1, 13):
        offer = governing_offer(offers, month)
        line = {
            "month": month,
            "line14_code": None,
            "line15_amount_cents": None,
            "line16_code": None,
            "full_time_flag": full_time[month - 1],
            "ft_source": sources[month - 1],
            "affordability_threshold_cents": None,
            "safe_harbor_applied": None,
            "special_situation": "NONE",
            "assessable": False,
            "_offer": offer,
            "_lnap": False,
            "_settled": False,
        }

        # step A — employment overlay
        if month < hire_month or (term_month is not None and month > term_month):
            line["line14_code"] = "1H"
            line["line15_amount_cents"] = None
            line["line16_code"] = "2A"
            line["full_time_flag"] = False
            line["ft_source"] = "NOT_EMPLOYED"
            line["special_situation"] = "NONE"
            line["assessable"] = False
            line["_settled"] = True
            lines.append(line)
            continue

        # step B — limited non-assessment period
        by_waiting = hire_month >= 1 and hire_month <= month <= hire_month + WAITING_PERIOD_MONTHS
        by_initial = False
        if cycle is not None:
            first = date(tax_year, month, 1)
            if to_date(cycle["measurement_start_date"]) <= first <= to_date(cycle["admin_period_end_date"]):
                by_initial = True
        line["_lnap"] = bool(by_waiting or by_initial)
        if by_waiting:
            line["special_situation"] = "WAITING_PERIOD"
        elif by_initial:
            line["special_situation"] = "INITIAL_MEASUREMENT"
        else:
            line["special_situation"] = "NONE"

        # step C — line 14
        if offer is None or offer["offer_kind"] == "NO_OFFER":
            code = "1H"
        elif offer["offer_kind"] == "COBRA_TERMINATED":
            code = "1H"
        elif offer["offer_kind"] == "RETIREE_COVERAGE":
            code = "1G"
        elif not offer["minimum_value"]:
            code = "1F"
        elif offer["conditional_spouse_offer"]:
            code = "1K"
        elif offer["offer_kind"] == "MEC_MV_FAMILY" and offer["lowest_cost_self_only_cents"] <= fpl_cents:
            code = "1A"
        elif offer["offer_kind"] == "MEC_MV_FAMILY":
            code = "1E"
        elif offer["offer_kind"] == "MEC_MV_SELF_DEP":
            code = "1C"
        elif offer["offer_kind"] == "MEC_MV_SELF_SPOUSE":
            code = "1D"
        else:
            code = "1B"
        line["line14_code"] = code

        # step D — line 15
        if code in LINE15_CODES and offer is not None:
            line["line15_amount_cents"] = offer["lowest_cost_self_only_cents"]
        else:
            line["line15_amount_cents"] = None

        lines.append(line)

    # step 3 / 4 — offered month count feeds the W-2 denominator
    offered_month_count = sum(1 for l in lines if l["line14_code"] != "1H")

    # step E — affordability
    harbor, threshold = select_safe_harbor(employee, season, form_plan_preference, offered_month_count)

    # step F — line 16, then step G — assessability
    for line in lines:
        if line["_settled"]:
            continue
        line["safe_harbor_applied"] = harbor
        line["affordability_threshold_cents"] = threshold
        offer = line["_offer"]
        month = line["month"]
        affordable = (
            harbor != "NONE"
            and threshold is not None
            and offer is not None
            and offer["lowest_cost_self_only_cents"] <= threshold
        )
        if offer is not None and offer["enrolled"]:
            line["line16_code"] = "2C"
        elif line["_lnap"]:
            line["line16_code"] = "2D"
        elif not line["full_time_flag"]:
            line["line16_code"] = "2B"
        elif (
            term_month is not None
            and month == term_month
            and offer is not None
            and offer["offer_kind"] != "NO_OFFER"
        ):
            line["line16_code"] = "2B"
        elif affordable and harbor == "W2":
            line["line16_code"] = "2F"
        elif affordable and harbor == "FPL":
            line["line16_code"] = "2G"
        elif affordable and harbor == "RATE_OF_PAY":
            line["line16_code"] = "2H"
        else:
            line["line16_code"] = None
        line["assessable"] = bool(line["full_time_flag"] and line["line16_code"] is None)

    for line in lines:
        line.pop("_offer", None)
        line.pop("_lnap", None)
        line.pop("_settled", None)

    rollups = rollup(lines)
    return lines, rollups, full_time, sources, average


def rollup(lines):
    codes = [l["line14_code"] for l in lines]
    all_12 = codes[0] if len(set(codes)) == 1 else None
    return {
        "all_12_months_code": all_12,
        "ft_month_count": sum(1 for l in lines if l["full_time_flag"]),
        "offered_month_count": sum(1 for l in lines if l["line14_code"] != "1H"),
        "assessable_month_count": sum(1 for l in lines if l["assessable"]),
        "line15_total_cents": sum(
            l["line15_amount_cents"] for l in lines if l["line15_amount_cents"] is not None
        ),
    }


# --------------------------------------------------------------------------- #
# 5. penalty recomputation and allocation
# --------------------------------------------------------------------------- #
def allocate_units(total_units, members):
    """Largest remainder over reporting_year_ft_months; units sum to total."""
    result = dict((m["id"], 0) for m in members)
    weights = dict((m["id"], m.get("reporting_year_ft_months") or 0) for m in members)
    total_weight = sum(weights.values())
    if not members or total_weight <= 0 or total_units <= 0:
        return result
    entries = []
    for member in members:
        weight = weights[member["id"]]
        numerator = total_units * weight
        base = numerator // total_weight
        remainder_num = numerator - base * total_weight
        result[member["id"]] = base
        entries.append((remainder_num, weight, member))
    left = total_units - sum(result.values())
    entries.sort(key=lambda e: (-e[0], -e[1], e[2]["_seq"]))
    for index in range(left):
        result[entries[index][2]["id"]] += 1
    return result


def allocate_cents(total_cents, members):
    """Largest-remainder floors; the whole leftover goes to the largest weight."""
    result = dict((m["id"], 0) for m in members)
    weights = dict((m["id"], m.get("reporting_year_ft_months") or 0) for m in members)
    total_weight = sum(weights.values())
    if not members or total_weight <= 0 or total_cents <= 0:
        return result
    for member in members:
        result[member["id"]] = (total_cents * weights[member["id"]]) // total_weight
    left = total_cents - sum(result.values())
    if left:
        winner = sorted(members, key=lambda m: (-weights[m["id"]], m["_seq"]))[0]
        result[winner["id"]] += left
    return result


def recompute_penalty(notice, group, season):
    """Runs the six pinned steps.  Mutates evidence `applied` flags."""
    penalty_a_monthly = floor_int(dec(season["penalty_a_annual_cents"]) / 12)
    penalty_b_monthly = floor_int(dec(season["penalty_b_annual_cents"]) / 12)

    a_months = set(notice["asserted_a_months"] or [])
    b_pairs = set(
        (entry["employee_id"], entry["month"]) for entry in (notice["asserted_b_employee_months"] or [])
    )
    ft_reduction = dict((m, 0) for m in range(1, 13))

    evidence = sorted(lk.evidence_of_notice(notice), key=lambda e: e["_seq"])
    for row in evidence:
        row["applied"] = False
    for row in evidence:
        kind = row["evidence_type"]
        if kind == "MEC_OFFER_PROOF":
            if row["month"] in a_months:
                a_months.discard(row["month"])
                row["applied"] = True
        elif kind == "FT_STATUS_DISPUTE":
            pair = (row.get("employee_id"), row["month"])
            if pair in b_pairs:
                b_pairs.discard(pair)
                row["applied"] = True
                ft_reduction[row["month"]] = ft_reduction.get(row["month"], 0) + 1
        elif kind == "OFFER_PROOF":
            pair = (row.get("employee_id"), row["month"])
            if pair in b_pairs:
                b_pairs.discard(pair)
                row["applied"] = True

    active_members = lk.members_of_group(group, active_only=True)
    group_ft = {}
    for month in range(1, 13):
        total = 0
        for member in active_members:
            for hc in lk.headcounts_of_member(member, "REPORTING_YEAR"):
                if hc["month"] == month:
                    total += hc["full_time_employee_count"]
        group_ft[month] = total - ft_reduction.get(month, 0)

    a_cents = 0
    for month in sorted(a_months):
        chargeable = group_ft.get(month, 0) - EXCLUSION_EMPLOYEES
        if chargeable < 0:
            chargeable = 0
        a_cents += chargeable * penalty_a_monthly

    surviving_pairs = [pair for pair in b_pairs if pair[1] not in a_months]
    b_cents = len(surviving_pairs) * penalty_b_monthly
    recalculated = a_cents + b_cents

    exclusion = allocate_units(EXCLUSION_EMPLOYEES, active_members)
    cents = allocate_cents(recalculated, active_members)

    return {
        "a_month_penalty_cents": a_cents,
        "b_month_penalty_cents": b_cents,
        "recalculated_amount_cents": recalculated,
        "applied_evidence_count": sum(1 for row in evidence if row["applied"]),
        "exclusion_by_member": exclusion,
        "cents_by_member": cents,
        "active_members": active_members,
    }


# --------------------------------------------------------------------------- #
# 6. transmission channel requirement
# --------------------------------------------------------------------------- #
COUNTED_SIBLING_STATES = ("BUILT", "TRANSMITTED", "ACCEPTED", "ACCEPTED_WITH_ERRORS", "PARTIALLY_ACCEPTED")


def transmission_channel(transmittal, member, season):
    own = sum(1 for f in lk.forms_of_transmittal(transmittal) if f["filing_status"] != "VOIDED")
    other = 0
    for sibling in lk.transmittals_of_member(member):
        if sibling["id"] == transmittal["id"]:
            continue
        if sibling["status"] in COUNTED_SIBLING_STATES:
            other += sibling.get("form_count") or 0
    aggregate = own + other + 1
    channel = "ELECTRONIC" if aggregate >= season["electronic_filing_threshold"] else "ANY"
    return aggregate, channel


# --------------------------------------------------------------------------- #
# 7. late furnishing penalty
# --------------------------------------------------------------------------- #
def late_furnishing_penalty(season, furnish_date, intentional_disregard):
    deadline = to_date(season["furnishing_deadline_date"])
    cutoff = to_date(season["tier2_cutoff_date"])
    days_late = (furnish_date - deadline).days
    if days_late <= 0:
        penalty = 0
    elif days_late <= TIER1_MAX_DAYS:
        penalty = TIER1_CENTS
    elif furnish_date < cutoff:
        penalty = TIER2_CENTS
    else:
        penalty = TIER3_CENTS
    if intentional_disregard:
        penalty = TIER4_CENTS
    return penalty


def day_difference(later, earlier):
    return (later - earlier).days


def add_days(value, days):
    return value + timedelta(days=days)
