"""Catalog curation and the non-catalog approval workflow."""

from decimal import Decimal

import domain
import serialize
from auth import employee_scope, employer_scope, endpoint
from errors import fail
from store import db, new_record, touch
from validate import (
    body,
    enum_field,
    int_field,
    nullable_text,
    pagination,
    query_enum,
    query_str,
    string_field,
)

from .common import filter_eq, object_response, paged

LISTING_STATUSES = ["CURATED", "SUSPENDED"]
APPROVAL_SOURCES = ["CATALOG", "APPROVED_EXCEPTION"]
REQUEST_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED"]
OPEN_REQUEST_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED")
DECISIONS = ["APPROVE", "REJECT", "REQUEST_CHANGES"]


def _pair_taken(employer_id, program_id):
    """Rule 38 — a CURATED listing or an open request already covers the pair."""
    for listing in db.listings.values():
        if (
            listing["employer_id"] == employer_id
            and listing["program_id"] == program_id
            and listing["status"] == "CURATED"
        ):
            return True
    for request_row in db.requests.values():
        if request_row["program_id"] != program_id:
            continue
        if request_row["status"] not in OPEN_REQUEST_STATUSES:
            continue
        employee = db.employees.get(request_row["employee_id"])
        if employee is not None and employee["employer_id"] == employer_id:
            return True
    return False


def _new_listing(employer_id, program, agreement, source_request_id):
    if agreement is not None:
        discount = Decimal(str(agreement["negotiated_discount_pct"]))
        allowed = (
            ["DIRECT_BILL", "REIMBURSEMENT"]
            if agreement["direct_bill_enabled"]
            else ["REIMBURSEMENT"]
        )
        source = "CATALOG"
    else:
        discount = Decimal("0.0000")
        allowed = ["REIMBURSEMENT"]
        source = "APPROVED_EXCEPTION"

    rate = domain.round_half_up(
        Decimal(program["list_tuition_per_credit_cents"]) * (Decimal(1) - discount)
    )
    row = new_record(
        {
            "employer_id": employer_id,
            "program_id": program["id"],
            "agreement_id": agreement["id"] if agreement is not None else None,
            "source_request_id": source_request_id,
            "approval_source": source,
            "status": "CURATED",
            "negotiated_tuition_per_credit_cents": rate,
            "allowed_funding_models": allowed,
        }
    )
    db.listings[row["id"]] = row
    return row


