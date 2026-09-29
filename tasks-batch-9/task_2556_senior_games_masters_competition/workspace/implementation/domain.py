"""Store-aware domain logic: lookups, gates and cascades."""
import calc
import store
from core import as_date, as_dt, fail

LIVE_ENTRY_STATES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "ACCEPTED",
    "WAITLISTED",
    "MEDICAL_HOLD",
)
FEE_ENTRY_STATES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "WAITLISTED",
    "ACCEPTED",
)
NO_CAPACITY_ENTRY_STATES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "WAITLISTED",
)
CLEARED_MEDICAL_STATES = ("SCREENED_CLEARED", "SCREENED_RESTRICTED", "CLEARED_BY_APPEAL")
IMPACT_HEAD_STATES = ("PENDING_PAYMENT", "REGISTERED", "CHECKED_IN")
OCCUPYING_SLOT_STATES = ("SCHEDULED", "IN_PROGRESS")
LIVE_ASSIGNMENT_STATES = ("ASSIGNED", "CONFIRMED")
LEDGER_ASSIGNMENT_STATES = ("ASSIGNED", "CONFIRMED", "COMPLETED")
OCCUPYING_STAY_STATES = ("RESERVED", "CHECKED_IN", "COMPLETED")
LIVE_RESULT_STATES = ("VERIFIED", "RECORD_PENDING", "PUBLISHED")


# ------------------------------------------------------------------- lookups
def entries_of_athlete(athlete_id, statuses=None):
    out = [e for e in store.rows("sport_entry") if e["athlete_id"] == athlete_id]
    if statuses is not None:
        out = [e for e in out if e["status"] in statuses]
    return out


def entries_of_event(event_id, statuses=None):
    out = [e for e in store.rows("sport_entry") if e["sport_event_id"] == event_id]
    if statuses is not None:
        out = [e for e in out if e["status"] in statuses]
    return out


def event_of_entry(entry):
    return store.get("sport_event", entry["sport_event_id"])


def sport_of_event(event):
    return store.get("sport", event["sport_id"])


def edition_of_athlete(athlete):
    return store.get("games_edition", athlete["games_edition_id"])


def slots_of_event(event_id, statuses=None):
    out = [s for s in store.rows("session_slot") if s["sport_event_id"] == event_id]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return out


def slots_of_venue(venue_id, statuses=None):
    out = [s for s in store.rows("session_slot") if s["venue_id"] == venue_id]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return out


def assignments_of_slot(slot_id, statuses=None):
    out = [
        a for a in store.rows("personnel_assignment") if a["session_slot_id"] == slot_id
    ]
    if statuses is not None:
        out = [a for a in out if a["status"] in statuses]
    return out


def assignments_of_person(personnel_id, statuses=None):
    out = [
        a for a in store.rows("personnel_assignment") if a["personnel_id"] == personnel_id
    ]
    if statuses is not None:
        out = [a for a in out if a["status"] in statuses]
    return out


def results_of_entry(entry_id, statuses=None):
    out = [r for r in store.rows("competition_result") if r["sport_entry_id"] == entry_id]
    if statuses is not None:
        out = [r for r in out if r["status"] in statuses]
    return out


def records_citing(result_id, statuses=None):
    out = [
        r
        for r in store.rows("age_group_record")
        if r["competition_result_id"] == result_id
    ]
    if statuses is not None:
        out = [r for r in out if r["status"] in statuses]
    return out


def stays_of_athlete(athlete_id, statuses=None):
    out = [s for s in store.rows("village_stay") if s["athlete_id"] == athlete_id]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return out


def stays_of_block(block_id, statuses=None):
    out = [
        s for s in store.rows("village_stay") if s["accommodation_block_id"] == block_id
    ]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return out


def athletes_of_edition(edition_id, statuses=None):
    out = [a for a in store.rows("athlete") if a["games_edition_id"] == edition_id]
    if statuses is not None:
        out = [a for a in out if a["registration_status"] in statuses]
    return out


def blocks_of_edition(edition_id):
    return [b for b in store.rows("accommodation_block") if b["games_edition_id"] == edition_id]


