"""Plan endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize
from services.store_helpers import make_record, touch, get_plan

bp = Blueprint("plans", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIER"}


@bp.route("/plans", methods=["POST"])
@require_roles("CarrierAdmin")
def create_plan():
    body = common.get_json_body()

    code = common.require_str(body, "code")
    tier = common.require_enum(body, "tier", TIERS)
    base_rate_bps = common.require_int(body, "base_rate_bps", minimum=1)
    cancellation_limit_pct = common.require_int(body, "cancellation_limit_pct", minimum=1, maximum=100)
    medical_limit_cents = common.require_int(body, "medical_limit_cents", minimum=0)
    delay_block_cap_cents = common.require_int(body, "delay_block_cap_cents", minimum=0)
    delay_limit_cents = common.require_int(body, "delay_limit_cents", minimum=0)
    baggage_item_sublimit_cents = common.require_int(body, "baggage_item_sublimit_cents", minimum=0)
    baggage_limit_cents = common.require_int(body, "baggage_limit_cents", minimum=0)
    baggage_depreciation_bps = common.require_int(body, "baggage_depreciation_bps", minimum=0, maximum=10000)
    waiver_window_days = common.require_int(body, "waiver_window_days", minimum=0)
    free_look_days = common.require_int(body, "free_look_days", minimum=0)
    claim_filing_window_days = common.require_int(body, "claim_filing_window_days", minimum=1)
    cfar_loading_bps = common.require_int(body, "cfar_loading_bps", minimum=0)
    cfar_reimbursement_pct = common.require_int(body, "cfar_reimbursement_pct", minimum=1, maximum=100)
    senior_age_threshold = common.opt_int(body, "senior_age_threshold", default=70, minimum=0)
    senior_loading_bps = common.require_int(body, "senior_loading_bps", minimum=0)

    # Duplicate code (after well-formedness, per error catalogue / validation order)
    for p in db.plans.values():
        if p["code"] == code:
            raise errors.conflict(errors.ERR_DUPLICATE_CODE, "Plan code already in use.")

    rec = make_record()
    rec.update({
        "code": code,
        "tier": tier,
        "base_rate_bps": base_rate_bps,
        "cancellation_limit_pct": cancellation_limit_pct,
        "medical_limit_cents": medical_limit_cents,
        "delay_block_cap_cents": delay_block_cap_cents,
        "delay_limit_cents": delay_limit_cents,
        "baggage_item_sublimit_cents": baggage_item_sublimit_cents,
        "baggage_limit_cents": baggage_limit_cents,
        "baggage_depreciation_bps": baggage_depreciation_bps,
        "waiver_window_days": waiver_window_days,
        "free_look_days": free_look_days,
        "claim_filing_window_days": claim_filing_window_days,
        "cfar_loading_bps": cfar_loading_bps,
        "cfar_reimbursement_pct": cfar_reimbursement_pct,
        "senior_age_threshold": senior_age_threshold,
        "senior_loading_bps": senior_loading_bps,
        "status": "ACTIVE",
    })
    db.plans[rec["id"]] = rec
    return response.success_object(serialize.plan_out(rec), status=201)


@bp.route("/plans/<plan_id>", methods=["GET"])
@require_roles("Any")
def get_plan_route(plan_id):
    rec = get_plan(plan_id)
    return response.success_object(serialize.plan_out(rec), status=200)


@bp.route("/plans", methods=["GET"])
@require_roles("Any")
def list_plans():
    tier = request.args.get("tier")
    status = request.args.get("status")
    items = list(db.plans.values())
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.plan_out(p) for p in page], limit, offset, total)


@bp.route("/plans/<plan_id>/retire", methods=["POST"])
@require_roles("CarrierAdmin")
def retire_plan(plan_id):
    rec = get_plan(plan_id)
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Plan is not ACTIVE.")
    rec["status"] = "RETIRED"
    touch(rec)
    return response.success_object(serialize.plan_out(rec), status=200)
