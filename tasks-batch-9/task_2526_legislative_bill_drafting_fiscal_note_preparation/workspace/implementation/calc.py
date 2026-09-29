"""Every calculation in SCAFFOLD S1.3 / PRD S3.

All money is an integer number of cents.  Where a rate must be applied the exact
rational product is formed with fractions.Fraction and then rounded half up
(ties away from zero) exactly as many times as the specification says.
No float ever touches an observable cent.
"""

from datetime import timedelta
from fractions import Fraction

from store import add_days, all_rows, db, parse_iso

# --- drafting_complexity_score ---------------------------------------------
SECTION_WEIGHT = 4
ADVISORY_WEIGHT = 3
BLOCKING_WEIGHT = 9
CONFIDENTIAL_WEIGHT = 12
PRIORITY_WEIGHT = 8
APPROPRIATION_TIER_CENTS = 5000000

# --- drafting_sla_due_utc --------------------------------------------------
SLA_HOURS_PER_POINT = 6
SLA_FLOOR_HOURS = 24
SLA_CEILING_HOURS = 240
PRIORITY_MULTIPLIER = Fraction(1, 2)
DEADLINE_PRESSURE_MULTIPLIER = Fraction(3, 4)
DEADLINE_PRESSURE_WINDOW_DAYS = 14

# --- fiscal_note_cost_total ------------------------------------------------
INCREMENTAL_FTE_FLOOR = Fraction(1, 2)
INDIRECT_OVERHEAD_PCT = Fraction(185, 1000)
CONTINGENCY_TIER_1_CENTS = 10000000
CONTINGENCY_TIER_2_CENTS = 100000000
CONTINGENCY_PCT_LOW = Fraction(5, 100)
CONTINGENCY_PCT_MID = Fraction(8, 100)
CONTINGENCY_PCT_HIGH = Fraction(12, 100)

# --- multi_year_revenue_projection ----------------------------------------
GROWTH_RATE = Fraction(325, 10000)
PROJECTION_HORIZON_YEARS = 4
SCENARIO_MULTIPLIER_HIGH = Fraction(115, 100)
SCENARIO_MULTIPLIER_LOW = Fraction(85, 100)

# --- fiscal_note_due_date --------------------------------------------------
LATE_PENALTY = 12
REVISION_PENALTY = 5
RESPONSIVE_BAND_HIGH = 70
RESPONSIVE_BAND_LOW = 40
EXTENSION_DAYS_MID = 5
EXTENSION_DAYS_LOW = 10

# --- bill_number_assignment ------------------------------------------------
HOUSE_PREFIX = "HB "
SENATE_PREFIX = "SB "

# --- member_priority_slot_ledger ------------------------------------------
MEMBER_CLARIFICATION_HOLD_THRESHOLD = 2

# --- amendment_turnaround_deadline ----------------------------------------
COMMITTEE_TURNAROUND_MINUTES = 240
FLOOR_TURNAROUND_MINUTES = 60
SINE_DIE_COMPRESSION_HOURS = 48
SINE_DIE_COMPRESSION_FACTOR = Fraction(1, 2)

# --- committee_hearing_window_occupancy -----------------------------------
CHANGEOVER_BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# exact arithmetic helpers
# ---------------------------------------------------------------------------


def to_fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value):
    """Nearest whole unit, ties resolved away from zero."""
    frac = to_fraction(value)
    if frac < 0:
        return -round_half_up(-frac)
    return (2 * frac.numerator + frac.denominator) // (2 * frac.denominator)


