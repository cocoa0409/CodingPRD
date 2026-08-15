"""EmployeeSnapshot endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SNAPSHOT_LOCKED,
    ERR_DUPLICATE_EMPLOYEE_REF,
    ERR_GROUP_INVALID_STATE,
    ERR_CROSS_STUDY_REFERENCE,
    ERR_GROUP_CRITERIA_MISMATCH,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compute_annualized_base_cents, compute_tenure_years
from services.core import new_record, touch, recompute_study_aggregates, recompute_member_count
from util import D
from validate import (
    get_body, req_str, req_int, req_date, req_enum, require_path_resource,
    require_fk,
)

bp = Blueprint("snapshots", __name__)

GENDER_CLASSES = {"MALE", "FEMALE", "NONBINARY"}
ETHNICITY_CLASSES = {"WHITE", "BLACK", "HISPANIC", "ASIAN", "OTHER"}
AGE_BANDS = {"UNDER_40", "FORTY_PLUS"}

COMP_FIELDS = ("base_salary_cents", "bonus_cents", "fte_factor", "job_level")


def _validate_fte(body, field="fte_factor"):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if D(v) <= 0 or D(v) > 1:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must satisfy 0 < fte <= 1.0")
    return v


def _check_criteria(snapshot, group):
    """Snapshot must satisfy the group's membership criteria (PRD §3.2)."""
    if (snapshot["job_family"] != group["job_family"]
            or snapshot["location_code"] != group["location_code"]
            or not (group["min_job_level"] <= snapshot["job_level"] <= group["max_job_level"])):
        raise_error(ERR_GROUP_CRITERIA_MISMATCH,
                    "snapshot does not satisfy the group's membership criteria")


@bp.post("/employee-snapshots")
def create_snapshot():
    authorized(["PeopleOpsAdmin"])
    body = get_body()
    # Priority 3.7: shape (string fields) — needed to resolve FKs
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence
    study = require_fk("pay_equity_studies", study_id, "study_id")
    # Priority 3.7: remaining shape
    employee_ref = req_str(body, "employee_ref")
    gender_class = req_enum(body, "gender_class", GENDER_CLASSES)
    ethnicity_class = req_enum(body, "ethnicity_class", ETHNICITY_CLASSES)
    age_band = req_enum(body, "age_band", AGE_BANDS)
    job_family = req_str(body, "job_family")
    job_level = req_int(body, "job_level", minimum=1, maximum=10)
    location_code = req_str(body, "location_code")
    fte_factor = _validate_fte(body)
    base_salary_cents = req_int(body, "base_salary_cents", minimum=0)
    bonus_cents = req_int(body, "bonus_cents", minimum=0)
    hire_date = req_date(body, "hire_date")
    # Priority 4: state — intake closes when the study leaves DRAFT
    if study["status"] != "DRAFT":
        raise_error(ERR_SNAPSHOT_LOCKED,
                    "snapshot creation requires the parent study to be DRAFT")
    # Priority 7: uniqueness of employee_ref within the study
    for s in db["employee_snapshots"].values():
        if s["study_id"] == study_id and s["employee_ref"] == employee_ref:
            raise_error(ERR_DUPLICATE_EMPLOYEE_REF,
                        f"employee_ref already exists within the study: {employee_ref}")

    rec = new_record("employee_snapshots", {
        "study_id": study_id,
        "employee_ref": employee_ref,
        "gender_class": gender_class,
        "ethnicity_class": ethnicity_class,
        "age_band": age_band,
        "job_family": job_family,
        "job_level": job_level,
        "location_code": location_code,
        "fte_factor": fte_factor,
        "base_salary_cents": base_salary_cents,
        "bonus_cents": bonus_cents,
        "hire_date": hire_date,
        "comparator_group_id": None,
        "annualized_base_cents": compute_annualized_base_cents(base_salary_cents, fte_factor),
        "tenure_years": compute_tenure_years(study["analysis_period_end"], hire_date),
    })
    recompute_study_aggregates(study_id)
    return success_object(public(rec), status=201)


