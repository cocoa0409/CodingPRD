"""Core business logic: calculations, derived fields, cascades, state transitions.

All monetary math uses integer cents; division/percentage operations round
half-up via decimal.Decimal (never float, never banker's rounding).
"""
import math
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ApiError,
    bad_request,
    conflict,
    unprocessable,
    ERR_ALLOCATION_NOT_OPEN,
    ERR_ALLOCATION_NOT_WAITLISTING,
    ERR_OFFER_NOT_PENDING,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_CITATION_NOT_ISSUED,
    ERR_CLOSURE_INVALID_STATE,
    ERR_ROUTE_INVALID_STATE,
    ERR_PLATE_NOT_REGISTERED,
    ERR_CLOSURE_OVERLAP,
    ERR_DUPLICATE_ACTIVE_PERMIT,
    ERR_FLEET_WINDOW_CONFLICT,
    ERR_OFFER_EXPIRED,
    ERR_PATRON_INELIGIBLE,
    ERR_INELIGIBLE_COMMUTE_MODE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DUPLICATE_ALLOCATION_CODE,
    ERR_ALREADY_WAITLISTED,
    ERR_APPEAL_ALREADY_EXISTS,
    ERR_ACCOUNT_EXISTS,
    ERR_PATRON_BLOCKED,
    ERR_INSUFFICIENT_CREDIT,
    ERR_DISPLACEMENT_OVER_CAPACITY,
    ERR_INSUFFICIENT_FUNDING,
    ERR_INSUFFICIENT_SHUTTLE_CAPACITY,
    ERR_INSUFFICIENT_POINTS,
    forbidden,
    payment_required,
)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SURCHARGE_PCT = Decimal("0.05")
ADMIN_FEE_CENTS = 500

VIOLATION_BASE_CENTS = {
    "NO_VALID_PERMIT": 7500,
    "EXPIRED_PERMIT": 5000,
    "WRONG_ZONE": 4000,
    "CLOSED_LOT": 6000,
}
REPEAT_WINDOW_DAYS = 365
REPEAT_THRESHOLD = 2
ESCALATION_MULTIPLIER = Decimal("1.5")
EVENT_DAY_SURCHARGE_CENTS = 1500

ROLE_WEIGHT = {"FACULTY": 100, "STAFF": 80, "STUDENT": 60}
WAIT_DAY_CAP = 30
WAIT_DAY_POINTS = 2
RESIDENCY_BONUS = 10
DECLINE_PENALTY = 15

BLOCK_THRESHOLD_CENTS = 10000
OFFER_TTL_HOURS = 72
MAX_REQUEUES = 2

POINTS_PER_DAY = 10
REDEMPTION_BLOCK_POINTS = 500
REDEMPTION_BLOCK_CREDIT_CENTS = 2500

