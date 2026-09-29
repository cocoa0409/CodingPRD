"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` helper checks only what the PRD pins for that resource:
the shape of the system-managed properties and the enumerations the resource's
own fields are drawn from.  The append-only ledger rows are additionally checked
for the *absence* of ``updated_at`` and ``version``.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DOI_PREFIX,
    PERSISTENT_IDENTIFIER_PREFIX,
    SCORE_MAX,
    SCORE_MIN,
)


# --------------------------------------------------------------------------- #
# shared shape checks
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict) -> None:
    """id is a UUID with no type prefix; created_at / updated_at are ISO 8601 UTC
    timestamps with three fractional digits; version starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """An append-only ledger row carries only id and created_at of the system
    properties — updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data or data["updated_at"] is None, (
        "updated_at must be absent from an append-only row"
    )
    assert "version" not in data or data["version"] is None, (
        "version must be absent from an append-only row"
    )


def assert_timestamp_has_three_fractional_digits(value: str) -> None:
    assert isinstance(value, str) and "." in value, (
        f"expected a timestamp with fractional digits, got {value!r}"
    )
    fraction = value.split(".")[1]
    digits = "".join(ch for ch in fraction if ch.isdigit())
    assert len(digits) == 3, f"expected three fractional digits in {value!r}"


# --------------------------------------------------------------------------- #
# per-entity assertions
# --------------------------------------------------------------------------- #
def assert_publisher(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert isinstance(data["publisher_code"], str) and data["publisher_code"].isupper()
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["screening_status"] in [
        "UNSCREENED",
        "CLEARED",
        "WATCHLIST",
        "PREDATORY_FLAGGED",
        "BLOCKED",
    ], f"unexpected screening_status {data['screening_status']!r}"
    assert isinstance(data["active_agreement_count"], int)
    if data.get("predatory_score") is not None:
        assert SCORE_MIN <= data["predatory_score"] <= SCORE_MAX


def assert_journal(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["publisher_id"])
    assert isinstance(data["issn"], str)
    assert data["oa_model"] in ["FULLY_OA", "HYBRID", "SUBSCRIPTION"]
    assert isinstance(data["list_apc_cents"], int) and data["list_apc_cents"] >= 0
    assert 0 <= data["required_embargo_months"] <= 48


def assert_transformative_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["publisher_id"])
    assert data["status"] in ["DRAFT", "ACTIVE", "EXHAUSTED", "EXPIRED"]
    assert isinstance(data["article_quota"], int) and data["article_quota"] >= 1
    assert isinstance(data["articles_used"], int) and data["articles_used"] >= 0
    assert 0 <= data["discount_pct"] <= 0.95
    assert isinstance(data["covered_oa_models"], list) and data["covered_oa_models"]


def assert_agreement_coverage(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["journal_id"])
    assert data["coverage_type"] in ["FULL_APC", "CAPPED_APC", "READ_ONLY"]
    assert data["covered_until"] >= data["covered_from"]
    if data["coverage_type"] == "CAPPED_APC":
        assert data["capped_amount_cents"] > 0
    else:
        assert data.get("capped_amount_cents") is None


def assert_author(data: dict) -> None:
    assert_common_fields(data)
    assert data["affiliation_status"] in [
        "ELIGIBLE_FACULTY",
        "ELIGIBLE_POSTDOC",
        "ELIGIBLE_GRAD",
        "VISITING",
        "EMERITUS",
        "UNAFFILIATED",
    ]
    assert isinstance(data["annual_cap_cents"], int) and data["annual_cap_cents"] >= 0
    assert isinstance(data["apc_committed_cents"], int)
    assert isinstance(data["apc_disbursed_cents"], int)
    assert isinstance(data["linked_output_count"], int)


def assert_funder(data: dict) -> None:
    assert_common_fields(data)
    assert data["mandate_type"] in ["NONE", "GREEN_OA", "GOLD_OA", "IMMEDIATE_CC_BY"]
    assert 0 <= data["max_embargo_months"] <= 24
    assert 1 <= data["deposit_deadline_days"] <= 365
    assert data["license_required"] in ["ANY", "CC_BY", "CC_BY_OR_NC"]
    assert isinstance(data["apc_allowable"], bool)


def assert_grant(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["funder_id"])
    assert is_valid_uuid(data["pi_author_id"])
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert data["mandate_status"] in ["IN_PROGRESS", "SATISFIED", "BREACHED"]
    assert isinstance(data["output_count"], int)
    assert isinstance(data["compliant_output_count"], int)


def assert_article(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["journal_id"])
    assert is_valid_uuid(data["corresponding_author_id"])
    assert data["funding_status"] in [
        "DRAFT",
        "ELIGIBILITY_CHECKED",
        "FUNDING_REQUESTED",
        "FUNDED",
        "PARTIALLY_FUNDED",
        "SELF_FUNDED",
        "DECLINED",
    ]
    assert data["compliance_status"] in [
        "PENDING_DEPOSIT",
        "EMBARGOED",
        "COMPLIANT",
        "NON_COMPLIANT",
        "EXEMPT",
    ]
    assert isinstance(data["determination_count"], int)
    assert isinstance(data["latest_deposit_ordinal"], int)


