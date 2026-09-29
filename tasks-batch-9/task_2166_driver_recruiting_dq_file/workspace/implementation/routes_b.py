"""Routes: employment verifications, screening checks, Clearinghouse queries,
drug test orders."""
from datetime import timedelta

import calc
import domain
from core import (ALL_ROLES, DB, ROLE_APPLICANT, ROLE_DER, ROLE_RECRUITER,
                  ROLE_SAFETY, actor_id, all_rows, body, created, d, dt, fail,
                  fk, fmt_date, fmt_instant, must_get, new_row, now, ok,
                  qs, req_bool, req_date, req_enum, req_instant, req_int,
                  req_str, require_roles, serialize, today, touch)
from routes_a import filtered, page

EV_TERMINAL = ("RESPONDED_VERIFIED", "RESPONDED_DISPUTED", "GOOD_FAITH_DOCUMENTED")
CHECK_TERMINAL = ("ADJUDICATED_PASS", "ADVERSE_FINAL")
CQ_TERMINAL = ("CONSENT_DENIED", "RESULT_CLEAR", "RESULT_INFO_EXISTS",
               "RESULT_PROHIBITED")
DT_TERMINAL = ("MRO_VERIFIED_NEGATIVE", "MRO_VERIFIED_POSITIVE")


def require_owner(applicant_id):
    if actor_id() != applicant_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Resource belongs to another applicant.")


def guard_application_active(application):
    """Validation priority 24."""
    if (application["qualification_status"] == "DISQUALIFIED"
            or application["screening_status"] == "SCREEN_FAILED"):
        fail("ERR_APPLICATION_NOT_QUALIFIED",
             "The application behind this operation is no longer qualified.")


