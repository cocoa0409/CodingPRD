"""Shape assertions, invariant checkers and reference arithmetic."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    GERM_ADJUSTMENT,
    PURITY_ADJUSTMENT,
    RECOVERY_CAP_TIERS,
    THRESHOLDS,
    WEED_ADJUSTMENT,
)

# Entities that carry only ``id`` and ``created_at``.
IDENTITY_ONLY_ENTITIES = ("Variety", "TreatmentProduct", "FieldHistoryRecord", "HarvestEvent")


# ---------------------------------------------------------------------------
# Arithmetic helpers mirroring the contract's rounding rules
# ---------------------------------------------------------------------------


def round_half_up(value: float | Decimal, places: int) -> float:
    """Round half-up to ``places`` decimal places, away from zero on a tie."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def truncate(value: float, places: int = 0) -> float:
    factor = 10**places
    return int(value * factor) / factor if places else float(int(value))


def expected_moisture_dockage_pct(moisture_pct: float) -> float:
    return max(
        0.0,
        (moisture_pct - THRESHOLDS["MOISTURE_BASE_PCT"]) * THRESHOLDS["MOISTURE_SHRINK_FACTOR"],
    )


def expected_provisional_clean_kg(
    gross_weight_kg: float, moisture_pct: float, estimated_conditioning_shrink_pct: float
) -> float:
    dockage = expected_moisture_dockage_pct(moisture_pct)
    raw = gross_weight_kg * (1 - dockage / 100.0) * (1 - estimated_conditioning_shrink_pct / 100.0)
    return round_half_up(raw, 3)


def expected_clean_units(clean_kg: float) -> float:
    return round_half_up(clean_kg / THRESHOLDS["UNIT_KG"], 2)


def expected_dockage_pct(cumulative_shrink_kg: float, gross_kg: float) -> float:
    return round_half_up(cumulative_shrink_kg / gross_kg * 100.0, 2)


def expected_rate_per_10000(count: int, sampled_plants: int) -> float:
    return round_half_up(count / sampled_plants * 10000.0, 2)


def expected_disease_incidence_pct(diseased_plants: int, sampled_plants: int) -> float:
    return round_half_up(diseased_plants / sampled_plants * 100.0, 2)


def expected_price_adjustment_pct(
    germination_pct: float, purity_pct: float, weed_seed_count_per_kg: int, intake_moisture_pct: float
) -> float:
    """Sum the quality steps, subtract moisture dockage, then clamp floor before ceiling."""
    if germination_pct >= GERM_ADJUSTMENT["HIGH_PCT"]:
        adjustment = GERM_ADJUSTMENT["HIGH_ADJ"]
    elif germination_pct >= GERM_ADJUSTMENT["MID_PCT"]:
        adjustment = GERM_ADJUSTMENT["MID_ADJ"]
    else:
        adjustment = GERM_ADJUSTMENT["LOW_ADJ"]

    if purity_pct >= PURITY_ADJUSTMENT["HIGH_PCT"]:
        adjustment += PURITY_ADJUSTMENT["HIGH_ADJ"]
    elif purity_pct >= PURITY_ADJUSTMENT["MID_PCT"]:
        adjustment += PURITY_ADJUSTMENT["MID_ADJ"]
    else:
        adjustment += PURITY_ADJUSTMENT["LOW_ADJ"]

    if weed_seed_count_per_kg == 0:
        adjustment += WEED_ADJUSTMENT["CLEAN_ADJ"]
    elif weed_seed_count_per_kg <= WEED_ADJUSTMENT["LOW_MAX"]:
        adjustment += WEED_ADJUSTMENT["LOW_ADJ"]
    elif weed_seed_count_per_kg <= WEED_ADJUSTMENT["MID_MAX"]:
        adjustment += WEED_ADJUSTMENT["MID_ADJ"]

    adjustment -= expected_moisture_dockage_pct(intake_moisture_pct)
    adjustment = max(adjustment, THRESHOLDS["ADJ_FLOOR_PCT"])
    adjustment = min(adjustment, THRESHOLDS["ADJ_CAP_PCT"])
    return round_half_up(adjustment, 2)


def expected_adjusted_price_cents(base_price_per_unit_cents: int, adjustment_pct: float) -> int:
    return int(round_half_up(base_price_per_unit_cents * (1 + adjustment_pct / 100.0), 0))


def expected_recovery_cap_pct(provisional_net_cents: int) -> float:
    for floor_cents, cap_pct in RECOVERY_CAP_TIERS:
        if provisional_net_cents >= floor_cents:
            return cap_pct
    return RECOVERY_CAP_TIERS[-1][1]


