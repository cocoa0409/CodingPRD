"""Trade proposal, voting, accept/reject/cancel, and execution."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from core.errors import (
    err_faab_insufficient,
    err_invalid_state,
    err_not_eligible_voter,
    err_not_team_owner,
    err_player_no_longer_eligible,
    err_player_not_on_roster,
    err_reference_not_found,
    err_resource_not_found,
    err_trade_not_open_for_voting,
    err_two_way_faab_forbidden,
    err_validation,
)
from core.store import store
from core.utils import format_iso, new_id, now_iso, parse_iso
from services.timestamps import stamp_create, stamp_update


def propose_trade(league_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    from services.league_service import get_league
    league = get_league(league_id)

    proposing_team_id = body.get("proposing_team_id")
    counterparty_team_id = body.get("counterparty_team_id")
    send_player_ids = body.get("send_player_ids")
    receive_player_ids = body.get("receive_player_ids")
    send_faab = body.get("send_faab_dollars", 0)
    receive_faab = body.get("receive_faab_dollars", 0)

    if not proposing_team_id or not counterparty_team_id:
        raise err_validation("proposing_team_id and counterparty_team_id required.")
    if proposing_team_id == counterparty_team_id:
        raise err_validation("proposing and counterparty teams must differ.")

    proposing = store.teams.get(proposing_team_id)
    counterparty = store.teams.get(counterparty_team_id)
    if not proposing or proposing["league_id"] != league_id:
        raise err_reference_not_found(f"Proposing team {proposing_team_id} not in league.")
    if not counterparty or counterparty["league_id"] != league_id:
        raise err_reference_not_found(f"Counterparty team {counterparty_team_id} not in league.")

    if proposing["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    if not isinstance(send_player_ids, list) or not send_player_ids:
        raise err_validation("send_player_ids must be non-empty array.")
    if not isinstance(receive_player_ids, list) or not receive_player_ids:
        raise err_validation("receive_player_ids must be non-empty array.")

    # Reference checks
    for pid in send_player_ids + receive_player_ids:
        if pid not in store.players:
            raise err_reference_not_found(f"Player {pid} not found.")

    if not isinstance(send_faab, int) or isinstance(send_faab, bool) or send_faab < 0:
        raise err_validation("send_faab_dollars must be a non-negative integer.")
    if not isinstance(receive_faab, int) or isinstance(receive_faab, bool) or receive_faab < 0:
        raise err_validation("receive_faab_dollars must be a non-negative integer.")

    if send_faab > 0 and receive_faab > 0:
        raise err_two_way_faab_forbidden()

    # Players actually on rosters
    proposer_players = set(store.players_on_team(proposing_team_id))
    counterparty_players = set(store.players_on_team(counterparty_team_id))
    for pid in send_player_ids:
        if pid not in proposer_players:
            raise err_player_not_on_roster(f"Player {pid} not on proposing team's roster.")
    for pid in receive_player_ids:
        if pid not in counterparty_players:
            raise err_player_not_on_roster(f"Player {pid} not on counterparty's roster.")

    trade = {
        "league_id": league_id,
        "proposing_team_id": proposing_team_id,
        "counterparty_team_id": counterparty_team_id,
        "send_player_ids": list(send_player_ids),
        "receive_player_ids": list(receive_player_ids),
        "send_faab_dollars": send_faab,
        "receive_faab_dollars": receive_faab,
        "status": "OFFERED",
        "review_deadline_ts": None,
        "veto_count": 0,
    }
    stamp_create(trade)
    store.trade_proposals[trade["id"]] = trade
    return trade


def list_trades(league_id: str, status: Optional[str] = None, team_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from services.league_service import get_league
    get_league(league_id)
    items = [t for t in store.trade_proposals.values() if t["league_id"] == league_id]
    if status:
        items = [t for t in items if t["status"] == status]
    if team_id:
        items = [
            t
            for t in items
            if t["proposing_team_id"] == team_id or t["counterparty_team_id"] == team_id
        ]
    items.sort(key=lambda x: x["created_at"])
    return items


def get_trade(trade_id: str) -> Dict[str, Any]:
    t = store.trade_proposals.get(trade_id)
    if not t:
        raise err_resource_not_found(f"TradeProposal {trade_id} not found.")
    return t


def accept_trade(trade_id: str, acting_user_id: str) -> Dict[str, Any]:
    trade = get_trade(trade_id)
    counterparty = store.teams.get(trade["counterparty_team_id"])
    if not counterparty or counterparty["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()
    if trade["status"] != "OFFERED":
        raise err_invalid_state(f"Trade not OFFERED (current={trade['status']}).")

    # Re-check preconditions
    proposer = store.teams.get(trade["proposing_team_id"])
    proposer_players = set(store.players_on_team(trade["proposing_team_id"]))
    counterparty_players = set(store.players_on_team(trade["counterparty_team_id"]))
    for pid in trade["send_player_ids"]:
        if pid not in proposer_players:
            raise err_player_not_on_roster(f"Player {pid} no longer on proposer.")
    for pid in trade["receive_player_ids"]:
        if pid not in counterparty_players:
            raise err_player_not_on_roster(f"Player {pid} no longer on counterparty.")
    if proposer["faab_balance_dollars"] < trade["send_faab_dollars"]:
        raise err_faab_insufficient()
    if counterparty["faab_balance_dollars"] < trade["receive_faab_dollars"]:
        raise err_faab_insufficient()

    league = store.leagues.get(trade["league_id"])
    now_dt = parse_iso(league["now_ts"])
    deadline = now_dt + timedelta(hours=league["trade_review_hours"])
    trade["review_deadline_ts"] = format_iso(deadline)
    trade["status"] = "ACCEPTED_PENDING_REVIEW"
    trade["veto_count"] = 0
    stamp_update(trade)
    return trade


def reject_trade(trade_id: str, acting_user_id: str) -> Dict[str, Any]:
    trade = get_trade(trade_id)
    counterparty = store.teams.get(trade["counterparty_team_id"])
    if not counterparty or counterparty["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()
    if trade["status"] != "OFFERED":
        raise err_invalid_state(f"Trade not OFFERED (current={trade['status']}).")
    trade["status"] = "REJECTED"
    stamp_update(trade)
    return trade


def cancel_trade(trade_id: str, acting_user_id: str) -> Dict[str, Any]:
    trade = get_trade(trade_id)
    proposer = store.teams.get(trade["proposing_team_id"])
    if not proposer or proposer["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()
    if trade["status"] != "OFFERED":
        raise err_invalid_state(f"Trade not OFFERED (current={trade['status']}).")
    trade["status"] = "CANCELED"
    stamp_update(trade)
    return trade


def cast_vote(trade_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    trade = get_trade(trade_id)
    if trade["status"] != "ACCEPTED_PENDING_REVIEW":
        raise err_trade_not_open_for_voting()

    voting_team_id = body.get("voting_team_id")
    if not voting_team_id:
        raise err_validation("voting_team_id required.")
    vote_choice = body.get("vote")
    if vote_choice not in {"VETO", "APPROVE"}:
        raise err_validation("vote must be VETO or APPROVE.")

    voting_team = store.teams.get(voting_team_id)
    if not voting_team or voting_team["league_id"] != trade["league_id"]:
        raise err_reference_not_found(f"Team {voting_team_id} not in league.")
    if voting_team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    # Voter eligibility: not proposer, not counterparty
    if voting_team_id in (trade["proposing_team_id"], trade["counterparty_team_id"]):
        raise err_not_eligible_voter()
    # No double-voting
    for v in store.votes_for_trade(trade_id):
        if v["voting_team_id"] == voting_team_id:
            raise err_not_eligible_voter()

    league = store.leagues.get(trade["league_id"])

    vote = {
        "id": new_id(),
        "created_at": now_iso(),
        "trade_proposal_id": trade_id,
        "voting_team_id": voting_team_id,
        "vote": vote_choice,
        "cast_at_ts": league["now_ts"],
    }
    store.trade_votes[vote["id"]] = vote

    # Recompute veto_count and check threshold
    veto_count = sum(
        1 for v in store.votes_for_trade(trade_id) if v["vote"] == "VETO"
    )
    trade["veto_count"] = veto_count
    eligible_voters = league["team_count"] - 2
    if eligible_voters <= 0:
        veto_pct = 0
    else:
        veto_pct = (veto_count * 100) // eligible_voters

    now_dt = parse_iso(league["now_ts"])
    deadline = parse_iso(trade["review_deadline_ts"])
    if veto_pct >= league["veto_quorum_pct"] and now_dt < deadline:
        trade["status"] = "VETOED"
    stamp_update(trade)

    return vote


def process_expired_trades(league: Dict[str, Any]) -> None:
    """Process trades whose review_deadline_ts has been crossed."""
    now_dt = parse_iso(league["now_ts"])
    trades = [
        t
        for t in store.trade_proposals.values()
        if t["league_id"] == league["id"]
        and t["status"] == "ACCEPTED_PENDING_REVIEW"
        and t.get("review_deadline_ts")
    ]
    # Sort by deadline ts ascending for deterministic processing
    trades.sort(key=lambda t: t["review_deadline_ts"])
    for trade in trades:
        deadline = parse_iso(trade["review_deadline_ts"])
        if now_dt < deadline:
            continue
        # Compute veto percentage
        eligible_voters = league["team_count"] - 2
        veto_count = sum(
            1 for v in store.votes_for_trade(trade["id"]) if v["vote"] == "VETO"
        )
        veto_pct = (veto_count * 100) // eligible_voters if eligible_voters > 0 else 0
        trade["veto_count"] = veto_count

        if veto_pct >= league["veto_quorum_pct"]:
            # Already would be VETOED — leave status as is or mark VETOED
            trade["status"] = "VETOED"
            stamp_update(trade)
            continue

        # Re-check preconditions
        if not _preconditions_satisfied(trade):
            trade["status"] = "EXPIRED"
            stamp_update(trade)
            continue

        # Execute
        _execute_trade(league, trade)
        trade["status"] = "EXECUTED"
        stamp_update(trade)


def _preconditions_satisfied(trade: Dict[str, Any]) -> bool:
    proposer = store.teams.get(trade["proposing_team_id"])
    counterparty = store.teams.get(trade["counterparty_team_id"])
    if not proposer or not counterparty:
        return False
    proposer_players = set(store.players_on_team(trade["proposing_team_id"]))
    counterparty_players = set(store.players_on_team(trade["counterparty_team_id"]))
    for pid in trade["send_player_ids"]:
        if pid not in proposer_players:
            return False
    for pid in trade["receive_player_ids"]:
        if pid not in counterparty_players:
            return False
    if proposer["faab_balance_dollars"] < trade["send_faab_dollars"]:
        return False
    if counterparty["faab_balance_dollars"] < trade["receive_faab_dollars"]:
        return False
    return True


def _execute_trade(league: Dict[str, Any], trade: Dict[str, Any]) -> None:
    proposer = store.teams[trade["proposing_team_id"]]
    counterparty = store.teams[trade["counterparty_team_id"]]

    # Move send players to counterparty roster
    for pid in trade["send_player_ids"]:
        for s in list(store.roster_slots_for_team(proposer["id"])):
            if s["player_id"] == pid:
                s["team_id"] = counterparty["id"]
                s["slot_type"] = "BENCH"
                s["position_label"] = None
                stamp_update(s)
                break
    # Move receive players to proposer roster
    for pid in trade["receive_player_ids"]:
        for s in list(store.roster_slots_for_team(counterparty["id"])):
            if s["player_id"] == pid:
                s["team_id"] = proposer["id"]
                s["slot_type"] = "BENCH"
                s["position_label"] = None
                stamp_update(s)
                break

    if trade["send_faab_dollars"] > 0:
        proposer["faab_balance_dollars"] -= trade["send_faab_dollars"]
        counterparty["faab_balance_dollars"] += trade["send_faab_dollars"]
        stamp_update(proposer)
        stamp_update(counterparty)
    if trade["receive_faab_dollars"] > 0:
        counterparty["faab_balance_dollars"] -= trade["receive_faab_dollars"]
        proposer["faab_balance_dollars"] += trade["receive_faab_dollars"]
        stamp_update(proposer)
        stamp_update(counterparty)

    # Cancel pending waiver claims for traded players
    traded = set(trade["send_player_ids"]) | set(trade["receive_player_ids"])
    for w in store.waiver_claims.values():
        if w["league_id"] != league["id"]:
            continue
        if w["status"] != "PENDING":
            continue
        if w["add_player_id"] in traded:
            w["status"] = "CANCELED"
            stamp_update(w)
