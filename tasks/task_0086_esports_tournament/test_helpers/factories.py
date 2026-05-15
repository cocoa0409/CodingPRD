"""Payload factories — one per endpoint that takes a request body.

Each factory emits only source=input fields and accepts **overrides so
tests can vary specific values without re-typing the entire payload.
"""
from __future__ import annotations
import datetime as dt
import uuid
from typing import Any, Dict, List, Optional

from .constants import MVP_BPS, TOTAL_BPS, TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_utc(days_offset: int = 0, hours_offset: int = 0,
            minutes_offset: int = 0, seconds_offset: int = 0,
            base: Optional[str] = None) -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision.

    PRD §2.4 specifies ISO 8601 UTC strings with three fractional digits.
    When `base` is None, anchors at a canonical test epoch
    (2026-01-01T00:00:00.000Z) so tests are deterministic across runs.
    """
    if base is None:
        anchor = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    else:
        anchor = dt.datetime.fromisoformat(base.replace("Z", "+00:00"))
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=dt.timezone.utc)
    target = anchor + dt.timedelta(
        days=days_offset, hours=hours_offset,
        minutes=minutes_offset, seconds=seconds_offset,
    )
    # Always emit 3 fractional digits.
    return target.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{target.microsecond // 1000:03d}Z"
    )


# ---------------------------------------------------------------------------
# Tournament (PRD §3.1)
# ---------------------------------------------------------------------------
def default_prize_tier_table() -> List[Dict[str, int]]:
    """PRD §2.9 + §3.1: 'sum of every entry's percentage_bps plus the
    MVP allocation of 500 basis points (5% of the pool) must equal
    exactly 10000 basis points'. 5500+3000+1000+500 = 10000."""
    return [
        {"placement": 1, "percentage_bps": 5500},
        {"placement": 2, "percentage_bps": 3000},
        {"placement": 3, "percentage_bps": 1000},
    ]


def default_ban_pick_sequence() -> List[Dict[str, Any]]:
    """A short 6-step draft so tests can exercise draft flow without
    huge fixtures. PRD §3.1: 'ordered list of {step, team, action}
    blocks defining the draft order'."""
    return [
        {"step": 1, "team": "A", "action": "BAN"},
        {"step": 2, "team": "B", "action": "BAN"},
        {"step": 3, "team": "A", "action": "PICK"},
        {"step": 4, "team": "B", "action": "PICK"},
        {"step": 5, "team": "A", "action": "PICK"},
        {"step": 6, "team": "B", "action": "PICK"},
    ]


def default_map_pool() -> List[str]:
    return ["map_alpha", "map_beta", "map_gamma", "map_delta"]


def default_character_pool() -> List[str]:
    return [f"char_{i}" for i in range(10)]


def create_tournament_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 create-tournament payload. Defaults emit a valid
    prize_tier_table whose percentage_bps + MVP_BPS == 10000 and
    deadlines safely in the future relative to the canonical test
    epoch."""
    suffix = uuid.uuid4().hex[:8]
    defaults: Dict[str, Any] = {
        "name": f"{TEST_DEFAULTS['TOURNAMENT_NAME']}-{suffix}",
        "format": TEST_DEFAULTS["TOURNAMENT_FORMAT"],
        "region": TEST_DEFAULTS["TOURNAMENT_REGION"],
        "min_age": TEST_DEFAULTS["MIN_AGE"],
        "min_team_ranking_points": TEST_DEFAULTS["MIN_TEAM_RANKING_POINTS"],
        "entry_fee_cents": TEST_DEFAULTS["ENTRY_FEE_CENTS"],
        "entry_fee_currency": TEST_DEFAULTS["ENTRY_FEE_CURRENCY"],
        "roster_lock_deadline": iso_utc(
            days_offset=TEST_DEFAULTS["ROSTER_LOCK_OFFSET_DAYS"],
        ),
        "registration_deadline": iso_utc(
            days_offset=TEST_DEFAULTS["REGISTRATION_OFFSET_DAYS"],
        ),
        "base_prize_pool_cents": TEST_DEFAULTS["BASE_PRIZE_POOL_CENTS"],
        "prize_tier_table": default_prize_tier_table(),
        "ban_pick_sequence": default_ban_pick_sequence(),
        "map_pool": default_map_pool(),
        "character_pool": default_character_pool(),
        "seeding_rule": TEST_DEFAULTS["SEEDING_RULE"],
        "max_teams": TEST_DEFAULTS["MAX_TEAMS"],
        "required_referee_level": TEST_DEFAULTS["REQUIRED_REFEREE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def cancel_tournament_payload(reason: str = "Operations halted") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# TeamRegistration (PRD §3.2)
# ---------------------------------------------------------------------------
def create_team_registration_payload(manager_id: str,
                                     **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'submitting team_name, manager_id, region, optional
    logo_url, and sponsors.' manager_id is required and MUST equal the
    caller's X-User-ID (ownership rule)."""
    suffix = uuid.uuid4().hex[:8]
    defaults: Dict[str, Any] = {
        "team_name": f"Team-{suffix}",
        "manager_id": manager_id,
        "region": "NA",
        "logo_url": "https://example.test/logo.png",
        "sponsors": [{"name": "ACME", "tier": "GOLD"}],
    }
    defaults.update(overrides)
    return defaults


