"""Assertion helpers expressed in program vocabulary.

These wrap the framework validators so that a test reads as a statement about
the program rather than about HTTP.  Nothing here hides a failure: every helper
either asserts or returns the decoded payload for further inspection.
"""

import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .types import Cents, Json, Page

# ---------------------------------------------------------------------------
# Envelope-level helpers
# ---------------------------------------------------------------------------


def expect_created(response) -> Json:
    """A creation succeeded: HTTP 201 with a resource payload."""
    return validate_success(response, 201)


def expect_ok(response) -> Json:
    """A read or a state-advancing action succeeded: HTTP 200."""
    return validate_success(response, 200)


def expect_error(response, error_id: str) -> Json:
    """The call failed with exactly ``error_id`` and that identifier's status."""
    return validate_error(response, error_id)


def expect_one_of(response, error_ids: Iterable[str]) -> str:
    """The call failed with one of several admissible identifiers."""
    return validate_error_is_one_of(response, list(error_ids))


def expect_page(response) -> Page:
    """A list read succeeded; returns ``(rows, meta)``."""
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------


def assert_resource_envelope(resource: Json) -> None:
    """Every resource carries an id, both timestamps and a version."""
    assert is_valid_uuid(resource["id"]), "id must be a UUID: {0}".format(resource["id"])
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1


def assert_version(resource: Json, expected: int) -> None:
    assert resource["version"] == expected, "expected version {0}, got {1}".format(
        expected, resource["version"]
    )


_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$"
)


def _as_instant(value: Any):
    """Parse an ISO 8601 UTC instant, or return None when the value is not one.

    The PRD pins the *instants* it cares about (``a signature on Wednesday
    2026-08-12 expires at 2026-08-18T00:00:00Z``) while fixing an explicit
    fractional-second rendering only for ``created_at`` and ``updated_at``.  A
    timestamp assertion is therefore a statement about the moment, not about how
    many fractional digits the serializer prints.
    """
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _values_agree(want: Any, got: Any) -> bool:
    if got == want:
        return True
    want_instant = _as_instant(want)
    if want_instant is None:
        return False
    got_instant = _as_instant(got)
    return got_instant is not None and got_instant == want_instant


def assert_fields(resource: Json, **expected: Any) -> None:
    """Assert several field values at once, reporting each mismatch by name."""
    mismatches = []
    for field, want in expected.items():
        got = resource.get(field, "<absent>")
        if not _values_agree(want, got):
            mismatches.append("{0}: expected {1!r}, got {2!r}".format(field, want, got))
    assert not mismatches, "; ".join(mismatches)


def assert_absent_or_none(resource: Json, *fields: str) -> None:
    for field in fields:
        assert resource.get(field) is None, "{0} should be null, got {1!r}".format(
            field, resource.get(field)
        )


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------


