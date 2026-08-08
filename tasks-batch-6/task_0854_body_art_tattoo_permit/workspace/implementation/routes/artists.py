"""Artist routes — PRD §3.2, §3.8."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_artist, require_owns_establishment
from envelope import array_response, force, send, watch
from errors import ApiError
from util import days

bp = Blueprint("artists", __name__)


@bp.post("/body-art/artists")
def create_artist():
    caller = authenticate(["HealthOfficer", "EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    legal_name = V.req_string(data, "legal_name", 1, 120)
    est = V.get_establishment(establishment_id)
    require_owns_establishment(caller, establishment_id)

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "legal_name": legal_name,
            "permit_status": "PENDING",
            "bbp_training_completed_on": None,
            "bbp_training_expires_on": None,
            "bbp_recert_required": False,
            "permit_expires_on": None,
        }
    )
    store.artists[rec["id"]] = rec
    return send(lambda: serialize.artist(rec), 201)


@bp.get("/body-art/artists/<artist_id>")
def read_artist(artist_id):
    authenticate(
        ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator", "Artist"]
    )
    artist = V.get_artist(artist_id)
    return send(lambda: serialize.artist(artist), 200)


@bp.get("/body-art/artists")
def list_artists():
    authenticate(
        ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]
    )
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    permit_status = V.filter_enum("permit_status", config.ARTIST_PERMIT_STATUSES)

    rows = store.sorted_rows(store.artists)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if permit_status is not None:
        rows = [r for r in rows if r["permit_status"] == permit_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.artist(r) for r in page], limit, offset, total)


@bp.post("/body-art/artists/<artist_id>/bbp-training")
def record_bbp_training(artist_id):
    caller = authenticate(["Artist", "EstablishmentOperator"])
    artist = V.get_artist(artist_id)
    data = V.body()
    completed_on = V.req_datetime(data, "completed_on")
    require_owns_artist(caller, artist_id, artist)

    est = store.establishments.get(artist["establishment_id"])
    watch(artist)
    artist["bbp_training_completed_on"] = completed_on
    artist["bbp_training_expires_on"] = completed_on + days(
        config.BBP_TRAINING_VALIDITY_DAYS
    )
    artist["bbp_recert_required"] = False

    if artist["permit_status"] == "PROBATION" and completed_on <= store.now():
        artist["permit_status"] = "ACTIVE"
        if est is not None:
            force(est)
            domain.recompute_active_artist_count(est)
            domain.recompute_posture(est)
    return send(lambda: serialize.artist(artist), 200)


@bp.post("/body-art/artists/<artist_id>/activate")
def activate_artist(artist_id):
    authenticate(["HealthOfficer"])
    artist = V.get_artist(artist_id)
    if artist["permit_status"] != "PENDING":
        raise ApiError("ERR_ARTIST_STATE_INVALID")
    est = store.establishments.get(artist["establishment_id"])
    if est is None or est["permit_status"] != "ACTIVE":
        raise ApiError("ERR_ESTABLISHMENT_PERMIT_NOT_ACTIVE")
    expires = artist["bbp_training_expires_on"]
    if expires is None or expires <= store.now():
        raise ApiError("ERR_ARTIST_BBP_MISSING")

    watch(artist)
    artist["permit_status"] = "ACTIVE"
    artist["permit_expires_on"] = est["permit_expires_on"]
    force(est)
    domain.recompute_active_artist_count(est)
    domain.recompute_posture(est)
    return send(lambda: serialize.artist(artist), 200)


@bp.post("/body-art/artists/<artist_id>/enforcement-actions")
def create_artist_enforcement(artist_id):
    caller = authenticate(["HealthOfficer"])
    artist = V.get_artist(artist_id)
    data = V.body()
    action_type = V.req_enum(data, "action_type", config.ENFORCEMENT_ACTION_TYPES)
    reason_code = V.req_enum(data, "reason_code", config.ENFORCEMENT_REASON_CODES)
    expected_version = V.req_int(data, "expected_artist_version")

    if expected_version != artist["version"]:
        raise ApiError("ERR_STALE_ARTIST_VERSION")
    if domain.active_enforcement_for_artist(artist["id"]) is not None:
        raise ApiError("ERR_ACTIVE_ENFORCEMENT_EXISTS")

    est = store.establishments.get(artist["establishment_id"])
    force(artist)
    action = domain.create_enforcement_action(
        subject_type="ARTIST",
        establishment_id=None,
        artist_id=artist["id"],
        action_type=action_type,
        reason_code=reason_code,
        issued_by_user_id=caller.user_id,
        auto_generated=False,
    )
    domain.apply_artist_enforcement(artist, est, action_type)
    return send(lambda: serialize.enforcement_action(action), 201)
