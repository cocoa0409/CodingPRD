"""Entity assertions, timestamp canonicalisation and domain invariants."""

from typing import Optional

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import RETENTION_SLOT_CAPACITY_G

# ---------------------------------------------------------------------------
# Timestamp canonicalisation
#
# The PRD renders created_at / updated_at with exactly three fractional-second
# digits, but instants that a test supplies (a certificate's valid_until, a
# retention interval bound, a grant's expires_at) are echoed back as the same
# instant rather than the same string.  Every comparison below is therefore
# made on the canonical instant, never on the raw sub-second width.
# ---------------------------------------------------------------------------

_ISO_MONTH_LENGTHS = None  # placeholder to keep the module import light


def canonical_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a canonical millisecond string.

    "2027-06-30T00:00:00Z", "2027-06-30T00:00:00.000Z" and
    "2027-06-30T00:00:00.0Z" all canonicalise to the same value.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    raw = value.strip()
    assert raw.endswith("Z"), f"Expected a UTC instant ending in Z, got {value!r}"
    body = raw[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "") -> None:
    """Assert two ISO 8601 UTC instants denote the same millisecond."""
    assert actual is not None, f"{label or 'instant'} must not be null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label or 'instant'} expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_envelope_meta(body: dict, expected_response_type: str) -> None:
    """Assert the standard envelope meta block of a parsed response body."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp"
    )
    assert body["response_type"] == expected_response_type, (
        f"Expected response_type {expected_response_type!r}, "
        f"got {body.get('response_type')!r}"
    )


def assert_pagination_meta(meta: dict, limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_customer_brief(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["brief_code"], str) and len(data["brief_code"]) == 8
    assert data["brief_code"].startswith("BRF-")
    assert 1 <= len(data["customer_name"]) <= 120
    assert data["matrix_type"] in ("BEVERAGE_STILL", "BEVERAGE_CARBONATED",
                                  "DAIRY_YOGURT", "BAKERY_SWEET", "SAVOURY_SNACK")
    assert data["target_profile"] in ("CITRUS_TOP_NOTE", "VANILLA_CREAM", "RED_FRUIT",
                                     "SAVOURY_UMAMI", "MINT_COOL")
    assert 0 < float(data["dosage_pct"]) <= 100
    assert int(data["annual_volume_kg"]) >= 1
    assert int(data["cost_in_use_cap_cents_per_tonne"]) >= 0
    assert data["confidentiality_tier"] in ("TIER_1_STANDARD", "TIER_2_RESTRICTED",
                                            "TIER_3_BLACK_BOX")
    assert isinstance(data["natural_claim_required"], bool)
    assert isinstance(data["kosher_required"], bool)
    assert isinstance(data["halal_required"], bool)
    assert isinstance(data["allergen_exclusions"], list)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CLARIFICATION_REQUESTED",
                             "ACCEPTED", "REJECTED", "CLOSED_WON", "CLOSED_LOST")
    assert isinstance(data["clarification_round_count"], int)
    assert 0 <= data["clarification_round_count"] <= 3


def assert_raw_material(data: dict) -> None:
    assert_common_fields(data)
    assert 1 <= len(data["material_code"]) <= 40
    assert 1 <= len(data["name"]) <= 120
    assert isinstance(data["cost_per_kg_cents"], int) and data["cost_per_kg_cents"] >= 1
    assert data["natural_status"] in ("NATURAL", "NATURAL_FLAVOR_WONF",
                                     "NATURE_IDENTICAL", "ARTIFICIAL")
    assert data["potency_class"] in ("HIGH_IMPACT", "STANDARD")
    assert 1 <= int(data["max_use_ppm"]) <= 1000000
    assert isinstance(data["allergen_codes"], list)
    assert data["claim_status"] in ("CLEAR", "RESTRICTED")
    assert isinstance(data["verified_claim_types"], list)


def assert_substantiation_record(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["raw_material_id"])
    assert data["claim_type"] in ("ALLERGEN_FREE_STATEMENT", "KOSHER",
                                 "HALAL", "NATURAL")
    assert 1 <= len(data["issuing_body"]) <= 120
    assert 1 <= len(data["document_ref"]) <= 80
    canonical_instant(data["valid_until"])
    assert data["status"] in ("PENDING", "VERIFIED", "REVOKED")
    assert isinstance(data["is_expired"], bool)


def assert_formula(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["brief_id"])
    assert 1 <= len(data["name"]) <= 120
    assert data["confidentiality_tier"] in ("TIER_1_STANDARD", "TIER_2_RESTRICTED",
                                            "TIER_3_BLACK_BOX")
    assert isinstance(data["iteration_no"], int) and data["iteration_no"] >= 1
    assert data["status"] in ("DRAFT", "COSTED", "SUBMITTED", "APPROVED",
                             "REWORK_REQUIRED", "SUPERSEDED", "ARCHIVED")
    assert isinstance(data["component_count"], int) and data["component_count"] >= 0
    assert float(data["total_weight_pct"]) >= 0
    assert isinstance(data["cost_stale"], bool)
    assert isinstance(data["allergen_codes"], list)
    assert data["allergen_codes"] == sorted(data["allergen_codes"]), (
        "allergen_codes must be an ascending, duplicate-free array"
    )
    assert len(set(data["allergen_codes"])) == len(data["allergen_codes"])


def assert_formula_component(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["formula_id"])
    assert data["component_type"] in ("RAW_MATERIAL", "SUB_FORMULA")
    if data["component_type"] == "RAW_MATERIAL":
        assert is_valid_uuid(data["raw_material_id"])
        assert data.get("sub_formula_id") is None
    else:
        assert is_valid_uuid(data["sub_formula_id"])
        assert data.get("raw_material_id") is None
    assert 0 < float(data["weight_pct"]) <= 100
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_sample_lot(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["formula_id"])
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["batch_size_g"], int)
    assert 1 <= data["batch_size_g"] <= 5000
    assert isinstance(data["allocated_g"], int) and data["allocated_g"] >= 0
    assert isinstance(data["available_g"], int) and data["available_g"] >= 0
    assert data["qc_status"] in ("PENDING", "PASSED", "FAILED")
    assert data["disposition_status"] in ("HELD", "RELEASED", "CONSUMED", "SCRAPPED")
    assert isinstance(data["compounded_by_user_id"], str)
    assert_lot_mass_conserved(data)


def assert_retention_cabinet(data: dict) -> None:
    assert_common_fields(data)
    assert 1 <= len(data["cabinet_code"]) <= 40
    assert 1 <= int(data["capacity_slots"]) <= 200
    assert -40 <= float(data["storage_temp_c"]) <= 30
    assert isinstance(data["slots_available"], int)
    assert 0 <= data["slots_available"] <= data["capacity_slots"]


def assert_retention_sample(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["sample_lot_id"])
    assert is_valid_uuid(data["cabinet_id"])
    assert isinstance(data["quantity_g"], int) and data["quantity_g"] >= 1
    assert data["status"] in ("STORED", "WITHDRAWN")
    canonical_instant(data["stored_from"])
    canonical_instant(data["stored_until"])
    assert data["slot_count"] == expected_slot_count(data["quantity_g"])


def assert_application_rig(data: dict) -> None:
    assert_common_fields(data)
    assert 1 <= len(data["rig_code"]) <= 40
    assert data["matrix_type"] in ("BEVERAGE_STILL", "BEVERAGE_CARBONATED",
                                  "DAIRY_YOGURT", "BAKERY_SWEET", "SAVOURY_SNACK")
    assert 0 <= int(data["cleanout_buffer_minutes"]) <= 480


def assert_application_test(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["sample_lot_id"])
    assert is_valid_uuid(data["rig_id"])
    canonical_instant(data["window_start"])
    canonical_instant(data["window_end"])
    assert 0 < float(data["dosage_pct"]) <= 100
    assert isinstance(data["consumed_g"], int) and data["consumed_g"] >= 1
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")


def assert_sample_shipment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["sample_lot_id"])
    assert is_valid_uuid(data["brief_id"])
    assert len(data["destination_country"]) == 2
    assert data["destination_country"] == data["destination_country"].upper()
    assert isinstance(data["shipped_g"], int) and data["shipped_g"] >= 1
    assert data["status"] in ("DRAFT", "PACKET_ASSEMBLED", "BLOCKED",
                             "DISPATCHED", "CANCELLED")
    assert isinstance(data["required_document_types"], list)


def assert_regulatory_document(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["shipment_id"])
    assert data["doc_type"] in ("SDS", "ALLERGEN_STATEMENT", "NATURAL_DECLARATION",
                                "KOSHER_CERT", "HALAL_CERT", "EXPORT_DECLARATION",
                                "IP_NDA_ADDENDUM")
    assert data["status"] in ("PINNED", "STALE")


def assert_scale_up_batch(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["formula_id"])
    assert 1 <= int(data["target_kg"]) <= 20000
    assert isinstance(data["pinned_formula_version"], int)
    assert data["status"] in ("REQUESTED", "TOLERANCE_SET", "PILOT_RUN",
                             "QUALIFIED", "REJECTED", "CANCELLED")
    assert isinstance(data["tolerance_spec"], list)


def assert_commercialization_forecast(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["brief_id"])
    assert int(data["annual_volume_kg"]) >= 1
    assert int(data["unit_price_cents_per_kg"]) >= 1
    assert isinstance(data["pinned_brief_version"], int)
    assert data["status"] in ("ACTIVE", "AT_RISK", "SUPERSEDED", "REALIZED", "LAPSED")
    assert data["variant_applied"] in ("RISK_WEIGHTED", "COMMITTED")
    assert isinstance(data["weighted_annual_value_cents"], int)


def assert_disclosure_grant(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["brief_id"])
    assert is_valid_uuid(data["formula_id"])
    assert data["disclosed_tier"] in ("TIER_1_STANDARD", "TIER_2_RESTRICTED",
                                     "TIER_3_BLACK_BOX")
    assert data["redaction_level"] in ("REDACTED", "FULL")
    assert data["status"] in ("ACTIVE", "EXPIRED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def expected_slot_count(quantity_g: int) -> int:
    """A whole number of 50-gram slots, rounded up to the next whole slot."""
    return -(-int(quantity_g) // RETENTION_SLOT_CAPACITY_G)


def assert_lot_mass_conserved(lot: dict) -> None:
    """batch_size_g always equals available_g plus allocated_g."""
    assert lot["batch_size_g"] == lot["available_g"] + lot["allocated_g"], (
        f"Gram ledger drifted: batch_size_g {lot['batch_size_g']} != "
        f"available_g {lot['available_g']} + allocated_g {lot['allocated_g']}"
    )


def assert_cabinet_slots_conserved(cabinet: dict, occupied_slots: int) -> None:
    """capacity_slots always equals slots_available plus the occupied slots."""
    assert cabinet["capacity_slots"] == cabinet["slots_available"] + occupied_slots, (
        f"Slot ledger drifted: capacity_slots {cabinet['capacity_slots']} != "
        f"slots_available {cabinet['slots_available']} + occupied {occupied_slots}"
    )


def assert_integer_cents(value, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_four_decimal_places(value, label: str = "value") -> None:
    """A dosage or component weight retains exactly four decimal places."""
    assert float(value) == pytest.approx(round(float(value), 4), abs=1e-9), (
        f"{label} must retain four decimal places, got {value!r}"
    )


def assert_two_decimal_places(value, label: str = "value") -> None:
    assert_cost_precision(float(value), 2)


def assert_uncosted_formula(formula: dict) -> None:
    """A formula that has never been costed, or whose costing was invalidated."""
    assert formula["bench_cost_per_kg_cents"] is None, (
        "bench_cost_per_kg_cents must be null while the formula is uncosted"
    )
    assert formula["bench_cost_in_use_cents_per_tonne"] is None
    assert formula["firm_cost_in_use_cents_per_tonne"] is None
    assert formula["natural_claim_eligible"] is None
    assert formula["kosher_eligible"] is None
    assert formula["halal_eligible"] is None
    assert formula["allergen_codes"] == []
