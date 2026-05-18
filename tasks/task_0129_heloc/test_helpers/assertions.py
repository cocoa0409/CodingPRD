"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Borrower, Property, SeniorLien, Heloc carry id + created_at +
  updated_at + version.
- Draw, Payment, RateReset, Fee, DefaultEvent, InsuranceEvent,
  SeniorLienDefaultEvent, BankruptcyEvent are immutable ledger / audit
  entries carrying ONLY id + created_at. PRD §2.4: "they do not carry
  updated_at or version — both fields are absent from their responses".
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


_HELOC_STATUSES = {"PENDING", "DRAW", "REPAY", "DEFAULT", "CLOSED"}
_DEFAULT_TRIGGERS = {
    "DELINQUENCY_90",
    "INSURANCE_LAPSE",
    "SENIOR_LIEN_DEFAULT",
    "BANKRUPTCY",
}
_OCCUPANCY = {"PRIMARY", "SECONDARY", "INVESTMENT"}
_INSURANCE_STATUS = {"ACTIVE", "LAPSED"}
_SENIOR_LIEN_STATUS = {"CURRENT", "DEFAULTED"}
_FEE_TYPES = {"ANNUAL", "EARLY_CLOSURE"}
_FEE_STATUSES = {"ASSESSED", "WAIVED"}
_INSURANCE_EVENT_TYPES = {"LAPSE", "REINSTATE"}


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
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: Borrower / Property / SeniorLien / Heloc carry
    updated_at + version; version begins at 1 on creation."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: ledger entries / audit events expose ONLY id and
    created_at. updated_at and version must be absent from their
    responses because no in-place mutation is ever performed on them."""
    assert "updated_at" not in data, (
        f"immutable resource must NOT carry updated_at; got "
        f"{data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"immutable resource must NOT carry version; got "
        f"{data.get('version')!r}"
    )


# ===========================================================================
# Top-level resources
# ===========================================================================
def assert_borrower(data: Dict[str, Any]) -> None:
    """PRD §3.1 Borrower shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    # PRD §3.1: bankruptcy_flag begins false; never resets to false.
    assert isinstance(data.get("bankruptcy_flag"), bool)
    # PRD §3.1: bankruptcy_filed_at begins null.
    bf = data.get("bankruptcy_filed_at", None)
    assert bf is None or isinstance(bf, str), (
        f"bankruptcy_filed_at must be null or ISO string, got {bf!r}"
    )


def assert_property(data: Dict[str, Any]) -> None:
    """PRD §3.1 Property shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("borrower_id"), str) and data["borrower_id"]
    assert isinstance(data.get("address"), str) and data["address"]
    assert isinstance(data.get("appraised_value_cents"), int)
    assert data["appraised_value_cents"] >= 100_000
    assert data.get("occupancy") in _OCCUPANCY, (
        f"unexpected occupancy: {data.get('occupancy')!r}"
    )
    assert data.get("insurance_status") in _INSURANCE_STATUS, (
        f"unexpected insurance_status: {data.get('insurance_status')!r}"
    )
    il = data.get("insurance_lapsed_at", None)
    assert il is None or isinstance(il, str)


def assert_senior_lien(data: Dict[str, Any]) -> None:
    """PRD §3.1 SeniorLien shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("property_id"), str) and data["property_id"]
    assert isinstance(data.get("holder_name"), str) and data["holder_name"]
    assert isinstance(data.get("principal_balance_cents"), int)
    assert data["principal_balance_cents"] >= 0
    assert data.get("status") in _SENIOR_LIEN_STATUS, (
        f"unexpected senior lien status: {data.get('status')!r}"
    )
    d = data.get("defaulted_at", None)
    assert d is None or isinstance(d, str)


