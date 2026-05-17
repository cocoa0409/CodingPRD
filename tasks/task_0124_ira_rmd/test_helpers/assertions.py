"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Top-level participant-facing resources (Participant, Account,
  ConversionRequest, BeneficiaryClaim) carry id + created_at +
  updated_at + version.
- Append-once event records (ContributionEvent, DistributionEvent,
  Form1099R, ExcessPenalty) carry ONLY id + created_at. They do NOT
  carry updated_at or version. A ContributionEvent records reversal
  in reversed_at, a DistributionEvent in settled_at, an ExcessPenalty
  in assessed_at.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """Every resource carries id + created_at — PRD §2.4."""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 with three fractional digits, got "
        f"{data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: top-level participant-facing resources carry
    updated_at + version. version starts at 1 and increments by exactly
    1 per mutation.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 with three fractional digits, got "
        f"{data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_no_updated_at_no_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-once event records carry NEITHER updated_at NOR
    version. We do not assert their absence (an implementation MAY
    serialize null values), but tests must never rely on them being
    present. This helper is a documentation hook; if asserting absence
    is desired, individual tests do so directly.
    """
    return None  # No-op; presence/absence is not load-bearing.


# ===========================================================================
# Top-level resources — PRD §3
# ===========================================================================
def assert_participant(data: Dict[str, Any]) -> None:
    """PRD §3.1 Participant shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    assert data.get("tax_status") in {
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD",
    }, f"unexpected tax_status: {data.get('tax_status')!r}"
    assert isinstance(data.get("is_deceased"), bool)
    # date_of_death is null while alive, ISO date when deceased.
    dod = data.get("date_of_death")
    assert dod is None or isinstance(dod, str), (
        f"date_of_death must be null or string, got {dod!r}"
    )


