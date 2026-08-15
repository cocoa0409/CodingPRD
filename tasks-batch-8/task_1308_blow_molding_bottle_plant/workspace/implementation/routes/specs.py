from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_CUSTOMER_NOT_FOUND, \
    ERR_BOTTLE_SPEC_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_INVALID_STATE, \
    ERR_ALREADY_TERMINAL, ERR_SPEC_UNCHANGED_SINCE_REJECTION
from calc import logistics_comparison
from services import stamp_new, touch, ser_bottle_spec, \
    ser_qualification_run, sorted_rows, cancel_order
from util import new_id
from validate import get_body, check_fields, pagination_params, query_filter, \
    query_number
from routes.freight import require_active_card

bp = Blueprint("bottle_specs", __name__)

RESINS = {"PET", "HDPE", "PP"}
COLOR_CLASSES = {"CLEAR", "LIGHT", "DARK"}
LABEL_TYPES = {"NONE", "PRESSURE_SENSITIVE", "SHRINK_SLEEVE", "IN_MOLD"}
RUN_STATUSES = {"PLANNED", "EXECUTED", "CUSTOMER_REVIEW", "APPROVED",
                "REJECTED"}
READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler", "LogisticsCoordinator",
              "CustomerQualityRep"]

# The twelve content fields a PATCH may touch (PRD 3.2)
CONTENT_FIELDS = {
    "target_weight_g": ("number", False),
    "weight_tolerance_pct": ("number", False),
    "color_contrast_class": ("enum", False, COLOR_CLASSES),
    "bottle_cube_cm3": ("int", False),
    "preform_cube_cm3": ("int", False),
    "preform_weight_g": ("number", False),
    "neck_finish": ("str", False),
    "height_mm": ("number", False),
    "diameter_mm": ("number", False),
    "unit_price_cents": ("int", False),
    "label_type": ("enum", False, LABEL_TYPES),
    "min_cavitation_required": ("int", False),
}


def get_spec_or_404(spec_id):
    spec = store.bottle_specs.get(spec_id)
    if spec is None:
        raise_err(ERR_BOTTLE_SPEC_NOT_FOUND, "BottleSpec id does not resolve")
    return spec


def has_open_orders(spec):
    for o in store.production_orders.values():
        if (o["bottle_spec_id"] == spec["id"]
                and o["status"] in ("SCHEDULED", "RELEASED", "RUNNING", "HELD")):
            return True
    return False


@bp.post("/bottle-specs")
def create_spec():
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "customer_id": ("str", True),
        "spec_code": ("str", True),
        "resin_type": ("enum", True, RESINS),
        "color_contrast_class": ("enum", True, COLOR_CLASSES),
        "target_weight_g": ("number", True),
        "weight_tolerance_pct": ("number", False),
        "neck_finish": ("str", True),
        "height_mm": ("number", True),
        "diameter_mm": ("number", True),
        "bottle_cube_cm3": ("int", True),
        "preform_cube_cm3": ("int", True),
        "preform_weight_g": ("number", True),
        "unit_price_cents": ("int", True),
        "label_type": ("enum", True, LABEL_TYPES),
        "min_cavitation_required": ("int", True),
    })
    customer = store.customers.get(body["customer_id"])
    if customer is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer id does not resolve")
    for s in store.bottle_specs.values():
        if (s["customer_id"] == customer["id"]
                and s["spec_code"] == body["spec_code"]):
            raise_err(ERR_DUPLICATE_CODE,
                      "spec_code must be unique within the customer")
    spec = {
        "customer_id": customer["id"],
        "spec_code": body["spec_code"],
        "resin_type": body["resin_type"],
        "color_contrast_class": body["color_contrast_class"],
        "target_weight_g": body["target_weight_g"],
        "weight_tolerance_pct": body.get("weight_tolerance_pct"),
        "neck_finish": body["neck_finish"],
        "height_mm": body["height_mm"],
        "diameter_mm": body["diameter_mm"],
        "bottle_cube_cm3": body["bottle_cube_cm3"],
        "preform_cube_cm3": body["preform_cube_cm3"],
        "preform_weight_g": body["preform_weight_g"],
        "unit_price_cents": body["unit_price_cents"],
        "label_type": body["label_type"],
        "min_cavitation_required": body["min_cavitation_required"],
        "content_revision": 1,
        "qualified_revision": None,
        "rejected_revision": None,
        "status": "DRAFT",
    }
    if spec["weight_tolerance_pct"] is None:
        from decimal import Decimal
        spec["weight_tolerance_pct"] = Decimal("2.0")
    stamp_new(spec, new_id())
    store.bottle_specs[spec["id"]] = spec
    return success_object(ser_bottle_spec(spec), 201)


