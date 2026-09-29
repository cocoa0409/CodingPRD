"""Nomination intake, the career eligibility assessment and screening review
(PRD 3.3, 3.4)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import lookup
import payload
import response
import serialize
from auth import ROLE_ADMIN, ROLE_ELECTOR, ROLE_SCREENER
from errors import fail

bp = Blueprint("candidacies", __name__)

PATHWAYS = ("MODERN", "VETERANS", "POSTHUMOUS", "SPECIAL")
DECISIONS = ("ADVANCE", "REJECT", "DEFER", "REQUEST_INFO")
MAX_INFO_REQUESTS = calc.MAX_INFO_REQUESTS


def _credential_checks(elector):
    """The two credential checks of PRD 3.2: status before expiry."""
    if elector["status"] != "CREDENTIALED":
        fail("ERR_ELECTOR_NOT_CREDENTIALED", "The elector is not CREDENTIALED.")
    if elector["credential_expires_on"] < clock.now():
        fail("ERR_CREDENTIAL_EXPIRED", "The elector's credential has expired.")


@bp.route("/candidacies", methods=["POST"])
def create_candidacy():
    actor = auth.caller(ROLE_ELECTOR, ROLE_ADMIN)
    data = payload.body()
    cycle_id = payload.req_id(data, "cycle_id")
    candidate_id = payload.req_id(data, "candidate_id")
    nominated_by_elector_id = payload.req_id(data, "nominated_by_elector_id")
    pathway = payload.req_enum(data, "pathway", PATHWAYS)
    justification = payload.opt_str(data, "justification", default=None)
    carryover_from_candidacy_id = payload.opt_id(data, "carryover_from_candidacy_id", default=None)

    auth.acting_elector(actor)

    # Existence band, in the fixed order cycle, candidate, candidacy, elector,
    # then eligibility rule.
    cycle = lookup.cycle(cycle_id)
    candidate = lookup.candidate(candidate_id)
    if carryover_from_candidacy_id is not None:
        lookup.candidacy(carryover_from_candidacy_id)
    nominator = lookup.elector(nominated_by_elector_id)
    rule = calc.rule_for(candidate["category"], pathway)
    if rule is None:
        fail(
            "ERR_ELIGIBILITY_RULE_NOT_FOUND",
            "No eligibility rule governs %s / %s." % (candidate["category"], pathway),
        )

    if cycle["status"] != "NOMINATIONS_OPEN":
        fail("ERR_INVALID_CYCLE_STATE", "Nominations may only be filed against NOMINATIONS_OPEN.")

    if actor.role == ROLE_ELECTOR and nominated_by_elector_id != actor.user_id:
        fail(
            "ERR_NOMINATOR_IDENTITY_MISMATCH",
            "An elector may only file a nomination under their own identity.",
        )
    _credential_checks(nominator)

    # The seven-step assessment runs first; the duplicate-person check is last.
    eligible_from_year = calc.assess_career_eligibility(
        cycle, candidate, pathway, justification, rule
    )

    for other in db.candidacies.values():
        if (
            other["cycle_id"] == cycle["id"]
            and other["candidate_id"] == candidate["id"]
            and other["status"] != "REJECTED"
        ):
            fail("ERR_DUPLICATE_CANDIDACY", "This candidate already has a live candidacy here.")

    row = db.stamp(
        {
            "cycle_id": cycle["id"],
            "candidate_id": candidate["id"],
            "nominated_by_elector_id": nominated_by_elector_id,
            "screened_by_elector_id": None,
            "carryover_from_candidacy_id": carryover_from_candidacy_id,
            "pathway": pathway,
            "justification": justification,
            "status": "SUBMITTED",
            "eligible_from_year": eligible_from_year,
            "appearance_number": 0,
            "info_request_count": 0,
            "latest_round_votes": 0,
            "latest_round_pct": 0.0,
            "screening_notes": None,
        }
    )
    db.candidacies[row["id"]] = row

    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    return response.created(serialize.candidacy(row))


@bp.route("/candidacies", methods=["GET"])
def list_candidacies():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.candidacies,
        [
            ("cycle_id", "cycle_id", "str"),
            ("candidate_id", "candidate_id", "str"),
            ("nominated_by_elector_id", "nominated_by_elector_id", "str"),
            ("screened_by_elector_id", "screened_by_elector_id", "str"),
            ("carryover_from_candidacy_id", "carryover_from_candidacy_id", "str"),
            ("status", "status", "str"),
            ("pathway", "pathway", "str"),
        ],
        serialize.candidacy,
    )


@bp.route("/candidacies/<row_id>", methods=["GET"])
def read_candidacy(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.candidacy(lookup.candidacy(row_id)))


@bp.route("/candidacies/<row_id>/screening-decisions", methods=["POST"])
def screening_decision(row_id):
    actor = auth.caller(ROLE_SCREENER)
    data = payload.body()
    decision = payload.req_enum(data, "decision", DECISIONS)
    screening_notes = payload.opt_str(data, "screening_notes", default=None)

    acting = auth.acting_elector(actor)
    candidacy = lookup.candidacy(row_id)
    cycle = lookup.cycle(candidacy["cycle_id"])
    candidate = lookup.candidate(candidacy["candidate_id"])

    # Band 6: the cycle-state precondition belongs to ADVANCE alone.
    if decision == "ADVANCE" and cycle["status"] != "SCREENING":
        fail("ERR_INVALID_CYCLE_STATE", "A candidacy may only be advanced while the cycle screens.")
    if candidacy["status"] != "SCREENING":
        fail("ERR_INVALID_CANDIDACY_STATE", "A screening decision requires the SCREENING state.")

    # Band 8: segregation of duties before the committee-membership check.
    if actor.user_id == candidacy["nominated_by_elector_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Nobody may screen their own nomination.")
    if not acting["is_screening_member"] or acting["status"] != "CREDENTIALED":
        fail("ERR_NOT_SCREENING_MEMBER", "The acting elector does not sit on the committee.")

    if decision == "ADVANCE" and candidate["hof_status"] != "NOT_INDUCTED":
        fail("ERR_CANDIDATE_INELIGIBLE", "The candidate is no longer in play.")

    if decision == "REQUEST_INFO" and candidacy["info_request_count"] >= MAX_INFO_REQUESTS:
        fail("ERR_INFO_REQUEST_LIMIT", "The information-request budget is exhausted.")

    candidacy["screened_by_elector_id"] = actor.user_id
    if screening_notes is not None:
        candidacy["screening_notes"] = screening_notes

    if decision == "ADVANCE":
        candidacy["status"] = "ADVANCED"
    elif decision == "REJECT":
        candidacy["status"] = "REJECTED"
    elif decision == "DEFER":
        candidacy["status"] = "DEFERRED"
    else:
        candidacy["status"] = "INFO_REQUESTED"
        candidacy["info_request_count"] = candidacy["info_request_count"] + 1
    db.touch(candidacy)

    derive.recompute_cycle(cycle)
    return response.ok(serialize.candidacy(candidacy))


@bp.route("/candidacies/<row_id>/supplements", methods=["POST"])
def supplement(row_id):
    """INFO_REQUESTED -> SCREENING, closed only by the nominating elector."""
    actor = auth.caller(ROLE_ELECTOR)
    data = payload.body()
    supplement_note = payload.req_str(data, "supplement_note", allow_empty=False)

    auth.acting_elector(actor)
    candidacy = lookup.candidacy(row_id)

    if candidacy["status"] != "INFO_REQUESTED":
        fail("ERR_INVALID_CANDIDACY_STATE", "A supplement requires the INFO_REQUESTED state.")
    if actor.user_id != candidacy["nominated_by_elector_id"]:
        fail(
            "ERR_NOMINATOR_IDENTITY_MISMATCH",
            "Only the nominating elector may answer an information request.",
        )

    existing = candidacy["screening_notes"]
    candidacy["screening_notes"] = (
        supplement_note if not existing else existing + "\n" + supplement_note
    )
    candidacy["status"] = "SCREENING"
    db.touch(candidacy)
    return response.ok(serialize.candidacy(candidacy))
