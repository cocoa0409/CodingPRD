"""Domain calculations: attendance rates, tenure, term windows, compliance."""
from util import add_months, add_days, parse_dt, round_half_up

CONSECUTIVE_GAP_DAYS = 1
DISCLOSURE_DUE_DAYS = 30
MEETING_MIN_GAP_HOURS = 24


# --------------------------------------------------------------------------
# Attendance counts / rates
# --------------------------------------------------------------------------
def attendance_counts(store, term_id):
    present = absent = excused = 0
    for a in store.attendance.values():
        if a["term_id"] == term_id:
            p = a["presence"]
            if p == "PRESENT":
                present += 1
            elif p == "ABSENT":
                absent += 1
            elif p == "EXCUSED":
                excused += 1
    return present, absent, excused


def provisional_rate(present, absent):
    denom = present + absent
    if denom == 0:
        return 0.0
    return round_half_up(present / denom * 100, 1)


def final_rate(present, absent, excused):
    denom = present + absent + excused
    if denom == 0:
        return None
    return round_half_up(present / denom * 100, 1)


# --------------------------------------------------------------------------
# Term window
# --------------------------------------------------------------------------
def term_end(start_dt, term_length_months):
    return add_months(start_dt, term_length_months)


def disclosure_due(term_start_dt):
    return add_days(term_start_dt, DISCLOSURE_DUE_DAYS)


# --------------------------------------------------------------------------
# Tenure (consecutive terms + cumulative years)
# --------------------------------------------------------------------------
def served_terms(store, applicant_id, board_id):
    served = [
        t for t in store.terms.values()
        if t["applicant_id"] == applicant_id and t["board_id"] == board_id
        and t["status"] in ("ACTIVE", "HOLDOVER", "EXPIRED", "COMPLETED")
    ]
    served.sort(key=lambda t: (t["term_start_date"], t["_seq"]))
    return served


def consecutive_terms(store, applicant_id, board_id):
    served = served_terms(store, applicant_id, board_id)
    if not served:
        return 0
    count = 1
    for k in range(len(served) - 1, 0, -1):
        newer = served[k]
        older = served[k - 1]
        pred_end = parse_dt(older["term_end_date"])
        this_start = parse_dt(newer["term_start_date"])
        if add_days(pred_end, CONSECUTIVE_GAP_DAYS) >= this_start:
            count += 1
        else:
            break
    return count


def cumulative_years(store, applicant_id, board_id, term_length_months):
    served = served_terms(store, applicant_id, board_id)
    total_days = 0
    for t in served:
        start = parse_dt(t["term_start_date"])
        nominal_end = add_months(start, term_length_months)
        total_days += (nominal_end - start).days
    return round_half_up(total_days / 365.0, 2)


# --------------------------------------------------------------------------
# Overlap (half-open intervals)
# --------------------------------------------------------------------------
def term_overlaps(store, seat_id, start_dt, end_dt, exclude_term_id=None):
    for t in store.terms.values():
        if t["seat_id"] != seat_id:
            continue
        if t["status"] not in ("ACTIVE", "HOLDOVER"):
            continue
        if exclude_term_id and t["id"] == exclude_term_id:
            continue
        o_start = parse_dt(t["term_start_date"])
        o_end = parse_dt(t["term_end_date"])
        # half-open [start, end): overlap iff start < o_end and o_start < end
        if start_dt < o_end and o_start < end_dt:
            return True
    return False


# --------------------------------------------------------------------------
# Board attendance index (pinned rounding order)
# --------------------------------------------------------------------------
def board_attendance_index(store, board_id):
    members = [
        t for t in store.terms.values()
        if t["board_id"] == board_id
        and t["status"] in ("ACTIVE", "HOLDOVER", "EXPIRED", "COMPLETED")
    ]
    if not members:
        return None
    exact_rates = []
    for t in members:
        present, absent, excused = attendance_counts(store, t["id"])
        denom = present + absent + excused
        if denom == 0:
            continue
        exact_rates.append(present / denom * 100)
    if not exact_rates:
        return None
    return round_half_up(sum(exact_rates) / len(exact_rates), 1)
