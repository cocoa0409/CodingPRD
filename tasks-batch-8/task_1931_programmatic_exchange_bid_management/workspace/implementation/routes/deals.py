"""Deal endpoints (PRD §3.3): drafting, review, the renegotiation loop,
pause/resume, lazy expiry, and the per-deal records reverse lookup."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_state, stale_version, unauthorized, ApiError,
    ERR_PUBLISHER_SUSPENDED, ERR_PACKAGE_NOT_ACTIVE, ERR_PARTNER_NOT_ACTIVE,
    ERR_DEAL_NOT_EDITABLE, ERR_DEAL_WINDOW_CLOSED, ERR_INVALID_TIME_RANGE,
    ERR_PG_COMMITMENT_MISMATCH,
)
from middleware import (
    require_roles, ALL_ROLES, ROLE_PUBLISHER_MANAGER, ROLE_EXCHANGE_ADMIN,
)
from response import success_object, success_list, paginate
from util import (
    get_body, req_str, req_int, opt_int, req_enum, opt_enum,
    req_datetime, opt_datetime, has_field,
)
from services.core import (
    DEAL_TYPES, AUCTION_TYPES, EXCLUSIVE_DEAL_TYPES,
    base_record, touch, serialize_deal, serialize_record,
    recompute_package_floor, expire_deal_if_due, expire_all_deals, _sorted,
)

bp = Blueprint("deals", __name__)


def _get_deal_or_404(deal_id):
    d = store.deals.get(deal_id)
    if d is None:
        raise not_found("Deal not found")
    return d


def _require_deal_owner(deal, user_id):
    if deal["publisher_id"] != user_id:
        raise unauthorized("Deal belongs to a different publisher")


def _check_pg_commitment(deal_type, committed):
    """Stage 14 (creation shape): committed_impressions required and > 0 iff
    PROGRAMMATIC_GUARANTEED, forbidden otherwise."""
    if deal_type == "PROGRAMMATIC_GUARANTEED":
        if committed is None or committed <= 0:
            raise ApiError(ERR_PG_COMMITMENT_MISMATCH, 422,
                           "committed_impressions is required and must be > 0 for "
                           "PROGRAMMATIC_GUARANTEED deals")
    else:
        if committed is not None:
            raise ApiError(ERR_PG_COMMITMENT_MISMATCH, 422,
                           "committed_impressions is forbidden for non-PG deal types")


def _liveness_checks(deal):
    """Package / publisher / partner must all be ACTIVE (pinned order:
    package, then publisher, then partner)."""
    pkg = store.packages.get(deal["package_id"])
    if pkg is None or pkg["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_NOT_ACTIVE, 409, "Package is not ACTIVE")
    pub = store.publishers.get(deal["publisher_id"])
    if pub is None or pub["status"] != "ACTIVE":
        raise ApiError(ERR_PUBLISHER_SUSPENDED, 409, "Publisher is not ACTIVE")
    partner = store.partners.get(deal["demand_partner_id"])
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError(ERR_PARTNER_NOT_ACTIVE, 409, "DemandPartner is not ACTIVE")


def _pin_approved_floor(deal):
    pkg = store.packages[deal["package_id"]]
    recompute_package_floor(pkg)
    deal["approved_floor_cpm_micros"] = max(pkg["effective_floor_cpm_micros"],
                                            deal["floor_cpm_micros"])


@bp.route("/deals", methods=["POST"])
def create_deal():
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    package_id = req_str(body, "package_id")
    demand_partner_id = req_str(body, "demand_partner_id")
    deal_type = req_enum(body, "deal_type", DEAL_TYPES)
    auction_type = req_enum(body, "auction_type", AUCTION_TYPES)
    floor = req_int(body, "floor_cpm_micros", min_v=1)
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    committed = opt_int(body, "committed_impressions")
    # existence, left to right: package, then demand partner
    pkg = store.packages.get(package_id)
    if pkg is None:
        raise not_found("InventoryPackage not found")
    partner = store.partners.get(demand_partner_id)
    if partner is None:
        raise not_found("DemandPartner not found")
    # ownership (stage 6): the caller must own the package's publisher
    if pkg["publisher_id"] != user_id:
        raise unauthorized("Package belongs to a different publisher")
    # state gates (stage 6)
    if pkg["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_NOT_ACTIVE, 409, "Package is not ACTIVE")
    if partner["status"] != "ACTIVE":
        raise ApiError(ERR_PARTNER_NOT_ACTIVE, 409, "DemandPartner is not ACTIVE")
    # interval sanity (stage 9): flight is [start_at, end_at), end strictly after start
    if not start_at < end_at:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422, "start_at must be strictly before end_at")
    # PG commitment terms (stage 14)
    _check_pg_commitment(deal_type, committed)
    deal = base_record()
    deal.update({
        "package_id": package_id,
        "publisher_id": pkg["publisher_id"],
        "demand_partner_id": demand_partner_id,
        "deal_type": deal_type,
        "is_exclusive": deal_type in EXCLUSIVE_DEAL_TYPES,
        "auction_type": auction_type,
        "floor_cpm_micros": floor,
        "committed_impressions": committed,
        "delivered_impressions": 0,
        "approved_floor_cpm_micros": None,
        "status": "DRAFT",
        "renegotiation_count": 0,
        "_start_dt": start_at,
        "_end_dt": end_at,
        "_ever_approved": False,
    })
    store.deals[deal["id"]] = deal
    return success_object(serialize_deal(deal), 201)


@bp.route("/deals", methods=["GET"])
def list_deals():
    require_roles(ALL_ROLES)
    expire_all_deals()  # lazy expiry sweep applied to listed deals
    package_id = request.args.get("package_id")
    publisher_id = request.args.get("publisher_id")
    demand_partner_id = request.args.get("demand_partner_id")
    status = request.args.get("status")
    items = list(store.deals.values())
    if package_id is not None:
        items = [d for d in items if d["package_id"] == package_id]
    if publisher_id is not None:
        items = [d for d in items if d["publisher_id"] == publisher_id]
    if demand_partner_id is not None:
        items = [d for d in items if d["demand_partner_id"] == demand_partner_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_deal(d) for d in page], limit, offset, total)


@bp.route("/deals/<dealId>", methods=["GET"])
def get_deal(dealId):
    require_roles(ALL_ROLES)
    deal = _get_deal_or_404(dealId)
    expire_deal_if_due(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>", methods=["PUT"])
def update_deal(dealId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    expected_version = req_int(body, "expected_deal_version")
    floor = opt_int(body, "floor_cpm_micros", min_v=1)
    start_at = opt_datetime(body, "start_at")
    end_at = opt_datetime(body, "end_at")
    committed = opt_int(body, "committed_impressions")
    # auction_type / deal_type are not editable; a present-but-invalid enum is
    # a stage-3 failure, a valid-but-different value is the stage-7 gate below
    new_auction_type = opt_enum(body, "auction_type", AUCTION_TYPES)
    new_deal_type = opt_enum(body, "deal_type", DEAL_TYPES)
    deal = _get_deal_or_404(dealId)
    _require_deal_owner(deal, user_id)
    expire_deal_if_due(deal)
    # stage 7: editable only while DRAFT or RENEGOTIATING; auction_type and
    # deal_type immutable
    if deal["status"] not in ("DRAFT", "RENEGOTIATING"):
        raise ApiError(ERR_DEAL_NOT_EDITABLE, 409,
                       "Deal commercial terms are editable only in DRAFT or RENEGOTIATING")
    if new_auction_type is not None and new_auction_type != deal["auction_type"]:
        raise ApiError(ERR_DEAL_NOT_EDITABLE, 409, "auction_type is immutable")
    if new_deal_type is not None and new_deal_type != deal["deal_type"]:
        raise ApiError(ERR_DEAL_NOT_EDITABLE, 409, "deal_type is immutable")
    # OCC (§2.7)
    if expected_version != deal["version"]:
        raise stale_version("expected_deal_version does not match the deal version")
    merged_start = start_at if start_at is not None else deal["_start_dt"]
    merged_end = end_at if end_at is not None else deal["_end_dt"]
    if not merged_start < merged_end:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422, "start_at must be strictly before end_at")
    if deal["deal_type"] == "PROGRAMMATIC_GUARANTEED":
        merged_committed = committed if committed is not None else deal["committed_impressions"]
        if merged_committed is None or merged_committed <= 0:
            raise ApiError(ERR_PG_COMMITMENT_MISMATCH, 422,
                           "committed_impressions is required and must be > 0 for "
                           "PROGRAMMATIC_GUARANTEED deals")
        if merged_committed < deal["delivered_impressions"]:
            raise ApiError(ERR_PG_COMMITMENT_MISMATCH, 422,
                           "committed_impressions may not be lowered below "
                           "delivered_impressions")
    else:
        if committed is not None:
            raise ApiError(ERR_PG_COMMITMENT_MISMATCH, 422,
                           "committed_impressions is forbidden for non-PG deal types")
    if floor is not None:
        deal["floor_cpm_micros"] = floor
    if start_at is not None:
        deal["_start_dt"] = start_at
    if end_at is not None:
        deal["_end_dt"] = end_at
    if committed is not None:
        deal["committed_impressions"] = committed
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/submit", methods=["POST"])
def submit_deal(dealId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    deal = _get_deal_or_404(dealId)
    _require_deal_owner(deal, user_id)
    expire_deal_if_due(deal)
    if deal["status"] not in ("DRAFT", "RENEGOTIATING"):
        raise invalid_state("Deal is not in DRAFT or RENEGOTIATING")
    _liveness_checks(deal)
    deal["status"] = "PENDING_REVIEW"
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/approve", methods=["POST"])
def approve_deal(dealId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    deal = _get_deal_or_404(dealId)
    expire_deal_if_due(deal)
    if deal["status"] != "PENDING_REVIEW":
        raise invalid_state("Deal is not PENDING_REVIEW")
    _liveness_checks(deal)
    # pin the approved floor: max(package effective floor now, deal floor);
    # blocklists never gate approval (§3.3)
    _pin_approved_floor(deal)
    deal["status"] = "ACTIVE"
    deal["_ever_approved"] = True
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/reject", methods=["POST"])
def reject_deal(dealId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    deal = _get_deal_or_404(dealId)
    expire_deal_if_due(deal)
    if deal["status"] != "PENDING_REVIEW":
        raise invalid_state("Deal is not PENDING_REVIEW")
    deal["status"] = "DRAFT"
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/renegotiate", methods=["POST"])
def renegotiate_deal(dealId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    deal = _get_deal_or_404(dealId)
    _require_deal_owner(deal, user_id)
    expire_deal_if_due(deal)
    if deal["status"] != "ACTIVE":
        raise invalid_state("Deal is not ACTIVE")
    deal["status"] = "RENEGOTIATING"
    deal["renegotiation_count"] += 1
    deal["approved_floor_cpm_micros"] = None
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/pause", methods=["POST"])
def pause_deal(dealId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER, ROLE_EXCHANGE_ADMIN])
    deal = _get_deal_or_404(dealId)
    if role == ROLE_PUBLISHER_MANAGER:
        _require_deal_owner(deal, user_id)
    expire_deal_if_due(deal)
    if deal["status"] != "ACTIVE":
        raise invalid_state("Deal is not ACTIVE")
    deal["status"] = "PAUSED"
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/resume", methods=["POST"])
def resume_deal(dealId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    deal = _get_deal_or_404(dealId)
    _require_deal_owner(deal, user_id)
    expire_deal_if_due(deal)
    if deal["status"] != "PAUSED":
        raise invalid_state("Deal is not PAUSED")
    _liveness_checks(deal)
    now = store.now()
    if not (deal["_start_dt"] <= now < deal["_end_dt"]):
        raise ApiError(ERR_DEAL_WINDOW_CLOSED, 409,
                       "Logical clock is outside the deal flight window; "
                       "the deal must instead be expired")
    _pin_approved_floor(deal)
    deal["status"] = "ACTIVE"
    touch(deal)
    return success_object(serialize_deal(deal))


@bp.route("/deals/<dealId>/records", methods=["GET"])
def deal_records(dealId):
    require_roles(ALL_ROLES)
    deal = _get_deal_or_404(dealId)
    expire_deal_if_due(deal)
    items = [r for r in store.records.values() if r["deal_id"] == dealId]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_record(r) for r in page], limit, offset, total)
