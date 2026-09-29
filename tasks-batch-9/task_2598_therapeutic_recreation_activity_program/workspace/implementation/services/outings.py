"""Outing manifests, escort supervision, seat waterfall, consent derivation."""
from datetime import timedelta

from db import overlaps, parse_date, parse_datetime
from services import constants as C
from services.numbers import ceil_int, dec, divide, rhu

VEHICLE_BLOCKING = ("TRANSPORT_BOOKED", "READY", "DEPARTED", "RETURNED")
CLOSED_LOGISTICS = ("DEPARTED", "RETURNED", "CANCELLED")


def outing_consents(st, outing_id):
    return [c for c in st.consents.values() if c["outing_id"] == outing_id]


def manifest_rows(st, outing_id):
    return [
        c for c in outing_consents(st, outing_id) if c["status"] in ("REQUESTED", "GRANTED")
    ]


def departure_date(outing):
    return parse_datetime(outing["departure_at"]).date()


def consent_effective(consent, outing):
    if consent["status"] != "GRANTED":
        return False
    expires_on = consent.get("expires_on")
    if expires_on is None:
        return True
    return parse_date(expires_on) >= departure_date(outing)


def derive_consent_status(st, outing):
    rows = outing_consents(st, outing["id"])
    if any(row["status"] == "DENIED" for row in rows):
        return "CONSENT_BLOCKED"
    manifest = [row for row in rows if row["status"] in ("REQUESTED", "GRANTED")]
    if not manifest:
        return "COLLECTING"
    for row in manifest:
        if row["status"] != "GRANTED" or not consent_effective(row, outing):
            return "COLLECTING"
    return "CONSENT_COMPLETE"


def rider_tier(st, consent):
    resident = st.residents.get(consent["resident_id"])
    return resident.get("supervision_tier") if resident else None


def rider_mobility(st, consent):
    resident = st.residents.get(consent["resident_id"])
    return resident.get("functional_mobility") if resident else None


def supervision(st, outing):
    """Weighted load over the manifest, escorts at 1 per 4, TIER_3 floor 2."""
    manifest = manifest_rows(st, outing["id"])
    total = dec(0)
    has_tier_3 = False
    for consent in manifest:
        tier = rider_tier(st, consent)
        if tier is None:
            continue
        total += dec(C.TIER_WEIGHT[tier])
        if tier == "TIER_3":
            has_tier_3 = True
    load = rhu(total, 2)
    base = ceil_int(divide(load, C.OUTING_RATIO_DENOMINATOR))
    escorts = max(base, C.TIER_3_ESCORT_FLOOR) if has_tier_3 else base
    return float(load), escorts


def reserved_by_others(st, vehicle_id, exclude_outing_id):
    amb = 0
    wheelchair = 0
    for outing in st.outings.values():
        if outing["vehicle_id"] != vehicle_id:
            continue
        if outing["id"] == exclude_outing_id:
            continue
        if outing["logistics_status"] not in C.RESERVING_LOGISTICS:
            continue
        amb += outing["ambulatory_seats_required"]
        wheelchair += outing["wheelchair_seats_required"]
    return amb, wheelchair


def seat_allocation(st, outing):
    """Wheelchair demand first, then convert up to two spare stations."""
    vehicle = st.vehicles[outing["vehicle_id"]]
    manifest = manifest_rows(st, outing["id"])
    wc_demand = 0
    amb_riders = 0
    for consent in manifest:
        if rider_mobility(st, consent) == "WHEELCHAIR_DEPENDENT":
            wc_demand += 1
        else:
            amb_riders += 1
    amb_demand = amb_riders + outing["escort_count"]

    other_amb, other_wc = reserved_by_others(st, vehicle["id"], outing["id"])
    free_wc = max(0, vehicle["wheelchair_stations"] - other_wc)
    free_amb = max(0, vehicle["ambulatory_seats"] - other_amb)

    wheelchair_shortfall = max(0, wc_demand - free_wc)
    stations_left = max(0, free_wc - wc_demand)
    converted = min(stations_left, C.MAX_STATION_CONVERSIONS)
    ambulatory_shortfall = max(0, amb_demand - (free_amb + converted))
    return {
        "ambulatory_seats_required": amb_demand,
        "wheelchair_seats_required": wc_demand,
        "seat_shortfall_total": wheelchair_shortfall + ambulatory_shortfall,
    }


def apply_supervision(st, outing, ctx):
    load, escorts = supervision(st, outing)
    ctx.set_fields(
        outing, {"weighted_supervision_load": load, "required_escorts": escorts}
    )


def apply_seat_allocation(st, outing, ctx):
    ctx.set_fields(outing, seat_allocation(st, outing))


def recompute_counts(st, outing, ctx):
    ctx.set_fields(
        outing,
        {
            "roster_count": len(outing_consents(st, outing["id"])),
            "manifest_count": len(manifest_rows(st, outing["id"])),
        },
    )


def recompute_vehicle_reservations(st, vehicle, ctx, force_bump=False):
    amb = 0
    wheelchair = 0
    for outing in st.outings.values():
        if outing["vehicle_id"] != vehicle["id"]:
            continue
        if outing["logistics_status"] not in C.RESERVING_LOGISTICS:
            continue
        amb += outing["ambulatory_seats_required"]
        wheelchair += outing["wheelchair_seats_required"]
    values = {
        "reserved_ambulatory_seats": amb,
        "reserved_wheelchair_stations": wheelchair,
    }
    if force_bump:
        for key, value in values.items():
            vehicle[key] = value
        ctx.bump(vehicle)
    else:
        ctx.set_fields(vehicle, values)


def vehicle_conflict(st, vehicle, outing):
    """Turnaround widens each interval forward, after the return."""
    turnaround = timedelta(minutes=vehicle.get("turnaround_minutes", 0) or 0)
    lo = parse_datetime(outing["departure_at"])
    hi = parse_datetime(outing["return_at"]) + turnaround
    for other in st.outings.values():
        if other["id"] == outing["id"] or other["vehicle_id"] != vehicle["id"]:
            continue
        if other["logistics_status"] not in VEHICLE_BLOCKING:
            continue
        o_lo = parse_datetime(other["departure_at"])
        o_hi = parse_datetime(other["return_at"]) + turnaround
        if overlaps(lo, hi, o_lo, o_hi):
            return other
    return None


def manifest_all_effective(st, outing):
    manifest = manifest_rows(st, outing["id"])
    return all(consent_effective(row, outing) for row in manifest)