def basis_age(athlete, edition):
    if edition and edition.get("age_basis") == "FIRST_COMPETITION_DAY":
        return athlete["age_at_first_day"]
    return athlete["age_at_reference"]


def contact_sport_count(athlete_id):
    total = 0
    for entry in entries_of_athlete(athlete_id, FEE_ENTRY_STATES):
        event = event_of_entry(entry)
        if event is None:
            continue
        sport = sport_of_event(event)
        if sport is not None and sport["contact_class"] == "HIGH":
            total += 1
    return total


# ------------------------------------------------------------------- cascades
def event_to_undersubscribed(event):
    was_seeded = event["status"] == "SEEDED"
    event["status"] = "UNDERSUBSCRIBED"
    if was_seeded:
        event["seeded_at_utc"] = None
    store.touch(event)
    for slot in slots_of_event(event["id"], ("SCHEDULED",)):
        release_slot(slot)


def event_release_capacity(event):
    """An entry leaves ACCEPTED: give the slot back, maybe fall undersubscribed."""
    event["accepted_entry_count"] -= 1
    event["available_slots"] += 1
    store.touch(event)
    if (
        event["status"] in ("OPEN", "SEEDED")
        and event["accepted_entry_count"] < event["min_entries_to_stage"]
    ):
        event_to_undersubscribed(event)


def event_consume_capacity(event):
    """An entry enters ACCEPTED: take a slot, maybe recover to OPEN."""
    event["accepted_entry_count"] += 1
    event["available_slots"] -= 1
    store.touch(event)
    if (
        event["status"] == "UNDERSUBSCRIBED"
        and event["accepted_entry_count"] >= event["min_entries_to_stage"]
    ):
        event["status"] = "OPEN"
        store.touch(event)


def release_assignment(assignment, adjust_slot_counter=True):
    was_confirmed = assignment["status"] == "CONFIRMED"
    assignment["status"] = "RELEASED"
    store.touch(assignment)
    person = store.get("personnel", assignment["personnel_id"])
    if person is not None:
        person["assigned_minutes_total"] -= assignment["duration_minutes"]
        store.touch(person)
    if adjust_slot_counter and was_confirmed and person is not None:
        if person["personnel_type"] == "OFFICIAL":
            slot = store.get("session_slot", assignment["session_slot_id"])
            if slot is not None:
                slot["confirmed_official_count"] = max(
                    0, slot["confirmed_official_count"] - 1
                )
                store.touch(slot)


def release_slot(slot):
    """Event fell undersubscribed or was cancelled: the block is given up."""
    slot["status"] = "RELEASED"
    slot["confirmed_official_count"] = 0
    store.touch(slot)
    for assignment in assignments_of_slot(slot["id"], LIVE_ASSIGNMENT_STATES):
        release_assignment(assignment, adjust_slot_counter=False)


def displace_slot(slot):
    """Venue closure: the block is abandoned where it stands."""
    from_scheduled = slot["status"] == "SCHEDULED"
    slot["status"] = "DISPLACED"
    if from_scheduled:
        slot["confirmed_official_count"] = 0
    store.touch(slot)
    for assignment in assignments_of_slot(slot["id"], LIVE_ASSIGNMENT_STATES):
        release_assignment(assignment, adjust_slot_counter=False)


def complete_slot(slot):
    """Block closes: confirmed service completes, no-shows are booked."""
    slot["status"] = "COMPLETED"
    store.touch(slot)
    for assignment in assignments_of_slot(slot["id"]):
        if assignment["status"] == "CONFIRMED":
            assignment["status"] = "COMPLETED"
            store.touch(assignment)
        elif assignment["status"] == "ASSIGNED":
            assignment["status"] = "NO_SHOW"
            store.touch(assignment)
            person = store.get("personnel", assignment["personnel_id"])
            if person is not None:
                person["no_show_count"] += 1
                person["assigned_minutes_total"] -= assignment["duration_minutes"]
                store.touch(person)
    event = store.get("sport_event", slot["sport_event_id"])
    if event is not None and event["status"] == "IN_PROGRESS":
        if not slots_of_event(event["id"], ("SCHEDULED", "IN_PROGRESS", "DISPLACED")):
            event["status"] = "COMPLETED"
            store.touch(event)


