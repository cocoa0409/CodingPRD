"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    CompliancePosture,
    ContractStatus,
    CrewAssignmentStatus,
    InspectionStatus,
    MakeGoodStatus,
    PermitStatus,
    RideAllocationStatus,
    RideStatus,
    RouteStatus,
    RouteStopStatus,
    SettlementStatus,
    SettlementVariant,
    WeatherClosureStatus,
    WorkerComplianceStatus,
)


# ─── Shared shape checks ──────────────────────────────────────────────────────

def assert_identity_fields(data: dict) -> None:
    """Every resource is addressed by a server-minted UUID with no type prefix."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def assert_versioned_fields(data: dict) -> None:
    """The fourteen versioned resource kinds also carry updated_at and version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or above, got {data['version']}"


def normalize_instant(value: str) -> str:
    """Strip the optional fractional-second part from a UTC instant.

    All instants the system reads or writes are ISO 8601 UTC, so two spellings of
    the same second compare equal once the fractional digits are dropped.
    """
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    head = value[:-1].split(".")[0]
    return head + "Z"


def assert_instant_equals(actual, expected: str, label: str = "instant") -> None:
    assert isinstance(actual, str), (
        f"{label} must be an ISO 8601 UTC instant, got {actual!r}"
    )
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_status_in(data: dict, enum_cls, field: str = "status") -> None:
    allowed = [member.value for member in enum_cls]
    assert data.get(field) in allowed, (
        f"{field} must be one of {allowed}, got {data.get(field)!r}"
    )


def assert_whole_cents(value, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of cents, got {value!r}"
    )


def assert_two_decimal_hours(value, label: str = "hours") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} carries more than two decimal places: {value!r}"
    )


