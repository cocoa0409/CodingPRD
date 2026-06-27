from datetime import timedelta

from flask import Blueprint, request

from db import db, base_fields, bump, now_iso
from middleware import get_auth, require_role
from validators import get_body, req_str
from clock import clock, parse_iso, format_iso
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive
import calculations as calc

bp = Blueprint("contracts", __name__)


@bp.route("/contracts", methods=["POST"])
def sign_contract():
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    body = get_body()
    offer_id = req_str(body, "offer_id", allow_empty=False)
    if "expected_offer_version" not in body or body["expected_offer_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_offer_version")
    if not isinstance(body["expected_offer_version"], int) or isinstance(body["expected_offer_version"], bool):
        raise err("ERR_INVALID_REQUEST", "expected_offer_version must be an integer")
    expected = body["expected_offer_version"]

    # existence (priority 4)
    offer = svc.get_offer(offer_id)
    campaign = svc.get_campaign(offer["campaign_id"])
    creator = svc.get_creator(offer["creator_id"])

    # ownership: acting brand owns the campaign behind the offer
    if campaign["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this offer's campaign")

    # state legality (priority 7): source offer must be ACCEPTED
    if offer["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Source offer is not ACCEPTED")

    # OCC (priority 8)
    if expected != offer["version"]:
        raise err("ERR_STALE_OFFER_VERSION", "expected_offer_version does not match offer.version")

    # brand-safety gate (priority 11)
    derive.recompute_brand_safety_status(creator)
    if creator["brand_safety_status"] == "BLOCKED":
        raise err("ERR_BRAND_SAFETY_BLOCKED", "Creator is BLOCKED on brand safety")

    # exclusivity gate (priority 13)
    excl_days = offer["exclusivity_days"]
    start = clock.now()
    end = start + timedelta(days=excl_days)
    if excl_days > 0:  # zero-length window never conflicts
        for other in db.contracts.values():
            if other["creator_id"] != offer["creator_id"]:
                continue
            if other["status"] not in {"ACTIVE", "FULFILLED"}:
                continue
            o_start = parse_iso(other["exclusivity_start"])
            o_end = parse_iso(other["exclusivity_end"])
            if o_start == o_end:
                continue  # other zero-length window never conflicts
            # half-open overlap: aStart < bEnd AND bStart < aEnd
            if start < o_end and o_start < end:
                raise err("ERR_EXCLUSIVITY_CONFLICT", "Exclusivity window overlaps another contract")

    # budget gate (priority 18)
    derive.recompute_brand_budget(_brand_of_campaign(campaign))
    brand = _brand_of_campaign(campaign)
    if brand["available_budget_cents"] < offer["current_amount_cents"]:
        raise err("ERR_BUDGET_EXCEEDED", "Signing would exceed brand budget")

    # ---- commit ----
    rec = base_fields()
    rec.update({
        "offer_id": offer_id,
        "campaign_id": offer["campaign_id"],
        "creator_id": offer["creator_id"],
        "contracted_rate_cents": offer["current_amount_cents"],
        "pinned_offer_version": offer["version"],
        "exclusivity_start": format_iso(start),
        "exclusivity_end": format_iso(end),
        "status": "ACTIVE",
    })
    db.contracts[rec["id"]] = rec

    # consume offer (bump version)
    bump(offer)

    # debit committed budget on brand + campaign
    derive.recompute_brand_budget(brand)
    derive.recompute_campaign_committed(campaign)

    # bubble-up: first contract on OPEN campaign -> ACTIVE
    if campaign["status"] == "OPEN":
        campaign["status"] = "ACTIVE"
        bump(campaign)

    return success(S.contract_view(rec), status=201)


