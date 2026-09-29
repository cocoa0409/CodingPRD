"""Domain assertion helpers.

Per-entity shape checks plus the invariant checkers the PRD states as
conserved quantities.
"""

from typing import Any, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Row = dict[str, Any]


# --------------------------------------------------------------------------
# Common-field shape (PRD §2.4)
# --------------------------------------------------------------------------


def assert_common_fields(row: Row, entity_name: str = "resource") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row.get("id")), (
        f"{entity_name}.id must be a server-minted UUID with no type prefix, got "
        f"{row.get('id')!r}"
    )
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, got "
        f"{row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, got "
        f"{row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), (
        f"{entity_name}.version must be an integer, got {row.get('version')!r}"
    )
    assert row["version"] >= 1, (
        f"{entity_name}.version begins at 1, got {row['version']}"
    )


def assert_utc_millisecond_timestamp(value: str, label: str) -> None:
    """PRD §2.4 renders timestamps with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be rendered in UTC with a Z suffix: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------


def assert_equipment_model(row: Row) -> None:
    assert_common_fields(row, "EquipmentModel")
    for field in (
        "model_code",
        "name",
        "category",
        "energy_type",
        "certification_posture",
    ):
        assert isinstance(row.get(field), str), f"EquipmentModel.{field} must be a string"
    assert isinstance(row.get("base_price_cents"), int), (
        "EquipmentModel.base_price_cents must be an integer number of cents"
    )
    assert isinstance(row.get("supported_controls_packages"), list)
    assert isinstance(row.get("required_scopes"), list)
    assert isinstance(row.get("covered_scopes"), list)


def assert_certification_listing(row: Row) -> None:
    assert_common_fields(row, "CertificationListing")
    assert is_valid_uuid(row.get("equipment_model_id"))
    assert isinstance(row.get("agency_code"), str)
    assert isinstance(row.get("scopes"), list)
    assert isinstance(row.get("status"), str)
    assert isinstance(row.get("revision"), int)


def assert_chain_account(row: Row) -> None:
    assert_common_fields(row, "ChainAccount")
    assert isinstance(row.get("account_code"), str)
    assert isinstance(row.get("name"), str)
    assert isinstance(row.get("contracted_unit_volume"), int)


def assert_chain_configuration(row: Row) -> None:
    assert_common_fields(row, "ChainConfiguration")
    assert is_valid_uuid(row.get("chain_account_id"))
    assert is_valid_uuid(row.get("equipment_model_id"))
    assert isinstance(row.get("config_code"), str)
    assert isinstance(row.get("option_codes"), list)
    assert isinstance(row.get("controls_package"), str)
    assert isinstance(row.get("branding_kit"), str)
    assert isinstance(row.get("status"), str)
    assert isinstance(row.get("branding_signed_off"), bool)
    assert isinstance(row.get("indicative_unit_price_cents"), int)


def assert_performance_validation(row: Row) -> None:
    assert_common_fields(row, "PerformanceValidation")
    assert is_valid_uuid(row.get("chain_configuration_id"))
    assert isinstance(row.get("menu_item_code"), str)
    assert isinstance(row.get("status"), str)
    assert isinstance(row.get("attempt_count"), int)
    assert isinstance(row.get("test_runs"), list)


def assert_construction_program(row: Row) -> None:
    assert_common_fields(row, "ConstructionProgram")
    assert is_valid_uuid(row.get("chain_account_id"))
    assert isinstance(row.get("program_code"), str)
    assert isinstance(row.get("program_type"), str)
    assert isinstance(row.get("site_count_planned"), int)
    assert isinstance(row.get("commit_posture"), str)


def assert_site_order(row: Row) -> None:
    assert_common_fields(row, "SiteOrder")
    assert is_valid_uuid(row.get("construction_program_id"))
    assert is_valid_uuid(row.get("chain_configuration_id"))
    assert isinstance(row.get("site_code"), str)
    assert isinstance(row.get("unit_count"), int)
    assert isinstance(row.get("fulfillment_status"), str)
    assert isinstance(row.get("commitment_status"), str)


def assert_build_line(row: Row) -> None:
    assert_common_fields(row, "BuildLine")
    assert isinstance(row.get("line_code"), str)
    assert isinstance(row.get("plant_code"), str)
    assert isinstance(row.get("daily_capacity_units"), int)
    assert isinstance(row.get("supported_energy_types"), list)
    assert isinstance(row.get("committed_units"), int)


def assert_production_slot(row: Row) -> None:
    assert_common_fields(row, "ProductionSlot")
    assert is_valid_uuid(row.get("build_line_id"))
    assert is_valid_uuid(row.get("site_order_id"))
    assert isinstance(row.get("units"), int)
    assert isinstance(row.get("status"), str)


def assert_connected_unit(row: Row) -> None:
    assert_common_fields(row, "ConnectedUnit")
    assert is_valid_uuid(row.get("equipment_model_id"))
    assert isinstance(row.get("serial_number"), str)
    assert isinstance(row.get("service_tier"), str)
    assert isinstance(row.get("service_program_status"), str)
    assert isinstance(row.get("firmware_version"), str)
    assert isinstance(row.get("recipe_book_version"), int)
    assert isinstance(row.get("health_score"), int)
    assert isinstance(row.get("reserve_balance_cents"), int)
    assert isinstance(row.get("claims_paid_cents"), int)


def assert_firmware_campaign(row: Row) -> None:
    assert_common_fields(row, "FirmwareCampaign")
    assert is_valid_uuid(row.get("equipment_model_id"))
    assert isinstance(row.get("campaign_code"), str)
    assert isinstance(row.get("target_firmware_version"), str)
    assert isinstance(row.get("cohort_scope"), str)
    assert isinstance(row.get("status"), str)
    assert isinstance(row.get("cohort_unit_ids"), list)


def assert_service_partner(row: Row) -> None:
    assert_common_fields(row, "ServicePartner")
    assert isinstance(row.get("partner_code"), str)
    assert isinstance(row.get("region_code"), str)
    assert isinstance(row.get("parts_stocking_level"), str)
    assert isinstance(row.get("status"), str)
    assert isinstance(row.get("authorized_model_ids"), list)


def assert_technician_certification(row: Row) -> None:
    assert_common_fields(row, "TechnicianCertification")
    assert is_valid_uuid(row.get("service_partner_id"))
    assert is_valid_uuid(row.get("equipment_model_id"))
    assert isinstance(row.get("technician_code"), str)
    assert isinstance(row.get("status"), str)


def assert_warranty_claim(row: Row) -> None:
    assert_common_fields(row, "WarrantyClaim")
    assert is_valid_uuid(row.get("connected_unit_id"))
    assert is_valid_uuid(row.get("service_partner_id"))
    assert is_valid_uuid(row.get("technician_certification_id"))
    assert isinstance(row.get("claim_code"), str)
    assert isinstance(row.get("parts_cost_cents"), int)
    assert isinstance(row.get("status"), str)


# --------------------------------------------------------------------------
# Domain invariants (PRD §2.11)
# --------------------------------------------------------------------------


def assert_committed_units_matches_active_slots(
    line: Row, slots: Iterable[Row]
) -> None:
    """committed_units equals the sum of units over RESERVED/CONFIRMED/IN_BUILD slots."""
    active = [
        slot
        for slot in slots
        if slot.get("build_line_id") == line["id"]
        and slot.get("status") in ("RESERVED", "CONFIRMED", "IN_BUILD")
    ]
    expected = sum(slot["units"] for slot in active)
    assert line["committed_units"] == expected, (
        "BuildLine.committed_units must equal the sum of units over that line's "
        f"slots in RESERVED, CONFIRMED or IN_BUILD; ledger says "
        f"{line['committed_units']} but the active slots sum to {expected}"
    )


def assert_reserve_ledger_conserved(unit: Row, expected_initial: Optional[int] = None) -> None:
    """reserve_balance_cents plus claims_paid_cents equals reserve_initial_cents."""
    initial = (
        expected_initial
        if expected_initial is not None
        else unit.get("reserve_initial_cents")
    )
    total = unit["reserve_balance_cents"] + unit["claims_paid_cents"]
    assert total == initial, (
        "reserve_balance_cents plus claims_paid_cents must equal "
        f"reserve_initial_cents; got {unit['reserve_balance_cents']} + "
        f"{unit['claims_paid_cents']} = {total} against an initial of {initial}"
    )


def assert_slack_days(site_order: Row, expected: Optional[int]) -> None:
    assert site_order.get("slack_days") == expected, (
        f"slack_days should be {expected} for a projected delivery of "
        f"{site_order.get('projected_delivery_date')!r} against a commitment of "
        f"{site_order.get('committed_delivery_date')!r}, got "
        f"{site_order.get('slack_days')!r}"
    )


def assert_health_score(unit: Row, expected: int) -> None:
    assert unit["health_score"] == expected, (
        f"health_score should be {expected} for {unit.get('fault_count_30d')} faults, "
        f"{unit.get('missed_heartbeat_count')} missed heartbeats and firmware "
        f"{unit.get('firmware_version')!r}, got {unit['health_score']}"
    )


def assert_no_derived_price_yet(config: Row) -> None:
    assert config.get("firm_unit_price_cents") is None, (
        "firm_unit_price_cents is stamped only at release, so it must still be "
        f"null here, got {config.get('firm_unit_price_cents')!r}"
    )
