from flask import Blueprint

from db import db, base_fields, bump
from middleware import get_auth, require_role
from validators import get_body, req_str
from clock import clock
from errors import err
from response import success
import serializers as S
import services as svc
import derive
import calculations as calc

bp = Blueprint("payouts", __name__)


@bp.route("/payouts", methods=["POST"])
def create_payout():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    contract_id = req_str(body, "contract_id", allow_empty=False)
    if "expected_contract_version" not in body or body["expected_contract_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_contract_version")
    if not isinstance(body["expected_contract_version"], int) or isinstance(body["expected_contract_version"], bool):
        raise err("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")
    expected = body["expected_contract_version"]

    contract = svc.get_contract(contract_id)

    # state legality (priority 7): contract must be FULFILLED
    if contract["status"] != "FULFILLED":
        raise err("ERR_INVALID_STATE", "Payout can only be created against a FULFILLED contract")

    # OCC (priority 8)
    if expected != contract["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", "expected_contract_version does not match contract.version")

    # only one live payout per contract (priority 19)
    for p in db.payouts.values():
        if p["contract_id"] == contract_id and p["status"] in {"PENDING", "RELEASED", "SETTLED"}:
            raise err("ERR_PAYOUT_ALREADY_EXISTS", "A live payout already exists for this contract")

    creator = db.creators.get(contract["creator_id"])
    has_w9 = bool(creator["tax_id_on_file"]) if creator else False
    gross, fee, withholding, net = calc.payout_breakdown(contract["contracted_rate_cents"], has_w9)

    rec = base_fields()
    rec.update({
        "contract_id": contract_id,
        "gross_amount_cents": gross,
        "platform_fee_cents": fee,
        "tax_withholding_cents": withholding,
        "net_amount_cents": net,
        "expected_contract_version": expected,
        "status": "PENDING",
    })
    db.payouts[rec["id"]] = rec

    # creating the payout bumps the contract version (occupies its single slot)
    bump(contract)

    return success(S.payout_view(rec), status=201)


@bp.route("/payouts/<payout_id>", methods=["GET"])
def get_payout(payout_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    p = svc.get_payout(payout_id)
    return success(S.payout_view(p), status=200)


@bp.route("/payouts/<payout_id>/release", methods=["POST"])
def release_payout(payout_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    p = svc.get_payout(payout_id)
    if p["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING payout can be released")
    contract = db.contracts.get(p["contract_id"])
    creator = db.creators.get(contract["creator_id"]) if contract else None

    # W-9 gate (priority 17) — PRD 3.9 lists tax check first, then brand safety
    if not creator or not creator["tax_id_on_file"]:
        raise err("ERR_W9_REQUIRED", "Creator must have a W-9 on file before release")
    derive.recompute_brand_safety_status(creator)
    if creator["brand_safety_status"] == "BLOCKED":
        raise err("ERR_BRAND_SAFETY_BLOCKED", "Creator is BLOCKED on brand safety")

    p["status"] = "RELEASED"
    bump(p)
    return success(S.payout_view(p), status=200)


@bp.route("/payouts/<payout_id>/settle", methods=["POST"])
def settle_payout(payout_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    p = svc.get_payout(payout_id)
    if p["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Only a RELEASED payout can be settled")

    p["status"] = "SETTLED"
    settle_year = clock.now().year
    p["_settled_year"] = settle_year
    bump(p)

    contract = db.contracts.get(p["contract_id"])
    if contract:
        # bubble: FULFILLED -> SETTLED
        if contract["status"] == "FULFILLED":
            contract["status"] = "SETTLED"
            bump(contract)
        # campaign actual_spend += net
        campaign = db.campaigns.get(contract["campaign_id"])
        if campaign:
            campaign["actual_spend_cents"] += p["net_amount_cents"]
        # creator ytd += net (round-then-sum) and 1099 auto-gen at threshold
        creator = db.creators.get(contract["creator_id"])
        if creator:
            derive.recompute_creator_ytd(creator)
            _maybe_generate_1099(creator, settle_year)

    return success(S.payout_view(p), status=200)


def _maybe_generate_1099(creator, tax_year):
    """If post-update YTD >= threshold and no 1099 exists for creator+year,
    auto-generate one frozen at the creator's ytd_paid_cents (PRD 3.9, 3.11)."""
    if creator["ytd_paid_cents"] < calc.TAX_1099_THRESHOLD_CENTS:
        return
    for t in db.tax_forms.values():
        if t["creator_id"] == creator["id"] and t["tax_year"] == tax_year:
            return  # at most one per creator per year
    rec = base_fields()
    rec.update({
        "creator_id": creator["id"],
        "tax_year": tax_year,
        "total_reported_cents": creator["ytd_paid_cents"],
        "status": "GENERATED",
    })
    db.tax_forms[rec["id"]] = rec


@bp.route("/payouts/<payout_id>/fail", methods=["POST"])
def fail_payout(payout_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    p = svc.get_payout(payout_id)
    if p["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING payout can be failed")
    p["status"] = "FAILED"
    bump(p)
    return success(S.payout_view(p), status=200)