def expected_advance_recovery_cents(provisional_net_cents: int, advance_outstanding_cents: int) -> int:
    cap_pct = expected_recovery_cap_pct(provisional_net_cents)
    capped = int(round_half_up(provisional_net_cents * cap_pct / 100.0, 0))
    return min(advance_outstanding_cents, capped)


def expected_history_component(season_year: int, restricted_crop_years: list[int]) -> float:
    """Decay-weighted history component: per-record contributions rounded before summation."""
    total = 0.0
    for crop_year in restricted_crop_years:
        elapsed_years = season_year - crop_year
        total += round_half_up(THRESHOLDS["HISTORY_BASE_RISK"] * THRESHOLDS["DECAY_FACTOR"] ** elapsed_years, 2)
    return round_half_up(total, 2)


def expected_isolation_component(isolation_min_m: float, isolation_distance_m: float) -> float:
    shortfall = max(0.0, isolation_min_m - isolation_distance_m)
    return round_half_up(shortfall * THRESHOLDS["ISOLATION_RISK_PER_M"], 2)


# ---------------------------------------------------------------------------
# Common-field shape assertions
# ---------------------------------------------------------------------------


def assert_identity_fields(data: dict[str, Any]) -> None:
    assert "id" in data, "response is missing id"
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert "created_at" in data, "response is missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), f"created_at is not ISO 8601: {data['created_at']!r}"