FLEET_BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# Rounding helper
# ---------------------------------------------------------------------------
def round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest integer, half-up (never banker's)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Date / time parsing
# ---------------------------------------------------------------------------
def parse_iso_date(value, field: str) -> date:
    if not isinstance(value, str):
        raise bad_request(f"{field} must be an ISO date string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise bad_request(f"{field} must be a valid ISO date (YYYY-MM-DD)")


def parse_iso_datetime(value, field: str) -> datetime:
    if not isinstance(value, str):
        raise bad_request(f"{field} must be an ISO 8601 datetime string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise bad_request(f"{field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def logical_date() -> date:
    return db.now().date()


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------
def patron_standing(patron: dict) -> str:
    return (
        "BLOCKED"
        if patron["outstanding_balance_cents"] >= BLOCK_THRESHOLD_CENTS
        else "GOOD_STANDING"
    )


def recompute_patron_standing_and_permit_cascade(patron: dict):
    """Recompute patron standing; flip permits ACTIVE<->SUSPENDED on transitions."""
    old = patron["standing"]
    new = patron_standing(patron)
    if old == new:
        return
    patron["standing"] = new
    touch(patron)
    if new == "BLOCKED":
        for permit in db.permits.values():
            if permit["patron_id"] == patron["id"] and permit["status"] == "ACTIVE":
                permit["status"] = "SUSPENDED"
                touch(permit)
    else:  # GOOD_STANDING
        for permit in db.permits.values():
            if permit["patron_id"] == patron["id"] and permit["status"] == "SUSPENDED":
                permit["status"] = "ACTIVE"
                touch(permit)


def recompute_lot_reserved_and_availability(lot: dict):
    reserved = sum(
        c["reserved_spaces"]
        for c in db.closures.values()
        if c["lot_id"] == lot["id"] and c["status"] in ("SCHEDULED", "ACTIVE")
    )
    lot["reserved_spaces_total"] = reserved
    allocated = sum(
        a["allocated_count"]
        for a in db.allocations.values()
        if a["lot_id"] == lot["id"]
    )
    lot["available_capacity"] = lot["capacity_total"] - reserved - allocated


def recompute_fund(fund: dict):
    committed = sum(
        r["annual_operating_cost_cents"]
        for r in db.shuttle_routes.values()
        if r["fund_id"] == fund["id"] and r["status"] in ("ACTIVE", "SUSPENDED")
    )
    fund["committed_shuttle_funding_cents"] = committed
    fund["available_balance_cents"] = (
        fund["permit_revenue_cents"]
        + fund["citation_revenue_cents"]
        - committed
    )


def reevaluate_allocation_status(allocation: dict):
    """System-managed OPEN <-> WAITLISTING flip."""
    if allocation["allocated_count"] + allocation["offers_outstanding"] >= allocation["quota"]:
        allocation["status"] = "WAITLISTING"
    else:
        allocation["status"] = "OPEN"


def bump_allocation(allocation: dict):
    """Re-evaluate status and increment version after a mutation."""
    reevaluate_allocation_status(allocation)
    touch(allocation)


def touch(record: dict):
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = db.iso_now()


# ---------------------------------------------------------------------------
# Common field bootstrap
# ---------------------------------------------------------------------------
def new_record() -> dict:
    ts = db.iso_now()
    db.next_creation_seq()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ---------------------------------------------------------------------------
# permit_fee_calculation (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_permit_fee(allocation: dict, valid_from: date, apply_credit_cents):
    """Returns (fee_base, surcharge, fee_total, credit_applied, fee_paid)."""
    base_fee_cents = allocation["base_fee_cents"]
    term_start = allocation["_term_start"]
    term_end = allocation["_term_end"]

    total_days = (term_end - term_start).days + 1

    if allocation["proration_policy"] == "PRORATED_WEEKLY":
        term_weeks = math.ceil(total_days / 7)
        remaining_days = (term_end - valid_from).days + 1
        weeks_remaining = math.ceil(remaining_days / 7)
        weekly_rate = round_half_up(Decimal(base_fee_cents) / Decimal(term_weeks))
        fee_base_cents = weekly_rate * weeks_remaining
    else:  # FLAT_HALF_TERM
        midterm_date = term_start + timedelta(days=total_days // 2)
        if valid_from <= midterm_date:
            fee_base_cents = base_fee_cents
        else:
            fee_base_cents = round_half_up(Decimal(base_fee_cents) * Decimal("0.5"))

    surcharge_cents = round_half_up(Decimal(fee_base_cents) * SURCHARGE_PCT)
    fee_total_cents = fee_base_cents + surcharge_cents

    if apply_credit_cents is not None:
        credit_applied = min(apply_credit_cents, fee_total_cents)
    else:
        credit_applied = 0
    fee_paid = fee_total_cents - credit_applied
    return fee_base_cents, surcharge_cents, fee_total_cents, credit_applied, fee_paid


# ---------------------------------------------------------------------------
# permit_refund_calculation (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_refund(permit: dict) -> int:
    today = logical_date()
    valid_from = permit["_valid_from"]
    valid_to = permit["_valid_to"]
    fee_paid = permit["fee_paid_cents"]
    if today < valid_from:
        return fee_paid
    total_days = (valid_to - valid_from).days + 1
    remaining_days = (valid_to - today).days  # cancel day itself consumed
    share = round_half_up(
        Decimal(fee_paid) * Decimal(remaining_days) / Decimal(total_days)
    )
    return max(0, share - ADMIN_FEE_CENTS)


# ---------------------------------------------------------------------------
# citation_fine_calculation (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_fine(patron: dict, lot: dict, violation_type: str) -> int:
    base = VIOLATION_BASE_CENTS[violation_type]
    now = db.now()
    window_start = now - timedelta(days=REPEAT_WINDOW_DAYS)
    repeat_count = sum(
        1
        for c in db.citations.values()
        if c["patron_id"] == patron["id"]
        and c["status"] == "PAID"
        and c["_issued_at"] >= window_start
    )
    multiplier = ESCALATION_MULTIPLIER if repeat_count >= REPEAT_THRESHOLD else Decimal("1.0")
    escalated = round_half_up(Decimal(base) * multiplier)

    event_surcharge = 0
    for closure in db.closures.values():
        if (
            closure["lot_id"] == lot["id"]
            and closure["reason"] == "EVENT"
            and closure["status"] == "ACTIVE"
            and closure["_starts_at"] <= now < closure["_ends_at"]
        ):
            event_surcharge = EVENT_DAY_SURCHARGE_CENTS
            break
    return escalated + event_surcharge


# ---------------------------------------------------------------------------
# waitlist_priority_score (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def waitlist_priority_score(entry: dict, patron: dict) -> int:
    wait_seconds = (db.now() - entry["_waiting_since"]).total_seconds()
    wait_days = math.floor(wait_seconds / 86400)
    score = ROLE_WEIGHT[patron["campus_role"]]
    score += min(wait_days, WAIT_DAY_CAP) * WAIT_DAY_POINTS
    if patron["residency"] == "ON_CAMPUS":
        score += RESIDENCY_BONUS
    score -= DECLINE_PENALTY * entry["decline_count"]
    return score


# ---------------------------------------------------------------------------
# Offer selector — used by extend-offers AND by seat-freed cascades
# ---------------------------------------------------------------------------
def sweep_expired_offers(allocation: dict):
    """OFFERED entries past offer_expires_at -> EXPIRED -> requeue/withdraw."""
    now = db.now()
    changed = False
    for entry in list(db.waitlist_entries.values()):
        if entry["allocation_id"] != allocation["id"] or entry["status"] != "OFFERED":
            continue
        if now > entry["_offer_expires_at"]:
            entry["status"] = "EXPIRED"
            allocation["offers_outstanding"] -= 1
            changed = True
            # immediate requeue branch
            if entry["requeue_count"] < MAX_REQUEUES:
                entry["requeue_count"] += 1
                entry["decline_count"] += 1
                entry["status"] = "WAITING"
                entry["waiting_since"] = db.iso_now()
                entry["_waiting_since"] = now
                entry["offered_at"] = None
                entry["offer_expires_at"] = None
                entry["_offered_at"] = None
                entry["_offer_expires_at"] = None
            else:
                entry["status"] = "WITHDRAWN"
                entry["decline_count"] += 1
            touch(entry)
    if changed:
        bump_allocation(allocation)


def extend_offers(allocation: dict):
    """Sweep expired offers, then promote top-scored WAITING entries.

    Returns list of entry ids promoted in this round.
    """
    sweep_expired_offers(allocation)
    free_seats = (
        allocation["quota"]
        - allocation["allocated_count"]
        - allocation["offers_outstanding"]
    )
    promoted = []
    if free_seats > 0:
        candidates = [
            e
            for e in db.waitlist_entries.values()
            if e["allocation_id"] == allocation["id"] and e["status"] == "WAITING"
        ]

        def sort_key(e):
            patron = db.patrons[e["patron_id"]]
            score = waitlist_priority_score(e, patron)
            # score DESC, waiting_since ASC
            return (-score, e["_waiting_since"])

        candidates.sort(key=sort_key)
        now = db.now()
        for entry in candidates[:free_seats]:
            entry["status"] = "OFFERED"
            entry["offered_at"] = db.iso_now()
            entry["_offered_at"] = now
            expires = now + timedelta(hours=OFFER_TTL_HOURS)
            entry["offer_expires_at"] = db.fmt_ts(expires)
            entry["_offer_expires_at"] = expires
            touch(entry)
            allocation["offers_outstanding"] += 1
            promoted.append(entry["id"])
    if promoted:
        bump_allocation(allocation)
    return promoted


# ---------------------------------------------------------------------------
# Eligibility checks
# ---------------------------------------------------------------------------
def check_patron_eligible(patron: dict, allocation: dict):
    if patron["campus_role"] not in allocation["eligible_roles"]:
        raise forbidden(
            ERR_PATRON_INELIGIBLE,
            "Patron role is not eligible for this allocation",
        )
    rule = allocation["residency_rule"]
    if rule == "ON_CAMPUS_ONLY" and patron["residency"] != "ON_CAMPUS":
        raise forbidden(ERR_PATRON_INELIGIBLE, "Residency rule not satisfied")
    if rule == "OFF_CAMPUS_ONLY" and patron["residency"] != "OFF_CAMPUS":
        raise forbidden(ERR_PATRON_INELIGIBLE, "Residency rule not satisfied")


# ---------------------------------------------------------------------------
# Plate double-booking (temporal, inclusive windows)
# ---------------------------------------------------------------------------
def check_plate_available(plate_number: str, valid_from: date, valid_to: date):
    for permit in db.permits.values():
        if permit["plate_number"] != plate_number:
            continue
        if permit["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        # inclusive [valid_from, valid_to]: touching counts as overlap
        if valid_from <= permit["_valid_to"] and permit["_valid_from"] <= valid_to:
            raise conflict(
                ERR_DUPLICATE_ACTIVE_PERMIT,
                "Plate already covered by an ACTIVE/SUSPENDED permit on overlapping dates",
            )


# ---------------------------------------------------------------------------
# Closure overlap (half-open)
# ---------------------------------------------------------------------------
def windows_overlap_half_open(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def check_closure_overlap(lot_id: str, starts_at, ends_at, exclude_closure_id=None):
    for c in db.closures.values():
        if c["lot_id"] != lot_id or c["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if exclude_closure_id and c["id"] == exclude_closure_id:
            continue
        if windows_overlap_half_open(starts_at, ends_at, c["_starts_at"], c["_ends_at"]):
            raise conflict(
                ERR_CLOSURE_OVERLAP,
                "Closure window overlaps another SCHEDULED/ACTIVE closure on the same lot",
            )


# ---------------------------------------------------------------------------
# Fleet window buffer
# ---------------------------------------------------------------------------
def windows_gap_ok(a_start, a_end, b_start, b_end, buffer_minutes=FLEET_BUFFER_MINUTES):
    """True iff the gap between [a_start,a_end] and [b_start,b_end] >= buffer."""
    if a_end <= b_start:
        return (b_start - a_end) >= buffer_minutes
    if b_end <= a_start:
        return (a_start - b_end) >= buffer_minutes
    return False  # overlapping windows have zero gap


def check_fleet_buffer(fleet_group: str, start_min: int, end_min: int,
                       statuses: tuple, exclude_route_id=None):
    for r in db.shuttle_routes.values():
        if r["fleet_group"] != fleet_group or r["status"] not in statuses:
            continue
        if exclude_route_id and r["id"] == exclude_route_id:
            continue
        if not windows_gap_ok(
            start_min,
            end_min,
            r["service_window_start_minutes"],
            r["service_window_end_minutes"],
        ):
            raise conflict(
                ERR_FLEET_WINDOW_CONFLICT,
                "Fleet window buffer (< 30 min gap) conflict with another route in the fleet group",
            )


# ---------------------------------------------------------------------------
# Serializers — strip internal underscore keys
# ---------------------------------------------------------------------------
def serialize(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.startswith("_")}
