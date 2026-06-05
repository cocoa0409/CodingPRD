"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API process before every individual test, so the
database is empty at the start of every test — each fixture rebuilds its
preconditions from scratch using only PRD-declared endpoints.

Uses ``get_success_data()`` (lenient 2xx validator) internally so setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures inside the test body.

Identity threading (PRD §2.1): the Landlord role is entity-backed, so any
unit-creation call is issued with ``make_landlord_headers(landlord_id)`` once
the landlord exists, matching the X-User-ID to the acting landlord's id.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_region_payload,
    create_payment_standard_payload,
    create_household_payload,
    create_voucher_payload,
    create_landlord_payload,
    create_unit_payload,
    create_inspection_payload,
    create_hap_contract_payload,
    create_portability_move_payload,
    create_annual_review_payload,
    finalize_annual_review_payload,
    create_special_mobility_grant_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_landlord_headers

ADMIN = TEST_USERS["program_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
COORDINATOR = TEST_USERS["portability_coordinator_headers"]


# --- Clock primitive (PRD §2.9) ---


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# --- Primitive entity builders ---


def create_region(**overrides) -> dict:
    return get_success_data(
        api_client.create_region(create_region_payload(**overrides), ADMIN)
    )


def create_payment_standard(region_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_payment_standard(
            create_payment_standard_payload(region_id, **overrides), ADMIN
        )
    )


def create_household(region_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_household(
            create_household_payload(region_id, **overrides), CASEWORKER
        )
    )


def make_eligible_household(region_id: str, **overrides) -> dict:
    """Create a household and drive it to ELIGIBLE (PRD §3.2)."""
    hh = create_household(region_id, **overrides)
    get_success_data(api_client.determine_eligibility(hh["id"], CASEWORKER))
    return get_success_data(api_client.get_household(hh["id"], CASEWORKER))


def issue_voucher(household_id: str, **overrides) -> dict:
    """Issue a voucher to an ELIGIBLE household (PRD §3.3)."""
    return get_success_data(
        api_client.create_voucher(
            create_voucher_payload(household_id, **overrides), CASEWORKER
        )
    )


def create_landlord(**overrides) -> dict:
    return get_success_data(
        api_client.create_landlord(create_landlord_payload(**overrides), ADMIN)
    )


def create_unit(landlord_id: str, region_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(landlord_id, region_id, **overrides),
            make_landlord_headers(landlord_id),
        )
    )


def create_passed_initial_inspection(unit_id: str, **overrides) -> dict:
    """Schedule an INITIAL inspection on a unit and pass it (PRD §3.4)."""
    insp = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(unit_id, inspection_type="INITIAL", **overrides),
            INSPECTOR,
        )
    )
    get_success_data(api_client.pass_inspection(insp["id"], INSPECTOR))
    return insp


# --- Composite lease-up scenario ---


def setup_leaseup_ready(
    *,
    family_size: int = 3,
    annual_income_cents: int = 1800000,
    dependents_count: Optional[int] = None,
    childcare_expense_cents: Optional[int] = None,
    bedroom_size: int = 2,
    amount_cents: int = 95000,
    fmr_cents: int = 100000,
    asking_rent_cents: int = 90000,
    comparable_rent_cents: int = 90000,
    term_days: Optional[int] = None,
    clock: Optional[str] = "2026-06-01T00:00:00Z",
    region_code: str = "LU_REGION",
    is_special_mobility_area: Optional[bool] = None,
) -> dict:
    """Build the full precondition graph for a HAP-contract lease-up:
    region + payment standard + ELIGIBLE household + issued voucher + landlord +
    unit + passed INITIAL inspection. Returns a dict of created entities and the
    captured voucher version (PRD §3.1-§3.5)."""
    if clock is not None:
        set_clock(clock)
    region = create_region(code=region_code, is_special_mobility_area=is_special_mobility_area)
    create_payment_standard(
        region["id"], bedroom_size=bedroom_size,
        amount_cents=amount_cents, fmr_cents=fmr_cents,
    )
    hh_kwargs = {"family_size": family_size, "annual_income_cents": annual_income_cents}
    if dependents_count is not None:
        hh_kwargs["dependents_count"] = dependents_count
    if childcare_expense_cents is not None:
        hh_kwargs["childcare_expense_cents"] = childcare_expense_cents
    household = make_eligible_household(region["id"], **hh_kwargs)
    v_kwargs = {}
    if term_days is not None:
        v_kwargs["term_days"] = term_days
    voucher = issue_voucher(household["id"], **v_kwargs)
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=bedroom_size,
        asking_rent_cents=asking_rent_cents, comparable_rent_cents=comparable_rent_cents,
    )
    inspection = create_passed_initial_inspection(unit["id"])
    return {
        "region": region,
        "household": household,
        "voucher": voucher,
        "landlord": landlord,
        "unit": unit,
        "initial_inspection": inspection,
        "voucher_version": voucher["version"],
    }


