"""Cascades, derived counters and the conflict predicates.

Every function here completes inside the request that calls it: there is no
queue, no background job and no partially applied cascade (PRD 2.9).
"""
import calc
import store
from util import rhu

# --------------------------------------------------------------------------
# divisions and the fleet floor
# --------------------------------------------------------------------------


def eff_floor(division, regatta):
    """max(division.min_entries, regatta.fleet_minimum) -- PRD 3.2, 3.4."""
    return max(int(division["min_entries"]), int(regatta["fleet_minimum"]))


def derive_counts(division):
    assigned = 0
    accepted = 0
    for entry in store.find("entries", division_id=division["id"]):
        status = entry.get("registration_status")
        if status in ("SUBMITTED", "ACCEPTED"):
            assigned += 1
        if status == "ACCEPTED":
            accepted += 1
    return assigned, accepted


def refresh_counts(division):
    assigned, accepted = derive_counts(division)
    return store.apply_changes(
        division, {"assigned_entry_count": assigned, "accepted_entry_count": accepted}
    )


def refresh_division(division, regatta=None):
    """Re-derive both counts and apply the CONFIRMED -> PROVISIONAL revert edge.

    Returns True when the division reverted, which is what causes the next hop.
    """
    if regatta is None:
        regatta = store.get("regattas", division["regatta_id"])
    refresh_counts(division)
    reverted = False
    if division.get("status") == "CONFIRMED":
        if int(division["assigned_entry_count"]) < eff_floor(division, regatta):
            store.apply_changes(division, {"status": "PROVISIONAL"})
            reverted = True
    if reverted:
        refresh_confirmed_division_count(regatta)
        block_pending_races(regatta)
    return reverted


def refresh_confirmed_division_count(regatta):
    count = len(
        [d for d in store.find("divisions", regatta_id=regatta["id"]) if d.get("status") == "CONFIRMED"]
    )
    store.apply_changes(regatta, {"confirmed_division_count": count})


def under_min_division_exists(regatta):
    """Some non-merged division already holding an assigned entry is under its floor."""
    for division in store.find("divisions", regatta_id=regatta["id"]):
        if division.get("status") == "MERGED":
            continue
        if int(division.get("assigned_entry_count") or 0) < 1:
            continue
        if int(division["assigned_entry_count"]) < eff_floor(division, regatta):
            return True
    return False


def provisional_with_entries_exists(regatta):
    """The clearing predicate of PRD 3.4: any PROVISIONAL division holding entries."""
    for division in store.find("divisions", regatta_id=regatta["id"]):
        if division.get("status") != "PROVISIONAL":
            continue
        if int(division.get("assigned_entry_count") or 0) >= 1:
            return True
    return False


def block_pending_races(regatta):
    for race in store.find("races", regatta_id=regatta["id"]):
        if race.get("start_status") == "PENDING":
            store.apply_changes(race, {"start_blocked_reason": "DIVISION_UNDER_MINIMUM"})


def clear_blocked_races(regatta):
    """Only clears once no division of the regatta is PROVISIONAL while holding entries."""
    if provisional_with_entries_exists(regatta):
        return
    for race in store.find("races", regatta_id=regatta["id"]):
        if race.get("start_blocked_reason") == "DIVISION_UNDER_MINIMUM":
            store.apply_changes(race, {"start_blocked_reason": None})


# --------------------------------------------------------------------------
# staffing
# --------------------------------------------------------------------------


def refresh_staffing(race):
    ready, staffed, _missing, _ws, _we = calc.race_staffing_readiness(race)
    store.apply_changes(race, {"staffing_ready": ready, "staffed_position_codes": staffed})


def refresh_pending_staffing(regatta):
    for race in store.find("races", regatta_id=regatta["id"]):
        if race.get("start_status") == "PENDING":
            refresh_staffing(race)


# --------------------------------------------------------------------------
# duty-minutes ledger
# --------------------------------------------------------------------------


def refresh_member_ledger(member):
    store.apply_changes(member, {"assigned_duty_minutes": calc.member_duty_minutes(member["id"])})


def refresh_mark_boat_ledger(mark_boat):
    store.apply_changes(
        mark_boat, {"committed_minutes": calc.mark_boat_committed_minutes(mark_boat["id"])}
    )


