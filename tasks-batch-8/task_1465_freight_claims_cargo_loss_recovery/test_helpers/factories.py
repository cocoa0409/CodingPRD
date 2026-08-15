"""Payload factories — one per entity, input fields only.

Natural keys (scac_code, bol_number) get unique suffixes so repeated setup
inside one test never collides on uniqueness rules.
"""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:10].upper()


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "scac_code": f"C{_suffix()[:8]}",
        "legal_name": "Test Carrier LLC",
        "liability_model": "FULL_VALUE",
        "max_auto_settle_cents": TEST_DEFAULTS["MAX_AUTO_SETTLE_CENTS"],
        "carmack_acknowledgment_days": 30,
        "carmack_filing_days": 270,
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(**overrides) -> dict:
    defaults = {
        "origin_zip3": "100",
        "destination_zip3": "200",
        "baseline_claim_ratio_bp": TEST_DEFAULTS["BASELINE_CLAIM_RATIO_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(carrier_id, lane_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "lane_id": lane_id,
        "contracted_discount_pct": 0,
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(carrier_id, lane_id, **overrides) -> dict:
    defaults = {
        "bol_number": f"BOL-{_suffix()}",
        "carrier_id": carrier_id,
        "lane_id": lane_id,
        "ship_date": TEST_DEFAULTS["SHIP_DATE"],
        "delivery_date": TEST_DEFAULTS["DELIVERY_DATE"],
        "declared_value_cents": TEST_DEFAULTS["DECLARED_VALUE_CENTS"],
        "total_weight_lbs": TEST_DEFAULTS["TOTAL_WEIGHT_LBS"],
        "package_count": TEST_DEFAULTS["PACKAGE_COUNT"],
        "commodity_class": "GENERAL",
        "is_concealed_damage": False,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(shipment_id, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "claim_type": "DAMAGE",
        "claimed_amount_cents": TEST_DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "document_kind": "BOL",
        "storage_uri": f"s3://docs/{_suffix()}.pdf",
        "captured_at": TEST_DEFAULTS["SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {"negligence_flag": "CARRIER_NEGLIGENT"}
    defaults.update(overrides)
    return defaults


def create_salvage_payload(**overrides) -> dict:
    defaults = {
        "disposition_kind": "AUCTION",
        "gross_proceeds_cents": 5_000,
        "handling_cost_cents": 500,
        "scheduled_at": "2026-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(expected_claim_version, **overrides) -> dict:
    defaults = {
        "justification": "Shipper disputes the decline",
        "requested_amount_cents": TEST_DEFAULTS["CLAIMED_AMOUNT_CENTS"],
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(amount_cents, expected_claim_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_subrogation_payload(**overrides) -> dict:
    defaults = {
        "responsible_party_kind": "THIRD_PARTY_CARRIER",
        "responsible_party_name": "Responsible Party LLC",
        "target_recovery_cents": 40_000,
    }
    defaults.update(overrides)
    return defaults


def create_reserve_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_calendar_payload(**overrides) -> dict:
    defaults = {
        "calendar_date": "2026-08-01",
        "is_business_day": True,
        "day_kind": "BUSINESS",
    }
    defaults.update(overrides)
    return defaults
