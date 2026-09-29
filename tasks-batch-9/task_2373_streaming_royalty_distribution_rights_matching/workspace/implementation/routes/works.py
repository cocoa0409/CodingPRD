"""Work (metadata catalogue) endpoints (§3.1)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import API_PREFIX, ROLE_RIGHTS_OPS_ANALYST, ROLE_ROYALTY_ADMIN, WORK_TYPES
from db import db, stamp_new
from errors import ApiError
from middleware import require
from response import created_response, object_response, paginate_and_serialize
from services import derive
from validation import normalize_text

bp = Blueprint("works", __name__, url_prefix=API_PREFIX)


@bp.post("/works")
@require(ROLE_RIGHTS_OPS_ANALYST, ROLE_ROYALTY_ADMIN)
def create_work():
    data = validation.body()

    # Item 3: body foreign keys resolve before structural validation.
    linked_work_id = data.get("linked_work_id")
    if isinstance(linked_work_id, str) and linked_work_id:
        lookup.work(linked_work_id)

    work_type = validation.get_enum(data, "work_type", WORK_TYPES)
    identifier = validation.get_string(data, "identifier", max_len=32)
    title = validation.get_string(data, "title", max_len=300)
    artist_credit = validation.get_string(
        data, "artist_credit", required=False, default=None, nullable=True)
    linked_work_id = validation.get_id(
        data, "linked_work_id", required=False, nullable=True)

    if work_type == "RECORDING" and not artist_credit:
        validation.bad("Field 'artist_credit' is required on a RECORDING.")
    if work_type == "COMPOSITION" and artist_credit is not None:
        validation.bad("Field 'artist_credit' must be null on a COMPOSITION.")

    for existing in db.works.values():
        if existing["work_type"] == work_type and existing["identifier"] == identifier:
            raise ApiError("ERR_DUPLICATE_WORK_IDENTIFIER")

    record = {
        "work_type": work_type,
        "identifier": identifier,
        "title": title,
        "artist_credit": artist_credit,
        "linked_work_id": linked_work_id,
        "normalized_title": normalize_text(title),
        "normalized_artist": normalize_text(artist_credit) if artist_credit else None,
        "provisional_match_by_user_id": None,
    }
    stamp_new(record)
    db.works[record["id"]] = record
    return created_response(serializers.work(record))


@bp.get("/works/<work_id>")
@require()
def read_work(work_id):
    work = lookup.work(work_id)
    return object_response(serializers.work(work))


@bp.get("/works")
@require()
def list_works():
    records = lookup.apply_filters(db.works.values(), {
        "work_type": lookup.field("work_type"),
        "linked_work_id": lookup.field("linked_work_id"),
        "rights_state": derive.work_rights_state,
    })
    return paginate_and_serialize(records, serializers.work)
