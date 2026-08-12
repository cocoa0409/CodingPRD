"""Corner coverage: notice lead-time boundaries (budget 14d, assessment 30d),
subsidy gating order, holder eligibility, builder standing gates, reinstate,
closeout/terminate preconditions, budget-empty, seat-vacancy, future-dating,
fiscal-year mismatch, and record-purchase lot state."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_adopted_budget,
    create_and_close_lot,
    create_and_schedule_notice,
    create_draft_agreement,
    create_offered_lot,
    create_open_phase,
    create_phase,
    create_lot,
    create_builder,
    create_proposed_budget,
    create_resident,
    create_residents,
    create_violation_notice_sent,
    list_community_seats,
    set_clock,
    setup_active_agreement_scenario,
    setup_missed_tranche_scenario,
    get_success_data,
    validate_error,
    make_builder_rep_headers,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.factories import (
    create_budget_payload,
    create_notice_payload,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestBudgetNoticeLeadBoundary:
    def test_thirteen_days_fails_fourteen_passes(self):
        """PRD §3.5: "Adoption is where governance posture bites, and two statutory notice gates apply first: a resident notice of type `BUDGET_ADOPTION` referencing this budget via `budget_id` must exist in `SENT` status (otherwise `ERR_NOTICE_NOT_SENT`; a superseded notice does not count even if it was sent), and that notice's `sent_at` must be at least fourteen days before the adoption moment (otherwise `ERR_NOTICE_LEAD_TIME`)."

        Design: Corner/validations/budget_notice_lead_boundary
        """
        community = create_active_community("Leadtime Lake", 10)
        budget = create_proposed_budget(community["id"], 2027, [("MANAGEMENT", 100000)])
        create_and_schedule_notice(
            community["id"], "BUDGET_ADOPTION", "2026-05-02T00:00:00Z",
            budget_id=budget["id"], subject="b", body="adopt",
        )
        set_clock("2026-05-02T00:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        resp13 = api_client.adopt_budget(budget["id"], DIRECTOR)
        validate_error(resp13, ApiErrorId.ERR_NOTICE_LEAD_TIME)

        set_clock("2026-05-16T00:00:00Z")
        adopted = get_success_data(api_client.adopt_budget(budget["id"], DIRECTOR))
        assert adopted["status"] == "ADOPTED", (
            f"exactly 14 days after SENT passes (inclusive lead), got {adopted['status']}"
        )


class TestAssessmentNoticeLeadFailure:
    def test_notice_sent_one_day_past_deadline_blocks_arm(self):
        """PRD §3.5: "A resident notice of type `ASSESSMENT_CHANGE` referencing the rate via `assessment_rate_id` must exist in `SENT` status (`ERR_NOTICE_NOT_SENT`), and its `sent_at` must be no later than thirty days before midnight UTC on January 1 of the rate's fiscal year (`ERR_NOTICE_LEAD_TIME`)."

        Design: Corner/validations/assessment_notice_lead_failure
        """
        community = create_active_community("Rate Ridge", 10)
        budget = create_adopted_budget(community["id"], 2027, [("MANAGEMENT", 100000)])
        rate = get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2027},
                CTRL,
            )
        )
        # FY2027 starts 2027-01-01; the 30-day lead deadline is 2026-12-02.
        create_and_schedule_notice(
            community["id"], "ASSESSMENT_CHANGE", "2026-12-03T00:00:00Z",
            assessment_rate_id=rate["id"], subject="late", body="rate",
            effective_date="2027-01-01T00:00:00Z",
        )
        set_clock("2026-12-03T00:00:00Z")
        resp = api_client.arm_rate(rate["id"], CTRL)
        validate_error(resp, ApiErrorId.ERR_NOTICE_LEAD_TIME)
        read = get_success_data(api_client.get_assessment_rate(rate["id"], CTRL))
        assert read["status"] == "CALCULATED"


class TestHolderNotEligible:
    def test_prospect_holder_rejected_despite_votes(self):
        """PRD §3.9: "Certifying the result requires the payload's `votes_cast`, `votes_for`, and `holder_resident_id` to pass three tests: quorum — `votes_cast` at least the ceiling of one fifth of `eligible_voter_count` (twenty percent, with the boundary inclusive; `ERR_QUORUM_NOT_MET` below it); strict majority — `votes_for` strictly more than half of `votes_cast`, so an exact tie fails (`ERR_ELECTION_MAJORITY_NOT_REACHED`); and holder eligibility — the holder must be an `OWNER` resident of the community not already holding a `FILLED` or `ELECTION_CALLED` seat (`ERR_HOLDER_NOT_ELIGIBLE`)."

        Design: Corner/validations/holder_not_eligible
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=4, planned_lot_count=4, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)], community_name="Eligibility Estates",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "E1")
        lot2 = create_offered_lot(scenario["phase"]["id"], "E2")
        r1, r2, r3 = create_residents(
            scenario["community"]["id"],
            [("E One", "e1@x.com"), ("E Two", "e2@x.com"), ("E Prospect", "e3@x.com")],
        )
        set_clock("2026-06-01T00:00:00Z")
        close_lots_with_owners(
            scenario["agreement"]["id"], [lot1["id"], lot2["id"]], [r1["id"], r2["id"]]
        )
        seats = list_community_seats(scenario["community"]["id"])
        seat5 = seats[4]
        assert seat5["status"] == "VACANT", (
            f"2/4 closings -> PARITY converts seat 5, got {seat5['status']}"
        )
        called = get_success_data(api_client.call_election(seat5["id"], DIRECTOR))
        assert called["eligible_voter_count"] == 2

        resp = api_client.certify_election(
            seat5["id"],
            {"votes_cast": 1, "votes_for": 1, "holder_resident_id": r3["id"]},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_HOLDER_NOT_ELIGIBLE)
        seat_read = get_success_data(api_client.get_board_seat(seat5["id"], DIRECTOR))
        assert seat_read["status"] == "ELECTION_CALLED"


