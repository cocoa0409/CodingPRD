"""Damage assessments, their append-only line-item log, and final settlement."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, new_append_only, touch, ordered
from errors import ApiError
from guard import (auth, lookup, get_body, resolve_fk, v_string, v_int, v_number,
                   v_bool, v_enum, require_customer_owner)
from response import success, created, paginate

bp = Blueprint("assessments", __name__)

COMPONENTS = ("FLOOR", "WALL", "HVAC", "ROOF", "DOOR", "ELECTRICAL")
SEVERITIES = ("MINOR", "MODERATE", "SEVERE")
GRADES = ("A", "B", "C", "D")
OPEN_STATES = ("DRAFT", "SUBMITTED", "DISPUTED")


@bp.post("/damage-assessments")
def create_assessment():
    user_id, role = auth("DamageAssessor")
    body = get_body()

    # rank 4 -- body foreign keys in the declared field order
    lease = resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")
    unit = resolve_fk(body, "unit_id", store.units, "ERR_UNIT_NOT_FOUND")
    job = resolve_fk(body, "logistics_job_id", store.jobs, "ERR_LOGISTICS_JOB_NOT_FOUND")

    # rank 5 -- body shape
    lease_id = v_string(body, "lease_id")
    unit_id = v_string(body, "unit_id")
    logistics_job_id = v_string(body, "logistics_job_id")
    expected_lease_version = v_int(body, "expected_lease_version")

    # rank 8 -- stale parent version
    if expected_lease_version != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION",
                       "expected_lease_version does not match the lease's current version.")

    # rank 13 -- cross-entity link agreement
    if (job["status"] != "COMPLETED" or job["job_type"] != "TEARDOWN_RETURN"
            or job["lease_id"] != lease_id or job["unit_id"] != unit_id):
        raise ApiError("ERR_ENTITY_LINK_MISMATCH",
                       "The logistics job does not match this lease and unit.")

    # re-assessment retires every still-open assessment on this lease
    for existing in services.assessments_of_lease(lease_id):
        if existing["status"] in OPEN_STATES:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    lease["assessment_round"] += 1
    touch(lease)

    record = new_record(
        unit_id=unit_id,
        lease_id=lease_id,
        logistics_job_id=logistics_job_id,
        assessor_user_id=user_id,
        status="DRAFT",
        dispute_rounds=0,
        condition_grade_before=unit["condition_grade"],
        condition_grade_after=None,
        gross_damage_cents=0,
        wear_allowance_cents=0,
        chargeable_cents=0,
        dispute_reason=None,
    )
    store.assessments[record["id"]] = record
    return created(S.assessment(record))


@bp.get("/damage-assessments/<assessment_id>")
def read_assessment(assessment_id):
    user_id, role = auth("DamageAssessor", "FleetAdmin", "Customer")
    record = lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    lease = store.leases.get(record["lease_id"])
    if lease is not None:
        require_customer_owner(user_id, role, lease["customer_id"])
    return success(S.assessment(record))


@bp.get("/damage-assessments")
def list_assessments():
    auth("DamageAssessor", "FleetAdmin")
    records = ordered(store.assessments.values())
    records = services.apply_filters(records, {
        "unit_id": "unit_id",
        "lease_id": "lease_id",
        "logistics_job_id": "logistics_job_id",
        "status": "status",
    })
    return paginate(records, S.assessment)


@bp.post("/damage-assessments/<assessment_id>/line-items")
def append_line_item(assessment_id):
    auth("DamageAssessor")
    assessment = lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    body = get_body()
    component = v_enum(body, "component", COMPONENTS)
    severity = v_enum(body, "severity", SEVERITIES)
    quantity = v_number(body, "quantity", exclusive_minimum=0)
    wear_and_tear = v_bool(body, "wear_and_tear")

    # rank 7 -- source state
    if assessment["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Line items may only be appended while DRAFT or DISPUTED.")

    record = new_append_only(
        damage_assessment_id=assessment_id,
        component=component,
        severity=severity,
        quantity=quantity,
        wear_and_tear=wear_and_tear,
        repair_cost_cents=calc.damage_line_repair_cost(component, severity, quantity),
    )
    store.line_items[record["id"]] = record
    return created(S.line_item(record))


@bp.get("/damage-assessments/<assessment_id>/line-items")
def list_line_items(assessment_id):
    auth("DamageAssessor", "FleetAdmin", "Customer")
    lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    records = services.line_items_of_assessment(assessment_id)
    return paginate(records, S.line_item)


@bp.post("/damage-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    auth("DamageAssessor")
    assessment = lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")

    # rank 7 -- source state
    if assessment["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or DISPUTED assessment may be submitted.")

    lines = services.line_items_of_assessment(assessment_id)
    assessment["gross_damage_cents"] = calc.damage_gross(lines)
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return success(S.assessment(assessment))


@bp.post("/damage-assessments/<assessment_id>/dispute")
def dispute_assessment(assessment_id):
    user_id, role = auth("Customer")
    assessment = lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    body = get_body()
    dispute_reason = v_string(body, "dispute_reason")

    # rank 6 -- resource ownership
    lease = store.leases[assessment["lease_id"]]
    require_customer_owner(user_id, role, lease["customer_id"])

    # rank 7 -- source state
    if assessment["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED assessment may be disputed.")

    # rank 19 -- dispute budget remaining
    if assessment["dispute_rounds"] >= calc.MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_LIMIT_REACHED", "The dispute budget for this assessment is spent.")

    assessment["status"] = "DISPUTED"
    assessment["dispute_rounds"] += 1
    assessment["dispute_reason"] = dispute_reason
    touch(assessment)
    return success(S.assessment(assessment))


@bp.post("/damage-assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    auth("FleetAdmin")
    assessment = lookup(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    body = get_body()
    condition_grade_after = v_enum(body, "condition_grade_after", GRADES)

    # rank 7 -- source state
    if assessment["status"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_NOT_SUBMITTED", "Only a SUBMITTED assessment may be finalized.")
    lease = store.leases[assessment["lease_id"]]
    if lease["occupancy_status"] != "VACATED":
        raise ApiError("ERR_INVALID_STATE", "The lease has not been vacated.")

    unit = store.units[assessment["unit_id"]]
    spec = store.building_specs[unit["building_spec_id"]]
    lines = services.line_items_of_assessment(assessment_id)
    start = calc.parse_iso_date(lease["start_date"])
    vacated = calc.parse_iso_date(lease["actual_vacated_date"])

    wear_allowance, chargeable = calc.damage_finalized_net(
        lines, assessment["gross_damage_cents"], start, vacated, spec["replacement_value_cents"])

    assessment["condition_grade_after"] = condition_grade_after
    assessment["wear_allowance_cents"] = wear_allowance
    assessment["chargeable_cents"] = chargeable
    assessment["status"] = "FINALIZED"
    touch(assessment)

    # cascade: ACCRUING -> SETTLED
    if lease["billing_status"] == "ACCRUING":
        permit_cents = 0
        for permit in services.permits_of_lease(lease["id"]):
            if permit["status"] == "APPROVED":
                permit_cents = permit["permit_fee_cents"]
                break
        final = calc.settled_actual(
            lease["monthly_base_rate_cents"],
            lease["monthly_accessory_rate_cents"],
            lease["term_months"],
            start,
            vacated,
            lease["mobilization_fee_cents"],
            permit_cents,
            lease["relocation_surcharge_cents"],
            chargeable,
        )
        lease["final_settlement_cents"] = final
        lease["billed_to_date_cents"] = final
        lease["billing_status"] = "SETTLED"
        touch(lease)

        customer = store.customers[lease["customer_id"]]
        services.recompute_customer(customer, demote_on_hold_flip=True)

    return success(S.assessment(assessment))
