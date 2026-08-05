"""The encounter and its two parallel state axes (PRD 3.5)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import billing, cascades, serialize
from services.notifications import raise_notification

bp = Blueprint("visits", __name__)


@bp.post("/sbhc/visits")
def create_visit():
    op = Op("POST /sbhc/visits", ["Clinician"])
    # Rung 5 resolves body identifiers in the order PRD 2.6 names them.
    op.body_id("school", "schools", "school_id", "ERR_SCHOOL_NOT_FOUND")
    op.body_id("clinician", "clinicians", "clinician_id", "ERR_CLINICIAN_NOT_FOUND")
    op.body_id("student", "students", "student_id", "ERR_STUDENT_NOT_FOUND")
    op.schema(
        [
            Field("student_id", "string", required=True),
            Field("school_id", "string", required=True),
            Field("clinician_id", "string", required=True),
            Field("visit_type", "enum", required=True, values=config.VISIT_TYPES),
            Field("scheduled_start_at", "datetime", required=True),
            Field("delivery_mode", "enum", values=config.DELIVERY_MODES),
            Field("confidential_service_requested", "boolean"),
        ]
    )

    def _site_posture(op):
        if op.get("school")["program_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_SUSPENDED", "The site's program is suspended.")

    def _enrollment(op):
        enrollment = helpers.active_enrollment(
            op.body["student_id"], op.body["school_id"], clock.current_school_year()
        )
        if enrollment is None:
            raise ApiError(
                "ERR_ENROLLMENT_NOT_ACTIVE",
                "The student holds no ACTIVE enrollment at this site for the current school year.",
            )
        op.rows["enrollment"] = enrollment

    def _consent(op):
        category = helpers.required_consent_category(
            op.body["visit_type"], bool(op.field("confidential_service_requested", False))
        )
        consent = helpers.find_usable_consent(op.body["student_id"], category)
        if consent is None:
            raise ApiError(
                "ERR_CONSENT_REQUIRED",
                "No ACTIVE unexpired %s consent is on file." % category,
            )
        op.rows["consent"] = consent

    def _telehealth_consent(op):
        if op.field("delivery_mode", "IN_PERSON") != "TELEHEALTH":
            return
        if helpers.find_usable_consent(op.body["student_id"], "TELEHEALTH") is None:
            raise ApiError(
                "ERR_TELEHEALTH_CONSENT_REQUIRED",
                "No ACTIVE unexpired TELEHEALTH consent is on file.",
            )

    def _discipline(op):
        wanted = config.VISIT_TYPE_TO_CLINICIAN_DISCIPLINE[op.body["visit_type"]]
        if op.get("clinician")["discipline"] != wanted:
            raise ApiError(
                "ERR_DISCIPLINE_MISMATCH",
                "This visit type requires a %s clinician." % wanted,
            )

    op.hook(14, _site_posture)
    op.hook(15, _enrollment)
    op.hook(18, _consent)
    op.hook(19, _telehealth_consent)
    op.hook(20, _discipline)
    op.run()

    consent = op.get("consent")
    visit = store.new_row(
        "visits",
        {
            "student_id": op.body["student_id"],
            "school_id": op.body["school_id"],
            "clinician_id": op.body["clinician_id"],
            "enrollment_id": op.get("enrollment")["id"],
            "consent_id": consent["id"],
            "visit_type": op.body["visit_type"],
            "delivery_mode": op.field("delivery_mode", "IN_PERSON"),
            "confidential_service_requested": bool(
                op.field("confidential_service_requested", False)
            ),
            "confidential": consent["granted_by"] == "STUDENT_SELF",
            "scheduled_start_at": op.body["scheduled_start_at"],
            "completed_at": None,
            "disposition": None,
            "clinical_status": "SCHEDULED",
            "billing_status": "NOT_APPLICABLE",
            "gross_charge_total_cents": 0,
            "no_charge_total_cents": 0,
            "patient_responsibility_total_cents": 0,
            "write_off_total_cents": 0,
            "payer_billed_total_cents": 0,
        },
    )
    return envelope.created(serialize.dump(visit))


@bp.get("/sbhc/visits/<id>")
def read_visit(id):
    op = Op(
        "GET /sbhc/visits/{id}",
        ["Clinician", "Registrar", "BillingSpecialist", "SbhcAdmin", "CareCoordinator"],
    )
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("visit")))


@bp.get("/sbhc/visits")
def list_visits():
    op = Op(
        "GET /sbhc/visits", ["Clinician", "Registrar", "BillingSpecialist", "SbhcAdmin"]
    )
    op.paginated()
    op.run()
    rows = store.all_rows("visits")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "school_id": "school_id",
            "clinician_id": "clinician_id",
            "enrollment_id": "enrollment_id",
            "consent_id": "consent_id",
            "clinical_status": "clinical_status",
            "billing_status": "billing_status",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/visits/<id>/start")
def start_visit(id):
    op = Op("POST /sbhc/visits/{id}/start", ["Clinician"])
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")

    def _state(op):
        if op.get("visit")["clinical_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED encounter may be started.")

    def _site_posture(op):
        school = store.get("schools", op.get("visit")["school_id"])
        if school is not None and school["program_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_SUSPENDED", "The site's program is suspended.")

    def _consent(op):
        consent = store.get("consents", op.get("visit")["consent_id"])
        if consent is None or not helpers.consent_is_usable(consent):
            raise ApiError(
                "ERR_CONSENT_REQUIRED",
                "The governing consent is no longer ACTIVE and unexpired.",
            )

    op.hook(17, _state)
    op.hook(17.5, _site_posture)
    op.hook(18, _consent)
    op.run()

    visit = op.get("visit")
    visit["clinical_status"] = "IN_PROGRESS"
    store.touch(visit)
    return envelope.ok(serialize.dump(visit))


@bp.post("/sbhc/visits/<id>/complete")
def complete_visit(id):
    op = Op("POST /sbhc/visits/{id}/complete", ["Clinician"])
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")
    op.schema([Field("disposition", "enum", required=True, values=config.DISPOSITIONS)])

    def _state(op):
        visit = op.get("visit")
        if visit["clinical_status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS encounter may be completed.")
        if visit["delivery_mode"] == "TELEHEALTH":
            done = cascades.sessions_of_visit(visit["id"], ("COMPLETED",))
            if not done:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A telehealth encounter needs a COMPLETED session behind it.",
                )

    op.hook(17, _state)
    op.run()

    visit = op.get("visit")
    student = store.get("students", visit["student_id"])
    visit["clinical_status"] = "COMPLETED"
    visit["completed_at"] = clock.now_iso()
    visit["disposition"] = op.body["disposition"]

    billing.mint_charges_for_visit(visit, student)
    billing.settle_visit(visit, student, rerun_floor=True)
    raise_notification("VISIT_COMPLETED", visit["student_id"], visit)
    return envelope.ok(serialize.dump(visit))


@bp.post("/sbhc/visits/<id>/close-unfulfilled")
def close_unfulfilled(id):
    op = Op("POST /sbhc/visits/{id}/close-unfulfilled", ["Clinician"])
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")
    op.schema(
        [
            Field(
                "outcome", "enum", required=True, values=config.CLOSE_UNFULFILLED_OUTCOMES
            )
        ]
    )

    def _state(op):
        visit = op.get("visit")
        outcome = op.body["outcome"]
        if outcome == "CANCELLED":
            if visit["clinical_status"] not in ("SCHEDULED", "IN_PROGRESS"):
                raise ApiError("ERR_INVALID_STATE", "This encounter cannot be cancelled.")
        else:
            if visit["clinical_status"] != "SCHEDULED":
                raise ApiError(
                    "ERR_INVALID_STATE", "Only a SCHEDULED encounter may be a no-show."
                )

    def _grace(op):
        if op.body["outcome"] != "NO_SHOW":
            return
        visit = op.get("visit")
        earliest = clock.add_minutes(
            clock.parse_datetime(visit["scheduled_start_at"]), config.NO_SHOW_GRACE_MINUTES
        )
        if clock.now_dt() < earliest:
            raise ApiError(
                "ERR_NO_SHOW_TOO_EARLY",
                "The 10-minute no-show grace has not elapsed.",
            )

    op.hook(17, _state)
    op.hook(25, _grace)
    op.run()

    visit = op.get("visit")
    outcome = op.body["outcome"]
    visit["clinical_status"] = outcome
    store.touch(visit)
    cascades.cancel_sessions_for_visit(visit, "CANCELLED" if outcome == "CANCELLED" else "NO_SHOW")
    return envelope.ok(serialize.dump(visit))
