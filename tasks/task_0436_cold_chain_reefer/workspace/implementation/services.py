"""Business logic: degree-minute integration, impairment, posture, fee math,
integrity scoring, claim payout, and the recompute/serialization of derived
fields (SCAFFOLD §1.3 calculations / PRD §2.8–§2.11, §3.6–§3.9).

Money is integer cents throughout; the only rounding (per-lot spoilage payout
and the integrity score) uses Decimal ROUND_HALF_UP.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    DET_TIER1_MAX,
    DOOR_FREE,
    DOOR_PENALTY,
    EXC_PER_DEGREE_HOUR,
    FREE_TIME_MIN,
    LUMPER_BASE_CENTS,
    LUMPER_MULTITEMP_SURCHARGE_CENTS,
    LUMPER_PER_PALLET_CENTS,
    PRECOOL_PENALTY,
    RATE1_CENTS,
    RATE2_CENTS,
    STOP_BUFFER_MIN,
    STOP_SERVICE_MIN,
    TOL_PARTIAL_SPAN,
)
from db import store
from models import touch


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    """Round a numeric value half-up to the nearest whole integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a numeric value half-up to 2 decimal places, returned as float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _lane_for_compartment(comp):
    return store.temp_lanes.get(comp["temp_lane_id"])


def _temp_readings_for(comp_id):
    return [
        r for r in store.sensor_readings.values()
        if r["compartment_id"] == comp_id and r["kind"] == "TEMP"
    ]


def out_of_band_magnitude(temp_c, lane):
    """How far temp_c sits beyond the nearer band bound (0 if in band)."""
    return max(
        0.0,
        temp_c - lane["setpoint_max_c"],
        lane["setpoint_min_c"] - temp_c,
    )


def _is_in_band(temp_c, lane):
    return lane["setpoint_min_c"] <= temp_c <= lane["setpoint_max_c"]


# ---------------------------------------------------------------------------
# degree_minutes_out_of_range (SCAFFOLD §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def _ordered_temp_readings(comp_id):
    readings = _temp_readings_for(comp_id)
    readings.sort(key=lambda r: (r["offset_min"], r["created_at"], r["_seq"]))
    return readings


def degree_minutes(comp, end_offset=None):
    """Step-function integration of out-of-band magnitude over TEMP readings.

    end_offset:
      - None  -> FINAL variant: the last reading's interval ends at its own
                 offset_min (closed series, no open trailing interval).
      - value -> PROVISIONAL variant: the last reading is extended to end_offset
                 (typically the current clock offset).
    """
    lane = _lane_for_compartment(comp)
    if lane is None:
        return 0.0
    readings = _ordered_temp_readings(comp["id"])
    if not readings:
        return 0.0
    total = 0.0
    n = len(readings)
    for i, r in enumerate(readings):
        if i + 1 < n:
            next_off = readings[i + 1]["offset_min"]
        elif end_offset is None:
            next_off = r["offset_min"]          # FINAL: close on last reading
        else:
            next_off = end_offset               # PROVISIONAL: extend to clock-now
        duration = max(0, next_off - r["offset_min"])
        out_mag = out_of_band_magnitude(r["temp_c"], lane)
        total += duration * out_mag
    return total


def provisional_degree_minutes(comp):
    """PROVISIONAL degree-minutes at the current logical clock offset.

    END_OFFSET is the clock-now offset relative to the shipment's IN_TRANSIT
    start. If the shipment never dispatched (no anchor), or the clock is before
    the anchor, the open trailing interval is treated as zero-width by ending at
    the last reading's own offset.
    """
    shipment = store.shipments.get(comp["shipment_id"])
    end_offset = _now_offset_min(shipment)
    if end_offset is None:
        return degree_minutes(comp, end_offset=None)
    readings = _ordered_temp_readings(comp["id"])
    if readings and end_offset < readings[-1]["offset_min"]:
        end_offset = readings[-1]["offset_min"]
    return degree_minutes(comp, end_offset=end_offset)


def _now_offset_min(shipment):
    """Clock-now expressed as minutes since the shipment's IN_TRANSIT anchor.

    Returns None when the shipment has no dispatch anchor.
    """
    if shipment is None:
        return None
    anchor = shipment.get("_in_transit_anchor")
    if anchor is None:
        return None
    delta = store.now() - anchor
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# impairment & posture (SCAFFOLD §1.3 compartment_impairment / PRD §2.8–§2.9)
# ---------------------------------------------------------------------------
def classify_impairment(deg, lane):
    tol = lane["tolerance_degree_minutes"]
    if deg <= tol:
        return "NONE"
    if deg <= tol + TOL_PARTIAL_SPAN:
        return "PARTIAL"
    return "TOTAL_LOSS"


def _live_impairment(comp):
    """Per-compartment impairment from PROVISIONAL degree-minutes (pre-deliver)."""
    lane = _lane_for_compartment(comp)
    if lane is None:
        return "NONE"
    deg = provisional_degree_minutes(comp)
    return classify_impairment(deg, lane)


def _compartments_of(shipment_id):
    comps = [c for c in store.compartments.values() if c["shipment_id"] == shipment_id]
    comps.sort(key=lambda c: (c["ordinal"], c["created_at"], c["_seq"]))
    return comps


