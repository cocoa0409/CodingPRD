"""Waste profiles, verification samples and the approval decision."""

from flask import Blueprint, g

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import (by_created_at, check_expected_version, check_generator_scope,
                           load, reference, respond_list, scope_filter_generator)
from services import calc, cascade, derive
from services.tracking import touch
from util import add_months, new_id

bp = Blueprint("waste_profiles", __name__)

ALL_READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "WasteApprovalChemist",
               "TreatmentOperator", "RegulatoryInspector", "Generator"]
SAMPLE_READERS = ["PlatformAdmin", "ComplianceManager", "WasteApprovalChemist", "RegulatoryInspector", "Generator"]
LINE_READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "RegulatoryInspector", "Generator"]

CREATE_SPEC = {
    "generator_id": {"type": "string", "required": True},
    "facility_id": {"type": "string", "required": True},
    "waste_codes": {"type": "array", "required": True, "non_empty": True,
                    "items": {"type": "string", "non_empty": True}},
    "physical_form": {"type": "string", "required": True, "enum": calc.PHYSICAL_FORMS},
    "compatibility_class": {"type": "string", "required": True, "enum": calc.COMPATIBILITY_CLASSES},
    "ldr_subcategory": {"type": "string", "required": True, "enum": calc.LDR_SUBCATEGORIES},
    "declared_constituent_ppm": {"type": "number", "required": True, "ge": 0},
    "declared_flash_point_c": {"type": "number", "required": True},
    "declared_ph": {"type": "number", "required": True, "ge": 0, "le": 14},
    "requested_treatment_method": {"type": "string", "required": True, "enum": calc.TREATMENT_METHODS},
    "recertification_months": {"type": "int", "ge": 1, "le": 24, "default": 12},
}