def register(app):
    # -----------------------------------------------------------------
    # EmploymentVerification
    # -----------------------------------------------------------------
    @app.post("/employment-verifications")
    def verification_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        employer_name = req_str(payload, "employer_name")
        is_dot_regulated = req_bool(payload, "is_dot_regulated")
        employed_from = req_date(payload, "employed_from")
        employed_to = req_date(payload, "employed_to")
        guard_application_active(application)
        if not employed_to > employed_from:
            fail("ERR_VALIDATION", "employed_to must be strictly after employed_from.")
        row = new_row("employment_verifications", {
            "application_id": application["id"],
            "employer_name": employer_name,
            "is_dot_regulated": is_dot_regulated,
            "employed_from": fmt_date(employed_from),
            "employed_to": fmt_date(employed_to),
            "status": "PENDING",
            "request_round": 0,
            "last_requested_at": None,
            "safety_performance_history_received": False,
            "drug_alcohol_violation_reported": False,
        })
        return created(serialize(row))

    @app.get("/employment-verifications/<verification_id>")
    def verification_read(verification_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("employment_verifications", verification_id)))

    @app.get("/employment-verifications")
    def verification_list():
        require_roles(ALL_ROLES)
        return page(filtered("employment_verifications", {
            "application_id": qs("application_id"),
            "status": qs("status"),
        }))

    @app.post("/employment-verifications/<verification_id>/send-request")
    def verification_send_request(verification_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("employment_verifications", verification_id)
        if row["status"] in EV_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Verification is already terminal.")
        if row["status"] not in ("PENDING", "NO_RESPONSE"):
            fail("ERR_INVALID_STATE", "Verification cannot be re-requested from here.")
        if row["status"] == "NO_RESPONSE" and row["request_round"] >= calc.GOOD_FAITH_ROUNDS:
            fail("ERR_INVALID_STATE", "The good-faith request budget is exhausted.")
        application = domain.application_of(row["application_id"])
        if application is not None and application["screening_status"] == "SCREEN_FAILED":
            fail("ERR_INVALID_STATE", "The parent application has failed screening.")
        row["status"] = "REQUESTED"
        row["request_round"] += 1
        row["last_requested_at"] = fmt_instant(now())
        touch(row)
        return ok(serialize(row))

    @app.post("/employment-verifications/<verification_id>/record-response")
    def verification_record_response(verification_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("employment_verifications", verification_id)
        payload = body()
        outcome = req_enum(payload, "outcome", ("VERIFIED", "DISPUTED"))
        sph = req_bool(payload, "safety_performance_history_received")
        dav = req_bool(payload, "drug_alcohol_violation_reported")
        if row["status"] in EV_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Verification is already terminal.")
        if row["status"] != "REQUESTED":
            fail("ERR_INVALID_STATE", "Verification is not in REQUESTED.")
        row["safety_performance_history_received"] = sph
        row["drug_alcohol_violation_reported"] = dav
        application = domain.application_of(row["application_id"])
        if outcome == "VERIFIED":
            row["status"] = "RESPONDED_VERIFIED"
            touch(row)
            if application is not None:
                domain.recompute_coverage(application)
                if application["gap_days_unexplained"] <= calc.MAX_UNEXPLAINED_GAP_DAYS:
                    dq_file = domain.file_of_application(application)
                    if dq_file is not None:
                        domain.set_document(dq_file, "EMPLOYMENT_VERIFICATION",
                                            "PRESENT",
                                            effective_on=fmt_date(today()))
                        domain.recompute_file(dq_file, force_touch=True)
        else:
            row["status"] = "RESPONDED_DISPUTED"
            touch(row)
            if application is not None and dav:
                domain.cascade_screen_fail(application, "PRIOR_DA_VIOLATION")
        return ok(serialize(row))

    @app.post("/employment-verifications/<verification_id>/mark-no-response")
    def verification_mark_no_response(verification_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("employment_verifications", verification_id)
        if row["status"] in EV_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Verification is already terminal.")
        if row["status"] != "REQUESTED":
            fail("ERR_INVALID_STATE", "Verification is not in REQUESTED.")
        last = dt(row.get("last_requested_at"))
        if last is None or now() < last + timedelta(days=calc.NO_RESPONSE_WAIT_DAYS):
            fail("ERR_INVALID_STATE", "The no-response waiting period has not elapsed.")
        if row["request_round"] < calc.GOOD_FAITH_ROUNDS:
            row["status"] = "NO_RESPONSE"
            touch(row)
        else:
            row["status"] = "GOOD_FAITH_DOCUMENTED"
            touch(row)
            application = domain.application_of(row["application_id"])
            if application is not None:
                domain.recompute_coverage(application)
        return ok(serialize(row))

    # -----------------------------------------------------------------
    # ScreeningCheck
    # -----------------------------------------------------------------
    @app.post("/screening-checks")
    def check_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        check_type = req_enum(payload, "check_type", ("MVR", "PSP", "CRIMINAL"))
        for existing in calc.rows_where("screening_checks",
                                        application_id=application["id"]):
            if (existing["check_type"] == check_type
                    and existing["status"] not in CHECK_TERMINAL):
                fail("ERR_INVALID_STATE",
                     "A non-terminal %s check already exists." % check_type)
        guard_application_active(application)
        row = new_row("screening_checks", {
            "application_id": application["id"],
            "check_type": check_type,
            "status": "ORDERED",
            "issued_on": None,
            "expires_on": None,
            "violation_points": 0,
            "serious_violation_count": 0,
            "crash_preventable_count": 0,
            "adjudication_score": 0.0,
            "pre_adverse_at": None,
        })
        if application["screening_status"] == "SUBMITTED":
            application["screening_status"] = "SCREENING"
            touch(application)
        return created(serialize(row))

    @app.get("/screening-checks/<screening_check_id>")
    def check_read(screening_check_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("screening_checks", screening_check_id)))

    @app.get("/screening-checks")
    def check_list():
        require_roles(ALL_ROLES)
        return page(filtered("screening_checks", {
            "application_id": qs("application_id"),
            "check_type": qs("check_type"),
            "status": qs("status"),
        }))

    @app.post("/screening-checks/<screening_check_id>/record-result")
    def check_record_result(screening_check_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("screening_checks", screening_check_id)
        payload = body()
        issued_on = req_date(payload, "issued_on")
        violation_points = req_int(payload, "violation_points", minimum=0)
        serious = req_int(payload, "serious_violation_count", minimum=0)
        crashes = req_int(payload, "crash_preventable_count", minimum=0)
        if row["status"] in CHECK_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Screening check is already terminal.")
        if row["status"] not in ("ORDERED", "DISPUTED"):
            fail("ERR_INVALID_STATE", "Screening check cannot accept a result here.")
        application = domain.application_of(row["application_id"])
        applicant = domain.applicant_of_application(application)
        carrier = domain.carrier_of_application(application)
        row["issued_on"] = fmt_date(issued_on)
        row["violation_points"] = violation_points
        row["serious_violation_count"] = serious
        row["crash_preventable_count"] = crashes
        if row["check_type"] == "MVR":
            validity = int(carrier.get("mvr_validity_days") or 365)
            row["expires_on"] = fmt_date(issued_on + timedelta(days=validity))
        else:
            row["expires_on"] = None
        row["adjudication_score"] = calc.mvr_adjudication_score(row, applicant, carrier)
        row["status"] = "RECEIVED"
        touch(row)
        return ok(serialize(row))

    @app.post("/screening-checks/<screening_check_id>/adjudicate")
    def check_adjudicate(screening_check_id):
        require_roles([ROLE_SAFETY])
        row = must_get("screening_checks", screening_check_id)
        payload = body()
        decision = req_enum(payload, "decision",
                            ("PASS", "PRE_ADVERSE", "ADVERSE_FINAL"))
        if row["status"] in CHECK_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Screening check is already terminal.")
        if decision in ("PASS", "PRE_ADVERSE"):
            if row["status"] != "RECEIVED":
                fail("ERR_INVALID_STATE", "Screening check is not in RECEIVED.")
        else:
            if row["status"] != "PRE_ADVERSE":
                fail("ERR_INVALID_STATE", "Screening check is not in PRE_ADVERSE.")
            opened = dt(row.get("pre_adverse_at"))
            if opened is None or now() < opened + timedelta(days=calc.DISPUTE_WINDOW_DAYS):
                fail("ERR_INVALID_STATE", "The dispute window has not elapsed.")
        application = domain.application_of(row["application_id"])
        carrier = domain.carrier_of_application(application)
        if decision == "PASS":
            if row["check_type"] == "MVR":
                threshold = int(carrier.get("mvr_point_threshold") or 7)
                if float(row.get("adjudication_score") or 0.0) >= threshold:
                    fail("ERR_MVR_POINTS_EXCEEDED",
                         "MVR adjudication score meets or exceeds the threshold.")
            row["status"] = "ADJUDICATED_PASS"
            touch(row)
            dq_file = domain.file_of_application(application)
            if dq_file is not None:
                doc_type = calc.CHECK_TYPE_TO_DOC[row["check_type"]]
                doc = calc.document_of(dq_file, doc_type)
                if doc is not None:
                    doc["status"] = "PRESENT"
                    doc["effective_on"] = row["issued_on"]
                    doc["expires_on"] = row["expires_on"]
                    doc["source_ref"] = row["id"]
                    touch(doc)
                domain.recompute_file(dq_file, force_touch=True)
            domain.evaluate_screen_cleared(application)
        elif decision == "PRE_ADVERSE":
            row["status"] = "PRE_ADVERSE"
            row["pre_adverse_at"] = fmt_instant(now())
            touch(row)
        else:
            row["status"] = "ADVERSE_FINAL"
            touch(row)
            domain.cascade_screen_fail(application, "ADVERSE_SCREENING")
        return ok(serialize(row))

    @app.post("/screening-checks/<screening_check_id>/dispute")
    def check_dispute(screening_check_id):
        require_roles([ROLE_APPLICANT])
        row = must_get("screening_checks", screening_check_id)
        application = domain.application_of(row["application_id"])
        require_owner(application["applicant_id"] if application else None)
        payload = body()
        req_str(payload, "dispute_note")
        if row["status"] in CHECK_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Screening check is already terminal.")
        if row["status"] != "PRE_ADVERSE":
            fail("ERR_INVALID_STATE", "Screening check is not in PRE_ADVERSE.")
        opened = dt(row.get("pre_adverse_at"))
        if opened is None or now() >= opened + timedelta(days=calc.DISPUTE_WINDOW_DAYS):
            fail("ERR_INVALID_STATE", "The dispute window has closed.")
        row["status"] = "DISPUTED"
        row["pre_adverse_at"] = None
        touch(row)
        return ok(serialize(row))

    # -----------------------------------------------------------------
    # ClearinghouseQuery
    # -----------------------------------------------------------------
    @app.post("/clearinghouse-queries")
    def query_create():
        require_roles([ROLE_DER])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        query_type = req_enum(payload, "query_type", ("LIMITED", "FULL"))
        guard_application_active(application)
        row = new_row("clearinghouse_queries", {
            "application_id": application["id"],
            "query_type": query_type,
            "status": "CONSENT_PENDING",
            "consent_granted_at": None,
            "consent_expires_on": None,
            "result": "PENDING",
            "follow_up_full_query_id": None,
        })
        if query_type == "FULL":
            for other in calc.rows_where("clearinghouse_queries",
                                         application_id=application["id"]):
                if (other["id"] != row["id"] and other["query_type"] == "LIMITED"
                        and other["status"] == "RESULT_INFO_EXISTS"
                        and other.get("follow_up_full_query_id") is None):
                    other["follow_up_full_query_id"] = row["id"]
                    touch(other)
        return created(serialize(row))

    @app.get("/clearinghouse-queries/<clearinghouse_query_id>")
    def query_read(clearinghouse_query_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("clearinghouse_queries",
                                     clearinghouse_query_id)))

    @app.get("/clearinghouse-queries")
    def query_list():
        require_roles(ALL_ROLES)
        return page(filtered("clearinghouse_queries", {
            "application_id": qs("application_id"),
            "query_type": qs("query_type"),
            "status": qs("status"),
            "follow_up_full_query_id": qs("follow_up_full_query_id"),
        }))

    @app.post("/clearinghouse-queries/<clearinghouse_query_id>/consent-decision")
    def query_consent(clearinghouse_query_id):
        require_roles([ROLE_APPLICANT])
        row = must_get("clearinghouse_queries", clearinghouse_query_id)
        application = domain.application_of(row["application_id"])
        require_owner(application["applicant_id"] if application else None)
        payload = body()
        decision = req_enum(payload, "decision", ("GRANT", "DENY"))
        if row["status"] in CQ_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Clearinghouse query is already terminal.")
        if row["status"] != "CONSENT_PENDING":
            fail("ERR_INVALID_STATE", "Clearinghouse query is not in CONSENT_PENDING.")
        if decision == "GRANT":
            row["status"] = "CONSENT_GRANTED"
            row["consent_granted_at"] = fmt_instant(now())
            row["consent_expires_on"] = fmt_date(
                today() + timedelta(days=calc.CONSENT_VALIDITY_DAYS))
            touch(row)
        else:
            row["status"] = "CONSENT_DENIED"
            touch(row)
            if application is not None:
                domain.cascade_screen_fail(application, "CONSENT_REFUSED")
        return ok(serialize(row))

    @app.post("/clearinghouse-queries/<clearinghouse_query_id>/record-result")
    def query_record_result(clearinghouse_query_id):
        require_roles([ROLE_DER])
        row = must_get("clearinghouse_queries", clearinghouse_query_id)
        payload = body()
        result = req_enum(payload, "result",
                          ("NO_INFO", "INFORMATION_EXISTS", "PROHIBITED"))
        if row["status"] != "CONSENT_GRANTED":
            fail("ERR_CONSENT_NOT_GRANTED",
                 "This query does not carry a granted consent.")
        if result == "INFORMATION_EXISTS" and row["query_type"] != "LIMITED":
            fail("ERR_INVALID_STATE",
                 "INFORMATION_EXISTS may only be recorded on a LIMITED query.")
        if result == "PROHIBITED" and row["query_type"] != "FULL":
            fail("ERR_INVALID_STATE",
                 "PROHIBITED may only be recorded on a FULL query.")
        expires = d(row.get("consent_expires_on"))
        if expires is None or today() > expires:
            fail("ERR_CONSENT_EXPIRED", "The Clearinghouse consent has expired.")
        application = domain.application_of(row["application_id"])
        row["result"] = result
        if result == "NO_INFO":
            row["status"] = "RESULT_CLEAR"
            touch(row)
            dq_file = domain.file_of_application(application) if application else None
            if dq_file is not None:
                domain.set_document(dq_file, "CLEARINGHOUSE_QUERY", "PRESENT",
                                    effective_on=fmt_date(today()),
                                    source_ref=row["id"])
                domain.recompute_file(dq_file, force_touch=True)
            if application is not None:
                domain.evaluate_screen_cleared(application)
        elif result == "INFORMATION_EXISTS":
            row["status"] = "RESULT_INFO_EXISTS"
            touch(row)
        else:
            row["status"] = "RESULT_PROHIBITED"
            touch(row)
            if application is not None:
                domain.cascade_screen_fail(application, "CLEARINGHOUSE_PROHIBITED")
        return ok(serialize(row))

    # -----------------------------------------------------------------
    # DrugTestOrder
    # -----------------------------------------------------------------
    @app.post("/drug-test-orders")
    def order_create():
        require_roles([ROLE_DER])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        test_type = req_enum(payload, "test_type",
                             ("PRE_EMPLOYMENT", "RETURN_TO_DUTY"))
        guard_application_active(application)
        row = new_row("drug_test_orders", {
            "application_id": application["id"],
            "test_type": test_type,
            "status": "ORDERED",
            "collected_at": None,
            "dilute_recollect_count": 0,
        })
        return created(serialize(row))

    @app.get("/drug-test-orders/<drug_test_order_id>")
    def order_read(drug_test_order_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("drug_test_orders", drug_test_order_id)))

    @app.get("/drug-test-orders")
    def order_list():
        require_roles(ALL_ROLES)
        return page(filtered("drug_test_orders", {
            "application_id": qs("application_id"),
            "status": qs("status"),
        }))

    @app.post("/drug-test-orders/<drug_test_order_id>/record-collection")
    def order_record_collection(drug_test_order_id):
        require_roles([ROLE_DER])
        row = must_get("drug_test_orders", drug_test_order_id)
        payload = body()
        collected_at = req_instant(payload, "collected_at")
        if row["status"] in DT_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Drug test order is already terminal.")
        if row["status"] not in ("ORDERED", "LAB_DILUTE"):
            fail("ERR_INVALID_STATE", "Drug test order cannot be collected here.")
        if row["status"] == "LAB_DILUTE":
            if row["dilute_recollect_count"] >= calc.MAX_DILUTE_RECOLLECTIONS:
                fail("ERR_INVALID_STATE",
                     "The permitted dilute recollection has already been used.")
            row["dilute_recollect_count"] += 1
        row["collected_at"] = fmt_instant(collected_at)
        row["status"] = "COLLECTED"
        touch(row)
        return ok(serialize(row))

    @app.post("/drug-test-orders/<drug_test_order_id>/record-lab-result")
    def order_record_lab(drug_test_order_id):
        require_roles([ROLE_DER])
        row = must_get("drug_test_orders", drug_test_order_id)
        payload = body()
        lab_result = req_enum(payload, "lab_result",
                              ("NEGATIVE", "POSITIVE", "DILUTE"))
        if row["status"] in DT_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Drug test order is already terminal.")
        if row["status"] != "COLLECTED":
            fail("ERR_INVALID_STATE", "Drug test order is not in COLLECTED.")
        row["status"] = {"NEGATIVE": "LAB_NEGATIVE",
                         "POSITIVE": "LAB_POSITIVE",
                         "DILUTE": "LAB_DILUTE"}[lab_result]
        touch(row)
        return ok(serialize(row))

    @app.post("/drug-test-orders/<drug_test_order_id>/record-mro-verification")
    def order_record_mro(drug_test_order_id):
        require_roles([ROLE_DER])
        row = must_get("drug_test_orders", drug_test_order_id)
        payload = body()
        decision = req_enum(payload, "mro_decision",
                            ("VERIFIED_NEGATIVE", "VERIFIED_POSITIVE"))
        if row["status"] in DT_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Drug test order is already terminal.")
        if decision == "VERIFIED_NEGATIVE":
            if row["status"] not in ("LAB_NEGATIVE", "LAB_POSITIVE"):
                fail("ERR_INVALID_STATE",
                     "Drug test order has no laboratory result to verify.")
        else:
            if row["status"] != "LAB_POSITIVE":
                fail("ERR_INVALID_STATE",
                     "A positive verification requires a positive laboratory result.")
        application = domain.application_of(row["application_id"])
        if decision == "VERIFIED_NEGATIVE":
            row["status"] = "MRO_VERIFIED_NEGATIVE"
            touch(row)
            dq_file = domain.file_of_application(application) if application else None
            if dq_file is not None:
                domain.set_document(dq_file, "DRUG_TEST_RESULT", "PRESENT",
                                    effective_on=fmt_date(today()),
                                    source_ref=row["id"])
                domain.recompute_file(dq_file, force_touch=True)
            if application is not None:
                domain.evaluate_screen_cleared(application)
        else:
            row["status"] = "MRO_VERIFIED_POSITIVE"
            touch(row)
            if application is not None:
                domain.cascade_screen_fail(application, "DRUG_TEST_POSITIVE")
        return ok(serialize(row))
