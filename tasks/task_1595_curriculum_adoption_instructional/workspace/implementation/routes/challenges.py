"""ChallengeCase + CommitteeVote endpoints (PRD §3.9): filing windows,
freeze-on-file, quorum decisions with plurality, one appeal per case, and
closure."""

from datetime import timedelta

from flask import Blueprint, request

import serializers
from db import bump, new_id, now_clock, stamp_new, store
from errors import (ApiError, ERR_APPEAL_WINDOW_CLOSED,
                    ERR_CHALLENGE_TARGET_INVALID, ERR_CHALLENGE_WINDOW_CLOSED,
                    ERR_DUPLICATE_VOTE, ERR_OPEN_CHALLENGE_EXISTS,
                    ERR_QUORUM_NOT_MET, ERR_SEGREGATION_OF_DUTIES, conflict,
                    insufficient_permissions, invalid_state, validation)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, req_enum,
                        req_str, require_roles)
from response import paginate, sort_created, success_object
from services import cascades

bp = Blueprint("challenge_cases", __name__)

GROUNDS = ("CONTENT_OBJECTION", "AGE_APPROPRIATENESS", "ALIGNMENT_DISPUTE",
           "PROCEDURAL_IRREGULARITY")
VOTE_VALUES = ("UPHOLD", "RESTRICT", "REMOVE")
CHALLENGE_WINDOW_DAYS = 90
APPEAL_WINDOW_DAYS = 14
QUORUM = 3

# Per-target-state role gating (SCAFFOLD §1.7 shared_operations).
CHALLENGE_TRANSITION_ROLES = {
    "SCREENING": ("CurriculumDirector",),
    "COMMITTEE_REVIEW": ("CurriculumDirector",),
    "HEARING": ("CurriculumDirector",),
    "CLOSED": ("CurriculumDirector",),
    "DECIDED": ("CommitteeMember",),
    "APPEALED": ("CommunityMember",),
}

# Non-terminal challenge statuses: FILED .. APPEALED (CLOSED is terminal).
OPEN_CHALLENGE_STATUSES = ("FILED", "SCREENING", "COMMITTEE_REVIEW", "HEARING",
                           "DECIDED", "APPEALED")


def _get_challenge(cc_id):
    return get_or_404(store.challenge_cases, cc_id, "ChallengeCase")


@bp.route("/challenge-cases", methods=["POST"])
def create_challenge():
    user_id, role = auth_context()
    require_roles(role, ("CommunityMember",))
    body = get_body()
    # Tier 3: target_id resolved per target_type; an invalid target_type falls
    # through to the tier-4 shape error.
    target = None
    target_type = body.get("target_type")
    raw_target_id = body.get("target_id")
    if target_type in ("MATERIAL", "SUPPLEMENTAL_REQUEST") \
            and isinstance(raw_target_id, str) and raw_target_id:
        if target_type == "MATERIAL":
            target = get_or_404(store.materials, raw_target_id,
                                "InstructionalMaterial")
        else:
            target = get_or_404(store.supplemental_requests, raw_target_id,
                                "SupplementalRequest")
    target_type = req_enum(body, "target_type", ("MATERIAL", "SUPPLEMENTAL_REQUEST"))
    target_id = req_str(body, "target_id")
    grounds = req_enum(body, "grounds", GROUNDS)
    if target is None:
        if target_type == "MATERIAL":
            target = get_or_404(store.materials, target_id,
                                "InstructionalMaterial")
        else:
            target = get_or_404(store.supplemental_requests, target_id,
                                "SupplementalRequest")

    # Cascade order (PRD §2.7): tier 7 window -> tier 10 open challenge ->
    # tier 11 target eligibility. The window rule fires only when the target
    # carries the relevant stamp (adopted_at / approved_at).
    if target_type == "MATERIAL":
        eligible = target["adoption_status"] == "ADOPTED"
        basis = target.get("adopted_at")
    else:
        eligible = target["status"] in ("APPROVED", "REAFFIRMED")
        basis = target.get("approved_at")
    # Tier 7 temporal: filed no later than 90 days after adopted_at/approved_at.
    if basis is not None and now_clock() > basis + timedelta(days=CHALLENGE_WINDOW_DAYS):
        raise conflict(ERR_CHALLENGE_WINDOW_CLOSED,
                       "the 90-day challenge window has closed")
    # Tier 10: one open challenge per target.
    for other in store.challenge_cases.values():
        if (other["target_type"] == target_type
                and other["target_id"] == target_id
                and other["status"] in OPEN_CHALLENGE_STATUSES):
            raise conflict(ERR_OPEN_CHALLENGE_EXISTS,
                           "the target already has an open challenge")
    # Tier 11 referential: target eligibility.
    if not eligible:
        raise conflict(ERR_CHALLENGE_TARGET_INVALID,
                       "the challenge target is not eligible")

    challenge = {
        "id": new_id(),
        "target_type": target_type,
        "target_id": target_id,
        "grounds": grounds,
        "filer_user_id": user_id,
        "status": "FILED",
        "decision": None,
        "vote_round": 1,
        "appeal_used": False,
        "filed_at": now_clock(),
        "decided_at": None,
    }
    stamp_new(challenge)
    store.challenge_cases[challenge["id"]] = challenge
    cascades.freeze_challenge_target(challenge)
    return success_object(serializers.challenge_case(challenge), status=201)


