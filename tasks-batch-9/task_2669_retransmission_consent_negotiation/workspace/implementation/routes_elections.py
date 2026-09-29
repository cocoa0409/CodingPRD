"""Carriage elections and the filing fork (PRD 3.3)."""
from flask import Blueprint

import calc
import derive
from common import (
    authenticate,
    body_json,
    pagination,
    paginate,
    present,
    query_enum,
    query_str,
    take_dt,
    take_enum,
    take_int,
    take_str,
)
from envelope import array_response, object_response
from errors import ApiError
from routes_setup import TIERS
from store import (
    ALL_ROLES,
    ELECTION_DEADLINE_UTC,
    base_row,
    clock,
    db,
    fmt_dt,
    now_iso,
    parse_iso,
    touch,
)

bp = Blueprint("elections", __name__)

ELECTION_TYPES = ["RETRANS_CONSENT", "MUST_CARRY"]
ELECTION_STATUSES = [
    "DRAFT", "NEGOTIATING", "ELECTION_EFFECTIVE", "CONSENT_GRANTED", "ELECTION_LAPSED",
]
NON_TERMINAL = ["DRAFT", "NEGOTIATING", "ELECTION_EFFECTIVE"]


def _require_station_actor(user_id, election):
    """Priority 6 -- the acting negotiator must be the election's station."""
    if user_id != election["station_id"]:
        raise ApiError("ERR_NOT_COUNTERPARTY")


def _require_election_window():
    """Priority 20 -- the clock must be at or before ELECTION_DEADLINE_UTC."""
    if clock() > ELECTION_DEADLINE_UTC:
        raise ApiError("ERR_ELECTION_WINDOW_CLOSED")


@bp.post("/retrans/elections")
def create_election():
    authenticate(["StationGroupNegotiator"])
    body = body_json()
    station_id = take_str(body, "station_id")
    distributor_id = take_str(body, "distributor_id")
    cycle_label = take_str(body, "cycle_label", min_len=1, max_len=20)
    election_type = take_enum(body, "election_type", ELECTION_TYPES)
    requested_tier = take_enum(body, "requested_tier", TIERS)
    incumbent_expiry = take_dt(body, "incumbent_expiry_utc")
    incumbent_rate = take_int(body, "incumbent_rate_per_sub_cents", minimum=0, maximum=600)

    derive.get_station(station_id)
    derive.get_distributor(distributor_id)

    for existing in derive.rows_of(db.elections, station_id=station_id,
                                  distributor_id=distributor_id, cycle_label=cycle_label):
        if existing["status"] in NON_TERMINAL:
            raise ApiError("ERR_DUPLICATE_ELECTION")

    row = base_row()
    row.update({
        "station_id": station_id,
        "distributor_id": distributor_id,
        "cycle_label": cycle_label,
        "election_type": election_type,
        "requested_tier": requested_tier,
        "incumbent_expiry_utc": fmt_dt(incumbent_expiry),
        "incumbent_rate_per_sub_cents": incumbent_rate,
        "status": "DRAFT",
        "filed_at_utc": None,
        "withdrawal_reason": None,
    })
    db.elections[row["id"]] = row
    return object_response(derive.election_json(row), 201)


