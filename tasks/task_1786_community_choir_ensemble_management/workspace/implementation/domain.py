"""Business logic: derived fields, calculations, posture gates, cascades,
waitlist promotions, and the ops checkpoint (PRD section 3).

Money is integer cents; every fractional-cent calculation goes through
``rhu_cents`` (Decimal, ROUND_HALF_UP).  composite_score is 2dp half-up and
attendance_rate is 4dp half-up (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

import store
from errors import ApiError
from store import touch
from timeutil import clock, render_server, whole_days_between

# ----------------------------------------------------------------- constants
VOICE_PARTS = ("SOPRANO", "ALTO", "TENOR", "BASS")
POSTURES = ("DRAFT", "OPEN", "REHEARSING", "CONCERT_LOCK", "ARCHIVED")
PAYMENT_METHODS = ("CASH", "CHECK", "CARD")
ATTENDANCE_STATUSES = ("PRESENT", "LATE", "ABSENT_UNEXCUSED", "ABSENT_EXCUSED")
SERVICE_KINDS = ("REHEARSAL", "CONCERT", "MASTERCLASS")
MEMBER_STATUS_ACTIONS = ("DROP", "SUSPEND", "REINSTATE")
CONCERT_ACTIONS = ("LOCK_PROGRAM", "MARK_READY", "PERFORM", "CANCEL")
TOUR_ACTIONS = ("OPEN_REGISTRATION", "LOCK_ROSTER", "COMPLETE", "CANCEL")
COMMITTEE_ACTIONS = ("ACTIVATE", "DISSOLVE")
AUDITION_DECISIONS = ("ACCEPT", "WAITLIST", "REJECT")
GRANT_DECISIONS = ("APPROVE", "REJECT")
SECTION_STATUSES = ("OPEN", "CLOSED")

ACCEPT_THRESHOLD = Decimal("7.0")
OVERDUE_WEEKLY_FINE_CENTS = 200
PROGRAM_BUFFER_SECONDS = 900
SECTION_COUNT_STATUSES = ("ENROLLED", "ACTIVE", "PROBATION")
OPEN_INVOICE_STATUSES = ("ISSUED", "PARTIAL", "OVERDUE")
INVOICE_TERMINAL_STATUSES = ("PAID", "WAIVED")

_ATTENDANCE_WEIGHT = {
    "PRESENT": Decimal("1"),
    "LATE": Decimal("0.5"),
    "ABSENT_EXCUSED": Decimal("0.75"),
    "ABSENT_UNEXCUSED": Decimal("0"),
}


def rhu_cents(value):
    """Decimal -> integer cents, round half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# ------------------------------------------------------------ season helpers
def gate_season(season, allowed_postures):
    """PRD 2.9: ARCHIVED rejects every write (ERR_SEASON_TERMINAL); otherwise
    the posture must be in ``allowed_postures`` (None = no gate)."""
    if season["posture"] == "ARCHIVED":
        raise ApiError("ERR_SEASON_TERMINAL", "season is ARCHIVED")
    if allowed_postures is not None and season["posture"] not in allowed_postures:
        raise ApiError("ERR_SEASON_POSTURE", "season posture does not permit this write")


def season_of_member(member):
    return store.seasons[member["season_id"]]


def treasury_credit(season, amount):
    if amount:
        season["treasury_balance_cents"] += amount
        touch(season)


def treasury_debit(season, amount, check=True):
    if check and season["treasury_balance_cents"] < amount:
        raise ApiError("ERR_INSUFFICIENT_TREASURY", "treasury cannot cover the debit")
    if amount:
        season["treasury_balance_cents"] -= amount
        touch(season)


# ------------------------------------------------------------ invoice math
def dues_discounted(season):
    return rhu_cents(dec(season["base_dues_cents"]) * (Decimal("1") - dec(season["early_bird_pct"])))


def dues_provisional(season, issued_dt):
    if issued_dt <= season["_early_bird_cutoff_dt"]:
        return dues_discounted(season)
    return season["base_dues_cents"]


