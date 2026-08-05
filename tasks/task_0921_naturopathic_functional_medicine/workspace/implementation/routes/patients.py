"""Patients, the gate view, scope-of-practice reviews and intake sections."""

from flask import Blueprint

import config
import ladder
from clock import clock
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.gate import open_red_flag_referral, recompute_gate
from services.intake import (
    expiry_instant,
    materialise_patient_intake,
    materialise_section,
    recompute_scores,
)

bp = Blueprint("patients", __name__)


# --------------------------------------------------------------------- patients


@bp.route("/patients", methods=["POST"])
def create_patient():
    def handler(ctx):
        row = make_row(
            full_name=ctx.body["full_name"],
            email=ctx.body["email"],
            state_code=ctx.body["state_code"],
            primary_practitioner_id=ctx.body["primary_practitioner_id"],
            telehealth_consent=bool(ctx.body.get("telehealth_consent", False)),
            medication_classes=ctx.body.get("medication_classes") or [],
            clinical_status="INTAKE",
            scope_review_status="NONE",
            scope_review_reason=None,
            scope_review_opened_by_user_id=None,
            intake_booking_score=0,
            intake_protocol_score=0,
            clinical_write_gate="OPEN",
            red_flag_referral_open=False,
            cash_charged_total_cents=0,
            cash_refunded_total_cents=0,
        )
        db.patients[row["id"]] = row
        return serializers.patient(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN, config.ROLE_ND],
            "body_fks": ["primary_practitioner_id"],
            "shape": [
                ("full_name", "string", True),
                ("email", "string", True),
                ("state_code", "string", True),
                ("primary_practitioner_id", "string", True),
                ("telehealth_consent", "bool", False),
                ("medication_classes", "array", False, {"of": "string"}),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    def handler(ctx):
        patient = ctx.path["patient"]
        materialise_patient_intake(patient)
        return serializers.patient(patient)

    return ladder.run(
        {
            "roles": list(config.ALL_ROLES),
            "path": [("patient", pid)],
            "owner": lambda ctx: ctx.path["patient"]["id"],
            "handler": handler,
        }
    )


@bp.route("/patients", methods=["GET"])
def list_patients():
    def handler(ctx):
        rows = ordered(db.patients.values())
        practitioner_id = ctx.args_get("primary_practitioner_id")
        clinical_status = ctx.args_get("clinical_status")
        if practitioner_id is not None:
            rows = [r for r in rows if r["primary_practitioner_id"] == practitioner_id]
        if clinical_status is not None:
            rows = [r for r in rows if r["clinical_status"] == clinical_status]
        for row in rows:
            materialise_patient_intake(row)
        return ladder.list_result(ctx, rows, serializers.patient)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_BILLING,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/patients/<pid>/gate", methods=["GET"])
def get_gate(pid):
    def handler(ctx):
        patient = ctx.path["patient"]
        materialise_patient_intake(patient)
        referral = open_red_flag_referral(patient["id"])
        return {
            "clinical_write_gate": patient["clinical_write_gate"],
            "scope_review_status": patient["scope_review_status"],
            "red_flag_referral_open": patient["red_flag_referral_open"],
            "open_red_flag_referral_id": referral["id"] if referral else None,
            "intake_booking_score": patient["intake_booking_score"],
            "intake_protocol_score": patient["intake_protocol_score"],
        }

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_DISPENSARY_TECH,
                config.ROLE_CLINICAL_DIRECTOR,
            ],
            "path": [("patient", pid)],
            "handler": handler,
        }
    )


# --------------------------------------------------------------- scope reviews


@bp.route("/patients/<pid>/scope-reviews", methods=["POST"])
def open_scope_review(pid):
    def own_state(ctx):
        if ctx.path["patient"]["scope_review_status"] not in (
            "NONE",
            "CLEARED",
            "RESTRICTED",
        ):
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        patient = ctx.path["patient"]
        patient["scope_review_status"] = "UNDER_REVIEW"
        patient["scope_review_reason"] = ctx.body["reason"]
        patient["scope_review_opened_by_user_id"] = ctx.user_id
        recompute_gate(patient)
        bump(patient)
        return serializers.patient(patient)

    return ladder.run(
        {
            "roles": [config.ROLE_CLINICAL_DIRECTOR],
            "path": [("patient", pid)],
            "own_state": own_state,
            "shape": [("reason", "string", True)],
            "handler": handler,
        }
    )


