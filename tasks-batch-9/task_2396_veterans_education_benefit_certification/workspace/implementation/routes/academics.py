"""AcademicTerm, Program and CatalogVersion endpoints (including CASCADE-B)."""

from common import (
    ListQuery,
    ROLE_BURSAR,
    ROLE_SAA,
    ROLE_SCO,
    ROLE_SUPERVISORY,
    ROLE_VA,
    append_audit,
    authenticate,
    by_created,
    day_of,
    get_catalog_version,
    get_program,
    get_term,
    new_row,
    require_official,
    serialize,
    set_input_day,
    touch,
)
from db import db, lock
from errors import fail
from response import object_response
from validation import body, bool_field, day_field, enum_field, int_field, string_field

TERM_TYPES = ("FALL", "SPRING", "SUMMER", "WINTER")
TERM_STATUSES = ("OPEN", "CLOSED")
DEGREE_LEVELS = ("UNDERGRAD", "GRADUATE", "CERTIFICATE")
PROGRAM_STATUSES = ("DRAFT", "PENDING_SAA", "APPROVED", "CONDITIONAL", "SUSPENDED")
REVIEW_STATUSES = ("DRAFT", "PENDING_SAA", "APPROVED", "APPROVED_WITH_CONDITIONS",
                   "REJECTED", "SUSPENDED")
SAA_DECISIONS = ("APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED")

CATALOG_SUBMITTABLE = ("DRAFT", "REJECTED", "SUSPENDED")
CATALOG_SUSPENDABLE = ("APPROVED", "APPROVED_WITH_CONDITIONS")
CATALOG_WINDOW_BLOCKING = ("PENDING_SAA", "APPROVED", "APPROVED_WITH_CONDITIONS")

TERM_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)
PROGRAM_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_SAA, ROLE_BURSAR, ROLE_VA)
CATALOG_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_SAA, ROLE_VA)


