"""TeamRegistration service."""
from __future__ import annotations

from typing import Any

from ..auth import current_actor
from ..calculations import fx_convert
from ..clock import CLOCK, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .serializers import serialize_team_registration


def _require_tournament(tid: str) -> dict[str, Any]:
    t = get_store().tournaments.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", f"Tournament {tid} not found.")
    return t


def _require_registration(rid: str) -> dict[str, Any]:
    r = get_store().team_registrations.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", f"TeamRegistration {rid} not found.")
    return r


def create_team_registration(tid: str, body: dict[str, Any]) -> dict[str, Any]:
    t = _require_tournament(tid)
    user_id, _role = current_actor()
    for key in ("team_name", "manager_id", "region", "sponsors"):
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    if body["region"] not in {"NA", "EU", "APAC", "SA"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid region: {body['region']}")
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_REGISTRATION_NOT_OPEN",
                       f"Tournament not in REGISTRATION_OPEN (status={t['status']}).")
    if user_id != body["manager_id"]:
        raise ApiError("ERR_FORBIDDEN", "X-User-ID must equal manager_id.")

    store = get_store()
    # Duplicate team_name check (excluding WITHDRAWN)
    for existing in store.team_registrations.values():
        if existing["tournament_id"] != t["id"]:
            continue
        if existing["status"] == "WITHDRAWN":
            continue
        if existing["team_name"] == body["team_name"]:
            raise ApiError("ERR_DUPLICATE_TEAM_NAME",
                           f"team_name {body['team_name']!r} already exists in this tournament.")

    r = common_fields_create()
    r.update({
        "tournament_id": t["id"],
        "team_name": body["team_name"],
        "manager_id": body["manager_id"],
        "region": body["region"],
        "logo_url": body.get("logo_url"),
        "sponsors": list(body["sponsors"]),
        "seed_number": None,
        "ranking_points_snapshot": None,
        "entry_fee_paid_cents": 0,
        "status": "DRAFT",
    })
    store.team_registrations[r["id"]] = r
    return serialize_team_registration(r)


def get_team_registration(rid: str) -> dict[str, Any]:
    r = _require_registration(rid)
    user_id, role = current_actor()
    if role == "TeamManager" and r["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "TeamManager may only read own registration.")
    return serialize_team_registration(r)


def pay_entry_fee(rid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _role = current_actor()
    r = _require_registration(rid)
    if r["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Caller is not the manager of this registration.")

    t = get_store().tournaments.get(r["tournament_id"])
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Parent tournament not found.")

    # Auto-promote DRAFT to FEE_PENDING on first pay attempt
    if r["status"] == "DRAFT":
        r["status"] = "FEE_PENDING"

    if r["status"] != "FEE_PENDING":
        raise ApiError("ERR_INVALID_STATE", f"Registration not in FEE_PENDING (status={r['status']}).")

    for key in ("amount_cents", "currency"):
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    amount = int(body["amount_cents"])
    ccy = body["currency"]
    converted = fx_convert(amount, ccy, t["entry_fee_currency"])
    candidate_paid = int(r.get("entry_fee_paid_cents", 0)) + converted

    # ---------- Validation chain (priority order) ---------- #
    store = get_store()

    # 1) Roster: >= 5 MAIN contracts bound + each identity_verified
    main_contracts = [
        c for c in store.player_contracts.values()
        if c.get("team_id") == r["id"] and c.get("roster_slot") == "MAIN"
    ]
    if len(main_contracts) < 5:
        raise ApiError("ERR_ROSTER_INCOMPLETE",
                       f"Need at least 5 MAIN-slot contracts; have {len(main_contracts)}.")

    # 2) Identity verified
    for c in main_contracts:
        if not c.get("identity_verified"):
            raise ApiError("ERR_IDENTITY_NOT_VERIFIED",
                           f"Contract {c['id']} not identity-verified.")

    # 3) Underage check
    min_age = int(t.get("min_age", 16))
    for c in main_contracts:
        if int(c.get("player_age", 0)) < min_age:
            raise ApiError("ERR_PLAYER_UNDERAGE",
                           f"Player {c.get('player_id')} below min_age {min_age}.")

    # 4) Region check
    if t["region"] != "GLOBAL" and r["region"] != t["region"]:
        raise ApiError("ERR_REGION_MISMATCH",
                       f"Team region {r['region']} != Tournament region {t['region']}.")

    # 5) Ranking aggregate
    aggregate = sum(
        int(c.get("ranking_points", 0))
        for c in main_contracts
        if c.get("status") in {"ACTIVE", "PENDING_SIGNATURES"}
    )
    if aggregate < int(t.get("min_team_ranking_points", 0)):
        raise ApiError("ERR_TEAM_RANKING_INSUFFICIENT",
                       f"Aggregate ranking {aggregate} < min {t['min_team_ranking_points']}.")

    # 6) Fiscal — Entry fee insufficient
    if candidate_paid < int(t["entry_fee_cents"]):
        # Update entry_fee_paid_cents (cumulative) but DO NOT transition.
        r["entry_fee_paid_cents"] = candidate_paid
        bump_version(r)
        raise ApiError("ERR_ENTRY_FEE_INSUFFICIENT",
                       f"Paid {candidate_paid} < required {t['entry_fee_cents']}.")

    # 7) Tournament cap
    registered_count = sum(
        1 for x in store.team_registrations.values()
        if x["tournament_id"] == t["id"] and x["status"] == "REGISTERED"
    )
    if registered_count + 1 > int(t["max_teams"]):
        raise ApiError("ERR_TOURNAMENT_FULL",
                       f"Tournament max_teams={t['max_teams']} would be exceeded.")

    # All gates passed → transition.
    r["entry_fee_paid_cents"] = candidate_paid
    r["ranking_points_snapshot"] = aggregate
    r["status"] = "REGISTERED"
    bump_version(r)
    return serialize_team_registration(r)


def withdraw(rid: str) -> dict[str, Any]:
    user_id, _role = current_actor()
    r = _require_registration(rid)
    if r["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Caller is not the manager of this registration.")
    if r["status"] not in {"FEE_PENDING", "REGISTERED"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Registration in {r['status']}, cannot withdraw.")
    t = get_store().tournaments.get(r["tournament_id"])
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Parent tournament not found.")
    deadline = parse_iso(t["roster_lock_deadline"])
    if CLOCK.now >= deadline or t["status"] in {"ROSTER_LOCKED", "BRACKET_PUBLISHED",
                                                "IN_PROGRESS", "COMPLETED", "PRIZES_DISTRIBUTED"}:
        raise ApiError("ERR_ROSTER_LOCKED", "Roster lock deadline has passed.")
    refund_amount = int(r.get("entry_fee_paid_cents", 0)) if r["status"] == "REGISTERED" else 0
    r["status"] = "WITHDRAWN"
    if refund_amount > 0:
        r["entry_fee_paid_cents"] = 0
    bump_version(r)
    return serialize_team_registration(r)
