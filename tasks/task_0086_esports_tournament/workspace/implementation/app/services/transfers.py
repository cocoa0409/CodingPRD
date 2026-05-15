"""TransferWindow + TransferOffer services."""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from ..audit import log_event
from ..auth import current_actor
from ..calculations import fx_convert
from ..clock import CLOCK, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso


VALID_CCY = {"USD", "EUR", "KRW", "CNY"}


def _require_window(wid: str) -> dict[str, Any]:
    w = get_store().transfer_windows.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferWindow {wid} not found.")
    return w


def _require_offer(oid: str) -> dict[str, Any]:
    o = get_store().transfer_offers.get(oid)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", f"TransferOffer {oid} not found.")
    return o


def create_window(body: dict[str, Any]) -> dict[str, Any]:
    for k in ("name", "opens_at", "closes_at"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    parse_iso(body["opens_at"])
    parse_iso(body["closes_at"])
    w = common_fields_create()
    w.update({
        "name": body["name"],
        "opens_at": body["opens_at"],
        "closes_at": body["closes_at"],
        "cooling_off_days": int(body.get("cooling_off_days", 30)),
    })
    get_store().transfer_windows[w["id"]] = w
    return dict(w)


def get_window(wid: str) -> dict[str, Any]:
    return dict(_require_window(wid))


def _check_window_open(w: dict[str, Any]) -> None:
    o = parse_iso(w["opens_at"])
    c = parse_iso(w["closes_at"])
    if not (o <= CLOCK.now < c):
        raise ApiError("ERR_WINDOW_CLOSED",
                       "Clock.now is outside [opens_at, closes_at).")


def _check_cooling_off(player_id: str, window: dict[str, Any]) -> None:
    """No same-player_id LEAGUE_APPROVED offer within cooling_off_days."""
    days = int(window["cooling_off_days"])
    threshold = CLOCK.now - timedelta(days=days)
    for o in get_store().transfer_offers.values():
        if o["player_id"] != player_id:
            continue
        if o["status"] != "LEAGUE_APPROVED":
            continue
        decision_at = o.get("league_decision_at")
        if not decision_at:
            continue
        try:
            d = parse_iso(decision_at)
        except Exception:
            continue
        if d >= threshold:
            raise ApiError("ERR_COOLING_OFF_ACTIVE",
                           f"Player {player_id} has a recent LEAGUE_APPROVED transfer within cooling-off window.")


def propose_offer(body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    for k in ("player_id", "from_team_id", "to_team_id", "window_id", "transfer_fee_cents", "transfer_fee_currency"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    if body["transfer_fee_currency"] not in VALID_CCY:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid currency: {body['transfer_fee_currency']}")
    store = get_store()
    if body["from_team_id"] not in store.team_registrations:
        raise ApiError("ERR_NOT_FOUND", f"from_team_id {body['from_team_id']} not found.")
    if body["to_team_id"] not in store.team_registrations:
        raise ApiError("ERR_NOT_FOUND", f"to_team_id {body['to_team_id']} not found.")
    w = _require_window(body["window_id"])

    # Caller must be manager of from_team or to_team
    from_team = store.team_registrations[body["from_team_id"]]
    to_team = store.team_registrations[body["to_team_id"]]
    if user_id != from_team["manager_id"] and user_id != to_team["manager_id"]:
        raise ApiError("ERR_FORBIDDEN", "Caller is not a manager of from_team or to_team.")

    _check_window_open(w)
    _check_cooling_off(body["player_id"], w)

    o = common_fields_create()
    o.update({
        "player_id": body["player_id"],
        "from_team_id": body["from_team_id"],
        "to_team_id": body["to_team_id"],
        "window_id": w["id"],
        "transfer_fee_cents": int(body["transfer_fee_cents"]),
        "transfer_fee_currency": body["transfer_fee_currency"],
        "status": "PROPOSED",
        "from_team_decision_at": None,
        "to_team_decision_at": None,
        "league_decision_at": None,
        "history": [{
            "round": 1, "by": "FROM" if user_id == from_team["manager_id"] else "TO",
            "action": "PROPOSE",
            "terms": {
                "transfer_fee_cents": int(body["transfer_fee_cents"]),
                "transfer_fee_currency": body["transfer_fee_currency"],
            },
            "at": now_iso(),
        }],
    })
    store.transfer_offers[o["id"]] = o
    return dict(o)


def get_offer(oid: str) -> dict[str, Any]:
    return dict(_require_offer(oid))


def counter_offer(oid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    o = _require_offer(oid)
    if o["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", f"Offer in {o['status']}, expected PROPOSED.")
    from_team = get_store().team_registrations.get(o["from_team_id"])
    if from_team is None or from_team["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Only the from_team manager may counter.")
    w = _require_window(o["window_id"])
    _check_window_open(w)
    _check_cooling_off(o["player_id"], w)
    for k in ("transfer_fee_cents", "transfer_fee_currency"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    if body["transfer_fee_currency"] not in VALID_CCY:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid currency: {body['transfer_fee_currency']}")
    o["transfer_fee_cents"] = int(body["transfer_fee_cents"])
    o["transfer_fee_currency"] = body["transfer_fee_currency"]
    o["history"].append({
        "round": len(o["history"]) + 1,
        "by": "FROM",
        "action": "COUNTER",
        "terms": {
            "transfer_fee_cents": o["transfer_fee_cents"],
            "transfer_fee_currency": o["transfer_fee_currency"],
        },
        "at": now_iso(),
    })
    o["status"] = "COUNTERED"
    bump_version(o)
    return dict(o)


def accept_offer(oid: str) -> dict[str, Any]:
    user_id, _ = current_actor()
    o = _require_offer(oid)
    if o["status"] not in {"PROPOSED", "COUNTERED"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Offer in {o['status']}, expected PROPOSED or COUNTERED.")
    from_team = get_store().team_registrations.get(o["from_team_id"])
    to_team = get_store().team_registrations.get(o["to_team_id"])
    # If status is PROPOSED, the from_team manager accepts.
    # If status is COUNTERED, the to_team manager accepts (per scaffold)
    if o["status"] == "PROPOSED":
        if from_team is None or from_team["manager_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Only the from_team manager may accept a PROPOSED offer.")
    else:  # COUNTERED
        if to_team is None or to_team["manager_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Only the to_team manager may accept a COUNTERED offer.")
    o["status"] = "ACCEPTED_BY_FROM"
    o["from_team_decision_at"] = now_iso()
    o["history"].append({
        "round": len(o["history"]) + 1, "by": "FROM",
        "action": "ACCEPT", "terms": {}, "at": now_iso(),
    })
    bump_version(o)
    return dict(o)


def co_accept_offer(oid: str) -> dict[str, Any]:
    user_id, _ = current_actor()
    o = _require_offer(oid)
    if o["status"] != "ACCEPTED_BY_FROM":
        raise ApiError("ERR_INVALID_STATE",
                       f"Offer in {o['status']}, expected ACCEPTED_BY_FROM.")
    to_team = get_store().team_registrations.get(o["to_team_id"])
    if to_team is None or to_team["manager_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Only the to_team manager may co-accept.")
    w = _require_window(o["window_id"])
    _check_window_open(w)
    o["status"] = "ACCEPTED_BY_BOTH"
    o["to_team_decision_at"] = now_iso()
    o["history"].append({
        "round": len(o["history"]) + 1, "by": "TO",
        "action": "ACCEPT", "terms": {}, "at": now_iso(),
    })
    bump_version(o)
    return dict(o)


def reject_offer(oid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, role = current_actor()
    o = _require_offer(oid)
    if o["status"] not in {"PROPOSED", "COUNTERED", "ACCEPTED_BY_FROM", "ACCEPTED_BY_BOTH"}:
        raise ApiError("ERR_INVALID_STATE", f"Offer in {o['status']}, cannot reject.")
    from_team = get_store().team_registrations.get(o["from_team_id"])
    to_team = get_store().team_registrations.get(o["to_team_id"])
    if role == "TeamManager":
        if (from_team is None or from_team["manager_id"] != user_id) and (to_team is None or to_team["manager_id"] != user_id):
            raise ApiError("ERR_FORBIDDEN", "TeamManager must be either from-team or to-team manager.")
    o["status"] = "REJECTED"
    if "reason" in body:
        o["reject_reason"] = body["reason"]
    o["history"].append({
        "round": len(o["history"]) + 1, "by": "ADMIN" if role == "LeagueAdmin" else "TEAM",
        "action": "REJECT", "terms": {"reason": body.get("reason")}, "at": now_iso(),
    })
    bump_version(o)
    return dict(o)


def league_approve(oid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    o = _require_offer(oid)
    decision = body.get("decision", "APPROVE")
    if o["status"] != "ACCEPTED_BY_BOTH":
        raise ApiError("ERR_INVALID_STATE",
                       f"Offer in {o['status']}, expected ACCEPTED_BY_BOTH.")
    if decision == "REJECT":
        o["status"] = "REJECTED"
        o["league_decision_at"] = now_iso()
        bump_version(o)
        return dict(o)
    # APPROVE branch
    w = _require_window(o["window_id"])
    # PRD §3.7: any operation gated by the window rejects outside
    # [opens_at, closes_at) with ERR_WINDOW_CLOSED. ERR_WINDOW_CLOSED
    # precedes ERR_COOLING_OFF_ACTIVE in §2.9 precedence.
    opens = parse_iso(w["opens_at"])
    closes = parse_iso(w["closes_at"])
    if not (opens <= CLOCK.now < closes):
        raise ApiError("ERR_WINDOW_CLOSED",
                       "Clock.now is outside [opens_at, closes_at).")
    _check_cooling_off(o["player_id"], w)
    # Player's current PlayerContract.status == ACTIVE
    store = get_store()
    pc = None
    for c in store.player_contracts.values():
        if c["player_id"] == o["player_id"] and c["team_id"] == o["from_team_id"]:
            pc = c
            break
    if pc is None or pc["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE",
                       f"Player {o['player_id']} has no ACTIVE contract on from_team.")

    before = copy.deepcopy(o)
    # Hop 1: reassign PlayerContract.team_id
    pc["team_id"] = o["to_team_id"]
    bump_version(pc)
    # Hop 2: transfer-fee ledger
    t = store.tournaments.get(store.team_registrations[o["to_team_id"]]["tournament_id"])
    if t is not None:
        fee_converted = fx_convert(int(o["transfer_fee_cents"]), o["transfer_fee_currency"], t["entry_fee_currency"])
        to_team = store.team_registrations[o["to_team_id"]]
        from_team = store.team_registrations[o["from_team_id"]]
        to_team["entry_fee_paid_cents"] = int(to_team.get("entry_fee_paid_cents", 0)) - fee_converted
        from_team["entry_fee_paid_cents"] = int(from_team.get("entry_fee_paid_cents", 0)) + fee_converted
        bump_version(to_team)
        bump_version(from_team)
    # Hop 3: audit log
    o["status"] = "LEAGUE_APPROVED"
    o["league_decision_at"] = now_iso()
    bump_version(o)
    log_event("TRANSFER_OFFER", o["id"], user_id, "LeagueAdmin", "APPROVE_TRANSFER",
              {"before": before, "after": copy.deepcopy(o)})
    return dict(o)