def assert_heloc(data: Dict[str, Any]) -> None:
    """PRD §3.2-§3.9 Heloc shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("borrower_id"), str) and data["borrower_id"]
    assert isinstance(data.get("property_id"), str) and data["property_id"]

    # Input integer fields — PRD §3.2
    for key in (
        "credit_limit_cents",
        "margin_bps",
        "periodic_cap_bps",
        "lifetime_cap_bps",
        "lifetime_floor_bps",
        "repayment_term_years",
        "annual_fee_cents",
        "early_closure_fee_cents",
    ):
        assert isinstance(data.get(key), int), (
            f"{key} must be integer, got {type(data.get(key))}"
        )

    # Computed integer fields — PRD §3.2, §3.3, §3.4
    for key in (
        "principal_balance_cents",
        "available_credit_cents",
        "accrued_interest_cents",
        "delinquency_days",
    ):
        assert isinstance(data.get(key), int), (
            f"{key} must be integer, got {type(data.get(key))}"
        )
        assert data[key] >= 0, f"{key} must be non-negative"

    # PRD §3.2: "computes initial_rate_bps ... sets current_rate_bps
    # equal to initial_rate_bps" — these are populated AT activation.
    # Pre-activation (PENDING) they may be null because PRD does not
    # define their values for the PENDING state.  Post-activation they
    # must be integers.
    if data.get("status") == "PENDING":
        assert data.get("current_rate_bps") is None or isinstance(
            data.get("current_rate_bps"), int
        )
        assert data.get("initial_rate_bps") is None or isinstance(
            data.get("initial_rate_bps"), int
        )
    else:
        assert isinstance(data.get("current_rate_bps"), int)
        assert isinstance(data.get("initial_rate_bps"), int)

    # PRD §3.2: status enum
    assert data.get("status") in _HELOC_STATUSES, (
        f"unexpected status: {data.get('status')!r}"
    )

    # PRD §3.2: annual_fee_waived_first_year is a boolean (input).
    assert isinstance(data.get("annual_fee_waived_first_year"), bool)

    # PRD §3.6: default_trigger is one of the four enum values OR null.
    dt = data.get("default_trigger", None)
    assert dt is None or dt in _DEFAULT_TRIGGERS, (
        f"unexpected default_trigger: {dt!r}"
    )

    # PRD §3.2/§3.9: defaulted_at / closed_at null until transition.
    for key in ("defaulted_at", "closed_at"):
        v = data.get(key, None)
        assert v is None or isinstance(v, str), (
            f"{key} must be null or ISO string, got {v!r}"
        )


def assert_heloc_get_response(data: Dict[str, Any]) -> None:
    """PRD §3.10: 'The single-HELOC read response includes the standard
    fields described in §2.4 as well as the computed
    minimum_payment_due_cents, the current available_credit_cents, and
    the current current_rate_bps, all evaluated against the present
    state of the account.'"""
    assert_heloc(data)
    assert "minimum_payment_due_cents" in data, (
        "GET /helocs/{id} must surface minimum_payment_due_cents "
        "per PRD §3.10"
    )
    mpd = data["minimum_payment_due_cents"]
    assert isinstance(mpd, int) and mpd >= 0, (
        f"minimum_payment_due_cents must be non-negative integer, "
        f"got {mpd!r}"
    )


# ===========================================================================
# Ledger / audit-log entries — id + created_at ONLY
# ===========================================================================
def assert_draw(data: Dict[str, Any]) -> None:
    """PRD §3.3 Draw shape (immutable ledger entry)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("heloc_id"), str) and data["heloc_id"]
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 10_000, (
        "PRD §3.3: amount_cents at least 10000"
    )
    assert isinstance(data.get("drawn_at"), str)
    assert is_iso8601_timestamp(data["drawn_at"]), (
        f"drawn_at must be ISO 8601, got {data['drawn_at']!r}"
    )


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §3.4 Payment shape (immutable ledger entry)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("heloc_id"), str) and data["heloc_id"]
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    # PRD §3.4: 'interest_component_cents is the smaller of the
    # payment's amount_cents and the HELOC's accrued_interest_cents'.
    assert isinstance(data.get("interest_component_cents"), int)
    assert data["interest_component_cents"] >= 0
    # PRD §3.4: 'principal_component_cents is the payment's amount_cents
    # minus the interest_component_cents'.
    assert isinstance(data.get("principal_component_cents"), int)
    assert data["principal_component_cents"] >= 0
    # Conservation: components sum exactly to amount.
    assert (
        data["interest_component_cents"]
        + data["principal_component_cents"]
        == data["amount_cents"]
    ), (
        "PRD §3.4 waterfall: interest_component + principal_component "
        "must equal amount_cents"
    )
    assert isinstance(data.get("posted_at"), str)
    assert is_iso8601_timestamp(data["posted_at"])


def assert_rate_reset(data: Dict[str, Any]) -> None:
    """PRD §3.5 RateReset shape (immutable ledger entry)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("heloc_id"), str) and data["heloc_id"]
    assert isinstance(data.get("prime_rate_bps"), int)
    assert 0 <= data["prime_rate_bps"] <= 3_000
    assert isinstance(data.get("requested_rate_bps"), int)
    assert isinstance(data.get("applied_rate_bps"), int)
    assert isinstance(data.get("reset_at"), str)
    assert is_iso8601_timestamp(data["reset_at"])


