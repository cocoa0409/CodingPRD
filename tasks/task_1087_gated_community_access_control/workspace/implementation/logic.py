"""Business logic: calculations, cascades, gate matching, capacity, overlap."""
from datetime import timedelta
from decimal import Decimal

from core import (
    db, now, touch, span_seconds, hours_ceil, round_half_up,
    GUEST_HOURLY_CENTS, VENDOR_HOURLY_CENTS, OVERSTAY_SURCHARGE_CENTS_PER_HOUR,
    OVERAGE_MULTIPLIER, REPEAT_WINDOW_DAYS, DELINQUENT_SURCHARGE_CENTS,
    FINE_CAP_CENTS, DELINQUENCY_THRESHOLD_CENTS, PATROL_BUFFER_MINUTES,
)

# ---------------------------------------------------------------------------
# Pass fees (SCAFFOLD pass_fee)
# ---------------------------------------------------------------------------
def pass_rate(p):
    return VENDOR_HOURLY_CENTS if p["pass_type"] == "VENDOR" else GUEST_HOURLY_CENTS


def compute_estimated_fee(p):
    rate = pass_rate(p)
    planned_hours = hours_ceil(span_seconds(p["valid_until"], p["valid_from"]))
    return planned_hours * rate


def compute_final_fee(p):
    rate = pass_rate(p)
    entry_at = p["entry_at"]
    exit_at = p["exit_at"]
    valid_until = p["valid_until"]
    end = min(exit_at, valid_until)
    billable_hours = hours_ceil(span_seconds(end, entry_at))
    overstay_hours = hours_ceil(span_seconds(exit_at, valid_until))
    return billable_hours * rate + overstay_hours * OVERSTAY_SURCHARGE_CENTS_PER_HOUR


# ---------------------------------------------------------------------------
# Amenity settlement (SCAFFOLD amenity_settlement)
# ---------------------------------------------------------------------------
def compute_quoted_fee(amenity, start_at, end_at):
    planned_hours = hours_ceil(span_seconds(end_at, start_at))
    return planned_hours * amenity["hourly_fee_cents"] + amenity["deposit_cents"]


def compute_settled_fee(amenity, reservation):
    hourly = amenity["hourly_fee_cents"]
    checkin_at = reservation["checkin_at"]
    checkout_at = reservation["checkout_at"]
    end_at = reservation["end_at"]
    base_hours = hours_ceil(span_seconds(min(checkout_at, end_at), checkin_at))
    overage_hours = hours_ceil(span_seconds(checkout_at, end_at))
    return base_hours * hourly + overage_hours * OVERAGE_MULTIPLIER * hourly


# ---------------------------------------------------------------------------
# Violation fine (SCAFFOLD violation_fine)
# ---------------------------------------------------------------------------
def compute_repeat_index(resident_id, violation_type, issued_at, exclude_id):
    window = timedelta(days=REPEAT_WINDOW_DAYS)
    count = 0
    for v in db.violations.values():
        if v["id"] == exclude_id:
            continue
        if v["resident_id"] != resident_id:
            continue
        if v["violation_type"] != violation_type:
            continue
        if v["status"] not in ("ISSUED", "UPHELD", "REDUCED", "PAID"):
            continue
        prior = v["issued_at"]
        if prior is None:
            continue
        delta = issued_at - prior
        if timedelta(0) <= delta <= window:
            count += 1
    return count


def tier_multiplier(repeat_index):
    return {0: Decimal("1.0"), 1: Decimal("1.5"), 2: Decimal("2.0")}.get(
        repeat_index, Decimal("3.0")
    )


def compute_assessed_fine(base_fine_cents, repeat_index, standing):
    mult = tier_multiplier(repeat_index)
    base_component = round_half_up(Decimal(base_fine_cents) * mult)
    surcharge = DELINQUENT_SURCHARGE_CENTS if standing == "DELINQUENT" else 0
    return min(FINE_CAP_CENTS, base_component + surcharge)


# ---------------------------------------------------------------------------
# Resident balance / standing / delinquency cascade (PRD 3.1, 2.8)
# ---------------------------------------------------------------------------
def compute_outstanding_balance(resident_id):
    total = 0
    for v in db.violations.values():
        if v["resident_id"] != resident_id:
            continue
        if v["status"] in ("ISSUED", "APPEALED", "UPHELD", "REDUCED"):
            total += v["assessed_fine_cents"]
        elif v["status"] == "PAID":
            total -= (v["paid_amount_cents"] or 0)
    return total


def compute_accrued_late_fee(resident_id):
    total = 0
    for v in db.violations.values():
        if v["resident_id"] != resident_id:
            continue
        if v["status"] in ("ISSUED", "UPHELD", "REDUCED"):
            total += round_half_up(Decimal(v["assessed_fine_cents"]) * Decimal("0.015"))
    return total


def recompute_resident(resident):
    """Recompute balance + standing; refresh version if changed; fire the
    delinquency cascade (auto-suspend) on a GOOD->DELINQUENT flip while ACTIVE."""
    new_balance = compute_outstanding_balance(resident["id"])
    old_standing = resident["standing"]
    new_standing = "DELINQUENT" if new_balance >= DELINQUENCY_THRESHOLD_CENTS else "GOOD"
    changed = (new_balance != resident["outstanding_balance_cents"]) or (
        new_standing != old_standing
    )
    resident["outstanding_balance_cents"] = new_balance
    resident["standing"] = new_standing
    if changed:
        touch(resident)
    if old_standing == "GOOD" and new_standing == "DELINQUENT" and resident["status"] == "ACTIVE":
        suspend_resident(resident)


