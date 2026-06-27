"""Calculation rules. Scaffold 1.3 / PRD 2.7, 2.8, 3.4, 3.7, 3.8, 3.9.

Money is integer cents; all scaling uses Decimal with ROUND_HALF_UP. The pinned
rounding order is round-per-line-then-sum (PRD 2.7). Readiness weighted_score is
rounded to 4 decimals ROUND_HALF_UP (PRD 2.8).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# Scaffold 1.3 constants
DISCOUNT_2_PCT = Decimal("0.10")
DISCOUNT_3_PLUS_PCT = Decimal("0.15")
MASTERY_SCORE = Decimal("0.80")
TRANSITION_BUFFER_MINUTES = 15


def _round_half_up_cents(value):
    """Round a Decimal to whole cents, ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Occurrence counting — PRD 3.9.
# An occurrence is a calendar date D in [cycle_start, cycle_end) with
# D.weekday() == session.day_of_week (UTC). day_of_week: 0=Mon..6=Sun, which
# matches Python's date.weekday().
# ---------------------------------------------------------------------------
def _date_floor(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def occurrence_dates(cycle_start, cycle_end, day_of_week):
    """Return the list of UTC calendar dates (datetime at midnight) in
    [cycle_start, cycle_end) whose weekday equals day_of_week."""
    dates = []
    # Start scanning from the date of cycle_start; include a date D when
    # cycle_start <= D < cycle_end. A date counts if its midnight instant is
    # within [cycle_start, cycle_end).
    d = _date_floor(cycle_start)
    # If cycle_start is mid-day, the first candidate midnight may be before
    # cycle_start; advance until >= cycle_start.
    while d < cycle_start:
        d = d + timedelta(days=1)
    while d < cycle_end:
        if d.weekday() == day_of_week:
            dates.append(d)
        d = d + timedelta(days=1)
    return dates


def prorated_line_cents(tuition_basis_cents, window_count, occurrences_total):
    """PRD 3.9: prorated = basis * window / total, ROUND_HALF_UP per line.
    When occurrences_total == 0, there is nothing to charge -> 0."""
    if occurrences_total <= 0:
        return 0
    value = (Decimal(tuition_basis_cents) * Decimal(window_count)) / Decimal(occurrences_total)
    return _round_half_up_cents(value)


def compute_window_count(enrollment_joined_at, cycle_start, cycle_end, current_utc,
                         day_of_week, variant):
    """PRD 3.9: compute the charged-occurrence window count for one enrollment."""
    occ = occurrence_dates(cycle_start, cycle_end, day_of_week)
    occurrences_total = len(occ)
    if enrollment_joined_at > cycle_start:
        # Joined mid-cycle: occurrences on or after the calendar date of joined_at.
        join_date = _date_floor(enrollment_joined_at)
        window = sum(1 for d in occ if d >= join_date)
    elif variant == "FORWARD_LOOKING":
        window = occurrences_total
    else:  # CHRONOLOGICAL
        window = sum(1 for d in occ if d < current_utc)
    return window, occurrences_total


# ---------------------------------------------------------------------------
# Sibling discount + pinned total — PRD 3.9 / scaffold sibling_discount.
# ---------------------------------------------------------------------------
def discount_pct_for_student_count(n):
    if n <= 1:
        return Decimal("0.00")
    if n == 2:
        return DISCOUNT_2_PCT
    return DISCOUNT_3_PLUS_PCT


def apply_sibling_discount(lines, student_created_at, student_seq):
    """lines: list of dicts each with enrollment_id, student_id, basis_cents,
    prorated_cents. student_created_at: {student_id -> created_at} for tie-break.
    student_seq: {student_id -> creation sequence} — the deterministic discriminator
    when created_at collides (never the student id, which the PRD forbids).

    Mutates each line, adding discount_pct, line_total_cents, line_discount_amount.
    Returns (subtotal_cents, discount_cents, total_cents) per the pinned order.
    """
    students = set(line["student_id"] for line in lines)
    n = len(students)
    fam_pct = discount_pct_for_student_count(n)

    # Full-price student: argmax over students of (max prorated_cents among that
    # student's lines); tie-break smallest Student.created_at (then creation order).
    full_price_student = None
    best_key = None
    for sid in students:
        max_line = max(line["prorated_cents"] for line in lines if line["student_id"] == sid)
        created = student_created_at.get(sid, "")
        seq = student_seq.get(sid, 0)
        # We want the student with the highest max_line; tie-break earliest created_at,
        # then earliest creation sequence.
        key = (max_line, created, seq)
        if best_key is None or _full_price_better(key, best_key):
            best_key = key
            full_price_student = sid

    for line in lines:
        if line["student_id"] == full_price_student:
            line_pct = Decimal("0.00")
        else:
            line_pct = fam_pct
        prorated = Decimal(line["prorated_cents"])
        line_total = _round_half_up_cents(prorated * (Decimal("1") - line_pct))
        line["discount_pct"] = float(line_pct)
        line["line_total_cents"] = line_total
        line["line_discount_amount"] = line["prorated_cents"] - line_total

    # PRD 2.7 pinned order: each line already rounded; sum per stage.
    subtotal_cents = sum(line["prorated_cents"] for line in lines)
    discount_cents = sum(line["line_discount_amount"] for line in lines)
    total_cents = sum(line["line_total_cents"] for line in lines)
    return subtotal_cents, discount_cents, total_cents


def _full_price_better(candidate, current):
    """candidate/current are (max_line, created_at, seq). Higher max_line wins;
    tie-break by earliest created_at, then earliest creation sequence."""
    c_max, c_created, c_seq = candidate
    cur_max, cur_created, cur_seq = current
    if c_max != cur_max:
        return c_max > cur_max
    if c_created != cur_created:
        return c_created < cur_created
    return c_seq < cur_seq


# ---------------------------------------------------------------------------
# Level-up readiness — PRD 3.7 / scaffold level_up_readiness.
# ---------------------------------------------------------------------------
def compute_readiness(skill_scores, skills, readiness_threshold):
    """skill_scores: list of {skill_id, score}. skills: list of Skill records of
    the assessed level. Returns (mastered_count, weighted_score, strict_ready,
    holistic_ready). weighted_score rounded to 4 decimals ROUND_HALF_UP."""
    total_skills = len(skills)
    weight_by_skill = {s["id"]: Decimal(str(s["weight"])) for s in skills}

    mastered_count = 0
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for entry in skill_scores:
        score = Decimal(str(entry["score"]))
        sid = entry["skill_id"]
        weight = weight_by_skill.get(sid, Decimal("0"))
        if score >= MASTERY_SCORE:
            mastered_count += 1
        weighted_sum += score * weight
        weight_total += weight

    if weight_total == 0:
        weighted_score = Decimal("0")
    else:
        weighted_score = (weighted_sum / weight_total).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)

    strict_ready = (mastered_count == total_skills)
    holistic_ready = weighted_score >= Decimal(str(readiness_threshold))
    return mastered_count, float(weighted_score), strict_ready, holistic_ready