def pay_entry_fee_payload(amount_cents: int,
                          currency: str = "USD") -> Dict[str, Any]:
    """PRD §3.2: 'The payment endpoint accepts amount_cents and currency
    as the submitted-payment description.'"""
    return {"amount_cents": amount_cents, "currency": currency}


# ---------------------------------------------------------------------------
# PlayerContract (PRD §3.3)
# ---------------------------------------------------------------------------
def default_required_signatories() -> List[Dict[str, str]]:
    """PRD §3.3: 'required_signatories is an ordered list of {party}
    entries whose party value is PLAYER, TEAM_MANAGER, or LEAGUE_ADMIN;
    it pins the order in which the contract must be signed.'"""
    return [
        {"party": "PLAYER"},
        {"party": "TEAM_MANAGER"},
        {"party": "LEAGUE_ADMIN"},
    ]


def create_player_contract_payload(team_id: str,
                                   player_id: Optional[str] = None,
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 create-contract payload."""
    suffix = uuid.uuid4().hex[:8]
    pid = player_id or f"player-{suffix}"
    defaults: Dict[str, Any] = {
        "player_id": pid,
        "player_legal_name": f"Player {suffix}",
        "player_age": TEST_DEFAULTS["PLAYER_AGE"],
        "team_id": team_id,
        "contract_type": "EXCLUSIVE",
        "roster_slot": "MAIN",
        "term_start": iso_utc(),
        "term_end": iso_utc(days_offset=365),
        "monthly_compensation_cents": 500_000,
        "compensation_currency": "USD",
        "dispute_resolution_clause": "ARBITRATION",
        "ranking_points": TEST_DEFAULTS["PLAYER_RANKING"],
        "required_signatories": default_required_signatories(),
    }
    defaults.update(overrides)
    return defaults


def file_identity_verification_payload(jurisdiction: str = "US",
                                       status: str = "VERIFIED",
                                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'supplies the document_hash, the jurisdiction ..., the
    verification status (either VERIFIED or REJECTED), and a
    rejection_reason (required when status is REJECTED).'"""
    defaults: Dict[str, Any] = {
        "document_hash": f"sha256:{uuid.uuid4().hex}",
        "jurisdiction": jurisdiction,
        "status": status,
    }
    if status == "REJECTED" and "rejection_reason" not in overrides:
        defaults["rejection_reason"] = "Document illegible"
    defaults.update(overrides)
    return defaults


def file_amendment_payload(proposed_changes: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    return {"proposed_changes": proposed_changes or {
        "monthly_compensation_cents": 600_000,
    }}


def terminate_contract_payload(reason: str = "Dispute resolved"
                               ) -> Dict[str, Any]:
    """PRD §3.3: 'supplying a reason; the precondition is that the
    supplied reason is non-empty and the dispute_resolution_clause has
    been invoked.'"""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Match + Draft (PRD §3.4)
# ---------------------------------------------------------------------------
def update_match_payload(scheduled_start: str,
                         scheduled_end: str,
                         version: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if version is not None:
        payload["version"] = version
    return payload


def assign_referee_payload(referee_user_id: str) -> Dict[str, Any]:
    """PRD §3.4: 'supplying referee_user_id'."""
    return {"referee_user_id": referee_user_id}


def draft_event_payload(step_index: int,
                        action: str = "BAN",
                        side: str = "A",
                        target_type: str = "MAP",
                        target_name: str = "map_alpha",
                        anomaly_type: Optional[str] = None,
                        ) -> Dict[str, Any]:
    """PRD §3.4: 'caller supplies step_index, action (BAN or PICK),
    side (A or B), target_type (MAP or CHARACTER), target_name, and an
    optional anomaly_type.'"""
    payload: Dict[str, Any] = {
        "step_index": step_index,
        "action": action,
        "side": side,
        "target_type": target_type,
        "target_name": target_name,
    }
    if anomaly_type is not None:
        payload["anomaly_type"] = anomaly_type
    return payload


def report_result_payload(winner_team_id: str) -> Dict[str, Any]:
    return {"winner_team_id": winner_team_id}


def forfeit_match_payload(winner_team_id: str,
                          forfeit_reason: str = "Forfeit") -> Dict[str, Any]:
    return {
        "winner_team_id": winner_team_id,
        "forfeit_reason": forfeit_reason,
    }


# ---------------------------------------------------------------------------
# MatchIncident (PRD §3.5)
# ---------------------------------------------------------------------------
def create_incident_payload(match_id: str,
                            subject_type: str,
                            subject_id: str,
                            referee_id: str,
                            classification: str = "RULE_VIOLATION",
                            evidence: Optional[List[Dict[str, str]]] = None,
                            ) -> Dict[str, Any]:
    """PRD §3.5: 'supplying match_id, subject_type, subject_id,
    classification, the evidence array ..., and referee_id, which must
    equal X-User-ID.'"""
    return {
        "match_id": match_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "classification": classification,
        "evidence": evidence or [
            {"kind": "REPLAY", "uri": "https://e.test/r.mp4",
             "hash": "sha256:" + uuid.uuid4().hex},
        ],
        "referee_id": referee_id,
    }


def rule_incident_payload(ruling: str,
                          penalty_type: Optional[str] = None,
                          fine_amount_cents: Optional[int] = None,
                          ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ruling": ruling}
    if penalty_type is not None:
        payload["penalty_type"] = penalty_type
    if fine_amount_cents is not None:
        payload["fine_amount_cents"] = fine_amount_cents
    return payload


def appeal_incident_payload(grounds: str = "Procedural error"
                            ) -> Dict[str, Any]:
    return {"grounds": grounds}


def appeal_decide_payload(decision: str = "AFFIRM",
                          new_ruling: Optional[str] = None,
                          new_penalty_type: Optional[str] = None,
                          ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if new_ruling is not None:
        payload["new_ruling"] = new_ruling
    if new_penalty_type is not None:
        payload["new_penalty_type"] = new_penalty_type
    return payload


# ---------------------------------------------------------------------------
# Referee (PRD §3.4)
# ---------------------------------------------------------------------------
def create_referee_payload(user_id: Optional[str] = None,
                           certification_level: str = "L2",
                           certification_expiry_days: int = 365,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'with user_id, full_name, certification_level (one of
    L1, L2, or L3), and certification_expiry.'"""
    uid = user_id or f"ref-{uuid.uuid4().hex[:8]}"
    defaults: Dict[str, Any] = {
        "user_id": uid,
        "full_name": f"Referee {uid[-4:]}",
        "certification_level": certification_level,
        "certification_expiry": iso_utc(days_offset=certification_expiry_days),
    }
    defaults.update(overrides)
    return defaults


def update_referee_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ---------------------------------------------------------------------------
# CrowdfundContribution (PRD §3.7)
# ---------------------------------------------------------------------------
def create_crowdfund_payload(amount_cents: int,
                             status: str = "COLLECTED",
                             contributor_user_id: Optional[str] = None,
                             ) -> Dict[str, Any]:
    return {
        "contributor_user_id": contributor_user_id or f"backer-{uuid.uuid4().hex[:6]}",
        "amount_cents": amount_cents,
        "status": status,
    }


# ---------------------------------------------------------------------------
# TransferWindow + TransferOffer (PRD §3.7)
# ---------------------------------------------------------------------------
def create_transfer_window_payload(opens_at: Optional[str] = None,
                                   closes_at: Optional[str] = None,
                                   cooling_off_days: int = 30,
                                   name: Optional[str] = None,
                                   ) -> Dict[str, Any]:
    return {
        "name": name or f"Window-{uuid.uuid4().hex[:6]}",
        "opens_at": opens_at or iso_utc(),
        "closes_at": closes_at or iso_utc(days_offset=30),
        "cooling_off_days": cooling_off_days,
    }


def create_transfer_offer_payload(player_id: str,
                                  from_team_id: str,
                                  to_team_id: str,
                                  window_id: str,
                                  transfer_fee_cents: int = 50_000,
                                  transfer_fee_currency: str = "USD",
                                  ) -> Dict[str, Any]:
    return {
        "player_id": player_id,
        "from_team_id": from_team_id,
        "to_team_id": to_team_id,
        "window_id": window_id,
        "transfer_fee_cents": transfer_fee_cents,
        "transfer_fee_currency": transfer_fee_currency,
    }


def counter_offer_payload(transfer_fee_cents: int,
                          transfer_fee_currency: str = "USD"
                          ) -> Dict[str, Any]:
    return {
        "transfer_fee_cents": transfer_fee_cents,
        "transfer_fee_currency": transfer_fee_currency,
    }


def reject_offer_payload(reason: str = "Declined") -> Dict[str, Any]:
    return {"reason": reason}


def league_approve_payload(decision: str = "APPROVE") -> Dict[str, Any]:
    return {"decision": decision}


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.7)
# ---------------------------------------------------------------------------
def clock_advance_payload(to: str) -> Dict[str, Any]:
    return {"to": to}


__all__ = [
    "iso_utc",
    "default_prize_tier_table",
    "default_ban_pick_sequence",
    "default_map_pool",
    "default_character_pool",
    "default_required_signatories",
    "create_tournament_payload",
    "cancel_tournament_payload",
    "create_team_registration_payload",
    "pay_entry_fee_payload",
    "create_player_contract_payload",
    "file_identity_verification_payload",
    "file_amendment_payload",
    "terminate_contract_payload",
    "update_match_payload",
    "assign_referee_payload",
    "draft_event_payload",
    "report_result_payload",
    "forfeit_match_payload",
    "create_incident_payload",
    "rule_incident_payload",
    "appeal_incident_payload",
    "appeal_decide_payload",
    "create_referee_payload",
    "update_referee_payload",
    "create_crowdfund_payload",
    "create_transfer_window_payload",
    "create_transfer_offer_payload",
    "counter_offer_payload",
    "reject_offer_payload",
    "league_approve_payload",
    "clock_advance_payload",
]
