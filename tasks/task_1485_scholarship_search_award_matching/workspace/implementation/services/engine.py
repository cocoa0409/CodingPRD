"""Derived-field reconciliation and cascades (PRD §2.9, §3.6-§3.9)."""

from datetime import timedelta

import clock
import db
from services import calc


# ---------------------------------------------------------------------------
# FK traversal helpers
# ---------------------------------------------------------------------------

def program_of_award(award):
    app = db.get("applications", award["application_id"])
    return db.get("programs", app["program_id"]) if app else None


def program_of_application(app):
    return db.get("programs", app["program_id"]) if app else None


def donor_of_program(program):
    return db.get("donors", program["donor_id"]) if program else None


def award_of_disbursement(disb):
    return db.get("awards", disb["award_id"])


def awards_of_student(student_id):
    return [a for a in db.all_records("awards") if a["student_id"] == student_id]


def disbursements_of_award(award_id):
    return [d for d in db.all_records("disbursements") if d["award_id"] == award_id]


def awards_of_fund(fund_id):
    out = []
    for a in db.all_records("awards"):
        app = db.get("applications", a["application_id"])
        if not app:
            continue
        prog = db.get("programs", app["program_id"])
        if prog and prog["fund_id"] == fund_id:
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# Fund / student aggregates (PRD §2.9, §3.1)
# ---------------------------------------------------------------------------

def net_confirmed(award_id):
    """sum(ever-CONFIRMED amounts) - sum(amounts marked RETURNED from CONFIRMED)."""
    total = 0
    for d in disbursements_of_award(award_id):
        if d.get("_ever_confirmed"):
            total += d["amount_cents"]
        if d.get("_returned_from_confirmed"):
            total -= d["amount_cents"]
    return total


def recompute_fund(fund, committed_override=None):
    awards = awards_of_fund(fund["id"])
    reserved = 0
    disbursed = 0
    returned = 0
    for a in awards:
        if a["offer_status"] in ("OFFERED", "ACCEPTED"):
            reserved += max(0, a["amount_cents"] - net_confirmed(a["id"]))
        for d in disbursements_of_award(a["id"]):
            if d.get("_ever_confirmed"):
                disbursed += d["amount_cents"]
            if d.get("_returned_from_confirmed"):
                returned += d["amount_cents"]
    committed = fund["committed_cents"] if committed_override is None else committed_override
    available = committed - reserved - disbursed + returned
    fields = {"reserved_cents": reserved, "disbursed_cents": disbursed,
              "returned_cents": returned, "available_cents": available}
    if committed_override is not None:
        fields["committed_cents"] = committed_override
    db.mutate(fund, **fields)


def recompute_student(student):
    awards = awards_of_student(student["id"])
    total_accepted = sum(a["amount_cents"] for a in awards if a["offer_status"] == "ACCEPTED")
    total_disbursed = sum(net_confirmed(a["id"]) for a in awards)
    aid_cap = student["cost_of_attendance_cents"] - student["efc_cents"]
    excess = max(0, total_accepted - aid_cap)
    db.mutate(student, total_accepted_cents=total_accepted,
              total_disbursed_cents=total_disbursed, aid_cap_cents=aid_cap,
              excess_cents=excess)


# ---------------------------------------------------------------------------
# Stacking cap + over-award recovery (PRD §3.6)
# ---------------------------------------------------------------------------

