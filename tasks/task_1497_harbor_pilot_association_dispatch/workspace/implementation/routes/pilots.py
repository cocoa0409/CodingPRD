"""Pilots, endorsements, and the rotation board."""
from flask import Blueprint

from db import DB, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import (
    base_entity,
    board_max_position,
    endorsement_view,
    pilot_rotation_entry,
    pilot_view,
    rotation_entry_view,
)
from util import body, pagination_args, paginate, req_dt, req_enum, req_int, req_str

bp = Blueprint("pilots", __name__)

ENDORSEMENT_CLASSES = ("HARBOR", "COASTAL", "UNLIMITED")


def _get_pilot(pid):
    p = DB["pilots"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Pilot does not exist")
    return p


@bp.post("/pilotage/pilots")
def create_pilot():
    auth(["AssociationAdmin"])
    data = body()
    full_name = req_str(data, "full_name")
    license_number = req_str(data, "license_number")
    share_units = req_int(data, "share_units", minimum=1)
    for p in DB["pilots"].values():
        if p["license_number"] == license_number:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "license_number must be unique"
            )

    # Client-injected system/computed fields (status, version, rest_until,
    # duty_minutes_rolling_7d) are ignored.
    pilot = base_entity()
    pilot.update(
        {
            "full_name": full_name,
            "license_number": license_number,
            "share_units": share_units,
            "status": "ACTIVE",
            "rest_until": None,
        }
    )
    DB["pilots"][pilot["id"]] = pilot

    # Every registered pilot has exactly one RotationEntry at the bottom of
    # the board: position max+1, previous_position null, IN_ROTATION.
    entry = base_entity()
    entry.update(
        {
            "pilot_id": pilot["id"],
            "position": board_max_position() + 1,
            "previous_position": None,
            "status": "IN_ROTATION",
        }
    )
    DB["rotation_entries"][entry["id"]] = entry

    return ok(pilot_view(pilot), status=201)


@bp.get("/pilotage/pilots/<pid>")
def get_pilot(pid):
    auth(ANY_ROLE)
    pilot = _get_pilot(pid)
    return ok(pilot_view(pilot))


@bp.post("/pilotage/pilots/<pid>/endorsements")
def create_endorsement(pid):
    auth(["AssociationAdmin"])
    pilot = _get_pilot(pid)
    data = body()

    # OCC on Pilot.version (validation priority 4) precedes structural checks.
    expected = data.get("expected_pilot_version")
    if (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and expected != pilot["version"]
    ):
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_pilot_version differs from the pilot's current version",
        )

    # Structural validation (priority 23 catch-all), including the required
    # OCC field itself.
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Missing or invalid required field: expected_pilot_version",
        )
    endorsement_class = req_enum(data, "endorsement_class", ENDORSEMENT_CLASSES)
    tonnage_cap_gt = req_int(data, "tonnage_cap_gt", minimum=1)
    expires_at = req_dt(data, "expires_at")

    # Per-class supersession: the older same-class CURRENT endorsement flips
    # to SUPERSEDED (a mutation: updated_at refresh + version bump).
    for e in DB["endorsements"].values():
        if (
            e["pilot_id"] == pilot["id"]
            and e["endorsement_class"] == endorsement_class
            and e["status"] == "CURRENT"
        ):
            e["status"] = "SUPERSEDED"
            touch(e)

    endorsement = base_entity()
    endorsement.update(
        {
            "pilot_id": pilot["id"],
            "endorsement_class": endorsement_class,
            "tonnage_cap_gt": tonnage_cap_gt,
            "expires_at": expires_at,
            "status": "CURRENT",
        }
    )
    DB["endorsements"][endorsement["id"]] = endorsement

    # Issuing an endorsement mutates the pilot's supersession view.
    touch(pilot)

    return ok(endorsement_view(endorsement), status=201)


@bp.get("/pilotage/pilots/<pid>/endorsements")
def list_endorsements(pid):
    auth(ANY_ROLE)
    _get_pilot(pid)
    limit, offset = pagination_args()
    items = [
        e
        for e in DB["endorsements"].values()
        if e["pilot_id"] == pid
    ]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([endorsement_view(e) for e in page], total, limit, offset)


@bp.get("/pilotage/pilots/<pid>/rotation-entries")
def list_pilot_rotation_entries(pid):
    auth(ANY_ROLE)
    _get_pilot(pid)
    limit, offset = pagination_args()
    items = [r for r in DB["rotation_entries"].values() if r["pilot_id"] == pid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([rotation_entry_view(r) for r in page], total, limit, offset)


@bp.get("/pilotage/rotation-entries")
def list_rotation_entries():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    status = _optional_query_enum("status", ("IN_ROTATION", "OFF_BOARD"))
    items = list(DB["rotation_entries"].values())
    if status is not None:
        items = [r for r in items if r["status"] == status]
    # Board-wide listing is ordered by position ascending.
    items.sort(key=lambda r: (r["position"], r["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([rotation_entry_view(r) for r in page], total, limit, offset)


def _optional_query_enum(name, choices):
    from flask import request

    v = request.args.get(name)
    if v is None:
        return None
    if v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Query parameter {name} out of range"
        )
    return v
