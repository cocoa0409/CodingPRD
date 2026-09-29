"""Immediate re-derivation and the cascades of PRD sections 2.10, 3.7 and 3.8.

Every mutating request ends by re-deriving the whole world to a fixed point. A row
is only marked dirty when a value genuinely changes, so re-deriving rows a request
did not touch can never invent a spurious version bump.
"""
from flask import g

import calc
import db
from db import mark, set_field, store
from util import add_hours, dt_of, fmt_dt, minutes_between

COORDINATED = "LEVEL_3_COORDINATED"


def station(station_id):
    return store.get("stations", station_id)


def legs_of_version(version_id):
    return [leg for leg in store.values("flight_legs") if leg["schedule_version_id"] == version_id]


def active(legs):
    return [leg for leg in legs if leg["status"] != "CANCELLED"]


def legs_of_aircraft(aircraft_id):
    return [
        leg for leg in store.values("flight_legs")
        if leg["assigned_aircraft_id"] == aircraft_id and leg["status"] != "CANCELLED"
    ]


def required_slot_set(leg):
    """Which movements of this leg need a slot, given its endpoints' coordination."""
    required = set()
    origin = station(leg["origin_station_id"])
    dest = station(leg["dest_station_id"])
    if origin and origin["coordination_level"] == COORDINATED:
        required.add("DEPARTURE")
    if dest and dest["coordination_level"] == COORDINATED:
        required.add("ARRIVAL")
    return required


def is_fully_slotted(leg):
    required = required_slot_set(leg)
    if "DEPARTURE" in required and not leg["departure_slot_holding_id"]:
        return False
    if "ARRIVAL" in required and not leg["arrival_slot_holding_id"]:
        return False
    return True


def leg_is_international(leg):
    origin = station(leg["origin_station_id"])
    dest = station(leg["dest_station_id"])
    if not origin or not dest:
        return False
    return origin["country_code"] != dest["country_code"]


def connect_figures(leg, upstream):
    """(connect_minutes, mct_shortfall_minutes) for a designated connection."""
    if upstream is None:
        return None, 0
    connecting = station(upstream["dest_station_id"])
    connect_minutes = minutes_between(dt_of(upstream["arr_utc"]), dt_of(leg["dep_utc"]))
    if connecting is None:
        return connect_minutes, 0
    if leg_is_international(upstream) or leg_is_international(leg):
        required = connecting["min_connect_international_minutes"]
    else:
        required = connecting["min_connect_domestic_minutes"]
    shortfall = required - connect_minutes
    return connect_minutes, shortfall if shortfall > 0 else 0


def recompute_leg(leg):
    changed = False
    changed |= set_field(leg, "block_minutes", minutes_between(dt_of(leg["dep_utc"]), dt_of(leg["arr_utc"])))
    changed |= set_field(leg, "is_international", leg_is_international(leg))
    upstream = store.get("flight_legs", leg["connects_from_leg_id"]) if leg["connects_from_leg_id"] else None
    connect_minutes, shortfall = connect_figures(leg, upstream)
    changed |= set_field(leg, "connect_minutes", connect_minutes)
    changed |= set_field(leg, "mct_shortfall_minutes", shortfall)
    open_count = len([
        o for o in store.values("notification_obligations")
        if o["flight_leg_id"] == leg["id"] and o["status"] == "PENDING"
    ])
    changed |= set_field(leg, "open_obligation_count", open_count)
    if changed:
        mark(leg)
    return changed


