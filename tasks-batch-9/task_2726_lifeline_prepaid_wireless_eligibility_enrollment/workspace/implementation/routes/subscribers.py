"""Applicant intake, listing and eligibility-check opening."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (CHECK_STATUSES, CLAIMED_BASES, ELIGIBILITY_BASES,
                           PROGRAM_ADMINISTRATOR, PROVIDER_AGENT,
                           QUALIFYING_BENEFITS, ROLES_ALL, SUBSCRIBER_STATUSES,
                           TRIBAL_ONLY_BENEFITS, authenticate, get_address,
                           get_subscriber)
from services import calc, derive

bp = Blueprint("subscribers", __name__)


@bp.post("/lifeline/subscribers")
def create_subscriber():
    authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    body = v.get_body()
    address_id = v.string_field(body, "address_id", min_len=1)
    full_name = v.string_field(body, "full_name", min_len=1, max_len=120)
    date_of_birth = v.date_field(body, "date_of_birth")
    last4_ssn = v.string_field(body, "last4_ssn", pattern=r"^\d{4}$", min_len=4,
                               max_len=4)
    household_size = v.int_field(body, "household_size", minimum=1, maximum=12)
    annual_income_cents = v.int_field(body, "annual_income_cents", minimum=0)
    last_3mo_income_cents = v.int_field(body, "last_3mo_income_cents",
                                        required=False, minimum=0, default=0)
    qualifying_benefit = v.enum_field(body, "qualifying_benefit",
                                      QUALIFYING_BENEFITS, required=False,
                                      default="NONE")
    tribal_lands_flag = v.bool_field(body, "tribal_lands_flag", required=False,
                                     default=False)

    address = get_address(address_id)

    identity_key = calc.identity_key(full_name, date_of_birth, last4_ssn)
    for existing in db.db.subscribers.values():
        if existing["identity_key"] == identity_key:
            raise ApiError("ERR_DUPLICATE_SUBSCRIBER_IDENTITY",
                           "An applicant with this identity fingerprint already exists")

    row = db.base_row()
    row.update({
        "address_id": address_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "last4_ssn": last4_ssn,
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
        "last_3mo_income_cents": last_3mo_income_cents,
        "qualifying_benefit": qualifying_benefit,
        "tribal_lands_flag": tribal_lands_flag,
        "identity_key": identity_key,
        "status": "DUPLICATE_HOLD" if address["status"] == "DUPLICATE_FLAGGED"
                  else "PROSPECT",
    })
    db.db.subscribers[row["id"]] = row
    db.touch(address)
    return response.ok(derive.subscriber_json(row), 201)


@bp.get("/lifeline/subscribers/<subscriber_id>")
def read_subscriber(subscriber_id):
    authenticate(ROLES_ALL)
    subscriber = get_subscriber(subscriber_id)
    return response.ok(derive.subscriber_json(subscriber))


@bp.get("/lifeline/subscribers")
def list_subscribers():
    authenticate(ROLES_ALL)
    address_id = response.filter_str("address_id")
    status = response.filter_enum("status", SUBSCRIBER_STATUSES)
    basis = response.filter_enum("eligibility_basis", ELIGIBILITY_BASES)
    identity_key = response.filter_str("identity_key")
    rows = list(db.db.subscribers.values())
    if address_id is not None:
        rows = [r for r in rows if r["address_id"] == address_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if identity_key is not None:
        rows = [r for r in rows if r["identity_key"] == identity_key]
    if basis is not None:
        rows = [r for r in rows if derive.eligibility_basis(r) == basis]
    return response.paginate(db.by_created(rows), derive.subscriber_json)


@bp.post("/lifeline/subscribers/<subscriber_id>/eligibility-checks")
def create_eligibility_check(subscriber_id):
    authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    subscriber = get_subscriber(subscriber_id)

    body = v.get_body()
    claimed_basis = v.enum_field(body, "claimed_basis", CLAIMED_BASES)
    proof_document_ref = v.string_field(body, "proof_document_ref", required=False,
                                        min_len=0, default=None)

    if subscriber["status"] == "BARRED":
        raise ApiError("ERR_SUBSCRIBER_BARRED",
                       "A barred applicant cannot be screened")

    threshold = calc.fpg_income_threshold(subscriber["household_size"],
                                          subscriber["tribal_lands_flag"])
    if claimed_basis == "INCOME":
        income_variant = "STRICT_ANNUALIZED"
        evaluated = subscriber["annual_income_cents"]
        snapshot_threshold = threshold
        if evaluated > snapshot_threshold:
            raise ApiError("ERR_SUBSCRIBER_INCOME_ABOVE_THRESHOLD",
                           "Evaluated income exceeds the household income threshold")
    else:
        income_variant = "NOT_APPLICABLE"
        evaluated = None
        snapshot_threshold = None
        claimed_program = subscriber["qualifying_benefit"]
        if claimed_program == "NONE":
            raise ApiError("ERR_NO_QUALIFYING_BASIS",
                           "The applicant claims no qualifying assistance program")
        if (claimed_program in TRIBAL_ONLY_BENEFITS
                and not subscriber["tribal_lands_flag"]):
            raise ApiError("ERR_NO_QUALIFYING_BASIS",
                           "The claimed program requires qualifying Tribal lands")

    row = db.base_row()
    row.update({
        "subscriber_id": subscriber["id"],
        "claimed_basis": claimed_basis,
        "proof_document_ref": proof_document_ref,
        "income_variant": income_variant,
        "evaluated_income_cents": evaluated,
        "income_threshold_cents": snapshot_threshold,
        "status": "PENDING_VERIFIER",
        "verifier_outcome": None,
        "verifier_reason_code": None,
        "matched_benefit": None,
        "confirmed_at": None,
        "expires_at": None,
        "resubmission_count": 0,
    })
    db.db.eligibility_checks[row["id"]] = row

    # Opening a check also moves the applicant.
    if subscriber["status"] == "DE_ENROLLED":
        if derive.de_enrollment_count(subscriber["id"]) < 2:
            subscriber["status"] = "ELIGIBILITY_PENDING"
            db.touch(subscriber)
    elif subscriber["status"] == "PROSPECT":
        subscriber["status"] = "ELIGIBILITY_PENDING"
        db.touch(subscriber)

    return response.ok(derive.eligibility_check_json(row), 201)


@bp.get("/lifeline/subscribers/<subscriber_id>/eligibility-checks")
def list_subscriber_checks(subscriber_id):
    authenticate(ROLES_ALL)
    subscriber = get_subscriber(subscriber_id)
    status = response.filter_enum("status", CHECK_STATUSES)
    claimed_basis = response.filter_enum("claimed_basis", CLAIMED_BASES)
    rows = derive.checks_of_subscriber(subscriber["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if claimed_basis is not None:
        rows = [r for r in rows if r["claimed_basis"] == claimed_basis]
    return response.paginate(db.by_created(rows), derive.eligibility_check_json)
