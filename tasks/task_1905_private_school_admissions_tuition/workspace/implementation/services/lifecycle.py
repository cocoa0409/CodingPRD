"""State-machine cascades, decision sweep, and ops run-sweep (scaffold §1.2)."""

import db
from services import serializers as ser
from services.calculations import (compute_composite, compute_deposit,
                                   estimated_deposit_for_application, rank_key)

OFFER_EXPIRY_DAYS = 21
PROMOTED_OFFER_EXPIRY_DAYS = 7
CONTRACT_RESPONSE_DAYS = 14


def touch(rec) -> None:
    rec["updated_at"] = db.fmt_ts(db.wall_now())
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Award release cascade (§3.4)
# ---------------------------------------------------------------------------

def release_aid(application) -> None:
    aid = ser.find_aid_for_application(application["id"])
    if aid is None or aid["award_status"] == "RELEASED":
        return
    aid["award_status"] = "RELEASED"
    touch(aid)


# ---------------------------------------------------------------------------
# Offer placement (round close admit / waitlist promotion)
# ---------------------------------------------------------------------------

def place_offer(application, promoted: bool) -> None:
    clock = db.get_clock()
    days = PROMOTED_OFFER_EXPIRY_DAYS if promoted else OFFER_EXPIRY_DAYS
    application["status"] = "OFFERED"
    application["offer_expires_at"] = db.fmt_clock(db.days_later(clock, days))
    application["promoted_from_waitlist"] = promoted
    application["estimated_deposit_cents"] = estimated_deposit_for_application(application)
    touch(application)


# ---------------------------------------------------------------------------
# Decision sweep on round close (§3.5, committee_rank_assignment)
# ---------------------------------------------------------------------------

def run_decision_sweep(cycle, round_name: str) -> None:
    clock = db.get_clock()
    pool = [a for a in db.applications.values()
            if a["cycle_id"] == cycle["id"]
            and a["round"] == round_name
            and a["status"] == "EVALUATION_COMPLETE"]

    for section in db.grade_sections.values():
        if section["cycle_id"] != cycle["id"]:
            continue
        held, _aid_held = ser.seat_counts(section["id"])
        seats_open = section["capacity"] - held
        aid_cap = int(section["capacity"] * section["max_aid_seat_pct"])  # floor
        section_pool = sorted(
            (a for a in pool if a["grade_section_id"] == section["id"]),
            key=rank_key,
        )
        admitted = 0
        waitlisted = 0
        aid_seats_added = 0
        for app in section_pool:
            aid_seeking = ser.is_aid_seeking(app["id"])
            if admitted < seats_open and (not aid_seeking or aid_seats_added < aid_cap):
                place_offer(app, promoted=False)
                admitted += 1
                if aid_seeking:
                    aid_seats_added += 1
            elif waitlisted < section["capacity"]:
                app["status"] = "WAITLISTED"
                touch(app)
                waitlisted += 1
            else:
                app["status"] = "DENIED"
                touch(app)
    _ = clock


# ---------------------------------------------------------------------------
# Ops run-sweep (§3.5): expirations/lapses first, then waitlist promotion
# ---------------------------------------------------------------------------

