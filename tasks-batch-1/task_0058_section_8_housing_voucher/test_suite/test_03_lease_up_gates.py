"""Queue A (depth) — lease-up gate ordering, cross-entity preconditions, and
temporal boundary semantics around lease-up and the cure window.
"""
from test_helpers import (
    api_client, validate_success, validate_error, set_clock,
    setup_leaseup_ready, setup_abated_contract,
    create_region, make_eligible_household, issue_voucher,
    create_landlord, create_unit, create_passed_initial_inspection,
    create_hap_contract_payload, create_voucher_payload,
    CASEWORKER, INSPECTOR,
)


def _lease_up_resp(scenario, contract_rent_cents, version=None):
    return api_client.create_hap_contract(
        create_hap_contract_payload(
            scenario["voucher"]["id"], scenario["unit"]["id"],
            contract_rent_cents,
            scenario["voucher_version"] if version is None else version,
        ),
        CASEWORKER,
    )


# ── rule: priority_pair_validation_conflict ────────────────


def test_expired_voucher_beats_rent_not_reasonable():
    """PRD §3.5: "Third, the voucher must not be expired ... and a voucher whose
    expiration date is at or before the current UTC is rejected with
    ERR_VOUCHER_EXPIRED (HTTP 422). ... Fifth, the rent must be reasonable."
    A lease-up failing both the (earlier) expiry gate and the (later) rent gate
    returns ERR_VOUCHER_EXPIRED.

    Design: Difficulty/priority_pair_validation_conflict/expired_voucher_vs_rent_not_reasonable_temporal_beats_constraint
    """
    scenario = setup_leaseup_ready(
        region_code="PRI_REGA", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=200000, comparable_rent_cents=90000, term_days=60,
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-09-01T00:00:00Z")
    validate_error(_lease_up_resp(scenario, 200000), "ERR_VOUCHER_EXPIRED", 422)


def test_inspection_not_passed_beats_rent_burden():
    """PRD §3.5: "Fourth, the unit must have a passed initial inspection: there
    must exist a PASSED inspection of type INITIAL for the unit, and lease-up
    without one is rejected with ERR_INSPECTION_NOT_PASSED (HTTP 422). ... Sixth
    and last, the initial rent-burden gate must pass." The (earlier) inspection
    gate wins over the (later) burden gate.

    Design: Difficulty/priority_pair_validation_conflict/inspection_not_passed_vs_rent_burden_safety_beats_fiscal
    """
    set_clock("2026-06-01T00:00:00Z")
    region = create_region(code="PRI_REGB")
    from test_helpers import create_payment_standard
    create_payment_standard(region["id"], bedroom_size=0, amount_cents=40000, fmr_cents=40000)
    household = make_eligible_household(region["id"], family_size=1, annual_income_cents=600000)
    voucher = issue_voucher(household["id"])
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=0,
        asking_rent_cents=70000, comparable_rent_cents=70000,
    )
    # No INITIAL inspection passed for the unit.
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 70000, voucher["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_INSPECTION_NOT_PASSED", 422)


# ── rule: boundary_precision_check ─────────────────────────


def test_rent_reasonableness_equal_to_comparable_is_reasonable():
    """PRD §3.1: "the outcome is REASONABLE when the requested_rent_cents is less
    than or equal to that snapshotted comparable rent, with the boundary
    inclusive, and NOT_REASONABLE otherwise." Requested 90,000 == comparable
    90,000 -> REASONABLE.

    Design: Difficulty/boundary_precision_check/rent_reasonableness_inclusive_equal_passes
    """
    from test_helpers import create_rent_reasonableness_payload
    region = create_region(code="BND_REGA")
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=2,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    det = validate_success(
        api_client.create_rent_reasonableness(
            create_rent_reasonableness_payload(unit["id"], requested_rent_cents=90000),
            CASEWORKER,
        ),
        201,
    )
    assert det["outcome"] == "REASONABLE"


