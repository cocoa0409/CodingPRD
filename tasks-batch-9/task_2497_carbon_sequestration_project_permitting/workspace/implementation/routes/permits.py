"""Injection well permit and injection period endpoints (PRD 3.6, 3.9)."""

from decimal import Decimal as D

from flask import Blueprint

import clock
import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("permits", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"
VERIFIER = "IndependentVerifier"


@bp.post("/ccs/injection-well-permits")
@mw.require(DEV)
def create_permit():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    geologic_model_id = mw.req_str(payload, "geologic_model_id")
    well_name = mw.req_str(payload, "well_name")
    casing_program = mw.req_enum(payload, "casing_program", enums.CASING_PROGRAM)
    corrosion_resistant = mw.req_bool(payload, "corrosion_resistant_material")
    tubing_packer = mw.opt_bool(payload, "tubing_packer_installed", default=False)
    requested_pressure = mw.req_num(payload, "requested_injection_pressure_psi", gt=0)

    project = lookup.project(project_id)
    model = lookup.model(geologic_model_id)
    if model["project_id"] != project["id"]:
        raise ApiError(
            "ERR_PROJECT_NOT_FOUND", "the geologic model does not belong to the given project"
        )

    derive.require_not_frozen(project)

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "geologic_model_id": model["id"],
            "well_name": well_name,
            "casing_program": casing_program,
            "corrosion_resistant_material": corrosion_resistant,
            "tubing_packer_installed": tubing_packer,
            "requested_injection_pressure_psi": requested_pressure,
            "max_injection_pressure_psi": calc.q2(D("0.90") * model["fracture_pressure_psi"]),
            "authorized_injection_rate_tpy": D("0"),
            "permit_status": "DRAFT",
            "construction_status": "NOT_STARTED",
            "last_mit_type": None,
            "last_mit_result": None,
            "last_mit_at": None,
            "mit_pass_count": 0,
            "technical_reviewer_user_id": None,
            "revision_round_count": 0,
            "activated_at": None,
        }
    )
    db.injection_well_permits[row["id"]] = row

    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.permit(row), 201)


@bp.get("/ccs/injection-well-permits")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_permits():
    project_id = mw.query_str("project_id")
    geologic_model_id = mw.query_str("geologic_model_id")
    permit_status = mw.query_enum("permit_status", enums.PERMIT_STATUS)
    rows = db.ordered(db.injection_well_permits.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if geologic_model_id is not None:
        rows = [r for r in rows if r["geologic_model_id"] == geologic_model_id]
    if permit_status is not None:
        rows = [r for r in rows if r["permit_status"] == permit_status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.permit(r) for r in page], limit, offset, total)


@bp.get("/ccs/injection-well-permits/<permit_id>")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def get_permit(permit_id):
    return response.object_response(serialize.permit(lookup.permit(permit_id)))


@bp.post("/ccs/injection-well-permits/<permit_id>/submit")
@mw.require(DEV)
def submit_permit(permit_id):
    payload = mw.body()
    mw.opt_str(payload, "submission_note")

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    if permit["permit_status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_PERMIT_STATE",
            "a permit may only be submitted from DRAFT or REVISION_REQUESTED",
        )

    # A resubmission from REVISION_REQUESTED carries no construction-standard or
    # pressure re-check (PRD 3.6).
    if permit["permit_status"] == "DRAFT":
        if permit["requested_injection_pressure_psi"] > permit["max_injection_pressure_psi"]:
            raise ApiError(
                "ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT",
                "requested injection pressure exceeds the 90-percent-of-fracture ceiling",
            )
        if (
            permit["casing_program"] != enums.COMPLIANT_CASING_PROGRAM
            or not permit["corrosion_resistant_material"]
            or not permit["tubing_packer_installed"]
        ):
            raise ApiError(
                "ERR_CASING_PROGRAM_NONCOMPLIANT",
                "the well's construction programme does not meet the Class VI standards",
            )

    if D(project["aor_radius_km"]) <= 0:
        raise ApiError("ERR_AOR_NOT_DELINEATED", "area of review has not been delineated")

    permit["revision_round_count"] = permit["revision_round_count"] + 1
    permit["permit_status"] = "SUBMITTED"
    db.touch(permit)
    return response.object_response(serialize.permit(permit))


