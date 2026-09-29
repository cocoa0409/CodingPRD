"""The logical clock, service contracts and facilities (PRD 3.1, 3.9)."""
from flask import Blueprint

from core import (
    ApiError, CLOCK, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
    ROLE_GRIEVANCE_COORDINATOR, ROLE_REGISTERED_DIETITIAN, all_rows, authorize,
    base_row, body_json, check_string_length, filter_eq, insert, iso, listing,
    now_logical, pagination, parse_instant, present, public, respond_object,
    touch, validate_fields,
)
from calc import (
    D, contract_facilities, derive_posture, facility_batches,
    facility_issuances, reconcile_ledger_from_source, rows_where,
)
from ops import (
    LEDGER_VIEW_FIELDS, SHARPS_VIEW_FIELDS, apply_close_out_verdict,
    need_contract, need_facility, not_terminal, paged, require_state,
    sync_facility, view,
)

bp = Blueprint("contract", __name__, url_prefix="/cfs")

CONTRACT_READ_ROLES = (
    ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
    ROLE_GRIEVANCE_COORDINATOR,
)
FACILITY_READ_ROLES = (
    ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CORRECTIONAL_OFFICER,
    ROLE_REGISTERED_DIETITIAN, ROLE_GRIEVANCE_COORDINATOR,
)

CONTRACT_TERMINAL = ("CLOSED",)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize()
    body = body_json()
    validate_fields(body, [Field("current_utc", "datetime", required=True)])
    CLOCK.set(parse_instant(body["current_utc"]))
    return respond_object({"current_utc": iso(now_logical())}, 200)


# --------------------------------------------------------------------------
# Service contracts
# --------------------------------------------------------------------------
CONTRACT_FIELDS = [
    Field("contract_code", "string", required=True),
    Field("vendor_name", "string", required=True),
    Field("contracted_kcal_per_meal_day", "integer", required=True, min_inclusive=1200),
    Field("contracted_protein_grams_per_meal_day", "number", required=True, min_inclusive=40),
    Field("contracted_sodium_mg_cap_per_meal_day", "integer", required=True, min_inclusive=1000),
    Field("cost_ceiling_cents_per_meal_day", "integer", required=True, min_exclusive=0),
    Field("ld_cents_per_missed_meal", "integer", required=True, min_inclusive=0),
    Field("ld_monthly_cap_cents", "integer", required=True, min_inclusive=0),
    Field("substitution_allowance_pct", "number", required=True,
          min_inclusive=0, max_inclusive=100),
]


