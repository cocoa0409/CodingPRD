"""Public review windows (gap rule, close boundary) and the board decision's
composite/participation gates plus slate-level cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cycle,
    create_material,
    get_cycle,
    get_material,
    set_clock,
    setup_cycle_board_pending,
    setup_cycle_in_pilot_open,
    setup_cycle_in_scoring,
    setup_two_candidate_cycle,
    submit_review,
    transition_cycle,
    create_pilot,
    transition_pilot,
    upsert_alignment,
    validate_error,
    vet_material,
)

SECRETARY = TEST_USERS["board_secretary_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]


def _drive_second_cycle_to_scoring(framework_id):
    """A second MATHEMATICS cycle on the same framework, driven to SCORING."""
    cycle = create_cycle(framework_id, school_year_start=2028)
    material = create_material(cycle["id"], title="Math Text B",
                               publisher_name="PubB")
    vet_material(material["id"])
    upsert_alignment(material["id"], standard_code="S1", coverage_rating="FULL")
    transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")
    transition_cycle(cycle["id"], "PILOT_OPEN")
    pilot = create_pilot(cycle["id"], material["id"], school_code="SCH-B",
                         teacher_count=1)
    transition_pilot(pilot["id"], "ACTIVE")
    submit_review(pilot["id"], "t1", (3, 4, 3, 3))
    transition_pilot(pilot["id"], "CLOSED")
    transition_cycle(cycle["id"], "SCORING")
    return cycle


class TestPublicReviewWindowGap:
    def test_short_gap_rejected(self, api):
        """PRD §3.4: "for every other cycle sharing this `subject_area` whose
        status is anything but `NOT_ADOPTED` and which already has a recorded
        review window, the new window must stand strictly clear by thirty days
        — either the new window opens more than thirty days after the
        existing window closes, or the existing window opens more than thirty
        days after the new window closes. Any other arrangement, including a
        gap of exactly thirty days, conflicts and is rejected with
        `ERR_PUBLIC_REVIEW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/public_review_window_gap_rule
        """
        # Cycle A opens its review at the default clock: [08-01, 08-31].
        ctx_a = setup_cycle_in_scoring()
        transition_cycle(ctx_a["cycle"]["id"], "PUBLIC_REVIEW")
        cycle_b = _drive_second_cycle_to_scoring(ctx_a["framework"]["id"])

        # 2026-09-15 is only 15 clear days after cycle A's 08-31 close.
        set_clock("2026-09-15T00:00:00Z")
        validate_error(
            api.transition_cycle(cycle_b["id"], {"to_state": "PUBLIC_REVIEW"},
                                 SECRETARY),
            ApiErrorId.ERR_PUBLIC_REVIEW_WINDOW_CONFLICT)

    def test_clear_gap_accepted_and_window_stamped(self, api):
        """PRD §3.4: "the new window must stand strictly clear by thirty days
        — either the new window opens more than thirty days after the
        existing window closes, or the existing window opens more than thirty
        days after the new window closes."
        PRD §3.4: "Opening stamps the window onto the cycle:
        `public_review_opens_at` takes the current logical clock and
        `public_review_closes_at` is set thirty days later."

        Design: Difficulty/resource_temporal_overlap/public_review_window_gap_rule
        """
        ctx_a = setup_cycle_in_scoring()
        transition_cycle(ctx_a["cycle"]["id"], "PUBLIC_REVIEW")
        cycle_b = _drive_second_cycle_to_scoring(ctx_a["framework"]["id"])

        # 2026-10-01 opens more than thirty days after the 08-31 close.
        set_clock("2026-10-01T00:00:00Z")
        updated = transition_cycle(cycle_b["id"], "PUBLIC_REVIEW")
        assert updated["status"] == "PUBLIC_REVIEW"
        assert updated["public_review_opens_at"].startswith("2026-10-01")
        assert updated["public_review_closes_at"].startswith("2026-10-31"), (
            "closes thirty days after the 2026-10-01 open")


class TestPublicReviewCloseBoundary:
    def test_public_review_close_boundary(self, api):
        """PRD §3.4: "Closing requires the logical clock to have reached
        `public_review_closes_at`; the boundary is inclusive, so closing at
        exactly the close instant passes, while an earlier attempt fails with
        `ERR_PUBLIC_REVIEW_NOT_CLOSED`."

        Design: Corner/validations/public_review_close_boundary
        """
        # Review window [2026-08-01, 2026-08-31] opened at the default clock.
        ctx = setup_cycle_in_scoring()
        transition_cycle(ctx["cycle"]["id"], "PUBLIC_REVIEW")

        set_clock("2026-08-30T00:00:00Z")  # one day before closes_at
        validate_error(
            api.transition_cycle(ctx["cycle"]["id"],
                                 {"to_state": "BOARD_PENDING"}, SECRETARY),
            ApiErrorId.ERR_PUBLIC_REVIEW_NOT_CLOSED)

        set_clock("2026-08-31T00:00:00Z")  # exactly closes_at: inclusive pass
        updated = transition_cycle(ctx["cycle"]["id"], "BOARD_PENDING")
        assert updated["status"] == "BOARD_PENDING"


class TestBoardDecisionGates:
    def test_composite_exact_threshold_passes(self, api):
        """PRD §3.4: "The composite gate runs first: the material's
        `official_composite` must be at least 3.20, with exactly 3.20 passing
        and a null composite failing outright, or the decision is rejected
        with `ERR_COMPOSITE_BELOW_THRESHOLD`."

        Design: Corner/calculations/composite_exact_threshold_passes
        """
        # Composites 4.0, 2.2, 3.4 -> official mean 9.6/3 == 3.20 exactly.
        ctx = setup_cycle_board_pending(
            reviews=[(4, 4, 4, 4), (2, 2, 3, 2), (4, 3, 3, 3)],
            teacher_count=3)
        material = get_material(ctx["material"]["id"])
        assert material["official_composite"] == pytest.approx(3.20, abs=0.01)

        resp = api.board_decision(
            ctx["cycle"]["id"],
            {"material_id": ctx["material"]["id"], "decision": "ADOPT"},
            SECRETARY)
        assert resp.status_code == 200
        assert get_material(ctx["material"]["id"])["adoption_status"] == "ADOPTED"

    def test_board_adopt_low_composite_rejected(self, api):
        """PRD §3.4: "The composite gate runs first: the material's
        `official_composite` must be at least 3.20, with exactly 3.20 passing
        and a null composite failing outright, or the decision is rejected
        with `ERR_COMPOSITE_BELOW_THRESHOLD`."

        Design: Corner/validations/board_adopt_low_composite_rejected
        """
        ctx = setup_cycle_board_pending(reviews=[(2, 2, 2, 2)], teacher_count=1)
        assert get_material(ctx["material"]["id"])["official_composite"] == \
            pytest.approx(2.00, abs=0.01)
        validate_error(
            api.board_decision(
                ctx["cycle"]["id"],
                {"material_id": ctx["material"]["id"], "decision": "ADOPT"},
                SECRETARY),
            ApiErrorId.ERR_COMPOSITE_BELOW_THRESHOLD)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "BOARD_PENDING"

    def test_participation_below_floor_rejected_after_composite_passes(
            self, api):
        """PRD §3.4: "The participation gate runs only after the composite
        gate has passed: the material's `participation_rate` must be at least
        0.60, with exactly 0.60 passing, or the decision is rejected with
        `ERR_PARTICIPATION_BELOW_FLOOR`."

        Design: Difficulty/boundary_precision_check/participation_floor_inclusive_at_board
        """
        # M1: official 3.67, participation 3/5 == 0.60. M2: official 4.00,
        # participation 2/5 == 0.40 (composite passes first, floor fails).
        ctx = setup_two_candidate_cycle(
            m1_reviews=[(4, 4, 4, 4), (3, 4, 3, 3), (4, 3, 4, 4)],
            m2_reviews=[(4, 4, 4, 4), (4, 4, 4, 4)],
            teacher_count=5)
        m2 = get_material(ctx["m2"]["id"])
        assert m2["official_composite"] == pytest.approx(4.00, abs=0.01)
        assert m2["participation_rate"] == pytest.approx(0.40, abs=0.0001)

        validate_error(
            api.board_decision(ctx["cycle"]["id"],
                               {"material_id": ctx["m2"]["id"],
                                "decision": "ADOPT"}, SECRETARY),
            ApiErrorId.ERR_PARTICIPATION_BELOW_FLOOR)

    def test_participation_exactly_floor_passes_and_cascades(self, api):
        """PRD §3.4: "the material's `participation_rate` must be at least
        0.60, with exactly 0.60 passing"
        PRD §3.4: "A successful adoption moves the chosen material to
        `ADOPTED`, stamps its `adopted_at` from the logical clock, records it
        on the cycle as `adopted_material_id`, moves every other
        `PILOT_CANDIDATE` material of the cycle to `REJECTED`, and advances
        the cycle to `ADOPTED`."

        Design: Difficulty/boundary_precision_check/participation_floor_inclusive_at_board
        """
        ctx = setup_two_candidate_cycle(
            m1_reviews=[(4, 4, 4, 4), (3, 4, 3, 3), (4, 3, 4, 4)],
            m2_reviews=[(4, 4, 4, 4), (4, 4, 4, 4)],
            teacher_count=5)
        m1 = get_material(ctx["m1"]["id"])
        assert m1["official_composite"] == pytest.approx(3.67, abs=0.01)
        assert m1["participation_rate"] == pytest.approx(0.60, abs=0.0001)

        resp = api.board_decision(ctx["cycle"]["id"],
                                  {"material_id": ctx["m1"]["id"],
                                   "decision": "ADOPT"}, SECRETARY)
        assert resp.status_code == 200
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "ADOPTED"
        assert cycle["adopted_material_id"] == ctx["m1"]["id"]
        assert get_material(ctx["m1"]["id"])["adoption_status"] == "ADOPTED"
        # Board cascade: the other pilot candidate is rejected.
        assert get_material(ctx["m2"]["id"])["adoption_status"] == "REJECTED"


class TestNotAdoptedTerminal:
    def test_not_adopted_terminal_lockdown(self, api):
        """PRD §3.4: "A rejection decision is the slate-killer: every
        `PILOT_CANDIDATE` material of the cycle moves to `REJECTED`, and the
        cycle moves to `NOT_ADOPTED`, a terminal status."
        PRD §3.1: "Any transition requested while the cycle is not in the
        required from-state is rejected with `ERR_INVALID_STATE`."
        PRD §3.5: "A quote may be submitted into a cycle whose status is
        `PILOT_OPEN`, `SCORING`, `PUBLIC_REVIEW`, `BOARD_PENDING`, `ADOPTED`,
        or `PROCURING`"

        Design: Corner/state_machines/not_adopted_terminal_lockdown
        """
        ctx = setup_cycle_board_pending(reviews=[(2, 2, 2, 2)], teacher_count=1)
        resp = api.board_decision(
            ctx["cycle"]["id"],
            {"material_id": ctx["material"]["id"], "decision": "REJECT"},
            SECRETARY)
        assert resp.status_code == 200
        assert get_cycle(ctx["cycle"]["id"])["status"] == "NOT_ADOPTED"
        assert get_material(ctx["material"]["id"])["adoption_status"] == \
            "REJECTED"

        # Every further transition is rejected from the terminal state.
        validate_error(api.transition_cycle(ctx["cycle"]["id"],
                                            {"to_state": "PUBLIC_REVIEW"},
                                            SECRETARY),
                       ApiErrorId.ERR_INVALID_STATE)

        # NOT_ADOPTED is outside the quote-submission cycle-status set.
        validate_error(
            api.create_quote(ctx["cycle"]["id"], {
                "material_id": ctx["material"]["id"], "publisher_name": "PubA",
                "print_unit_price": 10.00, "print_quantity": 5,
                "digital_seat_rate": 0, "digital_seat_count": 0,
                "training_sessions": 0, "license_years": 0}, PROCUREMENT),
            ApiErrorId.ERR_INVALID_STATE)
