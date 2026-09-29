"""Office endpoints (PRD 3.1)."""
from flask import Blueprint

import auth
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("offices", __name__)


@bp.post("/offices")
def create_office():
    auth.require(constants.ELECTION_COMMISSIONER)
    body = validation.get_body()

    # rule 4 — body foreign keys resolve in input-list order
    election = lookup.fk_election(body)

    name = validation.req_str(body, "name")
    eligible_class_years = validation.req_enum_array(body, "eligible_class_years",
                                                     constants.CLASS_YEARS)
    required_signature_count = validation.req_int(body, "required_signature_count",
                                                  minimum=0)
    term_start_date = validation.req_dt(body, "term_start_date")
    term_end_date = validation.req_dt(body, "term_end_date")
    seat_count = validation.opt_int(body, "seat_count",
                                    default=constants.DEFAULT_SEAT_COUNT, minimum=1)
    min_gpa = validation.opt_decimal(body, "min_gpa",
                                     default=constants.DEFAULT_MIN_GPA,
                                     minimum=0, maximum=4)
    min_credits = validation.opt_int(body, "min_credits",
                                     default=constants.DEFAULT_MIN_CREDITS, minimum=0)
    required_training_modules = validation.opt_int(
        body, "required_training_modules",
        default=constants.DEFAULT_REQUIRED_TRAINING_MODULES, minimum=0)
    if election is None:
        validation.req_str(body, "election_id")
        errors.fail(errors.ERR_ELECTION_NOT_FOUND, "election_id was not found.")

    row = db.new_row(db.store.offices, {
        "election_id": election["id"],
        "name": name,
        "seat_count": seat_count,
        "eligible_class_years": eligible_class_years,
        "required_signature_count": required_signature_count,
        "min_gpa": min_gpa,
        "min_credits": min_credits,
        "required_training_modules": required_training_modules,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "status": "OPEN",
        "filled_seat_count": 0,
        "valid_votes_count": 0,
        "abstain_votes_count": 0,
        "invalidated_votes_count": 0,
    })
    return response.object_response(serialize.office(row), 201)


@bp.get("/offices")
def list_offices():
    auth.require_any()
    rows = listing.filtered(db.store.offices, {
        "election_id": ("election_id", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.office)


@bp.get("/offices/<office_id>")
def read_office(office_id):
    auth.require_any()
    row = lookup.office(office_id)
    return response.object_response(serialize.office(row))