@bp.route("/patients/<pid>/scope-reviews/close", methods=["POST"])
def close_scope_review(pid):
    def segregation(ctx):
        if ctx.user_id == ctx.path["patient"]["primary_practitioner_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    def own_state(ctx):
        if ctx.path["patient"]["scope_review_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        patient = ctx.path["patient"]
        patient["scope_review_status"] = ctx.body["outcome"]
        recompute_gate(patient)
        bump(patient)
        return serializers.patient(patient)

    return ladder.run(
        {
            "roles": [config.ROLE_CLINICAL_DIRECTOR],
            "path": [("patient", pid)],
            "segregation": segregation,
            "own_state": own_state,
            "shape": [("outcome", "string", True), ("notes", "string", False)],
            "enums": {"outcome": config.SCOPE_REVIEW_CLOSE_OUTCOMES},
            "handler": handler,
        }
    )


# ------------------------------------------------------------- intake sections


@bp.route("/patients/<pid>/intake-sections", methods=["POST"])
def submit_intake_section(pid):
    def handler(ctx):
        patient = ctx.path["patient"]
        section_type = ctx.body["section_type"]
        existing = None
        for section in db.intake_sections.values():
            if (
                section["patient_id"] == patient["id"]
                and section["section_type"] == section_type
            ):
                existing = section
                break
        stamp = clock.stamp()
        if existing is not None:
            existing["payload_summary"] = ctx.body["payload_summary"]
            existing["status"] = "SUBMITTED"
            existing["submitted_at"] = stamp
            existing["attested_at"] = None
            existing["expires_at"] = None
            existing["weight"] = config.INTAKE_SECTION_WEIGHTS[section_type]
            bump(existing)
            row = existing
        else:
            row = make_row(
                patient_id=patient["id"],
                section_type=section_type,
                payload_summary=ctx.body["payload_summary"],
                status="SUBMITTED",
                weight=config.INTAKE_SECTION_WEIGHTS[section_type],
                submitted_at=stamp,
                attested_at=None,
                expires_at=None,
            )
            db.intake_sections[row["id"]] = row
        recompute_scores(patient)
        return serializers.intake_section(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT, config.ROLE_HEALTH_COACH],
            "path": [("patient", pid)],
            "owner": lambda ctx: ctx.path["patient"]["id"],
            "shape": [
                ("section_type", "string", True),
                ("payload_summary", "string", True),
            ],
            "enums": {"section_type": config.SECTION_TYPES},
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/patients/<pid>/intake-sections", methods=["GET"])
def list_intake_sections(pid):
    def handler(ctx):
        patient = ctx.path["patient"]
        materialise_patient_intake(patient)
        rows = ordered(
            [
                s
                for s in db.intake_sections.values()
                if s["patient_id"] == patient["id"]
            ]
        )
        status = ctx.args_get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return ladder.list_result(ctx, rows, serializers.intake_section)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_PATIENT,
            ],
            "path": [("patient", pid)],
            "owner": lambda ctx: ctx.path["patient"]["id"],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/intake-sections/<sid>/attest", methods=["POST"])
def attest_intake_section(sid):
    def own_state(ctx):
        materialise_section(ctx.path["intake_section"])
        if ctx.path["intake_section"]["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        section = ctx.path["intake_section"]
        patient = db.patients.get(section["patient_id"])
        section["status"] = "ATTESTED"
        section["attested_at"] = clock.stamp()
        section["expires_at"] = clock.render(expiry_instant(section["attested_at"]))
        bump(section)
        if patient is not None:
            recompute_scores(patient)
            bump(patient)
        return serializers.intake_section(section)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT],
            "path": [("intake_section", sid)],
            "owner": lambda ctx: ctx.path["intake_section"]["patient_id"],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )
