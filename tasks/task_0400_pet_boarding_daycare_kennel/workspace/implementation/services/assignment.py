"""RunAssignment creation checks (PRD §3.6): eligibility, pet self-exclusion,
suite overlap, daycare capacity, group compatibility.
"""
import errors
from db import db
from services.common import parse_date, add_days
from services import calc

SIZE_RANK = {"TOY": 0, "SMALL": 1, "MEDIUM": 2, "LARGE": 3}


def assignment_window(reservation):
    """[window_start_date, window_end_date) derived from the reservation.
    OVERNIGHT: end = reservation.end_date. DAYCARE: end = start_date + 1 day."""
    start = reservation["start_date"]
    if reservation["service_type"] == "OVERNIGHT":
        end = reservation["end_date"]
    else:
        end = add_days(reservation["start_date"], 1)
    return start, end


def _half_open_overlap(s1, e1, s2, e2):
    """Two half-open [s,e) date intervals overlap iff s1 < e2 and s2 < e1."""
    return parse_date(s1) < parse_date(e2) and parse_date(s2) < parse_date(e1)


def _closed_overlap(s1, e1, s2, e2):
    """Closed/inclusive overlap for pet self-exclusion: intervals collide when
    they share any calendar date. With windows stored as [start, end_exclusive),
    the inclusive last date is end - 1 day. Two intervals collide iff
    s1 <= (e2-1) and s2 <= (e1-1), i.e. s1 < e2 and s2 < e1 — but for daycare
    where a single date has end = start+1, two same-date days must collide.
    Using inclusive-last-day comparison: last1 = e1-1day, last2 = e2-1day.
    Collide iff s1 <= last2 and s2 <= last1."""
    last1 = parse_date(e1).toordinal() - 1
    last2 = parse_date(e2).toordinal() - 1
    s1o = parse_date(s1).toordinal()
    s2o = parse_date(s2).toordinal()
    return s1o <= last2 and s2o <= last1


def _non_released_assignments():
    return [a for a in db.run_assignments.values() if a["status"] != "RELEASED"]


def _reservation_of(assignment):
    return db.reservations.get(assignment["reservation_id"])


def check_eligibility(run, pet, reservation):
    """ERR_RUN_NOT_ELIGIBLE: status AVAILABLE, run size >= pet size, kind maps
    to service_type."""
    if run["status"] != "AVAILABLE":
        raise errors.err_run_not_eligible()
    if SIZE_RANK[run["size_class"]] < SIZE_RANK[pet["size_class"]]:
        raise errors.err_run_not_eligible()
    expected_kind = ("OVERNIGHT_SUITE" if reservation["service_type"] == "OVERNIGHT"
                     else "DAYCARE_PEN")
    if run["kind"] != expected_kind:
        raise errors.err_run_not_eligible()


def check_pet_double_booked(pet_id, win_start, win_end, exclude_reservation_id=None):
    """ERR_PET_DOUBLE_BOOKED: new window overlaps any non-RELEASED assignment of
    the same pet, using closed/inclusive semantics."""
    for a in _non_released_assignments():
        res = _reservation_of(a)
        if res is None or res["pet_id"] != pet_id:
            continue
        if _closed_overlap(win_start, win_end, a["window_start_date"],
                           a["window_end_date"]):
            raise errors.err_pet_double_booked()


def check_suite_overlap(run_id, win_start, win_end):
    """ERR_RUN_OVERLAP: OVERNIGHT_SUITE half-open interval collides with an
    existing non-RELEASED assignment on the same suite."""
    for a in _non_released_assignments():
        if a["run_id"] != run_id:
            continue
        if _half_open_overlap(win_start, win_end, a["window_start_date"],
                              a["window_end_date"]):
            raise errors.err_run_overlap()


def _daycare_date_set(win_start, win_end):
    """Set of calendar dates (ordinals) covered by a daycare window. Daycare
    windows span a single date [start, start+1)."""
    s = parse_date(win_start).toordinal()
    e = parse_date(win_end).toordinal()
    return set(range(s, e))


def check_daycare_capacity(run, win_start, win_end, facility):
    """ERR_RUN_CAPACITY_EXCEEDED: for each date in the candidate window, the
    count of non-RELEASED assignments on that date (including candidate) must
    not exceed daycare_capacity + overbook_grace."""
    cap = run["daycare_capacity"] + facility["overbook_grace"]
    cand_dates = _daycare_date_set(win_start, win_end)
    for d in cand_dates:
        count = 1  # candidate itself
        for a in _non_released_assignments():
            if a["run_id"] != run["id"]:
                continue
            a_dates = _daycare_date_set(a["window_start_date"], a["window_end_date"])
            if d in a_dates:
                count += 1
        if count > cap:
            raise errors.err_run_capacity_exceeded()


def check_group_compatibility(run, candidate_pet, win_start, win_end):
    """ERR_GROUP_INCOMPATIBLE on DAYCARE_PEN: candidate scored against existing
    HELD/OCCUPIED pets on the overlapping date, oldest-first by created_at."""
    cand_dates = _daycare_date_set(win_start, win_end)
    # Gather existing assignments on this run that are HELD or OCCUPIED and
    # share a date with the candidate; order oldest-first by created_at.
    existing_assignments = []
    for a in db.run_assignments.values():
        if a["run_id"] != run["id"]:
            continue
        if a["status"] not in ("HELD", "OCCUPIED"):
            continue
        a_dates = _daycare_date_set(a["window_start_date"], a["window_end_date"])
        if cand_dates & a_dates:
            existing_assignments.append(a)
    existing_assignments.sort(key=lambda a: a["created_at"])

    existing_pets = []
    for a in existing_assignments:
        res = _reservation_of(a)
        if res is None:
            continue
        epet = db.pets.get(res["pet_id"])
        if epet is None:
            continue
        existing_pets.append((epet["size_class"], epet["temperament"]))

    score = calc.group_compatibility_score(candidate_pet["size_class"],
                                           candidate_pet["temperament"],
                                           existing_pets)
    ceiling = calc.group_ceiling(candidate_pet["temperament"])
    if score > ceiling:
        raise errors.err_group_incompatible()