def test_list_vouchers_empty_set_for_unused_region():
    """PRD §4: "GET /vouchers | List vouchers, filterable by household or issuing
    region". PRD §2.3: "Every list response includes the following fields in the
    meta object: limit, offset, total_count, and has_more." A region with no
    vouchers returns an empty array with total_count 0.

    Design: Difficulty/boundary_precision_check/list_vouchers_empty_set_for_unused_region
    """
    region = create_region(code="BND_REGB")
    resp = api_client.list_vouchers(CASEWORKER, params={"issuing_region_id": region["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


# ── rule: cross_entity_state_dependency ────────────────────


def test_leaseup_requires_unit_initial_inspection_passed():
    """PRD §3.5: "Fourth, the unit must have a passed initial inspection: there
    must exist a PASSED inspection of type INITIAL for the unit, and lease-up
    without one is rejected with ERR_INSPECTION_NOT_PASSED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/leaseup_requires_unit_initial_inspection_passed
    """
    set_clock("2026-06-01T00:00:00Z")
    region = create_region(code="CESD_REGA")
    from test_helpers import create_payment_standard
    create_payment_standard(region["id"], bedroom_size=2, amount_cents=95000, fmr_cents=100000)
    household = make_eligible_household(
        region["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"])
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=2,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    # Schedule an INITIAL inspection but do NOT pass it.
    from test_helpers import create_inspection_payload
    api_client.create_inspection(
        create_inspection_payload(unit["id"], inspection_type="INITIAL"), INSPECTOR
    )
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 90000, voucher["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_INSPECTION_NOT_PASSED", 422)


def test_voucher_issuance_requires_household_eligible():
    """PRD §3.3: "Issuance requires the household_id; if the named household is
    not in ELIGIBLE status, issuance is rejected with ERR_HOUSEHOLD_NOT_ELIGIBLE
    (HTTP 422)." An APPLIED household (eligibility never run) is rejected.

    Design: Difficulty/cross_entity_state_dependency/voucher_issuance_requires_household_eligible
    """
    region = create_region(code="CESD_REGB")
    from test_helpers import create_household
    household = create_household(region["id"], family_size=3, annual_income_cents=1800000)
    resp = api_client.create_voucher(create_voucher_payload(household["id"]), CASEWORKER)
    validate_error(resp, "ERR_HOUSEHOLD_NOT_ELIGIBLE", 422)


# ── rule: resource_temporal_overlap ────────────────────────


def test_cure_at_exactly_deadline_succeeds_inclusive():
    """PRD §3.4: "An Inspector records a cure only while the inspection is FAILED
    and the server's current UTC is on or before the cure_deadline; a cure
    attempted after the deadline is rejected with ERR_CURE_DEADLINE_PASSED."
    Failing scheduled 2026-06-15 sets a 14-day window to 2026-06-29; curing at
    exactly 2026-06-29 succeeds.

    Design: Difficulty/resource_temporal_overlap/cure_within_deadline_inclusive_boundary
    """
    scenario = setup_abated_contract(
        family_size=3, annual_income_cents=1800000, dependents_count=2,
        amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000,
        annual_scheduled_date="2026-06-15T00:00:00Z",
    )
    annual = scenario["annual_inspection"]
    set_clock("2026-06-29T00:00:00Z")
    validate_success(api_client.cure_inspection(annual["id"], INSPECTOR), 200)
    insp = validate_success(api_client.get_inspection(annual["id"], INSPECTOR), 200)
    contract = validate_success(
        api_client.get_hap_contract(scenario["contract"]["id"], CASEWORKER), 200
    )
    assert insp["status"] == "CURED"
    assert contract["status"] == "ACTIVE"


def test_voucher_expiration_at_exact_instant_blocks_leaseup():
    """PRD §3.5: "Third, the voucher must not be expired: the server's current
    UTC must be strictly before the voucher's expiration_date, and a voucher
    whose expiration date is at or before the current UTC is rejected with
    ERR_VOUCHER_EXPIRED (HTTP 422)." Clock at exactly the expiration instant is
    rejected (open right boundary).

    Design: Difficulty/resource_temporal_overlap/voucher_expiration_open_right_boundary_blocks_leaseup
    """
    scenario = setup_leaseup_ready(
        region_code="OVL_REGB", family_size=3, annual_income_cents=1800000,
        dependents_count=2, bedroom_size=2, amount_cents=95000, fmr_cents=100000,
        asking_rent_cents=90000, comparable_rent_cents=90000, term_days=60,
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-07-31T00:00:00Z")
    validate_error(_lease_up_resp(scenario, 90000), "ERR_VOUCHER_EXPIRED", 422)
