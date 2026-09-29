"""EnrollmentChangeReport and BenefitDebt endpoints (CALC-5, CALC-6, CASCADE-A)."""

from calc import calc5, calc6_allocate, is_protected
from common import (
    ListQuery,
    ROLE_BURSAR,
    ROLE_SCO,
    ROLE_STUDENT,
    ROLE_SUPERVISORY,
    ROLE_VA,
    append_audit,
    authenticate,
    clock_day,
    day_of,
    get_certification,
    get_change_report,
    get_debt,
    new_row,
    require_official,
    serialize,
    set_computed_day,
    set_input_day,
    touch,
)
from db import db, lock
from domain import guard_terminal, reconcile_change_report
from errors import fail
from response import object_response
from validation import body, bool_field, day_field, enum_field, int_field, number_field, string_field

CHANGE_TYPES = ("CREDIT_HOUR_REDUCTION", "COMPLETE_WITHDRAWAL", "TERM_DATE_CHANGE")
REPORTING_STATUSES = ("TIMELY", "LATE")
CHANGE_STATUSES = ("REPORTED", "RECONCILED")
DEBTOR_TYPES = ("STUDENT", "SCHOOL")
COLLECTION_STATUSES = ("OPEN", "PARTIALLY_REPAID", "SATISFIED", "WAIVED")
NOTIFICATION_STATUSES = ("PENDING", "SENT", "ACKNOWLEDGED", "OVERDUE")
NOTIFICATION_CHANNELS = ("EMAIL", "POSTAL", "PORTAL")
DEBT_LIVE = ("OPEN", "PARTIALLY_REPAID")

WRITER_ROLES = (ROLE_SCO, ROLE_SUPERVISORY)
CHANGE_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)
DEBT_READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA, ROLE_STUDENT)


