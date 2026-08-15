"""Business logic: attribution model, jurisdiction resolution, nexus
recompute, employer posture, filing calendar generation, obligation amounts,
late penalties, UI experience rate, voluntary-contribution projection,
abatement eligibility, and the scheduled sweep."""
from datetime import date, datetime, timedelta, timezone

from core import (
    db,
    new_record,
    touch,
    rhu,
)

# Pinned calculation constants (SCAFFOLD Table 3)
NEXUS_DAYS_THRESHOLD = 20
NEXUS_WAGE_THRESHOLD_CENTS = 5000000
LAPSE_WINDOW_DAYS = 90
QUARTERLY_CAP_CENTS = 250000
SEMIWEEKLY_THRESHOLD_CENTS = 5000000
NEXT_DAY_THRESHOLD_CENTS = 1000000000
RATE_FLOOR_BP = 50
RATE_CEILING_BP = 900
MIN_PENALTY_CENTS = 2500
TIER1_MAX_DAYS = 5
TIER2_MAX_DAYS = 15
ABATEMENT_WINDOW_DAYS = 60
FIRST_TIME_LOOKBACK_YEARS = 3
DELINQUENT_PENALTY_CENTS = 1000000
DELINQUENT_LATE_DAYS = 30

OPEN_NOTICE_STATUSES = {"RECEIVED", "TRIAGED", "RESPONSE_IN_PROGRESS", "ESCALATED"}
MONITORED_NEXUS_STATUSES = {"WATCH", "THRESHOLD_MET", "CONFIRMED", "LAPSED"}
OPEN_OBLIGATION_STATUSES = {"SCHEDULED", "DUE", "LATE"}
NONTERMINAL_OBLIGATION_STATUSES = {"SCHEDULED", "DUE", "LATE", "FILED"}

HUGE_CENTS = 10**18


def d(dtm):
    """datetime -> date."""
    return dtm.date() if isinstance(dtm, datetime) else dtm


# ---------------------------------------------------------------------------
# Employer posture & aggregate counters (calc compliance_posture, PRD §2.7)
# ---------------------------------------------------------------------------
def recompute_employer():
    emp = db.employers.get(db.employer_id) if db.employer_id else None
    if emp is None:
        return
    open_notices = [n for n in db.notices.values() if n["status"] in OPEN_NOTICE_STATUSES]
    outstanding = sum(
        n["penalty_amount_cents"] - n["abated_amount_cents"] for n in open_notices
    )
    late_obligations = [o for o in db.obligations.values() if o["status"] == "LATE"]
    if (
        any(n["status"] == "ESCALATED" for n in open_notices)
        or any(o["late_days"] > DELINQUENT_LATE_DAYS for o in late_obligations)
        or outstanding > DELINQUENT_PENALTY_CENTS
    ):
        posture = "DELINQUENT"
    elif (
        open_notices
        or late_obligations
        or any(c["status"] == "THRESHOLD_MET" for c in db.nexus_cases.values())
    ):
        posture = "WATCH"
    else:
        posture = "GOOD_STANDING"
    registered_states = {
        r["state_code"] for r in db.registrations.values() if r["status"] == "ACTIVE"
    }
    new_vals = {
        "compliance_posture": posture,
        "open_notice_count": len(open_notices),
        "outstanding_penalty_cents": outstanding,
        "registered_state_count": len(registered_states),
    }
    changed = any(emp.get(k) != v for k, v in new_vals.items())
    emp.update(new_vals)
    if changed:
        touch(emp)


# ---------------------------------------------------------------------------
# Attribution model (calc nexus_threshold_evaluation, PRD §3.3)
# ---------------------------------------------------------------------------
def covering_segment(emp_id, day):
    """Segment covering a date: effective_from <= day < effective_to (half-open).
    Both CURRENT and SUPERSEDED segments participate."""
    best = None
    for a in db.assignments.values():
        if a["employee_id"] != emp_id:
            continue
        if d(a["effective_from"]) <= day and (
            a["effective_to"] is None or day < d(a["effective_to"])
        ):
            if best is None or a["_seq"] > best["_seq"]:
                best = a
    return best