@bp.get("/retrans/elections")
def list_elections():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    station_id = query_str("station_id")
    distributor_id = query_str("distributor_id")
    election_type = query_enum("election_type", ELECTION_TYPES)
    status = query_enum("status", ELECTION_STATUSES)
    cycle_label = query_str("cycle_label")
    rows = derive.rows_of(db.elections)
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if distributor_id is not None:
        rows = [r for r in rows if r["distributor_id"] == distributor_id]
    if election_type is not None:
        rows = [r for r in rows if r["election_type"] == election_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cycle_label is not None:
        rows = [r for r in rows if r["cycle_label"] == cycle_label]
    items, total = paginate(rows, limit, offset, derive.election_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/elections/<election_id>")
def read_election(election_id):
    authenticate(ALL_ROLES)
    election = derive.get_election(election_id)
    return object_response(derive.election_json(election))


@bp.patch("/retrans/elections/<election_id>")
def amend_election(election_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body = body_json()
    election_type = take_enum(body, "election_type", ELECTION_TYPES, required=False)
    requested_tier = take_enum(body, "requested_tier", TIERS, required=False)
    incumbent_rate = take_int(body, "incumbent_rate_per_sub_cents", minimum=0,
                              maximum=600, required=False)
    election = derive.get_election(election_id)
    _require_station_actor(user_id, election)
    if election["status"] != "DRAFT":
        raise ApiError("ERR_ELECTION_NOT_DRAFT")
    _require_election_window()

    if present(body, "election_type"):
        election["election_type"] = election_type
    if present(body, "requested_tier"):
        election["requested_tier"] = requested_tier
    if present(body, "incumbent_rate_per_sub_cents"):
        election["incumbent_rate_per_sub_cents"] = incumbent_rate
    touch(election)
    return object_response(derive.election_json(election))


@bp.post("/retrans/elections/<election_id>/file")
def file_election(election_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body_json(required=False)
    election = derive.get_election(election_id)
    _require_station_actor(user_id, election)
    if election["status"] != "DRAFT":
        raise ApiError("ERR_ELECTION_NOT_DRAFT")
    # Priority 17 -- must-carry is BROADCAST_BASIC only.
    if election["election_type"] == "MUST_CARRY" and election["requested_tier"] != "BROADCAST_BASIC":
        raise ApiError("ERR_MUST_CARRY_NO_NEGOTIATION")
    _require_election_window()

    station = db.stations[election["station_id"]]
    if election["election_type"] == "RETRANS_CONSENT" and station["network_affiliation"] != "INDEPENDENT":
        # Priority 28 -- the requested tier must sit in permitted_tiers on the
        # station's ACTIVE affiliation agreement.
        affiliation = derive.active_affiliation(election["station_id"])
        if affiliation is None or election["requested_tier"] not in affiliation["permitted_tiers"]:
            raise ApiError("ERR_TIER_NOT_PERMITTED")

    election["filed_at_utc"] = now_iso()
    if election["election_type"] == "RETRANS_CONSENT":
        election["status"] = "NEGOTIATING"
        distributor = db.distributors[election["distributor_id"]]
        deadline = calc.blackout_notice_deadline(
            parse_iso(election["incumbent_expiry_utc"]),
            distributor["required_blackout_notice_days"],
        )
        negotiation = base_row()
        negotiation.update({
            "election_id": election["id"],
            "status": "OPEN",
            "impasse_declared_at_utc": None,
            "blackout_notice_deadline_utc": fmt_dt(deadline),
        })
        db.negotiations[negotiation["id"]] = negotiation
    else:
        election["status"] = "ELECTION_EFFECTIVE"
    touch(election)
    touch(station)
    return object_response(derive.election_json(election))


@bp.post("/retrans/elections/<election_id>/withdraw")
def withdraw_election(election_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body = body_json()
    reason = take_str(body, "withdrawal_reason", min_len=1)
    election = derive.get_election(election_id)
    _require_station_actor(user_id, election)
    if election["status"] not in ("NEGOTIATING", "ELECTION_EFFECTIVE"):
        raise ApiError("ERR_ELECTION_NOT_WITHDRAWABLE")
    _require_election_window()

    was_negotiating = election["status"] == "NEGOTIATING"
    election["status"] = "DRAFT"
    election["withdrawal_reason"] = reason
    election["filed_at_utc"] = None
    touch(election)
    touch(db.stations[election["station_id"]])

    if was_negotiating:
        negotiation = derive.negotiation_of_election(election["id"])
        if negotiation is not None:
            negotiation["status"] = "CANCELLED"
            touch(negotiation)
            for offer in derive.offers_of(negotiation["id"]):
                if offer["status"] == "SUBMITTED":
                    offer["status"] = "EXPIRED"
                    touch(offer)
            for notice in derive.notices_of(negotiation["id"]):
                if notice["status"] == "SERVED":
                    notice["status"] = "SUPERSEDED"
                    touch(notice)
    return object_response(derive.election_json(election))


@bp.get("/retrans/elections/<election_id>/negotiations")
def list_election_negotiations(election_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    derive.get_election(election_id)
    rows = derive.rows_of(db.negotiations, election_id=election_id)
    items, total = paginate(rows, limit, offset, derive.negotiation_json)
    return array_response(items, limit, offset, total)
