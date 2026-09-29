"""Request-body builders.

Each builder produces the minimal valid body for one write, and every builder
accepts keyword overrides so a test can bend exactly the field it is probing
without restating the rest. Nothing here computes a business outcome.
"""

import itertools
import string
from typing import Any, Dict, Optional

from .constants import (
    PLAYER_POSITIONS,
    STANDARD_SALARY_CAP_LIMIT_CENTS,
)
from .types import Payload

_LETTERS = string.ascii_uppercase
_market_codes = itertools.product(_LETTERS, repeat=3)
_counter = itertools.count(1)


def next_market_code() -> str:
    """A fresh three-letter market code, unique within a test's database."""
    return "".join(next(_market_codes))


def next_sequence() -> int:
    """A monotonically increasing integer for building distinct names."""
    return next(_counter)


# ---------------------------------------------------------------------------
# Clubs and players
# ---------------------------------------------------------------------------
def team_payload(
    name: Optional[str] = None,
    market_code: Optional[str] = None,
    waiver_priority_rank: int = 1,
    salary_cap_limit_cents: int = STANDARD_SALARY_CAP_LIMIT_CENTS,
    **overrides: Any,
) -> Payload:
    """A club registration body carrying only the four required inputs."""
    sequence = next_sequence()
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"Club {sequence}",
        "market_code": market_code if market_code is not None else next_market_code(),
        "salary_cap_limit_cents": salary_cap_limit_cents,
        "waiver_priority_rank": waiver_priority_rank,
    }
    payload.update(overrides)
    return payload


def player_payload(
    full_name: Optional[str] = None,
    position: str = PLAYER_POSITIONS[0],
    **overrides: Any,
) -> Payload:
    """A player registration body; day buckets default to the server's zeroes."""
    payload: Dict[str, Any] = {
        "full_name": full_name if full_name is not None else f"Player {next_sequence()}",
        "position": position,
    }
    payload.update(overrides)
    return payload


def team_limits_payload(**overrides: Any) -> Payload:
    """A limits adjustment body; every field of the body is optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------
def signing_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    years: int = 1,
    base_salary_cents: int = 10_000_000,
    signing_bonus_cents: int = 0,
    **overrides: Any,
) -> Payload:
    """A signing filing body with its contract terms."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "SIGNING",
        "expected_team_version": expected_team_version,
        "years": years,
        "base_salary_cents": base_salary_cents,
        "signing_bonus_cents": signing_bonus_cents,
    }
    payload.update(overrides)
    return payload


def release_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    **overrides: Any,
) -> Payload:
    """A release filing body."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "RELEASE",
        "expected_team_version": expected_team_version,
    }
    payload.update(overrides)
    return payload


def designation_change_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    target_designation: str,
    **overrides: Any,
) -> Payload:
    """A designation-change filing body."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "DESIGNATION_CHANGE",
        "expected_team_version": expected_team_version,
        "target_designation": target_designation,
    }
    payload.update(overrides)
    return payload


def practice_squad_elevation_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    target_designation: str = "ACTIVE",
    **overrides: Any,
) -> Payload:
    """A practice-squad elevation filing body."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "PRACTICE_SQUAD_ELEVATION",
        "expected_team_version": expected_team_version,
        "target_designation": target_designation,
    }
    payload.update(overrides)
    return payload


def ir_placement_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    injury_designation_id: str,
    **overrides: Any,
) -> Payload:
    """An injured-reserve placement filing body."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "IR_PLACEMENT",
        "expected_team_version": expected_team_version,
        "injury_designation_id": injury_designation_id,
    }
    payload.update(overrides)
    return payload


def ir_activation_payload(
    team_id: str,
    player_id: str,
    expected_team_version: int,
    injury_designation_id: str,
    **overrides: Any,
) -> Payload:
    """An injured-reserve activation filing body."""
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": "IR_ACTIVATION",
        "expected_team_version": expected_team_version,
        "injury_designation_id": injury_designation_id,
    }
    payload.update(overrides)
    return payload


def approve_payload(**overrides: Any) -> Payload:
    """A decision body approving a filing."""
    payload: Dict[str, Any] = {"decision": "APPROVE"}
    payload.update(overrides)
    return payload


def reject_payload(rejection_reason: str = "Cap room insufficient",
                   **overrides: Any) -> Payload:
    """A decision body rejecting a filing, with the mandatory reason."""
    payload: Dict[str, Any] = {
        "decision": "REJECT",
        "rejection_reason": rejection_reason,
    }
    payload.update(overrides)
    return payload


