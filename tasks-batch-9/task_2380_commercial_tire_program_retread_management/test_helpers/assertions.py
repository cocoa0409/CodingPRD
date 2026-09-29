"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountType,
    AgreementStatus,
    BillingMode,
    BillingStatus,
    CallPriority,
    CasingStatus,
    CertificationLevel,
    CreditEntryType,
    CreditSourceEntityType,
    DispatchStatus,
    FleetAccountStatus,
    InspectionGrade,
    InvoiceStatus,
    ManifestStatus,
    RetreadJobStatus,
    RetreadLineStatus,
    SurveyFindingCode,
    TechnicianStatus,
    TireAssetStatus,
    VehicleStatus,
    VehicleType,
    WheelPosition,
)

_POSITIONS = [p.value for p in WheelPosition]


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """Assert the id / created_at / updated_at / version quartet."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label} id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label} created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label} updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_label} version must be an int"
    assert data["version"] >= 1, f"{entity_label} version starts at 1"


def assert_append_only_fields(data: dict, entity_label: str = "observation") -> None:
    """Assert an append-only observation carries only id and created_at.

    Neither ``updated_at`` nor ``version`` may be present on these resources.
    """
    assert is_valid_uuid(data.get("id", "")), f"{entity_label} id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label} created_at must be ISO 8601"
    assert "version" not in data, f"{entity_label} must not carry version"
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"


def assert_bare_uuid(value: str) -> None:
    """A resource identifier is a bare UUID with no type prefix."""
    assert is_valid_uuid(value), f"expected a bare UUID, got {value!r}"
    assert "_" not in value and ":" not in value, (
        f"identifier {value!r} must carry no type prefix"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_service_location(data: dict) -> None:
    assert_common_fields(data, "service location")
    assert isinstance(data["name"], str) and data["name"]
    assert 3 <= len(data["location_code"]) <= 16
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert 15 <= data["road_service_response_minutes_committed"] <= 480
    assert isinstance(data["scrap_permit_number"], str)
    assert isinstance(data["scrap_permit_expires_on"], str)
    assert isinstance(data["is_retread_plant"], bool)
    assert isinstance(data["casings_in_holding_count"], int)
    assert data["casings_in_holding_count"] >= 0


def assert_fleet_account(data: dict) -> None:
    assert_common_fields(data, "fleet account")
    assert data["account_type"] in [t.value for t in AccountType]
    assert data["billing_mode"] in [m.value for m in BillingMode]
    assert data["status"] in [s.value for s in FleetAccountStatus]
    assert is_valid_uuid(data["home_location_id"])
    assert isinstance(data["casing_credit_balance_cents"], int)
    assert data["casing_credit_balance_cents"] >= 0, (
        "the fleet's casing credit balance may never be negative"
    )


def assert_national_agreement(data: dict) -> None:
    assert_common_fields(data, "national agreement")
    assert data["status"] in [s.value for s in AgreementStatus]
    assert is_valid_uuid(data["fleet_account_id"])
    assert 0 <= data["tier_discount_pct"] <= 0.50
    assert 0 <= data["casing_credit_rate_cents"] <= 100000
    assert 15 <= data["emergency_response_minutes"] <= 480
    assert 0 <= data["emergency_labor_rate_cents_per_hour"] <= 100000


def assert_tire_policy(data: dict) -> None:
    assert_common_fields(data, "tire policy")
    assert data["position"] in _POSITIONS
    assert 0 < data["target_pressure_psi"] <= 150
    assert 0 < data["pressure_tolerance_pct"] <= 0.50
    assert data["min_tread_depth_32nds"] >= 2
    assert data["min_tread_depth_32nds"] < data["pull_point_32nds"] <= 20
    assert 0 <= data["max_retread_count"] <= 5
    assert isinstance(data["approved_brands"], list) and data["approved_brands"]
    assert data["pull_point_32nds"] < data["new_tire_tread_depth_32nds"] <= 32
    assert isinstance(data["casing_spec_code"], str) and data["casing_spec_code"]


def assert_vehicle(data: dict) -> None:
    assert_common_fields(data, "vehicle")
    assert data["vehicle_type"] in [t.value for t in VehicleType]
    assert data["status"] in [s.value for s in VehicleStatus]
    assert is_valid_uuid(data["fleet_account_id"])
    assert data["current_odometer_miles"] >= 0


def assert_casing(data: dict) -> None:
    assert_common_fields(data, "casing")
    assert data["status"] in [s.value for s in CasingStatus]
    assert is_valid_uuid(data["fleet_account_id"])
    assert data["intended_position"] in _POSITIONS
    assert 1 <= data["scrap_weight_lbs"] <= 500
    assert 0 <= data["retread_count"] <= 5
    assert data["inspection_grade"] in [None] + [g.value for g in InspectionGrade]
    assert isinstance(data["provisional_credit_cents"], int)


def assert_tire_asset(data: dict) -> None:
    assert_common_fields(data, "tire asset")
    assert data["status"] in [s.value for s in TireAssetStatus]
    assert is_valid_uuid(data["fleet_account_id"])
    assert is_valid_uuid(data["casing_id"])
    assert data["cost_basis_cents"] >= 0
    assert data["position"] is None or data["position"] in _POSITIONS
    assert data["accumulated_miles"] >= 0, "accumulated_miles is floored at 0"


def assert_tire_survey(data: dict) -> None:
    assert_append_only_fields(data, "tire survey")
    assert is_valid_uuid(data["tire_asset_id"])
    assert 0 <= data["pressure_psi"] <= 200
    assert 0 <= data["tread_depth_32nds"] <= 32
    assert data["odometer_miles"] >= 0
    assert data["finding_code"] in [f.value for f in SurveyFindingCode]
    assert isinstance(data["pull_recommended"], bool)
    assert isinstance(data["surveyed_by_user_id"], str) and data["surveyed_by_user_id"]
    assert_four_decimal_places(data["pressure_deviation_pct"], "pressure_deviation_pct")


def assert_casing_credit_entry(data: dict) -> None:
    assert_append_only_fields(data, "casing credit entry")
    assert is_valid_uuid(data["fleet_account_id"])
    assert data["entry_type"] in [t.value for t in CreditEntryType]
    assert isinstance(data["amount_cents"], int), "amounts are integer cents"
    assert data["source_entity_type"] in [t.value for t in CreditSourceEntityType]
    assert is_valid_uuid(data["source_entity_id"])
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["memo"], str)


def assert_retread_line(data: dict) -> None:
    assert_common_fields(data, "retread line")
    assert data["status"] in [s.value for s in RetreadLineStatus]
    assert is_valid_uuid(data["service_location_id"])
    assert 0 <= data["cure_cooldown_minutes"] <= 240
    assert data["booked_minutes"] >= 0


def assert_retread_job(data: dict) -> None:
    assert_common_fields(data, "retread job")
    assert data["status"] in [s.value for s in RetreadJobStatus]
    assert is_valid_uuid(data["casing_id"])
    assert is_valid_uuid(data["retread_line_id"])
    assert isinstance(data["slot_minutes"], int)
    assert 60 <= data["slot_minutes"] <= 480
    assert isinstance(data["reschedule_count"], int)
    assert data["reschedule_count"] >= 0


def assert_technician(data: dict) -> None:
    assert_common_fields(data, "technician")
    assert data["status"] in [s.value for s in TechnicianStatus]
    assert data["certification_level"] in [c.value for c in CertificationLevel]
    assert is_valid_uuid(data["service_location_id"])
    assert data["completed_call_count"] >= 0


def assert_road_service_call(data: dict) -> None:
    assert_common_fields(data, "road service call")
    assert data["dispatch_status"] in [s.value for s in DispatchStatus]
    assert data["billing_status"] in [s.value for s in BillingStatus]
    assert data["priority"] in [p.value for p in CallPriority]
    assert is_valid_uuid(data["fleet_account_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["service_location_id"])


def assert_scrap_manifest(data: dict) -> None:
    assert_common_fields(data, "scrap manifest")
    assert data["status"] in [s.value for s in ManifestStatus]
    assert is_valid_uuid(data["service_location_id"])
    assert 1 <= data["hauler_capacity_lbs"] <= 40000
    assert data["tire_count"] >= 0
    assert data["total_weight_lbs"] >= 0
    assert isinstance(data["manifest_number"], str) and data["manifest_number"]


def assert_cross_location_invoice(data: dict) -> None:
    assert_common_fields(data, "cross-location invoice")
    assert data["status"] in [s.value for s in InvoiceStatus]
    assert is_valid_uuid(data["fleet_account_id"])
    assert is_valid_uuid(data["national_agreement_id"])
    assert data["line_count"] >= 0
    for money_field in (
        "subtotal_cents",
        "discount_cents",
        "net_before_credit_cents",
        "credit_applied_cents",
        "total_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} is integer cents"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------

def assert_four_decimal_places(value, label: str = "value") -> None:
    """A fraction rounded half up to four decimal places has no fifth digit."""
    assert value is not None, f"{label} must be present"
    quantised = round(float(value) * 10000)
    assert abs(float(value) * 10000 - quantised) < 1e-6, (
        f"{label} must carry at most four decimal places, got {value!r}"
    )


def assert_invoice_rollup_arithmetic(invoice: dict) -> None:
    """The four pinned rollup steps must agree with each other."""
    assert (
        invoice["net_before_credit_cents"]
        == invoice["subtotal_cents"] - invoice["discount_cents"]
    ), "net_before_credit_cents is subtotal_cents less discount_cents"
    assert (
        invoice["total_cents"]
        == invoice["net_before_credit_cents"] - invoice["credit_applied_cents"]
    ), "total_cents is net_before_credit_cents less credit_applied_cents"
    cap = int(invoice["net_before_credit_cents"] * 0.25)
    assert invoice["credit_applied_cents"] <= cap, (
        "credit_applied_cents may not exceed 25 percent of net_before_credit_cents"
    )


def assert_ledger_sum(entries, expected_total: int) -> None:
    """The summed ledger must equal the expected conserved total."""
    actual = sum(e["amount_cents"] for e in entries)
    assert actual == expected_total, (
        f"Expected the ledger to sum to {expected_total}, got {actual} "
        f"across {len(entries)} entries"
    )


def assert_balance_equals_ledger(fleet: dict, entries) -> None:
    """casing_credit_balance_cents is nothing but the sum of the ledger."""
    total = sum(e["amount_cents"] for e in entries)
    assert fleet["casing_credit_balance_cents"] == total, (
        f"Expected balance {total} from the ledger, got "
        f"{fleet['casing_credit_balance_cents']}"
    )


def assert_provisional_credit_from_entries(casing: dict, entries) -> None:
    """A casing's provisional credit sums its non-APPLICATION entries."""
    total = sum(
        e["amount_cents"]
        for e in entries
        if e.get("casing_id") == casing["id"]
        and e["entry_type"] in ("ACCRUAL", "REVERSAL", "ADJUSTMENT", "EXPIRY")
    )
    assert casing["provisional_credit_cents"] == total, (
        f"Expected provisional_credit_cents {total}, got "
        f"{casing['provisional_credit_cents']}"
    )


