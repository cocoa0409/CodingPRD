"""State machines and cascades (PRD 2.9, 3.1-3.9).

Cascades are immediate and complete: every consequence lands inside the request
that triggered it, and each mutated record independently advances its own
version and updated_at.
"""

from decimal import Decimal

from db import clock, db, ordered, plus_days, plus_hours, touch
from services import calc


# ---------------------------------------------------------------------------
# Volunteer
# ---------------------------------------------------------------------------

def recompute_seniority(volunteer):
    """PRD 3.2: the stored score is refreshed on exactly five triggers — a status
    change, a certification reaching PASSED/EXPIRED/REVOKED, a strike_count
    change, and a hosted show having its performance_score rewritten."""
    if volunteer is None:
        return
    fresh = calc.seniority_score(volunteer)
    if volunteer.get("seniority_score") != fresh:
        volunteer["seniority_score"] = fresh
        touch(volunteer)


def set_volunteer_status(volunteer, new_status):
    if volunteer["status"] == new_status:
        return False
    volunteer["status"] = new_status
    touch(volunteer)
    recompute_seniority(volunteer)
    return True


def strip_operator_from_scheduled_episodes(volunteer_id):
    """An uncertified pair of hands never stays on the board."""
    for episode in db.episodes.values():
        if episode["air_status"] == "SCHEDULED" and episode["board_operator_volunteer_id"] == volunteer_id:
            episode["board_operator_volunteer_id"] = None
            episode["needs_substitute"] = True
            touch(episode)


def try_promote_to_certified(volunteer):
    """IN_TRAINING -> CERTIFIED, or PROBATION -> CERTIFIED once the core set is live."""
    if volunteer["status"] not in ("IN_TRAINING", "PROBATION"):
        return
    if not calc.core_set_complete(volunteer["id"]):
        return
    if volunteer["status"] == "PROBATION" and volunteer.get("strike_count", 0) >= 2:
        return
    set_volunteer_status(volunteer, "CERTIFIED")


def add_strike(volunteer):
    volunteer["strike_count"] = volunteer.get("strike_count", 0) + 1
    touch(volunteer)
    if volunteer["strike_count"] >= 2 and volunteer["status"] == "CERTIFIED":
        set_volunteer_status(volunteer, "PROBATION")
    recompute_seniority(volunteer)


def suspend_volunteer(volunteer):
    """CERTIFIED/PROBATION -> SUSPENDED plus the four-link programming cascade."""
    if volunteer["status"] in ("CERTIFIED", "PROBATION"):
        set_volunteer_status(volunteer, "SUSPENDED")
    for program in db.programs.values():
        if program["host_volunteer_id"] != volunteer["id"]:
            continue
        if program["programming_status"] not in ("SCHEDULED", "ON_AIR_ACTIVE"):
            continue
        # performance_score is deliberately NOT recomputed on this path.
        program["programming_status"] = "UNDER_REVIEW"
        touch(program)
        for episode in db.episodes.values():
            if (
                episode["program_id"] == program["id"]
                and episode["air_status"] == "SCHEDULED"
                and episode["board_operator_volunteer_id"] == volunteer["id"]
            ):
                episode["board_operator_volunteer_id"] = None
                episode["needs_substitute"] = True
                touch(episode)


def terminate_volunteer(volunteer):
    if volunteer["status"] in ("CERTIFIED", "PROBATION", "SUSPENDED"):
        set_volunteer_status(volunteer, "RESIGNED")
    for program in db.programs.values():
        if program["host_volunteer_id"] != volunteer["id"]:
            continue
        if program["programming_status"] == "CANCELLED":
            continue
        program["programming_status"] = "CANCELLED"
        program["cancellation_reason"] = "HOST_TERMINATED"
        touch(program)
        release_program_slots(program)


def apply_sanction(incident, respondent):
    sanction = incident.get("sanction") or "NONE"
    if respondent is None or sanction == "NONE":
        return
    if sanction == "WARNING":
        # A warning demotes only when it is the strike that reaches two.
        add_strike(respondent)
    elif sanction == "SUSPENSION":
        suspend_volunteer(respondent)
    elif sanction == "TERMINATION":
        terminate_volunteer(respondent)


# ---------------------------------------------------------------------------
# Program compliance dimension
# ---------------------------------------------------------------------------

def program_standing(program):
    return calc.standing_for_points(calc.program_penalty_points(program["id"]))


