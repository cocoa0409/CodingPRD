"""The nine calculations of the contract, with every rounding point pinned."""
import math
from datetime import timedelta

import store
from util import parse_dt, rhu

TYPE_MULTIPLIER = {
    "MONOHULL": 1.00,
    "MULTIHULL": 0.82,
    "KEELBOAT_SPORT": 0.94,
}

BONUS_TABLE = {1: 0.0, 2: 3.0, 3: 5.7, 4: 8.0, 5: 10.0, 6: 11.7}
BONUS_TAIL_OFFSET = 6.0

PRESTART_COVERAGE_MINUTES = 30
POSTSTART_COVERAGE_MINUTES = 120

REQUIRED_ALWAYS = ("PRO", "TIMEKEEPER", "SIGNALS")


# --------------------------------------------------------------------------
# certificate_rating_value
# --------------------------------------------------------------------------


def certificate_rating_value(rule_code, sail_area_m2, hull_length_m, displacement_kg, draft_m, boat_type):
    """Returns (raw_speed_index, rating_value, band_key_spm)."""
    base = math.sqrt(float(sail_area_m2)) / (float(displacement_kg) ** (1.0 / 3.0))
    length_factor = max(1.00, min(1.60, float(hull_length_m) / 8.0))
    draft_penalty = 0.03 if float(draft_m) > 2.20 else 0.00
    type_multiplier = TYPE_MULTIPLIER[boat_type]
    # the 4-decimal rounding happens BEFORE the rule branch
    raw_speed_index = rhu(base * length_factor * (1.0 - draft_penalty) * type_multiplier, 4)
    if rule_code == "TOD_PHRF":
        rating_value = max(-30.0, min(300.0, rhu(420.0 - 380.0 * raw_speed_index, 1)))
        band_key_spm = rating_value
    else:
        rating_value = max(0.5000, min(1.6000, rhu(0.4000 + 0.7000 * raw_speed_index, 4)))
        band_key_spm = rhu(420.0 - 542.8571 * (rating_value - 0.4000), 1)
    return raw_speed_index, rating_value, band_key_spm


# --------------------------------------------------------------------------
# corrected_time
# --------------------------------------------------------------------------


def corrected_time(elapsed_seconds, cert, race, regatta):
    """Dual variant. Only ever called for a FINISHED result."""
    if elapsed_seconds is None or cert is None:
        return None
    if regatta.get("handicap_basis") == "UNIFIED_TOD" or cert.get("rule_code") == "TOD_PHRF":
        # variant TIME_ON_DISTANCE
        if cert.get("rule_code") == "TOD_PHRF":
            allowance_spm = cert.get("rating_value")
        else:
            allowance_spm = cert.get("band_key_spm")
        return rhu(float(elapsed_seconds) - float(allowance_spm) * float(race["course_distance_nm"]), 1)
    # variant TIME_ON_TIME
    return rhu(float(elapsed_seconds) * float(cert["rating_value"]), 1)


def result_corrected_seconds(result, race, regatta):
    if result.get("finish_status") != "FINISHED":
        return None
    entry = store.get("entries", result.get("entry_id"))
    if entry is None:
        return None
    cert = store.get("rating_certificates", entry.get("certificate_id"))
    return corrected_time(result.get("elapsed_seconds"), cert, race, regatta)


# --------------------------------------------------------------------------
# race_points_and_places
# --------------------------------------------------------------------------


def _base_points(slot, scoring_system):
    if scoring_system == "LOW_POINT":
        return float(slot)
    if slot <= 6:
        return BONUS_TABLE[slot]
    return float(slot) + BONUS_TAIL_OFFSET


