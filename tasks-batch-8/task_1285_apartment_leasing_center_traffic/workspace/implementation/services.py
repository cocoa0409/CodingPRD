"""Domain services: sweeps, cascades, calculations, lookups, serializers."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, clock_now, fmt_dt, next_seq
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3 / PRD §3)
# ---------------------------------------------------------------------------
OFFER_WINDOW_HOURS = 72
SIGNING_WINDOW_HOURS = 48
OVERRIDE_FLOOR_PCT = Decimal("0.8")
INCOME_MULTIPLIER = 3
CREDIT_AUTO_APPROVE = 700
CREDIT_CONDITION_MIN = 620

COMMITTED_LEASE_STATES = ("ISSUED", "SIGNED_BY_APPLICANT", "EXECUTED")
INQUIRY_SOURCES = ("WALK_IN", "PHONE", "WEB_FORM", "ILS_LISTING", "REFERRAL")
PRORATE_METHODS = ("CALENDAR", "FIXED_30")
CONCESSION_TYPES = ("NONE", "FLAT_AMOUNT", "PERCENT_OFF", "FREE_MONTHS")


# ---------------------------------------------------------------------------
# Common field lifecycle
# ---------------------------------------------------------------------------
def stamp(rec):
    now = clock_now()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()


def touch(rec):
    rec["updated_at"] = clock_now()
    rec["version"] += 1


def sorted_created(items):
    """List order: creation timestamp ascending, creation order as tie-break."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Lookups (existence errors per scaffold error catalog)
# ---------------------------------------------------------------------------
def _lookup(table, rid, error_id, label):
    rec = DB[table].get(rid)
    if rec is None:
        raise ApiError(error_id, 404, f"{label} does not exist")
    return rec


def get_property(rid):
    return _lookup("properties", rid, "ERR_PROPERTY_NOT_FOUND", "Property")


def get_agent(rid):
    return _lookup("agents", rid, "ERR_AGENT_NOT_FOUND", "Agent")


def get_floorplan(rid):
    return _lookup("floorplans", rid, "ERR_FLOORPLAN_NOT_FOUND", "Floorplan")


def get_offer(rid):
    return _lookup("offers", rid, "ERR_PRICING_OFFER_NOT_FOUND", "Pricing offer")


def get_inquiry(rid):
    return _lookup("inquiries", rid, "ERR_INQUIRY_NOT_FOUND", "Inquiry")


def get_tour(rid):
    return _lookup("tours", rid, "ERR_TOUR_NOT_FOUND", "Tour")


def get_waitlist_entry(rid):
    return _lookup("waitlist_entries", rid, "ERR_WAITLIST_ENTRY_NOT_FOUND", "Waitlist entry")


def get_application(rid):
    return _lookup("applications", rid, "ERR_APPLICATION_NOT_FOUND", "Application")


def get_lease(rid):
    return _lookup("leases", rid, "ERR_LEASE_NOT_FOUND", "Lease")


def get_movein(rid):
    return _lookup("moveins", rid, "ERR_MOVE_IN_NOT_FOUND", "Move-in")


# ---------------------------------------------------------------------------
# Availability ledger (computed on read — PRD §2.7)
# ---------------------------------------------------------------------------
def committed_units(floorplan_id):
    return sum(
        1
        for l in DB["leases"].values()
        if l["floorplan_id"] == floorplan_id and l["status"] in COMMITTED_LEASE_STATES
    )


def available_units(fp):
    return fp["total_units"] - committed_units(fp["id"])


def published_offer_for(floorplan_id):
    """The floorplan's single PUBLISHED offer, if any (post-sweep state)."""
    for o in sorted_created(DB["offers"].values()):
        if o["floorplan_id"] == floorplan_id and o["status"] == "PUBLISHED":
            return o
    return None


def offered_count(floorplan_id):
    return sum(
        1
        for e in DB["waitlist_entries"].values()
        if e["floorplan_id"] == floorplan_id and e["status"] == "OFFERED"
    )


def effective_available_units(fp):
    return available_units(fp) - offered_count(fp["id"])


