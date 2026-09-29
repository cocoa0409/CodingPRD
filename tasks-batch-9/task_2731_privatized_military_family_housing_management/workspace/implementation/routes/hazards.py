"""Environmental hazard cases and displacement lodging (PRD 3.8)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, fmt_date, iso, now, now_iso, parse_date,
                period_of, sort_rows, today)
from errors import ApiError
from services import calc, core, lookup

bp = Blueprint("hazards", __name__)

REPORT_ROLES = (mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER, mw.ENVIRONMENTAL_SPECIALIST)
VOID_ROLES = (mw.PLATFORM_ADMIN, mw.INSTALLATION_HOUSING_OFFICE)
LODGING_WRITE_ROLES = (mw.PROPERTY_MANAGER, mw.ENVIRONMENTAL_SPECIALIST)
LODGING_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                      mw.ENVIRONMENTAL_SPECIALIST, mw.INSTALLATION_HOUSING_OFFICE)
HAZARD_TERMINAL = ("CLOSED", "VOIDED")
VOIDABLE = ("ASSESSED", "REMEDIATION_IN_PROGRESS", "DISPLACEMENT_ACTIVE",
            "CLEARANCE_PENDING")
LEAD_TYPES = ("LEAD_PAINT", "LEAD_WATER")


# ------------------------------------------------------------- report a hazard

@bp.post("/hazard-cases")
def report_case():
    user_id, role = mw.authenticate(REPORT_ROLES)
    body = mw.json_body()
    raw_lease = mw.raw_ref(body, "lease_id")
    if raw_lease is not None:
        mw.require_owner(role, user_id, mw.lease_sponsor(raw_lease))
    housing_unit_id = mw.v_id(body, "housing_unit_id")
    lease_id = mw.v_id(body, "lease_id", required=False, default=None)
    source_order_id = mw.v_id(body, "source_work_order_id", required=False, default=None)
    hazard_type = mw.v_enum(body, "hazard_type", mw.HAZARD_TYPES)
    symptoms = mw.v_str(body, "reported_symptoms")

    unit = lookup.housing_unit(housing_unit_id)
    lease = lookup.lease(lease_id) if lease_id is not None else None
    source = lookup.work_order(source_order_id) if source_order_id is not None else None

    if lease is not None:
        if lease["housing_unit_id"] != unit["id"] \
                or lease["occupancy_status"] == "TERMINATED":
            raise ApiError("ERR_LEASE_UNIT_MISMATCH")
    if source is not None and source["housing_unit_id"] != unit["id"]:
        raise ApiError("ERR_WORK_ORDER_UNIT_MISMATCH")

    row = base_row()
    row["housing_unit_id"] = unit["id"]
    row["lease_id"] = lease["id"] if lease else None
    row["source_work_order_id"] = source["id"] if source else None
    row["remediation_work_order_id"] = None
    row["hazard_type"] = hazard_type
    row["reported_symptoms"] = symptoms
    row["affected_area_sqft"] = None
    row["lead_level_ppm"] = None
    row["assessment_severity"] = None
    row["child_under_six_present"] = False
    row["displacement_required"] = False
    row["assessed_by_user_id"] = None
    row["assessed_at"] = None
    row["cleared_by_user_id"] = None
    row["clearance_test_passed"] = None
    row["status"] = "REPORTED"
    db.hazard_cases[row["id"]] = row
    return resp.created(row)


@bp.get("/hazard-cases/<case_id>")
def get_case(case_id):
    mw.authenticate(mw.ALL_ROLES)
    return resp.ok(lookup.hazard_case(case_id))


@bp.get("/hazard-cases")
def list_cases():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    housing_unit_id = mw.q_str("housing_unit_id")
    lease_id = mw.q_str("lease_id")
    source_order_id = mw.q_str("source_work_order_id")
    remediation_order_id = mw.q_str("remediation_work_order_id")
    hazard_type = mw.q_enum("hazard_type", mw.HAZARD_TYPES)
    status = mw.q_enum("status", mw.HAZARD_STATUSES)
    rows = sort_rows(list(db.hazard_cases.values()))
    if housing_unit_id is not None:
        rows = [r for r in rows if r["housing_unit_id"] == housing_unit_id]
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if source_order_id is not None:
        rows = [r for r in rows if r["source_work_order_id"] == source_order_id]
    if remediation_order_id is not None:
        rows = [r for r in rows if r["remediation_work_order_id"] == remediation_order_id]
    if hazard_type is not None:
        rows = [r for r in rows if r["hazard_type"] == hazard_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return resp.page(rows, limit, offset)


# ------------------------------------------------------------------- assessment

def _derive_child_under_six(case, reference_date):
    lease = db.leases.get(case["lease_id"]) if case.get("lease_id") else None
    if lease is None:
        return False
    for dependent in lookup.dependents_of(lease["service_member_id"]):
        if not dependent.get("is_full_time_custody"):
            continue
        age = calc.age_years(parse_date(dependent["date_of_birth"]), reference_date)
        if age < 6:
            return True
    return False


def _hold_reason(case):
    if case["assessment_severity"] == "SEVERITY_3":
        detail = "SEVERITY_3"
    else:
        detail = "SEVERITY_2 with a child under six"
    return "%s: %s" % (case["hazard_type"], detail)


@bp.post("/hazard-cases/<case_id>/assess")
def assess_case(case_id):
    user_id, _role = mw.authenticate((mw.ENVIRONMENTAL_SPECIALIST,))
    body = mw.json_body()
    area = mw.v_number(body, "affected_area_sqft", required=False, default=None, minimum=0)
    ppm = mw.v_number(body, "lead_level_ppm", required=False, default=None, minimum=0)
    mw.v_bool(body, "child_under_six_present")
    case = lookup.hazard_case(case_id)

    if case["hazard_type"] == "MOLD":
        if area is None:
            mw.bad("affected_area_sqft", "is required for a mold assessment")
        ppm = None
    else:
        if ppm is None:
            mw.bad("lead_level_ppm", "is required for a lead assessment")
        area = None

    if case["status"] in HAZARD_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if case["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    moment = now()
    child_present = _derive_child_under_six(case, moment.date())
    severity = calc.hazard_severity(case["hazard_type"], area, ppm)
    displacement = calc.displacement_required(severity, child_present)

    case["affected_area_sqft"] = area
    case["lead_level_ppm"] = ppm
    case["assessment_severity"] = severity
    case["child_under_six_present"] = child_present
    case["displacement_required"] = displacement
    case["assessed_by_user_id"] = user_id
    case["assessed_at"] = iso(moment)
    case["status"] = "ASSESSED"

    unit = lookup.housing_unit(case["housing_unit_id"])
    category = "MOLD_SUSPECTED" if case["hazard_type"] == "MOLD" else "LEAD_SUSPECTED"
    order = core.create_work_order(
        unit, case.get("lease_id"), None, category,
        "Hazard remediation for %s case %s" % (case["hazard_type"], case["id"]),
        displacement)
    case["remediation_work_order_id"] = order["id"]

    if not displacement:
        case["status"] = "REMEDIATION_IN_PROGRESS"
        bump(case)
        return resp.ok(case)

    case["status"] = "DISPLACEMENT_ACTIVE"
    bump(case)

    if unit["status"] == "OCCUPIED":
        unit["status"] = "HAZARD_HOLD"
        unit["hazard_hold_reason"] = _hold_reason(case)
        bump(unit)
        core.recount_for_unit(unit)

    assessment_date = moment.date()
    days = calc.abatement_days(assessment_date)
    for lease in lookup.leases_of_unit(unit["id"]):
        if lease["allotment_status"] != "ACTIVE":
            continue
        lease["allotment_status"] = "SUSPENDED"
        core.post_transaction(
            lease, "ABATEMENT", period_of(assessment_date),
            calc.abatement_amount(lease["daily_rent_cents"], days),
            "HAZARD_ABATEMENT:" + case["id"])
        bump(lease)
    return resp.ok(case)


# -------------------------------------------------------------------- clearance

@bp.post("/hazard-cases/<case_id>/clearance")
def certify_clearance(case_id):
    user_id, _role = mw.authenticate((mw.ENVIRONMENTAL_SPECIALIST,))
    body = mw.json_body()
    passed = mw.v_bool(body, "clearance_test_passed")
    case = lookup.hazard_case(case_id)

    if case["status"] in HAZARD_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    # Rung 19 outranks rung 26, so an undeclared edge is reported as a
    # transition error even when the case has also never been assessed.
    if case["status"] != "CLEARANCE_PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if case["status"] == "REPORTED":
        raise ApiError("ERR_HAZARD_NOT_ASSESSED")
    if case.get("assessed_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if passed:
        case["clearance_test_passed"] = True
        case["cleared_by_user_id"] = user_id
        case["status"] = "CLOSED"
        bump(case)
        core.release_hazard_hold(case)
        return resp.ok(case)

    case["clearance_test_passed"] = False
    case["cleared_by_user_id"] = None
    case["status"] = "REMEDIATION_IN_PROGRESS"
    unit = lookup.housing_unit(case["housing_unit_id"])
    category = "MOLD_SUSPECTED" if case["hazard_type"] == "MOLD" else "LEAD_SUSPECTED"
    follow_on = core.create_work_order(
        unit, case.get("lease_id"), case.get("remediation_work_order_id"), category,
        "Follow-on remediation after failed clearance for case %s" % case["id"],
        bool(case["displacement_required"]))
    case["remediation_work_order_id"] = follow_on["id"]
    bump(case)
    return resp.ok(case)


# ------------------------------------------------------------------------- void

@bp.post("/hazard-cases/<case_id>/void")
def void_case(case_id):
    mw.authenticate(VOID_ROLES)
    body = mw.json_body()
    mw.v_str(body, "void_reason")
    case = lookup.hazard_case(case_id)

    if case["status"] in HAZARD_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if case["status"] not in VOIDABLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    case["status"] = "VOIDED"
    bump(case)

    order = db.work_orders.get(case.get("remediation_work_order_id"))
    if order is not None and order["status"] != "CLOSED":
        order["status"] = "CLOSED"
        bump(order)

    core.close_authorized_lodgings(case, None, cascade_account=False)

    source_ref = "HAZARD_ABATEMENT:" + case["id"]
    unit = lookup.housing_unit(case["housing_unit_id"])
    for lease in lookup.leases_of_unit(unit["id"]):
        rows = [t for t in lookup.transactions_of(lease["id"])
                if t["type"] == "ABATEMENT" and t["source_ref"] == source_ref]
        if not rows:
            continue
        total = sum(int(t["amount_cents"]) for t in rows)
        if total != 0:
            core.post_transaction(lease, "ARREARS_ADJUSTMENT",
                                  rows[-1]["period_month"], abs(total), source_ref)
            bump(lease)

    core.release_hazard_hold(case, force=True)
    return resp.ok(case)


# ------------------------------------------------------------ displacement lodging

@bp.post("/displacement-lodgings")
def authorize_lodging():
    mw.authenticate(LODGING_WRITE_ROLES)
    body = mw.json_body()
    case_id = mw.v_id(body, "hazard_case_id")
    lease_id = mw.v_id(body, "lease_id")
    start_date = mw.v_date(body, "start_date")
    end_date = mw.v_date(body, "end_date")
    nightly = mw.v_int(body, "nightly_rate_cents", minimum=1)
    occupants = mw.v_int(body, "occupants_count", minimum=1)

    lease = lookup.lease(lease_id)
    case = lookup.hazard_case(case_id)

    if case["status"] == "REPORTED":
        raise ApiError("ERR_HAZARD_NOT_ASSESSED")
    if lease["housing_unit_id"] != case["housing_unit_id"] \
            or lease["occupancy_status"] == "TERMINATED":
        raise ApiError("ERR_LEASE_UNIT_MISMATCH")

    dependents = lookup.dependents_of(lease["service_member_id"])
    authorized_size = 2 + calc.full_time_dependent_count(dependents)
    if occupants > authorized_size:
        raise ApiError("ERR_OCCUPANTS_EXCEED_AUTHORIZED")

    for other in lookup.lodgings_of_lease(lease["id"]):
        if other["status"] not in ("AUTHORIZED", "CLOSED"):
            continue
        other_start = parse_date(other["start_date"])
        other_end = parse_date(other["end_date"])
        if start_date < other_end and other_start < end_date:
            raise ApiError("ERR_LODGING_INTERVAL_OVERLAP")

    row = base_row()
    row["hazard_case_id"] = case["id"]
    row["lease_id"] = lease["id"]
    row["start_date"] = fmt_date(start_date)
    row["end_date"] = fmt_date(end_date)
    row["nightly_rate_cents"] = nightly
    row["occupants_count"] = occupants
    row["actual_end_date"] = None
    row["nights_displaced"] = 0
    row["per_night_authorized_cents"] = 0
    row["lodging_authorized_cents"] = 0
    row["rent_abatement_cents"] = 0
    row["status"] = "AUTHORIZED"
    db.lodgings[row["id"]] = row
    return resp.created(row)


@bp.get("/displacement-lodgings/<lodging_id>")
def get_lodging(lodging_id):
    mw.authenticate(LODGING_READ_ROLES)
    return resp.ok(lookup.lodging(lodging_id))


@bp.get("/displacement-lodgings")
def list_lodgings():
    mw.authenticate(LODGING_READ_ROLES)
    limit, offset = mw.pagination()
    case_id = mw.q_str("hazard_case_id")
    lease_id = mw.q_str("lease_id")
    status = mw.q_enum("status", mw.LODGING_STATUSES)
    rows = sort_rows(list(db.lodgings.values()))
    if case_id is not None:
        rows = [r for r in rows if r["hazard_case_id"] == case_id]
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return resp.page(rows, limit, offset)


@bp.post("/displacement-lodgings/<lodging_id>/close")
def close_lodging(lodging_id):
    mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    actual_end_date = mw.v_date(body, "actual_end_date")
    lodging = lookup.lodging(lodging_id)

    if lodging["status"] == "CLOSED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if lodging["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if actual_end_date < parse_date(lodging["start_date"]):
        mw.bad("actual_end_date", "must not precede start_date")

    core.close_lodging(lodging, actual_end_date, cascade_account=True)
    return resp.ok(lodging)
