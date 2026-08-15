"""RateSchedule service: CRUD, publish, supersede."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_rate_schedule(body):
    required = ["code", "rate_class", "effective_from", "customer_charge_cents",
                "tiers", "demand_charge_cents_per_kw", "irrigation_offseason_discount_pct",
                "load_management_credit_cents"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    schedule = new_common({
        "code": body["code"],
        "rate_class": body["rate_class"],
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "status": "DRAFT",
        "customer_charge_cents": body["customer_charge_cents"],
        "tiers": body["tiers"],
        "demand_charge_cents_per_kw": body["demand_charge_cents_per_kw"],
        "irrigation_offseason_discount_pct": body["irrigation_offseason_discount_pct"],
        "load_management_credit_cents": body["load_management_credit_cents"],
    })
    store.rate_schedules[schedule["id"]] = schedule
    return schedule


def get_rate_schedule(schedule_id):
    s = store.rate_schedules.get(schedule_id)
    if not s:
        raise ApiError("ERR_NOT_FOUND", 404, "RateSchedule not found")
    return s


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Check if two half-open [from, to) windows overlap."""
    a_f = db.parse_iso(a_from)
    a_t = db.parse_iso(a_to) if a_to else None
    b_f = db.parse_iso(b_from)
    b_t = db.parse_iso(b_to) if b_to else None
    if a_t is None and b_t is None:
        return True
    if a_t is None:
        return b_t > a_f
    if b_t is None:
        return a_t > b_f
    return a_f < b_t and b_f < a_t


def publish_schedule(schedule_id):
    s = get_rate_schedule(schedule_id)
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Schedule must be DRAFT to publish")
    # Check overlap with other PUBLISHED schedules for same rate_class
    for other in store.rate_schedules.values():
        if (other["id"] != s["id"] and other["status"] == "PUBLISHED"
                and other["rate_class"] == s["rate_class"]):
            if _windows_overlap(s["effective_from"], s.get("effective_to"),
                                other["effective_from"], other.get("effective_to")):
                raise ApiError("ERR_RATE_OVERLAP", 409,
                               "A PUBLISHED schedule for the same rate_class has an overlapping window")
    s["status"] = "PUBLISHED"
    touch(s)
    return s


def supersede_schedule(schedule_id, body):
    s = get_rate_schedule(schedule_id)
    if s["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Schedule must be PUBLISHED to supersede")
    replacement_id = body.get("replacement_id")
    if not replacement_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "replacement_id is required")
    replacement = store.rate_schedules.get(replacement_id)
    if not replacement:
        raise ApiError("ERR_NOT_FOUND", 404, "Replacement RateSchedule not found")
    if replacement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Replacement must be in DRAFT status")
    if replacement["rate_class"] != s["rate_class"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Replacement must be for the same rate_class")
    # replacement.effective_from <= this.effective_from
    if db.parse_iso(replacement["effective_from"]) > db.parse_iso(s["effective_from"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "replacement.effective_from must be <= this schedule's effective_from")

    # Overlap check for replacement, excluding the one being superseded
    for other in store.rate_schedules.values():
        if (other["id"] not in (s["id"], replacement["id"]) and other["status"] == "PUBLISHED"
                and other["rate_class"] == replacement["rate_class"]):
            if _windows_overlap(replacement["effective_from"], replacement.get("effective_to"),
                                other["effective_from"], other.get("effective_to")):
                raise ApiError("ERR_RATE_OVERLAP", 409,
                               "Replacement would overlap an existing PUBLISHED schedule")

    # Atomic transition
    s["status"] = "SUPERSEDED"
    touch(s)
    replacement["status"] = "PUBLISHED"
    touch(replacement)

    # Recompute PROVISIONAL invoices for affected locations
    _recompute_provisional_invoices(s["rate_class"])

    return s


def _recompute_provisional_invoices(rate_class):
    """Recompute all PROVISIONAL invoices for locations on the given rate_class."""
    from services.invoice import compute_invoice_fields
    loc_ids = {loc["id"] for loc in store.service_locations.values()
               if loc.get("rate_class") == rate_class}
    for inv in store.invoices.values():
        if inv.get("service_location_id") in loc_ids and inv.get("status") == "PROVISIONAL":
            compute_invoice_fields(inv, provisional=True)
            touch(inv)


def find_published_schedule(rate_class, at_dt):
    """Find the PUBLISHED schedule for a rate_class effective at a given datetime."""
    candidates = []
    for s in store.rate_schedules.values():
        if s["rate_class"] != rate_class or s["status"] != "PUBLISHED":
            continue
        ef = db.parse_iso(s["effective_from"])
        et = db.parse_iso(s["effective_to"]) if s.get("effective_to") else None
        if ef <= at_dt and (et is None or at_dt < et):
            candidates.append(s)
    if not candidates:
        return None
    # If multiple, pick the one with the latest effective_from
    candidates.sort(key=lambda s: db.parse_iso(s["effective_from"]))
    return candidates[-1]