def register(app):
    # ------------------------------------------------------------------ listings
    @app.post("/catalog-listings")
    @endpoint(["BenefitAdministrator"])
    def create_listing():
        data = body()
        employer_id = string_field(data, "employer_id")
        program_id = string_field(data, "program_id")
        agreement_id = string_field(data, "agreement_id")
        expected_version = int_field(data, "expected_agreement_version")

        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        program = domain.must(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        agreement = domain.must(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")

        employer_scope(employer_id)

        if expected_version != agreement["version"]:
            fail(
                "ERR_STALE_AGREEMENT_VERSION",
                "expected_agreement_version %s but the agreement is at version %s"
                % (expected_version, agreement["version"]),
            )

        from validate import iso_date

        if (
            agreement["status"] != "ACTIVE"
            or agreement["employer_id"] != employer_id
            or agreement["school_id"] != program["school_id"]
            or iso_date(agreement["effective_to"]) <= iso_date(agreement["effective_from"])
        ):
            fail(
                "ERR_AGREEMENT_NOT_ACTIVE",
                "the agreement does not actively join this employer to the program's school",
            )

        if _pair_taken(employer_id, program_id):
            fail("ERR_DUPLICATE_LISTING", "this employer/program pair is already covered")

        row = _new_listing(employer_id, program, agreement, None)
        touch(agreement)
        return object_response(serialize.listing(row), 201)

    @app.get("/catalog-listings")
    @endpoint(["BenefitAdministrator", "Employee", "PlatformAdmin"])
    def list_listings():
        limit, offset = pagination()
        status = query_enum("status", LISTING_STATUSES)
        approval_source = query_enum("approval_source", APPROVAL_SOURCES)
        rows = list(db.listings.values())
        rows = filter_eq(rows, "employer_id", query_str("employer_id"))
        rows = filter_eq(rows, "program_id", query_str("program_id"))
        rows = filter_eq(rows, "agreement_id", query_str("agreement_id"))
        rows = filter_eq(rows, "source_request_id", query_str("source_request_id"))
        rows = filter_eq(rows, "status", status)
        rows = filter_eq(rows, "approval_source", approval_source)
        return paged(rows, serialize.listing, limit, offset)

    @app.get("/catalog-listings/<listing_id>")
    @endpoint(["BenefitAdministrator", "Employee", "PlatformAdmin"])
    def read_listing(listing_id):
        listing = domain.must(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")
        employer_scope(listing["employer_id"])
        return object_response(serialize.listing(listing))

    @app.post("/catalog-listings/<listing_id>/suspend")
    @endpoint(["BenefitAdministrator"])
    def suspend_listing(listing_id):
        listing = domain.must(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")
        employer_scope(listing["employer_id"])
        if listing["status"] != "CURATED":
            fail("ERR_LISTING_NOT_CURATED", "listing is %s, not CURATED" % listing["status"])
        listing["status"] = "SUSPENDED"
        touch(listing)
        return object_response(serialize.listing(listing))

    # ------------------------------------------------------- approval requests
    @app.post("/program-approval-requests")
    @endpoint(["Employee"])
    def create_request():
        data = body()
        employee_id = string_field(data, "employee_id")
        program_id = string_field(data, "program_id")
        justification = string_field(data, "justification", max_len=2000)
        requested_annual_cost_cents = int_field(data, "requested_annual_cost_cents", minimum=0)

        employee = domain.must(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
        domain.must(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")

        employee_scope(employee_id)

        policy = domain.current_policy(employee["employer_id"])
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
        if _pair_taken(employee["employer_id"], program_id):
            fail("ERR_DUPLICATE_LISTING", "this employer/program pair is already covered")
        if not policy["non_catalog_approval_required"]:
            fail(
                "ERR_NON_CATALOG_APPROVAL_DISABLED",
                "the current policy closes the non-catalog exception path",
            )

        row = new_record(
            {
                "employee_id": employee_id,
                "program_id": program_id,
                "justification": justification,
                "requested_annual_cost_cents": requested_annual_cost_cents,
                "status": "SUBMITTED",
                "revision_count": 0,
                "decision_note": None,
            }
        )
        db.requests[row["id"]] = row
        return object_response(serialize.request(row), 201)

    @app.get("/program-approval-requests")
    @endpoint(["Employee", "BenefitAdministrator"])
    def list_requests():
        limit, offset = pagination()
        status = query_enum("status", REQUEST_STATUSES)
        rows = list(db.requests.values())
        rows = filter_eq(rows, "employee_id", query_str("employee_id"))
        rows = filter_eq(rows, "program_id", query_str("program_id"))
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.request, limit, offset)

    def _own_request(request_row):
        employee_scope(request_row["employee_id"])
        employee = db.employees[request_row["employee_id"]]
        employer_scope(employee["employer_id"])
        return employee

    @app.get("/program-approval-requests/<request_id>")
    @endpoint(["Employee", "BenefitAdministrator"])
    def read_request(request_id):
        request_row = domain.must(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
        _own_request(request_row)
        return object_response(serialize.request(request_row))

    @app.post("/program-approval-requests/<request_id>/review")
    @endpoint(["BenefitAdministrator"])
    def review_request(request_id):
        request_row = domain.must(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
        _own_request(request_row)
        if request_row["status"] != "SUBMITTED":
            fail(
                "ERR_REQUEST_INVALID_STATE",
                "request is %s, not SUBMITTED" % request_row["status"],
            )
        request_row["status"] = "UNDER_REVIEW"
        touch(request_row)
        return object_response(serialize.request(request_row))

    @app.post("/program-approval-requests/<request_id>/resubmit")
    @endpoint(["Employee"])
    def resubmit_request(request_id):
        data = body()
        justification = string_field(
            data, "justification", required=False, max_len=2000, default=None
        )
        requested_annual_cost_cents = int_field(
            data, "requested_annual_cost_cents", required=False, minimum=0, default=None
        )
        request_row = domain.must(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
        _own_request(request_row)
        if request_row["status"] != "CHANGES_REQUESTED":
            fail(
                "ERR_REQUEST_INVALID_STATE",
                "request is %s, not CHANGES_REQUESTED" % request_row["status"],
            )
        if request_row["revision_count"] >= 2:
            fail("ERR_REVISION_LIMIT_REACHED", "the revision limit of 2 rounds is reached")
        if justification is not None:
            request_row["justification"] = justification
        if requested_annual_cost_cents is not None:
            request_row["requested_annual_cost_cents"] = requested_annual_cost_cents
        request_row["status"] = "SUBMITTED"
        request_row["revision_count"] += 1
        touch(request_row)
        return object_response(serialize.request(request_row))

    @app.post("/program-approval-requests/<request_id>/decide")
    @endpoint(["BenefitAdministrator"])
    def decide_request(request_id):
        data = body()
        decision = enum_field(data, "decision", DECISIONS)
        decision_note = nullable_text(data, "decision_note", 2000)

        request_row = domain.must(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
        employee = _own_request(request_row)
        if request_row["status"] != "UNDER_REVIEW":
            fail(
                "ERR_REQUEST_INVALID_STATE",
                "request is %s, not UNDER_REVIEW" % request_row["status"],
            )

        program = db.programs[request_row["program_id"]]

        if decision == "APPROVE":
            school = db.schools[program["school_id"]]
            if school["accreditation_status"] != "ACCREDITED":
                fail(
                    "ERR_SCHOOL_NOT_ACCREDITED",
                    "the offering school is %s" % school["accreditation_status"],
                )
            if employee["eligibility_status"] != "ELIGIBLE":
                fail(
                    "ERR_EMPLOYEE_NOT_ELIGIBLE",
                    "employee is %s" % employee["eligibility_status"],
                )
            request_row["status"] = "APPROVED"
            request_row["decision_note"] = decision_note
            touch(request_row)
            _new_listing(employee["employer_id"], program, None, request_row["id"])
        elif decision == "REJECT":
            request_row["status"] = "REJECTED"
            request_row["decision_note"] = decision_note
            touch(request_row)
        else:
            request_row["status"] = "CHANGES_REQUESTED"
            request_row["decision_note"] = decision_note
            touch(request_row)

        return object_response(serialize.request(request_row))