def assert_eligibility_determination(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["article_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["basis"] in ["PROVISIONAL", "FINAL"]
    assert data["route"] in ["TA_FULL", "TA_CAPPED", "FUND_APC", "AUTHOR_PAYS"]
    assert data["determination_reason"] in [
        "TA_FULL_COVERAGE",
        "TA_CAPPED_COVERAGE",
        "NO_COVERAGE_FUND_ELIGIBLE",
        "NO_COVERAGE_AUTHOR_PAYS",
        "PREDATORY_FLAGGED_NO_INSTITUTIONAL_FUNDS",
    ]
    assert isinstance(data["list_base_cents"], int)
    assert isinstance(data["covered_amount_cents"], int)
    assert isinstance(data["author_share_cents"], int)
    assert isinstance(data["eligible_request_cents"], int)


def assert_apc_fund(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "FROZEN"]
    assert data["total_budget_cents"] > 0
    assert data["priority_rank"] >= 1
    assert data["per_article_cap_cents"] > 0
    assert isinstance(data["eligible_affiliation_statuses"], list)
    assert data["eligible_affiliation_statuses"]
    assert_fund_ledger_consistent(data)


def assert_fund_request(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["article_id"])
    assert data["status"] in [
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN",
        "PAID",
    ]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["requested_cents"] > 0
    assert isinstance(data["fully_funded"], bool)


def assert_fund_allocation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["fund_request_id"])
    assert is_valid_uuid(data["fund_id"])
    assert data["status"] in ["ENCUMBERED", "DISBURSED", "RELEASED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_publisher_invoice(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["publisher_id"])
    assert is_valid_uuid(data["article_id"])
    assert data["currency"] == "USD"
    assert data["status"] in [
        "RECEIVED",
        "VALIDATED",
        "DISPUTED",
        "APPROVED_FOR_PAYMENT",
        "PAID",
    ]
    assert data["validation_outcome"] in [
        "MATCH",
        "WITHIN_TOLERANCE",
        "AMOUNT_VARIANCE",
        "DISCOUNT_SHORTFALL",
    ]
    assert 0 <= data["claimed_discount_pct"] <= 0.95
    assert 0 <= data["vat_pct"] <= 0.30
    assert_invoice_pricing_consistent(data)


def assert_repository_deposit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["article_id"])
    assert data["version_label"] in ["ACCEPTED_MANUSCRIPT", "VERSION_OF_RECORD"]
    assert data["license"] in [
        "CC_BY",
        "CC_BY_NC",
        "CC_BY_NC_ND",
        "ALL_RIGHTS_RESERVED",
    ]
    assert data["status"] in ["DRAFT", "SUBMITTED", "INGESTED", "SUPERSEDED"]
    assert isinstance(data["version_ordinal"], int) and data["version_ordinal"] >= 1
    assert isinstance(data["returned_count"], int) and data["returned_count"] >= 0
    assert_file_checksum_format(data["file_checksum"])


# --------------------------------------------------------------------------- #
# domain invariants
# --------------------------------------------------------------------------- #
def assert_fund_ledger_consistent(fund: dict) -> None:
    """available_cents is total_budget_cents less committed_cents less spent_cents."""
    expected = fund["total_budget_cents"] - fund["committed_cents"] - fund["spent_cents"]
    assert fund["available_cents"] == expected, (
        f"available_cents should be {expected}, got {fund['available_cents']} "
        f"(budget {fund['total_budget_cents']}, committed {fund['committed_cents']}, "
        f"spent {fund['spent_cents']})"
    )


def assert_invoice_pricing_consistent(invoice: dict) -> None:
    """expected_amount_cents is net_cents plus vat_cents with no further rounding,
    and variance_cents is invoice_amount_cents less expected_amount_cents."""
    assert invoice["expected_amount_cents"] == invoice["net_cents"] + invoice["vat_cents"], (
        f"expected_amount_cents should be net + vat = "
        f"{invoice['net_cents'] + invoice['vat_cents']}, got {invoice['expected_amount_cents']}"
    )
    assert (
        invoice["variance_cents"]
        == invoice["invoice_amount_cents"] - invoice["expected_amount_cents"]
    ), (
        f"variance_cents should be {invoice['invoice_amount_cents'] - invoice['expected_amount_cents']}, "
        f"got {invoice['variance_cents']}"
    )


def assert_file_checksum_format(checksum: str) -> None:
    assert isinstance(checksum, str) and len(checksum) == 64, (
        f"file_checksum must be 64 characters, got {checksum!r}"
    )
    assert all(ch in "0123456789abcdef" for ch in checksum), (
        f"file_checksum must be lowercase hexadecimal, got {checksum!r}"
    )


def assert_persistent_identifier_format(pid: str) -> None:
    assert isinstance(pid, str) and pid.startswith(PERSISTENT_IDENTIFIER_PREFIX), (
        f"persistent_identifier must start with {PERSISTENT_IDENTIFIER_PREFIX!r}, got {pid!r}"
    )
    counter = pid[len(PERSISTENT_IDENTIFIER_PREFIX) :]
    assert len(counter) == 6 and counter.isdigit(), (
        f"persistent_identifier counter must be six digits, got {counter!r}"
    )


def assert_doi_format(doi: str, publisher_code: str, sequence: Optional[int] = None) -> None:
    assert isinstance(doi, str) and doi.startswith(DOI_PREFIX), (
        f"doi must start with {DOI_PREFIX!r}, got {doi!r}"
    )
    tail = doi[len(DOI_PREFIX) :]
    assert tail.startswith(publisher_code + "."), (
        f"doi must carry the publisher code {publisher_code!r}, got {doi!r}"
    )
    if sequence is not None:
        assert tail == f"{publisher_code}.{sequence}", (
            f"doi should be {DOI_PREFIX}{publisher_code}.{sequence}, got {doi!r}"
        )


def assert_allocation_sequence(rows: List[dict]) -> None:
    """Allocation lines are listed in waterfall order with a one-based
    sequence_index."""
    for position, row in enumerate(rows, start=1):
        assert row["sequence_index"] == position, (
            f"allocation {position} should carry sequence_index {position}, "
            f"got {row['sequence_index']}"
        )


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int,
                           has_more: bool) -> None:
    assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset should be {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count should be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more should be {has_more}, got {meta['has_more']}"
    )
