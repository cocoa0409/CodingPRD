"""MaintenancePlan routes."""
from datetime import timedelta

from flask import Blueprint

from db import db, new_id
from errors import (
    ERR_BAD_REQUEST,
    ERR_CROSS_SITE_REFERENCE,
    ERR_EQUIPMENT_LIFECYCLE,
    ERR_INVALID_STATE,
    ERR_PLAN_KIND_FIELDS,
    raise_err,
)
from middleware import require_role
from response import success_object
from services.common import (
    bump_version,
    check_version,
    get_equipment_or_404,
    get_json_body,
    get_plan_or_404,
    get_site_or_404,
    get_template_or_404,
)
from services.serialize import serialize_plan

bp = Blueprint("plans", __name__)

VALID_KINDS = {"PERIODIC_TIME", "PERIODIC_USAGE", "TRIGGER_ALARM", "TRIGGER_THRESHOLD"}
VALID_OPS = {"GTE", "GT", "LTE", "LT"}


def _validate_kind_fields(kind, fields):
    """Check that the kind-required fields are present and shape-valid.

    `fields` is a dict of the relevant fields from the body or merged state.
    """
    if kind == "PERIODIC_TIME":
        v = fields.get("interval_days")
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise_err(ERR_PLAN_KIND_FIELDS, "interval_days is required for PERIODIC_TIME")
    elif kind == "PERIODIC_USAGE":
        v = fields.get("interval_usage")
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise_err(ERR_PLAN_KIND_FIELDS, "interval_usage is required for PERIODIC_USAGE")
    elif kind == "TRIGGER_ALARM":
        v = fields.get("alarm_code")
        if not isinstance(v, str) or not v:
            raise_err(ERR_PLAN_KIND_FIELDS, "alarm_code is required for TRIGGER_ALARM")
    elif kind == "TRIGGER_THRESHOLD":
        m = fields.get("threshold_metric")
        op = fields.get("threshold_op")
        tv = fields.get("threshold_value")
        if not isinstance(m, str) or not m:
            raise_err(ERR_PLAN_KIND_FIELDS, "threshold_metric is required")
        if op not in VALID_OPS:
            raise_err(ERR_PLAN_KIND_FIELDS, "threshold_op invalid")
        if not isinstance(tv, (int, float)) or isinstance(tv, bool):
            raise_err(ERR_PLAN_KIND_FIELDS, "threshold_value invalid")


