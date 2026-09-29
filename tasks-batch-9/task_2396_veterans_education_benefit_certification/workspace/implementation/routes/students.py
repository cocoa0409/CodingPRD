"""VeteranStudent and StudentAccountCharge endpoints."""

from calc import is_protected
from common import (
    ListQuery,
    ROLE_BURSAR,
    ROLE_SCO,
    ROLE_STUDENT,
    ROLE_SUPERVISORY,
    ROLE_VA,
    authenticate,
    get_charge,
    get_student,
    get_term,
    new_row,
    require_official,
    serialize,
    set_input_day,
    touch,
)
from db import db, lock
from domain import open_protection_window, refresh_protection
from errors import fail
from response import object_response
from validation import body, day_field, enum_field, int_field, string_field

CHAPTERS = ("CH30", "CH31", "CH33", "CH35", "CH1606")
BENEFIT_LEVELS = (40, 50, 60, 70, 80, 90, 100)
COE_STATUSES = ("NOT_SUBMITTED", "VERIFIED", "EXPIRED")
HOLD_STATUSES = ("NONE", "REGISTRATION_HOLD")
CHARGE_TYPES = ("TUITION", "MANDATORY_FEE", "LATE_FEE", "REINSTATEMENT_FEE")
PENALTY_CHARGE_TYPES = ("LATE_FEE", "REINSTATEMENT_FEE")

OFFICIAL_PAIR = (ROLE_SCO, ROLE_SUPERVISORY)
STUDENT_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA, ROLE_STUDENT)
STUDENT_LIST_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)
CHARGE_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)


def register(app):
    # ---------------------------------------------------------- students
    @app.post("/veteran-students")
    def create_student():
        with lock:
            actor = authenticate(OFFICIAL_PAIR)
            data = body()
            student_number = string_field(data, "student_number")
            full_name = string_field(data, "full_name")
            chapter = enum_field(data, "chapter", CHAPTERS)
            benefit_level_pct = int_field(data, "benefit_level_pct", choices=BENEFIT_LEVELS)
            granted = int_field(data, "entitlement_days_granted", minimum=1)
            delimiting_date = day_field(data, "delimiting_date")
            coe_issued_on = day_field(data, "coe_issued_on", required=False)
            require_official(actor)

            for existing in db.students.values():
                if existing["student_number"] == student_number:
                    fail("ERR_DUPLICATE_STUDENT_NUMBER",
                         "Another veteran student already uses this student number.")

            row = new_row()
            row["student_number"] = student_number
            row["full_name"] = full_name
            row["chapter"] = chapter
            row["benefit_level_pct"] = benefit_level_pct
            row["entitlement_days_granted"] = granted
            row["entitlement_days_remaining"] = granted
            set_input_day(row, "delimiting_date", delimiting_date)
            set_input_day(row, "coe_issued_on", coe_issued_on)
            row["coe_status"] = "NOT_SUBMITTED"
            row["coe_verified_on"] = None
            row["verified_document_reference"] = None
            row["protected_until"] = None
            row["benefit_payment_protected"] = False
            row["account_hold_status"] = "NONE"
            row["open_debt_principal_cents"] = 0
            db.students[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/veteran-students/<student_id>")
    def read_student(student_id):
        with lock:
            actor = authenticate(STUDENT_READ_ROLES)
            require_official(actor)
            student = get_student(student_id)
            if actor.role == ROLE_STUDENT and actor.user_id != student["id"]:
                fail("ERR_STUDENT_SCOPE_VIOLATION",
                     "A student may only read their own record.")
            return object_response(serialize(student))

    @app.get("/veteran-students")
    def list_students():
        with lock:
            actor = authenticate(STUDENT_LIST_ROLES)
            query = ListQuery((("student_number", None),
                               ("chapter", CHAPTERS),
                               ("coe_status", COE_STATUSES),
                               ("account_hold_status", HOLD_STATUSES)))
            require_official(actor)
            return query.emit(db.students.values())

    @app.post("/veteran-students/<student_id>/verify-coe")
    def verify_coe(student_id):
        with lock:
            actor = authenticate(OFFICIAL_PAIR)
            data = body()
            coe_issued_on = day_field(data, "coe_issued_on")
            document_reference = string_field(data, "verified_document_reference")
            require_official(actor)
            student = get_student(student_id)

            if student["coe_status"] not in ("NOT_SUBMITTED", "EXPIRED"):
                fail("ERR_COE_ALREADY_VERIFIED",
                     "This Certificate of Eligibility is already verified.")

            open_protection_window(student, coe_issued_on, document_reference)
            refresh_protection(student)
            touch(student)
            return object_response(serialize(student))

    @app.post("/veteran-students/<student_id>/expire-coe")
    def expire_coe(student_id):
        with lock:
            authenticate((ROLE_VA,))
            student = get_student(student_id)
            if student["coe_status"] != "VERIFIED":
                fail("ERR_COE_NOT_VERIFIED",
                     "This Certificate of Eligibility is not verified.")
            student["coe_status"] = "EXPIRED"
            refresh_protection(student)
            touch(student)
            return object_response(serialize(student))

    @app.post("/veteran-students/<student_id>/account-holds")
    def set_account_hold(student_id):
        with lock:
            authenticate((ROLE_BURSAR,))
            data = body()
            hold_status = enum_field(data, "hold_status", HOLD_STATUSES)
            student = get_student(student_id)

            if hold_status == "REGISTRATION_HOLD" and is_protected(student):
                fail("ERR_PROTECTED_STUDENT_PENALTY",
                     "38 USC 3679(e) bars a registration hold while VA payment is outstanding.")

            student["account_hold_status"] = hold_status
            touch(student)
            return object_response(serialize(student))

    # -------------------------------------------------- account charges
    @app.post("/student-account-charges")
    def create_charge():
        with lock:
            authenticate((ROLE_BURSAR,))
            data = body()
            student_id = string_field(data, "student_id")
            term_id = string_field(data, "term_id")
            charge_type = enum_field(data, "charge_type", CHARGE_TYPES)
            amount_cents = int_field(data, "amount_cents", minimum=0)

            student = get_student(student_id)
            term = get_term(term_id)

            if charge_type in PENALTY_CHARGE_TYPES and is_protected(student):
                fail("ERR_PROTECTED_STUDENT_PENALTY",
                     "38 USC 3679(e) bars a penalty charge while VA payment is outstanding.")

            row = new_row()
            row["student_id"] = student["id"]
            row["term_id"] = term["id"]
            row["charge_type"] = charge_type
            row["amount_cents"] = amount_cents
            row["status"] = "POSTED"
            db.charges[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/student-account-charges/<charge_id>")
    def read_charge(charge_id):
        with lock:
            actor = authenticate(CHARGE_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_charge(charge_id)))

    @app.get("/student-account-charges")
    def list_charges():
        with lock:
            actor = authenticate(CHARGE_READ_ROLES)
            query = ListQuery((("student_id", None),
                               ("term_id", None),
                               ("charge_type", CHARGE_TYPES)))
            require_official(actor)
            return query.emit(db.charges.values())
