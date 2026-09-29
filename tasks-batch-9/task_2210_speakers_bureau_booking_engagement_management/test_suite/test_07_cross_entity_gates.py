"""Operations gated on the posture of a neighbouring row.

A paused roster entry blocks one signature leg but not the other; a missing tax
form blocks a payout that is otherwise fully approved; and a travel receipt
cannot be paid until the agreement on the engagement above it has executed.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    CLIENT_SIGNATURE_NAME,
    SPEAKER_SIGNATURE_NAME,
    assert_booking_and_settlement,
    read_contract,
    read_engagement,
    read_remittance,
    read_speaker,
    read_travel_expense,
    remittance_payout_payload,
    setup_drafted_contract,
    setup_paid_engagement,
    setup_sent_contract,
    signature_payload,
    travel_expense_payload,
    validate_error,
    validate_success,
)

POLICY_A_TRAVEL = {"travel_policy_code": "POLICY_A"}
ALLOWANCE_OPTION = {"travel_allowance_cents": 70_000}


class TestProbationBlocksOnlyTheSpeakerLeg:
    def test_a_paused_speaker_cannot_sign_but_the_client_leg_still_lands(self, api):
        """Pausing the roster entry stops the speaker signature while leaving the client signature untouched.

        PRD: The **speaker leg** is available to the acting `Speaker` while `speaker_signed_at_utc` is still null, is gated on the speaker's `roster_status` being `ACTIVE` — a paused speaker is refused with `ERR_SPEAKER_NOT_ACTIVE` — and stamps `speaker_signed_at_utc` with the logical clock.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_speaker_probation_blocks_only_the_speaker_signature_leg
        """
        bundle = setup_sent_contract(api)
        validate_success(
            api.update_speaker(
                bundle["speaker"]["id"], {"roster_status": "PAUSED"}, ADMIN_HEADERS
            )
        )

        validate_error(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            ),
            ApiErrorId.ERR_SPEAKER_NOT_ACTIVE.value,
        )
        assert read_contract(api, bundle["contract"]["id"])[
            "speaker_signed_at_utc"
        ] is None

        signed = validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(CLIENT_SIGNATURE_NAME),
                bundle["client_headers"],
            )
        )
        assert signed["status"] == "PARTIALLY_SIGNED"
        assert signed["client_signed_at_utc"] is not None

    def test_restoring_the_roster_entry_lets_the_join_complete(self, api):
        """Once the roster posture is restored the speaker leg lands and the agreement executes.

        PRD: A `BureauAdmin` may revise `roster_status`, `tax_form_status`, `fee_floor_cents`, `fee_ceiling_cents`, `travel_class` and `travel_buffer_days` on an existing speaker; each such edit increments the speaker's `version` by one.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_speaker_probation_blocks_only_the_speaker_signature_leg
        """
        bundle = setup_sent_contract(api)
        speaker_id = bundle["speaker"]["id"]
        validate_success(
            api.update_speaker(speaker_id, {"roster_status": "PAUSED"}, ADMIN_HEADERS)
        )
        validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(CLIENT_SIGNATURE_NAME),
                bundle["client_headers"],
            )
        )

        restored = validate_success(
            api.update_speaker(speaker_id, {"roster_status": "ACTIVE"}, ADMIN_HEADERS)
        )
        assert restored["roster_status"] == "ACTIVE"

        executed = validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at_utc"] is not None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONTRACTED"
        assert engagement["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert engagement["provisional_commission_cents"] == 318_750

    def test_the_client_leg_is_gated_on_credit_rather_than_roster_posture(self, api):
        """The two legs carry different guards, so a paused speaker does not affect the client's own gate.

        PRD: The **client leg** is available to the acting `Client` while `client_signed_at_utc` is still null, is gated on the client's `credit_status` not being `HOLD` — a held client is refused with `ERR_CLIENT_CREDIT_HOLD` — and stamps `client_signed_at_utc` with the logical clock.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_speaker_probation_blocks_only_the_speaker_signature_leg
        """
        bundle = setup_sent_contract(api)
        validate_success(
            api.update_speaker(
                bundle["speaker"]["id"], {"roster_status": "PAUSED"}, ADMIN_HEADERS
            )
        )

        signed = validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(CLIENT_SIGNATURE_NAME),
                bundle["client_headers"],
            )
        )
        assert signed["status"] == "PARTIALLY_SIGNED"
        assert signed["executed_at_utc"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "booking_status"
        ] == "CONFIRMED"


class TestTaxFormGatesTheApprovedPayout:
    def test_an_approved_remittance_will_not_pay_out_without_a_tax_form(self, api):
        """A fully collected engagement still cannot pay the speaker while the tax form is missing.

        PRD: A `BureauAdmin` pays out a remittance whose `status` is `APPROVED`, supplying an optional `payment_reference`; a remittance in any other status is refused with `ERR_REMITTANCE_NOT_APPROVED`, and a payout attempted while the speaker's `tax_form_status` is `MISSING` is refused with `ERR_SPEAKER_TAX_FORM_MISSING`.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_missing_tax_form_blocks_approved_remittance_payout
        """
        bundle = setup_paid_engagement(
            api, speaker_overrides={"tax_form_status": "MISSING"}
        )
        assert bundle["invoice"]["amount_due_cents"] == 1_297_313
        remittance = bundle["remittance"]
        assert remittance["status"] == "APPROVED"
        assert remittance["net_payable_cents"] == 956_250

        validate_error(
            api.pay_remittance(
                remittance["id"], remittance_payout_payload("WIRE-1"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_SPEAKER_TAX_FORM_MISSING.value,
        )

        after = read_remittance(api, remittance["id"])
        assert after["status"] == "APPROVED"
        assert after["paid_at_utc"] is None
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 956_250

    def test_filing_the_tax_form_releases_the_identical_payout(self, api):
        """With the form on file the same payout lands, stamps the payment instant and clears the payable.

        PRD: The payout drives the remittance `APPROVED → PAID`, stamps `paid_at_utc` with the logical clock, decreases the speaker's `pending_remittance_cents` by `net_payable_cents`, drives the engagement's settlement dimension `COLLECTED → REMITTED`, and moves every travel expense of that engagement sitting in `APPROVED` to `REIMBURSED`.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_missing_tax_form_blocks_approved_remittance_payout
        """
        bundle = setup_paid_engagement(
            api, speaker_overrides={"tax_form_status": "MISSING"}
        )
        remittance_id = bundle["remittance"]["id"]
        validate_error(
            api.pay_remittance(
                remittance_id, remittance_payout_payload("WIRE-1"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_SPEAKER_TAX_FORM_MISSING.value,
        )

        validate_success(
            api.update_speaker(
                bundle["speaker"]["id"], {"tax_form_status": "ON_FILE"}, ADMIN_HEADERS
            )
        )
        paid = validate_success(
            api.pay_remittance(
                remittance_id, remittance_payout_payload("WIRE-2"), ADMIN_HEADERS
            )
        )

        assert paid["status"] == "PAID"
        assert paid["paid_at_utc"] is not None
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 0
        assert_booking_and_settlement(
            read_engagement(api, bundle["engagement"]["id"]), "DELIVERED", "REMITTED"
        )

    def test_the_surcharge_is_the_part_of_the_collection_never_remitted(self, api):
        """What the client paid splits exactly into the speaker's net, the withheld commission and the bureau's surcharge.

        PRD: The surcharge is bureau revenue and is never remitted to the speaker.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_missing_tax_form_blocks_approved_remittance_payout
        """
        bundle = setup_paid_engagement(
            api, speaker_overrides={"tax_form_status": "MISSING"}
        )
        invoice = bundle["invoice"]
        remittance = bundle["remittance"]

        assert invoice["surcharge_cents"] == 22_313
        assert remittance["commission_cents"] == 318_750
        assert (
            remittance["net_payable_cents"]
            + remittance["commission_cents"]
            + invoice["surcharge_cents"]
            == invoice["amount_due_cents"]
        )
        assert 956_250 + 318_750 + 22_313 == 1_297_313


class TestTravelApprovalNeedsAnExecutedAgreement:
    def test_a_receipt_may_be_filed_before_the_agreement_is_executed(self, api):
        """The receipt is accepted against a merely confirmed booking and waits in submitted with nothing computed.

        PRD: Travel receipts may be filed by the acting `Speaker` or by the owning `BookingAgent` against an engagement whose `booking_status` is `CONFIRMED` or `CONTRACTED` — the receipt may arrive as soon as the booking is confirmed, even though the rule for paying it lives on the agreement.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_travel_approval_requires_executed_contract
        """
        bundle = setup_drafted_contract(
            api,
            contract_overrides=POLICY_A_TRAVEL,
            option_overrides=ALLOWANCE_OPTION,
        )
        assert bundle["contract"]["status"] == "DRAFT"

        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )
        assert expense["status"] == "SUBMITTED"
        assert expense["reimbursable_cents"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 0

    def test_approval_is_refused_while_the_agreement_is_still_a_draft(self, api):
        """The approval is rejected on the agreement's state and leaves the receipt and the engagement total untouched.

        PRD: Approval is the same actor on the same source state but demands three further conditions: the engagement's `booking_status` must be `CONTRACTED`, the engagement's agreement must actually be `EXECUTED` — otherwise `ERR_CONTRACT_NOT_EXECUTED` — and the engagement's `settlement_status` must still be `UNBILLED`, since once billing has begun the travel line has already been struck.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_travel_approval_requires_executed_contract
        """
        bundle = setup_drafted_contract(
            api,
            contract_overrides=POLICY_A_TRAVEL,
            option_overrides=ALLOWANCE_OPTION,
        )
        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )

        validate_error(
            api.approve_travel_expense(expense["id"], AGENT_HEADERS),
            ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value,
        )

        after = read_travel_expense(api, expense["id"])
        assert after["status"] == "SUBMITTED"
        assert after["reimbursable_cents"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 0

    def test_executing_the_agreement_lets_the_identical_approval_through(self, api):
        """Once both signatures are in, the same approval computes the reimbursable amount under the schedule policy.

        PRD: Approval drives `SUBMITTED → APPROVED`, writes `reimbursable_cents`, and increases the engagement's `travel_reimbursable_cents` by that amount.
        Design: Difficulty/cross_entity_state_dependency/cross_entity_travel_approval_requires_executed_contract
        """
        bundle = setup_drafted_contract(
            api,
            contract_overrides=POLICY_A_TRAVEL,
            option_overrides=ALLOWANCE_OPTION,
        )
        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )
        validate_error(
            api.approve_travel_expense(expense["id"], AGENT_HEADERS),
            ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value,
        )

        validate_success(api.send_contract(bundle["contract"]["id"], AGENT_HEADERS))
        validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            )
        )
        validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(CLIENT_SIGNATURE_NAME),
                bundle["client_headers"],
            )
        )

        approved = validate_success(
            api.approve_travel_expense(expense["id"], AGENT_HEADERS)
        )
        assert approved["status"] == "APPROVED"
        assert approved["reimbursable_cents"] == 63_750
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 63_750
