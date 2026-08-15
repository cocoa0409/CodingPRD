"""Routes: fishing trips, catch reports, landing declarations."""

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
    find_holding,
    get_declaration,
    get_opening,
    get_trip,
    get_vessel,
    list_response,
    make_entity,
    make_event,
    not_owner,
    ok_object,
    pub,
    require_roles,
    touch,
    vessel_has_issued_permit,
)
import domain
from store import iso, parse_dt, now_iso

bp = Blueprint("trips", __name__)

TRIP_PLANNERS = ["VesselOwner", "Captain"]
CAPTAIN = ["Captain"]
REGULATOR = ["FisheriesRegulator"]
REPORT_TYPES = ["HARVEST", "DISCARD"]


def _validate_gear_requirements(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(400, "ERR_INVALID_REQUEST", "gear_requirements must be an array")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(
                400, "ERR_INVALID_REQUEST", "gear_requirements entries must be objects"
            )
        gear = entry.get("gear_type")
        if gear not in domain.GEAR_TYPES:
            raise ApiError(
                400, "ERR_INVALID_REQUEST", "gear_requirements gear_type is invalid"
            )
        units = entry.get("units")
        if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
            raise ApiError(
                400, "ERR_INVALID_REQUEST", "gear_requirements units must be > 0"
            )
        out.append({"gear_type": gear, "units": units})
    return out


def _check_trip_overlap(vessel_id, dep, ret, exclude_id=None):
    for t in store.db.trips.values():
        if t["vessel_id"] != vessel_id or t["status"] == "CANCELLED":
            continue
        if exclude_id is not None and t["id"] == exclude_id:
            continue
        # Half-open semantics: back-to-back trips are allowed.
        if dep < parse_dt(t["planned_return_utc"]) and ret > parse_dt(t["planned_departure_utc"]):
            raise ApiError(
                409,
                "ERR_TRIP_WINDOW_OVERLAP",
                "trip window overlaps another non-CANCELLED trip of the same vessel",
            )


def _check_containment(opening, dep, ret):
    if dep < parse_dt(opening["opens_at"]) or ret > parse_dt(opening["closes_at"]):
        raise ApiError(
            409,
            "ERR_OUTSIDE_OPENING_WINDOW",
            "planned window must be contained in [opens_at, closes_at]",
        )


@bp.route("/fishing-trips", methods=["POST"])
def create_trip():
    uid, role = auth()
    require_roles(role, TRIP_PLANNERS)
    payload = body()
    vessel_id = f_str(payload, "vessel_id")
    if uid != vessel_id:
        not_owner("X-User-ID must equal the vessel_id in the payload")
    vessel = get_vessel(vessel_id)
    opening = get_opening(f_str(payload, "season_opening_id"))
    dep = f_dt(payload, "planned_departure_utc")
    ret = f_dt(payload, "planned_return_utc")
    # Tier 7 temporal: containment, then trip overlap.
    _check_containment(opening, dep, ret)
    _check_trip_overlap(vessel["id"], dep, ret)
    # Tier 8 cross-entity link state.
    if vessel["status"] != "ACTIVE":
        raise ApiError(409, "ERR_VESSEL_NOT_ACTIVE", "vessel must be ACTIVE to plan a trip")
    if not vessel_has_issued_permit(vessel["id"], opening["fishery_code"]):
        raise ApiError(
            409, "ERR_PERMIT_NOT_ACTIVE", "no ISSUED permit for the opening's fishery"
        )
    # Tier 9 shape.
    if ret <= dep:
        raise ApiError(
            400,
            "ERR_INVALID_TIME_WINDOW",
            "planned_return_utc must be later than planned_departure_utc",
        )
    gear_requirements = _validate_gear_requirements(payload.get("gear_requirements"))
    observer_required = domain.compute_observer_required(vessel, dep, ret)
    trip = make_entity(
        {
            "vessel_id": vessel["id"],
            "season_opening_id": opening["id"],
            "planned_departure_utc": iso(dep),
            "planned_return_utc": iso(ret),
            "gear_requirements": gear_requirements,
            "observer_required": observer_required,
            "observer_waived": False,
            "actual_departure_utc": None,
            "actual_return_utc": None,
            "status": "PLANNED",
        }
    )
    store.db.trips[trip["id"]] = trip
    if observer_required:
        domain.create_observer_request(trip)
    return ok_object(pub(trip), 201)


@bp.route("/fishing-trips", methods=["GET"])
def list_trips():
    auth()
    return list_response(
        store.db.trips.values(),
        [
            ("vessel_id", request.args.get("vessel_id")),
            ("season_opening_id", request.args.get("season_opening_id")),
            ("status", request.args.get("status")),
        ],
    )


@bp.route("/fishing-trips/<rid>", methods=["GET"])
def get_one_trip(rid):
    auth()
    return ok_object(pub(get_trip(rid)))


@bp.route("/fishing-trips/<rid>", methods=["PATCH"])
def reschedule_trip(rid):
    uid, role = auth()
    require_roles(role, TRIP_PLANNERS)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    payload = body()
    expected = f_int(payload, "expected_trip_version")
    if expected != trip["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_trip_version is stale")
    if trip["status"] != "PLANNED":
        raise ApiError(409, "ERR_TRIP_NOT_PLANNED", "reschedule requires PLANNED status")
    dep = f_dt(payload, "planned_departure_utc")
    ret = f_dt(payload, "planned_return_utc")
    opening = get_opening(trip["season_opening_id"])
    _check_containment(opening, dep, ret)
    _check_trip_overlap(trip["vessel_id"], dep, ret, exclude_id=trip["id"])
    if ret <= dep:
        raise ApiError(
            400,
            "ERR_INVALID_TIME_WINDOW",
            "planned_return_utc must be later than planned_departure_utc",
        )
    trip["planned_departure_utc"] = iso(dep)
    trip["planned_return_utc"] = iso(ret)
    vessel = get_vessel(trip["vessel_id"])
    trip["observer_required"] = domain.compute_observer_required(vessel, dep, ret)
    touch(trip)
    return ok_object(pub(trip))


@bp.route("/fishing-trips/<rid>/depart", methods=["POST"])
def depart_trip(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if trip["status"] != "PLANNED":
        raise ApiError(409, "ERR_TRIP_NOT_PLANNED", "depart requires PLANNED status")
    # Safety gates (tier 6): observer coverage, then gear sufficiency.
    if (
        trip["observer_required"]
        and not trip["observer_waived"]
        and not any(
            a["trip_id"] == trip["id"] and a["status"] == "CONFIRMED"
            for a in store.db.assignments.values()
        )
    ):
        raise ApiError(
            409,
            "ERR_OBSERVER_COVERAGE_MISSING",
            "depart requires a CONFIRMED observer assignment or a waiver",
        )
    for req in trip["gear_requirements"]:
        available = sum(
            a["units_operational"]
            for a in store.db.gear_assets.values()
            if a["vessel_id"] == trip["vessel_id"] and a["gear_type"] == req["gear_type"]
        )
        if available < req["units"]:
            raise ApiError(
                409,
                "ERR_GEAR_SHORTAGE",
                f"insufficient operational units of {req['gear_type']}",
            )
    # Temporal (tier 7): opening must be OPEN and clock within the window.
    opening = get_opening(trip["season_opening_id"])
    now = store.db.clock
    if (
        opening["status"] != "OPEN"
        or not (parse_dt(opening["opens_at"]) <= now <= parse_dt(opening["closes_at"]))
    ):
        raise ApiError(
            409,
            "ERR_OUTSIDE_OPENING_WINDOW",
            "opening is not OPEN or the clock is outside the opening window",
        )
    # Cross-entity link (tier 8): vessel must be ACTIVE.
    vessel = get_vessel(trip["vessel_id"])
    if vessel["status"] != "ACTIVE":
        raise ApiError(409, "ERR_VESSEL_NOT_ACTIVE", "vessel must be ACTIVE to depart")
    trip["status"] = "DEPARTED"
    trip["actual_departure_utc"] = now_iso()
    touch(trip)
    for a in store.db.assignments.values():
        if a["trip_id"] == trip["id"] and a["status"] == "CONFIRMED":
            a["status"] = "DEPLOYED"
            touch(a)
    return ok_object(pub(trip))


@bp.route("/fishing-trips/<rid>/return", methods=["POST"])
def return_trip(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if trip["status"] != "DEPARTED":
        raise ApiError(409, "ERR_TRIP_NOT_DEPARTED", "return requires DEPARTED status")
    trip["status"] = "RETURNED"
    trip["actual_return_utc"] = now_iso()
    touch(trip)
    vessel = get_vessel(trip["vessel_id"])
    domain.vms_gap_check(vessel, trip)
    return ok_object(pub(trip))


@bp.route("/fishing-trips/<rid>/cancel", methods=["POST"])
def cancel_trip(rid):
    uid, role = auth()
    require_roles(role, TRIP_PLANNERS)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if trip["status"] != "PLANNED":
        raise ApiError(409, "ERR_TRIP_NOT_PLANNED", "cancel requires PLANNED status")
    domain.cancel_trip_cascade(trip)
    return ok_object(pub(trip))


# ---------------------------------------------------------------------------
# Catch reports (append-only)
# ---------------------------------------------------------------------------

@bp.route("/fishing-trips/<rid>/catch-reports", methods=["POST"])
def create_catch_report(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if trip["status"] != "DEPARTED":
        raise ApiError(
            409, "ERR_TRIP_NOT_DEPARTED", "catch reports require a DEPARTED trip"
        )
    payload = body()
    fishery = f_enum(payload, "fishery_code", domain.FISHERY_CODES)
    report_type = f_enum(payload, "report_type", REPORT_TYPES)
    reported_lbs = f_int(payload, "reported_lbs")
    reported_at = f_dt(payload, "reported_at")
    if reported_lbs <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "reported_lbs must be > 0")
    haul_seq = 1 + sum(
        1 for r in store.db.catch_reports.values() if r["trip_id"] == trip["id"]
    )
    report = make_event(
        {
            "trip_id": trip["id"],
            "haul_seq": haul_seq,
            "fishery_code": fishery,
            "report_type": report_type,
            "reported_lbs": reported_lbs,
            "reported_at": iso(reported_at),
        }
    )
    store.db.catch_reports[report["id"]] = report
    return ok_object(pub(report), 201)


@bp.route("/fishing-trips/<rid>/catch-reports", methods=["GET"])
def list_catch_reports(rid):
    auth()
    get_trip(rid)
    items = [r for r in store.db.catch_reports.values() if r["trip_id"] == rid]
    return list_response(items)


# ---------------------------------------------------------------------------
# Landing declarations
# ---------------------------------------------------------------------------

def _validate_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "lines must be a non-empty array")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(400, "ERR_INVALID_REQUEST", "line entries must be objects")
        fishery = entry.get("fishery_code")
        if fishery not in domain.FISHERY_CODES:
            raise ApiError(400, "ERR_INVALID_REQUEST", "line fishery_code is invalid")
        declared = entry.get("declared_lbs")
        if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
            raise ApiError(
                400, "ERR_INVALID_REQUEST", "declared_lbs must be an integer >= 0"
            )
        lines.append({"fishery_code": fishery, "declared_lbs": declared})
    return lines


@bp.route("/fishing-trips/<rid>/landing-declarations", methods=["POST"])
def create_declaration(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if trip["status"] != "RETURNED":
        raise ApiError(
            409, "ERR_TRIP_NOT_RETURNED", "landing declaration requires a RETURNED trip"
        )
    payload = body()
    port_code = f_str(payload, "port_code")
    lines = _validate_lines(payload.get("lines"))
    if any(d["trip_id"] == trip["id"] for d in store.db.declarations.values()):
        raise ApiError(
            409, "ERR_DECLARATION_EXISTS", "a landing declaration already exists for this trip"
        )
    declaration = make_entity(
        {
            "trip_id": trip["id"],
            "port_code": port_code,
            "lines": lines,
            "discrepancy_details": [],
            "status": "DRAFT",
        }
    )
    store.db.declarations[declaration["id"]] = declaration
    return ok_object(pub(declaration), 201)


@bp.route("/fishing-trips/<rid>/landing-declarations", methods=["GET"])
def list_declarations(rid):
    auth()
    get_trip(rid)
    items = [d for d in store.db.declarations.values() if d["trip_id"] == rid]
    return list_response(items)


@bp.route("/landing-declarations/<rid>", methods=["GET"])
def get_one_declaration(rid):
    auth()
    return ok_object(pub(get_declaration(rid)))


@bp.route("/landing-declarations/<rid>/submit", methods=["POST"])
def submit_declaration(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    declaration = get_declaration(rid)
    trip = get_trip(declaration["trip_id"])
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if declaration["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError(
            409, "ERR_DECLARATION_NOT_SUBMITTED", "submit requires DRAFT or AMENDED"
        )
    if trip["status"] != "RETURNED":
        raise ApiError(409, "ERR_TRIP_NOT_RETURNED", "submit requires a RETURNED trip")
    declaration["discrepancy_details"] = domain.compute_discrepancy_details(
        trip["id"], declaration["lines"]
    )
    declaration["status"] = "SUBMITTED"
    touch(declaration)
    return ok_object(pub(declaration))


@bp.route("/landing-declarations/<rid>/verify", methods=["POST"])
def verify_declaration(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    declaration = get_declaration(rid)
    if declaration["status"] != "SUBMITTED":
        raise ApiError(409, "ERR_DECLARATION_NOT_SUBMITTED", "verify requires SUBMITTED")
    trip = get_trip(declaration["trip_id"])
    # Observer gate.
    if (
        trip["observer_required"]
        and not trip["observer_waived"]
        and not any(
            a["trip_id"] == trip["id"] and a["status"] == "DEBRIEFED"
            for a in store.db.assignments.values()
        )
    ):
        raise ApiError(
            409,
            "ERR_OBSERVER_NOT_DEBRIEFED",
            "landing verify requires a DEBRIEFED assignment or a waiver",
        )
    # Discrepancy gate: over tolerance -> DISPUTED (200, no error).
    details = domain.compute_discrepancy_details(trip["id"], declaration["lines"])
    declaration["discrepancy_details"] = details
    if not all(d["within_tolerance"] for d in details):
        declaration["status"] = "DISPUTED"
        touch(declaration)
        return ok_object(pub(declaration))
    # Quota gate per line: holding must exist, committed availability must cover.
    season_year = store.db.clock.year
    holdings = []
    for line in declaration["lines"]:
        holding = find_holding(trip["vessel_id"], line["fishery_code"], season_year)
        if holding is None:
            raise ApiError(
                404,
                "ERR_QUOTA_HOLDING_NOT_FOUND",
                f"no holding for fishery {line['fishery_code']} and season {season_year}",
            )
        available = domain.availability(holding)["available_committed_pounds"]
        if available < line["declared_lbs"]:
            raise ApiError(
                402,
                "ERR_QUOTA_EXCEEDED",
                "declared pounds exceed available_committed_pounds",
            )
        holdings.append((holding, line["declared_lbs"]))
    # Post the landings.
    opening = get_opening(trip["season_opening_id"])
    for holding, declared in holdings:
        holding["landed_pounds"] += declared
        touch(holding)
        opening["landed_against_tac_pounds"] += declared
    touch(opening)
    declaration["status"] = "VERIFIED"
    touch(declaration)
    if (
        opening["status"] == "OPEN"
        and opening["landed_against_tac_pounds"] >= opening["tac_pounds"]
    ):
        domain.close_opening_cascade(opening, early=True)
    return ok_object(pub(declaration))


@bp.route("/landing-declarations/<rid>/amend", methods=["POST"])
def amend_declaration(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    declaration = get_declaration(rid)
    trip = get_trip(declaration["trip_id"])
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if declaration["status"] != "DISPUTED":
        raise ApiError(409, "ERR_DECLARATION_NOT_DISPUTED", "amend requires DISPUTED")
    payload = body()
    declaration["lines"] = _validate_lines(payload.get("lines"))
    declaration["status"] = "AMENDED"
    touch(declaration)
    return ok_object(pub(declaration))


@bp.route("/landing-declarations/<rid>/finalize", methods=["POST"])
def finalize_declaration(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    declaration = get_declaration(rid)
    if declaration["status"] != "VERIFIED":
        raise ApiError(409, "ERR_DECLARATION_NOT_VERIFIED", "finalize requires VERIFIED")
    declaration["status"] = "FINALIZED"
    touch(declaration)
    trip = get_trip(declaration["trip_id"])
    if trip["status"] == "RETURNED":
        trip["status"] = "LANDING_FINALIZED"
        touch(trip)
    return ok_object(pub(declaration))