# ---------------------------------------------------------------------------
# Waitlist queue helpers (scaffold: waitlist_position_assignment)
# ---------------------------------------------------------------------------
def next_position(floorplan_id, exclude_id=None):
    """max(position of OTHER entries in WAITING/OFFERED) + 1; 1 when none."""
    best = 0
    for e in DB["waitlist_entries"].values():
        if (
            e["floorplan_id"] == floorplan_id
            and e["status"] in ("WAITING", "OFFERED")
            and e["id"] != exclude_id
        ):
            best = max(best, e["position"])
    return best + 1


def queue_head(floorplan_id):
    """WAITING entry with min position, tie-break created_at ASC; None if empty."""
    waiting = [
        e
        for e in DB["waitlist_entries"].values()
        if e["floorplan_id"] == floorplan_id and e["status"] == "WAITING"
    ]
    if not waiting:
        return None
    waiting.sort(key=lambda e: (e["position"], e["created_at"], e["_seq"]))
    return waiting[0]


def promote_entry(entry):
    entry["status"] = "OFFERED"
    entry["offer_expires_at"] = clock_now() + timedelta(hours=OFFER_WINDOW_HOURS)
    touch(entry)


def auto_promote(floorplan_id):
    """Availability-driven promotion of the queue head (one per freeing event)."""
    fp = DB["floorplans"].get(floorplan_id)
    if fp is None:
        return
    head = queue_head(floorplan_id)
    if head is None:
        return
    if effective_available_units(fp) >= 1:
        promote_entry(head)


def requeue_entry(entry):
    """OFFERED -> WAITING: requeue to the back of the queue, expiry cleared."""
    entry["status"] = "WAITING"
    entry["offer_expires_at"] = None
    entry["position"] = next_position(entry["floorplan_id"], exclude_id=entry["id"])
    touch(entry)


# ---------------------------------------------------------------------------
# Lazy expiry sweeps (PRD §2.4) — run at the start of every request
# ---------------------------------------------------------------------------
def sweep_all():
    now = clock_now()
    # Waitlist offer expiry: OFFERED -> WAITING requeue (>= offer_expires_at).
    for e in list(DB["waitlist_entries"].values()):
        if (
            e["status"] == "OFFERED"
            and e["offer_expires_at"] is not None
            and now >= e["offer_expires_at"]
        ):
            requeue_entry(e)
    # Pricing offer expiry: PUBLISHED -> EXPIRED (>= expires_at).
    for o in list(DB["offers"].values()):
        if o["status"] == "PUBLISHED" and now >= o["expires_at"]:
            o["status"] = "EXPIRED"
            touch(o)
    # Lease signing-deadline expiry: ISSUED -> EXPIRED (>= signing_deadline);
    # the freed unit may auto-promote the waitlist queue head.
    for l in list(DB["leases"].values()):
        if l["status"] == "ISSUED" and now >= l["signing_deadline"]:
            l["status"] = "EXPIRED"
            touch(l)
            auto_promote(l["floorplan_id"])


# ---------------------------------------------------------------------------
# Cross-entity cascades (PRD §2.9)
# ---------------------------------------------------------------------------
def cancel_scheduled_tours(inquiry):
    for t in DB["tours"].values():
        if t["inquiry_id"] == inquiry["id"] and t["status"] == "SCHEDULED":
            t["status"] = "CANCELLED"
            touch(t)


def maybe_revert_inquiry(inquiry):
    """TOUR_SCHEDULED -> CONTACTED when no SCHEDULED tour remains (guarded)."""
    if inquiry["status"] != "TOUR_SCHEDULED":
        return
    remaining = any(
        t["inquiry_id"] == inquiry["id"] and t["status"] == "SCHEDULED"
        for t in DB["tours"].values()
    )
    if not remaining:
        inquiry["status"] = "CONTACTED"
        touch(inquiry)


