"""Dual-variant projections and the combinatorial money/score formulas.

Every scenario here is built from an empty database through the public API,
because the server is restarted before each test and the logical clock starts at
its own startup instant.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import (
    assert_cents,
    assert_committed_is_authority,
    assert_posture,
    assert_ratio,
)
from test_helpers.fixtures import (
    add_test_run,
    baseline,
    certify,
    complete_milestone,
    complete_session,
    guarantee_block,
    link_milestones,
    make_block,
    make_budget_line,
    make_hire,
    make_hiring_plan,
    make_milestone,
    make_ose_order,
    make_permit,
    make_program,
    make_system,
    make_training_session,
    onboard,
    open_booking,
    read_program,
    read_readiness,
    record_review,
    reopen_milestone,
    respond_to_offer,
    set_clock,
    start_milestone,
    submit_permit,
)
from test_helpers.test_users import (
    BASELINING_DIRECTOR,
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROGRAM_DIRECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
)

# =============================================================================
# Scenario builders reused by the tests in this file
# =============================================================================


def _harbor_crest_after_rework(api):
    """A three-milestone chain whose first milestone has been reworked once.

    M1 finished 2026-12-05, was reopened for corridor fire-rating rework,
    restarted the same day and finished again on 2026-12-10, so its
    rework_count is 1 while M2 and M3 are untouched.
    """
    program = make_program(
        api,
        property_name="Harbor Crest Hotel",
        brand_code="HRC",
        room_count=180,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
        rework_buffer_days=3,
        slip_tolerance_days=10,
    )
    m1 = make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=90,
        planned_start_date="2026-09-01",
    )
    m2 = make_milestone(
        api,
        program["id"],
        code="CO_ISSUANCE",
        name="Certificate of occupancy issuance",
        duration_days=30,
        planned_start_date="2026-12-01",
    )
    m3 = make_milestone(
        api,
        program["id"],
        code="SYSTEMS_CUTOVER",
        name="Systems cutover",
        duration_days=25,
        planned_start_date="2027-01-05",
    )
    link_milestones(api, m1["id"], m2["id"], dependency_type="FINISH_START", lag_days=0)
    link_milestones(api, m2["id"], m3["id"], dependency_type="FINISH_START", lag_days=5)
    baseline(api, program["id"], BASELINING_DIRECTOR)

    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, m1["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-12-05T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, m1["id"], CONSTRUCTION_MANAGER)
    reopen_milestone(api, m1["id"], "Corridor fire-rating rework", CONSTRUCTION_MANAGER)
    start_milestone(api, m1["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-12-10T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, m1["id"], CONSTRUCTION_MANAGER)

    return {
        "program_id": program["id"],
        "m1_id": m1["id"],
        "m2_id": m2["id"],
        "m3_id": m3["id"],
    }


def _riverbend_with_two_accepted_hires(api):
    """A baselined program with two accepted hires and two committed orders.

    The single 90-day milestone puts projected_opening_date_committed at
    2026-12-14; the PAYROLL line carries a 400000-cent commitment and the
    MARKETING line a 250000-cent commitment, neither of them received.
    """
    program = make_program(
        api,
        property_name="Riverbend Suites",
        brand_code="RBS",
        room_count=150,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=90,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)

    plan = make_hiring_plan(
        api,
        program["id"],
        department="ROOMS",
        headcount_target=2,
        wave_start_date="2026-09-28",
    )
    hires = []
    for full_name in ("Ana Reyes", "Ben Oduya"):
        hire = make_hire(
            api,
            plan["id"],
            None,
            TALENT_MANAGER,
            full_name=full_name,
            hourly_rate_cents=1333.4,
            scheduled_hours_per_day=7.5,
            start_date="2026-09-28",
        )
        respond_to_offer(api, hire["id"], "ACCEPT", TALENT_MANAGER)
        hires.append(hire)

    payroll_line = make_budget_line(
        api, program["id"], PROGRAM_DIRECTOR, category="PAYROLL", authorized_cents=5000000
    )
    marketing_line = make_budget_line(
        api, program["id"], PROGRAM_DIRECTOR, category="MARKETING", authorized_cents=2000000
    )
    make_ose_order(
        api,
        program["id"],
        payroll_line["id"],
        payroll_line["version"],
        description="Pre-opening agency staffing retainer",
        amount_cents=400000,
        pallet_count=2,
        delivery_window_start="2026-10-01",
        delivery_window_end="2026-10-15",
    )
    make_ose_order(
        api,
        program["id"],
        marketing_line["id"],
        marketing_line["version"],
        description="Launch campaign print run",
        amount_cents=250000,
        pallet_count=3,
        delivery_window_start="2026-10-05",
        delivery_window_end="2026-10-20",
    )
    return {
        "program_id": program["id"],
        "hire_ids": [hire["id"] for hire in hires],
    }


def _lakeview_grand_half_ready(api):
    """A program sitting at exactly one half of its systems and staffing.

    Two required systems with only the PMS certified, two hiring plans with only
    ROOMS onboarded, one of the four mandatory permit types issued, and a
    committed projection six days past the contractual target date.
    """
    program = make_program(
        api,
        property_name="Lakeview Grand",
        brand_code="LVG",
        room_count=240,
        construction_start_date="2026-09-01",
        target_opening_date="2026-12-08",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
        slip_tolerance_days=10,
    )
    milestone = make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=90,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)

    rooms_plan = make_hiring_plan(
        api,
        program["id"],
        department="ROOMS",
        headcount_target=1,
        wave_start_date="2026-09-10",
    )
    make_hiring_plan(
        api,
        program["id"],
        department="ADMIN",
        headcount_target=1,
        wave_start_date="2026-09-10",
    )
    session = make_training_session(
        api,
        program["id"],
        TALENT_MANAGER,
        title="Rooms orientation",
        training_room_code="TR-1",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T12:00:00Z",
        capacity=10,
        department="ROOMS",
    )
    hire = make_hire(
        api,
        rooms_plan["id"],
        session["id"],
        TALENT_MANAGER,
        full_name="Ana Reyes",
        hourly_rate_cents=2000,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    respond_to_offer(api, hire["id"], "ACCEPT", TALENT_MANAGER)

    pms = make_system(api, program["id"], SYSTEMS_INTEGRATOR, system_type="PMS", is_required=True)
    make_system(api, program["id"], SYSTEMS_INTEGRATOR, system_type="POS", is_required=True)
    permit = make_permit(
        api,
        program["id"],
        milestone["id"],
        LICENSING_COORDINATOR,
        permit_type="ELEVATOR",
        review_days=21,
    )

    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-11-30T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)

    complete_session(api, session["id"], TALENT_MANAGER)
    onboard(api, hire["id"], TALENT_MANAGER)

    add_test_run(
        api,
        pms["id"],
        "2026-11-30T10:00:00Z",
        40,
        40,
        TEST_RUNNER_INTEGRATOR,
        blocker_count=0,
    )
    certify(api, pms["id"], CERTIFYING_INTEGRATOR)

    submit_permit(api, permit["id"], LICENSING_COORDINATOR)
    record_review(api, permit["id"], "ISSUE", LICENSING_COORDINATOR)

    return {"program_id": program["id"]}


def _cedar_point_three_hires(api, accepted):
    """Three identical hires on one plan, ``accepted`` of them moved to ACCEPTED.

    Each hire earns 1333.4 cents an hour over 7.5 hours a day — 10000.50 cents
    a day — from 2026-09-28 to the committed projected opening of 2026-12-14,
    which is 77 pre-opening days and therefore a fractional exact product.
    """
    program = make_program(
        api,
        property_name="Cedar Point Inn",
        brand_code="CPI",
        room_count=120,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=90,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)

    plan = make_hiring_plan(
        api,
        program["id"],
        department="FOOD_BEVERAGE",
        headcount_target=3,
        wave_start_date="2026-09-28",
    )
    hire_ids = []
    for full_name in ("Cora Lin", "Dan Mbeki", "Eve Tanaka"):
        hire = make_hire(
            api,
            plan["id"],
            None,
            TALENT_MANAGER,
            full_name=full_name,
            hourly_rate_cents=1333.4,
            scheduled_hours_per_day=7.5,
            start_date="2026-09-28",
        )
        hire_ids.append(hire["id"])
    for hire_id in hire_ids[:accepted]:
        respond_to_offer(api, hire_id, "ACCEPT", TALENT_MANAGER)
    return {"program_id": program["id"], "hire_ids": hire_ids}


def _meridian_harbour_booking_open(api):
    """A CONSTRUCTION_COMPLETE program accepting bookings on 2026-11-30.

    The 90-day milestone finished on 2026-11-30, so the committed projected
    opening is 2026-12-14 and any block arriving before that date is a
    pre-opening booking carrying contingency exposure.
    """
    program = make_program(
        api,
        property_name="Meridian Harbour",
        brand_code="MHB",
        room_count=200,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    milestone = make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=90,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-11-30T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    open_booking(api, program["id"], COMMERCIAL_DIRECTOR)
    return {"program_id": program["id"]}


def _read_milestone(api, milestone_id):
    return get_success_data(api.get_milestone(milestone_id, PROGRAM_DIRECTOR))


def _read_hire(api, hire_id):
    return get_success_data(api.get_hire(hire_id, TALENT_MANAGER))


# =============================================================================
# Rule: the schedule runs twice over the same rows
# =============================================================================


class TestScheduleVariantDivergenceAfterRework:
    """One reworked predecessor, two different projected opening dates."""

    def test_only_the_committed_variant_absorbs_the_rework_buffer(self, api):
        """Harbor Crest reworked its first milestone once. The optimistic view still
        projects 2027-02-22 while the committed view carries the three-day rework
        buffer and projects 2027-02-25, three days apart.

        Under the `COMMITTED` variant a milestone's effective duration is `duration_days` plus `blocked_days_accrued`, and every edge leaving a predecessor whose `rework_count` is above zero additionally absorbs the program's `rework_buffer_days`.

        Design: Difficulty/dual_variant_calc/schedule_variant_divergence_after_milestone_rework
        """
        built = _harbor_crest_after_rework(api)

        program = read_program(api, built["program_id"])
        assert program["projected_opening_date_optimistic"] == "2027-02-22"
        assert program["projected_opening_date_committed"] == "2027-02-25"
        assert program["projected_opening_date"] == "2027-02-25"
        assert_committed_is_authority(program)

        readiness = read_readiness(api, built["program_id"])
        assert readiness["projected_opening_date_optimistic"] == "2027-02-22"
        assert readiness["projected_opening_date_committed"] == "2027-02-25"
        assert readiness["variant_gap_days"] == 3

    def test_slip_and_posture_are_measured_on_the_committed_projection(self, api):
        """Only the committed projection is allowed to gate anything. It trails the
        1 February target by 24 days, which is well past the ten-day tolerance, so
        the programme is restricted rather than merely mobilizing.

        `schedule_slip_days` is the whole-day count by which the committed projected opening date exceeds `target_opening_date`, or zero when the committed projection is on or before the target — it never goes negative.

        Design: Difficulty/dual_variant_calc/schedule_variant_divergence_after_milestone_rework
        """
        built = _harbor_crest_after_rework(api)

        program = read_program(api, built["program_id"])
        assert program["schedule_slip_days"] == 24
        assert_posture(program, "RESTRICTED")

        readiness = read_readiness(api, built["program_id"])
        assert readiness["schedule_slip_days"] == 24
        assert readiness["readiness_posture"] == "RESTRICTED"

        m1 = _read_milestone(api, built["m1_id"])
        assert m1["rework_count"] == 1
        assert m1["actual_start_date"] == "2026-12-05"
        assert m1["actual_finish_date"] == "2026-12-10"
        assert m1["actual_duration_days"] == 5

    def test_backward_pass_leaves_every_milestone_on_the_critical_path(self, api):
        """The rework buffer that the forward pass added after the reworked milestone
        is subtracted again on the way back, so no milestone in the chain picks up
        artificial slack and all three stay critical.

        Because the rework allowance is subtracted here exactly as it was added in the forward pass, a milestone that only drives edges out of a reworked predecessor keeps zero float rather than gaining artificial slack.

        Design: Difficulty/dual_variant_calc/schedule_variant_divergence_after_milestone_rework
        """
        built = _harbor_crest_after_rework(api)

        m2 = _read_milestone(api, built["m2_id"])
        assert m2["earliest_start_date"] == "2026-12-13"
        assert m2["earliest_finish_date"] == "2027-01-12"

        m3 = _read_milestone(api, built["m3_id"])
        assert m3["earliest_start_date"] == "2027-01-17"
        assert m3["earliest_finish_date"] == "2027-02-11"

        for milestone_id in (built["m1_id"], built["m2_id"], built["m3_id"]):
            milestone = _read_milestone(api, milestone_id)
            assert milestone["total_float_days"] == 0
            assert milestone["is_critical"] is True

        program = read_program(api, built["program_id"])
        assert program["critical_path_milestone_count"] == 3


# =============================================================================
# Rule: cost at completion is published on two bases
# =============================================================================


class TestCostAtCompletionTwoBases:
    """Purchase-order money and forecast money from the same stored rows."""

    def test_commitment_basis_counts_only_budget_line_money(self, api):
        """Riverbend has committed 400000 cents of payroll and 250000 cents of
        marketing, and has two accepted hires who have not started yet. The
        purchase-order view sees 650000 cents and nothing else.

        The `COMMITMENT_BASIS` figure, written to `cost_at_completion_commitment_cents`, is the purchase-order view: the sum, over all three of the program's budget lines, of each line's `committed_cents` plus its `spent_cents`.

        Design: Difficulty/dual_variant_calc/cost_at_completion_commitment_vs_accrual_basis
        """
        built = _riverbend_with_two_accepted_hires(api)

        program = read_program(api, built["program_id"])
        assert program["projected_opening_date_committed"] == "2026-12-14"

        readiness = read_readiness(api, built["program_id"])
        assert_cents(readiness["cost_at_completion_commitment_cents"], 650000)

    def test_accrual_basis_swaps_the_payroll_commitment_for_the_projection(self, api):
        """The forecast view drops the payroll line's 400000-cent commitment and puts
        the two accepted hires' wages to the committed opening date in its place,
        landing 1140078 cents above the purchase-order view.

        The `ACCRUAL_BASIS` figure, written to `cost_at_completion_accrual_cents`, is the forecast view used for budget escalation: it sums `committed_cents` plus `spent_cents` over the program's budget lines whose `category` is **not** `PAYROLL`, adds the `PAYROLL` line's `spent_cents` alone (or zero when the program has no `PAYROLL` line), and then adds the program's `payroll_accrual_cents`.

        Design: Difficulty/dual_variant_calc/cost_at_completion_commitment_vs_accrual_basis
        """
        built = _riverbend_with_two_accepted_hires(api)

        for hire_id in built["hire_ids"]:
            assert_cents(_read_hire(api, hire_id)["accrual_cents"], 770039)

        readiness = read_readiness(api, built["program_id"])
        assert_cents(readiness["payroll_accrual_cents"], 1540078)
        assert_cents(readiness["cost_at_completion_accrual_cents"], 1790078)
        assert (
            readiness["cost_at_completion_accrual_cents"]
            - readiness["cost_at_completion_commitment_cents"]
            == 1140078
        )


# =============================================================================
# Rule: the readiness score is four weighted terms with a clamp
# =============================================================================


class TestReadinessScoreFourTermFormula:
    """Four component ratios, four constant weights, one ordered branch chain."""

    def test_four_component_terms_are_published_side_by_side(self, api):
        """Lakeview Grand has one of two systems certified, one of two departments
        ready, one of the four mandatory permits issued and six days of slip, so the
        clamped schedule term reads 0.8.

        The **schedule term** is 1.0 minus `schedule_slip_days` divided by 30, floored at 0.0 — in other words a month of slip drives the schedule term to zero and no further.

        Design: Difficulty/combinatorial_formula/readiness_score_four_term_weighted_with_clamped_slip_term
        """
        built = _lakeview_grand_half_ready(api)

        readiness = read_readiness(api, built["program_id"])
        assert_ratio(readiness["systems_ratio"], 0.5)
        assert_ratio(readiness["staffing_ratio"], 0.5)
        assert_ratio(readiness["permit_ratio"], 0.25)
        assert_ratio(readiness["schedule_term"], 0.8)
        assert readiness["schedule_slip_days"] == 6
        assert readiness["projected_opening_date_committed"] == "2026-12-14"

    def test_weighted_score_and_the_ordered_posture_branch(self, api):
        """The same four terms weighted at 0.30, 0.25, 0.25 and 0.20 give 0.4975.
        Nothing is frozen and six days of slip sits inside the ten-day tolerance, yet
        0.4975 is far below the on-track floor, so the programme is still mobilizing.

        `readiness_score` is the systems ratio weighted at 0.30, plus the staffing ratio weighted at 0.25, plus the permit ratio weighted at 0.25, plus the schedule term weighted at 0.20, rounded half up to four decimal places.

        Design: Difficulty/combinatorial_formula/readiness_score_four_term_weighted_with_clamped_slip_term
        """
        built = _lakeview_grand_half_ready(api)

        readiness = read_readiness(api, built["program_id"])
        assert_ratio(readiness["readiness_score"], 0.4975)
        assert readiness["readiness_posture"] == "MOBILIZING"

        program = read_program(api, built["program_id"])
        assert_ratio(program["readiness_score"], 0.4975)
        assert_posture(program, "MOBILIZING")
        assert program["certified_system_count"] == 1
        assert program["required_system_count"] == 2
        assert program["departments_ready_count"] == 1
        assert program["hiring_plan_count"] == 2
        assert program["issued_mandatory_permit_count"] == 1


# =============================================================================
# Rule: the payroll accrual rounds per hire before it is summed
# =============================================================================


class TestPayrollAccrualRoundingOrder:
    """Rounding order is pinned where it changes the answer by a cent."""

    def test_each_hire_rounds_before_the_program_total_is_summed(self, api):
        """Three Cedar Point hires each accrue exactly 770038.50 cents over the 77
        pre-opening days. Rounded per hire and then summed the programme owes
        2310117 cents; summed first and rounded once it would owe one cent less.

        The per-hire payroll accrual is rounded to whole cents once per hire and only then summed into the program total; summing exact products and rounding once at the end is not the specified order and produces a different total whenever discarded fractions carry.

        Design: Difficulty/combinatorial_formula/payroll_accrual_rounds_per_hire_before_summing
        """
        built = _cedar_point_three_hires(api, accepted=3)

        for hire_id in built["hire_ids"]:
            assert_cents(_read_hire(api, hire_id)["accrual_cents"], 770039)

        readiness = read_readiness(api, built["program_id"])
        assert_cents(readiness["payroll_accrual_cents"], 2310117)
        assert readiness["payroll_accrual_cents"] != 2310116

    def test_accrual_basis_with_no_payroll_line_is_the_projection_alone(self, api):
        """Cedar Point has authorized no budget lines at all, so the purchase-order
        view is zero and the forecast view is nothing but the three hires' projected
        wages.

        The `ACCRUAL_BASIS` figure, written to `cost_at_completion_accrual_cents`, is the forecast view used for budget escalation: it sums `committed_cents` plus `spent_cents` over the program's budget lines whose `category` is **not** `PAYROLL`, adds the `PAYROLL` line's `spent_cents` alone (or zero when the program has no `PAYROLL` line), and then adds the program's `payroll_accrual_cents`.

        Design: Difficulty/combinatorial_formula/payroll_accrual_rounds_per_hire_before_summing
        """
        built = _cedar_point_three_hires(api, accepted=3)

        readiness = read_readiness(api, built["program_id"])
        assert_cents(readiness["cost_at_completion_accrual_cents"], 2310117)
        assert_cents(readiness["cost_at_completion_commitment_cents"], 0)

    def test_an_offered_hire_is_outside_the_accrual_set(self, api):
        """With only two of the three offers accepted the programme accrues two
        rounded per-hire figures, 1540078 cents, and the candidate still holding an
        unanswered offer accrues nothing.

        That day count is multiplied by the hire's `hourly_rate_cents` and by its `scheduled_hours_per_day`, and the product is rounded half up to whole cents to give the hire's `accrual_cents`; a hire whose state is anything other than `ACCEPTED` or `ONBOARDED` holds `accrual_cents` of 0.

        Design: Difficulty/combinatorial_formula/payroll_accrual_rounds_per_hire_before_summing
        """
        built = _cedar_point_three_hires(api, accepted=2)

        first, second, third = built["hire_ids"]
        assert_cents(_read_hire(api, first)["accrual_cents"], 770039)
        assert_cents(_read_hire(api, second)["accrual_cents"], 770039)
        assert_cents(_read_hire(api, third)["accrual_cents"], 0)

        readiness = read_readiness(api, built["program_id"])
        assert_cents(readiness["payroll_accrual_cents"], 1540078)


# =============================================================================
# Rule: the contingency fee tier is keyed on the pre-fee relocation base
# =============================================================================


class TestContingencyAdminFeeTier:
    """The fee band is picked before the fee exists, and never re-picked."""

    def test_tier_is_selected_on_the_base_relocation_amount(self, api):
        """Meridian Harbour holds 19 rooms for four nights arriving 1 December, ahead
        of the committed opening. The 1900000-cent relocation base sits in the
        eight-percent band, so the contingency is 2052000 cents and not 2128000.

        Third, a fee tier is chosen **on that base relocation amount** — not on the subtotal and not on the final contingency: five percent when the base is below five thousand dollars (500,000 cents), eight percent when the base is at least five thousand dollars and below twenty thousand dollars (2,000,000 cents), and twelve percent when the base is at or above twenty thousand dollars.

        Design: Difficulty/combinatorial_formula/contingency_admin_fee_tier_keyed_on_pre_fee_base
        """
        built = _meridian_harbour_booking_open(api)

        block = make_block(
            api,
            built["program_id"],
            None,
            COMMERCIAL_DIRECTOR,
            account_name="Meridian Group",
            arrival_date="2026-12-01",
            night_count=4,
            room_count=19,
            rate_cents=20000,
        )
        assert block["room_nights"] == 76
        assert_cents(block["revenue_cents"], 1520000)
        assert block["is_pre_opening"] is True
        assert block["state"] == "ACCEPTED"
        assert_cents(block["contingency_cents"], 2052000)
        assert block["contingency_cents"] != 2128000

    def test_guarantee_penalty_lands_after_the_tier_has_been_chosen(self, api):
        """Guaranteeing the same block adds the flat 150000-cent penalty on top of
        the 2052000-cent subtotal. The penalty cannot promote the block into the
        twelve-percent band, so the exposure is exactly 2202000 cents.

        Because the guarantee penalty is added after tier selection, it can never push a block into a higher fee tier.

        Design: Difficulty/combinatorial_formula/contingency_admin_fee_tier_keyed_on_pre_fee_base
        """
        built = _meridian_harbour_booking_open(api)

        block = make_block(
            api,
            built["program_id"],
            None,
            COMMERCIAL_DIRECTOR,
            account_name="Meridian Group",
            arrival_date="2026-12-01",
            night_count=4,
            room_count=19,
            rate_cents=20000,
        )
        guaranteed = guarantee_block(api, block["id"], COMMERCIAL_DIRECTOR)
        assert guaranteed["state"] == "GUARANTEED"
        assert_cents(guaranteed["contingency_cents"], 2202000)

        program = read_program(api, built["program_id"])
        assert_cents(program["contingency_liability_cents"], 2202000)
        assert program["committed_room_nights"] == 76
