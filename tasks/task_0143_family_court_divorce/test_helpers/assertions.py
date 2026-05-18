"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.5: every persisted resource carries id + created_at +
updated_at + version EXCEPT MediationSession (lightweight log,
id + created_at only) and ServerClock (singleton with only now).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CASE_STATUSES,
    DISCLOSURE_STATUSES,
    DIVISION_MODELS,
    FINAL_JUDGMENT_STATUSES,
    GUIDELINE_MODELS,
    LEGAL_CUSTODY_VALUES,
    MEDIATION_OUTCOMES,
    MEDIATION_SESSION_STATUSES,
    ORDER_KINDS,
    PARENTING_PLAN_STATUSES,
    PARTY_ROLES,
    PHYSICAL_CUSTODY_VALUES,
    SUPPORT_ORDER_STATUSES,
    SUPPORT_TYPES,
    TEMP_ORDER_STATUSES,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.5
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.5: 'id — a server-minted UUID. Identifiers carry no type
    prefix.' / 'created_at — an ISO 8601 UTC timestamp ... set at
    creation and never mutated.'"""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.5: 'updated_at — an ISO 8601 UTC timestamp ... refreshed
    on every mutation of the resource' / 'version — an integer that
    starts at 1 on creation and is incremented by 1 on every mutation
    of the resource.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def assert_version_incremented_by_one(new: int, old: int) -> None:
    """PRD §2.5: 'incremented by 1 on every mutation of the resource.
    The increment is per-resource.'"""
    assert isinstance(new, int) and isinstance(old, int), (
        f"version must be int, got new={new!r} old={old!r}"
    )
    assert new == old + 1, (
        f"version must increment by exactly 1, got old={old} -> new={new}"
    )


# ---------------------------------------------------------------------------
# Docket number — PRD §3.1
# ---------------------------------------------------------------------------
_DOCKET_RE = re.compile(r"^FC-\d{4}-\d{6}$")


def assert_docket_number_format(docket_number: str) -> None:
    """PRD §3.1: 'mints Case.docket_number in the format
    FC-YYYY-NNNNNN'."""
    assert isinstance(docket_number, str), (
        f"docket_number must be a string, got {type(docket_number)}"
    )
    assert _DOCKET_RE.match(docket_number), (
        f"docket_number must match FC-YYYY-NNNNNN, got {docket_number!r}"
    )


