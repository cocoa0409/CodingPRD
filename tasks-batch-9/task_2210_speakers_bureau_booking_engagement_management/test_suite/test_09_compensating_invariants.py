"""Reversals that must leave the ledgers exactly where they started.

Voiding an issued invoice has to unwind both the client's receivable and the
speaker's payable; the calendar has to give back precisely the days it took,
whichever exit a hold uses; and a speaker's refusal has to rewind the option,
the package and the inquiry so the client can choose again.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    add_option,
    add_second_engagement_for_speaker,
    cancellation_payload,
    create_hold,
    create_second_speaker,
    create_speaker,
    engagement_decline_payload,
    find_holds_for_speaker,
    get_success_data,
    read_client,
    read_engagement,
    read_inquiry,
    read_invoice,
    read_option,
    read_proposal,
    read_remittance,
    read_speaker,
    select_option_payload,
    set_clock,
    setup_contracted_engagement,
    setup_delivered_engagement_with_travel,
    setup_draft_proposal,
    validate_error,
    validate_success,
    void_payload,
)

RECORDING_CONTRACT = {
    "travel_policy_code": "POLICY_A",
    "recording_rights": "FULL_BUY_OUT",
    "recording_fee_cents": 350_000,
    "technical_rider_code": "STAGE_PLUS",
    "exclusivity_days": 90,
}
BUY_OUT_OPTION = {"travel_allowance_cents": 70_000}
BLACKOUT = {
    "hold_start_utc": "2026-11-01T00:00:00Z",
    "hold_end_utc": "2026-11-03T23:59:59Z",
    "reason": "writing retreat",
}
DECEMBER_EVENT_START = "2026-12-05T16:00:00Z"
DECEMBER_EVENT_END = "2026-12-05T18:00:00Z"


def _hold_for_engagement(api, speaker_id, engagement_id):
    matches = [
        hold
        for hold in find_holds_for_speaker(api, speaker_id)
        if hold.get("engagement_id") == engagement_id
    ]
    assert len(matches) == 1
    return matches[0]


def _blackout_hold(api, speaker_id):
    matches = [
        hold
        for hold in find_holds_for_speaker(api, speaker_id)
        if hold["kind"] == "BLACKOUT"
    ]
    assert len(matches) == 1
    return matches[0]


class TestVoidUnwindsBothLedgers:
    def test_issuance_leaves_a_receivable_and_a_payable_standing(self, api):
        """A delivered engagement with a buy-out and approved travel bills the client and owes the speaker.

        PRD: Fourth, a `Remittance` is created in `status` `PENDING`, recording `engagement_id` and the payee as `speaker_id`, with `paid_at_utc` null. For a delivery, its `gross_fee_cents` is the commissionable base `quoted_fee_cents` plus `recording_fee_cents`; its `commission_cents` is the engagement's `final_commission_cents`; its `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, which is passed straight through to the speaker and is never commissioned; and its `net_payable_cents` is `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`.
        Design: Difficulty/compensating_invariant/compensating_invoice_void_unwinds_client_balance_and_speaker_payable
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )

        assert bundle["invoice"]["status"] == "ISSUED"
        assert bundle["invoice"]["amount_due_cents"] == 1_718_304
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 1_718_304

        remittance = bundle["remittance"]
        assert remittance["status"] == "PENDING"
        assert remittance["gross_fee_cents"] == 1_625_000
        assert remittance["commission_cents"] == 406_250
        assert remittance["travel_passthrough_cents"] == 63_750
        assert remittance["net_payable_cents"] == 1_282_500
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 1_282_500

    def test_the_void_returns_both_balances_to_where_issuance_found_them(self, api):
        """Voiding the issued invoice clears the receivable, voids the remittance and writes the settlement off.

        PRD: The void drives the invoice `ISSUED → VOID`, decreases the client's `outstanding_balance_cents` by `amount_due_cents` minus `amount_paid_cents` so that the balance returns to exactly where it stood before issuance, drives the engagement's settlement dimension `INVOICED → WRITTEN_OFF`, and moves the engagement's remittance `PENDING → VOIDED` while decreasing the speaker's `pending_remittance_cents` by that remittance's `net_payable_cents`.
        Design: Difficulty/compensating_invariant/compensating_invoice_void_unwinds_client_balance_and_speaker_payable
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )

        voided = validate_success(
            api.void_invoice(bundle["invoice"]["id"], void_payload(
                void_reason="client insolvent"
            ), ADMIN_HEADERS)
        )
        assert voided["status"] == "VOID"

        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 0
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 0

        remittance = read_remittance(api, bundle["remittance"]["id"])
        assert remittance["status"] == "VOIDED"
        assert remittance["paid_at_utc"] is None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["settlement_status"] == "WRITTEN_OFF"
        assert engagement["booking_status"] == "DELIVERED"
        assert engagement["final_commission_cents"] == 406_250
        assert engagement["travel_reimbursable_cents"] == 63_750

    def test_a_second_void_is_refused_and_changes_nothing(self, api):
        """The compensation runs once: the invoice is no longer voidable and the cleared ledgers stay cleared.

        PRD: Voiding is only available while the invoice is `ISSUED`; an invoice that is already `PARTIALLY_PAID`, `PAID` or `VOID` is refused with `ERR_INVOICE_NOT_PAYABLE`.
        Design: Difficulty/compensating_invariant/compensating_invoice_void_unwinds_client_balance_and_speaker_payable
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )
        invoice_id = bundle["invoice"]["id"]
        validate_success(api.void_invoice(invoice_id, void_payload(), ADMIN_HEADERS))

        validate_error(
            api.void_invoice(invoice_id, void_payload(), ADMIN_HEADERS),
            ApiErrorId.ERR_INVOICE_NOT_PAYABLE.value,
        )

        assert read_invoice(api, invoice_id)["status"] == "VOID"
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 0
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 0
        assert read_remittance(api, bundle["remittance"]["id"])["status"] == "VOIDED"


