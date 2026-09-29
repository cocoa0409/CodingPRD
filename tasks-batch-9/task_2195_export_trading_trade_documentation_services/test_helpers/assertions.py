"""Per-entity shape assertions and domain invariant checkers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Json = Dict[str, Any]

MONEY_TOL = 0.01
WEIGHT_TOL = 0.001


def approx_money(expected: float):
    return pytest.approx(expected, abs=MONEY_TOL)


def approx_weight(expected: float):
    return pytest.approx(expected, abs=WEIGHT_TOL)


def assert_common_fields(row: Json) -> None:
    """id, created_at, updated_at and version are present on nearly every entity."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1


def assert_envelope_meta(body: Json) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_buyer(row: Json) -> None:
    assert_common_fields(row)
    assert isinstance(row["legal_name"], str) and row["legal_name"]
    assert len(row["country_code"]) == 2 and row["country_code"].isupper()
    assert row["credit_rating"] in {"AAA", "AA", "A", "BBB", "BB", "B", "CCC"}
    assert row["sanctions_tier"] in {"NONE", "WATCHLIST", "EMBARGOED"}
    assert isinstance(row["restricted_party_flag"], bool)
    assert isinstance(row["open_order_count"], int)
    assert row["aggregate_exposure_usd"] is not None


def assert_export_order(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["buyer_id"])
    assert row["prepared_by_user_id"]
    assert row["incoterm"] in {"EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"}
    assert row["destination_zone"] in {"ZONE_1", "ZONE_2", "ZONE_3"}
    assert row["fulfillment_status"] in {
        "DRAFT",
        "COMPLIANCE_PENDING",
        "COMPLIANCE_CLEARED",
        "COMPLIANCE_BLOCKED",
        "BOOKED",
        "SHIPPED",
        "SHORT_SHIPPED",
        "CLOSED",
        "CANCELLED",
    }
    assert row["settlement_status"] in {
        "UNSECURED",
        "LC_ACCEPTED",
        "DOCS_PRESENTED",
        "PAID",
        "DISHONORED",
        "CLAIM_FILED",
        "INDEMNIFIED",
        "WRITTEN_OFF",
    }
    for money_field in (
        "ordered_goods_value_usd",
        "shipped_goods_value_usd",
        "provisional_seller_cost_usd",
        "provisional_buyer_cost_usd",
        "final_seller_cost_usd",
        "final_buyer_cost_usd",
        "cost_allocation_variance_usd",
        "outstanding_receivable_usd",
        "licensed_value_allocated_usd",
        "insured_exposure_usd",
        "short_shipped_value_usd",
    ):
        assert money_field in row, f"missing computed money field {money_field}"


def assert_shipment_line(row: Json) -> None:
    assert_common_fields(row)
    assert row["line_no"] >= 1
    assert row["uom"] in {"EA", "KG", "LTR", "MTR", "SET"}
    assert row["quantity"] > 0
    assert row["unit_price_usd"] > 0
    assert row["gross_weight_kg"] >= row["net_weight_kg"]
    assert row["package_count"] >= 1
    assert len(row["hs_code"]) in (6, 10)


