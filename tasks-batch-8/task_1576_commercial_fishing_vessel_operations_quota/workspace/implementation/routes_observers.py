"""Routes: observer registry and observer assignments."""

from datetime import timedelta

from flask import Blueprint, request

from errors import ApiError
import store
from common import (
    auth,
    body,
    f_dt,
    f_enum,
    f_int,
    f_str,
    get_assignment,
    get_observer,
    get_trip,
    get_vessel,
    list_response,
    make_entity,
    not_owner,
    ok_object,
    pub,
    require_roles,
    touch,
)
import domain
from store import iso, parse_dt

bp = Blueprint("observers", __name__)

COORDINATOR = ["ObserverCoordinator"]
OBSERVER = ["Observer"]
REGULATOR = ["FisheriesRegulator"]
CERT_LEVELS = ["A", "B", "C"]
REST_BUFFER = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Observer registry
# ---------------------------------------------------------------------------

@bp.route("/observers", methods=["POST"])
def create_observer():
    _, role = auth()
    require_roles(role, COORDINATOR)
    payload = body()
    observer = make_entity(
        {
            "observer_name": f_str(payload, "observer_name"),
            "certification_level": f_enum(payload, "certification_level", CERT_LEVELS),
            "home_base": f_str(payload, "home_base"),
            "status": "AVAILABLE",
        }
    )
    store.db.observers[observer["id"]] = observer
    return ok_object(pub(observer), 201)


@bp.route("/observers", methods=["GET"])
def list_observers():
    auth()
    return list_response(
        store.db.observers.values(), [("status", request.args.get("status"))]
    )


@bp.route("/observers/<rid>", methods=["GET"])
def get_one_observer(rid):
    auth()
    return ok_object(pub(get_observer(rid)))


# ---------------------------------------------------------------------------
# Observer assignments
# ---------------------------------------------------------------------------

@bp.route("/observer-assignments", methods=["GET"])
def list_assignments():
    auth()
    return list_response(
        store.db.assignments.values(),
        [
            ("trip_id", request.args.get("trip_id")),
            ("observer_id", request.args.get("observer_id")),
            ("status", request.args.get("status")),
        ],
    )


@bp.route("/observer-assignments/<rid>", methods=["GET"])
def get_one_assignment(rid):
    auth()
    return ok_object(pub(get_assignment(rid)))


@bp.route("/observer-assignments/<rid>/assign", methods=["POST"])
def assign_observer(rid):
    _, role = auth()
    require_roles(role, COORDINATOR)
    assignment = get_assignment(rid)
    payload = body()
    observer = get_observer(f_str(payload, "observer_id"))
    expected = f_int(payload, "expected_observer_version")
    if expected != observer["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_observer_version is stale")
    if assignment["status"] != "REQUESTED":
        raise ApiError(
            409, "ERR_ASSIGNMENT_NOT_REQUESTED", "assign requires REQUESTED status"
        )
    trip = get_trip(assignment["trip_id"])
    vessel = get_vessel(trip["vessel_id"])
    # Certification gate (tier 6): FULL requires A; PARTIAL requires A or B.
    coverage_class = vessel["observer_coverage_class"]
    cert = observer["certification_level"]
    if coverage_class == "FULL" and cert != "A":
        raise ApiError(
            422, "ERR_OBSERVER_CERT_INSUFFICIENT", "FULL coverage class requires cert A"
        )
    if coverage_class == "PARTIAL" and cert not in ("A", "B"):
        raise ApiError(
            422,
            "ERR_OBSERVER_CERT_INSUFFICIENT",
            "PARTIAL coverage class requires cert A or B",
        )
    coverage_from = f_dt(payload, "coverage_from")
    coverage_to = f_dt(payload, "coverage_to")
    # Double-booking gate (tier 7) with a 24h rest buffer.
    for other in store.db.assignments.values():
        if (
            other["observer_id"] == observer["id"]
            and other["status"] in ("ASSIGNED", "CONFIRMED", "DEPLOYED")
        ):
            existing_from = parse_dt(other["coverage_from"])
            existing_to = parse_dt(other["coverage_to"])
            if not (
                coverage_from >= existing_to + REST_BUFFER
                or coverage_to + REST_BUFFER <= existing_from
            ):
                raise ApiError(
                    409,
                    "ERR_OBSERVER_DOUBLE_BOOKED",
                    "coverage collides with an existing assignment including the 24h rest buffer",
                )
    if coverage_to <= coverage_from:
        raise ApiError(
            400, "ERR_INVALID_TIME_WINDOW", "coverage_to must be later than coverage_from"
        )
    assignment["observer_id"] = observer["id"]
    assignment["coverage_from"] = iso(coverage_from)
    assignment["coverage_to"] = iso(coverage_to)
    assignment["status"] = "ASSIGNED"
    touch(assignment)
    if observer["status"] != "ON_ASSIGNMENT":
        observer["status"] = "ON_ASSIGNMENT"
        touch(observer)
    else:
        # Assignment still advanced the observer's availability picture.
        touch(observer)
    return ok_object(pub(assignment))


