"""Concurrency tokens and the recording-rights feature flag.

The two optimistic-concurrency guards protect different resources with
different codes, and both must leave the target untouched when they fire.  The
recording-rights flag then shows how one contract field propagates all the way
through the invoice surcharge, the final commission and the speaker's payout.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    add_second_engagement_for_speaker,
    commission_adjustment_payload,
    create_client,
    create_inquiry,
    create_speaker,
    proposal_payload,
    qualify_inquiry,
    read_engagement,
    read_inquiry,
    set_clock,
    setup_contracted_engagement,
    setup_delivered_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_EVENT_START_UTC = "2026-11-20T16:00:00Z"
SECOND_EVENT_END_UTC = "2026-11-20T18:00:00Z"
SECOND_VALID_UNTIL_UTC = "2026-11-10T00:00:00Z"
SECOND_SETUP_CLOCK_UTC = "2026-10-16T00:00:00Z"
RECORDING_FEE_CENTS = 350_000
BUY_OUT_CONTRACT = {
    "recording_rights": "FULL_BUY_OUT",
    "recording_fee_cents": RECORDING_FEE_CENTS,
    "technical_rider_code": "STAGE_PLUS",
}


class TestStaleInquiryVersionBlocksAProposalRound:
    def _qualified_inquiry_with_both_versions(self, api) -> dict:
        set_clock(api)
        create_speaker(api)
        client_row = create_client(api)
        created = create_inquiry(api, client_row)
        qualified = qualify_inquiry(api, created["id"])
        return {"created": created, "qualified": qualified}

    def test_the_pre_qualification_version_is_refused(self, api):
        """Qualification bumped the inquiry, so the version read before it is already stale.

        PRD: If that value does not equal the inquiry's current `version`, the request is rejected with `ERR_STALE_INQUIRY_VERSION` (HTTP 412).
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_inquiry_version_blocks_proposal_creation
        """
        bundle = self._qualified_inquiry_with_both_versions(api)
        stale_version = bundle["created"]["version"]
        current_version = bundle["qualified"]["version"]
        assert current_version == stale_version + 1

        validate_error(
            api.create_proposal(
                bundle["created"]["id"],
                proposal_payload(stale_version),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_STALE_INQUIRY_VERSION.value,
            expected_status=412,
        )

        after = read_inquiry(api, bundle["created"]["id"])
        assert after["status"] == "QUALIFIED"
        assert after["version"] == current_version
        _rows, meta = validate_paginated(
            api.list_proposals(
                AGENT_HEADERS, params={"inquiry_id": bundle["created"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_retry_with_the_current_version_opens_the_round(self, api):
        """The refusal changed nothing, so re-reading the inquiry is enough to make the round work.

        PRD: On success the inquiry's `version` advances by one.
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_inquiry_version_blocks_proposal_creation
        """
        bundle = self._qualified_inquiry_with_both_versions(api)
        current_version = bundle["qualified"]["version"]

        validate_error(
            api.create_proposal(
                bundle["created"]["id"],
                proposal_payload(bundle["created"]["version"]),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_STALE_INQUIRY_VERSION.value,
        )

        proposal = validate_success(
            api.create_proposal(
                bundle["created"]["id"],
                proposal_payload(current_version),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert proposal["status"] == "DRAFT"
        assert proposal["options_count"] == 0
        assert (
            read_inquiry(api, bundle["created"]["id"])["version"] == current_version + 1
        )


class TestStaleEngagementVersionBlocksACommissionAdjustment:
    def test_a_one_behind_version_is_refused_without_re_pricing_anything(self, api):
        """A failed rate rewrite must leave the snapshot, the counter and the version exactly as they were.

        PRD: If that value does not equal the engagement's current `version`, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_engagement_version_blocks_commission_adjustment
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])
        assert before["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)

        validate_error(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.18, before["version"] - 1),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
            expected_status=412,
        )

        after = read_engagement(api, before["id"])
        assert after["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert after["commission_adjustment_count"] == 0
        assert after["version"] == before["version"]

    def test_the_retry_with_the_current_version_re_prices_the_engagement(self, api):
        """The token from a fresh read is accepted, and the new rate rewrites the provisional figure.

        PRD: An accepted adjustment overwrites `commission_pct_snapshot` with `new_commission_pct`, rewrites `provisional_commission_cents` using the provisional formula at the new rate — `quoted_fee_cents` multiplied by the new snapshot, rounded half up — and increments `commission_adjustment_count` by one.
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_engagement_version_blocks_commission_adjustment
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])

        validate_error(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.18, before["version"] - 1),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
        )

        adjusted = validate_success(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.18, before["version"]),
                ADMIN_HEADERS,
            )
        )
        assert adjusted["commission_pct_snapshot"] == pytest.approx(0.18, abs=0.001)
        assert adjusted["provisional_commission_cents"] == 229_500
        assert adjusted["commission_adjustment_count"] == 1
        assert adjusted["version"] == before["version"] + 1


class TestRecordingRightsFlag:
    def _both_engagements(self, api) -> dict:
        bundle = setup_delivered_engagement(api)
        return add_second_engagement_for_speaker(
            api,
            bundle,
            event_start_utc=SECOND_EVENT_START_UTC,
            event_end_utc=SECOND_EVENT_END_UTC,
            valid_until_utc=SECOND_VALID_UNTIL_UTC,
            contract_overrides=BUY_OUT_CONTRACT,
            setup_clock_utc=SECOND_SETUP_CLOCK_UTC,
        )

    def test_with_the_flag_off_the_invoice_carries_no_recording_line(self, api):
        """The engagement with `NONE` bills the fee alone, and its surcharge comes off that single line.

        PRD: Its three lines come straight off the engagement: `fee_line_cents` is `quoted_fee_cents`, `recording_line_cents` is `recording_fee_cents`, and `travel_line_cents` is the engagement's `travel_reimbursable_cents` as it stands at issuance.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)

        assert bundle["engagement"]["recording_fee_cents"] == 0
        invoice = bundle["invoice"]
        assert invoice["fee_line_cents"] == 1_275_000
        assert invoice["recording_line_cents"] == 0
        assert invoice["travel_line_cents"] == 0
        assert invoice["surcharge_cents"] == 22_313
        assert invoice["amount_due_cents"] == 1_297_313

    def test_with_the_flag_off_the_two_commission_variants_agree(self, api):
        """With no recording fee the commissionable base is the fee, so nothing diverges.

        PRD: First, `final_commission_cents` is written as the final variant of the commission calculation: `quoted_fee_cents` **plus** `recording_fee_cents`, that sum multiplied by `commission_pct_snapshot`, and that single product rounded half up to a whole number of cents.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)
        engagement = read_engagement(api, bundle["engagement"]["id"])

        assert engagement["provisional_commission_cents"] == 318_750
        assert engagement["final_commission_cents"] == 318_750
        assert bundle["remittance"]["net_payable_cents"] == 956_250

    def test_with_the_flag_on_the_recording_line_is_surcharged_on_its_own(self, api):
        """The buy-out adds a second billable line, and the surcharge is rounded per line before being summed.

        PRD: The processing surcharge is then computed at a rate of 1.75 percent — that is, 0.0175 — and the **order of operations is normative**: the server multiplies each of the three lines by the surcharge rate separately, rounds each of those three products half up to a whole number of cents, and only then adds the three rounded parts together to obtain `surcharge_cents`.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)

        assert bundle["contract_2"]["recording_rights"] == "FULL_BUY_OUT"
        assert bundle["engagement_2"]["recording_fee_cents"] == RECORDING_FEE_CENTS

        invoice = bundle["invoice_2"]
        assert invoice["fee_line_cents"] == 1_275_000
        assert invoice["recording_line_cents"] == RECORDING_FEE_CENTS
        assert invoice["surcharge_cents"] == 22_313 + 6_125
        assert invoice["amount_due_cents"] == 1_653_438

    def test_the_flag_widens_the_commission_base_so_the_final_variant_diverges(
        self, api
    ):
        """Same fee and same pinned rate, but the buy-out makes the final commission larger than the provisional one.

        PRD: Same engagement, same pinned rate, but a strictly larger result than the provisional figure whenever `recording_fee_cents` is positive; the difference — `recording_fee_cents` multiplied by `commission_pct_snapshot`, rounded half up — is exactly the extra amount the remittance withholds beyond the provisional figure.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)
        engagement = read_engagement(api, bundle["engagement_2"]["id"])

        assert engagement["provisional_commission_cents"] == 318_750
        assert engagement["final_commission_cents"] == 406_250
        assert (
            engagement["final_commission_cents"]
            - engagement["provisional_commission_cents"]
            == 87_500
        )

    def test_the_wider_base_flows_through_to_the_speakers_payout(self, api):
        """The remittance takes the buy-out into the gross and withholds the larger commission.

        PRD: For a delivery, its `gross_fee_cents` is the commissionable base `quoted_fee_cents` plus `recording_fee_cents`; its `commission_cents` is the engagement's `final_commission_cents`; its `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, which is passed straight through to the speaker and is never commissioned; and its `net_payable_cents` is `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)

        remittance = bundle["remittance_2"]
        assert remittance["gross_fee_cents"] == 1_625_000
        assert remittance["commission_cents"] == 406_250
        assert remittance["travel_passthrough_cents"] == 0
        assert remittance["net_payable_cents"] == 1_218_750
        assert bundle["remittance"]["net_payable_cents"] == 956_250

    def test_two_deliveries_alone_do_not_promote_the_speaker(self, api):
        """The silver gate needs a rolling score as well as a delivery count, and no feedback exists yet.

        PRD: Both conditions of a tier must hold and the highest satisfied tier wins: `GOLD` requires `engagements_delivered_count` of at least 4 **and** a `rolling_score` of at least 4.50; `SILVER` requires `engagements_delivered_count` of at least 2 **and** a `rolling_score` of at least 4.00; otherwise the speaker is `BRONZE`, and a speaker whose `rolling_score` is still null is always `BRONZE`.
        Design: Corner/cross_cutting_layers/conditional_flag_recording_rights_toggles_the_recording_line_and_the_final_commission
        """
        bundle = self._both_engagements(api)

        speaker = bundle["speaker"]
        assert speaker["engagements_delivered_count"] == 2
        assert speaker["rolling_score"] is None
        assert speaker["roster_tier"] == "BRONZE"
        assert speaker["default_commission_pct"] == pytest.approx(0.25, abs=0.001)
        assert speaker["lifetime_gross_fees_cents"] == 1_275_000 + 1_625_000
