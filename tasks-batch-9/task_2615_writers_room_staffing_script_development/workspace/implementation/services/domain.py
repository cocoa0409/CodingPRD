"""Derived-state recomputation and the three named cascades (PRD 2.10)."""
from datetime import timedelta

from db import created_order, db, end_of_day, touch
from services import calc

# --------------------------------------------------------------- lookups
def agreement_of(season):
    return db.agreements.get(season["guild_agreement_id"])


def rooms_of(season_id):
    return created_order([r for r in db.rooms.values() if r["season_id"] == season_id])


def seats_of(room_id):
    return created_order([s for s in db.seats.values() if s["room_id"] == room_id])


def seats_of_writer(writer_id):
    return created_order([s for s in db.seats.values() if s["writer_id"] == writer_id])


def windows_of(writer_id):
    return created_order([w for w in db.windows.values() if w["writer_id"] == writer_id])


def episodes_of(season_id):
    return created_order([e for e in db.episodes.values() if e["season_id"] == season_id])


def assignments_of(episode_id):
    return created_order([a for a in db.assignments.values() if a["episode_id"] == episode_id])


def assignments_of_seat(seat_id):
    return created_order([a for a in db.assignments.values()
                          if a.get("room_seat_id") == seat_id])


def milestones_of(assignment_id):
    rows = [m for m in db.milestones.values() if m["assignment_id"] == assignment_id]
    return sorted(rows, key=lambda m: (m["sequence_index"], m["_seq"]))


def items_of(review_id):
    return created_order([i for i in db.items.values() if i["review_id"] == review_id])


def submissions_of(episode_id):
    return created_order([s for s in db.submissions.values() if s["episode_id"] == episode_id])


def ledger_of_season(season_id):
    return created_order([e for e in db.ledger.values() if e["season_id"] == season_id])


def ledger_of_assignment(assignment_id):
    return created_order([e for e in db.ledger.values()
                          if e["assignment_id"] == assignment_id])


def season_of_room(room):
    return db.seasons.get(room["season_id"])


def season_of_episode(episode):
    return db.seasons.get(episode["season_id"])


def episode_of_assignment(assignment):
    return db.episodes.get(assignment["episode_id"])


# ------------------------------------------------------- room / season money
def recompute_room(room):
    """Seat counters plus the four-step weekly burn. Returns True if changed."""
    season = season_of_room(room)
    agreement = agreement_of(season)
    seats = seats_of(room["id"])
    before = (room["filled_seat_count"], room["confirmed_seat_count"],
              room["open_seat_count"], room["confirmed_diversity_seat_count"],
              room["seat_subtotal_weekly_cents"], room["facility_tier"],
              room["facility_surcharge_weekly_cents"], room["weekly_burn_cents"])
    filled = [s for s in seats if s["status"] in ("OFFERED", "CONFIRMED")]
    confirmed = [s for s in seats if s["status"] == "CONFIRMED"]
    room["filled_seat_count"] = len(filled)
    room["confirmed_seat_count"] = len(confirmed)
    room["open_seat_count"] = room["seat_capacity"] - len(filled)
    room["confirmed_diversity_seat_count"] = len(
        [s for s in confirmed if s["diversity_program_funded"]])
    calc.room_weekly_burn(room, seats, agreement)
    after = (room["filled_seat_count"], room["confirmed_seat_count"],
             room["open_seat_count"], room["confirmed_diversity_seat_count"],
             room["seat_subtotal_weekly_cents"], room["facility_tier"],
             room["facility_surcharge_weekly_cents"], room["weekly_burn_cents"])
    return before != after


def recompute_season_commitment(season):
    total = 0
    for room in rooms_of(season["id"]):
        if room["status"] in ("STAFFING", "ACTIVE"):
            total += room["weekly_burn_cents"]
    season["staffing_commitment_weekly_cents"] = total
    return total


def recompute_season_committed_fees(season):
    total = sum(e["amount_cents"] for e in ledger_of_season(season["id"]))
    season["script_fee_committed_cents"] = total
    return total


