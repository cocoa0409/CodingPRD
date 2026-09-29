"""Non-linear lifecycles and the cascades that fan out of a single call.

Each scenario is rebuilt from an empty database, because the server is restarted
before every test and the logical clock is moved explicitly wherever a stamped
instant or a "now" comparison matters.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, is_iso8601_timestamp

from test_helpers.assertions import (
    assert_cents,
    assert_posture,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.fixtures import (
    baseline,
    complete_milestone,
    complete_session,
    link_milestones,
    make_block,
    make_hire,
    make_hiring_plan,
    make_milestone,
    make_permit,
    make_program,
    make_punch_item,
    make_training_session,
    onboard,
    open_booking,
    read_program,
    read_readiness,
    record_review,
    reopen_punch_item,
    respond_to_offer,
    rule_on_punch_item,
    set_clock,
    start_milestone,
    submit_for_verification,
    submit_permit,
    suspend_booking,
)
from test_helpers.test_users import (
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    TALENT_MANAGER,
    USER_ID_CONSTRUCTION_MANAGER,
    USER_ID_QUALITY_INSPECTOR,
)

# =============================================================================
# Scenario builders reused by the tests in this file
# =============================================================================


def _foundry_row_deficient_permit(api):
    """A food-service file found deficient, freezing the programme.

    The 60-day construction milestone finished on 2026-11-05 and the authority
    then returned the application, charging its 21 review days to that milestone
    and driving it out of COMPLETE into BLOCKED.
    """
    program = make_program(
        api,
        property_name="Foundry Row Hotel",
        brand_code="FRH",
        room_count=160,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
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
        duration_days=60,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-11-05T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)

    permit = make_permit(
        api,
        program["id"],
        milestone["id"],
        LICENSING_COORDINATOR,
        permit_type="FOOD_SERVICE",
        review_days=21,
    )
    submit_permit(api, permit["id"], LICENSING_COORDINATOR)
    record_review(
        api,
        permit["id"],
        "DEFICIENCY",
        LICENSING_COORDINATOR,
        deficiency_reason="Grease interceptor undersized",
    )
    return {
        "program_id": program["id"],
        "milestone_id": milestone["id"],
        "permit_id": permit["id"],
    }


def _union_yard_booking_open_with_draft_permit(api):
    """A CONSTRUCTION_COMPLETE programme already selling, with a drafted file.

    Booking acceptance was opened before the licensing sequence started, so the
    two dimensions are at CONSTRUCTION_COMPLETE and BOOKING_OPEN respectively.
    """
    program = make_program(
        api,
        property_name="Union Yard Hotel",
        brand_code="UYH",
        room_count=170,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
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
        duration_days=60,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-11-05T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, milestone["id"], CONSTRUCTION_MANAGER)
    open_booking(api, program["id"], COMMERCIAL_DIRECTOR)

    permit = make_permit(
        api,
        program["id"],
        milestone["id"],
        LICENSING_COORDINATOR,
        permit_type="FOOD_SERVICE",
        review_days=21,
    )
    return {"program_id": program["id"], "permit_id": permit["id"]}


def _old_mill_resubmitted_punch_item(api):
    """A major defect that was rejected once and has been handed back for review.

    Construction manager cm-1 raised and submitted the defect, inspector qi-1
    rejected it, and cm-1 submitted the reworked defect again.
    """
    program = make_program(
        api,
        property_name="Old Mill Lodge",
        brand_code="OML",
        room_count=90,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    item = make_punch_item(
        api,
        program["id"],
        CONSTRUCTION_MANAGER,
        description="Lobby millwork gap",
        severity="MAJOR",
    )
    submit_for_verification(api, item["id"], CONSTRUCTION_MANAGER)
    rule_on_punch_item(api, item["id"], "REJECT", QUALITY_INSPECTOR)
    submit_for_verification(api, item["id"], CONSTRUCTION_MANAGER)
    return {"program_id": program["id"], "item_id": item["id"]}


def _ashgrove_with_submitted_permit_and_block(api, arrival_date):
    """A selling programme in LICENSING holding one accepted block.

    M1 finished on 2026-11-05 and drives the 20-day certificate-of-occupancy
    milestone, so the committed projected opening is 2026-12-09 before the
    authority is heard from.
    """
    program = make_program(
        api,
        property_name="Ashgrove Hotel",
        brand_code="AGH",
        room_count=210,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
        slip_tolerance_days=10,
    )
    m1 = make_milestone(
        api,
        program["id"],
        code="CONSTRUCTION_COMPLETE",
        name="Construction complete",
        duration_days=60,
        planned_start_date="2026-09-01",
    )
    m2 = make_milestone(
        api,
        program["id"],
        code="CO_ISSUANCE",
        name="Certificate of occupancy issuance",
        duration_days=20,
        planned_start_date="2026-11-05",
    )
    link_milestones(api, m1["id"], m2["id"], dependency_type="FINISH_START", lag_days=0)
    baseline(api, program["id"], PROGRAM_DIRECTOR)

    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, m1["id"], CONSTRUCTION_MANAGER)
    set_clock(api, "2026-11-05T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, m1["id"], CONSTRUCTION_MANAGER)

    permit = make_permit(
        api,
        program["id"],
        m1["id"],
        LICENSING_COORDINATOR,
        permit_type="FOOD_SERVICE",
        review_days=21,
    )
    submit_permit(api, permit["id"], LICENSING_COORDINATOR)
    open_booking(api, program["id"], COMMERCIAL_DIRECTOR)
    block = make_block(
        api,
        program["id"],
        None,
        COMMERCIAL_DIRECTOR,
        account_name="Ashgrove Conference Bureau",
        arrival_date=arrival_date,
        night_count=4,
        room_count=19,
        rate_cents=20000,
    )
    return {
        "program_id": program["id"],
        "m1_id": m1["id"],
        "m2_id": m2["id"],
        "permit_id": permit["id"],
        "block_id": block["id"],
        "block": block,
    }


def _kestrel_bay_ready_to_onboard(api):
    """One accepted engineering hire whose orientation session has been delivered.

    The programme has no systems and no permit applications, so the readiness
    score is carried entirely by its schedule term until the hire onboards.
    """
    program = make_program(
        api,
        property_name="Kestrel Bay Resort",
        brand_code="KBR",
        room_count=130,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=120,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
        slip_tolerance_days=10,
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
        department="ENGINEERING",
        headcount_target=1,
        wave_start_date="2026-09-10",
    )
    session = make_training_session(
        api,
        program["id"],
        TALENT_MANAGER,
        title="Engineering orientation",
        training_room_code="TR-2",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T12:00:00Z",
        capacity=8,
        department="ENGINEERING",
    )
    hire = make_hire(
        api,
        plan["id"],
        session["id"],
        TALENT_MANAGER,
        full_name="Chidi Okafor",
        hourly_rate_cents=2500,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    respond_to_offer(api, hire["id"], "ACCEPT", TALENT_MANAGER)
    set_clock(api, "2026-09-20T00:00:00Z", TALENT_MANAGER)
    complete_session(api, session["id"], TALENT_MANAGER)
    return {
        "program_id": program["id"],
        "plan_id": plan["id"],
        "hire_id": hire["id"],
        "session_id": session["id"],
    }


def _read_milestone(api, milestone_id):
    return get_success_data(api.get_milestone(milestone_id, PROGRAM_DIRECTOR))


def _read_permit(api, permit_id):
    return get_success_data(api.get_permit_application(permit_id, LICENSING_COORDINATOR))


def _read_punch_item(api, item_id):
    return get_success_data(api.get_punch_item(item_id, QUALITY_INSPECTOR))


def _read_hire(api, hire_id):
    return get_success_data(api.get_hire(hire_id, TALENT_MANAGER))


def _read_plan(api, program_id, plan_id):
    plans = get_success_data(api.list_hiring_plans(program_id, TALENT_MANAGER))
    return next(plan for plan in plans if plan["id"] == plan_id)


def _read_block(api, program_id, block_id):
    blocks = get_success_data(
        api.list_reservation_blocks(program_id, COMMERCIAL_DIRECTOR)
    )
    return next(block for block in blocks if block["id"] == block_id)


# =============================================================================
# Rule: the permit application re-enters a state it already occupied
# =============================================================================


class TestPermitResubmissionCycle:
    """DEFICIENT is a detour, not a terminus: the file goes back to SUBMITTED."""

    def test_resubmission_returns_the_file_to_submitted(self, api):
        """Foundry Row answers the grease-interceptor finding and hands the same file
        back to the authority. It re-enters SUBMITTED, and the resubmission counter
        is what proves the loop was travelled rather than the row having stayed put.

        A resubmission increments `resubmission_count` by one, refreshes `submitted_at`, and clears `deficiency_reason`.

        Design: Difficulty/non_linear_state_machine/permit_deficiency_resubmission_cycle_returns_to_submitted
        """
        built = _foundry_row_deficient_permit(api)
        assert _read_permit(api, built["permit_id"])["state"] == "DEFICIENT"

        resubmitted = get_success_data(
            api.submit_permit_application(built["permit_id"], LICENSING_COORDINATOR)
        )
        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["deficiency_reason"] is None

        program = read_program(api, built["program_id"])
        assert program["schedule_state"] == "LICENSING"

    def test_resubmission_releases_the_milestone_but_keeps_the_blocked_days(self, api):
        """The 21 review days the finding cost are already spent and cannot be given
        back. Handing the file back in releases the milestone to IN_PROGRESS while
        the charge and the recorded finish date both stay on the record.

        It also releases the milestone it had blocked: a gating milestone sitting in `BLOCKED` returns `BLOCKED → IN_PROGRESS`, retaining its `blocked_days_accrued` because those review days have already been consumed and cannot be given back, and the schedule is recomputed on the changed inputs.

        Design: Difficulty/non_linear_state_machine/permit_deficiency_resubmission_cycle_returns_to_submitted
        """
        built = _foundry_row_deficient_permit(api)
        blocked = _read_milestone(api, built["milestone_id"])
        assert blocked["state"] == "BLOCKED"
        assert blocked["blocked_days_accrued"] == 21

        get_success_data(
            api.submit_permit_application(built["permit_id"], LICENSING_COORDINATOR)
        )

        released = _read_milestone(api, built["milestone_id"])
        assert released["state"] == "IN_PROGRESS"
        assert released["blocked_days_accrued"] == 21
        assert released["actual_finish_date"] == "2026-11-05"

    def test_the_freeze_lifts_while_both_projections_keep_the_charge(self, api):
        """With no mandatory file sitting deficient any more the freeze condition has
        cleared. The committed view still carries the 21 charged days to 2026-12-10
        while the optimistic view, which ignores them, reads 2026-11-19.

        The posture is recomputed too, and because the mandatory-deficiency freeze condition has cleared, a `FROZEN` posture can lift here.

        Design: Difficulty/non_linear_state_machine/permit_deficiency_resubmission_cycle_returns_to_submitted
        """
        built = _foundry_row_deficient_permit(api)
        assert read_program(api, built["program_id"])["readiness_posture"] == "FROZEN"

        get_success_data(
            api.submit_permit_application(built["permit_id"], LICENSING_COORDINATOR)
        )

        program = read_program(api, built["program_id"])
        assert_posture(program, "MOBILIZING")
        assert program["projected_opening_date_committed"] == "2026-12-10"
        assert program["projected_opening_date_optimistic"] == "2026-11-19"


# =============================================================================
# Rule: the two dimensions on the program record move independently
# =============================================================================


class TestDimensionsAdvanceIndependently:
    """Delivery progress and commercial posture are separate state machines."""

    def test_permit_submission_advances_only_the_delivery_dimension(self, api):
        """Union Yard is already selling when its first mandatory file reaches the
        authority. That submission moves the delivery dimension into licensing and
        leaves the commercial dimension exactly where it was.

        On success `submitted_at` is stamped from the logical clock instant, and if the application is mandatory and the program's delivery dimension is sitting at `CONSTRUCTION_COMPLETE`, that dimension advances `CONSTRUCTION_COMPLETE → LICENSING` — the first mandatory file to reach the authority is what puts the program into licensing.

        Design: Difficulty/non_linear_state_machine/program_schedule_and_commercial_dimensions_advance_independently
        """
        built = _union_yard_booking_open_with_draft_permit(api)
        before = read_program(api, built["program_id"])
        assert_program_dimensions(
            before,
            schedule_state="CONSTRUCTION_COMPLETE",
            commercial_state="BOOKING_OPEN",
        )

        submitted = get_success_data(
            api.submit_permit_application(built["permit_id"], LICENSING_COORDINATOR)
        )
        assert submitted["state"] == "SUBMITTED"

        after = read_program(api, built["program_id"])
        assert_program_dimensions(
            after, schedule_state="LICENSING", commercial_state="BOOKING_OPEN"
        )

    def test_manual_suspension_advances_only_the_commercial_dimension(self, api):
        """A rate-strategy review stops the reservation ramp. Suspending acceptance
        moves the commercial dimension alone; the programme is still in licensing on
        the delivery side and still merely mobilizing.

        The two dimensions evolve independently: nothing about the commercial dimension is implied by the delivery dimension except where this document says so.

        Design: Difficulty/non_linear_state_machine/program_schedule_and_commercial_dimensions_advance_independently
        """
        built = _union_yard_booking_open_with_draft_permit(api)
        submit_permit(api, built["permit_id"], LICENSING_COORDINATOR)

        suspended = suspend_booking(api, built["program_id"], COMMERCIAL_DIRECTOR)
        assert suspended["commercial_state"] == "BOOKING_SUSPENDED"

        program = read_program(api, built["program_id"])
        assert_program_dimensions(
            program,
            schedule_state="LICENSING",
            commercial_state="BOOKING_SUSPENDED",
            readiness_posture="MOBILIZING",
        )


# =============================================================================
# Rule: the punch-list item carries two nested cycles
# =============================================================================


class TestPunchItemRejectAndReopenCycles:
    """A rework loop through REJECTED and a reopen loop back to OPEN."""

    def test_rework_loop_ends_in_verification_with_the_rejection_counted(self, api):
        """The Old Mill defect was rejected once, reworked and submitted again by the
        same construction manager. Inspector qi-1 now verifies it, and the rejection
        counter still records the loop.

        `REJECT` moves the item `READY_FOR_VERIFICATION → REJECTED` and increments `rejection_count` by one.

        Design: Difficulty/non_linear_state_machine/punch_item_reject_resubmit_verify_reopen_cycle
        """
        built = _old_mill_resubmitted_punch_item(api)
        item = _read_punch_item(api, built["item_id"])
        assert item["state"] == "READY_FOR_VERIFICATION"
        assert item["rejection_count"] == 1
        assert item["submitted_by_user_id"] == USER_ID_CONSTRUCTION_MANAGER

        verified = rule_on_punch_item(api, built["item_id"], "VERIFY", QUALITY_INSPECTOR)
        assert verified["state"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_ID_QUALITY_INSPECTOR
        assert verified["rejection_count"] == 1
        assert verified["blocks_certificate_of_occupancy"] is False

    def test_reopen_loop_returns_the_item_to_open_and_clears_both_actors(self, api):
        """Reopening the verified defect takes the row back to the state it started
        in, with both recorded operators wiped. The rework counter is not part of
        that compensation and still reads one.

        Reopening clears both `verified_by_user_id` and `submitted_by_user_id`, and turns `blocks_certificate_of_occupancy` back to true when the item's `severity` is `CRITICAL`.

        Design: Difficulty/non_linear_state_machine/punch_item_reject_resubmit_verify_reopen_cycle
        """
        built = _old_mill_resubmitted_punch_item(api)
        rule_on_punch_item(api, built["item_id"], "VERIFY", QUALITY_INSPECTOR)

        reopened = reopen_punch_item(
            api, built["item_id"], "Gap reappeared after settling", QUALITY_INSPECTOR
        )
        assert reopened["state"] == "OPEN"
        assert reopened["verified_by_user_id"] is None
        assert reopened["submitted_by_user_id"] is None
        assert reopened["rejection_count"] == 1
        assert reopened["blocks_certificate_of_occupancy"] is False

        program = read_program(api, built["program_id"])
        assert program["open_critical_punch_count"] == 0
        assert_posture(program, "MOBILIZING")


# =============================================================================
# Rule: one deficiency decision fans out five links deep
# =============================================================================


class TestPermitDeficiencyCascade:
    """Permit, milestone, schedule, posture and finally the reservation book."""

    def test_deficiency_charges_the_milestone_and_moves_the_committed_date(self, api):
        """Ashgrove's food-service file is returned deficient. The 21 review days are
        charged to the completed construction milestone, which keeps driving its
        successor, so the committed opening moves from 2026-12-09 to 2026-12-30 while
        the optimistic view does not budge.

        **Second**, caused by the first, the gating milestone absorbs the review cost: the permit's `review_days` is added to that milestone's `blocked_days_accrued`, and the milestone moves to `BLOCKED` from either `IN_PROGRESS` or `COMPLETE` — and when it comes from `COMPLETE` its `actual_finish_date` and its `actual_duration_days` are both retained, so the schedule keeps using that finish date as the driving finish for its successors.

        Design: Difficulty/transitive_cascade/permit_deficiency_freezes_program_and_puts_blocks_at_risk
        """
        built = _ashgrove_with_submitted_permit_and_block(api, "2026-12-20")
        before = read_program(api, built["program_id"])
        assert before["projected_opening_date_committed"] == "2026-12-09"

        deficient = record_review(
            api,
            built["permit_id"],
            "DEFICIENCY",
            LICENSING_COORDINATOR,
            deficiency_reason="Grease interceptor undersized",
        )
        assert deficient["state"] == "DEFICIENT"
        assert deficient["deficiency_reason"] == "Grease interceptor undersized"

        m1 = _read_milestone(api, built["m1_id"])
        assert m1["state"] == "BLOCKED"
        assert m1["blocked_days_accrued"] == 21
        assert m1["actual_finish_date"] == "2026-11-05"

        m2 = _read_milestone(api, built["m2_id"])
        assert m2["earliest_start_date"] == "2026-11-26"
        assert m2["earliest_finish_date"] == "2026-12-16"

        program = read_program(api, built["program_id"])
        assert program["projected_opening_date_committed"] == "2026-12-30"
        assert program["projected_opening_date_optimistic"] == "2026-12-09"
        assert program["schedule_slip_days"] == 0

    def test_the_freeze_suspends_selling_and_sweeps_the_block_to_at_risk(self, api):
        """A block arriving 20 December was a safe post-opening booking until the
        deficiency pushed the committed opening out to 30 December. The freeze
        suspends acceptance and the block is swept at risk, carrying 2052000 cents.

        **Fifth**, caused by the fourth, the commercial dimension moves `BOOKING_OPEN → BOOKING_SUSPENDED`, every reservation block in `ACCEPTED` or `GUARANTEED` whose `arrival_date` falls before the **new** committed projected opening date moves to `AT_RISK` with `at_risk_reason` recorded as `PERMIT_DEFICIENCY`, and the contingency-liability computation reruns over the changed book.

        Design: Difficulty/transitive_cascade/permit_deficiency_freezes_program_and_puts_blocks_at_risk
        """
        built = _ashgrove_with_submitted_permit_and_block(api, "2026-12-20")
        assert built["block"]["state"] == "ACCEPTED"
        assert built["block"]["is_pre_opening"] is False
        assert_cents(built["block"]["contingency_cents"], 0)

        record_review(
            api,
            built["permit_id"],
            "DEFICIENCY",
            LICENSING_COORDINATOR,
            deficiency_reason="Grease interceptor undersized",
        )

        program = read_program(api, built["program_id"])
        assert_posture(program, "FROZEN")
        assert program["commercial_state"] == "BOOKING_SUSPENDED"
        assert_cents(program["contingency_liability_cents"], 2052000)
        assert program["committed_room_nights"] == 76

        block = _read_block(api, built["program_id"], built["block_id"])
        assert block["state"] == "AT_RISK"
        assert block["at_risk_reason"] == "PERMIT_DEFICIENCY"
        assert block["is_pre_opening"] is True
        assert_cents(block["contingency_cents"], 2052000)

    def test_a_block_arriving_after_the_new_committed_date_is_left_alone(self, api):
        """The sweep is only reachable because the committed date moved past the
        arrival. A block arriving 15 January is still beyond the new 30 December
        projection, so it stays accepted with no exposure even though the freeze fires.

        Every other block — one in a terminal state, or one whose `arrival_date` is on or after the committed projected opening — holds `contingency_cents` of 0.

        Design: Difficulty/transitive_cascade/permit_deficiency_freezes_program_and_puts_blocks_at_risk
        """
        built = _ashgrove_with_submitted_permit_and_block(api, "2027-01-15")

        record_review(
            api,
            built["permit_id"],
            "DEFICIENCY",
            LICENSING_COORDINATOR,
            deficiency_reason="Grease interceptor undersized",
        )

        program = read_program(api, built["program_id"])
        assert_posture(program, "FROZEN")
        assert program["commercial_state"] == "BOOKING_SUSPENDED"
        assert program["projected_opening_date_committed"] == "2026-12-30"
        assert_cents(program["contingency_liability_cents"], 0)

        block = _read_block(api, built["program_id"], built["block_id"])
        assert block["state"] == "ACCEPTED"
        assert block["at_risk_reason"] is None
        assert block["is_pre_opening"] is False
        assert_cents(block["contingency_cents"], 0)


# =============================================================================
# Rule: onboarding one hire bubbles up two levels
# =============================================================================


class TestHireOnboardingBubblesUp:
    """Hire to hiring plan to programme score, in three caused steps."""

    def test_before_onboarding_the_score_is_the_schedule_term_alone(self, api):
        """Kestrel Bay has no systems and no permit applications, and its one
        engineering plan has nobody on payroll yet. Only the unblemished schedule
        term contributes, so the score is exactly 0.2000.

        The **staffing ratio** is `departments_ready_count` divided by `hiring_plan_count`, or 0.0 when `hiring_plan_count` is zero.

        Design: Difficulty/transitive_cascade/hire_onboarding_bubbles_plan_readiness_into_program_score
        """
        built = _kestrel_bay_ready_to_onboard(api)

        readiness = read_readiness(api, built["program_id"])
        assert_ratio(readiness["readiness_score"], 0.2000)
        assert_ratio(readiness["staffing_ratio"], 0.0)
        assert_ratio(readiness["systems_ratio"], 0.0)
        assert_ratio(readiness["permit_ratio"], 0.0)
        assert_ratio(readiness["schedule_term"], 1.0)
        assert readiness["schedule_slip_days"] == 0

        plan = _read_plan(api, built["program_id"], built["plan_id"])
        assert plan["onboarded_count"] == 0
        assert plan["readiness_flag"] == "NOT_READY"

    def test_onboarding_stamps_the_hire_and_flips_the_plan_to_ready(self, api):
        """The engineer's orientation has been delivered and the clock has passed the
        first payroll day, so onboarding succeeds. The single onboarded head is the
        whole one-person department, so the plan flips to ready.

        Second, caused by the first, the plan's `onboarded_count` rises by one, its `staffing_ratio` is recomputed, and its `readiness_flag` flips `NOT_READY → READY` as soon as the eighty-percent threshold above is met.

        Design: Difficulty/transitive_cascade/hire_onboarding_bubbles_plan_readiness_into_program_score
        """
        built = _kestrel_bay_ready_to_onboard(api)

        onboarded = onboard(api, built["hire_id"], TALENT_MANAGER)
        assert onboarded["state"] == "ONBOARDED"
        assert is_iso8601_timestamp(onboarded["onboarded_at"])
        assert onboarded["onboarded_at"].startswith("2026-09-20")

        plan = _read_plan(api, built["program_id"], built["plan_id"])
        assert plan["onboarded_count"] == 1
        assert_ratio(plan["staffing_ratio"], 1.0)
        assert plan["readiness_flag"] == "READY"

    def test_plan_readiness_rescores_the_program_and_reprices_the_hire(self, api):
        """One ready department out of one raises the staffing term to its full 0.25
        weight, lifting the score from 0.2000 to 0.4500 — still short of the on-track
        floor. The hire's own accrual runs to the committed opening date.

        Third, caused by the second, the program's `departments_ready_count` rises by one, so the posture computation reruns and `readiness_score` rises by its staffing term.

        Design: Difficulty/transitive_cascade/hire_onboarding_bubbles_plan_readiness_into_program_score
        """
        built = _kestrel_bay_ready_to_onboard(api)
        onboard(api, built["hire_id"], TALENT_MANAGER)

        program = read_program(api, built["program_id"])
        assert program["departments_ready_count"] == 1
        assert program["hiring_plan_count"] == 1
        assert_ratio(program["readiness_score"], 0.4500)
        assert_posture(program, "MOBILIZING")

        readiness = read_readiness(api, built["program_id"])
        assert_ratio(readiness["staffing_ratio"], 1.0)
        assert_ratio(readiness["readiness_score"], 0.4500)

        assert_cents(_read_hire(api, built["hire_id"])["accrual_cents"], 1800000)