def stacking_recompute(student, trigger_program=None):
    """Recompute totals/excess and run the single-pass over-award recovery order."""
    recompute_student(student)
    accepted = [a for a in awards_of_student(student["id"]) if a["offer_status"] == "ACCEPTED"]
    if not accepted:
        return
    if trigger_program is not None:
        scope = trigger_program["stacking_scope"]
    else:
        # No single triggering program (student COA/EFC change): most restrictive scope wins.
        scopes = set()
        for a in accepted:
            p = program_of_award(a)
            if p:
                scopes.add(p["stacking_scope"])
        scope = "PER_TERM" if "PER_TERM" in scopes else "ANNUAL"
    cap = calc.stacking_cap_cents(student, scope)
    total = sum(a["amount_cents"] for a in accepted)
    excess = max(0, total - cap)
    if excess <= 0:
        return
    # Newest accepted first: accepted_at DESC, created_at DESC (seq DESC final tie-break).
    ordered = sorted(accepted,
                     key=lambda a: (a["accepted_at"] or "", a["created_at"], a["_seq"]),
                     reverse=True)
    remaining = excess
    for a in ordered:
        if remaining <= 0:
            break
        headroom = a["amount_cents"] - net_confirmed(a["id"])
        reduction = min(remaining, headroom)
        if reduction > 0:
            db.create_record("adjustments", {
                "award_id": a["id"],
                "reason": "OVER_AWARD",
                "delta_cents": -reduction,
                "status": "PENDING_APPROVAL",
                "auto_generated": True,
                "created_by_user_id": None,
                "approved_by_user_id": None,
            })
            remaining -= reduction


# ---------------------------------------------------------------------------
# Award funding dimension recompute + Cascade A (PRD §3.7)
# ---------------------------------------------------------------------------

def recompute_funding_status(award):
    """Recompute funding_status while offer_status == ACCEPTED.

    Returns True when the award has just transitioned INTO FULLY_DISBURSED.
    """
    if award["offer_status"] != "ACCEPTED":
        return False
    net = net_confirmed(award["id"])
    amount = award["amount_cents"]
    if net <= 0:
        target = "ENCUMBERED"
    elif net < amount:
        target = "DISBURSING"
    elif net == amount:
        target = "FULLY_DISBURSED"
    else:
        target = "OVER_DISBURSED"
    was_full = award["funding_status"] == "FULLY_DISBURSED"
    if award["funding_status"] != target:
        db.mutate(award, funding_status=target)
    return target == "FULLY_DISBURSED" and not was_full


def letter_for_award(award_id):
    for t in db.all_records("thank_you_letters"):
        if t["award_id"] == award_id:
            return t
    return None


def stale_reports_for_donor(donor_id):
    for r in db.all_records("donor_reports"):
        if r["donor_id"] == donor_id and r["status"] == "GENERATED":
            db.mutate(r, status="DRAFT")


def stale_reports_covered_by_letter(letter):
    """Deliver/waive staleness: GENERATED reports covering the letter's award."""
    award = db.get("awards", letter["award_id"])
    if not award:
        return
    program = program_of_award(award)
    if not program:
        return
    for r in db.all_records("donor_reports"):
        if r["donor_id"] != program["donor_id"] or r["status"] != "GENERATED":
            continue
        if report_covers_award(r, award):
            db.mutate(r, status="DRAFT")


def report_covers_award(report, award):
    """Award has >= 1 CONFIRMED disbursement with confirmed date in the half-open window."""
    for d in disbursements_of_award(award["id"]):
        if d["status"] == "CONFIRMED" and d.get("confirmed_at"):
            cdate = clock.parse_iso(d["confirmed_at"]).date().isoformat()
            if report["period_start"] <= cdate < report["period_end"]:
                return True
    return False


def on_full_disbursement(award):
    """Cascade A links 2-3: auto-create ThankYouLetter; stale donor reports."""
    if letter_for_award(award["id"]) is not None:
        return  # re-reaching FULLY_DISBURSED never duplicates the letter
    program = program_of_award(award)
    donor = donor_of_program(program)
    anonymous = bool(donor and donor.get("anonymous"))
    db.create_record("thank_you_letters", {
        "award_id": award["id"],
        "status": "WAIVED" if anonymous else "REQUIRED",
        "content_ref": None,
        "auto_created": True,
        "due_at": clock.iso3(clock.days_from_now(30)),
    })
    # A thank-you letter for that donor was created -> GENERATED reports go stale.
    if donor:
        stale_reports_for_donor(donor["id"])


