"""SeasonalTrueUp endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import _touch, round_half_up

bp = Blueprint("true_ups", __name__)

ALLOWED_CREATE_FIELDS = {"contract_id", "expected_contract_version"}
NORMATIVE_RATES = {"ROCK_SALT": 0.0023, "ICE_MELT_BLEND": 0.0015, "LIQUID_BRINE": 0.0040}


@bp.route("/true-ups", methods=["POST"])
def create_trueup():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    contract_id = body.get("contract_id")
    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id is required", 400)
    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)

    # Contract type check
    if contract.get("contract_type") != "SEASONAL":
        raise ApiError(ERR_CONTRACT_TYPE_FORBIDS, "True-up only for SEASONAL contracts", 409)

    # Contract must be EXPIRED
    if contract.get("status") != "EXPIRED":
        raise ApiError(ERR_INVALID_STATE, f"Contract is {contract.get('status')}, must be EXPIRED", 409)

    # OCC check
    expected_version = body.get("expected_contract_version")
    if expected_version is None:
        raise ApiError(ERR_INVALID_REQUEST, "expected_contract_version is required", 400)
    if expected_version != contract.get("version"):
        raise ApiError(ERR_STALE_CONTRACT_VERSION, f"Expected version {expected_version}, current is {contract.get('version')}", 412)

    # FINAL variant: only VERIFIED/CLOSED events
    billable_statuses = {"BILLABLE_CONFIRMED", "INVOICED", "DISPUTED", "SETTLED"}
    all_visits = [v for v in db.visits.list_all() if v.get("contract_id") == contract_id]

    # Filter to VERIFIED/CLOSED events only
    final_visits = []
    for v in all_visits:
        if v.get("billing_status") not in billable_statuses:
            continue
        event = db.storm_events.get(v.get("storm_event_id"))
        if event and event.get("status") in ("VERIFIED", "CLOSED"):
            final_visits.append(v)

    billable_count = len(final_visits)
    cap = contract.get("seasonal_push_cap") or 0
    overage_pushes = max(0, billable_count - cap)
    overage_cents = overage_pushes * (contract.get("seasonal_overage_rate_cents") or 0)

    sla_miss_count = contract.get("season_sla_miss_count") or 0
    fee = contract.get("seasonal_fee_cents") or 0
    penalty = contract.get("sla_miss_penalty_cents") or 15000
    perf_credit = min(sla_miss_count * penalty, int(fee * 0.20))

    # Materials
    material_actual = 0
    material_normative = 0
    for v in all_visits:
        mats = [m for m in db.materials.list_all() if m.get("visit_id") == v["id"] and m.get("status") == "RECORDED"]
        for m in mats:
            material_actual += m.get("line_cost_cents") or 0
            site = db.sites.get(v.get("site_id"))
            if site:
                area = site.get("pavement_area_sqft") or 0
                mat_type = m.get("material_type")
                rate = NORMATIVE_RATES.get(mat_type, 0)
                snapshot = m.get("rate_per_lb_cents_snapshot") or 0
                material_normative += round_half_up(area * rate * snapshot)

    allowance = 0
    for cs in db.contract_sites.list_all():
        if cs.get("contract_id") == contract_id:
            salt_lbs = cs.get("salt_included_lbs") or 0
            salt_rate = contract.get("salt_rate_per_lb_cents") or 25
            allowance += round_half_up(salt_lbs * salt_rate)

    material_settlement = max(0, min(material_actual, material_normative) - allowance)
    balance = overage_cents + material_settlement - perf_credit

    # Supersede existing DRAFT true-up
    for t in db.true_ups.list_all():
        if t.get("contract_id") == contract_id and t.get("status") == "DRAFT":
            t["status"] = "SUPERSEDED"
            _touch(t)
            db.true_ups.update(t["id"], t)

    trueup = {
        "id": db._new_id(),
        "contract_id": contract_id,
        "status": "DRAFT",
        "billable_push_count": billable_count,
        "overage_pushes": overage_pushes,
        "overage_cents": overage_cents,
        "material_actual_cents": material_actual,
        "material_normative_cents": material_normative,
        "material_allowance_cents": allowance,
        "material_settlement_cents": material_settlement,
        "sla_miss_count": sla_miss_count,
        "performance_credit_cents": perf_credit,
        "balance_due_cents": balance,
        "issued_at": None,
        "settled_at": None,
        "settled_amount_cents": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.true_ups.create(trueup)

    # Increment contract version
    _touch(contract)
    db.contracts.update(contract_id, contract)

    return success_created(trueup)


def _get_trueup_or_404(id):
    t = db.true_ups.get(id)
    if not t:
        raise ApiError(ERR_NOT_FOUND, f"TrueUp {id} not found", 404)
    return t


@bp.route("/true-ups/<id>", methods=["GET"])
def get_trueup(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    trueup = _get_trueup_or_404(id)
    if role == "ClientContact":
        contract = db.contracts.get(trueup.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your true-up", 403)
    return success_object(trueup)


@bp.route("/true-ups", methods=["GET"])
def list_trueups():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    limit, offset = get_pagination()
    all_tus = db.true_ups.list_all()

    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if contract_id:
        all_tus = [t for t in all_tus if t.get("contract_id") == contract_id]
    if status:
        all_tus = [t for t in all_tus if t.get("status") == status]
    if role == "ClientContact":
        all_tus = [t for t in all_tus if db.contracts.get(t.get("contract_id", ""), {}) and db.contracts.get(t.get("contract_id", "")).get("client_id") == user_id]

    all_tus = sorted(all_tus, key=lambda t: t.get("created_at", ""))
    total = len(all_tus)
    page = all_tus[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/true-ups/<id>/issue", methods=["POST"])
def issue_trueup(id):
    user_id, role = require_roles("OpsDispatcher")
    trueup = _get_trueup_or_404(id)
    if trueup["status"] in ("SETTLED", "SUPERSEDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"TrueUp is {trueup['status']} (terminal)", 409)
    if trueup["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot issue from {trueup['status']}", 409)
    trueup["status"] = "ISSUED"
    trueup["issued_at"] = db.now_iso()
    _touch(trueup)
    db.true_ups.update(id, trueup)
    return success_object(trueup)


@bp.route("/true-ups/<id>/settle", methods=["POST"])
def settle_trueup(id):
    user_id, role = require_roles("OpsDispatcher")
    trueup = _get_trueup_or_404(id)
    if trueup["status"] in ("SETTLED", "SUPERSEDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"TrueUp is {trueup['status']} (terminal)", 409)
    if trueup["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot settle from {trueup['status']}", 409)

    body = get_json_body()
    settled_amount = body.get("settled_amount_cents")
    if settled_amount is None:
        raise ApiError(ERR_INVALID_REQUEST, "settled_amount_cents is required", 400)
    if settled_amount != trueup.get("balance_due_cents"):
        raise ApiError(ERR_SETTLEMENT_MISMATCH, f"settled {settled_amount} != balance_due {trueup.get('balance_due_cents')}", 422)

    trueup["status"] = "SETTLED"
    trueup["settled_at"] = db.now_iso()
    trueup["settled_amount_cents"] = settled_amount
    _touch(trueup)
    db.true_ups.update(id, trueup)
    return success_object(trueup)