def revise_payload(**overrides: Any) -> Payload:
    """A revision body; every field of the body is optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Waiver wire
# ---------------------------------------------------------------------------
def waiver_request_payload(player_id: str, from_team_id: str,
                           transaction_id: str, **overrides: Any) -> Payload:
    """A waiver placement body citing the authorising release filing."""
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "from_team_id": from_team_id,
        "transaction_id": transaction_id,
    }
    payload.update(overrides)
    return payload


def waiver_claim_payload(claiming_team_id: str, expected_team_version: int,
                         **overrides: Any) -> Payload:
    """A claim body from one club on one wire."""
    payload: Dict[str, Any] = {
        "claiming_team_id": claiming_team_id,
        "expected_team_version": expected_team_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------
def trade_payload(initiating_team_id: str, counterparty_team_id: str,
                  conditional_clause_type: str = "NONE",
                  **overrides: Any) -> Payload:
    """A trade construction body between two clubs.

    PRD 3.7: "Either non-`NONE` clause requires a non-blank `condition_note`
    describing the term." A clause other than `NONE` therefore carries a note
    unless the caller supplies its own wording.
    """
    payload: Dict[str, Any] = {
        "initiating_team_id": initiating_team_id,
        "counterparty_team_id": counterparty_team_id,
        "conditional_clause_type": conditional_clause_type,
    }
    if conditional_clause_type != "NONE":
        payload["condition_note"] = (
            "Deal contingent on the term the clause records."
        )
    payload.update(overrides)
    return payload


def contract_asset_payload(contract_id: str, direction: str,
                           expected_trade_version: int,
                           **overrides: Any) -> Payload:
    """A trade asset body offering one contract."""
    payload: Dict[str, Any] = {
        "asset_kind": "CONTRACT",
        "direction": direction,
        "expected_trade_version": expected_trade_version,
        "contract_id": contract_id,
    }
    payload.update(overrides)
    return payload


def draft_pick_asset_payload(direction: str, expected_trade_version: int,
                             draft_pick_year: int = 2027,
                             draft_pick_round: int = 1,
                             **overrides: Any) -> Payload:
    """A trade asset body offering one future draft pick."""
    payload: Dict[str, Any] = {
        "asset_kind": "DRAFT_PICK",
        "direction": direction,
        "expected_trade_version": expected_trade_version,
        "draft_pick_year": draft_pick_year,
        "draft_pick_round": draft_pick_round,
    }
    payload.update(overrides)
    return payload


def cash_asset_payload(direction: str, expected_trade_version: int,
                       cash_amount_cents: int = 1_000_000,
                       **overrides: Any) -> Payload:
    """A trade asset body offering cash consideration."""
    payload: Dict[str, Any] = {
        "asset_kind": "CASH_CONSIDERATION",
        "direction": direction,
        "expected_trade_version": expected_trade_version,
        "cash_amount_cents": cash_amount_cents,
    }
    payload.update(overrides)
    return payload


def counter_payload(expected_trade_version: int, **overrides: Any) -> Payload:
    """A counter body carrying the trade's expected version."""
    payload: Dict[str, Any] = {"expected_trade_version": expected_trade_version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tenders and contract options
# ---------------------------------------------------------------------------
def tender_payload(player_id: str, team_id: str, offer_type: str,
                   tender_level: str, prior_base_salary_cents: int,
                   **overrides: Any) -> Payload:
    """A tender issuance body."""
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "team_id": team_id,
        "offer_type": offer_type,
        "tender_level": tender_level,
        "prior_base_salary_cents": prior_base_salary_cents,
    }
    payload.update(overrides)
    return payload


def tender_response_payload(response: str, **overrides: Any) -> Payload:
    """A tender response body carrying the agent's answer."""
    payload: Dict[str, Any] = {"response": response}
    payload.update(overrides)
    return payload


def option_decision_payload(decision: str, expected_contract_version: int,
                            **overrides: Any) -> Payload:
    """An option decision body carrying the contract's expected version."""
    payload: Dict[str, Any] = {
        "decision": decision,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Medical dimension
# ---------------------------------------------------------------------------
def injury_designation_payload(player_id: str, team_id: str,
                               designation_type: str,
                               **overrides: Any) -> Payload:
    """An injury designation body."""
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "team_id": team_id,
        "designation_type": designation_type,
    }
    payload.update(overrides)
    return payload


def paperwork_payload(paperwork_reference: str = "LEAGUE-IR-0001",
                      **overrides: Any) -> Payload:
    """A league-paperwork body carrying the mandatory reference."""
    payload: Dict[str, Any] = {"paperwork_reference": paperwork_reference}
    payload.update(overrides)
    return payload


def physical_exam_payload(player_id: str, team_id: str, exam_type: str,
                          window_start_at: str, window_end_at: str,
                          **overrides: Any) -> Payload:
    """A physical-exam scheduling body with its half-open window."""
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "team_id": team_id,
        "exam_type": exam_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def exam_result_payload(result: str, performed_at: str,
                        **overrides: Any) -> Payload:
    """An exam result body carrying the instant the exam was performed."""
    payload: Dict[str, Any] = {"result": result, "performed_at": performed_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compliance sweep
# ---------------------------------------------------------------------------
def compliance_check_payload(team_id: str, **overrides: Any) -> Payload:
    """A sweep body naming the club to evaluate."""
    payload: Dict[str, Any] = {"team_id": team_id}
    payload.update(overrides)
    return payload
