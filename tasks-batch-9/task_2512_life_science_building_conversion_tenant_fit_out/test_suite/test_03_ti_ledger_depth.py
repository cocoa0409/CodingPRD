"""Allowance authorisation, the pro-rata draw and its reversal."""

from test_helpers import (
    USER_CX_TECH,
    USER_CX_WITNESS,
    assert_ledger_identity,
    assert_money,
    assert_proposal,
    accept_terms,
    draw_allowance,
    expected_authorization,
    get_lease,
    get_phase,
    get_project,
    get_record,
    phase_ti_eligible_usd,
    record_result,
    schedule_script,
    setup_lease_at_loi,
    setup_lease_with_committed_phases,
    setup_project_at_substantial_completion,
    volume_credit_psf,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
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
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}

# The three packages of the drawing case, in the order they complete.
DRAW_PHASES = [
    {
        "premium_class": "VIVARIUM",
        "work_class": "QUIET",
        "hard_cost_usd": 100000.00,
        "restoration_cost_usd": 420000.00,
    },
    {
        "premium_class": "LAB_MEP",
        "work_class": "QUIET",
        "hard_cost_usd": 20000.00,
        "restoration_cost_usd": 180000.00,
        "predecessor_index": 0,
    },
    {
        "premium_class": "SHELL",
        "work_class": "QUIET",
        "hard_cost_usd": 60000.00,
        "restoration_cost_usd": 90000.00,
        "predecessor_index": 1,
    },
]


def _biology_lease_with_three_complete_phases(api):
    """A 4000 sf biology lease authorised at 500,000.00 with three packages complete."""
    return setup_lease_with_committed_phases(
        api,
        DRAW_PHASES,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides={"base_rent_psf": 105.00},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={"design_exhaust_cfm": 15000, "design_power_kw": 220},
    )


