"""EnrollmentCertification and TuitionFeeReport endpoints."""

from calc import (
    calc2_as_certified,
    calc3_steps_2_to_7,
    calc4_calendar_full_term,
    net_covered_from_report,
)
from common import (
    ListQuery,
    ROLE_BURSAR,
    ROLE_SAA,
    ROLE_SCO,
    ROLE_SUPERVISORY,
    ROLE_VA,
    append_audit,
    authenticate,
    clock_day,
    day_of,
    get_certification,
    get_program,
    get_student,
    get_term,
    get_tuition_report,
    new_row,
    require_official,
    serialize,
    set_input_day,
    touch,
)
from db import db, lock
from domain import (
    CERT_LIVE_FOR_OVERLAP,
    apply_calc1,
    effective_catalog_version,
    guard_terminal,
    refresh_protection,
    reported_tuition_report,
)
from errors import fail
from response import object_response
from validation import body, day_field, int_field, number_field, string_field

CERT_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "CERTIFIED", "AMENDMENT_PENDING",
                 "TERMINATED", "VOID")
CERT_EDITABLE = ("DRAFT", "RETURNED")
REPORT_STATUSES = ("REPORTED", "SUPERSEDED")
AUDIT_EVENT_TYPES = ("CERTIFICATION_SUBMITTED", "CERTIFICATION_RETURNED",
                     "CERTIFICATION_CERTIFIED", "CERTIFICATION_AUTO_RETURNED",
                     "CERTIFICATION_VOIDED", "AMENDMENT_OPENED", "AMENDMENT_RECONCILED",
                     "DEBT_CREATED", "DEBT_WAIVED", "VA_PAYMENT_RECORDED", "AWARD_REVERSED")

WRITER_ROLES = (ROLE_SCO, ROLE_SUPERVISORY)
CERT_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_SAA, ROLE_VA)
AUDIT_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_SAA, ROLE_VA)
TFR_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)


