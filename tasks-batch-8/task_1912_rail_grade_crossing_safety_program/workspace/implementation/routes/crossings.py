"""Crossing inventory endpoints (PRD §3.1)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_CROSSING_NOT_FOUND,
    ERR_DUPLICATE_DOT_NUMBER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LOCALITY_NOT_FOUND,
    ERR_STALE_VERSION,
)
from helpers import (
    body_or_empty,
    get_or_404,
    opt_int_range,
    paginate,
    query_bool,
    query_filter,
    reject_unknown,
    req_enum,
    req_int_range,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import domain

bp = Blueprint("crossings", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

HIGHWAY_CLASSES = ("ARTERIAL", "COLLECTOR", "LOCAL")
DEVICE_CLASSES = ("PASSIVE_CROSSBUCK", "FLASHING_LIGHTS", "GATES", "FOUR_QUADRANT_GATES")

CREATE_FIELDS = (
    "dot_crossing_number",
    "railroad_code",
    "road_authority_locality_id",
    "highway_functional_class",
    "annual_train_count",
    "train_speed_max_mph",
    "aadt",
    "school_bus_count",
    "sight_distance_rating",
    "warning_device_class",
)

PATCH_FIELDS = (
    "expected_crossing_version",
    "annual_train_count",
    "aadt",
    "school_bus_count",
    "sight_distance_rating",
    "warning_device_class",
    "train_speed_max_mph",
)


def serialize_crossing(c):
    return {
        "id": c["id"],
        "dot_crossing_number": c["dot_crossing_number"],
        "railroad_code": c["railroad_code"],
        "road_authority_locality_id": c["road_authority_locality_id"],
        "highway_functional_class": c["highway_functional_class"],
        "annual_train_count": c["annual_train_count"],
        "train_speed_max_mph": c["train_speed_max_mph"],
        "aadt": c["aadt"],
        "school_bus_count": c["school_bus_count"],
        "sight_distance_rating": c["sight_distance_rating"],
        "warning_device_class": c["warning_device_class"],
        "status": c["status"],
        "exposure_index": float(c["exposure_index"]),
        "projected_exposure_index": float(c["projected_exposure_index"]),
        "incident_count_5yr": domain.live_incident_count_5yr(c["id"]),
        "hazard_score": float(c["hazard_score"]),
        "diagnostic_review_due": c["diagnostic_review_due"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/crossings")
def create_crossing():
    auth(["ProgramAdministrator"])
    body = body_or_empty()

    # Priority 3 (existence): body FK road_authority_locality_id, checked when
    # a resolvable string value is supplied.
    loc_id = body.get("road_authority_locality_id")
    if isinstance(loc_id, str) and loc_id and loc_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {loc_id} does not exist")

    # Priority 7 (business constraints): request shape, then uniqueness.
    reject_unknown(body, CREATE_FIELDS)
    dot_crossing_number = req_str(body, "dot_crossing_number")
    railroad_code = req_str(body, "railroad_code")
    road_authority_locality_id = req_str(body, "road_authority_locality_id")
    if road_authority_locality_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {road_authority_locality_id} does not exist")
    highway_functional_class = req_enum(body, "highway_functional_class", HIGHWAY_CLASSES)
    annual_train_count = req_int_range(body, "annual_train_count", 0, None)
    train_speed_max_mph = req_int_range(body, "train_speed_max_mph", 1, 110)
    aadt = req_int_range(body, "aadt", 0, None)
    school_bus_count = opt_int_range(body, "school_bus_count", 0, None, default=0)
    sight_distance_rating = req_int_range(body, "sight_distance_rating", 1, 5)
    warning_device_class = req_enum(body, "warning_device_class", DEVICE_CLASSES)

    if any(c["dot_crossing_number"] == dot_crossing_number for c in store.crossings.values()):
        raise ApiError(ERR_DUPLICATE_DOT_NUMBER, 409, f"dot_crossing_number {dot_crossing_number} already exists")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "dot_crossing_number": dot_crossing_number,
        "railroad_code": railroad_code,
        "road_authority_locality_id": road_authority_locality_id,
        "highway_functional_class": highway_functional_class,
        "annual_train_count": annual_train_count,
        "train_speed_max_mph": train_speed_max_mph,
        "aadt": aadt,
        "school_bus_count": school_bus_count,
        "sight_distance_rating": sight_distance_rating,
        "warning_device_class": warning_device_class,
        "status": "ACTIVE",
        "exposure_index": None,
        "projected_exposure_index": None,
        "hazard_score": None,
        "diagnostic_review_due": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.crossings[rec["id"]] = rec
    domain.recompute_crossing_risk(rec)
    return ok(serialize_crossing(rec), 201)


@bp.get("/crossings")
def list_crossings():
    auth(ALL_ROLES)
    status_f = query_filter("status")
    railroad_f = query_filter("railroad_code")
    locality_f = query_filter("road_authority_locality_id")
    due_f = query_bool("diagnostic_review_due")

    items = []
    for c in store.crossings.values():
        if status_f is not None and c["status"] != status_f:
            continue
        if railroad_f is not None and c["railroad_code"] != railroad_f:
            continue
        if locality_f is not None and c["road_authority_locality_id"] != locality_f:
            continue
        if due_f is not None and c["diagnostic_review_due"] != due_f:
            continue
        items.append(c)
    items = sorted(items, key=lambda c: c["created_at"])
    page, meta = paginate([serialize_crossing(c) for c in items])
    return ok_list(page, meta)


@bp.get("/crossings/<crossing_id>")
def get_crossing(crossing_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.crossings, crossing_id, ERR_CROSSING_NOT_FOUND,
                     f"Crossing {crossing_id} does not exist")
    return ok(serialize_crossing(rec))


@bp.patch("/crossings/<crossing_id>/inventory")
def patch_crossing_inventory(crossing_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.crossings, crossing_id, ERR_CROSSING_NOT_FOUND,
                     f"Crossing {crossing_id} does not exist")
    body = body_or_empty()

    # Priority 5 (OCC): expected_crossing_version compared after existence/state.
    expected = body.get("expected_crossing_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != rec["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                412,
                f"expected_crossing_version {expected} does not match current version {rec['version']}",
            )

    # Priority 7: request shape (incl. the non-optional OCC field).
    reject_unknown(body, PATCH_FIELDS)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'expected_crossing_version' is required and must be an integer")

    updates = {}
    if "annual_train_count" in body:
        updates["annual_train_count"] = req_int_range(body, "annual_train_count", 0, None)
    if "aadt" in body:
        updates["aadt"] = req_int_range(body, "aadt", 0, None)
    if "school_bus_count" in body:
        updates["school_bus_count"] = req_int_range(body, "school_bus_count", 0, None)
    if "sight_distance_rating" in body:
        updates["sight_distance_rating"] = req_int_range(body, "sight_distance_rating", 1, 5)
    if "warning_device_class" in body:
        updates["warning_device_class"] = req_enum(body, "warning_device_class", DEVICE_CLASSES)
    if "train_speed_max_mph" in body:
        updates["train_speed_max_mph"] = req_int_range(body, "train_speed_max_mph", 1, 110)

    rec.update(updates)
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    old_hazard, _ = domain.recompute_crossing_risk(rec)
    domain.run_hazard_staleness_cascade(rec, old_hazard)
    return ok(serialize_crossing(rec))


@bp.post("/crossings/<crossing_id>/confirm-closure")
def confirm_closure(crossing_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.crossings, crossing_id, ERR_CROSSING_NOT_FOUND,
                     f"Crossing {crossing_id} does not exist")
    if rec["status"] != "CLOSURE_PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            f"Crossing must be CLOSURE_PENDING to confirm closure (current: {rec['status']})",
        )
    rec["status"] = "CLOSED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    domain.closure_cascade(rec)
    return ok(serialize_crossing(rec))
