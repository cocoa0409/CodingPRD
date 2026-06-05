"""Entity record construction, common-field management, and serializers.

Records are plain dicts. Two entities (VaccinationRecord, AppointmentAddOn) are
immutable and carry only id + created_at (PRD §2.4); all others carry
created_at, updated_at and an integer version starting at 1.
"""
from util import new_id, iso
import clock


def base_versioned():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def base_immutable():
    return {
        "id": new_id(),
        "created_at": clock.now(),
    }


def touch(rec):
    """Bump version and refresh updated_at on a versioned record."""
    rec["version"] += 1
    rec["updated_at"] = clock.now()


# ---------------------------------------------------------------------------
# Serializers — render internal dicts (datetimes as objects) into JSON-ready
# dicts (datetimes rendered ISO). Field selection matches the entity tables.
# ---------------------------------------------------------------------------

def _common(rec, immutable=False):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if not immutable:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def ser_breed(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "coat_type": r["coat_type"],
        "size_class": r["size_class"],
        "base_service_minutes": r["base_service_minutes"],
    })
    return out


def ser_service_tier(r):
    out = _common(r)
    out.update({
        "code": r["code"],
        "base_price_cents": r["base_price_cents"],
        "duration_multiplier": r["duration_multiplier"],
    })
    return out


def ser_add_on(r):
    out = _common(r)
    out.update({
        "code": r["code"],
        "price_cents": r["price_cents"],
        "duration_minutes": r["duration_minutes"],
        "requires_calm": r["requires_calm"],
    })
    return out


def ser_customer(r):
    out = _common(r)
    out.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "service_zip": r["service_zip"],
        "no_show_strikes": r["no_show_strikes"],
        "account_status": r["account_status"],
        "outstanding_fee_cents": r["outstanding_fee_cents"],
    })
    return out


def ser_pet(r):
    out = _common(r)
    out.update({
        "customer_id": r["customer_id"],
        "breed_id": r["breed_id"],
        "name": r["name"],
        "weight_lbs": r["weight_lbs"],
        "coat_condition": r["coat_condition"],
        "behavioral_flag": r["behavioral_flag"],
        "muzzle_required": r["muzzle_required"],
        "vaccination_status": r["vaccination_status"],
    })
    return out


def ser_vaccination(r):
    out = _common(r, immutable=True)
    out.update({
        "pet_id": r["pet_id"],
        "vaccine_type": r["vaccine_type"],
        "issued_on": iso(r["issued_on"]),
        "expires_on": iso(r["expires_on"]),
    })
    return out


def ser_groomer(r):
    out = _common(r)
    out.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "skill_level": r["skill_level"],
        "handles_aggressive": r["handles_aggressive"],
        "status": r["status"],
    })
    return out


def ser_van(r):
    out = _common(r)
    out.update({
        "label": r["label"],
        "max_stops": r["max_stops"],
        "has_show_equipment": r["has_show_equipment"],
    })
    return out


def ser_route_day(r):
    out = _common(r)
    out.update({
        "van_id": r["van_id"],
        "service_date": iso(r["service_date"]),
        "window_start": iso(r["window_start"]),
        "window_end": iso(r["window_end"]),
        "coverage_zip": r["coverage_zip"],
        "status": r["status"],
        "booked_minutes": r["booked_minutes"],
    })
    return out


def ser_route_stop(r):
    out = _common(r)
    out.update({
        "route_day_id": r["route_day_id"],
        "slot_start": iso(r["slot_start"]),
        "scheduled_minutes": r["scheduled_minutes"],
        "slot_end": iso(r["slot_end"]),
        "status": r["status"],
    })
    return out


def ser_appointment(r):
    out = _common(r)
    out.update({
        "pet_id": r["pet_id"],
        "service_tier_id": r["service_tier_id"],
        "route_stop_id": r["route_stop_id"],
        "groomer_id": r["groomer_id"],
        "recurring_plan_id": r["recurring_plan_id"],
        "estimated_minutes": r["estimated_minutes"],
        "quoted_price_cents": r["quoted_price_cents"],
        "final_price_cents": r["final_price_cents"],
        "quote_round": r["quote_round"],
        "status": r["status"],
    })
    return out


def ser_appointment_add_on(r):
    out = _common(r, immutable=True)
    out.update({
        "appointment_id": r["appointment_id"],
        "add_on_id": r["add_on_id"],
        "price_cents_snapshot": r["price_cents_snapshot"],
    })
    return out


def ser_recurring_plan(r):
    out = _common(r)
    out.update({
        "pet_id": r["pet_id"],
        "service_tier_id": r["service_tier_id"],
        "cadence_days": r["cadence_days"],
        "discount_pct": r["discount_pct"],
        "status": r["status"],
    })
    return out


def ser_fee_charge(r):
    out = _common(r)
    out.update({
        "customer_id": r["customer_id"],
        "appointment_id": r["appointment_id"],
        "fee_type": r["fee_type"],
        "amount_cents": r["amount_cents"],
        "settlement_status": r["settlement_status"],
    })
    return out