def register(app):
    # ------------------------------------------------------- certifications
    @app.post("/enrollment-certifications")
    def create_certification():
        with lock:
            actor = authenticate(WRITER_ROLES)
            data = body()
            student_id = string_field(data, "student_id")
            term_id = string_field(data, "term_id")
            program_id = string_field(data, "program_id")
            credit_hours_total = number_field(data, "credit_hours_total", exclusive_minimum=0)
            credit_hours_online = number_field(data, "credit_hours_online", minimum=0)
            start_raw = day_field(data, "term_start_certified")
            end_raw = day_field(data, "term_end_certified")
            require_official(actor)

            student = get_student(student_id)
            term = get_term(term_id)
            program = get_program(program_id)

            if credit_hours_online > credit_hours_total:
                fail("ERR_INVALID_CREDIT_SPLIT",
                     "credit_hours_online may not exceed credit_hours_total.")

            row = new_row()
            row["student_id"] = student["id"]
            row["term_id"] = term["id"]
            row["program_id"] = program["id"]
            row["pinned_catalog_version_id"] = None
            row["submitted_by_official_id"] = None
            row["certified_by_official_id"] = None
            row["credit_hours_total"] = credit_hours_total
            row["credit_hours_online"] = credit_hours_online
            set_input_day(row, "term_start_certified", start_raw)
            set_input_day(row, "term_end_certified", end_raw)
            row["certified_days"] = 0
            row["rate_of_pursuit_pct"] = 0
            row["rop_tier_pct"] = 0
            row["training_time"] = None
            row["modality"] = None
            row["mha_eligible"] = False
            row["mha_monthly_rate_cents"] = 0
            row["mha_term_total_cents"] = 0
            row["net_covered_cents"] = 0
            row["ay_cap_remaining_before_cents"] = 0
            row["va_tuition_cents"] = 0
            row["cap_charged_cents"] = 0
            row["yr_gap_cents"] = 0
            row["entitlement_days_charged"] = 0
            row["tuition_paid_cents"] = 0
            row["mha_paid_cents"] = 0
            row["tuition_payment_posted_on"] = None
            row["amount_basis"] = None
            row["return_reason"] = None
            row["status"] = "DRAFT"

            apply_calc1(row, program, student)
            db.certifications[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/enrollment-certifications/<cert_id>")
    def read_certification(cert_id):
        with lock:
            actor = authenticate(CERT_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_certification(cert_id)))

    @app.get("/enrollment-certifications")
    def list_certifications():
        with lock:
            actor = authenticate(CERT_READ_ROLES)
            query = ListQuery((("student_id", None),
                               ("term_id", None),
                               ("program_id", None),
                               ("pinned_catalog_version_id", None),
                               ("submitted_by_official_id", None),
                               ("certified_by_official_id", None),
                               ("status", CERT_STATUSES)))
            require_official(actor)
            return query.emit(db.certifications.values())

    @app.patch("/enrollment-certifications/<cert_id>")
    def patch_certification(cert_id):
        with lock:
            actor = authenticate(WRITER_ROLES)
            data = body()
            credit_hours_total = number_field(data, "credit_hours_total",
                                              required=False, exclusive_minimum=0)
            credit_hours_online = number_field(data, "credit_hours_online",
                                              required=False, minimum=0)
            start_raw = day_field(data, "term_start_certified", required=False)
            end_raw = day_field(data, "term_end_certified", required=False)
            require_official(actor)

            cert = get_certification(cert_id)
            if cert["status"] not in CERT_EDITABLE:
                fail("ERR_CERTIFICATION_NOT_EDITABLE",
                     "Only a DRAFT or RETURNED certification may be revised.")

            merged_total = (credit_hours_total if credit_hours_total is not None
                            else cert["credit_hours_total"])
            merged_online = (credit_hours_online if credit_hours_online is not None
                             else cert["credit_hours_online"])
            if merged_online > merged_total:
                fail("ERR_INVALID_CREDIT_SPLIT",
                     "credit_hours_online may not exceed credit_hours_total.")

            cert["credit_hours_total"] = merged_total
            cert["credit_hours_online"] = merged_online
            if start_raw is not None:
                set_input_day(cert, "term_start_certified", start_raw)
            if end_raw is not None:
                set_input_day(cert, "term_end_certified", end_raw)
            cert["status"] = "DRAFT"
            cert["return_reason"] = None

            apply_calc1(cert, db.programs[cert["program_id"]], db.students[cert["student_id"]])
            touch(cert)
            return object_response(serialize(cert))

    @app.post("/enrollment-certifications/<cert_id>/submit")
    def submit_certification(cert_id):
        with lock:
            actor = authenticate(WRITER_ROLES)
            require_official(actor)
            cert = get_certification(cert_id)
            guard_terminal(cert)

            if cert["status"] not in CERT_EDITABLE:
                fail("ERR_CERTIFICATION_NOT_SUBMITTABLE",
                     "Only a DRAFT or RETURNED certification may be submitted.")

            term = db.terms[cert["term_id"]]
            if term["status"] != "OPEN":
                fail("ERR_TERM_CLOSED",
                     "The academic term is closed to new certification submissions.")

            student = db.students[cert["student_id"]]
            start = day_of(cert, "term_start_certified")
            end = day_of(cert, "term_end_certified")

            delimiting = day_of(student, "delimiting_date")
            if delimiting is not None and end > delimiting:
                fail("ERR_DELIMITING_DATE_PASSED",
                     "The certified period ends after the student's delimiting date.")

            if start < day_of(term, "start_date") or end > day_of(term, "end_date"):
                fail("ERR_CERTIFIED_DATES_OUTSIDE_TERM",
                     "The certified period must fall inside the term's own dates.")

            for other in db.certifications.values():
                if other["id"] == cert["id"] or other["student_id"] != cert["student_id"]:
                    continue
                if other["status"] not in CERT_LIVE_FOR_OVERLAP:
                    continue
                other_start = day_of(other, "term_start_certified")
                other_end = day_of(other, "term_end_certified")
                # CLOSED interval: a shared endpoint is a collision.
                if other_start <= end and start <= other_end:
                    fail("ERR_OVERLAPPING_ENROLLMENT_PERIOD",
                         "Another live certification for this student covers part of "
                         "this period.")

            version = effective_catalog_version(cert["program_id"], start)
            if version is None:
                fail("ERR_CATALOG_VERSION_NOT_EFFECTIVE",
                     "No approved catalog version covers the certified start date.")

            cert["status"] = "SUBMITTED"
            cert["submitted_by_official_id"] = actor.user_id
            cert["pinned_catalog_version_id"] = version["id"]
            cert["return_reason"] = None
            touch(cert)

            append_audit(cert["id"], "CERTIFICATION_SUBMITTED", actor.role, actor.user_id,
                         "Certification submitted for supervisory review.")
            return object_response(serialize(cert))

    @app.post("/enrollment-certifications/<cert_id>/return")
    def return_certification(cert_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            return_reason = string_field(data, "return_reason")
            require_official(actor)
            cert = get_certification(cert_id)
            guard_terminal(cert)

            if cert["status"] != "SUBMITTED":
                fail("ERR_CERTIFICATION_NOT_SUBMITTED",
                     "Only a SUBMITTED certification may be returned.")

            cert["status"] = "RETURNED"
            cert["return_reason"] = return_reason
            touch(cert)

            append_audit(cert["id"], "CERTIFICATION_RETURNED", actor.role, actor.user_id,
                         "Certification returned: %s" % return_reason)
            return object_response(serialize(cert))

    @app.post("/enrollment-certifications/<cert_id>/certify")
    def certify_certification(cert_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            cert = get_certification(cert_id)
            guard_terminal(cert)

            if cert["status"] != "SUBMITTED":
                fail("ERR_CERTIFICATION_NOT_SUBMITTED",
                     "Only a SUBMITTED certification may be certified.")

            student = db.students[cert["student_id"]]
            if student["coe_status"] != "VERIFIED":
                fail("ERR_COE_NOT_VERIFIED",
                     "The student's Certificate of Eligibility is not verified.")

            if actor.user_id == cert["submitted_by_official_id"]:
                fail("ERR_SEGREGATION_OF_DUTIES",
                     "The certifying official may not be the submitting official.")

            program = db.programs[cert["program_id"]]
            if program["approval_status"] not in ("APPROVED", "CONDITIONAL"):
                fail("ERR_PROGRAM_NOT_APPROVED",
                     "The program is not approved by the State Approving Agency.")

            term = db.terms[cert["term_id"]]
            deadline = day_of(term, "certification_deadline")
            if deadline is not None and clock_day() > deadline:
                fail("ERR_CERTIFICATION_DEADLINE_PASSED",
                     "The term's certification deadline has passed.")

            report = reported_tuition_report(cert["id"])
            if report is None:
                fail("ERR_TUITION_REPORT_MISSING",
                     "A REPORTED tuition and fee report is required before certifying.")

            entitlement_days = calc4_calendar_full_term(cert["certified_days"],
                                                        cert["rop_tier_pct"])
            if entitlement_days > student["entitlement_days_remaining"]:
                fail("ERR_INSUFFICIENT_ENTITLEMENT",
                     "The student does not have enough entitlement days remaining.")

            cert["mha_term_total_cents"] = calc2_as_certified(
                day_of(cert, "term_start_certified"),
                day_of(cert, "term_end_certified"),
                cert["mha_eligible"],
                cert["mha_monthly_rate_cents"],
            )

            money = calc3_steps_2_to_7(cert, student, report["net_covered_cents"])
            cert["net_covered_cents"] = money["net_covered_cents"]
            cert["ay_cap_remaining_before_cents"] = money["ay_cap_remaining_before_cents"]
            cert["va_tuition_cents"] = money["va_tuition_cents"]
            cert["cap_charged_cents"] = money["cap_charged_cents"]
            cert["yr_gap_cents"] = money["yr_gap_cents"]

            cert["entitlement_days_charged"] = entitlement_days
            cert["certified_by_official_id"] = actor.user_id
            cert["amount_basis"] = "AS_CERTIFIED"
            cert["status"] = "CERTIFIED"
            touch(cert)

            student["entitlement_days_remaining"] -= entitlement_days
            refresh_protection(student)
            touch(student)

            append_audit(cert["id"], "CERTIFICATION_CERTIFIED", actor.role, actor.user_id,
                         "Certification certified to VA on the AS_CERTIFIED basis.")
            return object_response(serialize(cert))

    @app.post("/enrollment-certifications/<cert_id>/void")
    def void_certification(cert_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            cert = get_certification(cert_id)
            guard_terminal(cert)

            if cert["status"] not in CERT_EDITABLE:
                fail("ERR_CERTIFICATION_NOT_EDITABLE",
                     "Only a DRAFT or RETURNED certification may be voided.")

            cert["status"] = "VOID"
            touch(cert)

            append_audit(cert["id"], "CERTIFICATION_VOIDED", actor.role, actor.user_id,
                         "Certification voided.")
            return object_response(serialize(cert))

    @app.post("/enrollment-certifications/<cert_id>/record-va-payment")
    def record_va_payment(cert_id):
        with lock:
            actor = authenticate((ROLE_VA,))
            data = body()
            tuition_amount_cents = int_field(data, "tuition_amount_cents", minimum=0)
            mha_amount_cents = int_field(data, "mha_amount_cents", minimum=0)
            posted_on = day_field(data, "posted_on")

            cert = get_certification(cert_id)
            guard_terminal(cert)

            if cert["tuition_payment_posted_on"] is not None:
                fail("ERR_VA_PAYMENT_ALREADY_RECORDED",
                     "A VA payment has already been recorded for this certification.")

            cert["tuition_paid_cents"] = tuition_amount_cents
            cert["mha_paid_cents"] = mha_amount_cents
            set_input_day(cert, "tuition_payment_posted_on", posted_on)
            touch(cert)

            student = db.students[cert["student_id"]]
            refresh_protection(student)
            touch(student)

            append_audit(cert["id"], "VA_PAYMENT_RECORDED", actor.role, actor.user_id,
                         "VA disbursed %d cents tuition and %d cents housing."
                         % (tuition_amount_cents, mha_amount_cents))
            return object_response(serialize(cert))

    @app.get("/enrollment-certifications/<cert_id>/audit-entries")
    def list_audit_entries(cert_id):
        with lock:
            actor = authenticate(AUDIT_READ_ROLES)
            query = ListQuery((("event_type", AUDIT_EVENT_TYPES),))
            require_official(actor)
            cert = get_certification(cert_id)
            return query.emit(
                db.audit_entries.values(),
                extra=lambda e: e["certification_id"] == cert["id"],
                order_key=lambda e: e["sequence_index"],
            )

    # --------------------------------------------------- tuition fee reports
    @app.post("/tuition-fee-reports")
    def create_tuition_report():
        with lock:
            authenticate((ROLE_BURSAR,))
            data = body()
            certification_id = string_field(data, "certification_id")
            gross = int_field(data, "gross_tuition_cents", minimum=0)
            fees = int_field(data, "mandatory_fees_cents", minimum=0)
            tuition_aid = int_field(data, "tuition_specific_aid_cents", minimum=0)
            non_tuition_aid = int_field(data, "non_tuition_aid_cents", minimum=0)
            expected_version = int_field(data, "expected_certification_version", minimum=0)

            cert = get_certification(certification_id)

            if expected_version != cert["version"]:
                fail("ERR_STALE_CERTIFICATION_VERSION",
                     "The certification has been modified since it was read.")

            net_covered = net_covered_from_report(gross, fees, tuition_aid)

            row = new_row()
            row["certification_id"] = cert["id"]
            row["gross_tuition_cents"] = gross
            row["mandatory_fees_cents"] = fees
            row["tuition_specific_aid_cents"] = tuition_aid
            row["non_tuition_aid_cents"] = non_tuition_aid
            row["net_covered_cents"] = net_covered
            row["status"] = "REPORTED"

            for prior in db.tuition_reports.values():
                if prior["certification_id"] == cert["id"] and prior["status"] == "REPORTED":
                    prior["status"] = "SUPERSEDED"
                    touch(prior)

            db.tuition_reports[row["id"]] = row

            cert["net_covered_cents"] = net_covered
            touch(cert)

            return object_response(serialize(row), 201)

    @app.get("/tuition-fee-reports/<report_id>")
    def read_tuition_report(report_id):
        with lock:
            actor = authenticate(TFR_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_tuition_report(report_id)))

    @app.get("/tuition-fee-reports")
    def list_tuition_reports():
        with lock:
            actor = authenticate(TFR_READ_ROLES)
            query = ListQuery((("certification_id", None),
                               ("status", REPORT_STATUSES)))
            require_official(actor)
            return query.emit(db.tuition_reports.values())
