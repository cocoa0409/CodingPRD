"""Derived-state recomputation, ledgers and cascades.

Recomputations use ``set_value`` so a row is only marked dirty (and therefore
version-bumped) when a stored field genuinely changed; routes additionally
``touch`` every resource the PRD names as version-incrementing.
"""

from decimal import Decimal

import calc
from core import (
    MIN_ENTRIES_FOR_POINTS,
    OFFICIAL_TRAVEL_GAP_MINUTES,
    REGIONAL_SHOW_CAP,
    assignments_of_official,
    assignments_of_slot,
    class_entries_of_class,
    class_entries_of_entry,
    classes_of_show,
    db,
    divisions_of_show,
    entries_of_show,
    minutes_between,
    set_value,
    slots_of_class,
    slots_of_ring,
    submissions_of_class,
    timedelta_minutes,
    touch,
)

ENTRY_COUNT_STATUSES = ("ENTERED", "CONFIRMED", "COMPLETED", "DISQUALIFIED")
CONFIRMED_COUNT_STATUSES = ("CONFIRMED", "COMPLETED")
PRIZE_LEDGER_CLASS_STATUSES = ("RESULTS_POSTED", "POINTS_SUBMITTED")
NATIONAL_CREDITED_STATUSES = ("NATIONAL_ACCEPTED", "RECORDED")
REGIONAL_CREDITED_STATUSES = ("REGIONAL_ACCEPTED", "RECORDED")
OCCUPYING_SLOT_STATUSES = ("SCHEDULED", "RUNNING", "COMPLETED")


# --------------------------------------------------------------------------
# class counters
# --------------------------------------------------------------------------
def recompute_class_counts(cls):
    rows = class_entries_of_class(cls["id"])
    entry_count = sum(1 for ce in rows if ce["status"] in ENTRY_COUNT_STATUSES)
    confirmed = sum(1 for ce in rows if ce["status"] in CONFIRMED_COUNT_STATUSES)
    set_value(cls, "entry_count", entry_count)
    set_value(cls, "confirmed_entry_count", confirmed)
    set_value(cls, "point_eligible", confirmed >= MIN_ENTRIES_FOR_POINTS)


def recompute_placed_count(cls):
    rows = class_entries_of_class(cls["id"])
    placed = sum(
        1 for ce in rows if ce["placing"] is not None and ce["status"] == "COMPLETED"
    )
    set_value(cls, "placed_count", placed)


# --------------------------------------------------------------------------
# show ledgers
# --------------------------------------------------------------------------
def recompute_show_stalls(show):
    total = 0
    for entry in entries_of_show(show["id"]):
        if entry["verification_status"] == "ACCEPTED":
            total += int(entry["assigned_stall_count"])
    set_value(show, "reserved_stall_count", total)


def recompute_show_prizes(show):
    total = 0
    for cls in classes_of_show(show["id"]):
        if cls["status"] in PRIZE_LEDGER_CLASS_STATUSES:
            total += int(cls["awarded_prize_cents"])
    set_value(show, "allocated_prize_cents", total)


def active_division_share(show, extra_bp=0):
    total = extra_bp
    for division in divisions_of_show(show["id"]):
        if division["status"] == "ACTIVE":
            total += int(division["division_share_bp"])
    return total


def recompute_division_share(show):
    set_value(show, "division_share_bp_total", active_division_share(show))


def recompute_welfare_strikes(show):
    count = 0
    for case in db.cases.values():
        if case["case_type"] != "WELFARE_CITATION" or case["status"] != "SUBSTANTIATED":
            continue
        entry = db.entries.get(case["entry_id"])
        if entry is not None and entry["show_id"] == show["id"]:
            count += 1
    set_value(show, "welfare_strike_count", count)


# --------------------------------------------------------------------------
# ring schedule layout
# --------------------------------------------------------------------------
def recompute_ring_layout(ring):
    occupying = [s for s in slots_of_ring(ring["id"]) if s["status"] in OCCUPYING_SLOT_STATUSES]
    occupying.sort(key=lambda s: (s["start_utc"], s["created_at"], s["_seq"]))
    for index, slot in enumerate(occupying, start=1):
        set_value(slot, "order_index", index)
    set_value(
        ring,
        "scheduled_minutes_total",
        sum(minutes_between(s["start_utc"], s["end_utc"]) for s in occupying),
    )
    set_value(ring, "slot_count", len(occupying))


def slot_minutes(slot):
    return minutes_between(slot["warmup_start_utc"], slot["end_utc"])


