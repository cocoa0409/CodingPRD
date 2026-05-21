"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3
for that entity. Common-fields entities (PRD §2.4) carry id +
created_at + updated_at + version. The two append-only entities
(`TransferLink` and `FSAContribution`) carry only id + created_at —
PRD §2.4: "Two entities are append-only ledger lines and therefore
carry only `id` and `created_at`, with neither `updated_at` nor
`version`: `TransferLink` ... and `FSAContribution` ..."
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields resource carries id, created_at,
    updated_at, version (integer starting at 1, incremented on each
    modification)."""
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: TransferLink and FSAContribution carry only id and
    created_at; neither updated_at nor version may be present."""
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.5: "the mutation proceeds and `version` increments by one"."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Rider — PRD §3.1
# ---------------------------------------------------------------------------
def assert_rider(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "full_name must be non-empty string"
    )
    assert isinstance(data.get("email"), str) and data["email"], (
        "email must be non-empty string"
    )
    assert "low_income_verified" in data, (
        "Rider missing low_income_verified"
    )
    assert isinstance(data["low_income_verified"], bool), (
        f"low_income_verified must be bool, got "
        f"{type(data['low_income_verified'])}"
    )
    # employer_id may be null when not enrolled.
    emp_id = data.get("employer_id", None)
    assert emp_id is None or isinstance(emp_id, str), (
        f"employer_id must be string or null, got {emp_id!r}"
    )


# ---------------------------------------------------------------------------
# Employer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_employer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("enrollment_status") in {
        "ACTIVE", "SUSPENDED", "TERMINATED",
    }, f"enrollment_status invalid: {data.get('enrollment_status')!r}"
    cap = data.get("monthly_contribution_cap_cents")
    assert isinstance(cap, int) and cap >= 0, (
        f"monthly_contribution_cap_cents must be non-negative int, "
        f"got {cap!r}"
    )


# ---------------------------------------------------------------------------
# FareCard — PRD §3.2
# ---------------------------------------------------------------------------
def assert_fare_card(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("rider_id"), str)
    assert data.get("discount_class") in {
        "STANDARD", "REDUCED_FARE", "LOW_INCOME",
    }, f"discount_class invalid: {data.get('discount_class')!r}"
    assert data.get("status") in {"ACTIVE", "SUSPENDED", "CLOSED"}, (
        f"FareCard.status invalid: {data.get('status')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("valid_from", ""))), (
        f"valid_from must be ISO 8601, got {data.get('valid_from')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("valid_until", ""))), (
        f"valid_until must be ISO 8601, got {data.get('valid_until')!r}"
    )
    wallet = data.get("wallet_balance_cents")
    assert isinstance(wallet, int) and wallet >= 0, (
        f"wallet_balance_cents must be non-negative int, got {wallet!r}"
    )
    # mobile_token_id may be null.
    mt = data.get("mobile_token_id", None)
    assert mt is None or isinstance(mt, str), (
        f"mobile_token_id must be string or null, got {mt!r}"
    )


# ---------------------------------------------------------------------------
# ReducedFareCertificate — PRD §3.2
# ---------------------------------------------------------------------------
def assert_reduced_fare_certificate(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("rider_id"), str)
    assert data.get("program_type") in {
        "SENIOR", "DISABILITY", "STUDENT",
    }, f"program_type invalid: {data.get('program_type')!r}"
    assert is_iso8601_timestamp(str(data.get("valid_from", "")))
    assert is_iso8601_timestamp(str(data.get("valid_until", "")))
    assert data.get("status") in {"PENDING", "ACTIVE", "REVOKED"}, (
        f"ReducedFareCertificate.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# LowIncomeVerification — PRD §3.3
# ---------------------------------------------------------------------------
def assert_low_income_verification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("rider_id"), str)
    di = data.get("declared_annual_income_cents")
    assert isinstance(di, int) and di >= 0, (
        f"declared_annual_income_cents must be non-negative int, got {di!r}"
    )
    # verified_annual_income_cents is null while PENDING per PRD §3.3.
    vi = data.get("verified_annual_income_cents", None)
    assert vi is None or (isinstance(vi, int) and vi >= 0), (
        f"verified_annual_income_cents must be non-negative int or null, "
        f"got {vi!r}"
    )
    assert data.get("status") in {
        "PENDING", "ACTIVE", "REJECTED", "EXPIRED",
    }, f"LowIncomeVerification.status invalid: {data.get('status')!r}"
    # approved_at is null until ACTIVE.
    aa = data.get("approved_at", None)
    assert aa is None or is_iso8601_timestamp(str(aa)), (
        f"approved_at must be ISO 8601 or null, got {aa!r}"
    )


