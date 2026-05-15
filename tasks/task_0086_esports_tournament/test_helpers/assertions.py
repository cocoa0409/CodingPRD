"""Entity assertions and domain invariant checkers.

Each asserter accepts the dict shape returned by the corresponding
endpoint and verifies fields the PRD mandates. Per PRD §2.4 only
mutable entities carry updated_at + version; append-only entities
expose ONLY id and created_at.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4 mutable-entity common fields: id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    v = data.get("version")
    assert isinstance(v, int) and v >= 1, (
        f"{entity_name}.version must be a positive int, got {v!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Four entities are deliberately append-only or singleton
    in nature and carry only id and created_at — both updated_at and
    version are absent on these rows.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Tournament (PRD §3.1, §2.4)
# ---------------------------------------------------------------------------
TOURNAMENT_FORMATS = {"SWISS", "DOUBLE_ELIMINATION", "ROUND_ROBIN",
                      "GROUP_PLAYOFFS"}
TOURNAMENT_REGIONS = {"NA", "EU", "APAC", "SA", "GLOBAL"}
TOURNAMENT_STATES = {"DRAFT", "REGISTRATION_OPEN", "ROSTER_LOCKED",
                     "BRACKET_PUBLISHED", "IN_PROGRESS", "COMPLETED",
                     "PRIZES_DISTRIBUTED", "CANCELLED"}
CURRENCIES = {"USD", "EUR", "KRW", "CNY"}
SEEDING_RULES = {"RANKING", "RANDOM", "REGIONAL_BALANCE"}


def assert_tournament(data: dict) -> None:
    _assert_common_mutable(data, "Tournament")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("format") in TOURNAMENT_FORMATS, (
        f"Tournament.format must be in {TOURNAMENT_FORMATS}, got "
        f"{data.get('format')!r}"
    )
    assert data.get("region") in TOURNAMENT_REGIONS
    assert data.get("status") in TOURNAMENT_STATES
    assert isinstance(data.get("min_age"), int)
    assert isinstance(data.get("min_team_ranking_points"), int)
    assert isinstance(data.get("entry_fee_cents"), int)
    assert data.get("entry_fee_currency") in CURRENCIES
    assert is_iso8601_timestamp(data.get("roster_lock_deadline", ""))
    assert is_iso8601_timestamp(data.get("registration_deadline", ""))
    assert isinstance(data.get("base_prize_pool_cents"), int)
    # Computed fields (PRD §3.1).
    assert isinstance(data.get("crowdfunded_prize_pool_cents"), int), (
        "Tournament.crowdfunded_prize_pool_cents must be present (computed)"
    )
    assert isinstance(data.get("total_prize_pool_cents"), int), (
        "Tournament.total_prize_pool_cents must be present (computed)"
    )
    assert data["total_prize_pool_cents"] == (
        data["base_prize_pool_cents"] + data["crowdfunded_prize_pool_cents"]
    ), (
        "Tournament.total_prize_pool_cents must equal base_prize_pool_cents "
        "+ crowdfunded_prize_pool_cents (PRD §3.1)"
    )
    assert isinstance(data.get("prize_tier_table"), list)
    assert isinstance(data.get("ban_pick_sequence"), list)
    assert isinstance(data.get("map_pool"), list)
    assert isinstance(data.get("character_pool"), list)
    assert data.get("seeding_rule") in SEEDING_RULES


def assert_prize_tier_sum_invariant(table: Iterable[Dict[str, int]],
                                    mvp_bps: int = 500) -> None:
    """PRD §3.1: 'sum of every entry's percentage_bps plus the MVP
    allocation of 500 basis points (5% of the pool) must equal exactly
    10000 basis points.'"""
    total = sum(t.get("percentage_bps", 0) for t in table) + mvp_bps
    assert total == 10000, (
        f"Prize tier sum + MVP_BPS must equal 10000, got {total}"
    )


# ---------------------------------------------------------------------------
# TeamRegistration (PRD §3.2)
# ---------------------------------------------------------------------------
TEAM_REG_STATES = {"DRAFT", "FEE_PENDING", "REGISTERED",
                   "DISQUALIFIED", "WITHDRAWN"}


