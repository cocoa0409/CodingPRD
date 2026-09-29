"""Domain assertion helpers.

Everything asserted here is stated by the PRD: the six-bucket commitment
identity of §2.5, the append-only shape of §2.7, the error envelope of §2.2 and
the derived-field definitions of §3.2, §3.5, §3.6 and §3.8.
"""

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    API_REQUEST_ID_PREFIX,
    COMMITMENT_BUCKETS,
    ERROR_DATA_KEYS,
    ERROR_META_KEYS,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------- common shape
def assert_system_fields(record: Json, expected_version: Optional[int] = None) -> None:
    """PRD §2.7: `id` is a server-minted UUID with no type prefix; timestamps
    are ISO 8601 with three fractional digits; `version` starts at 1."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']!r}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"created_at is not ISO 8601: {record['created_at']!r}"
    assert is_iso8601_timestamp(
        record["updated_at"]
    ), f"updated_at is not ISO 8601: {record['updated_at']!r}"
    assert record["updated_at"] >= record["created_at"], (
        "updated_at may never precede created_at"
    )
    assert isinstance(record["version"], int) and record["version"] >= 1
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_append_only_record(record: Json) -> None:
    """PRD §2.7: ledger entries, interest accrual periods and exit milestones
    carry only `id` and `created_at` — `updated_at` and `version` are absent."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, (
        "an append-only journal row must not expose updated_at"
    )
    assert "version" not in record, (
        "an append-only journal row must not expose version"
    )


def assert_error_envelope(body: Json) -> None:
    """PRD §2.2: an error carries `error_id` and `message` and nothing else, and
    the `meta` object holds only `api_request_id` and `api_request_timestamp`."""
    assert body["response_type"] == "error", (
        f"response_type must be the literal 'error', got {body['response_type']!r}"
    )
    assert set(body["meta"].keys()) == ERROR_META_KEYS, (
        f"error meta carries only {sorted(ERROR_META_KEYS)}, got {sorted(body['meta'])}"
    )
    assert body["meta"]["api_request_id"].startswith(API_REQUEST_ID_PREFIX)
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert set(body["data"].keys()) == ERROR_DATA_KEYS, (
        f"error data carries only {sorted(ERROR_DATA_KEYS)}, got {sorted(body['data'])}"
    )
    assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        f"the error envelope has exactly three top-level keys, got {sorted(body)}"
    )


# ---------------------------------------------------------------- money identity
def assert_commitment_conservation(loan: Json) -> None:
    """PRD §2.5: `commitment_balance_check_cents` reports `committed_amount_cents`
    less the sum of the six buckets and must read exactly zero after every write
    touching any loan money bucket."""
    bucket_total = sum(loan[name] for name in COMMITMENT_BUCKETS)
    assert loan["commitment_balance_check_cents"] == 0, (
        "commitment_balance_check_cents must read exactly zero; buckets sum to "
        f"{bucket_total} against committed {loan['committed_amount_cents']}"
    )
    assert loan["committed_amount_cents"] - bucket_total == 0, (
        "committed_amount_cents less the six buckets must be zero: "
        f"{loan['committed_amount_cents']} vs {bucket_total}"
    )


def assert_available_rehab_pool(loan: Json) -> None:
    """PRD §2.5: `available_rehab_pool_cents` reports `undisbursed_holdback_cents`
    plus `reserved_release_cents`."""
    assert loan["available_rehab_pool_cents"] == (
        loan["undisbursed_holdback_cents"] + loan["reserved_release_cents"]
    ), "available_rehab_pool_cents is not undisbursed plus reserved"


def assert_loan_buckets(
    loan: Json,
    *,
    committed_amount_cents: Optional[int] = None,
    funded_principal_cents: Optional[int] = None,
    repaid_principal_cents: Optional[int] = None,
    reserved_release_cents: Optional[int] = None,
    undisbursed_holdback_cents: Optional[int] = None,
    interest_reserve_balance_cents: Optional[int] = None,
    decommitted_holdback_cents: Optional[int] = None,
) -> None:
    expected = {
        "committed_amount_cents": committed_amount_cents,
        "funded_principal_cents": funded_principal_cents,
        "repaid_principal_cents": repaid_principal_cents,
        "reserved_release_cents": reserved_release_cents,
        "undisbursed_holdback_cents": undisbursed_holdback_cents,
        "interest_reserve_balance_cents": interest_reserve_balance_cents,
        "decommitted_holdback_cents": decommitted_holdback_cents,
    }
    for field, value in expected.items():
        if value is not None:
            assert loan[field] == value, (
                f"{field} expected {value}, got {loan[field]}"
            )
    assert_commitment_conservation(loan)
    assert_available_rehab_pool(loan)


def assert_loan_axes(
    loan: Json,
    *,
    payment_status: Optional[str] = None,
    construction_status: Optional[str] = None,
    exit_status: Optional[str] = None,
) -> None:
    """PRD §3.4: a loan carries three independent state axes."""
    if payment_status is not None:
        assert loan["payment_status"] == payment_status, (
            f"payment_status expected {payment_status}, got {loan['payment_status']}"
        )
    if construction_status is not None:
        assert loan["construction_status"] == construction_status, (
            "construction_status expected "
            f"{construction_status}, got {loan['construction_status']}"
        )
    if exit_status is not None:
        assert loan["exit_status"] == exit_status, (
            f"exit_status expected {exit_status}, got {loan['exit_status']}"
        )


