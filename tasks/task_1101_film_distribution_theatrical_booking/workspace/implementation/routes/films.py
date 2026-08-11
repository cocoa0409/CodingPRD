"""Film endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_distributor_frozen,
    err_wide_gate, err_stale_version, err_not_found,
)
from services.core import (
    serialize_film, get_film, get_distributor, new_entity_common, touch,
    compute_distributor_posture, compute_screens_committed,
)
from util import parse_dt, iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("films", __name__)


GENRES = {"NARRATIVE", "DOCUMENTARY", "ANIMATION", "GENRE_HORROR"}
RATINGS = {"G", "PG", "PG13", "R", "NC17"}
PATTERNS = {"WIDE", "LIMITED", "PLATFORM"}


@bp.route("/distributors/<did>/films", methods=["POST"])
@require_roles("Booker")
def create_film(did, _user_id, _role):
    d = get_distributor(did)
    body = get_json_body()
    require_fields(body, ["title", "genre", "runtime_minutes", "rating",
                          "release_pattern", "target_release_date", "min_screens_for_wide"])
    if body["genre"] not in GENRES:
        raise err_invalid_request("genre must be one of NARRATIVE|DOCUMENTARY|ANIMATION|GENRE_HORROR")
    if body["rating"] not in RATINGS:
        raise err_invalid_request("rating must be G|PG|PG13|R|NC17")
    if body["release_pattern"] not in PATTERNS:
        raise err_invalid_request("release_pattern must be WIDE|LIMITED|PLATFORM")
    if not isinstance(body["runtime_minutes"], int):
        raise err_invalid_request("runtime_minutes must be integer")
    if not isinstance(body["min_screens_for_wide"], int):
        raise err_invalid_request("min_screens_for_wide must be integer")
    trd = parse_dt(body["target_release_date"])
    if trd is None:
        raise err_invalid_request("target_release_date must be ISO 8601")
    common = new_entity_common()
    twe = trd + timedelta(days=90)
    f = {
        **common,
        "distributor_id": did,
        "title": body["title"],
        "genre": body["genre"],
        "runtime_minutes": body["runtime_minutes"],
        "rating": body["rating"],
        "release_pattern": body["release_pattern"],
        "target_release_date": iso_from_dt(trd),
        "min_screens_for_wide": body["min_screens_for_wide"],
        "lifecycle_status": "PRE_RELEASE",
        "theatrical_window_end": iso_from_dt(twe),
    }
    db.films[f["id"]] = f
    return success_object(serialize_film(f), 201)


@bp.route("/distributors/<did>/films/<fid>", methods=["GET"])
@require_roles("Any")
def read_film(did, fid, _user_id, _role):
    return success_object(serialize_film(get_film(did, fid)))


@bp.route("/distributors/<did>/films", methods=["GET"])
@require_roles("Any")
def list_films(did, _user_id, _role):
    get_distributor(did)
    items = [f for f in db.films.values() if f["distributor_id"] == did]
    from flask import request
    filters = {}
    for k in ("lifecycle_status", "release_pattern", "distributor_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_film, filters)


@bp.route("/distributors/<did>/films/<fid>/open_release", methods=["POST"])
@require_roles("Booker")
def open_release(did, fid, _user_id, _role):
    d = get_distributor(did)
    f = get_film(did, fid)
    # Validation priority: 4 FROZEN, 5 INVALID_STATE, 14 WIDE_GATE, 20 STALE_VERSION
    body = get_json_body()
    if compute_distributor_posture(did) == "FROZEN":
        raise err_distributor_frozen()
    if f["lifecycle_status"] != "PRE_RELEASE":
        raise err_invalid_state("Film must be PRE_RELEASE to open")
    if f["release_pattern"] == "WIDE":
        if compute_screens_committed(fid) < f["min_screens_for_wide"]:
            raise err_wide_gate()
    # OCC
    if "expected_film_version" in body:
        if body["expected_film_version"] != f["version"]:
            raise err_stale_version()
    f["lifecycle_status"] = "IN_RELEASE"
    touch(f)
    return success_object(serialize_film(f))


@bp.route("/distributors/<did>/films/<fid>/pull", methods=["POST"])
@require_roles("Booker")
def pull_film(did, fid, _user_id, _role):
    f = get_film(did, fid)
    if f["lifecycle_status"] not in ("PRE_RELEASE", "IN_RELEASE", "HOLDOVER_PHASE"):
        raise err_invalid_state("Film cannot be pulled from this state")
    # No BookingAgreement in ACCEPTED/IN_PLAY/HELD_OVER
    for b in db.booking_agreements.values():
        if b["film_id"] == fid and b["deal_status"] in ("ACCEPTED", "IN_PLAY", "HELD_OVER"):
            raise err_invalid_state("Cannot pull: bookings in ACCEPTED/IN_PLAY/HELD_OVER exist")
    if f["lifecycle_status"] == "PRE_RELEASE":
        # Cancel PROPOSED/COUNTERED agreements
        for b in db.booking_agreements.values():
            if b["film_id"] == fid and b["deal_status"] in ("PROPOSED", "COUNTERED"):
                b["deal_status"] = "CANCELLED"
                touch(b)
    # Cancel SCHEDULED ancillary windows (all three source states)
    for w in db.ancillary_windows.values():
        if w["film_id"] == fid and w["status"] == "SCHEDULED":
            w["status"] = "CANCELLED"
            touch(w)
    f["lifecycle_status"] = "PULLED"
    touch(f)
    return success_object(serialize_film(f))


@bp.route("/distributors/<did>/films/<fid>/request_ancillary_handoff", methods=["POST"])
@require_roles("Booker")
def request_ancillary_handoff(did, fid, _user_id, _role):
    from services.clock import get_logical_clock
    f = get_film(did, fid)
    if f["lifecycle_status"] not in ("IN_RELEASE", "HOLDOVER_PHASE"):
        raise err_invalid_state("Film must be IN_RELEASE or HOLDOVER_PHASE")
    # All bookings terminal
    for b in db.booking_agreements.values():
        if b["film_id"] == fid and b["deal_status"] not in ("COMPLETED", "CANCELLED", "DECLINED"):
            raise err_invalid_state("All BookingAgreements must be terminal for handoff")
    # From IN_RELEASE also: clock >= theatrical_window_end - 7 days
    if f["lifecycle_status"] == "IN_RELEASE":
        now = get_logical_clock()
        twe = parse_dt(f["theatrical_window_end"])
        if twe is None or now < (twe - timedelta(days=7)):
            raise err_invalid_state("Too early for ancillary handoff")
    f["lifecycle_status"] = "ANCILLARY_PENDING"
    touch(f)
    return success_object(serialize_film(f))