# ---------------------------------------------------------------------------
# Instructor schedule overlap — PRD 3.4 / scaffold instructor_schedule_overlap.
# Closed interval inflated by a symmetric 15-minute buffer on BOTH sides.
# ---------------------------------------------------------------------------
def instructor_schedule_conflict(candidate, other_sessions):
    """candidate and each other have start_minute/end_minute. other_sessions are
    the OPEN sessions of the same instructor on the same day_of_week.
    Conflict when candidate.start < other.end + BUFFER and other.start < candidate.end + BUFFER."""
    cs = candidate["start_minute"]
    ce = candidate["end_minute"]
    for o in other_sessions:
        os_ = o["start_minute"]
        oe = o["end_minute"]
        if cs < oe + TRANSITION_BUFFER_MINUTES and os_ < ce + TRANSITION_BUFFER_MINUTES:
            return True
    return False


# ---------------------------------------------------------------------------
# Makeup same-day overlap — PRD 3.8 / scaffold makeup_same_day_overlap.
# Half-open interval, no buffer.
# ---------------------------------------------------------------------------
def makeup_time_conflict(start_minute, end_minute, other_bookings):
    """other_bookings: the student's BOOKED/ATTENDED bookings on the same
    occurrence_date. Conflict when start < other.end and other.start < end
    (half-open [start, end), no buffer)."""
    for b in other_bookings:
        os_ = b["occurrence_start_minute"]
        oe = b["occurrence_end_minute"]
        if start_minute < oe and os_ < end_minute:
            return True
    return False
