"""One request per catalogued error code, each aimed at the rung that must answer it."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    adjudicate_dispute_payload,
    approve_milestone_payload,
    create_dispute_payload,
    create_enforcement_action_payload,
    determine_relief_claim_payload,
    reject_performance_report_payload,
    reverse_reserve_transaction_payload,
    withdraw_deduction_event_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ALPHA,
    BETA,
    CERTIFIER,
    LENDER,
    list_enforcement_rows,
    refresh_concession,
    refresh_service_period,
    set_clock,
    setup_concession_in_operations,
    setup_disputed_deduction,
)


class TestUnauthenticatedOutranksEverything:
    def test_a_headerless_reversal_of_a_missing_row_is_a_401_not_a_404(self):
        """No identity, an unresolvable path id and a thin body: the 401 answers first.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the five
        recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401) before anything else is examined."

        Design: Corner/errors/a_headerless_request_is_answered_before_the_path_is_resolved
        """
        response = api_client.reverse_reserve_transaction(
            NON_EXISTENT_UUID,
            reverse_reserve_transaction_payload("no identity headers on this request"),
            NO_AUTH_HEADERS,
        )

        validate_error(response, "ERR_UNAUTHENTICATED", 401)
        error_body = response.json()["data"]
        assert "id" not in error_body
        assert "resulting_balance_cents" not in error_body
        assert "sequence_no" not in error_body
        body = api_client.list_reserve_transactions(ADMIN).json()
        assert body["meta"]["total_count"] == 0


class TestEnforcementGroundsAreArmSpecific:
    def test_a_voluntary_ground_cannot_support_a_step_in(self):
        """Both enum members are valid; only the pairing is not.

        PRD: "Grounds are not interchangeable between the arms: `PERSISTENT_BREACH`
        and `LENDER_DEFAULT_CURE` are the only grounds admitted for a step-in, and
        `AUTHORITY_VOLUNTARY`, `CONCESSIONAIRE_DEFAULT`, `AUTHORITY_DEFAULT` and
        `FORCE_MAJEURE` are the only grounds admitted for a termination."

        Design: Corner/errors/a_voluntary_ground_cannot_support_a_step_in
        """
        ctx = setup_concession_in_operations()

        response = api_client.create_enforcement_action(
            ctx["concession_id"],
            create_enforcement_action_payload(
                "STEP_IN", "AUTHORITY_VOLUNTARY", "2027-02-01"
            ),
            ALPHA,
        )

        validate_error(response, "ERR_ENFORCEMENT_GROUND_NOT_ADMITTED", 422)
        _, meta = list_enforcement_rows(ctx["concession_id"])
        assert meta["total_count"] == 0
        assert refresh_concession(ctx)["status"] == "OPERATIONS"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "ACTIVE"

        # The admitted step-in ground used as the control is LENDER_DEFAULT_CURE:
        # PERSISTENT_BREACH additionally requires the points ledger to have set
        # persistent_breach_flag, which this concession has not done.
        admitted = validate_success(
            api_client.create_enforcement_action(
                ctx["concession_id"],
                create_enforcement_action_payload(
                    "STEP_IN", "LENDER_DEFAULT_CURE", "2027-02-01"
                ),
                ALPHA,
            ),
            201,
        )
        assert admitted["status"] == "STEP_IN_ACTIVE"
        assert admitted["cure_deadline"] == "2027-05-02"
        assert refresh_concession(ctx)["status"] == "STEP_IN"


class TestOnlyOneDisputeMayBeOpenAtATime:
    def test_a_second_dispute_on_the_same_deduction_costs_nothing(self):
        """The open dispute blocks the second raise even though the event is still live.

        PRD: "At most one dispute per event may be open — that is, sitting in
        `RAISED`, `REFERRED_BACK` or `RESUBMITTED` — and a second attempt is refused
        with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/errors/only_one_dispute_may_be_open_on_a_deduction_at_a_time
        """
        ctx = setup_disputed_deduction()
        event_id = ctx["deduction_event"]["id"]
        first_dispute = ctx["dispute"]

        response = api_client.create_deduction_dispute(
            event_id,
            create_dispute_payload("Second bite at the same deduction."),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_DISPUTE_ALREADY_OPEN", 409)
        body = api_client.list_deduction_disputes(
            ALPHA, params={"deduction_event_id": event_id}
        ).json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["id"] == first_dispute["id"]
        held = validate_success(
            api_client.get_deduction_dispute(first_dispute["id"], ALPHA)
        )
        assert held["status"] == "RAISED"
        assert held["round_no"] == 1
        assert held["grounds"] == first_dispute["grounds"]
        event = validate_success(api_client.get_deduction_event(event_id, ALPHA))
        assert event["status"] == "DISPUTED"
        assert event["allowed_amount_cents"] == 500000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167



class TestApprovingAnUnknownMilestone:
    def test_the_certifier_is_told_the_milestone_does_not_exist(self):
        """The role and the body are both correct, so only the path id can answer.

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/approving_an_unknown_milestone_is_not_found
        """
        response = api_client.approve_drawdown_milestone(
            NON_EXISTENT_UUID, approve_milestone_payload(120000000), CERTIFIER
        )

        validate_error(response, "ERR_DRAWDOWN_MILESTONE_NOT_FOUND", 404)
        body = api_client.list_drawdown_milestones(LENDER).json()
        assert body["meta"]["total_count"] == 0


class TestRejectingAnUnknownPerformanceReport:
    def test_an_unresolvable_report_in_the_path_uses_its_own_entity_code(self):
        """The same id in a body would be a referenced-entity failure instead.

        PRD: "A request that both names a non-existent path resource and carries a
        malformed body is a 404, not a 400."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/rejecting_an_unknown_performance_report_is_not_found
        """
        response = api_client.reject_performance_report(
            NON_EXISTENT_UUID,
            reject_performance_report_payload("Unsupported minute log."),
            ALPHA,
        )

        validate_error(response, "ERR_PERFORMANCE_REPORT_NOT_FOUND", 404)
        body = api_client.list_performance_reports(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestWithdrawingAnUnknownDeductionEvent:
    def test_no_period_is_recomputed_for_an_event_that_does_not_exist(self):
        """Withdrawal is the write that reverses money, and it never starts here.

        PRD: "Where a path names more than one id, the ids are resolved left to right
        and the leftmost unresolvable id determines the error."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/withdrawing_an_unknown_deduction_event_is_not_found
        """
        response = api_client.withdraw_deduction_event(
            NON_EXISTENT_UUID,
            withdraw_deduction_event_payload("Issued against the wrong period."),
            ALPHA,
        )

        validate_error(response, "ERR_DEDUCTION_EVENT_NOT_FOUND", 404)
        body = api_client.list_deduction_events(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestAdjudicatingAnUnknownDispute:
    def test_the_404_precedes_the_segregation_of_duties_comparison(self):
        """There is no issuer to compare the adjudicating officer against.

        PRD: "Where several rules could refuse the same request, they are evaluated
        in a fixed order and the first violation found is the one reported."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/adjudicating_an_unknown_dispute_is_not_found
        """
        response = api_client.adjudicate_deduction_dispute(
            NON_EXISTENT_UUID,
            adjudicate_dispute_payload("UPHOLD", "Relief overlap accepted."),
            BETA,
        )

        validate_error(response, "ERR_DEDUCTION_DISPUTE_NOT_FOUND", 404)
        body = api_client.list_deduction_disputes(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestDeterminingAnUnknownReliefClaim:
    def test_a_rejection_decision_leaves_the_missing_row_as_the_only_defect(self):
        """A REJECT carries no granted figures, so no earlier rung has anything to test.

        PRD: "The identifier appears verbatim in the `error_id` field of the error
        envelope described in §2.2."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/determining_an_unknown_relief_claim_is_not_found
        """
        response = api_client.determine_relief_claim(
            NON_EXISTENT_UUID,
            determine_relief_claim_payload(
                "REJECT", determination_note="Not a qualifying event."
            ),
            ALPHA,
        )

        validate_error(response, "ERR_RELIEF_CLAIM_NOT_FOUND", 404)
        body = api_client.list_relief_claims(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestReversingAnUnknownReserveTransaction:
    def test_the_missing_row_is_not_reported_as_an_already_reversed_row(self):
        """With no target there is nothing that could have been reversed already.

        PRD: "Identifiers supplied in a request *body* rather than in the path are a
        separate rung: the `concessionaire_id` named when drafting a concession, the
        optional `performance_report_id` named when issuing a deduction event, and
        the reversal target named when reversing a ledger entry all yield
        `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) when they resolve to no row."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/reversing_an_unknown_reserve_transaction_is_not_found
        """
        response = api_client.reverse_reserve_transaction(
            NON_EXISTENT_UUID,
            reverse_reserve_transaction_payload("Booked against the wrong concession."),
            ADMIN,
        )

        validate_error(response, "ERR_RESERVE_TRANSACTION_NOT_FOUND", 404)
        body = api_client.list_reserve_transactions(ADMIN).json()
        assert body["meta"]["total_count"] == 0


class TestReadingAnUnknownRefinancingEvent:
    def test_the_read_side_404_returns_no_share_fields_at_all(self):
        """An admitted reader still gets a 404 rather than an empty gain-sharing shape.

        PRD: "Every resource is readable at exactly one level under the prefix, and
        no resource's id is ever nested inside another resource's id in a read path."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/reading_an_unknown_refinancing_event_is_not_found
        """
        response = api_client.get_refinancing_event(NON_EXISTENT_UUID, LENDER)

        validate_error(response, "ERR_REFINANCING_EVENT_NOT_FOUND", 404)
        error_body = response.json()["data"]
        assert "authority_share_cents" not in error_body
        assert "concessionaire_share_cents" not in error_body
        body = api_client.list_refinancing_events(LENDER).json()
        assert body["meta"]["total_count"] == 0


class TestEscalatingAnUnknownEnforcementAction:
    def test_a_bodyless_escalation_of_a_missing_row_never_reaches_the_cure_window(self):
        """A row that does not exist has no cure deadline to be early or late against.

        PRD: "Whichever of the two is attempted outside its window is refused with
        `ERR_CURE_WINDOW_VIOLATION` (HTTP 409)."

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/escalating_an_unknown_enforcement_action_is_not_found
        """
        set_clock("2027-06-01T00:00:00Z")

        response = api_client.escalate_enforcement_action(NON_EXISTENT_UUID, LENDER)

        validate_error(response, "ERR_ENFORCEMENT_ACTION_NOT_FOUND", 404)
        body = api_client.list_enforcement_actions(LENDER).json()
        assert body["meta"]["total_count"] == 0