@bp.post("/ccs/injection-well-permits/<permit_id>/review")
@mw.require(REVIEWER)
def review_permit(permit_id):
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", enums.PERMIT_REVIEW_DECISION)
    mw.opt_str(payload, "review_note")

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    if decision == "BEGIN_TECHNICAL_REVIEW":
        if permit["permit_status"] != "SUBMITTED":
            raise ApiError(
                "ERR_INVALID_PERMIT_STATE", "technical review may only be opened from SUBMITTED"
            )
        model = db.geologic_models.get(permit["geologic_model_id"])
        if model is None or model["status"] != "ACCEPTED":
            raise ApiError(
                "ERR_INVALID_MODEL_STATE", "the referenced geologic model is not ACCEPTED"
            )
        if model["seal_classification"] == "FAIL":
            raise ApiError(
                "ERR_SEAL_INTEGRITY_FAIL", "the referenced geologic model's seal classification is FAIL"
            )
        permit["technical_reviewer_user_id"] = mw.caller_id()
        permit["permit_status"] = "TECHNICAL_REVIEW"
        db.touch(permit)
        return response.object_response(serialize.permit(permit))

    if permit["permit_status"] != "TECHNICAL_REVIEW":
        raise ApiError(
            "ERR_INVALID_PERMIT_STATE", "this decision is only admissible from TECHNICAL_REVIEW"
        )

    if decision == "REQUEST_REVISION":
        permit["permit_status"] = "REVISION_REQUESTED"
        db.touch(permit)
        return response.object_response(serialize.permit(permit))

    if decision == "APPROVE":
        if project["corrective_action_completion_pct"] != D("100.00"):
            raise ApiError(
                "ERR_CORRECTIVE_ACTION_INCOMPLETE",
                "corrective action completion percentage is below 100",
            )
        permit["permit_status"] = "APPROVED"
    else:
        permit["permit_status"] = "DENIED"

    db.touch(permit)
    derive.recompute_required_assurance(project)
    db.touch(project)
    return response.object_response(serialize.permit(permit))


