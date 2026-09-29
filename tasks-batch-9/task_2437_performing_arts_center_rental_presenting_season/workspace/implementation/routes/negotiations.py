"""Artist fee negotiation rounds (PRD section 3.2)."""

from flask import Blueprint

import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import auth, body, page, query_filter, req_int, req_num
from lookup import find_engagement, find_negotiation
from store import public, stamp, store, touch

bp = Blueprint("negotiations", __name__)

MAX_ROUNDS_PER_ENGAGEMENT = 3
MAX_REVISIONS_PER_ROUND = 2


@bp.post("/engagements/<engagement_id>/fee-negotiations")
def open_round(engagement_id):
    user_id, _role = auth("ProgrammingDirector")
    engagement = find_engagement(engagement_id)
    data = body()
    offered_fee = req_int(data, "offered_fee_cents", minimum=0)
    offered_share = req_num(
        data, "offered_artist_share_pct", minimum=0, maximum=1, max_decimals=2
    )
    expected_version = req_int(data, "expected_engagement_version")

    if engagement["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_ENGAGEMENT_NOT_DRAFT")
    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")
    if engagement["engagement_type"] != "PRESENTED":
        raise ApiError(
            "ERR_ENGAGEMENT_TYPE_MISMATCH",
            "Fee negotiations belong to PRESENTED engagements only.",
        )
    if engagement["negotiation_round_count"] >= MAX_ROUNDS_PER_ENGAGEMENT:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    artist = store.artists.get(engagement["artist_id"])
    if artist is not None and offered_fee < artist["guarantee_floor_cents"]:
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")

    for existing in derive.engagement_negotiations(engagement["id"]):
        if existing["status"] in ("OFFERED", "COUNTERED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    engagement["negotiation_round_count"] += 1
    record = {
        "engagement_id": engagement["id"],
        "round_index": engagement["negotiation_round_count"],
        "status": "OFFERED",
        "offered_fee_cents": offered_fee,
        "offered_artist_share_pct": offered_share,
        "counter_fee_cents": None,
        "counter_artist_share_pct": None,
        "revision_count": 0,
        "accepted_fee_cents": None,
        "accepted_share_pct": None,
        "opened_by_user_id": user_id,
        "accepted_by_user_id": None,
    }
    stamp(record)
    store.negotiations[record["id"]] = record
    touch(engagement)
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/fee-negotiations")
def list_rounds(engagement_id):
    auth("ProgrammingDirector", "ArtistRepresentative", "FinanceController")
    engagement = find_engagement(engagement_id)
    items = derive.engagement_negotiations(engagement["id"])
    status = query_filter("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, meta = page(items)
    return array_response([public(r) for r in window], meta)


@bp.post("/fee-negotiations/<negotiation_id>/counter")
def counter_round(negotiation_id):
    user_id, _role = auth("ArtistRepresentative")
    round_rec = find_negotiation(negotiation_id)
    engagement = store.engagements.get(round_rec["engagement_id"])
    if user_id != engagement["artist_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    data = body()
    counter_fee = req_int(data, "counter_fee_cents", minimum=0)
    counter_share = req_num(
        data, "counter_artist_share_pct", minimum=0, maximum=1, max_decimals=2
    )
    if round_rec["status"] != "OFFERED":
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    if engagement["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_ENGAGEMENT_NOT_DRAFT")

    round_rec["status"] = "COUNTERED"
    round_rec["counter_fee_cents"] = counter_fee
    round_rec["counter_artist_share_pct"] = counter_share
    touch(round_rec)
    return object_response(public(round_rec))


@bp.post("/fee-negotiations/<negotiation_id>/revise-offer")
def revise_offer(negotiation_id):
    auth("ProgrammingDirector")
    round_rec = find_negotiation(negotiation_id)
    engagement = store.engagements.get(round_rec["engagement_id"])
    data = body()
    offered_fee = req_int(data, "offered_fee_cents", minimum=0)
    offered_share = req_num(
        data, "offered_artist_share_pct", minimum=0, maximum=1, max_decimals=2
    )
    if round_rec["status"] != "COUNTERED":
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    if round_rec["revision_count"] >= MAX_REVISIONS_PER_ROUND:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    artist = store.artists.get(engagement["artist_id"]) if engagement else None
    if artist is not None and offered_fee < artist["guarantee_floor_cents"]:
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")

    round_rec["status"] = "OFFERED"
    round_rec["offered_fee_cents"] = offered_fee
    round_rec["offered_artist_share_pct"] = offered_share
    round_rec["revision_count"] += 1
    round_rec["counter_fee_cents"] = None
    round_rec["counter_artist_share_pct"] = None
    touch(round_rec)
    return object_response(public(round_rec))


@bp.post("/fee-negotiations/<negotiation_id>/accept")
def accept_round(negotiation_id):
    user_id, role = auth("ProgrammingDirector", "ArtistRepresentative")
    round_rec = find_negotiation(negotiation_id)
    engagement = store.engagements.get(round_rec["engagement_id"])
    if role == "ArtistRepresentative" and user_id != engagement["artist_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    required_state = "OFFERED" if role == "ArtistRepresentative" else "COUNTERED"
    if round_rec["status"] != required_state:
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    for sibling in derive.engagement_negotiations(engagement["id"]):
        if sibling["id"] != round_rec["id"] and sibling["status"] == "ACCEPTED":
            raise ApiError(
                "ERR_NEGOTIATION_NOT_OPEN",
                "Another round of this engagement is already ACCEPTED.",
            )
    if engagement["financial_clearance"] == "BLOCKED":
        raise ApiError("ERR_CLEARANCE_BLOCKED")

    if required_state == "OFFERED":
        accepted_fee = round_rec["offered_fee_cents"]
        accepted_share = round_rec["offered_artist_share_pct"]
    else:
        accepted_fee = round_rec["counter_fee_cents"]
        accepted_share = round_rec["counter_artist_share_pct"]

    round_rec["accepted_fee_cents"] = accepted_fee
    round_rec["accepted_share_pct"] = accepted_share
    round_rec["accepted_by_user_id"] = user_id
    round_rec["status"] = "ACCEPTED"
    touch(round_rec)

    engagement["negotiated_fee_cents"] = accepted_fee
    engagement["artist_share_pct"] = accepted_share
    engagement["fee_accepted_by_user_id"] = user_id
    margin = derive.recompute_projected_margin_only(engagement)
    if margin < 0 and engagement["financial_clearance"] == "CLEARED":
        engagement["financial_clearance"] = "ESCALATED"
        engagement["risk_tier"] = "HIGH"
    touch(engagement)
    return object_response(public(round_rec))
