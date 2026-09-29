"""Match offers and the acceptance cascade (PRD 3.5)."""
from flask import Blueprint, request as flask_request

import calc
import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from errors import ApiError
from guards import route

bp = Blueprint("offers", __name__)

OFFER_READ_ROLES = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_VOLUNTEER,
    C.ROLE_PARTNER_CONTACT,
]


@route(bp, "/match-offers/<offer_id>", ["GET"], OFFER_READ_ROLES)
def get_match_offer(offer_id):
    offer = G.g08_offer(offer_id)
    return R.ok(Z.match_offer(offer))


@route(bp, "/match-offers", ["GET"], OFFER_READ_ROLES)
def list_match_offers():
    rows = S.all_rows("match_offers")
    filters = (
        "project_request_id",
        "volunteer_id",
        "scope_definition_id",
        "availability_window_id",
        "status",
    )
    for key in filters:
        value = flask_request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return R.paginate(rows, Z.match_offer)


@route(bp, "/match-offers/<offer_id>/accept", ["POST"], [C.ROLE_VOLUNTEER])
def accept_match_offer(offer_id):
    offer = G.g08_offer(offer_id)
    G.g15_owns_volunteer(offer["volunteer_id"])
    volunteer = S.get("volunteers", offer["volunteer_id"])
    req = S.get("project_requests", offer["project_request_id"])
    partner = S.get("partner_orgs", req["partner_org_id"])
    cycle = S.get("program_cycles", req["cycle_id"])
    scope = S.get("scope_definitions", offer["scope_definition_id"])
    window = S.get("availability_windows", offer["availability_window_id"])

    G.g22_offer_open(offer)
    G.g31_partner_not_suspended(partner)
    G.g32_credential_verified(volunteer)
    G.g33_volunteer_active(volunteer)
    G.g38_offer_not_expired(offer)
    G.g49_scope_approved(scope)
    G.g51_cycle_not_frozen(cycle)
    G.g53_partner_engagement_limit(partner)
    G.g54_volunteer_concurrency(volunteer)

    offer["status"] = "ACCEPTED"
    offer["responded_at"] = S.now()
    S.touch(offer)

    engagement = S.insert(
        "engagements",
        {
            "match_offer_id": offer["id"],
            "project_request_id": req["id"],
            "volunteer_id": volunteer["id"],
            "scope_definition_id": scope["id"],
            "cycle_id": req["cycle_id"],
            "availability_window_id": offer["availability_window_id"],
            "committed_hours": calc.dec(offer["reserved_hours"]),
            "work_status": "NOT_STARTED",
            "valuation_status": "UNVALUED",
            "quality_gate": "PENDING",
            "confidentiality_attested": False,
            "destruction_certificate_ref": None,
            "handoff_artifact_count": 0,
            "handoff_at": None,
            "terminated_at": None,
            "termination_reason": None,
        },
    )

    req["status"] = "ENGAGED"
    S.touch(req)

    # step three: a freeze caused by the new commitment sweeps the cycle
    if cycle is not None and calc.cycle_posture(cycle) == "FROZEN":
        domain.withdraw_frozen_cycle_offers(cycle["id"], req["id"])

    # independently: sibling offers on the same request are pulled as ADMIN
    domain.withdraw_open_offers_of_request(req, "ADMIN", bump_failed=False)

    return R.created(Z.engagement(engagement))


@route(bp, "/match-offers/<offer_id>/decline", ["POST"], [C.ROLE_VOLUNTEER])
def decline_match_offer(offer_id):
    offer = G.g08_offer(offer_id)
    G.g15_owns_volunteer(offer["volunteer_id"])
    payload = G.body()
    reason = G.v_enum(payload, "decline_reason", C.DECLINE_REASONS)
    G.g22_offer_open(offer)
    G.g38_offer_not_expired(offer)
    domain.release_offer(offer, "DECLINED", decline_reason=reason, bump_failed=True)
    return R.ok(Z.match_offer(offer))


@route(
    bp, "/match-offers/<offer_id>/withdraw", ["POST"], [C.ROLE_SCOPING_SPECIALIST]
)
def withdraw_match_offer(offer_id):
    offer = G.g08_offer(offer_id)
    payload = G.body()
    reason = G.v_enum(
        payload, "withdraw_reason", C.WITHDRAW_REASONS, required=False
    )
    G.g22_offer_open(offer)
    domain.release_offer(
        offer,
        "WITHDRAWN",
        withdraw_reason=reason,
        bump_failed=(reason != "ADMIN"),
    )
    return R.ok(Z.match_offer(offer))