def recompute_holding(holding):
    changed = False
    planned = holding["series_weeks"] * len(holding["days_of_week"])
    attached = len([
        leg for leg in store.values("flight_legs")
        if leg["status"] != "CANCELLED"
        and holding["id"] in (leg["departure_slot_holding_id"], leg["arrival_slot_holding_id"])
    ])
    credited = len([
        record for record in store.values("slot_utilization_records")
        if record["slot_holding_id"] == holding["id"] and record["credited"]
    ])
    changed |= set_field(holding, "planned_operations", planned)
    changed |= set_field(holding, "attached_operations", attached)
    changed |= set_field(holding, "credited_operations", credited)
    changed |= set_field(holding, "utilization_pct", calc.pct(credited, planned))
    as_filed = calc.pct(attached, planned)
    changed |= set_field(holding, "utilization_pct_as_filed", as_filed)
    at_risk = (
        holding["holding_status"] == "HELD"
        and attached >= 1
        and as_filed < calc.UTILIZATION_THRESHOLD
    )
    changed |= set_field(holding, "at_risk_of_loss", at_risk)
    if changed:
        mark(holding)
    return changed


def recompute_aircraft(aircraft):
    changed = False
    legs = legs_of_aircraft(aircraft["id"])
    status, _, _, _ = calc.rotation_walk(aircraft, legs, station)
    contiguous, cumulative = calc.maintenance_windows(legs, station)
    changed |= set_field(aircraft, "assigned_leg_count", len(legs))
    changed |= set_field(aircraft, "rotation_feasibility_status", status)
    changed |= set_field(aircraft, "maintenance_opportunity_minutes", contiguous)
    changed |= set_field(aircraft, "cumulative_ground_minutes", cumulative)
    if changed:
        mark(aircraft)
    return changed


def rotation_view(aircraft):
    legs = legs_of_aircraft(aircraft["id"])
    status, violation, first_turn, total_block = calc.rotation_walk(aircraft, legs, station)
    contiguous, cumulative = calc.maintenance_windows(legs, station)
    ordered = sorted(legs, key=calc.leg_order_key)
    return {
        "rotation_feasibility_status": status,
        "maintenance_opportunity_minutes": contiguous,
        "cumulative_ground_minutes": cumulative,
        "ordered_leg_ids": [leg["id"] for leg in ordered],
        "first_violation_leg_id": violation,
        "required_turn_minutes": first_turn,
        "total_block_minutes": total_block,
    }


def gate_overflow_count(legs):
    overflow = 0
    for station_id, day in sorted(calc.station_date_pairs(legs)):
        stn = station(station_id)
        if stn is None:
            continue
        peak = calc.peak_concurrency(calc.gate_intervals(legs, station_id, day))
        if peak > stn["gate_count"]:
            overflow += 1
    return overflow


def marketing_carriers_of_version(version_id):
    required = []
    for leg in active(legs_of_version(version_id)):
        for carrier_id in leg["marketing_carrier_ids"]:
            if carrier_id not in required:
                required.append(carrier_id)
    return required


def recompute_submission(submission):
    """codeshare_sync_status reads the version's current legs, never a frozen list."""
    changed = False
    required = marketing_carriers_of_version(submission["schedule_version_id"])
    if not required:
        status = "NOT_REQUIRED"
    elif all(carrier_id in submission["codeshare_ack_carrier_ids"] for carrier_id in required):
        status = "SYNCHRONIZED"
    else:
        status = "PENDING_ACK"
    changed |= set_field(submission, "codeshare_sync_status", status)
    if changed:
        mark(submission)
    return changed


def submissions_of_version(version_id):
    return [s for s in store.values("filing_submissions") if s["schedule_version_id"] == version_id]