def assert_account(data: Dict[str, Any]) -> None:
    """PRD §3.2 Account shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("participant_id"), str)
    assert data.get("account_type") in {"TRADITIONAL", "ROTH"}
    assert data.get("status") in {"OPEN", "FROZEN", "CLOSED"}
    assert isinstance(data.get("balance_cents"), int)
    assert data["balance_cents"] >= 0, (
        f"balance_cents must be non-negative, got {data['balance_cents']}"
    )
    assert isinstance(data.get("ytd_contribution_cents"), int)
    assert data["ytd_contribution_cents"] >= 0
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("prior_year_end_balance_cents"), int)
    assert data["prior_year_end_balance_cents"] >= 0
    # inherited_from_participant_id is null for own accounts.
    inherited = data.get("inherited_from_participant_id")
    assert inherited is None or isinstance(inherited, str), (
        f"inherited_from_participant_id must be null or string, got "
        f"{inherited!r}"
    )


def assert_conversion_request(data: Dict[str, Any]) -> None:
    """PRD §3.7 ConversionRequest shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("source_account_id"), str)
    assert isinstance(data.get("destination_account_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 1
    assert isinstance(data.get("backdoor_flag"), bool)
    assert data.get("status") in {
        "PENDING", "APPROVED", "REJECTED", "COMPLETED", "CANCELED",
    }, f"unexpected status: {data.get('status')!r}"


def assert_beneficiary_claim(data: Dict[str, Any]) -> None:
    """PRD §3.6 BeneficiaryClaim shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("beneficiary_participant_id"), str)
    assert isinstance(data.get("claim_date"), str)
    assert isinstance(data.get("deadline_date"), str)
    assert data.get("status") in {
        "CLAIMED", "SUSPENDED", "DRAINED", "FORFEITED",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("drained_amount_cents"), int)
    assert data["drained_amount_cents"] >= 0


# ===========================================================================
# Append-once event records — PRD §2.4 (no updated_at, no version)
# ===========================================================================
def assert_contribution_event(data: Dict[str, Any]) -> None:
    """PRD §3.3 ContributionEvent shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 1
    assert data.get("contribution_type") in {
        "REGULAR", "CATCHUP", "BACKDOOR_NONDEDUCTIBLE",
    }, f"unexpected contribution_type: {data.get('contribution_type')!r}"
    assert isinstance(data.get("tax_year"), int)
    assert data.get("status") in {"POSTED", "REVERSED"}
    # reversed_at null while POSTED, ISO timestamp when REVERSED.
    rev = data.get("reversed_at")
    assert rev is None or isinstance(rev, str), (
        f"reversed_at must be null or string, got {rev!r}"
    )


def assert_distribution_event(data: Dict[str, Any]) -> None:
    """PRD §3.4 DistributionEvent shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("gross_amount_cents"), int)
    assert data["gross_amount_cents"] >= 1
    assert data.get("distribution_reason") in {
        "NORMAL", "EARLY", "RMD", "DEATH", "CONVERSION", "EXCESS_REMOVAL",
    }, (
        f"unexpected distribution_reason: "
        f"{data.get('distribution_reason')!r}"
    )
    assert isinstance(data.get("federal_withholding_cents"), int)
    assert data["federal_withholding_cents"] >= 0
    assert isinstance(data.get("net_amount_cents"), int)
    # PRD §3.4: 'net_amount_cents is then the exact integer difference
    # gross_amount_cents minus federal_withholding_cents'.
    assert (
        data["net_amount_cents"]
        == data["gross_amount_cents"] - data["federal_withholding_cents"]
    ), (
        f"net_amount_cents != gross - withholding: "
        f"{data['net_amount_cents']} != "
        f"{data['gross_amount_cents']} - {data['federal_withholding_cents']}"
    )
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("settled_at"), str)
    assert is_iso8601_timestamp(data["settled_at"]), (
        f"settled_at must be ISO 8601, got {data['settled_at']!r}"
    )


def assert_form_1099r(data: Dict[str, Any]) -> None:
    """PRD §3.9 Form1099R shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("recipient_participant_id"), str)
    assert data.get("source_event_type") in {
        "DISTRIBUTION", "EXCESS_PENALTY", "CONVERSION",
    }, (
        f"unexpected source_event_type: "
        f"{data.get('source_event_type')!r}"
    )
    assert isinstance(data.get("source_event_id"), str)
    assert isinstance(data.get("box1_gross_distribution_cents"), int)
    assert isinstance(data.get("box2a_taxable_amount_cents"), int)
    assert isinstance(data.get("box4_federal_withholding_cents"), int)
    # PRD §3.9: box7 in {1, 2, 7, 4, G, 8}.
    box7 = data.get("box7_distribution_code")
    assert str(box7) in {"1", "2", "7", "4", "G", "8"}, (
        f"unexpected box7_distribution_code: {box7!r}"
    )
    assert data.get("status") in {"ISSUED", "CORRECTED", "VOIDED"}


def assert_excess_penalty(data: Dict[str, Any]) -> None:
    """PRD §3.8 ExcessPenalty shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("excess_amount_cents"), int)
    assert data["excess_amount_cents"] >= 0
    assert isinstance(data.get("penalty_amount_cents"), int)
    assert data["penalty_amount_cents"] >= 0
    assert isinstance(data.get("assessed_at"), str)
    assert is_iso8601_timestamp(data["assessed_at"]), (
        f"assessed_at must be ISO 8601, got {data['assessed_at']!r}"
    )


# ===========================================================================
# Read projections — PRD §3.5, §3.6
# ===========================================================================
def assert_rmd_quote(data: Dict[str, Any]) -> None:
    """PRD §3.5 GET /accounts/{id}/rmd returns required_amount_cents."""
    assert "required_amount_cents" in data, (
        f"missing required_amount_cents; got keys: {list(data)}"
    )
    assert isinstance(data["required_amount_cents"], int), (
        f"required_amount_cents must be integer cents, got "
        f"{type(data['required_amount_cents'])}"
    )
    assert data["required_amount_cents"] >= 0


def assert_drawdown_projection(data: Dict[str, Any]) -> None:
    """PRD §3.6 GET /beneficiary-claims/{id}/projection returns three
    fields: remaining_years, projected_rmd_cents,
    projected_total_drawdown_cents.
    """
    for k in (
        "remaining_years",
        "projected_rmd_cents",
        "projected_total_drawdown_cents",
    ):
        assert k in data, f"missing {k}; got keys: {list(data)}"
        assert isinstance(data[k], int), (
            f"{k} must be integer, got {type(data[k])}"
        )
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_distribution_net_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.4: 'net_amount_cents is then the exact integer difference
    gross_amount_cents minus federal_withholding_cents — no further
    rounding occurs at the subtraction step.'"""
    assert (
        data["net_amount_cents"]
        == data["gross_amount_cents"] - data["federal_withholding_cents"]
    )


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that begins at 1 on creation and
    increments by exactly 1 on each mutation.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


__all__ = [
    "assert_participant",
    "assert_account",
    "assert_conversion_request",
    "assert_beneficiary_claim",
    "assert_contribution_event",
    "assert_distribution_event",
    "assert_form_1099r",
    "assert_excess_penalty",
    "assert_rmd_quote",
    "assert_drawdown_projection",
    "assert_distribution_net_invariant",
    "assert_version_incremented_by_one",
]
