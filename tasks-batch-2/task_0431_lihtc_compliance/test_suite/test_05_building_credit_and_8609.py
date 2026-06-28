"""Building applicable fraction / credit, Form 8609 dual-variant credit, revoke/recapture,
set-aside certification, and optimistic concurrency on building version.

Translates queue A (Difficulty) instances combinatorial_formula/applicable_fraction_min,
dual_variant_calc/first_year_credit, non_linear_state_machine/building_credit_branch_revert,
compensating_invariant/revoke_final, and cross_entity_state_dependency/form8609_requires_set_aside;
plus queue B (Corner) set-aside, recapture, and OCC instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_project,
    create_building,
    create_unit,
    create_household,
    setup_project_building,
    make_qualified_unit,
    create_approved_certification,
    setup_set_aside_met_with_designated_units,
    issue_provisional_8609,
    issue_final_8609,
    setup_building_at_provisional,
    setup_building_at_final,
    setup_dual_variant_building_at_final,
    setup_noncompliant_project_with_final_building,
    DUAL_VARIANT_MONTHLY,
    FLAT_MONTHLY_QUALIFIED,
)
from test_helpers import api_client

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]


# ─── Difficulty: applicable fraction = min(two fractions) then tiered credit ──

def _two_qualified_units_building():
    """Project SET_ASIDE-eligible + building (10 units, 10000 sqft, NINE_PERCENT) with two
    AMI_50 br1 units (each 1000 sqft) made QUALIFIED. Returns (project, building, units)."""
    project, building = setup_project_building()
    u1 = create_unit(
        building["id"], unit_number="U1", bedroom_count=1, sqft=1_000,
        utility_allowance_cents=9_000, ami_designation="AMI_50",
    )
    u2 = create_unit(
        building["id"], unit_number="U2", bedroom_count=1, sqft=1_000,
        utility_allowance_cents=9_000, ami_designation="AMI_50",
    )
    h1 = create_household(project["id"], head_name="H1")
    h2 = create_household(project["id"], head_name="H2")
    create_approved_certification(h1["id"], u1["id"], cert_type="INITIAL", annual_income_cents=3_000_000)
    create_approved_certification(h2["id"], u2["id"], cert_type="INITIAL", annual_income_cents=3_000_000)
    return project, building, (u1, u2)


def test_applicable_fraction_min_and_qualified_basis(api):
    """PRD §3.5: "First, the unit fraction is the count of the building's counted low-income
    units divided by the building's `total_residential_units`, rounded half-up to 4 decimal
    places. Second, the floor-space fraction is the sum of the `sqft` of the building's
    counted low-income units divided by the building's `total_residential_sqft`, rounded
    half-up to 4 decimal places. Third, the building's `applicable_fraction` is the smaller of
    the unit fraction and the floor-space fraction. Fourth, the `qualified_basis_cents` is the
    building's `eligible_basis_cents` multiplied by the `applicable_fraction`, floored."

    Design: Difficulty/combinatorial_formula/applicable_fraction_min_of_two_fractions_then_tiered_credit
    """
    project, building, _units = _two_qualified_units_building()
    after = get_success_data(api.get_building(building["id"], OWNER))
    assert after["applicable_fraction"] == 0.2000
    assert after["qualified_basis_cents"] == 20_000_000


def test_annual_credit_tiered_by_nine_percent(api):
    """PRD §3.5: "Fifth, a credit factor in basis points is taken from the building's
    `credit_type` — 900 basis points for `NINE_PERCENT` and 400 basis points for
    `FOUR_PERCENT` — and the `annual_credit_cents` is the `qualified_basis_cents` multiplied
    by that credit factor divided by 10000, floored."

    Design: Difficulty/combinatorial_formula/applicable_fraction_min_of_two_fractions_then_tiered_credit
    """
    project, building, _units = _two_qualified_units_building()
    after = get_success_data(api.get_building(building["id"], OWNER))
    assert after["annual_credit_cents"] == 1_800_000


# ─── Difficulty: first-year dual-variant credit ───────

def test_provisional_8609_forward_looking_fraction_and_credit(api):
    """PRD §3.6: "the provisional fraction is the count of the building's non-`MARKET`
    (designated) units divided by `total_residential_units`, rounded half-up to 4 decimal
    places. The building's `annual_credit_cents` is then recomputed as the
    `eligible_basis_cents` multiplied by that provisional fraction, multiplied by the credit
    factor in basis points (900 for `NINE_PERCENT`, 400 for `FOUR_PERCENT`) divided by 10000,
    floored."

    Design: Difficulty/dual_variant_calc/first_year_credit_provisional_vs_final_on_building
    """
    project, building, prov_form, _final = setup_dual_variant_building_at_final()
    assert prov_form["issuance_type"] == "PROVISIONAL"
    assert prov_form["allocated_fraction"] == 0.8000
    assert prov_form["allocated_annual_credit_cents"] == 7_200_000


def test_final_8609_chronological_fraction_and_credit(api):
    """PRD §3.6: "The FINAL issuance pins the building's `first_year_fraction` to the **final
    chronological fraction**, which is the average of the twelve month-end qualified fractions:
    for each of the twelve months, the month's qualified-unit count (supplied as the
    twelve-element `monthly_qualified_units` array in the request body) is divided by
    `total_residential_units`; those twelve monthly fractions are summed and divided by 12, and
    that average is rounded half-up to 4 decimal places."

    Design: Difficulty/dual_variant_calc/first_year_credit_provisional_vs_final_on_building
    """
    project, building, _prov, final_form = setup_dual_variant_building_at_final()
    assert final_form["issuance_type"] == "FINAL"
    assert final_form["allocated_fraction"] == 0.6000
    assert final_form["allocated_annual_credit_cents"] == 5_400_000
    assert building["annual_credit_cents"] == 5_400_000


# ─── Difficulty: building credit branch + revert (revoke-final) ──

def test_revoke_final_branches_back_to_provisional(api):
    """PRD §3.6: "A `StateHFA` may **revoke a FINAL** 8609, branching the building back from
    `FINAL_8609` to `PROVISIONAL_8609`. This sets the FINAL `Form8609`'s `status` to
    `REVOKED`, restores the building's `first_year_fraction` to the provisional fraction, and
    recomputes `annual_credit_cents` accordingly."

    Design: Difficulty/non_linear_state_machine/building_credit_branch_revert_final_to_provisional
    """
    project, building, _prov, _final = setup_dual_variant_building_at_final()
    assert building["credit_status"] == "FINAL_8609"
    reverted = validate_success(api.revoke_final(building["id"], HFA), 200)
    assert reverted["credit_status"] == "PROVISIONAL_8609"
    assert reverted["first_year_fraction"] == 0.8000


def test_final_then_revoke_restores_provisional_credit(api):
    """PRD §3.6: "This sets the FINAL `Form8609`'s `status` to `REVOKED`, restores the
    building's `first_year_fraction` to the provisional fraction, and recomputes
    `annual_credit_cents` accordingly."

    Design: Difficulty/non_linear_state_machine/building_credit_branch_revert_final_to_provisional
    """
    project, building, _prov, _final = setup_dual_variant_building_at_final()
    reverted = validate_success(api.revoke_final(building["id"], HFA), 200)
    assert reverted["annual_credit_cents"] == 7_200_000


# ─── Difficulty: compensating invariant — revoke-final restores credit ──

def test_revoke_final_conserves_annual_credit(api):
    """PRD §3.6: "restores the building's `first_year_fraction` to the provisional fraction,
    and recomputes `annual_credit_cents` accordingly."

    Design: Difficulty/compensating_invariant/revoke_final_restores_building_annual_credit
    """
    project, building, _prov, final_form = setup_dual_variant_building_at_final()
    # Forward FINAL pinned credit to 5_400_000.
    assert building["annual_credit_cents"] == 5_400_000
    reverted = validate_success(api.revoke_final(building["id"], HFA), 200)
    assert reverted["annual_credit_cents"] == 7_200_000


def test_revoke_final_returns_to_provisional_credit_status(api):
    """PRD §3.6: "A `StateHFA` may **revoke a FINAL** 8609, branching the building back from
    `FINAL_8609` to `PROVISIONAL_8609`."

    Design: Difficulty/compensating_invariant/revoke_final_restores_building_annual_credit
    """
    project, building, _prov, _final = setup_dual_variant_building_at_final()
    reverted = validate_success(api.revoke_final(building["id"], HFA), 200)
    assert reverted["credit_status"] == "PROVISIONAL_8609"
    assert reverted["annual_credit_cents"] == 7_200_000


# ─── Difficulty: form8609 issuance requires project SET_ASIDE_MET ──

def test_provisional_8609_rejected_while_project_draft(api):
    """PRD §3.6: "it is permitted only when the building is in `PRE_ALLOCATION` and the owning
    project's `status` is `SET_ASIDE_MET` or `CREDIT_PERIOD`; an issuance against a project
    that has not reached the set-aside-met state is rejected with `ERR_SET_ASIDE_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/form8609_issuance_requires_project_set_aside_met
    """
    project = create_project(minimum_set_aside="FORTY_SIXTY")
    building = create_building(
        project["id"], total_residential_units=2, total_residential_sqft=2_000
    )
    create_unit(
        building["id"], unit_number="U1", bedroom_count=1, sqft=1_000,
        utility_allowance_cents=9_000, ami_designation="AMI_50",
    )
    res = api.issue_form8609(building["id"], {"issuance_type": "PROVISIONAL"}, HFA)
    validate_error(res, "ERR_SET_ASIDE_NOT_MET", expected_status=409)


def test_provisional_8609_succeeds_after_set_aside_certified(api):
    """PRD §3.7: "A `StateHFA` certifies the set-aside to advance a project from `DRAFT` to
    `SET_ASIDE_MET`; if the elected test is not satisfied, the certification is rejected with
    `ERR_SET_ASIDE_NOT_MET`."
    PRD §3.6: "A `StateHFA` issues a **PROVISIONAL** Form 8609 to move a building from
    `PRE_ALLOCATION` to `PROVISIONAL_8609`."

    Design: Difficulty/cross_entity_state_dependency/form8609_issuance_requires_project_set_aside_met
    """
    project = create_project(minimum_set_aside="FORTY_SIXTY")
    building = create_building(
        project["id"], total_residential_units=2, total_residential_sqft=2_000
    )
    create_unit(
        building["id"], unit_number="U1", bedroom_count=1, sqft=1_000,
        utility_allowance_cents=9_000, ami_designation="AMI_50",
    )
    get_success_data(api.certify_set_aside(project["id"], HFA))
    res = api.issue_form8609(building["id"], {"issuance_type": "PROVISIONAL"}, HFA)
    validate_success(res, 201)
    after = get_success_data(api.get_building(building["id"], HFA))
    assert after["credit_status"] == "PROVISIONAL_8609"


# ─── Corner: AVERAGE_INCOME set-aside test ────────────

def test_set_aside_average_income_passes_at_60_average(api):
    """PRD §3.7: "Under `AVERAGE_INCOME`, the low-income units are those whose `ami_designation`
    is `AMI_40`, `AMI_50`, `AMI_60`, or `AMI_80`. Each contributes its band percentage (40, 50,
    60, or 80). The average designation is the sum of those band percentages divided by the
    count of low-income units, rounded half-up to 2 decimal places. The test is satisfied when
    there is at least one low-income unit and the average designation is at most 60.00."

    Design: Corner/calculations/set_aside_average_income_test_passes_at_60_average
    """
    project = create_project(minimum_set_aside="AVERAGE_INCOME")
    building = create_building(
        project["id"], total_residential_units=4, total_residential_sqft=4_000
    )
    for n, band in [("U1", "AMI_80"), ("U2", "AMI_80"), ("U3", "AMI_40"), ("U4", "AMI_40")]:
        create_unit(
            building["id"], unit_number=n, bedroom_count=1, sqft=1_000,
            utility_allowance_cents=9_000, ami_designation=band,
        )
    res = api.certify_set_aside(project["id"], HFA)  # average = 60.00 <= ceiling
    project_after = validate_success(res, 200)
    assert project_after["status"] == "SET_ASIDE_MET"


def test_set_aside_average_income_fails_above_60_average(api):
    """PRD §3.7: "The test is satisfied when there is at least one low-income unit and the
    average designation is at most 60.00."
    PRD §3.7: "if the elected test is not satisfied, the certification is rejected with
    `ERR_SET_ASIDE_NOT_MET`."

    Design: Corner/calculations/set_aside_average_income_test_fails_above_60_average
    """
    project = create_project(minimum_set_aside="AVERAGE_INCOME")
    building = create_building(
        project["id"], total_residential_units=4, total_residential_sqft=4_000
    )
    for n, band in [("U1", "AMI_80"), ("U2", "AMI_60"), ("U3", "AMI_50"), ("U4", "AMI_60")]:
        create_unit(
            building["id"], unit_number=n, bedroom_count=1, sqft=1_000,
            utility_allowance_cents=9_000, ami_designation=band,
        )
    res = api.certify_set_aside(project["id"], HFA)  # average = 62.50 > ceiling
    validate_error(res, "ERR_SET_ASIDE_NOT_MET", expected_status=409)
    project_after = get_success_data(api.get_project(project["id"], HFA))
    assert project_after["status"] == "DRAFT"


# ─── Corner: recapture requires NONCOMPLIANT ──────────

def test_recapture_on_compliant_project_returns_requires_noncompliant(api):
    """PRD §3.6: "Recapture is permitted only when the building is in `FINAL_8609`, when the
    owning project's `posture` is `NONCOMPLIANT` (otherwise the request is rejected with
    `ERR_RECAPTURE_REQUIRES_NONCOMPLIANT`), and when the supplied `expected_building_version`
    matches the building's current `version` (otherwise `ERR_STALE_VERSION` as described in
    Section 2.7)."

    Design: Corner/errors/recapture_on_compliant_project_returns_requires_noncompliant
    """
    project, building = setup_building_at_final(total_units=2, designated_count=1)
    assert building["credit_status"] == "FINAL_8609"
    res = api.recapture(
        building["id"], {"expected_building_version": building["version"]}, HFA
    )
    validate_error(res, "ERR_RECAPTURE_REQUIRES_NONCOMPLIANT", expected_status=409)
    after = get_success_data(api.get_building(building["id"], HFA))
    assert after["credit_status"] == "FINAL_8609"


# ─── Corner: OCC on FINAL 8609 issuance ───────────────

def test_occ_stale_version_on_final_8609_returns_412(api):
    """PRD §2.7: "A request that issues a FINAL 8609 must carry the field
    `expected_building_version`, and its value must equal the target building's current
    `version`. If another writer has advanced the building's `version` since the client last
    read it — for instance by having already issued the FINAL 8609 and pinned the chronological
    fraction — then the requesting client's view is stale and the issuance is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_final_8609_returns_412
    """
    project, building = setup_building_at_provisional(total_units=2, designated_count=1)
    stale = building["version"] - 1
    res = api.issue_form8609(
        building["id"],
        {
            "issuance_type": "FINAL",
            "monthly_qualified_units": FLAT_MONTHLY_QUALIFIED,
            "expected_building_version": stale,
        },
        HFA,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = get_success_data(api.get_building(building["id"], HFA))
    assert after["credit_status"] == "PROVISIONAL_8609"


def test_occ_correct_version_on_final_8609_succeeds_and_bumps_version(api):
    """PRD §3.6: "The building's `annual_credit_cents` is recomputed from the final
    `first_year_fraction`, a `Form8609` snapshot with `issuance_type` of `FINAL` and `status`
    of `ISSUED` is created, and the building's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_final_8609_succeeds_and_bumps_version
    """
    project, building = setup_building_at_provisional(total_units=2, designated_count=1)
    before_version = building["version"]
    res = api.issue_form8609(
        building["id"],
        {
            "issuance_type": "FINAL",
            "monthly_qualified_units": FLAT_MONTHLY_QUALIFIED,
            "expected_building_version": before_version,
        },
        HFA,
    )
    validate_success(res, 201)
    after = get_success_data(api.get_building(building["id"], HFA))
    assert after["credit_status"] == "FINAL_8609"
    assert after["version"] == before_version + 1


# ─── Corner: OCC on recapture + recapture compensation ──

def test_occ_stale_version_on_recapture_returns_412(api):
    """PRD §2.7: "A recapture request must carry `expected_building_version` matching the
    building's current `version`; if the building's `version` has advanced since the client
    last observed it (for example because a FINAL 8609 was just re-issued), the recapture
    carries a stale version and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_recapture_returns_412
    """
    project, building, _finding = setup_noncompliant_project_with_final_building(
        total_units=2, designated_count=1
    )
    assert project["posture"] == "NONCOMPLIANT"
    stale = building["version"] - 1
    res = api.recapture(building["id"], {"expected_building_version": stale}, HFA)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = get_success_data(api.get_building(building["id"], HFA))
    assert after["credit_status"] == "FINAL_8609"


def test_recapture_compensation_zeroes_credit_on_noncompliant_project(api):
    """PRD §3.6: "Recapture is a compensating action: it sets the building's
    `annual_credit_cents`, `applicable_fraction`, and `qualified_basis_cents` all to 0, sets
    the FINAL `Form8609`'s `status` to `REVOKED`, and increments the building's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/recapture_compensation_zeroes_credit_on_noncompliant_project
    """
    project, building, _finding = setup_noncompliant_project_with_final_building(
        total_units=2, designated_count=1
    )
    res = api.recapture(
        building["id"], {"expected_building_version": building["version"]}, HFA
    )
    recaptured = validate_success(res, 200)
    assert recaptured["credit_status"] == "RECAPTURED"
    assert recaptured["annual_credit_cents"] == 0
    assert recaptured["qualified_basis_cents"] == 0
