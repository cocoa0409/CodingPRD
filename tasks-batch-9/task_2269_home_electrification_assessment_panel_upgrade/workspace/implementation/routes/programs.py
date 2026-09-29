"""Program, catalog and sweep endpoints (PRD section 3.1)."""
from flask import Blueprint, request

import clock
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import PROGRAM_ADMIN, PROGRAM_REVIEWER, ALL_ROLES, authorize

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("DRAFT", "OPEN", "SUSPENDED", "CLOSED")
CATEGORIES = ("HVAC", "WATER_HEATING", "APPLIANCE", "ENVELOPE", "ELECTRICAL_INFRASTRUCTURE")
CAP_GROUPS = ("HVAC_GROUP", "WATER_GROUP", "APPLIANCE_GROUP", "ELECTRICAL_GROUP", "NONE")


@bp.post("/programs")
@authorize(PROGRAM_ADMIN)
def create_program():
    payload = guards.body()
    record = {
        "name": fields.req_str(payload, "name", allow_empty=False),
        "state_code": fields.req_str(payload, "state_code", pattern=r"[A-Z]{2}"),
        "program_year": fields.opt_int(payload, "program_year", default=2026),
        "status": "DRAFT",
        "budget_total_cents": fields.req_int(payload, "budget_total_cents", minimum=0),
        "reservation_ttl_days": fields.opt_int(payload, "reservation_ttl_days", default=120, minimum=0),
        "extension_window_days": fields.opt_int(payload, "extension_window_days", default=30, minimum=0),
        "max_extension_days": fields.opt_int(payload, "max_extension_days", default=60, minimum=0),
        "max_extensions_per_reservation": fields.opt_int(
            payload, "max_extensions_per_reservation", default=1, minimum=0),
        "low_tier_cap_cents": fields.opt_int(payload, "low_tier_cap_cents", default=1400000, minimum=0),
        "moderate_tier_cap_cents": fields.opt_int(payload, "moderate_tier_cap_cents", default=800000, minimum=0),
        "standard_tier_cap_cents": fields.opt_int(payload, "standard_tier_cap_cents", default=300000, minimum=0),
        "low_tier_cost_share_pct": fields.opt_num(payload, "low_tier_cost_share_pct", default=1.00, minimum=0),
        "moderate_tier_cost_share_pct": fields.opt_num(
            payload, "moderate_tier_cost_share_pct", default=0.50, minimum=0),
        "standard_tier_cost_share_pct": fields.opt_num(
            payload, "standard_tier_cost_share_pct", default=0.30, minimum=0),
        "ami_low_threshold_pct": fields.opt_num(payload, "ami_low_threshold_pct", default=80.0, minimum=0),
        "ami_moderate_threshold_pct": fields.opt_num(
            payload, "ami_moderate_threshold_pct", default=150.0, minimum=0),
        "group_cap_cents": fields.opt_int(payload, "group_cap_cents", default=800000, minimum=0),
        "panel_upgrade_cap_cents": fields.opt_int(payload, "panel_upgrade_cap_cents", default=400000, minimum=0),
        "federal_credit_pct": fields.opt_num(payload, "federal_credit_pct", default=0.30, minimum=0),
        "federal_credit_cap_cents": fields.opt_int(payload, "federal_credit_cap_cents", default=200000, minimum=0),
        "max_combined_benefit_pct": fields.opt_num(payload, "max_combined_benefit_pct", default=1.00, minimum=0),
        "max_remediations_per_project": fields.opt_int(
            payload, "max_remediations_per_project", default=1, minimum=0),
        "quality_suspension_threshold": fields.opt_int(
            payload, "quality_suspension_threshold", default=70, minimum=0),
        "recertification_threshold": fields.opt_int(payload, "recertification_threshold", default=75, minimum=0),
    }
    record["budget_available_cents"] = record["budget_total_cents"]
    record["budget_reserved_cents"] = 0
    record["budget_committed_cents"] = 0
    record["budget_clawed_back_cents"] = 0
    program = store.new_record(record)
    store.programs[program["id"]] = program
    return envelope.object_response(store.public(program), 201)


@bp.get("/programs/<program_id>")
@authorize(*ALL_ROLES)
def read_program(program_id):
    program = domain.get_program(program_id)
    return envelope.object_response(store.public(program))