def recompute_version(version):
    """Seven counters, the score, the posture, and the two posture cascades."""
    changed = False
    legs = legs_of_version(version["id"])
    live = active(legs)

    counters = {
        "leg_count": len(legs),
        "unslotted_leg_count": len([
            leg for leg in live
            if leg["status"] == "REFILE_REQUIRED" or not is_fully_slotted(leg)
        ]),
        "curfew_violation_count": len([
            leg for leg in live if leg["curfew_waiver_reference"] is not None
        ]),
        "mct_violation_count": len([
            leg for leg in live
            if leg["connects_from_leg_id"] and leg["mct_shortfall_minutes"] > 0
        ]),
        "gate_overflow_count": gate_overflow_count(live),
        "at_risk_slot_count": 0,
    }

    at_risk = set()
    for leg in live:
        for field in ("departure_slot_holding_id", "arrival_slot_holding_id"):
            holding = store.get("slot_holdings", leg[field])
            if holding is not None and holding["at_risk_of_loss"]:
                at_risk.add(holding["id"])
    counters["at_risk_slot_count"] = len(at_risk)

    for field, value in counters.items():
        changed |= set_field(version, field, value)

    score = calc.compliance_score(counters)
    changed |= set_field(version, "schedule_compliance_score", score)

    accrued = sum(
        submission["total_charge_cents"]
        for submission in submissions_of_version(version["id"])
        if submission["status"] in ("TRANSMITTED", "ACKNOWLEDGED")
    )
    changed |= set_field(version, "filing_charge_accrued_cents", accrued)

    previous = version["compliance_state"]
    posture = calc.compliance_state(score, counters["at_risk_slot_count"])
    if posture != previous:
        version["compliance_state"] = posture
        changed = True
        if posture == "WARNED" and previous == "CLEAN":
            flag_resync(version)
        elif posture == "BLOCKED":
            blocked_cascade(version)
        # The cascade can move the ledger, so settle it again.
        accrued = sum(
            submission["total_charge_cents"]
            for submission in submissions_of_version(version["id"])
            if submission["status"] in ("TRANSMITTED", "ACKNOWLEDGED")
        )
        set_field(version, "filing_charge_accrued_cents", accrued)

    if changed:
        mark(version)
    return changed


def flag_resync(version):
    """CLEAN -> WARNED: acknowledged filings are stale but stay ACKNOWLEDGED."""
    for submission in submissions_of_version(version["id"]):
        if submission["status"] == "ACKNOWLEDGED" and not submission["resync_required"]:
            submission["resync_required"] = True
            mark(submission)


def blocked_cascade(version):
    """Entering BLOCKED rejects live filings, reverses their charges, unfiles legs."""
    rejected_any = False
    for submission in submissions_of_version(version["id"]):
        if submission["status"] in ("TRANSMITTED", "ACKNOWLEDGED"):
            submission["status"] = "REJECTED"
            submission["rejection_reason"] = "SCHEDULE_BLOCKED"
            mark(submission)
            rejected_any = True
    # The version returns from filed to validated, which is the framing under
    # which its currently-filed legs step back to slot-backed while legs
    # already in REFILE_REQUIRED are skipped entirely (PRD 2.10).
    if rejected_any and version["filing_status"] == "FILED":
        version["filing_status"] = "VALIDATED"
    for leg in active(legs_of_version(version["id"])):
        if leg["status"] == "FILED":
            leg["status"] = "SLOT_BACKED"
            mark(leg)


def recompute_carrier(carrier):
    held = len([
        holding for holding in store.values("slot_holdings")
        if holding["carrier_id"] == carrier["id"] and holding["holding_status"] == "HELD"
    ])
    if set_field(carrier, "held_series_count", held):
        mark(carrier)
        return True
    return False


def recompute_season(season):
    held = len([
        holding for holding in store.values("slot_holdings")
        if holding["season_id"] == season["id"] and holding["holding_status"] == "HELD"
    ])
    if set_field(season, "held_series_count", held):
        mark(season)
        return True
    return False


def recompute_all():
    """Re-derive every dependent quantity to a fixed point inside this request."""
    if getattr(g, "deriving", False):
        return
    g.deriving = True
    try:
        for _ in range(6):
            changed = False
            for leg in store.values("flight_legs"):
                changed |= recompute_leg(leg)
            for holding in store.values("slot_holdings"):
                changed |= recompute_holding(holding)
            for aircraft in store.values("aircraft"):
                changed |= recompute_aircraft(aircraft)
            for submission in store.values("filing_submissions"):
                changed |= recompute_submission(submission)
            for version in store.values("schedule_versions"):
                changed |= recompute_version(version)
            for carrier in store.values("carriers"):
                changed |= recompute_carrier(carrier)
            for season in store.values("seasons"):
                changed |= recompute_season(season)
            if not changed:
                break
    finally:
        g.deriving = False
