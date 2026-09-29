"""Requests that violate two rules at once: the earlier rung of the ladder answers."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    approve_milestone_payload,
    create_refinancing_event_payload,
    create_relief_claim_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    CERTIFIER,
    list_reserve_rows,
    raise_enforcement_action,
    refresh_concession,
    request_milestone,
    set_clock,
    setup_concession_at_financial_close,
    setup_concession_in_operations,
    setup_notified_relief_claim,
)


class TestTargetStateBeatsTheCommitmentCeiling:
    def test_re_approving_an_approved_milestone_reports_the_state_violation(self):
        """A second approval at 500,000,000 cents breaches both state and commitment.

        PRD: "Both branches require the milestone to be in `REQUESTED`, and
        approval additionally requires the concession to be in `FINANCIAL_CLOSE` or
        `CONSTRUCTION`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_commitment_ceiling_on_a_second_milestone_approval
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        validate_success(
            api_client.approve_drawdown_milestone(
                milestone["id"], approve_milestone_payload(120000000), CERTIFIER
            )
        )

        response = api_client.approve_drawdown_milestone(
            milestone["id"], approve_milestone_payload(500000000), CERTIFIER
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    def test_the_refused_re_approval_leaves_the_first_split_and_the_concession_alone(self):
        """The target row's own state is read before any funding ceiling is tested.

        PRD: "Where several rules could refuse the same request, they are evaluated
        in a fixed order and the first violation found is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_commitment_ceiling_on_a_second_milestone_approval
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        api_client.approve_drawdown_milestone(
            milestone["id"], approve_milestone_payload(120000000), CERTIFIER
        )

        api_client.approve_drawdown_milestone(
            milestone["id"], approve_milestone_payload(500000000), CERTIFIER
        )

        unchanged = validate_success(
            api_client.get_drawdown_milestone(milestone["id"], ALPHA)
        )
        assert unchanged["status"] == "APPROVED"
        assert unchanged["certified_cost_cents"] == 120000000
        assert unchanged["equity_portion_cents"] == 100000000
        assert unchanged["debt_portion_cents"] == 20000000
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 0
        assert concession["senior_debt_drawn_cents"] == 0
        assert concession["status"] == "FINANCIAL_CLOSE"


class TestNotificationDeadlineBeatsTheWindowConflict:
    def test_a_late_claim_inside_a_buffered_window_reports_the_late_notification(self):
        """The second claim is both late and buffered-adjacent to the first.

        PRD: "The claim's `notified_at` is stamped from the logical clock at
        creation, and the whole calendar days between the claimed `event_start` and
        that instant must be at most twenty."

        Design: Difficulty/priority_pair_validation_conflict/relief_notification_deadline_beats_the_buffered_window_conflict
        """
        ctx = setup_notified_relief_claim()
        set_clock("2027-03-20T00:00:00Z")

        response = api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                "RELIEF_EVENT", "2027-02-12", "2027-02-20", 9, 300000
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_RELIEF_NOTIFICATION_LATE", 422)

    def test_the_refused_late_claim_writes_no_row_and_leaves_the_first_claim_alone(self):
        """The notification window sits above the relief-window conflict on the ladder.

        PRD: "Exactly twenty days after the event began is still in time;
        twenty-one days is `ERR_RELIEF_NOTIFICATION_LATE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/relief_notification_deadline_beats_the_buffered_window_conflict
        """
        ctx = setup_notified_relief_claim()
        first_claim_id = ctx["relief_claim"]["id"]
        set_clock("2027-03-20T00:00:00Z")

        api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                "RELIEF_EVENT", "2027-02-12", "2027-02-20", 9, 300000
            ),
            ctx["cnr_headers"],
        )

        body = api_client.list_relief_claims(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 1
        first = validate_success(api_client.get_relief_claim(first_claim_id, ALPHA))
        assert first["status"] == "NOTIFIED"
        assert first["granted_relief_days"] == 0
        assert refresh_concession(ctx)["status"] == "OPERATIONS"


class TestEnforcementFreezeBeatsTheGainTest:
    def test_a_frozen_project_reports_the_enforcement_rather_than_the_missing_gain(self):
        """The proposal would also fail the gain test, but the freeze answers first.

        PRD: "The proposal requires the concession to be in `OPERATIONS`, otherwise
        `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (HTTP 409), and is frozen by a live
        enforcement action with `ERR_CONCESSION_UNDER_ENFORCEMENT` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/open_enforcement_freeze_beats_the_no_gain_refinancing_check
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-04-02T00:00:00Z")
        raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2027-04-02", ALPHA
        )

        response = api_client.create_refinancing_event(
            ctx["concession_id"],
            create_refinancing_event_payload("2027-04-02", 150000000, 180000000, 2000000),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_CONCESSION_UNDER_ENFORCEMENT", 409)

    def test_the_frozen_proposal_appends_neither_a_refinancing_row_nor_a_ledger_row(self):
        """The enforcement freeze sits above the refinancing-gain test on the ladder.

        PRD: "The ordering is deliberate, and fiscal caps sit last on purpose."

        Design: Difficulty/priority_pair_validation_conflict/open_enforcement_freeze_beats_the_no_gain_refinancing_check
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-04-02T00:00:00Z")
        raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2027-04-02", ALPHA
        )

        api_client.create_refinancing_event(
            ctx["concession_id"],
            create_refinancing_event_payload("2027-04-02", 150000000, 180000000, 2000000),
            ctx["cnr_headers"],
        )

        body = api_client.list_refinancing_events(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 0
        concession = refresh_concession(ctx)
        assert concession["lifecycle_reserve_balance_cents"] == 8000000
        _, reserve_meta = list_reserve_rows(ctx["concession_id"])
        assert reserve_meta["total_count"] == 1