def ring_overlap(ring, candidate_start, candidate_end):
    buffer_minutes = timedelta_minutes(ring["turnover_buffer_minutes"])
    for slot in slots_of_ring(ring["id"]):
        if slot["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if candidate_start < slot["end_utc"] + buffer_minutes and (
            slot["start_utc"] < candidate_end + buffer_minutes
        ):
            return True
    return False


def official_overlap(official, candidate_slot):
    candidate_ring = candidate_slot["ring_id"]
    for assignment in assignments_of_official(official["id"]):
        if assignment["status"] != "ACTIVE":
            continue
        other = db.slots.get(assignment["slot_id"])
        if other is None or other["id"] == candidate_slot["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        gap = timedelta_minutes(
            0 if other["ring_id"] == candidate_ring else OFFICIAL_TRAVEL_GAP_MINUTES
        )
        if candidate_slot["warmup_start_utc"] <= other["end_utc"] + gap and (
            other["warmup_start_utc"] <= candidate_slot["end_utc"] + gap
        ):
            return True
    return False


# --------------------------------------------------------------------------
# confirmation join
# --------------------------------------------------------------------------
def confirmation_join(entry):
    if entry["verification_status"] != "ACCEPTED" or entry["settlement_status"] != "PAID":
        return
    affected = {}
    for class_entry in class_entries_of_entry(entry["id"]):
        if class_entry["status"] != "ENTERED":
            continue
        class_entry["status"] = "CONFIRMED"
        touch(class_entry)
        cls = db.classes.get(class_entry["class_id"])
        if cls is not None:
            affected[cls["id"]] = cls
    for cls in affected.values():
        recompute_class_counts(cls)


def scratch_class_entries(entry):
    affected = {}
    for class_entry in class_entries_of_entry(entry["id"]):
        if class_entry["status"] not in ("ENTERED", "CONFIRMED"):
            continue
        class_entry["status"] = "SCRATCHED"
        touch(class_entry)
        cls = db.classes.get(class_entry["class_id"])
        if cls is not None:
            affected[cls["id"]] = cls
    for cls in affected.values():
        recompute_class_counts(cls)


# --------------------------------------------------------------------------
# footing cascade
# --------------------------------------------------------------------------
def footing_cascade(ring):
    """Depth-4 unwind fired when an AVAILABLE ring drops below the safety floor."""
    ring["status"] = "MAINTENANCE_HOLD"
    touch(ring)
    for slot in slots_of_ring(ring["id"]):
        if slot["status"] != "SCHEDULED" or slot["slot_type"] != "CLASS":
            continue
        slot["status"] = "CANCELLED"
        touch(slot)
        class_id = slot.get("class_id")
        cls = db.classes.get(class_id) if class_id else None
        if cls is not None and cls["status"] == "SCHEDULED":
            cls["status"] = "OPEN"
            cls["estimated_minutes"] = None
            touch(cls)
        for assignment in assignments_of_slot(slot["id"]):
            if assignment["status"] != "ACTIVE":
                continue
            assignment["status"] = "RELEASED"
            touch(assignment)
            official = db.officials.get(assignment["official_id"])
            if official is not None:
                official["assigned_minutes"] = max(
                    0, int(official["assigned_minutes"]) - slot_minutes(slot)
                )
                touch(official)


# --------------------------------------------------------------------------
# standings crediting
# --------------------------------------------------------------------------
def _rider_of(class_entry):
    entry = db.entries.get(class_entry["entry_id"])
    if entry is None:
        return None, None
    return db.riders.get(entry["rider_id"]), entry


def scoring_class_entries(cls):
    return [ce for ce in class_entries_of_class(cls["id"]) if ce["status"] == "COMPLETED"]


def credit_national(cls, submission, body_reference):
    total = Decimal("0.0")
    for class_entry in scoring_class_entries(cls):
        points = calc.national_points_for(class_entry["placing"], cls["confirmed_entry_count"])
        set_value(class_entry, "points_national", points)
        total += points
        if class_entry["placing"] is not None and points:
            rider, _entry = _rider_of(class_entry)
            if rider is not None:
                set_value(
                    rider,
                    "national_points_total",
                    Decimal(str(rider["national_points_total"])) + points,
                )
    submission["national_points_total"] = total
    submission["national_body_reference"] = body_reference


