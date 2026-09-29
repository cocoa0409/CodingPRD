"""Submission reads a different aggregate's state.

Every application-local precondition is satisfied while the contract still waits
for its countersignature.  The submit is refused, and the identical call succeeds
the moment the countersignature lands.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents


@pytest.fixture()
def signed_but_unapproved_contract(client):
    """A ready student file behind a contract in compliance review."""
    partner = fx.build_active_partner(client, activate=False)
    fx.send_contract_for_signature(client, partner["contract_id"])

    ready = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-6001",
        passport_hash="hash-passport-6001",
        applicant_user_id="applicant-6001",
    )
    fx.agency_sign_contract(client, partner["agency_id"], partner["contract_id"])

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "contract_id": partner["contract_id"],
        "schedule_id": partner["schedule_id"],
        "application_id": ready["application_id"],
        "owner_headers": partner["owner_headers"],
    }


class TestSubmitGatedOnContractState:
    def test_submission_is_refused_while_the_contract_awaits_countersignature(
        self, client, signed_but_unapproved_contract
    ):
        """A file with every local precondition met still cannot move.

        "the agency has exactly one contract in `ACTIVE`, and that contract is the
        one pinned"

        "a blocked integrity standing, or the absence of a contract in `ACTIVE`, is
        `ERR_AGENCY_POSTURE_BLOCKED` and `ERR_INVALID_CONTRACT_STATE` respectively"

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_until_contract_reaches_active
        """
        env = signed_but_unapproved_contract

        response = client.submit_application(
            env["application_id"], env["owner_headers"]
        )
        validate_error(response, E.ERR_INVALID_CONTRACT_STATE)

        application = fx.read_application(client, env["application_id"])
        assert application["status"] == C.APPLICATION_DRAFT
        assert application["pinned_contract_id"] is None
        assert application["disclosure_state"] == C.DISCLOSURE_ACKNOWLEDGED

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_PENDING_COMPLIANCE_REVIEW

    def test_the_countersignature_unblocks_the_identical_call_and_pins_the_paper(
        self, client, signed_but_unapproved_contract
    ):
        """Approval is the only thing that changed between the two attempts.

        "`COMPLIANCE_APPROVE` moves `PENDING_COMPLIANCE_REVIEW → ACTIVE` and is
        the countersignature."

        "It pins `pinned_contract_id` to the sole contract in `ACTIVE` and
        `pinned_schedule_id` to the rate card effective on that date — and those
        two pins, not the currently effective records, are what every later
        milestone accrual reads."

        "The approving identity is stamped into `compliance_approved_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_until_contract_reaches_active
        """
        env = signed_but_unapproved_contract

        client.submit_application(env["application_id"], env["owner_headers"])
        fx.compliance_approve_contract(client, env["contract_id"])

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_ACTIVE
        assert contract["compliance_approved_by_user_id"] == "compliance-2"

        fx.submit_application(client, env["agency_id"], env["application_id"])

        application = fx.read_application(client, env["application_id"])
        assert application["status"] == C.APPLICATION_SUBMITTED
        assert application["pinned_contract_id"] == env["contract_id"]
        assert application["pinned_schedule_id"] == env["schedule_id"]
        assert application["submitted_on"] == C.DEFAULT_CLOCK_DATE

    def test_the_successful_submission_freezes_the_unrated_projection(
        self, client, signed_but_unapproved_contract
    ):
        """No scorecard exists, so all four milestones price at the base rates.

        "It resolves the agency's performance tier as of `submitted_on` and
        freezes it into `tier_snapshot_at_submission`."

        "`UNRATED` when the agency has no scorecard at all"

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_until_contract_reaches_active
        """
        env = signed_but_unapproved_contract

        fx.compliance_approve_contract(client, env["contract_id"])
        fx.submit_application(client, env["agency_id"], env["application_id"])

        application = fx.read_application(client, env["application_id"])
        assert application["tier_snapshot_at_submission"] == C.TIER_UNRATED
        assert_cents(
            application["projected_commission_cents"],
            355713,
            "projected_commission_cents",
        )