def assert_entry_counts(entries, **expected_by_type) -> None:
    """Assert how many entries of each type the ledger holds."""
    for entry_type, expected in expected_by_type.items():
        actual = len([e for e in entries if e["entry_type"] == entry_type.upper()])
        assert actual == expected, (
            f"Expected {expected} {entry_type.upper()} entries, got {actual}"
        )


def entries_of_type(entries, entry_type: str):
    return [e for e in entries if e["entry_type"] == entry_type]


def assert_group_reports_cost_per_mile(group: dict, expected: float) -> None:
    """A cost-per-mile group must carry its grouping triple and its figure.

    The PRD names the grouping dimensions (``brand``, ``position`` and
    ``vehicle_type``) and pins the figure to four decimal places, so the value
    is asserted wherever the group exposes it.
    """
    for dimension in ("brand", "position", "vehicle_type"):
        assert dimension in group, f"group must carry its {dimension} dimension"
    matches = [
        value
        for value in group.values()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(float(value) - expected) < 5e-5
    ]
    assert matches, (
        f"Expected the group to report a cost per mile of {expected}, "
        f"got group {group}"
    )


def assert_sla_pricing(call: dict) -> None:
    """gross_cents less sla_credit_cents is the per-line billable figure."""
    assert (
        call["invoice_total_cents"] == call["gross_cents"] - call["sla_credit_cents"]
    ), "invoice_total_cents is gross_cents less sla_credit_cents"
    if call["sla_met"]:
        assert call["sla_credit_cents"] == 0, (
            "a met commitment earns exactly no service-level credit"
        )