def assert_team_registration(data: dict) -> None:
    _assert_common_mutable(data, "TeamRegistration")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data.get("team_name"), str) and len(data["team_name"]) > 0
    assert isinstance(data.get("manager_id"), str) and len(data["manager_id"]) > 0
    assert data.get("region") in {"NA", "EU", "APAC", "SA"}
    assert data.get("status") in TEAM_REG_STATES
    assert isinstance(data.get("entry_fee_paid_cents"), int)
    assert data["entry_fee_paid_cents"] >= 0
    assert isinstance(data.get("roster_locked"), bool)
    # sponsors should be a list (may be empty).
    sp = data.get("sponsors")
    assert sp is None or isinstance(sp, list)


# ---------------------------------------------------------------------------
# PlayerContract (PRD §3.3)
# ---------------------------------------------------------------------------
CONTRACT_TYPES = {"EXCLUSIVE", "LOAN", "FREE_AGENT"}
ROSTER_SLOTS = {"MAIN", "SUBSTITUTE"}
DISPUTE_CLAUSES = {"ARBITRATION", "LITIGATION", "MEDIATION"}
SIGNATORY_PARTIES = {"PLAYER", "TEAM_MANAGER", "LEAGUE_ADMIN"}
CONTRACT_STATES = {"DRAFT", "PENDING_SIGNATURES", "ACTIVE",
                   "AMENDMENT_PENDING", "TERMINATED", "EXPIRED"}


def assert_player_contract(data: dict) -> None:
    _assert_common_mutable(data, "PlayerContract")
    assert isinstance(data.get("player_id"), str) and len(data["player_id"]) > 0
    assert isinstance(data.get("player_legal_name"), str)
    assert isinstance(data.get("player_age"), int) and data["player_age"] >= 0
    assert isinstance(data.get("identity_verified"), bool)
    assert is_valid_uuid(data.get("team_id", ""))
    assert data.get("contract_type") in CONTRACT_TYPES
    assert data.get("roster_slot") in ROSTER_SLOTS
    assert is_iso8601_timestamp(data.get("term_start", ""))
    assert is_iso8601_timestamp(data.get("term_end", ""))
    assert data.get("compensation_currency") in CURRENCIES
    assert data.get("dispute_resolution_clause") in DISPUTE_CLAUSES
    assert data.get("status") in CONTRACT_STATES
    sigs = data.get("signatures")
    assert isinstance(sigs, list)
    req = data.get("required_signatories")
    assert isinstance(req, list)
    for entry in req:
        assert entry.get("party") in SIGNATORY_PARTIES


# ---------------------------------------------------------------------------
# IdentityVerification (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_identity_verification(data: dict) -> None:
    _assert_common_appendonly(data, "IdentityVerification")
    assert "updated_at" not in data, (
        "IdentityVerification is append-only and must not expose updated_at "
        "(PRD §2.4)"
    )
    assert "version" not in data, (
        "IdentityVerification is append-only and must not expose version "
        "(PRD §2.4)"
    )
    assert isinstance(data.get("player_id"), str)
    assert isinstance(data.get("contract_id"), str)
    assert data.get("status") in {"VERIFIED", "REJECTED"}
    assert isinstance(data.get("jurisdiction"), str) and len(data["jurisdiction"]) == 2


# ---------------------------------------------------------------------------
# Match (PRD §3.4)
# ---------------------------------------------------------------------------
MATCH_STATES = {"SCHEDULED", "DRAFT_IN_PROGRESS", "LIVE", "COMPLETED",
                "FORFEITED", "DISQUALIFIED"}


def assert_match(data: dict) -> None:
    _assert_common_mutable(data, "Match")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data.get("round_number"), int)
    assert isinstance(data.get("bracket_position"), int)
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("status") in MATCH_STATES
    assert isinstance(data.get("is_bye"), bool)