def register(app):
    # -------------------------------------------------------- change reports
    @app.post("/enrollment-change-reports")
    def create_change_report():
        with lock:
            actor = authenticate(WRITER_ROLES)
            data = body()
            certification_id = string_field(data, "certification_id")
            change_type = enum_field(data, "change_type", CHANGE_TYPES)
            effective_raw = day_field(data, "effective_date")
            mitigating = bool_field(data, "mitigating_circumstances_flag")
            new_credit_hours = number_field(data, "new_credit_hours",
                                           required=False, minimum=0)
            new_credit_hours_online = number_field(data, "new_credit_hours_online",
                                                  required=False, minimum=0)
            new_term_end_raw = day_field(data, "new_term_end_certified", required=False)
            punitive = bool_field(data, "punitive_grade_flag", required=False, default=False)
            disbursed_aid = int_field(data, "disbursed_tuition_aid_cents",
                                      required=False, default=0, minimum=0)

            if change_type == "CREDIT_HOUR_REDUCTION" and (new_credit_hours is None
                                                           or new_credit_hours_online is None):
                fail("ERR_INVALID_REQUEST",
                     "new_credit_hours and new_credit_hours_online are required for "
                     "a CREDIT_HOUR_REDUCTION.")
            if change_type == "TERM_DATE_CHANGE" and new_term_end_raw is None:
                fail("ERR_INVALID_REQUEST",
                     "new_term_end_certified is required for a TERM_DATE_CHANGE.")

            require_official(actor)

            cert = get_certification(certification_id)
            guard_terminal(cert)

            if cert["status"] != "CERTIFIED":
                fail("ERR_CERTIFICATION_NOT_CERTIFIED",
                     "Only a CERTIFIED certification may receive a change report.")

            student = db.students[cert["student_id"]]
            if punitive and is_protected(student):
                fail("ERR_PROTECTED_STUDENT_PENALTY",
                     "38 USC 3679(e) bars a punitive grade while VA payment is outstanding.")

            row = new_row()
            set_input_day(row, "effective_date", effective_raw)
            effective_day = day_of(row, "effective_date")
            if not (day_of(cert, "term_start_certified") <= effective_day
                    <= day_of(cert, "term_end_certified")):
                fail("ERR_CHANGE_DATE_OUTSIDE_TERM",
                     "effective_date must fall inside the certified enrollment period.")

            if change_type == "CREDIT_HOUR_REDUCTION" and new_credit_hours_online > new_credit_hours:
                fail("ERR_INVALID_CREDIT_SPLIT",
                     "new_credit_hours_online may not exceed new_credit_hours.")

            reported_day = clock_day()
            days_late, reporting_status, liability_party = calc5(reported_day, effective_day)

            row["certification_id"] = cert["id"]
            row["reconciled_by_official_id"] = None
            row["change_type"] = change_type
            row["new_credit_hours"] = new_credit_hours
            row["new_credit_hours_online"] = new_credit_hours_online
            set_input_day(row, "new_term_end_certified", new_term_end_raw)
            row["mitigating_circumstances_flag"] = mitigating
            row["punitive_grade_flag"] = punitive
            row["disbursed_tuition_aid_cents"] = disbursed_aid
            set_computed_day(row, "reported_on", reported_day)
            row["days_late"] = days_late
            row["reporting_status"] = reporting_status
            row["liability_party"] = liability_party
            row["status"] = "REPORTED"
            db.change_reports[row["id"]] = row

            cert["status"] = "AMENDMENT_PENDING"
            touch(cert)

            append_audit(cert["id"], "AMENDMENT_OPENED", actor.role, actor.user_id,
                         "Change report %s opened (%s)." % (row["id"], change_type))
            return object_response(serialize(row), 201)

    @app.get("/enrollment-change-reports/<report_id>")
    def read_change_report(report_id):
        with lock:
            actor = authenticate(CHANGE_READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_change_report(report_id)))

    @app.get("/enrollment-change-reports")
    def list_change_reports():
        with lock:
            actor = authenticate(CHANGE_READ_ROLES)
            query = ListQuery((("certification_id", None),
                               ("reconciled_by_official_id", None),
                               ("change_type", CHANGE_TYPES),
                               ("reporting_status", REPORTING_STATUSES),
                               ("status", CHANGE_STATUSES)))
            require_official(actor)
            return query.emit(db.change_reports.values())

    @app.post("/enrollment-change-reports/<report_id>/reconcile")
    def reconcile(report_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            report = get_change_report(report_id)

            if report["status"] != "REPORTED":
                fail("ERR_CHANGE_REPORT_ALREADY_RECONCILED",
                     "This change report has already been reconciled.")

            cert = db.certifications[report["certification_id"]]
            if cert["status"] != "AMENDMENT_PENDING":
                fail("ERR_CERTIFICATION_NOT_CERTIFIED",
                     "The certification is not awaiting an amendment.")

            reconcile_change_report(report, actor)
            return object_response(serialize(report))

    # ---------------------------------------------------------- benefit debts
    @app.get("/benefit-debts/<debt_id>")
    def read_debt(debt_id):
        with lock:
            actor = authenticate(DEBT_READ_ROLES)
            require_official(actor)
            debt = get_debt(debt_id)
            if actor.role == ROLE_STUDENT and actor.user_id != debt["student_id"]:
                fail("ERR_STUDENT_SCOPE_VIOLATION",
                     "A student may only read their own debts.")
            return object_response(serialize(debt))

    @app.get("/benefit-debts")
    def list_debts():
        with lock:
            actor = authenticate(DEBT_READ_ROLES)
            query = ListQuery((("student_id", None),
                               ("certification_id", None),
                               ("change_report_id", None),
                               ("waived_by_official_id", None),
                               ("debtor_type", DEBTOR_TYPES),
                               ("collection_status", COLLECTION_STATUSES),
                               ("notification_status", NOTIFICATION_STATUSES)))
            require_official(actor)
            if actor.role == ROLE_STUDENT and query.get("student_id") != actor.user_id:
                fail("ERR_STUDENT_SCOPE_VIOLATION",
                     "A student must scope the query to their own student_id.")
            return query.emit(db.debts.values())

    @app.post("/benefit-debts/<debt_id>/notify")
    def notify_debt(debt_id):
        with lock:
            actor = authenticate(WRITER_ROLES)
            data = body()
            channel = enum_field(data, "notification_channel", NOTIFICATION_CHANNELS)
            require_official(actor)
            debt = get_debt(debt_id)

            if debt["notification_status"] != "PENDING":
                fail("ERR_DEBT_ALREADY_NOTIFIED",
                     "This debt notification has already been sent.")

            debt["notification_status"] = "SENT"
            debt["notification_channel"] = channel
            set_computed_day(debt, "notified_on", clock_day())
            touch(debt)
            return object_response(serialize(debt))

    @app.post("/benefit-debts/<debt_id>/acknowledge")
    def acknowledge_debt(debt_id):
        with lock:
            actor = authenticate((ROLE_STUDENT,))
            debt = get_debt(debt_id)

            if actor.user_id != debt["student_id"]:
                fail("ERR_STUDENT_SCOPE_VIOLATION",
                     "A student may only acknowledge their own debt.")

            if debt["notification_status"] not in ("SENT", "OVERDUE"):
                fail("ERR_DEBT_NOT_NOTIFIED",
                     "This debt has not been notified yet.")

            debt["notification_status"] = "ACKNOWLEDGED"
            set_computed_day(debt, "acknowledged_on", clock_day())
            touch(debt)
            return object_response(serialize(debt))

    @app.post("/benefit-debts/<debt_id>/mark-overdue")
    def mark_debt_overdue(debt_id):
        with lock:
            authenticate((ROLE_VA,))
            debt = get_debt(debt_id)

            if debt["notification_status"] not in ("PENDING", "SENT"):
                fail("ERR_DEBT_ALREADY_NOTIFIED",
                     "This debt notification is no longer escalatable.")

            due = day_of(debt, "notification_due_on")
            if due is not None and clock_day() <= due:
                fail("ERR_INVALID_REQUEST",
                     "The notification deadline has not passed yet.")

            debt["notification_status"] = "OVERDUE"
            touch(debt)
            return object_response(serialize(debt))

    @app.post("/benefit-debts/<debt_id>/repayments")
    def repay_debt(debt_id):
        with lock:
            authenticate((ROLE_BURSAR,))
            data = body()
            amount_cents = int_field(data, "amount_cents", minimum=0)

            debt = get_debt(debt_id)

            if debt["collection_status"] not in DEBT_LIVE:
                fail("ERR_DEBT_ALREADY_SETTLED",
                     "This debt is no longer collectable.")
            if amount_cents > debt["outstanding_cents"]:
                fail("ERR_REPAYMENT_EXCEEDS_BALANCE",
                     "The repayment exceeds the outstanding balance.")

            applied_tuition, applied_mha = calc6_allocate(debt, amount_cents)
            debt["tuition_repaid_cents"] += applied_tuition
            debt["mha_repaid_cents"] += applied_mha
            debt["repaid_cents"] = debt["tuition_repaid_cents"] + debt["mha_repaid_cents"]
            debt["outstanding_cents"] = debt["principal_cents"] - debt["repaid_cents"]
            debt["collection_status"] = ("SATISFIED" if debt["outstanding_cents"] == 0
                                        else "PARTIALLY_REPAID")
            touch(debt)

            if debt["debtor_type"] == "STUDENT":
                student = db.students.get(debt["student_id"])
                if student is not None:
                    student["open_debt_principal_cents"] -= amount_cents
                    touch(student)

            return object_response(serialize(debt))

    @app.post("/benefit-debts/<debt_id>/waive")
    def waive_debt(debt_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            waiver_reason = string_field(data, "waiver_reason")
            require_official(actor)
            debt = get_debt(debt_id)

            if debt["collection_status"] not in DEBT_LIVE:
                fail("ERR_DEBT_ALREADY_SETTLED",
                     "This debt is no longer waivable.")

            report = db.change_reports.get(debt["change_report_id"])
            if report is not None and actor.user_id == report["reconciled_by_official_id"]:
                fail("ERR_WAIVER_SEGREGATION",
                     "The waiving official may not be the reconciling official.")

            outstanding_before = debt["outstanding_cents"]
            debt["collection_status"] = "WAIVED"
            debt["waived_by_official_id"] = actor.user_id
            debt["waiver_reason"] = waiver_reason
            debt["outstanding_cents"] = 0
            touch(debt)

            if debt["debtor_type"] == "STUDENT":
                student = db.students.get(debt["student_id"])
                if student is not None:
                    student["open_debt_principal_cents"] -= outstanding_before
                    touch(student)

            append_audit(debt["certification_id"], "DEBT_WAIVED", actor.role, actor.user_id,
                         "Debt %s waived: %s" % (debt["id"], waiver_reason))
            return object_response(serialize(debt))