def day_state(emp, day):
    """State attributed for one employee on one day, with fallback to the
    employee's current work location when no segment covers the day."""
    if day < d(emp["hire_date"]):
        return None
    term = emp.get("termination_date")
    if term is not None and day > d(term):
        return None
    seg = covering_segment(emp["id"], day)
    if seg is not None:
        loc = db.locations.get(seg["work_location_id"])
        return loc["state_code"] if loc else None
    loc = db.locations.get(emp["current_work_location_id"])
    return loc["state_code"] if loc else None


def days_in_state(emp, state, w_start, w_end):
    """Calendar days in [w_start, w_end] (inclusive) attributed to state."""
    start = max(w_start, d(emp["hire_date"]))
    end = w_end
    term = emp.get("termination_date")
    if term is not None:
        end = min(end, d(term))
    if end < start:
        return 0
    cnt = 0
    cur = start
    while cur <= end:
        if day_state(emp, cur) == state:
            cnt += 1
        cur += timedelta(days=1)
    return cnt


# ---------------------------------------------------------------------------
# Nexus recompute + auto-transitions
# ---------------------------------------------------------------------------
def recompute_nexus_case(case):
    now = db.clock
    clock_d = d(now)
    state = case["state_code"]
    ytd_start = date(clock_d.year, 1, 1)
    trail_start = clock_d - timedelta(days=LAPSE_WINDOW_DAYS)
    days_ytd = 0
    days_trail = 0
    wages = 0
    for emp in db.employees.values():
        emp_days = days_in_state(emp, state, ytd_start, clock_d)
        days_ytd += emp_days
        days_trail += days_in_state(emp, state, trail_start, clock_d)
        wages += rhu(emp["annual_wage_cents"] * emp_days, 365)
    days_met = days_ytd >= NEXUS_DAYS_THRESHOLD
    wages_met = wages >= NEXUS_WAGE_THRESHOLD_CENTS
    if days_met and wages_met:
        basis = "BOTH"
    elif days_met:
        basis = "DAYS"
    elif wages_met:
        basis = "WAGES"
    else:
        basis = "NONE"
    case["employee_days_ytd"] = days_ytd
    case["employee_days_trailing_90d"] = days_trail
    case["wages_ytd_cents"] = wages
    case["threshold_basis"] = basis
    case["last_recomputed_at"] = now
    status = case["status"]
    if status == "WATCH" and basis != "NONE":
        case["status"] = "THRESHOLD_MET"
    elif status == "THRESHOLD_MET" and basis == "NONE":
        case["status"] = "WATCH"
    elif (
        status == "CONFIRMED"
        and days_trail == 0
        and case.get("established_date") is not None
        and now >= case["established_date"] + timedelta(days=LAPSE_WINDOW_DAYS)
    ):
        case["status"] = "LAPSED"
    elif status == "LAPSED" and days_trail > 0:
        case["status"] = "WATCH"
    elif status == "EXEMPT" and basis != "NONE":
        case["status"] = "WATCH"
    touch(case)
    recompute_employer()


def cascade_nexus(state_code):
    for case in db.nexus_cases.values():
        if case["state_code"] == state_code:
            recompute_nexus_case(case)
            return case
    return None


# ---------------------------------------------------------------------------
# Local jurisdiction resolution (calc local_jurisdiction_resolution, PRD §3.2)
# ---------------------------------------------------------------------------
def _local_candidates_work(loc):
    cands = []
    statewide = f"{loc['state_code']}-ALL"
    for ag in db.agencies.values():
        if (
            ag["agency_kind"] != "LOCAL"
            or not ag.get("is_active", True)
            or ag["state_code"] != loc["state_code"]
        ):
            continue
        lc = ag.get("locality_code")
        if lc is not None and lc == loc.get("postal_code"):
            spec = 0
        elif lc is not None and lc == (loc.get("city") or "").upper():
            spec = 1
        elif lc == statewide:
            spec = 2
        else:
            continue
        cands.append((ag, spec))
    return cands