class TestHoldLifecycleConservesHeldDays:
    def _two_bookings_and_a_blackout(self, api):
        bundle = setup_contracted_engagement(api)
        create_hold(api, bundle["speaker"], **BLACKOUT)
        return add_second_engagement_for_speaker(
            api,
            bundle,
            event_start_utc=DECEMBER_EVENT_START,
            event_end_utc=DECEMBER_EVENT_END,
            valid_until_utc="2026-11-15T00:00:00Z",
            deliver=False,
        )

    def test_three_live_holds_sum_into_the_speakers_held_days(self, api):
        """Two buffered bookings and one manual blackout each contribute their own span to the running total.

        PRD: Either way the server computes `day_span` as the number of distinct UTC calendar dates the closed interval from `hold_start_utc` to `hold_end_utc` touches, and adds that `day_span` to the speaker's `held_days_count`.
        Design: Difficulty/compensating_invariant/compensating_hold_lifecycle_conserves_speaker_held_days_count
        """
        bundle = self._two_bookings_and_a_blackout(api)
        speaker_id = bundle["speaker"]["id"]

        first = _hold_for_engagement(api, speaker_id, bundle["engagement"]["id"])
        second = _hold_for_engagement(api, speaker_id, bundle["engagement_2"]["id"])
        blackout = _blackout_hold(api, speaker_id)

        assert first["day_span"] == 3
        assert second["day_span"] == 3
        assert blackout["day_span"] == 3
        assert {first["status"], second["status"], blackout["status"]} == {"ACTIVE"}
        assert read_speaker(api, speaker_id)["held_days_count"] == 9

    def test_cancelling_releases_exactly_that_bookings_days(self, api):
        """The cancelled booking's hold is released and gives back its three days, leaving the blackout alone.

        PRD: Cancellation releases it, moving that hold `ACTIVE → RELEASED`.
        Design: Difficulty/compensating_invariant/compensating_hold_lifecycle_conserves_speaker_held_days_count
        """
        bundle = self._two_bookings_and_a_blackout(api)
        speaker_id = bundle["speaker"]["id"]

        set_clock(api, "2026-09-01T00:00:00Z")
        validate_success(
            api.cancel_engagement(
                bundle["engagement"]["id"],
                cancellation_payload("the October conference was scrapped"),
                bundle["client_headers"],
            )
        )

        released = _hold_for_engagement(api, speaker_id, bundle["engagement"]["id"])
        assert released["status"] == "RELEASED"
        assert read_speaker(api, speaker_id)["held_days_count"] == 6
        assert _blackout_hold(api, speaker_id)["status"] == "ACTIVE"
        assert read_engagement(api, bundle["engagement"]["id"])[
            "settlement_status"
        ] == "WAIVED"

    def test_delivering_consumes_rather_than_releases_the_second_hold(self, api):
        """Delivery retires the second hold through the consumed exit, and only the blackout still occupies the calendar.

        PRD: Fifth, the engagement's own calendar hold moves `ACTIVE → CONSUMED` and the speaker's `held_days_count` drops by that hold's `day_span`.
        Design: Difficulty/compensating_invariant/compensating_hold_lifecycle_conserves_speaker_held_days_count
        """
        bundle = self._two_bookings_and_a_blackout(api)
        speaker_id = bundle["speaker"]["id"]
        set_clock(api, "2026-09-01T00:00:00Z")
        validate_success(
            api.cancel_engagement(
                bundle["engagement"]["id"],
                cancellation_payload("the October conference was scrapped"),
                bundle["client_headers"],
            )
        )

        set_clock(api, "2026-12-05T20:00:00Z")
        validate_success(
            api.deliver_engagement(bundle["engagement_2"]["id"], AGENT_HEADERS)
        )

        consumed = _hold_for_engagement(api, speaker_id, bundle["engagement_2"]["id"])
        assert consumed["status"] == "CONSUMED"
        assert read_speaker(api, speaker_id)["held_days_count"] == 3

        still_active = [
            hold
            for hold in find_holds_for_speaker(api, speaker_id)
            if hold["status"] == "ACTIVE"
        ]
        assert len(still_active) == 1
        assert still_active[0]["kind"] == "BLACKOUT"

    def test_the_blackout_span_is_never_touched_by_either_exit(self, api):
        """Neither the cancellation nor the delivery moves the manually entered blackout.

        PRD: Manual blackout holds are never touched by either event.
        Design: Difficulty/compensating_invariant/compensating_hold_lifecycle_conserves_speaker_held_days_count
        """
        bundle = self._two_bookings_and_a_blackout(api)
        speaker_id = bundle["speaker"]["id"]
        before = _blackout_hold(api, speaker_id)

        set_clock(api, "2026-09-01T00:00:00Z")
        validate_success(
            api.cancel_engagement(
                bundle["engagement"]["id"],
                cancellation_payload("the October conference was scrapped"),
                bundle["client_headers"],
            )
        )
        set_clock(api, "2026-12-05T20:00:00Z")
        validate_success(
            api.deliver_engagement(bundle["engagement_2"]["id"], AGENT_HEADERS)
        )

        after = _blackout_hold(api, speaker_id)
        assert after["status"] == "ACTIVE"
        assert after["day_span"] == before["day_span"]
        assert after["hold_start_utc"] == before["hold_start_utc"]
        assert after["hold_end_utc"] == before["hold_end_utc"]