def _synthesis_lease_at_loi(api):
    """A 24200 sf chemistry lease on the fifth floor, still at letter of intent."""
    return setup_lease_at_loi(
        api,
        research_type="CHEMISTRY_SYNTHESIS",
        premises_floor_number=5,
        floor_numbers=(5,),
        rentable_sf=24200,
        lease_overrides={
            "term_months": 180,
            "base_rent_psf": 118.00,
            "delivery_deadline": "2027-06-30T00:00:00Z",
        },
        building_overrides=NAMEPLATE,
        floor_overrides={5: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
    )


def test_the_seven_economics_steps_run_in_order_on_acceptance(api):
    """Acceptance computes the whole authorisation once, in a fixed order.

    A chemistry programme on the fifth floor carries its own premium plus the
    high-floor stack uplift, and the subtotal, the provisional authorisation,
    the volume credit, the final rate, the authorisation and the escrow
    requirement all follow from it.

    Design: Difficulty/combinatorial_formula/ti_allowance_tier_selected_on_provisional_not_final_authorization
    """
    bundle = _synthesis_lease_at_loi(api)
    accepted = accept_terms(
        api, bundle["lease"], bundle["tenant"]["id"], 140.00
    )
    lease = accepted["lease"]
    expected = expected_authorization("CHEMISTRY_SYNTHESIS", 140.00, 5, 24200)

    assert lease["status"] == "TERMS_ACCEPTED"
    assert_money(lease["accepted_allowance_psf"], 140.00, "accepted_allowance_psf")
    assert_money(lease["lab_premium_psf_applied"], 67.50, "lab_premium_psf_applied")
    assert_money(
        lease["provisional_authorized_ti_usd"], 5021500.00, "provisional authorisation"
    )
    assert_money(lease["volume_credit_psf"], 3.00, "volume_credit_psf")
    assert_money(lease["final_allowance_psf"], 204.50, "final_allowance_psf")
    assert_money(lease["ti_authorized_usd"], 4948900.00, "ti_authorized_usd")
    assert_money(
        lease["restoration_escrow_required_usd"], 250000.00, "escrow requirement"
    )
    for field, value in expected.items():
        assert_money(lease[field], value, field)


def test_the_credit_tier_is_never_reselected_from_the_post_credit_authorisation(api):
    """The tier is chosen from the pre-credit figure and then left alone.

    The provisional authorisation clears five million and earns the top credit,
    which then pulls the authorisation itself back below five million; the deal
    keeps the top credit rather than falling to the middle tier, and the ledger
    opens fully uncommitted at that figure.

    Design: Difficulty/combinatorial_formula/ti_allowance_tier_selected_on_provisional_not_final_authorization
    """
    bundle = _synthesis_lease_at_loi(api)
    accepted = accept_terms(
        api, bundle["lease"], bundle["tenant"]["id"], 140.00
    )
    lease = accepted["lease"]

    assert lease["provisional_authorized_ti_usd"] >= 5000000.00
    assert lease["ti_authorized_usd"] < 5000000.00
    assert_money(
        lease["volume_credit_psf"],
        volume_credit_psf(lease["provisional_authorized_ti_usd"]),
        "volume_credit_psf",
    )
    # Re-selecting the tier from the authorisation would have produced 1.50,
    # a final rate of 206.00 and an authorisation of 4,985,200.00.
    assert_money(lease["final_allowance_psf"], 204.50, "final_allowance_psf")
    assert lease["final_allowance_psf"] != 206.00
    assert_money(lease["ti_authorized_usd"], 4948900.00, "ti_authorized_usd")

    assert_money(lease["ti_uncommitted_usd"], 4948900.00, "ti_uncommitted_usd")
    assert_money(lease["ti_committed_usd"], 0.00, "ti_committed_usd")
    assert_money(lease["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert_money(lease["ti_forfeited_usd"], 0.00, "ti_forfeited_usd")
    assert_ledger_identity(lease)
    assert_proposal(accepted["proposal"])
    assert accepted["proposal"]["status"] == "ACCEPTED"


def test_each_completed_package_commits_its_own_class_weighted_eligible_cost(api):
    """Every premium class earns its own share and its own multiplier.

    Three packages of different classes complete in sequence, and each commits
    its own eligible figure against the allowance, so the committed bucket is
    the sum of three differently weighted lines rather than a single blended
    percentage of the hard costs.

    Design: Difficulty/combinatorial_formula/ti_draw_per_line_rounding_then_residual_to_largest_committed
    """
    bundle = _biology_lease_with_three_complete_phases(api)
    vivarium, lab_mep, shell = bundle["phases"]
    lease = bundle["lease"]

    assert_money(lease["ti_authorized_usd"], 500000.00, "ti_authorized_usd")
    assert_money(vivarium["ti_eligible_usd"], 114750.00, "vivarium eligible")
    assert_money(lab_mep["ti_eligible_usd"], 20060.00, "lab mep eligible")
    assert_money(shell["ti_eligible_usd"], 36000.00, "shell eligible")
    assert_money(
        vivarium["ti_eligible_usd"],
        phase_ti_eligible_usd(100000.00, "VIVARIUM"),
        "vivarium eligible",
    )
    assert_money(
        lab_mep["ti_eligible_usd"],
        phase_ti_eligible_usd(20000.00, "LAB_MEP"),
        "lab mep eligible",
    )
    assert_money(
        shell["ti_eligible_usd"], phase_ti_eligible_usd(60000.00, "SHELL"), "shell eligible"
    )

    for phase in (vivarium, lab_mep, shell):
        assert phase["status"] == "COMPLETE"
        assert_money(
            phase["ti_committed_usd"], phase["ti_eligible_usd"], "ti_committed_usd"
        )
    assert_money(lease["ti_committed_usd"], 170810.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 329190.00, "ti_uncommitted_usd")
    assert_ledger_identity(lease)


def test_the_draw_is_capped_then_rounded_per_line_with_the_residual_to_the_largest(api):
    """A draw is rounded line by line and the residual lands on one named package.

    The request is capped at three tenths of the authorisation, each package's
    pro-rata share is rounded on its own, and the one cent left over by that
    rounding is added to the package holding the largest committed figure -- not
    spread, and not dropped on the last line.

    Design: Difficulty/combinatorial_formula/ti_draw_per_line_rounding_then_residual_to_largest_committed
    """
    bundle = _biology_lease_with_three_complete_phases(api)
    vivarium, lab_mep, shell = bundle["phases"]

    lease = draw_allowance(api, bundle["lease"]["id"], 400000.00)

    assert_money(lease["ti_disbursed_usd"], 150000.00, "ti_disbursed_usd")
    assert_money(lease["ti_committed_usd"], 20810.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 329190.00, "ti_uncommitted_usd")
    assert_money(lease["ti_forfeited_usd"], 0.00, "ti_forfeited_usd")
    assert_money(lease["last_disbursement_usd"], 150000.00, "last_disbursement_usd")
    assert_ledger_identity(lease)

    lines = {
        "vivarium": get_phase(api, vivarium["id"])["ti_disbursed_usd"],
        "lab_mep": get_phase(api, lab_mep["id"])["ti_disbursed_usd"],
        "shell": get_phase(api, shell["id"])["ti_disbursed_usd"],
    }
    assert_money(lines["vivarium"], 100769.87, "vivarium line")
    assert_money(lines["lab_mep"], 17616.06, "lab mep line")
    assert_money(lines["shell"], 31614.07, "shell line")
    assert_money(sum(lines.values()), 150000.00, "sum of the lines")
    # The unrounded share of the largest committed package is 100,769.8613; the
    # residual cent is what carries it to 100,769.87.
    assert lines["vivarium"] > 100769.865


def test_a_failed_script_reverses_the_last_draw_to_the_cent_everywhere(api):
    """A failing script claws the most recent draw back on every row it touched.

    The lease returns to the committed and disbursed figures it held before the
    draw, and each package returns to nothing disbursed -- including the package
    that carried the residual cent, which a fresh pro-rata split would have left
    a cent short.

    Design: Difficulty/compensating_invariant/commissioning_fail_reverses_last_draw_across_lease_and_every_phase
    """
    bundle = setup_project_at_substantial_completion(
        api,
        DRAW_PHASES,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides={"base_rent_psf": 105.00},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={"design_exhaust_cfm": 15000, "design_power_kw": 220},
    )
    assert bundle["project"]["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    drawn = draw_allowance(api, bundle["lease"]["id"], 400000.00)
    assert_money(drawn["ti_disbursed_usd"], 150000.00, "ti_disbursed_usd")
    assert_money(drawn["ti_committed_usd"], 20810.00, "ti_committed_usd")
    assert_money(drawn["last_disbursement_usd"], 150000.00, "last_disbursement_usd")
    vivarium = get_phase(api, bundle["phases"][0]["id"])
    assert_money(vivarium["ti_disbursed_usd"], 100769.87, "residual-bearing line")

    record = schedule_script(api, bundle["project"]["id"], "IQ", USER_CX_TECH)
    failed = record_result(api, record["id"], "FAIL", USER_CX_WITNESS, 0.4)

    assert failed["status"] == "FAILED"
    assert failed["result"] == "FAIL"
    lease = get_lease(api, bundle["lease"]["id"])
    assert_money(lease["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
    assert_money(lease["ti_committed_usd"], 170810.00, "ti_committed_usd")
    assert_money(lease["ti_uncommitted_usd"], 329190.00, "ti_uncommitted_usd")
    assert_money(lease["ti_forfeited_usd"], 0.00, "ti_forfeited_usd")
    assert_money(lease["last_disbursement_usd"], 0.00, "last_disbursement_usd")
    assert_ledger_identity(lease)
    for index, expected_committed in enumerate((114750.00, 20060.00, 36000.00)):
        phase = get_phase(api, bundle["phases"][index]["id"])
        assert_money(phase["ti_disbursed_usd"], 0.00, "ti_disbursed_usd")
        assert_money(phase["ti_committed_usd"], expected_committed, "ti_committed_usd")


def test_a_second_failure_cannot_reverse_the_same_draw_twice(api):
    """Zeroing the recorded draw is what makes the reversal idempotent.

    The first failure claws the draw back and leaves nothing recorded to claw
    back; a second failing script therefore moves no money, and neither the
    construction status nor the passed-script count is disturbed by either
    failure.

    Design: Difficulty/compensating_invariant/commissioning_fail_reverses_last_draw_across_lease_and_every_phase
    """
    bundle = setup_project_at_substantial_completion(
        api,
        DRAW_PHASES,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides={"base_rent_psf": 105.00},
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={"design_exhaust_cfm": 15000, "design_power_kw": 220},
    )
    draw_allowance(api, bundle["lease"]["id"], 400000.00)
    first = schedule_script(api, bundle["project"]["id"], "IQ", USER_CX_TECH)
    record_result(api, first["id"], "FAIL", USER_CX_WITNESS, 0.4)
    after_first = get_lease(api, bundle["lease"]["id"])

    second = schedule_script(api, bundle["project"]["id"], "OQ", USER_CX_TECH)
    record_result(api, second["id"], "FAIL", USER_CX_WITNESS, 0.2)
    after_second = get_lease(api, bundle["lease"]["id"])

    for field in (
        "ti_authorized_usd",
        "ti_uncommitted_usd",
        "ti_committed_usd",
        "ti_disbursed_usd",
        "ti_forfeited_usd",
        "last_disbursement_usd",
    ):
        assert_money(after_second[field], after_first[field], field)
    assert after_second["status"] == "EXECUTED"
    assert_ledger_identity(after_second)

    project = get_project(api, bundle["project"]["id"])
    assert project["construction_status"] == "C_SUBSTANTIAL_COMPLETION"
    assert project["passed_script_count"] == 0
    assert get_record(api, first["id"])["status"] == "FAILED"
