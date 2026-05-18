"""Concurrency races explicitly defined by PRD §2.9.

For each race PRD defines an outcome (first-writer-wins or exactly-one-
succeeds), the test asserts at least one succeeds and at most one
succeeds (i.e. exactly one). For races where PRD names a specific
error_id for the loser, that error_id is required.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_disbursement_payload,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_contingency_fee_payload,
    create_damages_multiplier_payload,
    iso_utc,
    make_managing_partner_headers,
    patch_settlement_offer_payload,
    run_race,
    send_demand_letter_payload,
    server_now_dt,
    setup_case_with_fee,
    setup_negotiating,
    setup_ready_for_demand,
    setup_settled_with_liens,
    TEST_USERS,
    validate_error,
)


class TestSingletonRaces:

    def test_concurrent_damages_creation_one_succeeds(self, api):
        """PRD §2.9: "When two paralegals try to insert the singleton
        Damages row for the same case at the same moment, the second
        insert is rejected with ERR_DAMAGES_ALREADY_EXISTS (HTTP 409)."

        Claim: two parallel POST /damages → exactly one succeeds, the
        loser sees ERR_DAMAGES_ALREADY_EXISTS.
        """
        _, case, _ = setup_case_with_fee()
        results = run_race(
            lambda: api.create_damages(
                case["id"], create_damages_multiplier_payload(),
                TEST_USERS["paralegal_headers"],
            ),
            lambda: api.create_damages(
                case["id"], create_damages_multiplier_payload(),
                TEST_USERS["paralegal_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == (
            ApiErrorId.ERR_DAMAGES_ALREADY_EXISTS.value
        )

    def test_concurrent_fee_agreement_creation_one_succeeds(
        self, api,
    ):
        """PRD §2.9: "When two operators try to create the singleton
        ContingencyFeeAgreement row for the same case at the same
        moment, the second insert is rejected with
        ERR_FEE_AGREEMENT_ALREADY_EXISTS (HTTP 409)."

        Claim: parallel POSTs → exactly one wins; loser sees
        ERR_FEE_AGREEMENT_ALREADY_EXISTS.
        """
        from test_helpers import create_client, create_case
        client = create_client()
        case = create_case(client["id"])
        results = run_race(
            lambda: api.create_contingency_fee(
                case["id"], create_contingency_fee_payload(),
                TEST_USERS["managing_partner_headers"],
            ),
            lambda: api.create_contingency_fee(
                case["id"], create_contingency_fee_payload(),
                TEST_USERS["managing_partner_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == (
            ApiErrorId.ERR_FEE_AGREEMENT_ALREADY_EXISTS.value
        )


class TestApprovalRace:

    def test_concurrent_disbursement_approval_one_succeeds(self, api):
        """PRD §2.9: "When two ManagingPartner operators both call
        disbursement approval against the same case, exactly one
        approval is recorded — first-writer-wins on
        Case.disbursement_approved_by transitioning from null — and
        the loser sees ERR_DISBURSEMENT_ALREADY_APPROVED (HTTP 409)."

        Claim: parallel approvals → exactly one succeeds; loser sees
        ERR_DISBURSEMENT_ALREADY_APPROVED.
        """
        result = setup_settled_with_liens(case_costs_cents=0)
        case_id = result["case"]["id"]
        results = run_race(
            lambda: api.approve_disbursement(
                case_id,
                approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
                TEST_USERS["managing_partner_headers"],
            ),
            lambda: api.approve_disbursement(
                case_id,
                approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
                TEST_USERS["managing_partner_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == (
            ApiErrorId.ERR_DISBURSEMENT_ALREADY_APPROVED.value
        )


class TestOfferAcceptanceRace:

    def test_concurrent_offer_acceptance_one_succeeds(self, api):
        """PRD §2.9: "When two Attorney operators both attempt to flip
        the same PENDING settlement offer to ACCEPTED simultaneously,
        exactly one acceptance wins on a first-writer-wins basis at
        the SettlementOffer.status transition out of PENDING; the
        loser sees ERR_OFFER_NOT_PENDING (HTTP 409)."

        Claim: parallel ACCEPTED PATCHes → exactly one succeeds;
        loser sees ERR_OFFER_NOT_PENDING.
        """
        _, case, _, _, _, _, offer = setup_negotiating()
        results = run_race(
            lambda: api.patch_settlement_offer(
                case["id"], offer["id"],
                patch_settlement_offer_payload("ACCEPTED"),
                TEST_USERS["attorney_headers"],
            ),
            lambda: api.patch_settlement_offer(
                case["id"], offer["id"],
                patch_settlement_offer_payload("ACCEPTED"),
                TEST_USERS["attorney_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == (
            ApiErrorId.ERR_OFFER_NOT_PENDING.value
        )


class TestDemandLetterSendRace:

    def test_concurrent_demand_send_one_succeeds(self, api):
        """PRD §2.9: "When two attorneys both attempt to send the same
        DRAFT demand letter, exactly one send wins on a
        first-writer-wins basis at the DemandLetter.status transition
        out of DRAFT, and the loser sees ERR_DEMAND_NOT_DRAFT
        (HTTP 409)."

        Claim: parallel sends → exactly one succeeds; loser sees
        ERR_DEMAND_NOT_DRAFT.
        """
        from test_helpers import create_demand_letter
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        results = run_race(
            lambda: api.send_demand_letter(
                case["id"], letter["id"],
                TEST_USERS["attorney_headers"],
                send_demand_letter_payload(),
            ),
            lambda: api.send_demand_letter(
                case["id"], letter["id"],
                TEST_USERS["attorney_headers_alt"],
                send_demand_letter_payload(),
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == (
            ApiErrorId.ERR_DEMAND_NOT_DRAFT.value
        )
