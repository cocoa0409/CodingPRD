"""Business logic: calculations, cascades, and the season sweep (PRD section 3).

Constants and algorithms are pinned by SCAFFOLD 1.3 and the PRD narratives:
  - registration_fee_calculation: scholarship step first (round half-up), then
    family step (round half-up); result pinned forever in fee_charged_cents.
  - registration_refund: VOLUNTARY tiered by meetings held; NO_SHOW always 0;
    ADMIN_CANCELLATION always 100% of net_paid_cents.
  - waitlist_promotion_selector: waitlisted_at ASC, created_at ASC tie-break.
  - instructor_settlement_pay: per-line rounding first, then sum, then floor.
  - consecutive_absence_replay: PRESENT resets, ABSENT increments, EXCUSED
    neither; counter >= 3 on an ENROLLED registration fires the no-show drop.
  - room_overlap_check buffered by 15 minutes; instructor_overlap_check not.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import store
from errors import raise_err
from util import new_record, bump

REFUND_REVIEW_THRESHOLD_CENTS = 10000
NO_SHOW_ABSENCE_THRESHOLD = 3
ROOM_TURNOVER_BUFFER_MINUTES = 15
ATTENDANCE_QUALIFYING_PCT = 50
PROMOTED_PAYMENT_WINDOW_HOURS = 48
DIRECT_PAYMENT_WINDOW_HOURS = 72

NON_TERMINAL_SESSION_STATES = ("DRAFT", "PUBLISHED", "ACTIVE")
OPEN_SESSION_STATES = ("PUBLISHED", "ACTIVE")


def rhu(numer, denom):
    """Integer round-half-up of numer/denom (integer inputs, exact Decimal)."""
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def season_of_session(session):
    program = store.programs.get(session["program_id"])
    if program is None:
        return None
    return store.seasons.get(program["season_id"])


def meetings_of_session(session_id):
    return [m for m in store.meetings.values() if m["session_id"] == session_id]


def registrations_of_session(session_id):
    return [r for r in store.registrations.values() if r["session_id"] == session_id]


def age_years(birth, at):
    """Whole years completed between birth_date and `at`; a birthday falling
    exactly on `at` counts as reached (calendar-date comparison)."""
    return at.year - birth.year - ((at.month, at.day) < (birth.month, birth.day))


# ---------------------------------------------------------------------------
# scheduling conflict checks (PRD 2.9 / 3.2) — pinned order:
#   capacity -> availability -> room overlap (buffered) -> instructor overlap
# ---------------------------------------------------------------------------
def check_scheduling(session, room, starts_at, ends_at, exclude_meeting_id=None):
    if room["capacity"] < session["capacity"]:
        raise_err("ERR_ROOM_CAPACITY_INSUFFICIENT", "Room capacity is below the session capacity")
    if room["status"] != "ACTIVE":
        raise_err("ERR_ROOM_UNAVAILABLE", "Room is in MAINTENANCE")
    buffer = timedelta(minutes=ROOM_TURNOVER_BUFFER_MINUTES)
    new_occ_end = ends_at + buffer
    for other in store.meetings.values():
        if other["id"] == exclude_meeting_id or other["room_id"] != room["id"]:
            continue
        other_session = store.sessions.get(other["session_id"])
        if other_session is None or other_session["status"] not in NON_TERMINAL_SESSION_STATES:
            continue
        other_occ_end = other["ends_at"] + buffer
        if starts_at < other_occ_end and other["starts_at"] < new_occ_end:
            raise_err("ERR_ROOM_CONFLICT", "Room occupancy (with turnover buffer) overlaps another meeting")
    for other in store.meetings.values():
        if other["id"] == exclude_meeting_id:
            continue
        other_session = store.sessions.get(other["session_id"])
        if other_session is None or other_session["status"] not in NON_TERMINAL_SESSION_STATES:
            continue
        if other_session["instructor_id"] != session["instructor_id"]:
            continue
        if starts_at < other["ends_at"] and other["starts_at"] < ends_at:
            raise_err("ERR_INSTRUCTOR_DOUBLE_BOOKED", "Instructor has another meeting overlapping this interval")


# ---------------------------------------------------------------------------
# registration fee (PRD 3.6) — computed exactly once, then pinned
# ---------------------------------------------------------------------------
def approved_scholarship_pct(household_id, season_id):
    for app in store.applications.values():
        if (
            app["household_id"] == household_id
            and app["season_id"] == season_id
            and app["status"] == "APPROVED"
        ):
            return app["approved_pct"]
    return 0


def family_discount_evaluation(household_id, season, threshold):
    existing = 0
    for r in store.registrations.values():
        if r["household_id"] != household_id or r["enrollment_status"] != "ENROLLED":
            continue
        r_session = store.sessions.get(r["session_id"])
        if r_session is None:
            continue
        r_season = season_of_session(r_session)
        if r_season is not None and r_season["id"] == season["id"]:
            existing += 1
    return (existing + 1) >= threshold


def compute_registration_fee(session, season, household):
    is_resident = household["residency_status"] == "RESIDENT"
    base = session["fee_resident_cents"] if is_resident else session["fee_nonresident_cents"]
    sch_pct = approved_scholarship_pct(household["id"], season["id"])
    fam_applied = family_discount_evaluation(
        household["id"], season, season["family_discount_threshold"]
    )
    fam_pct = season["family_discount_pct"] if fam_applied else 0
    # Pinned evaluation order: scholarship step first (round), family second (round).
    intermediate = rhu(base * (100 - sch_pct), 100)
    fee = rhu(intermediate * (100 - fam_pct), 100)
    return {
        "residency_at_registration": "RESIDENT" if is_resident else "NONRESIDENT",
        "scholarship_pct_applied": sch_pct,
        "family_discount_applied": fam_applied,
        "fee_charged_cents": fee,
    }


def create_registration_record(session, participant, household):
    season = season_of_session(session)
    now = clock.now()
    fee_info = compute_registration_fee(session, season, household)
    reg = new_record()
    reg.update(
        session_id=session["id"],
        participant_id=participant["id"],
        household_id=participant["household_id"],
        residency_at_registration=fee_info["residency_at_registration"],
        scholarship_pct_applied=fee_info["scholarship_pct_applied"],
        family_discount_applied=fee_info["family_discount_applied"],
        fee_charged_cents=fee_info["fee_charged_cents"],
        net_paid_cents=0,
        refund_total_cents=0,
        enrollment_status=None,
        payment_status="PENDING",
        drop_reason=None,
        waitlisted_at=None,
        promoted_at=None,
        payment_due_at=None,
        consecutive_absences=0,
    )
    if session["enrolled_count"] >= session["capacity"]:
        reg["enrollment_status"] = "WAITLISTED"
        reg["waitlisted_at"] = now
        session["waitlist_count"] += 1
    else:
        reg["enrollment_status"] = "ENROLLED"
        if reg["fee_charged_cents"] > 0:
            reg["payment_status"] = "PENDING"
            reg["payment_due_at"] = now + timedelta(hours=DIRECT_PAYMENT_WINDOW_HOURS)
        else:
            reg["payment_status"] = "WAIVED"
            reg["payment_due_at"] = None
        session["enrolled_count"] += 1
    bump(session)
    store.registrations[reg["id"]] = reg
    return reg


# ---------------------------------------------------------------------------
# refunds (PRD 3.7 / 3.8)
# ---------------------------------------------------------------------------
def voluntary_refund_amount(session, reg, now):
    meetings = meetings_of_session(session["id"])
    meetings_total = len(meetings)
    meetings_held = sum(1 for m in meetings if m["starts_at"] <= now)
    if meetings_held == 0:
        return reg["net_paid_cents"]
    if meetings_held <= meetings_total // 2:
        return rhu(reg["net_paid_cents"], 2)
    return 0


def issue_refund(reg, amount):
    """Refund issuance sub-procedure.  Mutates the registration's payment axis
    (caller bumps the registration); creates the REFUND ledger entry; credits
    the household immediately when the refund is born COMPLETED."""
    pay = reg["payment_status"]
    if pay == "PENDING":
        # Never paid: the axis voids in every variant; no refund is possible.
        reg["payment_status"] = "VOID"
        return None
    if pay != "PAID" or amount <= 0:
        # WAIVED is left alone; a zero refund leaves PAID untouched.
        return None
    tx = new_record()
    tx.update(
        registration_id=reg["id"],
        type="REFUND",
        amount_cents=amount,
        method="ACCOUNT_CREDIT",
        status=None,
    )
    if amount >= REFUND_REVIEW_THRESHOLD_CENTS:
        tx["status"] = "PENDING"
        reg["payment_status"] = "REFUND_PENDING"
    else:
        tx["status"] = "COMPLETED"
        reg["payment_status"] = "REFUNDED"
        reg["refund_total_cents"] += amount
        household = store.households.get(reg["household_id"])
        if household is not None:
            household["account_credit_cents"] += amount
            bump(household)
    store.payments[tx["id"]] = tx
    return tx


# ---------------------------------------------------------------------------
# waitlist promotion (PRD 3.8): waitlisted_at ASC, created_at ASC; one per
# freed seat; promoted registration pays within 48h or is WAIVED at fee 0.
# ---------------------------------------------------------------------------
def promote_waitlist(session, now, promoted_ids=None):
    if session["status"] not in OPEN_SESSION_STATES:
        return None
    candidates = [
        r
        for r in store.registrations.values()
        if r["session_id"] == session["id"] and r["enrollment_status"] == "WAITLISTED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["waitlisted_at"] or r["created_at"], r["created_at"], r["_seq"]))
    reg = candidates[0]
    reg["enrollment_status"] = "ENROLLED"
    reg["promoted_at"] = now
    if reg["fee_charged_cents"] > 0:
        reg["payment_status"] = "PENDING"
        reg["payment_due_at"] = now + timedelta(hours=PROMOTED_PAYMENT_WINDOW_HOURS)
    else:
        reg["payment_status"] = "WAIVED"
        reg["payment_due_at"] = None
    bump(reg)
    session["waitlist_count"] -= 1
    session["enrolled_count"] += 1
    bump(session)
    if promoted_ids is not None:
        promoted_ids.append(reg["id"])
    return reg


# ---------------------------------------------------------------------------
# drops (PRD 3.8)
# ---------------------------------------------------------------------------
def drop_registration(reg):
    now = clock.now()
    session = store.sessions[reg["session_id"]]
    if reg["enrollment_status"] == "WAITLISTED":
        reg["enrollment_status"] = "DROPPED"
        reg["drop_reason"] = "VOLUNTARY"
        if reg["payment_status"] == "PENDING":
            reg["payment_status"] = "VOID"
        bump(reg)
        session["waitlist_count"] -= 1
        bump(session)
        return reg
    # ENROLLED: tiered voluntary refund, then promotion for the freed seat.
    refund = voluntary_refund_amount(session, reg, now)
    reg["enrollment_status"] = "DROPPED"
    reg["drop_reason"] = "VOLUNTARY"
    issue_refund(reg, refund)
    bump(reg)
    session["enrolled_count"] -= 1
    bump(session)
    promote_waitlist(session, now)
    return reg


def no_show_drop(reg, session, now):
    """ENROLLED -> DROPPED (NO_SHOW): refund is always zero — a forfeit."""
    reg["enrollment_status"] = "DROPPED"
    reg["drop_reason"] = "NO_SHOW"
    if reg["payment_status"] == "PENDING":
        reg["payment_status"] = "VOID"
    session["enrolled_count"] -= 1
    bump(session)
    promote_waitlist(session, now)


# ---------------------------------------------------------------------------
# session cancellation / completion cascades (PRD 3.9)
# ---------------------------------------------------------------------------
def cancel_session_cascade(session, reason):
    now = clock.now()
    session["status"] = "CANCELLED"
    session["cancellation_reason"] = reason
    regs = sorted(registrations_of_session(session["id"]), key=lambda r: r["_seq"])
    for reg in regs:
        if reg["enrollment_status"] != "ENROLLED":
            continue
        reg["enrollment_status"] = "CANCELLED"
        reg["drop_reason"] = reason
        issue_refund(reg, reg["net_paid_cents"])  # ADMIN_CANCELLATION: 100%
        bump(reg)
    for reg in regs:
        if reg["enrollment_status"] != "WAITLISTED":
            continue
        reg["enrollment_status"] = "CANCELLED"
        reg["drop_reason"] = reason
        if reg["payment_status"] == "PENDING":
            reg["payment_status"] = "VOID"
        bump(reg)
    session["enrolled_count"] = 0
    session["waitlist_count"] = 0
    for contract in store.contracts.values():
        if contract["session_id"] != session["id"]:
            continue
        if contract["status"] == "ACCEPTED":
            contract["status"] = "TERMINATED"
            contract["payout_cents"] = contract["cancellation_guarantee_cents"]
            bump(contract)
        elif contract["status"] == "OFFERED":
            contract["status"] = "VOID"
            contract["payout_cents"] = 0
            bump(contract)
    bump(session)


def _attendance_qualifies(reg, held_meeting_ids, meetings_held):
    if meetings_held == 0:
        return False  # attendance_pct is 0 when nothing held; 0 < 50
    present = 0
    for rec in store.attendance.values():
        if (
            rec["registration_id"] == reg["id"]
            and rec["status"] == "PRESENT"
            and rec["meeting_id"] in held_meeting_ids
        ):
            present += 1
    # 100 * present / meetings_held >= 50  <=>  2 * present >= meetings_held
    return 2 * present >= meetings_held


def complete_session_cascade(session):
    now = clock.now()
    for contract in store.contracts.values():
        if contract["session_id"] != session["id"]:
            continue
        if contract["status"] == "ACCEPTED":
            meetings = meetings_of_session(session["id"])
            held = [m for m in meetings if m["starts_at"] <= now]
            held_ids = {m["id"] for m in held}
            meetings_held = len(held)
            counted = []
            for reg in registrations_of_session(session["id"]):
                if reg["enrollment_status"] != "ENROLLED":
                    continue
                if contract["settlement_basis"] == "ENROLLMENT_BASIS":
                    counted.append(reg)
                elif _attendance_qualifies(reg, held_ids, meetings_held):
                    counted.append(reg)
            # Pinned rounding: round each per-registration line first, then sum.
            subtotal = sum(
                rhu(reg["net_paid_cents"] * contract["revenue_share_bp"], 10000)
                for reg in counted
            )
            contract["settlement_headcount"] = len(counted)
            contract["settlement_amount_cents"] = max(contract["guarantee_min_cents"], subtotal)
            contract["payout_cents"] = contract["settlement_amount_cents"]
            contract["status"] = "SETTLED"
            bump(contract)
        elif contract["status"] == "OFFERED":
            contract["status"] = "VOID"
            contract["payout_cents"] = 0
            bump(contract)
    for reg in registrations_of_session(session["id"]):
        if reg["enrollment_status"] != "WAITLISTED":
            continue
        reg["enrollment_status"] = "CANCELLED"
        reg["drop_reason"] = "ADMIN"
        if reg["payment_status"] == "PENDING":
            reg["payment_status"] = "VOID"
        bump(reg)
    session["waitlist_count"] = 0
    session["status"] = "COMPLETED"
    bump(session)


# ---------------------------------------------------------------------------
# attendance absence replay (PRD 3.9)
# ---------------------------------------------------------------------------
def replay_absences(reg):
    now = clock.now()
    rows = []
    for rec in store.attendance.values():
        if rec["registration_id"] != reg["id"]:
            continue
        meeting = store.meetings.get(rec["meeting_id"])
        if meeting is None or meeting["starts_at"] > now:
            continue
        rows.append((meeting["starts_at"], rec["created_at"], rec["_seq"], rec["status"]))
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    counter = 0
    for _, _, _, status in rows:
        if status == "PRESENT":
            counter = 0
        elif status == "ABSENT":
            counter += 1
        # EXCUSED neither increments nor resets
    changed = reg["consecutive_absences"] != counter
    reg["consecutive_absences"] = counter
    fired = False
    if reg["enrollment_status"] == "ENROLLED" and counter >= NO_SHOW_ABSENCE_THRESHOLD:
        session = store.sessions.get(reg["session_id"])
        if session is not None:
            no_show_drop(reg, session, now)
            fired = True
    if changed or fired:
        bump(reg)


# ---------------------------------------------------------------------------
# season sweep (PRD 3.9): step 1 payment timeouts, step 2 enrollment checks
# ---------------------------------------------------------------------------
def run_sweep(season):
    now = clock.now()
    activated_session_ids = []
    cancelled_session_ids = []
    expired_registration_ids = []
    promoted_registration_ids = []

    # Step 1: expire ENROLLED + PENDING registrations past their payment
    # deadline, payment_due_at ASC (created_at ASC tie-break); each expiry runs
    # the promotion selector for its session before the next expiry.
    expiries = []
    for reg in store.registrations.values():
        if reg["enrollment_status"] != "ENROLLED" or reg["payment_status"] != "PENDING":
            continue
        if reg["payment_due_at"] is None or reg["payment_due_at"] > now:
            continue
        session = store.sessions.get(reg["session_id"])
        if session is None:
            continue
        reg_season = season_of_session(session)
        if reg_season is None or reg_season["id"] != season["id"]:
            continue
        expiries.append(reg)
    expiries.sort(key=lambda r: (r["payment_due_at"], r["created_at"], r["_seq"]))
    for reg in expiries:
        if reg["enrollment_status"] != "ENROLLED" or reg["payment_status"] != "PENDING":
            continue
        reg["enrollment_status"] = "EXPIRED"
        reg["drop_reason"] = "PAYMENT_TIMEOUT"
        reg["payment_status"] = "VOID"
        bump(reg)
        expired_registration_ids.append(reg["id"])
        session = store.sessions[reg["session_id"]]
        session["enrolled_count"] -= 1
        bump(session)
        promote_waitlist(session, now, promoted_registration_ids)

    # Step 2: minimum-enrollment checks, only while the season is PUBLISHED.
    if season["status"] == "PUBLISHED":
        due_sessions = []
        for session in store.sessions.values():
            if session["status"] != "PUBLISHED":
                continue
            sess_season = season_of_session(session)
            if sess_season is None or sess_season["id"] != season["id"]:
                continue
            if session["enrollment_check_at"] <= now:
                due_sessions.append(session)
        due_sessions.sort(key=lambda s: (s["enrollment_check_at"], s["created_at"], s["_seq"]))
        for session in due_sessions:
            if session["status"] != "PUBLISHED":
                continue
            if session["enrolled_count"] >= session["min_enrollment"]:
                session["status"] = "ACTIVE"
                bump(session)
                activated_session_ids.append(session["id"])
            else:
                cancel_session_cascade(session, "LOW_ENROLLMENT")
                cancelled_session_ids.append(session["id"])

    return {
        "activated_session_ids": activated_session_ids,
        "cancelled_session_ids": cancelled_session_ids,
        "expired_registration_ids": expired_registration_ids,
        "promoted_registration_ids": promoted_registration_ids,
    }


# ---------------------------------------------------------------------------
# payments (PRD 3.7)
# ---------------------------------------------------------------------------
def pay_registration(reg, amount_cents, method):
    household = store.households.get(reg["household_id"])
    if method == "ACCOUNT_CREDIT":
        if household is None or household["account_credit_cents"] < amount_cents:
            raise_err("ERR_INSUFFICIENT_CREDIT", "Household account credit does not cover the amount")
    tx = new_record()
    tx.update(
        registration_id=reg["id"],
        type="CHARGE",
        amount_cents=amount_cents,
        method=method,
        status="COMPLETED",
    )
    store.payments[tx["id"]] = tx
    reg["payment_status"] = "PAID"
    reg["net_paid_cents"] += amount_cents
    reg["payment_due_at"] = None
    bump(reg)
    if method == "ACCOUNT_CREDIT":
        household["account_credit_cents"] -= amount_cents
        bump(household)
    return tx


def approve_refund(tx):
    reg = store.registrations.get(tx["registration_id"])
    household = store.households.get(reg["household_id"]) if reg is not None else None
    tx["status"] = "COMPLETED"
    bump(tx)
    if reg is not None:
        reg["refund_total_cents"] += tx["amount_cents"]
        if reg["payment_status"] == "REFUND_PENDING":
            reg["payment_status"] = "REFUNDED"
        bump(reg)
    if household is not None:
        household["account_credit_cents"] += tx["amount_cents"]
        bump(household)
    return tx
