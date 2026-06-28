"""Unit income/rent-limit arithmetic, the over-income 140% boundary, and rent-ceiling leasing.

Translates queue A (Difficulty) instances combinatorial_formula/rent_ceiling and
boundary_precision_check/over_income, plus queue B (Corner) rent-ceiling lease validations.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_unit_payload,
    lease_payload,
    setup_project_building,
    make_qualified_unit,
    create_unit,
    create_household,
    create_approved_certification,
)
from test_helpers import api_client

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]


# ─── Difficulty: rent-ceiling nested floor order ──────

def test_rent_ceiling_pinned_floor_order_ami60_br2(api):
    """PRD §3.1: "The `income_limit_cents` is then the AMI baseline multiplied by the AMI
    percentage divided by 100, multiplied by the household-size factor divided by 10000, with
    the result floored. The `gross_rent_ceiling_cents` is the `income_limit_cents` multiplied
    by 30, divided by 100, divided by 12, floored — that is, thirty percent of the annual
    income limit expressed as a monthly figure, floored. Finally, the `net_max_rent_cents` is
    the `gross_rent_ceiling_cents` minus the unit's `utility_allowance_cents`."

    Design: Difficulty/combinatorial_formula/rent_ceiling_nested_floor_order_income_then_thirty_then_twelve
    """
    project, building = setup_project_building()
    res = api.create_unit(
        create_unit_payload(
            building["id"],
            unit_number="U2",
            bedroom_count=2,
            sqft=1_000,
            utility_allowance_cents=12_500,
            ami_designation="AMI_60",
        ),
        OWNER,
    )
    unit = validate_success(res, 201)
    assert unit["income_limit_cents"] == 5_184_000
    assert unit["gross_rent_ceiling_cents"] == 129_600
    assert unit["net_max_rent_cents"] == 117_100


def test_rent_ceiling_floor_applied_at_each_step_ami50_br1(api):
    """PRD §2.6: "Where a calculation has several floored steps, each intermediate result is
    floored before it feeds the next step; the flooring is not deferred to the end."

    Design: Difficulty/combinatorial_formula/rent_ceiling_nested_floor_order_income_then_thirty_then_twelve
    """
    project, building = setup_project_building()
    res = api.create_unit(
        create_unit_payload(
            building["id"],
            unit_number="U1",
            bedroom_count=1,
            sqft=1_000,
            utility_allowance_cents=9_000,
            ami_designation="AMI_50",
        ),
        OWNER,
    )
    unit = validate_success(res, 201)
    # income 3_840_000 -> gross floor(3_840_000*30/100/12)=96_000 -> net 96_000-9_000=87_000.
    assert unit["income_limit_cents"] == 3_840_000
    assert unit["gross_rent_ceiling_cents"] == 96_000
    assert unit["net_max_rent_cents"] == 87_000


# ─── Difficulty: over-income 140% strict boundary ─────

def _setup_qualified_ami60_br2_unit():
    """AMI_60 br2 unit (income_limit 5_184_000, over140 7_257_600) made QUALIFIED via an
    approved INITIAL cert at income 4_000_000. Returns (unit, household)."""
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
    return unit, household


def test_over_income_false_at_exactly_140_threshold(api):
    """PRD §3.3: "The `is_over_income` flag is set true only when the `cert_type` is `RECERT`
    and the certified `annual_income_cents` is strictly greater than
    `over_income_threshold_cents`; income exactly equal to 140 percent of the limit is not
    over-income, because the boundary is strict."

    Design: Difficulty/boundary_precision_check/over_income_strict_greater_than_140_threshold
    """
    unit, household = _setup_qualified_ami60_br2_unit()
    cert = get_success_data(
        api.create_certification(
            {
                "household_id": household["id"],
                "unit_id": unit["id"],
                "cert_type": "RECERT",
                "annual_income_cents": 7_257_600,  # exactly the 140% threshold
                "effective_date": "2027-01-15T00:00:00Z",
            },
            OWNER,
        )
    )
    submitted = validate_success(api.submit_certification(cert["id"], OWNER), 200)
    assert submitted["over_income_threshold_cents"] == 7_257_600
    assert submitted["is_over_income"] is False


def test_over_income_true_one_cent_above_140_threshold(api):
    """PRD §3.3: "The `is_over_income` flag is set true only when the `cert_type` is `RECERT`
    and the certified `annual_income_cents` is strictly greater than
    `over_income_threshold_cents`; income exactly equal to 140 percent of the limit is not
    over-income, because the boundary is strict."

    Design: Difficulty/boundary_precision_check/over_income_strict_greater_than_140_threshold
    """
    unit, household = _setup_qualified_ami60_br2_unit()
    cert = get_success_data(
        api.create_certification(
            {
                "household_id": household["id"],
                "unit_id": unit["id"],
                "cert_type": "RECERT",
                "annual_income_cents": 7_257_601,  # threshold + 1
                "effective_date": "2027-01-15T00:00:00Z",
            },
            OWNER,
        )
    )
    submitted = validate_success(api.submit_certification(cert["id"], OWNER), 200)
    assert submitted["over_income_threshold_cents"] == 7_257_600
    assert submitted["is_over_income"] is True


# ─── Corner: rent-ceiling lease validation ────────────

def test_lease_rent_over_net_max_returns_rent_over_limit(api):
    """PRD §3.4: "The tenant-paid `monthly_rent_cents` must not exceed the unit's
    `net_max_rent_cents` (the unit's net rent ceiling, already net of the utility allowance);
    a lease whose rent is above that ceiling is rejected with `ERR_RENT_OVER_LIMIT`, the
    rent-plus-utility-allowance overcharge guard."

    Design: Corner/validations/lease_rent_over_net_max_returns_rent_over_limit
    """
    project, building = setup_project_building()
    unit = create_unit(
        building["id"],
        unit_number="U1",
        bedroom_count=1,
        sqft=1_000,
        utility_allowance_cents=9_000,
        ami_designation="AMI_50",
    )
    household = create_household(project["id"])
    res = api.lease_unit(
        unit["id"],
        lease_payload(
            household["id"],
            monthly_rent_cents=90_000,  # net_max_rent_cents is 87_000
            rent_start_date="2026-02-01T00:00:00Z",
            rent_end_date="2027-02-01T00:00:00Z",
        ),
        OWNER,
    )
    validate_error(res, "ERR_RENT_OVER_LIMIT", expected_status=422)


def test_lease_at_exactly_net_max_rent_succeeds(api):
    """PRD §3.4: "The tenant-paid `monthly_rent_cents` must not exceed the unit's
    `net_max_rent_cents` (the unit's net rent ceiling, already net of the utility allowance);
    a lease whose rent is above that ceiling is rejected with `ERR_RENT_OVER_LIMIT`, the
    rent-plus-utility-allowance overcharge guard."

    Design: Corner/validations/lease_at_net_max_rent_succeeds
    """
    project, building = setup_project_building()
    unit = create_unit(
        building["id"],
        unit_number="U1",
        bedroom_count=1,
        sqft=1_000,
        utility_allowance_cents=9_000,
        ami_designation="AMI_50",
    )
    household = create_household(project["id"])
    res = api.lease_unit(
        unit["id"],
        lease_payload(
            household["id"],
            monthly_rent_cents=87_000,  # exactly net_max_rent_cents
            rent_start_date="2026-02-01T00:00:00Z",
            rent_end_date="2027-02-01T00:00:00Z",
        ),
        OWNER,
    )
    lease = validate_success(res, 201)
    assert lease["status"] == "ACTIVE"
