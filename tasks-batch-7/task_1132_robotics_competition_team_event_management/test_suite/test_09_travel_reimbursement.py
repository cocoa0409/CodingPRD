"""Travel reimbursement: marginal tiered formula, mode caps, qualification
gate (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_event,
    create_team_payload,
    create_travel_booking_payload,
    make_team_lead_headers,
    open_registration,
    add_milestone,
    setup_qualified_team,
    validate_error,
    validate_success,
    api_client,
)

RO = TEST_USERS["registration_officer_headers"]
TO = TEST_USERS["travel_officer_headers"]


def _book_and_approve(ctx, team_entry, mode, cost_cents):
    event_id = ctx["event"]["id"]
    team_id = team_entry["team"]["id"]
    lead = make_team_lead_headers(team_entry["mentor"]["id"])
    booking = validate_success(
        api_client.create_travel_booking(
            event_id, team_id,
            create_travel_booking_payload(mode=mode, cost_cents=cost_cents),
            lead,
        ),
        expected_status=201,
    )
    return api_client.approve_travel_booking(event_id, team_id, booking["id"], TO)


class TestMarginalVsAverage:
    def test_air_400000_reimburses_260000_marginal(self):
        """PRD §3.8: "the first 200000 cents of the eligible amount are
        reimbursed at 80 percent; any remainder above 200000 cents is
        reimbursed at 50 percent." For AIR (cap 1500000) at 400000 cents:
        200000 × 0.80 + 200000 × 0.50 = 260000. "The forbidden average-rate
        misreading — apply 50 percent to the entire eligible amount — would
        yield 125000 cents on the same booking and is not the specified
        behaviour."

        Design: Difficulty/dual_variant_calc/travel_reimbursement_marginal_vs_average
        """
        ctx, target, _ = setup_qualified_team()
        resp = _book_and_approve(ctx, target, "AIR", 400000)
        approved = validate_success(resp)
        assert approved["reimbursement_status"] == "APPROVED"
        assert approved["reimbursed_cents"] == 260000

    def test_prd_example_250000_reimburses_185000(self):
        """PRD §3.8: "a booking of 250000 cents eligible yields 200000 × 0.80
        = 160000 cents from tier 1 plus 50000 × 0.50 = 25000 cents from tier
        2, totalling 185000 cents."

        Design: Difficulty/dual_variant_calc/travel_reimbursement_marginal_vs_average
        """
        ctx, target, _ = setup_qualified_team()
        resp = _book_and_approve(ctx, target, "AIR", 250000)
        approved = validate_success(resp)
        assert approved["reimbursed_cents"] == 185000


class TestTierBoundariesAndCaps:
    def test_exactly_tier1_limit_all_at_80_percent(self):
        """PRD §3.8: "the first 200000 cents of the eligible amount are
        reimbursed at 80 percent; any remainder above 200000 cents is
        reimbursed at 50 percent" — at exactly 200000 there is no tier-2
        remainder (min/max boundary), so BUS (cap 400000) yields 160000.

        Design: Difficulty/combinatorial_formula/travel_reimbursement_mode_a_tiered_with_caps
        """
        ctx, target, _ = setup_qualified_team()
        resp = _book_and_approve(ctx, target, "BUS", 200000)
        approved = validate_success(resp)
        assert approved["reimbursed_cents"] == 160000

    def test_cost_above_mode_cap_rejected_at_validation(self):
        """PRD §3.8: "The cap is 1500000 cents for `AIR`, 800000 cents for
        `RAIL`, 400000 cents for `BUS`, and 300000 cents for `SELF_DRIVE`...
        a booking whose `cost_cents` exceeds the mode's cap is rejected at
        validation time with `ERR_REIMBURSEMENT_CAP_EXCEEDED` (HTTP 422), so
        the cap check fires before the formula runs."

        Design: Difficulty/combinatorial_formula/travel_reimbursement_mode_a_tiered_with_caps
        """
        ctx, target, _ = setup_qualified_team()
        resp = _book_and_approve(ctx, target, "SELF_DRIVE", 300001)
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_CAP_EXCEEDED)


class TestQualificationGate:
    def test_unqualified_team_booking_rejected(self):
        """PRD §3.8: "Approval is by a `TravelOfficer` and is gated on two
        things: the team's `qualified_for_championship` must be true (else
        `ERR_NOT_QUALIFIED`, HTTP 409), and the computed reimbursement must be
        strictly greater than zero."

        Design: Difficulty/cross_entity_state_dependency/travel_approve_depends_on_team_qualified
        """
        event = create_event()
        add_milestone(event["id"], "KICKOFF", "2026-01-10T17:00:00Z")
        open_registration(event["id"])
        team = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=9501), RO),
            expected_status=201,
        )
        mentor = validate_success(
            api_client.create_person(
                event["id"],
                {"team_id": team["id"], "full_name": "Lead", "email": "lead9501@example.com",
                 "role_kind": "MENTOR"},
                RO,
            ),
            expected_status=201,
        )
        lead = make_team_lead_headers(mentor["id"])
        booking = validate_success(
            api_client.create_travel_booking(
                event["id"], team["id"],
                create_travel_booking_payload(mode="BUS", cost_cents=100000),
                lead,
            ),
            expected_status=201,
        )
        resp = api_client.approve_travel_booking(event["id"], team["id"], booking["id"], TO)
        validate_error(resp, ApiErrorId.ERR_NOT_QUALIFIED)

    def test_qualified_team_booking_approved(self):
        """PRD §3.8: "Once a team is qualified, it can book travel against the
        championship." and approval "moves the booking `PENDING → APPROVED`
        and writes `reimbursed_cents` from the `travel_reimbursement`
        calculation."

        Design: Difficulty/cross_entity_state_dependency/travel_approve_depends_on_team_qualified
        """
        ctx, target, _ = setup_qualified_team()
        team_id = target["team"]["id"]
        team = validate_success(api_client.get_team(ctx["event"]["id"], team_id, TO))
        assert team["qualified_for_championship"] is True
        resp = _book_and_approve(ctx, target, "RAIL", 100000)
        approved = validate_success(resp)
        assert approved["reimbursement_status"] == "APPROVED"
        assert approved["reimbursed_cents"] == 80000  # 100000 × 0.80
