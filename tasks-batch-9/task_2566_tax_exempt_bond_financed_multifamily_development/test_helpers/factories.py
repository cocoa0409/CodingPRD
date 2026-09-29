"""Payload builders for the rows the tests keep needing.

Every builder returns a plain dict of request fields, so a test may override any
one of them inline. Nothing here talks to the API; the fixtures do that.

The two unit rosters are calibrated, not arbitrary. The four-unit roster puts
half the units and exactly half the floor space under restriction, so the unit
fraction, the floor-space fraction and the applicable fraction all read 5,000
basis points. The ten-unit roster deliberately splits them: four of ten units is
4,000 basis points, but 3,350 of 8,500 square feet is only 3,941, so the
applicable fraction has to pick the smaller of the two.
"""

from . import constants


def developer_payload(name=constants.SPONSOR_NAME, tax_id=constants.SPONSOR_TAX_ID,
                      contact_email=constants.SPONSOR_EMAIL, **overrides):
    payload = {"name": name, "tax_id": tax_id, "contact_email": contact_email}
    payload.update(overrides)
    return payload


def second_developer_payload(**overrides):
    """A second, unrelated sponsor — the foreign owner in ownership probes."""
    payload = {
        "name": constants.SECOND_SPONSOR_NAME,
        "tax_id": constants.SECOND_SPONSOR_TAX_ID,
        "contact_email": constants.SECOND_SPONSOR_EMAIL,
    }
    payload.update(overrides)
    return payload


def investor_payload(name=constants.INVESTOR_NAME, tax_id=constants.INVESTOR_TAX_ID,
                     investor_type=constants.INVESTOR_TYPE, **overrides):
    payload = {"name": name, "tax_id": tax_id, "investor_type": investor_type}
    payload.update(overrides)
    return payload


def second_investor_payload(**overrides):
    payload = {
        "name": constants.SECOND_INVESTOR_NAME,
        "tax_id": constants.SECOND_INVESTOR_TAX_ID,
        "investor_type": "FUND",
    }
    payload.update(overrides)
    return payload


def cap_pool_payload(program_year=constants.PROGRAM_YEAR,
                     base_cap_cents=constants.POOL_BASE_CAP_CENTS,
                     carryforward_cents=constants.POOL_CARRYFORWARD_CENTS, **overrides):
    """The canonical pool: 500,000,000 of base cap plus 100,000,000 carried forward."""
    payload = {
        "program_year": program_year,
        "base_cap_cents": base_cap_cents,
        "carryforward_cents": carryforward_cents,
    }
    payload.update(overrides)
    return payload


def compact_project_payload(developer_id, **overrides):
    """The four-unit development, aggregate basis 400,000,000."""
    payload = {
        "developer_id": developer_id,
        "name": constants.COMPACT_PROJECT_NAME,
        "total_units": constants.COMPACT_TOTAL_UNITS,
        "total_floor_space_sqft": constants.COMPACT_TOTAL_FLOOR_SPACE_SQFT,
        "land_cost_cents": constants.COMPACT_LAND_COST_CENTS,
        "depreciable_basis_cents": constants.COMPACT_DEPRECIABLE_BASIS_CENTS,
        "set_aside_election": "MIN_40_60",
    }
    payload.update(overrides)
    return payload


def ten_unit_project_payload(developer_id, **overrides):
    """The ten-unit development, aggregate basis 400,000,000."""
    payload = {
        "developer_id": developer_id,
        "name": constants.TEN_UNIT_PROJECT_NAME,
        "total_units": constants.TEN_UNIT_TOTAL_UNITS,
        "total_floor_space_sqft": constants.TEN_UNIT_TOTAL_FLOOR_SPACE_SQFT,
        "land_cost_cents": constants.TEN_UNIT_LAND_COST_CENTS,
        "depreciable_basis_cents": constants.TEN_UNIT_DEPRECIABLE_BASIS_CENTS,
        "set_aside_election": "MIN_40_60",
    }
    payload.update(overrides)
    return payload


