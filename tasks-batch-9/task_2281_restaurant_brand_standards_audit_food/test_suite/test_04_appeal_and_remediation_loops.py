"""The capped appeal review cycle and the reject/resubmit remediation loop."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    STANDARD_ACTION_DUE_AT,
    ApiErrorId,
    api_client,
    assert_corrective_action,
    assert_dispute,
    assert_instant,
    request_info_payload,
    setup_dispute_after_two_info_cycles,
    setup_finalized_visit,
    setup_rejected_corrective_action,
    validate_error,
    validate_success,
    verify_payload,
)


class TestCappedInformationRequests:
    def test_two_information_cycles_walk_the_dispute_back_and_forth(self):
        """Each accepted request raises the counter and returns to evidence review.

        PRD: "From `EVIDENCE_REVIEW` a reviewer may push the dispute back to
        `INFO_REQUESTED` for another round, again raising `info_request_count`; but
        `info_request_count` must be strictly below 2 for any information request to be
        accepted, so the `EVIDENCE_REVIEW → INFO_REQUESTED → EVIDENCE_REVIEW` cycle is
        capped at two rounds and a third request is rejected with
        `ERR_INFO_REQUEST_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/dispute_third_information_request_rejected_after_two_cycles
        """
        program = setup_dispute_after_two_info_cycles()

        first_cycle, second_cycle = program["info_requests"]
        assert first_cycle["status"] == "INFO_REQUESTED"
        assert first_cycle["info_request_count"] == 1
        assert second_cycle["status"] == "INFO_REQUESTED"
        assert second_cycle["info_request_count"] == 2

        dispute = program["dispute"]
        assert_dispute(dispute)
        assert dispute["status"] == "EVIDENCE_REVIEW", \
            "each supplement returns the dispute to evidence review"
        assert dispute["info_request_count"] == 2
        assert dispute["reviewer_auditor_id"] == program["reviewer"]["id"], \
            "the first information request claims the dispute for its reviewer"

    def test_the_third_information_request_is_refused_at_the_cap(self):
        """A third round is rejected and leaves the dispute exactly where it was.

        PRD: "`info_request_count` is below 2 — `ERR_INFO_REQUEST_LIMIT_REACHED` (HTTP
        409), on `POST /disputes/{id}/request-info`."

        Design: Difficulty/non_linear_state_machine/dispute_third_information_request_rejected_after_two_cycles
        """
        program = setup_dispute_after_two_info_cycles()
        dispute_id = program["dispute"]["id"]

        validate_error(
            api_client.request_dispute_info(
                dispute_id,
                request_info_payload(information_requested="One more document, please."),
                program["reviewer_calibration_headers"],
            ),
            ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED,
            expected_status=409,
        )

        dispute = validate_success(api_client.get_dispute(dispute_id, ADMIN_HEADERS))
        assert dispute["status"] == "EVIDENCE_REVIEW", "the refused request is a no-op"
        assert dispute["info_request_count"] == 2, "the counter does not move past the cap"
        assert dispute["resolved_at"] is None


class TestRemediationRejectResubmitLoop:
    def test_rejection_counts_the_round_and_keeps_the_violation_open(self):
        """A rejected action loops back without closing the open-action pool.

        PRD: "When the `outcome` is `REJECTED`, a `rejection_reason` must accompany it,
        the action moves `SUBMITTED → REJECTED`, and `rejection_count` rises by one; the
        open-action count does not move, because the violation remains open."

        Design: Difficulty/non_linear_state_machine/corrective_action_reject_resubmit_cycle_reaches_verified
        """
        baseline = setup_finalized_visit()
        assert baseline["visit"]["status"] == "FINALIZED"
        location_before = validate_success(
            api_client.get_location(baseline["location"]["id"], ADMIN_HEADERS)
        )
        assert location_before["open_corrective_action_count"] == 3, \
            "one action per violating scored item"

        program = setup_rejected_corrective_action(baseline, item_code="BS-1")
        action = program["action"]
        assert_corrective_action(action)
        assert action["severity"] == "STANDARD"
        assert_instant(action["due_at"], STANDARD_ACTION_DUE_AT, "due_at")
        assert action["status"] == "REJECTED"
        assert action["submission_count"] == 1
        assert action["rejection_count"] == 1

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["open_corrective_action_count"] == 3, \
            "a rejection leaves the action inside the open remediation pool"

    def test_resubmission_after_rejection_reaches_verified_and_closes_the_action(self):
        """The loop lets the franchisee iterate and still finish at VERIFIED.

        PRD: "A rejected action may be resubmitted, advancing `REJECTED → SUBMITTED` under
        exactly the same ownership and evidence preconditions and again raising
        `submission_count` and refreshing `submitted_at`; this is the loop that lets a
        franchisee iterate on inadequate evidence."

        Design: Difficulty/non_linear_state_machine/corrective_action_reject_resubmit_cycle_reaches_verified
        """
        program = setup_rejected_corrective_action(item_code="BS-1")
        action_id = program["action"]["id"]

        resubmitted = validate_success(
            api_client.submit_corrective_action(
                action_id, program["franchisee_headers"],
                {"remediation_note": "Replacement fitting installed and photographed."},
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_count"] == 2
        assert resubmitted["rejection_count"] == 1
        assert resubmitted["evidence_photo_count"] == 2

        verified = validate_success(
            api_client.verify_corrective_action(
                action_id, verify_payload("ACCEPTED"), program["auditor_headers"],
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["submission_count"] == 2, "both submissions are counted"
        assert verified["rejection_count"] == 1
        assert verified["verified_at"] is not None

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["open_corrective_action_count"] == 2, \
            "acceptance drops the location's open-action count by one"
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "remediation does not rewrite the audit score"
