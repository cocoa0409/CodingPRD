"""PlayerContract service — multi-party signing chain, amendments, termination."""
from __future__ import annotations

from typing import Any

from ..auth import current_actor
from ..clock import CLOCK, parse_iso
from ..errors import ApiError
from ..store import (
    bump_version,
    common_fields_append_only,
    common_fields_create,
    get_store,
    now_iso,
)


VALID_CONTRACT_TYPE = {"EXCLUSIVE", "LOAN", "FREE_AGENT"}
VALID_SLOT = {"MAIN", "SUBSTITUTE"}
VALID_DISPUTE = {"ARBITRATION", "LITIGATION", "MEDIATION"}
VALID_PARTY = {"PLAYER", "TEAM_MANAGER", "LEAGUE_ADMIN"}


def _require_contract(cid: str) -> dict[str, Any]:
    c = get_store().player_contracts.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"PlayerContract {cid} not found.")
    return c


def _require_team(team_id: str) -> dict[str, Any]:
    r = get_store().team_registrations.get(team_id)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", f"TeamRegistration {team_id} not found.")
    return r


def create_contract(body: dict[str, Any]) -> dict[str, Any]:
    user_id, _role = current_actor()
    required = [
        "player_id", "player_legal_name", "player_age", "team_id",
        "contract_type", "roster_slot", "term_start", "term_end",
        "monthly_compensation_cents", "compensation_currency",
        "ranking_points", "required_signatories",
    ]
    for key in required:
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    if body["contract_type"] not in VALID_CONTRACT_TYPE:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid contract_type: {body['contract_type']}")
    if body["roster_slot"] not in VALID_SLOT:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid roster_slot: {body['roster_slot']}")
    dispute = body.get("dispute_resolution_clause", "ARBITRATION")
    if dispute not in VALID_DISPUTE:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid dispute_resolution_clause: {dispute}")
    if body["compensation_currency"] not in {"USD", "EUR", "KRW", "CNY"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid compensation_currency: {body['compensation_currency']}")

    team = _require_team(body["team_id"])
    if user_id != team["manager_id"]:
        raise ApiError("ERR_FORBIDDEN", "Caller is not the manager of the destination team.")

    # Validate signatories
    sigs = body.get("required_signatories", [])
    if not isinstance(sigs, list):
        raise ApiError("ERR_BAD_REQUEST", "required_signatories must be a list.")
    for s in sigs:
        if not isinstance(s, dict) or s.get("party") not in VALID_PARTY:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid required_signatories entry: {s!r}")

    # Roster-mutation gate: only before roster_lock_deadline
    t = get_store().tournaments.get(team["tournament_id"])
    if t is not None:
        if t["status"] in {"ROSTER_LOCKED", "BRACKET_PUBLISHED", "IN_PROGRESS",
                            "COMPLETED", "PRIZES_DISTRIBUTED", "CANCELLED"}:
            raise ApiError("ERR_ROSTER_LOCKED", "Roster is locked for this tournament.")
        deadline = parse_iso(t["roster_lock_deadline"])
        if CLOCK.now >= deadline:
            raise ApiError("ERR_ROSTER_LOCKED", "Roster lock deadline has passed.")

    term_start = parse_iso(body["term_start"])
    term_end = parse_iso(body["term_end"])
    if term_end <= term_start:
        raise ApiError("ERR_INVALID_CONTRACT_TERM", "term_end must be strictly after term_start.")

    c = common_fields_create()
    c.update({
        "player_id": body["player_id"],
        "player_legal_name": body["player_legal_name"],
        "player_age": int(body["player_age"]),
        "identity_verified": False,
        "team_id": team["id"],
        "contract_type": body["contract_type"],
        "roster_slot": body["roster_slot"],
        "term_start": body["term_start"],
        "term_end": body["term_end"],
        "monthly_compensation_cents": int(body["monthly_compensation_cents"]),
        "compensation_currency": body["compensation_currency"],
        "dispute_resolution_clause": dispute,
        "ranking_points": int(body["ranking_points"]),
        "required_signatories": list(sigs),
        "signatures": [],
        "status": "DRAFT",
        "signed_version_id": None,
    })
    get_store().player_contracts[c["id"]] = c
    return dict(c)


def get_contract(cid: str) -> dict[str, Any]:
    c = _require_contract(cid)
    user_id, role = current_actor()
    if role == "Player" and c["player_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Player can only read their own contracts.")
    if role == "TeamManager":
        team = get_store().team_registrations.get(c["team_id"])
        if team is None or team["manager_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "TeamManager can only read own-team contracts.")
    return dict(c)


def file_identity_verification(cid: str, body: dict[str, Any]) -> dict[str, Any]:
    c = _require_contract(cid)
    for key in ("document_hash", "jurisdiction", "status"):
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    if body["status"] not in {"VERIFIED", "REJECTED"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid status: {body['status']}")
    if body["status"] == "REJECTED" and not body.get("rejection_reason"):
        raise ApiError("ERR_BAD_REQUEST", "rejection_reason required when status=REJECTED.")
    v = common_fields_append_only()
    v.update({
        "player_id": c["player_id"],
        "contract_id": c["id"],
        "document_hash": body["document_hash"],
        "jurisdiction": body["jurisdiction"],
        "status": body["status"],
        "rejection_reason": body.get("rejection_reason"),
    })
    get_store().identity_verifications[v["id"]] = v
    if body["status"] == "VERIFIED":
        c["identity_verified"] = True
        bump_version(c)
    return dict(v)


def initiate_signing(cid: str) -> dict[str, Any]:
    user_id, _ = current_actor()
    c = _require_contract(cid)
    team = get_store().team_registrations.get(c["team_id"])
    if team is None or team["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "TeamManager can only initiate own-team contracts.")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Contract in {c['status']}, expected DRAFT.")
    if not c.get("identity_verified"):
        raise ApiError("ERR_IDENTITY_NOT_VERIFIED", "Identity must be verified before initiate-signing.")
    term_end = parse_iso(c["term_end"])
    term_start = parse_iso(c["term_start"])
    if term_end <= term_start:
        raise ApiError("ERR_INVALID_CONTRACT_TERM", "term_end must be strictly after term_start.")
    if not c["required_signatories"]:
        raise ApiError("ERR_NO_SIGNATORIES", "required_signatories must be non-empty.")
    c["status"] = "PENDING_SIGNATURES"
    bump_version(c)
    return dict(c)


_ROLE_TO_PARTY = {
    "Player": "PLAYER",
    "TeamManager": "TEAM_MANAGER",
    "LeagueAdmin": "LEAGUE_ADMIN",
}


def sign_contract(cid: str) -> dict[str, Any]:
    user_id, role = current_actor()
    c = _require_contract(cid)
    if c["status"] not in {"PENDING_SIGNATURES", "AMENDMENT_PENDING"}:
        raise ApiError("ERR_INVALID_STATE", f"Contract in {c['status']}, not signable.")
    sigs = c["signatures"]
    required = c["required_signatories"]
    if len(sigs) >= len(required):
        raise ApiError("ERR_INVALID_STATE", "All required signatures already collected.")
    expected_party = required[len(sigs)]["party"]
    if _ROLE_TO_PARTY.get(role) != expected_party:
        raise ApiError("ERR_WRONG_SIGNATORY",
                       f"Expected {expected_party}, got role {role}.")
    # Ownership semantics
    if role == "Player" and c["player_id"] != user_id:
        raise ApiError("ERR_WRONG_SIGNATORY", "Player X-User-ID must equal contract.player_id.")
    if role == "TeamManager":
        team = get_store().team_registrations.get(c["team_id"])
        if team is None or team["manager_id"] != user_id:
            raise ApiError("ERR_WRONG_SIGNATORY", "TeamManager X-User-ID must equal team.manager_id.")

    new_sig = {
        "party": expected_party,
        "signed_by_user_id": user_id,
        "signed_at": now_iso(),
    }
    c["signatures"] = sigs + [new_sig]
    bump_version(c)

    # If all collected, transition to ACTIVE
    if len(c["signatures"]) == len(required):
        team = get_store().team_registrations.get(c["team_id"])
        if team is not None and team["status"] in {"WITHDRAWN", "DISQUALIFIED"}:
            raise ApiError("ERR_TEAM_NOT_ELIGIBLE", "Cannot finalise contract on an ineligible team.")
        if c["status"] == "AMENDMENT_PENDING":
            # Don't auto-active; requires admin approval per PRD §3.3
            return dict(c)
        c["status"] = "ACTIVE"
        c["signed_version_id"] = str(c["version"])
        bump_version(c)
    return dict(c)


def file_amendment(cid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    c = _require_contract(cid)
    team = get_store().team_registrations.get(c["team_id"])
    if team is None or team["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "TeamManager can only amend own-team contracts.")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Contract in {c['status']}, expected ACTIVE.")
    if c.get("signed_version_id") is None:
        raise ApiError("ERR_INVALID_STATE", "Contract has no pinned signed_version_id.")
    term_end = parse_iso(c["term_end"])
    if CLOCK.now >= term_end:
        raise ApiError("ERR_INVALID_STATE", "Contract term has ended.")
    if "proposed_changes" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing proposed_changes.")
    amendment = common_fields_append_only()
    amendment.update({
        "contract_id": c["id"],
        "proposed_changes": body["proposed_changes"],
        "status": "PENDING",
    })
    get_store().amendments[amendment["id"]] = amendment
    c["status"] = "AMENDMENT_PENDING"
    c["signed_version_id"] = None
    # Reset signatures for re-signing
    c["signatures"] = []
    bump_version(c)
    # Return contract with amendment id surfaced for the route to use
    out = dict(c)
    out["latest_amendment_id"] = amendment["id"]
    return out


def approve_amendment(cid: str, aid: str) -> dict[str, Any]:
    c = _require_contract(cid)
    a = get_store().amendments.get(aid)
    if a is None or a.get("contract_id") != cid:
        raise ApiError("ERR_NOT_FOUND", f"Amendment {aid} not found for contract {cid}.")
    if c["status"] != "AMENDMENT_PENDING":
        raise ApiError("ERR_INVALID_STATE", f"Contract in {c['status']}, expected AMENDMENT_PENDING.")
    # Check all required signatories re-signed (signatures length matches required)
    if len(c["signatures"]) != len(c["required_signatories"]):
        raise ApiError("ERR_INVALID_STATE", "Not all required parties have re-signed.")
    a["status"] = "APPROVED"
    c["status"] = "ACTIVE"
    bump_version(c)
    c["signed_version_id"] = str(c["version"])
    return dict(c)


def terminate_contract(cid: str, body: dict[str, Any]) -> dict[str, Any]:
    c = _require_contract(cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Contract in {c['status']}, expected ACTIVE.")
    reason = body.get("reason")
    if not reason:
        raise ApiError("ERR_BAD_REQUEST", "reason is required.")
    c["status"] = "TERMINATED"
    c["termination_reason"] = reason
    bump_version(c)
    return dict(c)
