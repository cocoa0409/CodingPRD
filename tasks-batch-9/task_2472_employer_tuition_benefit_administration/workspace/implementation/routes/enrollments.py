"""Enrollments, registration, outcomes and coaching."""

from decimal import Decimal

from flask import g

import domain
import serialize
from auth import employee_scope, employer_scope, endpoint, school_scope
from errors import fail, invalid
from store import db, new_record, touch
from validate import (
    COMPLETION_STATUSES,
    FUNDING_MODELS,
    MODALITIES,
    RISK_FLAGS,
    array_field,
    body,
    date_field,
    enum_field,
    int_field,
    iso_date,
    nullable_text,
    number_field,
    pagination,
    query_enum,
    query_str,
    string_field,
)

from .common import filter_eq, object_response, paged

ACADEMIC_STATUSES = ["REGISTERED", "IN_PROGRESS", "PASSED", "FAILED", "WITHDRAWN", "INCOMPLETE"]
FUNDING_STATUSES = ["RESERVED", "BILLED", "SETTLED", "RELEASED", "CLAWED_BACK"]
INVOICE_STATUSES = ["ISSUED", "APPROVED_FOR_PAYMENT", "PAID", "VOIDED"]
CLAIM_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED"]
OBLIGATION_STATUSES = ["ASSESSED", "PARTIALLY_PAID", "SETTLED", "WAIVED"]


def own_enrollment(enrollment):
    """Rule 16 for every resource hanging off an enrollment."""
    employee = db.employees[enrollment["employee_id"]]
    employee_scope(employee["id"])
    employer_scope(employee["employer_id"])
    school_scope(domain.enrollment_school_id(enrollment))
    return employee


