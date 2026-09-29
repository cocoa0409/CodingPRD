"""Plans and save-offer templates (PRD §3.1)."""
from decimal import Decimal

from flask import Blueprint

import constants as K
import serializers as S
import validation as V
from db import base_record, store
from middleware import auth
from response import created, ok
from routes import send_list

bp = Blueprint("catalog", __name__)


@bp.post("/plans")
@auth("PlatformAdmin")
def create_plan():
    data = V.body()
    target = V.fk(data, "downgrade_target_plan_id", "plans")

    code = V.req_str(data, "code")
    if not V.PLAN_CODE_RE.match(code):
        V.bad("code", "must contain only uppercase letters, digits and underscores")
    if any(p["code"] == code for p in store.plans.values()):
        V.bad("code", "must be unique across plans")
    name = V.req_str(data, "name")
    monthly = V.req_int(data, "monthly_price_cents", minimum=1)
    unit_cogs = V.req_int(data, "unit_cogs_cents", minimum=0)
    floor = V.req_frac(data, "margin_floor_pct", minimum=Decimal("0"), maximum=Decimal("1"))
    per_cycle = V.opt_int(data, "shipments_per_cycle", 1, minimum=1)
    per_term = V.opt_int(data, "shipments_per_term", 12, minimum=1)
    freqs = V.opt_array(data, "allowed_frequency_weeks", [2, 4, 8])
    if not freqs:
        V.bad("allowed_frequency_weeks", "must be a non-empty array")
    cleaned = []
    for value in freqs:
        weeks = V._as_int("allowed_frequency_weeks", value)
        if weeks < 1:
            V.bad("allowed_frequency_weeks", "must contain positive integers")
        cleaned.append(weeks)
    negative_option = V.opt_bool(data, "is_negative_option", True)
    reminder_days = V.opt_int(data, "renewal_reminder_days_before", 10,
                              minimum=K.MIN_REMINDER_LEAD_DAYS)
    max_pause = V.opt_int(data, "max_pause_cycles", 3, minimum=1)
    catalog_raw = V.opt_array(data, "addon_catalog", [])
    catalog = []
    for entry in catalog_raw:
        if not isinstance(entry, dict):
            V.bad("addon_catalog", "entries must be objects")
        catalog.append({
            "code": V.req_str(entry, "code"),
            "unit_price_cents": V.req_int(entry, "unit_price_cents", minimum=0),
            "unit_cogs_cents": V.req_int(entry, "unit_cogs_cents", minimum=0),
        })
    status = V.opt_enum(data, "status", K.PLAN_STATUSES, "ACTIVE")

    rec = base_record()
    rec.update({
        "code": code,
        "name": name,
        "monthly_price_cents": monthly,
        "unit_cogs_cents": unit_cogs,
        "shipments_per_cycle": per_cycle,
        "shipments_per_term": per_term,
        "allowed_frequency_weeks": cleaned,
        "margin_floor_pct": floor,
        "is_negative_option": negative_option,
        "renewal_reminder_days_before": reminder_days,
        "max_pause_cycles": max_pause,
        "addon_catalog": catalog,
        "downgrade_target_plan_id": target["id"] if target else None,
        "status": status,
    })
    store.plans[rec["id"]] = rec
    return created(S.plan(rec))


@bp.get("/plans/<plan_id>")
@auth()
def read_plan(plan_id):
    return ok(S.plan(V.must_exist("plans", plan_id)))


@bp.get("/plans")
@auth()
def list_plans():
    return send_list(store.plans.values(), S.plan,
                     {"downgrade_target_plan_id": "downgrade_target_plan_id",
                      "status": "status"})


@bp.post("/save-offer-templates")
@auth("PlatformAdmin")
def create_template():
    data = V.body()
    code = V.req_str(data, "code")
    if any(t["code"] == code for t in store.save_offer_templates.values()):
        V.bad("code", "must be unique across save-offer templates")
    name = V.req_str(data, "name")
    offer_type = V.req_enum(data, "offer_type", K.OFFER_TYPES)
    priority_rank = V.req_int(data, "priority_rank", minimum=1)
    discount_pct = V.opt_frac(data, "discount_pct", Decimal("0.0000"),
                              minimum=Decimal("0"), exclusive_max=Decimal("1"))
    discount_cycles = V.opt_int(data, "discount_cycles", 0, minimum=0)
    pause_cycles = V.opt_int(data, "pause_cycles", 0, minimum=0)
    skip_count = V.opt_int(data, "skip_count", 0, minimum=0)
    min_tenure = V.opt_int(data, "min_tenure_days", 0, minimum=0)
    reasons = V.opt_array(data, "eligible_reason_codes", [])
    for reason in reasons:
        if reason not in K.REASON_CODES:
            V.bad("eligible_reason_codes", "must contain declared reason codes")
    quota = V.opt_int(data, "max_per_subscriber_per_365d", 1, minimum=0)
    expires_after = V.opt_int(data, "expires_after_hours", 48, minimum=0)
    status = V.opt_enum(data, "status", K.PLAN_STATUSES, "ACTIVE")

    rec = base_record()
    rec.update({
        "code": code,
        "name": name,
        "offer_type": offer_type,
        "discount_pct": discount_pct,
        "discount_cycles": discount_cycles,
        "pause_cycles": pause_cycles,
        "skip_count": skip_count,
        "min_tenure_days": min_tenure,
        "eligible_reason_codes": list(reasons),
        "max_per_subscriber_per_365d": quota,
        "priority_rank": priority_rank,
        "expires_after_hours": expires_after,
        "status": status,
    })
    store.save_offer_templates[rec["id"]] = rec
    return created(S.template(rec))


@bp.get("/save-offer-templates/<template_id>")
@auth("PlatformAdmin", "RetentionSpecialist", "ComplianceOfficer")
def read_template(template_id):
    return ok(S.template(V.must_exist("save_offer_templates", template_id)))
