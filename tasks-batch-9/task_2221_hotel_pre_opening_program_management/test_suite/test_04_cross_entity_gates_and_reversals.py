"""Cross-entity gates and compensating reversals.

Two families of behaviour live here. The first covers gates whose answer lives
on a different record than the one being mutated: a permit that waits on a
construction milestone, an onboarding that waits on a delivered orientation
class, a guarantee that waits on the commercial dimension of the program. The
second covers reversals that must return a counter to exactly the value it held
before the forward move — a cancelled purchase order, a cancelled room block
and a decertified system.
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import PreOpeningApiClient
from test_helpers.api_errors import (
    ERR_BOOKING_NOT_OPEN,
    ERR_GATING_MILESTONE_NOT_COMPLETE,
    ERR_ORIENTATION_NOT_COMPLETED,
)
from test_helpers.assertions import (
    assert_budget_split,
    assert_cents,
    assert_ratio,
)
from test_helpers.constants import CODE_CONSTRUCTION_COMPLETE
from test_helpers.fixtures import (
    add_test_run,
    baseline,
    complete_milestone,
    complete_session,
    make_block,
    make_budget_line,
    make_hire,
    make_hiring_plan,
    make_milestone,
    make_ose_order,
    make_permit,
    make_program,
    make_punch_item,
    make_system,
    make_training_session,
    open_booking,
    program_version,
    read_budget_lines,
    read_program,
    read_readiness,
    respond_to_offer,
    resolve_block,
    set_clock,
    start_milestone,
)
from test_helpers.test_users import (
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
)

# ─── File-local setup helpers ─────────────────────────────────────────────────


def _program_with_construction_milestone(
    api: PreOpeningApiClient, duration_days: int, **program_overrides: Any
) -> Dict[str, Any]:
    """A baselined program whose single milestone carries CONSTRUCTION_COMPLETE."""
    program = make_program(api, **program_overrides)
    milestone = make_milestone(
        api,
        program["id"],
        code=CODE_CONSTRUCTION_COMPLETE,
        name="Construction complete",
        duration_days=duration_days,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)
    return {"program": read_program(api, program["id"]), "milestone": milestone}


def _quarry_lane_with_draft_permit(api: PreOpeningApiClient) -> Dict[str, Any]:
    """Construction under way, and a food-service file drafted against it."""
    built = _program_with_construction_milestone(
        api,
        60,
        property_name="Quarry Lane Hotel",
        brand_code="QLH",
        room_count=105,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    built["milestone"] = start_milestone(api, built["milestone"]["id"])
    built["permit"] = make_permit(
        api,
        built["program"]["id"],
        built["milestone"]["id"],
        permit_type="FOOD_SERVICE",
        review_days=21,
    )
    return built


def _wrenfield_accepted_hire(api: PreOpeningApiClient) -> Dict[str, Any]:
    """An accepted engineering hire enrolled in an orientation not yet delivered."""
    built = _program_with_construction_milestone(
        api,
        90,
        property_name="Wrenfield Hotel",
        brand_code="WFH",
        room_count=118,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    plan = make_hiring_plan(
        api,
        built["program"]["id"],
        department="ENGINEERING",
        headcount_target=1,
        wave_start_date="2026-09-10",
    )
    session = make_training_session(
        api,
        built["program"]["id"],
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
        full_name="Dara Nwosu",
        hourly_rate_cents=2500,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    respond_to_offer(api, hire["id"], "ACCEPT")
    set_clock(api, "2026-09-20T00:00:00Z", TALENT_MANAGER)
    built.update({"plan": plan, "session": session, "hire": hire})
    return built


def _construction_complete_program(
    api: PreOpeningApiClient, **program_overrides: Any
) -> Dict[str, Any]:
    """A program driven to CONSTRUCTION_COMPLETE over 2026-09-01..2026-11-30."""
    built = _program_with_construction_milestone(api, 90, **program_overrides)
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, built["milestone"]["id"])
    set_clock(api, "2026-11-30T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, built["milestone"]["id"])
    built["program"] = read_program(api, built["program"]["id"])
    return built


def _elmswick_accepted_block(api: PreOpeningApiClient) -> Dict[str, Any]:
    """An accepted pre-opening block on a program whose book was then suspended."""
    built = _construction_complete_program(
        api,
        property_name="Elmswick Hotel",
        brand_code="EWH",
        room_count=190,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    program_id = built["program"]["id"]
    open_booking(api, program_id)
    built["block"] = make_block(
        api,
        program_id,
        program_version(api, program_id),
        account_name="Elmswick Alumni Weekend",
        arrival_date="2026-12-01",
        night_count=4,
        room_count=19,
        rate_cents=20000,
    )
    get_success_data(
        api.suspend_booking(program_id, COMMERCIAL_DIRECTOR, {"reason": "Rate parity audit"})
    )
    return built


def _thornbury_at_risk_block(api: PreOpeningApiClient) -> Dict[str, Any]:
    """A frozen program whose only block was swept into AT_RISK."""
    built = _construction_complete_program(
        api,
        property_name="Thornbury Hotel",
        brand_code="TBH",
        room_count=205,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=500,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )
    program_id = built["program"]["id"]
    open_booking(api, program_id)
    built["block"] = make_block(
        api,
        program_id,
        program_version(api, program_id),
        account_name="Thornbury Wedding Party",
        arrival_date="2026-12-01",
        night_count=4,
        room_count=19,
        rate_cents=20000,
    )
    built["punch"] = make_punch_item(
        api,
        program_id,
        headers=QUALITY_INSPECTOR,
        description="Elevator machine room fire rating incomplete",
        severity="CRITICAL",
    )
    return built


def _barrow_point_committed_order(api: PreOpeningApiClient) -> Dict[str, Any]:
    """One committed housekeeping order against a one-million-cent SETUP line."""
    program = make_program(
        api,
        property_name="Barrow Point Hotel",
        brand_code="BPH",
        room_count=112,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    line = make_budget_line(api, program["id"], category="SETUP", authorized_cents=1000000)
    order = make_ose_order(
        api,
        program["id"],
        line["id"],
        line["version"],
        description="Housekeeping carts",
        amount_cents=400000,
        pallet_count=4,
        delivery_window_start="2026-10-01",
        delivery_window_end="2026-10-15",
    )
    return {"program": program, "budget_line": line, "order": order}


def _calder_wharf_certified_system(api: PreOpeningApiClient) -> Dict[str, Any]:
    """A certified property-management system with one clean run behind it."""
    program = make_program(
        api,
        property_name="Calder Wharf Hotel",
        brand_code="CWH",
        room_count=98,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    system = make_system(api, program["id"], system_type="PMS", is_required=True)
    add_test_run(
        api,
        system["id"],
        "2026-09-10T10:00:00Z",
        40,
        40,
        headers=TEST_RUNNER_INTEGRATOR,
        blocker_count=0,
    )
    certified = get_success_data(api.certify_system(system["id"], CERTIFYING_INTEGRATOR))
    return {"program": program, "system": certified}


# ─── Cross-entity gate: the permit waits on the milestone ─────────────────────


class TestPermitSubmitGatingMilestone:
    """A file cannot reach the authority before its gating milestone finishes."""

    def test_submitting_while_the_gating_milestone_runs_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """The food-service application is gated on the construction milestone,
        which is still in progress, so the licensing coordinator cannot file it.

        First submission demands that the gating milestone be `COMPLETE`; if it is not, the request is refused with `ERR_GATING_MILESTONE_NOT_COMPLETE`.

        Design: Difficulty/cross_entity_state_dependency/permit_submit_blocked_until_gating_milestone_complete
        """
        built = _quarry_lane_with_draft_permit(api)
        assert built["milestone"]["state"] == "IN_PROGRESS"
        assert built["permit"]["state"] == "DRAFT"

        response = api.submit_permit_application(built["permit"]["id"], LICENSING_COORDINATOR)

        validate_error(response, ERR_GATING_MILESTONE_NOT_COMPLETE, 422)

    def test_refused_submission_leaves_both_records_where_they_were(
        self, api: PreOpeningApiClient
    ) -> None:
        """The file stays a draft with no submission stamp, the milestone keeps
        running and the program has not entered licensing.

        An application begins in `DRAFT` with `submitted_at`, `issued_at` and `deficiency_reason` null and `resubmission_count` at 0.

        Design: Difficulty/cross_entity_state_dependency/permit_submit_blocked_until_gating_milestone_complete
        """
        built = _quarry_lane_with_draft_permit(api)

        api.submit_permit_application(built["permit"]["id"], LICENSING_COORDINATOR)

        permit = get_success_data(
            api.get_permit_application(built["permit"]["id"], LICENSING_COORDINATOR)
        )
        assert permit["state"] == "DRAFT"
        assert permit["submitted_at"] is None
        assert permit["resubmission_count"] == 0

        milestone = get_success_data(
            api.get_milestone(built["milestone"]["id"], CONSTRUCTION_MANAGER)
        )
        assert milestone["state"] == "IN_PROGRESS"

        program = read_program(api, built["program"]["id"])
        assert program["schedule_state"] == "BASELINED"
        assert program["issued_mandatory_permit_count"] == 0

    def test_completing_the_gating_milestone_opens_the_submission(
        self, api: PreOpeningApiClient
    ) -> None:
        """Once the sixty-day milestone is signed off on the last day of October
        the same file goes through, and because it is a mandatory type it drags
        the program into licensing.

        On success `submitted_at` is stamped from the logical clock instant, and if the application is mandatory and the program's delivery dimension is sitting at `CONSTRUCTION_COMPLETE`, that dimension advances `CONSTRUCTION_COMPLETE → LICENSING` — the first mandatory file to reach the authority is what puts the program into licensing.

        Design: Difficulty/cross_entity_state_dependency/permit_submit_blocked_until_gating_milestone_complete
        """
        built = _quarry_lane_with_draft_permit(api)
        set_clock(api, "2026-10-31T00:00:00Z", CONSTRUCTION_MANAGER)
        completed = complete_milestone(api, built["milestone"]["id"])
        assert completed["state"] == "COMPLETE"

        response = api.submit_permit_application(built["permit"]["id"], LICENSING_COORDINATOR)

        permit = validate_success(response, 200)
        assert permit["state"] == "SUBMITTED"
        assert is_iso8601_timestamp(permit["submitted_at"])
        assert permit["submitted_at"].startswith("2026-10-31T00:00:00")
        assert permit["is_mandatory"] is True
        assert read_program(api, built["program"]["id"])["schedule_state"] == "LICENSING"


# ─── Cross-entity gate: onboarding waits on the orientation class ─────────────


class TestOnboardOrientationGate:
    """Nobody joins the payroll until the orientation class has been delivered."""

    def test_onboarding_before_the_orientation_is_delivered_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """The engineering hire has accepted and her start date has passed, but
        the orientation class she is enrolled in has not been marked delivered.

        It moves a hire `ACCEPTED → ONBOARDED` and requires two things: the hire must have a non-null `orientation_session_id` whose session is in state `COMPLETED`, else `ERR_ORIENTATION_NOT_COMPLETED`; and the logical clock date must have reached or passed the hire's `start_date`, else `ERR_INVALID_HIRE_STATE`.

        Design: Difficulty/cross_entity_state_dependency/hire_onboard_blocked_until_orientation_session_completed
        """
        built = _wrenfield_accepted_hire(api)

        response = api.onboard_hire(built["hire"]["id"], TALENT_MANAGER)

        validate_error(response, ERR_ORIENTATION_NOT_COMPLETED, 422)

    def test_refused_onboarding_leaves_the_staffing_rollup_at_zero(
        self, api: PreOpeningApiClient
    ) -> None:
        """The hire stays accepted with no onboarding stamp, the class keeps its
        single enrolment, and neither the plan's ratio nor the program's
        readiness moves.

        `readiness_flag` flips to `READY` once `onboarded_count` reaches at least eighty percent of `headcount_target` — precisely, once `onboarded_count` multiplied by 100 is at least `headcount_target` multiplied by 80 — and reads `NOT_READY` otherwise.

        Design: Difficulty/cross_entity_state_dependency/hire_onboard_blocked_until_orientation_session_completed
        """
        built = _wrenfield_accepted_hire(api)

        api.onboard_hire(built["hire"]["id"], TALENT_MANAGER)

        hire = get_success_data(api.get_hire(built["hire"]["id"], TALENT_MANAGER))
        assert hire["state"] == "ACCEPTED"
        assert hire["onboarded_at"] is None

        sessions, _ = validate_paginated(
            api.list_training_sessions(built["program"]["id"], TALENT_MANAGER)
        )
        assert sessions[0]["state"] == "SCHEDULED"
        assert sessions[0]["enrolled_count"] == 1

        plans, _ = validate_paginated(
            api.list_hiring_plans(built["program"]["id"], TALENT_MANAGER)
        )
        assert plans[0]["onboarded_count"] == 0
        assert_ratio(plans[0]["staffing_ratio"], 0.0)
        assert plans[0]["readiness_flag"] == "NOT_READY"

        program = read_program(api, built["program"]["id"])
        assert program["departments_ready_count"] == 0
        assert_ratio(program["readiness_score"], 0.2000)

    def test_delivering_the_orientation_unlocks_onboarding(
        self, api: PreOpeningApiClient
    ) -> None:
        """Marking the class delivered lets the same call through, and the single
        onboarded engineer carries the whole department to readiness.

        Third, caused by the second, the program's `departments_ready_count` rises by one, so the posture computation reruns and `readiness_score` rises by its staffing term.

        Design: Difficulty/cross_entity_state_dependency/hire_onboard_blocked_until_orientation_session_completed
        """
        built = _wrenfield_accepted_hire(api)
        delivered = complete_session(api, built["session"]["id"])
        assert delivered["state"] == "COMPLETED"

        response = api.onboard_hire(built["hire"]["id"], TALENT_MANAGER)

        hire = validate_success(response, 200)
        assert hire["state"] == "ONBOARDED"
        assert is_iso8601_timestamp(hire["onboarded_at"])
        assert hire["onboarded_at"].startswith("2026-09-20T00:00:00")

        plans, _ = validate_paginated(
            api.list_hiring_plans(built["program"]["id"], TALENT_MANAGER)
        )
        assert plans[0]["onboarded_count"] == 1
        assert_ratio(plans[0]["staffing_ratio"], 1.0)
        assert plans[0]["readiness_flag"] == "READY"

        program = read_program(api, built["program"]["id"])
        assert program["departments_ready_count"] == 1
        assert_ratio(program["readiness_score"], 0.4500)


# ─── Cross-entity gate: the guarantee waits on the commercial dimension ───────


class TestGuaranteeRequiresBookingOpen:
    """A block already on the books cannot be guaranteed while selling is halted."""

    def test_guaranteeing_while_booking_is_suspended_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """The alumni-weekend block was accepted while the book was open, but a
        rate parity audit has since suspended selling, so the guarantee is
        refused on the program's commercial state.

        Guaranteeing a block moves it `ACCEPTED → GUARANTEED`, requires the commercial dimension to be `BOOKING_OPEN` (else `ERR_BOOKING_NOT_OPEN`) and the posture not to be `FROZEN` (else `ERR_PROGRAM_FROZEN`), and reruns the contingency computation so that this block's `contingency_cents` gains the program's `guarantee_penalty_cents` and the program's `contingency_liability_cents` is recomputed.

        Design: Difficulty/cross_entity_state_dependency/block_guarantee_requires_program_commercial_state_booking_open
        """
        built = _elmswick_accepted_block(api)
        assert built["block"]["state"] == "ACCEPTED"
        assert read_program(api, built["program"]["id"])["commercial_state"] == "BOOKING_SUSPENDED"

        response = api.guarantee_block(built["block"]["id"], COMMERCIAL_DIRECTOR)

        validate_error(response, ERR_BOOKING_NOT_OPEN, 409)

    def test_refused_guarantee_adds_no_penalty_to_the_exposure(
        self, api: PreOpeningApiClient
    ) -> None:
        """The block keeps the accepted-state exposure of nineteen hundred
        thousand cents of relocation plus an eight percent fee, with no
        guarantee penalty layered on top.

        Sixth, the block's `contingency_cents` is that subtotal, plus the program's `guarantee_penalty_cents` when and only when the block's state is `GUARANTEED`.

        Design: Difficulty/cross_entity_state_dependency/block_guarantee_requires_program_commercial_state_booking_open
        """
        built = _elmswick_accepted_block(api)

        api.guarantee_block(built["block"]["id"], COMMERCIAL_DIRECTOR)

        blocks, _ = validate_paginated(
            api.list_reservation_blocks(built["program"]["id"], COMMERCIAL_DIRECTOR)
        )
        assert blocks[0]["state"] == "ACCEPTED"
        assert blocks[0]["is_pre_opening"] is True
        assert_cents(blocks[0]["contingency_cents"], 2052000)

        program = read_program(api, built["program"]["id"])
        assert_cents(program["contingency_liability_cents"], 2052000)
        assert program["commercial_state"] == "BOOKING_SUSPENDED"
        assert program["readiness_posture"] == "MOBILIZING"

    def test_reopening_the_book_lets_the_guarantee_through(
        self, api: PreOpeningApiClient
    ) -> None:
        """When selling resumes the same guarantee succeeds and the program's
        exposure grows by exactly the guarantee penalty.

        Guaranteeing a block moves it `ACCEPTED → GUARANTEED`, requires the commercial dimension to be `BOOKING_OPEN` (else `ERR_BOOKING_NOT_OPEN`) and the posture not to be `FROZEN` (else `ERR_PROGRAM_FROZEN`), and reruns the contingency computation so that this block's `contingency_cents` gains the program's `guarantee_penalty_cents` and the program's `contingency_liability_cents` is recomputed.

        Design: Difficulty/cross_entity_state_dependency/block_guarantee_requires_program_commercial_state_booking_open
        """
        built = _elmswick_accepted_block(api)
        reopened = open_booking(api, built["program"]["id"])
        assert reopened["commercial_state"] == "BOOKING_OPEN"

        response = api.guarantee_block(built["block"]["id"], COMMERCIAL_DIRECTOR)

        block = validate_success(response, 200)
        assert block["state"] == "GUARANTEED"
        assert_cents(block["contingency_cents"], 2202000)
        assert_cents(
            read_program(api, built["program"]["id"])["contingency_liability_cents"], 2202000
        )


# ─── Compensating reversal: the cancelled purchase order ──────────────────────


class TestOseOrderCancelBudgetInvariant:
    """Cancelling an order returns the line to its pre-commitment split."""

    def test_cancellation_terminates_the_order_without_receiving_it(
        self, api: PreOpeningApiClient
    ) -> None:
        """The housekeeping carts are dropped because the supplier discontinued
        the item, so the order ends cancelled and was never stored.

        Cancelling an order moves it `COMMITTED → CANCELLED`, also terminal, and accepts an optional `reason`.

        Design: Difficulty/compensating_invariant/ose_order_cancel_restores_budget_line_without_authorized_drift
        """
        built = _barrow_point_committed_order(api)

        response = api.cancel_ose_order(
            built["order"]["id"],
            PROCUREMENT_MANAGER,
            {"reason": "Supplier discontinued the SKU"},
        )

        order = validate_success(response, 200)
        assert order["state"] == "CANCELLED"
        assert order["received_at"] is None
        assert order["stored_bay_code"] is None

    def test_cancellation_restores_available_without_touching_authorized(
        self, api: PreOpeningApiClient
    ) -> None:
        """The four hundred thousand cents of commitment come back as available
        money, spend stays at nothing, and the authorized figure has not drifted
        by a cent.

        The commitment is released: the line's `committed_cents` falls by `amount_cents` while its `available_cents` rises by the same amount, and `authorized_cents` does not drift by a single cent — the compensating invariant that lets a pre-opening budget be audited months later.

        Design: Difficulty/compensating_invariant/ose_order_cancel_restores_budget_line_without_authorized_drift
        """
        built = _barrow_point_committed_order(api)
        committed_line = read_budget_lines(api, built["program"]["id"])[0]
        assert_budget_split(committed_line, 1000000, 400000, 0)

        api.cancel_ose_order(
            built["order"]["id"],
            PROCUREMENT_MANAGER,
            {"reason": "Supplier discontinued the SKU"},
        )

        line = read_budget_lines(api, built["program"]["id"])[0]
        assert_budget_split(line, 1000000, 0, 0)
        assert_cents(line["available_cents"], 1000000)
        assert_cents(line["authorized_cents"], built["budget_line"]["authorized_cents"])

    def test_cancellation_returns_both_cost_at_completion_bases_to_zero(
        self, api: PreOpeningApiClient
    ) -> None:
        """With no commitment and no spend left anywhere, and nobody on the
        payroll, both published cost views fall back to nothing.

        The `COMMITMENT_BASIS` figure, written to `cost_at_completion_commitment_cents`, is the purchase-order view: the sum, over all three of the program's budget lines, of each line's `committed_cents` plus its `spent_cents`.

        Design: Difficulty/compensating_invariant/ose_order_cancel_restores_budget_line_without_authorized_drift
        """
        built = _barrow_point_committed_order(api)

        api.cancel_ose_order(
            built["order"]["id"],
            PROCUREMENT_MANAGER,
            {"reason": "Supplier discontinued the SKU"},
        )

        readiness = read_readiness(api, built["program"]["id"])
        assert_cents(readiness["cost_at_completion_commitment_cents"], 0)
        assert_cents(readiness["cost_at_completion_accrual_cents"], 0)


# ─── Compensating reversal: the cancelled room block ──────────────────────────


class TestBlockCancellationRestoresRoomNights:
    """Cancelling an at-risk block hands the room-nights back to the ceiling."""

    def test_the_freeze_sweep_puts_the_block_at_risk_with_full_exposure(
        self, api: PreOpeningApiClient
    ) -> None:
        """A critical fire-rating defect freezes the property, which sweeps the
        wedding block into at-risk with the punch reason and leaves the
        seventy-six room-nights and their exposure on the program.

        The `at_risk_reason` recorded is exactly `PERMIT_DEFICIENCY` when the freeze was caused by a mandatory permit application sitting in `DEFICIENT`, and otherwise exactly `CRITICAL_PUNCH_OPEN` when it was caused by `open_critical_punch_count` being above zero; in every other state the field is null.

        Design: Difficulty/compensating_invariant/block_cancellation_restores_committed_room_nights_and_zero_liability
        """
        built = _thornbury_at_risk_block(api)

        blocks, _ = validate_paginated(
            api.list_reservation_blocks(built["program"]["id"], COMMERCIAL_DIRECTOR)
        )
        assert blocks[0]["state"] == "AT_RISK"
        assert blocks[0]["at_risk_reason"] == "CRITICAL_PUNCH_OPEN"
        assert_cents(blocks[0]["contingency_cents"], 2052000)

        program = read_program(api, built["program"]["id"])
        assert program["committed_room_nights"] == 76
        assert_cents(program["contingency_liability_cents"], 2052000)

    def test_cancelling_zeroes_the_block_s_contingency(
        self, api: PreOpeningApiClient
    ) -> None:
        """Settling the block by cancellation ends it terminally with no
        contingency owed, while the derived room-night and revenue figures it was
        created with are preserved on the record.

        `CANCEL` moves it `AT_RISK → CANCELLED`, also terminal: `contingency_cents` is reset to 0 and its `room_nights` leave `committed_room_nights`, restoring that counter to exactly its pre-create value — the compensating invariant that keeps the room-night ceiling honest across a full accept-and-cancel round trip.

        Design: Difficulty/compensating_invariant/block_cancellation_restores_committed_room_nights_and_zero_liability
        """
        built = _thornbury_at_risk_block(api)

        block = resolve_block(api, built["block"]["id"], "CANCEL")

        assert block["state"] == "CANCELLED"
        assert_cents(block["contingency_cents"], 0)
        assert block["room_nights"] == 76
        assert_cents(block["revenue_cents"], 1520000)

    def test_cancelling_restores_the_program_counters_to_their_pre_create_values(
        self, api: PreOpeningApiClient
    ) -> None:
        """Both program counters return to zero — the exact values they held
        before the block existed — while the freeze and the suspended book
        remain in place.

        `committed_room_nights` is the sum of `room_nights` over its reservation blocks in state `ACCEPTED`, `GUARANTEED` or `AT_RISK`.

        Design: Difficulty/compensating_invariant/block_cancellation_restores_committed_room_nights_and_zero_liability
        """
        built = _thornbury_at_risk_block(api)

        resolve_block(api, built["block"]["id"], "CANCEL")

        program = read_program(api, built["program"]["id"])
        assert program["committed_room_nights"] == 0
        assert_cents(program["contingency_liability_cents"], 0)
        assert program["readiness_posture"] == "FROZEN"
        assert program["commercial_state"] == "BOOKING_SUSPENDED"


# ─── Compensating reversal: decertification ───────────────────────────────────


class TestSystemDecertification:
    """A fresh run against a certified system withdraws the certification."""

    def test_a_new_run_decertifies_the_system_and_clears_the_certifier(
        self, api: PreOpeningApiClient
    ) -> None:
        """A regression run on the property-management system finds nine of ten
        cases passing and one open blocker, which pulls the certified system back
        into testing and erases the sign-off.

        From `PLANNED` it goes to `TESTING`; a system already in `TESTING` stays in `TESTING` for a retest; a system in `FAILED` recovers into `TESTING`; and a system in `CERTIFIED` is **decertified** back into `TESTING`, which clears `certified_by_user_id` and `certified_at` as the exact compensation of the earlier certification, recomputes the program's `certified_system_count` and reruns the posture computation.

        Design: Difficulty/compensating_invariant/system_decertification_restores_certified_count_and_clears_certifier
        """
        built = _calder_wharf_certified_system(api)
        assert built["system"]["state"] == "CERTIFIED"
        assert built["system"]["certified_by_user_id"] == "si-certifier-2"

        run = add_test_run(
            api,
            built["system"]["id"],
            "2026-09-18T10:00:00Z",
            20,
            18,
            headers=TEST_RUNNER_INTEGRATOR,
            blocker_count=1,
        )

        assert_ratio(run["pass_rate"], 0.9)
        assert run["result"] == "FAILED"
        system = get_success_data(
            api.get_system_implementation(built["system"]["id"], CERTIFYING_INTEGRATOR)
        )
        assert system["state"] == "TESTING"
        assert system["certified_by_user_id"] is None
        assert system["certified_at"] is None

    def test_decertification_leaves_every_run_inside_the_pooled_rate(
        self, api: PreOpeningApiClient
    ) -> None:
        """The latest rate follows the regression run while the pooled rate keeps
        both runs — fifty-eight of sixty cases — and the open blocker is carried
        forward from the newest run.

        `cumulative_pass_rate` pools every run of the system: it is the sum of `cases_passed` across all runs divided by the sum of `cases_total` across all runs, rounded half up to four decimal places, and null when there are no runs.

        Design: Difficulty/compensating_invariant/system_decertification_restores_certified_count_and_clears_certifier
        """
        built = _calder_wharf_certified_system(api)

        add_test_run(
            api,
            built["system"]["id"],
            "2026-09-18T10:00:00Z",
            20,
            18,
            headers=TEST_RUNNER_INTEGRATOR,
            blocker_count=1,
        )

        system = get_success_data(
            api.get_system_implementation(built["system"]["id"], CERTIFYING_INTEGRATOR)
        )
        assert system["test_run_count"] == 2
        assert_ratio(system["latest_pass_rate"], 0.9)
        assert_ratio(system["cumulative_pass_rate"], 0.9667)
        assert system["open_blocker_count"] == 1

    def test_decertification_restores_the_program_s_certified_count_and_score(
        self, api: PreOpeningApiClient
    ) -> None:
        """The program's certified count falls back to zero — its value before
        the certification — so the systems term leaves the readiness score and
        the property drops back to mobilizing.

        `required_system_count` is the number of its system implementations whose `is_required` is true, and `certified_system_count` is the number of those required systems in state `CERTIFIED`.

        Design: Difficulty/compensating_invariant/system_decertification_restores_certified_count_and_clears_certifier
        """
        built = _calder_wharf_certified_system(api)
        before = read_program(api, built["program"]["id"])
        assert before["certified_system_count"] == 1
        assert_ratio(before["readiness_score"], 0.5000)

        add_test_run(
            api,
            built["system"]["id"],
            "2026-09-18T10:00:00Z",
            20,
            18,
            headers=TEST_RUNNER_INTEGRATOR,
            blocker_count=1,
        )

        program = read_program(api, built["program"]["id"])
        assert program["certified_system_count"] == 0
        assert program["required_system_count"] == 1
        assert_ratio(program["readiness_score"], 0.2000)
        assert program["readiness_posture"] == "MOBILIZING"