def recompute_coverage(season):
    ready = 0
    for ep in episodes_of(season["id"]):
        if (ep["script_readiness"] in ("READY", "LOCKED")
                and ep["clearance_posture"] in ("CLEARED", "CONDITIONAL_WAIVED")):
            ready += 1
    season["ready_script_count"] = ready
    gap = season["ready_script_target"] - ready
    if gap < 0:
        gap = 0
    season["coverage_gap"] = gap
    if gap == 0:
        season["coverage_posture"] = "COVERED"
    elif gap <= 2:
        season["coverage_posture"] = "AT_RISK"
    else:
        season["coverage_posture"] = "CRITICAL"
    return season


def recompute_seat_money(seat, room=None):
    room = room or db.rooms[seat["room_id"]]
    season = season_of_room(room)
    agreement = agreement_of(season)
    writer = db.writers[seat["writer_id"]]
    calc.seat_weekly_compensation(seat, room, writer, agreement)
    calc.seat_prorated_commitment(seat)
    return seat


# ------------------------------------------------------ milestones / lateness
def set_assignment_due_dates(assignment, episode, agreement):
    """All four due-date fields are always populated regardless of type."""
    start = episode["production_start_date"]
    for kind, field in calc.DUE_DATE_FIELD.items():
        assignment[field] = calc.due_date_for(start, agreement[calc.LEAD_DAY_FIELD[kind]])
    return assignment


def synthesize_milestones(assignment, agreement):
    from db import base_row
    chain = calc.MILESTONE_CHAINS[assignment["assignment_type"]]
    now = db.now()
    rows = []
    for index, kind in enumerate(chain, start=1):
        row = base_row()
        row.update({
            "assignment_id": assignment["id"],
            "milestone_type": kind,
            "sequence_index": index,
            "due_date": assignment[calc.DUE_DATE_FIELD[kind]],
            "delivered_at": None,
            "days_late": 0,
            "status": "PENDING",
        })
        if now > row["due_date"]:
            row["status"] = "LATE"
        db.milestones[row["id"]] = row
        rows.append(row)
    return rows


def recompute_late_milestone_count(assignment):
    count = 0
    for m in milestones_of(assignment["id"]):
        if m["status"] == "LATE":
            count += 1
        elif m["status"] in ("DELIVERED", "NOTES_ISSUED", "ACCEPTED") and m["days_late"] > 0:
            count += 1
    changed = assignment["late_milestone_count"] != count
    assignment["late_milestone_count"] = count
    return changed


# ------------------------------------------------- guarantee settlement / fees
def _candidates(seat, season, extra=None):
    rows = assignments_of_seat(seat["id"])
    if extra is not None:
        rows = rows + [extra]
    if season["guarantee_application_mode"] == "FORWARD_COMMIT":
        pool = [a for a in rows if a["status"] != "VOID"]
        pool.sort(key=lambda a: (a["created_at"], a["_seq"]))
    else:
        pool = [a for a in rows if a["status"] == "APPROVED"]
        pool.sort(key=lambda a: (a["approved_at"], a["created_at"], a["_seq"]))
    return rows, pool


def settle_plan(seat, season, agreement, extra=None):
    """Intended (applied, offset, payable) per non-void assignment of the seat."""
    rows, pool = _candidates(seat, season, extra)
    capacity = seat["episodic_guarantee_count"]
    winners = set(a["id"] for a in pool[:capacity])
    offset_pct = agreement["guarantee_offset_pct_by_level"][seat["level_at_hire"]]
    plan = {}
    for row in rows:
        if row["status"] == "VOID":
            continue
        applied = row["id"] in winners
        offset = calc.rhu(calc.D(row["gross_fee_cents"]) * calc.D(offset_pct)) if applied else 0
        plan[row["id"]] = (applied, offset, row["gross_fee_cents"] - offset)
    return plan


def recount_seat_guarantees(seat):
    consumed = 0
    for a in assignments_of_seat(seat["id"]):
        if a["status"] != "VOID" and a["guarantee_slot_applied"]:
            consumed += 1
    before = (seat["guarantee_slots_consumed"], seat["guarantee_slots_remaining"])
    seat["guarantee_slots_consumed"] = consumed
    seat["guarantee_slots_remaining"] = seat["episodic_guarantee_count"] - consumed
    if before != (seat["guarantee_slots_consumed"], seat["guarantee_slots_remaining"]):
        touch(seat)
        return True
    return False


