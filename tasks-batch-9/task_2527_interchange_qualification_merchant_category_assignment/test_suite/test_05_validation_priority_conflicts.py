"""Requests that violate two declared checks at once, where the published
rejection ladder decides which single error is reported.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_incentive_enrollment_payload,
    make_reclassification_request_payload,
)
from test_helpers.fixtures import (
    board_merchant,
    create_acquirer,
    create_incentive_program,
    create_mcc,
    create_platform,
    enrol_merchant,
    open_audit,
    read_incentive_program,
    read_merchant,
    set_clock,
    start_fieldwork,
    sustain_findings,
)
from test_helpers.test_users import TEST_USERS, make_acquirer_ops_headers

AUDITOR = "CA-1"


def _closed_full_program_and_a_second_eligible_merchant():
    """Merchant A's 96000000 commitment leaves 4000000 free, which is below the
    5000000 minimum and therefore closes the program."""
    set_clock("2026-09-03T00:00:00Z")
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    create_mcc(
        "5411",
        "GROCERY",
        description="Grocery Stores",
        program_eligibility=["SMALL_TICKET"],
    )
    program = create_incentive_program(
        program_name="Grocery Growth 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=80.00,
    )
    merchant_a = board_merchant(acquirer["id"], "GROCERY", legal_name="Grocer A")
    merchant_b = board_merchant(acquirer["id"], "GROCERY", legal_name="Grocer B")
    enrol_merchant(
        program["id"],
        merchant_a["id"],
        96000000,
        acquirer["id"],
        expected_incentive_program_version=program["version"],
    )
    return {
        "acquirer": acquirer,
        "program": read_incentive_program(program["id"]),
        "merchant_b": merchant_b,
    }


class TestClosedEnrollmentBeatsCapacity:
    def test_the_closed_state_error_masks_the_capacity_error(self):
        """The commitment of 6000000 both meets a `CLOSED_FULL` program and
        exceeds the 4000000 that remains free, and the ladder reports the state
        problem rather than the fiscal one.

        PRD 2.9: "Read the enrollment path against that ladder and the
        consequences are concrete: a request against a `CLOSED_FULL` program
        without `waitlist_requested` reports `ERR_ENROLLMENT_CLOSED` even if its
        `expected_incentive_program_version` is also stale and its commitment is
        also below the minimum, because priority 9 sits above priorities 12 and
        32."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_enrollment_closed_state_beats_incentive_capacity_fiscal
        """
        state = _closed_full_program_and_a_second_eligible_merchant()
        assert state["program"]["enrollment_state"] == "CLOSED_FULL"
        assert state["program"]["uncommitted_capacity_cents"] == 4000000

        response = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                state["program"]["id"],
                state["merchant_b"]["id"],
                6000000,
                state["program"]["version"],
                waitlist_requested=False,
            ),
            make_acquirer_ops_headers(state["acquirer"]["id"]),
        )
        error = validate_error(response, "ERR_ENROLLMENT_CLOSED", 409)
        assert error["error_id"] != "ERR_INCENTIVE_CAPACITY_EXCEEDED"

    def test_the_refused_enrollment_leaves_the_pool_and_the_program_version_alone(self):
        """A refusal writes nothing: the pool, the enrolled count, the state and
        the program's version are all exactly as they were.

        PRD 2.10: "At all times an incentive program's `total_capacity_cents` must
        equal its `uncommitted_capacity_cents` plus the sum of
        `committed_volume_cents` over its enrollments in status `ENROLLED` or
        `PROBATION`."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_enrollment_closed_state_beats_incentive_capacity_fiscal
        """
        state = _closed_full_program_and_a_second_eligible_merchant()
        before = state["program"]

        api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                before["id"],
                state["merchant_b"]["id"],
                6000000,
                before["version"],
                waitlist_requested=False,
            ),
            make_acquirer_ops_headers(state["acquirer"]["id"]),
        )

        after = read_incentive_program(before["id"])
        assert after["enrollment_state"] == "CLOSED_FULL"
        assert after["uncommitted_capacity_cents"] == 4000000
        assert after["enrolled_count"] == 1
        assert after["version"] == before["version"]


def _misrepresented_merchant():
    """A sustained audit rewrites the merchant to 7995 and freezes it."""
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
        "7995",
        "GAMBLING",
        description="Betting and Wagering",
        program_eligibility=[],
        requires_documentation=True,
        high_risk=True,
    )
    merchant = board_merchant(acquirer["id"], "GROCERY", legal_name="Corner Grocer")
    audit = open_audit(merchant["id"], "COMPLAINT", auditor_user_id=AUDITOR)
    start_fieldwork(
        audit["id"],
        "2026-09-03T09:00:00Z",
        "2026-09-04T17:00:00Z",
        auditor_user_id=AUDITOR,
    )
    sustain_findings(
        audit["id"],
        "7995",
        auditor_user_id=AUDITOR,
        findings_note="Gambling volume disguised as grocery",
    )
    return {"acquirer": acquirer, "merchant": read_merchant(merchant["id"])}


class TestMisrepresentedMerchantBeatsUndefinedCategory:
    def test_the_frozen_merchant_error_masks_the_undefined_category_error(self):
        """The request names both a frozen merchant and a category code no
        definition carries, and the ladder reports the merchant freeze.

        PRD 2.9: "The referenced merchant's `mcc_status` is not `MISREPRESENTED`
        — otherwise `ERR_MERCHANT_MISREPRESENTED` (409). A merchant proven to have
        misrepresented its category is frozen out of every downstream money or
        category operation, so this guard covers four operations: `POST
        /reclassification-requests`, `POST
        /settlement-batches/{id}/transaction-records`, `POST
        /incentive-enrollments` and `POST /merchants/{id}/verify-category`."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_merchant_misrepresented_safety_beats_mcc_not_defined_referential
        """
        state = _misrepresented_merchant()
        assert state["merchant"]["mcc_status"] == "MISREPRESENTED"

        response = api_client.create_reclassification_request(
            make_reclassification_request_payload(
                state["merchant"]["id"],
                "9999",
                state["merchant"]["version"],
                justification="Please restore grocery",
            ),
            make_acquirer_ops_headers(state["acquirer"]["id"]),
        )
        error = validate_error(response, "ERR_MERCHANT_MISREPRESENTED", 409)
        assert error["error_id"] != "ERR_MCC_NOT_DEFINED"

    def test_no_reclassification_row_is_created_and_the_merchant_is_untouched(self):
        """The terminal state absorbs the attempt: no request exists for the
        merchant and its restated category still stands.

        PRD 3.3: "`MISREPRESENTED` is terminal for a merchant. No transition
        leaves it, and while it holds, the merchant may not have clearing records
        added for it, may not be the subject of a new reclassification request,
        may not be enrolled into an incentive program, and may not be verified."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_merchant_misrepresented_safety_beats_mcc_not_defined_referential
        """
        state = _misrepresented_merchant()

        api_client.create_reclassification_request(
            make_reclassification_request_payload(
                state["merchant"]["id"],
                "9999",
                state["merchant"]["version"],
                justification="Please restore grocery",
            ),
            make_acquirer_ops_headers(state["acquirer"]["id"]),
        )

        listing = api_client.list_reclassification_requests(
            TEST_USERS["network_admin_headers"],
            params={"merchant_id": state["merchant"]["id"]},
        )
        rows, meta = validate_paginated(listing)
        assert rows == []
        assert meta["total_count"] == 0

        after = read_merchant(state["merchant"]["id"])
        assert after["mcc_status"] == "MISREPRESENTED"
        assert after["assigned_mcc"] == "7995"