def unit_payload(project_id, unit_number, bedroom_count=2, floor_space_sqft=800,
                 designation="RESTRICTED", utility_allowance_cents=12000,
                 market_rent_cents=150000, ami_percent=60, **overrides):
    """One unit designation. ``ami_percent`` is dropped for non-restricted rows."""
    payload = {
        "project_id": project_id,
        "unit_number": unit_number,
        "bedroom_count": bedroom_count,
        "floor_space_sqft": floor_space_sqft,
        "designation": designation,
        "utility_allowance_cents": utility_allowance_cents,
        "market_rent_cents": market_rent_cents,
    }
    if designation == "RESTRICTED":
        payload["ami_percent"] = ami_percent
    payload.update(overrides)
    return payload


# Two restricted two-bedrooms of 800 and 900 square feet, then two market
# one-bedrooms of 850 each: 1,700 restricted square feet out of 3,400.
COMPACT_ROSTER = (
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "floor_space_sqft": 800,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "102",
        "bedroom_count": 2,
        "floor_space_sqft": 900,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "201",
        "bedroom_count": 1,
        "floor_space_sqft": 850,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "202",
        "bedroom_count": 1,
        "floor_space_sqft": 850,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
)

# Four restricted two-bedrooms of 700, 800, 900 and 950 square feet — 3,350 in
# all — then six market one-bedrooms filling the remaining 5,150.
TEN_UNIT_ROSTER = (
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "floor_space_sqft": 700,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "102",
        "bedroom_count": 2,
        "floor_space_sqft": 800,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "103",
        "bedroom_count": 2,
        "floor_space_sqft": 900,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "104",
        "bedroom_count": 2,
        "floor_space_sqft": 950,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "201",
        "bedroom_count": 1,
        "floor_space_sqft": 860,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "202",
        "bedroom_count": 1,
        "floor_space_sqft": 860,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "203",
        "bedroom_count": 1,
        "floor_space_sqft": 860,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "204",
        "bedroom_count": 1,
        "floor_space_sqft": 860,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "205",
        "bedroom_count": 1,
        "floor_space_sqft": 860,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
    {
        "unit_number": "206",
        "bedroom_count": 1,
        "floor_space_sqft": 850,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
)


def roster_payloads(project_id, roster):
    """Turn a roster of unit descriptions into request bodies for one development."""
    return [dict(spec, project_id=project_id) for spec in roster]


def agreement_payload(project_id, set_aside_election="MIN_40_60",
                      compliance_period_years=constants.COMPLIANCE_PERIOD_YEARS,
                      extended_use_years=constants.EXTENDED_USE_YEARS,
                      recording_county=constants.RECORDING_COUNTY, **overrides):
    """Fifteen years of compliance and thirty of extended use — the exact minimum gap."""
    payload = {
        "project_id": project_id,
        "set_aside_election": set_aside_election,
        "compliance_period_years": compliance_period_years,
        "extended_use_years": extended_use_years,
        "recording_county": recording_county,
    }
    payload.update(overrides)
    return payload


def cap_request_payload(project_id, cap_pool_id,
                        requested_amount_cents=constants.REQUESTED_AMOUNT_CENTS,
                        requested_closing_date=constants.REQUESTED_CLOSING_DATE,
                        **overrides):
    payload = {
        "project_id": project_id,
        "cap_pool_id": cap_pool_id,
        "requested_amount_cents": requested_amount_cents,
        "requested_closing_date": requested_closing_date,
    }
    payload.update(overrides)
    return payload


def award_payload(expected_cap_pool_version,
                  awarded_amount_cents=constants.AWARDED_AMOUNT_CENTS,
                  expiry_date=constants.AWARD_EXPIRY_DATE, **overrides):
    payload = {
        "decision": "AWARD",
        "expected_cap_pool_version": expected_cap_pool_version,
        "awarded_amount_cents": awarded_amount_cents,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def denial_payload(expected_cap_pool_version, denial_reason="cap oversubscribed",
                   **overrides):
    payload = {
        "decision": "DENY",
        "expected_cap_pool_version": expected_cap_pool_version,
        "denial_reason": denial_reason,
    }
    payload.update(overrides)
    return payload


def bond_issue_payload(project_id, volume_cap_allocation_id,
                       eligible_cost_cents=constants.ELIGIBLE_COST_CENTS,
                       capitalized_interest_cents=constants.CAPITALIZED_INTEREST_CENTS,
                       bond_yield_bps=constants.BOND_YIELD_BPS,
                       investment_yield_bps=constants.INVESTMENT_YIELD_BPS, **overrides):
    """Sizes to a par of exactly 200,000,000 — the awarded amount to the cent."""
    payload = {
        "project_id": project_id,
        "volume_cap_allocation_id": volume_cap_allocation_id,
        "eligible_cost_cents": eligible_cost_cents,
        "capitalized_interest_cents": capitalized_interest_cents,
        "bond_yield_bps": bond_yield_bps,
        "investment_yield_bps": investment_yield_bps,
    }
    payload.update(overrides)
    return payload


def draw_payload(bond_issue_id, expected_bond_issue_version, draw_number=1,
                 period_start=constants.DRAW_PERIOD_START,
                 period_end=constants.DRAW_PERIOD_END,
                 requested_amount_cents=constants.DRAW_AMOUNT_CENTS, **overrides):
    payload = {
        "bond_issue_id": bond_issue_id,
        "draw_number": draw_number,
        "period_start": period_start,
        "period_end": period_end,
        "requested_amount_cents": requested_amount_cents,
        "expected_bond_issue_version": expected_bond_issue_version,
    }
    payload.update(overrides)
    return payload


def operating_month_payload(month_index, noi_cents=constants.MONTH_NOI_CENTS,
                            debt_service_cents=constants.MONTH_DEBT_SERVICE_CENTS,
                            occupied_units=constants.COMPACT_TOTAL_UNITS, **overrides):
    """A month whose coverage is 12,000 basis points and whose building is full."""
    payload = {
        "month_index": month_index,
        "noi_cents": noi_cents,
        "debt_service_cents": debt_service_cents,
        "occupied_units": occupied_units,
    }
    payload.update(overrides)
    return payload


def cost_certification_payload(
    project_id,
    certified_land_cost_cents=constants.CERTIFIED_LAND_COST_CENTS,
    certified_depreciable_basis_cents=constants.CERTIFIED_DEPRECIABLE_BASIS_CENTS,
    certified_eligible_basis_cents=constants.CERTIFIED_ELIGIBLE_BASIS_CENTS,
    preparer_name=constants.PREPARER_NAME,
    **overrides
):
    payload = {
        "project_id": project_id,
        "certified_land_cost_cents": certified_land_cost_cents,
        "certified_depreciable_basis_cents": certified_depreciable_basis_cents,
        "certified_eligible_basis_cents": certified_eligible_basis_cents,
        "preparer_name": preparer_name,
    }
    payload.update(overrides)
    return payload


def credit_allocation_payload(project_id, cost_certification_id,
                             credit_percentage_bps=constants.CREDIT_PERCENTAGE_BPS,
                             placed_in_service_date=constants.PLACED_IN_SERVICE_DATE,
                             **overrides):
    payload = {
        "project_id": project_id,
        "cost_certification_id": cost_certification_id,
        "credit_percentage_bps": credit_percentage_bps,
        "placed_in_service_date": placed_in_service_date,
    }
    payload.update(overrides)
    return payload


def delivery_payload(credit_allocation_id, investor_id,
                     expected_credit_allocation_version,
                     requested_credit_cents=30000000,
                     capital_contribution_cents=25500000, **overrides):
    """A 30,000,000 strip bought for 25,500,000 — 8,500 basis points a credit dollar."""
    payload = {
        "credit_allocation_id": credit_allocation_id,
        "investor_id": investor_id,
        "requested_credit_cents": requested_credit_cents,
        "capital_contribution_cents": capital_contribution_cents,
        "expected_credit_allocation_version": expected_credit_allocation_version,
    }
    payload.update(overrides)
    return payload


def compliance_report_payload(project_id, reporting_year=2027,
                              restricted_units_occupied=2, total_units_occupied=4,
                              average_ami_percent=60, **overrides):
    payload = {
        "project_id": project_id,
        "reporting_year": reporting_year,
        "restricted_units_occupied": restricted_units_occupied,
        "total_units_occupied": total_units_occupied,
        "average_ami_percent": average_ami_percent,
    }
    payload.update(overrides)
    return payload


def inspection_payload(project_id, window_start="2027-06-01T00:00:00Z",
                       window_end="2027-06-15T00:00:00Z",
                       inspector_name="Rowan Vega", **overrides):
    payload = {
        "project_id": project_id,
        "window_start": window_start,
        "window_end": window_end,
        "inspector_name": inspector_name,
    }
    payload.update(overrides)
    return payload