class TestSpeakerDeclineRewindsTheChain:
    def _three_option_package(self, api):
        bundle = setup_draft_proposal(api)
        second_speaker = create_second_speaker(api)
        third_speaker = create_speaker(
            api,
            full_name="Noor Haddad",
            topics=["AI_STRATEGY", "FUTURE_OF_WORK"],
            travel_class="ECONOMY",
        )
        bundle["second_speaker"] = second_speaker
        bundle["third_speaker"] = third_speaker
        bundle["option_2"] = add_option(
            api,
            bundle["proposal"],
            second_speaker,
            quoted_fee_cents=1_150_000,
            rank_no=2,
        )
        bundle["option_3"] = add_option(
            api,
            bundle["proposal"],
            third_speaker,
            quoted_fee_cents=1_050_000,
            rank_no=3,
        )
        get_success_data(api.present_proposal(bundle["proposal"]["id"], AGENT_HEADERS))
        engagement = get_success_data(
            api.select_proposal_option(
                bundle["proposal"]["id"],
                select_option_payload(bundle["option"]["id"]),
                bundle["client_headers"],
            )
        )
        bundle["engagement"] = read_engagement(api, engagement["id"])
        return bundle

    def _decline(self, api, bundle):
        return validate_success(
            api.decline_engagement(
                bundle["engagement"]["id"],
                engagement_decline_payload(
                    decline_reason="double-booked personally"
                ),
                bundle["speaker_headers"],
            )
        )

    def test_the_refusal_puts_the_rejected_siblings_back_on_the_table(self, api):
        """Declining rejects the chosen option, revives both swept siblings and walks the package and inquiry back one step.

        PRD: The previously selected option moves `SELECTED → REJECTED`; every sibling option of that same package that had been swept to `REJECTED` at selection time returns to `OFFERED`; the package itself moves `ACCEPTED → PRESENTED`, which is the second cycle on that entity and is permitted only while the logical clock remains strictly before `valid_until_utc`; and the inquiry walks back `WON → PROPOSED`.
        Design: Difficulty/compensating_invariant/compensating_speaker_decline_rewinds_option_proposal_and_inquiry_states
        """
        bundle = self._three_option_package(api)
        declined = self._decline(api, bundle)

        assert declined["booking_status"] == "DECLINED_BY_SPEAKER"
        assert read_option(api, bundle["option"]["id"])["status"] == "REJECTED"
        assert read_option(api, bundle["option_2"]["id"])["status"] == "OFFERED"
        assert read_option(api, bundle["option_3"]["id"])["status"] == "OFFERED"
        assert read_proposal(api, bundle["proposal"]["id"])["status"] == "PRESENTED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "PROPOSED"

    def test_no_calendar_was_ever_touched_by_the_offer_or_the_refusal(self, api):
        """Because a hold is only minted on confirmation, all three quoted speakers still show an empty calendar.

        PRD: No hold exists yet at this point, because a hold is only minted on confirmation.
        Design: Difficulty/compensating_invariant/compensating_speaker_decline_rewinds_option_proposal_and_inquiry_states
        """
        bundle = self._three_option_package(api)
        self._decline(api, bundle)

        for key in ("speaker", "second_speaker", "third_speaker"):
            speaker_id = bundle[key]["id"]
            assert read_speaker(api, speaker_id)["held_days_count"] == 0
            assert find_holds_for_speaker(api, speaker_id) == []

    def test_the_refusal_is_terminal_so_it_cannot_be_repeated(self, api):
        """A second decline finds the engagement in a state the transition is not declared from.

        PRD: The codes are `ERR_INQUIRY_STATE_INVALID`, `ERR_PROPOSAL_STATE_INVALID`, `ERR_ENGAGEMENT_STATE_INVALID`, `ERR_CONTRACT_STATE_INVALID`, `ERR_TRAVEL_EXPENSE_STATE_INVALID`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_REMITTANCE_NOT_APPROVED`, `ERR_CLAIM_NOT_OPEN` and `ERR_GRANT_NOT_ACTIVE`, all HTTP 409.
        Design: Difficulty/compensating_invariant/compensating_speaker_decline_rewinds_option_proposal_and_inquiry_states
        """
        bundle = self._three_option_package(api)
        self._decline(api, bundle)

        validate_error(
            api.decline_engagement(
                bundle["engagement"]["id"],
                engagement_decline_payload(),
                bundle["speaker_headers"],
            ),
            ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID.value,
        )
        assert read_engagement(api, bundle["engagement"]["id"])[
            "booking_status"
        ] == "DECLINED_BY_SPEAKER"

    def test_the_client_can_choose_a_revived_sibling_instead(self, api):
        """Re-selecting the second-ranked option mints a fresh engagement at that option's own fee.

        PRD: On success the named option moves `OFFERED → SELECTED` while every sibling in `OFFERED` moves `OFFERED → REJECTED`, the package moves `PRESENTED → ACCEPTED`, the inquiry moves `PROPOSED → WON`, and a new `Engagement` is minted.
        Design: Difficulty/compensating_invariant/compensating_speaker_decline_rewinds_option_proposal_and_inquiry_states
        """
        bundle = self._three_option_package(api)
        self._decline(api, bundle)

        replacement = get_success_data(
            api.select_proposal_option(
                bundle["proposal"]["id"],
                select_option_payload(bundle["option_2"]["id"]),
                bundle["client_headers"],
            )
        )
        engagement = read_engagement(api, replacement["id"])

        assert engagement["id"] != bundle["engagement"]["id"]
        assert engagement["booking_status"] == "OFFERED"
        assert engagement["quoted_fee_cents"] == 1_150_000
        assert engagement["speaker_id"] == bundle["second_speaker"]["id"]
        assert read_option(api, bundle["option_2"]["id"])["status"] == "SELECTED"
        assert read_option(api, bundle["option_3"]["id"])["status"] == "REJECTED"
        assert read_proposal(api, bundle["proposal"]["id"])["status"] == "ACCEPTED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "WON"