# ---------------------------------------------------------------- entity helpers
def assert_borrower_score(
    borrower: Json,
    *,
    intake_experience_score: Optional[float] = None,
    recertified_experience_score: Optional[float] = None,
    effective_experience_score: Optional[float] = None,
    experience_tier: Optional[str] = None,
) -> None:
    """PRD §3.1: the clamped total is rounded half up to two decimal places and
    `experience_tier` is always banded from `effective_experience_score`."""
    if intake_experience_score is not None:
        assert borrower["intake_experience_score"] == pytest.approx(
            intake_experience_score, abs=0.005
        ), (
            "intake_experience_score expected "
            f"{intake_experience_score}, got {borrower['intake_experience_score']}"
        )
    if recertified_experience_score is not None:
        assert borrower["recertified_experience_score"] == pytest.approx(
            recertified_experience_score, abs=0.005
        ), (
            "recertified_experience_score expected "
            f"{recertified_experience_score}, "
            f"got {borrower['recertified_experience_score']}"
        )
    if effective_experience_score is not None:
        assert borrower["effective_experience_score"] == pytest.approx(
            effective_experience_score, abs=0.005
        ), (
            "effective_experience_score expected "
            f"{effective_experience_score}, "
            f"got {borrower['effective_experience_score']}"
        )
    if experience_tier is not None:
        assert borrower["experience_tier"] == experience_tier, (
            f"experience_tier expected {experience_tier}, "
            f"got {borrower['experience_tier']}"
        )


def assert_contractor_payability(
    contractor: Json, *, license_status: str, payable: bool
) -> None:
    """PRD §3.2: `payable` is true only when `license_status` is `ACTIVE` and
    `w9_on_file` is true."""
    assert contractor["license_status"] == license_status, (
        f"license_status expected {license_status}, got {contractor['license_status']}"
    )
    assert contractor["payable"] is payable, (
        f"payable expected {payable}, got {contractor['payable']}"
    )
    assert contractor["payable"] == (
        contractor["license_status"] == "ACTIVE" and contractor["w9_on_file"] is True
    ), "payable must be the conjunction of an ACTIVE licence and a W-9 on file"


def assert_contractor_waiver_figures(
    contractor: Json,
    *,
    collected_waiver_coverage_cents: Optional[int] = None,
    released_to_contractor_cents: Optional[int] = None,
    open_waiver_headroom_cents: Optional[int] = None,
) -> None:
    """PRD §3.6: headroom is coverage less released, and it may go negative."""
    if collected_waiver_coverage_cents is not None:
        assert (
            contractor["collected_waiver_coverage_cents"]
            == collected_waiver_coverage_cents
        ), (
            "collected_waiver_coverage_cents expected "
            f"{collected_waiver_coverage_cents}, "
            f"got {contractor['collected_waiver_coverage_cents']}"
        )
    if released_to_contractor_cents is not None:
        assert (
            contractor["released_to_contractor_cents"] == released_to_contractor_cents
        ), (
            "released_to_contractor_cents expected "
            f"{released_to_contractor_cents}, "
            f"got {contractor['released_to_contractor_cents']}"
        )
    if open_waiver_headroom_cents is not None:
        assert (
            contractor["open_waiver_headroom_cents"] == open_waiver_headroom_cents
        ), (
            "open_waiver_headroom_cents expected "
            f"{open_waiver_headroom_cents}, "
            f"got {contractor['open_waiver_headroom_cents']}"
        )
    assert contractor["open_waiver_headroom_cents"] == (
        contractor["collected_waiver_coverage_cents"]
        - contractor["released_to_contractor_cents"]
    ), "open_waiver_headroom_cents must be coverage less released"


def assert_scope_line_release(
    line: Json,
    *,
    released_cents: int,
    released_percent: float,
    status: Optional[str] = None,
) -> None:
    """PRD §3.6: `released_percent` is `released_cents` divided by
    `approved_cost_cents` carried to four decimal places."""
    assert line["released_cents"] == released_cents, (
        f"released_cents expected {released_cents}, got {line['released_cents']}"
    )
    assert line["released_percent"] == pytest.approx(released_percent, abs=5e-5), (
        f"released_percent expected {released_percent}, got {line['released_percent']}"
    )
    if status is not None:
        assert line["status"] == status, (
            f"scope line status expected {status}, got {line['status']}"
        )


