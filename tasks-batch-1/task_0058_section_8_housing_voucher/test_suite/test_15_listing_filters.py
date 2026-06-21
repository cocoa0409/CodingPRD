"""Queue B (breadth) — FK reverse-reachability list filters (PRD Section 4)."""
from test_helpers import (
    api_client, validate_success,
    create_region, create_landlord, create_unit, create_passed_initial_inspection,
    make_eligible_household, issue_voucher, create_payment_standard,
    setup_active_hap_contract, schedule_annual_inspection, request_portability_move,
    grant_special_mobility, draft_annual_review,
    create_rent_reasonableness_payload,
    CASEWORKER, INSPECTOR, COORDINATOR, ADMIN,
)


def _total(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["meta"]["total_count"]


def test_filter_units_by_landlord():
    """PRD §4: "GET /units | List units, filterable by landlord or region".

    Design: Corner/endpoints/fk_filter_units_by_landlord
    """
    region = create_region(code="FK_R")
    landlord = create_landlord(name="LLfk", payee_account="acct-fk")
    create_unit(
        landlord["id"], region["id"], bedroom_size=1,
        asking_rent_cents=80000, comparable_rent_cents=80000,
    )
    assert _total(api_client.list_units(ADMIN, params={"landlord_id": landlord["id"]})) == 1


def test_filter_hap_contracts_by_administering_region():
    """PRD §4: "GET /hap-contracts | List HAP contracts, filterable by voucher,
    unit, or administering region".

    Design: Corner/endpoints/fk_filter_hap_contracts_by_administering_region
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, region_code="ADM_R", family_size=3,
        annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    region_id = scenario["region"]["id"]
    assert _total(
        api_client.list_hap_contracts(CASEWORKER, params={"administering_region_id": region_id})
    ) == 1


def test_filter_inspections_by_hap_contract():
    """PRD §4: "GET /inspections | List inspections, filterable by unit or
    contract".

    Design: Corner/endpoints/fk_filter_inspections_by_hap_contract
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, region_code="FKI_R", family_size=3,
        annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    schedule_annual_inspection(scenario["unit"]["id"], contract["id"])
    assert _total(
        api_client.list_inspections(INSPECTOR, params={"hap_contract_id": contract["id"]})
    ) == 1


def test_filter_portability_moves_by_receiving_region():
    """PRD §4: "GET /portability-moves | List portability moves, filterable by
    voucher or receiving region".

    Design: Corner/endpoints/fk_filter_portability_moves_by_receiving_region
    """
    home = create_region(code="PMR_HOME")
    dest = create_region(code="PMR_DEST")
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    request_portability_move(voucher["id"], dest["id"])
    assert _total(
        api_client.list_portability_moves(COORDINATOR, params={"receiving_region_id": dest["id"]})
    ) == 1


def test_filter_special_mobility_grants_by_target_region():
    """PRD §4: "GET /special-mobility-grants | List special mobility grants,
    filterable by voucher or target region".

    Design: Corner/endpoints/fk_filter_special_mobility_grants_by_target_region
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T00:00:00Z")
    home = create_region(code="SMG_HOME")
    opp = create_region(code="SMG_OPP", is_special_mobility_area=True)
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    grant_special_mobility(voucher["id"], opp["id"])
    assert _total(
        api_client.list_special_mobility_grants(COORDINATOR, params={"target_region_id": opp["id"]})
    ) == 1


def test_filter_rent_reasonableness_by_unit():
    """PRD §4: "GET /rent-reasonableness | List rent reasonableness
    determinations, filterable by unit".

    Design: Corner/endpoints/fk_filter_rent_reasonableness_by_unit
    """
    region = create_region(code="RRU_R")
    landlord = create_landlord(name="LLrru", payee_account="acct-rru")
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=1,
        asking_rent_cents=80000, comparable_rent_cents=80000,
    )
    validate_success(
        api_client.create_rent_reasonableness(
            create_rent_reasonableness_payload(unit["id"], requested_rent_cents=75000),
            CASEWORKER,
        ),
        201,
    )
    assert _total(
        api_client.list_rent_reasonableness(CASEWORKER, params={"unit_id": unit["id"]})
    ) == 1


def test_filter_annual_reviews_by_hap_contract():
    """PRD §4: "GET /annual-reviews | List annual reviews, filterable by
    contract".

    Design: Corner/endpoints/fk_filter_annual_reviews_by_hap_contract
    """
    scenario, contract = setup_active_hap_contract(
        contract_rent_cents=90000, region_code="ARF_R", family_size=3,
        annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    draft_annual_review(contract["id"], new_annual_income_cents=1900000)
    assert _total(
        api_client.list_annual_reviews(CASEWORKER, params={"hap_contract_id": contract["id"]})
    ) == 1