def _local_candidates_resident(emp):
    cands = []
    state = emp["resident_state_code"]
    statewide = f"{state}-ALL"
    for ag in db.agencies.values():
        if (
            ag["agency_kind"] != "LOCAL"
            or not ag.get("is_active", True)
            or ag["state_code"] != state
        ):
            continue
        lc = ag.get("locality_code")
        rlc = emp.get("resident_locality_code")
        if lc is not None and rlc is not None and lc == rlc:
            spec = 1
        elif lc == statewide:
            spec = 2
        else:
            continue
        cands.append((ag, spec))
    return cands


def _rank(cands):
    return sorted(cands, key=lambda t: (t[0].get("precedence_rank", 100), t[1], t[0]["_seq"]))


def resolve_jurisdiction(emp, loc):
    """Returns (work_agency_id, resident_agency_id, precedence_trace)."""
    work_ranked = _rank(_local_candidates_work(loc))
    resident_ranked = _rank(_local_candidates_resident(emp))
    work = work_ranked[0][0] if work_ranked else None
    resident = resident_ranked[0][0] if resident_ranked else None

    work_part = (
        f"WORK[{work['agency_name']} rank={work.get('precedence_rank', 100)}"
        f" spec={work_ranked[0][1]}]"
        if work
        else "WORK[NONE_FOUND]"
    )
    resident_part = (
        f"RESIDENT[{resident['agency_name']} rank={resident.get('precedence_rank', 100)}"
        f" spec={resident_ranked[0][1]}]"
        if resident
        else "RESIDENT[NONE_FOUND]"
    )
    collapsed = work is not None and resident is not None and work["id"] == resident["id"]
    if collapsed:
        resident = None
        resident_part = "RESIDENT[NONE_FOUND COLLAPSED]"
    trace = work_part + ";" + resident_part
    return (work["id"] if work else None), (resident["id"] if resident else None), trace


def truncate_open_segment(emp_id, new_from_dt):
    """Truncate the employee's open CURRENT segment at new_from_dt.
    Returns the truncated segment (or None)."""
    cur = None
    for a in db.assignments.values():
        if (
            a["employee_id"] == emp_id
            and a["status"] == "CURRENT"
            and a["effective_to"] is None
        ):
            if cur is None or a["_seq"] > cur["_seq"]:
                cur = a
    if cur is None:
        return None
    cur["effective_to"] = new_from_dt
    if new_from_dt <= cur["effective_from"]:
        cur["status"] = "SUPERSEDED"
    touch(cur)
    return cur


def create_assignment(emp, loc, effective_from, source, work_agency_id, resident_agency_id, trace, override_reason=None):
    rec = new_record(
        db.assignments,
        {
            "employee_id": emp["id"],
            "work_location_id": loc["id"],
            "effective_from": effective_from,
            "effective_to": None,
            "resident_agency_id": resident_agency_id,
            "work_agency_id": work_agency_id,
            "resolution_source": source,
            "precedence_trace": trace,
            "status": "CURRENT",
            "override_reason": override_reason,
        },
    )
    return rec


def auto_assignment(emp, loc, effective_from):
    work_id, resident_id, trace = resolve_jurisdiction(emp, loc)
    truncate_open_segment(emp["id"], effective_from)
    return create_assignment(emp, loc, effective_from, "AUTO_GEOCODE", work_id, resident_id, trace)


