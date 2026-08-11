"""Recipes, revisions and label approvals."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import label_required_elements
from .cascades import recipe_revision_cascade
from .envelope import list_response, object_response
from .errors import ApiError
from .store import base_record, collection_sorted, db, touch
from .util import dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
)

bp = Blueprint("recipes", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")
LABEL_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "STALE")


def require_id(payload, name):
    """Rung 19 presence/type guard in front of an existence rung."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", "Field '%s' is required." % name)
    return value


# ------------------------------------------------------------------ recipes


@bp.post("/recipes")
def create_recipe():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("name", "string", required=True),
            field("style", "enum", required=True, members=C.RECIPE_STYLES),
            field("target_ph_ceiling", "number", required=True),
            field("planned_f1_days", "integer", required=True),
            field("planned_f2_days", "integer", required=True),
            field("base_gravity_brix", "number", required=True),
            field(
                "intended_abv_class", "enum", required=True, members=C.ABV_CLASSES
            ),
            field("f2_added_sugar_g_per_l", "number", default=Decimal("0")),
            field("pasteurization_required", "boolean", default=False),
        ],
    )
    if data["planned_f2_days"] > C.F2_MAX_DAYS:
        raise ApiError(
            "ERR_VALIDATION",
            "planned_f2_days may not exceed %d days." % C.F2_MAX_DAYS,
        )

    record = base_record()
    record.update(
        {
            "name": data["name"],
            "style": data["style"],
            "recipe_version_number": 1,
            "target_ph_ceiling": round2(data["target_ph_ceiling"]),
            "planned_f1_days": data["planned_f1_days"],
            "planned_f2_days": data["planned_f2_days"],
            "f2_added_sugar_g_per_l": dec(data["f2_added_sugar_g_per_l"]),
            "base_gravity_brix": dec(data["base_gravity_brix"]),
            "pasteurization_required": bool(data["pasteurization_required"]),
            "intended_abv_class": data["intended_abv_class"],
            "active_label_approval_id": None,
        }
    )
    db.recipes[record["id"]] = record
    return object_response(record, 201)


@bp.post("/recipes/<id>/revise")
def revise_recipe(id):
    authorize("ProductionOperator", "PlatformAdmin")
    recipe = lookup.recipe(id)
    payload = body_dict()
    parse_body(payload, [field("change_note", "string")])

    recipe["recipe_version_number"] = int(recipe["recipe_version_number"]) + 1
    recipe_revision_cascade(recipe)
    touch(recipe)
    return object_response(recipe)


@bp.get("/recipes/<id>")
def read_recipe(id):
    authorize(*READ_ROLES)
    return object_response(lookup.recipe(id))


@bp.get("/recipes/<id>/label-approvals")
def list_recipe_label_approvals(id):
    authorize(*READ_ROLES)
    recipe = lookup.recipe(id)
    status = query_enum("status", LABEL_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.label_approvals,
        lambda a: a["recipe_id"] == recipe["id"]
        and (status is None or a["status"] == status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------- label approvals


def _label_class_gate(approval, recipe):
    """Rung 48 -- superset, class match and pasteurisation statement."""
    required = label_required_elements(approval["abv_class"], approval["pasteurized"])
    approval["required_elements"] = required
    declared = set(approval["declared_elements"] or [])
    if not declared.issuperset(set(required)):
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "declared_elements must be a superset of required_elements.",
        )
    if approval["abv_class"] != recipe["intended_abv_class"]:
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "The label abv_class does not match the recipe's intended_abv_class.",
        )
    if recipe["pasteurization_required"] and not approval["pasteurized"]:
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "The recipe requires pasteurisation, so the label must carry the statement.",
        )


@bp.post("/label-approvals")
def create_label_approval():
    authorize("ComplianceOfficer", "PlatformAdmin")
    payload = body_dict()
    lookup.recipe(require_id(payload, "recipe_id"))
    data = parse_body(
        payload,
        [
            field("recipe_id", "string", required=True),
            field("abv_class", "enum", required=True, members=C.ABV_CLASSES),
            field("pasteurized", "boolean", required=True),
            field("declared_elements", "array", required=True),
        ],
    )
    record = base_record()
    record.update(
        {
            "recipe_id": data["recipe_id"],
            "approved_recipe_version_number": None,
            "abv_class": data["abv_class"],
            "pasteurized": bool(data["pasteurized"]),
            "required_elements": label_required_elements(
                data["abv_class"], bool(data["pasteurized"])
            ),
            "declared_elements": list(data["declared_elements"]),
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "approved_at": None,
            "stale_reason": None,
        }
    )
    db.label_approvals[record["id"]] = record
    return object_response(record, 201)


@bp.post("/label-approvals/<id>/submit")
def submit_label_approval(id):
    authorize("ComplianceOfficer", "PlatformAdmin")
    approval = lookup.label_approval(id)
    body_dict()
    if approval["status"] not in ("DRAFT", "STALE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT or STALE revision may be submitted.",
        )
    recipe = lookup.recipe(approval["recipe_id"])
    _label_class_gate(approval, recipe)

    from flask import g

    approval["status"] = "SUBMITTED"
    approval["submitted_by_user_id"] = g.user_id
    approval["stale_reason"] = None
    touch(approval)
    return object_response(approval)


@bp.post("/label-approvals/<id>/approve")
def approve_label_approval(id):
    from flask import g

    authorize("ComplianceOfficer", "PlatformAdmin")
    approval = lookup.label_approval(id)
    body_dict()
    if approval["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SUBMITTED revision may be approved."
        )
    recipe = lookup.recipe(approval["recipe_id"])
    _label_class_gate(approval, recipe)
    if g.user_id == approval["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver may not be the submitter of this revision.",
        )

    for other in collection_sorted(
        db.label_approvals,
        lambda a: a["recipe_id"] == recipe["id"]
        and a["id"] != approval["id"]
        and a["status"] == "APPROVED",
    ):
        other["status"] = "STALE"
        other["stale_reason"] = "RECIPE_REVISED"
        touch(other)

    approval["status"] = "APPROVED"
    approval["approved_recipe_version_number"] = int(recipe["recipe_version_number"])
    approval["approved_by_user_id"] = g.user_id
    approval["approved_at"] = db.clock
    approval["stale_reason"] = None
    touch(approval)

    recipe["active_label_approval_id"] = approval["id"]
    touch(recipe)
    return object_response(approval)
