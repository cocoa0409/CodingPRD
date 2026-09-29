"""Lookup, ledger-append and cascade helpers shared by the route modules."""
import derive
from constants import (
    KG_PER_L_PER_BAR,
    LOT_CONSUMED_FRACTION,
    MIN_TRAINED_RESPONDERS,
)
from errors import raise_error
from store import base_row, db, touch


# --------------------------------------------------------------------------
# path / body identifier resolution
# --------------------------------------------------------------------------
def _lookup(table, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in table:
        raise_error(error_id)
    return table[row_id]


def get_agreement(row_id):
    return _lookup(db.funding_agreements, row_id, "ERR_FUNDING_AGREEMENT_NOT_FOUND")


def get_station(row_id):
    return _lookup(db.stations, row_id, "ERR_STATION_NOT_FOUND")


def get_vessel(row_id):
    return _lookup(db.pressure_vessels, row_id, "ERR_PRESSURE_VESSEL_NOT_FOUND")


def get_asset(row_id):
    return _lookup(db.production_assets, row_id, "ERR_PRODUCTION_ASSET_NOT_FOUND")


def get_lot(row_id):
    return _lookup(db.production_lots, row_id, "ERR_PRODUCTION_LOT_NOT_FOUND")


def get_delivery(row_id):
    return _lookup(db.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")


def get_session(row_id):
    return _lookup(db.dispense_sessions, row_id, "ERR_DISPENSE_SESSION_NOT_FOUND")


def get_event(row_id):
    return _lookup(db.safety_events, row_id, "ERR_SAFETY_EVENT_NOT_FOUND")


def get_claim(row_id):
    return _lookup(db.incentive_claims, row_id, "ERR_INCENTIVE_CLAIM_NOT_FOUND")


def get_report(row_id):
    return _lookup(db.uptime_reports, row_id, "ERR_UPTIME_REPORT_NOT_FOUND")


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------
def require_not_frozen(station):
    if derive.safety_posture(station) == "FROZEN":
        raise_error("ERR_STATION_FROZEN")


def require_not_restricted_h70(station, pressure_class):
    if pressure_class == "H70" and derive.safety_posture(station) == "RESTRICTED":
        raise_error("ERR_POSTURE_RESTRICTS_H70")


def require_responders(station):
    if derive.trained_responders(station["id"]) < MIN_TRAINED_RESPONDERS:
        raise_error("ERR_RESPONDER_TRAINING_LAPSED")


def require_vessel_fit(vessel):
    if derive.vessel_status(vessel) not in ("CURRENT", "DUE"):
        raise_error("ERR_VESSEL_INSPECTION_OVERDUE")


def bay_conflict(station, window_start, window_end, exclude_id=None):
    """Aggregate-capacity test on half-open [window_start, window_end)."""
    busy = 0
    for delivery in derive.deliveries_of(station["id"]):
        if delivery["id"] == exclude_id:
            continue
        if delivery["status"] not in ("SCHEDULED", "ARRIVED"):
            continue
        if delivery["window_start"] < window_end and window_start < delivery["window_end"]:
            busy += 1
    return busy >= station["offload_bay_count"]


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------
def append_ledger(station_id, reason, delta_kg, source_ref_type, source_ref_id):
    row = base_row(with_common=False)
    row.update({
        "station_id": station_id,
        "sequence_no": db.next_ledger_sequence(station_id),
        "reason": reason,
        "delta_kg": derive.q3(delta_kg),
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "occurred_at": db.clock,
    })
    db.ledger_entries[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# vessel pressure arithmetic
# --------------------------------------------------------------------------
def pressure_delta_for_mass(vessel, mass_kg):
    return mass_kg / (vessel["water_volume_l"] * KG_PER_L_PER_BAR)


def set_vessel_pressure(vessel, new_pressure_bar):
    vessel["current_pressure_bar"] = derive.q2(new_pressure_bar)
    touch(vessel)


# --------------------------------------------------------------------------
# lot consumption join
# --------------------------------------------------------------------------
def maybe_consume_lot(lot):
    if lot["status"] != "RELEASED":
        return
    delivered = derive.accepted_delivered_kg(lot["id"])
    threshold = derive.q3(lot["mass_kg"] * LOT_CONSUMED_FRACTION)
    if delivered >= threshold:
        lot["status"] = "CONSUMED"
        touch(lot)


# --------------------------------------------------------------------------
# freeze cascade (PRD 3.7 hops four and five)
# --------------------------------------------------------------------------
def apply_freeze_cascade(station):
    if derive.safety_posture(station) != "FROZEN":
        return
    for session in derive.sessions_of(station["id"]):
        if session["fill_status"] not in ("PRECOOLING", "FUELING"):
            continue
        session["fill_status"] = "ABORTED"
        session["abort_reason"] = "STATION_FROZEN"
        if session["billing_status"] == "PENDING":
            session["billing_status"] = "VOIDED"
        touch(session)


# --------------------------------------------------------------------------
# subsystem field mapping (PRD 3.7)
# --------------------------------------------------------------------------
SUBSYSTEM_FIELD = {
    "LEAK_DETECTED": ("leak_detection_status", "ALARM", "NORMAL"),
    "VENTILATION_FAULT": ("ventilation_status", "FAULT", "NORMAL"),
    "COMPRESSOR_FAULT": ("compressor_status", "OFFLINE", "ONLINE"),
    "SETBACK_BREACH": ("setback_compliant", False, True),
}


def apply_subsystem_open(station, kind):
    mapping = SUBSYSTEM_FIELD.get(kind)
    if mapping:
        field, unhealthy, _healthy = mapping
        station[field] = unhealthy


def apply_subsystem_clear(station, kind, cleared_event_id):
    mapping = SUBSYSTEM_FIELD.get(kind)
    if not mapping:
        return
    field, _unhealthy, healthy = mapping
    for event in derive.events_of(station["id"]):
        if event["id"] == cleared_event_id:
            continue
        if event["kind"] != kind:
            continue
        if event["status"] in ("OPEN", "ACKNOWLEDGED"):
            return
    station[field] = healthy
