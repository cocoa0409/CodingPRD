"""Cleaning turns, incidents (incl. resolve cascades), charges, logical clock
(PRD §3.7, §3.8, §2.4)."""

from datetime import timedelta

from flask import Blueprint

import common
import db
import errors
import response
from middleware import require_roles
from routes.bookings import ALL_ROLES, check_booking_owner, load_booking
from services import booking_ops, risk, settlement, sweep

bp = Blueprint("ops", __name__)

INCIDENT_TYPES = ("MECHANICAL_FAILURE", "GROUNDING", "DAMAGE")
SEVERITIES = ("MINOR", "MAJOR", "TOTAL_LOSS")
RESOLUTIONS = (
    "REPAIRED_RESUME", "REPAIRED_TERMINATE", "GROUNDING_CONFIRMED",
    "DAMAGE_ASSESSED", "REJECTED",
)
LEGAL_RESOLUTION = {
    "MECHANICAL_FAILURE": ("REPAIRED_RESUME", "REPAIRED_TERMINATE"),
    "GROUNDING": ("GROUNDING_CONFIRMED",),
    "DAMAGE": ("DAMAGE_ASSESSED",),
}


# ---------------------------------------------------------------------------
# Cleaning turns
# ---------------------------------------------------------------------------

@bp.get("/bookings/<bid>/cleaning-turns")
@require_roles(*ALL_ROLES)
def list_cleaning_turns(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    turns = [t for t in db.all_of("cleaning_turns") if t["booking_id"] == bid]
    page, total, limit, offset = common.paginate(turns)
    return response.list_ok(
        [common.cleaning_turn_out(t) for t in page], total, limit, offset
    )


@bp.post("/cleaning-turns/<tid>/inspect")
@require_roles("DockStaff")
def inspect_cleaning_turn(tid, user_id, role):
    turn = db.get("cleaning_turns", tid)
    if turn is None:
        errors.err(errors.ERR_NOT_FOUND, f"CleaningTurn {tid} does not exist")
    body = common.json_body()
    passed = common.as_bool(common.req_field(body, "passed"), "passed")
    if turn["status"] != "IN_PROGRESS":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"CleaningTurn in state {turn['status']} cannot be inspected",
        )
    if passed:
        turn["status"] = "COMPLETED"
    else:
        turn["re_clean_count"] += 1
    db.touch(turn)
    return response.ok(common.cleaning_turn_out(turn))


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/incidents")
@require_roles("Renter")
def report_incident(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    body = common.json_body()
    incident_type = common.as_enum(
        common.req_field(body, "incident_type"), "incident_type", INCIDENT_TYPES
    )
    occurred_at = common.parse_datetime(
        common.req_field(body, "occurred_at"), "occurred_at"
    )
    description = common.opt_field(body, "description")
    if description is not None and not isinstance(description, str):
        errors.err(errors.ERR_INVALID_REQUEST, "description must be a string")
    start_dt = settlement._dt_of_date(booking["start_date"])
    if occurred_at < start_dt:
        errors.err(
            errors.ERR_INVALID_REQUEST,
            "occurred_at must not precede the booking start",
        )
    if occurred_at > db.get_clock():
        errors.err(errors.ERR_INVALID_REQUEST, "occurred_at lies in the future")

    if booking["status"] not in ("CHECKED_OUT", "INTERRUPTED", "RETURNED", "CLOSED"):
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Incidents cannot be reported on a booking in state {booking['status']}",
        )

    rec = db.base_record()
    rec.update({
        "booking_id": booking["id"],
        "incident_type": incident_type,
        "occurred_at": occurred_at,
        "description": description,
        "status": "REPORTED",
        "severity": None,
        "resolution": None,
        "downtime_days": None,
        "assessed_damage_cents": None,
    })
    db.insert("incidents", rec)
    return response.ok(common.incident_out(rec), status=201)