# ---------------------------------------------------------------------------
# MobilePaymentToken — PRD §3.4
# ---------------------------------------------------------------------------
def assert_mobile_payment_token(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("rider_id"), str)
    assert data.get("wallet_provider") in {
        "APPLE_PAY", "GOOGLE_PAY", "SAMSUNG_PAY",
    }, f"wallet_provider invalid: {data.get('wallet_provider')!r}"
    assert isinstance(data.get("device_fingerprint"), str), (
        "device_fingerprint must be a string"
    )
    assert data.get("status") in {"ACTIVE", "REVOKED"}, (
        f"MobilePaymentToken.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Trip — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
def assert_trip(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("card_id"), str)
    assert isinstance(data.get("idempotency_key"), str)
    assert is_iso8601_timestamp(str(data.get("tap_in_at", ""))), (
        f"tap_in_at must be ISO 8601, got {data.get('tap_in_at')!r}"
    )
    # tap_out_at is null until COMPLETED / INCOMPLETE_FORCED.
    to = data.get("tap_out_at", None)
    assert to is None or is_iso8601_timestamp(str(to)), (
        f"tap_out_at must be ISO 8601 or null, got {to!r}"
    )
    assert data.get("fare_status") in {
        "PROVISIONAL", "SETTLED", "DISPUTED",
    }, f"fare_status invalid: {data.get('fare_status')!r}"
    assert data.get("travel_status") in {
        "TAPPED_IN", "COMPLETED", "INCOMPLETE_FORCED",
    }, f"travel_status invalid: {data.get('travel_status')!r}"
    pf = data.get("provisional_fare_cents")
    assert isinstance(pf, int) and pf >= 0, (
        f"provisional_fare_cents must be non-negative int, got {pf!r}"
    )
    # settled_fare_cents is null until SETTLED.
    sf = data.get("settled_fare_cents", None)
    assert sf is None or (isinstance(sf, int) and sf >= 0), (
        f"settled_fare_cents must be non-negative int or null, got {sf!r}"
    )
    pff = data.get("paid_from_fsa_cents", 0)
    assert isinstance(pff, int) and pff >= 0, (
        f"paid_from_fsa_cents must be non-negative int, got {pff!r}"
    )
    # transfer_link_id and cap_period_id may be present.
    tl = data.get("transfer_link_id", None)
    assert tl is None or isinstance(tl, str), (
        f"transfer_link_id must be string or null, got {tl!r}"
    )


# ---------------------------------------------------------------------------
# TransferLink — PRD §3.5 (append-only ledger)
# ---------------------------------------------------------------------------
def assert_transfer_link(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("first_trip_id"), str)
    assert isinstance(data.get("second_trip_id"), str)
    wm = data.get("window_minutes")
    assert isinstance(wm, int), f"window_minutes must be int, got {wm!r}"
    assert 0 < wm <= 120, (
        f"window_minutes must satisfy 0 < x <= 120, got {wm}"
    )


# ---------------------------------------------------------------------------
# FareCapPeriod — PRD §2.9
# ---------------------------------------------------------------------------
def assert_fare_cap_period(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("card_id"), str)
    assert data.get("scope") in {"DAILY", "WEEKLY"}, (
        f"scope invalid: {data.get('scope')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("window_start", "")))
    assert is_iso8601_timestamp(str(data.get("window_end", "")))
    ac = data.get("accumulated_cents")
    assert isinstance(ac, int) and ac >= 0, (
        f"accumulated_cents must be non-negative int, got {ac!r}"
    )
    cc = data.get("cap_cents")
    assert isinstance(cc, int) and cc >= 0, (
        f"cap_cents must be non-negative int, got {cc!r}"
    )
    cr = data.get("cap_reached_at", None)
    assert cr is None or is_iso8601_timestamp(str(cr)), (
        f"cap_reached_at must be ISO 8601 or null, got {cr!r}"
    )


# ---------------------------------------------------------------------------
# CommuterBenefitAccount — PRD §3.9
# ---------------------------------------------------------------------------
def assert_commuter_benefit_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("rider_id"), str)
    assert isinstance(data.get("employer_id"), str)
    b = data.get("balance_cents")
    assert isinstance(b, int), (
        f"balance_cents must be int, got {b!r}"
    )
    assert data.get("status") in {"ACTIVE", "FROZEN"}, (
        f"CommuterBenefitAccount.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# FSAContribution — PRD §3.9 (append-only ledger)
# ---------------------------------------------------------------------------
def assert_fsa_contribution(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("account_id"), str)
    a = data.get("amount_cents")
    assert isinstance(a, int), (
        f"amount_cents must be int, got {a!r}"
    )
    # contribution_month is a YYYY-MM tag per PRD §3.9.
    cm = data.get("contribution_month")
    assert isinstance(cm, str) and len(cm) == 7 and cm[4] == "-", (
        f"contribution_month must be YYYY-MM, got {cm!r}"
    )
    assert data.get("status") in {"APPLIED", "REVERSED"}, (
        f"FSAContribution.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# DisputeCase — PRD §3.7
# ---------------------------------------------------------------------------
def assert_dispute_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("trip_id"), str)
    assert isinstance(data.get("rider_id"), str)
    assert data.get("status") in {
        "OPEN", "INVESTIGATING", "RESOLVED_REFUNDED", "RESOLVED_REJECTED",
    }, f"DisputeCase.status invalid: {data.get('status')!r}"
    # refund_amount_cents is null until RESOLVED_REFUNDED.
    ra = data.get("refund_amount_cents", None)
    assert ra is None or (isinstance(ra, int) and ra >= 0), (
        f"refund_amount_cents must be non-negative int or null, got {ra!r}"
    )


# ---------------------------------------------------------------------------
# Conservation invariants — PRD §2.8 / §2.10
# ---------------------------------------------------------------------------
def assert_wallet_plus_fsa_conserved(
    *,
    pre_wallet: int, pre_fsa: int,
    post_wallet: int, post_fsa: int,
    expected_delta: int,
) -> None:
    """PRD §2.8: "Running accumulators, cap remainders, and the wallet
    share of a refund are all integer cents throughout, with the wallet
    share absorbing any rounding remainder so that the sum of FSA share
    and wallet share equals the conserved total exactly."

    Asserts that (post_wallet + post_fsa) - (pre_wallet + pre_fsa) ==
    expected_delta, i.e. the wallet+FSA total moved by exactly the
    requested amount (no drift)."""
    pre_total = pre_wallet + pre_fsa
    post_total = post_wallet + post_fsa
    actual_delta = post_total - pre_total
    assert actual_delta == expected_delta, (
        f"Wallet+FSA conservation violated: pre {pre_total}, "
        f"post {post_total}, delta {actual_delta}, expected {expected_delta}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_rider",
    "assert_employer",
    "assert_fare_card",
    "assert_reduced_fare_certificate",
    "assert_low_income_verification",
    "assert_mobile_payment_token",
    "assert_trip",
    "assert_transfer_link",
    "assert_fare_cap_period",
    "assert_commuter_benefit_account",
    "assert_fsa_contribution",
    "assert_dispute_case",
    "assert_wallet_plus_fsa_conserved",
]
