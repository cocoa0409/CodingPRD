"""Unit li_status cycling, lease occupancy overlap, the available-unit rule, and market leasing.

Translates queue A (Difficulty) instances non_linear_state_machine/unit_li_status_cycle and
resource_temporal_overlap/lease_half_open_zero_buffer, plus queue B (Corner) available-unit
and market-consistency instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_project_building,
    make_qualified_unit,
    make_over_income_unit,
    create_unit,
    create_household,
    lease_payload,
)
from test_helpers import api_client

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]


# ─── Difficulty: unit li_status QUALIFIED <-> OVER_INCOME cycle ──

def test_recert_over_income_moves_qualified_to_over_income(api):
    """PRD §3.3: "Approving a `RECERT` certification whose `is_over_income` is true transitions
    the unit's `li_status` from `QUALIFIED` to `OVER_INCOME`. The unit remains counted as
    low-income in this state (its `is_low_income_counted` stays true), but this transition
    **arms the available-unit rule** for the building: the next available comparable-or-smaller
    unit must be rented to a qualified household."

    Design: Difficulty/non_linear_state_machine/unit_li_status_cycle_qualified_over_income_qualified
    """
    project, building, unit, household = make_qualified_unit(
        unit_overrides={
            "unit_number": "U2",
            "bedroom_count": 2,
            "sqft": 1_000,
            "utility_allowance_cents": 12_500,
            "ami_designation": "AMI_60",
        },
        initial_income_cents=4_000_000,
    )
    assert unit["li_status"] == "QUALIFIED"
    # RECERT income 8_000_000 > over140 7_257_600 -> over-income.
    over = get_success_data(
        api.create_certification(
            {
                "household_id": household["id"],
                "unit_id": unit["id"],
                "cert_type": "RECERT",
                "annual_income_cents": 8_000_000,
                "effective_date": "2027-01-15T00:00:00Z",
            },
            OWNER,
        )
    )
    get_success_data(api.submit_certification(over["id"], OWNER))
    get_success_data(api.approve_certification(over["id"], {"decision": "APPROVE"}, HFA))
    unit_after = get_success_data(api.get_unit(unit["id"], OWNER))
    assert unit_after["li_status"] == "OVER_INCOME"
    assert unit_after["is_low_income_counted"] is True


def test_recert_no_longer_over_income_returns_over_income_to_qualified(api):
    """PRD §3.3: "Approving a `RECERT` certification whose `is_over_income` is false on a unit
    currently in `OVER_INCOME` transitions the unit's `li_status` from `OVER_INCOME` back to
    `QUALIFIED`, which disarms that unit's contribution to the available-unit rule."

    Design: Difficulty/non_linear_state_machine/unit_li_status_cycle_qualified_over_income_qualified
    """
    project, building, unit, household = make_over_income_unit(
        unit_overrides={
            "unit_number": "U2",
            "bedroom_count": 2,
            "sqft": 1_000,
            "utility_allowance_cents": 12_500,
            "ami_designation": "AMI_60",
        },
        initial_income_cents=4_000_000,
        recert_income_cents=8_000_000,  # > over140 7_257_600 -> OVER_INCOME
    )
    assert unit["li_status"] == "OVER_INCOME"
    # A later RECERT at 6_000_000 <= over140 7_257_600 -> not over-income -> back to QUALIFIED.
    back = get_success_data(
        api.create_certification(
            {
                "household_id": household["id"],
                "unit_id": unit["id"],
                "cert_type": "RECERT",
                "annual_income_cents": 6_000_000,
                "effective_date": "2028-01-15T00:00:00Z",
            },
            OWNER,
        )
    )
    get_success_data(api.submit_certification(back["id"], OWNER))
    get_success_data(api.approve_certification(back["id"], {"decision": "APPROVE"}, HFA))
    unit_after = get_success_data(api.get_unit(unit["id"], OWNER))
    assert unit_after["li_status"] == "QUALIFIED"
    assert unit_after["is_low_income_counted"] is True


# ─── Difficulty: lease half-open zero-buffer overlap ──

def _market_unit_with_household():
    project, building = setup_project_building()
    unit = create_unit(
        building["id"],
        unit_number="M1",
        bedroom_count=1,
        sqft=1_000,
        utility_allowance_cents=9_000,
        ami_designation="MARKET",
    )
    household = create_household(project["id"])
    return unit, household


def test_overlapping_lease_rejected_half_open(api):
    """PRD §3.4: "A new lease overlaps an existing `ACTIVE` lease on the same unit when the
    new start is before the existing end and the existing start is before the new end; in that
    case the new lease is rejected with `ERR_LEASE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_half_open_zero_buffer_overlap_on_unit
    """
    unit, household = _market_unit_with_household()
    get_success_data(
        api.lease_unit(
            unit["id"],
            lease_payload(
                household["id"],
                monthly_rent_cents=150_000,
                rent_start_date="2026-01-01T00:00:00Z",
                rent_end_date="2026-06-01T00:00:00Z",
            ),
            OWNER,
        )
    )
    res = api.lease_unit(
        unit["id"],
        lease_payload(
            household["id"],
            monthly_rent_cents=150_000,
            rent_start_date="2026-05-01T00:00:00Z",  # overlaps [2026-01-01, 2026-06-01)
            rent_end_date="2026-12-01T00:00:00Z",
        ),
        OWNER,
    )
    validate_error(res, "ERR_LEASE_OVERLAP", expected_status=409)


def test_back_to_back_lease_at_prior_end_accepted(api):
    """PRD §3.4: "Because the interval is half-open with zero buffer, a back-to-back lease
    that begins exactly at a prior lease's `rent_end_date` does not overlap and is permitted."

    Design: Difficulty/resource_temporal_overlap/lease_half_open_zero_buffer_overlap_on_unit
    """
    unit, household = _market_unit_with_household()
    get_success_data(
        api.lease_unit(
            unit["id"],
            lease_payload(
                household["id"],
                monthly_rent_cents=150_000,
                rent_start_date="2026-01-01T00:00:00Z",
                rent_end_date="2026-06-01T00:00:00Z",
            ),
            OWNER,
        )
    )
    res = api.lease_unit(
        unit["id"],
        lease_payload(
            household["id"],
            monthly_rent_cents=150_000,
            rent_start_date="2026-06-01T00:00:00Z",  # exactly the prior rent_end_date
            rent_end_date="2026-12-01T00:00:00Z",
        ),
        OWNER,
    )
    lease = validate_success(res, 201)
    assert lease["status"] == "ACTIVE"


# ─── Corner: available-unit rule ──────────────────────

def test_available_unit_rule_blocks_market_lease_while_over_income_exists(api):
    """PRD §3.4: "while any unit in the building is in `OVER_INCOME` status, a
    comparable-or-smaller unit — one whose `bedroom_count` is less than or equal to the
    over-income unit's `bedroom_count` — may not be leased to a non-qualified household (a
    `MARKET` household or a student-ineligible one); such a lease is rejected with
    `ERR_AVAILABLE_UNIT_RULE`."

    Design: Corner/validations/available_unit_rule_blocks_market_lease_while_over_income_exists
    """
    # Over-income AMI_50 br1 unit in the building.
    project, building, oi_unit, _hh1 = make_over_income_unit(
        unit_overrides={
            "unit_number": "U_oi",
            "bedroom_count": 1,
            "sqft": 1_000,
            "utility_allowance_cents": 9_000,
            "ami_designation": "AMI_50",
        },
        initial_income_cents=3_000_000,
        recert_income_cents=6_000_000,  # > over140 5_376_000 -> OVER_INCOME
    )
    assert oi_unit["li_status"] == "OVER_INCOME"
    # Comparable MARKET br1 unit + a non-qualified household to lease it.
    market_unit = create_unit(
        building["id"],
        unit_number="U_mkt",
        bedroom_count=1,
        sqft=1_000,
        utility_allowance_cents=9_000,
        ami_designation="MARKET",
    )
    h2 = create_household(project["id"])
    res = api.lease_unit(
        market_unit["id"],
        lease_payload(
            h2["id"],
            monthly_rent_cents=150_000,
            rent_start_date="2027-03-01T00:00:00Z",
            rent_end_date="2028-03-01T00:00:00Z",
        ),
        OWNER,
    )
    validate_error(res, "ERR_AVAILABLE_UNIT_RULE", expected_status=409)


# ─── Corner: market unit lease immediate consistency ──

def test_market_unit_lease_sets_market_rented_immediately(api):
    """PRD §3.4: "Leasing a `MARKET` unit transitions that unit's `li_status` from
    `VACANT_NEVER_OCCUPIED` to `MARKET_RENTED`."

    Design: Corner/consistency_model/market_unit_lease_sets_market_rented_immediately
    """
    unit, household = _market_unit_with_household()
    res = api.lease_unit(
        unit["id"],
        lease_payload(
            household["id"],
            monthly_rent_cents=150_000,
            rent_start_date="2026-02-01T00:00:00Z",
            rent_end_date="2027-02-01T00:00:00Z",
        ),
        OWNER,
    )
    validate_success(res, 201)
    unit_after = get_success_data(api.get_unit(unit["id"], OWNER))
    assert unit_after["li_status"] == "MARKET_RENTED"
    assert unit_after["is_low_income_counted"] is False
