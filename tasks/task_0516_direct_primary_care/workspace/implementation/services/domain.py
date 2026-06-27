"""Core domain calculations, derived-field reconciliation, and cascades.

Every rule here traces to a PRD sentence (§3.1-§3.13).
"""
from datetime import timedelta
from decimal import Decimal

import db
from clock import clock
from services.money import round_half_up_cents

MONTHLY_PERIOD_DAYS = 30
ANNUAL_PERIOD_DAYS = 365

BUSINESS_OPEN_HOUR = 8
BUSINESS_CLOSE_HOUR = 18
ROUTINE_SLA_HOURS = 24
AFTER_HOURS_SLA_HOURS = 4

REFERRAL_AUTH_VALID_DAYS = 30


# ---------------------------------------------------------------------------
# Provider panel (PRD §3.1, §3.4)
# ---------------------------------------------------------------------------

def effective_cap(provider):
    """Provider's effective hard cap: panel_capacity if set, else practice.panel_hard_cap."""
    if provider.get("panel_capacity") is not None:
        return provider["panel_capacity"]
    practice = db.practices[provider["practice_id"]]
    return practice["panel_hard_cap"]


def recompute_provider_panel(provider):
    """Recompute active_panel_count and panel_load_bucket for a provider.

    active_panel_count = members assigned to this provider whose membership_status
    is ACTIVE or PAST_DUE (PENDING_PAYMENT/SUSPENDED/CANCELLED excluded).
    """
    count = 0
    for m in db.members.values():
        if m.get("assigned_provider_id") == provider["id"] and \
                m.get("membership_status") in ("ACTIVE", "PAST_DUE"):
            count += 1
    provider["active_panel_count"] = count

    practice = db.practices[provider["practice_id"]]
    cap = effective_cap(provider)
    target = practice["panel_target"]
    if count < target:
        bucket = "UNDER_TARGET"
    elif count < cap:
        bucket = "AT_TARGET"
    else:
        bucket = "FULL"
    provider["panel_load_bucket"] = bucket
    db.touch(provider)


# ---------------------------------------------------------------------------
# Employer seats (PRD §3.2)
# ---------------------------------------------------------------------------

def recompute_employer_seats(employer):
    """occupied_seat_count = EmployerSeat rows for this employer with status OCCUPIED."""
    count = 0
    for s in db.employer_seats.values():
        if s["employer_id"] == employer["id"] and s["seat_status"] == "OCCUPIED":
            count += 1
    employer["occupied_seat_count"] = count
    db.touch(employer)


# ---------------------------------------------------------------------------
# VisitSlot capacity (PRD §3.5)
# ---------------------------------------------------------------------------

def slot_effective_capacity(slot):
    if slot["slot_type"] == "IN_PERSON":
        return 1
    return slot["virtual_capacity"]


def recompute_slot(slot):
    """booked_count = visits on this slot not CANCELLED/NO_SHOW; slot_state derived."""
    count = 0
    for v in db.visits.values():
        if v["slot_id"] == slot["id"] and \
                v["clinical_status"] not in ("CANCELLED", "NO_SHOW"):
            count += 1
    slot["booked_count"] = count
    cap = slot_effective_capacity(slot)
    slot["slot_state"] = "OPEN" if count < cap else "FULL"
    db.touch(slot)


# ---------------------------------------------------------------------------
# member_monthly_share calculation (PRD §3.8)
# ---------------------------------------------------------------------------

def compute_member_share(membership, late_fee=False):
    """Compute member_share_cents for a membership.

    Order is fixed: ANNUAL discount (round) before employer sponsorship (round);
    late fee additive only on the next PAST_DUE-exit charge.
    """
    member = db.members[membership["member_id"]]
    practice = db.practices[member["practice_id"]]
    base_fee = membership["monthly_fee_cents"]

    if membership["plan_type"] == "ANNUAL_PREPAID":
        annual_total = round_half_up_cents(
            Decimal(base_fee) * 12 * (Decimal(1) - Decimal(str(practice["annual_fee_discount_pct"])))
        )
        period_fee = annual_total
    else:
        period_fee = base_fee

    seat_id = membership.get("employer_seat_id")
    if seat_id is not None:
        seat = db.employer_seats[seat_id]
        employer = db.employers[seat["employer_id"]]
        employer_covers = round_half_up_cents(
            Decimal(period_fee) * Decimal(str(employer["sponsorship_pct"]))
        )
        member_share = period_fee - employer_covers
    else:
        member_share = period_fee

    if late_fee:
        member_share = member_share + practice["late_fee_cents"]
    return member_share


def set_member_share(membership, late_fee=False):
    membership["member_share_cents"] = compute_member_share(membership, late_fee=late_fee)