def derive_posture_from_impairments(impairments):
    if any(i == "TOTAL_LOSS" for i in impairments):
        return "COMPROMISED"
    if any(i == "PARTIAL" for i in impairments):
        return "AT_RISK"
    return "INTACT"


def live_posture(shipment):
    """Posture derived from live (provisional) per-compartment impairment."""
    comps = _compartments_of(shipment["id"])
    if shipment["status"] == "DELIVERED":
        impairments = [c.get("impairment", "NONE") for c in comps]
    else:
        impairments = [_live_impairment(c) for c in comps]
    return derive_posture_from_impairments(impairments)


def recompute_posture_and_touch(shipment):
    """Recompute load_integrity_posture as a side effect and mutate the shipment.

    Per PRD §2.4/§2.9 a posture recomputation is a mutation: bumps version and
    refreshes updated_at. (Called on every sensor reading and door event.)
    """
    shipment["load_integrity_posture"] = live_posture(shipment)
    touch(shipment)


# ---------------------------------------------------------------------------
# DELIVER finalization (SCAFFOLD §1.2 deliver side_effects / PRD §3.8)
# ---------------------------------------------------------------------------
def finalize_on_deliver(shipment):
    """Finalize degree_minutes_out + impairment per compartment, then posture."""
    comps = _compartments_of(shipment["id"])
    impairments = []
    for comp in comps:
        lane = _lane_for_compartment(comp)
        deg = degree_minutes(comp, end_offset=None)  # FINAL
        comp["degree_minutes_out"] = deg
        imp = classify_impairment(deg, lane) if lane else "NONE"
        comp["impairment"] = imp
        impairments.append(imp)
        touch(comp)
    shipment["load_integrity_posture"] = derive_posture_from_impairments(impairments)


