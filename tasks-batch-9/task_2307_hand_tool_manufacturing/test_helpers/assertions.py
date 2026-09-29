"""Entity assertions and the domain invariant checkers of PRD §2.9."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AlloyGrade,
    CampaignStatus,
    CertStatus,
    Channel,
    ClaimReason,
    ClaimStatus,
    ClaimantStatus,
    ClaimantType,
    Disposition,
    EvidenceGrade,
    FurnaceStatus,
    PackStatus,
    PackType,
    ProcessStatus,
    ReportStatus,
    TestRunStatus,
    TestType,
    ToolFamily,
    WarrantyPosture,
    WarrantyTier,
)


def _members(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict) -> None:
    """Every resource carries an id and a created_at; most also carry an
    updated_at and a version that starts at 1 on creation."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_immutable_row_fields(data: dict) -> None:
    """A pack member line and a claim replacement line carry only id and
    created_at: neither updated_at nor version exists on them at all."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "an immutable line must not carry updated_at"
    assert "version" not in data, "an immutable line must not carry version"


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def assert_tool_sku(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and 1 <= len(data["sku_code"]) <= 32
    assert data["tool_family"] in _members(ToolFamily)
    assert data["channel"] in _members(Channel)
    assert isinstance(data["nominal_size_mm"], int)
    assert 1 <= data["nominal_size_mm"] <= 80
    assert data["alloy_grade"] in _members(AlloyGrade)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 1
    assert data["warranty_tier"] in _members(WarrantyTier)
    assert isinstance(data["lineage_depth"], int) and data["lineage_depth"] >= 0
    assert isinstance(data["proof_torque_required_nm"], (int, float))
    assert isinstance(data["brand_risk_score"], int)
    assert 0 <= data["brand_risk_score"] <= 100
    assert data["warranty_posture"] in _members(WarrantyPosture)
    assert isinstance(data["confirmed_counterfeit_count"], int)
    assert_unit_ledger(data)


def assert_unit_ledger(sku: dict) -> None:
    """units_received_total equals units_on_hand plus units_reserved plus
    units_shipped at every instant (PRD §2.9)."""
    total = sku["units_received_total"]
    on_hand = sku["units_on_hand"]
    reserved = sku["units_reserved"]
    shipped = sku["units_shipped"]
    for name, value in (
        ("units_received_total", total),
        ("units_on_hand", on_hand),
        ("units_reserved", reserved),
        ("units_shipped", shipped),
    ):
        assert isinstance(value, int) and value >= 0, f"{name} must be a non-negative integer"
    assert total == on_hand + reserved + shipped, (
        "unit ledger must close: "
        f"units_received_total {total} != {on_hand} + {reserved} + {shipped}"
    )


# ---------------------------------------------------------------------------
# Shop floor
# ---------------------------------------------------------------------------


def assert_production_lot(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data["specimen_pool_total"], int) and data["specimen_pool_total"] >= 1
    assert data["process_status"] in _members(ProcessStatus)
    assert data["cert_status"] in _members(CertStatus)
    assert data["disposition"] in _members(Disposition)
    assert isinstance(data["rework_cycle_count"], int) and data["rework_cycle_count"] >= 0
    assert isinstance(data["proof_torque_required_nm"], (int, float))
    assert_specimen_ledger(data)


def assert_specimen_ledger(lot: dict) -> None:
    """specimen_pool_total equals specimens_available plus specimens_committed
    plus specimens_consumed at every instant (PRD §2.9)."""
    total = lot["specimen_pool_total"]
    available = lot["specimens_available"]
    committed = lot["specimens_committed"]
    consumed = lot["specimens_consumed"]
    for name, value in (
        ("specimens_available", available),
        ("specimens_committed", committed),
        ("specimens_consumed", consumed),
    ):
        assert isinstance(value, int) and value >= 0, f"{name} must be a non-negative integer"
    assert total == available + committed + consumed, (
        "specimen ledger must close: "
        f"specimen_pool_total {total} != {available} + {committed} + {consumed}"
    )


def assert_heat_treat_furnace(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["furnace_code"], str) and data["furnace_code"]
    assert isinstance(data["max_charge_kg"], int) and data["max_charge_kg"] >= 1
    assert isinstance(data["alloy_grades_supported"], list)
    assert data["alloy_grades_supported"], "alloy_grades_supported must be non-empty"
    for grade in data["alloy_grades_supported"]:
        assert grade in _members(AlloyGrade)
    assert data["status"] in _members(FurnaceStatus)


def assert_furnace_campaign(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["furnace_id"])
    assert isinstance(data["charge_kg"], int) and data["charge_kg"] >= 1
    assert data["status"] in _members(CampaignStatus)
    assert data["window_end"] > data["window_start"]
    assert data["buffered_end"] > data["window_end"]


def assert_salt_spray_chamber(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert isinstance(data["coupon_capacity"], int) and data["coupon_capacity"] >= 1


def assert_test_run(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"])
    assert data["test_type"] in _members(TestType)
    assert isinstance(data["specimen_count"], int) and data["specimen_count"] >= 1
    assert isinstance(data["mandatory"], bool)
    assert data["status"] in _members(TestRunStatus)
    assert data["window_end"] > data["window_start"]


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


def assert_pack_configuration(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pack_code"], str) and data["pack_code"]
    assert data["pack_type"] in _members(PackType)
    assert is_valid_uuid(data["primary_sku_id"])
    assert data["status"] in _members(PackStatus)
    for field in (
        "member_subtotal_cents",
        "security_surcharge_cents",
        "pack_total_cents",
        "distinct_member_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
        assert data[field] >= 0
    assert data["pack_total_cents"] == (
        data["member_subtotal_cents"] + data["security_surcharge_cents"]
    ), "pack_total_cents must be member_subtotal_cents plus security_surcharge_cents"


def assert_pack_member(data: dict) -> None:
    assert_immutable_row_fields(data)
    assert is_valid_uuid(data["pack_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_extended_cents"], int)


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------


def assert_warranty_program(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["reserve_funded_cents"], int) and data["reserve_funded_cents"] >= 0
    assert isinstance(data["fraud_score_threshold"], int)
    assert 1 <= data["fraud_score_threshold"] <= 100
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["open_hold_count"], int) and data["open_hold_count"] >= 0


def assert_reserve_ledger(program: dict, charged_claims) -> None:
    """reserve_funded_cents equals reserve_balance_cents plus the sum of the
    reserve_charge_cents of the programme's claims currently in APPROVED or
    FULFILLED status (PRD §2.9)."""
    charged = sum(
        claim["reserve_charge_cents"]
        for claim in charged_claims
        if claim["status"] in ("APPROVED", "FULFILLED")
    )
    assert program["reserve_funded_cents"] == program["reserve_balance_cents"] + charged, (
        "reserve ledger must close: reserve_funded_cents "
        f"{program['reserve_funded_cents']} != {program['reserve_balance_cents']} + {charged}"
    )


def assert_claimant(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["claimant_type"] in _members(ClaimantType)
    assert data["status"] in _members(ClaimantStatus)
    for field in (
        "fraud_risk_score_intake",
        "fraud_risk_score_adjudication",
        "lifetime_claim_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0
    for field in ("fraud_risk_score_intake", "fraud_risk_score_adjudication"):
        assert data[field] <= 100, f"{field} is clamped to at most 100"


def assert_warranty_claim(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["claimant_id"])
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["serial_code"], str) and data["serial_code"]
    assert data["claim_reason"] in _members(ClaimReason)
    assert data["status"] in _members(ClaimStatus)
    assert isinstance(data["fraud_score_at_intake"], int)
    assert 0 <= data["fraud_score_at_intake"] <= 100
    assert isinstance(data["reserve_charge_cents"], int) and data["reserve_charge_cents"] >= 0
    assert isinstance(data["replacement_unit_count"], int)
    assert data["replacement_unit_count"] >= 0
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["fraud_cleared"], bool)


def assert_claim_line(data: dict) -> None:
    assert_immutable_row_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["component_code"], str) and data["component_code"]
    assert isinstance(data["component_list_price_cents"], int)
    assert data["component_list_price_cents"] >= 1
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_reserve_cents"], int)


# ---------------------------------------------------------------------------
# Brand protection
# ---------------------------------------------------------------------------


def assert_counterfeit_report(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["channel_name"], str) and data["channel_name"]
    assert isinstance(data["seller_handle"], str) and data["seller_handle"]
    assert data["evidence_grade"] in _members(EvidenceGrade)
    assert isinstance(data["unit_estimate"], int) and data["unit_estimate"] >= 0
    assert isinstance(data["risk_points"], int)
    assert data["status"] in _members(ReportStatus)


# ---------------------------------------------------------------------------
# Money precision
# ---------------------------------------------------------------------------


def assert_integer_cents(value, label: str = "amount") -> None:
    """Money is held as integer cents throughout: there are no fractional cents
    anywhere in the API."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_two_decimal_places(value, label: str = "value") -> None:
    """Lot hardness indices and signed result margins are carried to two
    decimal places."""
    assert value is not None, f"{label} must not be null"
    quantised = round(float(value) * 100)
    assert abs(float(value) * 100 - quantised) < 1e-6, (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_one_decimal_place(value, label: str = "value") -> None:
    """Torque requirements and per-run test means are carried to one decimal
    place."""
    assert value is not None, f"{label} must not be null"
    quantised = round(float(value) * 10)
    assert abs(float(value) * 10 - quantised) < 1e-6, (
        f"{label} must carry at most one decimal place, got {value!r}"
    )
