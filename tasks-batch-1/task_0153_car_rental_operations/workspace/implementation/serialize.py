"""Public serialization of entities.

Each serializer projects an internal record into the exact field set the PRD
declares, computing derived fields (counts, balances, etc.) from the live store.
Internal bookkeeping (_seq) is never exposed.
"""
import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def _audit_common(record):
    return {"id": record["id"], "created_at": record["created_at"]}


def location(record):
    out = _common(record)
    out.update(
        {
            "code": record["code"],
            "name": record["name"],
            "one_way_drop_fee_cents": record["one_way_drop_fee_cents"],
            "young_driver_surcharge_per_day_cents": record[
                "young_driver_surcharge_per_day_cents"
            ],
        }
    )
    return out


def _class_counts(class_id):
    total = 0
    available = 0
    for v in db.vehicles.values():
        if v["class_id"] != class_id:
            continue
        if v["status"] != "RETIRED":
            total += 1
        if v["status"] == "AVAILABLE":
            available += 1
    return total, available


def vehicle_class(record):
    total, available = _class_counts(record["id"])
    out = _common(record)
    out.update(
        {
            "code": record["code"],
            "tier_rank": record["tier_rank"],
            "daily_rate_cents": record["daily_rate_cents"],
            "weekly_rate_cents": record["weekly_rate_cents"],
            "included_miles_per_day": record["included_miles_per_day"],
            "overage_per_mile_cents": record["overage_per_mile_cents"],
            "ldw_per_day_cents": record["ldw_per_day_cents"],
            "pai_per_day_cents": record["pai_per_day_cents"],
            "total_count": total,
            "available_count": available,
        }
    )
    return out


def rate_plan(record):
    out = _common(record)
    out.update(
        {
            "location_id": record["location_id"],
            "class_id": record["class_id"],
            "daily_rate_cents": record["daily_rate_cents"],
            "weekly_rate_cents": record["weekly_rate_cents"],
            "active": record["active"],
            "effective_from": record["effective_from"],
        }
    )
    return out


def vehicle(record):
    out = _common(record)
    out.update(
        {
            "location_id": record["location_id"],
            "class_id": record["class_id"],
            "plate": record["plate"],
            "status": record["status"],
            "odometer_miles": record["odometer_miles"],
            "fuel_level_eighths": record["fuel_level_eighths"],
            "held_by_reservation_id": record["held_by_reservation_id"],
        }
    )
    return out


def member_points(member_id):
    """Compute (points_balance, lifetime_points) from accrual rows.

    The set_loyalty test capability can pin these directly; when pinned we honor
    the override, otherwise derive from LoyaltyAccrual history.
    """
    balance = 0
    lifetime = 0
    for a in db.loyalty_accruals.values():
        if a["member_id"] != member_id:
            continue
        balance += a["delta_points"]
        if a["kind"] == "ACCRUAL":
            lifetime += a["delta_points"]
    return balance, lifetime


def member_no_show_strikes(member_id):
    count = 0
    for r in db.reservations.values():
        if r["member_id"] == member_id and r["status"] == "NO_SHOW":
            count += 1
    return count


def member(record):
    out = _common(record)
    if record.get("_lifetime_override") is not None:
        lifetime = record["_lifetime_override"]
    else:
        _, lifetime = member_points(record["id"])
    if record.get("_balance_override") is not None:
        balance = record["_balance_override"]
    else:
        balance, _ = member_points(record["id"])
    if record.get("_strikes_override") is not None:
        strikes = record["_strikes_override"]
    else:
        strikes = member_no_show_strikes(record["id"])
    out.update(
        {
            "email": record["email"],
            "full_name": record["full_name"],
            "driver_age": record["driver_age"],
            "tier": record["tier"],
            "points_balance": balance,
            "lifetime_points": lifetime,
            "no_show_strikes": strikes,
        }
    )
    return out


def reservation(record):
    out = _common(record)
    out.update(
        {
            "member_id": record["member_id"],
            "pickup_location_id": record["pickup_location_id"],
            "dropoff_location_id": record["dropoff_location_id"],
            "class_id": record["class_id"],
            "pickup_at": record["pickup_at"],
            "dropoff_at": record["dropoff_at"],
            "rental_days": record["rental_days"],
            "ldw_selected": record["ldw_selected"],
            "pai_selected": record["pai_selected"],
            "status": record["status"],
            "quoted_total_cents": record["quoted_total_cents"],
            "hold_expires_at": record["hold_expires_at"],
        }
    )
    return out


def agreement(record):
    out = _common(record)
    out.update(
        {
            "reservation_id": record["reservation_id"],
            "vehicle_id": record["vehicle_id"],
            "odometer_out": record["odometer_out"],
            "fuel_out_eighths": record["fuel_out_eighths"],
            "odometer_in": record["odometer_in"],
            "fuel_in_eighths": record["fuel_in_eighths"],
            "status": record["status"],
            "final_total_cents": record["final_total_cents"],
            "miles_driven": record["miles_driven"],
        }
    )
    return out


def incident(record):
    out = _common(record)
    out.update(
        {
            "agreement_id": record["agreement_id"],
            "severity": record["severity"],
            "assessed_damage_cents": record["assessed_damage_cents"],
            "member_liability_cents": record["member_liability_cents"],
            "status": record["status"],
        }
    )
    return out


def ledger_entry(record):
    out = _audit_common(record)
    out.update(
        {
            "agreement_id": record["agreement_id"],
            "kind": record["kind"],
            "amount_cents": record["amount_cents"],
            "memo": record["memo"],
        }
    )
    return out


def loyalty_accrual(record):
    out = _audit_common(record)
    out.update(
        {
            "member_id": record["member_id"],
            "agreement_id": record["agreement_id"],
            "kind": record["kind"],
            "delta_points": record["delta_points"],
        }
    )
    return out
