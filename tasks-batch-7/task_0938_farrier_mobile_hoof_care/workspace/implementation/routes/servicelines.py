"""Per-limb service lines (PRD 3.5)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import (
    MAX_CONSECUTIVE_RESETS,
    SERVICE_TYPES,
    SERVICE_TYPE_ALLOWS_PAD,
    SERVICE_TYPE_REQUIRES_SKU,
    SERVICE_TYPE_TO_MINUTES,
    SERVICE_TYPE_TO_UNITS,
    SHOD_STATES,
)
from core.envelope import ok
from core.errors import ApiError
from core.store import db
from core.validate import bad, bad_enum, body, req_int, req_list
from domain.gates import ELIGIBLE, gate4_horse_hold, gate5_appointment
from domain.lookup import guard_appointment, must
from domain.reservations import resync_reservations
from domain.routecalc import check_capacity, recompute_stop_minutes
from domain.routeops import settle_route
from domain.rollups import (
    lines_of,
    prescription_covers,
    prescription_is_live,
    recompute_appointment_rollups,
    recompute_estimate,
)
from domain.serializers import serialize_many

from ._common import listing, single

bp = Blueprint("service_lines", __name__)

READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier", "Veterinarian")


@bp.get("/service-lines")
def list_service_lines():
    return listing(
        "service_lines",
        {
            "appointment_id": "appointment_id",
            "limb_state_id": "limb_state_id",
            "prescription_id": "prescription_id",
            "sku_id": "sku_id",
            "status": "status",
        },
        READ_ROLES,
    )


@bp.get("/service-lines/<line_id>")
def read_service_line(line_id):
    authenticate(READ_ROLES)
    line = must("service_lines", line_id)
    appointment = db.get("appointments", line["appointment_id"])
    if appointment is not None:
        guard_appointment(appointment)
    return single(line)


@bp.post("/appointments/<appointment_id>/service-lines")
def add_service_lines(appointment_id):
    authenticate(("Dispatcher", "Farrier"))
    appointment = db.get("appointments", appointment_id)
    if appointment is not None:
        guard_appointment(appointment)

    data = body()
    raw_lines = data.get("lines")
    elements = raw_lines if isinstance(raw_lines, list) else []

    # rung 8 then rung 15 then rung 18 -- existence runs in ladder order.
    for element in elements:
        if isinstance(element, dict):
            must_body_ref("shoe_skus", element.get("sku_id"))
    if appointment is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    for element in elements:
        if isinstance(element, dict):
            must_body_ref("vet_prescriptions", element.get("prescription_id"))

    # rung 21 -- shape, in index order.
    lines = req_list(data, "lines")
    expected_version = req_int(data, "expected_appointment_version")
    horse = db.get("horses", appointment["horse_id"])
    parsed = []
    for element in lines:
        if not isinstance(element, dict):
            bad("Every element of lines must be an object.")
        limb_state_id = element.get("limb_state_id")
        limb_state = db.get("limb_states", limb_state_id)
        if limb_state is None or limb_state["horse_id"] != horse["id"]:
            bad("limb_state_id must name a limb of this appointment's horse.")
        service_type = element.get("service_type")
        if not isinstance(service_type, str) or not service_type:
            bad("Field service_type is required on every line.")
        sku_id = element.get("sku_id")
        prescription_id = element.get("prescription_id")
        with_pad = element.get("with_pad", False)
        if not isinstance(with_pad, bool):
            bad("Field with_pad must be a boolean.")
        if sku_id is not None and not isinstance(sku_id, str):
            bad("Field sku_id must be an identifier.")
        if prescription_id is not None and not isinstance(prescription_id, str):
            bad("Field prescription_id must be an identifier.")
        if service_type in SERVICE_TYPES:
            if SERVICE_TYPE_REQUIRES_SKU[service_type] and not sku_id:
                bad("service_type %s requires sku_id." % service_type)
            if not SERVICE_TYPE_REQUIRES_SKU[service_type] and sku_id:
                bad("service_type %s must leave sku_id null." % service_type)
            if service_type == "CORRECTIVE" and not prescription_id:
                bad("CORRECTIVE requires prescription_id.")
            if service_type != "CORRECTIVE" and prescription_id:
                bad("Only CORRECTIVE may carry prescription_id.")
            if with_pad and not SERVICE_TYPE_ALLOWS_PAD[service_type]:
                bad("with_pad may be true only for NEW_SHOES and CORRECTIVE.")
        parsed.append(
            {
                "limb_state": limb_state,
                "service_type": service_type,
                "sku_id": sku_id,
                "prescription_id": prescription_id,
                "with_pad": with_pad,
            }
        )

    # rung 22 -- enum membership, in index order.
    for element in parsed:
        if element["service_type"] not in SERVICE_TYPES:
            bad_enum("service_type", element["service_type"])

    # rung 25
    if expected_version != appointment["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION")

    gate4_horse_hold(horse, appointment)
    gate5_appointment(appointment, ELIGIBLE["service_line_add"])

    # rungs 36-40, per element, in index order -- the first offending element's
    # error is returned and nothing at all is written.
    taken_limbs = {line["limb"] for line in lines_of(appointment)}
    for element in parsed:
        limb_state = element["limb_state"]
        limb = limb_state["limb"]
        service_type = element["service_type"]
        if service_type == "CORRECTIVE":
            prescription = db.get("vet_prescriptions", element["prescription_id"])
            if not prescription_is_live(prescription, appointment["scheduled_date"]):
                raise ApiError("ERR_NO_LIVE_PRESCRIPTION")
            if not prescription_covers(prescription, limb):
                raise ApiError("ERR_LIMB_NOT_IN_PRESCRIPTION_SCOPE")
        if service_type == "RESET":
            if limb_state["shoeing_state"] not in SHOD_STATES:
                raise ApiError("ERR_RESET_REQUIRES_SHOD_LIMB")
            if limb_state["consecutive_reset_count"] >= MAX_CONSECUTIVE_RESETS:
                raise ApiError("ERR_RESET_LIMIT_REACHED")
        if limb in taken_limbs:
            raise ApiError("ERR_DUPLICATE_LIMB_LINE")
        taken_limbs.add(limb)

    minted = []
    for element in parsed:
        minted.append(
            db.mint(
                "service_lines",
                {
                    "appointment_id": appointment["id"],
                    "limb_state_id": element["limb_state"]["id"],
                    "prescription_id": element["prescription_id"],
                    "sku_id": element["sku_id"],
                    "limb": element["limb_state"]["limb"],
                    "service_type": element["service_type"],
                    "with_pad": element["with_pad"],
                    "status": "PLANNED",
                    "labor_cents": 0,
                },
            )
        )

    stop = db.get("route_stops", appointment.get("route_stop_id"))
    route = db.get("routes", stop["route_id"]) if stop else None
    attached = stop is not None and appointment["status"] in ("SCHEDULED", "CONFIRMED")

    # Adjudication of friction 6: when the recomputation pushes an ALREADY
    # ATTACHED visit over a route cap or past its farrier's van stock, the
    # addition is refused atomically by the same three rungs that guard
    # attachment -- ERR_ROUTE_UNIT_CAPACITY_EXCEEDED, then
    # ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED, then ERR_VAN_STOCK_INSUFFICIENT.
    # Section 3.5 says in terms that the route's committed totals are
    # "recomputed and re-checked against both caps" on a line addition, and the
    # permissive reading would leave a route over its declared cap and a
    # reservation drawing stock the van does not hold.
    try:
        delta_units = sum(SERVICE_TYPE_TO_UNITS[e["service_type"]] for e in parsed)
        delta_minutes = sum(SERVICE_TYPE_TO_MINUTES[e["service_type"]] for e in parsed)
        if attached:
            check_capacity(route, delta_units, delta_minutes)
            resync_reservations(appointment, route["farrier_id"], dry_run=True)
    except ApiError:
        for row in minted:
            db.service_lines.pop(row["id"], None)
        raise

    recompute_appointment_rollups(appointment, horse)
    if attached:
        resync_reservations(appointment, route["farrier_id"])
        if recompute_stop_minutes(stop):
            db.touch(stop)
    recompute_estimate(appointment, horse)
    db.touch(appointment)
    if route is not None:
        settle_route(route)
    return ok(serialize_many(minted), 201)


@bp.delete("/service-lines/<line_id>")
def remove_service_line(line_id):
    authenticate(("Dispatcher", "Farrier"))
    line = must("service_lines", line_id)
    appointment = db.get("appointments", line["appointment_id"])
    guard_appointment(appointment)
    gate5_appointment(appointment, ELIGIBLE["service_line_remove"])
    if line["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    line["status"] = "REMOVED"
    db.touch(line)
    horse = db.get("horses", appointment["horse_id"])
    recompute_appointment_rollups(appointment, horse)
    stop = db.get("route_stops", appointment.get("route_stop_id"))
    route = db.get("routes", stop["route_id"]) if stop else None
    if stop is not None and appointment["status"] in ("SCHEDULED", "CONFIRMED"):
        resync_reservations(appointment, route["farrier_id"])
    if stop is not None and recompute_stop_minutes(stop):
        db.touch(stop)
    recompute_estimate(appointment, horse)
    db.touch(appointment)
    if route is not None:
        settle_route(route)
    return single(line)


def must_body_ref(table, value):
    from domain.lookup import must_ref

    return must_ref(table, value)
