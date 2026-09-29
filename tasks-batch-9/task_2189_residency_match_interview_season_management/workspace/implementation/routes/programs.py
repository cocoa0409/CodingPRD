"""Program registration, the season phase machine, match day, reporting and the
logical clock."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import acting_faculty, endpoint
from envelope import object_response
from errors import ApiError
from store import db, find, insert, iso, must_find, new_row, now, now_iso, ordered, rows, touch
from validators import (
    body,
    opt_bool,
    opt_int,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from routes.common import keep, listing

bp = Blueprint("programs", __name__)

PHASES = (
    "PRE_SEASON",
    "REVIEW_OPEN",
    "INTERVIEWS_OPEN",
    "RANKING",
    "LIST_CERTIFIED",
    "MATCH_COMPLETE",
    "SOAP_ACTIVE",
    "SEASON_CLOSED",
)

# Only these edges may be requested by a client; the rest are system-driven.
CLIENT_EDGES = {
    ("PRE_SEASON", "REVIEW_OPEN"),
    ("REVIEW_OPEN", "INTERVIEWS_OPEN"),
    ("INTERVIEWS_OPEN", "RANKING"),
    ("MATCH_COMPLETE", "SOAP_ACTIVE"),
    ("MATCH_COMPLETE", "SEASON_CLOSED"),
    ("SOAP_ACTIVE", "SEASON_CLOSED"),
}


@bp.post("/programs")
@endpoint("NrmpAdmin")
def create_program():
    data = body()
    name = req_str(data, "name", max_len=200)
    code = req_str(data, "nrmp_program_code")
    specialty = req_str(data, "specialty_code")
    quota = req_int(data, "quota_positions", minimum=1)
    visa = opt_bool(data, "visa_sponsorship_allowed", False)
    soap = opt_bool(data, "soap_participating", False)
    min_step2 = opt_int(data, "min_step2_score", 220, minimum=1, maximum=300)
    img = opt_bool(data, "img_accepted", False)

    for existing in rows("programs"):
        if existing["nrmp_program_code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "nrmp_program_code is already registered.")

    row = new_row(
        name=name,
        nrmp_program_code=code,
        specialty_code=specialty,
        quota_positions=quota,
        season_phase="PRE_SEASON",
        visa_sponsorship_allowed=visa,
        soap_participating=soap,
        min_step2_score=min_step2,
        img_accepted=img,
        rank_list_certified_at=None,
    )
    insert("programs", row)
    return object_response(serializers.program(row, materialising=True), 201)


@bp.get("/programs")
@endpoint("NrmpAdmin", "ProgramCoordinator", "ProgramDirector", "ComplianceOfficer")
def list_programs():
    items = rows("programs")
    items = keep(items, "specialty_code", q_str("specialty_code"))
    items = keep(items, "season_phase", q_enum("season_phase", PHASES))
    return listing(items, serializers.program)


@bp.get("/programs/<program_id>")
@endpoint(
    "NrmpAdmin", "ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "Applicant"
)
def read_program(program_id):
    program = must_find("programs", program_id)
    return object_response(serializers.program(program))


@bp.post("/programs/<program_id>/advance-phase")
@endpoint("ProgramCoordinator", "NrmpAdmin")
def advance_phase(program_id):
    program = must_find("programs", program_id)
    data = body()
    to_phase = req_enum(data, "to_phase", PHASES)

    current = program["season_phase"]
    if (current, to_phase) not in CLIENT_EDGES:
        helpers.invalid_state(
            "Program.season_phase %s has no client-requestable transition to %s."
            % (current, to_phase)
        )

    if to_phase == "REVIEW_OPEN":
        if not calc.program_faculty(program_id):
            helpers.invalid_state("The program has no registered faculty member.")
    elif to_phase == "INTERVIEWS_OPEN":
        advanced = [
            a
            for a in calc.program_applications(program_id)
            if a["screening_status"] == "ADVANCED"
        ]
        if not advanced:
            helpers.invalid_state("No application has reached ADVANCED.")
    elif to_phase == "RANKING":
        waves = calc.program_waves(program_id)
        if any(wave["status"] != "CLOSED" for wave in waves):
            helpers.invalid_state("Every interview wave must be CLOSED first.")
    elif to_phase == "SOAP_ACTIVE":
        if not program["soap_participating"]:
            helpers.invalid_state("The program does not participate in SOAP.")
        if calc.unfilled_positions(program) < 1:
            helpers.invalid_state("The program has no unfilled position.")
    elif to_phase == "SEASON_CLOSED":
        if current == "MATCH_COMPLETE":
            if calc.unfilled_positions(program) != 0:
                helpers.invalid_state("Unfilled positions remain.")
        else:
            round_four = [
                offer
                for offer in calc.program_soap_offers(program_id)
                if offer["soap_round"] == 4
            ]
            if calc.unfilled_positions(program) != 0 and not round_four:
                helpers.invalid_state(
                    "Unfilled positions remain and no fourth-round SOAP offer exists."
                )

    program["season_phase"] = to_phase

    if to_phase == "SEASON_CLOSED" and current == "SOAP_ACTIVE":
        for offer in calc.program_soap_offers(program_id):
            if offer["status"] == "OFFERED":
                offer["status"] = "EXPIRED"
                touch(offer)

    touch(program)
    return object_response(serializers.program(program))


@bp.post("/programs/<program_id>/run-match")
@endpoint("NrmpAdmin")
def run_match(program_id):
    program = must_find("programs", program_id)

    helpers.require_phase(program, ("LIST_CERTIFIED",))
    if program["rank_list_certified_at"] is None:
        helpers.invalid_state("The program has no certified rank list.")
    if calc.program_match_results(program_id):
        helpers.invalid_state("Match day has already run for this program.")

    rank_list = helpers.certified_rank_list(program_id)
    entries = sorted(
        calc.list_entries(rank_list["id"]) if rank_list else [],
        key=lambda e: e["rank_position"],
    )

    for entry in entries:
        if calc.has_unresolved_flag(entry["application_id"]):
            raise ApiError("ERR_UNRESOLVED_COMMUNICATION_FLAG")

    stamp = now_iso()
    filled = 0
    for entry in entries:
        application = find("applications", entry["application_id"])
        eligible = (
            application is not None
            and application["screening_status"] == "ADVANCED"
            and application["interview_status"] == "COMPLETED"
        )
        if eligible and filled < program["quota_positions"]:
            outcome = "MATCHED"
            position = entry["rank_position"]
            filled += 1
        else:
            outcome = "UNMATCHED"
            position = None
        insert(
            "match_results",
            new_row(
                program_id=program_id,
                application_id=entry["application_id"],
                outcome=outcome,
                matched_rank_position=position,
                published_at=stamp,
            ),
        )

    program["season_phase"] = "MATCH_COMPLETE"
    touch(program)
    return object_response(serializers.program(program))


@bp.get("/programs/<program_id>/pipeline-report")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin")
def pipeline_report(program_id):
    program = must_find("programs", program_id)
    report = calc.pipeline_report(program, lambda a_id: find("applicants", a_id))
    return object_response(report)


@bp.post("/_clock/set_current_utc")
@endpoint("NrmpAdmin")
def set_clock():
    data = body()
    current = req_dt(data, "current_utc")
    db.clock = current
    return object_response({"current_utc": iso(db.clock)})