@bp.get("/bookings/<bid>/incidents")
@require_roles(*ALL_ROLES)
def list_incidents(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    incidents = [i for i in db.all_of("incidents") if i["booking_id"] == bid]
    page, total, limit, offset = common.paginate(incidents)
    return response.list_ok(
        [common.incident_out(i) for i in page], total, limit, offset
    )


def _resolution_mismatch(message):
    errors.err(errors.ERR_INCIDENT_RESOLUTION_MISMATCH, message)


@bp.post("/incidents/<iid>/resolve")
@require_roles("Mechanic")
def resolve_incident(iid, user_id, role):
    incident = db.get("incidents", iid)
    if incident is None:
        errors.err(errors.ERR_NOT_FOUND, f"Incident {iid} does not exist")
    body = common.json_body()
    resolution = common.as_enum(
        common.req_field(body, "resolution"), "resolution", RESOLUTIONS
    )
    severity = common.opt_field(body, "severity")
    if severity is not None:
        common.as_enum(severity, "severity", SEVERITIES)
    downtime_days = common.opt_field(body, "downtime_days")
    if downtime_days is not None:
        common.as_int(downtime_days, "downtime_days")
    assessed = common.opt_field(body, "assessed_damage_cents")
    if assessed is not None:
        common.as_int(assessed, "assessed_damage_cents")

    if incident["status"] != "REPORTED":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Incident in state {incident['status']} cannot be resolved",
        )

    booking = db.get("bookings", incident["booking_id"])

    if resolution == "REJECTED":
        incident["status"] = "REJECTED"
        incident["resolution"] = "REJECTED"
        db.touch(incident)
        return response.ok(common.incident_out(incident))

    # Resolution legality for the incident type (final check of the flow).
    if resolution not in LEGAL_RESOLUTION[incident["incident_type"]]:
        _resolution_mismatch(
            f"{resolution} is not legal for {incident['incident_type']}"
        )
    if resolution in ("REPAIRED_RESUME", "REPAIRED_TERMINATE"):
        if severity not in ("MAJOR", "TOTAL_LOSS"):
            _resolution_mismatch(
                "Mechanical resolutions require severity MAJOR or TOTAL_LOSS"
            )
        remaining = settlement.remaining_nights(booking)
        if downtime_days is None or downtime_days < 1 or downtime_days > remaining:
            _resolution_mismatch(
                "downtime_days must be between 1 and the remaining nights of the stay"
            )
    elif resolution == "GROUNDING_CONFIRMED":
        if severity is None:
            _resolution_mismatch("GROUNDING_CONFIRMED requires severity")
    elif resolution == "DAMAGE_ASSESSED":
        if assessed is None:
            _resolution_mismatch("DAMAGE_ASSESSED requires assessed_damage_cents")
        if assessed < 0:
            errors.err(
                errors.ERR_INVALID_REQUEST, "assessed_damage_cents must be >= 0"
            )

    incident["status"] = "RESOLVED"
    incident["resolution"] = resolution
    incident["severity"] = severity
    if resolution in ("REPAIRED_RESUME", "REPAIRED_TERMINATE"):
        incident["downtime_days"] = downtime_days
    if resolution == "DAMAGE_ASSESSED":
        incident["assessed_damage_cents"] = assessed
    db.touch(incident)

    note = f"incident:{incident['id']}"
    if resolution == "REPAIRED_RESUME":
        refund = settlement.mechanical_refund_cents(booking, downtime_days)
        booking_ops.post_charge(
            booking["id"], "MECHANICAL_REFUND", -refund, "POSTED", note=note
        )
        # The repair completes on the water: cycle INTERRUPTED and back.
        if booking["status"] == "CHECKED_OUT":
            booking["status"] = "INTERRUPTED"
            db.touch(booking)
            booking["status"] = "CHECKED_OUT"
            db.touch(booking)
        elif booking["status"] == "INTERRUPTED":
            booking["status"] = "CHECKED_OUT"
            db.touch(booking)
    elif resolution == "REPAIRED_TERMINATE":
        unused = settlement.remaining_nights(booking)
        refund = settlement.mechanical_refund_cents(booking, unused)
        booking_ops.post_charge(
            booking["id"], "MECHANICAL_REFUND", -refund, "POSTED", note=note
        )
        if booking["status"] == "CHECKED_OUT":
            booking["status"] = "INTERRUPTED"
            db.touch(booking)
        vessel = db.get("vessels", booking["vessel_id"])
        today = db.current_date()
        window = db.base_record()
        window.update({
            "vessel_id": vessel["id"],
            "start_date": today,
            "end_date": today + timedelta(days=downtime_days),
            "reason": f"Emergency repair for incident {incident['id']}",
            "source": "INCIDENT_EMERGENCY",
            "status": "IN_PROGRESS",
        })
        db.insert("maintenance_windows", window)
        if vessel["status"] == "AVAILABLE":
            vessel["status"] = "IN_MAINTENANCE"
            db.touch(vessel)
        # The emergency window cascade-cancels every other overlapping
        # HELD/CONFIRMED booking of the vessel (closed-interval comparison).
        targets = [
            b
            for b in db.all_of("bookings")
            if b["vessel_id"] == vessel["id"]
            and b["id"] != booking["id"]
            and b["status"] in ("HELD", "CONFIRMED")
            and window["start_date"] <= b["end_date"]
            and window["end_date"] >= b["start_date"]
        ]
        for b in db.sorted_created(targets):
            booking_ops.cancel_booking(b, "VESSEL_MECHANICAL", system=True)
    elif resolution == "GROUNDING_CONFIRMED":
        booking_ops.post_charge(
            booking["id"],
            "GROUNDING_LIABILITY",
            settlement.GROUNDING_BASE[severity],
            "POSTED",
            note=note,
        )
    elif resolution == "DAMAGE_ASSESSED":
        booking_ops.post_charge(
            booking["id"], "DAMAGE", assessed, "POSTED", note=note
        )

    renter = db.get("renters", booking["renter_id"])
    if renter is not None:
        risk.recompute_risk(renter)
    return response.ok(common.incident_out(incident))


# ---------------------------------------------------------------------------
# Charges
# ---------------------------------------------------------------------------

@bp.get("/bookings/<bid>/charges")
@require_roles(*ALL_ROLES)
def list_charges(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    charges = booking_ops.charges_of(bid)
    page, total, limit, offset = common.paginate(charges)
    return response.list_ok(
        [common.charge_out(c) for c in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("FleetManager")
def set_current_utc(user_id, role):
    body = common.json_body()
    target = common.parse_datetime(
        common.req_field(body, "to_iso8601"), "to_iso8601"
    )
    db.set_clock(target)
    summary = sweep.run_sweep()
    return response.ok({
        "current_utc": db.now_iso(),
        "sweep_summary": summary,
    })