@bp.route("/observer-assignments/<rid>/confirm", methods=["POST"])
def confirm_assignment(rid):
    uid, role = auth()
    require_roles(role, OBSERVER)
    assignment = get_assignment(rid)
    if assignment.get("observer_id") is None or uid != assignment["observer_id"]:
        not_owner("X-User-ID must equal the assignment's observer_id")
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            409, "ERR_ASSIGNMENT_NOT_ASSIGNED", "confirm requires ASSIGNED status"
        )
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    return ok_object(pub(assignment))


@bp.route("/observer-assignments/<rid>/debrief", methods=["POST"])
def debrief_assignment(rid):
    uid, role = auth()
    require_roles(role, OBSERVER)
    assignment = get_assignment(rid)
    if assignment.get("observer_id") is None or uid != assignment["observer_id"]:
        not_owner("X-User-ID must equal the assignment's observer_id")
    if assignment["status"] != "DEPLOYED":
        raise ApiError(
            409, "ERR_ASSIGNMENT_NOT_DEPLOYED", "debrief requires DEPLOYED status"
        )
    trip = get_trip(assignment["trip_id"])
    if trip["status"] not in ("RETURNED", "LANDING_FINALIZED", "SETTLED"):
        raise ApiError(
            409,
            "ERR_TRIP_NOT_RETURNED",
            "debrief requires the trip in RETURNED, LANDING_FINALIZED, or SETTLED",
        )
    assignment["status"] = "DEBRIEFED"
    touch(assignment)
    domain.recompute_observer_status(get_observer(assignment["observer_id"]))
    return ok_object(pub(assignment))


@bp.route("/observer-assignments/<rid>/release", methods=["POST"])
def release_assignment(rid):
    _, role = auth()
    require_roles(role, COORDINATOR)
    assignment = get_assignment(rid)
    if assignment["status"] != "CONFIRMED":
        raise ApiError(
            409, "ERR_ASSIGNMENT_NOT_CONFIRMABLE", "release requires CONFIRMED status"
        )
    assignment["status"] = "RELEASED"
    touch(assignment)
    domain.recompute_observer_status(get_observer(assignment["observer_id"]))
    trip = get_trip(assignment["trip_id"])
    # Compensating re-request so the trip is not silently left uncovered.
    if (
        trip["status"] == "PLANNED"
        and trip["observer_required"]
        and not trip["observer_waived"]
    ):
        domain.create_observer_request(trip)
    return ok_object(pub(assignment))


@bp.route("/observer-assignments/<rid>/waive", methods=["POST"])
def waive_assignment(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    assignment = get_assignment(rid)
    if assignment["status"] != "REQUESTED":
        raise ApiError(
            409, "ERR_ASSIGNMENT_NOT_REQUESTED", "waive requires REQUESTED status"
        )
    assignment["status"] = "WAIVED"
    touch(assignment)
    trip = get_trip(assignment["trip_id"])
    trip["observer_waived"] = True
    touch(trip)
    return ok_object(pub(assignment))
