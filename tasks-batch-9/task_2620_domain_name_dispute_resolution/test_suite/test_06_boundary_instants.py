"""Inclusive and exclusive endpoints tested to the cent and to the second."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    VERIFIED_REGISTRANT_EMAIL,
    admit_panelist,
    api_client,
    assert_conflict_factors_sorted,
    cast_seat_vote,
    case_payload,
    draft_decision,
    file_court_challenge,
    fund_case_to_assessment,
    court_challenge_payload,
    get_success_data,
    implement_decision,
    issue_decision,
    make_complainant_headers,
    make_registrar_headers,
    make_respondent_headers,
    nominate_seat,
    read_appointment,
    read_case,
    read_complainant,
    read_decision,
    read_domain,
    read_panelist,
    replace_seat,
    screen_seat,
    seat_panelist_cleanly,
    set_clock,
    setup_filed_case,
    setup_responded_case,
    validate_error,
    validate_paginated,
    waive_seat,
    waiver_payload,
    withdraw_case,
)

SIXTY_DOCKET = {
    "iana_id": "IANA-1707",
    "domain_name": "sixty.example",
    "legal_name": "Sixty SA",
    "country_code": "FR",
}
BARRED_DOCKET = {
    "iana_id": "IANA-1808",
    "domain_name": "barred.example",
    "legal_name": "Barred Oy",
    "country_code": "FR",
}
WAITING_DOCKET = {
    "iana_id": "IANA-1909",
    "domain_name": "waiting.example",
    "legal_name": "Waiting AS",
    "country_code": "FR",
}


class TestConflictThresholdIsInclusive:
    def _nominated_pair(self):
        bundle = setup_responded_case(**SIXTY_DOCKET)
        fund_case_to_assessment(bundle["case"]["id"])
        first = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z",
        )
        second = admit_panelist(
            full_name="Bram de Vries", nationality_code="NL",
            roster_admitted_at="2018-11-11T00:00:00Z",
        )
        seat = nominate_seat(bundle["case"]["id"], "SOLE", first["id"])
        return bundle, first, second, seat

    def test_a_score_of_exactly_sixty_disqualifies_and_cannot_be_waived(self):
        """PRD §3.6: "A score at or above the disqualification threshold of 60
        sends the seat straight to `CONFLICTED`, taking no load and requiring no
        further step — exactly 60.00 disqualifies."
        PRD §3.6: "`conflict_factors` records which disclosure keys contributed a
        non-zero term, drawn from `FINANCIAL_INTEREST`, `PRIOR_APPOINTMENTS`,
        `PRIOR_REPRESENTATION` and `SAME_FIRM`, sorted in ascending order, and is
        empty when the score is 0.00."

        Design: Difficulty/boundary_precision_check/conflict_score_of_exactly_sixty_disqualifies_while_fifty_six_point_six_seven_is_waivable
        """
        bundle, first, _second, seat = self._nominated_pair()
        screened = screen_seat(
            seat["id"], first["id"],
            disclosed_prior_representation=True,
            disclosed_same_firm=True,
            months_since_last_contact=6,
        )
        # (45 + 35) * (1 - 6/24) is 60.00 exactly, and the comparison is at-or-above.
        assert float(screened["conflict_score"]) == 60.00
        assert screened["status"] == "CONFLICTED"
        assert screened["conflict_factors"] == ["PRIOR_REPRESENTATION", "SAME_FIRM"]
        assert_conflict_factors_sorted(screened)
        assert read_panelist(first["id"])["active_case_load"] == 0

        refused = api_client.record_waiver(seat["id"], waiver_payload(), CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_CONFLICT_NOT_WAIVABLE.value, 409)
        assert read_appointment(seat["id"])["status"] == "CONFLICTED"
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_APPOINTMENT"

    def test_one_more_month_of_decay_lands_on_a_waivable_fifty_six_point_six_seven(self):
        """PRD §3.6: "The financial interest is deliberately carved out before
        decay: its 60 points are added back at full value after the decayable
        subtotal has been decayed and rounded half up to two decimals, so a
        financial interest never ages away."
        PRD §3.6: "Both consents are stored on the seat, the engagement-window and
        capacity checks are re-run exactly as they are on direct acceptance, and
        the seat moves from `WAIVER_PENDING` to `ACCEPTED` with `accepted_at`,
        `decision_due_at` and the load increment."

        Design: Difficulty/boundary_precision_check/conflict_score_of_exactly_sixty_disqualifies_while_fifty_six_point_six_seven_is_waivable
        """
        bundle, first, second, seat = self._nominated_pair()
        screen_seat(
            seat["id"], first["id"], disclosed_prior_representation=True,
            disclosed_same_firm=True, months_since_last_contact=6,
        )
        predecessor = replace_seat(
            seat["id"], replacement_panelist_id=second["id"],
            reason="Disqualifying conflict on the first nominee.",
        )
        assert predecessor["status"] == "REPLACED"
        assert float(predecessor["conflict_score"]) == 60.00
        successor_id = predecessor["replaced_by_appointment_id"]

        screened = screen_seat(
            successor_id, second["id"], disclosed_prior_representation=True,
            disclosed_same_firm=True, months_since_last_contact=7,
        )
        # (45 + 35) * (1 - 7/24) is 56.666..., rounded half up to two decimals.
        assert float(screened["conflict_score"]) == 56.67
        assert screened["status"] == "WAIVER_PENDING"
        assert read_panelist(second["id"])["active_case_load"] == 0

        waived = waive_seat(successor_id)
        assert waived["status"] == "ACCEPTED"
        assert waived["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert waived["decision_due_at"] == "2026-08-15T00:00:00.000Z"
        assert read_panelist(second["id"])["active_case_load"] == 1
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_CONSTITUTED"
        assert read_appointment(seat["id"])["replaced_by_appointment_id"] == successor_id


class TestRefilingBarUpperEndpoint:
    def _withdrawn_case(self):
        bundle = setup_filed_case(**BARRED_DOCKET)
        set_clock("2026-08-10T00:00:00Z")
        bundle["case"] = withdraw_case(
            bundle["case"]["id"], bundle["complainant"]["id"],
            reason="The parties settled privately.",
        )
        return bundle

    def test_a_filing_at_the_exact_bar_instant_is_still_barred(self):
        """PRD §3.2: "Both endpoints of that interval are inclusive, so a filing
        attempted at the exact instant of `refiling_bar_until` is still barred with
        `ERR_REFILING_BAR_ACTIVE` and the domain frees up one instant later."
        PRD §3.3: "The case moves to `WITHDRAWN`, its `closed_at` is stamped at the
        current logical-clock instant, and its `refiling_bar_until` is set 30 days
        later."

        Design: Difficulty/boundary_precision_check/refiling_bar_upper_endpoint_is_inclusive_to_the_second
        """
        bundle = self._withdrawn_case()
        withdrawn = bundle["case"]
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["closed_at"] == "2026-08-10T00:00:00.000Z"
        assert withdrawn["refiling_bar_until"] == "2026-09-09T00:00:00.000Z"
        assert read_case(withdrawn["id"])["paid_cents"] == 0
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 0

        set_clock("2026-09-09T00:00:00Z")
        refused = api_client.create_case(
            case_payload(bundle["complainant"]["id"], bundle["domain"]["id"]),
            make_complainant_headers(bundle["complainant"]["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_REFILING_BAR_ACTIVE.value, 409)
        _, meta = validate_paginated(
            api_client.list_cases(
                CASE_MANAGER,
                params={"domain_id": bundle["domain"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 0

    def test_the_same_filing_one_second_later_is_accepted(self):
        """PRD §3.2: "A closed case leaves behind a cooling-off interval on that
        same domain instead, running from its `closed_at` to its
        `refiling_bar_until`, where `refiling_bar_until` is `closed_at` plus 30
        days."
        PRD §3.2: "An accepted filing lands in `status` `FILED` with `version` 1,
        mints its `case_number`, and sets `respondent_panel_election` to `NONE`."
        PRD §3.2: "The `required_seat_count` a case carries is 3 whenever either
        the complainant's `panel_election` or the respondent's
        `respondent_panel_election` is `THREE`, and 1 otherwise; with the default
        `SINGLE` election it therefore stands at 1 at filing."
        PRD §3.2: "A standard single-member filing therefore assesses 150000 cents
        entirely to the complainant with a pool of 105000 cents, and an expedited
        single-member filing assesses 168750 cents entirely to the complainant with
        a pool of 118125 cents."

        Design: Difficulty/boundary_precision_check/refiling_bar_upper_endpoint_is_inclusive_to_the_second
        """
        bundle = self._withdrawn_case()
        set_clock("2026-09-09T00:00:01Z")
        refiled = get_success_data(
            api_client.create_case(
                case_payload(bundle["complainant"]["id"], bundle["domain"]["id"]),
                make_complainant_headers(bundle["complainant"]["id"]),
            ),
            201,
        )
        assert refiled["status"] == "FILED"
        assert refiled["version"] == 1
        assert refiled["required_seat_count"] == 1
        assert refiled["assessed_fee_cents"] == 150000
        assert refiled["created_at"] == "2026-09-09T00:00:01.000Z"
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 1
        _, meta = validate_paginated(
            api_client.list_cases(
                CASE_MANAGER,
                params={"domain_id": bundle["domain"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2


class TestImplementationDeadlineInstant:
    def _issued_transfer_decision(self):
        bundle = setup_responded_case(**WAITING_DOCKET)
        case_id = bundle["case"]["id"]
        fund_case_to_assessment(case_id)
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z",
        )
        set_clock("2026-09-01T10:00:00Z")
        appointment = seat_panelist_cleanly(case_id, "SOLE", panelist)
        assert appointment["decision_due_at"] == "2026-09-15T10:00:00.000Z"
        decision = draft_decision(case_id, panelist["id"], draft_summary="Transfer is ordered.")
        cast_seat_vote(
            decision["id"], panelist["id"], "SOLE", "TRANSFER",
            rationale="All three elements are established.",
        )
        bundle["panelists"] = [panelist]
        bundle["appointments"] = [appointment]
        bundle["decision"] = issue_decision(decision["id"])
        bundle["case"] = read_case(case_id)
        return bundle

    def test_at_the_deadline_instant_the_challenge_is_admitted_and_execution_is_not(self):
        """PRD §3.8: "While the clock is at or before `implementation_deadline_at` a
        court challenge may be filed and the registrar may not act — an attempt to
        execute is refused with `ERR_IMPLEMENTATION_PERIOD_ACTIVE`."
        PRD §3.8: "At the exact deadline instant, therefore, the challenge is
        admitted and the execution is not."

        Design: Difficulty/boundary_precision_check/implementation_deadline_instant_is_still_inside_the_waiting_period
        """
        bundle = self._issued_transfer_decision()
        decision = bundle["decision"]
        assert decision["issued_at"] == "2026-09-01T10:00:00.000Z"
        assert decision["implementation_deadline_at"] == "2026-09-16T10:00:00.000Z"
        assert bundle["case"]["status"] == "IMPLEMENTATION_WAITING"

        set_clock("2026-09-16T10:00:00Z")
        refused = api_client.implement_decision(
            decision["id"], {"registrar_action_reference": "TRF-1909-EARLY"},
            make_registrar_headers(bundle["registrar"]["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_IMPLEMENTATION_PERIOD_ACTIVE.value, 409)
        still_issued = read_decision(decision["id"])
        assert still_issued["status"] == "ISSUED"
        assert still_issued["implemented_at"] is None
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "LOCKED"

        admitted = file_court_challenge(bundle, "RESPONDENT", docket_number="5:26-cv-02020")
        assert admitted["status"] == "FILED"
        assert admitted["filed_at"] == "2026-09-16T10:00:00.000Z"
        assert read_decision(decision["id"])["status"] == "STAYED"

    def test_one_second_past_the_deadline_the_registrar_acts_and_the_court_is_too_late(self):
        """PRD §3.8: "Once the clock is strictly past it, the registrar may act and
        the challenge window has shut — an attempt to file is refused with
        `ERR_CHALLENGE_WINDOW_CLOSED`."
        PRD §3.8: "Execution moves the decision from `ISSUED` to `IMPLEMENTED` with
        `implemented_at` stamped from the clock, and translates the outcome onto the
        domain: an outcome of `TRANSFER` drives `lock_status` to
        `TRANSFER_EXECUTED`, an outcome of `CANCELLATION` drives it to
        `CANCELLATION_EXECUTED`, and an outcome of `COMPLAINT_DENIED` simply
        releases the lock back to `UNLOCKED`."

        Design: Difficulty/boundary_precision_check/implementation_deadline_instant_is_still_inside_the_waiting_period
        """
        bundle = self._issued_transfer_decision()
        decision_id = bundle["decision"]["id"]
        set_clock("2026-09-16T10:00:01Z")
        too_late = api_client.create_court_challenge(
            decision_id,
            court_challenge_payload(
                "RESPONDENT", docket_number="5:26-cv-02121",
                # A respondent proves identity per request, so the challenge must
                # carry the verified registrant address to reach the window check.
                respondent_email=VERIFIED_REGISTRANT_EMAIL,
            ),
            make_respondent_headers(),
        )
        validate_error(too_late, ApiErrorId.ERR_CHALLENGE_WINDOW_CLOSED.value, 409)
        _, meta = validate_paginated(
            api_client.list_court_challenges(decision_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0

        implemented = implement_decision(bundle, registrar_action_reference="TRF-1909-FINAL")
        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["implemented_at"] == "2026-09-16T10:00:01.000Z"
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "TRANSFER_EXECUTED"
        case = read_case(bundle["case"]["id"])
        assert case["status"] == "IMPLEMENTED"
        assert case["closed_at"] == "2026-09-16T10:00:01.000Z"
        assert case["refiling_bar_until"] == "2026-10-16T10:00:01.000Z"
        assert read_appointment(bundle["appointments"][0]["id"])["status"] == "DISCHARGED"
        assert read_panelist(bundle["panelists"][0]["id"])["active_case_load"] == 0
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 0