# --------------------------------------------------------------------------
# races and the regatta aggregates
# --------------------------------------------------------------------------


def refresh_final_race_count(regatta):
    store.apply_changes(regatta, {"final_race_count": len(calc.counted_races(regatta))})


OPEN_PROTEST_STATUSES = ("FILED", "HEARING_SCHEDULED", "HEARD", "REOPENED")


def open_protest_exists(regatta):
    for protest in store.find("protests", regatta_id=regatta["id"]):
        if protest.get("status") in OPEN_PROTEST_STATUSES:
            return True
    return False


def maybe_score_regatta(regatta):
    """The RACING -> SCORED bubble-up of PRD 3.3. Never requested directly."""
    if regatta.get("status") != "RACING":
        return False
    if int(regatta["final_race_count"]) != int(regatta["planned_race_count"]):
        return False
    if open_protest_exists(regatta):
        return False
    store.apply_changes(regatta, {"status": "SCORED"})
    return True


# --------------------------------------------------------------------------
# series standings
# --------------------------------------------------------------------------


def write_series(regatta, division):
    for row in calc.division_standings(regatta, division):
        store.apply_changes(
            row["entry"],
            {
                "series_points_gross": row["gross"],
                "series_points_net": row["net"],
                "discarded_race_numbers": row["discarded_race_numbers"],
                "series_rank": row["rank"],
            },
        )


def refresh_series(regatta, division=None):
    """Hop 3 of scoring / hop 4 of a decision: re-run the standing."""
    if division is not None:
        write_series(regatta, division)
        return
    for div in store.find("divisions", regatta_id=regatta["id"]):
        write_series(regatta, div)


# --------------------------------------------------------------------------
# segregation of duties (PRD 2.10)
# --------------------------------------------------------------------------


def member_racing_conflict(regatta_id, member_id):
    """True when the member helms, crews or is a CONFIRMED PRO for that regatta."""
    for entry in store.find("entries", regatta_id=regatta_id):
        if entry.get("helm_member_id") == member_id:
            return True
        for element in entry.get("crew_manifest") or []:
            if element.get("member_id") == member_id:
                return True
    for assignment in store.find("duty_assignments", regatta_id=regatta_id, member_id=member_id):
        if assignment.get("status") == "CONFIRMED" and assignment.get("position") == "PRO":
            return True
    return False


def seats_of(panel, non_recused_only=True):
    out = []
    for seat in panel.get("seats") or []:
        if non_recused_only and seat.get("recused"):
            continue
        out.append(seat)
    return out


def member_on_seated_panel(regatta_id, member_id):
    """True when the member holds a non-recused seat on a SEATED panel of the regatta."""
    for panel in store.find("jury_panels", regatta_id=regatta_id):
        if panel.get("status") != "SEATED":
            continue
        for seat in seats_of(panel):
            if seat.get("member_id") == member_id:
                return True
    return False


def hearing_conflict(panel, protest):
    """Panel-versus-parties conflict tested when a hearing is scheduled."""
    helms = set()
    for field in ("protestor_entry_id", "protestee_entry_id"):
        entry = store.get("entries", protest.get(field))
        if entry is not None:
            helms.add(entry.get("helm_member_id"))
    for seat in seats_of(panel):
        if seat.get("member_id") in helms:
            return True
    protestee = store.get("entries", protest.get("protestee_entry_id"))
    if protestee is not None:
        cert = store.get("rating_certificates", protestee.get("certificate_id"))
        if cert is not None and cert.get("measured_by_member_id") == panel.get("chair_member_id"):
            return True
    return False


# --------------------------------------------------------------------------
# crew safety course (PRD 2.7 step 18)
# --------------------------------------------------------------------------


def crew_safety_ok(entry, regatta):
    series_start = store.D(regatta, "series_start_utc")
    for element in entry.get("crew_manifest") or []:
        member = store.get("club_members", element.get("member_id"))
        if member is None:
            return False
        expiry = store.D(member, "safety_course_expiry_utc")
        if expiry is None or expiry < series_start:
            return False
    return True


def crew_weight(entry):
    total = 0.0
    for element in entry.get("crew_manifest") or []:
        total += float(element.get("weight_kg") or 0)
    return rhu(total, 1)
