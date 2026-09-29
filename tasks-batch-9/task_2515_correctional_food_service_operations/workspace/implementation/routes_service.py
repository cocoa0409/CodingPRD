"""Meal service records and menu substitutions (PRD 3.7)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_GRIEVANCE_COORDINATOR,
    ROLE_REGISTERED_DIETITIAN, all_rows, authorize, base_row, body_json,
    filter_eq, insert, listing, now_logical, present, public, respond_object,
    touch, validate_fields,
)
from calc import (
    D, MEAL_SLOTS_PER_DAY, apply_ledger, floor_int, missed_meal_count,
    rows_where, substitution_equivalence,
)
from ops import (
    apply_missed_meal_escalation, contract_of, invalidate_reconciliation,
    need_contract, need_cycle, need_cycle_item, need_facility, need_forecast,
    need_service_record, need_substitution, not_terminal, require_state,
)

bp = Blueprint("service", __name__, url_prefix="/cfs")

MEAL_SLOTS = ("BREAKFAST", "LUNCH", "DINNER")
SUB_REASONS = ("SUPPLY_OUTAGE", "EQUIPMENT_FAILURE", "SECURITY_LOCKDOWN",
               "QA_CONDEMNATION")
DECISIONS = ("APPROVED", "REJECTED")
OPEN_BATCH_STAGES = ("PLANNED", "COOKED", "CHILLED", "STAGED")
TRAY_FIELDS = ("trays_served_general", "trays_served_segregation",
               "trays_served_satellite", "special_diet_trays_served")
SITE_TRAY_FIELDS = ("trays_served_general", "trays_served_segregation",
                    "trays_served_satellite")

RECORD_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CONTRACT_ADMINISTRATOR,
                     ROLE_COMPLIANCE_AUDITOR, ROLE_GRIEVANCE_COORDINATOR)
SUB_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
                  ROLE_COMPLIANCE_AUDITOR, ROLE_GRIEVANCE_COORDINATOR)


def post_record_close(record, contract):
    """Cascade hop 1: the incrementally maintained contract ledger."""
    contract["total_trays_served"] = int(contract["total_trays_served"]) + int(record["total_trays_served"])
    contract["meal_days_served"] = floor_int(
        D(contract["total_trays_served"]) / D(MEAL_SLOTS_PER_DAY))
    contract["missed_meal_total"] = int(contract["missed_meal_total"]) + int(record["missed_meal_count"])
    apply_ledger(contract)
    touch(contract)
    apply_missed_meal_escalation(contract)


# --------------------------------------------------------------------------
# Meal service records
# --------------------------------------------------------------------------
@bp.route("/meal-service-records", methods=["POST"])
def create_record():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("meal_forecast_id", "string", required=True),
        Field("service_date", "date", required=True),
        Field("meal_slot", "string", required=True, enum=MEAL_SLOTS),
        Field("trays_served_general", "integer", required=True, min_inclusive=0),
        Field("trays_served_segregation", "integer", required=True, min_inclusive=0),
        Field("trays_served_satellite", "integer", required=True, min_inclusive=0),
        Field("special_diet_trays_served", "integer", required=True, min_inclusive=0),
    ])
    facility = need_facility(body["facility_id"])
    forecast = need_forecast(body["meal_forecast_id"])
    if forecast["facility_id"] != facility["id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The forecast belongs to a different facility.")
    if forecast["service_date"] != body["service_date"] \
            or forecast["meal_slot"] != body["meal_slot"]:
        raise ApiError("ERR_SERVICE_WINDOW_MISMATCH")
    if forecast["status"] != "LOCKED":
        raise ApiError("ERR_FORECAST_NOT_LOCKED")
    if rows_where("meal_service_records", meal_forecast_id=forecast["id"]):
        raise ApiError("ERR_DUPLICATE_SERVICE_RECORD")

    served = sum(int(body[f]) for f in SITE_TRAY_FIELDS)
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "meal_forecast_id": forecast["id"],
        "service_date": body["service_date"],
        "meal_slot": body["meal_slot"],
        "trays_served_general": int(body["trays_served_general"]),
        "trays_served_segregation": int(body["trays_served_segregation"]),
        "trays_served_satellite": int(body["trays_served_satellite"]),
        "special_diet_trays_served": int(body["special_diet_trays_served"]),
        # The waste allowance is an operational buffer, never a commitment.
        "expected_service_trays": int(forecast["total_forecast_trays"]) - int(forecast["waste_allowance_trays"]),
        "total_trays_served": served,
        "missed_meal_count": 0,
        "substitution_count": 0,
        "dispute_tray_count": 0,
        "status": "OPEN",
        "closed_at": None,
    })
    insert("meal_service_records", row)
    return respond_object(public(row), 201)


@bp.route("/meal-service-records/<row_id>", methods=["GET"])
def read_record(row_id):
    authorize(*RECORD_READ_ROLES)
    return respond_object(public(need_service_record(row_id)), 200)


@bp.route("/meal-service-records", methods=["GET"])
def list_records():
    authorize(*RECORD_READ_ROLES)
    rows = filter_eq(all_rows("meal_service_records"), "facility_id")
    rows = filter_eq(rows, "meal_forecast_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "service_date")
    return listing(rows)


@bp.route("/meal-service-records/<row_id>", methods=["PATCH"])
def patch_record(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("trays_served_general", "integer", min_inclusive=0),
        Field("trays_served_segregation", "integer", min_inclusive=0),
        Field("trays_served_satellite", "integer", min_inclusive=0),
        Field("special_diet_trays_served", "integer", min_inclusive=0),
    ])
    record = need_service_record(row_id)
    not_terminal(record, "status", ("DISPUTED",))
    require_state(record, "status", ("OPEN",))
    for field in TRAY_FIELDS:
        if present(body, field):
            record[field] = int(body[field])
    record["total_trays_served"] = sum(int(record[f]) for f in SITE_TRAY_FIELDS)
    touch(record)
    return respond_object(public(record), 200)


@bp.route("/meal-service-records/<row_id>/close", methods=["POST"])
def close_record(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("expected_service_contract_version", "integer", required=True),
    ])
    record = need_service_record(row_id)
    facility = need_facility(record["facility_id"])
    contract = need_contract(facility["contract_id"])
    if int(body["expected_service_contract_version"]) != int(contract["version"]):
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    not_terminal(record, "status", ("DISPUTED",))
    require_state(record, "status", ("OPEN",))
    forecast = need_forecast(record["meal_forecast_id"])
    for batch in rows_where("production_batches", meal_forecast_id=forecast["id"]):
        if batch["production_stage"] in OPEN_BATCH_STAGES:
            raise ApiError("ERR_OPEN_BATCHES_REMAIN")

    record["missed_meal_count"] = missed_meal_count(record, forecast)
    record["status"] = "CLOSED"
    record["closed_at"] = now_logical()
    touch(record)
    post_record_close(record, contract)
    return respond_object(public(record), 200)


# --------------------------------------------------------------------------
# Menu substitutions
# --------------------------------------------------------------------------
@bp.route("/menu-substitutions", methods=["POST"])
def create_substitution():
    actor = authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("menu_cycle_item_id", "string", required=True),
        Field("meal_service_record_id", "string", required=True),
        Field("substitute_component_name", "string", required=True),
        Field("substitute_kcal_per_100g", "number", required=True, min_exclusive=0),
        Field("substitute_protein_grams_per_100g", "number", required=True, min_inclusive=0),
        Field("substitute_sodium_mg_per_100g", "number", required=True, min_inclusive=0),
        Field("substitute_portion_grams", "number", required=True, min_exclusive=0),
        Field("substitute_cost_cents", "integer", required=True, min_inclusive=0),
        Field("reason", "string", required=True, enum=SUB_REASONS),
    ])
    item = need_cycle_item(body["menu_cycle_item_id"])
    record = need_service_record(body["meal_service_record_id"])
    cycle = need_cycle(item["menu_cycle_id"])
    if cycle["facility_id"] != record["facility_id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The planned component belongs to another facility's menu.")
    verdict = substitution_equivalence(item, body)
    row = base_row()
    row.update({
        "menu_cycle_item_id": item["id"],
        "meal_service_record_id": record["id"],
        "substitute_component_name": body["substitute_component_name"],
        "substitute_kcal_per_100g": body["substitute_kcal_per_100g"],
        "substitute_protein_grams_per_100g": body["substitute_protein_grams_per_100g"],
        "substitute_sodium_mg_per_100g": body["substitute_sodium_mg_per_100g"],
        "substitute_portion_grams": body["substitute_portion_grams"],
        "substitute_cost_cents": int(body["substitute_cost_cents"]),
        "reason": body["reason"],
        "kcal_delta_pct": verdict["kcal_delta_pct"],
        "protein_delta_pct": verdict["protein_delta_pct"],
        "sodium_delta_mg": verdict["sodium_delta_mg"],
        "cost_variance_cents": verdict["cost_variance_cents"],
        "nutrition_equivalent": verdict["nutrition_equivalent"],
        "approval_status": "PENDING",
        "documented_by_user_id": actor.user_id,
        "decided_by_user_id": None,
    })
    insert("menu_substitutions", row)
    return respond_object(public(row), 201)


@bp.route("/menu-substitutions/<row_id>", methods=["GET"])
def read_substitution(row_id):
    authorize(*SUB_READ_ROLES)
    return respond_object(public(need_substitution(row_id)), 200)


@bp.route("/menu-substitutions", methods=["GET"])
def list_substitutions():
    authorize(*SUB_READ_ROLES)
    rows = filter_eq(all_rows("menu_substitutions"), "menu_cycle_item_id")
    rows = filter_eq(rows, "meal_service_record_id")
    rows = filter_eq(rows, "approval_status")
    return listing(rows)


@bp.route("/menu-substitutions/<row_id>/decision", methods=["POST"])
def decide_substitution(row_id):
    actor = authorize(ROLE_REGISTERED_DIETITIAN)
    body = body_json()
    validate_fields(body, [
        Field("decision", "string", required=True, enum=DECISIONS),
        Field("decision_note", "string"),
    ])
    sub = need_substitution(row_id)
    not_terminal(sub, "approval_status", ("APPROVED", "REJECTED"))
    require_state(sub, "approval_status", ("PENDING",))
    if actor.user_id == sub.get("documented_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    decision = body["decision"]
    if decision == "APPROVED" and not sub["nutrition_equivalent"] \
            and sub["reason"] != "QA_CONDEMNATION":
        raise ApiError("ERR_SUBSTITUTION_NOT_EQUIVALENT")

    sub["approval_status"] = decision
    sub["decided_by_user_id"] = actor.user_id
    touch(sub)

    if decision == "APPROVED":
        record = need_service_record(sub["meal_service_record_id"])
        record["substitution_count"] = int(record["substitution_count"]) + 1
        touch(record)
        facility = need_facility(record["facility_id"])
        contract = contract_of(facility)
        if contract is not None:
            # Hop 1: the substitution ledger moves.
            contract["substitution_total"] = int(contract["substitution_total"]) + 1
            apply_ledger(contract)
            # Hop 2: a held reconciliation is now stale.
            if contract["status"] == "RECONCILING":
                invalidate_reconciliation(contract)
            touch(contract)
    return respond_object(public(sub), 200)