def withdraw_entry(entry):
    was_accepted = entry["status"] == "ACCEPTED"
    entry["status"] = "WITHDRAWN"
    store.touch(entry)
    if was_accepted:
        event = event_of_entry(entry)
        if event is not None:
            event_release_capacity(event)


def hold_entry(entry):
    entry["status"] = "MEDICAL_HOLD"
    store.touch(entry)
    event = event_of_entry(entry)
    if event is not None:
        event_release_capacity(event)


def cancel_stay(stay):
    stay["status"] = "CANCELLED"
    stay["total_charge_cents"] = 0
    store.touch(stay)
    block = store.get("accommodation_block", stay["accommodation_block_id"])
    if block is not None:
        block["reserved_bed_nights"] -= stay["nights"]
        store.touch(block)


def withdraw_athlete_cascade(athlete, entry_states, stay_states):
    for entry in entries_of_athlete(athlete["id"], entry_states):
        withdraw_entry(entry)
    for stay in stays_of_athlete(athlete["id"], stay_states):
        cancel_stay(stay)


# ---------------------------------------------------------------------- gates
def venue_area_gate(venue, start, end, buffer_minutes, exclude_slot_id=None):
    cand_lo, cand_hi = calc.occupied_window(start, end, buffer_minutes)
    occupied = 0
    for slot in slots_of_venue(venue["id"], OCCUPYING_SLOT_STATES):
        if exclude_slot_id is not None and slot["id"] == exclude_slot_id:
            continue
        lo, hi = calc.occupied_window(
            as_dt(slot["start_utc"]),
            as_dt(slot["end_utc"]),
            slot["teardown_buffer_minutes"],
        )
        if calc.windows_intersect(cand_lo, cand_hi, lo, hi):
            occupied += 1
    if occupied >= venue["competition_area_count"]:
        fail("ERR_VENUE_AREA_CAPACITY_EXCEEDED")


def athlete_slot_windows(athlete_id, exclude_slot_id=None, extra_event_ids=()):
    event_ids = {
        e["sport_event_id"] for e in entries_of_athlete(athlete_id, ("ACCEPTED",))
    }
    event_ids.update(extra_event_ids)
    windows = []
    for slot in store.rows("session_slot"):
        if slot["status"] not in OCCUPYING_SLOT_STATES:
            continue
        if slot["sport_event_id"] not in event_ids:
            continue
        if exclude_slot_id is not None and slot["id"] == exclude_slot_id:
            continue
        windows.append((as_dt(slot["start_utc"]), as_dt(slot["end_utc"])))
    return windows


def recovery_gate(windows):
    total = len(windows)
    for i in range(total):
        for j in range(i + 1, total):
            first = windows[i]
            second = windows[j]
            gap = calc.gap_minutes(first[0], first[1], second[0], second[1])
            if gap < calc.ATHLETE_RECOVERY_GAP_MINUTES:
                fail("ERR_ATHLETE_SCHEDULE_CONFLICT")


def slot_recovery_gate(event, candidate_window, exclude_slot_id=None):
    """Slot write: every ACCEPTED entry of the event must keep its recovery gap."""
    for entry in entries_of_event(event["id"], ("ACCEPTED",)):
        windows = athlete_slot_windows(entry["athlete_id"], exclude_slot_id=exclude_slot_id)
        windows.append(candidate_window)
        recovery_gate(windows)


def acceptance_recovery_gate(entry, event):
    windows = athlete_slot_windows(
        entry["athlete_id"], extra_event_ids=(event["id"],)
    )
    recovery_gate(windows)


