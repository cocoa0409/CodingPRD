"""Transitions gated by the state of a different entity than the one being moved."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    OwnerSpec,
    add_beneficial_owner,
    api_client,
    appeal_payload,
    approve_termination,
    create_draft_application,
    execute_termination,
    make_merchant_user_headers,
    make_underwriting_officer_headers,
    onboard_standard_merchant,
    propose_termination,
    read_application,
    read_merchant,
    read_termination_decision,
    record_verification,
    screen_owner,
    set_clock,
    submit_application,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_TREASURY_01,
)


def _application_with_one_unscreened_owner(api):
    """Owner A cleared at 50.00 percent, owner B untouched at 30.00 percent."""
    set_clock(api, "2026-07-01T00:00:00Z")
    application = create_draft_application(
        api, legal_business_name="Willowbrook Home LLC", mcc_code="5999"
    )
    application_id = application["id"]
    owner_a = add_beneficial_owner(
        api, application_id, full_name="Cleo Marsh", ownership_pct=50.00
    )
    owner_b = add_beneficial_owner(
        api, application_id, full_name="Tomas Reed", ownership_pct=30.00
    )
    submit_application(api, application_id)
    record_verification(api, application_id)
    screen_owner(api, owner_a["id"])
    return application_id, owner_b["id"]


class TestOwnerScreeningGatesTheApplication:
    """The application's own fields are clean; a sibling owner row is what blocks it."""

    def test_an_owner_left_pending_blocks_the_advance(self):
        """Coverage and verification are fine, yet the unscreened owner refuses the transition.

        PRD 3.3: "Third, no beneficial owner may still have `status` `PENDING`, because an
        unscreened owner is an unknown, not a clean one; otherwise
        `ERR_OWNER_SCREENING_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/advance_to_underwriting_blocked_by_pending_owner_screening
        """
        api = api_client
        application_id, _ = _application_with_one_unscreened_owner(api)

        response = api.advance_to_underwriting(
            application_id, make_underwriting_officer_headers()
        )

        validate_error(response, "ERR_OWNER_SCREENING_INCOMPLETE", 409)
        assert read_application(api, application_id)["state"] == "IN_VERIFICATION"

    def test_screening_that_owner_unblocks_the_identical_request(self):
        """Only the owner row changes, and the same advance call then succeeds.

        PRD 3.3: "The owner's `status` is then derived in this pinned order: `SANCTIONS_HIT` when
        `sanctions_hit` is true; otherwise `ID_UNVERIFIED` when `id_verified` is false; otherwise
        `FLAGGED_PEP` when `pep_flag` is true; otherwise `CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/advance_to_underwriting_blocked_by_pending_owner_screening
        """
        api = api_client
        application_id, owner_b_id = _application_with_one_unscreened_owner(api)

        api.advance_to_underwriting(application_id, make_underwriting_officer_headers())

        screened = screen_owner(api, owner_b_id)
        assert screened["status"] == "CLEARED"

        response = api.advance_to_underwriting(
            application_id, make_underwriting_officer_headers()
        )
        advanced = validate_success(response, 200)

        assert advanced["state"] == "UNDERWRITING"
        assert float(advanced["owner_ownership_pct_total"]) == 80.00


def _merchant_with_an_approved_but_unexecuted_termination(api):
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-01T00:00:00Z",
        legal_business_name="Cobblestone Wares LLC",
        mcc_code="5999",
        owners=[OwnerSpec(full_name="Rita Alvarez")],
    )
    decision = propose_termination(
        api,
        onboarded.merchant_id,
        "PROHIBITED_ACTIVITY",
        USER_ANALYST_01,
        match_listing_flag=False,
    )
    approved = approve_termination(api, decision["id"], USER_COMMITTEE_01)
    assert approved["state"] == "APPROVED"
    set_clock(api, "2026-07-05T00:00:00Z")
    return onboarded, decision


class TestAnAppealNeedsAnExecutedDecision:
    """The same appeal body is refused against an APPROVED decision and taken once executed."""

    def _file_appeal(self, api, onboarded, decision):
        return api.create_appeal(
            appeal_payload(
                onboarded.merchant_id,
                decision["id"],
                "The flagged activity was a licensed reseller arrangement.",
            ),
            make_merchant_user_headers(onboarded.merchant_id),
        )

    def test_filing_against_a_merely_approved_decision_is_refused(self):
        """Approval is not the end of the sequence, so there is nothing to appeal yet.

        PRD 3.12: "The named decision must be in state `EXECUTED` and must belong to the same
        merchant as the appeal, or the filing is rejected with `ERR_APPEAL_DECISION_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_requires_executed_termination_decision
        """
        api = api_client
        onboarded, decision = _merchant_with_an_approved_but_unexecuted_termination(api)

        response = self._file_appeal(api, onboarded, decision)

        validate_error(response, "ERR_APPEAL_DECISION_NOT_EXECUTED", 409)
        assert read_termination_decision(api, decision["id"])["state"] == "APPROVED"
        assert read_merchant(api, onboarded.merchant_id)["account_state"] == "ACTIVE"

    def test_executing_the_decision_makes_the_same_body_acceptable(self):
        """Once the decision is EXECUTED the appeal is created with its creation defaults.

        PRD 3.12: "The appeal is created in state `SUBMITTED` with `filed_on_date` set to the
        logical clock date, `response_round_count` 0, `outstanding_info_items` empty, and
        `reviewer_user_id`, `reinstatement_reserve_pct_bps` and `decided_at` null."

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_requires_executed_termination_decision
        """
        api = api_client
        onboarded, decision = _merchant_with_an_approved_but_unexecuted_termination(api)

        self._file_appeal(api, onboarded, decision)

        executed = execute_termination(api, decision["id"], USER_TREASURY_01)
        assert executed["state"] == "EXECUTED"
        assert read_merchant(api, onboarded.merchant_id)["account_state"] == "TERMINATED"

        response = self._file_appeal(api, onboarded, decision)
        appeal = validate_success(response, 201)

        assert appeal["state"] == "SUBMITTED"
        assert appeal["filed_on_date"] == "2026-07-05"
        assert appeal["response_round_count"] == 0
        assert appeal["outstanding_info_items"] == []
        assert appeal["reviewer_user_id"] is None
        assert appeal["decided_at"] is None
        assert appeal["reinstatement_reserve_pct_bps"] is None
