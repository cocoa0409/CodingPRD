"""The two independent recount dimensions, and the audit that gates the workflow one."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    fixtures,
    make_candidate_representative_headers,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]

DAVIS_REP = "rep-davis"
BRENNAN_REP = "rep-brennan"
DIRECTOR_USER_ID = "dir-1"


def _fund(recount_id, amount_cents, requester_user_id):
    return api_client.post_recount_deposit(
        recount_id,
        {"amount_cents": amount_cents},
        make_candidate_representative_headers(requester_user_id),
    )


class TestInvalidRecountStatePrecedesInsufficientDeposit:
    """A second payment breaks the state rule and the amount rule; the earlier tier wins."""

    def _setup_fully_funded_partial_recount(self):
        scenario = fixtures.setup_canvassed_treasurer_contest()
        scenario["recount"] = fixtures.file_recount(
            scenario["contest"]["id"],
            requester_user_id=DAVIS_REP,
            scope="PARTIAL_BATCHES",
            scope_batch_ids=[batch["id"] for batch in scenario["batches"]],
            requested_by_candidate_name="DAVIS",
        )
        assert scenario["recount"]["required_deposit_cents"] == 170000
        scenario["held"] = fixtures.post_deposit(
            scenario["recount"]["id"], 170000, DAVIS_REP
        )
        return scenario

    def test_a_second_payment_on_a_funded_recount_reports_the_state_conflict(self):
        """PRD §2.9 places the invalid-state tier, whose recount member is
        `ERR_INVALID_RECOUNT_STATE`, at priority 14 and "The amount tendered equals the
        assessed deposit exactly — otherwise `ERR_DEPOSIT_INSUFFICIENT`, the service's only
        HTTP 402" at priority 48, and: "The server evaluates the checks below in exactly this
        order and responds to the **first** violation it finds; no later check is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/priority_invalid_recount_state_precedes_deposit_insufficient
        """
        scenario = self._setup_fully_funded_partial_recount()
        assert scenario["held"]["status"] == "DEPOSIT_HELD"
        assert scenario["held"]["deposit_status"] == "HELD"

        response = _fund(scenario["recount"]["id"], 999, DAVIS_REP)

        validate_error(response, ApiErrorId.ERR_INVALID_RECOUNT_STATE.value, 409)

    def test_the_refused_underpayment_moves_no_money_at_all(self):
        """PRD §3.8: "The recount must be `REQUESTED` with `deposit_status` `PENDING`; a
        recount that never owed a deposit is refused because no deposit is required, and one
        already funded is an illegal recount transition."

        Design: Difficulty/priority_pair_validation_conflict/priority_invalid_recount_state_precedes_deposit_insufficient
        """
        scenario = self._setup_fully_funded_partial_recount()

        _fund(scenario["recount"]["id"], 999, DAVIS_REP)

        recount = fixtures.read_recount(scenario["recount"]["id"])
        assertions.assert_recount(recount)
        assert recount["status"] == "DEPOSIT_HELD"
        assert recount["deposit_status"] == "HELD"
        assert recount["deposit_paid_cents"] == 170000
        assert recount["required_deposit_cents"] == 170000
        assert recount["refunded_cents"] == 0
        assert recount["forfeited_cents"] == 0
        assert recount["admin_retained_cents"] == 0


class TestMarginTriggeredRecountSkipsTheDepositState:
    """The workflow dimension runs REQUESTED to COMPLETED with the money dimension frozen."""

    def _file_margin_triggered_recount(self):
        scenario = fixtures.setup_canvassed_treasurer_contest()
        scenario["recount"] = fixtures.file_recount(
            scenario["contest"]["id"],
            requester_user_id=DIRECTOR_USER_ID,
            role="ElectionsDirector",
            trigger_type="AUTOMATIC_MARGIN",
        )
        return scenario

    def test_a_margin_triggered_recount_owes_nothing_and_refuses_funding(self):
        """PRD §3.8: "A recount whose `trigger_type` is `AUTOMATIC_MARGIN` or
        `AUDIT_ESCALATION` is free: `required_deposit_cents` is zero and `deposit_status` is
        `NOT_REQUIRED`." §2.9: "The recount actually owes a deposit before it may be funded —
        otherwise `ERR_DEPOSIT_NOT_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/nonlinear_recount_workflow_skips_deposit_state_while_money_dimension_frozen
        """
        scenario = self._file_margin_triggered_recount()
        filed = scenario["recount"]
        assertions.assert_recount(filed)
        assert filed["required_deposit_cents"] == 0
        assert filed["deposit_status"] == "NOT_REQUIRED"
        assert filed["status"] == "REQUESTED"

        response = _fund(filed["id"], 125000, DIRECTOR_USER_ID)

        validate_error(response, ApiErrorId.ERR_DEPOSIT_NOT_REQUIRED.value, 409)
        assert fixtures.read_recount(filed["id"])["status"] == "REQUESTED"

    def test_the_workflow_starts_straight_from_requested(self):
        """PRD §3.8: "The elections director starts a recount from `DEPOSIT_HELD`, or from
        `REQUESTED` when `deposit_status` is `NOT_REQUIRED` and no deposit was ever owed."

        Design: Difficulty/non_linear_state_machine/nonlinear_recount_workflow_skips_deposit_state_while_money_dimension_frozen
        """
        scenario = self._file_margin_triggered_recount()
        _fund(scenario["recount"]["id"], 125000, DIRECTOR_USER_ID)

        started = validate_success(
            api_client.start_recount(scenario["recount"]["id"], DIRECTOR)
        )

        assert started["status"] == "IN_PROGRESS"
        assert started["deposit_status"] == "NOT_REQUIRED"
        assert started["deposit_paid_cents"] == 0

    def test_completion_settles_the_cost_without_touching_the_money_dimension(self):
        """PRD §3.8: "A recount that carried no deposit leaves `deposit_status` at
        `NOT_REQUIRED` throughout." §3.8: "`actual_cost_cents` is the ballot cost plus the
        labour cost."

        Design: Difficulty/non_linear_state_machine/nonlinear_recount_workflow_skips_deposit_state_while_money_dimension_frozen
        """
        scenario = self._file_margin_triggered_recount()
        _fund(scenario["recount"]["id"], 125000, DIRECTOR_USER_ID)
        fixtures.start_recount(scenario["recount"]["id"])

        completed = fixtures.complete_recount(
            scenario["recount"]["id"], {"CHEN": 1570, "DAVIS": 1430}, 6.5
        )

        assert completed["status"] == "COMPLETED"
        assert completed["deposit_status"] == "NOT_REQUIRED"
        assert completed["deposit_paid_cents"] == 0
        assert completed["refunded_cents"] == 0
        assert completed["forfeited_cents"] == 0
        assert completed["actual_cost_cents"] == 68701
        assert completed["final_margin_votes"] == 140
        assert completed["outcome_changed"] is False
        contest = fixtures.read_contest(scenario["contest"]["id"])
        assert contest["margin_votes"] == 140
        assert contest["open_recount_count"] == 0


class TestRecountStartIsBlockedByALiveAudit:
    """Terminating the audit — a write on another row — unblocks the identical start call."""

    def _setup_funded_recount_under_a_live_audit(self):
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        scenario["recount"] = fixtures.file_recount(
            scenario["contest"]["id"],
            requester_user_id=BRENNAN_REP,
            requested_by_candidate_name="BRENNAN",
        )
        assert scenario["recount"]["required_deposit_cents"] == 200000
        scenario["held"] = fixtures.post_deposit(
            scenario["recount"]["id"], 200000, BRENNAN_REP
        )
        return scenario

    def test_a_fully_funded_recount_cannot_start_while_the_audit_is_live(self):
        """PRD §3.8: "no audit of the contest may sit outside `COMPLETE` or `TERMINATED`, or
        it is refused for a non-terminal audit: recount and audit work on one contest never
        run at the same time."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_recount_start_blocked_by_live_audit
        """
        scenario = self._setup_funded_recount_under_a_live_audit()
        assert scenario["held"]["status"] == "DEPOSIT_HELD"

        response = api_client.start_recount(scenario["recount"]["id"], DIRECTOR)

        validate_error(response, ApiErrorId.ERR_AUDIT_NOT_TERMINAL.value, 409)
        recount = fixtures.read_recount(scenario["recount"]["id"])
        assert recount["status"] == "DEPOSIT_HELD"
        assert recount["deposit_status"] == "HELD"

    def test_terminating_the_audit_supersedes_its_round_and_clears_the_election(self):
        """PRD §3.4: "On success `status` becomes `TERMINATED`, the `terminated_reason` is
        recorded, `public_report_published` becomes true, every non-terminal round becomes
        `SUPERSEDED` ... The election's `open_audit_count` is decreased by one, its
        `certification_risk_flag` re-derived."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_recount_start_blocked_by_live_audit
        """
        scenario = self._setup_funded_recount_under_a_live_audit()
        api_client.start_recount(scenario["recount"]["id"], DIRECTOR)

        terminated = fixtures.terminate_audit(
            scenario["audit"]["id"],
            "Superseded by a full-contest recount of the same contest.",
        )

        assertions.assert_audit(terminated)
        assert terminated["status"] == "TERMINATED"
        assert terminated["public_report_published"] is True
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == (
            "SUPERSEDED"
        )
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["open_audit_count"] == 0
        assert election["certification_risk_flag"] is False

    def test_the_identical_start_call_succeeds_once_the_audit_is_terminal(self):
        """PRD §3.8: "On success `status` becomes `IN_PROGRESS`." §3.8: "Those two dimensions
        live on one row and advance independently: `status` is the workflow dimension and
        `deposit_status` the money dimension."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_recount_start_blocked_by_live_audit
        """
        scenario = self._setup_funded_recount_under_a_live_audit()
        validate_error(
            api_client.start_recount(scenario["recount"]["id"], DIRECTOR),
            ApiErrorId.ERR_AUDIT_NOT_TERMINAL.value,
            409,
        )
        fixtures.terminate_audit(
            scenario["audit"]["id"],
            "Superseded by a full-contest recount of the same contest.",
        )

        started = validate_success(
            api_client.start_recount(scenario["recount"]["id"], DIRECTOR)
        )

        assert started["status"] == "IN_PROGRESS"
        assert started["deposit_status"] == "HELD"
        assert started["refunded_cents"] == 0
        assert started["forfeited_cents"] == 0