def ceil_fraction(value):
    frac = to_fraction(value)
    return -((-frac.numerator) // frac.denominator)


def floor_fraction(value):
    frac = to_fraction(value)
    return frac.numerator // frac.denominator


# ---------------------------------------------------------------------------
# drafting_complexity_score
# ---------------------------------------------------------------------------


def tier_bonus(appropriation_requested_cents):
    if appropriation_requested_cents == 0:
        return 0
    if appropriation_requested_cents <= APPROPRIATION_TIER_CENTS:
        return 5
    return 15


def intake_complexity_estimate(request_row):
    score = SECTION_WEIGHT * request_row["requested_sections_count"]
    if request_row["confidentiality"] == "CONFIDENTIAL":
        score += CONFIDENTIAL_WEIGHT
    if request_row["priority_flag"]:
        score += PRIORITY_WEIGHT
    score += tier_bonus(request_row["appropriation_requested_cents"])
    return score


def post_research_actual(request_row):
    """Uses the researched footprint and every conflict, in ANY resolution
    status; the appropriation tier bonus is dropped entirely."""
    affected = request_row.get("affected_sections_count") or 0
    score = SECTION_WEIGHT * affected
    score += ADVISORY_WEIGHT * request_row["advisory_conflict_count"]
    score += BLOCKING_WEIGHT * request_row["blocking_conflict_count"]
    if request_row["confidentiality"] == "CONFIDENTIAL":
        score += CONFIDENTIAL_WEIGHT
    if request_row["priority_flag"]:
        score += PRIORITY_WEIGHT
    return score


# ---------------------------------------------------------------------------
# drafting_sla_due_utc
# ---------------------------------------------------------------------------


def drafting_sla_due_utc(request_row, session_row, from_instant):
    score = request_row["actual_complexity_score"] or 0
    base_hours = max(SLA_FLOOR_HOURS, min(SLA_CEILING_HOURS, score * SLA_HOURS_PER_POINT))
    hours = Fraction(base_hours)
    if request_row["priority_flag"]:
        hours = hours * PRIORITY_MULTIPLIER
    deadline = parse_iso(session_row["introduction_deadline_utc"])
    pressure_start = deadline - timedelta(days=DEADLINE_PRESSURE_WINDOW_DAYS)
    if db.now() >= pressure_start:
        hours = hours * DEADLINE_PRESSURE_MULTIPLIER
    whole_hours = ceil_fraction(hours)
    candidate = from_instant + timedelta(hours=whole_hours)
    return min(candidate, deadline)


# ---------------------------------------------------------------------------
# fiscal_note_cost_total
# ---------------------------------------------------------------------------


def current_round_lines(note_row, scenario=None):
    lines = []
    for line in all_rows("cost_estimates"):
        if line["fiscal_note_request_id"] != note_row["id"]:
            continue
        if line["revision_round"] != note_row["revision_round"]:
            continue
        if scenario is not None and line["scenario"] != scenario:
            continue
        lines.append(line)
    return lines


def contingency_pct_for(direct_cost_cents):
    if direct_cost_cents <= CONTINGENCY_TIER_1_CENTS:
        return CONTINGENCY_PCT_LOW
    if direct_cost_cents <= CONTINGENCY_TIER_2_CENTS:
        return CONTINGENCY_PCT_MID
    return CONTINGENCY_PCT_HIGH


def fiscal_note_cost_total(note_row):
    """Returns (direct_cost_cents, contingency_pct, contingency_cents,
    certified_total_cents)."""
    lines = current_round_lines(note_row, "BASELINE")
    if note_row["methodology"] == "INCREMENTAL_COST":
        direct = 0
        for line in lines:
            direct += line["operating_cost_cents"] + line["one_time_cost_cents"]
            if to_fraction(line["fte_count"]) >= INCREMENTAL_FTE_FLOOR:
                direct += line["personnel_cost_cents"]
    else:
        personnel_total = sum(line["personnel_cost_cents"] for line in lines)
        direct = sum(
            line["operating_cost_cents"]
            + line["one_time_cost_cents"]
            + line["personnel_cost_cents"]
            for line in lines
        )
        direct += round_half_up(personnel_total * INDIRECT_OVERHEAD_PCT)
    pct = contingency_pct_for(direct)
    contingency = round_half_up(direct * pct)
    return direct, pct, contingency, direct + contingency


# ---------------------------------------------------------------------------
# multi_year_revenue_projection
# ---------------------------------------------------------------------------


def _base_year_line(note_row, scenario, base_year):
    for line in current_round_lines(note_row, scenario):
        if line["fiscal_year"] == base_year:
            return line
    return None


def _project(base):
    total = 0
    for k in range(PROJECTION_HORIZON_YEARS):
        total += round_half_up(Fraction(base) * (1 + GROWTH_RATE) ** k)
    return total


def multi_year_revenue_projection(note_row, session_row):
    """Returns (baseline_total, high_total, low_total)."""
    base_year = min(session_row["required_fiscal_years"])
    baseline_row = _base_year_line(note_row, "BASELINE", base_year)
    baseline_base = baseline_row["revenue_impact_cents"] if baseline_row else 0

    def base_for(scenario, multiplier):
        row = _base_year_line(note_row, scenario, base_year)
        if row is not None:
            return row["revenue_impact_cents"]
        return round_half_up(Fraction(baseline_base) * multiplier)

    high_base = base_for("HIGH", SCENARIO_MULTIPLIER_HIGH)
    low_base = base_for("LOW", SCENARIO_MULTIPLIER_LOW)
    return _project(baseline_base), _project(high_base), _project(low_base)


# ---------------------------------------------------------------------------
# fiscal_note_due_date
# ---------------------------------------------------------------------------


def responsiveness_score(agency_row):
    raw = (
        100
        - LATE_PENALTY * agency_row["late_submission_count"]
        - REVISION_PENALTY * agency_row["revision_count"]
    )
    return max(0, min(100, raw))


def extension_days(score):
    if score >= RESPONSIVE_BAND_HIGH:
        return 0
    if score >= RESPONSIVE_BAND_LOW:
        return EXTENSION_DAYS_MID
    return EXTENSION_DAYS_LOW


def fiscal_note_due_utc(agency_row, session_row, routed_instant):
    grant_days = session_row["fiscal_note_default_days"] + extension_days(
        responsiveness_score(agency_row)
    )
    return add_days(routed_instant, grant_days)


# ---------------------------------------------------------------------------
# amendment_turnaround_deadline
# ---------------------------------------------------------------------------


def amendment_turnaround_deadline(stage, requested_instant, session_row):
    base_minutes = (
        COMMITTEE_TURNAROUND_MINUTES if stage == "COMMITTEE" else FLOOR_TURNAROUND_MINUTES
    )
    sine_die = parse_iso(session_row["sine_die_utc"])
    remaining = sine_die - requested_instant
    if remaining <= timedelta(hours=SINE_DIE_COMPRESSION_HOURS):
        minutes = floor_fraction(Fraction(base_minutes) * SINE_DIE_COMPRESSION_FACTOR)
    else:
        minutes = base_minutes
    return requested_instant + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# enrollment_composition
# ---------------------------------------------------------------------------


def enrollment_composition(bill_row):
    adopted = [
        a
        for a in all_rows("amendments")
        if a["bill_id"] == bill_row["id"] and a["status"] == "ADOPTED"
    ]
    ordered = sorted(
        adopted,
        key=lambda a: (
            0 if a["stage"] == "COMMITTEE" else 1,
            a["created_at"],
            a["_seq"],
        ),
    )
    count = len(adopted)
    net = sum(a["fiscal_impact_delta_cents"] for a in adopted)
    sequence = [a["id"] for a in ordered]
    origin = "SPEAKER" if bill_row["chamber"] == "HOUSE" else "SENATE_PRESIDENT"
    return count, net, sequence, origin


# ---------------------------------------------------------------------------
# drafter_engagement_occupancy  (CLOSED intervals, aggregate multiplicity)
# ---------------------------------------------------------------------------


def occupancy_intervals(drafter_id, exclude_request_id=None, exclude_amendment_id=None):
    intervals = []
    for row in all_rows("drafting_requests"):
        if row["assigned_drafter_id"] != drafter_id:
            continue
        if row["status"] not in ("RESEARCH", "DRAFTING"):
            continue
        if exclude_request_id is not None and row["id"] == exclude_request_id:
            continue
        start = parse_iso(row["engagement_start_utc"])
        end = parse_iso(row["engagement_end_utc"])
        if start is None or end is None:
            continue
        intervals.append((start, end))
    for row in all_rows("amendments"):
        if row.get("drafted_by_drafter_id") != drafter_id:
            continue
        if row["status"] != "DRAFTED":
            continue
        if exclude_amendment_id is not None and row["id"] == exclude_amendment_id:
            continue
        start = parse_iso(row["drafting_start_utc"])
        end = parse_iso(row["drafting_due_utc"])
        if start is None or end is None:
            continue
        intervals.append((start, end))
    return intervals


def max_multiplicity_within(intervals, cand_start, cand_end):
    """Maximum pointwise multiplicity of the closed intervals restricted to the
    closed candidate interval.  Endpoint equality counts as overlap."""
    overlapping = [
        (s, e) for (s, e) in intervals if s <= cand_end and cand_start <= e
    ]
    if not overlapping:
        return 0
    candidates = set([cand_start, cand_end])
    for s, e in overlapping:
        if cand_start <= s <= cand_end:
            candidates.add(s)
        if cand_start <= e <= cand_end:
            candidates.add(e)
    best = 0
    for t in candidates:
        count = sum(1 for (s, e) in overlapping if s <= t <= e)
        if count > best:
            best = count
    return best


def drafter_admits(drafter_row, cand_start, cand_end, exclude_request_id=None,
                   exclude_amendment_id=None):
    intervals = occupancy_intervals(
        drafter_row["id"], exclude_request_id, exclude_amendment_id
    )
    peak = max_multiplicity_within(intervals, cand_start, cand_end)
    return peak + 1 <= drafter_row["max_concurrent_engagements"]


# ---------------------------------------------------------------------------
# committee_hearing_window_occupancy  (HALF-OPEN + 30 min changeover buffer)
# ---------------------------------------------------------------------------


def hearing_window_conflicts(committee_id, cand_start, cand_end):
    buffer_delta = timedelta(minutes=CHANGEOVER_BUFFER_MINUTES)
    for row in all_rows("committee_referrals"):
        if row["committee_id"] != committee_id:
            continue
        if row["status"] != "IN_COMMITTEE":
            continue
        existing_start = parse_iso(row["hearing_window_start_utc"])
        existing_end = parse_iso(row["hearing_window_end_utc"]) + buffer_delta
        if cand_start < existing_end and existing_start < cand_end:
            return True
    return False


# ---------------------------------------------------------------------------
# bill_number_assignment
# ---------------------------------------------------------------------------


def mint_bill_number(session_row, chamber):
    if chamber == "HOUSE":
        n = session_row["next_house_bill_number"]
        session_row["next_house_bill_number"] = n + 1
        return HOUSE_PREFIX + str(n)
    n = session_row["next_senate_bill_number"]
    session_row["next_senate_bill_number"] = n + 1
    return SENATE_PREFIX + str(n)