@bp.post("/tsdf/waste-profiles")
@endpoint(roles=["Generator", "ComplianceManager"], mutating=True)
def create_profile():
    raw = schema.raw_body()
    if isinstance(raw.get("generator_id"), str):
        check_generator_scope(raw["generator_id"])
    body = schema.validate(raw, CREATE_SPEC)
    gen = reference("generators", body["generator_id"])
    fac = reference("facilities", body["facility_id"])

    stamp = now()
    row = {
        "id": new_id(),
        "generator_id": gen["id"],
        "facility_id": fac["id"],
        "waste_codes": sorted(body["waste_codes"]),
        "physical_form": body["physical_form"],
        "compatibility_class": body["compatibility_class"],
        "ldr_subcategory": body["ldr_subcategory"],
        "declared_constituent_ppm": body["declared_constituent_ppm"],
        "declared_flash_point_c": body["declared_flash_point_c"],
        "declared_ph": body["declared_ph"],
        "requested_treatment_method": body["requested_treatment_method"],
        "recertification_months": body["recertification_months"],
        "status": "DRAFT",
        "required_sample_type": None,
        "sample_attempt_count": 0,
        "latest_sample_result": "NONE",
        "approved_treatment_method": None,
        "approved_at": None,
        "approved_by_user_id": None,
        "recertification_due_at": None,
        "suspension_reason_code": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("profiles", row)
    return created(derive.project_profile(row))


@bp.get("/tsdf/waste-profiles/<pid>")
@endpoint(roles=ALL_READERS)
def get_profile(pid):
    row = load("profiles", pid)
    check_generator_scope(row["generator_id"])
    return ok(derive.project_profile(row))


@bp.get("/tsdf/waste-profiles")
@endpoint(roles=ALL_READERS)
def list_profiles():
    filters, limit, offset = schema.listing(
        filters=["generator_id", "facility_id", "status", "required_sample_type"],
        enums={"status": calc.PROFILE_STATUSES, "required_sample_type": calc.SAMPLE_TYPES})
    generator_id = scope_filter_generator(filters)
    rows = by_created_at(list(db.profiles.values()))
    if generator_id is not None:
        rows = [p for p in rows if p["generator_id"] == generator_id]
    if "facility_id" in filters:
        rows = [p for p in rows if p["facility_id"] == filters["facility_id"]]
    if "status" in filters:
        rows = [p for p in rows if derive.profile_status(p) == filters["status"]]
    if "required_sample_type" in filters:
        rows = [p for p in rows if p["required_sample_type"] == filters["required_sample_type"]]
    return respond_list(rows, derive.project_profile, limit, offset)


def _recompute_required_sample_type(p):
    gen = derive.generator(p["generator_id"])
    rolling = derive.generator_scores(gen)[0] if gen is not None else 100
    return calc.required_sample_type(rolling, p["sample_attempt_count"])


@bp.post("/tsdf/waste-profiles/<pid>/submit")
@endpoint(roles=["Generator"], mutating=True)
def submit_profile(pid):
    body = schema.body({
        "revised_declared_constituent_ppm": {"type": "number", "ge": 0},
        "revised_declared_flash_point_c": {"type": "number"},
        "revised_declared_ph": {"type": "number", "ge": 0, "le": 14},
    })
    p = load("profiles", pid)
    check_generator_scope(p["generator_id"])

    status = derive.profile_status(p)
    if status not in ("DRAFT", "SAMPLE_FAILED", "EXPIRED"):
        fail("ERR_INVALID_STATE", "The profile cannot be submitted from its current status")

    if status == "DRAFT":
        gen = derive.generator(p["generator_id"])
        if gen is None or gen["status"] != "ACTIVE":
            fail("ERR_GENERATOR_SUSPENDED")
    elif status == "SAMPLE_FAILED":
        if p["sample_attempt_count"] > 2:
            fail("ERR_SAMPLE_LIMIT_EXCEEDED")

    for field in ("constituent_ppm", "flash_point_c", "ph"):
        supplied = body["revised_declared_" + field]
        if supplied is not None:
            p["declared_" + field] = supplied

    p["status"] = "SUBMITTED"
    p["required_sample_type"] = _recompute_required_sample_type(p)
    touch("profiles", p)
    return ok(derive.project_profile(p))


@bp.post("/tsdf/waste-profiles/<pid>/samples")
@endpoint(roles=["WasteApprovalChemist"], mutating=True)
def record_sample(pid):
    body = schema.body({
        "sample_type": {"type": "string", "required": True, "enum": calc.SAMPLE_TYPES},
        "measured_constituent_ppm": {"type": "number", "required": True, "ge": 0},
        "measured_flash_point_c": {"type": "number", "required": True},
        "measured_ph": {"type": "number", "required": True, "ge": 0, "le": 14},
        "expected_waste_profile_version": {"type": "int", "required": True},
    })
    p = load("profiles", pid)
    check_expected_version(p, body["expected_waste_profile_version"])

    if derive.profile_status(p) != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Samples may only be recorded against a submitted profile")
    if p["sample_attempt_count"] >= calc.MAX_SAMPLE_ATTEMPTS:
        fail("ERR_SAMPLE_LIMIT_EXCEEDED")

    # The tolerance band is chosen by the profile's required_sample_type, never by
    # the sample_type the chemist reports.
    applied = p["required_sample_type"] or body["sample_type"]
    deviation, result, reason = calc.evaluate_sample(
        applied, p["declared_constituent_ppm"], p["declared_flash_point_c"], p["declared_ph"],
        body["measured_constituent_ppm"], body["measured_flash_point_c"], body["measured_ph"])

    stamp = now()
    sample = {
        "id": new_id(),
        "waste_profile_id": p["id"],
        "sample_type": body["sample_type"],
        "measured_constituent_ppm": body["measured_constituent_ppm"],
        "measured_flash_point_c": body["measured_flash_point_c"],
        "measured_ph": body["measured_ph"],
        "recorded_by_user_id": g.user_id,
        "recorded_at": stamp,
        "applied_tolerance_type": applied,
        "constituent_deviation_pct": deviation,
        "result": result,
        "failure_reason_code": reason,
        "created_at": stamp,
    }
    insert("samples", sample)

    p["sample_attempt_count"] += 1
    p["latest_sample_result"] = result
    if result == "PASS":
        p["status"] = "SAMPLE_PASSED"
    elif p["sample_attempt_count"] >= calc.MAX_SAMPLE_ATTEMPTS:
        p["status"] = "REJECTED"
    else:
        p["status"] = "SAMPLE_FAILED"
        p["required_sample_type"] = "FULL"
    touch("profiles", p)
    return created(derive.project_sample(sample))


@bp.get("/tsdf/waste-profiles/<pid>/samples")
@endpoint(roles=SAMPLE_READERS)
def list_samples(pid):
    _, limit, offset = schema.listing(filters=[])
    p = load("profiles", pid)
    check_generator_scope(p["generator_id"])
    rows = by_created_at([s for s in db.samples.values() if s["waste_profile_id"] == pid])
    return respond_list(rows, derive.project_sample, limit, offset)


@bp.post("/tsdf/waste-profiles/<pid>/decision")
@endpoint(roles=["WasteApprovalChemist"], mutating=True)
def profile_decision(pid):
    body = schema.body({
        "decision": {"type": "string", "required": True, "enum": ["APPROVE", "REJECT"]},
        "approved_treatment_method": {"type": "string", "enum": calc.TREATMENT_METHODS},
        "reason_code": {"type": "string"},
    })
    if body["decision"] == "APPROVE" and body["approved_treatment_method"] is None:
        fail("ERR_INVALID_REQUEST", "approved_treatment_method is required to approve a profile")

    p = load("profiles", pid)
    status = derive.profile_status(p)

    if body["decision"] == "APPROVE":
        if status != "SAMPLE_PASSED":
            fail("ERR_INVALID_STATE", "Only a profile with a passed sample may be approved")
        gen = derive.generator(p["generator_id"])
        if gen is None or gen["status"] != "ACTIVE":
            fail("ERR_GENERATOR_SUSPENDED")
        samples = by_created_at([s for s in db.samples.values() if s["waste_profile_id"] == pid])
        if samples and samples[-1]["recorded_by_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")
        fac = derive.facility(p["facility_id"])
        if fac is None or body["approved_treatment_method"] not in fac["permitted_methods"]:
            fail("ERR_METHOD_NOT_PERMITTED")

        stamp = now()
        p["status"] = "APPROVED"
        p["approved_at"] = stamp
        p["approved_by_user_id"] = g.user_id
        p["approved_treatment_method"] = body["approved_treatment_method"]
        p["recertification_due_at"] = add_months(stamp, p["recertification_months"])
    else:
        if status not in ("SAMPLE_PASSED", "SAMPLE_FAILED"):
            fail("ERR_INVALID_STATE", "The profile cannot be rejected from its current status")
        p["status"] = "REJECTED"
        p["suspension_reason_code"] = body["reason_code"]

    touch("profiles", p)
    return ok(derive.project_profile(p))


@bp.post("/tsdf/waste-profiles/<pid>/status")
@endpoint(roles=["ComplianceManager"], mutating=True)
def set_profile_status(pid):
    body = schema.body({
        "to_status": {"type": "string", "required": True, "enum": ["APPROVED", "SUSPENDED"]},
        "reason_code": {"type": "string"},
    })
    p = load("profiles", pid)
    status = derive.profile_status(p)
    target = body["to_status"]

    if status == "APPROVED" and target == "SUSPENDED":
        p["status"] = "SUSPENDED"
        p["suspension_reason_code"] = body["reason_code"]
        cascade.profile_suspension_cascade(p)
    elif status == "SUSPENDED" and target == "APPROVED":
        p["status"] = "APPROVED"
        p["suspension_reason_code"] = None
        cascade.profile_reinstatement_cascade(p)
    else:
        fail("ERR_INVALID_STATE", "Unsupported waste profile status transition")

    touch("profiles", p)
    return ok(derive.project_profile(p))


@bp.get("/tsdf/waste-profiles/<pid>/manifest-lines")
@endpoint(roles=LINE_READERS)
def list_profile_lines(pid):
    filters, limit, offset = schema.listing(
        filters=["line_status"], enums={"line_status": calc.LINE_STATUSES})
    p = load("profiles", pid)
    check_generator_scope(p["generator_id"])
    rows = by_created_at([ln for ln in db.lines.values() if ln["waste_profile_id"] == pid])
    if "line_status" in filters:
        rows = [ln for ln in rows if ln["line_status"] == filters["line_status"]]
    return respond_list(rows, derive.project_line, limit, offset)