@bp.route("/challenge-cases", methods=["GET"])
def list_challenges():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.challenge_cases.values())
    target_id = request.args.get("target_id")
    status = request.args.get("status")
    if target_id is not None:
        items = [c for c in items if c["target_id"] == target_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(sort_created(items), serializers.challenge_case)


@bp.route("/challenge-cases/<ccId>", methods=["GET"])
def get_challenge(ccId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.challenge_case(_get_challenge(ccId)))


@bp.route("/challenge-cases/<ccId>/transitions", methods=["POST"])
def challenge_transition(ccId):
    user_id, role = auth_context()
    require_roles(role, ("CurriculumDirector", "CommitteeMember",
                         "CommunityMember"))
    challenge = _get_challenge(ccId)
    body = get_body()
    to_state = req_enum(body, "to_state", tuple(CHALLENGE_TRANSITION_ROLES))
    require_roles(role, CHALLENGE_TRANSITION_ROLES[to_state])
    status = challenge["status"]

    if to_state == "SCREENING":
        if status != "FILED":
            raise invalid_state("only a FILED challenge may enter SCREENING")
    elif to_state == "COMMITTEE_REVIEW":
        if status not in ("SCREENING", "APPEALED"):
            raise invalid_state("committee review follows SCREENING or an appeal")
    elif to_state == "HEARING":
        if status != "COMMITTEE_REVIEW":
            raise invalid_state("only a challenge in COMMITTEE_REVIEW may enter "
                                "HEARING")
    elif to_state == "DECIDED":
        if status not in ("COMMITTEE_REVIEW", "HEARING"):
            raise invalid_state("a decision requires COMMITTEE_REVIEW or HEARING")
        round_votes = [v for v in store.votes.values()
                       if v["challenge_id"] == challenge["id"]
                       and v["vote_round"] == challenge["vote_round"]]
        if len(round_votes) < QUORUM:
            raise conflict(ERR_QUORUM_NOT_MET,
                           "at least 3 votes are required in the current round")
    elif to_state == "APPEALED":
        # Tier 2 user-level ownership: only the filer may appeal.
        if user_id != challenge["filer_user_id"]:
            raise insufficient_permissions(
                "only the challenge's filer may appeal")
        if status != "DECIDED":
            raise invalid_state("only a DECIDED challenge may be appealed")
        if challenge["appeal_used"]:
            raise invalid_state("the single appeal has already been used")
        # Tier 7 temporal: no later than 14 days after decided_at (inclusive).
        decided_at = challenge["decided_at"]
        if decided_at is not None and now_clock() > decided_at + timedelta(
                days=APPEAL_WINDOW_DAYS):
            raise conflict(ERR_APPEAL_WINDOW_CLOSED,
                           "the 14-day appeal window has closed")
    elif to_state == "CLOSED":
        if status != "DECIDED":
            raise invalid_state("only a DECIDED challenge may be closed")
        decided_at = challenge["decided_at"]
        window_lapsed = (decided_at is not None
                         and now_clock() > decided_at + timedelta(
                             days=APPEAL_WINDOW_DAYS))
        if not (challenge["appeal_used"] or window_lapsed):
            raise invalid_state("the appeal window is still open")

    # --- side effects -------------------------------------------------------
    if to_state == "DECIDED":
        counts = {"UPHOLD": 0, "RESTRICT": 0, "REMOVE": 0}
        for v in round_votes:
            counts[v["vote"]] += 1
        top = max(counts.values())
        leaders = [k for k, n in counts.items() if n == top]
        # Any tie for the top count resolves to UPHELD (PRD §3.9).
        if len(leaders) == 1:
            decision = {"UPHOLD": "UPHELD", "RESTRICT": "RESTRICTED",
                        "REMOVE": "REMOVED"}[leaders[0]]
        else:
            decision = "UPHELD"
        challenge["decision"] = decision
        challenge["decided_at"] = now_clock()
        challenge["status"] = "DECIDED"
        bump(challenge)
        cascades.apply_challenge_decision(challenge)
        return success_object(serializers.challenge_case(challenge))
    if to_state == "APPEALED":
        challenge["appeal_used"] = True
        challenge["vote_round"] += 1
    challenge["status"] = to_state
    bump(challenge)
    return success_object(serializers.challenge_case(challenge))


# ---------------------------------------------------------------------------
# Committee votes (PRD §3.9)
# ---------------------------------------------------------------------------


@bp.route("/challenge-cases/<ccId>/votes", methods=["POST"])
def cast_vote(ccId):
    user_id, role = auth_context()
    require_roles(role, ("CommitteeMember",))
    challenge = _get_challenge(ccId)
    body = get_body()
    vote_value = req_enum(body, "vote", VOTE_VALUES)
    # Tier 9 segregation of duties: the filer may not vote on their own case.
    if user_id == challenge["filer_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the case filer may not vote on their own challenge")
    # Tier 10: one vote per member per round.
    for v in store.votes.values():
        if (v["challenge_id"] == challenge["id"]
                and v["voter_user_id"] == user_id
                and v["vote_round"] == challenge["vote_round"]):
            raise conflict(ERR_DUPLICATE_VOTE,
                           "the member has already voted in this round")
    vote = {
        "id": new_id(),
        "challenge_id": challenge["id"],
        "voter_user_id": user_id,
        "vote": vote_value,
        "vote_round": challenge["vote_round"],
        "created_at": now_clock(),
        "_seq": None,
    }
    from db import next_seq
    vote["_seq"] = next_seq()
    store.votes[vote["id"]] = vote
    return success_object(serializers.committee_vote(vote), status=201)


@bp.route("/challenge-cases/<ccId>/votes", methods=["GET"])
def list_votes(ccId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    challenge = _get_challenge(ccId)
    items = [v for v in store.votes.values()
             if v["challenge_id"] == challenge["id"]]
    vote_round = request.args.get("vote_round")
    if vote_round is not None:
        try:
            vote_round_int = int(vote_round)
        except (TypeError, ValueError):
            raise validation("vote_round must be an integer")
        items = [v for v in items if v["vote_round"] == vote_round_int]
    return paginate(sort_created(items), serializers.committee_vote)