# ---------------------------------------------------------------------------
# Case — PRD §3.1, §2.5
# ---------------------------------------------------------------------------
def assert_case(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert_docket_number_format(data.get("docket_number", ""))
    assert isinstance(data.get("petitioner_party_id"), str)
    assert is_valid_uuid(data["petitioner_party_id"])
    assert isinstance(data.get("respondent_party_id"), str)
    assert is_valid_uuid(data["respondent_party_id"])
    assert data.get("jurisdiction_state") in [
        "CA", "NY", "TX", "FL", "IL", "WA",
    ], f"jurisdiction_state must be allowed; got {data.get('jurisdiction_state')!r}"
    assert data.get("status") in CASE_STATUSES, (
        f"Case.status must be one of {CASE_STATUSES}, got "
        f"{data.get('status')!r}"
    )
    assert isinstance(data.get("has_minor_children"), bool)
    # mediation_round is system-managed; >= 0.
    if "mediation_round" in data:
        assert isinstance(data["mediation_round"], int)
        assert data["mediation_round"] >= 0
    # answer_deadline_at: ISO 8601 (PRD §3.1 sets it on case creation).
    assert "answer_deadline_at" in data, "missing answer_deadline_at"
    assert is_iso8601_timestamp(data["answer_deadline_at"]), (
        f"answer_deadline_at must be ISO 8601, got "
        f"{data['answer_deadline_at']!r}"
    )


# ---------------------------------------------------------------------------
# Party — PRD §3.1, §2.5
# ---------------------------------------------------------------------------
def assert_party(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("role") in PARTY_ROLES, (
        f"Party.role must be one of {PARTY_ROLES}, got {data.get('role')!r}"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("has_filed_answer"), bool), (
        f"has_filed_answer must be bool, got "
        f"{type(data.get('has_filed_answer'))}"
    )
    assert isinstance(data.get("case_id"), str)
    assert is_valid_uuid(data["case_id"])


# ---------------------------------------------------------------------------
# FinancialDisclosure — PRD §3.2, §2.5
# ---------------------------------------------------------------------------
def assert_disclosure(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in DISCLOSURE_STATUSES, (
        f"FinancialDisclosure.status must be one of "
        f"{DISCLOSURE_STATUSES}, got {data.get('status')!r}"
    )
    for f in (
        "gross_monthly_income_cents", "deductible_taxes_cents",
        "monthly_health_insurance_cents", "monthly_childcare_cents",
        "assets_total_cents", "debts_total_cents",
        "net_monthly_income_cents",
    ):
        assert f in data, f"missing {f}"
        assert isinstance(data[f], int), (
            f"{f} must be integer cents, got {type(data[f])}"
        )
        assert data[f] >= 0, (
            f"{f} must be non-negative, got {data[f]}"
        )


def assert_net_income(data: Dict[str, Any]) -> None:
    """PRD §3.2: 'The server computes net_monthly_income_cents
    immediately as the gross income minus the deductible taxes, floored
    at zero so it is never negative'."""
    gross = data["gross_monthly_income_cents"]
    taxes = data["deductible_taxes_cents"]
    expected = max(0, gross - taxes)
    assert data["net_monthly_income_cents"] == expected, (
        f"net_monthly_income_cents must be max(0, gross - taxes) = "
        f"max(0, {gross} - {taxes}) = {expected}; got "
        f"{data['net_monthly_income_cents']}"
    )


# ---------------------------------------------------------------------------
# ParentingPlan — PRD §3.3, §2.5
# ---------------------------------------------------------------------------
def assert_parenting_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in PARENTING_PLAN_STATUSES, (
        f"ParentingPlan.status must be one of {PARENTING_PLAN_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert data.get("legal_custody") in LEGAL_CUSTODY_VALUES
    assert data.get("physical_custody") in PHYSICAL_CUSTODY_VALUES
    p_on = data.get("petitioner_overnights_per_year")
    r_on = data.get("respondent_overnights_per_year")
    assert isinstance(p_on, int) and 0 <= p_on <= 365
    assert isinstance(r_on, int) and 0 <= r_on <= 365
    # PRD §3.3: 'the two values must sum to exactly 365'.
    assert p_on + r_on == 365, (
        f"overnights must sum to 365, got {p_on} + {r_on} = {p_on + r_on}"
    )


# ---------------------------------------------------------------------------
# SupportOrder — PRD §3.5, §2.5
# ---------------------------------------------------------------------------
def assert_support_order(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("support_type") in SUPPORT_TYPES, (
        f"support_type must be one of {SUPPORT_TYPES}, got "
        f"{data.get('support_type')!r}"
    )
    assert data.get("order_kind") in ORDER_KINDS, (
        f"order_kind must be one of {ORDER_KINDS}, got "
        f"{data.get('order_kind')!r}"
    )
    assert data.get("status") in SUPPORT_ORDER_STATUSES, (
        f"SupportOrder.status must be one of {SUPPORT_ORDER_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("monthly_amount_cents"), int), (
        f"monthly_amount_cents must be integer, got "
        f"{type(data.get('monthly_amount_cents'))}"
    )
    assert data["monthly_amount_cents"] >= 0, (
        f"monthly_amount_cents must be >= 0 (PRD §3.5 clamps to zero), "
        f"got {data['monthly_amount_cents']}"
    )


# ---------------------------------------------------------------------------
# TemporaryOrder — PRD §3.6, §2.5
# ---------------------------------------------------------------------------
def assert_temp_order(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in TEMP_ORDER_STATUSES, (
        f"TemporaryOrder.status must be one of {TEMP_ORDER_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# FinalJudgment — PRD §3.6, §2.5
# ---------------------------------------------------------------------------
def assert_final_judgment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in FINAL_JUDGMENT_STATUSES, (
        f"FinalJudgment.status must be one of {FINAL_JUDGMENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert data.get("division_model") in DIVISION_MODELS, (
        f"division_model must be one of {DIVISION_MODELS}, got "
        f"{data.get('division_model')!r}"
    )
    assert isinstance(data.get("petitioner_asset_share_cents"), int)
    assert isinstance(data.get("respondent_asset_share_cents"), int)


def assert_asset_division_conserved(
    fj: Dict[str, Any],
    p_assets: int, r_assets: int,
    p_debts: int, r_debts: int,
) -> None:
    """PRD §3.6: 'In both models, the resulting
    petitioner_asset_share_cents plus respondent_asset_share_cents
    equals the net pool exactly.'"""
    net_pool = p_assets + r_assets - p_debts - r_debts
    p_share = fj["petitioner_asset_share_cents"]
    r_share = fj["respondent_asset_share_cents"]
    assert p_share + r_share == net_pool, (
        f"asset-division invariant violated: "
        f"{p_share} + {r_share} = {p_share + r_share}; "
        f"net_pool = {p_assets} + {r_assets} - {p_debts} - {r_debts} = "
        f"{net_pool}"
    )


# ---------------------------------------------------------------------------
# MediationSession — PRD §3.4 (id + created_at only)
# ---------------------------------------------------------------------------
def assert_mediation_session(data: Dict[str, Any]) -> None:
    """PRD §2.5: 'MediationSession is treated as a lightweight log; it
    carries id and created_at but does not have updated_at or
    version.'"""
    _assert_id_and_created_at(data)
    # No updated_at / version assertions (PRD §2.5 explicitly excludes
    # them).
    assert data.get("status") in MEDIATION_SESSION_STATUSES
    if data.get("outcome") is not None:
        assert data["outcome"] in MEDIATION_OUTCOMES
    assert isinstance(data.get("mediator_user_id"), str)
    assert isinstance(data.get("scheduled_start_at"), str)
    assert isinstance(data.get("scheduled_end_at"), str)
    assert isinstance(data.get("round_index"), int)
    assert data["round_index"] >= 1


# ---------------------------------------------------------------------------
# ServerClock — PRD §2.6
# ---------------------------------------------------------------------------
def assert_server_clock(data: Dict[str, Any]) -> None:
    """PRD §2.5: 'ServerClock is a singleton system entity exposing only
    the now field; it has neither updated_at nor version.'"""
    assert "now" in data, f"ServerClock must expose now; got keys: {list(data)}"
    assert is_iso8601_timestamp(data["now"]), (
        f"ServerClock.now must be ISO 8601, got {data['now']!r}"
    )


# ---------------------------------------------------------------------------
# Error envelope check (PRD §2.2)
# ---------------------------------------------------------------------------
def assert_error_envelope(payload: Dict[str, Any]) -> None:
    """PRD §2.2: error envelope has meta + response_type=error +
    data.error_id + data.message."""
    assert payload.get("response_type") == "error", (
        f"Expected response_type=error; got {payload.get('response_type')!r}"
    )
    assert isinstance(payload.get("data"), dict)
    assert isinstance(payload["data"].get("error_id"), str)
    assert isinstance(payload["data"].get("message"), str)


__all__ = [
    "assert_version_incremented_by_one",
    "assert_docket_number_format",
    "assert_case",
    "assert_party",
    "assert_disclosure",
    "assert_net_income",
    "assert_parenting_plan",
    "assert_support_order",
    "assert_temp_order",
    "assert_final_judgment",
    "assert_asset_division_conserved",
    "assert_mediation_session",
    "assert_server_clock",
    "assert_error_envelope",
]
