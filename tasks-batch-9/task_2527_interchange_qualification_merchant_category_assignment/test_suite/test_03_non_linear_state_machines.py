"""State machines whose shape is not a straight line: a bounded cycle, two
parallel dimensions on one row, and a fork that re-joins at a single terminal.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_request_info_payload,
    make_sustain_findings_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    clear_findings,
    close_audit,
    create_mcc,
    create_platform,
    create_acquirer,
    file_reclassification,
    finalize_batch,
    open_audit,
    open_batch,
    read_audit,
    read_batch,
    read_merchant,
    read_record,
    request_info,
    resubmit_reclassification,
    review_reclassification,
    reverse_record,
    set_clock,
    start_fieldwork,
    submit_batch,
)
from test_helpers.test_users import make_category_analyst_headers

ANALYST = "AN-1"
ALL_FOUR_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID", "TRANSACTION_DATE", "CARDHOLDER_ZIP"]


def _looped_reclassification():
    """A request to 9399 that has already been round-tripped twice, so it sits in
    `UNDER_REVIEW` with `review_round` 3."""
    set_clock("2026-09-03T00:00:00Z")
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    create_mcc(
        "5411",
        "GROCERY",
        description="Grocery Stores",
        program_eligibility=["SMALL_TICKET"],
    )
    create_mcc(
        "9399",
        "GOVERNMENT",
        description="Government Services",
        program_eligibility=["GOVERNMENT"],
        requires_documentation=True,
    )
    merchant = board_merchant(acquirer["id"], "GROCERY")
    request = file_reclassification(
        merchant["id"],
        "9399",
        acquirer["id"],
        expected_merchant_version=merchant["version"],
        justification="Municipal parking collections",
    )
    rounds = [request]
    review_reclassification(request["id"], analyst_user_id=ANALYST)
    request_info(
        request["id"],
        analyst_user_id=ANALYST,
        info_request_note="Provide the municipal charter",
    )
    rounds.append(
        resubmit_reclassification(
            request["id"], acquirer["id"], supporting_doc_ref="DOC-CHARTER-1"
        )
    )
    review_reclassification(request["id"], analyst_user_id=ANALYST)
    request_info(
        request["id"], analyst_user_id=ANALYST, info_request_note="Charter is unsigned"
    )
    rounds.append(
        resubmit_reclassification(
            request["id"], acquirer["id"], supporting_doc_ref="DOC-CHARTER-2"
        )
    )
    under_review = review_reclassification(request["id"], analyst_user_id=ANALYST)
    return {
        "acquirer": acquirer,
        "merchant": merchant,
        "request": request,
        "rounds": rounds,
        "under_review": under_review,
    }


class TestCyclicReclassificationReviewLoop:
    def test_each_answer_re_enters_submitted_and_raises_the_review_round(self):
        """Two full turns of the loop carry the request back into `SUBMITTED`
        twice, lifting `review_round` from 1 to 2 and then to 3.

        PRD 3.4: "The acquirer then answers, supplying `supporting_doc_ref`; this
        advances the request `INFO_REQUESTED → SUBMITTED`, increments
        `review_round` by 1, stores the supplied document reference and clears
        `info_request_note` back to null."

        Design: Difficulty/non_linear_state_machine/cyclic_reclassification_review_loop_terminates_at_max_review_rounds
        """
        state = _looped_reclassification()
        first, second, third = state["rounds"]

        assert first["status"] == "SUBMITTED"
        assert first["review_round"] == 1
        assert second["status"] == "SUBMITTED"
        assert second["review_round"] == 2
        assert second["supporting_doc_ref"] == "DOC-CHARTER-1"
        assert second["info_request_note"] is None
        assert third["status"] == "SUBMITTED"
        assert third["review_round"] == 3
        assert third["supporting_doc_ref"] == "DOC-CHARTER-2"

    def test_the_third_information_request_is_refused_and_the_request_does_not_move(self):
        """With `review_round` already at 3 the cycle may not turn again, and the
        refusal leaves the request exactly where it was.

        PRD 3.4: "Once `review_round` has reached 3, a further attempt is refused
        with `ERR_REVIEW_ROUND_LIMIT_EXCEEDED` and the request stays exactly where
        it was, in `INFO_REQUESTED`; where documentation is demanded on the answer
        and none is supplied, the refusal is `ERR_DOCUMENTATION_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/cyclic_reclassification_review_loop_terminates_at_max_review_rounds
        """
        state = _looped_reclassification()
        assert state["under_review"]["status"] == "UNDER_REVIEW"
        assert state["under_review"]["review_round"] == 3

        response = api_client.request_info_reclassification_request(
            state["request"]["id"],
            make_request_info_payload(info_request_note="Third bite at the apple"),
            make_category_analyst_headers(ANALYST),
        )
        validate_error(response, "ERR_REVIEW_ROUND_LIMIT_EXCEEDED", 422)

        reread = validate_success(
            api_client.get_reclassification_request(
                state["request"]["id"], make_category_analyst_headers(ANALYST)
            )
        )
        assert reread["review_round"] == 3
        assert reread["status"] == "UNDER_REVIEW"
        assert reread["supporting_doc_ref"] == "DOC-CHARTER-2"
        assert read_merchant(state["merchant"]["id"])["assigned_mcc"] == "5411"


def _qualified_record_of_three_hundred_cents():
    """A finalized 20000-cent record that qualified to CPS Retail for 300 cents."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", headers=env["acquirer_headers"]
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-09-02", "USD", headers=env["acquirer_headers"]
    )
    record = add_record(
        batch["id"],
        merchant["id"],
        20000,
        env["acquirer"]["id"],
        expected_batch_version=batch["version"],
        headers=env["acquirer_headers"],
        auth_code="A00050",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-01T01:00:00Z",
        data_elements=ALL_FOUR_ELEMENTS,
    )
    submit_batch(batch["id"], headers=env["acquirer_headers"])
    finalize_batch(batch["id"])
    env["merchant"] = merchant
    env["batch"] = batch
    env["record"] = record
    return env


class TestParallelAuthorizationAndQualificationDimensions:
    def test_an_authorization_reversal_leaves_the_qualification_dimension_and_the_money(
        self,
    ):
        """The authorization reversal moves only the first dimension: the record
        stays `QUALIFIED` with its 300 cents, and the batch total does not move.

        PRD 3.7: "`qualification_status`, `assessed_interchange_cents`, the batch's
        `total_assessed_cents` and the merchant's `lifetime_net_assessed_cents` are
        all left untouched — the dimensions are isolated, and an implementation
        that reaches into the ledger here is wrong."

        Design: Difficulty/non_linear_state_machine/parallel_authorization_and_qualification_dimensions_move_independently
        """
        env = _qualified_record_of_three_hundred_cents()
        assert (
            read_record(env["record"]["id"])["qualified_rate_program_id"]
            == env["programs"]["CPS_RETAIL"]["id"]
        )

        reversed_auth = reverse_record(env["record"]["id"], "AUTH_REVERSAL")
        assert reversed_auth["authorization_status"] == "AUTH_REVERSED"
        assert reversed_auth["qualification_status"] == "QUALIFIED"
        assert reversed_auth["assessed_interchange_cents"] == 300
        assert read_batch(env["batch"]["id"])["total_assessed_cents"] == 300

    def test_a_clearing_reversal_zeroes_the_money_and_leaves_the_authorization_alone(
        self,
    ):
        """The clearing reversal moves only the second dimension: the record goes
        to `REVERSED` and its money is zeroed out of both ledgers, while
        `authorization_status` stays at the `AUTH_REVERSED` the earlier call left.

        PRD 3.7: "Throughout, `authorization_status` is not touched: a record can
        perfectly well sit in `AUTH_APPROVED` and `REVERSED` at the same time."

        Design: Difficulty/non_linear_state_machine/parallel_authorization_and_qualification_dimensions_move_independently
        """
        env = _qualified_record_of_three_hundred_cents()
        reverse_record(env["record"]["id"], "AUTH_REVERSAL")

        reversed_clearing = reverse_record(env["record"]["id"], "CLEARING_REVERSAL")
        assert reversed_clearing["authorization_status"] == "AUTH_REVERSED"
        assert reversed_clearing["qualification_status"] == "REVERSED"
        assert reversed_clearing["assessed_interchange_cents"] == 0
        assert read_batch(env["batch"]["id"])["total_assessed_cents"] == 0
        assert read_merchant(env["merchant"]["id"])["lifetime_net_assessed_cents"] == 0


AUDITOR = "CA-1"
CLOSER = "CA-2"


def _audit_in_fieldwork():
    """A documentation-gated utility merchant, boarded in
    `PENDING_VERIFICATION`, with an audit already in `FIELDWORK`."""
    set_clock("2026-09-03T00:00:00Z")
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    create_mcc(
        "4900",
        "UTILITY_SERVICE",
        description="Utilities",
        program_eligibility=["UTILITY"],
        requires_documentation=True,
    )
    create_mcc(
        "7995",
        "GAMBLING",
        description="Betting and Wagering",
        program_eligibility=[],
        requires_documentation=True,
        high_risk=True,
    )
    merchant = board_merchant(
        acquirer["id"], "UTILITY_SERVICE", legal_name="City Water Co"
    )
    audit = open_audit(merchant["id"], "PERIODIC", auditor_user_id=AUDITOR)
    start_fieldwork(
        audit["id"],
        "2026-09-03T09:00:00Z",
        "2026-09-05T17:00:00Z",
        auditor_user_id=AUDITOR,
    )
    return {"acquirer": acquirer, "merchant": merchant, "audit": audit}


class TestForkJoinCategoryAudit:
    def test_clearing_the_findings_restores_the_snapshotted_posture_verbatim(self):
        """The merchant was boarded in `PENDING_VERIFICATION`, so the snapshot
        holds that value and the cleared branch restores it rather than promoting
        the merchant to `VERIFIED`.

        PRD 3.9: "The merchant's `mcc_status` is restored verbatim from
        `mcc_status_before_review` and that snapshot field is then set back to
        null: a merchant whose snapshot held `VERIFIED` returns `UNDER_REVIEW →
        VERIFIED`, and a merchant whose snapshot held `PENDING_VERIFICATION`
        returns `UNDER_REVIEW → PENDING_VERIFICATION`."

        Design: Difficulty/non_linear_state_machine/fork_join_category_audit_cleared_branch_locks_out_the_sustained_branch
        """
        state = _audit_in_fieldwork()
        under_audit = read_merchant(state["merchant"]["id"])
        assert under_audit["mcc_status"] == "UNDER_REVIEW"
        assert under_audit["mcc_status_before_review"] == "PENDING_VERIFICATION"

        cleared = clear_findings(
            state["audit"]["id"],
            auditor_user_id=AUDITOR,
            findings_note="Utility classification is correct",
        )
        assert cleared["status"] == "FINDINGS_CLEARED"
        assert cleared["penalty_assessed_cents"] == 0
        assert cleared["correct_mcc"] is None

        merchant = read_merchant(state["merchant"]["id"])
        assert merchant["mcc_status"] == "PENDING_VERIFICATION"
        assert merchant["mcc_status_before_review"] is None
        assert merchant["assigned_mcc"] == "4900"

    def test_the_cleared_branch_locks_out_the_sustained_branch_and_the_join_closes(self):
        """The two branches are mutually exclusive, so sustaining after clearing is
        refused, and the audit still reaches the shared terminal when a second
        auditor closes it.

        PRD 3.9: "From `FIELDWORK` exactly one of two mutually exclusive branches
        may be taken, and both are reserved to the operator recorded as
        `auditor_user_id`; another auditor attempting either branch is refused with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/fork_join_category_audit_cleared_branch_locks_out_the_sustained_branch
        """
        state = _audit_in_fieldwork()
        clear_findings(
            state["audit"]["id"],
            auditor_user_id=AUDITOR,
            findings_note="Utility classification is correct",
        )

        from test_helpers.test_users import make_compliance_auditor_headers

        response = api_client.sustain_audit_findings(
            state["audit"]["id"],
            make_sustain_findings_payload(
                "7995", findings_note="Attempt the other branch"
            ),
            make_compliance_auditor_headers(AUDITOR),
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        after_refusal = read_audit(state["audit"]["id"])
        assert after_refusal["correct_mcc"] is None
        assert after_refusal["penalty_assessed_cents"] == 0
        assert read_merchant(state["merchant"]["id"])["assigned_mcc"] == "4900"

        closed = close_audit(state["audit"]["id"], CLOSER)
        assert closed["status"] == "CLOSED"
        assert closed["closed_by_user_id"] == CLOSER
