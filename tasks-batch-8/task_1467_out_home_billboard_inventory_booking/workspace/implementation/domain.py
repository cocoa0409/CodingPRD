"""Domain services: derived fields, cascades, availability, sweeps."""
from datetime import timedelta

import calc
import db
from util import D, clock_now, clock_today, midnight_of

# Blocking status sets (PRD 3.5 / calc face_availability_calendar)
BLOCKING = ("BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER")
CONTRACTED = ("BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER", "COMPLETED")
EXPOSURE_SET = ("BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER")
FLIGHT_TERMINAL = ("COMPLETED", "CANCELLED", "EXPIRED", "RELEASED")
ACTIVE_FLIGHT_SET = ("HELD", "BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def face_flights(face_id):
    return [f for f in db.flights.values() if f["face_id"] == face_id]


def campaign_flights(campaign_id):
    return [f for f in db.flights.values() if f["campaign_id"] == campaign_id]


def flight_make_goods(flight_id):
    return [m for m in db.make_goods.values() if m["flight_id"] == flight_id]


def face_work_orders(face_id):
    return [w for w in db.work_orders.values() if w["face_id"] == face_id]


def face_posture(status):
    if status == "AVAILABLE":
        return "OPEN"
    if status == "UNDER_MAINTENANCE":
        return "RESTRICTED"
    return "BLOCKED"


def unexpired_held(flight):
    return flight["status"] == "HELD" and clock_now() < flight["held_until"]


def is_blocking(flight):
    return flight["status"] in BLOCKING or unexpired_held(flight)


# ---------------------------------------------------------------------------
# Ledger recomputes
# ---------------------------------------------------------------------------
def recompute_campaign_ledgers(campaign):
    fs = [f for f in campaign_flights(campaign["id"]) if f["status"] in CONTRACTED]
    campaign["contracted_cents"] = sum(
        f["gross_cents"] + f["holdover_charge_cents"] for f in fs)
    campaign["net_contracted_cents"] = sum(calc.per_flight_net(f) for f in fs)


def recompute_delivery_posture(campaign):
    fs = campaign_flights(campaign["id"])
    if any(f["status"] == "COMPLETED" and D(str(f["delivery_ratio"])) < D("0.9")
           for f in fs):
        new = "UNDER_DELIVERED"
    elif any(f["status"] in ("MISSED", "HOLDOVER")
             or f["suspension_started_at"] is not None
             or f["suspension_days_accrued"] > 0 for f in fs):
        new = "AT_RISK"
    else:
        new = "ON_TRACK"
    if new != campaign["delivery_posture"]:
        campaign["delivery_posture"] = new
        db.touch(campaign)


def recompute_exposure(advertiser):
    camp_ids = {c["id"] for c in db.campaigns.values()
                if c["advertiser_id"] == advertiser["id"]}
    total = sum(f["net_cents"] + f["holdover_charge_cents"]
                for f in db.flights.values()
                if f["campaign_id"] in camp_ids and f["status"] in EXPOSURE_SET)
    if total != advertiser["exposure_cents"]:
        advertiser["exposure_cents"] = total
        db.touch(advertiser)


def refresh_campaign(campaign, advertiser=None):
    """Ledger + posture + exposure refresh after a flight-affecting change."""
    recompute_campaign_ledgers(campaign)
    recompute_delivery_posture(campaign)
    if advertiser is None:
        advertiser = db.advertisers.get(campaign["advertiser_id"])
    if advertiser is not None:
        recompute_exposure(advertiser)


# ---------------------------------------------------------------------------
# Make-goods (PRD 3.9)
# ---------------------------------------------------------------------------
def auto_make_good(flight, reason, credit_cents):
    mg = db.new_resource()
    mg.update({
        "flight_id": flight["id"],
        "reason": reason,
        "credit_cents": credit_cents,
        "status": "PROPOSED",
        "proposed_by": "system",
    })
    db.make_goods[mg["id"]] = mg
    return mg


def evaluate_under_delivery(flight):
    """Auto-propose UNDER_DELIVERY at completion when short of the 0.90
    guarantee. At most one live auto make-good per flight."""
    credit = calc.under_delivery_credit(flight)
    if credit is None:
        return
    for mg in flight_make_goods(flight["id"]):
        if mg["reason"] == "UNDER_DELIVERY" and mg["proposed_by"] == "system" \
                and mg["status"] in ("PROPOSED", "APPROVED", "APPLIED"):
            return
    auto_make_good(flight, "UNDER_DELIVERY", credit)


# ---------------------------------------------------------------------------
# Campaign auto transitions (PRD 3.4)
# ---------------------------------------------------------------------------
def check_campaign_active(campaign):
    if campaign["status"] == "APPROVED":
        campaign["status"] = "ACTIVE"
        db.touch(campaign)


def check_campaign_terminal(campaign):
    if campaign["status"] != "ACTIVE":
        return
    fs = campaign_flights(campaign["id"])
    if fs and all(f["status"] in FLIGHT_TERMINAL for f in fs):
        campaign["status"] = "COMPLETED"
        db.touch(campaign)
        for f in fs:
            if f["status"] == "COMPLETED":
                evaluate_under_delivery(f)


# ---------------------------------------------------------------------------
# Flight completion (PRD 3.7)
# ---------------------------------------------------------------------------
def complete_flight(flight, with_holdover):
    """Shared completion path: suspension settlement, holdover pricing,
    ledger recomputes, under-delivery evaluation, campaign auto-complete."""
    now = clock_now()
    today = now.date()
    face = db.faces.get(flight["face_id"])
    campaign = db.campaigns.get(flight["campaign_id"])

    # Permit-suspension settlement when the flight completes while suspended:
    # days run from suspension_started_at until the flight's end_date (PRD 3.9).
    if flight["suspension_started_at"] is not None:
        days = (flight["end_date"] - flight["suspension_started_at"].date()).days
        if days < 0:
            days = 0
        flight["suspension_days_accrued"] += days
        flight["suspension_started_at"] = None
        auto_make_good(flight, "PERMIT_SUSPENSION",
                       calc.mg_permit_suspension(flight, days))

    if with_holdover:
        weeks, charge = calc.holdover_charge(flight, today)
        flight["holdover_weeks"] = weeks
        flight["holdover_charge_cents"] = charge
    else:
        flight["holdover_weeks"] = 0
        flight["holdover_charge_cents"] = 0
    flight["status"] = "COMPLETED"
    db.touch(flight)

    if campaign is not None:
        refresh_campaign(campaign)
        evaluate_under_delivery(flight)
        check_campaign_terminal(campaign)


def flight_enters_live(flight):
    flight["status"] = "LIVE"
    db.touch(flight)
    campaign = db.campaigns.get(flight["campaign_id"])
    if campaign is not None:
        check_campaign_active(campaign)
        recompute_delivery_posture(campaign)


# ---------------------------------------------------------------------------
# Permit cascades (PRD 3.2)
# ---------------------------------------------------------------------------
def suspend_face_for_permit(face):
    """Link 2-4 of the permit cascade: face -> PERMIT_SUSPENDED, stamp LIVE /
    HOLDOVER flights, recompute affected campaign postures."""
    face["current_permit_id"] = None
    if face["status"] in ("AVAILABLE", "UNDER_MAINTENANCE"):
        face["status"] = "PERMIT_SUSPENDED"
        face["booking_posture"] = "BLOCKED"
        db.touch(face)
        now = clock_now()
        for f in face_flights(face["id"]):
            if f["status"] in ("LIVE", "HOLDOVER") \
                    and f["suspension_started_at"] is None:
                f["suspension_started_at"] = now
                db.touch(f)
                campaign = db.campaigns.get(f["campaign_id"])
                if campaign is not None:
                    recompute_delivery_posture(campaign)


def restore_face_for_permit(face, permit):
    """Restoration cascade (PRD 3.2): face leaves PERMIT_SUSPENDED, suspension
    days accrue, PERMIT_SUSPENSION make-goods are auto-proposed."""
    face["current_permit_id"] = permit["id"]
    if face["status"] != "PERMIT_SUSPENDED":
        db.touch(face)
        return
    in_progress = any(w["status"] == "IN_PROGRESS"
                      for w in face_work_orders(face["id"]))
    face["status"] = "UNDER_MAINTENANCE" if in_progress else "AVAILABLE"
    face["booking_posture"] = face_posture(face["status"])
    db.touch(face)
    now = clock_now()
    for f in face_flights(face["id"]):
        if f["suspension_started_at"] is not None:
            days = (now - f["suspension_started_at"]).days
            if days < 0:
                days = 0
            f["suspension_days_accrued"] += days
            f["suspension_started_at"] = None
            db.touch(f)
            auto_make_good(f, "PERMIT_SUSPENSION",
                           calc.mg_permit_suspension(f, days))
            campaign = db.campaigns.get(f["campaign_id"])
            if campaign is not None:
                recompute_delivery_posture(campaign)


def expire_permit(permit):
    permit["status"] = "EXPIRED"
    db.touch(permit)
    face = db.faces.get(permit["face_id"])
    if face is not None and face["current_permit_id"] == permit["id"]:
        suspend_face_for_permit(face)


# ---------------------------------------------------------------------------
# Availability / occupancy (PRD 3.5)
# ---------------------------------------------------------------------------
def static_overlap_violation(face, new_start, new_end, exclude_flight_id=None):
    """STATIC changeover rule: one full free day vs every blocking flight."""
    if face["display_type"] != "STATIC":
        return False
    for f in face_flights(face["id"]):
        if exclude_flight_id is not None and f["id"] == exclude_flight_id:
            continue
        if not is_blocking(f):
            continue
        if new_start >= f["end_date"] + timedelta(days=2):
            continue
        if new_end + timedelta(days=2) <= f["start_date"]:
            continue
        return True
    return False


def loop_capacity_exceeded(face, new_start, new_end, new_slots,
                           exclude_flight_id=None):
    """Digital loop capacity: occupied + new <= loop_slots_total (PRD 3.5)."""
    if face["display_type"] != "DIGITAL":
        return False
    occupied = 0
    for f in face_flights(face["id"]):
        if exclude_flight_id is not None and f["id"] == exclude_flight_id:
            continue
        if not is_blocking(f):
            continue
        if f["start_date"] <= new_end and f["end_date"] >= new_start:
            occupied += f["loop_slots"] or 0
    return occupied + new_slots > face["loop_slots_total"]


def merged_calendar(face, include_held, from_date, to_date):
    """Merged union of occupied inclusive intervals clipped to the window.
    Adjacent intervals (no free day) merge; one free day stays split."""
    intervals = []
    for f in face_flights(face["id"]):
        if f["status"] in BLOCKING or (include_held and unexpired_held(f)):
            s = max(f["start_date"], from_date)
            e = min(f["end_date"], to_date)
            if e >= s:
                intervals.append((s, e))
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + timedelta(days=1):
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [{"start_date": s.isoformat(), "end_date": e.isoformat()}
            for s, e in merged]


# ---------------------------------------------------------------------------
# Clock sweep (PRD 2.5): four steps in fixed order.
# ---------------------------------------------------------------------------
def run_sweep():
    now = clock_now()

    # Step 1: permit aging
    for p in sorted(db.permits.values(), key=lambda r: r["_seq"]):
        if p["status"] == "ACTIVE":
            if now >= p["expires_on"]:
                expire_permit(p)
            elif p["expires_on"] - timedelta(days=30) <= now:
                p["status"] = "RENEWAL_PENDING"
                db.touch(p)
        elif p["status"] == "RENEWAL_PENDING":
            if now >= p["expires_on"]:
                expire_permit(p)

    # Step 2: hold expiry
    for f in sorted(db.flights.values(), key=lambda r: r["_seq"]):
        if f["status"] == "HELD" and now >= f["held_until"]:
            f["status"] = "EXPIRED"
            db.touch(f)
            campaign = db.campaigns.get(f["campaign_id"])
            if campaign is not None:
                check_campaign_terminal(campaign)

    # Step 3: missed-posting marking
    for f in sorted(db.flights.values(), key=lambda r: r["_seq"]):
        if f["status"] in ("BOOKED", "ART_CLEARED") \
                and now >= midnight_of(f["start_date"] + timedelta(days=3)):
            verified = any(pr["flight_id"] == f["id"] and pr["status"] == "VERIFIED"
                           for pr in db.posting_records.values())
            if not verified:
                f["status"] = "MISSED"
                db.touch(f)
                campaign = db.campaigns.get(f["campaign_id"])
                if campaign is not None:
                    recompute_delivery_posture(campaign)

    # Step 4: end-of-flight resolution
    live = [f for f in db.flights.values() if f["status"] == "LIVE"]
    live.sort(key=lambda r: (r["end_date"], r["_seq"]))
    for f in live:
        if now >= midnight_of(f["end_date"] + timedelta(days=1)):
            successor_verified = any(
                pr["status"] == "VERIFIED"
                for other in face_flights(f["face_id"]) if other["id"] != f["id"]
                for pr in db.posting_records.values()
                if pr["flight_id"] == other["id"])
            if successor_verified:
                complete_flight(f, with_holdover=False)
            else:
                f["status"] = "HOLDOVER"
                db.touch(f)
                campaign = db.campaigns.get(f["campaign_id"])
                if campaign is not None:
                    recompute_delivery_posture(campaign)