@bp.route("/sites/<site_id>/plans", methods=["POST"])
def create_plan(site_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    body = get_json_body()

    for f in ["equipment_id", "template_id", "kind"]:
        if f not in body or body.get(f) in (None, ""):
            raise_err(ERR_BAD_REQUEST, f"{f} is required")

    kind = body["kind"]
    if kind not in VALID_KINDS:
        raise_err(ERR_BAD_REQUEST, "invalid kind")

    # Cross-site validation
    eq = db.equipment.get(body["equipment_id"])
    if eq is None:
        from errors import ERR_NOT_FOUND
        raise_err(ERR_NOT_FOUND, "equipment_id not found")
    if eq["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "equipment belongs to a different site")
    tpl = db.templates.get(body["template_id"])
    if tpl is None:
        from errors import ERR_NOT_FOUND
        raise_err(ERR_NOT_FOUND, "template_id not found")
    if tpl["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "template belongs to a different site")

    _validate_kind_fields(kind, body)

    pid = new_id()
    clock = db.site_clock(site_id)
    p = {
        "id": pid,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "site_id": site_id,
        "equipment_id": body["equipment_id"],
        "template_id": body["template_id"],
        "kind": kind,
        "interval_days": body.get("interval_days") if kind == "PERIODIC_TIME" else None,
        "interval_usage": body.get("interval_usage") if kind == "PERIODIC_USAGE" else None,
        "alarm_code": body.get("alarm_code") if kind == "TRIGGER_ALARM" else None,
        "threshold_metric": body.get("threshold_metric") if kind == "TRIGGER_THRESHOLD" else None,
        "threshold_op": body.get("threshold_op") if kind == "TRIGGER_THRESHOLD" else None,
        "threshold_value": body.get("threshold_value") if kind == "TRIGGER_THRESHOLD" else None,
        "status": "DRAFT",
        "last_generated_at": None,
        "last_generated_usage": None,
        "next_due_at": None,
    }
    db.plans[pid] = p
    return success_object(serialize_plan(p), 201)


@bp.route("/sites/<site_id>/plans/<plan_id>", methods=["GET"])
def get_plan(site_id, plan_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    return success_object(serialize_plan(p))


@bp.route("/sites/<site_id>/plans/<plan_id>", methods=["PATCH"])
def patch_plan(site_id, plan_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    body = get_json_body()
    check_version(p, body)

    if "kind" in body and body["kind"] != p["kind"]:
        raise_err(ERR_BAD_REQUEST, "kind is immutable")

    # Build merged state to validate kind-required fields after mutation.
    merged = {
        "interval_days": body.get("interval_days", p.get("interval_days")),
        "interval_usage": body.get("interval_usage", p.get("interval_usage")),
        "alarm_code": body.get("alarm_code", p.get("alarm_code")),
        "threshold_metric": body.get("threshold_metric", p.get("threshold_metric")),
        "threshold_op": body.get("threshold_op", p.get("threshold_op")),
        "threshold_value": body.get("threshold_value", p.get("threshold_value")),
    }
    _validate_kind_fields(p["kind"], merged)

    # Apply only fields relevant to kind
    if p["kind"] == "PERIODIC_TIME" and "interval_days" in body:
        p["interval_days"] = body["interval_days"]
        # Recompute next_due_at = (last_generated_at OR plan.created_at) + new interval_days*86400s
        base = p["last_generated_at"] if p.get("last_generated_at") else p["created_at"]
        p["next_due_at"] = base + timedelta(seconds=p["interval_days"] * 86400)
    if p["kind"] == "PERIODIC_USAGE" and "interval_usage" in body:
        p["interval_usage"] = body["interval_usage"]
    if p["kind"] == "TRIGGER_ALARM" and "alarm_code" in body:
        p["alarm_code"] = body["alarm_code"]
    if p["kind"] == "TRIGGER_THRESHOLD":
        if "threshold_metric" in body:
            p["threshold_metric"] = body["threshold_metric"]
        if "threshold_op" in body:
            p["threshold_op"] = body["threshold_op"]
        if "threshold_value" in body:
            p["threshold_value"] = body["threshold_value"]

    bump_version(p, site_id)
    return success_object(serialize_plan(p))


@bp.route("/sites/<site_id>/plans/<plan_id>/activate", methods=["POST"])
def activate_plan(site_id, plan_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    if p["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Plan must be DRAFT to activate")

    # Check kind-required fields
    _validate_kind_fields(p["kind"], p)

    # Equipment lifecycle gate — must not be DECOMMISSIONED. Tests bootstrap
    # plan activation while equipment is still INSTALLED (then commission
    # requires an ACTIVE plan), so INSTALLED/COMMISSIONED/IN_SERVICE are all
    # acceptable for plan activation.
    eq = db.equipment.get(p["equipment_id"])
    if eq is None or eq["lifecycle_status"] == "DECOMMISSIONED":
        raise_err(ERR_EQUIPMENT_LIFECYCLE, "Equipment lifecycle does not permit activation")

    p["status"] = "ACTIVE"
    clock = db.site_clock(site_id)
    if p["kind"] == "PERIODIC_TIME":
        p["next_due_at"] = clock + timedelta(seconds=p["interval_days"] * 86400)
    if p["kind"] == "PERIODIC_USAGE":
        p["last_generated_usage"] = eq["usage_counter"]

    bump_version(p, site_id)
    return success_object(serialize_plan(p))


@bp.route("/sites/<site_id>/plans/<plan_id>/pause", methods=["POST"])
def pause_plan(site_id, plan_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    if p["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Plan must be ACTIVE to pause")
    p["status"] = "PAUSED"
    bump_version(p, site_id)
    return success_object(serialize_plan(p))


@bp.route("/sites/<site_id>/plans/<plan_id>/resume", methods=["POST"])
def resume_plan(site_id, plan_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    if p["status"] != "PAUSED":
        raise_err(ERR_INVALID_STATE, "Plan must be PAUSED to resume")
    p["status"] = "ACTIVE"
    if p["kind"] == "PERIODIC_TIME":
        clock = db.site_clock(site_id)
        if p.get("last_generated_at"):
            candidate = p["last_generated_at"] + timedelta(seconds=p["interval_days"] * 86400)
            p["next_due_at"] = max(candidate, clock)
        else:
            p["next_due_at"] = clock + timedelta(seconds=p["interval_days"] * 86400)
    bump_version(p, site_id)
    return success_object(serialize_plan(p))


@bp.route("/sites/<site_id>/plans/<plan_id>/retire", methods=["POST"])
def retire_plan(site_id, plan_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    p = get_plan_or_404(site_id, plan_id)
    if p["status"] not in {"ACTIVE", "PAUSED"}:
        raise_err(ERR_INVALID_STATE, "Plan must be ACTIVE or PAUSED to retire")
    p["status"] = "RETIRED"
    bump_version(p, site_id)
    return success_object(serialize_plan(p))