def _already_credited_regional(rider_id, show_id, exclude_class_id):
    """Regional points already credited to a rider at a show by accepted submissions."""
    total = 0
    for class_entry in db.class_entries.values():
        if class_entry["class_id"] == exclude_class_id:
            continue
        entry = db.entries.get(class_entry["entry_id"])
        if entry is None or entry["show_id"] != show_id or entry["rider_id"] != rider_id:
            continue
        if not any(
            s["status"] in REGIONAL_CREDITED_STATUSES
            for s in submissions_of_class(class_entry["class_id"])
        ):
            continue
        total += int(class_entry["points_regional"])
    return total


def credit_regional(cls, submission, body_reference):
    rows = scoring_class_entries(cls)
    rows.sort(key=lambda ce: (int(cls["class_number"]), ce["created_at"], ce["_seq"]))
    running = {}
    total = 0
    for class_entry in rows:
        rider, entry = _rider_of(class_entry)
        raw = calc.raw_regional_points_for(class_entry["placing"])
        if rider is None or entry is None:
            set_value(class_entry, "points_regional", 0)
            continue
        key = rider["id"]
        if key not in running:
            running[key] = _already_credited_regional(rider["id"], entry["show_id"], cls["id"])
        headroom = max(0, REGIONAL_SHOW_CAP - running[key])
        points = min(raw, headroom)
        set_value(class_entry, "points_regional", points)
        running[key] += points
        total += points
        if points:
            set_value(
                rider, "regional_points_total", int(rider["regional_points_total"]) + points
            )
    submission["regional_points_total"] = total
    submission["regional_body_reference"] = body_reference


def _reverse_national(cls):
    for class_entry in class_entries_of_class(cls["id"]):
        points = Decimal(str(class_entry["points_national"]))
        if points:
            rider, _entry = _rider_of(class_entry)
            if rider is not None:
                set_value(
                    rider,
                    "national_points_total",
                    Decimal(str(rider["national_points_total"])) - points,
                )
        set_value(class_entry, "points_national", Decimal("0.0"))


def _reverse_regional(cls):
    for class_entry in class_entries_of_class(cls["id"]):
        points = int(class_entry["points_regional"])
        if points:
            rider, _entry = _rider_of(class_entry)
            if rider is not None:
                set_value(
                    rider, "regional_points_total", int(rider["regional_points_total"]) - points
                )
        set_value(class_entry, "points_regional", 0)


def reject_submission(submission, cls):
    """Compensate every already-credited leg and zero the submission's totals."""
    status = submission["status"]
    if status in ("NATIONAL_ACCEPTED", "RECORDED"):
        _reverse_national(cls)
    if status in ("REGIONAL_ACCEPTED", "RECORDED"):
        _reverse_regional(cls)
    submission["national_points_total"] = Decimal("0.0")
    submission["regional_points_total"] = 0
    submission["status"] = "REJECTED"
    touch(submission)


def retract_submission(submission, cls):
    """Compensate every credited leg and mark the submission RETRACTED."""
    status = submission["status"]
    if status in ("NATIONAL_ACCEPTED", "RECORDED"):
        _reverse_national(cls)
    if status in ("REGIONAL_ACCEPTED", "RECORDED"):
        _reverse_regional(cls)
    submission["status"] = "RETRACTED"
    touch(submission)


# --------------------------------------------------------------------------
# compliance POSITIVE cascade
# --------------------------------------------------------------------------
def positive_finding_cascade(entry, show):
    horse = db.horses.get(entry["horse_id"])
    if horse is not None:
        horse["eligibility_status"] = "SUSPENDED"
        touch(horse)

    touched_classes = {}
    if horse is not None:
        for class_entry in list(db.class_entries.values()):
            parent = db.entries.get(class_entry["entry_id"])
            if parent is None or parent["horse_id"] != horse["id"]:
                continue
            if class_entry["status"] not in ("ENTERED", "CONFIRMED", "COMPLETED"):
                continue
            cls = db.classes.get(class_entry["class_id"])
            if cls is None or cls["status"] == "VOIDED":
                continue
            class_entry["status"] = "DISQUALIFIED"
            class_entry["prize_cents"] = 0
            class_entry["placing"] = None
            touch(class_entry)
            touched_classes[cls["id"]] = cls

    for cls in touched_classes.values():
        if cls["status"] == "RESULTS_POSTED":
            cls["status"] = "JUDGED"
            cls["awarded_prize_cents"] = 0
            touch(cls)
        recompute_placed_count(cls)
        recompute_class_counts(cls)

    for cls in touched_classes.values():
        for submission in submissions_of_class(cls["id"]):
            if submission["status"] in (
                "PREPARED",
                "NATIONAL_ACCEPTED",
                "REGIONAL_ACCEPTED",
                "RECORDED",
            ):
                retract_submission(submission, cls)

    shows_to_refresh = {show["id"]: show}
    for cls in touched_classes.values():
        division = db.divisions.get(cls["division_id"])
        owning = db.shows.get(division["show_id"]) if division else None
        if owning is not None:
            shows_to_refresh[owning["id"]] = owning
    for owning in shows_to_refresh.values():
        recompute_show_prizes(owning)