def on_disbursement_confirmed(disb):
    """Cascade A link 1 (fund/student/award recompute) + report staleness."""
    award = award_of_disbursement(disb)
    program = program_of_award(award)
    fund = db.get("award_funds", program["fund_id"])
    student = db.get("students", award["student_id"])
    recompute_fund(fund)
    recompute_student(student)
    became_full = recompute_funding_status(award)
    if became_full:
        on_full_disbursement(award)
    else:
        # A covered disbursement was newly confirmed -> covered GENERATED reports stale.
        donor = donor_of_program(program)
        if donor:
            cdate = clock.parse_iso(disb["confirmed_at"]).date().isoformat()
            for r in db.all_records("donor_reports"):
                if (r["donor_id"] == donor["id"] and r["status"] == "GENERATED"
                        and r["period_start"] <= cdate < r["period_end"]):
                    db.mutate(r, status="DRAFT")


def on_disbursement_returned(disb, from_confirmed):
    """Clawback recompute after SENT/CONFIRMED -> RETURNED."""
    award = award_of_disbursement(disb)
    program = program_of_award(award)
    fund = db.get("award_funds", program["fund_id"])
    student = db.get("students", award["student_id"])
    recompute_fund(fund)
    recompute_student(student)
    recompute_funding_status(award)


# ---------------------------------------------------------------------------
# Waitlist promotion (PRD §3.6)
# ---------------------------------------------------------------------------

def waitlist_promotion(award):
    """Fire the selector on the cycle the award's application was SELECTED from."""
    app = db.get("applications", award["application_id"])
    if not app:
        return
    cycle_id = app.get("_cycle_id")
    if not cycle_id:
        return
    cycle = db.get("review_cycles", cycle_id)
    if not cycle or cycle["status"] != "FINALIZED":
        return
    pool = [a for a in db.all_records("applications")
            if a.get("_cycle_id") == cycle_id and a["status"] == "WAITLISTED"]
    if not pool:
        return
    pool.sort(key=lambda a: (a.get("decision_rank") or 10 ** 9,
                             a.get("submitted_at") or "",
                             a["created_at"], a["_seq"]))
    winner = pool[0]
    db.mutate(winner, status="SELECTED")


# ---------------------------------------------------------------------------
# Reminders (PRD §3.3)
# ---------------------------------------------------------------------------

_OFFSETS = [("D14", 14), ("D7", 7), ("D1", 1)]


def schedule_reminders(app, program):
    close_dt = clock.parse_iso(program["application_close_at"])
    for code, days in _OFFSETS:
        send_at = close_dt - timedelta(days=days)
        if send_at < clock.now():
            continue  # past offsets are never scheduled
        db.create_record("reminders", {
            "application_id": app["id"],
            "offset_code": code,
            "send_at": clock.iso3(send_at),
            "status": "SCHEDULED",
            "sent_at": None,
        })


def suppress_reminders(app_id):
    for r in db.all_records("reminders"):
        if r["application_id"] == app_id and r["status"] == "SCHEDULED":
            db.mutate(r, status="SUPPRESSED")


# ---------------------------------------------------------------------------
# Donor report aggregation (PRD §3.9)
# ---------------------------------------------------------------------------

def donor_report_aggregates(report):
    included = []
    total_disbursed = 0
    for a in db.all_records("awards"):
        app = db.get("applications", a["application_id"])
        if not app:
            continue
        prog = db.get("programs", app["program_id"])
        if not prog or prog["donor_id"] != report["donor_id"]:
            continue
        in_window = 0
        has_confirmed_in_window = False
        for d in disbursements_of_award(a["id"]):
            if d["status"] == "CONFIRMED" and d.get("confirmed_at"):
                cdate = clock.parse_iso(d["confirmed_at"]).date().isoformat()
                if report["period_start"] <= cdate < report["period_end"]:
                    has_confirmed_in_window = True
                    in_window += d["amount_cents"]
        if has_confirmed_in_window:
            included.append(a)
            total_disbursed += in_window
    complete = True
    for a in included:
        letter = letter_for_award(a["id"])
        if letter is None or letter["status"] not in ("DELIVERED", "WAIVED"):
            complete = False
            break
    return len(included), total_disbursed, complete
