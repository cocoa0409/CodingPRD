"""RenewalOffer routes."""
import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import store, now_iso, parse_iso, format_iso
from errors import (
    ApiError,
    ERR_SOD_VIOLATION,
    ERR_STALE_AGREEMENT_VERSION,
    err_invalid_request,
    err_invalid_state,
    err_invalid_term_length,
    err_not_found,
    err_rate_sum_mismatch,
)
from middleware import require_role
from response import success_list, success_object
from services.posture import recompute_network_posture
from services.serializers import renewal_offer_view, agreement_view


bp = Blueprint("renewal_offers", __name__)


VALID_TERM_MONTHS = {12, 24, 36, 48, 60}
VALID_PROPOSER_ROLES = {"NETWORK_AFFILIATE_RELATIONS", "STATION_GROUP_OWNER"}
CALLER_ROLE_TO_PROPOSER = {
    "NetworkAffiliateRelations": "NETWORK_AFFILIATE_RELATIONS",
    "StationGroupOwner": "STATION_GROUP_OWNER",
}


def _new_id():
    return str(uuid.uuid4())


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be in [1, 100]")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def _paginate(items, limit, offset):
    items = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items)
    return items[offset : offset + limit], total


def _get_scoped(nid, sid, aid, oid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    a = store.agreements.get(aid)
    if a is None or a.get("station_id") != sid:
        raise err_not_found("agreement not found")
    if oid is not None:
        o = store.renewal_offers.get(oid)
        if o is None or o.get("agreement_id") != aid:
            raise err_not_found("renewal offer not found")
        return n, s, a, o
    return n, s, a


def _add_months(dt, months):
    """Add months to a datetime. Uses simple month arithmetic; clamps day-of-month."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # days in target month
    if month == 12:
        next_month_first = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_month_first = dt.replace(year=year, month=month + 1, day=1)
    this_month_first = dt.replace(year=year, month=month, day=1)
    days_in_month = (next_month_first - this_month_first).days
    day = min(dt.day, days_in_month)
    return dt.replace(year=year, month=month, day=day)


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers", methods=["POST"])
def create_renewal_offer(nid, sid, aid):
    user_id, caller_role = require_role("NetworkAffiliateRelations", "StationGroupOwner")
    n, s, a = _get_scoped(nid, sid, aid)
    body = request.get_json(silent=True) or {}
    proposed_by_role = body.get("proposed_by_role")
    prc = body.get("proposed_reverse_comp_pct")
    prs = body.get("proposed_retrans_share_pct")
    ptm = body.get("proposed_term_months")
    expected_ver = body.get("expected_agreement_version")
    if (
        proposed_by_role is None
        or prc is None
        or prs is None
        or ptm is None
        or expected_ver is None
    ):
        raise err_invalid_request("missing required field")
    if proposed_by_role not in VALID_PROPOSER_ROLES:
        raise err_invalid_request("proposed_by_role must be NETWORK_AFFILIATE_RELATIONS or STATION_GROUP_OWNER")
    # Rate sum
    if abs((float(prc) + float(prs)) - 1.0) > 1e-9:
        raise err_rate_sum_mismatch()
    # Term length
    try:
        ptm_int = int(ptm)
    except (TypeError, ValueError):
        raise err_invalid_request("proposed_term_months must be integer")
    if ptm_int not in VALID_TERM_MONTHS:
        raise err_invalid_term_length()
    # OCC on agreement
    if int(expected_ver) != a.get("version", 1):
        raise ApiError(ERR_STALE_AGREEMENT_VERSION, 412, "expected_agreement_version does not match current agreement version")

    # Check existing PROPOSED offer (alternating-turn rule)
    existing_proposed = None
    for o in store.renewal_offers.values():
        if o.get("agreement_id") == aid and o.get("status") == "PROPOSED":
            existing_proposed = o
            break
    if existing_proposed is not None:
        # new offer's proposed_by_role must differ
        if existing_proposed.get("proposed_by_role") == proposed_by_role:
            raise err_invalid_state("alternating turns: new offer must be from the other role")
        prior_round = existing_proposed.get("round_index", 1)
        new_round = prior_round + 1
        # Flip prior PROPOSED -> COUNTERED
        existing_proposed["status"] = "COUNTERED"
        existing_proposed["updated_at"] = now_iso()
        existing_proposed["version"] = existing_proposed.get("version", 1) + 1
    else:
        # First offer: agreement must be in ACTIVE or EXPIRING to enter renewal
        if a.get("status") in ("ACTIVE", "EXPIRING"):
            # Check the 180-day rule if currently ACTIVE
            if a.get("status") == "ACTIVE":
                current_dt = parse_iso(n["current_utc"])
                term_end = parse_iso(a["term_end_utc"])
                threshold = term_end - timedelta(days=180)
                if current_dt < threshold:
                    raise err_invalid_state("agreement not yet eligible for renewal (180-day window)")
            a["status"] = "RENEWAL_NEGOTIATION"
            a["renewal_round_count"] = a.get("renewal_round_count", 0) + 1
            a["updated_at"] = now_iso()
            a["version"] = a.get("version", 1) + 1
            new_round = 1
        elif a.get("status") == "RENEWAL_NEGOTIATION":
            # Subsequent first-in-line offer after prior rejected/withdrawn
            new_round = a.get("renewal_round_count", 0) + 1
            a["renewal_round_count"] = new_round
            a["updated_at"] = now_iso()
            a["version"] = a.get("version", 1) + 1
        else:
            raise err_invalid_state("agreement must be ACTIVE, EXPIRING, or RENEWAL_NEGOTIATION to propose an offer")

    oid = _new_id()
    ts = now_iso()
    offer = {
        "id": oid,
        "agreement_id": aid,
        "proposed_by_role": proposed_by_role,
        "proposed_reverse_comp_pct": prc,
        "proposed_retrans_share_pct": prs,
        "proposed_term_months": ptm_int,
        "round_index": new_round,
        "status": "PROPOSED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.renewal_offers[oid] = offer
    recompute_network_posture(n)
    return success_object(renewal_offer_view(offer), 201)


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers/<oid>", methods=["GET"])
def get_renewal_offer(nid, sid, aid, oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, _, o = _get_scoped(nid, sid, aid, oid)
    return success_object(renewal_offer_view(o))


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers", methods=["GET"])
def list_renewal_offers(nid, sid, aid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid, aid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    items = [o for o in store.renewal_offers.values() if o.get("agreement_id") == aid]
    if status is not None:
        items = [o for o in items if o.get("status") == status]
    items, total = _paginate(items, limit, offset)
    return success_list([renewal_offer_view(o) for o in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers/<oid>/accept", methods=["POST"])
def accept_renewal_offer(nid, sid, aid, oid):
    user_id, caller_role = require_role("NetworkAffiliateRelations", "StationGroupOwner")
    n, s, a, o = _get_scoped(nid, sid, aid, oid)
    if o.get("status") not in ("PROPOSED", "COUNTERED"):
        raise err_invalid_state("offer must be PROPOSED or COUNTERED to accept")
    # SoD: caller role must differ from proposed_by_role
    caller_proposer = CALLER_ROLE_TO_PROPOSER.get(caller_role)
    if caller_proposer == o.get("proposed_by_role"):
        raise ApiError(ERR_SOD_VIOLATION, 403, "proposer cannot accept own offer")
    # Apply terms
    a["reverse_comp_pct"] = o["proposed_reverse_comp_pct"]
    a["retrans_share_pct"] = o["proposed_retrans_share_pct"]
    term_end_dt = parse_iso(a["term_end_utc"])
    new_end = _add_months(term_end_dt, o["proposed_term_months"])
    a["term_end_utc"] = format_iso(new_end)
    a["status"] = "ACTIVE"
    a["updated_at"] = now_iso()
    a["version"] = a.get("version", 1) + 1
    o["status"] = "ACCEPTED"
    o["updated_at"] = now_iso()
    o["version"] = o.get("version", 1) + 1
    # Other PROPOSED|COUNTERED offers on same agreement -> SUPERSEDED
    for other in store.renewal_offers.values():
        if other["id"] == oid:
            continue
        if other.get("agreement_id") != aid:
            continue
        if other.get("status") in ("PROPOSED", "COUNTERED"):
            other["status"] = "SUPERSEDED"
            other["updated_at"] = now_iso()
            other["version"] = other.get("version", 1) + 1
    recompute_network_posture(n)
    return success_object(renewal_offer_view(o))


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers/<oid>/reject", methods=["POST"])
def reject_renewal_offer(nid, sid, aid, oid):
    user_id, caller_role = require_role("NetworkAffiliateRelations", "StationGroupOwner")
    n, s, a, o = _get_scoped(nid, sid, aid, oid)
    if o.get("status") != "PROPOSED":
        raise err_invalid_state("offer must be PROPOSED to reject")
    caller_proposer = CALLER_ROLE_TO_PROPOSER.get(caller_role)
    if caller_proposer == o.get("proposed_by_role"):
        raise ApiError(ERR_SOD_VIOLATION, 403, "proposer cannot reject own offer")
    o["status"] = "REJECTED"
    o["updated_at"] = now_iso()
    o["version"] = o.get("version", 1) + 1
    recompute_network_posture(n)
    return success_object(renewal_offer_view(o))


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/renewal-offers/<oid>/withdraw", methods=["POST"])
def withdraw_renewal_offer(nid, sid, aid, oid):
    user_id, caller_role = require_role("NetworkAffiliateRelations", "StationGroupOwner")
    n, s, a, o = _get_scoped(nid, sid, aid, oid)
    if o.get("status") != "PROPOSED":
        raise err_invalid_state("offer must be PROPOSED to withdraw")
    caller_proposer = CALLER_ROLE_TO_PROPOSER.get(caller_role)
    if caller_proposer != o.get("proposed_by_role"):
        raise ApiError(ERR_SOD_VIOLATION, 403, "only proposer may withdraw offer")
    o["status"] = "WITHDRAWN"
    o["updated_at"] = now_iso()
    o["version"] = o.get("version", 1) + 1
    recompute_network_posture(n)
    return success_object(renewal_offer_view(o))


# Flat reverse-reachability endpoints
@bp.route("/renewal-offers/<oid>", methods=["GET"])
def get_renewal_offer_flat(oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    o = store.renewal_offers.get(oid)
    if o is None:
        raise err_not_found("renewal offer not found")
    return success_object(renewal_offer_view(o))


@bp.route("/renewal-offers", methods=["GET"])
def list_renewal_offers_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    aid = request.args.get("agreement_id")
    items = list(store.renewal_offers.values())
    if aid is not None:
        items = [o for o in items if o.get("agreement_id") == aid]
    items, total = _paginate(items, limit, offset)
    return success_list([renewal_offer_view(o) for o in items], limit, offset, total)
