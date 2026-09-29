"""Published match results and the SOAP scramble."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import acting_faculty, endpoint, require_faculty_program, require_owns_applicant
from envelope import object_response
from errors import ApiError
from store import (
    SOAP_OFFER_WINDOW_HOURS,
    dt_of,
    find,
    hours,
    insert,
    iso,
    must_find,
    new_row,
    now,
    now_iso,
    rows,
    touch,
)
from validators import body, fk, q_enum, q_int, q_str, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("match", __name__)

OUTCOMES = ("PENDING", "MATCHED", "UNMATCHED", "VACATED")
OFFER_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")


# =============================================================== MatchResult
@bp.get("/match-results")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def list_match_results():
    items = rows("match_results")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "outcome", q_enum("outcome", OUTCOMES))
    return listing(items, serializers.match_result)


@bp.get("/match-results/<result_id>")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def read_match_result(result_id):
    return object_response(serializers.match_result(must_find("match_results", result_id)))


# ================================================================= SoapOffer
@bp.post("/soap-offers")
@endpoint("ProgramDirector")
def create_soap_offer():
    data = body()
    program = fk(data, "program_id", "programs")
    application = fk(data, "application_id", "applications")
    if program is None or application is None:
        req_str(data, "program_id")
        req_str(data, "application_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    soap_round = req_int(data, "soap_round", minimum=1, maximum=4)

    helpers.require_phase(program, ("SOAP_ACTIVE",))
    if not program["soap_participating"]:
        helpers.invalid_state("The program does not participate in SOAP.")
    unmatched = [
        result
        for result in calc.program_match_results(program["id"])
        if result["application_id"] == application["id"] and result["outcome"] == "UNMATCHED"
    ]
    if not unmatched:
        helpers.invalid_state(
            "The application holds no UNMATCHED MatchResult under this program."
        )

    if calc.has_unresolved_flag(application["id"]):
        raise ApiError("ERR_UNRESOLVED_COMMUNICATION_FLAG")

    faculty = acting_faculty()
    require_faculty_program(faculty, program["id"])

    budget = calc.soap_offer_budget(program)
    if len(calc.live_soap_offers(program["id"])) + 1 > budget:
        raise ApiError("ERR_SOAP_BUDGET_EXCEEDED")

    offered_at = now()
    row = new_row(
        program_id=program["id"],
        application_id=application["id"],
        soap_round=soap_round,
        status="OFFERED",
        offered_at=iso(offered_at),
        expires_at=iso(offered_at + hours(SOAP_OFFER_WINDOW_HOURS)),
    )
    insert("soap_offers", row)
    return object_response(serializers.soap_offer(row), 201)


@bp.get("/soap-offers")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def list_soap_offers():
    items = rows("soap_offers")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "soap_round", q_int("soap_round", minimum=1, maximum=4))
    items = keep(items, "status", q_enum("status", OFFER_STATUSES))
    return listing(items, serializers.soap_offer)


@bp.get("/soap-offers/<offer_id>")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def read_soap_offer(offer_id):
    return object_response(serializers.soap_offer(must_find("soap_offers", offer_id)))


def _offer_applicant_id(offer):
    application = find("applications", offer["application_id"])
    return application["applicant_id"] if application else None


@bp.post("/soap-offers/<offer_id>/accept")
@endpoint("Applicant")
def accept_soap_offer(offer_id):
    offer = must_find("soap_offers", offer_id)
    helpers.require_state(offer, "status", ("OFFERED",))
    require_owns_applicant(_offer_applicant_id(offer))

    expires_at = dt_of(offer, "expires_at")
    if expires_at is not None and now() >= expires_at:
        raise ApiError("ERR_SOAP_OFFER_EXPIRED")

    program = find("programs", offer["program_id"])
    if calc.unfilled_positions(program) < 1:
        raise ApiError("ERR_NO_POSITIONS_AVAILABLE")

    offer["status"] = "ACCEPTED"
    touch(offer)

    existing = None
    for result in calc.program_match_results(program["id"]):
        if result["application_id"] == offer["application_id"]:
            existing = result
            break
    if existing is None:
        insert(
            "match_results",
            new_row(
                program_id=program["id"],
                application_id=offer["application_id"],
                outcome="MATCHED",
                matched_rank_position=None,
                published_at=None,
            ),
        )
    else:
        existing["outcome"] = "MATCHED"
        existing["matched_rank_position"] = None
        touch(existing)

    helpers.recompute_program_counters(program)
    return object_response(serializers.soap_offer(offer))


@bp.post("/soap-offers/<offer_id>/decline")
@endpoint("Applicant")
def decline_soap_offer(offer_id):
    offer = must_find("soap_offers", offer_id)
    helpers.require_state(offer, "status", ("OFFERED",))
    require_owns_applicant(_offer_applicant_id(offer))

    expires_at = dt_of(offer, "expires_at")
    if expires_at is not None and now() >= expires_at:
        raise ApiError("ERR_SOAP_OFFER_EXPIRED")

    offer["status"] = "DECLINED"
    touch(offer)
    return object_response(serializers.soap_offer(offer))