@bp.get("/programs")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_programs():
    limit, offset = guards.pagination()
    status = request.args.get("status")
    state_code = request.args.get("state_code")
    records = store.ordered(
        store.programs,
        lambda p: (status is None or p["status"] == status)
        and (state_code is None or p["state_code"] == state_code),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/programs/<program_id>/status")
@authorize(PROGRAM_ADMIN)
def program_status(program_id):
    payload = guards.body()
    new_status = fields.req_enum(payload, "new_status", PROGRAM_STATUSES)
    fields.opt_str(payload, "status_note")
    program = domain.get_program(program_id)
    current = program["status"]

    allowed = {
        ("DRAFT", "OPEN"),
        ("OPEN", "SUSPENDED"),
        ("SUSPENDED", "OPEN"),
        ("OPEN", "CLOSED"),
        ("SUSPENDED", "CLOSED"),
    }
    if (current, new_status) not in allowed:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if new_status == "OPEN" and current == "DRAFT" and program["budget_total_cents"] <= 0:
        raise ApiError(
            errors.ERR_INVALID_STATE_TRANSITION,
            message="budget_total_cents must be greater than zero to open the program.",
        )
    if new_status == "CLOSED":
        for reservation in store.reservations.values():
            if reservation["program_id"] == program["id"] and reservation["status"] == "RESERVED":
                raise ApiError(
                    errors.ERR_INVALID_STATE_TRANSITION,
                    message="The program still holds a RESERVED reservation.",
                )

    program["status"] = new_status
    store.touch(program)
    return envelope.object_response(store.public(program))


@bp.post("/programs/<program_id>/sweep")
@authorize(PROGRAM_ADMIN)
def program_sweep(program_id):
    guards.body()
    program = domain.get_program(program_id)
    now = clock.now()

    due = []
    for reservation in store.reservations.values():
        if reservation["program_id"] != program["id"] or reservation["status"] != "RESERVED":
            continue
        expires_at = clock.parse_datetime(reservation["expires_at"])
        if expires_at is not None and expires_at <= now:
            due.append((expires_at, reservation["_seq"], reservation))
    due.sort(key=lambda row: (row[0], row[1]))

    released = 0
    expired_project_ids = []
    for _expires, _seq, reservation in due:
        released += reservation["reserved_amount_cents"]
        project = domain.expire_reservation(reservation)
        if project is not None:
            expired_project_ids.append(project["id"])

    return envelope.object_response({
        "program_id": program["id"],
        "swept_reservation_count": len(due),
        "released_cents": released,
        "expired_project_ids": expired_project_ids,
        "program_budget_available_cents": program["budget_available_cents"],
    })


@bp.post("/programs/<program_id>/measure-catalog-items")
@authorize(PROGRAM_ADMIN)
def create_catalog_item(program_id):
    payload = guards.body()
    item = {
        "measure_code": fields.req_str(payload, "measure_code", pattern=r"[A-Z0-9]+(-[A-Z0-9]+)*"),
        "measure_name": fields.req_str(payload, "measure_name", allow_empty=False),
        "category": fields.req_enum(payload, "category", CATEGORIES),
        "unit_incentive_cents": fields.req_int(payload, "unit_incentive_cents", minimum=0),
        "measure_cap_cents": fields.req_int(payload, "measure_cap_cents", minimum=0),
        "combined_cap_group": fields.req_enum(payload, "combined_cap_group", CAP_GROUPS),
        "sort_order": fields.req_int(payload, "sort_order", minimum=0),
        "max_quantity": fields.opt_int(payload, "max_quantity", default=1, minimum=1),
        "required_panel_capacity_amps": fields.opt_int(
            payload, "required_panel_capacity_amps", default=0, minimum=0),
        "upgraded_capacity_amps": fields.opt_int(payload, "upgraded_capacity_amps", default=0, minimum=0),
        "is_panel_upgrade": fields.opt_bool(payload, "is_panel_upgrade", default=False),
        "requires_qualifying_appliance": fields.opt_bool(
            payload, "requires_qualifying_appliance", default=False),
        "qualifies_as_appliance_anchor": fields.opt_bool(
            payload, "qualifies_as_appliance_anchor", default=False),
        "prerequisite_measure_code": fields.opt_str(payload, "prerequisite_measure_code"),
        "standard_tier_eligible": fields.opt_bool(payload, "standard_tier_eligible", default=False),
        "active": fields.opt_bool(payload, "active", default=True),
    }
    program = domain.get_program(program_id)
    item["program_id"] = program["id"]

    if item["prerequisite_measure_code"] is not None:
        if domain.catalog_item(program["id"], item["prerequisite_measure_code"]) is None:
            raise ApiError(errors.ERR_MEASURE_CODE_NOT_IN_CATALOG)

    if domain.catalog_item(program["id"], item["measure_code"]) is not None:
        raise ApiError(errors.ERR_DUPLICATE_MEASURE_CODE)

    record = store.new_record(item)
    store.catalog_items[record["id"]] = record
    return envelope.object_response(store.public(record), 201)


@bp.get("/programs/<program_id>/measure-catalog-items")
@authorize(*ALL_ROLES)
def list_catalog_items(program_id):
    limit, offset = guards.pagination()
    active = guards.bool_arg("active")
    category = request.args.get("category")
    group = request.args.get("combined_cap_group")
    program = domain.get_program(program_id)

    def keep(item):
        if item["program_id"] != program["id"]:
            return False
        if active is not None and item["active"] != active:
            return False
        if category is not None and item["category"] != category:
            return False
        if group is not None and item["combined_cap_group"] != group:
            return False
        return True

    records = store.ordered(store.catalog_items, keep)
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/programs/<program_id>/measure-catalog-items/<item_id>/retirement")
@authorize(PROGRAM_ADMIN)
def retire_catalog_item(program_id, item_id):
    payload = guards.body()
    fields.opt_str(payload, "retirement_note")
    program = domain.get_program(program_id)
    item = store.catalog_items.get(item_id)
    if item is None or item["program_id"] != program["id"]:
        raise ApiError(errors.ERR_MEASURE_CATALOG_ITEM_NOT_FOUND)
    item["active"] = False
    store.touch(item)
    return envelope.object_response(store.public(item))


@bp.get("/programs/<program_id>/households")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_program_households(program_id):
    limit, offset = guards.pagination()
    income_tier = request.args.get("income_tier")
    county_code = request.args.get("county_code")
    program = domain.get_program(program_id)
    records = store.ordered(
        store.households,
        lambda h: h["program_id"] == program["id"]
        and (income_tier is None or h["income_tier"] == income_tier)
        and (county_code is None or h["county_code"] == county_code),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.get("/programs/<program_id>/contractors")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_program_contractors(program_id):
    limit, offset = guards.pagination()
    status = request.args.get("status")
    program = domain.get_program(program_id)
    records = store.ordered(
        store.contractors,
        lambda c: c["program_id"] == program["id"] and (status is None or c["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.get("/programs/<program_id>/inspectors")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_program_inspectors(program_id):
    limit, offset = guards.pagination()
    program = domain.get_program(program_id)
    records = store.ordered(store.inspectors, lambda i: i["program_id"] == program["id"])
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))
