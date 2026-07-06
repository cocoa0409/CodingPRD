"""Exchange routes — the most rule-dense entity."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE,
                    ERR_MEMBER_SUSPENDED, ERR_INSUFFICIENT_BALANCE,
                    ERR_EXCHANGE_TIME_CONFLICT, ERR_TRUST_TIER_TOO_LOW)
from response import envelope_object, envelope_array
from services import validators, pagination, balance, ledger
from services.serializers import exchange_dto
from db import parse_iso

bp = Blueprint("exchanges", __name__)

TIER_ORDER = {"UNVERIFIED": 0, "BASIC": 1, "TRUSTED": 2, "ANCHOR": 3}


def _exchange_windows_overlap(a_start, a_dur_min, b_start, b_dur_min, buffer_min=30):
    """Return True if extended windows overlap (with 30-min buffer both sides)."""
    a_lo = a_start - buffer_min * 60
    a_hi = a_start + a_dur_min * 60 + buffer_min * 60
    b_lo = b_start - buffer_min * 60
    b_hi = b_start + b_dur_min * 60 + buffer_min * 60
    # Overlap if intervals intersect (open-right semantics; but with buffer
    # touching endpoints is a full overlap — we treat overlap as strict half-open).
    return a_lo < b_hi and b_lo < a_hi


@bp.route("/exchanges", methods=["POST"])
def create_exchange():
    user_id, _ = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, [
        "offer_id", "request_id", "scheduled_start_utc", "committed_minutes"
    ])
    offer_id = validators.require_str(payload, "offer_id")
    request_id = validators.require_str(payload, "request_id")
    sched_iso = validators.require_datetime(payload, "scheduled_start_utc")
    committed = validators.require_minute_multiple(payload, "committed_minutes", 15, 480)

    # Priority 3: existence (left-to-right)
    offer = db.skill_offers.get(offer_id)
    if offer is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Offer not found")
    req = db.skill_requests.get(request_id)
    if req is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Request not found")

    provider_id = offer["member_id"]
    requester_id = req["member_id"]

    # Priority 6: ownership + provider != requester
    if requester_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be the request owner")
    if provider_id == requester_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "requester and provider must be different members")

    # Priority 7: suspension gate
    requester = db.members.get(requester_id)
    if requester is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Requester member not found")
    provider = db.members.get(provider_id)
    if provider is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Provider member not found")
    # refresh strikes
    balance.recompute_member_snapshot(requester_id, bump_version=False)
    if requester["is_suspended"]:
        raise_err(ERR_MEMBER_SUSPENDED, "requester is suspended")

    # Priority 8: fiscal balance gate
    if requester["forward_looking_balance_minutes"] < committed:
        raise_err(ERR_INSUFFICIENT_BALANCE, "requester balance insufficient")

    # Priority 10: temporal-overlap on Exchanges (30-min buffer both sides)
    sched_ts = parse_iso(sched_iso).timestamp()
    for x in db.exchanges.values():
        if x["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if requester_id not in (x["provider_member_id"], x["requester_member_id"]) and \
           provider_id not in (x["provider_member_id"], x["requester_member_id"]):
            continue
        other_start = parse_iso(x["scheduled_start_utc"]).timestamp()
        # Only conflict for the same member — check each.
        for member_side in (requester_id, provider_id):
            if member_side in (x["provider_member_id"], x["requester_member_id"]):
                if _exchange_windows_overlap(sched_ts, committed,
                                             other_start, x["committed_minutes"]):
                    raise_err(ERR_EXCHANGE_TIME_CONFLICT,
                              "exchange interval overlaps another SCHEDULED/DELIVERED exchange")

    # Priority 11: business_constraint state — request must be OPEN, offer ACTIVE
    if req["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "SkillRequest.status must be OPEN")
    if offer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "SkillOffer.status must be ACTIVE")

    # Priority 12: trust tier
    if TIER_ORDER[requester["trust_tier"]] < TIER_ORDER[offer["required_trust_tier"]]:
        raise_err(ERR_TRUST_TIER_TOO_LOW,
                  f"requester tier {requester['trust_tier']} below required {offer['required_trust_tier']}")

    # Priority 14: schema — committed_minutes MUST equal offer.minutes_per_session
    if committed != offer["minutes_per_session"]:
        raise_err(ERR_INVALID_REQUEST, "committed_minutes must equal offer.minutes_per_session")

    # scheduled_start must lie within [request.earliest, request.latest]
    e_ts = parse_iso(req["earliest_start_utc"]).timestamp()
    l_ts = parse_iso(req["latest_start_utc"]).timestamp()
    if not (e_ts <= sched_ts <= l_ts):
        raise_err(ERR_INVALID_REQUEST,
                  "scheduled_start_utc must lie within request's earliest/latest window")

    # All gates passed. Insert.
    x = {
        "offer_id": offer_id,
        "request_id": request_id,
        "provider_member_id": provider_id,
        "requester_member_id": requester_id,
        "scheduled_start_utc": sched_iso,
        "committed_minutes": committed,
        "status": "SCHEDULED",
        "settled_at_utc": None,
    }
    db.stamp_new(x)
    db.exchanges[x["id"]] = x

    # Side effects
    req["status"] = "MATCHED"
    db.touch(req)
    balance.recompute_member_snapshot(requester_id, bump_version=False)

    return envelope_object(exchange_dto(x), status=201)


@bp.route("/exchanges", methods=["GET"])
def list_exchanges():
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.exchanges.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [x for x in items
                 if member_id in (x["provider_member_id"], x["requester_member_id"])]
    for k in ("provider_member_id", "requester_member_id", "offer_id", "request_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([exchange_dto(x) for x in window], limit, offset, total)


@bp.route("/exchanges/<xid>", methods=["GET"])
def get_exchange(xid):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    x = db.exchanges.get(xid)
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")
    return envelope_object(exchange_dto(x), status=200)


@bp.route("/exchanges/<xid>/mark-delivered", methods=["POST"])
def mark_delivered(xid):
    user_id, _ = require_role({ROLE_MEMBER})
    x = db.exchanges.get(xid)
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")
    if x["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Exchange.status must be SCHEDULED")
    if x["provider_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be exchange.provider_member_id")
    if db.clock_dt() < parse_iso(x["scheduled_start_utc"]):
        raise_err(ERR_INVALID_STATE, "logical clock has not reached scheduled_start_utc")
    x["status"] = "DELIVERED"
    db.touch(x)
    return envelope_object(exchange_dto(x), status=200)


@bp.route("/exchanges/<xid>/settle", methods=["POST"])
def settle_exchange(xid):
    user_id, _ = require_role({ROLE_MEMBER})
    x = db.exchanges.get(xid)
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")
    if x["status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Exchange.status must be DELIVERED")
    if x["requester_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be exchange.requester_member_id")
    end_ts = parse_iso(x["scheduled_start_utc"]).timestamp() + x["committed_minutes"] * 60
    if db.clock_dt().timestamp() < end_ts:
        raise_err(ERR_INVALID_STATE, "logical clock has not reached end of session")
    # No OPEN dispute may reference this exchange
    for d in db.disputes.values():
        if d["exchange_id"] == xid and d["status"] == "OPEN":
            raise_err(ERR_INVALID_STATE, "OPEN dispute exists against this exchange")

    minutes = x["committed_minutes"]
    x["status"] = "SETTLED"
    x["settled_at_utc"] = db.get_clock_iso()
    db.touch(x)
    # Ledger entries: SPENT for requester, EARNED for provider
    ledger.post_entry(member_id=x["requester_member_id"], entry_kind="SPENT",
                      delta_minutes=-minutes, exchange_id=xid)
    ledger.post_entry(member_id=x["provider_member_id"], entry_kind="EARNED",
                      delta_minutes=+minutes, exchange_id=xid)
    balance.recompute_member_snapshot(x["requester_member_id"], bump_version=True)
    balance.recompute_member_snapshot(x["provider_member_id"], bump_version=True)
    # Request MATCHED -> CLOSED
    req = db.skill_requests.get(x["request_id"])
    if req is not None and req["status"] == "MATCHED":
        req["status"] = "CLOSED"
        db.touch(req)
    return envelope_object(exchange_dto(x), status=200)


@bp.route("/exchanges/<xid>/cancel", methods=["POST"])
def cancel_exchange(xid):
    user_id, _ = require_role({ROLE_MEMBER})
    x = db.exchanges.get(xid)
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")
    if x["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Exchange.status must be SCHEDULED")
    if user_id not in (x["provider_member_id"], x["requester_member_id"]):
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be a party to the exchange")
    if db.clock_dt() >= parse_iso(x["scheduled_start_utc"]):
        raise_err(ERR_INVALID_STATE, "cannot cancel on or after scheduled_start_utc")
    x["status"] = "CANCELLED"
    db.touch(x)
    # Roll linked request MATCHED -> OPEN
    req = db.skill_requests.get(x["request_id"])
    if req is not None and req["status"] == "MATCHED":
        req["status"] = "OPEN"
        db.touch(req)
    # Recompute forward-looking balance for requester (pending debit removed)
    balance.recompute_member_snapshot(x["requester_member_id"], bump_version=False)
    return envelope_object(exchange_dto(x), status=200)