def register(app):
    # ------------------------------------------------------- academic terms
    @app.post("/academic-terms")
    def create_term():
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            term_code = string_field(data, "term_code")
            academic_year = string_field(data, "academic_year")
            term_type = enum_field(data, "term_type", TERM_TYPES)
            start_raw = day_field(data, "start_date")
            end_raw = day_field(data, "end_date")
            drop_raw = day_field(data, "drop_deadline")
            cert_deadline_raw = day_field(data, "certification_deadline")
            require_official(actor)

            for existing in db.terms.values():
                if existing["term_code"] == term_code:
                    fail("ERR_DUPLICATE_TERM_CODE",
                         "Another academic term already uses this term code.")

            row = new_row()
            row["term_code"] = term_code
            row["academic_year"] = academic_year
            row["term_type"] = term_type
            set_input_day(row, "start_date", start_raw)
            set_input_day(row, "end_date", end_raw)
            set_input_day(row, "drop_deadline", drop_raw)
            set_input_day(row, "certification_deadline", cert_deadline_raw)

            start = day_of(row, "start_date")
            end = day_of(row, "end_date")
            drop = day_of(row, "drop_deadline")
            deadline = day_of(row, "certification_deadline")
            if not (start < end and start <= drop <= end and deadline >= start):
                fail("ERR_INVALID_TERM_DATES",
                     "The term date ordering constraints are not satisfied.")

            row["status"] = "OPEN"
            db.terms[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/academic-terms/<term_id>")
    def read_term(term_id):
        with lock:
            actor = authenticate(TERM_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_term(term_id)))

    @app.get("/academic-terms")
    def list_terms():
        with lock:
            actor = authenticate(TERM_READ_ROLES)
            query = ListQuery((("academic_year", None),
                               ("term_type", TERM_TYPES),
                               ("status", TERM_STATUSES)))
            require_official(actor)
            return query.emit(db.terms.values())

    @app.post("/academic-terms/<term_id>/close")
    def close_term(term_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            term = get_term(term_id)
            if term["status"] != "OPEN":
                fail("ERR_TERM_ALREADY_CLOSED", "This academic term is already closed.")
            term["status"] = "CLOSED"
            touch(term)
            return object_response(serialize(term))

    # ------------------------------------------------------------- programs
    @app.post("/programs")
    def create_program():
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            program_code = string_field(data, "program_code")
            name = string_field(data, "name")
            degree_level = enum_field(data, "degree_level", DEGREE_LEVELS)
            full_time_credit_hours = int_field(data, "full_time_credit_hours", minimum=1)
            campus_bah_monthly_cents = int_field(data, "campus_bah_monthly_cents", minimum=0)
            require_official(actor)

            for existing in db.programs.values():
                if existing["program_code"] == program_code:
                    fail("ERR_DUPLICATE_PROGRAM_CODE",
                         "Another program already uses this program code.")

            row = new_row()
            row["program_code"] = program_code
            row["name"] = name
            row["degree_level"] = degree_level
            row["full_time_credit_hours"] = full_time_credit_hours
            row["campus_bah_monthly_cents"] = campus_bah_monthly_cents
            row["approval_status"] = "DRAFT"
            row["approved_catalog_version_id"] = None
            db.programs[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/programs/<program_id>")
    def read_program(program_id):
        with lock:
            actor = authenticate(PROGRAM_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_program(program_id)))

    @app.get("/programs")
    def list_programs():
        with lock:
            actor = authenticate(PROGRAM_READ_ROLES)
            query = ListQuery((("approval_status", PROGRAM_STATUSES),
                               ("degree_level", DEGREE_LEVELS),
                               ("approved_catalog_version_id", None)))
            require_official(actor)
            return query.emit(db.programs.values())

    # ------------------------------------------------------ catalog versions
    @app.post("/catalog-versions")
    def create_catalog_version():
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            program_id = string_field(data, "program_id")
            catalog_year = string_field(data, "catalog_year")
            start_raw = day_field(data, "effective_start")
            end_raw = day_field(data, "effective_end")
            has_tuition = bool_field(data, "has_published_tuition_schedule")
            has_refund = bool_field(data, "has_refund_policy")
            has_length = bool_field(data, "has_program_length_disclosure")
            require_official(actor)

            program = get_program(program_id)

            row = new_row()
            row["program_id"] = program["id"]
            row["catalog_year"] = catalog_year
            set_input_day(row, "effective_start", start_raw)
            set_input_day(row, "effective_end", end_raw)
            row["has_published_tuition_schedule"] = has_tuition
            row["has_refund_policy"] = has_refund
            row["has_program_length_disclosure"] = has_length
            row["conditions_note"] = None
            row["suspension_reason"] = None
            row["review_status"] = "DRAFT"

            start = day_of(row, "effective_start")
            end = day_of(row, "effective_end")
            for other in db.catalog_versions.values():
                if other["program_id"] != program["id"]:
                    continue
                if other["review_status"] not in CATALOG_WINDOW_BLOCKING:
                    continue
                other_start = day_of(other, "effective_start")
                other_end = day_of(other, "effective_end")
                # HALF-OPEN overlap: touching windows are legal.
                if start < other_end and other_start < end:
                    fail("ERR_CATALOG_WINDOW_OVERLAP",
                         "This effective window overlaps another live catalog version "
                         "of the same program.")

            db.catalog_versions[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/catalog-versions/<cv_id>")
    def read_catalog_version(cv_id):
        with lock:
            actor = authenticate(CATALOG_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_catalog_version(cv_id)))

    @app.get("/catalog-versions")
    def list_catalog_versions():
        with lock:
            actor = authenticate(CATALOG_READ_ROLES)
            query = ListQuery((("program_id", None),
                               ("review_status", REVIEW_STATUSES),
                               ("catalog_year", None)))
            require_official(actor)
            return query.emit(db.catalog_versions.values())

    @app.post("/catalog-versions/<cv_id>/submit-to-saa")
    def submit_catalog_version(cv_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            version = get_catalog_version(cv_id)

            if version["review_status"] not in CATALOG_SUBMITTABLE:
                fail("ERR_CATALOG_NOT_SUBMITTABLE",
                     "This catalog version cannot be submitted from its current review status.")
            if not (version["has_published_tuition_schedule"]
                    and version["has_refund_policy"]
                    and version["has_program_length_disclosure"]):
                fail("ERR_CATALOG_COMPLIANCE_INCOMPLETE",
                     "All three catalog compliance items must be satisfied before SAA review.")

            version["review_status"] = "PENDING_SAA"
            version["suspension_reason"] = None
            touch(version)

            program = db.programs.get(version["program_id"])
            if program is not None:
                program["approval_status"] = "PENDING_SAA"
                touch(program)

            return object_response(serialize(version))

    @app.post("/catalog-versions/<cv_id>/saa-decision")
    def saa_decision(cv_id):
        with lock:
            authenticate((ROLE_SAA,))
            data = body()
            decision = enum_field(data, "decision", SAA_DECISIONS)
            conditions_note = string_field(data, "conditions_note", required=False)
            if decision == "APPROVED_WITH_CONDITIONS" and conditions_note is None:
                fail("ERR_INVALID_REQUEST",
                     "conditions_note is required for an APPROVED_WITH_CONDITIONS decision.")

            version = get_catalog_version(cv_id)
            if version["review_status"] != "PENDING_SAA":
                fail("ERR_CATALOG_NOT_PENDING_SAA",
                     "This catalog version is not pending SAA review.")

            program = db.programs.get(version["program_id"])

            version["review_status"] = decision
            if decision == "APPROVED_WITH_CONDITIONS":
                version["conditions_note"] = conditions_note
            touch(version)

            if program is not None:
                if decision == "APPROVED":
                    program["approval_status"] = "APPROVED"
                    program["approved_catalog_version_id"] = version["id"]
                elif decision == "APPROVED_WITH_CONDITIONS":
                    program["approval_status"] = "CONDITIONAL"
                    program["approved_catalog_version_id"] = version["id"]
                else:
                    program["approval_status"] = "DRAFT"
                    program["approved_catalog_version_id"] = None
                touch(program)

            return object_response(serialize(version))

    @app.post("/catalog-versions/<cv_id>/suspend")
    def suspend_catalog_version(cv_id):
        with lock:
            authenticate((ROLE_SAA,))
            data = body()
            suspension_reason = string_field(data, "suspension_reason")

            version = get_catalog_version(cv_id)
            if version["review_status"] not in CATALOG_SUSPENDABLE:
                fail("ERR_CATALOG_NOT_SUSPENDABLE",
                     "Only an approved catalog version may be suspended.")

            # CASCADE-B L1
            version["review_status"] = "SUSPENDED"
            version["suspension_reason"] = suspension_reason
            touch(version)

            # CASCADE-B L2
            programs = [p for p in db.programs.values()
                        if p["approved_catalog_version_id"] == version["id"]]
            programs = by_created(programs)
            for program in programs:
                program["approval_status"] = "SUSPENDED"
                touch(program)

                # CASCADE-B L3 / L4
                affected = [c for c in db.certifications.values()
                            if c["program_id"] == program["id"] and c["status"] == "SUBMITTED"]
                for cert in by_created(affected):
                    cert["status"] = "RETURNED"
                    cert["return_reason"] = "PROGRAM_SUSPENDED"
                    touch(cert)
                    append_audit(
                        cert["id"],
                        "CERTIFICATION_AUTO_RETURNED",
                        "system",
                        "system",
                        "Auto-returned because catalog version %s was suspended." % version["id"],
                    )

            return object_response(serialize(version))