def dues_final(season, received_dt):
    """FINAL variant: early-bird earned only if received_at <= cutoff."""
    if received_dt <= season["_early_bird_cutoff_dt"]:
        return dues_discounted(season)
    return season["base_dues_cents"]


def invoice_balance(inv):
    amount = inv["final_amount_cents"]
    if amount is None:
        amount = inv["provisional_amount_cents"]
    return amount - inv["scholarship_applied_cents"] - inv["paid_cents"] + inv["late_fee_cents"]


def reveal_invoice_final(inv, received_dt):
    if inv["final_amount_cents"] is None:
        season = store.seasons[inv["season_id"]]
        inv["final_amount_cents"] = dues_final(season, received_dt)
        touch(inv)


def member_dues_balance(member_id):
    return sum(
        invoice_balance(i)
        for i in store.dues_invoices.values()
        if i["member_id"] == member_id and i["status"] in OPEN_INVOICE_STATUSES
    )


def member_has_overdue_invoice(member_id):
    return any(
        i["member_id"] == member_id and i["status"] == "OVERDUE"
        for i in store.dues_invoices.values()
    )


# ------------------------------------------------------------- member math
def compute_attendance_rate(member):
    enrolled_dt = member.get("_enrolled_dt")
    counted = [
        r for r in store.rehearsals.values()
        if r["season_id"] == member["season_id"]
        and r["status"] == "COMPLETED"
        and (enrolled_dt is None or r["_scheduled_dt"] >= enrolled_dt)
    ]
    if not counted:
        return 1.0
    total = Decimal("0")
    for r in counted:
        rec = next(
            (a for a in store.attendance_records.values()
             if a["rehearsal_id"] == r["id"] and a["member_id"] == member["id"]),
            None,
        )
        if rec is not None:
            total += _ATTENDANCE_WEIGHT[rec["status"]]
    rate = (total / Decimal(len(counted))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(rate)


def compute_performance_eligible(member, dues_balance=None):
    season = store.seasons[member["season_id"]]
    if dues_balance is None:
        dues_balance = member_dues_balance(member["id"])
    return (
        member["status"] == "ACTIVE"
        and dec(member["attendance_rate"]) >= dec(season["attendance_threshold"])
        and dues_balance == 0
    )


def sync_member(member):
    """Refresh stored derived fields; touch only on real change."""
    changed = False
    dues = member_dues_balance(member["id"])
    if member["dues_balance_cents"] != dues:
        member["dues_balance_cents"] = dues
        changed = True
    rate = compute_attendance_rate(member)
    if member["attendance_rate"] != rate:
        member["attendance_rate"] = rate
        changed = True
    eligible = compute_performance_eligible(member, dues_balance=dues)
    if member["performance_eligible"] != eligible:
        member["performance_eligible"] = eligible
        changed = True
    if changed:
        touch(member)


def sync_section(section):
    n = sum(
        1 for m in store.members.values()
        if m["section_id"] == section["id"] and m["status"] in SECTION_COUNT_STATUSES
    )
    if section["active_count"] != n:
        section["active_count"] = n
        touch(section)


def sync_score(score):
    open_n = sum(
        1 for c in store.score_checkouts.values()
        if c["score_id"] == score["id"] and c["status"] in ("CHECKED_OUT", "OVERDUE")
    )
    available = score["copy_count"] - open_n - score["copies_lost"]
    if score["copies_available"] != available:
        score["copies_available"] = available
        touch(score)


def sync_concert_duration(concert):
    total = sum(
        p["duration_seconds"] for p in store.program_pieces.values()
        if p["concert_id"] == concert["id"] and p["status"] == "CONFIRMED"
    )
    if concert["program_duration_seconds"] != total:
        concert["program_duration_seconds"] = total
        touch(concert)


def sync_committee_raised(committee):
    total = sum(
        p["amount_cents"] for p in store.pledges.values()
        if p["committee_id"] == committee["id"] and p["status"] == "FULFILLED"
    )
    if committee["raised_cents"] != total:
        committee["raised_cents"] = total
        touch(committee)


def sync_tour_confirmed(tour):
    n = sum(
        1 for r in store.tour_registrations.values()
        if r["tour_id"] == tour["id"] and r["status"] == "CONFIRMED"
    )
    if tour["confirmed_count"] != n:
        tour["confirmed_count"] = n
        touch(tour)


# ------------------------------------------------------------- bubble-ups
def after_invoice_cured(invoice):
    """An invoice reached PAID or WAIVED: ENROLLED -> ACTIVE bubble-up and the
    SUSPENDED -> ACTIVE cure path."""
    member = store.members[invoice["member_id"]]
    sync_member(member)
    if member["status"] == "ENROLLED" and member["dues_balance_cents"] == 0:
        member["status"] = "ACTIVE"
        touch(member)
    elif (
        member["status"] == "SUSPENDED"
        and member["dues_balance_cents"] == 0
        and not member_has_overdue_invoice(member["id"])
        and dec(member["attendance_rate"]) >= dec(store.seasons[member["season_id"]]["attendance_threshold"])
    ):
        member["status"] = "ACTIVE"
        touch(member)
    sync_member(member)


# ------------------------------------------------------------ guest quotes
def quote_fee(service_lines, travel_stipend_cents):
    """Pinned rounding order: round each line first, then sum, then stipend."""
    total = 0
    for line in service_lines:
        total += rhu_cents(dec(line["rate_cents"]) * dec(line["units"]))
    return total + (travel_stipend_cents or 0)


def cancellation_fee(quoted_fee_cents):
    return rhu_cents(Decimal("0.20") * Decimal(quoted_fee_cents))


# ------------------------------------------------------------ tour helpers
def tour_registrations(tour_id):
    return [r for r in store.tour_registrations.values() if r["tour_id"] == tour_id]


def tour_refund_amount(tour, registration):
    days_before = whole_days_between(clock.now, tour["_departure_dt"])
    if days_before >= 60:
        pct = Decimal("1")
    elif days_before >= 30:
        pct = Decimal("0.5")
    else:
        pct = Decimal("0")
    return rhu_cents(dec(registration["deposit_paid_cents"]) * pct)


def promote_tour_waitlist(tour):
    if tour["status"] != "REGISTRATION_OPEN":
        return
    regs = tour_registrations(tour["id"])
    while True:
        taken = sum(1 for r in regs if r["status"] in ("REGISTERED", "CONFIRMED"))
        if taken >= tour["seat_count"]:
            break
        waiting = [r for r in regs if r["status"] == "WAITLISTED"]
        if not waiting:
            break
        oldest = min(waiting, key=store.order_key)
        oldest["status"] = "REGISTERED"
        touch(oldest)


# ------------------------------------------------------ member waitlist
def promote_member_waitlist(season):
    candidates = [
        m for m in store.members.values()
        if m["season_id"] == season["id"] and m["status"] == "WAITLISTED"
    ]
    if not candidates:
        return

    def rank(member):
        auds = [
            a for a in store.auditions.values()
            if a["member_id"] == member["id"] and a["status"] == "COMPLETED"
        ]
        if not auds:
            return (Decimal("0"), member["_created_dt"], member["_seq"])
        aud = max(auds, key=store.order_key)
        return (-dec(aud["composite_score"]), aud["_created_dt"], aud["_seq"])

    for member in sorted(candidates, key=rank):
        open_sections = [
            s for s in store.sections.values()
            if s["season_id"] == season["id"]
            and s["status"] == "OPEN"
            and s["target_max"] - s["active_count"] > 0
        ]
        if not open_sections:
            break
        section = min(
            open_sections,
            key=lambda s: (-(s["target_max"] - s["active_count"]), s["_created_dt"], s["_seq"]),
        )
        member["status"] = "ENROLLED"
        member["section_id"] = section["id"]
        member["enrolled_at"] = clock.now_server_string()
        member["_enrolled_dt"] = clock.now
        touch(member)
        sync_section(section)
        sync_member(member)


# -------------------------------------------------------- departure cascade
def member_departure_cascade(member):
    """Shared DROP / RESIGN cascade (PRD 3.3): open checkouts -> LOST with
    charges; non-terminal tour registrations cancelled; waitlist promotion;
    section active_count recompute."""
    for co in list(store.score_checkouts.values()):
        if co["member_id"] == member["id"] and co["status"] in ("CHECKED_OUT", "OVERDUE"):
            score = store.music_scores[co["score_id"]]
            charge = score["replacement_cost_cents"]
            co["charge_cents"] = charge
            member["ledger_balance_cents"] += charge
            if co["status"] == "OVERDUE":
                member["ledger_balance_cents"] += co["fine_cents"]
            co["status"] = "LOST"
            touch(co)
            score["copies_lost"] += 1
            touch(score)
            sync_score(score)
    affected_tours = set()
    for reg in list(store.tour_registrations.values()):
        if reg["member_id"] == member["id"] and reg["status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
            tour = store.tours[reg["tour_id"]]
            if reg["status"] == "CONFIRMED":
                refund = tour_refund_amount(tour, reg)
                reg["refund_cents"] = refund
                treasury_debit(store.seasons[tour["season_id"]], refund, check=False)
            reg["status"] = "CANCELLED"
            touch(reg)
            affected_tours.add(tour["id"])
    for tour_id in affected_tours:
        tour = store.tours[tour_id]
        sync_tour_confirmed(tour)
        promote_tour_waitlist(tour)
    if member["section_id"]:
        section = store.sections.get(member["section_id"])
        if section is not None:
            sync_section(section)


# ------------------------------------------------------ concert cancellation
def cancel_linked_contract(contract, season, check=True):
    """Cascade link 2b/3b: OFFERED|COUNTERED|ACCEPTED|APPROVED -> CANCELLED.
    After ACCEPTED a 20% cancellation fee is debited from the treasury."""
    if contract["status"] not in ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED", "APPROVED"):
        return
    if contract["status"] in ("ACCEPTED", "APPROVED"):
        fee = cancellation_fee(contract["quoted_fee_cents"])
        treasury_debit(season, fee, check=check)
        contract["cancellation_fee_cents"] = fee
    contract["status"] = "CANCELLED"
    touch(contract)


def concert_cancel_cascade(concert):
    """PRD 3.6: release booking (deposit refund), void non-VOID pieces, cancel
    linked contracts (fee after acceptance).  PAID contracts are never touched.
    Atomic: the total fee exposure is pre-checked before any write."""
    season = store.seasons[concert["season_id"]]
    booking = next(
        (b for b in store.venue_bookings.values()
         if b["concert_id"] == concert["id"] and b["status"] in ("REQUESTED", "CONFIRMED")),
        None,
    )
    pieces = [
        p for p in store.program_pieces.values()
        if p["concert_id"] == concert["id"] and p["status"] != "VOID"
    ]
    contracts = []
    for p in pieces:
        cid = p.get("guest_contract_id")
        if cid:
            c = store.guest_contracts.get(cid)
            if c is not None and c["status"] in ("OFFERED", "COUNTERED", "ACCEPTED", "APPROVED"):
                contracts.append(c)
    total_fees = sum(
        cancellation_fee(c["quoted_fee_cents"])
        for c in contracts if c["status"] in ("ACCEPTED", "APPROVED")
    )
    deposit_refund = booking["deposit_cents"] if booking and booking["status"] == "CONFIRMED" else 0
    if season["treasury_balance_cents"] + deposit_refund < total_fees:
        raise ApiError("ERR_INSUFFICIENT_TREASURY", "treasury cannot cover cancellation fees")
    if booking is not None:
        if booking["status"] == "CONFIRMED":
            treasury_credit(season, booking["deposit_cents"])
        booking["status"] = "RELEASED"
        touch(booking)
    for p in pieces:
        p["status"] = "VOID"
        touch(p)
    for c in contracts:
        cancel_linked_contract(c, season, check=False)
    concert["status"] = "CANCELLED"
    touch(concert)
    sync_concert_duration(concert)


# ------------------------------------------------------------- checkpoint
def run_checkpoint(season):
    """PRD 3.1 ops checkpoint: audition expiry, invoice overdue + late fees +
    suspension, attendance probation sweep, member & tour waitlist promotion,
    checkout overdue + fines; then ops_week_index += 1 (version bumps)."""
    now = clock.now
    season_id = season["id"]

    # 1. expire stale auditions
    for a in list(store.auditions.values()):
        member = store.members[a["member_id"]]
        if member["season_id"] != season_id:
            continue
        if a["status"] == "SCHEDULED" and a["_scheduled_dt"] < now:
            a["status"] = "NO_SHOW"
            touch(a)
            if member["status"] == "AUDITION_SCHEDULED":
                member["status"] = "APPLICANT"
                touch(member)
                sync_member(member)

    # 2. invoice overdue sweep + late-fee accrual + suspension
    season_invoices = [i for i in store.dues_invoices.values() if i["season_id"] == season_id]
    for inv in season_invoices:
        if (
            inv["status"] in ("ISSUED", "PARTIAL")
            and season["_dues_due_dt"] < now
            and invoice_balance(inv) > 0
        ):
            inv["status"] = "OVERDUE"
            touch(inv)
    for inv in season_invoices:
        if inv["status"] == "OVERDUE":
            weeks = max(0, whole_days_between(season["_dues_due_dt"], now)) // 7
            fee = min(season["late_fee_cap_cents"], weeks * season["late_fee_weekly_cents"])
            if inv["late_fee_cents"] != fee:
                inv["late_fee_cents"] = fee
                touch(inv)
    for m in list(store.members.values()):
        if m["season_id"] == season_id and m["status"] in ("ACTIVE", "PROBATION"):
            sync_member(m)
            if member_has_overdue_invoice(m["id"]):
                m["status"] = "SUSPENDED"
                touch(m)
                sync_member(m)

    # 3. attendance probation sweep
    threshold = dec(season["attendance_threshold"])
    for m in list(store.members.values()):
        if m["season_id"] != season_id:
            continue
        sync_member(m)
        if m["status"] == "ACTIVE" and dec(m["attendance_rate"]) < threshold:
            m["status"] = "PROBATION"
            touch(m)
            sync_member(m)
        elif (
            m["status"] == "PROBATION"
            and dec(m["attendance_rate"]) >= threshold
            and m["dues_balance_cents"] == 0
        ):
            m["status"] = "ACTIVE"
            touch(m)
            sync_member(m)

    # 4. member waitlist promotion
    promote_member_waitlist(season)

    # 5. tour waitlist promotion
    for tour in list(store.tours.values()):
        if tour["season_id"] == season_id:
            promote_tour_waitlist(tour)

    # 6. checkout overdue sweep + fine accrual
    for co in list(store.score_checkouts.values()):
        member = store.members.get(co["member_id"])
        if member is None or member["season_id"] != season_id:
            continue
        score = store.music_scores[co["score_id"]]
        cap = score["replacement_cost_cents"]
        if co["status"] == "CHECKED_OUT" and co["_due_dt"] < now:
            co["status"] = "OVERDUE"
            co["fine_cents"] = min(OVERDUE_WEEKLY_FINE_CENTS, cap)
            touch(co)
        elif co["status"] == "OVERDUE":
            new_fine = min(co["fine_cents"] + OVERDUE_WEEKLY_FINE_CENTS, cap)
            if new_fine != co["fine_cents"]:
                co["fine_cents"] = new_fine
                touch(co)

    season["ops_week_index"] += 1
    touch(season)
