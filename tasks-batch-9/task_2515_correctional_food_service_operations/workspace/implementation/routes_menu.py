"""Menu cycles, components, nutrition attestation and activation (PRD 3.2)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN, all_rows,
    authorize, base_row, body_json, filter_eq, insert, listing, now_logical,
    pagination, present, public, respond_object, touch, validate_fields,
)
from calc import (
    D, MEAL_SLOTS_PER_DAY, cycle_cost, cycle_items, cycle_nutrition,
    facility_cycles,
)
from ops import (
    contract_of, need_cycle, need_cycle_item, need_facility, not_terminal,
    paged, require_state,
)

bp = Blueprint("menu", __name__, url_prefix="/cfs")

CYCLE_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
                    ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR)
ITEM_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
                   ROLE_COMPLIANCE_AUDITOR)
MEAL_SLOTS = ("BREAKFAST", "LUNCH", "DINNER")
CYCLE_TERMINAL = ("RETIRED",)


@bp.route("/menu-cycles", methods=["POST"])
def create_cycle():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("cycle_code", "string", required=True),
        Field("cycle_length_days", "integer", required=True,
              min_inclusive=1, max_inclusive=7),
    ])
    facility = need_facility(body["facility_id"])
    for existing in facility_cycles(facility["id"]):
        if existing["cycle_code"] == body["cycle_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "cycle_code is already in use at this facility.")
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "cycle_code": body["cycle_code"],
        "cycle_length_days": body["cycle_length_days"],
        "status": "DRAFT",
        "item_count": 0,
        "approved_kcal_per_meal_day": None,
        "approved_protein_grams_per_meal_day": None,
        "approved_sodium_mg_per_meal_day": None,
        "approved_cost_cents_per_meal_day": None,
        "nutrition_signed_by_user_id": None,
        "activated_by_user_id": None,
        "activated_at": None,
    })
    insert("menu_cycles", row)
    return respond_object(public(row), 201)


@bp.route("/menu-cycles/<row_id>", methods=["GET"])
def read_cycle(row_id):
    authorize(*CYCLE_READ_ROLES)
    return respond_object(public(need_cycle(row_id)), 200)


@bp.route("/menu-cycles", methods=["GET"])
def list_cycles():
    authorize(*CYCLE_READ_ROLES)
    rows = filter_eq(all_rows("menu_cycles"), "facility_id")
    rows = filter_eq(rows, "status")
    return listing(rows)


ITEM_FIELDS = [
    Field("cycle_day", "integer", required=True),
    Field("meal_slot", "string", required=True, enum=MEAL_SLOTS),
    Field("component_name", "string", required=True),
    Field("kcal_per_100g", "number", required=True, min_exclusive=0),
    Field("protein_grams_per_100g", "number", required=True, min_inclusive=0),
    Field("sodium_mg_per_100g", "number", required=True, min_inclusive=0),
    Field("portion_grams", "number", required=True, min_exclusive=0),
    Field("raw_cost_cents", "integer", required=True, min_inclusive=0),
    Field("therapeutic_safe", "boolean"),
    Field("religious_tags", "array"),
]


@bp.route("/menu-cycles/<row_id>/items", methods=["POST"])
def add_item(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, ITEM_FIELDS)
    cycle = need_cycle(row_id)
    day = body["cycle_day"]
    if day < 1 or day > int(cycle["cycle_length_days"]):
        raise ApiError("ERR_CYCLE_DAY_OUT_OF_RANGE")
    for existing in cycle_items(cycle["id"]):
        if existing["cycle_day"] == day and existing["meal_slot"] == body["meal_slot"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "That cycle day and meal slot is already filled.")
    not_terminal(cycle, "status", CYCLE_TERMINAL)
    row = base_row()
    row.update({
        "menu_cycle_id": cycle["id"],
        "cycle_day": day,
        "meal_slot": body["meal_slot"],
        "component_name": body["component_name"],
        "kcal_per_100g": body["kcal_per_100g"],
        "protein_grams_per_100g": body["protein_grams_per_100g"],
        "sodium_mg_per_100g": body["sodium_mg_per_100g"],
        "portion_grams": body["portion_grams"],
        "raw_cost_cents": body["raw_cost_cents"],
        "therapeutic_safe": body["therapeutic_safe"] if present(body, "therapeutic_safe") else True,
        "religious_tags": list(body["religious_tags"]) if present(body, "religious_tags") else [],
    })
    insert("menu_cycle_items", row)
    # The cycle's component set changed: the count moves and a signature dies.
    cycle["item_count"] = len(cycle_items(cycle["id"]))
    if cycle["status"] == "NUTRITION_APPROVED":
        cycle["status"] = "DRAFT"
        cycle["approved_kcal_per_meal_day"] = None
        cycle["approved_protein_grams_per_meal_day"] = None
        cycle["approved_sodium_mg_per_meal_day"] = None
        cycle["approved_cost_cents_per_meal_day"] = None
        cycle["nutrition_signed_by_user_id"] = None
    touch(cycle)
    return respond_object(public(row), 201)


@bp.route("/menu-cycles/<row_id>/items", methods=["GET"])
def list_cycle_items(row_id):
    authorize(*ITEM_READ_ROLES)
    limit, offset = pagination()
    cycle = need_cycle(row_id)
    rows = filter_eq(cycle_items(cycle["id"]), "meal_slot")
    return paged(rows, limit, offset)


@bp.route("/menu-cycle-items/<row_id>", methods=["GET"])
def read_item(row_id):
    authorize(*ITEM_READ_ROLES)
    return respond_object(public(need_cycle_item(row_id)), 200)


@bp.route("/menu-cycle-items", methods=["GET"])
def list_items():
    authorize(*ITEM_READ_ROLES)
    rows = filter_eq(all_rows("menu_cycle_items"), "menu_cycle_id")
    rows = filter_eq(rows, "meal_slot")
    return listing(rows)


@bp.route("/menu-cycles/<row_id>/nutrition-sign", methods=["POST"])
def nutrition_sign(row_id):
    actor = authorize(ROLE_REGISTERED_DIETITIAN)
    cycle = need_cycle(row_id)
    not_terminal(cycle, "status", CYCLE_TERMINAL)
    require_state(cycle, "status", ("DRAFT",))
    # Completeness is checked before anything is attested (PRD 3.2).
    if int(cycle["item_count"]) != int(cycle["cycle_length_days"]) * MEAL_SLOTS_PER_DAY:
        raise ApiError("ERR_MENU_CYCLE_INCOMPLETE")
    facility = need_facility(cycle["facility_id"])
    contract = contract_of(facility)
    figures = cycle_nutrition(cycle)
    if D(figures["approved_kcal_per_meal_day"]) < D(contract["contracted_kcal_per_meal_day"]):
        raise ApiError("ERR_NUTRITION_BELOW_STANDARD", "Energy is below the contracted floor.")
    if D(figures["approved_protein_grams_per_meal_day"]) < D(contract["contracted_protein_grams_per_meal_day"]):
        raise ApiError("ERR_NUTRITION_BELOW_STANDARD", "Protein is below the contracted floor.")
    if D(figures["approved_sodium_mg_per_meal_day"]) > D(contract["contracted_sodium_mg_cap_per_meal_day"]):
        raise ApiError("ERR_SODIUM_CAP_EXCEEDED")
    _raw_total, approved_cost = cycle_cost(cycle, facility)
    cycle["approved_kcal_per_meal_day"] = figures["approved_kcal_per_meal_day"]
    cycle["approved_protein_grams_per_meal_day"] = figures["approved_protein_grams_per_meal_day"]
    cycle["approved_sodium_mg_per_meal_day"] = figures["approved_sodium_mg_per_meal_day"]
    cycle["approved_cost_cents_per_meal_day"] = approved_cost
    cycle["nutrition_signed_by_user_id"] = actor.user_id
    cycle["status"] = "NUTRITION_APPROVED"
    touch(cycle)
    return respond_object(public(cycle), 200)


@bp.route("/menu-cycles/<row_id>/activate", methods=["POST"])
def activate_cycle(row_id):
    actor = authorize(ROLE_CONTRACT_ADMINISTRATOR)
    cycle = need_cycle(row_id)
    not_terminal(cycle, "status", CYCLE_TERMINAL)
    require_state(cycle, "status", ("NUTRITION_APPROVED",))
    if cycle.get("nutrition_signed_by_user_id") == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    facility = need_facility(cycle["facility_id"])
    contract = contract_of(facility)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    # Recomputed against the facility's *current* satellite tier.
    _raw_total, approved_cost = cycle_cost(cycle, facility)
    if approved_cost > int(contract["cost_ceiling_cents_per_meal_day"]):
        raise ApiError("ERR_COST_CEILING_EXCEEDED")
    cycle["approved_cost_cents_per_meal_day"] = approved_cost
    cycle["status"] = "ACTIVE"
    cycle["activated_by_user_id"] = actor.user_id
    cycle["activated_at"] = now_logical()
    touch(cycle)
    for other in facility_cycles(facility["id"]):
        if other["id"] != cycle["id"] and other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            touch(other)
    return respond_object(public(cycle), 200)