class TestBuilderStandingGatesExecute:
    def test_probation_builder_cannot_execute_new_agreement(self):
        """PRD §3.3: "Execution moves the agreement from `DRAFT` to `EXECUTED` under a `DeclarantExecutive` and enforces four gates: the community must be `ACTIVE` (`ERR_COMMUNITY_NOT_ACTIVE`), the builder must be in `GOOD_STANDING` (`ERR_BUILDER_NOT_IN_GOOD_STANDING`), the phase must be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`), and the tranche schedule must exactly cover the commitment — the sum of `lot_count_due` across the agreement's tranches must equal `total_lots_committed` (`ERR_TRANCHE_COVERAGE_MISMATCH`).".
        PRD §3.3: "Standing is enforced automatically: the moment any tranche of any of the builder's agreements becomes `MISSED`, the builder drops to `PROBATION`; the moment any of its agreements becomes `DEFAULTED`, it drops to `SUSPENDED`.".

        Design: Corner/validations/builder_standing_gates_execute
        """
        scenario = setup_missed_tranche_scenario(
            total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)],
            community_name="Standing Springs",
            earnest_money_cents=1000000,
        )
        # Second agreement drafted with a valid tranche while the builder is
        # PROBATION (first tranche MISSED at clock 2026-07-01).
        a2, _ = create_draft_agreement(
            scenario["community"]["id"], scenario["builder"]["id"], scenario["phase"]["id"], 1,
            [("2026-12-31T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        resp = api_client.execute_agreement(a2["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_BUILDER_NOT_IN_GOOD_STANDING)
        read = get_success_data(api_client.get_agreement(a2["id"], CTRL))
        assert read["status"] == "DRAFT"


class TestReinstateBlockedUntilDefaultsCleared:
    def test_reinstate_blocked_while_missed_then_succeeds_after_cure(self):
        """PRD §3.3: "A `DeclarantExecutive` may reinstate a builder to `GOOD_STANDING` only when no tranche of any of its agreements remains `MISSED` or `DEFAULTED` — and, when reinstating from `SUSPENDED`, additionally when no agreement of the builder is `DEFAULTED`; outstanding compliance defaults are rejected with `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`."

        Design: Corner/validations/reinstate_blocked_until_defaults_cleared
        """
        scenario = setup_missed_tranche_scenario(
            total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)],
            community_name="Reinstate Ridge",
            earnest_money_cents=1000000,
        )
        builder = scenario["builder"]
        tranche = scenario["tranches"][0]

        resp = api_client.reinstate_builder(builder["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_COMPLIANCE_DEFAULTS)

        set_clock("2026-07-10T00:00:00Z")
        get_success_data(
            api_client.cure_tranche(
                tranche["id"], {"payment_cents": 10000},
                make_builder_rep_headers(builder["id"]),
            )
        )
        reinstated = get_success_data(api_client.reinstate_builder(builder["id"], EXEC))
        assert reinstated["standing"] == "GOOD_STANDING"


class TestPhaseCloseoutBlocked:
    def test_closeout_blocked_by_nonterminal_lot_and_agreement(self):
        """PRD §3.2: "Closing out a `DELIVERING` phase requires that every lot in the phase be in `CLOSED` or `WITHDRAWN` and that every agreement drawing on the phase be in `COMPLETED`, `DEFAULTED`, or `TERMINATED`; either shortfall is rejected with `ERR_CLOSEOUT_BLOCKED`."

        Design: Corner/validations/phase_closeout_blocked
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)], community_name="Closeout Cove",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "C1")
        create_offered_lot(scenario["phase"]["id"], "C2")
        set_clock("2026-06-01T00:00:00Z")
        closed = create_and_close_lot(scenario["agreement"]["id"], lot1["id"])
        assert closed["status"] == "CLOSED"

        resp = api_client.close_out_phase(scenario["phase"]["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_CLOSEOUT_BLOCKED)


class TestTerminateBlockedByPendingClosing:
    def test_pending_escrow_blocks_termination(self):
        """PRD §3.3: "The same terminal housekeeping applies when a `DeclarantExecutive` terminates an agreement voluntarily: termination is available from `DRAFT`, `EXECUTED`, or `ACTIVE` only while no closing of the agreement is `PENDING` (`ERR_CLOSINGS_PENDING`), and it cancels the agreement's `SCHEDULED` and `OPEN` tranches."

        Design: Corner/validations/terminate_blocked_by_pending_closing
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)], community_name="Pending Pines",
            earnest_money_cents=1000000,
        )
        lot = create_offered_lot(scenario["phase"]["id"], "P1")
        closing = get_success_data(
            api_client.create_closing(
                {"agreement_id": scenario["agreement"]["id"], "lot_id": lot["id"]}, CTRL
            )
        )

        resp = api_client.terminate_agreement(scenario["agreement"]["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_CLOSINGS_PENDING)

        get_success_data(api_client.cancel_closing(closing["id"], CTRL))
        terminated = get_success_data(
            api_client.terminate_agreement(scenario["agreement"]["id"], EXEC)
        )
        assert terminated["status"] == "TERMINATED"
        tranche = get_success_data(api_client.get_tranche(scenario["tranches"][0]["id"], CTRL))
        assert tranche["status"] == "CANCELLED"


class TestBudgetEmptyAndRateOnUnadopted:
    def test_propose_requires_line_and_rate_requires_adopted(self):
        """PRD §3.5: "Proposal moves the budget from `DRAFT` to `PROPOSED` and requires at least one line item (`ERR_BUDGET_EMPTY`)."
        PRD §3.5: "The rate's `fiscal_year` must equal its budget's (`ERR_FISCAL_YEAR_MISMATCH`), the referenced budget must be `ADOPTED` (`ERR_BUDGET_NOT_ADOPTED`), and only one non-`SUPERSEDED` rate may exist per community and fiscal year (`ERR_DUPLICATE_ASSESSMENT_YEAR`).".

        Design: Corner/validations/budget_empty_and_rate_on_unadopted
        """
        community = create_active_community("Empty Estates", 10)
        bud1 = get_success_data(
            api_client.create_budget(
                create_budget_payload(community_id=community["id"], fiscal_year=2027), CTRL
            )
        )
        bud2 = create_proposed_budget(community["id"], 2028, [("MANAGEMENT", 100000)])

        resp_empty = api_client.propose_budget(bud1["id"], CTRL)
        validate_error(resp_empty, ApiErrorId.ERR_BUDGET_EMPTY)

        resp_adopt = api_client.create_assessment_rate(
            {"community_id": community["id"], "budget_id": bud2["id"], "fiscal_year": 2028},
            CTRL,
        )
        validate_error(resp_adopt, ApiErrorId.ERR_BUDGET_NOT_ADOPTED)


class TestSeatNotVacant:
    def test_call_election_on_filled_declarant_seat_rejected(self):
        """PRD §3.9: "Calling an election on a `VACANT` `OWNER_ELECTED` seat (`ERR_SEAT_NOT_VACANT` otherwise) — or re-calling one on a `LAPSED` seat — snapshots `eligible_voter_count` as the number of the community's residents in `OWNER` status at that moment and sets the `election_deadline` thirty days out.".
        PRD §3.1: "On activation the system creates five `BoardSeat` rows numbered `seat_no` 1 through 5, each `DECLARANT_APPOINTED` and `FILLED`, with `holder_name` taken from the supplied names.".

        Design: Corner/validations/seat_not_vacant
        """
        community = create_active_community("Seat Springs", 10)
        seats = list_community_seats(community["id"])
        assert len(seats) == 5
        seat1 = seats[0]
        assert seat1["seat_class"] == "DECLARANT_APPOINTED"
        assert seat1["status"] == "FILLED"

        resp = api_client.call_election(seat1["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SEAT_NOT_VACANT)


class TestSendAtInPastLegs:
    def test_send_at_and_hearing_date_must_be_strictly_future(self):
        """PRD §3.9: "Typed links bind the notice to its subject matter: a `BUDGET_ADOPTION` notice must carry a `budget_id`, and an `ASSESSMENT_CHANGE` notice must carry an `assessment_rate_id`; scheduling enforces those requirements (`ERR_VALIDATION`) and requires `send_at` to be strictly after the logical clock (`ERR_SEND_AT_IN_PAST`)."
        PRD §3.7: "Escalation past the deadline (`ERR_CURE_WINDOW_OPEN` while the cure window is still open) moves the violation to `ESCALATED`, after which an `AssociationDirector` schedules a hearing — `hearing_date` must be strictly after the logical clock (`ERR_SEND_AT_IN_PAST`) — moving it to `HEARING_SCHEDULED`.".

        Design: Corner/validations/send_at_in_past_legs
        """
        community = create_active_community("Past Prairie", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "L1")
        resident = create_resident(community["id"], "Pat Past", "pat@x.com")
        violation = create_violation_notice_sent(
            community["id"], lot["id"],
            respondent_resident_id=resident["id"], violation_type="SETBACK",
        )
        notice = get_success_data(
            api_client.create_notice(
                create_notice_payload(
                    community_id=community["id"], notice_type="GENERAL_MEETING",
                    subject="now", body="x", send_at="2026-05-01T00:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        set_clock("2026-05-16T00:00:00Z")
        get_success_data(api_client.escalate_violation(violation["id"], REVIEWER))

        # send_at 2026-05-01 == the notice's creation clock and is in the past
        # at the current clock: rejected either way.
        resp_notice = api_client.schedule_notice(notice["id"], LIFESTYLE)
        validate_error(resp_notice, ApiErrorId.ERR_SEND_AT_IN_PAST)

        resp_hearing = api_client.schedule_hearing(
            violation["id"], {"hearing_date": "2026-05-16T00:00:00Z"}, DIRECTOR
        )
        validate_error(resp_hearing, ApiErrorId.ERR_SEND_AT_IN_PAST)


class TestSubsidyGatingErrors:
    def test_stage_checked_before_prior_rate_existence(self):
        """PRD §3.5: "Under the declarant-subsidy variant, the election is validated in a fixed order: first, `transition_stage` must be `DECLARANT_CONTROL` (otherwise `ERR_SUBSIDY_NOT_AVAILABLE`), and second, an `EFFECTIVE` rate must exist for the prior fiscal year (otherwise `ERR_NO_PRIOR_RATE`)."

        Design: Corner/validations/subsidy_gating_errors
        """
        # Community A: DECLARANT_CONTROL, no EFFECTIVE prior-year rate.
        ca = create_active_community("No Prior", 10)
        buda = create_adopted_budget(ca["id"], 2027, [("MANAGEMENT", 100000)])

        # Community B: 4 units, one closing -> 25.00 pct -> OWNER_REPRESENTATION.
        cb = create_active_community("Stage Gate", 4)
        phase_b = create_open_phase(cb["id"], "P1", 1, 4)
        builder_b = create_builder(cb["id"], "SG Builders", "A")
        agreement_b, _ = create_active_agreement(
            cb["id"], builder_b["id"], phase_b["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        lot_b = create_offered_lot(phase_b["id"], "S1")
        set_clock("2026-06-01T00:00:00Z")
        create_and_close_lot(agreement_b["id"], lot_b["id"])
        budb = create_adopted_budget(
            cb["id"], 2027, [("MANAGEMENT", 100000)],
            notice_send_at="2026-06-02T00:00:00Z", adopt_at="2026-06-17T00:00:00Z",
        )

        resp_a = api_client.create_assessment_rate(
            {"community_id": ca["id"], "budget_id": buda["id"], "fiscal_year": 2027,
             "subsidy_elected": True},
            CTRL,
        )
        validate_error(resp_a, ApiErrorId.ERR_NO_PRIOR_RATE)

        resp_b = api_client.create_assessment_rate(
            {"community_id": cb["id"], "budget_id": budb["id"], "fiscal_year": 2027,
             "subsidy_elected": True},
            CTRL,
        )
        validate_error(resp_b, ApiErrorId.ERR_SUBSIDY_NOT_AVAILABLE)


class TestRecordPurchaseRequiresUnderContractLot:
    def test_offered_lot_rejected(self):
        """PRD §3.8: "Recording a purchase links the prospect to their homesite `lot_id`: the lot must belong to the same community as the resident (`ERR_RESIDENT_COMMUNITY_MISMATCH`) and must be `UNDER_CONTRACT` or `CLOSED` (`ERR_LOT_NOT_UNDER_CONTRACT`); the resident becomes a `PURCHASER`."

        Design: Corner/validations/record_purchase_requires_under_contract_lot
        """
        community = create_active_community("Purchase Point", 10)
        phase = create_open_phase(community["id"], "P1", 1, 5)
        lot = create_offered_lot(phase["id"], "P1")
        resident = create_resident(community["id"], "Peter Prospect", "peter@x.com")

        resp = api_client.record_purchase(resident["id"], {"lot_id": lot["id"]}, LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_UNDER_CONTRACT)
        read = get_success_data(api_client.get_resident(resident["id"], LIFESTYLE))
        assert read["status"] == "PROSPECT"


class TestFiscalYearMismatchRejected:
    def test_rate_year_must_equal_budget_year(self):
        """PRD §3.5: "The rate's `fiscal_year` must equal its budget's (`ERR_FISCAL_YEAR_MISMATCH`), the referenced budget must be `ADOPTED` (`ERR_BUDGET_NOT_ADOPTED`), and only one non-`SUPERSEDED` rate may exist per community and fiscal year (`ERR_DUPLICATE_ASSESSMENT_YEAR`).".

        Design: Corner/validations/fiscal_year_mismatch_rejected
        """
        community = create_active_community("Mismatch Meadows", 10)
        budget = create_adopted_budget(community["id"], 2027, [("MANAGEMENT", 100000)])
        resp = api_client.create_assessment_rate(
            {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2028},
            CTRL,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_MISMATCH)