def assert_one_decimal_amps(value, label: str = "amperage") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 1) == float(value), (
        f"{label} carries more than one decimal place: {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_jurisdiction(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be two uppercase letters"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["permit_lead_days"] >= 0
    assert 0 <= data["amusement_tax_pct"] <= 25
    assert data["permit_fee_cents"] >= 0
    assert isinstance(data["requires_state_ride_inspection"], bool)
    assert data["inspection_slot_capacity_per_day"] >= 1
    assert data["max_consecutive_work_days"] >= 1
    assert isinstance(data["housing_permit_required"], bool)


def assert_venue(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["city"], str) and len(data["city"]) > 0
    assert data["lot_area_sqft"] > 0
    assert data["power_amps_available"] > 0
    assert data["expected_attendance"] >= 0
    assert data["lot_surface"] in ("PAVED", "GRAVEL", "GRASS")
    assert data["housing_pads_available"] >= 0


def assert_route(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 2020 <= data["season_year"] <= 2100
    assert_status_in(data, RouteStatus)
    assert data["stop_count"] >= 0
    assert data["total_haul_miles"] >= 0
    assert_two_decimal_hours(data["total_travel_hours"], "total_travel_hours")
    assert_whole_cents(data["total_guaranteed_cents"], "total_guaranteed_cents")
    assert data["closed_stop_count"] >= 0


def assert_route_stop(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["venue_id"])
    for stamp in ("load_in_start", "open_date", "close_date", "teardown_deadline"):
        assert is_iso8601_timestamp(data[stamp]), f"{stamp} must be ISO 8601 UTC"
    assert_status_in(data, RouteStopStatus)
    assert_status_in(data, CompliancePosture, field="compliance_posture")
    assert data["operating_days"] >= 1
    assert_two_decimal_hours(
        data["travel_hours_from_previous"], "travel_hours_from_previous"
    )
    assert data["allocated_sqft_used"] >= 0
    assert isinstance(data["allocated_sqft_used"], int), (
        "allocated_sqft_used must be a whole number of square feet"
    )
    assert_one_decimal_amps(data["power_amps_used"], "power_amps_used")
    assert_whole_cents(
        data["labor_cost_provisional_cents"], "labor_cost_provisional_cents"
    )
    assert data["operating_ride_count"] >= 0
    assert_two_decimal_hours(
        data["closure_hours_adjudicated"], "closure_hours_adjudicated"
    )


def assert_contract(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["route_stop_id"])
    assert isinstance(data["counterparty_name"], str) and len(data["counterparty_name"]) > 0
    assert 20 <= data["revenue_split_pct_operator"] <= 70
    assert_whole_cents(data["guarantee_cents"], "guarantee_cents")
    assert data["guarantee_cents"] >= 0
    assert data["ride_minimum_count"] >= 0
    assert data["exclusivity"] in ("NONE", "RIDES", "FOOD", "FULL")
    assert data["settlement_basis"] in ("GREATER_OF", "SPLIT_ONLY")
    assert_status_in(data, ContractStatus)
    assert 0 <= data["negotiation_round"] <= 2


def assert_ride(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["ride_class"] in ("MAJOR", "FLAT", "KIDDIE")
    assert data["footprint_sqft"] > 0
    assert data["power_amps"] > 0
    assert data["crew_size_setup"] >= 1
    assert data["setup_hours"] > 0
    assert data["axle_count"] >= 1
    assert isinstance(data["requires_state_inspection"], bool)
    assert_status_in(data, RideStatus)


def assert_ride_allocation(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["ride_id"])
    assert is_valid_uuid(data["route_stop_id"])
    assert_status_in(data, RideAllocationStatus)
    assert isinstance(data["footprint_charged_sqft"], int), (
        "footprint_charged_sqft must be a whole number of square feet"
    )
    assert data["footprint_charged_sqft"] > 0
    assert_one_decimal_amps(data["power_charged_amps"], "power_charged_amps")
    assert is_iso8601_timestamp(data["occupation_start"])
    assert is_iso8601_timestamp(data["occupation_end"])


def assert_permit_application(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["route_stop_id"])
    assert data["permit_type"] in ("EVENT", "TRANSPORT", "ELECTRICAL", "HOUSING")
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["valid_until"] > data["valid_from"], (
        "valid_until must be strictly later than valid_from"
    )
    assert data["axles_declared"] >= 0
    assert_whole_cents(data["fee_cents"], "fee_cents")
    assert_status_in(data, PermitStatus)


def assert_inspection_order(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["ride_allocation_id"])
    assert data["authority"] in ("STATE", "THIRD_PARTY")
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert_status_in(data, InspectionStatus)
    assert data["attempt_number"] >= 1
    assert data["defect_count"] >= 0


def assert_worker(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["employment_type"] in ("PERMANENT", "SEASONAL_DOMESTIC", "H2B_VISA")
    assert data["hourly_rate_cents"] > 0
    assert isinstance(data["certified_ride_classes"], list)
    for ride_class in data["certified_ride_classes"]:
        assert ride_class in ("MAJOR", "FLAT", "KIDDIE")
    assert isinstance(data["housing_required"], bool)
    assert_status_in(data, WorkerComplianceStatus, field="compliance_status")
    assert_two_decimal_hours(data["scheduled_hours_total"], "scheduled_hours_total")
    assert data["worked_days_count"] >= 0
    if data["employment_type"] != "H2B_VISA":
        assert data.get("visa_expires_on") is None, (
            "visa_expires_on must be null for a worker who is not on an H-2B visa"
        )


def assert_crew_assignment(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["route_stop_id"])
    assert is_valid_uuid(data["worker_id"])
    assert data["crew_role"] in ("SETUP", "RIDE_OPERATOR", "TEARDOWN", "TICKETING")
    assert is_iso8601_timestamp(data["shift_start"])
    assert is_iso8601_timestamp(data["shift_end"])
    assert data["shift_end"] > data["shift_start"], (
        "shift_end must be strictly later than shift_start"
    )
    assert_status_in(data, CrewAssignmentStatus)
    assert_two_decimal_hours(data["shift_hours"], "shift_hours")
    assert_whole_cents(data["cost_cents"], "cost_cents")
    assert isinstance(data["housing_pad_assigned"], bool)


def assert_ticket_sale(data: dict) -> None:
    """A sales batch carries only `id` and `created_at` — no `updated_at`, no
    `version` — and no operation in the system mutates one after it is written."""
    assert_identity_fields(data)
    assert "updated_at" not in data, (
        "a ticket-sale record has no updated_at field"
    )
    assert "version" not in data, "a ticket-sale record has no version field"
    assert is_valid_uuid(data["route_stop_id"])
    assert data["channel"] in ("WRISTBAND", "SINGLE", "PRESALE", "COMP")
    assert data["units"] > 0
    assert data["unit_price_cents"] >= 0
    assert_whole_cents(data["gross_cents"], "gross_cents")
    assert data["gross_cents"] == data["units"] * data["unit_price_cents"], (
        "gross_cents must be units multiplied by unit_price_cents"
    )


def assert_settlement(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert_status_in(data, SettlementStatus)
    assert_status_in(data, SettlementVariant, field="variant")
    for field in (
        "gross_cents",
        "tax_cents",
        "taxable_net_cents",
        "split_share_cents",
        "shortfall_penalty_cents",
        "guarantee_effective_cents",
        "makegood_deduction_cents",
        "settlement_due_cents",
    ):
        assert_whole_cents(data[field], field)
    assert data["taxable_net_cents"] == data["gross_cents"] - data["tax_cents"], (
        "taxable_net_cents must be gross_cents less tax_cents"
    )
    assert data["effective_operator_pct"] <= 72.5, (
        "effective_operator_pct is capped at 72.5"
    )
    assert data["settlement_due_cents"] >= 0, (
        "settlement_due_cents is floored at zero"
    )


def assert_weather_closure(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["route_stop_id"])
    assert data["cause"] in ("WIND", "RAIN", "LIGHTNING", "HEAT")
    assert is_iso8601_timestamp(data["closed_from"])
    assert is_iso8601_timestamp(data["closed_to"])
    assert data["closed_to"] > data["closed_from"], (
        "closed_to must be strictly later than closed_from"
    )
    assert_two_decimal_hours(data["closure_hours_raw"], "closure_hours_raw")
    assert_two_decimal_hours(data["abated_hours"], "abated_hours")
    assert_status_in(data, WeatherClosureStatus)


def assert_make_good_arrangement(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["weather_closure_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["kind"] in ("CASH_REFUND", "SPONSOR_CREDIT", "BONUS_DAY")
    assert_whole_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] >= 0
    assert_status_in(data, MakeGoodStatus)


def assert_readiness(data: dict) -> None:
    assert is_valid_uuid(data["route_stop_id"])
    assert_status_in(data, CompliancePosture, field="compliance_posture")
    assert isinstance(data["event_permit_ok"], bool)
    assert isinstance(data["inspections_ok"], bool)
    assert isinstance(data["crew_coverage_ok"], bool)
    assert data["committed_ride_count"] >= 0
    assert data["ride_minimum_required"] >= 0
    if data["compliance_posture"] == CompliancePosture.CLEAR.value:
        assert data["blocking_error_id"] is None, (
            "there is no blocking error when the posture is CLEAR"
        )
    else:
        assert isinstance(data["blocking_error_id"], str) and data["blocking_error_id"], (
            "a held posture must name the blocking error it would raise"
        )


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_lot_ledgers(stop: dict, expected_sqft: int, expected_amps: float) -> None:
    """The lot's footprint and power ledgers read exactly the charged totals."""
    assert stop["allocated_sqft_used"] == expected_sqft, (
        f"Expected allocated_sqft_used {expected_sqft}, "
        f"got {stop['allocated_sqft_used']}"
    )
    assert stop["power_amps_used"] == expected_amps, (
        f"Expected power_amps_used {expected_amps}, got {stop['power_amps_used']}"
    )


def assert_labor_ledger(stop: dict, expected_cents: int) -> None:
    assert stop["labor_cost_provisional_cents"] == expected_cents, (
        f"Expected labor_cost_provisional_cents {expected_cents}, "
        f"got {stop['labor_cost_provisional_cents']}"
    )


def assert_guarantee_ledger(route: dict, expected_cents: int) -> None:
    assert route["total_guaranteed_cents"] == expected_cents, (
        f"Expected total_guaranteed_cents {expected_cents}, "
        f"got {route['total_guaranteed_cents']}"
    )


def assert_settlement_amounts(settlement: dict, **expected) -> None:
    """Compare a settlement row against a set of expected computed amounts."""
    for field, value in expected.items():
        assert settlement[field] == value, (
            f"Expected {field} {value}, got {settlement[field]}"
        )
