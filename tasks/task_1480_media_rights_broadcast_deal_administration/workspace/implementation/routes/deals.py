from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import now, parse_iso
from services.system import (deal_terminal_statuses, milestone_active_statuses,
                             suspend_broadcaster_with_consequences)
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_datetime, sorted_by_created, stamp_new, touch)

bp = Blueprint("deals", __name__)


def get_deal_or_404(deal_id):
    d = db.deals.get(deal_id)
    if d is None:
        raise_error("ERR_DEAL_NOT_FOUND")
    return d


@bp.route("/deals", methods=["GET"])
def list_deals():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.deals.values()))
    items = apply_filters(items, [
        ("asset_id", request.args.get("asset_id")),
        ("package_id", request.args.get("package_id")),
        ("winning_bid_id", request.args.get("winning_bid_id")),
        ("status", request.args.get("status")),
        ("broadcaster_id", request.args.get("broadcaster_id")),
        ("posture", request.args.get("posture")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(d) for d in page], limit, offset, total)


@bp.route("/deals/<dealId>", methods=["GET"])
def get_deal(dealId):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_deal_or_404(dealId)))


@bp.route("/deals/<dealId>/execute", methods=["POST"])
def execute_deal(dealId):
    require_roles({"RightsManager"})
    deal = get_deal_or_404(dealId)
    body = get_json_body()
    if "expected_deal_version" not in body:
        raise_error("ERR_INVALID_REQUEST", "expected_deal_version is required")
    expected = body["expected_deal_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error("ERR_INVALID_REQUEST", "expected_deal_version must be an integer")
    if expected != deal["version"]:
        raise_error("ERR_STALE_DEAL_VERSION")
    if deal["status"] != "DRAFT":
        raise_error("ERR_DEAL_NOT_DRAFT")
    term_start = req_datetime(body, "term_start", parse_iso)
    term_end = req_datetime(body, "term_end", parse_iso)
    if term_start >= term_end:
        raise_error("ERR_INVALID_TERM")

    # Business gates, in order: unresolved conflicts → payment schedule → production obligation.
    for c in db.rights_conflicts.values():
        if c["left_entity_kind"] == "DEAL" and c["left_entity_id"] == deal["id"]:
            raise_error("ERR_UNRESOLVED_RIGHTS_CONFLICT")
    milestones = [m for m in db.payment_milestones.values() if m["deal_id"] == deal["id"]]
    if not milestones:
        raise_error("ERR_NO_PAYMENT_SCHEDULE")
    obligations = [o for o in db.production_obligations.values() if o["deal_id"] == deal["id"]]
    if not obligations:
        raise_error("ERR_NO_PRODUCTION_OBLIGATION")

    deal["term_start"] = term_start
    deal["term_end"] = term_end
    deal["executed_at"] = now()

    # total_contracted_fee_cents: sum of escalated_rights_fee over all seasons.
    calc.recompute_all_allocations(deal)
    deal["total_contracted_fee_cents"] = calc.total_contracted_fee(deal)

    # audience_commitment_basis_points = guaranteed_rating_bp * audience_commitment_pct.
    asset = db.rights_assets.get(deal["asset_id"])
    bid = db.bids.get(deal["winning_bid_id"])
    if asset is not None and bid is not None:
        raw = Decimal(asset["guaranteed_rating_basis_points"]) * Decimal(str(bid["audience_commitment_pct"]))
        deal["audience_commitment_basis_points"] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    deal["status"] = "EXECUTED"
    touch(deal)
    calc.refresh_posture(deal)
    return success_object(serialize(deal))


@bp.route("/deals/<dealId>/open-renewal", methods=["POST"])
def open_renewal(dealId):
    require_roles({"RightsManager"})
    deal = get_deal_or_404(dealId)
    if deal["status"] != "ACTIVE":
        raise_error("ERR_DEAL_NOT_ACTIVE")
    now_dt = now()
    window_start = deal["term_end"] - timedelta(days=calc.RENEWAL_WINDOW_DAYS)
    if now_dt < window_start:
        raise_error("ERR_RENEWAL_WINDOW_NOT_OPEN")
    if now_dt >= deal["term_end"]:
        raise_error("ERR_DEAL_ALREADY_EXPIRED")
    if deal.get("posture") == "FROZEN":
        raise_error("ERR_DEAL_FROZEN")
    deal["status"] = "RENEWAL_OPEN"
    touch(deal)
    return success_object(serialize(deal))


@bp.route("/deals/<dealId>/terminate-breach", methods=["POST"])
def terminate_breach(dealId):
    require_roles({"ComplianceOfficer"})
    deal = get_deal_or_404(dealId)
    if deal["status"] != "ACTIVE":
        raise_error("ERR_DEAL_NOT_ACTIVE")
    posture_frozen_long_enough = False
    if deal.get("posture") == "FROZEN" and deal.get("posture_frozen_since"):
        if (now() - deal["posture_frozen_since"]).days >= calc.FROZEN_GRACE_DAYS:
            posture_frozen_long_enough = True
    if deal.get("payment_delinquency_count", 0) < calc.BREACH_THRESHOLD and not posture_frozen_long_enough:
        raise_error("ERR_BREACH_CONDITION_NOT_MET")

    for m in db.payment_milestones.values():
        if m["deal_id"] == deal["id"] and m["status"] in milestone_active_statuses():
            m["status"] = "DEFAULTED"
            touch(m)
    for o in db.production_obligations.values():
        if o["deal_id"] == deal["id"] and o["status"] == "TRACKING":
            o["status"] = "SHORTFALL_DECLARED"
            o["shortfall_games"] = o["games_required"] - o["games_delivered"]
            o["shortfall_declared_at"] = now()
            touch(o)
    for s in db.sublicense_requests.values():
        if s["deal_id"] == deal["id"]:
            if s["status"] == "PENDING":
                s["status"] = "REJECTED"
                touch(s)
            elif s["status"] == "APPROVED":
                s["status"] = "REVOKED"
                s["revoked_reason"] = "TERMINATION"
                touch(s)
    deal["status"] = "TERMINATED_BREACH"
    deal["posture"] = "FROZEN"
    if deal.get("posture_frozen_since") is None:
        deal["posture_frozen_since"] = now()
    touch(deal)
    broadcaster = db.broadcasters.get(deal["broadcaster_id"])
    if broadcaster is not None and broadcaster["status"] == "ACCREDITED":
        # §3.9: "the deal's broadcaster is suspended per §3.2" — the §3.2
        # suspension carries its market consequences (live bids withdrawn on
        # OPEN_FOR_BIDS packages, PENDING sublicenses on this broadcaster's
        # deals rejected).
        suspend_broadcaster_with_consequences(broadcaster)
    return success_object(serialize(deal))


@bp.route("/deals/<dealId>/terminate-convenience", methods=["POST"])
def terminate_convenience(dealId):
    require_roles({"RightsManager"})
    deal = get_deal_or_404(dealId)
    if deal["status"] != "ACTIVE":
        raise_error("ERR_DEAL_NOT_ACTIVE")
    if deal.get("payment_delinquency_count", 0) != 0:
        raise_error("ERR_OUTSTANDING_DELINQUENCY")
    deal["status"] = "TERMINATED_CONVENIENCE"
    touch(deal)
    return success_object(serialize(deal))
