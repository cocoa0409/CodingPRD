"""Challenge and ChallengeEvidence endpoints (PRD sections 3.2 and 3.3)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, dt_of, fmt_ts, new_record, parse_ts, serialize
from errors import ApiError
from middleware import (authenticate, get_enum, get_int, get_str, get_ts,
                        json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import cascades, domain

bp = Blueprint("challenges", __name__)

READ_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "ScoringOfficer", "Challenger", "Provider")
EVIDENCE_READ_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "Challenger", "Provider")
CHALLENGER_TYPES = ("PROVIDER", "COMMUNITY", "LOCAL_GOVERNMENT", "NONPROFIT")
CLASSIFICATIONS = ("SERVED", "UNDERSERVED", "UNSERVED")
NON_TERMINAL_CHALLENGE_STATES = ("SUBMITTED", "REBUTTAL_OPEN", "UNDER_REVIEW", "DEFICIENT")
ADJUDICATION_PROGRAM_STATES = ("CHALLENGE_OPEN", "CHALLENGE_CLOSED", "SCORING")


def _inside_challenge_window(program):
    now = db.now()
    return (parse_ts(program["challenge_window_start"]) <= now
            < parse_ts(program["challenge_window_end"]))


@bp.post("/broadband/challenges")
def create_challenge():
    user_id, _role = authenticate("Challenger", "Provider")
    body = json_body()

    program_id = get_str(body, "program_id")
    location_id = get_str(body, "location_id")
    challenger_type = get_enum(body, "challenger_type", CHALLENGER_TYPES)
    asserted = get_enum(body, "asserted_classification", CLASSIFICATIONS)
    rationale = get_str(body, "rationale")

    program = domain.require_program(program_id)                    # priority 20
    location = domain.require_location(location_id)                 # priority 21
    if program["program_state"] != "CHALLENGE_OPEN":                 # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if location["program_id"] != program["id"]:                     # priority 61
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH")
    if not _inside_challenge_window(program):                       # priority 65
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")
    for existing in db.challenges.values():                         # priority 75
        if (existing["location_id"] == location["id"]
                and existing["submitter_user_id"] == user_id
                and existing["challenge_state"] in NON_TERMINAL_CHALLENGE_STATES):
            raise ApiError("ERR_DUPLICATE_CHALLENGE")

    challenge = new_record({
        "program_id": program["id"],
        "location_id": location["id"],
        "challenger_type": challenger_type,
        "asserted_classification": asserted,
        "rationale": rationale,
        "submitter_user_id": user_id,
        "challenge_state": "SUBMITTED",
        "evidence_sufficiency_score": 0.0,
        "rebuttal_strength_score": 0.0,
        "required_sufficiency_threshold": float(calc.required_threshold(challenger_type)),
        "distinct_evidence_type_count": 0,
        "rebuttal_round": 0,
        "rebuttal_deadline": None,
        "resubmission_count": 0,
        "triaged_by_user_id": None,
        "determined_by_user_id": None,
        "outcome": None,
    })
    db.challenges[challenge["id"]] = challenge

    if domain.refresh_location_challenge_count(location):
        touch(location)
    return object_response(serialize(challenge), 201)


@bp.get("/broadband/challenges/<challenge_id>")
def get_challenge(challenge_id):
    authenticate(*READ_ROLES)
    challenge = domain.require_challenge(challenge_id)
    return object_response(serialize(challenge))


@bp.get("/broadband/challenges")
def list_challenges():
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    rows = list(db.challenges.values())
    for field in ("program_id", "location_id", "challenge_state", "challenger_type"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return paginated(rows, limit, offset)


@bp.post("/broadband/challenges/<challenge_id>/evidence")
def append_evidence(challenge_id):
    user_id, _role = authenticate("Challenger", "Provider")
    body = json_body()

    evidence_type = get_enum(body, "evidence_type", calc.EVIDENCE_TYPES)
    collected_raw, collected_at = get_ts(body, "collected_at")
    description = get_str(body, "description")
    expected_version = get_int(body, "expected_challenge_version")

    challenge = domain.require_challenge(challenge_id)               # priority 22
    location = db.locations.get(challenge["location_id"])
    program = db.programs.get(challenge["program_id"])

    if user_id == challenge["submitter_user_id"]:                    # priority 30
        side = "CHALLENGE"
    elif location is not None and user_id == location.get("reporting_provider_user_id"):
        side = "REBUTTAL"
    else:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if program["program_state"] != "CHALLENGE_OPEN":                 # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] not in ("SUBMITTED", "REBUTTAL_OPEN",
                                            "UNDER_REVIEW", "DEFICIENT"):  # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if expected_version != int(challenge["version"]):                # priority 50
        raise ApiError("ERR_STALE_CHALLENGE_VERSION")
    if not _inside_challenge_window(program):                        # priority 65
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")

    age_days = calc.evidence_age_days(dt_of(challenge["created_at"]), collected_at)
    base, multiplier, weighted, state = calc.evidence_weights(evidence_type, age_days)

    item = new_record({
        "challenge_id": challenge["id"],
        "evidence_type": evidence_type,
        "collected_at": collected_raw,
        "description": description,
        "submitter_side": side,
        "submitter_user_id": user_id,
        "base_weight": float(base),
        "recency_multiplier": float(multiplier),
        "weighted_value": float(weighted),
        "evidence_state": state,
    }, versioned=False)
    db.evidence[item["id"]] = item

    domain.refresh_challenge_scores(challenge)
    touch(challenge)
    return object_response(serialize(item), 201)


@bp.get("/broadband/challenges/<challenge_id>/evidence")
def list_evidence(challenge_id):
    authenticate(*EVIDENCE_READ_ROLES)
    limit, offset = pagination()
    challenge = domain.require_challenge(challenge_id)
    return paginated(domain.evidence_of_challenge(challenge["id"]), limit, offset)


@bp.post("/broadband/challenges/<challenge_id>/triage")
def triage(challenge_id):
    user_id, _role = authenticate("EligibilityAnalyst")
    challenge = domain.require_challenge(challenge_id)                # priority 22
    program = db.programs.get(challenge["program_id"])
    location = db.locations.get(challenge["location_id"])

    if program["program_state"] not in ADJUDICATION_PROGRAM_STATES:    # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] != "SUBMITTED":                    # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    accepted = domain.challenge_side_accepted(challenge)
    if not calc.evidence_standard_met(challenge, accepted):            # priority 76
        raise ApiError("ERR_EVIDENCE_STANDARD_NOT_MET")

    deadline = db.now() + timedelta(days=calc.REBUTTAL_WINDOW_DAYS)
    assign(challenge, "challenge_state", "REBUTTAL_OPEN")
    assign(challenge, "rebuttal_round", 1)
    assign(challenge, "rebuttal_deadline", fmt_ts(deadline))
    assign(challenge, "triaged_by_user_id", user_id)
    touch(challenge)

    if location is not None:
        changed = False
        if location["eligibility_state"] == "MAPPED":
            changed = assign(location, "eligibility_state", "CHALLENGED")
        changed = domain.refresh_location_challenge_count(location) or changed
        if changed:
            touch(location)
    return object_response(serialize(challenge))


@bp.post("/broadband/challenges/<challenge_id>/close-rebuttal")
def close_rebuttal(challenge_id):
    authenticate("EligibilityAnalyst")
    challenge = domain.require_challenge(challenge_id)
    program = db.programs.get(challenge["program_id"])

    if program["program_state"] not in ADJUDICATION_PROGRAM_STATES:    # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] != "REBUTTAL_OPEN":                # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    deadline = parse_ts(challenge.get("rebuttal_deadline")) if challenge.get("rebuttal_deadline") else None
    reached = deadline is not None and db.now() >= deadline
    has_rebuttal = calc.D(challenge["rebuttal_strength_score"]) > 0
    if not (reached or has_rebuttal):                                 # priority 67
        raise ApiError("ERR_REBUTTAL_DEADLINE_NOT_REACHED")

    assign(challenge, "challenge_state", "UNDER_REVIEW")
    touch(challenge)
    return object_response(serialize(challenge))


@bp.post("/broadband/challenges/<challenge_id>/request-additional-evidence")
def request_additional_evidence(challenge_id):
    authenticate("EligibilityAnalyst")
    body = json_body()
    get_str(body, "reason")                                           # priority 14

    challenge = domain.require_challenge(challenge_id)                # priority 22
    program = db.programs.get(challenge["program_id"])
    if program["program_state"] not in ("CHALLENGE_OPEN", "CHALLENGE_CLOSED"):  # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] != "UNDER_REVIEW":                # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if int(challenge["rebuttal_round"]) >= calc.MAX_REBUTTAL_ROUNDS:  # priority 78
        raise ApiError("ERR_REBUTTAL_ROUND_EXHAUSTED")

    deadline = db.now() + timedelta(days=calc.REBUTTAL_WINDOW_DAYS)
    assign(challenge, "challenge_state", "REBUTTAL_OPEN")
    assign(challenge, "rebuttal_round", int(challenge["rebuttal_round"]) + 1)
    assign(challenge, "rebuttal_deadline", fmt_ts(deadline))
    touch(challenge)
    return object_response(serialize(challenge))


@bp.post("/broadband/challenges/<challenge_id>/determine")
def determine(challenge_id):
    user_id, _role = authenticate("EligibilityAnalyst", "ProgramAdmin")
    body = json_body()
    outcome = get_enum(body, "outcome", ("SUSTAINED", "REJECTED", "DEFICIENT"))
    get_str(body, "determination_note", required=False)

    challenge = domain.require_challenge(challenge_id)                # priority 22
    program = db.programs.get(challenge["program_id"])
    location = db.locations.get(challenge["location_id"])

    if (challenge.get("triaged_by_user_id")                           # priority 32
            and challenge["triaged_by_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if program["program_state"] not in ADJUDICATION_PROGRAM_STATES:    # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] != "UNDER_REVIEW":                 # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    sufficiency = calc.D(challenge["evidence_sufficiency_score"])
    rebuttal = calc.D(challenge["rebuttal_strength_score"])
    if outcome == "SUSTAINED":
        accepted = domain.challenge_side_accepted(challenge)
        if not calc.evidence_standard_met(challenge, accepted):        # priority 76
            raise ApiError("ERR_EVIDENCE_STANDARD_NOT_MET")
        if rebuttal >= sufficiency:                                   # priority 77
            raise ApiError("ERR_REBUTTAL_PREVAILS")
    elif outcome == "DEFICIENT":
        if not (rebuttal >= sufficiency):                             # priority 76
            raise ApiError("ERR_EVIDENCE_STANDARD_NOT_MET")

    assign(challenge, "challenge_state", outcome)
    assign(challenge, "outcome", outcome)
    assign(challenge, "determined_by_user_id", user_id)
    touch(challenge)

    if outcome == "SUSTAINED":
        if location is not None:
            cascades.sustain_cascade(challenge, location)
    else:
        if location is not None and location["eligibility_state"] == "CHALLENGED":
            assign(location, "eligibility_state", "AFFIRMED")
            touch(location)
    return object_response(serialize(challenge))


@bp.post("/broadband/challenges/<challenge_id>/resubmit")
def resubmit(challenge_id):
    user_id, _role = authenticate("Challenger", "Provider")
    body = json_body()
    rationale = get_str(body, "rationale", required=False)

    challenge = domain.require_challenge(challenge_id)                # priority 22
    program = db.programs.get(challenge["program_id"])
    location = db.locations.get(challenge["location_id"])

    if user_id != challenge["submitter_user_id"]:                     # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if program["program_state"] != "CHALLENGE_OPEN":                  # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if challenge["challenge_state"] != "DEFICIENT":                   # priority 41
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if not _inside_challenge_window(program):                         # priority 65
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")
    if int(challenge["resubmission_count"]) >= calc.MAX_CHALLENGE_RESUBMISSIONS:  # priority 79
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")

    assign(challenge, "challenge_state", "SUBMITTED")
    assign(challenge, "resubmission_count", int(challenge["resubmission_count"]) + 1)
    assign(challenge, "rebuttal_round", 0)
    assign(challenge, "rebuttal_deadline", None)
    assign(challenge, "triaged_by_user_id", None)
    assign(challenge, "outcome", None)
    if rationale is not None:
        assign(challenge, "rationale", rationale)
    touch(challenge)

    if location is not None and location["eligibility_state"] == "AFFIRMED":
        assign(location, "eligibility_state", "CHALLENGED")
        touch(location)
    return object_response(serialize(challenge))