@bp.get("/employee-snapshots")
def list_snapshots():
    return list_response("employee_snapshots", {
        "study_id": request.args.get("study_id"),
        "comparator_group_id": request.args.get("comparator_group_id"),
    })


@bp.get("/employee-snapshots/<rid>")
def get_snapshot(rid):
    return get_one("employee_snapshots", rid)


@bp.patch("/employee-snapshots/<rid>")
def patch_snapshot(rid):
    authorized(["PeopleOpsAdmin"])
    # Priority 3: path existence
    snapshot = require_path_resource("employee_snapshots", rid)
    body = get_body()

    # Priority 3: body FK existence (left-to-right) when a non-null
    # comparator_group_id is supplied.
    target_group = None
    group_field_present = "comparator_group_id" in body
    new_group_id = body.get("comparator_group_id")
    if group_field_present and new_group_id is not None:
        if not isinstance(new_group_id, str):
            raise_error(ERR_INVALID_REQUEST, "invalid field: comparator_group_id")
        target_group = require_fk("comparator_groups", new_group_id, "comparator_group_id")

    # Priority 3.7: shape of provided fields
    if "base_salary_cents" in body and body["base_salary_cents"] is not None:
        req_int(body, "base_salary_cents", minimum=0)
    if "bonus_cents" in body and body["bonus_cents"] is not None:
        req_int(body, "bonus_cents", minimum=0)
    if "fte_factor" in body and body["fte_factor"] is not None:
        _validate_fte(body)
    if "job_level" in body and body["job_level"] is not None:
        req_int(body, "job_level", minimum=1, maximum=10)

    study = db["pay_equity_studies"].get(snapshot["study_id"])
    comp_touched = any(
        f in body and body[f] is not None and body[f] != snapshot[f]
        for f in COMP_FIELDS
    )

    # Priority 4: state — compensation-field edits require a DRAFT study
    if comp_touched and study["status"] != "DRAFT":
        raise_error(ERR_SNAPSHOT_LOCKED,
                    "compensation-field edits require the parent study to be DRAFT")

    # Group membership change validations
    membership_change = False
    if group_field_present and new_group_id != snapshot.get("comparator_group_id"):
        membership_change = True
        old_group_id = snapshot.get("comparator_group_id")
        # Priority 4: cannot leave a LOCKED/ANALYZED group; target must be DRAFT
        if old_group_id is not None:
            old_group = db["comparator_groups"].get(old_group_id)
            if old_group is not None and old_group["status"] != "DRAFT":
                raise_error(ERR_GROUP_INVALID_STATE,
                            "cannot unassign from a LOCKED/ANALYZED group")
        if target_group is not None:
            if target_group["status"] != "DRAFT":
                raise_error(ERR_GROUP_INVALID_STATE,
                            "cannot assign to a LOCKED/ANALYZED group")
            # Priority 7: referential consistency, then membership criteria
            if target_group["study_id"] != snapshot["study_id"]:
                raise_error(ERR_CROSS_STUDY_REFERENCE,
                            "comparator group belongs to a different study")

    # Apply compensation-field updates
    if comp_touched:
        for f in COMP_FIELDS:
            if f in body and body[f] is not None:
                snapshot[f] = body[f]
        snapshot["annualized_base_cents"] = compute_annualized_base_cents(
            snapshot["base_salary_cents"], snapshot["fte_factor"])

    # Criteria check uses the (possibly updated) snapshot field values
    if membership_change and target_group is not None:
        _check_criteria(snapshot, target_group)

    if membership_change:
        old_group_id = snapshot.get("comparator_group_id")
        snapshot["comparator_group_id"] = new_group_id

    if comp_touched or membership_change:
        touch(snapshot)

    if membership_change:
        # Recompute member_count of affected groups and bump their versions
        if old_group_id is not None:
            recompute_member_count(old_group_id)
        if new_group_id is not None:
            recompute_member_count(new_group_id)
        recompute_study_aggregates(snapshot["study_id"])

    return success_object(public(snapshot))