def assert_letter_of_credit(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {
        "RECEIVED",
        "UNDER_REVIEW",
        "AMENDMENT_REQUESTED",
        "ACCEPTED",
        "REJECTED",
        "EXPIRED",
        "UTILISED",
    }
    assert row["availability"] in {"SIGHT", "USANCE"}
    assert row["amount_usd"] > 0
    assert "COMMERCIAL_INVOICE" in row["required_document_types"]
    assert row["amendment_round"] >= 0
    assert len(row["issuing_bank_swift"]) in (8, 11)


def assert_terms_review(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"DRAFTING", "SUBMITTED", "SUPERSEDED"}
    assert isinstance(row["reviewed_lc_version"], int)
    assert row["reviewer_user_id"]
    assert row["finding_count"] >= 0


def assert_finding(row: Json) -> None:
    assert_common_fields(row)
    assert row["source"] in {"TERMS", "DOCUMENT"}
    assert row["severity"] in {"CRITICAL", "MAJOR", "MINOR"}
    assert row["clause_ref"] in {
        "AMOUNT",
        "EXPIRY",
        "LATEST_SHIPMENT",
        "DOCUMENTS",
        "GOODS",
        "OTHER",
    }
    assert row["cure_status"] in {"OPEN", "CURED", "WAIVED"}
    assert isinstance(row["raised_in_round"], int)


def assert_trade_document(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"DRAFT", "ISSUED", "SUPERSEDED", "VOIDED"}
    assert row["doc_type"] in {
        "COMMERCIAL_INVOICE",
        "PACKING_LIST",
        "CERTIFICATE_OF_ORIGIN",
        "BILL_OF_LADING",
        "INSURANCE_CERTIFICATE",
        "INSPECTION_CERTIFICATE",
    }
    assert row["revision"] >= 1
    assert isinstance(row["pinned_order_version"], int)
    assert row["generated_by_user_id"]


def assert_screening(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"INITIATED", "PENDING_LICENSE", "CLEARED", "BLOCKED"}
    assert row["ruleset_version"] >= 1
    assert row["denied_party_hits"] >= 0


def assert_export_license(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"ISSUED", "ACTIVE", "EXHAUSTED", "EXPIRED"}
    assert row["authority"] in {"BIS", "DDTC", "OFAC", "NATIONAL_OTHER"}
    assert row["licensed_value_usd"] > 0
    assert_license_ledger_conserved(row)


def assert_sailing(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"OPEN", "FULL", "CUTOFF_PASSED", "DEPARTED"}
    assert len(row["carrier_scac"]) == 4 and row["carrier_scac"].isupper()
    assert row["capacity_weight_kg"] > 0
    assert row["tariff_rate_per_1000kg_usd"] > 0


def assert_booking(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"BOOKED", "CONFIRMED", "SHIPPED", "CANCELLED"}
    assert row["container_type"] in {"LCL", "DRY_20", "DRY_40", "REEFER_40"}
    assert row["booked_weight_kg"] > 0
    assert row["chargeable_weight_kg"] >= row["booked_weight_kg"]


def assert_presentation(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {
        "PRESENTED",
        "COMPLIED",
        "DISCREPANT",
        "CURING",
        "REFUSED",
        "HONOURED",
    }
    assert row["presentation_round"] >= 1
    assert row["presented_by_user_id"]
    assert row["open_finding_count"] >= 0


def assert_presentation_link(row: Json) -> None:
    """The junction carries only id and created_at from the common field set."""
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row, "the append-only junction carries no updated_at"
    assert "version" not in row, "the append-only junction carries no version"
    assert row["link_status"] in {"ACTIVE", "REPLACED", "INVALIDATED"}
    assert row["pinned_document_revision"] >= 1
    assert row["linked_in_round"] >= 1


def assert_policy(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {"ACTIVE", "EXHAUSTED", "EXPIRED"}
    assert row["exposure_tier"] in {"TIER_1", "TIER_2", "TIER_3"}
    assert row["credit_limit_usd"] > 0
    assert 50.00 <= row["insured_pct"] <= 95.00
    assert_policy_ledger_conserved(row)


def assert_dispute(row: Json) -> None:
    assert_common_fields(row)
    assert row["status"] in {
        "OPEN",
        "OFFERED",
        "COUNTERED",
        "SETTLED",
        "ESCALATED",
        "CLOSED_NO_SETTLEMENT",
    }
    assert row["dispute_type"] in {"SHORT_SHIPMENT", "QUALITY", "NON_PAYMENT"}
    assert row["opened_by_role"] in {"ForeignBuyer", "FinanceCollectionsOfficer"}
    assert row["claimed_amount_usd"] > 0
    assert row["negotiation_round"] >= 0


# ---------------------------------------------------------------------------
# conserved ledger invariants
# ---------------------------------------------------------------------------


def assert_license_ledger_conserved(license_row: Json) -> None:
    assert license_row["consumed_value_usd"] + license_row[
        "remaining_value_usd"
    ] == approx_money(license_row["licensed_value_usd"])
    assert license_row["remaining_value_usd"] >= -MONEY_TOL


def assert_policy_ledger_conserved(policy_row: Json) -> None:
    assert policy_row["utilized_usd"] + policy_row[
        "available_limit_usd"
    ] == approx_money(policy_row["credit_limit_usd"])
    assert policy_row["available_limit_usd"] >= -MONEY_TOL


def assert_sailing_weight(sailing_row: Json, expected_kg: float) -> None:
    assert sailing_row["booked_weight_kg"] == approx_weight(expected_kg)


def assert_order_dimensions(
    order: Json, fulfillment: Optional[str] = None, settlement: Optional[str] = None
) -> None:
    """The two order dimensions evolve independently; assert them independently."""
    if fulfillment is not None:
        assert order["fulfillment_status"] == fulfillment, (
            f"fulfillment_status {order['fulfillment_status']} != {fulfillment}"
        )
    if settlement is not None:
        assert order["settlement_status"] == settlement, (
            f"settlement_status {order['settlement_status']} != {settlement}"
        )


def assert_no_version_field(row: Json) -> None:
    assert "version" not in row


def find_by(rows: List[Json], **criteria: Any) -> Json:
    for row in rows:
        if all(row.get(k) == v for k, v in criteria.items()):
            return row
    raise AssertionError(f"no row matching {criteria} in {rows}")


def maybe_find_by(rows: List[Json], **criteria: Any) -> Optional[Json]:
    for row in rows:
        if all(row.get(k) == v for k, v in criteria.items()):
            return row
    return None


def is_absent_or_none(row: Json, field: str) -> bool:
    """A field the PRD declares null in this state is either absent or null."""
    return row.get(field) is None
