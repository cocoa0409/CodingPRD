"""DistributionElection endpoints (PRD section 3.6). OCC-guarded on the
participant version; Participant self-service is ownership-checked."""

import db
import services
from errors import (
    ApiError,
    ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED,
    ERR_CASE_INVALID_STATE,
    ERR_ELECTION_INVALID_STATE,
    ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION,
    ERR_PARTICIPANT_OWNERSHIP_VIOLATION,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_election, public_payout
from util import (
    apply_filters,
    body_fk,
    body_json,
    check_no_fields,
    check_shape,
    occ_check,
    paginate,
    pagination_params,
    path_entity,
)

bp = make_blueprint("elections")

ELECTION_METHODS = {
    "LUMP_SUM_CHECK",
    "DIRECT_ROLLOVER_IRA",
    "DIRECT_ROLLOVER_QUALIFIED_PLAN",
}

ELECTABLE_STATES = {"PENDING_ELECTION", "ELECTION_SUBMITTED", "RESTORED"}


@bp.post("/distribution-elections")
def create_election():
    user_id, role = authenticate(["Participant", "PlanAdministrator"])
    body = body_json()
    # Priority 2: Participant self-service ownership.
    if (
        role == "Participant"
        and body.get("participant_id") is not None
        and body.get("participant_id") != user_id
    ):
        raise ApiError(
            ERR_PARTICIPANT_OWNERSHIP_VIOLATION, 403,
            "a Participant may only submit an election for themself",
        )
    check_shape(body, {
        "participant_id": {"type": "string", "required": True},
        "election_method": {
            "type": "enum", "values": ELECTION_METHODS, "required": True,
        },
        "destination_detail": {"type": "string"},
        "expected_participant_version": {"type": "integer", "required": True},
    })
    participant = body_fk(body, "participant_id", "participants", "participant")
    # Priority 5: OCC on the participant version.
    occ_check(body, "expected_participant_version", participant["version"])

    case = db.get("cases", participant["termination_case_id"])
    # Priority 6: from-state gates.
    if case["status"] != "DISTRIBUTION_IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "elections require case status DISTRIBUTION_IN_PROGRESS",
        )
    if participant["distribution_status"] not in ELECTABLE_STATES:
        raise ApiError(
            ERR_ELECTION_INVALID_STATE, 409,
            "election requires distribution_status PENDING_ELECTION, "
            "ELECTION_SUBMITTED, or RESTORED",
        )
    # Priority 11: cross-entity state.
    if participant["locate_status"] == "MISSING":
        raise ApiError(
            ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION, 409,
            "a missing participant goes through the search protocol",
        )
    if services.case_blackout_active(case["id"]):
        raise ApiError(
            ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED, 409,
            "new elections are blocked while a blackout is ACTIVE",
        )

    # Side effects: supersede any prior SUBMITTED election of this participant.
    for prior in db.all_of("elections"):
        if (
            prior["participant_id"] == participant["id"]
            and prior["status"] == "SUBMITTED"
        ):
            prior["status"] = "SUPERSEDED"
            db.touch(prior)
    election = db.new_entity("elections", {
        "participant_id": participant["id"],
        "election_method": body["election_method"],
        "destination_detail": body.get("destination_detail"),
        "status": "SUBMITTED",
    })
    participant["distribution_status"] = "ELECTION_SUBMITTED"
    db.touch(participant)
    return success_obj(public_election(election), 201)


@bp.get("/distribution-elections/<election_id>")
def get_election(election_id):
    authenticate(ALL_ROLES)
    return success_obj(
        public_election(path_entity("elections", election_id, "election")), 200
    )


@bp.get("/distribution-elections")
def list_elections():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("elections"), ["participant_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_election(e) for e in page], limit, offset, total, has_more
    )


@bp.post("/distribution-elections/<election_id>/accept")
def accept_election(election_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    election = path_entity("elections", election_id, "election")
    if election["status"] != "SUBMITTED":
        raise ApiError(
            ERR_ELECTION_INVALID_STATE, 409,
            "accept requires a SUBMITTED election",
        )
    participant = db.get("participants", election["participant_id"])
    if participant["locate_status"] == "MISSING":
        raise ApiError(
            ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION, 409,
            "a missing participant's election cannot be accepted",
        )
    election["status"] = "ACCEPTED"
    db.touch(election)
    services.create_payout(
        participant, "ELECTION", election["election_method"], election["id"]
    )
    participant["distribution_status"] = "ELECTION_ACCEPTED"
    db.touch(participant)
    return success_obj(public_election(election), 200)


@bp.post("/distribution-elections/<election_id>/reject")
def reject_election(election_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True}})
    election = path_entity("elections", election_id, "election")
    if election["status"] != "SUBMITTED":
        raise ApiError(
            ERR_ELECTION_INVALID_STATE, 409,
            "reject requires a SUBMITTED election",
        )
    election["status"] = "REJECTED"
    db.touch(election)
    participant = db.get("participants", election["participant_id"])
    if participant is not None and participant["distribution_status"] == "ELECTION_SUBMITTED":
        participant["distribution_status"] = "PENDING_ELECTION"
        db.touch(participant)
    return success_obj(public_election(election), 200)


@bp.get("/distribution-elections/<election_id>/payouts")
def list_election_payouts(election_id):
    authenticate(ALL_ROLES)
    election = path_entity("elections", election_id, "election")
    items = [
        p for p in db.all_of("payouts")
        if p["distribution_election_id"] == election["id"]
    ]
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_payout(p) for p in page], limit, offset, total, has_more
    )
