"""Compensatory claims: submission, scoring preview and verification
(PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import logic
import respond
import validate
from db import db

bp = Blueprint("claims", __name__)

READ_ROLES = ["LeagueDraftAdmin", "ClubGM"]


@bp.post("/compensatory-claims")
def create_claim():
    user_id, role = auth.begin(["ClubGM"])
    data = validate.body()
    cycle_id = validate.string(data, "draft_cycle_id")
    club_id = validate.string(data, "club_id")
    claim_type = validate.enum(data, "claim_type", K.CLAIM_TYPES)
    player_name = validate.string(data, "player_name")
    departed_apy_cents = validate.integer(data, "departed_apy_cents", minimum=0)
    snap_pct = validate.number(data, "snap_pct", minimum=0, maximum=1)
    postseason_honor = validate.enum(
        data,
        "postseason_honor",
        K.POSTSEASON_HONORS,
        required=False,
        default="NONE",
    )

    cycle = logic.fk_lookup(db.draft_cycles, cycle_id, "draft cycle")
    club = logic.fk_lookup(db.clubs, club_id, "club")
    logic.own_club(role, user_id, club["id"])
    logic.require_unfrozen(cycle)
    logic.require_same_cycle(club["draft_cycle_id"], cycle["id"])

    authoritative, advisory = calc.comp_scores(
        departed_apy_cents, snap_pct, postseason_honor
    )
    rec = db.insert(
        db.compensatory_claims,
        "CompensatoryClaim",
        {
            "draft_cycle_id": cycle["id"],
            "club_id": club["id"],
            "claim_type": claim_type,
            "player_name": player_name,
            "departed_apy_cents": departed_apy_cents,
            "snap_pct": snap_pct,
            "postseason_honor": postseason_honor,
            "status": "SUBMITTED",
            "claim_score": authoritative,
            "advisory_snap_adjusted_score": advisory,
            "qualifies": authoritative >= K.COMP_QUALIFY_SCORE_MIN,
            "awarded_round": 0,
            "awarded_sequence": 0,
        },
    )
    return respond.created(rec)


@bp.get("/compensatory-claims/<claim_id>")
def get_claim(claim_id):
    auth.begin(READ_ROLES)
    return respond.one(logic.path_lookup(db.compensatory_claims, claim_id))


@bp.get("/compensatory-claims")
def list_claims():
    auth.begin(READ_ROLES)
    limit, offset = validate.pagination()
    cycle_id = validate.query_str("draft_cycle_id")
    club_id = validate.query_str("club_id")
    claim_type = validate.query_enum("claim_type", K.CLAIM_TYPES)
    status = validate.query_enum("status", K.CLAIM_STATUSES)
    rows = list(db.compensatory_claims.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["draft_cycle_id"] == cycle_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if claim_type is not None:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.listing(logic.by_claim_score(rows), limit, offset)


@bp.post("/compensatory-claims/<claim_id>/verify")
def verify_claim(claim_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    action = validate.enum(data, "action", ("VERIFY", "REJECT"))
    claim = logic.path_lookup(db.compensatory_claims, claim_id)
    cycle = db.draft_cycles.get(claim["draft_cycle_id"])

    if action == "VERIFY" and cycle is not None:
        logic.require_phase(cycle, ("COMBINE_WEEK", "ORDER_PENDING"))
    if cycle is not None:
        logic.require_unfrozen(cycle)

    if claim["status"] != "SUBMITTED":
        raise logic.invalid_transition("Only a SUBMITTED claim may be decided.")
    claim["status"] = "VERIFIED" if action == "VERIFY" else "REJECTED"
    return respond.ok(claim)
