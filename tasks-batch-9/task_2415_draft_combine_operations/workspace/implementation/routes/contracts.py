"""Slotted rookie contracts, the rookie pool and the undrafted window
(PRD 3.8, 2.8)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import logic
import respond
import validate
import versioning
from db import db
from errors import ApiError

bp = Blueprint("contracts", __name__)

READ_ROLES = ["LeagueDraftAdmin", "ClubGM", "ProspectAgent"]

STATUS_ROLES = {"SIGN": ("ProspectAgent",), "VOID": ("ClubGM",)}


def _mismatch():
    raise ApiError(
        "ERR_CONTRACT_PICK_MISMATCH",
        "The contract does not cohere with the supplied pick or origin.",
    )


@bp.post("/player-contracts")
def create_contract():
    user_id, role = auth.begin(["ClubGM"])
    data = validate.body()
    prospect_id = validate.string(data, "prospect_id")
    club_id = validate.string(data, "club_id")
    draft_pick_id = validate.string(data, "draft_pick_id", required=False)
    origin = validate.enum(data, "origin", K.CONTRACT_ORIGINS)
    expected_version = validate.integer(data, "expected_prospect_version")
    udfa_bonus = validate.integer(
        data, "udfa_signing_bonus_cents", required=False, minimum=0
    )

    prospect = logic.fk_lookup(db.prospects, prospect_id, "prospect")
    club = logic.fk_lookup(db.clubs, club_id, "club")
    pick = None
    if draft_pick_id is not None:
        pick = logic.fk_lookup(db.draft_picks, draft_pick_id, "draft pick")

    logic.own_club(role, user_id, club["id"])
    cycle = derive.prospect_cycle(prospect)
    if origin == "UDFA":
        logic.require_phase(cycle, ("UDFA_WINDOW",))
    logic.require_unfrozen(cycle)

    if expected_version != prospect["version"]:
        raise ApiError(
            "ERR_STALE_PARENT_VERSION", "The supplied prospect version is not current."
        )

    if origin == "UDFA":
        close_at = cycle["udfa_window_close_at"]
        if close_at is None or db.now >= close_at:
            raise ApiError(
                "ERR_UDFA_WINDOW_CLOSED", "The undrafted free agent window is closed."
            )

    logic.require_same_cycle(club["draft_cycle_id"], prospect["draft_cycle_id"])
    if pick is not None:
        logic.require_same_cycle(pick["draft_cycle_id"], prospect["draft_cycle_id"])

    if origin == "DRAFTED":
        if (
            pick is None
            or pick["status"] != "USED"
            or pick["selected_prospect_id"] != prospect["id"]
            or pick["owning_club_id"] != club["id"]
        ):
            _mismatch()
    else:
        if pick is not None or udfa_bonus is None:
            _mismatch()
        if udfa_bonus > derive.udfa_pool_remaining(club):
            raise ApiError(
                "ERR_UDFA_POOL_EXHAUSTED",
                "The club's undrafted signing pool cannot absorb this bonus.",
            )

    if origin == "DRAFTED":
        slot = calc.slotted_contract_value(
            pick["round_number"], pick["pick_in_round"], "DRAFTED"
        )
    else:
        slot = calc.slotted_contract_value(0, 1, "UDFA", udfa_bonus_cents=udfa_bonus)

    for existing in logic.prospect_contracts(prospect["id"]):
        if existing["club_id"] == club["id"] and existing["status"] == "OFFERED":
            existing["status"] = "LAPSED"

    rec = db.insert(
        db.player_contracts,
        "PlayerContract",
        {
            "prospect_id": prospect["id"],
            "club_id": club["id"],
            "draft_pick_id": pick["id"] if pick is not None else None,
            "origin": origin,
            "status": "OFFERED",
            "contract_years": slot["contract_years"],
            "total_value_cents": slot["total_value_cents"],
            "signing_bonus_cents": slot["signing_bonus_cents"],
            "first_year_cap_charge_cents": slot["first_year_cap_charge_cents"],
            "total_cap_commitment_cents": slot["total_cap_commitment_cents"],
            "signed_at": None,
        },
    )
    if prospect["signing_status"] != "SIGNED":
        prospect["signing_status"] = "OFFER_OUT"
    versioning.force(prospect)
    return respond.created(rec)


@bp.get("/player-contracts/<contract_id>")
def get_contract(contract_id):
    auth.begin(READ_ROLES)
    return respond.one(logic.path_lookup(db.player_contracts, contract_id))


@bp.get("/player-contracts")
def list_contracts():
    auth.begin(READ_ROLES)
    limit, offset = validate.pagination()
    prospect_id = validate.query_str("prospect_id")
    club_id = validate.query_str("club_id")
    draft_pick_id = validate.query_str("draft_pick_id")
    origin = validate.query_enum("origin", K.CONTRACT_ORIGINS)
    status = validate.query_enum("status", K.CONTRACT_STATUSES)
    rows = list(db.player_contracts.values())
    if prospect_id is not None:
        rows = [r for r in rows if r["prospect_id"] == prospect_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if draft_pick_id is not None:
        rows = [r for r in rows if r["draft_pick_id"] == draft_pick_id]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.listing(logic.by_created(rows), limit, offset)


@bp.post("/player-contracts/<contract_id>/status")
def contract_status(contract_id):
    user_id, role = auth.actor()
    auth.require(role, ["ProspectAgent", "ClubGM"])
    auth.require_action_role(role, validate.peek("action"), STATUS_ROLES)

    data = validate.body()
    action = validate.enum(data, "action", ("SIGN", "VOID"))
    contract = logic.path_lookup(db.player_contracts, contract_id)
    prospect = db.prospects.get(contract["prospect_id"])
    club = db.clubs.get(contract["club_id"])
    cycle = derive.club_cycle(club) if club is not None else None

    if action == "SIGN":
        logic.own_prospect(role, user_id, contract["prospect_id"])
    else:
        logic.own_club(role, user_id, contract["club_id"])

    if action == "SIGN" and cycle is not None:
        logic.require_unfrozen(cycle)

    if action == "SIGN":
        if contract["status"] != "OFFERED":
            raise logic.invalid_transition("Only an OFFERED contract may be signed.")
        if contract["origin"] == "UDFA":
            close_at = cycle["udfa_window_close_at"] if cycle is not None else None
            if close_at is None or db.now >= close_at:
                raise ApiError(
                    "ERR_UDFA_WINDOW_CLOSED",
                    "The undrafted free agent window is closed.",
                )
        charged = 0
        for other in derive.club_contracts(contract["club_id"]):
            if other["status"] == "SIGNED":
                charged += other["first_year_cap_charge_cents"]
        if (
            charged + contract["first_year_cap_charge_cents"]
            > club["rookie_pool_total_cents"]
        ):
            raise ApiError(
                "ERR_ROOKIE_POOL_EXCEEDED",
                "Signing this contract would exceed the club's rookie pool.",
            )
        contract["status"] = "SIGNED"
        contract["signed_at"] = db.now
        if prospect is not None:
            prospect["signing_status"] = "SIGNED"
        return respond.ok(contract)

    # VOID
    if contract["status"] not in ("OFFERED", "SIGNED"):
        raise logic.invalid_transition(
            "Only an OFFERED or SIGNED contract may be voided."
        )
    contract["status"] = "VOIDED"
    if prospect is not None:
        prospect["signing_status"] = "UNSIGNED"
    return respond.ok(contract)