def restricted_cascade(program):
    """Everything a RESTRICTED standing takes off the air."""
    for slot in db.slots.values():
        if slot["program_id"] != program["id"]:
            continue
        if slot["status"] not in calc.LIVE_SLOT_STATUSES:
            continue
        slot["status"] = "PREEMPTED"
        slot["preempted_by_program_id"] = None
        touch(slot)
        grid = db.grids.get(slot["grid_id"])
        if grid is not None:
            touch(grid)
    for episode in db.episodes.values():
        if episode["program_id"] == program["id"] and episode["air_status"] == "SCHEDULED":
            episode["air_status"] = "CANCELLED"
            touch(episode)


def resettle_standing(program, standing_before):
    """Charge or refund has already landed; react to the new standing."""
    touch(program)
    standing_after = program_standing(program)
    if standing_after == "RESTRICTED" and standing_before != "RESTRICTED":
        restricted_cascade(program)
    return standing_after


# ---------------------------------------------------------------------------
# Slots and grids
# ---------------------------------------------------------------------------

def program_live_slot_count(program_id):
    count = 0
    for slot in db.slots.values():
        if slot["program_id"] != program_id or slot["status"] not in calc.LIVE_SLOT_STATUSES:
            continue
        grid = db.grids.get(slot["grid_id"])
        if grid is not None and grid["status"] == "SUPERSEDED":
            continue
        count += 1
    return count


def revert_to_unscheduled_if_idle(program):
    if program is None:
        return
    if program["programming_status"] in ("CANCELLED", "APPROVED_UNSCHEDULED"):
        return
    if program_live_slot_count(program["id"]) == 0:
        program["programming_status"] = "APPROVED_UNSCHEDULED"
        touch(program)


def release_slot(slot, reason, revert_program=True):
    slot["status"] = "RELEASED"
    slot["release_reason"] = reason
    touch(slot)
    grid = db.grids.get(slot["grid_id"])
    if grid is not None:
        touch(grid)
    if revert_program:
        revert_to_unscheduled_if_idle(db.programs.get(slot["program_id"]))


def release_program_slots(program, reason="PROGRAM_CANCELLED"):
    for slot in db.slots.values():
        if slot["program_id"] == program["id"] and slot["status"] in calc.LIVE_SLOT_STATUSES:
            release_slot(slot, reason, revert_program=False)


def cancel_program(program, reason):
    program["programming_status"] = "CANCELLED"
    program["cancellation_reason"] = reason
    touch(program)
    release_program_slots(program)
    for episode in db.episodes.values():
        if episode["program_id"] == program["id"] and episode["air_status"] == "SCHEDULED":
            episode["air_status"] = "CANCELLED"
            touch(episode)


def publish_grid(grid):
    grid["status"] = "PUBLISHED"
    grid["published_at"] = clock.now
    touch(grid)

    # 1. Shows holding a confirmed occupation on this grid take the air.
    for slot in db.slots.values():
        if slot["grid_id"] != grid["id"] or slot["status"] != "CONFIRMED":
            continue
        program = db.programs.get(slot["program_id"])
        if program is not None and program["programming_status"] == "SCHEDULED":
            program["programming_status"] = "ON_AIR_ACTIVE"
            touch(program)

    # 2. Any other published grid is superseded and its confirmations released.
    for other in list(db.grids.values()):
        if other["id"] == grid["id"] or other["status"] != "PUBLISHED":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)
        for slot in db.slots.values():
            if slot["grid_id"] == other["id"] and slot["status"] == "CONFIRMED":
                release_slot(slot, "GRID_SUPERSEDED", revert_program=False)

    # 3. Whoever is left with no live occupation drops back to unscheduled.
    for program in list(db.programs.values()):
        revert_to_unscheduled_if_idle(program)


# ---------------------------------------------------------------------------
# Episodes / logs
# ---------------------------------------------------------------------------

def open_music_log(episode, program):
    if program is not None and program["format_code"] == "MUSIC":
        episode["log_status"] = "PENDING"
        episode["log_due_at"] = plus_hours(episode["scheduled_start_utc"], 72)


def operator_is_live(volunteer_id):
    volunteer = db.volunteers.get(volunteer_id) if volunteer_id else None
    if volunteer is None:
        return False
    if volunteer["status"] in ("SUSPENDED", "RESIGNED"):
        return False
    return calc.holds_live_cert(volunteer_id, "BOARD_OPERATION")


# ---------------------------------------------------------------------------
# Premiums / pledges
# ---------------------------------------------------------------------------

def run_premium_waterfall(amount_cents, wants_premium):
    """Returns (premium_item_id, premium_status, tax_deductible_cents)."""
    if not wants_premium:
        return None, "WAIVED", amount_cents
    candidates = [i for i in db.premiums.values() if i["tier_threshold_cents"] <= amount_cents]
    if not candidates:
        return None, "NOT_ELIGIBLE", amount_cents
    candidates.sort(key=lambda i: (-i["tier_threshold_cents"], i["fair_market_value_cents"], i["sku"]))
    selected = None
    status = None
    for candidate in candidates:
        if calc.premium_available(candidate) >= 1:
            selected = candidate
            status = "RESERVED"
            break
    if selected is None:
        selected = candidates[0]
        status = "BACKORDERED"
    if status == "RESERVED":
        selected["reserved_qty"] += 1
        touch(selected)
    deductible = max(0, amount_cents - selected["fair_market_value_cents"])
    return selected["id"], status, deductible