# ---------------------------------------------------------------------------
# Filing calendar generation (calc filing_calendar_generation, PRD §3.4)
# ---------------------------------------------------------------------------
def last_day_of_month(y, m):
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def quarter_bounds(dt):
    m0 = 3 * ((dt.month - 1) // 3) + 1
    qs = date(dt.year, m0, 1)
    qe = last_day_of_month(dt.year, m0 + 2)
    return qs, qe


def roll_forward(day):
    """Weekend roll: Saturday +2, Sunday +1 (to Monday)."""
    if day.weekday() == 5:
        return day + timedelta(days=2)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def month_after_quarter_last_day(qe):
    """Due rule: last day of the month after the quarter."""
    if qe.month == 12:
        return date(qe.year + 1, 1, 31)
    return last_day_of_month(qe.year, qe.month + 1)


def _at_midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def semiweekly_windows(qs, qe):
    """IRS-style semiweekly liability windows clipped to the quarter.
    [Sat..Tue] due Friday of the same week; [Wed..Fri] due Wednesday of next week."""
    groups = {}
    cur = qs
    while cur <= qe:
        wd = cur.weekday()  # Mon=0 ... Sun=6
        if wd in (5, 6, 0, 1):  # Sat, Sun, Mon, Tue
            tue = cur + timedelta(days=(1 - wd) % 7)
            sat = tue - timedelta(days=3)
            key = (sat, tue)
            due = tue + timedelta(days=3)
        else:  # Wed, Thu, Fri
            wed = cur - timedelta(days=wd - 2)
            fri = wed + timedelta(days=2)
            key = (wed, fri)
            due = fri + timedelta(days=5)
        groups[key] = due
        cur += timedelta(days=1)
    rows = []
    for (ws, we), due in sorted(groups.items()):
        rows.append((max(ws, qs), min(we, qe), due))
    return rows


def withholding_amount(reg, agency, p_start, p_end):
    """Per-employee lines rounded half up, then summed (pinned order)."""
    rate = agency.get("withholding_rate_bp") or 0
    total = 0
    for emp in db.employees.values():
        days = days_in_state(emp, reg["state_code"], p_start, p_end)
        if days >= 1:
            total += rhu(emp["annual_wage_cents"] * days * rate, 365 * 10000)
    return total


def days_employed_ytd(emp, t_day, year):
    """Days from max(hire_date, Jan 1 of year) to min(t, termination or t),
    inclusive both ends; 0 when the interval is empty."""
    start = max(d(emp["hire_date"]), date(year, 1, 1))
    end = t_day
    term = emp.get("termination_date")
    if term is not None and d(term) < end:
        end = d(term)
    if end < start:
        return 0
    return (end - start).days + 1


def ui_effective_rate_bp(reg, agency, year):
    """EFFECTIVE UIRate of this registration with rate_year == year, else
    the agency's new-employer rate."""
    best = None
    for r in db.ui_rates.values():
        if (
            r["registration_id"] == reg["id"]
            and r["rate_year"] == year
            and r["status"] == "EFFECTIVE"
        ):
            if best is None or r["_seq"] > best["_seq"]:
                best = r
    if best is not None:
        return best["final_rate_bp"]
    return agency.get("new_employer_rate_bp") or 0


def ui_contribution_amount(reg, agency, q_start, q_end):
    rate_bp = ui_effective_rate_bp(reg, agency, q_start.year)
    wage_base = agency.get("ui_wage_base_cents")
    if wage_base is None:
        wage_base = HUGE_CENTS
    total = 0
    pre_day = q_start - timedelta(days=1)
    for emp in db.employees.values():
        if days_in_state(emp, reg["state_code"], q_start, q_end) >= 1:
            wage = emp["annual_wage_cents"]
            ytd_end = rhu(wage * days_employed_ytd(emp, q_end, q_start.year), 365)
            ytd_pre = rhu(wage * days_employed_ytd(emp, pre_day, q_start.year), 365)
            taxable = max(0, min(ytd_end, wage_base) - min(ytd_pre, wage_base))
            total += rhu(taxable * rate_bp, 10000)
    return total


def local_return_amount(reg, agency, q_start, q_end):
    total = 0
    for emp in db.employees.values():
        start = max(q_start, d(emp["hire_date"]))
        end = q_end
        term = emp.get("termination_date")
        if term is not None:
            end = min(end, d(term))
        if end < start:
            continue
        days = 0
        cur = start
        while cur <= end:
            seg = covering_segment(emp["id"], cur)
            if seg is not None and seg.get("work_agency_id") == agency["id"]:
                days += 1
            cur += timedelta(days=1)
        if days >= 1:
            if emp.get("resident_locality_code") is not None and emp.get(
                "resident_locality_code"
            ) == agency.get("locality_code"):
                rate = agency.get("resident_rate_bp") or 0
            else:
                rate = agency.get("nonresident_rate_bp") or 0
            total += rhu(emp["annual_wage_cents"] * days * rate, 365 * 10000)
    return total


def create_obligation(reg, kind, p_start, p_end, due_date, amount):
    return new_record(
        db.obligations,
        {
            "registration_id": reg["id"],
            "obligation_kind": kind,
            "period_start": _at_midnight(p_start),
            "period_end": _at_midnight(p_end),
            "due_date": _at_midnight(due_date),
            "amount_due_cents": amount,
            "amount_paid_cents": 0,
            "status": "SCHEDULED",
            "filed_at": None,
            "filed_by_user_id": None,
            "confirmed_by_user_id": None,
            "late_days": 0,
        },
    )


def generate_calendar(reg, ref_date):
    """Generate FilingObligation rows for the calendar quarter containing
    ref_date (full quarter, even partially elapsed)."""
    agency = db.agencies[reg["agency_id"]]
    qs, qe = quarter_bounds(ref_date)
    kind = reg["registration_kind"]
    quarter_due = roll_forward(month_after_quarter_last_day(qe))
    if kind == "STATE_WITHHOLDING":
        freq = reg["filing_frequency"]
        if freq == "MONTHLY":
            for m_off in range(3):
                m = qs.month + m_off
                p_start = date(qs.year, m, 1)
                p_end = last_day_of_month(qs.year, m)
                if m == 12:
                    due = date(qs.year + 1, 1, 15)
                else:
                    due = date(qs.year, m + 1, 15)
                due = roll_forward(due)
                amt = withholding_amount(reg, agency, p_start, p_end)
                create_obligation(reg, "WITHHOLDING_DEPOSIT", p_start, p_end, due, amt)
        elif freq == "QUARTERLY":
            amt = withholding_amount(reg, agency, qs, qe)
            create_obligation(reg, "WITHHOLDING_DEPOSIT", qs, qe, quarter_due, amt)
        elif freq == "SEMIWEEKLY":
            for ws, we, due in semiweekly_windows(qs, qe):
                amt = withholding_amount(reg, agency, ws, we)
                create_obligation(reg, "WITHHOLDING_DEPOSIT", ws, we, roll_forward(due), amt)
        amt = withholding_amount(reg, agency, qs, qe)
        create_obligation(reg, "WITHHOLDING_RETURN", qs, qe, quarter_due, amt)
    elif kind == "STATE_UI":
        create_obligation(reg, "UI_RETURN", qs, qe, quarter_due, 0)
        amt = ui_contribution_amount(reg, agency, qs, qe)
        create_obligation(reg, "UI_CONTRIBUTION", qs, qe, quarter_due, amt)
    elif kind == "LOCAL":
        amt = local_return_amount(reg, agency, qs, qe)
        create_obligation(reg, "LOCAL_RETURN", qs, qe, quarter_due, amt)


def compute_deposit_tier(reg):
    if any(
        o["registration_id"] == reg["id"]
        and o["obligation_kind"] == "WITHHOLDING_DEPOSIT"
        and o["amount_due_cents"] >= NEXT_DAY_THRESHOLD_CENTS
        for o in db.obligations.values()
    ):
        return "NEXT_DAY"
    if reg.get("filing_frequency") == "SEMIWEEKLY":
        return "ACCELERATED"
    return "STANDARD"


def apply_next_day_due_dates(reg):
    """On tier flip to NEXT_DAY: due_date of each non-terminal WITHHOLDING_DEPOSIT
    becomes the next business day after its period_end (weekend roll)."""
    for o in db.obligations.values():
        if (
            o["registration_id"] == reg["id"]
            and o["obligation_kind"] == "WITHHOLDING_DEPOSIT"
            and o["status"] in NONTERMINAL_OBLIGATION_STATUSES
        ):
            new_due = roll_forward(d(o["period_end"]) + timedelta(days=1))
            new_due_dt = _at_midnight(new_due)
            if o["due_date"] != new_due_dt:
                o["due_date"] = new_due_dt
                touch(o)


def classify_frequency(basis_cents):
    if basis_cents < QUARTERLY_CAP_CENTS:
        return "QUARTERLY"
    if basis_cents <= SEMIWEEKLY_THRESHOLD_CENTS:
        return "MONTHLY"
    return "SEMIWEEKLY"


# ---------------------------------------------------------------------------
# Late penalties (calc late_penalty_assessment, PRD §3.8)
# ---------------------------------------------------------------------------
def late_penalty(amount_due_cents, late_days):
    if late_days <= 0 or amount_due_cents <= 0:
        return 0
    if late_days <= TIER1_MAX_DAYS:
        pct = 2
    elif late_days <= TIER2_MAX_DAYS:
        pct = 5
    else:
        pct = 10
    return max(MIN_PENALTY_CENTS, rhu(amount_due_cents * pct, 100))


def compute_severity(notice_type, penalty_amount_cents):
    if notice_type == "AUDIT" or penalty_amount_cents >= 500000:
        return "HIGH"
    if penalty_amount_cents >= 50000:
        return "MEDIUM"
    return "LOW"


def create_late_penalty_notice(obl):
    now = db.clock
    penalty = late_penalty(obl["amount_due_cents"], 1)
    notice = new_record(
        db.notices,
        {
            "registration_id": obl["registration_id"],
            "filing_obligation_id": obl["id"],
            "notice_type": "PENALTY_ASSESSMENT",
            "received_date": now,
            "response_due_date": now + timedelta(days=30),
            "penalty_amount_cents": penalty,
            "abated_amount_cents": 0,
            "status": "RECEIVED",
            "severity": compute_severity("PENALTY_ASSESSMENT", penalty),
            "resolution_notes": None,
        },
    )
    obl["_late_notice_id"] = notice["id"]
    return notice


# ---------------------------------------------------------------------------
# UI experience rate (calc ui_experience_rate, PRD §3.7)
# ---------------------------------------------------------------------------
def ui_bracket(ratio_bp):
    if ratio_bp >= 1500:
        return 50
    if ratio_bp >= 1000:
        return 120
    if ratio_bp >= 500:
        return 240
    if ratio_bp >= 100:
        return 360
    if ratio_bp >= 0:
        return 480
    if ratio_bp >= -499:
        return 600
    if ratio_bp >= -999:
        return 750
    return 900


def ui_rate_fields(rate, agency, voluntary_applied_cents):
    """Returns (reserve_ratio_bp, final_rate_bp) under the pinned order."""
    if not rate["experience_rated"]:
        return None, agency.get("new_employer_rate_bp") or 0
    net = (
        rate["contributions_paid_3yr_cents"]
        + voluntary_applied_cents
        - rate["benefits_charged_3yr_cents"]
    )
    ratio = rhu(10000 * net, rate["taxable_payroll_3yr_cents"])
    final = ui_bracket(ratio) + (agency.get("solvency_surcharge_bp") or 0)
    final = min(RATE_CEILING_BP, max(RATE_FLOOR_BP, final))
    return ratio, final


def recompute_ui_rate(rate):
    reg = db.registrations[rate["registration_id"]]
    agency = db.agencies[reg["agency_id"]]
    ratio, final = ui_rate_fields(rate, agency, rate["voluntary_contribution_applied_cents"])
    rate["reserve_ratio_bp"] = ratio
    rate["final_rate_bp"] = final


# ---------------------------------------------------------------------------
# Voluntary contribution projection (calc voluntary_contribution_optimization)
# ---------------------------------------------------------------------------
def vc_projection(rate, reg, agency, proposed_amount_cents):
    _, final_without = ui_rate_fields(
        rate, agency, rate["voluntary_contribution_applied_cents"]
    )
    _, final_with = ui_rate_fields(
        rate, agency, rate["voluntary_contribution_applied_cents"] + proposed_amount_cents
    )
    wage_base = agency.get("ui_wage_base_cents")
    if wage_base is None:
        wage_base = HUGE_CENTS
    year = rate["rate_year"]
    w_start = date(year, 1, 1)
    w_end = date(year, 12, 31)
    projected_taxable = 0
    for emp in db.employees.values():
        if days_in_state(emp, reg["state_code"], w_start, w_end) >= 1:
            projected_taxable += min(emp["annual_wage_cents"], wage_base)
    savings = rhu((final_without - final_with) * projected_taxable, 10000) - proposed_amount_cents
    return final_without, final_with, projected_taxable, savings


# ---------------------------------------------------------------------------
# Abatement eligibility (calc abatement_eligibility, PRD §3.9)
# ---------------------------------------------------------------------------
def _years_before(dt, years):
    try:
        return dt.replace(year=dt.year - years)
    except ValueError:
        return dt.replace(year=dt.year - years, day=28)


def abatement_eligibility(notice, abatement_type):
    outstanding = notice["penalty_amount_cents"] - notice["abated_amount_cents"]
    anchor = notice["received_date"]
    window_start = _years_before(anchor, FIRST_TIME_LOOKBACK_YEARS)
    priors = []
    for n in db.notices.values():
        if n["id"] == notice["id"]:
            continue
        if n["notice_type"] != "PENALTY_ASSESSMENT":
            continue
        if not (window_start <= n["received_date"] < anchor):
            continue
        if n["penalty_amount_cents"] - n["abated_amount_cents"] > 0:
            priors.append(n)
    priors.sort(key=lambda n: (n["received_date"], n["_seq"]))
    prior_count = len(priors)
    if abatement_type == "FIRST_TIME":
        eligible = outstanding if prior_count == 0 else 0
    elif abatement_type == "REASONABLE_CAUSE":
        eligible = outstanding
    else:  # STATUTORY: floor half
        eligible = outstanding // 2
    return prior_count, eligible


# ---------------------------------------------------------------------------
# Location-change cascades (PRD §3.6)
# ---------------------------------------------------------------------------
def effectuate_location_change(lc):
    emp = db.employees[lc["employee_id"]]
    to_loc = db.locations[lc["to_work_location_id"]]
    old_state = lc["from_location_snapshot"]["state_code"]
    new_state = to_loc["state_code"]
    emp["current_work_location_id"] = lc["to_work_location_id"]
    touch(emp)
    truncated = truncate_open_segment(emp["id"], lc["effective_date"])
    work_id, resident_id, trace = resolve_jurisdiction(emp, to_loc)
    new_seg = create_assignment(
        emp, to_loc, lc["effective_date"], "AUTO_GEOCODE", work_id, resident_id, trace
    )
    lc["_truncated_segment_id"] = truncated["id"] if truncated else None
    lc["_effectuated_segment_id"] = new_seg["id"]
    lc["status"] = "EFFECTIVE"
    touch(lc)
    cascade_nexus(old_state)
    if new_state != old_state:
        cascade_nexus(new_state)
    recompute_employer()


def reverse_location_change(lc):
    emp = db.employees[lc["employee_id"]]
    snap = lc["from_location_snapshot"]
    old_state = snap["state_code"]
    new_loc = db.locations.get(lc["to_work_location_id"])
    new_state = new_loc["state_code"] if new_loc else old_state
    emp["current_work_location_id"] = snap["work_location_id"]
    touch(emp)
    seg = db.assignments.get(lc.get("_effectuated_segment_id") or "")
    if seg is not None:
        seg["status"] = "SUPERSEDED"
        touch(seg)
    prior = db.assignments.get(lc.get("_truncated_segment_id") or "")
    if prior is not None:
        prior["effective_to"] = None
        prior["status"] = "CURRENT"
        touch(prior)
    lc["status"] = "REVERSED"
    touch(lc)
    cascade_nexus(old_state)
    if new_state != old_state:
        cascade_nexus(new_state)
    recompute_employer()


def terminate_employee(emp, termination_date):
    emp["termination_date"] = termination_date
    emp["status"] = "TERMINATED"
    touch(emp)
    truncated = truncate_open_segment(emp["id"], termination_date)
    if truncated is not None:
        loc = db.locations.get(truncated["work_location_id"])
        if loc is not None:
            cascade_nexus(loc["state_code"])
    recompute_employer()


# ---------------------------------------------------------------------------
# Agreement status (clock-derived, PRD §3.1)
# ---------------------------------------------------------------------------
def agreement_status(ag, now):
    if now < ag["effective_from"]:
        return "SCHEDULED"
    if ag["effective_to"] is not None and ag["effective_to"] < now:
        return "EXPIRED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# The scheduled sweep (PRD §2.4): runs on every clock set
# ---------------------------------------------------------------------------
def run_sweep():
    now = db.clock
    # ReciprocityAgreement status recompute
    for ag in db.agreements.values():
        new_status = agreement_status(ag, now)
        if ag["status"] != new_status:
            ag["status"] = new_status
            touch(ag)
    # WithholdingElection VALIDATED->ACTIVE / EXPIRED
    for el in db.elections.values():
        if (
            el["status"] in ("VALIDATED", "ACTIVE")
            and el.get("effective_to") is not None
            and el["effective_to"] < now
        ):
            el["status"] = "EXPIRED"
            touch(el)
        elif el["status"] == "VALIDATED" and el["effective_from"] <= now:
            el["status"] = "ACTIVE"
            touch(el)
    # VoluntaryContribution PROPOSED -> EXPIRED past deadline
    for vc in db.vcs.values():
        if vc["status"] == "PROPOSED" and now > vc["decision_deadline"]:
            vc["status"] = "EXPIRED"
            touch(vc)
    # FilingObligation SCHEDULED->DUE, DUE->LATE with notice cascade
    for ob in sorted(db.obligations.values(), key=lambda o: o["_seq"]):
        if ob["status"] == "SCHEDULED" and ob["period_end"] < now:
            ob["status"] = "DUE"
            touch(ob)
        if ob["status"] == "DUE" and now >= ob["due_date"] + timedelta(days=1):
            ob["status"] = "LATE"
            ob["late_days"] = (d(now) - d(ob["due_date"])).days
            touch(ob)
            if ob["amount_due_cents"] > 0:
                create_late_penalty_notice(ob)
            recompute_employer()
        elif ob["status"] == "LATE":
            ld = (d(now) - d(ob["due_date"])).days
            if ld < 0:
                ld = 0
            if ld != ob["late_days"]:
                ob["late_days"] = ld
                touch(ob)
    # LocationChange APPROVED -> EFFECTIVE
    for lc in sorted(db.location_changes.values(), key=lambda c: c["_seq"]):
        if lc["status"] == "APPROVED" and lc["effective_date"] <= now:
            emp = db.employees.get(lc["employee_id"])
            if emp is not None and emp["status"] == "ACTIVE":
                effectuate_location_change(lc)
    # Employer posture recompute
    recompute_employer()