# ---------------------------------------------------------------------------
# Billing period (PRD §3.3)
# ---------------------------------------------------------------------------

def period_length_days(plan_type):
    return ANNUAL_PERIOD_DAYS if plan_type == "ANNUAL_PREPAID" else MONTHLY_PERIOD_DAYS


def compute_period_end(membership):
    start = membership["current_period_start"]
    if start is None:
        return None
    return start + timedelta(days=period_length_days(membership["plan_type"]))


# ---------------------------------------------------------------------------
# membership_proration calculation (PRD §3.9)
# ---------------------------------------------------------------------------

def compute_proration_refund(membership):
    """Refund the unused portion of the current period as wallet credit (ACTIVE cancel)."""
    plen = period_length_days(membership["plan_type"])
    start = membership["current_period_start"]
    now = clock.now()
    elapsed_seconds = (now - start).total_seconds()
    elapsed_days = int(elapsed_seconds // 86400)  # whole days, floor
    if elapsed_days < 0:
        elapsed_days = 0
    remaining_days = max(0, plen - elapsed_days)
    daily_share = Decimal(membership["member_share_cents"]) / Decimal(plen)  # exact rational
    refund = round_half_up_cents(daily_share * Decimal(remaining_days))
    return refund


# ---------------------------------------------------------------------------
# invoice_split calculation (PRD §3.7)
# ---------------------------------------------------------------------------

def compute_invoice_split(member, practice, service_lines):
    """Return dict with gross/dpc/insurance/member_responsibility cents."""
    covered = set(practice.get("dpc_covered_service_codes") or [])
    gross = 0
    dpc = 0
    for line in service_lines:
        amt = line["units"] * line["unit_charge_cents"]
        gross += amt
        if line["service_code"] in covered:
            dpc += amt
    non_dpc = gross - dpc

    if not member["has_insurance"]:
        insurance_billed = 0
        member_resp = non_dpc
    else:
        insurance_billed = non_dpc
        member_resp = round_half_up_cents(
            Decimal(non_dpc) * Decimal(str(practice["insurance_coinsurance_pct"]))
        )
    return {
        "gross_charge_cents": gross,
        "dpc_covered_cents": dpc,
        "insurance_billed_cents": insurance_billed,
        "member_responsibility_cents": member_resp,
    }


# ---------------------------------------------------------------------------
# thread_sla_deadline calculation (PRD §3.12)
# ---------------------------------------------------------------------------

def compute_thread_sla(created_at):
    """Return (priority, response_deadline) from created_at hour-of-day UTC."""
    hour = created_at.hour
    if BUSINESS_OPEN_HOUR <= hour < BUSINESS_CLOSE_HOUR:
        priority = "ROUTINE"
        deadline = created_at + timedelta(hours=ROUTINE_SLA_HOURS)
    else:
        priority = "AFTER_HOURS"
        deadline = created_at + timedelta(hours=AFTER_HOURS_SLA_HOURS)
    return priority, deadline


# ---------------------------------------------------------------------------
# panel_assignment_selector (PRD §3.4)
# ---------------------------------------------------------------------------

def select_auto_provider(member):
    """Return the auto-selected provider or None when no candidate exists."""
    candidates = []
    for p in db.providers.values():
        if p["practice_id"] != member["practice_id"]:
            continue
        if not p["accepting_new_members"]:
            continue
        if p["active_panel_count"] >= effective_cap(p):
            continue
        candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["active_panel_count"], p["created_at"], p.get("_seq", 0)))
    return candidates[0]


# ---------------------------------------------------------------------------
# Cascades shared by cancellation / suspension (PRD §3.3)
# ---------------------------------------------------------------------------

def cancel_open_visits_for_member(member):
    """Cancel all of a member's BOOKED/CHECKED_IN visits; adjust slots."""
    affected_slots = set()
    for v in db.visits.values():
        if v["member_id"] == member["id"] and \
                v["clinical_status"] in ("BOOKED", "CHECKED_IN"):
            v["clinical_status"] = "CANCELLED"
            db.touch(v)
            affected_slots.add(v["slot_id"])
    for slot_id in affected_slots:
        slot = db.visit_slots.get(slot_id)
        if slot is not None:
            recompute_slot(slot)


def release_employer_seat(membership):
    """If sponsored, RELEASE the seat, clear its member, recompute employer count."""
    seat_id = membership.get("employer_seat_id")
    if seat_id is None:
        return
    seat = db.employer_seats.get(seat_id)
    if seat is not None:
        seat["seat_status"] = "RELEASED"
        seat["member_id"] = None
        db.touch(seat)
        employer = db.employers.get(seat["employer_id"])
        if employer is not None:
            recompute_employer_seats(employer)
    membership["employer_seat_id"] = None
    db.touch(membership)