def assert_fee(data: Dict[str, Any]) -> None:
    """PRD §3.8/§3.9 Fee shape (immutable ledger entry)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("heloc_id"), str) and data["heloc_id"]
    assert data.get("fee_type") in _FEE_TYPES, (
        f"unexpected fee_type: {data.get('fee_type')!r}"
    )
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data.get("status") in _FEE_STATUSES, (
        f"unexpected fee status: {data.get('status')!r}"
    )
    # PRD §3.8: 'The WAIVED status is reserved exclusively for the
    # first-anniversary waiver path.'
    if data["status"] == "WAIVED":
        assert data["fee_type"] == "ANNUAL", (
            "PRD §3.8: WAIVED only on first ANNUAL fee"
        )
        assert data["amount_cents"] == 0, (
            "PRD §3.8: WAIVED fee carries amount_cents 0"
        )
    assert isinstance(data.get("assessed_at"), str)
    assert is_iso8601_timestamp(data["assessed_at"])


def assert_default_event(data: Dict[str, Any]) -> None:
    """PRD §3.6 DefaultEvent shape (immutable audit log)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("heloc_id"), str) and data["heloc_id"]
    assert data.get("trigger") in _DEFAULT_TRIGGERS, (
        f"unexpected trigger: {data.get('trigger')!r}"
    )
    # PRD §3.6: 'For a DefaultEvent produced by the delinquency sweep,
    # the source_event_id is null'.
    se = data.get("source_event_id", None)
    if data["trigger"] == "DELINQUENCY_90":
        assert se is None, (
            "PRD §3.6: DELINQUENCY_90 DefaultEvent.source_event_id "
            "is null"
        )
    else:
        assert isinstance(se, str) and se, (
            f"PRD §3.6: DefaultEvent.source_event_id required for "
            f"trigger {data['trigger']}; got {se!r}"
        )
    assert isinstance(data.get("recorded_at"), str)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_insurance_event(data: Dict[str, Any]) -> None:
    """PRD §3.6 InsuranceEvent shape (immutable audit log)."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("property_id"), str) and data["property_id"]
    assert data.get("event_type") in _INSURANCE_EVENT_TYPES, (
        f"unexpected event_type: {data.get('event_type')!r}"
    )
    assert isinstance(data.get("recorded_at"), str)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_senior_lien_default_event(data: Dict[str, Any]) -> None:
    """PRD §3.6 SeniorLienDefaultEvent shape."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("senior_lien_id"), str)
    assert data["senior_lien_id"]
    assert isinstance(data.get("recorded_at"), str)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_bankruptcy_event(data: Dict[str, Any]) -> None:
    """PRD §3.6 BankruptcyEvent shape."""
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert isinstance(data.get("borrower_id"), str) and data["borrower_id"]
    assert isinstance(data.get("recorded_at"), str)
    assert is_iso8601_timestamp(data["recorded_at"])


# ===========================================================================
# Domain invariants — must hold after any operation
# ===========================================================================
def assert_credit_conservation(heloc: Dict[str, Any]) -> None:
    """PRD §3.3: 'adds amount_cents to the HELOC's principal_balance_cents
    and subtracts amount_cents from its available_credit_cents'.

    Therefore at every observation point where status is not PENDING:
      available_credit_cents + principal_balance_cents == credit_limit_cents.

    PENDING accounts have available_credit_cents derived only on
    activation (PRD §3.2 side effect), so we skip the invariant in
    PENDING.
    """
    if heloc.get("status") == "PENDING":
        return
    avail = heloc["available_credit_cents"]
    principal = heloc["principal_balance_cents"]
    limit = heloc["credit_limit_cents"]
    assert avail + principal == limit, (
        f"credit conservation violated: available({avail}) + "
        f"principal({principal}) != credit_limit({limit})"
    )


def assert_version_incremented_by_one(
    after: Dict[str, Any],
    before: Dict[str, Any],
) -> None:
    """PRD §2.4: 'The version field is an integer that begins at 1 on
    creation and increments by exactly one with every mutation to the
    resource.'"""
    assert "version" in after and "version" in before
    assert after["version"] == before["version"] + 1, (
        f"version must increment by exactly 1; before="
        f"{before['version']}, after={after['version']}"
    )


__all__ = [
    "assert_borrower",
    "assert_property",
    "assert_senior_lien",
    "assert_heloc",
    "assert_heloc_get_response",
    "assert_draw",
    "assert_payment",
    "assert_rate_reset",
    "assert_fee",
    "assert_default_event",
    "assert_insurance_event",
    "assert_senior_lien_default_event",
    "assert_bankruptcy_event",
    "assert_credit_conservation",
    "assert_version_incremented_by_one",
]