# ---------------------------------------------------------------------------
# DraftEvent (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_draft_event(data: dict) -> None:
    _assert_common_appendonly(data, "DraftEvent")
    assert "updated_at" not in data, (
        "DraftEvent is append-only and must not expose updated_at "
        "(PRD §2.4)"
    )
    assert "version" not in data, (
        "DraftEvent is append-only and must not expose version (PRD §2.4)"
    )
    assert isinstance(data.get("match_id"), str)
    assert isinstance(data.get("step_index"), int)
    assert data.get("action") in {"BAN", "PICK"}
    assert data.get("side") in {"A", "B"}
    assert data.get("target_type") in {"MAP", "CHARACTER"}
    assert isinstance(data.get("target_name"), str)
    assert isinstance(data.get("recorded_by_user_id"), str)


# ---------------------------------------------------------------------------
# MatchIncident (PRD §3.5)
# ---------------------------------------------------------------------------
INCIDENT_SUBJECTS = {"PLAYER", "TEAM", "MATCH"}
INCIDENT_CLASSIFICATIONS = {"LATENCY", "CHEATING_SUSPICION",
                            "UNSPORTSMANLIKE_CONDUCT", "RULE_VIOLATION"}
INCIDENT_RULINGS = {"PENDING", "UPHELD", "DISMISSED", "OVERTURNED"}
INCIDENT_PENALTIES = {"NONE", "WARNING", "FORFEIT", "DISQUALIFICATION", "FINE"}
INCIDENT_STATES = {"FILED", "UNDER_REVIEW", "RULED", "APPEALED", "CLOSED"}


def assert_match_incident(data: dict) -> None:
    _assert_common_mutable(data, "MatchIncident")
    assert isinstance(data.get("match_id"), str)
    assert data.get("subject_type") in INCIDENT_SUBJECTS
    assert isinstance(data.get("subject_id"), str)
    assert data.get("classification") in INCIDENT_CLASSIFICATIONS
    assert isinstance(data.get("evidence"), list)
    assert isinstance(data.get("referee_id"), str)
    assert data.get("ruling") in INCIDENT_RULINGS
    assert data.get("penalty_type") in INCIDENT_PENALTIES
    assert isinstance(data.get("appeal_count"), int)
    assert data["appeal_count"] >= 0
    assert data.get("status") in INCIDENT_STATES


# ---------------------------------------------------------------------------
# Referee (PRD §3.4)
# ---------------------------------------------------------------------------
REFEREE_LEVELS = {"L1", "L2", "L3"}
REFEREE_STATES = {"ACTIVE", "SUSPENDED"}


def assert_referee(data: dict) -> None:
    _assert_common_mutable(data, "Referee")
    assert isinstance(data.get("user_id"), str) and len(data["user_id"]) > 0
    assert isinstance(data.get("full_name"), str)
    assert data.get("certification_level") in REFEREE_LEVELS
    assert is_iso8601_timestamp(data.get("certification_expiry", ""))
    assert data.get("status") in REFEREE_STATES