def register(app):
    # --------------------------------------------------------------- enrollments
    @app.post("/enrollments")
    @endpoint(["Employee"])
    def create_enrollment():
        data = body()
        employee_id = string_field(data, "employee_id")
        catalog_listing_id = string_field(data, "catalog_listing_id")
        term_code = string_field(data, "term_code", max_len=16)
        term_start_date = date_field(data, "term_start_date")
        term_end_date = date_field(data, "term_end_date")
        credits = int_field(data, "credits", minimum=1, maximum=30)
        expected_employee_version = int_field(data, "expected_employee_version")
        supplied_model = enum_field(
            data, "funding_model", FUNDING_MODELS, required=False, default=None
        )
        if term_end_date <= term_start_date:
            invalid("'term_end_date' must be strictly after 'term_start_date'")

        employee = domain.must(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
        listing = domain.must(db.listings, catalog_listing_id, "ERR_LISTING_NOT_FOUND")

        employee_scope(employee_id)

        if expected_employee_version != employee["version"]:
            fail(
                "ERR_STALE_EMPLOYEE_VERSION",
                "expected_employee_version %s but the employee is at version %s"
                % (expected_employee_version, employee["version"]),
            )

        if listing["status"] != "CURATED":
            fail("ERR_LISTING_NOT_CURATED", "listing is %s, not CURATED" % listing["status"])

        employer = db.employers[employee["employer_id"]]
        policy = domain.current_policy(employer["id"])
        if policy is None:
            fail("ERR_NO_ACTIVE_POLICY", "the employer has no current benefit policy")

        if employee["eligibility_status"] in (
            "INELIGIBLE_EMPLOYMENT",
            "INELIGIBLE_HOURS",
            "INELIGIBLE_JOB_FAMILY",
        ):
            fail("ERR_EMPLOYEE_NOT_ELIGIBLE", "employee is %s" % employee["eligibility_status"])
        if employee["tenure_months"] < policy["min_tenure_months"]:
            fail("ERR_EMPLOYEE_TENURE_NOT_MET", "tenure is below the policy minimum")
        if employee["coaching_hold"]:
            fail("ERR_COACHING_HOLD_ACTIVE", "a high-risk enrollment holds further study")

        concurrent = credits
        for other in domain.enrollments_of_employee(employee_id):
            if other["academic_status"] not in domain.OPEN_ACADEMIC_STATES:
                continue
            if (
                iso_date(other["term_start_date"]) <= term_end_date
                and term_start_date <= iso_date(other["term_end_date"])
            ):
                concurrent += other["credits"]
        if concurrent > policy["max_concurrent_credits"]:
            fail(
                "ERR_CONCURRENT_CREDIT_LIMIT",
                "%d concurrent credits exceeds the policy ceiling of %d"
                % (concurrent, policy["max_concurrent_credits"]),
            )

        for other in domain.enrollments_of_employee(employee_id):
            if (
                other["catalog_listing_id"] == catalog_listing_id
                and other["term_code"] == term_code
                and other["academic_status"] not in ("WITHDRAWN", "FAILED")
            ):
                fail("ERR_DUPLICATE_ENROLLMENT", "this term is already enrolled")

        policy_model = policy["funding_model"]
        if policy_model == "HYBRID":
            effective_model = supplied_model
        else:
            effective_model = supplied_model if supplied_model is not None else policy_model
        if effective_model not in listing["allowed_funding_models"] or (
            policy_model != "HYBRID" and effective_model != policy_model
        ):
            fail(
                "ERR_FUNDING_MODEL_NOT_ALLOWED",
                "funding model %s is not available on this listing" % effective_model,
            )

        if employee["cap_available_cents"] <= 0:
            fail("ERR_ANNUAL_CAP_EXCEEDED", "no annual cap headroom remains for the plan year")

        gross, reserved = domain.provisional_reserve(
            listing, policy, credits, effective_model, employee["cap_available_cents"]
        )

        row = new_record(
            {
                "employee_id": employee_id,
                "catalog_listing_id": catalog_listing_id,
                "policy_id": policy["id"],
                "term_code": term_code,
                "term_start_date": term_start_date.isoformat(),
                "term_end_date": term_end_date.isoformat(),
                "credits": credits,
                "funding_model": effective_model,
                "plan_year": domain.plan_year_of(term_start_date, employer),
                "drop_deadline_date": domain.add_days(
                    term_start_date, policy["drop_window_days"]
                ).isoformat(),
                "gross_tuition_cents": gross,
                "employer_reserved_cents": reserved,
                "employer_settled_cents": 0,
                "employer_disbursed_cents": 0,
                "academic_status": "REGISTERED",
                "funding_status": "RESERVED",
                "credits_earned": 0,
                "persistence_risk_score": 0,
                "persistence_tier": "LOW",
                "last_session_date": None,
            }
        )
        db.enrollments[row["id"]] = row
        domain.recompute_persistence(row)
        domain.refresh_employee(employee)
        touch(employee)
        return object_response(serialize.enrollment(row), 201)

    @app.get("/enrollments")
    @endpoint(["Employee", "BenefitAdministrator", "Coach", "SchoolPartner"])
    def list_enrollments():
        limit, offset = pagination()
        academic_status = query_enum("academic_status", ACADEMIC_STATUSES)
        funding_status = query_enum("funding_status", FUNDING_STATUSES)
        rows = list(db.enrollments.values())
        rows = filter_eq(rows, "employee_id", query_str("employee_id"))
        rows = filter_eq(rows, "catalog_listing_id", query_str("catalog_listing_id"))
        rows = filter_eq(rows, "policy_id", query_str("policy_id"))
        rows = filter_eq(rows, "term_code", query_str("term_code"))
        rows = filter_eq(rows, "academic_status", academic_status)
        rows = filter_eq(rows, "funding_status", funding_status)
        return paged(rows, serialize.enrollment, limit, offset)

    @app.get("/enrollments/<enrollment_id>")
    @endpoint(["Employee", "BenefitAdministrator", "Coach", "SchoolPartner"])
    def read_enrollment(enrollment_id):
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        return object_response(serialize.enrollment(enrollment))

    @app.post("/enrollments/<enrollment_id>/confirm-registration")
    @endpoint(["SchoolPartner"])
    def confirm_registration(enrollment_id):
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        employee = own_enrollment(enrollment)
        listing = db.listings[enrollment["catalog_listing_id"]]
        if listing["status"] != "CURATED":
            fail("ERR_LISTING_NOT_CURATED", "listing is %s, not CURATED" % listing["status"])
        if enrollment["academic_status"] != "REGISTERED":
            fail(
                "ERR_ENROLLMENT_INVALID_ACADEMIC_STATE",
                "enrollment is %s, not REGISTERED" % enrollment["academic_status"],
            )
        if enrollment["funding_status"] != "RESERVED":
            fail(
                "ERR_ENROLLMENT_INVALID_FUNDING_STATE",
                "funding is %s, not RESERVED" % enrollment["funding_status"],
            )

        enrollment["academic_status"] = "IN_PROGRESS"
        if enrollment["funding_model"] == "DIRECT_BILL":
            invoice = new_record(
                {
                    "enrollment_id": enrollment["id"],
                    "amount_cents": enrollment["employer_reserved_cents"],
                    "due_date": domain.add_days(
                        iso_date(enrollment["term_start_date"]), 30
                    ).isoformat(),
                    "status": "ISSUED",
                    "paid_on": None,
                }
            )
            db.invoices[invoice["id"]] = invoice
            enrollment["funding_status"] = "BILLED"
        domain.recompute_persistence(enrollment)
        touch(enrollment)
        domain.refresh_and_touch(employee)
        return object_response(serialize.enrollment(enrollment))

    @app.post("/enrollments/<enrollment_id>/withdraw")
    @endpoint(["Employee"])
    def withdraw(enrollment_id):
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        employee = own_enrollment(enrollment)
        if enrollment["academic_status"] not in domain.OPEN_ACADEMIC_STATES:
            fail(
                "ERR_ENROLLMENT_INVALID_ACADEMIC_STATE",
                "enrollment is %s and cannot be withdrawn" % enrollment["academic_status"],
            )

        enrollment["academic_status"] = "WITHDRAWN"
        domain.append_system_outcome(enrollment, "WITHDRAWN")

        day = domain.clock_date()
        if day <= iso_date(enrollment["drop_deadline_date"]):
            domain.release_funding(enrollment)
        elif enrollment["funding_status"] == "SETTLED":
            domain.assess_obligation(enrollment, "WITHDRAWAL_AFTER_DROP_WINDOW")

        domain.recompute_persistence(enrollment)
        touch(enrollment)
        domain.refresh_and_touch(employee)
        return object_response(serialize.enrollment(enrollment))

    # ------------------------------------------------------------------ outcomes
    @app.post("/enrollments/<enrollment_id>/academic-outcomes")
    @endpoint(["SchoolPartner"])
    def post_outcome(enrollment_id):
        data = body()
        term_code = string_field(data, "term_code", max_len=16)
        completion_status = enum_field(data, "completion_status", COMPLETION_STATUSES)
        credits_earned = int_field(data, "credits_earned", minimum=0)
        grade_points = number_field(
            data, "grade_points", required=False, minimum=0, maximum=4, decimals=2, default=None
        )
        graded = completion_status in ("PASSED", "FAILED")
        if graded and grade_points is None:
            invalid("'grade_points' is required when completion_status is PASSED or FAILED")
        if not graded and grade_points is not None:
            invalid("'grade_points' must be null unless completion_status is PASSED or FAILED")

        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        if credits_earned > enrollment["credits"]:
            invalid("'credits_earned' may not exceed the enrollment's credits")
        if term_code != enrollment["term_code"]:
            invalid("'term_code' must equal the enrollment's term_code")

        employee = own_enrollment(enrollment)

        if enrollment["academic_status"] != "IN_PROGRESS":
            fail(
                "ERR_ENROLLMENT_INVALID_ACADEMIC_STATE",
                "enrollment is %s, not IN_PROGRESS" % enrollment["academic_status"],
            )

        policy = db.policies[enrollment["policy_id"]]
        if completion_status == "PASSED" and Decimal(str(grade_points)) < Decimal(
            str(policy["min_passing_grade_points"])
        ):
            fail(
                "ERR_ACADEMIC_PROGRESS_NOT_MET",
                "grade_points below the policy's min_passing_grade_points",
            )

        outcome = new_record(
            {
                "enrollment_id": enrollment["id"],
                "term_code": term_code,
                "completion_status": completion_status,
                "grade_points": grade_points,
                "credits_earned": credits_earned,
                "posted_on": domain.clock_date().isoformat(),
                "posted_by_role": "SCHOOL_PARTNER",
            },
            common=False,
        )
        db.outcomes[outcome["id"]] = outcome

        enrollment["academic_status"] = completion_status
        enrollment["credits_earned"] = credits_earned
        if completion_status in ("FAILED", "INCOMPLETE"):
            domain.run_clawback_or_release(enrollment)
        domain.recompute_persistence(enrollment)
        touch(enrollment)
        domain.refresh_and_touch(employee)
        return object_response(serialize.outcome(outcome), 201)

    @app.get("/enrollments/<enrollment_id>/academic-outcomes")
    @endpoint(["SchoolPartner", "BenefitAdministrator", "Employee", "Coach"])
    def list_outcomes(enrollment_id):
        limit, offset = pagination()
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        rows = [o for o in db.outcomes.values() if o["enrollment_id"] == enrollment_id]
        return paged(rows, serialize.outcome, limit, offset)

    # ------------------------------------------------------------------ coaching
    @app.post("/enrollments/<enrollment_id>/coaching-sessions")
    @endpoint(["Coach"])
    def log_session(enrollment_id):
        data = body()
        session_date = date_field(data, "session_date")
        modality = enum_field(data, "modality", MODALITIES)
        risk_flags = array_field(
            data, "risk_flags", RISK_FLAGS, required=False, default=[], non_empty=False
        )
        notes = nullable_text(data, "notes", 2000)
        if session_date > domain.clock_date():
            invalid("'session_date' may not be later than the current logical clock date")

        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        employee = db.employees[enrollment["employee_id"]]

        row = new_record(
            {
                "enrollment_id": enrollment["id"],
                "coach_user_id": g.user_id,
                "session_date": session_date.isoformat(),
                "modality": modality,
                "risk_flags": risk_flags,
                "notes": notes,
                "persistence_risk_score_after": None,
            },
            common=False,
        )
        db.sessions[row["id"]] = row

        score = domain.recompute_persistence(enrollment)
        row["persistence_risk_score_after"] = score
        touch(enrollment)
        domain.refresh_and_touch(employee)
        return object_response(serialize.session(row), 201)

    @app.get("/enrollments/<enrollment_id>/coaching-sessions")
    @endpoint(["Coach", "BenefitAdministrator", "Employee"])
    def list_sessions(enrollment_id):
        limit, offset = pagination()
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        rows = [s for s in db.sessions.values() if s["enrollment_id"] == enrollment_id]
        return paged(rows, serialize.session, limit, offset)

    # ------------------------------------------------------ nested money reads
    @app.get("/enrollments/<enrollment_id>/invoices")
    @endpoint(["BenefitAdministrator", "SchoolPartner", "PlatformAdmin"])
    def list_invoices(enrollment_id):
        limit, offset = pagination()
        status = query_enum("status", INVOICE_STATUSES)
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        rows = [i for i in db.invoices.values() if i["enrollment_id"] == enrollment_id]
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.invoice, limit, offset)

    @app.get("/enrollments/<enrollment_id>/reimbursement-claims")
    @endpoint(["Employee", "BenefitAdministrator"])
    def list_claims(enrollment_id):
        limit, offset = pagination()
        status = query_enum("status", CLAIM_STATUSES)
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        rows = [c for c in db.claims.values() if c["enrollment_id"] == enrollment_id]
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.claim, limit, offset)

    @app.get("/enrollments/<enrollment_id>/repayment-obligations")
    @endpoint(["Employee", "BenefitAdministrator"])
    def list_obligations(enrollment_id):
        limit, offset = pagination()
        status = query_enum("status", OBLIGATION_STATUSES)
        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)
        rows = [o for o in db.obligations.values() if o["enrollment_id"] == enrollment_id]
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.obligation, limit, offset)
