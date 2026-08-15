"""Payout endpoints (PRD section 3.6)."""

import db
import services
from errors import (
    ApiError,
    ERR_PAYOUT_NOT_CLEARABLE,
    ERR_PAYOUT_NOT_VOIDABLE,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_payout
from util import (
    body_json,
    check_no_fields,
    paginate,
    pagination_params,
    path_entity,
)

bp = make_blueprint("payouts")


@bp.get("/participants/<participant_id>/payouts")
def list_participant_payouts(participant_id):
    authenticate(ALL_ROLES)
    participant = path_entity("participants", participant_id, "participant")
    limit, offset = pagination_params()
    items = services.participant_payouts(participant["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_payout(p) for p in page], limit, offset, total, has_more
    )


@bp.post("/payouts/<payout_id>/mark-cleared")
def mark_cleared(payout_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_no_fields(body)
    payout = path_entity("payouts", payout_id, "payout")
    if payout["status"] != "ISSUED":
        raise ApiError(
            ERR_PAYOUT_NOT_CLEARABLE, 409,
            "mark-cleared requires an ISSUED payout",
        )
    now = db.now()
    payout["status"] = "CLEARED"
    payout["cleared_at"] = now
    db.touch(payout)
    # Linked election (if any) ACCEPTED -> SETTLED.
    if payout["distribution_election_id"]:
        election = db.get("elections", payout["distribution_election_id"])
        if election is not None and election["status"] == "ACCEPTED":
            election["status"] = "SETTLED"
            db.touch(election)
    # Resolve the participant by method.
    participant = db.get("participants", payout["participant_id"])
    if participant is not None:
        participant["distribution_status"] = (
            "PAID_OUT"
            if payout["method"] == "LUMP_SUM_CHECK"
            else "AUTO_ROLLED_OVER"
        )
        db.touch(participant)
    return success_obj(public_payout(payout), 200)


@bp.post("/payouts/<payout_id>/void")
def void_payout(payout_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_no_fields(body)
    payout = path_entity("payouts", payout_id, "payout")
    if payout["status"] != "STALE_UNCASHED":
        raise ApiError(
            ERR_PAYOUT_NOT_VOIDABLE, 409,
            "void requires a STALE_UNCASHED payout",
        )
    # No ledger movement: the uncashed gross never left
    # remaining_undistributed_cents.
    payout["status"] = "VOIDED"
    db.touch(payout)
    participant = db.get("participants", payout["participant_id"])
    if (
        participant is not None
        and participant["distribution_status"] == "ELECTION_ACCEPTED"
    ):
        participant["distribution_status"] = "PENDING_ELECTION"
        db.touch(participant)
    if payout["distribution_election_id"]:
        election = db.get("elections", payout["distribution_election_id"])
        if election is not None and election["status"] == "ACCEPTED":
            election["status"] = "SUPERSEDED"
            db.touch(election)
    return success_obj(public_payout(payout), 200)