# --------------------------------------------------------------------------
# read-only standings recomputation
# --------------------------------------------------------------------------
def rider_standings(rider, show_id=None):
    national_total = Decimal("0.0")
    national_classes = set()
    regional_total = 0
    capped = False

    entries = [e for e in db.entries.values() if e["rider_id"] == rider["id"]]
    if show_id is not None:
        entries = [e for e in entries if e["show_id"] == show_id]

    by_show = {}
    for entry in entries:
        by_show.setdefault(entry["show_id"], []).append(entry)

    for show_entries in by_show.values():
        rows = []
        for entry in show_entries:
            for class_entry in class_entries_of_entry(entry["id"]):
                if class_entry["status"] != "COMPLETED" or class_entry["placing"] is None:
                    continue
                cls = db.classes.get(class_entry["class_id"])
                if cls is not None:
                    rows.append((cls, class_entry))

        for cls, class_entry in rows:
            if any(
                s["status"] in NATIONAL_CREDITED_STATUSES
                for s in submissions_of_class(cls["id"])
            ):
                points = calc.national_points_for(
                    class_entry["placing"], cls["confirmed_entry_count"]
                )
                if points > 0:
                    national_total += points
                    national_classes.add(cls["id"])

        regional_rows = [
            (cls, ce)
            for (cls, ce) in rows
            if any(
                s["status"] in REGIONAL_CREDITED_STATUSES
                for s in submissions_of_class(cls["id"])
            )
        ]
        regional_rows.sort(
            key=lambda pair: (int(pair[0]["class_number"]), pair[1]["created_at"], pair[1]["_seq"])
        )
        running = 0
        for _cls, class_entry in regional_rows:
            raw = calc.raw_regional_points_for(class_entry["placing"])
            points = min(raw, max(0, REGIONAL_SHOW_CAP - running))
            if points < raw:
                capped = True
            running += points
        regional_total += running

    return {
        "rider_id": rider["id"],
        "national_points_total": float(national_total),
        "regional_points_total": regional_total,
        "national_class_count": len(national_classes),
        "regional_capped": capped,
    }


# --------------------------------------------------------------------------
# schedule projection
# --------------------------------------------------------------------------
def schedule_projection(show):
    projected_total = 0
    confirmed_total = 0
    projections = []
    for cls in sorted(classes_of_show(show["id"]), key=lambda c: (c["created_at"], c["_seq"])):
        slot = None
        for candidate in sorted(
            slots_of_class(cls["id"]), key=lambda s: (s["created_at"], s["_seq"])
        ):
            if candidate["status"] in ("SCHEDULED", "RUNNING"):
                slot = candidate
                break
        if slot is None:
            continue
        ring = db.rings.get(slot["ring_id"])
        division = db.divisions.get(cls["division_id"])
        if ring is None or division is None:
            continue
        rows = class_entries_of_class(cls["id"])
        projected_n = calc.count_class_entries(rows, calc.PROJECTED_STATUSES)
        confirmed_n = calc.count_class_entries(rows, calc.CONFIRMED_ONLY_STATUSES)
        projected_minutes = calc.duration_estimate(cls, division, ring, projected_n)
        confirmed_minutes = calc.duration_estimate(cls, division, ring, confirmed_n)
        projected_total += projected_minutes
        confirmed_total += confirmed_minutes
        projections.append(
            {
                "class_id": cls["id"],
                "class_number": cls["class_number"],
                "ring_id": ring["id"],
                "slot_id": slot["id"],
                "projected_minutes": projected_minutes,
                "confirmed_only_minutes": confirmed_minutes,
                "drift_minutes": projected_minutes - confirmed_minutes,
            }
        )
    return {
        "show_id": show["id"],
        "projected_total_minutes": projected_total,
        "confirmed_only_total_minutes": confirmed_total,
        "projected_drift_minutes": projected_total - confirmed_total,
        "class_projections": projections,
    }
