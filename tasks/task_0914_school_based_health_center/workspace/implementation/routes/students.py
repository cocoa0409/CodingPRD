"""Student roster, sliding-fee profile, exemptions and guardians (PRD 3.2)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import calc, cascades, serialize

bp = Blueprint("students", __name__)


def _dob_before_today(op):
    born = clock.parse_date(op.body["date_of_birth"])
    if born >= clock.now_date():
        raise ApiError(
            "ERR_VALIDATION", "date_of_birth must be strictly before the current clock date."
        )


@bp.post("/sbhc/students")
def create_student():
    op = Op("POST /sbhc/students", ["Registrar"])
    op.schema(
        [
            Field("first_name", "string", required=True, min_len=1),
            Field("last_name", "string", required=True, min_len=1),
            Field("date_of_birth", "date", required=True),
        ]
    )
    op.custom(_dob_before_today)
    op.run()

    student = store.new_row(
        "students",
        {
            "first_name": op.body["first_name"],
            "last_name": op.body["last_name"],
            "date_of_birth": op.body["date_of_birth"],
            "household_income_annual_cents": 0,
            "household_size": 1,
            "payer_route": "SELF_PAY",
            "insurance_member_id": None,
            "fpl_percent": 0.00,
            "discount_tier": "TIER_A",
            "immunization_compliance_status": "NON_COMPLIANT",
            "immunization_exemption_type": "NONE",
            "valid_dose_count": 0,
            "invalid_dose_count": 0,
            "voided_dose_count": 0,
            "total_dose_count": 0,
        },
    )
    return envelope.created(serialize.dump(student))


@bp.get("/sbhc/students/<id>")
def read_student(id):
    op = Op(
        "GET /sbhc/students/{id}",
        ["Registrar", "Clinician", "CareCoordinator", "BillingSpecialist", "SbhcAdmin", "Student"],
    )
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("student")))


@bp.patch("/sbhc/students/<id>/financial-profile")
def financial_profile(id):
    op = Op("PATCH /sbhc/students/{id}/financial-profile", ["Registrar"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.schema(
        [
            Field("household_income_annual_cents", "integer", required=True, minimum=0),
            Field("household_size", "integer", required=True, minimum=1),
            Field("payer_route", "enum", required=True, values=config.PAYER_ROUTES),
            Field("insurance_member_id", "string"),
        ]
    )
    op.run()

    student = op.get("student")
    student["household_income_annual_cents"] = op.body["household_income_annual_cents"]
    student["household_size"] = op.body["household_size"]
    student["payer_route"] = op.body["payer_route"]
    if op.body["payer_route"] == "SELF_PAY":
        student["insurance_member_id"] = None
    else:
        student["insurance_member_id"] = op.field("insurance_member_id", None)

    percent, tier = calc.fpl_percent_and_tier(
        student["household_income_annual_cents"], student["household_size"]
    )
    student["fpl_percent"] = float(percent)
    student["discount_tier"] = tier
    store.touch(student)
    return envelope.ok(serialize.dump(student))


@bp.put("/sbhc/students/<id>/immunization-exemption")
def immunization_exemption(id):
    op = Op("PUT /sbhc/students/{id}/immunization-exemption", ["Registrar"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.schema([Field("exemption_type", "enum", required=True, values=config.EXEMPTION_TYPES)])
    op.run()

    student = op.get("student")
    student["immunization_exemption_type"] = op.body["exemption_type"]
    cascades.recompute_dose_counters(student)
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.ok(serialize.dump(student))


# --------------------------------------------------------------------------
# Guardians
# --------------------------------------------------------------------------
@bp.post("/sbhc/students/<id>/guardians")
def create_guardian(id):
    op = Op("POST /sbhc/students/{id}/guardians", ["Registrar"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.schema(
        [
            Field("full_name", "string", required=True, min_len=1),
            Field(
                "relationship", "enum", required=True, values=config.GUARDIAN_RELATIONSHIPS
            ),
            Field("contact_email", "string", required=True, min_len=1),
            Field("is_primary", "boolean"),
            Field("notification_opt_out", "boolean"),
        ]
    )
    op.run()

    guardian = store.new_row(
        "guardians",
        {
            "student_id": id,
            "full_name": op.body["full_name"],
            "relationship": op.body["relationship"],
            "contact_email": op.body["contact_email"],
            "is_primary": bool(op.field("is_primary", False)),
            "notification_opt_out": bool(op.field("notification_opt_out", False)),
        },
    )
    return envelope.created(serialize.dump(guardian))


@bp.get("/sbhc/students/<id>/guardians")
def list_guardians(id):
    op = Op("GET /sbhc/students/{id}/guardians", ["Registrar", "SbhcAdmin", "Clinician"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.paginated()
    op.run()

    rows = [g for g in store.DB["guardians"].values() if g["student_id"] == id]
    # PRD 3.2: the documented exception to created_at ordering — the selector order.
    rows.sort(key=lambda g: (0 if g["is_primary"] else 1, g["created_at"], g["_seq"]))
    return helpers.list_response(rows, op)


@bp.post("/sbhc/guardians/<id>/notification-preference")
def notification_preference(id):
    op = Op("POST /sbhc/guardians/{id}/notification-preference", ["Guardian", "Registrar"])
    op.path_id("guardian", "guardians", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema([Field("notification_opt_out", "boolean", required=True)])

    def _ownership(op):
        if op.role == "Guardian" and op.user_id != id:
            raise ApiError(
                "ERR_OWNERSHIP_VIOLATION",
                "A guardian may only change their own notification preference.",
            )

    op.hook(11, _ownership)
    op.run()

    guardian = op.get("guardian")
    guardian["notification_opt_out"] = op.body["notification_opt_out"]
    store.touch(guardian)
    return envelope.ok(serialize.dump(guardian))
