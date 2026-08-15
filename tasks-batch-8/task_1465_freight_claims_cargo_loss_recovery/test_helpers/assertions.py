"""Entity assertions and domain invariant checkers.

All monetary assertions use integer cents per the PRD money rules: no
floating-point money appears in request or response bodies.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealDecision,
    AppealState,
    AssessmentState,
    CarrierStatus,
    CommodityClass,
    DayKind,
    DispositionKind,
    DocumentKind,
    EventKind,
    FilingStatus,
    LaneStatus,
    LiabilityModel,
    NegligenceFlag,
    PaymentStatus,
    ReserveState,
    ResponsiblePartyKind,
    SalvageState,
    SettlementState,
    ShipmentStatus,
    SubrogationState,
    VerificationStatus,
    AuthorityTier,
    ClaimType,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight_common_fields(data: dict):
    """For CarrierLaneAssignment and ClaimEvent: only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "updated_at must be absent on this resource"
    assert "version" not in data, "version must be absent on this resource"


def _assert_cents(data: dict, field: str, minimum: int = 0):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )
    assert value >= minimum, f"{field} must be >= {minimum}, got {value}"


def assert_carrier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["scac_code"], str) and data["scac_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["liability_model"] in {m.value for m in LiabilityModel}
    _assert_cents(data, "max_auto_settle_cents")
    assert isinstance(data["carmack_acknowledgment_days"], int)
    assert isinstance(data["carmack_filing_days"], int)
    _assert_cents(data, "claims_filed_count")
    _assert_cents(data, "claims_paid_count")
    _assert_cents(data, "claim_ratio_bp")
    assert data["status"] in {s.value for s in CarrierStatus}


def assert_lane(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["origin_zip3"], str) and data["origin_zip3"]
    assert isinstance(data["destination_zip3"], str) and data["destination_zip3"]
    _assert_cents(data, "baseline_claim_ratio_bp")
    _assert_cents(data, "shipments_count")
    _assert_cents(data, "claims_count")
    _assert_cents(data, "lane_claim_ratio_bp")
    assert data["status"] in {s.value for s in LaneStatus}


def assert_assignment(data: dict):
    _assert_lightweight_common_fields(data)
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert is_valid_uuid(data.get("lane_id", ""))
    assert isinstance(data["contracted_discount_pct"], int)
    assert 0 <= data["contracted_discount_pct"] <= 100
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bol_number"], str) and data["bol_number"]
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert is_valid_uuid(data.get("lane_id", ""))
    assert is_iso8601_timestamp(data.get("ship_date", ""))
    assert is_iso8601_timestamp(data.get("delivery_date", ""))
    _assert_cents(data, "declared_value_cents")
    assert isinstance(data["total_weight_lbs"], int) and data["total_weight_lbs"] > 0
    assert isinstance(data["package_count"], int) and data["package_count"] > 0
    assert data["commodity_class"] in {c.value for c in CommodityClass}
    assert isinstance(data["is_concealed_damage"], bool)
    assert data["status"] in {s.value for s in ShipmentStatus}


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert is_valid_uuid(data.get("lane_id", ""))
    assert data["claim_type"] in {t.value for t in ClaimType}
    _assert_cents(data, "claimed_amount_cents", minimum=1)
    assert data["filing_status"] in {s.value for s in FilingStatus}
    assert data["payment_status"] in {s.value for s in PaymentStatus}
    _assert_cents(data, "computed_liability_cents")
    _assert_cents(data, "salvage_credit_cents")
    _assert_cents(data, "net_exposure_cents")
    _assert_cents(data, "reserve_amount_cents")
    assert isinstance(data["appeal_round"], int) and data["appeal_round"] >= 0
    assert isinstance(data["acknowledgment_late"], bool)
    # concurrency_token mirrors version per the PRD common-properties rules.
    assert isinstance(data.get("concurrency_token"), int)
    assert data["concurrency_token"] == data["version"], (
        f"concurrency_token {data['concurrency_token']} must mirror version {data['version']}"
    )


def assert_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["document_kind"] in {k.value for k in DocumentKind}
    assert isinstance(data["storage_uri"], str) and data["storage_uri"]
    assert is_iso8601_timestamp(data.get("captured_at", ""))
    assert data["verification_status"] in {s.value for s in VerificationStatus}


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["assessed_by_user_id"], str) and data["assessed_by_user_id"]
    assert data["liability_model_applied"] in {m.value for m in LiabilityModel}
    _assert_cents(data, "limitation_basis_cents")
    _assert_cents(data, "carrier_limit_cents")
    assert isinstance(data["lane_discount_pct"], int)
    _assert_cents(data, "computed_liability_cents")
    assert data["negligence_flag"] in {f.value for f in NegligenceFlag}
    assert data["state"] in {s.value for s in AssessmentState}


def assert_salvage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["disposition_kind"] in {k.value for k in DispositionKind}
    _assert_cents(data, "gross_proceeds_cents")
    _assert_cents(data, "handling_cost_cents")
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data["state"] in {s.value for s in SalvageState}


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    _assert_cents(data, "requested_amount_cents", minimum=1)
    assert data["decision"] in {d.value for d in AppealDecision}
    assert data["state"] in {s.value for s in AppealState}


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["offered_by_role"] in {"ADJUSTER", "MANAGER", "CARRIER"}
    _assert_cents(data, "amount_cents", minimum=1)
    assert data["authority_tier_required"] in {t.value for t in AuthorityTier}
    assert data["state"] in {s.value for s in SettlementState}


def assert_subrogation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["responsible_party_kind"] in {k.value for k in ResponsiblePartyKind}
    assert isinstance(data["responsible_party_name"], str) and data["responsible_party_name"]
    _assert_cents(data, "target_recovery_cents", minimum=1)
    _assert_cents(data, "recovered_cents")
    _assert_cents(data, "recovery_ratio_bp")
    assert data["state"] in {s.value for s in SubrogationState}


def assert_reserve(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    _assert_cents(data, "amount_cents")
    assert isinstance(data["posted_by_user_id"], str) and data["posted_by_user_id"]
    assert is_iso8601_timestamp(data.get("posted_at", ""))
    assert data["state"] in {s.value for s in ReserveState}


def assert_event(data: dict):
    _assert_lightweight_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["event_kind"] in {k.value for k in EventKind}
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert is_iso8601_timestamp(data.get("event_at", ""))


def assert_calendar_row(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["calendar_date"], str) and data["calendar_date"]
    assert isinstance(data["is_business_day"], bool)
    assert data["day_kind"] in {k.value for k in DayKind}


def assert_net_exposure_invariant(claim: dict):
    """net_exposure_cents == max(computed_liability_cents - salvage_credit_cents, 0)."""
    expected = max(claim["computed_liability_cents"] - claim["salvage_credit_cents"], 0)
    assert claim["net_exposure_cents"] == expected, (
        f"net_exposure_cents {claim['net_exposure_cents']} != "
        f"max({claim['computed_liability_cents']} - {claim['salvage_credit_cents']}, 0)"
    )