def release_reserved_premium(pledge):
    if pledge["premium_status"] != "RESERVED":
        return
    item = db.premiums.get(pledge["premium_item_id"])
    if item is not None:
        item["reserved_qty"] = max(0, item["reserved_qty"] - 1)
        touch(item)
    pledge["premium_status"] = "RELEASED"


def return_shipped_premium(pledge):
    if pledge["premium_status"] != "SHIPPED":
        return
    item = db.premiums.get(pledge["premium_item_id"])
    if item is not None:
        item["shipped_qty"] = max(0, item["shipped_qty"] - 1)
        item["on_hand_qty"] += 1
        touch(item)
    pledge["premium_status"] = "RETURNED"


# ---------------------------------------------------------------------------
# Daily sweep (PRD 3.10)
# ---------------------------------------------------------------------------

def daily_sweep():
    expired_certification_ids = []
    delinquent_episode_ids = []
    missing_public_file_spot_ids = []
    created_incident_ids = []
    reviewed_program_ids = []

    # 1. Certification lapses.
    for cert in ordered(db.certifications):
        if cert["status"] != "PASSED":
            continue
        if cert["expires_on"] is None or clock.now < cert["expires_on"]:
            continue
        cert["status"] = "EXPIRED"
        touch(cert)
        expired_certification_ids.append(cert["id"])
        volunteer = db.volunteers.get(cert["volunteer_id"])
        if volunteer is not None:
            if cert["cert_type"] in calc.CORE_CERT_TYPES and volunteer["status"] == "CERTIFIED":
                set_volunteer_status(volunteer, "PROBATION")
            recompute_seniority(volunteer)
            strip_operator_from_scheduled_episodes(volunteer["id"])

    # 2. Delinquent music logs.
    for episode in ordered(db.episodes):
        if episode["log_status"] != "PENDING":
            continue
        if episode["log_due_at"] is None or clock.now < episode["log_due_at"]:
            continue
        episode["log_status"] = "DELINQUENT"
        touch(episode)
        delinquent_episode_ids.append(episode["id"])

    # 3. Missing public file postings, each of which opens a substantiated
    #    PUBLIC_FILE incident worth three points.
    from services.records import create_incident_row  # local import: avoids a cycle
    for spot in ordered(db.spots):
        if spot["public_file_status"] != "REQUIRED":
            continue
        if spot["public_file_due_at"] is None or clock.now < spot["public_file_due_at"]:
            continue
        spot["public_file_status"] = "MISSING"
        touch(spot)
        missing_public_file_spot_ids.append(spot["id"])
        program = db.programs.get(spot.get("assigned_program_id"))
        standing_before = program_standing(program) if program is not None else None
        incident = create_incident_row(
            category="PUBLIC_FILE",
            severity="MAJOR",
            program_id=spot.get("assigned_program_id"),
            episode_id=None,
            underwriting_spot_id=spot["id"],
            respondent_volunteer_id=None,
            complainant_note="Public file posting deadline elapsed without a filing.",
            occurred_at=spot["public_file_due_at"],
            sanction="NONE",
            status="SUBSTANTIATED",
            safe_harbor=False,
            points=3,
        )
        created_incident_ids.append(incident["id"])
        if program is not None:
            resettle_standing(program, standing_before)

    # 4. Re-evaluate every show currently on the air.
    for program in ordered(db.programs):
        if program["programming_status"] != "ON_AIR_ACTIVE":
            continue
        score = calc.performance_score(program, "TRAILING_SIX")
        program["performance_score"] = score
        program["performance_score_method"] = "TRAILING_SIX"
        program["last_evaluated_at"] = clock.now
        touch(program)
        recompute_seniority(db.volunteers.get(program["host_volunteer_id"]))
        reviewed_program_ids.append(program["id"])
        # The sweep may send a show down for review; it never promotes and never
        # sends anybody to PROBATION.
        if score < Decimal("60.00"):
            program["programming_status"] = "UNDER_REVIEW"

    return {
        "expired_certification_ids": expired_certification_ids,
        "delinquent_episode_ids": delinquent_episode_ids,
        "missing_public_file_spot_ids": missing_public_file_spot_ids,
        "created_incident_ids": created_incident_ids,
        "reviewed_program_ids": reviewed_program_ids,
    }
