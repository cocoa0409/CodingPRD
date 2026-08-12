"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgencyType,
    AssessmentStatus,
    AssetClass,
    AssetStatus,
    AwardStatus,
    CasualtyLifecycle,
    CasualtyType,
    CharterPurpose,
    CharterStatus,
    ContractForm,
    ContractStatus,
    CustodyStatus,
    DisposeMethod,
    DocEntryType,
    DocPackStatus,
    DocumentationStatus,
    EnvPosture,
    PermitStatus,
    PhaseStatus,
    PhaseType,
    PollutantClass,
    PollutionEventStatus,
    PollutionRiskTier,
    PropertyType,
    SalvageMethod,
    SecurityStatus,
    TerminateReason,
    WeatherWindowStatus,
)


def _assert_common(data: dict):
    """Standard system-managed fields present on every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_casualty(data: dict):
    _assert_common(data)
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert data["casualty_type"] in [e.value for e in CasualtyType]
    assert isinstance(data["declared_salved_value_cents"], int)
    assert data["declared_salved_value_cents"] > 0
    assert isinstance(data["position"], str)
    assert data["lifecycle_status"] in [e.value for e in CasualtyLifecycle]
    assert data["env_posture"] in [e.value for e in EnvPosture]


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert isinstance(data["casualty_seq"], int)
    assert isinstance(data["assessor_id"], str) and data["assessor_id"]
    assert data["pollution_risk_tier"] in [e.value for e in PollutionRiskTier]
    assert isinstance(data["wreck_removal_required"], bool)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in [e.value for e in AssessmentStatus]
    assert "reviewer_id" in data


def assert_salvage_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert isinstance(data["drafter_id"], str) and data["drafter_id"]
    assert data["method"] in [e.value for e in SalvageMethod]
    assert isinstance(data["required_equipment_classes"], list)
    assert len(data["required_equipment_classes"]) > 0
    assert data["status"] in [e.value for e in PlanStatus]
    assert "approver_id" in data


def assert_salvage_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert data["form"] in [e.value for e in ContractForm]
    assert data["status"] in [e.value for e in ContractStatus]
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0
    assert isinstance(data["cost_to_date_cents"], int)
    assert isinstance(data["overrun_flag"], bool)
    assert "terminate_reason" in data
    if data.get("terminate_reason") is not None:
        assert data["terminate_reason"] in [e.value for e in TerminateReason]


def assert_security_deposit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["lodged_amount_cents"], int) and data["lodged_amount_cents"] > 0
    assert isinstance(data["held_cents"], int)
    assert isinstance(data["released_cents"], int)
    assert isinstance(data["applied_cents"], int)
    assert data["status"] in [e.value for e in SecurityStatus]


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert data["agency_type"] in [e.value for e in AgencyType]
    assert is_iso8601_timestamp(data.get("valid_from", "")), "valid_from must be ISO 8601"
    assert is_iso8601_timestamp(data.get("valid_to", "")), "valid_to must be ISO 8601"
    assert data["status"] in [e.value for e in PermitStatus]


def assert_equipment_asset(data: dict):
    _assert_common(data)
    assert data["asset_class"] in [e.value for e in AssetClass]
    assert isinstance(data["day_rate_cents"], int) and data["day_rate_cents"] > 0
    assert data["max_hs_meters"] > 0
    assert data["status"] in [e.value for e in AssetStatus]


def assert_equipment_charter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert is_valid_uuid(data.get("equipment_asset_id", "")), "equipment_asset_id must be a UUID"
    assert data["purpose"] in [e.value for e in CharterPurpose]
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert data["status"] in [e.value for e in CharterStatus]
    assert "on_hire_at" in data and "off_hire_at" in data
    assert isinstance(data["standby_hours"], int)


def assert_weather_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert data["forecast_hs_meters"] >= 0
    assert data["status"] in [e.value for e in WeatherWindowStatus]


def assert_operation_phase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["phase_type"] in [e.value for e in PhaseType]
    assert isinstance(data["planned_duration_hours"], int)
    assert data["planned_duration_hours"] > 0
    assert data["status"] in [e.value for e in PhaseStatus]
    assert "weather_window_id" in data and "activated_at" in data


def assert_pollution_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert data["pollutant_class"] in [e.value for e in PollutantClass]
    assert data["tier"] in [e.value for e in PollutionRiskTier]
    assert data["est_volume_m3"] >= 0
    assert data["status"] in [e.value for e in PollutionEventStatus]
    assert isinstance(data["provisional_exposure_cents"], int)
    assert "final_exposure_cents" in data
    assert "special_compensation_payable_cents" in data


def assert_recovered_property(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("casualty_id", "")), "casualty_id must be a UUID"
    assert data["property_type"] in [e.value for e in PropertyType]
    assert data["quantity_tonnes"] > 0
    assert isinstance(data["declared_value_cents"], int)
    assert data["custody_status"] in [e.value for e in CustodyStatus]
    assert data["documentation_status"] in [e.value for e in DocumentationStatus]
    assert isinstance(data["lien_amount_cents"], int)


def assert_storage_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["capacity_tonnes"] > 0
    assert data["allocated_tonnes"] >= 0


def assert_salvage_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["status"] in [e.value for e in AwardStatus]
    assert isinstance(data["computed_amount_cents"], int)
    assert "agreed_amount_cents" in data
    assert "awarded_amount_cents" in data
    assert "paid_amount_cents" in data
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_doc_pack(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["status"] in [e.value for e in DocPackStatus]
    assert isinstance(data["required_count"], int) and data["required_count"] >= 0
    assert isinstance(data["satisfied_count"], int) and data["satisfied_count"] >= 0
    assert data["completeness_pct"] >= 0
    assert "review_notes" in data


def assert_doc_entry(data: dict):
    """Append-only record: id + created_at only; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DocEntry must not carry updated_at"
    assert "version" not in data, "DocEntry must not carry version"
    assert data["entry_type"] in [e.value for e in DocEntryType]
    assert isinstance(data["ref_id"], str) and data["ref_id"]
    assert is_iso8601_timestamp(data.get("entry_date", "")), "entry_date must be ISO 8601"
    assert isinstance(data["summary"], str)


# ─── Domain invariant checkers ──────────────────────────
def assert_security_conservation(deposit: dict):
    """Money conservation: lodged == held + released + applied at all times."""
    total = deposit["held_cents"] + deposit["released_cents"] + deposit["applied_cents"]
    assert deposit["lodged_amount_cents"] == total, (
        f"Security conservation violated: lodged {deposit['lodged_amount_cents']} "
        f"!= held {deposit['held_cents']} + released {deposit['released_cents']} "
        f"+ applied {deposit['applied_cents']}"
    )
    assert deposit["held_cents"] >= 0, "held_cents must never go negative"


def assert_property_mass_conservation(lot: dict):
    """Mass conservation: quantity == redelivered + sold + disposed + in_custody."""
    total = (
        lot["redelivered_tonnes"]
        + lot["sold_tonnes"]
        + lot["disposed_tonnes"]
        + lot["in_custody_tonnes"]
    )
    assert abs(lot["quantity_tonnes"] - total) < 1e-9, (
        f"Mass conservation violated: quantity {lot['quantity_tonnes']} != "
        f"redelivered {lot['redelivered_tonnes']} + sold {lot['sold_tonnes']} + "
        f"disposed {lot['disposed_tonnes']} + in_custody {lot['in_custody_tonnes']}"
    )
    assert lot["in_custody_tonnes"] >= 0, "in_custody_tonnes must never go negative"
