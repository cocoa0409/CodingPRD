"""Jurisdictions, engagements, the store roster and the logical clock."""

import re

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError
from money import ZERO, dec, num

bp = Blueprint("engagement", __name__)

CODE_RE = re.compile(r"^[A-Z]{2,8}$")


# ------------------------------------------------------------ jurisdictions

@bp.post("/jurisdictions")
def create_jurisdiction():
    auth.begin(("ComplianceOfficer",))
    body = shape.json_body()
    code = shape.field_str(body, "code")
    if not CODE_RE.match(code):
        shape.bad("Field 'code' must be 2 to 8 uppercase letters")
    name = shape.field_str(body, "name")
    gob_license_required = shape.field_bool(body, "gob_license_required", required=True)
    max_sale_days = shape.field_int(body, "max_sale_days", minimum=1)
    cooling_off = shape.field_int(
        body, "license_cooling_off_days", required=False, default=30, minimum=0
    )
    max_ratio = shape.field_pct(body, "max_augmentation_ratio")
    disclosure_required = shape.field_bool(
        body, "augmentation_disclosure_required", required=True
    )
    prohibited = shape.field_bool(
        body, "augmentation_prohibited", required=False, default=False
    )
    claim_codes = shape.field_code_list(
        body, "prohibited_claim_codes", calc.CLAIM_CODES, required=False, default=[]
    )
    advertising_disclosure = shape.field_bool(
        body, "advertising_disclosure_required", required=True
    )
    notice_days = shape.field_int(
        body, "surrender_notice_days", required=False, default=30, minimum=0
    )

    for existing in db.all_rows("jurisdictions"):
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION_CODE")

    row = db.insert(
        "jurisdictions",
        {
            "code": code,
            "name": name,
            "gob_license_required": gob_license_required,
            "max_sale_days": max_sale_days,
            "license_cooling_off_days": cooling_off,
            "max_augmentation_ratio": max_ratio,
            "augmentation_disclosure_required": disclosure_required,
            "augmentation_prohibited": prohibited,
            "prohibited_claim_codes": claim_codes,
            "advertising_disclosure_required": advertising_disclosure,
            "surrender_notice_days": notice_days,
        },
    )
    return response.ok(serializers.jurisdiction(row), 201)


@bp.get("/jurisdictions/<row_id>")
def read_jurisdiction(row_id):
    auth.begin(("ComplianceOfficer", "LiquidationConsultant", "RetailerController"))
    row = helpers.require("jurisdictions", row_id)
    return response.ok(serializers.jurisdiction(row))


# --------------------------------------------------------------- engagements

def _economics_gate(model, guaranty_pct, hybrid_pct, responsibility, shared_pct):
    if not calc.economics_config_valid(
        model, guaranty_pct, hybrid_pct, responsibility, shared_pct
    ):
        raise ApiError("ERR_ECONOMICS_CONFIG_INVALID")