def race_points_and_places(race):
    """Writes corrected_seconds, place, points and Race.points_pool_total."""
    regatta = store.get("regattas", race["regatta_id"])
    scoring_system = regatta["scoring_system"]
    all_results = [r for r in store.find("race_results", race_id=race["id"])]

    # corrected times are recomputed whenever the race points are recomputed
    for result in all_results:
        if result.get("voided"):
            continue
        store.apply_changes(result, {"corrected_seconds": result_corrected_seconds(result, race, regatta)})

    scored_ids = set()
    for division in store.find("divisions", regatta_id=race["regatta_id"]):
        if int(division.get("accepted_entry_count") or 0) < 1:
            continue
        n_div = int(division["accepted_entry_count"])
        candidates = []
        for result in all_results:
            if result.get("voided"):
                continue
            entry = store.get("entries", result.get("entry_id"))
            if entry is None or entry.get("division_id") != division["id"]:
                continue
            if entry.get("registration_status") != "ACCEPTED":
                continue
            candidates.append((result, entry))
        for result, _entry in candidates:
            scored_ids.add(result["id"])
        _score_division(candidates, n_div, scoring_system)

    # rows excluded from every division pass keep points 0 and place null
    for result in all_results:
        if result.get("voided") or result["id"] in scored_ids:
            continue
        store.apply_changes(result, {"points": 0, "place": None})

    total = 0.0
    for result in all_results:
        if result.get("voided"):
            continue
        total += float(result.get("points") or 0)
    store.apply_changes(race, {"points_pool_total": rhu(total, 1)})


def _score_division(candidates, n_div, scoring_system):
    finishers = [pair for pair in candidates if pair[0].get("finish_status") == "FINISHED"]
    finishers.sort(
        key=lambda pair: (
            float(pair[0].get("corrected_seconds") or 0),
            float(pair[0].get("elapsed_seconds") or 0),
            pair[1]["_seq"],
        )
    )
    # tie groups are maximal runs of equal corrected_seconds
    index = 0
    while index < len(finishers):
        span = 1
        key = finishers[index][0].get("corrected_seconds")
        while index + span < len(finishers) and finishers[index + span][0].get("corrected_seconds") == key:
            span += 1
        first_slot = index + 1
        slots = range(first_slot, first_slot + span)
        group_points = rhu(sum(_base_points(s, scoring_system) for s in slots) / float(span), 1)
        for result, _entry in finishers[index : index + span]:
            penalty = float(result.get("penalty_percent") or 0)
            if penalty > 0:
                points = rhu(
                    min(group_points + penalty / 100.0 * n_div, float(n_div + 1)),
                    1,
                )
            else:
                points = group_points
            store.apply_changes(result, {"place": first_slot, "points": points})
        index += span

    for result, _entry in candidates:
        status = result.get("finish_status")
        if status == "FINISHED":
            continue
        if status == "DNC":
            points = float(n_div + 2)
        elif status == "RDG":
            # taken from redress_points_average and never recomputed here
            points = result.get("points")
        else:
            points = float(n_div + 1)
        store.apply_changes(result, {"place": None, "points": points})


# --------------------------------------------------------------------------
# series_standing
# --------------------------------------------------------------------------


def counted_races(regatta):
    races = [
        r
        for r in store.find("races", regatta_id=regatta["id"])
        if r.get("scoring_status") == "FINAL" and r.get("start_status") != "ABANDONED"
    ]
    races.sort(key=lambda r: r["race_number"])
    return races


