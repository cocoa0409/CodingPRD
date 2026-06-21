"""ApplicationRecord + ComplianceRecord endpoints (PRD §3.4).

ApplicationRecord state machine (SCAFFOLD §1.2):
  LOGGED -> CONFIRMED (confirm, Applicator) — compliance enforced here
  LOGGED -> VOIDED (void, Agronomist)
  CONFIRMED -> VOIDED (void, Agronomist) — compensation
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_number,
    require_str,
    round2,
)
from middleware import get_user_id, require_roles
from response import array_response, object_response
from services import compute
from timeutil import iso_now, parse_iso

bp = Blueprint("application_records", __name__)
READ_ROLES = ("FarmManager", "Agronomist", "Applicator")


@bp.post("/application-records")
@require_roles("Agronomist", "Applicator")
def log_application():
    body = get_json_body()
    crop_plan_id = require_str(body, "crop_plan_id")
    input_product_id = require_str(body, "input_product_id")
    applicator_user_id = require_str(body, "applicator_user_id")
    rate_per_acre = require_number(body, "rate_per_acre")
    acres_treated = require_number(body, "acres_treated")

    # Left-to-right existence resolution (PRD §2.7): body FKs in declared order.
    lookups.crop_plan(crop_plan_id)
    product = lookups.input_product(input_product_id)
    lookups.applicator(applicator_user_id)

    if rate_per_acre <= 0:
        raise err("ERR_INVALID_REQUEST", "rate_per_acre must be > 0.")
    if acres_treated <= 0:
        raise err("ERR_INVALID_REQUEST", "acres_treated must be > 0.")

    # Cross-aggregate referential coherence (PRD §3.4, §2.10 priority 6):
    # an application whose product category is SEED is rejected.
    if product["category"] == "SEED":
        raise err(
            "ERR_PRODUCT_CATEGORY_MISMATCH",
            "Application product category must not be SEED.",
        )

    quantity_used = rate_per_acre * acres_treated
    applied_cost = round2(quantity_used * product["unit_cost"])

    rec = db.new_entity(
        {
            "crop_plan_id": crop_plan_id,
            "input_product_id": input_product_id,
            "applicator_user_id": applicator_user_id,
            "rate_per_acre": rate_per_acre,
            "acres_treated": acres_treated,
            "quantity_used": quantity_used,
            "applied_cost": applied_cost,
            "applied_at": None,
            "status": "LOGGED",
            "is_restricted": False,
            "reentry_clear_at": None,
        }
    )
    db.application_records[rec["id"]] = rec
    return object_response(serializers.application_record(rec), 201)


@bp.get("/application-records/<aid>")
@require_roles(*READ_ROLES)
def get_application(aid):
    rec = lookups.application_record(aid)
    return object_response(serializers.application_record(rec))


@bp.get("/application-records")
@require_roles(*READ_ROLES)
def list_applications():
    limit, offset = parse_pagination()
    records = list(db.application_records.values())
    for key in ("crop_plan_id", "input_product_id", "applicator_user_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.application_record(r) for r in page], limit, offset, total
    )


@bp.post("/application-records/<aid>/confirm")
@require_roles("Applicator")
def confirm_application(aid):
    rec = lookups.application_record(aid)
    if rec["status"] != "LOGGED":
        raise err("ERR_INVALID_STATE", "Application is not LOGGED.")

    plan = db.crop_plans.get(rec["crop_plan_id"])
    product = db.input_products.get(rec["input_product_id"])

    # Domain-rule precedence (PRD §2.10, §3.4):
    # 1) plan must be GROWING
    if plan is None or plan["status"] != "GROWING":
        raise err("ERR_PLAN_NOT_GROWING", "Owning plan is not GROWING.")

    restricted = bool(product["restricted_use"]) if product else False
    parcel = db.parcels.get(plan["parcel_id"]) if plan else None

    if restricted:
        # 2) certified applicator
        acting = db.applicators.get(get_user_id())
        if acting is None or not acting.get("certified"):
            raise err(
                "ERR_APPLICATOR_NOT_CERTIFIED",
                "Restricted-use confirm requires a certified applicator.",
            )
        # 3) acting applicator id must match the record's applicator_user_id
        if get_user_id() != rec["applicator_user_id"]:
            raise err(
                "ERR_APPLICATOR_MISMATCH",
                "Acting applicator does not match the record's applicator_user_id.",
            )

    # 4) re-entry gate (REI): blocked when parcel RESTRICTED and now < blocked_until.
    # Boundary inclusive of clearance (block is strict '<').
    now = clock.now()
    if parcel and parcel["status"] == "RESTRICTED" and parcel.get("reentry_blocked_until"):
        blocked_until = parse_iso(parcel["reentry_blocked_until"])
        if blocked_until is not None and now < blocked_until:
            raise err(
                "ERR_REENTRY_INTERVAL_ACTIVE",
                "Parcel re-entry interval has not elapsed.",
            )

    # 5) seasonal rate cap (after safety + temporal families, PRD §2.10 priority 9)
    if product and product.get("max_seasonal_rate_per_acre") is not None:
        cap = product["max_seasonal_rate_per_acre"]
        cumulative = sum(
            other["rate_per_acre"]
            for other in db.application_records.values()
            if other["crop_plan_id"] == rec["crop_plan_id"]
            and other["input_product_id"] == rec["input_product_id"]
            and other["status"] == "CONFIRMED"
        )
        if cumulative + rec["rate_per_acre"] > cap:
            raise err(
                "ERR_SEASONAL_RATE_EXCEEDED",
                "Cumulative confirmed rate would exceed the seasonal cap.",
            )

    # --- All preconditions passed; perform confirm + side effects ---
    rec["status"] = "CONFIRMED"
    rec["applied_at"] = iso_now(now)
    rec["quantity_used"] = rec["rate_per_acre"] * rec["acres_treated"]
    rec["applied_cost"] = round2(rec["quantity_used"] * product["unit_cost"])
    rec["is_restricted"] = restricted
    if restricted:
        rec["reentry_clear_at"] = iso_now(now + timedelta(hours=product["reentry_interval_hours"]))
    else:
        rec["reentry_clear_at"] = None
    db.touch(rec)

    # Recompute plan actual_input_cost & provisional_cost_per_acre.
    compute.recompute_actual_input_cost(plan)
    compute.recompute_provisional_cost_per_acre(plan)
    db.touch(plan)

    if restricted:
        comp = db.new_entity(
            {
                "application_record_id": rec["id"],
                "crop_plan_id": rec["crop_plan_id"],
                "applicator_user_id": rec["applicator_user_id"],
                "reentry_interval_hours": product["reentry_interval_hours"],
                "preharvest_interval_days": product["preharvest_interval_days"],
                "reentry_clear_at": rec["reentry_clear_at"],
                "status": "ACTIVE",
            }
        )
        db.compliance_records[comp["id"]] = comp

        if parcel:
            parcel["status"] = "RESTRICTED"
            compute.recompute_reentry_blocked_until(parcel)
            db.touch(parcel)

    return object_response(serializers.application_record(rec))


@bp.post("/application-records/<aid>/void")
@require_roles("Agronomist")
def void_application(aid):
    rec = lookups.application_record(aid)
    if rec["status"] not in ("LOGGED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Application is not LOGGED or CONFIRMED.")

    was_confirmed = rec["status"] == "CONFIRMED"
    was_restricted = bool(rec.get("is_restricted"))

    rec["status"] = "VOIDED"
    db.touch(rec)

    if was_confirmed:
        plan = db.crop_plans.get(rec["crop_plan_id"])
        if plan:
            compute.recompute_actual_input_cost(plan)
            compute.recompute_provisional_cost_per_acre(plan)
            db.touch(plan)

        if was_restricted:
            # Supersede the linked compliance record(s).
            for comp in db.compliance_records.values():
                if comp["application_record_id"] == rec["id"] and comp["status"] == "ACTIVE":
                    comp["status"] = "SUPERSEDED"
                    db.touch(comp)

            parcel = db.parcels.get(plan["parcel_id"]) if plan else None
            if parcel:
                new_blocked = compute.recompute_reentry_blocked_until(parcel)
                # If no ACTIVE compliance record keeps the parcel blocked AND no
                # other restricted record holds it, revert to AVAILABLE (PRD §3.4).
                still_active = any(
                    c["status"] == "ACTIVE"
                    and db.crop_plans.get(c["crop_plan_id"], {}).get("parcel_id") == parcel["id"]
                    for c in db.compliance_records.values()
                )
                if new_blocked is None and not still_active:
                    parcel["status"] = "AVAILABLE"
                db.touch(parcel)

    return object_response(serializers.application_record(rec))


# ---------- ComplianceRecord (read-only) ----------
@bp.get("/compliance-records/<cid>")
@require_roles(*READ_ROLES)
def get_compliance(cid):
    rec = lookups.compliance_record(cid)
    return object_response(serializers.compliance_record(rec))


@bp.get("/compliance-records")
@require_roles(*READ_ROLES)
def list_compliance():
    limit, offset = parse_pagination()
    records = list(db.compliance_records.values())
    for key in ("crop_plan_id", "application_record_id", "applicator_user_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.compliance_record(r) for r in page], limit, offset, total
    )