@bp.post("/engagements")
def create_engagement():
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    retailer_name = shape.field_str(body, "retailer_name")
    liquidator_name = shape.field_str(body, "liquidator_name")
    model = shape.field_enum(body, "economics_model", calc.ECONOMICS_MODELS)
    guaranty_pct = shape.field_pct(
        body, "guaranty_pct", required=False, default=None, low="0", high="1.5"
    )
    hybrid_pct = shape.field_pct(
        body, "hybrid_retailer_excess_pct", required=False, default=ZERO
    )
    responsibility = shape.field_enum(
        body, "expense_responsibility", calc.EXPENSE_RESPONSIBILITIES
    )
    shared_pct = shape.field_pct(
        body, "shared_expense_liquidator_pct", required=False, default=ZERO
    )
    sale_start = shape.field_date(body, "sale_start_date")
    target_end = shape.field_date(body, "target_end_date")
    if target_end < sale_start:
        shape.bad("Field 'target_end_date' may not fall before 'sale_start_date'")

    _economics_gate(model, guaranty_pct, hybrid_pct, responsibility, shared_pct)

    row = db.insert(
        "engagements",
        {
            "retailer_name": retailer_name,
            "liquidator_name": liquidator_name,
            "economics_model": model,
            "guaranty_pct": guaranty_pct,
            "hybrid_retailer_excess_pct": hybrid_pct,
            "expense_responsibility": responsibility,
            "shared_expense_liquidator_pct": shared_pct,
            "sale_start_date": sale_start.isoformat(),
            "target_end_date": target_end.isoformat(),
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "engagement_status": "DRAFT",
            "compliance_strike_count": 0,
            "compliance_posture": "OPEN",
            "original_cost_value_cents": 0,
            "guaranty_amount_cents": 0,
            "projected_gross_recovery_cents": 0,
            "projected_shortfall_cents": 0,
            "original_net_sales_cents": 0,
            "augmentation_net_sales_cents": 0,
            "gross_recovery_cents": 0,
            "expense_total_cents": 0,
            "expense_liquidator_share_cents": 0,
            "expense_retailer_share_cents": 0,
            "retention_accrual_cents": 0,
        },
    )
    return response.ok(serializers.engagement(row), 201)


@bp.get("/engagements/<row_id>")
def read_engagement(row_id):
    auth.begin(("LiquidationConsultant", "RetailerController", "ComplianceOfficer"))
    row = helpers.require("engagements", row_id)
    return response.ok(serializers.engagement(row))