def assert_versioned_common_fields(data: dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert "updated_at" in data, "response is missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), f"updated_at is not ISO 8601: {data['updated_at']!r}"
    assert "version" in data, "response is missing version"
    assert isinstance(data["version"], int), f"version is not an integer: {data['version']!r}"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']!r}"


def assert_no_mutable_common_fields(data: dict[str, Any]) -> None:
    """updated_at and version must be absent from the response shape entirely."""
    assert "updated_at" not in data, "updated_at must not be part of this response shape"
    assert "version" not in data, "version must not be part of this response shape"


def assert_fields_present(data: dict[str, Any], field_names: tuple[str, ...] | list[str]) -> None:
    missing = [name for name in field_names if name not in data]
    assert not missing, f"response is missing declared fields: {missing}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

VARIETY_FIELDS = (
    "crop_kind",
    "variety_name",
    "max_seed_class",
    "isolation_min_m",
    "restricted_prior_crop_kinds",
    "restricted_prior_crop_years",
    "germination_min_pct",
    "purity_min_pct",
    "max_off_type_per_10000",
    "max_restricted_weed_per_10000",
    "max_disease_incidence_pct",
    "max_rogueing_rounds",
    "estimated_conditioning_shrink_pct",
    "germ_validity_days",
    "max_carryover_generations",
    "treatment_required",
)


def assert_variety(data: dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert_no_mutable_common_fields(data)
    assert_fields_present(data, VARIETY_FIELDS)
    assert isinstance(data["restricted_prior_crop_kinds"], list)
    assert isinstance(data["treatment_required"], bool)


TREATMENT_PRODUCT_FIELDS = (
    "product_code",
    "epa_registration_number",
    "allowed_crop_kinds",
    "max_rate_g_per_100kg",
    "requires_dye",
    "restricted_use",
    "label_signal_word",
)


def assert_treatment_product(data: dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert_no_mutable_common_fields(data)
    assert_fields_present(data, TREATMENT_PRODUCT_FIELDS)


GROWER_FIELDS = ("grower_name", "region_code", "contact_email", "status", "compliance_flag_count")


def assert_grower(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, GROWER_FIELDS)
    assert data["status"] in {"GOOD_STANDING", "WATCH", "SUSPENDED"}
    assert isinstance(data["compliance_flag_count"], int)


PRODUCTION_FIELD_FIELDS = (
    "grower_id",
    "field_code",
    "acres",
    "isolation_distance_m",
    "last_assessed_risk_score",
    "history_record_count",
)


def assert_production_field(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, PRODUCTION_FIELD_FIELDS)


FIELD_HISTORY_RECORD_FIELDS = ("production_field_id", "crop_kind", "crop_year", "source_note")


def assert_field_history_record(data: dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert_no_mutable_common_fields(data)
    assert_fields_present(data, FIELD_HISTORY_RECORD_FIELDS)


PRODUCTION_CONTRACT_FIELDS = (
    "grower_id",
    "variety_id",
    "production_field_id",
    "season_year",
    "seed_class",
    "contracted_acres",
    "base_price_per_unit_cents",
    "conditioning_charge_per_unit_cents",
    "advance_total_cents",
    "advance_outstanding_cents",
    "status",
    "planted_on",
    "inspection_round",
    "rogueing_rounds_used",
    "eligibility_variant_applied",
    "eligibility_risk_score",
    "provisional_clean_units_total",
    "certified_units_total",
    "requires_field_officer_review",
    "cancel_reason",
)


def assert_production_contract(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, PRODUCTION_CONTRACT_FIELDS)


FIELD_INSPECTION_FIELDS = (
    "production_contract_id",
    "inspector_user_id",
    "inspection_round",
    "inspected_on",
    "sampled_plants",
    "off_type_plants",
    "restricted_weed_plants",
    "diseased_plants",
    "isolation_verified_m",
    "off_type_rate_per_10000",
    "weed_rate_per_10000",
    "disease_incidence_pct",
    "outcome",
    "status",
    "rogueing_plants_removed",
    "rogueing_declared_on",
    "rogueing_verified_by_user_id",
    "verified_remaining_off_type_plants",
)


def assert_field_inspection(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, FIELD_INSPECTION_FIELDS)
    assert data["outcome"] in {"PASSED", "ROGUEING_ORDERED", "FAILED"}


HARVEST_EQUIPMENT_FIELDS = (
    "equipment_code",
    "equipment_kind",
    "cleanout_minutes_required",
    "status",
    "last_cleanout_at",
    "last_cleanout_variety_id",
    "cleanout_certified",
)


def assert_harvest_equipment(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, HARVEST_EQUIPMENT_FIELDS)


HARVEST_EVENT_FIELDS = (
    "production_contract_id",
    "harvest_equipment_id",
    "seed_lot_id",
    "window_start",
    "window_end",
    "gross_weight_kg",
    "moisture_pct",
    "bag_size_kg",
    "moisture_dockage_pct",
    "provisional_clean_kg",
    "provisional_clean_units",
)


def assert_harvest_event(data: dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert_no_mutable_common_fields(data)
    assert_fields_present(data, HARVEST_EVENT_FIELDS)


CONDITIONING_LINE_FIELDS = (
    "line_code",
    "cleanout_minutes_required",
    "capacity_kg_per_hour",
    "status",
    "last_cleanout_variety_id",
    "last_run_end_utc",
)


def assert_conditioning_line(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, CONDITIONING_LINE_FIELDS)


SEED_LOT_FIELDS = (
    "lot_code",
    "variety_id",
    "production_contract_id",
    "parent_seed_lot_id",
    "season_year",
    "carryover_generation",
    "gross_kg",
    "current_kg",
    "cumulative_shrink_kg",
    "dockage_pct",
    "bag_size_kg",
    "bag_count",
    "tagged_bag_count",
    "intake_moisture_pct",
    "provisional_clean_units",
    "final_clean_units",
    "conditioning_status",
    "certification_status",
    "germination_pct",
    "purity_pct",
    "weed_seed_count_per_kg",
    "germination_valid_until",
    "adjusted_price_per_unit_cents",
    "disposition",
)


def assert_seed_lot(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, SEED_LOT_FIELDS)
    assert data["conditioning_status"] in {"RAW", "CLEANED", "SIZED", "TREATED", "BAGGED"}
    assert data["certification_status"] in {
        "UNSAMPLED",
        "SAMPLED",
        "PASSED",
        "FAILED",
        "TAGGED",
        "RETEST_DUE",
    }


CONDITIONING_RUN_FIELDS = (
    "seed_lot_id",
    "conditioning_line_id",
    "stage",
    "window_start",
    "window_end",
    "input_kg",
    "output_kg",
    "shrink_kg",
    "bag_count",
    "status",
    "treatment_product_id",
    "treatment_rate_g_per_100kg",
    "label_text",
    "cleanout_buffer_applied_minutes",
    "reversal_reason",
)


def assert_conditioning_run(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, CONDITIONING_RUN_FIELDS)
    assert data["status"] in {"PLANNED", "COMPLETED", "ABORTED", "REVERSED"}


LOT_SAMPLE_FIELDS = (
    "seed_lot_id",
    "sample_kind",
    "sampled_on",
    "sampler_user_id",
    "germination_pct",
    "purity_pct",
    "inert_pct",
    "weed_seed_count_per_kg",
    "tested_at",
    "result",
    "germination_valid_until",
)


def assert_lot_sample(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, LOT_SAMPLE_FIELDS)
    assert data["result"] in {"PENDING", "PASS", "FAIL"}


CERTIFICATION_TAG_FIELDS = (
    "seed_lot_id",
    "lot_sample_id",
    "tag_serial",
    "tag_class",
    "bag_count",
    "issued_at",
    "status",
    "void_reason",
)


def assert_certification_tag(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, CERTIFICATION_TAG_FIELDS)
    assert data["status"] in {"ISSUED", "VOIDED"}


SETTLEMENT_FIELDS = (
    "production_contract_id",
    "computed_by_user_id",
    "approved_by_user_id",
    "line_count",
    "settled_units_total",
    "gross_payable_cents",
    "conditioning_charges_cents",
    "provisional_net_cents",
    "recovery_cap_pct",
    "advance_recovery_cents",
    "net_payable_cents",
    "status",
    "dispute_reason",
    "payment_reference",
    "quality_hold",
)


def assert_grower_settlement(data: dict[str, Any]) -> None:
    assert_versioned_common_fields(data)
    assert_fields_present(data, SETTLEMENT_FIELDS)
    assert data["status"] in {"COMPUTED", "APPROVED", "PAID", "DISPUTED", "SUPERSEDED"}


ELIGIBILITY_ASSESSMENT_FIELDS = (
    "strict_history_result",
    "decay_weighted_result",
    "restricted_record_count",
    "history_component",
    "isolation_component",
    "contamination_risk_score",
    "isolation_shortfall_m",
    "applied_variant",
    "applied_result",
    "blocking_error_id",
)


def assert_eligibility_assessment(data: dict[str, Any]) -> None:
    assert_fields_present(data, ELIGIBILITY_ASSESSMENT_FIELDS)
    assert data["strict_history_result"] in {"ELIGIBLE", "INELIGIBLE"}
    assert data["decay_weighted_result"] in {"ELIGIBLE", "INELIGIBLE"}
    assert data["applied_variant"] in {"STRICT_HISTORY", "DECAY_WEIGHTED"}


# ---------------------------------------------------------------------------
# Invariant checkers
# ---------------------------------------------------------------------------


def assert_lot_mass_conserved(lot: dict[str, Any]) -> None:
    """Entering mass equals held mass plus cumulative shrink, with zero drift."""
    assert lot["gross_kg"] == lot["current_kg"] + lot["cumulative_shrink_kg"], (
        f"mass drift: gross_kg={lot['gross_kg']} current_kg={lot['current_kg']} "
        f"cumulative_shrink_kg={lot['cumulative_shrink_kg']}"
    )


def assert_tagged_bag_count_matches_issued_tags(lot: dict[str, Any], tags: list[dict[str, Any]]) -> None:
    issued_total = sum(tag["bag_count"] for tag in tags if tag["status"] == "ISSUED")
    assert lot["tagged_bag_count"] == issued_total, (
        f"tagged_bag_count={lot['tagged_bag_count']} but issued tags sum to {issued_total}"
    )


def assert_advance_conserved(contract: dict[str, Any], settlements: list[dict[str, Any]]) -> None:
    recovered = sum(
        settlement["advance_recovery_cents"]
        for settlement in settlements
        if settlement["status"] in {"APPROVED", "PAID"}
    )
    assert contract["advance_outstanding_cents"] + recovered == contract["advance_total_cents"], (
        f"advance drift: outstanding={contract['advance_outstanding_cents']} recovered={recovered} "
        f"total={contract['advance_total_cents']}"
    )


def assert_error_envelope(body: dict[str, Any], expected_error_id: str) -> None:
    """The error envelope carries the identifier and message inside ``data``."""
    assert body.get("response_type") == "error", f"response_type must be error, got {body.get('response_type')!r}"
    assert "data" in body, "error envelope is missing data"
    assert body["data"].get("error_id") == expected_error_id, (
        f"expected error_id {expected_error_id}, got {body['data'].get('error_id')!r}"
    )
    message = body["data"].get("message")
    assert isinstance(message, str) and message.strip(), "error envelope message must be a non-empty string"
    assert "meta" in body, "error envelope is missing meta"
    assert "error_id" not in body, "error_id must not appear at the top level of the envelope"


def assert_lot_code_format(lot_code: str, season_year: int) -> None:
    prefix = f"L-{season_year}-"
    assert lot_code.startswith(prefix), f"lot_code {lot_code!r} must start with {prefix!r}"
    suffix = lot_code[len(prefix) :]
    assert len(suffix) == 4 and suffix.isdigit(), f"lot_code {lot_code!r} must end in a 4-digit sequence"


def parse_instant(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of how many fractional digits it carries."""
    assert isinstance(text, str), f"expected an ISO 8601 instant string, got {text!r}"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected: str) -> None:
    """Compare two ISO 8601 UTC instants by the instant they denote.

    The PRD pins the *value* of derived instants such as ``germination_valid_until``
    (``tested_at`` advanced by the variety's ``germ_validity_days``) but never pins how
    many fractional-second digits such a field is rendered with, so the comparison is on
    the instant rather than on the literal string.
    """
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected the instant {expected!r}, got {actual!r}"
    )


def assert_tag_serial_format(tag_serial: str, season_year: int) -> None:
    prefix = f"TAG-{season_year}-"
    assert tag_serial.startswith(prefix), f"tag_serial {tag_serial!r} must start with {prefix!r}"
    suffix = tag_serial[len(prefix) :]
    assert len(suffix) == 6 and suffix.isdigit(), f"tag_serial {tag_serial!r} must end in a 6-digit sequence"
