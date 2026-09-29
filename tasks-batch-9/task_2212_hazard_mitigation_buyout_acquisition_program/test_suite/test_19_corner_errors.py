"""Errors: the bounded appeal cycle and the statutory bar on a short-term tenant."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS


ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["relocation_specialist_headers"]

LONG_TERM_TENANT = {
    "displacee_type": "TENANT_90_DAY",
    "household_reference": "HH-A",
    "rhp_method": "COMPARABLE_DWELLING",
    "rental_assistance_start_date": "2026-09-01",
    "current_rent_cents": 90_000,
    "current_utility_cents": 15_000,
    "comparable_rent_cents": 130_000,
    "comparable_utility_cents": 20_000,
    "monthly_gross_income_cents": 320_000,
    "moving_expense_cents": 175_000,
}
SHORT_TERM_TENANT = {
    "displacee_type": "TENANT_UNDER_90_DAY",
    "household_reference": "HH-B",
    "rhp_method": "COMPARABLE_DWELLING",
    "rental_assistance_start_date": "2026-09-01",
    "current_rent_cents": 70_000,
    "current_utility_cents": 12_000,
    "comparable_rent_cents": 110_000,
    "comparable_utility_cents": 18_000,
    "monthly_gross_income_cents": 260_000,
    "moving_expense_cents": 120_000,
}


def _two_tenant_cases_on_one_accepted_offer(api):
    """One tenant-occupied parcel with an ACCEPTED offer and two OPENED cases."""
    state = fixtures.parcel_with_accepted_offer(
        api,
        project_overrides={"project_code": "ERR-APPEAL-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-ERR-APPEAL-1", "site_address": "4501 River Rd",
            "acreage": 0.34, "occupancy_type": "TENANT_OCCUPIED",
            "structure_type": "MULTI_FAMILY",
        },
    )
    assert state["offer"]["status"] == "ACCEPTED"
    assert state["offer"]["net_offer_cents"] == 20_000_000

    state["case_a"] = fixtures.open_relocation_case(
        api, state["parcel"]["id"], **LONG_TERM_TENANT
    )
    state["case_b"] = fixtures.open_relocation_case(
        api, state["parcel"]["id"], **SHORT_TERM_TENANT
    )
    return state


def _deny(api, case_id, denial_reason):
    return validate_success(
        api.resolve_relocation_claim(
            case_id,
            factories.resolve_claim_payload(
                case_id, "DENY", denial_reason=denial_reason
            ),
            ADMIN,
        )
    )


def _appeal(api, case_id, appeal_basis):
    return api.appeal_relocation_claim(
        case_id, factories.appeal_payload(case_id, appeal_basis=appeal_basis),
        SPECIALIST,
    )


def test_the_long_term_tenant_may_appeal_twice_and_the_third_appeal_is_refused(api):
    """Two full denial-appeal laps are legal and the case is left alive with no move left.

    "First, `rental_assistance_months` is 42 when `displacee_type` is `TENANT_90_DAY`,
    and exactly 0 when `displacee_type` is `OWNER_OCCUPANT`, `TENANT_UNDER_90_DAY` or
    `BUSINESS`."

    "`DENY` from `CLAIM_SUBMITTED` moves `status` to `CLAIM_DENIED`, stores the
    `denial_reason`, and advances only the case's `version` by 1; the displacee retains
    the right to appeal."

    "The case must be in `CLAIM_DENIED`, otherwise `ERR_INVALID_CASE_STATE`, and
    `appeal_count` must be **strictly less than** 2, otherwise
    `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/errors/the_appeal_cycle_stops_at_the_second_appeal_and_a_short_term_tenant_cannot_claim
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _two_tenant_cases_on_one_accepted_offer(api)
    case_id = state["case_a"]["id"]

    determined = validate_success(
        api.determine_relocation_eligibility(case_id, SPECIALIST)
    )
    assert determined["status"] == "ELIGIBILITY_DETERMINED"
    assert determined["acquisition_price_cents"] == 20_000_000
    assert determined["rental_assistance_months"] == 42
    assert determined["rental_assistance_end_date"] == "2030-03-01"

    validate_success(api.submit_relocation_claim(case_id, SPECIALIST))
    _deny(api, case_id, "occupancy documentation incomplete")

    first_appeal = validate_success(
        _appeal(api, case_id, "lease and utility bills attached")
    )
    assert first_appeal["status"] == "APPEALED"
    assert first_appeal["appeal_count"] == 1

    validate_success(api.submit_relocation_claim(case_id, SPECIALIST))
    second_denial = _deny(api, case_id, "comparable dwelling evidence still missing")
    assert second_denial["status"] == "CLAIM_DENIED"

    second_appeal = validate_success(
        _appeal(api, case_id, "three comparables attached")
    )
    assert second_appeal["appeal_count"] == 2

    validate_success(api.submit_relocation_claim(case_id, SPECIALIST))
    third_denial = _deny(api, case_id, "comparables outside the market area")
    assert third_denial["status"] == "CLAIM_DENIED"
    assert third_denial["appeal_count"] == 2

    validate_error(
        _appeal(api, case_id, "fourth attempt"),
        ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value,
        409,
    )

    parked = validate_success(api.get_relocation_case(case_id, ADMIN))
    assert parked["status"] == "CLAIM_DENIED"
    assert parked["appeal_count"] == 2

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == 15_000_000


def test_the_short_term_tenant_is_determined_eligible_and_then_barred_from_claiming(api):
    """The statutory bar sits on the claim, one step after the determination succeeds.

    "A `RelocationSpecialist` determines eligibility on a case that must be in `OPENED`,
    otherwise `ERR_INVALID_CASE_STATE`."

    "Determination snapshots `acquisition_price_cents` from that accepted offer's
    `net_offer_cents`, computes `rental_assistance_months`,
    `rental_assistance_end_date`, `replacement_housing_payment_cents`,
    `rental_assistance_cents` and `total_relocation_benefit_cents`, moves `status` to
    `ELIGIBILITY_DETERMINED`, and advances the case's `version` by 1."

    "A `displacee_type` of `TENANT_UNDER_90_DAY` is statutorily ineligible and is
    refused with `ERR_TENANT_INELIGIBLE`, on both the initial submission and any
    resubmission after appeal."

    Design: Corner/errors/the_appeal_cycle_stops_at_the_second_appeal_and_a_short_term_tenant_cannot_claim
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _two_tenant_cases_on_one_accepted_offer(api)
    case_id = state["case_b"]["id"]

    determined = validate_success(
        api.determine_relocation_eligibility(case_id, SPECIALIST)
    )
    assert determined["status"] == "ELIGIBILITY_DETERMINED"
    assert determined["acquisition_price_cents"] == 20_000_000
    assert determined["rental_assistance_months"] == 0
    assert determined["rental_assistance_cents"] == 0

    validate_error(
        api.submit_relocation_claim(case_id, SPECIALIST),
        ApiErrorId.ERR_TENANT_INELIGIBLE.value,
        422,
    )

    stuck = validate_success(api.get_relocation_case(case_id, ADMIN))
    assert stuck["status"] == "ELIGIBILITY_DETERMINED"

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == 15_000_000
