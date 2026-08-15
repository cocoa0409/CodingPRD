"""Entity assertions and domain invariant checkers.

assert_{entity}(data) checks the PRD-declared shape of each resource.
WithholdingEntry is an immutable ledger row and must NOT carry updated_at or
version (PRD: "Both `updated_at` and `version` are absent from withholding
entries.").
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AmountBasis,
    BNoticeStage,
    BNoticeStatus,
    EntityClassification,
    FederalStatus,
    FilingChannel,
    FormType,
    MatchResult,
    MergeRequestStatus,
    PaymentStatus,
    PaymentType,
    RecipientCopyStatus,
    RemittanceStatus,
    ReportableBox,
    RequiredChannel,
    SourceSystem,
    StateObligationStatus,
    TaxYearStatus,
    TinMatchStatus,
    TinType,
    TransmittalStatus,
    VendorStatus,
    WithholdingEntryStatus,
    WithholdingEntryType,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_tax_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tax_year"], int)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end_exclusive"])
    assert isinstance(data["efiling_threshold_count"], int)
    assert isinstance(data["nec_reportable_threshold_cents"], int)
    assert isinstance(data["misc_reportable_threshold_cents"], int)
    assert is_iso8601_timestamp(data["recipient_copy_deadline"])
    assert data["backup_withholding_rate_bps"] == 2400
    assert data["status"] in [s.value for s in TaxYearStatus]


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    if data.get("tin") is not None:
        assert isinstance(data["tin"], str) and len(data["tin"]) == 9
        assert data["tin"].isdigit()
        assert data["tin_type"] in [t.value for t in TinType]
    assert data["entity_classification"] in [c.value for c in EntityClassification]
    for f in ("address_line1", "address_city", "address_state", "address_postal"):
        assert isinstance(data[f], str) and data[f], f"{f} must be a non-empty string"
    assert isinstance(data["e_delivery_consent"], bool)
    assert data["tin_match_status"] in [s.value for s in TinMatchStatus]
    assert isinstance(data["mismatch_count_3yr"], int) and data["mismatch_count_3yr"] >= 0
    assert data["b_notice_stage"] in [s.value for s in BNoticeStage]
    assert isinstance(data["backup_withholding_flag"], bool)
    assert isinstance(data["withholding_balance_cents"], int)
    assert data["status"] in [s.value for s in VendorStatus]


def assert_w9_submission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["submitted_legal_name"], str)
    assert isinstance(data["submitted_tin"], str)
    assert len(data["submitted_tin"]) == 9 and data["submitted_tin"].isdigit()
    assert data["submitted_tin_type"] in [t.value for t in TinType]
    assert isinstance(data["signature_name"], str)
    assert data["match_result"] in [m.value for m in MatchResult]


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert data["source_system"] in [s.value for s in SourceSystem]
    assert data["payment_type"] in [p.value for p in PaymentType]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["payment_date"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["is_reportable"], bool)
    assert data["reportable_box"] in [b.value for b in ReportableBox]
    assert isinstance(data["withheld_cents"], int) and data["withheld_cents"] >= 0
    assert data["status"] in [s.value for s in PaymentStatus]


def assert_withholding_entry(data: dict):
    # Immutable ledger row: id + created_at only — updated_at/version MUST be absent.
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "withholding entries must not expose updated_at"
    assert "version" not in data, "withholding entries must not expose version"
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["payment_id"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["quarter"], int) and 1 <= data["quarter"] <= 4
    assert data["entry_type"] in [t.value for t in WithholdingEntryType]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [s.value for s in WithholdingEntryStatus]


def assert_remittance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["quarter"], int) and 1 <= data["quarter"] <= 4
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in [s.value for s in RemittanceStatus]


def assert_box_amounts(boxes: dict):
    for key in ("box_1_cents", "box_2_cents", "box_3_cents", "box_4_cents", "box_6_cents"):
        assert key in boxes, f"box_amounts missing {key}"
        assert isinstance(boxes[key], int), f"{key} must be integer cents"


def assert_tax_return(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["tax_year"], int)
    assert data["form_type"] in [f.value for f in FormType]
    assert_box_amounts(data["box_amounts"])
    assert_box_amounts(data["provisional_box_amounts"])
    assert data["amount_basis"] in [b.value for b in AmountBasis]
    assert isinstance(data["is_correction"], bool)
    assert data["federal_status"] in [s.value for s in FederalStatus]
    assert data["recipient_copy_status"] in [s.value for s in RecipientCopyStatus]


def assert_transmittal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tax_year"], int)
    assert data["form_type"] in [f.value for f in FormType]
    if data.get("filing_channel") is not None:
        assert data["filing_channel"] in [c.value for c in FilingChannel]
    if data.get("return_count") is not None:
        assert isinstance(data["return_count"], int)
    assert data["status"] in [s.value for s in TransmittalStatus]


def assert_state_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["participates_in_cfsf"], bool)
    assert isinstance(data["direct_reporting_threshold_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_state_obligation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["state_rule_id"])
    assert isinstance(data["tax_year"], int)
    assert data["required_channel"] in [c.value for c in RequiredChannel]
    assert isinstance(data["reportable_amount_cents"], int)
    assert data["status"] in [s.value for s in StateObligationStatus]


def assert_b_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["notice_year"], int)
    assert data["stage"] in [BNoticeStage.FIRST.value, BNoticeStage.SECOND.value]
    assert data["status"] in [s.value for s in BNoticeStatus]


def assert_merge_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["source_vendor_id"])
    assert is_valid_uuid(data["target_vendor_id"])
    assert isinstance(data["reason"], str)
    assert isinstance(data["requested_by_user_id"], str)
    assert data["status"] in [s.value for s in MergeRequestStatus]


def assert_withholding_ledger_conservation(vendor: dict, entries: list):
    """Money conservation invariant: the vendor's balance equals the signed sum
    of that vendor's UNREMITTED entries, and every REVERSED debit has a
    compensating REVERSAL entry of the opposite signed amount."""
    unremitted_signed = sum(
        e["amount_cents"] for e in entries if e["status"] == WithholdingEntryStatus.UNREMITTED.value
    )
    assert vendor["withholding_balance_cents"] == unremitted_signed, (
        f"balance {vendor['withholding_balance_cents']} != UNREMITTED signed sum {unremitted_signed}"
    )
    reversals = [e for e in entries if e["entry_type"] == WithholdingEntryType.REVERSAL.value]
    for rev in reversals:
        origin = [e for e in entries if e["id"] == rev["reverses_entry_id"]]
        assert origin, "REVERSAL must name an existing entry via reverses_entry_id"
        assert rev["amount_cents"] == -origin[0]["amount_cents"], (
            "REVERSAL amount must net its original to zero"
        )
        assert rev["status"] == WithholdingEntryStatus.REVERSED.value
        assert origin[0]["status"] == WithholdingEntryStatus.REVERSED.value