def append_ledger(season_id, assignment, entry_type, amount_cents, memo):
    from db import append_row
    row = append_row()
    row.update({
        "season_id": season_id,
        "assignment_id": assignment["id"],
        "writer_id": assignment["writer_id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    })
    db.ledger[row["id"]] = row
    return row


def resettle_seat(seat, season, agreement):
    """Re-run settlement, writing GUARANTEE_REALLOCATION for every payable delta."""
    plan = settle_plan(seat, season, agreement)
    for assignment_id, (applied, offset, payable) in plan.items():
        row = db.assignments[assignment_id]
        if (row["guarantee_slot_applied"] == applied
                and row["guarantee_offset_cents"] == offset
                and row["payable_fee_cents"] == payable):
            continue
        delta = payable - row["payable_fee_cents"]
        row["guarantee_slot_applied"] = applied
        row["guarantee_offset_cents"] = offset
        row["payable_fee_cents"] = payable
        touch(row)
        if delta != 0:
            append_ledger(season["id"], row, "GUARANTEE_REALLOCATION", delta,
                          "guarantee reallocation on %s settlement" % row["assignment_type"])
    recompute_season_committed_fees(season)
    recount_seat_guarantees(seat)
    return plan


# ----------------------------------------------------------- readiness helpers
def rederive_readiness_on_loss(episode):
    """Used by CASCADE B: an episode whose live assignments left working states."""
    rows = assignments_of(episode["id"])
    before = episode["script_readiness"]
    if (before == "READY" and not episode.get("approved_teleplay_assignment_id")
            and any(a["status"] != "VOID" for a in rows)):
        episode["script_readiness"] = "IN_PROGRESS"
    elif before == "IN_PROGRESS" and rows and all(a["status"] == "VOID" for a in rows):
        episode["script_readiness"] = "NOT_STARTED"
    if episode["script_readiness"] != before:
        touch(episode)
        return True
    return False


# --------------------------------------------------------- CASCADE B: release
def release_seat(seat, room, season):
    """Seat-release chain. The room row is recomputed but not version-bumped here."""
    seat["status"] = "RELEASED"
    window_id = seat.get("consumed_window_id")
    if window_id:
        window = db.windows.get(window_id)
        if window is not None:
            window["status"] = "OPEN"
            window["consumed_by_seat_id"] = None
            touch(window)
    seat["consumed_window_id"] = None
    touch(seat)
    writer = db.writers.get(seat["writer_id"])
    if writer is not None and writer["active_seat_count"] > 0:
        writer["active_seat_count"] -= 1
    recompute_room(room)
    recompute_season_commitment(season)
    # the assignments held through this seat leave their working states
    touched_episodes = []
    for assignment in assignments_of_seat(seat["id"]):
        if assignment["status"] in ("DRAFTING", "DELIVERED", "IN_NOTES"):
            assignment["status"] = "REASSIGNMENT_PENDING"
            touch(assignment)
            episode = db.episodes.get(assignment["episode_id"])
            if episode is not None and episode not in touched_episodes:
                touched_episodes.append(episode)
    for episode in touched_episodes:
        rederive_readiness_on_loss(episode)
    recompute_coverage(season)
    return seat


# ----------------------------------------------------- CASCADE C: reconfigure
def reconfigure_room(room, new_format, new_duration, season):
    room["format"] = new_format
    room["duration_weeks_committed"] = new_duration
    for seat in seats_of(room["id"]):
        if seat["status"] != "CONFIRMED":
            continue
        before = (seat["guild_floor_weekly_cents"], seat["weekly_compensation_cents"],
                  seat["diversity_subsidy_weekly_cents"], seat["studio_charge_weekly_cents"],
                  seat["prorated_commitment_cents"])
        recompute_seat_money(seat, room)
        after = (seat["guild_floor_weekly_cents"], seat["weekly_compensation_cents"],
                 seat["diversity_subsidy_weekly_cents"], seat["studio_charge_weekly_cents"],
                 seat["prorated_commitment_cents"])
        if before != after:
            touch(seat)
    recompute_room(room)
    recompute_season_commitment(season)
    return room


# ---------------------------------------------------- CASCADE A: reschedule
def reschedule_season(season, new_start):
    delta = new_start - season["production_start_date"]
    season["production_start_date"] = new_start
    agreement = agreement_of(season)
    now = db.now()
    for episode in episodes_of(season["id"]):
        if episode["script_readiness"] == "LOCKED":
            continue
        episode["production_start_date"] = episode["production_start_date"] + delta
        touch(episode)
        for assignment in assignments_of(episode["id"]):
            if assignment["status"] == "VOID":
                continue
            set_assignment_due_dates(assignment, episode, agreement)
            for milestone in milestones_of(assignment["id"]):
                milestone["due_date"] = assignment[
                    calc.DUE_DATE_FIELD[milestone["milestone_type"]]]
                if milestone["status"] == "PENDING" and now > milestone["due_date"]:
                    milestone["status"] = "LATE"
                elif milestone["status"] == "LATE" and milestone["due_date"] >= now:
                    milestone["status"] = "PENDING"
                touch(milestone)
            recompute_late_milestone_count(assignment)
            touch(assignment)
    recompute_coverage(season)
    touch(season)
    return season


# ---------------------------------------------------------------- clearance
def recompute_review(review):
    assignment = db.assignments[review["assignment_id"]]
    episode = db.episodes[assignment["episode_id"]]
    season = db.seasons[episode["season_id"]]
    agreement = agreement_of(season)
    posture = calc.clearance_posture(review, items_of(review["id"]), agreement)
    review["posture"] = posture
    return posture


def mirror_clearance(review, posture):
    """Only the review over the episode's approved teleplay moves the episode."""
    assignment = db.assignments[review["assignment_id"]]
    episode = db.episodes[assignment["episode_id"]]
    if episode.get("approved_teleplay_assignment_id") != assignment["id"]:
        return False
    if episode["clearance_posture"] == posture:
        return False
    episode["clearance_posture"] = posture
    touch(episode)
    return True


# ------------------------------------------------------------------- credits
def submission_order_key(episode_id):
    """writer_id -> submission ordering key, used for every credit tie-break."""
    keys = {}
    for sub in submissions_of(episode_id):
        keys.setdefault(sub["writer_id"], (sub["created_at"], sub["_seq"]))
    return keys


def eligible_submissions(episode_id):
    return [s for s in submissions_of(episode_id) if s["status"] == "ELIGIBLE"]


def writer_has_approved_assignment(episode_id, writer_id):
    for a in assignments_of(episode_id):
        if a["writer_id"] == writer_id and a["status"] == "APPROVED":
            return True
    return False


def recompute_panel(arbitration, agreement):
    participants = list(arbitration["participant_writer_ids"])
    ballots = list(arbitration["vote_ledger"].values())
    count = arbitration["votes_cast_count"]
    if count == 0 or not participants:
        arbitration["leading_writer_id"] = None
        arbitration["concurrence_pct"] = 0
        return
    keys = submission_order_key(arbitration["episode_id"])
    means = {}
    for writer_id in participants:
        total = sum(calc.D(b.get(writer_id, 0)) for b in ballots)
        means[writer_id] = total / calc.D(count)
    ranked = sorted(participants,
                    key=lambda w: (-means[w], keys.get(w, (0, 0))))
    leading = ranked[0]
    band = calc.D(agreement["arbitration_concurrence_band_pct"])
    concurring = 0
    for ballot in ballots:
        if abs(calc.D(ballot.get(leading, 0)) - means[leading]) <= band:
            concurring += 1
    arbitration["leading_writer_id"] = leading
    arbitration["concurrence_pct"] = float(
        calc.rhu_places(calc.D(concurring) / calc.D(count), 3))
    arbitration["_panel_means"] = means
    return means


def panel_means(arbitration):
    participants = list(arbitration["participant_writer_ids"])
    ballots = list(arbitration["vote_ledger"].values())
    count = arbitration["votes_cast_count"]
    means = {}
    for writer_id in participants:
        total = sum(calc.D(b.get(writer_id, 0)) for b in ballots)
        means[writer_id] = total / calc.D(count) if count else calc.D(0)
    return means


def credit_string(subs, shares):
    """legal_names of credited writers joined by ' & ', descending final share."""
    rows = []
    for sub in subs:
        if not sub["receives_credit"]:
            continue
        share = shares.get(sub["writer_id"], 0)
        rows.append((-share, sub["created_at"], sub["_seq"], sub["writer_id"]))
    rows.sort()
    names = []
    for _, _, _, writer_id in rows:
        writer = db.writers.get(writer_id)
        if writer is not None:
            names.append(writer["legal_name"])
    return " & ".join(names) if names else None