def _brand_of_campaign(campaign):
    b = db.brands.get(campaign["brand_id"])
    if not b:
        raise err("ERR_NOT_FOUND", "Brand not found")
    return b


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    c = svc.get_contract(contract_id)
    return success(S.contract_view(c), status=200)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    offer_id = request.args.get("offer_id")
    campaign_id = request.args.get("campaign_id")
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    rows = list(db.contracts.values())
    if offer_id is not None:
        rows = [c for c in rows if c["offer_id"] == offer_id]
    if campaign_id is not None:
        rows = [c for c in rows if c["campaign_id"] == campaign_id]
    if creator_id is not None:
        rows = [c for c in rows if c["creator_id"] == creator_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, meta = paginate(rows)
    return success([S.contract_view(c) for c in page], status=200, pagination=meta)


@bp.route("/contracts/<contract_id>/cancel", methods=["POST"])
def cancel_contract(contract_id):
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    c = svc.get_contract(contract_id)
    campaign = db.campaigns.get(c["campaign_id"])
    if not campaign or campaign["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this contract's campaign")
    body = get_body()
    if "expected_contract_version" not in body or body["expected_contract_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_contract_version")
    if not isinstance(body["expected_contract_version"], int) or isinstance(body["expected_contract_version"], bool):
        raise err("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")

    # state legality: only ACTIVE -> CANCELLED
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE contract can be cancelled")

    # precondition: no payout in RELEASED/SETTLED
    for p in db.payouts.values():
        if p["contract_id"] == contract_id and p["status"] in {"RELEASED", "SETTLED"}:
            raise err("ERR_INVALID_STATE", "Cannot cancel: a RELEASED/SETTLED payout exists")

    c["status"] = "CANCELLED"
    bump(c)

    # compensating cascade
    brand = db.brands.get(campaign["brand_id"])
    if brand:
        derive.recompute_brand_budget(brand)
    derive.recompute_campaign_committed(campaign)

    for a in db.attribution_assets.values():
        if a["contract_id"] == contract_id and a["status"] == "ENABLED":
            a["status"] = "DISABLED"
            bump(a)

    for s in db.content_submissions.values():
        if s["contract_id"] == contract_id and s["status"] not in {"APPROVED", "REJECTED"}:
            s["status"] = "REJECTED"
            bump(s)

    return success(S.contract_view(c), status=200)


@bp.route("/contracts/<contract_id>/performance", methods=["GET"])
def contract_performance(contract_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    c = svc.get_contract(contract_id)

    asset_ids = {a["id"] for a in db.attribution_assets.values()
                 if a["contract_id"] == contract_id}
    impressions = 0
    engagements = 0
    sale_revenue = 0
    for e in db.conversion_events.values():
        if e["attribution_asset_id"] not in asset_ids:
            continue
        if e["event_type"] == "IMPRESSION":
            impressions += e["count"]
        elif e["event_type"] == "ENGAGEMENT":
            engagements += e["count"]
        elif e["event_type"] == "SALE":
            sale_revenue += e["revenue_cents"]

    # variant: actual once the contract's payout is SETTLED, else estimated
    settled_payout = None
    for p in db.payouts.values():
        if p["contract_id"] == contract_id and p["status"] == "SETTLED":
            settled_payout = p
            break

    if settled_payout is not None:
        variant = "actual"
        cost_basis = settled_payout["net_amount_cents"]
    else:
        variant = "estimated"
        cost_basis = c["contracted_rate_cents"]

    cpm, cpe, roas = calc.perf_metrics(cost_basis, impressions, engagements, sale_revenue)

    data = {
        "variant": variant,
        "impressions": impressions,
        "engagements": engagements,
        "sale_revenue_cents": sale_revenue,
        "cost_basis_cents": cost_basis,
        "cpm": cpm,
        "cpe": cpe,
        "roas": roas,
    }
    return success(data, status=200)


# ---- nested reads: attribution assets and payouts under a contract ----

@bp.route("/contracts/<contract_id>/attribution-assets", methods=["GET"])
def list_contract_assets(contract_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    svc.get_contract(contract_id)
    rows = [a for a in db.attribution_assets.values() if a["contract_id"] == contract_id]
    page, meta = paginate(rows)
    return success([S.attribution_asset_view(a) for a in page], status=200, pagination=meta)


@bp.route("/contracts/<contract_id>/payouts", methods=["GET"])
def list_contract_payouts(contract_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    svc.get_contract(contract_id)
    status = request.args.get("status")
    rows = [p for p in db.payouts.values() if p["contract_id"] == contract_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, meta = paginate(rows)
    return success([S.payout_view(p) for p in page], status=200, pagination=meta)
