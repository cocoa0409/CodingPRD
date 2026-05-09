"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each helper checks
exactly the surface contract the PRD declares; computed-field presence is
asserted only when PRD §3 explicitly states the field is exposed on the
listed endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def _assert_common_fields_full(data: Dict[str, Any], entity_label: str) -> None:
    """For entities with PRD §2.4 'common_fields: true' — id, created_at,
    updated_at, version are all present.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 with three fractional "
        f"digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 with three fractional "
        f"digits, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{entity_label}.version must be a positive integer, got {version!r}"
    )


def _assert_common_fields_bare(data: Dict[str, Any], entity_label: str) -> None:
    """For entities with PRD §2.4 write-once semantics — only id and
    created_at are present. updated_at and version MUST NOT be asserted.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Event (PRD §3.1, §3.6, §2.8)
# ---------------------------------------------------------------------------
def assert_event(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Event")
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 120
    assert data["event_type"] in {"SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"}
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["country_code"].isupper()
    assert isinstance(data["regulations_text"], str) and \
        1 <= len(data["regulations_text"]) <= 4000
    assert is_iso8601_timestamp(data["registration_opens_at"])
    assert is_iso8601_timestamp(data["registration_closes_at"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert data["settlement_currency"] in {"USD", "EUR", "JPY", "GBP"}
    assert isinstance(data["capacity_min"], int) and data["capacity_min"] >= 2
    assert isinstance(data["capacity_max"], int)
    assert data["capacity_max"] >= data["capacity_min"]
    assert data["capacity_max"] <= 256
    assert isinstance(data["prize_pool_cents"], int) and data["prize_pool_cents"] >= 0
    # tax_withholding_pct: PRD §2.6 — exactly two decimal places, 0..50 inclusive
    tax = data["tax_withholding_pct"]
    assert isinstance(tax, (int, float))
    assert 0 <= float(tax) <= 50
    assert data["status"] in {
        "DRAFT", "OPEN", "REGISTRATION_CLOSED", "DRAWN",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    }
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0
    assert isinstance(data["prize_paid_total_cents"], int)
    assert data["prize_paid_total_cents"] >= 0
    assert data["posture"] in {"CLEAN", "UNDER_REVIEW", "FROZEN"}


# ---------------------------------------------------------------------------
# Participant (PRD §3.1, §3.6)
# ---------------------------------------------------------------------------
def assert_participant(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Participant")
    assert is_valid_uuid(data.get("event_id", "")), \
        "Participant.event_id must be UUID"
    assert isinstance(data["athlete_external_id"], str)
    assert isinstance(data["display_name"], str) and \
        1 <= len(data["display_name"]) <= 80
    team = data.get("team_code")
    assert team is None or (
        isinstance(team, str) and len(team) == 3 and team.isupper() and team.isalpha()
    )
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    wr = data.get("world_ranking")
    assert wr is None or (isinstance(wr, int))
    assert data["region"] in {"AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA"}
    assert isinstance(data["entry_fee_paid_cents"], int)
    assert data["entry_fee_paid_cents"] >= 0
    assert data["status"] in {
        "REGISTERED", "SEEDED", "ACTIVE",
        "ELIMINATED", "WITHDRAWN", "DISQUALIFIED",
    }
    seed = data.get("bracket_seed")
    assert seed is None or (isinstance(seed, int) and seed >= 1)
    assert isinstance(data["gross_prize_cents"], int) and data["gross_prize_cents"] >= 0
    assert isinstance(data["net_prize_cents"], int) and data["net_prize_cents"] >= 0
    fr = data.get("final_rank")
    assert fr is None or (isinstance(fr, int) and fr >= 1)


# ---------------------------------------------------------------------------
# Referee (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_referee(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Referee")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    aff = data.get("team_affiliation")
    assert aff is None or (
        isinstance(aff, str) and len(aff) == 3 and aff.isupper() and aff.isalpha()
    )
    quals = data["qualifications"]
    assert isinstance(quals, list) and len(quals) >= 1
    assert all(q in {"SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"} for q in quals)
    assert data["grade"] in {"A", "B", "C"}
    assert isinstance(data["is_active"], bool)


# ---------------------------------------------------------------------------
# Match (PRD §3.2, §3.4)
# ---------------------------------------------------------------------------
def assert_match(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Match")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert isinstance(data["bracket_position"], int) and data["bracket_position"] >= 1
    home = data.get("home_participant_id")
    away = data.get("away_participant_id")
    assert home is None or is_valid_uuid(home)
    assert away is None or is_valid_uuid(away)
    if data["status"] == "BYE":
        assert away is None, "BYE match must have away_participant_id == null"
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["status"] in {
        "SCHEDULED", "RESULT_PENDING", "DISPUTED", "LOCKED", "BYE", "VOIDED",
    }


# ---------------------------------------------------------------------------
# RefereeAssignment (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_referee_assignment(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "RefereeAssignment")
    assert is_valid_uuid(data["match_id"])
    assert is_valid_uuid(data["referee_id"])
    assert data["role"] in {"HEAD", "ASSISTANT", "SUBSTITUTE"}
    assert data["status"] in {"ASSIGNED", "REVOKED", "ACTIVATED"}
    rep = data.get("replaces_assignment_id")
    assert rep is None or is_valid_uuid(rep)


# ---------------------------------------------------------------------------
# ResultEntry (PRD §3.4) — write-once
# ---------------------------------------------------------------------------
def assert_result_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "ResultEntry")
    assert is_valid_uuid(data["match_id"])
    assert is_valid_uuid(data["submitted_by_assignment_id"])
    assert isinstance(data["home_score"], int) and data["home_score"] >= 0
    assert isinstance(data["away_score"], int) and data["away_score"] >= 0
    assert data["kind"] in {"REFEREE_SUBMISSION", "CORRECTION"}


# ---------------------------------------------------------------------------
# Dispute (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Dispute")
    assert is_valid_uuid(data["match_id"])
    assert is_valid_uuid(data["filed_by_participant_id"])
    assert isinstance(data["reason_text"], str) and \
        1 <= len(data["reason_text"]) <= 1000
    assert data["status"] in {"OPEN", "UPHELD", "REJECTED"}


# ---------------------------------------------------------------------------
# RankingEntry (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_ranking_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "RankingEntry")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["points"], int) and data["points"] >= 0
    assert isinstance(data["goal_difference"], int)
    assert isinstance(data["away_goals"], int) and data["away_goals"] >= 0
    assert isinstance(data["sets_won"], int) and data["sets_won"] >= 0


# ---------------------------------------------------------------------------
# PrizePayment (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_prize_payment(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "PrizePayment")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["gross_amount_cents"], int)
    assert data["gross_amount_cents"] >= 0
    assert isinstance(data["tax_withheld_cents"], int)
    assert data["tax_withheld_cents"] >= 0
    assert isinstance(data["forfeit_amount_cents"], int)
    assert data["forfeit_amount_cents"] >= 0
    assert isinstance(data["net_amount_cents"], int)
    # PRD §3.6: net = gross - tax - forfeit, clamped at 0
    assert data["net_amount_cents"] >= 0
    assert is_iso8601_timestamp(data["scheduled_pay_at"])
    assert data["status"] in {"SCHEDULED", "FORFEITED", "PAID", "CANCELLED"}


# ---------------------------------------------------------------------------
# DopingSample (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_doping_sample(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "DopingSample")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["participant_id"])
    assert is_iso8601_timestamp(data["collected_at"])
    chain = data.get("chain_log")
    assert isinstance(chain, list)
    for entry in chain:
        assert entry["action"] in {"DISPATCH", "RECEIVE"}
        assert is_iso8601_timestamp(entry["at"])
        assert isinstance(entry.get("actor_user_id"), str)
    assert data["status"] in {
        "COLLECTED", "IN_TRANSIT", "RECEIVED",
        "NEGATIVE", "POSITIVE", "VOIDED",
    }


# ---------------------------------------------------------------------------
# SanctionRecord (PRD §3.8) — write-once
# ---------------------------------------------------------------------------
def assert_sanction(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "SanctionRecord")
    assert is_valid_uuid(data["sample_id"])
    assert is_valid_uuid(data["participant_id"])
    bm = data.get("ban_months")
    if bm is not None:
        assert isinstance(bm, int) and 1 <= bm <= 120
    assert isinstance(data["prize_forfeited_cents"], int)
    assert data["prize_forfeited_cents"] >= 0
    assert data["status"] in {"ISSUED", "APPEALED", "FINAL", "REVOKED"}


# ---------------------------------------------------------------------------
# Appeal (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Appeal")
    assert is_valid_uuid(data["sanction_id"])
    assert isinstance(data["filed_by_user_id"], str) and \
        len(data["filed_by_user_id"]) > 0
    assert isinstance(data["ground_text"], str) and \
        1 <= len(data["ground_text"]) <= 2000
    assert data["status"] in {"PENDING", "UPHELD", "DISMISSED"}


# ---------------------------------------------------------------------------
# AuditLog and SyncEvent (PRD §2.10) — write-once
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "AuditLog")
    assert data["kind"] in {"RESULT_CHANGE", "SANCTION_CHANGE"}
    assert data["subject_kind"] in {"MATCH", "SANCTION_RECORD"}
    assert is_valid_uuid(data["subject_id"])
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)


def assert_sync_event(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "SyncEvent")
    assert data["target_system"] in {"PAYMENT", "GOVERNING_BODY", "IM"}
    assert data["kind"] in {
        "ENTRY_FEE_CHARGED", "PRIZE_PAID",
        "SANCTION_ARCHIVED", "DRAW_ANNOUNCED",
    }


# ---------------------------------------------------------------------------
# Domain invariant helpers (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
def assert_prize_payment_arithmetic(data: Dict[str, Any]) -> None:
    """PRD §3.6: 'net is the gross minus tax withheld minus forfeit,
    clamped at a non-negative floor of 0.'"""
    expected = max(
        0,
        data["gross_amount_cents"]
        - data["tax_withheld_cents"]
        - data["forfeit_amount_cents"],
    )
    assert data["net_amount_cents"] == expected, (
        f"net_amount_cents={data['net_amount_cents']} != "
        f"max(0, gross-tax-forfeit)={expected}"
    )


def find_audit_logs(
    rows: Iterable[Dict[str, Any]],
    *,
    kind: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter a list of audit-log rows in test code."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if kind is not None and row.get("kind") != kind:
            continue
        if subject_kind is not None and row.get("subject_kind") != subject_kind:
            continue
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        out.append(row)
    return out


def find_sync_events(
    rows: Iterable[Dict[str, Any]],
    *,
    target_system: Optional[str] = None,
    kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter a list of sync-event rows in test code."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if target_system is not None and row.get("target_system") != target_system:
            continue
        if kind is not None and row.get("kind") != kind:
            continue
        out.append(row)
    return out


__all__ = [
    "assert_event",
    "assert_participant",
    "assert_referee",
    "assert_match",
    "assert_referee_assignment",
    "assert_result_entry",
    "assert_dispute",
    "assert_ranking_entry",
    "assert_prize_payment",
    "assert_doping_sample",
    "assert_sanction",
    "assert_appeal",
    "assert_audit_log",
    "assert_sync_event",
    "assert_prize_payment_arithmetic",
    "find_audit_logs",
    "find_sync_events",
]