def run_ops_sweep(cycle) -> dict:
    clock = db.get_clock()
    result = {
        "expired_offer_count": 0,
        "lapsed_contract_count": 0,
        "promoted_application_ids": [],
        "expired_waitlist_count": 0,
        "lapsed_reenrollment_count": 0,
    }

    # 1. Expire due offers (OFFERED -> EXPIRED with award release + seat free)
    for app in sorted(db.applications.values(), key=lambda a: a["_seq"]):
        if app["cycle_id"] != cycle["id"] or app["status"] != "OFFERED":
            continue
        exp = db.parse_iso(app["offer_expires_at"])
        if exp is not None and clock > exp:
            app["status"] = "EXPIRED"
            touch(app)
            release_aid(app)
            result["expired_offer_count"] += 1

    # 2. Lapse due contracts (ISSUED/SIGNED past response_due_at)
    for contract in sorted(db.contracts.values(), key=lambda c: c["_seq"]):
        app = db.applications.get(contract["application_id"])
        if app is None or app["cycle_id"] != cycle["id"]:
            continue
        if contract["status"] not in ("ISSUED", "SIGNED"):
            continue
        due = db.parse_iso(contract["response_due_at"])
        if due is not None and clock > due:
            contract["status"] = "LAPSED"
            touch(contract)
            app["status"] = "EXPIRED"
            touch(app)
            release_aid(app)
            result["lapsed_contract_count"] += 1

    # 3. Lapse due re-enrollment offers targeting this cycle
    for offer in sorted(db.reenrollment_offers.values(), key=lambda r: r["_seq"]):
        if offer["cycle_id"] != cycle["id"] or offer["status"] != "ISSUED":
            continue
        deadline = db.parse_iso(offer["response_deadline_at"])
        if deadline is not None and clock > deadline:
            offer["status"] = "LAPSED"
            touch(offer)
            result["lapsed_reenrollment_count"] += 1

    # 4. Past the melt deadline the waitlist expires instead of promoting
    melt = db.parse_iso(cycle["melt_deadline_at"])
    if melt is not None and clock > melt:
        for app in sorted(db.applications.values(), key=lambda a: a["_seq"]):
            if app["cycle_id"] == cycle["id"] and app["status"] == "WAITLISTED":
                app["status"] = "EXPIRED"
                touch(app)
                result["expired_waitlist_count"] += 1
        return result

    # 5. Waitlist promotion (only while EARLY_CLOSED / CLOSED and clock <= melt)
    if cycle["status"] in ("EARLY_CLOSED", "CLOSED"):
        for section in sorted(db.grade_sections.values(), key=lambda s: s["_seq"]):
            if section["cycle_id"] != cycle["id"]:
                continue
            while True:
                held, _ = ser.seat_counts(section["id"])
                if section["capacity"] - held <= 0:
                    break
                candidates = sorted(
                    (a for a in db.applications.values()
                     if a["grade_section_id"] == section["id"] and a["status"] == "WAITLISTED"),
                    key=rank_key,
                )
                if not candidates:
                    break
                chosen = candidates[0]
                place_offer(chosen, promoted=True)
                result["promoted_application_ids"].append(chosen["id"])

    return result


# ---------------------------------------------------------------------------
# Scoring completion (§3.3)
# ---------------------------------------------------------------------------

def maybe_complete_evaluation(application) -> None:
    """When both kinds are SCORED: compute composite and advance the application."""
    if application["status"] != "SUBMITTED":
        return
    kinds_scored = set()
    for e in db.evaluations.values():
        if e["application_id"] == application["id"] and e["status"] == "SCORED":
            kinds_scored.add(e["kind"])
    if "TEST" not in kinds_scored or "INTERVIEW" not in kinds_scored:
        return
    composite, preference, sibling = compute_composite(application)
    application["composite_score"] = composite
    application["preference_points"] = preference
    application["sibling_verified"] = sibling
    application["status"] = "EVALUATION_COMPLETE"
    touch(application)


# ---------------------------------------------------------------------------
# Enrollment cascade (§3.6)
# ---------------------------------------------------------------------------

def enroll_contract(contract) -> None:
    app = db.applications[contract["application_id"]]
    applicant = db.applicants[app["applicant_id"]]
    contract["status"] = "ENROLLED"
    now = db.fmt_ts(db.wall_now())
    student = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "family_id": applicant["family_id"],
        "first_name": applicant["first_name"],
        "last_name": applicant["last_name"],
        "current_grade_section_id": app["grade_section_id"],
        "status": "ACTIVE",
        "source": "ADMISSION",
        "re_enrolled_for_cycle_id": None,
    }
    db.students[student["id"]] = student
    contract["created_student_id"] = student["id"]
    touch(contract)
    app["status"] = "ENROLLED"
    touch(app)


# ---------------------------------------------------------------------------
# Withdraw cascade (§3.6)
# ---------------------------------------------------------------------------

def withdraw_application(app) -> None:
    status = app["status"]
    if status == "ENROLLED":
        # Summer melt
        app["status"] = "MELTED"
        touch(app)
        contract = ser.find_live_contract_for_application(app["id"])
        if contract is not None:
            contract["status"] = "MELTED"
            touch(contract)
            if contract["created_student_id"]:
                student = db.students.get(contract["created_student_id"])
                if student is not None:
                    student["status"] = "INACTIVE"
                    touch(student)
        release_aid(app)
        return

    app["status"] = "WITHDRAWN"
    touch(app)
    if status == "CONTRACT_ISSUED":
        contract = ser.find_live_contract_for_application(app["id"])
        if contract is not None and contract["status"] in ("ISSUED", "SIGNED"):
            contract["status"] = "CANCELLED"
            touch(contract)
        release_aid(app)
    elif status in ("SUBMITTED", "EVALUATION_COMPLETE", "WAITLISTED"):
        release_aid(app)


# ---------------------------------------------------------------------------
# Decline cascade (§3.6)
# ---------------------------------------------------------------------------

def decline_application(app) -> None:
    app["status"] = "DECLINED"
    touch(app)
    release_aid(app)
