"""Title plant (chain-of-title) endpoints (PRD §3.1, §3.3).

Plant records are immutable reference data: only id + created_at, no
updated_at/version (PRD §2.4). Adding a LIEN or MORTGAGE record is refused with
ERR_GAP_DEFECT when its recorded_date falls inside the CLOSED gap window
[gap_from_date, gap_to_date] of any COMPLETED TitleSearch on the same parcel whose
order is still gap_open (PRD §3.3).
"""

from flask import Blueprint, request

import errors
from clock import parse_iso8601
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_plant_record
from helpers import (
    get_body, require_str, require_int_min, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("plant_records", __name__)

INSTRUMENT_TYPES = {"DEED", "MORTGAGE", "LIEN", "EASEMENT", "RELEASE"}
GAP_DEFECT_TYPES = {"LIEN", "MORTGAGE"}


def _parse_dt(value, field):
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("%s must be a valid ISO 8601 instant" % field)


def _gap_defect(parcel_id, recorded_dt):
    """True if recorded_dt lands inside the closed gap window of any COMPLETED
    search on parcel_id whose order is still gap_open."""
    for s in db.title_searches.values():
        if s["status"] != "COMPLETED":
            continue
        if s["searched_parcel_id"] != parcel_id:
            continue
        order = db.orders.get(s["order_id"])
        if order is None or not order.get("gap_open"):
            continue
        if s["gap_from_date"] is None or s["gap_to_date"] is None:
            continue
        gap_from = parse_iso8601(s["gap_from_date"])
        gap_to = parse_iso8601(s["gap_to_date"])
        # Closed interval [gap_from, gap_to] — inclusive on both ends.
        if gap_from <= recorded_dt <= gap_to:
            return True
    return False


@bp.route("/title/plant-records", methods=["POST"])
@require_roles("TitleOfficer")
def create_plant_record():
    body = get_body()
    parcel_id = require_str(body, "parcel_id")
    county = require_str(body, "county")
    instrument_type = require_enum(body, "instrument_type", INSTRUMENT_TYPES)
    recorded_date = require_str(body, "recorded_date")
    recorded_dt = _parse_dt(recorded_date, "recorded_date")
    sequence_no = require_int_min(body, "sequence_no", 1)
    grantor = require_str(body, "grantor")
    grantee = require_str(body, "grantee")

    # Gap-defect check (priority 8, temporal): only LIEN/MORTGAGE are policed.
    if instrument_type in GAP_DEFECT_TYPES and _gap_defect(parcel_id, recorded_dt):
        raise errors.ApiError(
            errors.ERR_GAP_DEFECT, 409,
            "Instrument recorded inside an active uninsured gap window")

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "_seq": next_seq(),
        "parcel_id": parcel_id,
        "county": county,
        "instrument_type": instrument_type,
        "recorded_date": recorded_date,
        "sequence_no": sequence_no,
        "grantor": grantor,
        "grantee": grantee,
    }
    db.plant_records[pid] = record
    return success(serialize_plant_record(record), status=201)


@bp.route("/title/plant-records/<pid>", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter")
def get_plant_record(pid):
    record = db.plant_records.get(pid)
    if record is None:
        raise errors.not_found("Plant record not found")
    return success(serialize_plant_record(record), status=200)


@bp.route("/title/plant-records", methods=["GET"])
@require_roles("TitleOfficer", "Underwriter")
def list_plant_records():
    limit, offset = parse_pagination()
    items = list(db.plant_records.values())
    parcel_id = request.args.get("parcel_id")
    if parcel_id is not None:
        items = [p for p in items if p["parcel_id"] == parcel_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_plant_record(p) for p in page], limit, offset, total)
