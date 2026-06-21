"""Client endpoints: self-signup, fetch, waivers list, ID verification
state machine (PRD §3.2)."""
from flask import Blueprint, request

import db
from clock import logical_now
from errors import ApiError
from helpers import get_json_body, require_str, require_enum, paginate
from lookups import get_client
from middleware import require_auth
from response import success
from serializers import serialize_client, serialize_waiver
from services import whole_year_age, MIN_AGE_YEARS

bp = Blueprint("clients", __name__)

ID_DOC_TYPES = {"DRIVERS_LICENSE", "PASSPORT", "STATE_ID"}


@bp.route("/studio/clients", methods=["POST"])
def create_client():
    # Anonymous self-signup: no auth headers required.
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    date_of_birth = require_str(body, "date_of_birth")

    # email unique across all clients
    for c in db.clients.values():
        if c["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique")

    client = {
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
        "id_status": "UNVERIFIED",
        "id_document_type": None,
        "verified_age_years": None,
    }
    db.stamp_create(client)
    db.clients[client["id"]] = client
    return success(serialize_client(client), 201)


@bp.route("/studio/clients/<client_id>", methods=["GET"])
@require_auth(["StudioManager", "Client"])
def fetch_client(client_id):
    client = get_client(client_id)
    return success(serialize_client(client), 200)


@bp.route("/studio/clients/<client_id>/waivers", methods=["GET"])
@require_auth(["StudioManager", "Client"])
def list_client_waivers(client_id):
    get_client(client_id)
    items = [w for w in db.waivers.values() if w["client_id"] == client_id]
    page, meta = paginate(items)
    return success([serialize_waiver(w) for w in page], 200,
                   response_type="array", pagination=meta)


@bp.route("/studio/clients/<client_id>/id-verification", methods=["POST"])
@require_auth(["Client"])
def submit_verification(client_id):
    client = get_client(client_id)
    body = get_json_body()
    id_document_type = require_enum(body, "id_document_type", ID_DOC_TYPES)
    # State: allowed only from UNVERIFIED or REJECTED.
    if client["id_status"] not in ("UNVERIFIED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "id-verification submission not allowed from %s" % client["id_status"])
    client["id_document_type"] = id_document_type
    client["id_status"] = "PENDING_REVIEW"
    db.touch(client)
    return success(serialize_client(client), 200)


@bp.route("/studio/clients/<client_id>/id-verification/approve", methods=["POST"])
@require_auth(["StudioManager"])
def approve_verification(client_id):
    client = get_client(client_id)
    get_json_body()  # tolerate empty/JSON body
    if client["id_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "approve not allowed from %s" % client["id_status"])
    # Age gate: whole-year age at approval date must be >= MIN_AGE_YEARS.
    age = whole_year_age(client["date_of_birth"], logical_now())
    if age is None or age < MIN_AGE_YEARS:
        raise ApiError("ERR_UNDERAGE",
                       "Client must be at least %d years old" % MIN_AGE_YEARS)
    client["id_status"] = "VERIFIED"
    client["verified_age_years"] = age
    db.touch(client)
    return success(serialize_client(client), 200)


@bp.route("/studio/clients/<client_id>/id-verification/reject", methods=["POST"])
@require_auth(["StudioManager"])
def reject_verification(client_id):
    client = get_client(client_id)
    get_json_body()  # 'reason' optional, not persisted on the client record
    if client["id_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "reject not allowed from %s" % client["id_status"])
    client["id_status"] = "REJECTED"
    # verified_age_years left null
    db.touch(client)
    return success(serialize_client(client), 200)