def suspend_resident(resident):
    """Drive resident ACTIVE->SUSPENDED with its two secondary cascade effects."""
    resident["status"] = "SUSPENDED"
    touch(resident)
    # Cancel BOOKED / CHECKED_IN reservations, releasing party_size.
    for r in db.reservations.values():
        if r["resident_id"] == resident["id"] and r["status"] in ("BOOKED", "CHECKED_IN"):
            r["status"] = "CANCELLED"
            touch(r)
    # Revoke APPROVED + OFFSITE passes.
    for p in db.passes.values():
        if (
            p["sponsor_resident_id"] == resident["id"]
            and p["auth_status"] == "APPROVED"
            and p["presence_status"] == "OFFSITE"
        ):
            p["auth_status"] = "REVOKED"
            touch(p)


# ---------------------------------------------------------------------------
# Move-out cascade (PRD 2.8)
# ---------------------------------------------------------------------------
def moveout_cascade(resident):
    for veh in db.vehicles.values():
        if veh["resident_id"] == resident["id"] and veh["status"] == "ACTIVE":
            veh["status"] = "INACTIVE"
            touch(veh)
            revoke_active_decal(veh["id"])


def revoke_active_decal(vehicle_id):
    for d in db.decals.values():
        if d["vehicle_id"] == vehicle_id and d["status"] == "ACTIVE":
            d["status"] = "REVOKED"
            touch(d)


# ---------------------------------------------------------------------------
# Amenity concurrent load / capacity (SCAFFOLD amenity_concurrent_load)
# ---------------------------------------------------------------------------
def _overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def peak_load(amenity_id, start_at, end_at, exclude_id=None):
    active = [
        r for r in db.reservations.values()
        if r["amenity_id"] == amenity_id
        and r["status"] in ("BOOKED", "CHECKED_IN")
        and r["id"] != exclude_id
        and _overlaps(r["start_at"], r["end_at"], start_at, end_at)
    ]
    points = [start_at] + [r["start_at"] for r in active if start_at <= r["start_at"] < end_at]
    max_load = 0
    for t in points:
        load = sum(r["party_size"] for r in active if r["start_at"] <= t < r["end_at"])
        if load > max_load:
            max_load = load
    return max_load


# ---------------------------------------------------------------------------
# Patrol overlap (SCAFFOLD patrol_shift_overlap)
# ---------------------------------------------------------------------------
def patrol_conflict(community_id, officer_id, start_at, end_at, exclude_id=None):
    for p in db.patrols.values():
        if p["id"] == exclude_id:
            continue
        if p["officer_id"] != officer_id:
            continue
        if p["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        # closed intervals; gap between nearest endpoints
        gap_seconds = max(
            span_seconds(p["start_at"], end_at),
            span_seconds(start_at, p["end_at"]),
        )
        gap_minutes = gap_seconds / 60.0
        if gap_minutes < PATROL_BUFFER_MINUTES:
            return True
    return False


# ---------------------------------------------------------------------------
# Gate matching (PRD 3.4)
# ---------------------------------------------------------------------------
def process_gate_event(event, community_id, direction, plate_read):
    event_at = event["event_at"]
    matched_type = "UNMATCHED"
    matched_id = None
    decision = "DENY"
    reason = "NO_MATCH"

    # 1) Decal match: read == vehicle.plate, decal ACTIVE, in window.
    matched_decal = None
    for d in db.decals.values():
        veh = db.vehicles.get(d["vehicle_id"])
        if not veh or veh["plate"] != plate_read:
            continue
        if d["status"] != "ACTIVE":
            continue
        if event_at >= d["valid_until"]:
            # expired at gate-match time
            d["status"] = "EXPIRED"
            touch(d)
            continue
        if d["valid_from"] <= event_at < d["valid_until"]:
            matched_decal = d
            break

    if matched_decal is not None:
        matched_type = "DECAL"
        matched_id = matched_decal["id"]
        decision = "ALLOW"
        reason = "ALLOWED_DECAL"
    else:
        # 2) Pass match: visitor_plate == read, APPROVED, in window.
        matched_pass = None
        for p in db.passes.values():
            if p["visitor_plate"] != plate_read:
                continue
            if p["auth_status"] != "APPROVED":
                continue
            if event_at >= p["valid_until"]:
                p["auth_status"] = "EXPIRED"
                touch(p)
                continue
            if p["valid_from"] <= event_at < p["valid_until"]:
                matched_pass = p
                break
        if matched_pass is not None:
            matched_type = "PASS"
            matched_id = matched_pass["id"]
            decision = "ALLOW"
            reason = "ALLOWED_PASS"

    event["matched_type"] = matched_type
    event["matched_id"] = matched_id
    event["decision"] = decision
    event["reason"] = reason

    # 3) Presence axis (independent of the barrier decision).
    if direction == "ENTRY" and matched_type == "PASS":
        p = db.passes[matched_id]
        if (
            p["presence_status"] == "OFFSITE"
            and p["auth_status"] == "APPROVED"
            and p["valid_from"] <= event_at < p["valid_until"]
        ):
            p["presence_status"] = "ONSITE"
            p["entry_at"] = event_at
            touch(p)
    elif direction == "EXIT":
        # An EXIT departs whatever ONSITE pass this plate entered on, even past
        # window (so the overstay surcharge in final_fee can be billed).
        for p in db.passes.values():
            if p["visitor_plate"] == plate_read and p["presence_status"] == "ONSITE":
                p["presence_status"] = "DEPARTED"
                p["exit_at"] = event_at
                p["final_fee_cents"] = compute_final_fee(p)
                touch(p)
                break
