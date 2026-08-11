"""RetransSettlement routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import (
    ApiError,
    ERR_DUPLICATE_COMMITTED_SETTLEMENT,
    ERR_STALE_STATION_VERSION,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.calculations import (
    compute_provisional_share,
    compute_final_share,
    recompute_group_aggregate,
)
from services.serializers import settlement_view


bp = Blueprint("retrans_settlements", __name__)


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


def _get_scoped(nid, sid, rid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if rid is not None:
        r = store.retrans_settlements.get(rid)
        if r is None or r.get("station_id") != sid:
            raise err_not_found("settlement not found")
        return n, s, r
    return n, s


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements", methods=["POST"])
def create_settlement(nid, sid):
    require_role("StationGroupOwner", "NetworkAffiliateRelations")
    _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    agreement_id = body.get("agreement_id")
    period_index = body.get("period_index")
    gross = body.get("gross_retrans_cents")
    if agreement_id is None or period_index is None or gross is None:
        raise err_invalid_request("missing required field")
    if store.agreements.get(agreement_id) is None:
        raise err_invalid_request("agreement_id does not reference an existing AffiliationAgreement")
    rid = _new_id()
    ts = now_iso()
    r = {
        "id": rid,
        "station_id": sid,
        "agreement_id": agreement_id,
        "period_index": int(period_index),
        "gross_retrans_cents": int(gross),
        "net_retrans_cents": None,
        "network_share_cents": None,
        "variant_used": None,
        "status": "DRAFT",
        "outage_credit_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.retrans_settlements[rid] = r
    return success_object(settlement_view(r), 201)


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements/<rid>", methods=["GET"])
def get_settlement(nid, sid, rid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, r = _get_scoped(nid, sid, rid)
    return success_object(settlement_view(r))


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements", methods=["GET"])
def list_settlements(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    period_index = request.args.get("period_index")
    items = [r for r in store.retrans_settlements.values() if r.get("station_id") == sid]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    if period_index is not None:
        try:
            pidx = int(period_index)
        except ValueError:
            raise err_invalid_request("period_index must be integer")
        items = [r for r in items if r.get("period_index") == pidx]
    items, total = _paginate(items, limit, offset)
    return success_list([settlement_view(r) for r in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements/<rid>/commit", methods=["POST"])
def commit_settlement(nid, sid, rid):
    require_role("NetworkAffiliateRelations")
    n, s, r = _get_scoped(nid, sid, rid)
    if r.get("status") != "DRAFT":
        raise err_invalid_state("settlement must be DRAFT to commit")
    body = request.get_json(silent=True) or {}
    expected_station_version = body.get("expected_station_version")
    if expected_station_version is None:
        raise err_invalid_request("expected_station_version is required")
    if int(expected_station_version) != s.get("version", 1):
        raise ApiError(ERR_STALE_STATION_VERSION, 412, "expected_station_version mismatch")
    # Agreement must be ACTIVE
    agreement = store.agreements.get(r.get("agreement_id"))
    if agreement is None:
        raise err_invalid_state("agreement not found")
    if agreement.get("status") != "ACTIVE":
        raise err_invalid_state("agreement must be ACTIVE to commit settlement")
    # No other COMMITTED settlement for same (station_id, period_index)
    for other in store.retrans_settlements.values():
        if other["id"] == rid:
            continue
        if other.get("station_id") != sid:
            continue
        if other.get("period_index") != r["period_index"]:
            continue
        if other.get("status") == "COMMITTED":
            raise ApiError(ERR_DUPLICATE_COMMITTED_SETTLEMENT, 409, "another settlement already COMMITTED for this period")

    # Apply PENDING outage credits linked to this station's outage events for this period.
    # Per PRD §3.6: the commit "applies outage_credit_cents (computed from OutageCredit entries
    # linked to this settlement)" — credits transition from PENDING to APPLIED with
    # settlement_id set. Link all PENDING credits on this station in the settlement's period.
    applied_credits = []
    total_credit_cents = 0
    for c in store.outage_credits.values():
        if c.get("status") != "PENDING":
            continue
        if c.get("station_id") != sid:
            continue
        # Find the outage event to match period
        evt = store.outage_events.get(c.get("outage_event_id"))
        if evt is None:
            continue
        if evt.get("period_index") != r["period_index"]:
            continue
        c["status"] = "APPLIED"
        c["settlement_id"] = rid
        c["updated_at"] = now_iso()
        c["version"] = c.get("version", 1) + 1
        applied_credits.append(c)
        total_credit_cents += int(c.get("credit_cents", 0))

    # Compute net
    net = int(r["gross_retrans_cents"]) - total_credit_cents
    r["net_retrans_cents"] = net
    r["outage_credit_cents"] = total_credit_cents
    # PROVISIONAL share: use current aggregate
    sg = store.station_groups.get(s.get("station_group_id"))
    leverage_tier = sg.get("leverage_tier") if sg else "SMALL"
    current_trailing = sg.get("aggregate_retrans_cents", 0) if sg else 0
    share = compute_provisional_share(
        net,
        agreement["reverse_comp_pct"],
        leverage_tier,
        current_trailing,
    )
    r["network_share_cents"] = share
    r["variant_used"] = "PROVISIONAL"
    r["status"] = "COMMITTED"
    r["updated_at"] = now_iso()
    r["version"] = r.get("version", 1) + 1
    # Bump station version (per endpoint side_effects)
    s["version"] = s.get("version", 1) + 1
    s["updated_at"] = now_iso()
    # Recompute group aggregate
    if sg:
        recompute_group_aggregate(sg["id"], n.get("current_period_index", 0))
        sg["updated_at"] = now_iso()
    return success_object(settlement_view(r))


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements/<rid>/reconcile", methods=["POST"])
def reconcile_settlement(nid, sid, rid):
    require_role("NetworkAffiliateRelations")
    n, s, r = _get_scoped(nid, sid, rid)
    if r.get("status") != "COMMITTED":
        raise err_invalid_state("settlement must be COMMITTED to reconcile")
    if n.get("current_period_index", 0) <= r["period_index"]:
        raise err_invalid_state("network current_period_index must be > settlement.period_index")
    agreement = store.agreements.get(r.get("agreement_id"))
    if agreement is None:
        raise err_invalid_state("agreement not found")
    sg = store.station_groups.get(s.get("station_group_id"))
    leverage_tier = sg.get("leverage_tier") if sg else "SMALL"
    # Compute prior-period trailing aggregate (exclude current period settlements)
    # For FINAL: use snapshot as of end of prior period = aggregate minus any current-period settlements
    # We compute by summing net_retrans_cents for periods <= settlement.period_index - 1
    # within the trailing 4-period window ending at prior period.
    current_period = n.get("current_period_index", 0)
    prior_period = current_period - 1
    lower = prior_period - 3
    prior_trailing = 0
    for other in store.retrans_settlements.values():
        if other.get("status") not in ("COMMITTED", "RECONCILED"):
            continue
        if other.get("period_index") is None:
            continue
        if other["period_index"] < lower or other["period_index"] > prior_period:
            continue
        st = store.stations.get(other.get("station_id"))
        if st is None or st.get("station_group_id") != s.get("station_group_id"):
            continue
        net = other.get("net_retrans_cents")
        if net is None:
            continue
        prior_trailing += int(net)
    share = compute_final_share(
        int(r["net_retrans_cents"]),
        agreement["reverse_comp_pct"],
        leverage_tier,
        prior_trailing,
    )
    r["network_share_cents"] = share
    r["variant_used"] = "FINAL"
    r["status"] = "RECONCILED"
    r["updated_at"] = now_iso()
    r["version"] = r.get("version", 1) + 1
    if sg:
        recompute_group_aggregate(sg["id"], n.get("current_period_index", 0))
        sg["updated_at"] = now_iso()
    return success_object(settlement_view(r))


@bp.route("/networks/<nid>/stations/<sid>/retrans-settlements/<rid>/void", methods=["POST"])
def void_settlement(nid, sid, rid):
    require_role("NetworkAffiliateRelations")
    _, _, r = _get_scoped(nid, sid, rid)
    if r.get("status") != "DRAFT":
        raise err_invalid_state("settlement must be DRAFT to void")
    r["status"] = "VOID"
    r["updated_at"] = now_iso()
    r["version"] = r.get("version", 1) + 1
    return success_object(settlement_view(r))


# Flat reverse-reachability endpoints
@bp.route("/retrans-settlements/<rid>", methods=["GET"])
def get_settlement_flat(rid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    r = store.retrans_settlements.get(rid)
    if r is None:
        raise err_not_found("settlement not found")
    return success_object(settlement_view(r))


@bp.route("/retrans-settlements", methods=["GET"])
def list_settlements_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    aid = request.args.get("agreement_id")
    items = list(store.retrans_settlements.values())
    if sid is not None:
        items = [r for r in items if r.get("station_id") == sid]
    if aid is not None:
        items = [r for r in items if r.get("agreement_id") == aid]
    items, total = _paginate(items, limit, offset)
    return success_list([settlement_view(r) for r in items], limit, offset, total)