def conversion_cascade(application):
    """Lease EXECUTED: Application -> LEASED; source Inquiry -> CONVERTED; its
    remaining SCHEDULED tours -> CANCELLED."""
    if application["status"] in ("APPROVED", "CONDITIONS_CLEARED"):
        application["status"] = "LEASED"
        touch(application)
    if application["inquiry_id"]:
        inquiry = DB["inquiries"].get(application["inquiry_id"])
        if inquiry is not None and inquiry["status"] in ("CONTACTED", "TOUR_SCHEDULED"):
            inquiry["status"] = "CONVERTED"
            touch(inquiry)
            cancel_scheduled_tours(inquiry)


def lease_cancel_cascade(lease, was_executed):
    """Unwind chain: active move-ins cancelled; LEASED application compensates
    back to APPROVED (EXECUTED only); freed unit may auto-promote the head."""
    for m in DB["moveins"].values():
        if m["lease_id"] == lease["id"] and m["status"] in ("SCHEDULED", "READY"):
            m["status"] = "CANCELLED"
            touch(m)
    if was_executed:
        application = DB["applications"].get(lease["application_id"])
        if application is not None and application["status"] == "LEASED":
            application["status"] = "APPROVED"
            touch(application)
    auto_promote(lease["floorplan_id"])


# ---------------------------------------------------------------------------
# Calculations (scaffold §1.3) — integer cents, round-half-up via Decimal
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def effective_monthly_rent(base_rent_cents, concession_type, concession_value, lease_term_months):
    base = Decimal(base_rent_cents)
    value = Decimal(str(concession_value))
    if concession_type == "NONE":
        return int(base)
    if concession_type == "FLAT_AMOUNT":
        return max(0, round_half_up_cents(base - value))
    if concession_type == "PERCENT_OFF":
        return round_half_up_cents(base * (Decimal(100) - value) / Decimal(100))
    if concession_type == "FREE_MONTHS":
        term = Decimal(lease_term_months)
        billed = max(Decimal(0), term - min(value, term))
        return round_half_up_cents(base * billed / term)
    raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown concession_type")


def prorated_first_month_rent(monthly_rent_cents, scheduled_dt, prorate_method):
    """Daily rate rounded half-up to whole cents FIRST, then multiplied by the
    occupied-day count (pinned rounding order, PRD §2.6)."""
    day = scheduled_dt.day
    if prorate_method == "CALENDAR":
        divisor = calendar.monthrange(scheduled_dt.year, scheduled_dt.month)[1]
        days_occupied = divisor - day + 1
    else:  # FIXED_30
        divisor = 30
        days_occupied = 30 - min(day, 30) + 1
    daily_rate = round_half_up_cents(Decimal(monthly_rent_cents) / Decimal(divisor))
    return daily_rate * days_occupied


def screening_recommendation(annual_income_cents, credit_score, monthly_rent_snapshot_cents):
    income_ok = annual_income_cents >= INCOME_MULTIPLIER * 12 * monthly_rent_snapshot_cents
    if income_ok and credit_score >= CREDIT_AUTO_APPROVE:
        return "APPROVE"
    if income_ok and credit_score >= CREDIT_CONDITION_MIN:
        return "CONDITION"
    return "DENY"


