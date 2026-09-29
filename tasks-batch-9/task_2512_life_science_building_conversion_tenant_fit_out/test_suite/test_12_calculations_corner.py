"""Derived figures: the code tables, the two reporting bases, the premium classes
and the order in which the allowance is consumed."""

from test_helpers import (
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    assert_floor,
    assert_lease,
    assert_ledger_identity,
    assert_money,
    assert_ratio,
    assert_score,
    assert_utilization_report,
    create_building,
    create_lease,
    create_phase,
    create_tenant,
    decide_assessment,
    decide_hazmat_permit,
    file_hazmat_permit,
    get_floor,
    get_permit,
    get_lease,
    get_phase,
    get_success_data,
    get_utilization,
    make_tenant_headers,
    open_assessment,
    progress_phase,
    proposal_payload,
    schedule_phase,
    setup_building_with_floors,
    setup_conversion_approved_building,
    setup_permitted_project,
    submit_assessment,
    utc,
    validate_success,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "address_city": "Cambridge",
    "occupancy_status": "PARTIALLY_OCCUPIED",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
GROUND_PLATE = {
    "floor_to_floor_ft": 16.0,
    "live_load_psf": 125,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "assessment_basis": "SCREENING",
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
QC_LEASE = {
    "term_months": 120,
    "base_rent_psf": 95.00,
    "delivery_deadline": "2026-12-31T00:00:00Z",
}
QC_PROJECT = {
    "design_exhaust_cfm": 12000,
    "design_power_kw": 180,
    "scope_summary": "QC lab fit-out, floor 2",
}
BSL2_LEASE = {
    "term_months": 120,
    "base_rent_psf": 105.00,
    "delivery_deadline": "2026-12-31T00:00:00Z",
}
BSL2_PROJECT = {
    "design_exhaust_cfm": 18000,
    "design_power_kw": 250,
    "scope_summary": "BSL2 biology fit-out, floor 2",
}
VIVARIUM_LEASE = {
    "term_months": 180,
    "base_rent_psf": 120.00,
    "delivery_deadline": "2027-06-30T00:00:00Z",
}

DENIAL_REASON = "Incompatible storage adjacency with the neighbouring control area"

WINDOWS = (
    (utc(2026, 8, 3), utc(2026, 8, 4)),
    (utc(2026, 8, 5), utc(2026, 8, 6)),
    (utc(2026, 8, 7), utc(2026, 8, 8)),
    (utc(2026, 8, 9), utc(2026, 8, 10)),
)


def _qc_permitted_project(api):
    return setup_permitted_project(
        api,
        allowance_psf=70.00,
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides=dict(QC_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides=dict(QC_PROJECT),
    )


def _bsl2_permitted_project(api):
    return setup_permitted_project(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(BSL2_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides=dict(BSL2_PROJECT),
    )


def _scheduled_packages(api, project_id, specs):
    """Create and schedule one package per spec, one non-overlapping window each."""
    packages = []
    for index, spec in enumerate(specs):
        package = create_phase(api, project_id, sequence_no=index + 1, **spec)
        schedule_phase(api, package["id"], *WINDOWS[index])
        packages.append(package)
    return packages


def _run_to_completion(api, phase_id):
    progress_phase(api, phase_id, "IN_PROGRESS")
    return progress_phase(api, phase_id, "COMPLETE")


def test_the_allowance_follows_the_plate_the_class_and_nothing_else(api):
    """Height band, sprinklers and hazard class multiply out as declared.

    The same hazard class reports a smaller allowance the higher up the stack the
    plate sits, each whole-floor figure is the per-area figure times the areas the
    band permits, and a different hazard class on one plate moves both numbers
    together.

    Design: Corner/calculations/control_area_allowance_matches_the_table_across_floors_and_classes
    """
    bundle = setup_building_with_floors(
        api,
        (1, 2, 5),
        dict(NAMEPLATE),
        {1: dict(GROUND_PLATE), 2: dict(PLATE), 5: dict(PLATE)},
    )
    floors = bundle["floors"]

    ground = get_utilization(api, floors[1]["id"], "FLAMMABLE_IB", 1)
    second = get_utilization(api, floors[2]["id"], "FLAMMABLE_IB", 1)
    fifth = get_utilization(api, floors[5]["id"], "FLAMMABLE_IB", 1)
    corrosive = get_utilization(api, floors[2]["id"], "CORROSIVE", 1)

    assert_utilization_report(ground, floors[1]["id"], "FLAMMABLE_IB")
    assert ground["control_areas_allowed"] == 4
    assert_money(ground["allowance_per_control_area_gal"], 240.00, "per area")
    assert_money(ground["aggregate_allowance_gal"], 960.00, "whole floor")
    assert_money(second["allowance_per_control_area_gal"], 180.00, "per area")
    assert_money(second["aggregate_allowance_gal"], 540.00, "whole floor")
    assert_money(fifth["allowance_per_control_area_gal"], 120.00, "per area")
    assert_money(fifth["aggregate_allowance_gal"], 240.00, "whole floor")
    assert_utilization_report(corrosive, floors[2]["id"], "CORROSIVE")
    assert_money(corrosive["allowance_per_control_area_gal"], 750.00, "per area")
    assert_money(corrosive["aggregate_allowance_gal"], 2250.00, "whole floor")
    for number in (1, 2, 5):
        assert_floor(get_floor(api, floors[number]["id"]))


def test_the_two_reporting_bases_count_different_permits(api):
    """A pending application occupies allowance on one basis and not the other.

    Three applications on one control area differ only in how far each has got:
    the per-area numerator counts the pending one alongside the approved one, the
    whole-floor numerator counts only the approved one, and the refused one is
    invisible to both.

    Design: Corner/calculations/hazmat_utilization_input_sets_differ_by_permit_status
    """
    bundle = _qc_permitted_project(api)
    floor_id = bundle["premises_floor"]["id"]
    project_id = bundle["project"]["id"]
    tenant_headers = bundle["tenant_headers"]
    pending = file_hazmat_permit(
        api, project_id, floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 100.00, 1,
        headers=tenant_headers,
    )
    granted = file_hazmat_permit(
        api, project_id, floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 50.00, 1,
        headers=tenant_headers,
    )
    decide_hazmat_permit(api, granted["id"], "APPROVE")
    refused = file_hazmat_permit(
        api, project_id, floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 30.00, 1,
        headers=tenant_headers,
    )
    decide_hazmat_permit(api, refused["id"], "DENY", DENIAL_REASON)

    report = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)

    assert_utilization_report(report, floor_id, "FLAMMABLE_IB")
    assert_money(report["per_control_area_basis_gal"], 150.00, "per area basis")
    assert_money(report["aggregate_basis_gal"], 50.00, "whole floor basis")
    assert_money(report["per_control_area_utilization_pct"], 83.33, "per area pct")
    assert_money(report["aggregate_utilization_pct"], 9.26, "whole floor pct")
    assert get_permit(api, pending["id"])["status"] == "REQUESTED"
    assert get_permit(api, granted["id"])["status"] == "APPROVED"
    denied = get_permit(api, refused["id"])
    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == DENIAL_REASON


def test_each_premium_class_claims_its_own_share_and_multiplier(api):
    """Four classes, four different eligible figures.

    Three packages carry an identical hard cost and one carries a fifth of it, and
    each completion claims the figure its own class dictates, with the lease's
    committed bucket ending at the sum of the four.

    Design: Corner/calculations/phase_ti_eligible_applies_share_and_premium_multiplier_per_class
    """
    bundle = _bsl2_permitted_project(api)
    lease_before = get_lease(api, bundle["lease"]["id"])
    assert_money(lease_before["ti_authorized_usd"], 500000.00, "ti_authorized_usd")
    shell, lab_mep, vivarium, cleanroom = _scheduled_packages(
        api,
        bundle["project"]["id"],
        [
            {"premium_class": "SHELL", "work_class": "QUIET",
             "hard_cost_usd": 100000.00, "restoration_cost_usd": 90000.00},
            {"premium_class": "LAB_MEP", "work_class": "QUIET",
             "hard_cost_usd": 20000.00, "restoration_cost_usd": 180000.00},
            {"premium_class": "VIVARIUM", "work_class": "QUIET",
             "hard_cost_usd": 100000.00, "restoration_cost_usd": 420000.00},
            {"premium_class": "CLEANROOM", "work_class": "QUIET",
             "hard_cost_usd": 100000.00, "restoration_cost_usd": 110000.00},
        ],
    )

    for package in (shell, lab_mep, vivarium, cleanroom):
        _run_to_completion(api, package["id"])

    expected = {
        shell["id"]: 60000.00,
        lab_mep["id"]: 20060.00,
        vivarium["id"]: 114750.00,
        cleanroom["id"]: 107360.00,
    }
    for phase_id, eligible in expected.items():
        completed = get_phase(api, phase_id)
        assert_money(completed["ti_eligible_usd"], eligible, "ti_eligible_usd")
        assert_money(completed["ti_committed_usd"], eligible, "ti_committed_usd")
    lease = get_lease(api, bundle["lease"]["id"])
    assert_money(lease["ti_committed_usd"], 302170.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 197830.00, "ti_uncommitted_usd")
    assert_money(lease["ti_authorized_usd"], 500000.00, "ti_authorized_usd")
    assert_ledger_identity(lease)


def test_the_headroom_ratio_is_kept_to_four_places_before_it_is_banded(api):
    """A recurring quotient is stored at four places, not rounded to the band.

    The scarcer of the two utility quotients does not terminate, and the stored
    ratio carries four places of it, sits below the full-credit threshold and so
    earns the middle credit, while the weighted sum is rounded exactly once.

    Design: Corner/calculations/utility_headroom_ratio_rounds_to_four_decimals_before_credit_banding
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(
        api,
        building["id"],
        assessment_basis="SCREENING",
        required_vibration_class="VC_C",
        required_exhaust_cfm=50000,
        required_power_kw=750,
        measured_live_load_psf=88,
    )

    submitted = validate_success(
        api.submit_assessment(assessment["id"], ENGINEER_HEADERS), 200
    )

    assert_ratio(submitted["utility_headroom_ratio"], 1.0667)
    assert submitted["utility_credit"] == 60
    assert submitted["height_credit"] == 100
    assert submitted["structural_credit"] == 60
    assert submitted["vibration_credit"] == 100
    assert_score(submitted["suitability_score"], 78.0)
    assert submitted["verdict"] == "SUITABLE"


def test_the_basis_alone_picks_the_variant_even_with_every_measurement_in_hand(api):
    """A fully measured investigation scores like the screening of the same asset.

    Nothing is missing on either assessment, so the two bases have nothing to
    diverge over and the second scores identically to the first, which shows the
    variant is chosen by the declared basis rather than by the absence of a
    measurement.

    Design: Corner/calculations/investigation_variant_selected_by_basis_even_when_nothing_is_missing
    """
    building = create_building(api, **NAMEPLATE)
    measurements = {
        "required_vibration_class": "VC_C",
        "required_exhaust_cfm": 50000,
        "required_power_kw": 700,
        "measured_floor_to_floor_ft": 14.0,
        "measured_live_load_psf": 88,
        "measured_vibration_class": "VC_C",
    }
    investigation = open_assessment(
        api, building["id"], assessment_basis="INVESTIGATION", **measurements
    )

    investigated = submit_assessment(api, investigation["id"])
    decide_assessment(api, investigation["id"], "ACCEPT")
    screening = open_assessment(
        api, building["id"], assessment_basis="SCREENING", **measurements
    )
    screened = submit_assessment(api, screening["id"])

    assert investigated["assessment_basis"] == "INVESTIGATION"
    assert_score(investigated["suitability_score"], 78.0)
    assert investigated["verdict"] == "SUITABLE"
    assert investigated["hard_fail_capped"] is False
    assert screened["assessment_basis"] == "SCREENING"
    assert_score(screened["suitability_score"], 78.0)
    assert screened["verdict"] == "SUITABLE"
    assert (
        get_success_data(api.get_building(building["id"], LANDLORD_HEADERS))[
            "suitability_state"
        ]
        == "ASSESSING"
    )


def test_the_top_volume_tier_includes_the_deal_that_lands_exactly_on_it(api):
    """One cent of rent per foot decides which credit a deal earns.

    Two otherwise identical deals differ by a single cent of proposed allowance;
    the one whose provisional authorisation lands exactly on the top tier floor
    earns the larger credit and finishes with the smaller authorisation, which is
    the counter-intuitive consequence of an inclusive threshold.

    Design: Corner/calculations/volume_credit_tier_boundary_exact_five_million_and_one_cent_below
    """
    bundle = setup_conversion_approved_building(
        api,
        floor_numbers=(2, 3),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE), 3: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
    )
    tenant = create_tenant(
        api, "VIVARIUM", legal_name="Vivarium Partners LLC",
        credit_tier="INVESTMENT_GRADE",
    )
    tenant_headers = make_tenant_headers(tenant["id"])
    on_the_line = create_lease(
        api, tenant["id"], bundle["building"]["id"], bundle["floors"][2]["id"],
        20000, **VIVARIUM_LEASE,
    )
    just_under = create_lease(
        api, tenant["id"], bundle["building"]["id"], bundle["floors"][3]["id"],
        20000, **VIVARIUM_LEASE,
    )
    generous = get_success_data(
        api.create_proposal(
            on_the_line["id"],
            proposal_payload(on_the_line["version"], 162.00),
            LANDLORD_NEGOTIATOR_HEADERS,
        )
    )
    a_cent_less = get_success_data(
        api.create_proposal(
            just_under["id"],
            proposal_payload(just_under["version"], 161.99),
            LANDLORD_NEGOTIATOR_HEADERS,
        )
    )

    validate_success(api.accept_proposal(generous["id"], tenant_headers), 200)
    validate_success(api.accept_proposal(a_cent_less["id"], tenant_headers), 200)

    top_tier = get_lease(api, on_the_line["id"])
    middle_tier = get_lease(api, just_under["id"])
    assert_lease(top_tier)
    assert_money(top_tier["lab_premium_psf_applied"], 88.00, "lab_premium_psf_applied")
    assert_money(
        top_tier["provisional_authorized_ti_usd"], 5000000.00, "provisional"
    )
    assert_money(top_tier["volume_credit_psf"], 3.00, "volume_credit_psf")
    assert_money(top_tier["final_allowance_psf"], 247.00, "final_allowance_psf")
    assert_money(top_tier["ti_authorized_usd"], 4940000.00, "ti_authorized_usd")
    assert_money(
        top_tier["restoration_escrow_required_usd"], 250000.00, "escrow required"
    )
    assert_money(
        middle_tier["provisional_authorized_ti_usd"], 4999800.00, "provisional"
    )
    assert_money(middle_tier["volume_credit_psf"], 1.50, "volume_credit_psf")
    assert_money(middle_tier["final_allowance_psf"], 248.49, "final_allowance_psf")
    assert_money(middle_tier["ti_authorized_usd"], 4969800.00, "ti_authorized_usd")
    assert_money(
        middle_tier["restoration_escrow_required_usd"], 250000.00, "escrow required"
    )


def test_the_third_package_finds_the_allowance_already_spent(api):
    """Truncation at the floor of the bucket is not an error.

    The first package commits its whole eligible figure, the second is cut down to
    whatever is left, and the third earns a substantial eligible figure and commits
    nothing at all because the bucket is empty.

    Design: Corner/calculations/commitment_waterfall_truncates_the_third_phase_at_the_uncommitted_floor
    """
    bundle = _qc_permitted_project(api)
    shell, vivarium, lab_mep = _scheduled_packages(
        api,
        bundle["project"]["id"],
        [
            {"premium_class": "SHELL", "work_class": "QUIET",
             "hard_cost_usd": 100000.00, "restoration_cost_usd": 90000.00},
            {"premium_class": "VIVARIUM", "work_class": "QUIET",
             "hard_cost_usd": 250000.00, "restoration_cost_usd": 420000.00},
            {"premium_class": "LAB_MEP", "work_class": "QUIET",
             "hard_cost_usd": 80000.00, "restoration_cost_usd": 180000.00},
        ],
    )

    first = _run_to_completion(api, shell["id"])
    second = _run_to_completion(api, vivarium["id"])
    third = _run_to_completion(api, lab_mep["id"])

    assert_money(first["ti_committed_usd"], 60000.00, "ti_committed_usd")
    assert_money(second["ti_eligible_usd"], 286875.00, "ti_eligible_usd")
    assert_money(second["ti_committed_usd"], 140000.00, "ti_committed_usd")
    assert_money(third["ti_eligible_usd"], 80240.00, "ti_eligible_usd")
    assert_money(third["ti_committed_usd"], 0.00, "ti_committed_usd")
    lease = get_lease(api, bundle["lease"]["id"])
    assert_money(lease["ti_committed_usd"], 200000.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 0.00, "ti_uncommitted_usd")
    assert_money(lease["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert_money(lease["ti_forfeited_usd"], 0.00, "ti_forfeited_usd")
    assert_ledger_identity(lease)


def test_the_bucket_is_consumed_in_the_order_the_work_actually_finishes(api):
    """Finishing last in the numbering can still mean claiming first.

    The highest-numbered package is completed first and absorbs the entire
    authorisation, leaving the two packages ahead of it in the numbering with
    eligible figures they cannot claim -- the reverse of what a sequence-ordered
    waterfall would produce.

    Design: Corner/calculations/commitment_waterfall_follows_completion_order_not_sequence_no
    """
    bundle = _qc_permitted_project(api)
    shell, lab_mep, vivarium = _scheduled_packages(
        api,
        bundle["project"]["id"],
        [
            {"premium_class": "SHELL", "work_class": "QUIET",
             "hard_cost_usd": 100000.00, "restoration_cost_usd": 90000.00},
            {"premium_class": "LAB_MEP", "work_class": "QUIET",
             "hard_cost_usd": 80000.00, "restoration_cost_usd": 180000.00},
            {"premium_class": "VIVARIUM", "work_class": "QUIET",
             "hard_cost_usd": 250000.00, "restoration_cost_usd": 420000.00},
        ],
    )
    assert vivarium["sequence_no"] == 3

    last_in_the_numbering = _run_to_completion(api, vivarium["id"])
    first_in_the_numbering = _run_to_completion(api, shell["id"])
    second_in_the_numbering = _run_to_completion(api, lab_mep["id"])

    assert_money(
        last_in_the_numbering["ti_committed_usd"], 200000.00, "ti_committed_usd"
    )
    assert_money(
        first_in_the_numbering["ti_committed_usd"], 0.00, "ti_committed_usd"
    )
    assert_money(
        second_in_the_numbering["ti_committed_usd"], 0.00, "ti_committed_usd"
    )
    assert_money(
        last_in_the_numbering["ti_eligible_usd"], 286875.00, "ti_eligible_usd"
    )
    assert_money(
        first_in_the_numbering["ti_eligible_usd"], 60000.00, "ti_eligible_usd"
    )
    assert_money(
        second_in_the_numbering["ti_eligible_usd"], 80240.00, "ti_eligible_usd"
    )
    lease = get_lease(api, bundle["lease"]["id"])
    assert_money(lease["ti_committed_usd"], 200000.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 0.00, "ti_uncommitted_usd")
    assert_ledger_identity(lease)
