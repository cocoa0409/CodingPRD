"""PlanTemplate routes (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import validate
from services.listing import paginate_and_render
from services.serialize import plan_template_view

bp = Blueprint("plan_templates", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/plan-templates", methods=["POST"])
def create_plan_template():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    institution_id = validate.require_string(body, "institution_id")
    institution = db.institutions.get(institution_id)
    if institution is None:
        raise err("ERR_NOT_FOUND", "Institution not found")

    name = validate.require_string(body, "name")
    installment_count = validate.require_int(body, "installment_count")
    plan_fee_cents = validate.require_int(body, "plan_fee_cents")

    down_payment_pct = body.get("down_payment_pct")
    if not isinstance(down_payment_pct, (int, float)) or isinstance(down_payment_pct, bool):
        raise err("ERR_INVALID_REQUEST", "down_payment_pct must be a number")

    # plan_fee_cents >= 0 (PRD §3.1).
    if plan_fee_cents < 0:
        raise err("ERR_INVALID_REQUEST", "plan_fee_cents must be >= 0")

    late_fee_grace_days = body.get("late_fee_grace_days", 3)
    if not isinstance(late_fee_grace_days, int) or isinstance(late_fee_grace_days, bool) \
            or late_fee_grace_days < 0:
        raise err("ERR_INVALID_REQUEST", "late_fee_grace_days must be an integer >= 0")

    autopay_required = validate.optional_bool(body, "autopay_required", False)

    # installment_count in [1,12]; down_payment_pct in [0,0.5] (PRD §3.1).
    if installment_count < 1 or installment_count > 12:
        raise err("ERR_INVALID_PLAN_TEMPLATE", "installment_count out of [1,12]")
    if down_payment_pct < 0 or down_payment_pct > 0.5:
        raise err("ERR_INVALID_PLAN_TEMPLATE", "down_payment_pct out of [0,0.5]")

    record = db.stamp_new({
        "institution_id": institution_id,
        "name": name,
        "installment_count": installment_count,
        "down_payment_pct": down_payment_pct,
        "plan_fee_cents": plan_fee_cents,
        "late_fee_grace_days": late_fee_grace_days,
        "autopay_required": autopay_required,
        "status": "ACTIVE",
    })
    db.plan_templates[record["id"]] = record
    return success(plan_template_view(record), status=201)


@bp.route("/institutions/plan-templates/<plan_template_id>", methods=["GET"])
def get_plan_template(plan_template_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.plan_templates.get(plan_template_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Plan template not found")
    return success(plan_template_view(record), status=200)


@bp.route("/institutions/plan-templates", methods=["GET"])
def list_plan_templates():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    institution_id = request.args.get("institution_id")
    status = request.args.get("status")
    records = list(db.plan_templates.values())
    if institution_id is not None:
        records = [r for r in records if r["institution_id"] == institution_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, plan_template_view)


@bp.route("/institutions/plan-templates/<plan_template_id>/retire", methods=["POST"])
def retire_plan_template(plan_template_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    record = db.plan_templates.get(plan_template_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Plan template not found")
    if record["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan template must be ACTIVE to retire")
    record["status"] = "RETIRED"
    db.touch(record)
    return success(plan_template_view(record), status=200)
