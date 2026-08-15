"""ArtworkVersion endpoints: registration and the revision loop (PRD 3.3)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    approve_artwork,
    get_artwork,
    get_customer,
    sorted_created,
    touch,
)
from util import as_int, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("artworks", __name__)

_CREATE_FIELDS = {"artwork_code", "revision_no", "color_count", "plate_set_cost_cents"}


@bp.post("/label-jobs/customers/<customer_id>/artwork-versions")
def create_artwork(customer_id):
    auth(["PrepressOperator"])
    get_customer(customer_id)
    data = body()
    reject_unknown(data, _CREATE_FIELDS)
    artwork_code = as_str(required(data, "artwork_code"), "artwork_code")
    revision_no = as_int(required(data, "revision_no"), "revision_no")
    color_count = as_int(required(data, "color_count"), "color_count")
    if color_count < 1 or color_count > 8:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "color_count must be between 1 and 8"
        )
    plate_set_cost_cents = as_int(
        required(data, "plate_set_cost_cents"), "plate_set_cost_cents"
    )
    # Revision numbers are strictly monotonic within (customer, artwork_code).
    siblings = [
        a
        for a in DB["artworks"].values()
        if a["customer_id"] == customer_id and a["artwork_code"] == artwork_code
    ]
    if siblings and revision_no <= max(a["revision_no"] for a in siblings):
        raise ApiError(
            "ERR_ARTWORK_REVISION_NOT_MONOTONIC",
            422,
            "revision_no must be strictly greater than the current maximum "
            "revision for this artwork_code",
        )
    ts = now_iso()
    art = {
        "id": new_id(),
        "customer_id": customer_id,
        "artwork_code": artwork_code,
        "revision_no": revision_no,
        "color_count": color_count,
        "plate_set_cost_cents": plate_set_cost_cents,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["artworks"][art["id"]] = art
    return ok(art, 201)


@bp.get("/label-jobs/customers/<customer_id>/artwork-versions")
def list_artworks(customer_id):
    auth(ALL_ROLES)
    get_customer(customer_id)
    limit, offset = pagination_args()
    items = sorted_created(
        a for a in DB["artworks"].values() if a["customer_id"] == customer_id
    )
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/customers/<customer_id>/artwork-versions/<artwork_id>")
def get_one_artwork(customer_id, artwork_id):
    auth(ALL_ROLES)
    get_customer(customer_id)
    return ok(get_artwork(customer_id, artwork_id))


@bp.post("/label-jobs/customers/<customer_id>/artwork-versions/<artwork_id>/submit")
def submit_artwork(customer_id, artwork_id):
    auth(["PrepressOperator"])
    get_customer(customer_id)
    art = get_artwork(customer_id, artwork_id)
    data = body()
    reject_unknown(data, set())
    if art["status"] != "DRAFT":
        raise ApiError(
            "ERR_ARTWORK_NOT_DRAFT", 409, "submit requires artwork in DRAFT"
        )
    art["status"] = "SUBMITTED"
    touch(art)
    return ok(art)


@bp.post("/label-jobs/customers/<customer_id>/artwork-versions/<artwork_id>/approve")
def approve_artwork_endpoint(customer_id, artwork_id):
    auth(["PrepressOperator"])
    get_customer(customer_id)
    art = get_artwork(customer_id, artwork_id)
    data = body()
    reject_unknown(data, set())
    if art["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_ARTWORK_NOT_SUBMITTED", 409, "approve requires artwork in SUBMITTED"
        )
    approve_artwork(art)
    return ok(art)


@bp.post("/label-jobs/customers/<customer_id>/artwork-versions/<artwork_id>/return")
def return_artwork(customer_id, artwork_id):
    auth(["PrepressOperator"])
    get_customer(customer_id)
    art = get_artwork(customer_id, artwork_id)
    data = body()
    reject_unknown(data, set())
    if art["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_ARTWORK_NOT_SUBMITTED", 409, "return requires artwork in SUBMITTED"
        )
    art["status"] = "DRAFT"
    touch(art)
    return ok(art)
