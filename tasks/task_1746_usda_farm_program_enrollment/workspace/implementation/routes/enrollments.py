"""Enrollment endpoints (PRD §3.7, §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_AGI_INELIGIBLE, ERR_CONSERVATION_NOT_CERTIFIED,
    ERR_NO_ACTIVE_ELECTION, ERR_ACREAGE_NOT_CERTIFIED,
    ERR_SEGREGATION_OF_DUTIES, invalid_request, invalid_state, not_found,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_enrollment_or_404, active_membership,
    certified_report_for, active_election_for, yield_record_for,
)
from services.payment import compute_payment
from validation import (
    body, require_int, require_string, require_decimal, optional_decimal,
)

bp = Blueprint("enrollments", __name__)

AGI_LIMIT_CENTS = 90000000  # $900,000 statutory AGI limit (PRD §3.7)


@bp.post("/fsa/farms/<farm_id>/enrollments")
def create_enrollment(farm_id):
    user_id, _ = require_roles(["Producer"])
    get_farm_or_404(farm_id)
    data = body()
    program_year = require_int(data, "program_year")
    commodity = require_string(data, "commodity")

    enrollment = db.common_fields()
    enrollment.update({
        "farm_id": farm_id,
        "program_year": program_year,
        "commodity": commodity,
        "enrollment_status": "DRAFT",
        "pinned_election_id": None,
        "pinned_yield_record_id": None,
        "computed_payment_cents": None,
        "sequestration_cents": None,
        "submitted_by_producer_id": None,
    })
    db.enrollments[enrollment["id"]] = enrollment
    return success_object(enrollment, 201)


@bp.get("/fsa/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    require_roles(ALL_ROLES)
    return success_object(get_enrollment_or_404(enrollment_id))


@bp.get("/fsa/enrollments/<enrollment_id>/appeals")
def list_enrollment_appeals(enrollment_id):
    require_roles(ALL_ROLES)
    get_enrollment_or_404(enrollment_id)
    items = [
        a for a in db.appeals.values() if a["enrollment_id"] == enrollment_id
    ]
    items.sort(key=lambda a: a["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/farms/<farm_id>/enrollments")
def list_farm_enrollments(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    program_year = request.args.get("program_year")
    status = request.args.get("enrollment_status")
    items = [e for e in db.enrollments.values() if e["farm_id"] == farm_id]
    if program_year is not None:
        try:
            py = int(program_year)
        except ValueError:
            raise invalid_request("program_year must be an integer")
        items = [e for e in items if e["program_year"] == py]
    if status is not None:
        items = [e for e in items if e["enrollment_status"] == status]
    items.sort(key=lambda e: e["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/enrollments/<enrollment_id>/submit")
def submit_enrollment(enrollment_id):
    user_id, _ = require_roles(["Producer"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "DRAFT":
        raise invalid_state("Only a DRAFT enrollment may be submitted")

    if active_membership(enrollment["farm_id"], user_id) is None:
        raise invalid_request("Producer does not hold an ACTIVE membership on this farm")

    # Priority 10: an ACTIVE election must exist for (farm, year, commodity).
    if active_election_for(
            enrollment["farm_id"], enrollment["program_year"],
            enrollment["commodity"]) is None:
        raise ApiError(
            ERR_NO_ACTIVE_ELECTION,
            "No ACTIVE ProgramElection for (farm, year, commodity) at submit",
            422,
        )

    # Priority 11: the acreage report for (farm, year) must be CERTIFIED.
    if certified_report_for(enrollment["farm_id"], enrollment["program_year"]) is None:
        raise ApiError(
            ERR_ACREAGE_NOT_CERTIFIED,
            "AcreageReport for (farm, year) not CERTIFIED at submit",
            422,
        )

    # A YieldRecord must exist for (farm, commodity).
    if yield_record_for(enrollment["farm_id"], enrollment["commodity"]) is None:
        raise not_found("No YieldRecord for (farm, commodity)")

    enrollment["enrollment_status"] = "SUBMITTED"
    enrollment["submitted_by_producer_id"] = user_id
    db.touch(enrollment)
    return success_object(enrollment)


@bp.post("/fsa/enrollments/<enrollment_id>/ced-approve")
def ced_approve(enrollment_id):
    user_id, _ = require_roles(["CountyExecutiveDirector"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED enrollment may be CED-approved")

    # Segregation of duties: CED is not the submitting producer.
    if enrollment.get("submitted_by_producer_id") is not None \
            and enrollment["submitted_by_producer_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "CED is the submitting producer",
            422,
        )

    producer = db.producers.get(enrollment.get("submitted_by_producer_id"))
    if producer is None:
        raise not_found("Submitting producer not found")

    # Priority 8: conservation gate.
    if producer["conservation_status"] not in ("CERTIFIED", "EXEMPT"):
        raise ApiError(
            ERR_CONSERVATION_NOT_CERTIFIED,
            "Producer conservation_status not in {CERTIFIED, EXEMPT} at CED approval",
            422,
        )

    # Priority 9: AGI gate.
    agi = producer.get("adjusted_gross_income")
    if producer["agi_attestation_status"] != "VERIFIED" \
            or agi is None or agi > AGI_LIMIT_CENTS:
        raise ApiError(
            ERR_AGI_INELIGIBLE,
            "AGI attestation not VERIFIED or AGI exceeds 90000000 cents",
            422,
        )

    enrollment["enrollment_status"] = "CED_APPROVED"
    db.touch(enrollment)
    return success_object(enrollment)


@bp.post("/fsa/enrollments/<enrollment_id>/certify")
def certify_enrollment(enrollment_id):
    user_id, _ = require_roles(["CountyCommittee"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "CED_APPROVED":
        raise invalid_state("Only a CED_APPROVED enrollment may be certified")

    # Segregation of duties: committee reviewer did not submit the enrollment.
    if enrollment.get("submitted_by_producer_id") is not None \
            and enrollment["submitted_by_producer_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Committee reviewer submitted the enrollment",
            422,
        )

    _pin_and_lock(enrollment)
    enrollment["enrollment_status"] = "CERTIFIED"
    db.touch(enrollment)
    return success_object(enrollment)


def _pin_and_lock(enrollment):
    """Pin the current ACTIVE election and yield record; both become LOCKED."""
    election = active_election_for(
        enrollment["farm_id"], enrollment["program_year"], enrollment["commodity"])
    if election is None:
        # Fall back to any election for the key that isn't terminal-withdrawn.
        candidates = [
            e for e in db.program_elections.values()
            if e["farm_id"] == enrollment["farm_id"]
            and e["program_year"] == enrollment["program_year"]
            and e["commodity"] == enrollment["commodity"]
            and e["election_status"] in ("ACTIVE", "LOCKED")
        ]
        candidates.sort(key=lambda e: e["created_at"])
        election = candidates[-1] if candidates else None
    if election is None:
        raise ApiError(ERR_NO_ACTIVE_ELECTION,
                       "No ACTIVE ProgramElection for (farm, year, commodity)", 422)

    record = yield_record_for(enrollment["farm_id"], enrollment["commodity"])
    if record is None:
        raise not_found("No YieldRecord for (farm, commodity)")

    enrollment["pinned_election_id"] = election["id"]
    enrollment["pinned_yield_record_id"] = record["id"]

    if election["election_status"] == "ACTIVE":
        election["election_status"] = "LOCKED"
        db.touch(election)
    if record["yield_status"] in ("PROVISIONAL", "UPDATED", "CERTIFIED"):
        record["yield_status"] = "LOCKED"
        db.touch(record)


@bp.post("/fsa/enrollments/<enrollment_id>/compute-payment")
def compute_payment_endpoint(enrollment_id):
    require_roles(["CountySpecialist"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "CERTIFIED":
        raise invalid_state("Only a CERTIFIED enrollment may compute payment")

    data = body()
    national_my_price = require_decimal(data, "national_my_price")

    election = db.program_elections.get(enrollment.get("pinned_election_id"))
    if election is None:
        raise not_found("Pinned election not found")

    inputs = {"national_my_price": national_my_price}
    if election["election_code"] in ("ARC_CO", "ARC_IC"):
        county_actual_yield = data.get("county_actual_yield")
        benchmark_revenue = data.get("benchmark_revenue")
        if county_actual_yield is None or benchmark_revenue is None:
            raise invalid_request(
                "county_actual_yield and benchmark_revenue are required for ARC_CO")
        inputs["county_actual_yield"] = optional_decimal(data, "county_actual_yield")
        inputs["benchmark_revenue"] = optional_decimal(data, "benchmark_revenue")

    compute_payment(enrollment, inputs)
    # Keep the market inputs for the disaster-approval recompute cascade
    # (PRD §3.9: "the payment delta is recomputed"). Internal only.
    db.enrollment_compute_inputs[enrollment["id"]] = dict(inputs)
    enrollment["enrollment_status"] = "PAYMENT_COMPUTED"
    db.touch(enrollment)
    return success_object(enrollment)


@bp.post("/fsa/enrollments/<enrollment_id>/issue-payment")
def issue_payment(enrollment_id):
    require_roles(["CountyExecutiveDirector"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "PAYMENT_COMPUTED":
        raise invalid_state("Only a PAYMENT_COMPUTED enrollment may be issued")
    enrollment["enrollment_status"] = "PAYMENT_ISSUED"
    db.touch(enrollment)
    return success_object(enrollment)


@bp.post("/fsa/enrollments/<enrollment_id>/recertify")
def recertify_enrollment(enrollment_id):
    user_id, _ = require_roles(["CountyCommittee"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] != "REMANDED":
        raise invalid_state("Only a REMANDED enrollment may be recertified")
    # Pins are re-evaluated against current data (PRD §3.10).
    _pin_and_lock(enrollment)
    enrollment["enrollment_status"] = "CERTIFIED"
    db.touch(enrollment)
    return success_object(enrollment)


@bp.post("/fsa/enrollments/<enrollment_id>/void")
def void_enrollment(enrollment_id):
    user_id, _ = require_roles(["Producer"])
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["enrollment_status"] not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("Only a DRAFT or SUBMITTED enrollment may be voided")
    enrollment["enrollment_status"] = "VOID"
    db.touch(enrollment)
    return success_object(enrollment)