def round_half_up(value: Decimal) -> int:
    """The program's single rounding rule: half away from zero, to a whole unit."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def annuity_factor(rate_bps: int, years: int) -> Decimal:
    """(1 - (1+r)**-n) / r, quantized to ten decimal places before any use."""
    rate = Decimal(rate_bps) / Decimal(10000)
    raw = (Decimal(1) - (Decimal(1) + rate) ** (-years)) / rate
    return raw.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def present_value_of_savings(annual_savings_cents: int, useful_life_years: int) -> Cents:
    return round_half_up(
        Decimal(annual_savings_cents) * annuity_factor(300, useful_life_years)
    )


def sir_bps(present_value_cents: int, installed_cost_cents: int) -> int:
    return round_half_up(
        Decimal(present_value_cents) * Decimal(10000) / Decimal(installed_cost_cents)
    )


def admin_fee_cents(principal_cents: int) -> Cents:
    return round_half_up(Decimal(principal_cents) * Decimal(250) / Decimal(10000))


def assert_fee_decomposition(agreement: Json, principal_cents: int) -> None:
    """The financed amount is exactly principal + admin fee + recording fee."""
    admin = admin_fee_cents(principal_cents)
    assert_fields(
        agreement,
        principal_cents=principal_cents,
        admin_fee_cents=admin,
        county_recording_fee_cents=9500,
        financed_amount_cents=principal_cents + admin + 9500,
        contractor_payable_cents=principal_cents,
    )
    assert (
        agreement["financed_amount_cents"]
        == agreement["principal_cents"]
        + agreement["admin_fee_cents"]
        + agreement["county_recording_fee_cents"]
    )


# ---------------------------------------------------------------------------
# Conserved-quantity helpers
# ---------------------------------------------------------------------------


def assert_contractor_ledger(
    contractor: Json, gross_cents: int, clawed_back_cents: int
) -> None:
    """The two-sided contractor ledger always reconciles to net."""
    assert_fields(
        contractor,
        gross_disbursed_cents=gross_cents,
        clawed_back_total_cents=clawed_back_cents,
        net_disbursed_cents=gross_cents - clawed_back_cents,
    )
    assert contractor["net_disbursed_cents"] >= 0, "net disbursed may never go negative"


def assert_parcel_exposure(
    parcel: Json, recorded_cents: int, committed_cents: int
) -> None:
    assert_fields(
        parcel,
        recorded_pace_principal_cents=recorded_cents,
        committed_pace_principal_cents=committed_cents,
    )
    assert parcel["committed_pace_principal_cents"] >= parcel[
        "recorded_pace_principal_cents"
    ], "committed exposure can never fall below the recorded component"


def assert_schedule_conserves_principal(
    installments: List[Json], original_principal_cents: int
) -> None:
    """The principal legs of the schedule sum back to the financed amount."""
    total = sum(row["principal_cents"] for row in installments)
    assert total == original_principal_cents, (
        "principal legs sum to {0}, expected {1}".format(total, original_principal_cents)
    )


def assert_installment_row(
    row: Json,
    sequence: int,
    tax_year: int,
    principal_cents: int,
    interest_cents: int,
    servicing_fee_cents: int = 4000,
) -> None:
    assert_fields(
        row,
        sequence=sequence,
        tax_year=tax_year,
        principal_cents=principal_cents,
        interest_cents=interest_cents,
        servicing_fee_cents=servicing_fee_cents,
        total_due_cents=principal_cents + interest_cents + servicing_fee_cents,
        due_on="{0}-12-10".format(tax_year),
    )


def find_installment(installments: List[Json], tax_year: int) -> Json:
    for row in installments:
        if row["tax_year"] == tax_year:
            return row
    raise AssertionError("no installment for tax year {0}".format(tax_year))


# ---------------------------------------------------------------------------
# Payoff helpers
# ---------------------------------------------------------------------------


def assert_payoff_composition(
    transfer: Json,
    principal_cents: int,
    accrued_interest_cents: int,
    premium_bps: int,
) -> None:
    """Base is principal + interest + admin fee; the premium keys on that base."""
    base = principal_cents + accrued_interest_cents + 7500
    premium = round_half_up(Decimal(base) * Decimal(premium_bps) / Decimal(10000))
    assert_fields(
        transfer,
        payoff_principal_cents=principal_cents,
        accrued_interest_cents=accrued_interest_cents,
        payoff_admin_fee_cents=7500,
        base_payoff_cents=base,
        prepayment_premium_bps=premium_bps,
        prepayment_premium_cents=premium,
        payoff_total_cents=base + premium,
    )


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def ids_of(rows: List[Json]) -> List[str]:
    return [row["id"] for row in rows]


def assert_page_meta(meta: Json, total_count: int, limit: int = 10, offset: int = 0) -> None:
    assert_fields(
        meta,
        total_count=total_count,
        limit=limit,
        offset=offset,
        has_more=offset + limit < total_count,
    )


def assert_total_count(meta: Json, total_count: int) -> None:
    assert meta["total_count"] == total_count, "expected total_count {0}, got {1}".format(
        total_count, meta["total_count"]
    )