@bp.post("/engagements/<row_id>/submit-for-approval")
def submit_engagement(row_id):
    user_id, _role = auth.begin(("LiquidationConsultant",))
    engagement = helpers.require("engagements", row_id)
    if engagement["engagement_status"] != "DRAFT":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")
    stores = db.stores_of_engagement(engagement["id"])
    if not stores:
        raise ApiError(
            "ERR_ENGAGEMENT_STATE_INVALID", "The engagement has no closing stores"
        )
    for store in stores:
        original = [
            lot for lot in db.lots_of_store(store["id"]) if lot["source"] == "ORIGINAL"
        ]
        if not original:
            raise ApiError(
                "ERR_ENGAGEMENT_STATE_INVALID",
                "Every store must hold at least one original merchandise lot",
            )
    _economics_gate(
        engagement["economics_model"],
        engagement["guaranty_pct"],
        engagement["hybrid_retailer_excess_pct"],
        engagement["expense_responsibility"],
        engagement["shared_expense_liquidator_pct"],
    )

    engagement["engagement_status"] = "PENDING_RETAILER_APPROVAL"
    engagement["submitted_by_user_id"] = user_id
    calc.recompute_chain(engagement)
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.post("/engagements/<row_id>/approval-decision")
def decide_engagement(row_id):
    user_id, _role = auth.begin(("RetailerController",))
    engagement = db.get("engagements", row_id)
    auth.deny_self_decision(user_id, engagement, "submitted_by_user_id")
    body = shape.json_body()
    decision = shape.field_enum(body, "decision", ("APPROVE", "RETURN_FOR_REVISION"))
    shape.field_str(body, "decision_note", required=False, default=None)
    if engagement is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_FOUND")
    if engagement["engagement_status"] != "PENDING_RETAILER_APPROVAL":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")

    engagement["approved_by_user_id"] = user_id
    if decision == "RETURN_FOR_REVISION":
        engagement["engagement_status"] = "DRAFT"
        db.touch(engagement)
        return response.ok(serializers.engagement(engagement))

    engagement["engagement_status"] = "ACTIVE"
    for store in db.stores_of_engagement(engagement["id"]):
        if store["store_status"] != "PLANNED":
            continue
        jurisdiction = helpers.jurisdiction_of_store(store)
        if jurisdiction is not None and jurisdiction["gob_license_required"]:
            store["store_status"] = "LICENSE_PENDING"
        else:
            store["store_status"] = "SELLING"
            store["selling_start_date"] = engagement["sale_start_date"]
        db.touch(store)
    calc.recompute_chain(engagement)
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.post("/engagements/<row_id>/wind-down")
def wind_down_engagement(row_id):
    auth.begin(("LiquidationConsultant",))
    engagement = helpers.require("engagements", row_id)
    if engagement["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")
    for store in db.stores_of_engagement(engagement["id"]):
        if store["store_status"] not in calc.CLOSED_STORE_STATUSES:
            raise ApiError("ERR_STORES_NOT_CLOSED")
    engagement["engagement_status"] = "WIND_DOWN"
    calc.recompute_chain(engagement)
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.get("/engagements/<row_id>/recovery-summary")
def recovery_summary(row_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    engagement = helpers.require("engagements", row_id)
    calc.recompute_chain(engagement)
    stores = db.stores_of_engagement(engagement["id"])
    projected_ratio = calc.ratio4(
        engagement["projected_gross_recovery_cents"],
        engagement["original_cost_value_cents"],
    )
    realized_ratio = calc.ratio4(
        engagement["original_net_sales_cents"],
        engagement["original_cost_value_cents"],
    )
    planned_stages = []
    for store in stores:
        planned_stages.extend(
            s
            for s in db.stages_of_store(store["id"])
            if s["stage_status"] in calc.PLANNED_STAGE_STATUSES
        )
    if planned_stages:
        total = sum((dec(s["discount_pct"]) for s in planned_stages), ZERO)
        planned = calc.round4(total / dec(len(planned_stages)))
    else:
        planned = calc.round4(ZERO)
    data = {
        "projected_gross_recovery_cents": engagement["projected_gross_recovery_cents"],
        "projected_recovery_ratio": num(projected_ratio),
        "realized_gross_recovery_cents": engagement["gross_recovery_cents"],
        "realized_recovery_ratio": num(realized_ratio),
        "planned_avg_discount_pct": num(planned),
        "projected_shortfall_cents": engagement["projected_shortfall_cents"],
        "guaranty_amount_cents": engagement["guaranty_amount_cents"],
        "original_cost_value_cents": engagement["original_cost_value_cents"],
        "store_count": len(stores),
    }
    return response.ok(data)


@bp.post("/engagements/<row_id>/compliance-sweep")
def compliance_sweep(row_id):
    auth.begin(("ComplianceOfficer",))
    engagement = helpers.require("engagements", row_id)
    helpers.engagement_not_closed(engagement)

    today = clock.today()
    expired_license_count = 0
    closed_stage_count = 0
    suspended_store_count = 0

    for store in db.stores_of_engagement(engagement["id"]):
        for lic in db.licenses_of_store(store["id"]):
            if lic["license_status"] != "APPROVED":
                continue
            if calc.as_date(lic["period_end_date"]) >= today:
                continue
            lic["license_status"] = "EXPIRED"
            db.touch(lic)
            expired_license_count += 1
            if store["store_status"] == "SELLING":
                store["store_status"] = "SUSPENDED"
                store["suspension_reason"] = "LICENSE_EXPIRED"
                db.touch(store)
                suspended_store_count += 1
                engagement["compliance_strike_count"] += 1
                for stage in db.stages_of_store(store["id"]):
                    if stage["stage_status"] == "ACTIVE":
                        stage["stage_status"] = "CLOSED"
                        stage["closed_reason"] = "LICENSE_LOST"
                        stage["escalation_applied_pct"] = calc.round4(ZERO)
                        db.touch(stage)
                        closed_stage_count += 1

    for store in db.stores_of_engagement(engagement["id"]):
        for stage in list(db.stages_of_store(store["id"])):
            if stage["stage_status"] != "ACTIVE":
                continue
            if calc.as_date(stage["window_end_date"]) > today:
                continue
            stage["stage_status"] = "CLOSED"
            stage["closed_reason"] = "ON_SCHEDULE"
            stage["escalation_applied_pct"] = calc.round4(ZERO)
            db.touch(stage)
            closed_stage_count += 1
            if store["store_status"] != "SELLING":
                continue
            for successor in db.stages_of_store(store["id"]):
                if (
                    successor["stage_status"] == "ARMED"
                    and successor["stage_index"] == stage["stage_index"] + 1
                ):
                    successor["stage_status"] = "ACTIVE"
                    successor["activated_at"] = clock.iso_now()
                    db.touch(successor)
                    break

    engagement["compliance_posture"] = calc.compliance_posture(
        engagement["compliance_strike_count"]
    )
    calc.recompute_chain(engagement)
    db.touch(engagement)
    return response.ok(
        {
            "expired_license_count": expired_license_count,
            "closed_stage_count": closed_stage_count,
            "suspended_store_count": suspended_store_count,
            "compliance_strike_count": engagement["compliance_strike_count"],
            "compliance_posture": engagement["compliance_posture"],
        }
    )


# ------------------------------------------------------------------- stores

@bp.post("/engagements/<row_id>/stores")
def create_store(row_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    jurisdiction_id = shape.field_str(body, "jurisdiction_id")
    store_code = shape.field_str(body, "store_code")
    address_line = shape.field_str(body, "address_line")

    engagement = helpers.require("engagements", row_id)
    jurisdiction = helpers.require("jurisdictions", jurisdiction_id)
    for existing in db.stores_of_engagement(engagement["id"]):
        if existing["store_code"] == store_code:
            raise ApiError("ERR_DUPLICATE_STORE_CODE")
    if engagement["engagement_status"] == "CLOSED":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")

    row = db.insert(
        "stores",
        {
            "engagement_id": engagement["id"],
            "jurisdiction_id": jurisdiction["id"],
            "store_code": store_code,
            "address_line": address_line,
            "store_status": "PLANNED",
            "suspension_reason": "NONE",
            "selling_start_date": None,
            "selling_end_date": None,
            "original_cost_value_cents": 0,
            "augmentation_cost_value_cents": 0,
            "units_initial_total": 0,
            "units_sold_total": 0,
            "realized_sell_through_pct": calc.round4(ZERO),
            "planned_avg_discount_pct": calc.round4(ZERO),
            "projected_gross_recovery_cents": 0,
            "projected_recovery_ratio": calc.round4(ZERO),
            "realized_gross_recovery_cents": 0,
            "realized_recovery_ratio": calc.round4(ZERO),
            "augmentation_units_accounted": 0,
        },
    )
    return response.ok(serializers.store(row), 201)


@bp.get("/stores/<row_id>")
def read_store(row_id):
    user_id, role = auth.begin(
        (
            "LiquidationConsultant",
            "RetailerController",
            "ComplianceOfficer",
            "StoreManager",
        )
    )
    auth.scope_store(user_id, role, row_id)
    row = helpers.require("stores", row_id)
    return response.ok(serializers.store(row))


@bp.get("/stores")
def list_stores():
    auth.begin(("LiquidationConsultant", "RetailerController", "ComplianceOfficer"))
    limit, offset = shape.pagination()
    engagement_id = shape.query_str("engagement_id")
    jurisdiction_id = shape.query_str("jurisdiction_id")
    store_status = shape.query_enum("store_status", calc.STORE_STATUSES)
    rows = db.all_rows("stores")
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if store_status is not None:
        rows = [r for r in rows if r["store_status"] == store_status]
    return helpers.paginate(rows, serializers.store, limit, offset)


# ---------------------------------------------------------------- the clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = auth.resolve_actor(optional=True)
    if user_id is not None:
        auth.authorize(role, ("SystemOperator",))
    body = shape.json_body()
    raw = body.get("current_utc")
    instant = shape.field_instant(body, "current_utc")
    clock.set_now(instant, raw if isinstance(raw, str) else clock.iso_instant(instant))
    return response.ok({"current_utc": clock.raw()})