@bp.get("/bottle-specs/<sid>")
def get_spec(sid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_bottle_spec(get_spec_or_404(sid)))


@bp.patch("/bottle-specs/<sid>")
def patch_spec(sid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), CONTENT_FIELDS)
    spec = get_spec_or_404(sid)
    if spec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "RETIRED spec cannot be edited")
    changed = False
    for field, value in body.items():
        if spec[field] != value:
            spec[field] = value
            changed = True
    if changed:
        spec["content_revision"] += 1
        if spec["status"] == "PRODUCTION_ACTIVE":
            # disruptive edit: fall back to REVISION_REQUESTED, pin the
            # rejection at the freshly incremented revision, cancel the
            # spec's DRAFT/SCHEDULED orders and their active slots
            spec["status"] = "REVISION_REQUESTED"
            spec["rejected_revision"] = spec["content_revision"]
            for o in list(store.production_orders.values()):
                if (o["bottle_spec_id"] == spec["id"]
                        and o["status"] in ("DRAFT", "SCHEDULED")):
                    cancel_order(o)
        touch(spec)
    return success_object(ser_bottle_spec(spec))


@bp.post("/bottle-specs/<sid>/submit")
def submit_spec(sid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    check_fields(get_body(), {})
    spec = get_spec_or_404(sid)
    if spec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "RETIRED is terminal")
    if spec["status"] == "DRAFT":
        pass
    elif spec["status"] == "REVISION_REQUESTED":
        # guarded resubmission: content must have advanced past the
        # revision pinned on entry into REVISION_REQUESTED
        if (spec["rejected_revision"] is not None
                and spec["content_revision"] <= spec["rejected_revision"]):
            raise_err(ERR_SPEC_UNCHANGED_SINCE_REJECTION,
                      "Resubmission requires a content edit after rejection")
    else:
        raise_err(ERR_INVALID_STATE,
                  "Only DRAFT or REVISION_REQUESTED specs can be submitted")
    spec["status"] = "SUBMITTED"
    touch(spec)
    return success_object(ser_bottle_spec(spec))


@bp.post("/bottle-specs/<sid>/begin-qualification")
def begin_qualification(sid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    check_fields(get_body(), {})
    spec = get_spec_or_404(sid)
    if spec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "RETIRED is terminal")
    if spec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE,
                  "Only a SUBMITTED spec can enter qualification")
    spec["status"] = "IN_QUALIFICATION"
    touch(spec)
    return success_object(ser_bottle_spec(spec))


@bp.post("/bottle-specs/<sid>/retire")
def retire_spec(sid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    check_fields(get_body(), {})
    spec = get_spec_or_404(sid)
    if spec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "RETIRED is terminal")
    if spec["status"] not in ("DRAFT", "QUALIFIED", "PRODUCTION_ACTIVE"):
        raise_err(ERR_INVALID_STATE,
                  "Spec cannot be retired from its current state")
    if has_open_orders(spec):
        raise_err(ERR_INVALID_STATE,
                  "Spec has orders in SCHEDULED/RELEASED/RUNNING/HELD")
    spec["status"] = "RETIRED"
    touch(spec)
    return success_object(ser_bottle_spec(spec))


@bp.get("/bottle-specs/<sid>/qualification-runs")
def spec_runs(sid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
                        "CustomerQualityRep"])
    get_spec_or_404(sid)
    status = query_filter("status", RUN_STATUSES)
    limit, offset = pagination_params()
    rows = [r for r in store.qualification_runs.values()
            if r["bottle_spec_id"] == sid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_qualification_run(r) for r in page], limit,
                        offset, len(rows))


@bp.get("/bottle-specs/<sid>/logistics-comparison")
def logistics_compare(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator", "ProcessEngineer"])
    spec = get_spec_or_404(sid)
    quantity = query_number("quantity", required=True)
    if quantity != int(quantity):
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "quantity must be an integer")
    card = require_active_card()
    result = logistics_comparison(spec, int(quantity), card["tiers"])
    return success_object(result)
