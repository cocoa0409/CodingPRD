"""Per-resource shape assertions and domain invariant checkers."""

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CIRCUIT_FEE_TIER_1_MAX_CENTS,
    CIRCUIT_FEE_TIER_1_PCT,
    CIRCUIT_FEE_TIER_2_MAX_CENTS,
    CIRCUIT_FEE_TIER_2_PCT,
    CIRCUIT_FEE_TIER_3_PCT,
    DIETARY_UNIT_CENTS,
    MEALS_PER_STOP,
    PLACEMENT_SHARE_DEFAULT_PCT,
    PLACEMENT_SHARE_PCT,
)

_TIMESTAMP_3_FRACTIONAL = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|[+-]\d{2}:\d{2})$"
)


# ------------------------------------------------------------------- utilities
def round_half_up(value) -> int:
    """Round to a whole cent, half away from zero upward."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount: int, pct: float) -> int:
    """A percentage of an integer-cent aggregate, rounded half up once."""
    return round_half_up(Decimal(str(amount)) * Decimal(str(pct)))


def circuit_fee_pct(gross_cents: int) -> float:
    """The circuit fee rate the full gross selects."""
    if gross_cents < CIRCUIT_FEE_TIER_1_MAX_CENTS:
        return CIRCUIT_FEE_TIER_1_PCT
    if gross_cents < CIRCUIT_FEE_TIER_2_MAX_CENTS:
        return CIRCUIT_FEE_TIER_2_PCT
    return CIRCUIT_FEE_TIER_3_PCT


def circuit_fee_cents(gross_cents: int) -> int:
    return pct_of(gross_cents, circuit_fee_pct(gross_cents))


def placement_share_pct(placement: int) -> float:
    return PLACEMENT_SHARE_PCT.get(placement, PLACEMENT_SHARE_DEFAULT_PCT)


def prize_cents(prize_pool_cents: int, placement: int) -> int:
    return pct_of(prize_pool_cents, placement_share_pct(placement))


def meal_cost_cents(head_counts_by_dietary_flag: Dict[str, int]) -> int:
    """Per-class already-rounded unit multiplied by heads and meals, then summed."""
    total = 0
    for flag, heads in head_counts_by_dietary_flag.items():
        total += DIETARY_UNIT_CENTS[flag] * heads * MEALS_PER_STOP
    return total


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def travel_minutes(miles: int, avg_mph: int = 45, fuel_stop_miles: int = 200,
                   fuel_stop_minutes: int = 30) -> int:
    """Drive component rounded up, plus fuel stops rounded down."""
    if miles <= 0:
        return 0
    drive = math.ceil(miles / avg_mph * 60)
    fuel = (miles // fuel_stop_miles) * fuel_stop_minutes
    return drive + fuel


def normalize_instant(value: Optional[str]) -> Optional[str]:
    """Strip fractional seconds and normalise the zone so instants compare."""
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, tail = text.split(".", 1)
        zone = ""
        for marker in ("+", "-"):
            idx = tail.find(marker)
            if idx != -1:
                zone = tail[idx:]
                break
        text = head + zone
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    elif not text.endswith("Z"):
        text = text + "Z"
    return text


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity.get('id')!r}"
    for field in ("created_at", "updated_at"):
        value = entity.get(field)
        assert isinstance(value, str) and is_iso8601_timestamp(value), (
            f"{field} must be an ISO 8601 timestamp, got {value!r}"
        )
        assert _TIMESTAMP_3_FRACTIONAL.match(value), (
            f"{field} must carry exactly three fractional digits, got {value!r}"
        )
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_no_id_prefix(entity: Dict[str, Any]) -> None:
    assert "_" not in entity["id"], "ids carry no type prefix"


def _assert_fields(entity: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for key, want in expected.items():
        assert key in entity, f"{label} is missing {key}"
        got = entity[key]
        assert got == want, f"{label}.{key}: expected {want!r}, got {got!r}"


# --------------------------------------------------------------- per-resource
def assert_season(season: Dict[str, Any], **expected) -> None:
    assert_common_fields(season, expected.pop("version", None))
    for field in (
        "name",
        "year",
        "tuition_base_cents",
        "spring_training_start_date",
        "spring_training_end_date",
        "tour_departure_date",
        "billing_epoch",
        "tuition_charged_cents",
        "tuition_collected_cents",
        "late_fee_collected_cents",
        "housing_cost_cents",
        "tour_revenue_cents",
        "ledger_status",
    ):
        assert field in season, f"season is missing {field}"
    _assert_fields(season, expected, "season")


def assert_member(member: Dict[str, Any], **expected) -> None:
    assert_common_fields(member, expected.pop("version", None))
    for field in (
        "season_id",
        "full_name",
        "email",
        "date_of_birth",
        "section",
        "dietary_flag",
        "is_minor",
        "membership_status",
        "medical_status",
        "tuition_charged_cents",
        "tuition_paid_cents",
        "tuition_balance_cents",
        "refund_due_cents",
        "withdrawal_obligation_basis",
    ):
        assert field in member, f"member is missing {field}"
    _assert_fields(member, expected, "member")


def assert_member_contract(contract: Dict[str, Any], **expected) -> None:
    assert_common_fields(contract, expected.pop("version", None))
    for field in (
        "member_id",
        "tuition_amount_cents",
        "payment_plan_type",
        "status",
        "revision_round",
    ):
        assert field in contract, f"contract is missing {field}"
    _assert_fields(contract, expected, "contract")


def assert_payment_plan(plan: Dict[str, Any], **expected) -> None:
    assert_common_fields(plan, expected.pop("version", None))
    for field in (
        "member_id",
        "member_contract_id",
        "plan_type",
        "principal_cents",
        "surcharge_cents",
        "financed_total_cents",
        "installment_count",
        "installment_base_cents",
        "installment_remainder_cents",
        "first_due_date",
        "status",
        "delinquency_strikes",
        "principal_paid_cents",
        "late_fee_accrued_cents",
        "late_fee_paid_cents",
        "installments_due_count",
        "due_amount_cents",
        "arrears_cents",
        "outstanding_cents",
    ):
        assert field in plan, f"plan is missing {field}"
    _assert_fields(plan, expected, "plan")


def assert_tuition_payment(payment: Dict[str, Any], **expected) -> None:
    assert_common_fields(payment, expected.pop("version", None))
    for field in (
        "payment_plan_id",
        "amount_cents",
        "received_on",
        "method",
        "allocated_to_late_fee_cents",
        "allocated_to_principal_cents",
        "status",
    ):
        assert field in payment, f"payment is missing {field}"
    _assert_fields(payment, expected, "payment")
    assert (
        payment["allocated_to_late_fee_cents"]
        + payment["allocated_to_principal_cents"]
        == payment["amount_cents"]
    ), "the two allocations must sum exactly to the tendered amount"


def assert_host_school(school: Dict[str, Any], **expected) -> None:
    assert_common_fields(school, expected.pop("version", None))
    for field in (
        "name",
        "city",
        "state_code",
        "sleeping_space_count",
        "capacity_per_space",
        "rehearsal_field_count",
        "has_air_conditioning",
        "booked_block_count",
        "reserved_bed_nights",
    ):
        assert field in school, f"host school is missing {field}"
    _assert_fields(school, expected, "host school")


def assert_facility_agreement(agreement: Dict[str, Any], **expected) -> None:
    assert_common_fields(agreement, expected.pop("version", None))
    for field in (
        "host_school_id",
        "season_id",
        "usage_type",
        "start_date",
        "end_date",
        "nightly_rate_cents",
        "minimum_billable_beds",
        "status",
        "counter_round",
        "occupied_bed_nights",
        "billable_bed_nights",
        "billable_cents",
    ):
        assert field in agreement, f"agreement is missing {field}"
    _assert_fields(agreement, expected, "agreement")


def assert_housing_assignment(assignment: Dict[str, Any], **expected) -> None:
    assert_common_fields(assignment, expected.pop("version", None))
    for field in (
        "facility_agreement_id",
        "member_id",
        "space_index",
        "check_in_date",
        "check_out_date",
        "nights",
        "occupant_is_minor",
        "status",
    ):
        assert field in assignment, f"housing assignment is missing {field}"
    _assert_fields(assignment, expected, "housing assignment")


def assert_tour_stop(stop: Dict[str, Any], **expected) -> None:
    assert_common_fields(stop, expected.pop("version", None))
    for field in (
        "season_id",
        "stop_type",
        "venue_name",
        "city",
        "state_code",
        "arrive_at",
        "depart_at",
        "travel_miles_from_previous",
        "uniform_trunks",
        "instrument_cases",
        "prop_units",
        "truck_count",
        "rehearsal_minutes",
        "heat_index_f",
        "total_load_cuft",
        "total_load_lbs",
        "trucks_required",
        "required_travel_minutes",
        "roster_head_count",
        "minor_head_count",
        "required_chaperone_count",
        "required_cook_count",
        "meal_cost_cents",
        "status",
        "settlement_state",
    ):
        assert field in stop, f"tour stop is missing {field}"
    _assert_fields(stop, expected, "tour stop")


def assert_site_booking(booking: Dict[str, Any], **expected) -> None:
    assert_common_fields(booking, expected.pop("version", None))
    for field in (
        "tour_stop_id",
        "host_school_id",
        "facility_agreement_id",
        "block_start_at",
        "block_end_at",
        "indoor",
        "status",
    ):
        assert field in booking, f"site booking is missing {field}"
    _assert_fields(booking, expected, "site booking")


def assert_volunteer(volunteer: Dict[str, Any], **expected) -> None:
    assert_common_fields(volunteer, expected.pop("version", None))
    for field in (
        "full_name",
        "email",
        "role_type",
        "screening_status",
        "assignment_count",
    ):
        assert field in volunteer, f"volunteer is missing {field}"
    _assert_fields(volunteer, expected, "volunteer")


def assert_staff_assignment(assignment: Dict[str, Any], **expected) -> None:
    assert_common_fields(assignment, expected.pop("version", None))
    for field in (
        "volunteer_id",
        "tour_stop_id",
        "duty",
        "shift_start_at",
        "shift_end_at",
        "status",
    ):
        assert field in assignment, f"staff assignment is missing {field}"
    _assert_fields(assignment, expected, "staff assignment")


def assert_show_settlement(settlement: Dict[str, Any], **expected) -> None:
    assert_common_fields(settlement, expected.pop("version", None))
    for field in (
        "tour_stop_id",
        "appearance_fee_cents",
        "prize_pool_cents",
        "projected_placement",
        "provisional_prize_cents",
        "provisional_gross_cents",
        "provisional_circuit_fee_cents",
        "provisional_net_cents",
        "remittance_line_count",
        "status",
        "prepared_by_user_id",
    ):
        assert field in settlement, f"settlement is missing {field}"
    _assert_fields(settlement, expected, "settlement")


# ------------------------------------------------------- domain invariants
def assert_housing_chain(
    agreement: Dict[str, Any],
    school: Dict[str, Any],
    season: Dict[str, Any],
    occupied_bed_nights: int,
    billable_bed_nights: int,
    billable_cents: int,
    reserved_bed_nights: int,
    housing_cost_cents: int,
) -> None:
    """Every link of the housing chain, from stay to season rollup."""
    assert agreement["occupied_bed_nights"] == occupied_bed_nights, (
        f"agreement.occupied_bed_nights: expected {occupied_bed_nights}, "
        f"got {agreement['occupied_bed_nights']}"
    )
    assert agreement["billable_bed_nights"] == billable_bed_nights, (
        f"agreement.billable_bed_nights: expected {billable_bed_nights}, "
        f"got {agreement['billable_bed_nights']}"
    )
    assert agreement["billable_cents"] == billable_cents, (
        f"agreement.billable_cents: expected {billable_cents}, "
        f"got {agreement['billable_cents']}"
    )
    assert school["reserved_bed_nights"] == reserved_bed_nights, (
        f"school.reserved_bed_nights: expected {reserved_bed_nights}, "
        f"got {school['reserved_bed_nights']}"
    )
    assert season["housing_cost_cents"] == housing_cost_cents, (
        f"season.housing_cost_cents: expected {housing_cost_cents}, "
        f"got {season['housing_cost_cents']}"
    )


def assert_tuition_chain(
    plan: Dict[str, Any],
    member: Dict[str, Any],
    season: Dict[str, Any],
    principal_paid_cents: int,
    late_fee_paid_cents: int,
    arrears_cents: int,
    outstanding_cents: int,
    tuition_paid_cents: int,
    tuition_balance_cents: int,
    tuition_collected_cents: int,
    late_fee_collected_cents: int,
) -> None:
    """Plan, member and season legs of the tuition chain in one place."""
    assert plan["principal_paid_cents"] == principal_paid_cents
    assert plan["late_fee_paid_cents"] == late_fee_paid_cents
    assert plan["arrears_cents"] == arrears_cents
    assert plan["outstanding_cents"] == outstanding_cents
    assert member["tuition_paid_cents"] == tuition_paid_cents
    assert member["tuition_balance_cents"] == tuition_balance_cents
    assert season["tuition_collected_cents"] == tuition_collected_cents
    assert season["late_fee_collected_cents"] == late_fee_collected_cents


def assert_all_nulls(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity.get(field, "__missing__") is None, (
            f"{field} must be null, got {entity.get(field)!r}"
        )