def assert_sizing_fields(
    application: Json,
    *,
    cap_purchase_advance_cents: Optional[int] = None,
    cap_ltc_cents: Optional[int] = None,
    cap_ltarv_cents: Optional[int] = None,
    max_total_loan_cents: Optional[int] = None,
    sized_initial_funding_cents: Optional[int] = None,
    sized_interest_reserve_cents: Optional[int] = None,
    sized_committed_amount_cents: Optional[int] = None,
    sizing_stale: Optional[bool] = None,
) -> None:
    expected = {
        "cap_purchase_advance_cents": cap_purchase_advance_cents,
        "cap_ltc_cents": cap_ltc_cents,
        "cap_ltarv_cents": cap_ltarv_cents,
        "max_total_loan_cents": max_total_loan_cents,
        "sized_initial_funding_cents": sized_initial_funding_cents,
        "sized_interest_reserve_cents": sized_interest_reserve_cents,
        "sized_committed_amount_cents": sized_committed_amount_cents,
    }
    for field, value in expected.items():
        if value is not None:
            assert application[field] == value, (
                f"{field} expected {value}, got {application[field]}"
            )
    if sizing_stale is not None:
        assert application["sizing_stale"] is sizing_stale, (
            f"sizing_stale expected {sizing_stale}, got {application['sizing_stale']}"
        )


def assert_allocation_fields(
    application: Json,
    *,
    approved_loan_amount_cents: Optional[int] = None,
    alloc_initial_funding_cents: Optional[int] = None,
    alloc_interest_reserve_cents: Optional[int] = None,
    alloc_rehab_holdback_cents: Optional[int] = None,
) -> None:
    """PRD §3.4: the decision pass lands the committed total on the approved
    amount exactly, with no slack."""
    expected = {
        "approved_loan_amount_cents": approved_loan_amount_cents,
        "alloc_initial_funding_cents": alloc_initial_funding_cents,
        "alloc_interest_reserve_cents": alloc_interest_reserve_cents,
        "alloc_rehab_holdback_cents": alloc_rehab_holdback_cents,
    }
    for field, value in expected.items():
        if value is not None:
            assert application[field] == value, (
                f"{field} expected {value}, got {application[field]}"
            )
    if approved_loan_amount_cents is not None:
        parts = (
            application["alloc_initial_funding_cents"]
            + application["alloc_interest_reserve_cents"]
            + application["alloc_rehab_holdback_cents"]
        )
        assert parts == approved_loan_amount_cents, (
            "the three allocation buckets must sum to the approved amount exactly: "
            f"{parts} vs {approved_loan_amount_cents}"
        )


def assert_accrual_period(
    period: Json,
    *,
    day_count: Optional[int] = None,
    note_rate_days: Optional[int] = None,
    default_rate_days: Optional[int] = None,
    principal_snapshot_cents: Optional[int] = None,
    note_rate_interest_cents: Optional[int] = None,
    default_rate_interest_cents: Optional[int] = None,
    interest_accrued_cents: Optional[int] = None,
    swept_from_reserve_cents: Optional[int] = None,
    unpaid_added_cents: Optional[int] = None,
) -> None:
    """PRD §3.7: `interest_accrued_cents` is the sum of the two independently
    rounded rate components, and `day_count` splits into the two rate legs."""
    expected = {
        "day_count": day_count,
        "note_rate_days": note_rate_days,
        "default_rate_days": default_rate_days,
        "principal_snapshot_cents": principal_snapshot_cents,
        "note_rate_interest_cents": note_rate_interest_cents,
        "default_rate_interest_cents": default_rate_interest_cents,
        "interest_accrued_cents": interest_accrued_cents,
        "swept_from_reserve_cents": swept_from_reserve_cents,
        "unpaid_added_cents": unpaid_added_cents,
    }
    for field, value in expected.items():
        if value is not None:
            assert period[field] == value, (
                f"{field} expected {value}, got {period[field]}"
            )
    assert (
        period["note_rate_interest_cents"] + period["default_rate_interest_cents"]
        == period["interest_accrued_cents"]
    ), "interest_accrued_cents must be the sum of the two rate components"
    assert (
        period["note_rate_days"] + period["default_rate_days"] == period["day_count"]
    ), "note_rate_days plus default_rate_days must equal day_count"
    assert_append_only_record(period)


def assert_ledger_types(entries: Iterable[Json], expected: List[str]) -> None:
    """PRD §2.5 enumerates the ten ledger `entry_type` values; §2.3 orders list
    results by `created_at` ascending."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == expected, f"ledger entry types expected {expected}, got {actual}"


def assert_exit_monitoring(
    loan: Json, *, days_on_market: int, exit_watch_flag: bool
) -> None:
    """PRD §3.8: `exit_watch_flag` reads true when `days_on_market` is strictly
    greater than 90 days and no qualifying `PRICE_REDUCED` milestone exists."""
    assert loan["days_on_market"] == days_on_market, (
        f"days_on_market expected {days_on_market}, got {loan['days_on_market']}"
    )
    assert loan["exit_watch_flag"] is exit_watch_flag, (
        f"exit_watch_flag expected {exit_watch_flag}, got {loan['exit_watch_flag']}"
    )


def assert_unchanged(before: Json, after: Json, *fields: str) -> None:
    for field in fields:
        assert before[field] == after[field], (
            f"{field} should not have changed: was {before[field]!r}, "
            f"now {after[field]!r}"
        )


def assert_same_record(first: Json, second: Json) -> None:
    """Two reads of an unmutated record must be identical field for field."""
    assert first == second, (
        "a repeated read of an unmutated record must return the identical row"
    )