# ---------------------------------------------------------------------------
# CrowdfundContribution (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_crowdfund_contribution(data: dict) -> None:
    _assert_common_appendonly(data, "CrowdfundContribution")
    assert "updated_at" not in data, (
        "CrowdfundContribution is append-only and must not expose "
        "updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "CrowdfundContribution is append-only and must not expose version "
        "(PRD §2.4)"
    )
    assert isinstance(data.get("tournament_id"), str)
    assert isinstance(data.get("contributor_user_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data.get("status") in {"PLEDGED", "COLLECTED", "REFUNDED"}


# ---------------------------------------------------------------------------
# PrizePayout (PRD §3.6)
# ---------------------------------------------------------------------------
PRIZE_AWARD_KINDS = {"PLACEMENT", "MVP", "SPECIAL_AWARD"}
PRIZE_PAYOUT_STATES = {"PROVISIONAL", "FINALIZED", "PAID", "CLAWED_BACK"}


def assert_prize_payout(data: dict) -> None:
    _assert_common_mutable(data, "PrizePayout")
    assert isinstance(data.get("tournament_id"), str)
    assert data.get("award_kind") in PRIZE_AWARD_KINDS
    assert isinstance(data.get("gross_amount_cents"), int)
    assert data["gross_amount_cents"] >= 0
    assert isinstance(data.get("tax_withheld_cents"), int)
    assert data["tax_withheld_cents"] >= 0
    assert isinstance(data.get("net_amount_cents"), int)
    assert data.get("payout_currency") in CURRENCIES
    assert data.get("status") in PRIZE_PAYOUT_STATES


# ---------------------------------------------------------------------------
# TransferOffer / TransferWindow (PRD §3.7)
# ---------------------------------------------------------------------------
TRANSFER_STATES = {"PROPOSED", "COUNTERED", "ACCEPTED_BY_FROM",
                   "ACCEPTED_BY_BOTH", "LEAGUE_APPROVED", "REJECTED",
                   "EXPIRED"}


def assert_transfer_offer(data: dict) -> None:
    _assert_common_mutable(data, "TransferOffer")
    assert isinstance(data.get("player_id"), str)
    assert isinstance(data.get("from_team_id"), str)
    assert isinstance(data.get("to_team_id"), str)
    assert isinstance(data.get("window_id"), str)
    assert isinstance(data.get("transfer_fee_cents"), int)
    assert data.get("transfer_fee_currency") in CURRENCIES
    assert data.get("status") in TRANSFER_STATES
    assert isinstance(data.get("history"), list)


def assert_transfer_window(data: dict) -> None:
    _assert_common_mutable(data, "TransferWindow")
    assert isinstance(data.get("name"), str)
    assert is_iso8601_timestamp(data.get("opens_at", ""))
    assert is_iso8601_timestamp(data.get("closes_at", ""))
    assert isinstance(data.get("cooling_off_days"), int)


# ---------------------------------------------------------------------------
# AuditLogEntry (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: dict) -> None:
    _assert_common_appendonly(data, "AuditLogEntry")
    assert "updated_at" not in data, (
        "AuditLogEntry is append-only and must not expose updated_at "
        "(PRD §2.4)"
    )
    assert "version" not in data, (
        "AuditLogEntry is append-only and must not expose version (PRD §2.4)"
    )
    assert data.get("subject_type") in {"MATCH_INCIDENT", "TRANSFER_OFFER"}
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("action"), str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_prize_pool_conservation(payouts: Iterable[Dict[str, Any]],
                                   total_prize_pool_cents: int) -> None:
    """PRD §3.1: 'sum of PrizePayout.gross_amount_cents across the
    tournament equals total_prize_pool_cents exactly.'"""
    total = sum(p.get("gross_amount_cents", 0) for p in payouts)
    assert total == total_prize_pool_cents, (
        f"Prize pool invariant violated: sum(gross_amount_cents)={total} "
        f"!= total_prize_pool_cents={total_prize_pool_cents}"
    )


def assert_version_increases(before: dict, after: dict,
                             expected_increment: int = 1) -> None:
    """PRD §2.4: 'version ... incremented by one on every mutation,
    including state transitions.'"""
    assert after.get("version") == before.get("version") + expected_increment, (
        f"version did not advance by {expected_increment}: "
        f"before={before.get('version')}, after={after.get('version')}"
    )


def assert_updated_at_advanced(before: dict, after: dict) -> None:
    """PRD §2.4: 'updated_at ... refreshes to Clock.now on every
    successful mutation.'"""
    assert after.get("updated_at", "") >= before.get("updated_at", ""), (
        f"updated_at did not advance: before={before.get('updated_at')}, "
        f"after={after.get('updated_at')}"
    )


__all__ = [
    "assert_tournament",
    "assert_prize_tier_sum_invariant",
    "assert_team_registration",
    "assert_player_contract",
    "assert_identity_verification",
    "assert_match",
    "assert_draft_event",
    "assert_match_incident",
    "assert_referee",
    "assert_crowdfund_contribution",
    "assert_prize_payout",
    "assert_transfer_offer",
    "assert_transfer_window",
    "assert_audit_log_entry",
    "assert_prize_pool_conservation",
    "assert_version_increases",
    "assert_updated_at_advanced",
]