@bp.post("/ccs/injection-well-permits/<permit_id>/advance-construction")
@mw.require(DEV)
def advance_construction(permit_id):
    payload = mw.body()
    target = mw.req_enum(payload, "to_construction_status", enums.CONSTRUCTION_STATUS)

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    if target == "DRILLING" and permit["permit_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "drilling requires an APPROVED permit")

    if target != enums.CONSTRUCTION_SUCCESSOR.get(permit["construction_status"]):
        raise ApiError(
            "ERR_INVALID_CONSTRUCTION_SEQUENCE",
            "only the immediate successor of the current construction status is accepted",
        )

    if target == "COMPLETED" and permit["last_mit_result"] != "PASS":
        raise ApiError("ERR_MIT_NOT_PASSED", "the permit has no passing mechanical integrity test")

    permit["construction_status"] = target
    db.touch(permit)
    return response.object_response(serialize.permit(permit))


@bp.post("/ccs/injection-well-permits/<permit_id>/record-mit")
@mw.require(DEV)
def record_mit(permit_id):
    payload = mw.body()
    test_type = mw.req_enum(payload, "test_type", enums.MIT_TEST_TYPE)
    annulus_loss = None
    anomaly_detected = None
    if test_type == "ANNULUS_PRESSURE":
        annulus_loss = calc.q2(mw.req_num(payload, "annulus_pressure_loss_psi"))
    else:
        anomaly_detected = mw.req_bool(payload, "anomaly_detected")

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    verdict = calc.mit_verdict(test_type, annulus_loss, anomaly_detected)
    permit["last_mit_type"] = test_type
    permit["last_mit_result"] = verdict
    permit["last_mit_at"] = clock.now_iso()
    if verdict == "PASS":
        permit["mit_pass_count"] = permit["mit_pass_count"] + 1
    db.touch(permit)
    return response.object_response(serialize.permit(permit))


@bp.post("/ccs/injection-well-permits/<permit_id>/activate")
@mw.require(REVIEWER)
def activate_permit(permit_id):
    payload = mw.body()
    mw.opt_str(payload, "activation_note")

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    if permit["permit_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "only an APPROVED permit may be activated")
    if permit["construction_status"] != "COMPLETED":
        raise ApiError(
            "ERR_INVALID_CONSTRUCTION_SEQUENCE", "construction status must already be COMPLETED"
        )
    if permit["last_mit_result"] != "PASS":
        raise ApiError("ERR_MIT_NOT_PASSED", "the permit has no passing mechanical integrity test")
    if project["status"] not in ("INJECTION_AUTHORIZED", "INJECTION_ACTIVE"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "the project must be INJECTION_AUTHORIZED or INJECTION_ACTIVE",
        )
    if project["assurance_coverage_status"] != "FUNDED":
        raise ApiError("ERR_ASSURANCE_INSUFFICIENT", "financial assurance is not fully funded")

    permit["authorized_injection_rate_tpy"] = derive.effective_rate(project)
    permit["activated_at"] = clock.now_iso()
    permit["permit_status"] = "ACTIVE"
    db.touch(permit)

    if project["status"] == "INJECTION_AUTHORIZED":
        project["status"] = "INJECTION_ACTIVE"
        db.touch(project)

    return response.object_response(serialize.permit(permit))


# --------------------------------------------------------------------------- #
# Injection period records
# --------------------------------------------------------------------------- #


@bp.post("/ccs/injection-well-permits/<permit_id>/injection-periods")
@mw.require(DEV)
def create_injection_period(permit_id):
    payload = mw.body()
    period_start = mw.req_ts(payload, "period_start")
    period_end = mw.req_ts(payload, "period_end")
    start_dt = clock.must_parse(period_start, "period_start")
    end_dt = clock.must_parse(period_end, "period_end")
    if not end_dt > start_dt:
        raise ApiError("ERR_INVALID_REQUEST", "period_end must be strictly later than period_start")
    mass = mw.req_num(payload, "mass_injected_tonnes", ge=0)
    leakage = mw.opt_num(payload, "measured_leakage_tonnes", default=D("0"), ge=0, le=mass)

    permit = lookup.permit(permit_id)
    project = db.project_of_permit(permit)
    derive.require_not_frozen(project)

    if permit["permit_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "the well's permit is not ACTIVE")

    for existing in db.periods_of_permit(permit["id"]):
        if existing["status"] != "ACCEPTED":
            continue
        if start_dt < existing["period_end_dt"] and existing["period_start_dt"] < end_dt:
            raise ApiError(
                "ERR_INJECTION_PERIOD_OVERLAP",
                "the requested interval overlaps an accepted period of this well",
            )

    row = db.base_fields(with_version=False)
    row.update(
        {
            "permit_id": permit["id"],
            "period_start": period_start,
            "period_end": period_end,
            "period_start_dt": start_dt,
            "period_end_dt": end_dt,
            "mass_injected_tonnes": mass,
            "measured_leakage_tonnes": leakage,
            "net_stored_tonnes": calc.net_stored(mass, leakage),
            "status": "ACCEPTED",
            "voided_at": None,
        }
    )
    db.injection_periods[row["id"]] = row

    derive.recompute_ledger(project)
    db.touch(project)

    return response.object_response(serialize.period(row), 201)


@bp.get("/ccs/injection-well-permits/<permit_id>/injection-periods")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_injection_periods(permit_id):
    status = mw.query_enum("status", enums.PERIOD_STATUS)
    permit = lookup.permit(permit_id)
    rows = db.periods_of_permit(permit["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.period(r) for r in page], limit, offset, total)


@bp.post("/ccs/injection-periods/<period_id>/void")
@mw.require(DEV)
def void_injection_period(period_id):
    payload = mw.body()
    mw.req_str(payload, "void_reason")

    record = lookup.period(period_id)
    project = db.project_of_period(record)
    derive.require_not_frozen(project)

    if record["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "only an ACCEPTED period may be voided")

    for claim in db.claims_of(project["id"]):
        if claim["status"] == "ALLOWED" and derive.record_in_tax_year(record, claim["tax_year"]):
            raise ApiError(
                "ERR_INVALID_CLAIM_STATE",
                "an allowed credit covers this period's tax year",
            )

    record["status"] = "VOIDED"
    record["voided_at"] = clock.now_iso()

    derive.recompute_ledger(project)

    for claim in db.claims_of(project["id"]):
        if claim["status"] in ("DRAFT", "SUBMITTED") and derive.record_in_tax_year(
            record, claim["tax_year"]
        ):
            if derive.recompute_claim(claim, project):
                db.touch(claim)

    derive.recompute_pending_credit(project)
    db.touch(project)

    return response.object_response(serialize.period(record))