def _discard_count(policy, completed):
    if policy == "ONE_PER_FIVE":
        return 1 if completed >= 5 else 0
    if policy == "ONE_PER_FOUR":
        return min(2, completed // 4)
    return 0


def _entry_result_in(race_id, entry_id):
    for result in store.find("race_results", race_id=race_id, entry_id=entry_id):
        return result
    return None


def entry_standing(regatta, entry, races=None):
    """Pure computation of one entry's series columns."""
    races = counted_races(regatta) if races is None else races
    completed = len(races)
    per_race = []
    pool = []
    place_counts = {}
    last_points = None
    for race in races:
        result = _entry_result_in(race["id"], entry["id"])
        if result is None or result.get("voided"):
            continue
        points = float(result.get("points") or 0)
        per_race.append(points)
        place = result.get("place")
        if place is not None:
            place_counts[int(place)] = place_counts.get(int(place), 0) + 1
        if result.get("discardable"):
            pool.append((points, int(race["race_number"])))
    if races:
        last_race = races[-1]
        last_result = _entry_result_in(last_race["id"], entry["id"])
        if last_result is not None and not last_result.get("voided"):
            last_points = float(last_result.get("points") or 0)
    gross = rhu(sum(per_race), 1) if per_race else 0
    discard_count = _discard_count(regatta.get("discard_policy"), completed)
    # highest points first; on equal points the HIGHER race_number goes first
    pool.sort(key=lambda item: (-item[0], -item[1]))
    discards = pool[:discard_count]
    net = rhu(float(gross) - sum(item[0] for item in discards), 1) if discards else gross
    return {
        "entry": entry,
        "gross": gross,
        "net": net,
        "discarded_race_numbers": sorted(item[1] for item in discards),
        "completed": completed,
        "place_counts": place_counts,
        "last_points": last_points,
    }


def division_standings(regatta, division):
    """Every ACCEPTED entry of the division, in rank order, with a trace."""
    races = counted_races(regatta)
    entries = [
        e
        for e in store.find("entries", division_id=division["id"])
        if e.get("registration_status") == "ACCEPTED"
    ]
    rows = [entry_standing(regatta, entry, races) for entry in entries]
    n_div = max(1, int(division.get("accepted_entry_count") or len(entries) or 1))

    def firsts_key(row):
        return tuple(-row["place_counts"].get(place, 0) for place in range(1, n_div + 1))

    def last_key(row):
        return float("inf") if row["last_points"] is None else row["last_points"]

    for row in rows:
        row["_t1"] = firsts_key(row)
        row["_t2"] = last_key(row)
    rows.sort(key=lambda row: (float(row["net"]), row["_t1"], row["_t2"], row["entry"]["_seq"]))

    previous = None
    for index, row in enumerate(rows):
        if row["completed"] == 0:
            row["rank"] = None
            row["trace"] = "NO_COUNTED_RACES"
        else:
            row["rank"] = index + 1
            row["trace"] = _trace(previous, row)
        previous = row
    return rows


def _trace(previous, row):
    if previous is None:
        return "NET_POINTS"
    if float(previous["net"]) != float(row["net"]):
        return "NET_POINTS"
    if previous["_t1"] != row["_t1"]:
        return "PLACE_COUNTS"
    if previous["_t2"] != row["_t2"]:
        return "LAST_RACE_POINTS"
    return "CREATED_AT"


# --------------------------------------------------------------------------
# redress_points_average
# --------------------------------------------------------------------------

REDRESS_SOURCE_STATUSES = ("FINISHED", "DNF", "DNS", "RET", "OCS")


def redress_points_average(regatta, entry, redress_race):
    """None when the source set is empty (ERR_REDRESS_NOT_COMPUTABLE)."""
    values = []
    for race in counted_races(regatta):
        if race["id"] == redress_race["id"]:
            continue
        result = _entry_result_in(race["id"], entry["id"])
        if result is None or result.get("voided"):
            continue
        if result.get("finish_status") not in REDRESS_SOURCE_STATUSES:
            continue
        values.append(float(result.get("points") or 0))
    if not values:
        return None
    return rhu(sum(values) / float(len(values)), 1)


# --------------------------------------------------------------------------
# entry_division_assignment_selection
# --------------------------------------------------------------------------


def eligible_divisions(entry, cert, boat):
    key = float(cert["band_key_spm"])
    boat_type = boat["boat_type"]
    eligible = []
    for division in store.find("divisions", regatta_id=entry["regatta_id"]):
        if division.get("status") not in ("PROVISIONAL", "CONFIRMED"):
            continue
        if division["boat_type_filter"] not in (boat_type, "ANY"):
            continue
        if not (float(division["rating_band_low"]) <= key < float(division["rating_band_high"])):
            continue
        eligible.append(division)
    eligible.sort(
        key=lambda d: (
            float(d["rating_band_high"]) - float(d["rating_band_low"]),
            float(d["rating_band_low"]),
            d["_seq"],
        )
    )
    return eligible


# --------------------------------------------------------------------------
# division_merge_target_selection
# --------------------------------------------------------------------------


def merge_candidates(source):
    def mid(division):
        return (float(division["rating_band_low"]) + float(division["rating_band_high"])) / 2.0

    source_mid = mid(source)
    candidates = []
    for division in store.find("divisions", regatta_id=source["regatta_id"]):
        if division["id"] == source["id"]:
            continue
        if division.get("status") not in ("PROVISIONAL", "CONFIRMED"):
            continue
        if division["boat_type_filter"] not in (source["boat_type_filter"], "ANY"):
            continue
        candidates.append(division)
    candidates.sort(
        key=lambda d: (
            abs(mid(d) - source_mid),
            float(d["rating_band_low"]),
            d["_seq"],
        )
    )
    return candidates


# --------------------------------------------------------------------------
# race_staffing_readiness
# --------------------------------------------------------------------------


def coverage_window(race):
    start = parse_dt(race["scheduled_start_utc"])
    return (
        start - timedelta(minutes=PRESTART_COVERAGE_MINUTES),
        start + timedelta(minutes=POSTSTART_COVERAGE_MINUTES),
    )


def required_positions(race, regatta):
    required = {"PRO": 1, "TIMEKEEPER": 1, "SIGNALS": 1}
    if race["course_code"] in ("WINDWARD_LEEWARD", "TRIANGLE"):
        required["MARK_BOAT_DRIVER"] = 1
    if regatta["safety_category"] in ("CAT_3", "CAT_2"):
        required["SAFETY_BOAT"] = 1
    return required


def covers(assignment, window_start, window_end):
    return (
        parse_dt(assignment["window_start_utc"]) <= window_start
        and parse_dt(assignment["window_end_utc"]) >= window_end
    )


def on_station(race):
    window_start, window_end = coverage_window(race)
    out = []
    for assignment in store.find("duty_assignments", regatta_id=race["regatta_id"]):
        if assignment.get("status") != "CONFIRMED":
            continue
        if assignment.get("race_id") not in (None, race["id"]):
            continue
        if not covers(assignment, window_start, window_end):
            continue
        out.append(assignment)
    return out


def race_staffing_readiness(race):
    """Returns (ready, staffed_position_codes, missing_position_codes, w_start, w_end)."""
    regatta = store.get("regattas", race["regatta_id"])
    window_start, window_end = coverage_window(race)
    assignments = on_station(race)
    counts = {}
    for assignment in assignments:
        position = assignment["position"]
        counts[position] = counts.get(position, 0) + 1
    required = required_positions(race, regatta)
    missing = sorted(p for p in required if counts.get(p, 0) < required[p])
    staffed = sorted(set(counts.keys()))
    return (not missing), staffed, missing, window_start, window_end


# --------------------------------------------------------------------------
# duty_minutes_ledger
# --------------------------------------------------------------------------

LEDGER_STATUSES = ("PROPOSED", "CONFIRMED")


def member_duty_minutes(member_id):
    total = 0
    for assignment in store.find("duty_assignments", member_id=member_id):
        if assignment.get("status") in LEDGER_STATUSES:
            total += int(assignment.get("duty_minutes") or 0)
    return total


def mark_boat_committed_minutes(mark_boat_id):
    total = 0
    for assignment in store.find("duty_assignments", mark_boat_id=mark_boat_id):
        if assignment.get("status") in LEDGER_STATUSES:
            total += int(assignment.get("duty_minutes") or 0)
    return total
