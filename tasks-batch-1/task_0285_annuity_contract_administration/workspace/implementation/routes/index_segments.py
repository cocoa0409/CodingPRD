"""IndexSegment endpoints (INDEXED only) — PRD §3.3.

Two OPEN segments on the same contract+index_name may not overlap, but may abut
(half-open windows; adjacency allowed). Overlap: new.start < existing.end AND
existing.start < new.end -> ERR_SEGMENT_TERM_OVERLAP (409).
"""

from flask import Blueprint

import errors
import validation as v
from clock import iso8601, parse_iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import lookups

bp = Blueprint("index_segments", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def serialize(s):
    return {
        "id": s["id"],
        "contract_id": s["contract_id"],
        "index_name": s["index_name"],
        "term_start_date": s["term_start_date"],
        "term_end_date": s["term_end_date"],
        "segment_premium_cents": s["segment_premium_cents"],
        "cap_bps": s["cap_bps"],
        "floor_bps": s["floor_bps"],
        "participation_bps": s["participation_bps"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _require_dt(body, field):
    raw = v.require_string(body, field)
    dt = parse_iso8601(raw)
    if dt is None:
        raise errors.invalid_request("%s must be an ISO 8601 timestamp." % field)
    return raw, dt


@bp.post("/index-segments")
def create_segment():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    index_name = v.require_string(body, "index_name")
    start_raw, start_dt = _require_dt(body, "term_start_date")
    end_raw, end_dt = _require_dt(body, "term_end_date")
    segment_premium = v.require_int(body, "segment_premium_cents", minimum=1)
    cap_bps = v.require_int(body, "cap_bps")
    floor_bps = v.require_int(body, "floor_bps", required=False, default=0)
    participation_bps = v.require_int(
        body, "participation_bps", required=False, default=10000
    )

    if start_dt >= end_dt:
        raise errors.invalid_request("term_start_date must precede term_end_date.")

    contract = lookups.ref_contract(contract_id)

    # Overlap check against OPEN segments on the same contract + index_name.
    for s in store.index_segments.values():
        if (
            s["contract_id"] == contract_id
            and s["index_name"] == index_name
            and s["status"] == "OPEN"
        ):
            ex_start = parse_iso8601(s["term_start_date"])
            ex_end = parse_iso8601(s["term_end_date"])
            if start_dt < ex_end and ex_start < end_dt:
                raise errors.ApiError(
                    errors.ERR_SEGMENT_TERM_OVERLAP,
                    409,
                    "Index segment term window overlaps an OPEN segment.",
                )

    now = store.clock.now()
    sid = store.new_id()
    segment = {
        "id": sid,
        "contract_id": contract_id,
        "index_name": index_name,
        "term_start_date": start_raw,
        "term_end_date": end_raw,
        "segment_premium_cents": segment_premium,
        "cap_bps": cap_bps,
        "floor_bps": floor_bps,
        "participation_bps": participation_bps,
        "status": "OPEN",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.index_segments[sid] = segment
    return object_response(serialize(segment), 201, now)


@bp.get("/index-segments/<rid>")
def get_segment(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    segment = lookups.path_segment(rid)
    return object_response(serialize(segment), 200, store.clock.now())