# ---------------------------------------------------------------------------
# precool_verified (PRD §3.4)
# ---------------------------------------------------------------------------
def compartment_has_inband_precool(comp):
    lane = _lane_for_compartment(comp)
    if lane is None:
        return False
    for r in store.sensor_readings.values():
        if (
            r["compartment_id"] == comp["id"]
            and r["kind"] == "PRECOOL"
            and r.get("temp_c") is not None
            and _is_in_band(r["temp_c"], lane)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# detention_fee (SCAFFOLD §1.3 / PRD §3.9)
# ---------------------------------------------------------------------------
def detention_fee(arrived_min, departed_min):
    dwell_min = departed_min - arrived_min
    billable_min = max(0, dwell_min - FREE_TIME_MIN)
    billable_hours = math.ceil(billable_min / 60)  # any started hour billed
    tier1_hours = min(billable_hours, DET_TIER1_MAX)
    tier2_hours = billable_hours - tier1_hours
    return tier1_hours * RATE1_CENTS + tier2_hours * RATE2_CENTS


# ---------------------------------------------------------------------------
# lumper_fee (SCAFFOLD §1.3 / PRD §3.9)
# ---------------------------------------------------------------------------
def lumper_fee(pallets_handled, compartments_touched):
    return (
        LUMPER_BASE_CENTS
        + pallets_handled * LUMPER_PER_PALLET_CENTS
        + max(0, compartments_touched - 1) * LUMPER_MULTITEMP_SURCHARGE_CENTS
    )


def recompute_shipment_fee_totals(shipment):
    """Sum closed-stop fees onto shipment totals and mutate the shipment (PRD §2.11)."""
    total_det = 0
    total_lump = 0
    for s in store.stop_events.values():
        if s["shipment_id"] == shipment["id"] and s["status"] == "CLOSED":
            total_det += s["detention_fee_cents"]
            total_lump += s["lumper_fee_cents"]
    shipment["total_detention_fee_cents"] = total_det
    shipment["total_lumper_fee_cents"] = total_lump
    touch(shipment)


# ---------------------------------------------------------------------------
# stop_window_overlap (SCAFFOLD §1.3 / PRD §3.9)
# ---------------------------------------------------------------------------
def stop_window_collides(candidate_appt, shipment_id):
    """True if the candidate buffered service window collides with any existing
    non-CLOSED stop window on the same shipment.
    """
    w_start = candidate_appt
    w_end = candidate_appt + STOP_SERVICE_MIN
    for s in store.stop_events.values():
        if s["shipment_id"] != shipment_id or s["status"] == "CLOSED":
            continue
        e_start = s["appointment_min"]
        e_end = e_start + STOP_SERVICE_MIN
        separated = (w_end + STOP_BUFFER_MIN <= e_start) or (e_end + STOP_BUFFER_MIN <= w_start)
        if not separated:
            return True
    return False


# ---------------------------------------------------------------------------
# spoilage_claim_payout (SCAFFOLD §1.3 / PRD §3.8)
# ---------------------------------------------------------------------------
def _lots_in_pinned_order(shipment_id):
    """All ProductLots under a shipment, walked compartment.ordinal ASC then
    lot.created_at ASC (ties broken by creation sequence).
    """
    comps = _compartments_of(shipment_id)
    ordered = []
    for comp in comps:
        lots = [
            lot for lot in store.product_lots.values()
            if lot["compartment_id"] == comp["id"]
        ]
        lots.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
        for lot in lots:
            ordered.append((comp, lot))
    return ordered


def _factor_for_degree_minutes(deg, lane):
    tol = lane["tolerance_degree_minutes"]
    if deg <= tol:
        return Decimal("0.0")
    if deg <= tol + TOL_PARTIAL_SPAN:
        return Decimal("0.5")
    return Decimal("1.0")


def eligible_claim_value_cents(shipment):
    """ELIGIBLE (pre-cap) claimed_value_cents: per-lot payout rounded then summed
    in the pinned walk order (uses each compartment's FINAL degree_minutes_out).
    """
    total = 0
    for comp, lot in _lots_in_pinned_order(shipment["id"]):
        lane = _lane_for_compartment(comp)
        if lane is None:
            continue
        deg = comp["degree_minutes_out"]
        factor = _factor_for_degree_minutes(deg, lane)
        lot_payout = round_half_up_int(Decimal(str(lot["declared_value_cents"])) * factor)
        total += lot_payout
    return total


def set_lot_spoilage_statuses(shipment):
    """On APPROVE, set each lot's spoilage_status per its compartment's impairment.

    NONE -> SOUND, PARTIAL -> IMPAIRED, TOTAL_LOSS -> SPOILED.
    """
    mapping = {"NONE": "SOUND", "PARTIAL": "IMPAIRED", "TOTAL_LOSS": "SPOILED"}
    for comp, lot in _lots_in_pinned_order(shipment["id"]):
        imp = comp.get("impairment", "NONE")
        lot["spoilage_status"] = mapping.get(imp, "SOUND")
        touch(lot)


# ---------------------------------------------------------------------------
# load_integrity_score (SCAFFOLD §1.3 / PRD §3.7)
# ---------------------------------------------------------------------------
def _compartment_score(comp, shipment):
    lane = _lane_for_compartment(comp)
    if shipment["status"] == "DELIVERED":
        deg = comp["degree_minutes_out"]
    else:
        deg = provisional_degree_minutes(comp)
    s = Decimal("100")
    if not compartment_has_inband_precool(comp):
        s -= Decimal(PRECOOL_PENALTY)
    door_excess = max(0, comp["door_open_events"] - DOOR_FREE)
    s -= Decimal(DOOR_PENALTY) * Decimal(door_excess)
    degree_hours = Decimal(str(deg)) / Decimal("60")
    s -= Decimal(EXC_PER_DEGREE_HOUR) * degree_hours
    if s < Decimal("0"):
        s = Decimal("0")
    if s > Decimal("100"):
        s = Decimal("100")
    return s


def integrity_report(shipment):
    """Compute the worst-link integrity score plus per-compartment breakdown."""
    comps = _compartments_of(shipment["id"])
    breakdown = []
    scores = []
    for comp in comps:
        score = _compartment_score(comp, shipment)
        scores.append(score)
        if shipment["status"] == "DELIVERED":
            deg = comp["degree_minutes_out"]
            impairment = comp.get("impairment", "NONE")
        else:
            deg = provisional_degree_minutes(comp)
            lane = _lane_for_compartment(comp)
            impairment = classify_impairment(deg, lane) if lane else "NONE"
        breakdown.append(
            {
                "compartment_id": comp["id"],
                "ordinal": comp["ordinal"],
                "degree_minutes_out": round_half_up_2dp(deg),
                "impairment": impairment,
                "door_open_events": comp["door_open_events"],
                "score": round_half_up_int(score),
            }
        )
    if scores:
        shipment_score = round_half_up_int(min(scores))
    else:
        shipment_score = 100
    posture = live_posture(shipment)
    return {
        "shipment_id": shipment["id"],
        "load_integrity_score": shipment_score,
        "load_integrity_posture": posture,
        "compartments": breakdown,
    }


# ---------------------------------------------------------------------------
# Serialization of computed fields on read (PRD §3 narratives)
# ---------------------------------------------------------------------------
def shipment_view(shipment):
    """Public view with the live posture surfaced (recomputed for non-DELIVERED)."""
    from models import serialize
    out = serialize(shipment)
    if shipment["status"] == "DELIVERED":
        out["load_integrity_posture"] = shipment["load_integrity_posture"]
    else:
        out["load_integrity_posture"] = live_posture(shipment)
    return out


def compartment_view(comp):
    """Public view with computed degree_minutes_out and impairment surfaced."""
    from models import serialize
    shipment = store.shipments.get(comp["shipment_id"])
    out = serialize(comp)
    lane = _lane_for_compartment(comp)
    if shipment is not None and shipment["status"] == "DELIVERED":
        deg = comp["degree_minutes_out"]
        out["degree_minutes_out"] = round_half_up_2dp(deg)
        out["impairment"] = comp.get("impairment", "NONE")
    else:
        deg = provisional_degree_minutes(comp)
        out["degree_minutes_out"] = round_half_up_2dp(deg)
        out["impairment"] = classify_impairment(deg, lane) if lane else "NONE"
    return out