def personnel_conflict_gate(person, candidate_slot):
    cand_start = as_dt(candidate_slot["start_utc"])
    cand_end = as_dt(candidate_slot["end_utc"])
    for assignment in assignments_of_person(person["id"], LIVE_ASSIGNMENT_STATES):
        slot = store.get("session_slot", assignment["session_slot_id"])
        if slot is None or slot["status"] not in OCCUPYING_SLOT_STATES:
            continue
        buffer_minutes = (
            calc.TRAVEL_BUFFER_SAME_VENUE_MINUTES
            if slot["venue_id"] == candidate_slot["venue_id"]
            else calc.TRAVEL_BUFFER_CROSS_VENUE_MINUTES
        )
        if calc.personnel_collides(
            as_dt(slot["start_utc"]),
            as_dt(slot["end_utc"]),
            buffer_minutes,
            cand_start,
            cand_end,
        ):
            fail("ERR_PERSONNEL_DOUBLE_BOOKED")


def personnel_daily_gate(person, candidate_slot, duration_minutes):
    candidate_date = as_dt(candidate_slot["start_utc"]).date()
    same_date_minutes = 0
    for assignment in assignments_of_person(person["id"], LIVE_ASSIGNMENT_STATES):
        slot = store.get("session_slot", assignment["session_slot_id"])
        if slot is None:
            continue
        if as_dt(slot["start_utc"]).date() != candidate_date:
            continue
        same_date_minutes += assignment["duration_minutes"]
    if same_date_minutes + duration_minutes > calc.PERSONNEL_DAILY_LIMIT_MINUTES:
        fail("ERR_PERSONNEL_DAILY_LIMIT_EXCEEDED")


def bed_night_gate(block, check_in, check_out):
    existing = stays_of_block(block["id"], OCCUPYING_STAY_STATES)
    for night in calc.stay_dates(check_in, check_out):
        occupied = 0
        for stay in existing:
            start = as_date(stay["check_in_date"])
            end = as_date(stay["check_out_date"])
            if start is None or end is None:
                continue
            if start <= night < end:
                occupied += 1
        if occupied >= block["bed_capacity"]:
            fail("ERR_BLOCK_NIGHT_FULL")


# --------------------------------------------------------- waitlist promotion
def _promotion_key(entry, mark_direction):
    mark = entry.get("qualifying_mark")
    if mark is None:
        null_rank = 1
        mark_key = 0
    else:
        null_rank = 0
        mark_key = mark if mark_direction == "LOWER_IS_BETTER" else -mark
    return (
        entry["qualification_priority"],
        null_rank,
        mark_key,
        entry["created_at"],
        entry["_seq"],
    )


def promote_waitlist(edition_id):
    events = [
        e
        for e in store.rows("sport_event")
        if e["games_edition_id"] == edition_id
        and e["status"] in ("OPEN", "SEEDED", "UNDERSUBSCRIBED")
        and e["available_slots"] > 0
    ]
    for event in events:
        sport = sport_of_event(event)
        direction = sport["mark_direction"] if sport else "LOWER_IS_BETTER"
        candidates = []
        for entry in entries_of_event(event["id"], ("WAITLISTED",)):
            athlete = store.get("athlete", entry["athlete_id"])
            if athlete is None:
                continue
            if athlete["registration_status"] != "REGISTERED":
                continue
            if athlete["medical_status"] not in CLEARED_MEDICAL_STATES:
                continue
            candidates.append(entry)
        candidates.sort(key=lambda row: _promotion_key(row, direction))
        for entry in candidates:
            if event["available_slots"] <= 0:
                break
            entry["status"] = "ACCEPTED"
            store.touch(entry)
            event_consume_capacity(event)


# ------------------------------------------------------------ impact counting
def registered_head_count(edition_id):
    return len(athletes_of_edition(edition_id, IMPACT_HEAD_STATES))


def checked_in_head_count(edition_id):
    return len(athletes_of_edition(edition_id, ("CHECKED_IN",)))


def actual_room_nights(edition_id):
    block_ids = {b["id"] for b in blocks_of_edition(edition_id)}
    stays = [
        s
        for s in store.rows("village_stay")
        if s["accommodation_block_id"] in block_ids
        and s["status"] in ("CHECKED_IN", "COMPLETED")
    ]
    stays.sort(key=lambda s: (s["check_in_date"], s["created_at"], s["_seq"]))
    total = 0
    for stay in stays:
        total += stay["nights"]
    return total
