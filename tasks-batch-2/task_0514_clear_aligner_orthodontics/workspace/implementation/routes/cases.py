"""TreatmentCase + IntakeRecord endpoints and case lifecycle transitions."""
import re

from flask import Blueprint, request

from clock import clock, format_iso8601_ms
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.calculations import MIN_USABLE_QUALITY
from services.case_service import (select_clinician, first_run_steps,
                                   refinement_steps)
from services.listing import paginate
from services.store import (get_case, fk_patient, steps_for_case,
                            checkins_for_case, financing_for_case)
from validation import (get_body, require_str, require_int, require_number,
                        require_enum, require_bool, optional_str, parse_pagination)

bp = Blueprint("cases", __name__)

_STATE_RE = re.compile(r"^[A-Z]{2}$")
CHANNELS = {"IMPRESSION_KIT", "IN_OFFICE_SCAN"}


# ───────────────────────── Cases ─────────────────────────
@bp.route("/cases", methods=["POST"])
def create_case():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    body = get_body()
    patient_id = require_str(body, "patient_id")
    intake_channel = require_enum(body, "intake_channel", CHANNELS)
    list_price_cents = require_int(body, "list_price_cents")
    if list_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "list_price_cents must be >= 0.")
    # FK existence
    fk_patient(patient_id)

    rec = base_record(common_fields=True)
    rec.update({
        "patient_id": patient_id,
        "intake_channel": intake_channel,
        "status": "INTAKE_PENDING",
        "assigned_clinician_id": None,
        "list_price_cents": list_price_cents,
        "total_contracted_cents": 0,
        "amount_collected_cents": 0,
        "refund_issued_cents": 0,
        "refinement_count": 0,
        "planned_step_count": 0,
        "guardian_consent": False,
    })
    db.cases[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/cases/<cid>", methods=["GET"])
def fetch_case(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    rec = get_case(cid)
    return object_response(serialize(rec), status=200)


@bp.route("/cases", methods=["GET"])
def list_cases():
    _, role = get_auth()
    require_roles(role, {"Clinician", "BillingAdmin", "ManufacturingOps"})
    limit, offset = parse_pagination()
    patient_id = request.args.get("patient_id")
    assigned_clinician_id = request.args.get("assigned_clinician_id")
    status = request.args.get("status")
    records = list(db.cases.values())
    if patient_id is not None:
        records = [c for c in records if c["patient_id"] == patient_id]
    if assigned_clinician_id is not None:
        records = [c for c in records
                   if c["assigned_clinician_id"] == assigned_clinician_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ─────────────────────── Intake records ───────────────────────
@bp.route("/cases/<cid>/intake-records", methods=["POST"])
def create_intake(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "ManufacturingOps"})
    case = get_case(cid)
    body = get_body()
    channel = require_enum(body, "channel", CHANNELS)
    quality_score = require_number(body, "quality_score")
    if quality_score < 0.0 or quality_score > 1.0:
        raise err("ERR_INVALID_REQUEST", "quality_score must be between 0.0 and 1.0.")
    kit_tracking_number = optional_str(body, "kit_tracking_number")
    scan_clinic_state_code = optional_str(body, "scan_clinic_state_code")

    # priority 7: channel must equal the parent case's intake_channel
    if channel != case["intake_channel"]:
        raise err("ERR_CHANNEL_MISMATCH",
                  "IntakeRecord.channel must equal the case's intake_channel.")
    # priority 8: channel-specific required field
    if channel == "IMPRESSION_KIT":
        if not kit_tracking_number:
            raise err("ERR_INTAKE_FIELDS_INCOMPLETE",
                      "kit_tracking_number is required for IMPRESSION_KIT.")
    else:  # IN_OFFICE_SCAN
        if not scan_clinic_state_code:
            raise err("ERR_INTAKE_FIELDS_INCOMPLETE",
                      "scan_clinic_state_code is required for IN_OFFICE_SCAN.")

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": cid,
        "channel": channel,
        "captured_at": format_iso8601_ms(clock.now()),
        "kit_tracking_number": kit_tracking_number,
        "scan_clinic_state_code": scan_clinic_state_code,
        "quality_score": quality_score,
    })
    db.intake_records[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/cases/<cid>/intake-records", methods=["GET"])
def list_intake(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    get_case(cid)
    limit, offset = parse_pagination()
    records = [r for r in db.intake_records.values() if r["case_id"] == cid]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ─────────────────────── Guardian consent ───────────────────────
@bp.route("/cases/<cid>/guardian-consent", methods=["POST"])
def guardian_consent(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    case = get_case(cid)
    body = get_body()
    consent = require_bool(body, "guardian_consent")
    case["guardian_consent"] = consent
    touch(case)
    return object_response(serialize(case), status=200)


# ─────────────────────── Submit for review ───────────────────────
@bp.route("/cases/<cid>/submit-for-review", methods=["POST"])
def submit_for_review(cid):
    _, role = get_auth()
    require_roles(role, {"Patient"})
    case = get_case(cid)
    # state precondition
    if case["status"] != "INTAKE_PENDING":
        raise err("ERR_INVALID_STATE",
                  "Case must be INTAKE_PENDING to submit for review.")
    # usability gate (priority 9)
    usable = any(
        r["case_id"] == cid
        and r["channel"] == case["intake_channel"]
        and r["quality_score"] >= MIN_USABLE_QUALITY
        for r in db.intake_records.values()
    )
    if not usable:
        raise err("ERR_INTAKE_NOT_USABLE",
                  "No usable intake record meets MIN_USABLE_QUALITY.")
    # clinician assignment
    patient = db.patients[case["patient_id"]]
    chosen = select_clinician(patient)
    if chosen is None:
        # leave case INTAKE_PENDING
        raise err("ERR_NO_ELIGIBLE_CLINICIAN",
                  "No active clinician licensed in the patient's state.")
    case["assigned_clinician_id"] = chosen["id"]
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return object_response(serialize(case), status=200)


# ─────────────────────── Activate ───────────────────────
@bp.route("/cases/<cid>/activate", methods=["POST"])
def activate_case(cid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    case = get_case(cid)
    if case["status"] != "PLAN_APPROVED":
        raise err("ERR_INVALID_STATE", "Case must be PLAN_APPROVED to activate.")
    # money side settled (priority 19)
    has_active_financing = any(
        f["billing_state"] == "ACTIVE" for f in financing_for_case(cid)
    )
    paid_in_full = case["amount_collected_cents"] >= case["total_contracted_cents"]
    if not (has_active_financing or paid_in_full):
        raise err("ERR_PAYMENT_NOT_SETTLED",
                  "Activation requires active financing or full payment.")
    # move step_index 1 PLANNED -> IN_PRODUCTION
    case["status"] = "ACTIVE"
    touch(case)
    step1 = _step_by_index(cid, 1)
    if step1 is not None and step1["status"] == "PLANNED":
        step1["status"] = "IN_PRODUCTION"
        touch(step1)
    return object_response(serialize(case), status=200)


# ─────────────────────── Resume ───────────────────────
@bp.route("/cases/<cid>/resume", methods=["POST"])
def resume_case(cid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    case = get_case(cid)
    if case["status"] != "REFINEMENT":
        raise err("ERR_INVALID_STATE", "Case must be REFINEMENT to resume.")
    ref_steps = refinement_steps(cid)
    # every refinement-generated step must be in {PLANNED, IN_PRODUCTION,
    # MANUFACTURED, SHIPPED} (i.e. not VOID).
    for s in ref_steps:
        if s["status"] not in ("PLANNED", "IN_PRODUCTION", "MANUFACTURED", "SHIPPED"):
            raise err("ERR_INVALID_STATE",
                      "All refinement steps must be active to resume.")
    case["status"] = "ACTIVE"
    touch(case)
    # move the lowest-step_index PLANNED refinement step to IN_PRODUCTION
    planned_ref = [s for s in ref_steps if s["status"] == "PLANNED"]
    if planned_ref:
        target = min(planned_ref, key=lambda s: s["step_index"])
        target["status"] = "IN_PRODUCTION"
        touch(target)
    return object_response(serialize(case), status=200)


# ─────────────────────── Complete ───────────────────────
@bp.route("/cases/<cid>/complete", methods=["POST"])
def complete_case(cid):
    _, role = get_auth()
    require_roles(role, {"Clinician"})
    case = get_case(cid)
    if case["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Case must be ACTIVE to complete.")
    steps = steps_for_case(cid)
    non_void = [s for s in steps if s["status"] != "VOID"]
    if not all(s["status"] == "SHIPPED" for s in non_void):
        raise err("ERR_VALIDATION", "All non-void steps must be SHIPPED to complete.")
    checkins = checkins_for_case(cid)
    if not checkins:
        raise err("ERR_VALIDATION", "A completing case requires a check-in.")
    latest = max(checkins, key=lambda c: (c["created_at"], c["_seq"]))
    if latest["tracking_assessment"] != "ON_TRACK":
        raise err("ERR_VALIDATION",
                  "Latest check-in must be ON_TRACK to complete.")
    case["status"] = "COMPLETED"
    touch(case)
    return object_response(serialize(case), status=200)


# ─────────────────────── Nested list endpoints ───────────────────────
@bp.route("/cases/<cid>/aligner-steps", methods=["GET"])
def list_case_steps(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    get_case(cid)
    limit, offset = parse_pagination()
    records = steps_for_case(cid)
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/cases/<cid>/checkins", methods=["GET"])
def list_case_checkins(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    get_case(cid)
    limit, offset = parse_pagination()
    records = checkins_for_case(cid)
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/cases/<cid>/refinements", methods=["GET"])
def list_case_refinements(cid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    get_case(cid)
    limit, offset = parse_pagination()
    records = [r for r in db.refinements.values() if r["case_id"] == cid]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ─────────────────────── helpers ───────────────────────
def _step_by_index(case_id, idx):
    for s in db.aligner_steps.values():
        if s["case_id"] == case_id and s["step_index"] == idx:
            return s
    return None