def lease_up(
    voucher_id: str, unit_id: str, contract_rent_cents: int,
    expected_voucher_version: int,
) -> dict:
    """Create a HAP contract (lease-up). Returns the created contract (PRD §3.5)."""
    return get_success_data(
        api_client.create_hap_contract(
            create_hap_contract_payload(
                voucher_id, unit_id, contract_rent_cents, expected_voucher_version
            ),
            CASEWORKER,
        )
    )


def setup_active_hap_contract(
    *, contract_rent_cents: int = 90000, **overrides,
) -> Tuple[dict, dict]:
    """Build a lease-up-ready scenario and create the ACTIVE HAP contract.
    Returns (scenario_dict, contract) (PRD §3.5)."""
    scenario = setup_leaseup_ready(**overrides)
    contract = lease_up(
        scenario["voucher"]["id"], scenario["unit"]["id"],
        contract_rent_cents, scenario["voucher_version"],
    )
    scenario["contract"] = contract
    return scenario, contract


def schedule_annual_inspection(unit_id: str, hap_contract_id: str,
                               scheduled_date: str = "2026-06-15T00:00:00Z") -> dict:
    """Schedule an ANNUAL inspection against a contract (PRD §3.4)."""
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                unit_id, inspection_type="ANNUAL",
                scheduled_date=scheduled_date, hap_contract_id=hap_contract_id,
            ),
            INSPECTOR,
        )
    )


def setup_abated_contract(
    *, contract_rent_cents: int = 90000,
    annual_scheduled_date: str = "2026-06-15T00:00:00Z", **overrides,
) -> dict:
    """Build an ACTIVE contract, schedule an ANNUAL inspection, and FAIL it so
    the contract is ABATED (PRD §3.6). Returns a dict with scenario, contract,
    and the failed annual inspection."""
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=contract_rent_cents, **overrides
    )
    annual = schedule_annual_inspection(
        scenario["unit"]["id"], contract["id"], scheduled_date=annual_scheduled_date
    )
    get_success_data(api_client.fail_inspection(annual["id"], INSPECTOR))
    scenario["annual_inspection"] = annual
    return scenario


def request_portability_move(voucher_id: str, receiving_region_id: str) -> dict:
    """Request a portability move (PRD §3.7)."""
    return get_success_data(
        api_client.create_portability_move(
            create_portability_move_payload(voucher_id, receiving_region_id),
            COORDINATOR,
        )
    )


def grant_special_mobility(voucher_id: str, target_region_id: str, **overrides) -> dict:
    """Grant a special mobility incentive (PRD §3.8)."""
    return get_success_data(
        api_client.create_special_mobility_grant(
            create_special_mobility_grant_payload(
                voucher_id, target_region_id, **overrides
            ),
            COORDINATOR,
        )
    )


def draft_annual_review(hap_contract_id: str, new_annual_income_cents: int,
                        **overrides) -> dict:
    """Draft an annual review against a contract (PRD §3.8)."""
    return get_success_data(
        api_client.create_annual_review(
            create_annual_review_payload(
                hap_contract_id, new_annual_income_cents, **overrides
            ),
            CASEWORKER,
        )
    )