def response_met_target(inquiry, prop, responded_at):
    elapsed_seconds = (responded_at - inquiry["created_at"]).total_seconds()
    elapsed_minutes = int(elapsed_seconds // 60)  # truncated to whole minutes
    return elapsed_minutes <= prop["response_time_target_minutes"]


def closing_ratio_pct(closed, denominator):
    return float(
        (Decimal(100) * Decimal(closed) / Decimal(denominator)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


# ---------------------------------------------------------------------------
# Serializers (whitelisted fields; internal dt objects -> ISO strings)
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_property(p):
    out = {
        "name": p["name"],
        "code": p["code"],
        "response_time_target_minutes": p["response_time_target_minutes"],
        "tour_buffer_minutes": p["tour_buffer_minutes"],
        "self_guided_window_minutes": p["self_guided_window_minutes"],
        "max_moveins_per_day": p["max_moveins_per_day"],
        "utility_transfer_required": p["utility_transfer_required"],
        "prorate_method": p["prorate_method"],
        "required_addenda": list(p["required_addenda"]),
    }
    out.update(_common(p))
    return out


def ser_agent(a):
    out = {
        "full_name": a["full_name"],
        "email": a["email"],
        "property_id": a["property_id"],
        "max_concurrent_tours": a["max_concurrent_tours"],
        "active": a["active"],
    }
    out.update(_common(a))
    return out


def ser_floorplan(f):
    out = {
        "property_id": f["property_id"],
        "name": f["name"],
        "bedrooms": f["bedrooms"],
        "base_rent_cents": f["base_rent_cents"],
        "total_units": f["total_units"],
        "committed_units": committed_units(f["id"]),
        "available_units": available_units(f),
    }
    out.update(_common(f))
    return out


def ser_offer(o):
    out = {
        "property_id": o["property_id"],
        "floorplan_id": o["floorplan_id"],
        "base_rent_cents": o["base_rent_cents"],
        "concession_type": o["concession_type"],
        "concession_value": o["concession_value"],
        "lease_term_months": o["lease_term_months"],
        "effective_start": fmt_dt(o["effective_start"]),
        "expires_at": fmt_dt(o["expires_at"]),
        "effective_monthly_rent_cents": o["effective_monthly_rent_cents"],
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def ser_inquiry(i):
    out = {
        "property_id": i["property_id"],
        "floorplan_id": i["floorplan_id"],
        "contact_name": i["contact_name"],
        "contact_email": i["contact_email"],
        "source": i["source"],
        "assigned_agent_id": i["assigned_agent_id"],
        "first_responded_at": fmt_dt(i["first_responded_at"]),
        "response_met_target": i["response_met_target"],
        "status": i["status"],
    }
    out.update(_common(i))
    return out


def ser_tour(t):
    out = {
        "inquiry_id": t["inquiry_id"],
        "agent_id": t["agent_id"],
        "tour_type": t["tour_type"],
        "scheduled_start": fmt_dt(t["scheduled_start"]),
        "scheduled_end": fmt_dt(t["scheduled_end"]),
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_waitlist_entry(e):
    out = {
        "floorplan_id": e["floorplan_id"],
        "contact_name": e["contact_name"],
        "contact_email": e["contact_email"],
        "position": e["position"],
        "offer_expires_at": fmt_dt(e["offer_expires_at"]),
        "linked_application_id": e["linked_application_id"],
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def ser_application(a):
    out = {
        "inquiry_id": a["inquiry_id"],
        "waitlist_entry_id": a["waitlist_entry_id"],
        "floorplan_id": a["floorplan_id"],
        "applicant_name": a["applicant_name"],
        "applicant_email": a["applicant_email"],
        "annual_income_cents": a["annual_income_cents"],
        "credit_score": a["credit_score"],
        "monthly_rent_snapshot_cents": a["monthly_rent_snapshot_cents"],
        "recommendation": a["recommendation"],
        "required_deposit_cents": a["required_deposit_cents"],
        "deposit_paid_cents": a["deposit_paid_cents"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def ser_lease(l):
    out = {
        "application_id": l["application_id"],
        "floorplan_id": l["floorplan_id"],
        "monthly_rent_cents": l["monthly_rent_cents"],
        "deposit_cents": l["deposit_cents"],
        "addenda_codes": list(l["addenda_codes"]),
        "signing_deadline": fmt_dt(l["signing_deadline"]),
        "signed_at": fmt_dt(l["signed_at"]),
        "executed_at": fmt_dt(l["executed_at"]),
        "superseded_by_id": l["superseded_by_id"],
        "status": l["status"],
    }
    out.update(_common(l))
    return out


def ser_movein(m):
    out = {
        "lease_id": m["lease_id"],
        "scheduled_date": fmt_dt(m["scheduled_date"]),
        "utility_confirmed": m["utility_confirmed"],
        "prorated_rent_cents": m["prorated_rent_cents"],
        "status": m["status"],
    }
    out.update(_common(m))
    return out
