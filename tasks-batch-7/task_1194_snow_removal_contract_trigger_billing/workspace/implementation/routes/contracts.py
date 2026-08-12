"""Contract endpoints — CRUD, lifecycle transitions, renewal, billing/true-up previews."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import (
    recompute_contract_accumulators, _touch, _touch_client,
    check_season_overlap, evaluate_visit_billing, recompute_draft_invoices,
    round_half_up, compute_claim_scores,
)

bp = Blueprint("contracts", __name__)

CONTRACT_CREATE_FIELDS = {
    "client_id", "contract_type", "season_start", "season_end",
    "trigger_depth_inches", "per_push_rate_cents", "hourly_rate_cents",
    "hourly_tier2_rate_cents", "hourly_tier_threshold_minutes",
    "night_premium_pct", "seasonal_fee_cents", "seasonal_push_cap",
    "seasonal_overage_rate_cents", "sla_miss_penalty_cents",
    "require_photo_verification", "salt_rate_per_lb_cents",
    "blend_rate_per_lb_cents", "brine_rate_per_lb_cents", "prior_contract_id",
}

RENEW_FIELDS = {
    "season_start", "season_end", "trigger_depth_inches", "per_push_rate_cents",
    "hourly_rate_cents", "hourly_tier2_rate_cents", "seasonal_fee_cents",
    "seasonal_push_cap", "seasonal_overage_rate_cents", "sla_miss_penalty_cents",
}


def _check_contract_type_fields(body, contract_type):
    """Validate type-conditional required fields."""
    if contract_type == "PER_PUSH":
        if body.get("per_push_rate_cents") is None:
            raise ApiError(ERR_INVALID_REQUEST, "per_push_rate_cents required for PER_PUSH", 400)
    elif contract_type == "HOURLY":
        if body.get("hourly_rate_cents") is None:
            raise ApiError(ERR_INVALID_REQUEST, "hourly_rate_cents required for HOURLY", 400)
        if body.get("hourly_tier2_rate_cents") is None:
            raise ApiError(ERR_INVALID_REQUEST, "hourly_tier2_rate_cents required for HOURLY", 400)
    elif contract_type == "SEASONAL":
        if body.get("seasonal_fee_cents") is None:
            raise ApiError(ERR_INVALID_REQUEST, "seasonal_fee_cents required for SEASONAL", 400)
        if body.get("seasonal_push_cap") is None:
            raise ApiError(ERR_INVALID_REQUEST, "seasonal_push_cap required for SEASONAL", 400)
        if body.get("seasonal_overage_rate_cents") is None:
            raise ApiError(ERR_INVALID_REQUEST, "seasonal_overage_rate_cents required for SEASONAL", 400)


@bp.route("/contracts", methods=["POST"])
def create_contract():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - CONTRACT_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    client_id = body.get("client_id")
    if not client_id:
        raise ApiError(ERR_INVALID_REQUEST, "client_id is required", 400)
    client = db.clients.get(client_id)
    if not client:
        raise ApiError(ERR_NOT_FOUND, f"Client {client_id} not found", 404)

    contract_type = body.get("contract_type")
    if not contract_type or contract_type not in ("PER_PUSH", "SEASONAL", "HOURLY"):
        raise ApiError(ERR_INVALID_REQUEST, "contract_type must be PER_PUSH, SEASONAL, or HOURLY", 400)

    season_start = body.get("season_start")
    season_end = body.get("season_end")
    if not season_start or not season_end:
        raise ApiError(ERR_INVALID_REQUEST, "season_start and season_end are required", 400)
    ss = db._parse_iso(season_start)
    se = db._parse_iso(season_end)
    if not ss or not se:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid season dates", 400)
    if ss > se:
        raise ApiError(ERR_INVALID_REQUEST, "season_start must be <= season_end", 400)

    _check_contract_type_fields(body, contract_type)

    # Validate prior_contract_id if provided
    prior_id = body.get("prior_contract_id")
    if prior_id:
        prior = db.contracts.get(prior_id)
        if not prior:
            raise ApiError(ERR_NOT_FOUND, f"Prior contract {prior_id} not found", 404)

    contract = {
        "id": db._new_id(),
        "client_id": client_id,
        "contract_type": contract_type,
        "season_start": season_start,
        "season_end": season_end,
        "trigger_depth_inches": body.get("trigger_depth_inches", 2.00),
        "per_push_rate_cents": body.get("per_push_rate_cents"),
        "hourly_rate_cents": body.get("hourly_rate_cents"),
        "hourly_tier2_rate_cents": body.get("hourly_tier2_rate_cents"),
        "hourly_tier_threshold_minutes": body.get("hourly_tier_threshold_minutes", 2400),
        "night_premium_pct": body.get("night_premium_pct", 0.25),
        "seasonal_fee_cents": body.get("seasonal_fee_cents"),
        "seasonal_push_cap": body.get("seasonal_push_cap"),
        "seasonal_overage_rate_cents": body.get("seasonal_overage_rate_cents"),
        "sla_miss_penalty_cents": body.get("sla_miss_penalty_cents", 15000),
        "require_photo_verification": body.get("require_photo_verification", True),
        "salt_rate_per_lb_cents": body.get("salt_rate_per_lb_cents", 25),
        "blend_rate_per_lb_cents": body.get("blend_rate_per_lb_cents", 60),
        "brine_rate_per_lb_cents": body.get("brine_rate_per_lb_cents", 35),
        "status": "DRAFT",
        "season_billable_push_count": 0,
        "season_billable_minutes": 0,
        "season_billed_cents": 0,
        "unbilled_billable_cents": 0,
        "season_sla_miss_count": 0,
        "overage_active": False,
        "prior_contract_id": prior_id,
        "renewed_to_contract_id": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.contracts.create(contract)
    return success_created(contract)


def _get_contract_or_404(id):
    c = db.contracts.get(id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, f"Contract {id} not found", 404)
    return c


def _check_contract_ownership(contract, user_id, role):
    if role == "ClientContact" and contract.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your contract", 403)


@bp.route("/contracts/<id>", methods=["GET"])
def get_contract(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    contract = _get_contract_or_404(id)
    _check_contract_ownership(contract, user_id, role)
    return success_object(contract)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    limit, offset = get_pagination()
    all_contracts = db.contracts.list_all()
    # Filters
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    prior_contract_id = request.args.get("prior_contract_id")
    renewed_to_contract_id = request.args.get("renewed_to_contract_id")
    if client_id:
        all_contracts = [c for c in all_contracts if c.get("client_id") == client_id]
    if status:
        all_contracts = [c for c in all_contracts if c.get("status") == status]
    if prior_contract_id:
        all_contracts = [c for c in all_contracts if c.get("prior_contract_id") == prior_contract_id]
    if renewed_to_contract_id:
        all_contracts = [c for c in all_contracts if c.get("renewed_to_contract_id") == renewed_to_contract_id]
    # ClientContact scoping
    if role == "ClientContact":
        all_contracts = [c for c in all_contracts if c.get("client_id") == user_id]
    all_contracts = sorted(all_contracts, key=lambda c: c.get("created_at", ""))
    total = len(all_contracts)
    page = all_contracts[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/contracts/<id>/activate", methods=["POST"])
def activate_contract(id):
    user_id, role = require_roles("OpsDispatcher")
    contract = _get_contract_or_404(id)
    if contract["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Contract is EXPIRED (terminal)", 409)
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot activate from {contract['status']}", 409)

    # Check at least one site
    linked_sites = [cs for cs in db.contract_sites.list_all() if cs.get("contract_id") == id]
    if not linked_sites:
        raise ApiError(ERR_CONTRACT_HAS_NO_SITES, "Contract has no linked sites", 422)

    # Season overlap check for every linked site
    for cs in linked_sites:
        if check_season_overlap(id, cs["site_id"], exclude_contract_id=id):
            raise ApiError(ERR_SEASON_WINDOW_OVERLAP, "Season overlap with another ACTIVE/SUSPENDED contract", 409)

    contract["status"] = "ACTIVE"
    _touch(contract)
    db.contracts.update(id, contract)
    return success_object(contract)


@bp.route("/contracts/<id>/suspend", methods=["POST"])
def suspend_contract(id):
    user_id, role = require_roles("OpsDispatcher")
    contract = _get_contract_or_404(id)
    if contract["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Contract is EXPIRED (terminal)", 409)
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot suspend from {contract['status']}", 409)
    contract["status"] = "SUSPENDED"
    _touch(contract)
    db.contracts.update(id, contract)
    return success_object(contract)


@bp.route("/contracts/<id>/resume", methods=["POST"])
def resume_contract(id):
    user_id, role = require_roles("OpsDispatcher")
    contract = _get_contract_or_404(id)
    if contract["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Contract is EXPIRED (terminal)", 409)
    if contract["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot resume from {contract['status']}", 409)
    contract["status"] = "ACTIVE"
    _touch(contract)
    db.contracts.update(id, contract)
    return success_object(contract)


@bp.route("/contracts/<id>/expire", methods=["POST"])
def expire_contract(id):
    user_id, role = require_roles("OpsDispatcher")
    contract = _get_contract_or_404(id)
    if contract["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Contract is already EXPIRED", 409)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot expire from {contract['status']}", 409)

    # Clock must be strictly > season_end
    clock = db.get_clock()
    se = db._parse_iso(contract.get("season_end"))
    if not se or clock <= se:
        raise ApiError(ERR_INVALID_STATE, "Cannot expire: clock not past season_end", 409)

    # No open work
    open_statuses = {"SCHEDULED", "IN_PROGRESS", "AWAITING_BACKUP"}
    open_visits = [v for v in db.visits.list_all() if v.get("contract_id") == id and v.get("execution_status") in open_statuses]
    if open_visits:
        raise ApiError(ERR_CONTRACT_HAS_OPEN_WORK, "Contract has open work visits", 409)

    contract["status"] = "EXPIRED"
    _touch(contract)
    db.contracts.update(id, contract)
    return success_object(contract)


@bp.route("/contracts/<id>/renew", methods=["POST"])
def renew_contract(id):
    user_id, role = require_roles("OpsDispatcher")
    contract = _get_contract_or_404(id)
    if contract["status"] != "EXPIRED":
        raise ApiError(ERR_INVALID_STATE, "Can only renew EXPIRED contracts", 409)

    # Check no open true-up
    open_trueups = [t for t in db.true_ups.list_all() if t.get("contract_id") == id and t.get("status") in ("DRAFT", "ISSUED")]
    if open_trueups:
        raise ApiError(ERR_RENEWAL_BLOCKED, "Renewal blocked by open true-up", 409)

    body = get_json_body()
    unknown = set(body.keys()) - RENEW_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    new_ss = body.get("season_start")
    new_se = body.get("season_end")
    if not new_ss or not new_se:
        raise ApiError(ERR_INVALID_REQUEST, "season_start and season_end required", 400)
    nss = db._parse_iso(new_ss)
    nse = db._parse_iso(new_se)
    if not nss or not nse:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid season dates", 400)
    old_se = db._parse_iso(contract.get("season_end"))
    if old_se and nss <= old_se:
        raise ApiError(ERR_INVALID_REQUEST, "New season_start must be strictly after old season_end", 400)
    if nss > nse:
        raise ApiError(ERR_INVALID_REQUEST, "season_start must be <= season_end", 400)

    # Build new contract with overrides
    new_contract = {
        "id": db._new_id(),
        "client_id": contract["client_id"],
        "contract_type": contract["contract_type"],
        "season_start": new_ss,
        "season_end": new_se,
        "trigger_depth_inches": body.get("trigger_depth_inches", contract.get("trigger_depth_inches", 2.00)),
        "per_push_rate_cents": body.get("per_push_rate_cents", contract.get("per_push_rate_cents")),
        "hourly_rate_cents": body.get("hourly_rate_cents", contract.get("hourly_rate_cents")),
        "hourly_tier2_rate_cents": body.get("hourly_tier2_rate_cents", contract.get("hourly_tier2_rate_cents")),
        "hourly_tier_threshold_minutes": contract.get("hourly_tier_threshold_minutes", 2400),
        "night_premium_pct": contract.get("night_premium_pct", 0.25),
        "seasonal_fee_cents": body.get("seasonal_fee_cents", contract.get("seasonal_fee_cents")),
        "seasonal_push_cap": body.get("seasonal_push_cap", contract.get("seasonal_push_cap")),
        "seasonal_overage_rate_cents": body.get("seasonal_overage_rate_cents", contract.get("seasonal_overage_rate_cents")),
        "sla_miss_penalty_cents": body.get("sla_miss_penalty_cents", contract.get("sla_miss_penalty_cents", 15000)),
        "require_photo_verification": contract.get("require_photo_verification", True),
        "salt_rate_per_lb_cents": contract.get("salt_rate_per_lb_cents", 25),
        "blend_rate_per_lb_cents": contract.get("blend_rate_per_lb_cents", 60),
        "brine_rate_per_lb_cents": contract.get("brine_rate_per_lb_cents", 35),
        "status": "DRAFT",
        "season_billable_push_count": 0,
        "season_billable_minutes": 0,
        "season_billed_cents": 0,
        "unbilled_billable_cents": 0,
        "season_sla_miss_count": 0,
        "overage_active": False,
        "prior_contract_id": id,
        "renewed_to_contract_id": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.contracts.create(new_contract)

    # Update source contract
    contract["renewed_to_contract_id"] = new_contract["id"]
    _touch(contract)
    db.contracts.update(id, contract)

    return success_created(new_contract)


@bp.route("/contracts/<id>/billing-preview", methods=["GET"])
def billing_preview(id):
    user_id, role = require_roles("OpsDispatcher", "ClientContact")
    contract = _get_contract_or_404(id)
    _check_contract_ownership(contract, user_id, role)

    all_visits = [v for v in db.visits.list_all() if v.get("contract_id") == id and v.get("execution_status") != "CANCELLED"]

    provisional_count = 0
    provisional_cents = 0
    final_count = 0
    final_cents = 0

    for v in all_visits:
        event = db.storm_events.get(v.get("storm_event_id"))
        if not event:
            continue
        if event.get("status") == "VOIDED":
            continue

        # Provisional
        depth = None
        if event["status"] in ("REPORTED", "CHALLENGED"):
            depth = event.get("reported_accumulation_inches")
        elif event["status"] in ("VERIFIED", "CLOSED"):
            depth = event.get("verified_accumulation_inches")

        if depth is not None:
            trigger = None
            if v.get("applied_trigger_depth_inches") is not None:
                trigger = v["applied_trigger_depth_inches"]
            else:
                cs = db.contract_sites.get(v.get("contract_site_id"))
                if cs:
                    trigger = cs.get("effective_trigger_depth_inches")
            if trigger is not None and float(depth) >= float(trigger) and v.get("execution_status") == "COMPLETED":
                provisional_count += 1
                if contract["contract_type"] == "PER_PUSH":
                    rate = v.get("applied_per_push_rate_cents")
                    if rate is None:
                        cs = db.contract_sites.get(v.get("contract_site_id"))
                        rate = cs.get("effective_per_push_rate_cents") if cs else 0
                    provisional_cents += (rate or 0) + (v.get("material_cost_cents") or 0)
                elif contract["contract_type"] == "HOURLY":
                    provisional_cents += (v.get("billable_amount_cents") or 0) + (v.get("material_cost_cents") or 0)
                elif contract["contract_type"] == "SEASONAL":
                    provisional_cents += (v.get("material_cost_cents") or 0)

        # Final
        if event["status"] in ("VERIFIED", "CLOSED"):
            fdepth = event.get("verified_accumulation_inches")
            if fdepth is not None:
                trigger = None
                if v.get("applied_trigger_depth_inches") is not None:
                    trigger = v["applied_trigger_depth_inches"]
                else:
                    cs = db.contract_sites.get(v.get("contract_site_id"))
                    if cs:
                        trigger = cs.get("effective_trigger_depth_inches")
                if trigger is not None and float(fdepth) >= float(trigger) and v.get("execution_status") == "COMPLETED":
                    final_count += 1
                    if contract["contract_type"] == "PER_PUSH":
                        rate = v.get("applied_per_push_rate_cents")
                        if rate is None:
                            cs = db.contract_sites.get(v.get("contract_site_id"))
                            rate = cs.get("effective_per_push_rate_cents") if cs else 0
                        final_cents += (rate or 0) + (v.get("material_cost_cents") or 0)
                    elif contract["contract_type"] == "HOURLY":
                        final_cents += (v.get("billable_amount_cents") or 0) + (v.get("material_cost_cents") or 0)
                    elif contract["contract_type"] == "SEASONAL":
                        final_cents += (v.get("material_cost_cents") or 0)

    return success_object({
        "contract_id": id,
        "provisional_billable_push_count": provisional_count,
        "provisional_billable_cents": provisional_cents,
        "final_billable_push_count": final_count,
        "final_billable_cents": final_cents,
    })


@bp.route("/contracts/<id>/true-up-preview", methods=["GET"])
def trueup_preview(id):
    user_id, role = require_roles("OpsDispatcher", "ClientContact")
    contract = _get_contract_or_404(id)
    _check_contract_ownership(contract, user_id, role)

    if contract.get("contract_type") != "SEASONAL":
        raise ApiError(ERR_CONTRACT_TYPE_FORBIDS, "True-up preview only for SEASONAL contracts", 409)

    # PROJECTED: include REPORTED/CHALLENGED at reported accumulation
    all_visits = [v for v in db.visits.list_all() if v.get("contract_id") == id]

    # Determine billable set (optimistic)
    billable_visits = []
    for v in all_visits:
        if v.get("execution_status") != "COMPLETED":
            continue
        event = db.storm_events.get(v.get("storm_event_id"))
        if not event or event.get("status") == "VOIDED":
            continue
        depth = None
        if event["status"] in ("REPORTED", "CHALLENGED"):
            depth = event.get("reported_accumulation_inches")
        elif event["status"] in ("VERIFIED", "CLOSED"):
            depth = event.get("verified_accumulation_inches")
        if depth is None:
            continue
        trigger = None
        if v.get("applied_trigger_depth_inches") is not None:
            trigger = v["applied_trigger_depth_inches"]
        else:
            cs = db.contract_sites.get(v.get("contract_site_id"))
            if cs:
                trigger = cs.get("effective_trigger_depth_inches")
        if trigger is not None and float(depth) >= float(trigger):
            billable_visits.append(v)

    billable_count = len(billable_visits)
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
    NORMATIVE_RATES = {"ROCK_SALT": 0.0023, "ICE_MELT_BLEND": 0.0015, "LIQUID_BRINE": 0.0040}

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

    # Allowance
    allowance = 0
    for cs in db.contract_sites.list_all():
        if cs.get("contract_id") == id:
            salt_lbs = cs.get("salt_included_lbs") or 0
            salt_rate = contract.get("salt_rate_per_lb_cents") or 25
            allowance += round_half_up(salt_lbs * salt_rate)

    material_settlement = max(0, min(material_actual, material_normative) - allowance)
    balance = overage_cents + material_settlement - perf_credit

    return success_object({
        "contract_id": id,
        "projected_billable_push_count": billable_count,
        "projected_overage_pushes": overage_pushes,
        "projected_overage_cents": overage_cents,
        "projected_material_actual_cents": material_actual,
        "projected_material_normative_cents": material_normative,
        "projected_material_allowance_cents": allowance,
        "projected_material_settlement_cents": material_settlement,
        "projected_sla_miss_count": sla_miss_count,
        "projected_performance_credit_cents": perf_credit,
        "projected_balance_due_cents": balance,
    })