@bp.route("/service-contracts", methods=["POST"])
def create_contract():
    authorize(ROLE_CONTRACT_ADMINISTRATOR)
    body = body_json()
    validate_fields(body, CONTRACT_FIELDS)
    check_string_length(body, "contract_code", 3, 32)
    for existing in all_rows("service_contracts"):
        if existing["contract_code"] == body["contract_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "contract_code is already in use.")
    row = base_row()
    row.update({
        "contract_code": body["contract_code"],
        "vendor_name": body["vendor_name"],
        "status": "DRAFT",
        "contracted_kcal_per_meal_day": body["contracted_kcal_per_meal_day"],
        "contracted_protein_grams_per_meal_day": body["contracted_protein_grams_per_meal_day"],
        "contracted_sodium_mg_cap_per_meal_day": body["contracted_sodium_mg_cap_per_meal_day"],
        "cost_ceiling_cents_per_meal_day": body["cost_ceiling_cents_per_meal_day"],
        "ld_cents_per_missed_meal": body["ld_cents_per_missed_meal"],
        "ld_monthly_cap_cents": body["ld_monthly_cap_cents"],
        "substitution_allowance_pct": body["substitution_allowance_pct"],
        "ld_variant": None,
        "total_trays_served": 0,
        "meal_days_served": 0,
        "missed_meal_total": 0,
        "substitution_total": 0,
        "substitution_rate_pct": D("0.00"),
        "grievance_sla_breach_count": 0,
        "raw_liquidated_damages_cents": 0,
        "substitution_surcharge_cents": 0,
        "liquidated_damages_cents": 0,
        "gross_food_cost_cents": 0,
        "cost_cents_per_meal_day_actual": D("0.00"),
        "cost_recovery_credit_cents": 0,
        "net_liquidated_damages_cents": 0,
        "performance_score": D("0.00"),
        "reconciled_at": None,
        "closed_at": None,
    })
    insert("service_contracts", row)
    return respond_object(public(row), 201)


@bp.route("/service-contracts/<row_id>", methods=["GET"])
def read_contract(row_id):
    authorize(*CONTRACT_READ_ROLES)
    return respond_object(public(need_contract(row_id)), 200)


@bp.route("/service-contracts", methods=["GET"])
def list_contracts():
    authorize(ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR)
    rows = filter_eq(all_rows("service_contracts"), "status")
    return listing(rows)


@bp.route("/service-contracts/<row_id>/activate", methods=["POST"])
def activate_contract(row_id):
    authorize(ROLE_CONTRACT_ADMINISTRATOR)
    contract = need_contract(row_id)
    not_terminal(contract, "status", CONTRACT_TERMINAL)
    require_state(contract, "status", ("DRAFT",))
    if not contract_facilities(contract["id"]):
        raise ApiError("ERR_INVALID_STATE", "No facility names this contract.")
    contract["status"] = "ACTIVE"
    touch(contract)
    return respond_object(public(contract), 200)


LD_VARIANTS = ("INCIDENT_BASED", "POPULATION_WEIGHTED")


@bp.route("/service-contracts/<row_id>/reconcile", methods=["POST"])
def reconcile_contract(row_id):
    authorize(ROLE_CONTRACT_ADMINISTRATOR)
    body = body_json()
    contract = need_contract(row_id)
    not_terminal(contract, "status", CONTRACT_TERMINAL)
    require_state(contract, "status", ("ACTIVE",))
    records = [r for r in all_rows("meal_service_records")
               if r["facility_id"] in set(f["id"] for f in contract_facilities(contract["id"]))]
    if any(r["status"] == "OPEN" for r in records):
        raise ApiError("ERR_INVALID_STATE", "A service record under this contract is still OPEN.")
    if not any(r["status"] in ("CLOSED", "DISPUTED") for r in records):
        raise ApiError("ERR_INVALID_STATE", "No settled service record to reconcile.")
    variant = body.get("ld_variant")
    if variant not in LD_VARIANTS:
        raise ApiError("ERR_LD_VARIANT_REQUIRED")
    contract["ld_variant"] = variant
    reconcile_ledger_from_source(contract)
    contract["status"] = "RECONCILING"
    contract["reconciled_at"] = now_logical()
    touch(contract)
    return respond_object(public(contract), 200)


@bp.route("/service-contracts/<row_id>/close", methods=["POST"])
def close_contract(row_id):
    authorize(ROLE_CONTRACT_ADMINISTRATOR)
    contract = need_contract(row_id)
    not_terminal(contract, "status", CONTRACT_TERMINAL)
    require_state(contract, "status", ("RECONCILING",))
    facility_ids = set(f["id"] for f in contract_facilities(contract["id"]))
    record_ids = set(r["id"] for r in all_rows("meal_service_records")
                     if r["facility_id"] in facility_ids)
    for sub in all_rows("menu_substitutions"):
        if sub["approval_status"] == "PENDING" and sub["meal_service_record_id"] in record_ids:
            raise ApiError("ERR_INVALID_STATE", "A substitution under this contract is still PENDING.")
    contract["status"] = "CLOSED"
    contract["closed_at"] = now_logical()
    touch(contract)
    apply_close_out_verdict(contract)
    return respond_object(public(contract), 200)


@bp.route("/service-contracts/<row_id>/performance-summary", methods=["GET"])
def contract_performance(row_id):
    authorize(ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR)
    contract = need_contract(row_id)
    return respond_object(view(contract, LEDGER_VIEW_FIELDS), 200)


# --------------------------------------------------------------------------
# Facilities
# --------------------------------------------------------------------------
FACILITY_FIELDS = [
    Field("contract_id", "string", required=True),
    Field("facility_code", "string", required=True),
    Field("name", "string", required=True),
    Field("sharps_authorized_count", "integer", required=True, min_inclusive=0),
    Field("satellite_site_count", "integer", min_inclusive=0),
    Field("blast_chiller_capacity", "integer", min_inclusive=1),
]


@bp.route("/facilities", methods=["POST"])
def create_facility():
    authorize(ROLE_CONTRACT_ADMINISTRATOR)
    body = body_json()
    validate_fields(body, FACILITY_FIELDS)
    need_contract(body["contract_id"])
    for existing in all_rows("facilities"):
        if existing["facility_code"] == body["facility_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "facility_code is already in use.")
    authorized = body["sharps_authorized_count"]
    row = base_row()
    row.update({
        "facility_code": body["facility_code"],
        "name": body["name"],
        "contract_id": body["contract_id"],
        "satellite_site_count": body["satellite_site_count"] if present(body, "satellite_site_count") else 0,
        "blast_chiller_capacity": body["blast_chiller_capacity"] if present(body, "blast_chiller_capacity") else 2,
        "sharps_authorized_count": authorized,
        "sharps_issued_count": 0,
        "sharps_unaccounted_count": 0,
        "sharps_audit_shortfall": 0,
        "sharps_on_board_count": authorized,
        "open_sharps_discrepancy_count": 0,
        "open_contraband_incident_count": 0,
        "corrective_action_required": False,
        "kitchen_posture": "OPEN",
        "active_special_diet_count": 0,
        "last_sharps_audit_at": None,
    })
    insert("facilities", row)
    return respond_object(public(row), 201)


@bp.route("/facilities/<row_id>", methods=["GET"])
def read_facility(row_id):
    authorize(*FACILITY_READ_ROLES)
    return respond_object(public(need_facility(row_id)), 200)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    authorize(ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR,
              ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CORRECTIONAL_OFFICER)
    rows = filter_eq(all_rows("facilities"), "contract_id")
    rows = filter_eq(rows, "kitchen_posture")
    return listing(rows)


@bp.route("/facilities/<row_id>/sharps-audit", methods=["POST"])
def sharps_audit(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [Field("counted_on_board", "integer", required=True, min_inclusive=0)])
    facility = need_facility(row_id)
    counted = body["counted_on_board"]
    accounted = counted + int(facility["sharps_issued_count"]) + int(facility["sharps_unaccounted_count"])
    authorized = int(facility["sharps_authorized_count"])
    if accounted > authorized:
        raise ApiError("ERR_SHARPS_COUNT_OVER_AUTHORIZED")
    facility["sharps_on_board_count"] = counted
    facility["sharps_audit_shortfall"] = authorized - accounted
    facility["last_sharps_audit_at"] = now_logical()
    sync_facility(facility, force=True)
    return respond_object(public(facility), 200)


@bp.route("/facilities/<row_id>/sharps-summary", methods=["GET"])
def sharps_summary(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR)
    facility = need_facility(row_id)
    return respond_object(view(facility, SHARPS_VIEW_FIELDS), 200)


@bp.route("/facilities/<row_id>/production-batches", methods=["GET"])
def facility_batch_listing(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_COMPLIANCE_AUDITOR, ROLE_REGISTERED_DIETITIAN)
    limit, offset = pagination()
    facility = need_facility(row_id)
    rows = filter_eq(facility_batches(facility["id"]), "production_stage")
    return paged(rows, limit, offset)


@bp.route("/facilities/<row_id>/tool-issuances", methods=["GET"])
def facility_issuance_listing(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER, ROLE_COMPLIANCE_AUDITOR, ROLE_FOOD_SERVICE_SUPERVISOR)
    limit, offset = pagination()
    facility = need_facility(row_id)
    rows = filter_eq(facility_issuances(facility["id"]), "status")
    return paged(rows, limit, offset)
