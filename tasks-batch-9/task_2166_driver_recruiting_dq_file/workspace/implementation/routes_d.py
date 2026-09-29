"""Routes: DQ files, DQ documents, tuition agreements and hire records."""
from datetime import timedelta

import calc
import domain
from core import (ALL_ROLES, DB, ROLE_AUDITOR, ROLE_RECRUITER, ROLE_SAFETY,
                  ROLE_SCHOOL, actor_id, all_rows, body, created, d, dt, fail,
                  fk, fmt_date, fmt_instant, must_get, new_row, now, ok,
                  opt_date, opt_str, qs, req_date, req_enum, req_int, req_str,
                  require_roles, serialize, today, touch)
from routes_a import filtered, page

DOC_STATUSES = ("MISSING", "PRESENT", "EXPIRED", "WAIVED")
TERMINATION_TYPES = ("NONE", "VOLUNTARY", "INVOLUNTARY_PERFORMANCE",
                     "INVOLUNTARY_SAFETY", "ABANDONMENT")
REHIRE_FLAGS = ("ELIGIBLE", "NOT_ELIGIBLE", "CONDITIONAL")
HIRE_TERMINAL = ("TERMINATED", "RESCINDED")
TUITION_TERMINAL = ("FULFILLED",)


def register(app):
    # -----------------------------------------------------------------
    # DqFile
    # -----------------------------------------------------------------
    @app.get("/dq-files/<dq_file_id>")
    def dq_file_read(dq_file_id):
        require_roles(ALL_ROLES)
        dq_file = must_get("dq_files", dq_file_id)
        domain.refresh_file_silent(dq_file)
        return ok(serialize(dq_file))

    @app.get("/dq-files")
    def dq_file_list():
        require_roles(ALL_ROLES)
        for dq_file in all_rows("dq_files"):
            domain.refresh_file_silent(dq_file)
        return page(filtered("dq_files", {
            "application_id": qs("application_id"),
            "status": qs("status"),
            "review_state": qs("review_state"),
        }))

    @app.get("/dq-files/<dq_file_id>/completeness")
    def dq_file_completeness(dq_file_id):
        require_roles(ALL_ROLES)
        dq_file = must_get("dq_files", dq_file_id)
        variant = qs("variant") or "pre_hire_provisional"
        if variant not in calc.VARIANTS_COMPLETENESS:
            fail("ERR_VALIDATION", "variant is not a declared member.")
        result = calc.dq_completeness(dq_file, variant)
        result.pop("_pct_decimal", None)
        return ok(result)

    @app.post("/dq-files/<dq_file_id>/annual-review")
    def dq_file_annual_review(dq_file_id):
        require_roles([ROLE_AUDITOR])
        dq_file = must_get("dq_files", dq_file_id)
        payload = body()
        req_str(payload, "certification_note")
        if dq_file["status"] == "ARCHIVED":
            fail("ERR_INVALID_STATE", "The qualification file is archived.")
        application = domain.application_of_file(dq_file)
        recruiter_user_id = application.get("recruiter_user_id") if application else None
        if recruiter_user_id is not None and actor_id() == recruiter_user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The auditor may not certify a file they recruited.")
        current = None
        for check in calc.rows_where("screening_checks",
                                     application_id=dq_file["application_id"]):
            if check["check_type"] != "MVR" or check["status"] != "ADJUDICATED_PASS":
                continue
            expires = d(check.get("expires_on"))
            if expires is not None and expires >= today():
                current = check
                break
        if current is None:
            fail("ERR_MVR_EXPIRED", "No current MVR check backs this annual review.")
        domain.refresh_file_silent(dq_file)
        if dq_file["review_state"] not in ("DUE", "OVERDUE"):
            fail("ERR_REVIEW_NOT_DUE", "The annual review is not due yet.")
        carrier = domain.carrier_of_application(application)
        dq_file["last_annual_review_at"] = fmt_instant(now())
        dq_file["certified_by_user_id"] = actor_id()
        domain.set_document(dq_file, "MVR_ANNUAL", "PRESENT",
                            effective_on=fmt_date(today()))
        domain.set_document(dq_file, "ANNUAL_REVIEW_CERT", "PRESENT",
                            effective_on=fmt_date(today()))
        interval = int(carrier.get("annual_review_interval_days") or 365)
        dq_file["next_review_due_on"] = fmt_date(today() + timedelta(days=interval))
        dq_file["review_state"] = "NOT_DUE"
        domain.recompute_file(dq_file, force_touch=True)
        return ok(serialize(dq_file))

    @app.post("/dq-files/<dq_file_id>/revoke-certification")
    def dq_file_revoke(dq_file_id):
        require_roles([ROLE_AUDITOR])
        dq_file = must_get("dq_files", dq_file_id)
        payload = body()
        req_str(payload, "reason")
        if dq_file["status"] == "ARCHIVED":
            fail("ERR_INVALID_STATE", "The qualification file is archived.")
        if dq_file.get("last_annual_review_at") is None:
            fail("ERR_INVALID_STATE", "The file carries no certification to revoke.")
        application = domain.application_of_file(dq_file)
        recruiter_user_id = application.get("recruiter_user_id") if application else None
        if recruiter_user_id is not None and actor_id() == recruiter_user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The auditor may not revoke a file they recruited.")
        dq_file["last_annual_review_at"] = None
        dq_file["certified_by_user_id"] = None
        domain.set_document(dq_file, "MVR_ANNUAL", "MISSING", clear_effective=True)
        domain.set_document(dq_file, "ANNUAL_REVIEW_CERT", "MISSING",
                            clear_effective=True)
        domain.recompute_review(dq_file)
        domain.recompute_file(dq_file, force_touch=True)
        return ok(serialize(dq_file))

    # -----------------------------------------------------------------
    # DqDocument
    # -----------------------------------------------------------------
    @app.get("/dq-documents/<document_id>")
    def dq_document_read(document_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("dq_documents", document_id)))

    @app.get("/dq-documents")
    def dq_document_list():
        require_roles(ALL_ROLES)
        return page(filtered("dq_documents", {
            "dq_file_id": qs("dq_file_id"),
            "doc_type": qs("doc_type"),
            "status": qs("status"),
        }))

    @app.put("/dq-documents/<document_id>")
    def dq_document_write(document_id):
        require_roles([ROLE_RECRUITER])
        doc = must_get("dq_documents", document_id)
        payload = body()
        status = req_enum(payload, "status", DOC_STATUSES)
        expected = req_int(payload, "expected_dq_file_version")
        effective_on = opt_date(payload, "effective_on")
        expires_on = opt_date(payload, "expires_on")
        source_ref = opt_str(payload, "source_ref")
        dq_file = DB["dq_files"].get(doc["dq_file_id"])
        if dq_file is None:
            fail("ERR_DQ_FILE_NOT_FOUND", "The parent qualification file is missing.")
        if expected != dq_file["version"]:
            fail("ERR_STALE_VERSION", "expected_dq_file_version does not match.")
        doc["status"] = status
        if "effective_on" in payload:
            doc["effective_on"] = fmt_date(effective_on) if effective_on else None
        if "expires_on" in payload:
            doc["expires_on"] = fmt_date(expires_on) if expires_on else None
        if "source_ref" in payload:
            doc["source_ref"] = source_ref
        touch(doc)
        domain.recompute_file(dq_file, force_touch=True)
        application = domain.application_of_file(dq_file)
        if application is not None:
            if doc["doc_type"] == "MEDICAL_CERT":
                domain.recompute_applicant(
                    domain.applicant_of_application(application))
            domain.evaluate_qualified_join(application)
            domain.recompute_carrier(domain.carrier_of_application(application))
        return ok(serialize(doc))

    # -----------------------------------------------------------------
    # TuitionAgreement
    # -----------------------------------------------------------------
    @app.post("/tuition-agreements")
    def tuition_create():
        require_roles([ROLE_SCHOOL])
        payload = body()
        applicant = fk(payload, "applicant_id", "driver_applicants")
        if applicant is None:
            req_str(payload, "applicant_id")
            fail("ERR_VALIDATION", "applicant_id must be a valid identifier.")
        school_name = req_str(payload, "school_name")
        total_cents = req_int(payload, "tuition_total_cents", minimum=1)
        commitment_months = req_int(payload, "commitment_months", minimum=1)
        row = new_row("tuition_agreements", {
            "applicant_id": applicant["id"],
            "school_name": school_name,
            "tuition_total_cents": total_cents,
            "commitment_months": commitment_months,
            "base_monthly_cents": 0,
            "monthly_reimbursement_cents": 0,
            "forgiven_cents": 0,
            "months_served": 0,
            "reimbursed_cents": 0,
            "bonus_paid_cents": 0,
            "clawback_cents": 0,
            "outstanding_cents": 0,
            "status": "PENDING",
        })
        return created(serialize(row))

    @app.get("/tuition-agreements/<tuition_agreement_id>")
    def tuition_read(tuition_agreement_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("tuition_agreements", tuition_agreement_id)))

    @app.get("/tuition-agreements")
    def tuition_list():
        require_roles(ALL_ROLES)
        return page(filtered("tuition_agreements", {
            "applicant_id": qs("applicant_id"),
            "status": qs("status"),
        }))

    @app.post("/tuition-agreements/<tuition_agreement_id>/activate")
    def tuition_activate(tuition_agreement_id):
        require_roles([ROLE_SCHOOL])
        row = must_get("tuition_agreements", tuition_agreement_id)
        if row["status"] in TUITION_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "The agreement is already fulfilled.")
        if row["status"] != "PENDING":
            fail("ERR_INVALID_STATE", "The agreement is not PENDING.")
        has_active_hire = any(
            h["applicant_id"] == row["applicant_id"] and h["status"] == "ACTIVE"
            for h in all_rows("hire_records"))
        if not has_active_hire:
            fail("ERR_INVALID_STATE",
                 "The applicant holds no ACTIVE hire record.")
        schedule = calc.tuition_schedule(row["tuition_total_cents"],
                                         row["commitment_months"])
        row.update(schedule)
        row["status"] = "ACTIVE"
        touch(row)
        return ok(serialize(row))

    @app.post("/tuition-agreements/<tuition_agreement_id>/accrue-month")
    def tuition_accrue(tuition_agreement_id):
        require_roles([ROLE_SCHOOL])
        row = must_get("tuition_agreements", tuition_agreement_id)
        payload = body()
        req_str(payload, "service_month")
        if row["months_served"] >= row["commitment_months"]:
            fail("ERR_COMMITMENT_ALREADY_FULFILLED",
                 "The service commitment is already fulfilled.")
        if row["status"] in TUITION_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "The agreement is already fulfilled.")
        if row["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The agreement is not ACTIVE.")
        row["months_served"] += 1
        row["reimbursed_cents"] = row["months_served"] * row["base_monthly_cents"]
        row["bonus_paid_cents"] = row["months_served"] * (
            row["monthly_reimbursement_cents"] - row["base_monthly_cents"])
        row["outstanding_cents"] = (row["tuition_total_cents"]
                                    - row["forgiven_cents"]
                                    - row["reimbursed_cents"]
                                    - row["clawback_cents"])
        if row["months_served"] >= row["commitment_months"]:
            row["status"] = "FULFILLED"
        touch(row)
        return ok(serialize(row))

    @app.post("/tuition-agreements/<tuition_agreement_id>/reverse-clawback")
    def tuition_reverse(tuition_agreement_id):
        require_roles([ROLE_SCHOOL])
        row = must_get("tuition_agreements", tuition_agreement_id)
        payload = body()
        req_str(payload, "reason")
        if int(row.get("clawback_cents") or 0) <= 0:
            fail("ERR_NO_CLAWBACK_TO_REVERSE", "There is no clawback to reverse.")
        if row["status"] != "TERMINATED_CLAWBACK":
            fail("ERR_INVALID_STATE", "The agreement carries no clawback state.")
        row["outstanding_cents"] = row["clawback_cents"]
        row["clawback_cents"] = 0
        row["status"] = "ACTIVE"
        touch(row)
        domain.recompute_applicant(DB["driver_applicants"].get(row["applicant_id"]))
        return ok(serialize(row))

    # -----------------------------------------------------------------
    # HireRecord
    # -----------------------------------------------------------------
    @app.post("/hire-records")
    def hire_create():
        require_roles([ROLE_SAFETY])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        hired_on = req_date(payload, "hired_on")
        expected = req_int(payload, "expected_carrier_version")
        carrier = domain.carrier_of_application(application)
        applicant = domain.applicant_of_application(application)
        if expected != carrier["version"]:
            fail("ERR_STALE_VERSION", "expected_carrier_version does not match.")
        if application["qualification_status"] != "QUALIFIED":
            fail("ERR_APPLICATION_NOT_QUALIFIED",
                 "The application is not QUALIFIED.")
        if domain.clearinghouse_blocked(application):
            fail("ERR_CLEARINGHOUSE_PROHIBITED",
                 "The Clearinghouse picture is unresolved or prohibited.")
        if not domain.has_negative_pre_employment(application):
            fail("ERR_DRUG_TEST_NOT_NEGATIVE",
                 "No verified-negative pre-employment specimen exists.")
        band = calc.cdl_downgrade_risk(applicant, carrier)["cdl_downgrade_risk"]
        if band in ("DOWNGRADED", "NO_CERTIFICATE"):
            fail("ERR_MEDICAL_CERT_INVALID",
                 "The applicant's medical certificate does not support a hire.")
        dq_file = domain.file_of_application(application)
        if dq_file is None or dq_file["status"] != "COMPLETE":
            fail("ERR_DQ_FILE_INCOMPLETE", "The qualification file is not COMPLETE.")
        if application["gap_days_unexplained"] > calc.MAX_UNEXPLAINED_GAP_DAYS:
            fail("ERR_EMPLOYMENT_HISTORY_INCOMPLETE",
                 "Unexplained employment gap exceeds the permitted window.")
        verdict = calc.rehire_eligibility(applicant, carrier)["rehire_eligibility"]
        if verdict != "ELIGIBLE":
            fail("ERR_REHIRE_INELIGIBLE", "The applicant is not re-hire eligible.")
        posture = calc.carrier_posture(carrier)
        if posture["posture"] == "FROZEN":
            fail("ERR_CARRIER_POSTURE_BLOCKED", "The carrier posture is FROZEN.")
        if posture["filled_requisitions"] >= carrier["open_requisitions"]:
            fail("ERR_NO_OPEN_REQUISITION", "No funded requisition seat is open.")
        prior_candidates = [
            h for h in all_rows("hire_records")
            if h["applicant_id"] == applicant["id"]
            and h["carrier_id"] == carrier["id"]
            and h["status"] == "TERMINATED"
        ]
        prior_candidates.sort(
            key=lambda h: (d(h["terminated_on"]), h["created_at"], h["_seq"]),
            reverse=True)
        prior_hire_id = prior_candidates[0]["id"] if prior_candidates else None
        row = new_row("hire_records", {
            "application_id": application["id"],
            "applicant_id": applicant["id"],
            "carrier_id": carrier["id"],
            "prior_hire_id": prior_hire_id,
            "hired_on": fmt_date(hired_on),
            "terminated_on": None,
            "termination_type": "NONE",
            "rehire_flag": "ELIGIBLE",
            "tenure_days": 0,
            "status": "ACTIVE",
        })
        application["qualification_status"] = "HIRED"
        touch(application)
        domain.recompute_carrier(carrier)
        touch(carrier)
        return created(serialize(row))

    @app.get("/hire-records/<hire_record_id>")
    def hire_read(hire_record_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("hire_records", hire_record_id)))

    @app.get("/hire-records")
    def hire_list():
        require_roles(ALL_ROLES)
        return page(filtered("hire_records", {
            "application_id": qs("application_id"),
            "applicant_id": qs("applicant_id"),
            "carrier_id": qs("carrier_id"),
            "prior_hire_id": qs("prior_hire_id"),
            "status": qs("status"),
        }))

    @app.post("/hire-records/<hire_record_id>/terminate")
    def hire_terminate(hire_record_id):
        require_roles([ROLE_SAFETY])
        row = must_get("hire_records", hire_record_id)
        payload = body()
        terminated_on = req_date(payload, "terminated_on")
        termination_type = req_enum(payload, "termination_type", TERMINATION_TYPES)
        rehire_flag = req_enum(payload, "rehire_flag", REHIRE_FLAGS)
        if row["status"] in HIRE_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "The hire record is already terminal.")
        if row["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The hire record is not ACTIVE.")
        hired_on = d(row["hired_on"])
        if terminated_on < hired_on:
            fail("ERR_VALIDATION", "terminated_on must be on or after hired_on.")
        # HOP 1
        row["status"] = "TERMINATED"
        row["terminated_on"] = fmt_date(terminated_on)
        row["termination_type"] = termination_type
        row["rehire_flag"] = rehire_flag
        row["tenure_days"] = (terminated_on - hired_on).days
        touch(row)
        applicant = DB["driver_applicants"].get(row["applicant_id"])
        # HOP 2
        for agreement in all_rows("tuition_agreements"):
            if (agreement["applicant_id"] == row["applicant_id"]
                    and agreement["status"] == "ACTIVE"):
                agreement["clawback_cents"] = agreement["outstanding_cents"]
                agreement["outstanding_cents"] = 0
                agreement["status"] = "TERMINATED_CLAWBACK"
                touch(agreement)
        # HOP 3
        if applicant is not None:
            domain.recompute_applicant(applicant)
            # HOP 4
            if applicant["rehire_eligibility"] == "PERMANENTLY_INELIGIBLE":
                for application in all_rows("driver_applications"):
                    if application["applicant_id"] != applicant["id"]:
                        continue
                    if application["qualification_status"] in domain.APP_QUAL_TERMINAL:
                        continue
                    domain.cascade_disqualify(application, "REHIRE_INELIGIBLE")
        carrier = DB["carriers"].get(row["carrier_id"])
        domain.recompute_carrier(carrier)
        touch(carrier)
        return ok(serialize(row))

    @app.post("/hire-records/<hire_record_id>/rescind")
    def hire_rescind(hire_record_id):
        require_roles([ROLE_SAFETY])
        row = must_get("hire_records", hire_record_id)
        payload = body()
        req_str(payload, "reason")
        if row["status"] in HIRE_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "The hire record is already terminal.")
        if row["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The hire record is not ACTIVE.")
        for agreement in all_rows("tuition_agreements"):
            if (agreement["applicant_id"] == row["applicant_id"]
                    and agreement["status"] == "TERMINATED_CLAWBACK"):
                fail("ERR_INVALID_STATE",
                     "A tuition clawback stands against this applicant.")
        row["status"] = "RESCINDED"
        touch(row)
        application = domain.application_of(row["application_id"])
        if application is not None and application["qualification_status"] == "HIRED":
            application["qualification_status"] = "QUALIFIED"
            touch(application)
        applicant = DB["driver_applicants"].get(row["applicant_id"])
        if applicant is not None:
            domain.recompute_applicant(applicant)
        carrier = DB["carriers"].get(row["carrier_id"])
        domain.recompute_carrier(carrier)
        touch(carrier)
        return ok(serialize(row))
