"""Service plans and their fee itemisation (PRD §3.1)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import COMPLIANCE_OFFICER, ALL_ROLES, authorize
from services import calculations as calc
from services import reconcile

bp = Blueprint("service_plans", __name__)

TECHNOLOGIES = ("FIBER", "CABLE", "DSL", "FIXED_WIRELESS", "SATELLITE")
ETF_POLICIES = ("FULL", "PRORATED_MONTHLY", "NONE")
LABEL_CATEGORIES = ("MONTHLY_RECURRING", "ONE_TIME", "EARLY_TERMINATION",
                    "DATA_OVERAGE", "GOVERNMENT_TAX")
FEE_BASES = ("FIXED", "PCT_OF_MONTHLY_CHARGE")
APPLIES_DURING = ("ALWAYS", "INTRO_ONLY", "POST_PROMO_ONLY")

PRICE_FIELDS = ("monthly_price_cents", "intro_price_cents",
                "intro_term_months", "early_termination_fee_cents")
PATCHABLE = ("monthly_price_cents", "intro_price_cents", "intro_term_months",
             "data_allowance_gb", "overage_rate_cents_per_gb",
             "early_termination_fee_cents", "etf_proration_policy",
             "required_locales")


def _check_plan_coherence(intro_price, intro_term, allowance, overage):
    if intro_price is not None and (intro_term is None or intro_term < 1):
        validators.bad("Field 'intro_term_months' must be at least 1 when "
                       "'intro_price_cents' is present.")
    if allowance is None and overage != 0:
        validators.bad("Field 'overage_rate_cents_per_gb' must be 0 when "
                       "'data_allowance_gb' is null.")


@bp.route("/service-plans", methods=["POST"])
def create_service_plan():
    authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()

    plan_code = validators.get_str(body, "plan_code", 1, 32)
    display_name = validators.get_str(body, "display_name", 1, 120)
    technology = validators.get_enum(body, "technology", TECHNOLOGIES)
    download = validators.get_number(body, "advertised_download_mbps",
                                     exclusive_min=0, max_decimals=2)
    upload = validators.get_number(body, "advertised_upload_mbps",
                                   exclusive_min=0, max_decimals=2)
    monthly = validators.get_int(body, "monthly_price_cents", minimum=0)
    etf = validators.get_int(body, "early_termination_fee_cents", minimum=0)
    locales = validators.get_locale_array(body, "required_locales")
    intro_price = validators.get_int(body, "intro_price_cents", minimum=0,
                                     required=False, default=None,
                                     nullable=True)
    intro_term = validators.get_int(body, "intro_term_months", minimum=0,
                                   maximum=24, required=False, default=0)
    allowance = validators.get_int(body, "data_allowance_gb", minimum=1,
                                   required=False, default=None, nullable=True)
    overage = validators.get_int(body, "overage_rate_cents_per_gb", minimum=0,
                                 required=False, default=0)
    policy = validators.get_enum(body, "etf_proration_policy", ETF_POLICIES,
                                 required=False, default="FULL")
    eligible = validators.get_bool(body, "discount_program_eligible",
                                   required=False, default=False)

    _check_plan_coherence(intro_price, intro_term, allowance, overage)

    for existing in db.store.service_plans.values():
        if existing["plan_code"] == plan_code:
            fail(errors.ERR_DUPLICATE_PLAN_CODE)

    plan = db.new_record()
    plan.update({
        "plan_code": plan_code,
        "display_name": display_name,
        "technology": technology,
        "advertised_download_mbps": download,
        "advertised_upload_mbps": upload,
        "monthly_price_cents": monthly,
        "intro_price_cents": intro_price,
        "intro_term_months": intro_term,
        "data_allowance_gb": allowance,
        "overage_rate_cents_per_gb": overage,
        "early_termination_fee_cents": etf,
        "etf_proration_policy": policy,
        "discount_program_eligible": eligible,
        "required_locales": locales,
        "label_posture": "RESTRICTED",
        "evidence_sample_total": 0,
        "upheld_complaint_count": 0,
        "price_disclosure_drift": False,
        "active_label_version_id": None,
        "last_price_change_at": None,
    })
    db.store.service_plans[plan["id"]] = plan
    return response.success(serializers.service_plan(plan), 201)


@bp.route("/service-plans/<plan_id>", methods=["GET"])
def read_service_plan(plan_id):
    authorize(*ALL_ROLES)
    plan = lookup.service_plan(plan_id)
    return response.success(serializers.service_plan(plan), 200)


@bp.route("/service-plans/<plan_id>", methods=["PATCH"])
def amend_service_plan(plan_id):
    authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()
    validators.get_str(body, "change_justification", 1, None)

    updates = {}
    if "monthly_price_cents" in body:
        updates["monthly_price_cents"] = validators.get_int(
            body, "monthly_price_cents", minimum=0)
    if "intro_price_cents" in body:
        updates["intro_price_cents"] = validators.get_int(
            body, "intro_price_cents", minimum=0, nullable=True)
    if "intro_term_months" in body:
        updates["intro_term_months"] = validators.get_int(
            body, "intro_term_months", minimum=0, maximum=24)
    if "data_allowance_gb" in body:
        updates["data_allowance_gb"] = validators.get_int(
            body, "data_allowance_gb", minimum=1, nullable=True)
    if "overage_rate_cents_per_gb" in body:
        updates["overage_rate_cents_per_gb"] = validators.get_int(
            body, "overage_rate_cents_per_gb", minimum=0)
    if "early_termination_fee_cents" in body:
        updates["early_termination_fee_cents"] = validators.get_int(
            body, "early_termination_fee_cents", minimum=0)
    if "etf_proration_policy" in body:
        updates["etf_proration_policy"] = validators.get_enum(
            body, "etf_proration_policy", ETF_POLICIES)
    if "required_locales" in body:
        updates["required_locales"] = validators.get_locale_array(
            body, "required_locales")

    plan = lookup.service_plan(plan_id)

    merged = dict(plan)
    merged.update(updates)
    _check_plan_coherence(merged["intro_price_cents"],
                          merged["intro_term_months"],
                          merged["data_allowance_gb"],
                          merged["overage_rate_cents_per_gb"])

    price_moved = any(field in updates and updates[field] != plan[field]
                      for field in PRICE_FIELDS)

    plan.update(updates)

    if price_moved:
        plan["price_disclosure_drift"] = True
        plan["last_price_change_at"] = db.now_iso()
        published = calc.published_label(plan["id"])
        if published is not None:
            published["price_disclosure_drift"] = True
            db.touch(published)

    reconcile.recompute_draft_labels(plan)
    calc.recompute_plan_posture(plan)
    db.touch(plan)
    return response.success(serializers.service_plan(plan), 200)


@bp.route("/service-plans/<plan_id>/fee-line-items", methods=["POST"])
def create_fee_line_item(plan_id):
    authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()

    fee_code = validators.get_str(body, "fee_code", 1, 32)
    description = validators.get_str(body, "description", 1, 200)
    category = validators.get_enum(body, "label_category", LABEL_CATEGORIES)
    basis = validators.get_enum(body, "basis", FEE_BASES)
    amount = validators.get_int(body, "amount_cents", minimum=0,
                                required=False, default=None, nullable=True)
    rate = validators.get_number(body, "rate_pct", exclusive_min=0,
                                 exclusive_max=1, max_decimals=4,
                                 required=False, default=None, nullable=True)
    applies = validators.get_enum(body, "applies_during", APPLIES_DURING,
                                  required=False, default="ALWAYS")
    recovery = validators.get_bool(body, "is_regulatory_recovery",
                                   required=False, default=False)

    if category == "ONE_TIME" and basis != "FIXED":
        validators.bad("A ONE_TIME fee line must use the FIXED basis.")
    if basis == "FIXED":
        if amount is None:
            validators.bad("Field 'amount_cents' is required for a FIXED line.")
        if rate is not None:
            validators.bad("Field 'rate_pct' must be null for a FIXED line.")
    else:
        if rate is None:
            validators.bad("Field 'rate_pct' is required for a "
                           "PCT_OF_MONTHLY_CHARGE line.")
        if amount is not None:
            validators.bad("Field 'amount_cents' must be null for a "
                           "PCT_OF_MONTHLY_CHARGE line.")

    plan = lookup.service_plan(plan_id)

    for existing in db.store.fee_line_items.values():
        if existing["plan_id"] == plan["id"] and existing["fee_code"] == fee_code:
            validators.bad("Field 'fee_code' is already used on this plan.")

    line = db.new_record()
    line.update({
        "plan_id": plan["id"],
        "fee_code": fee_code,
        "description": description,
        "label_category": category,
        "basis": basis,
        "amount_cents": amount,
        "rate_pct": rate,
        "applies_during": applies,
        "is_regulatory_recovery": recovery,
    })
    db.store.fee_line_items[line["id"]] = line

    reconcile.recompute_draft_labels(plan)
    return response.success(serializers.fee_line_item(line), 201)


@bp.route("/service-plans/<plan_id>/fee-line-items", methods=["GET"])
def list_fee_line_items(plan_id):
    authorize(*ALL_ROLES)
    validators.pagination_params()
    plan = lookup.service_plan(plan_id)

    category = request.args.get("label_category")
    rows = [r for r in db.store.fee_line_items.values()
            if r["plan_id"] == plan["id"]
            and (category is None or r["label_category"] == category)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.fee_line_item)
    return response.success_list(items, meta, 200)
