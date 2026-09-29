"""Declared transitions, terminal states and the cascades they drag along.

Each entity in the pipeline advances only along the edges the contract declares,
and several of those edges reach sideways: presenting touches the inquiry,
opening a fresh round retires the previous package and its options, collection
walks the settlement dimension, and a credit-posture edit releases blocked
enquiries.  The refusals here are all the generic source-state guard, except
the signature leg, which has its own idempotency code.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    AGENT_USER_ID,
    ApiErrorId,
    CLIENT_SIGNATURE_NAME,
    SPEAKER_SIGNATURE_NAME,
    add_option,
    add_second_engagement_for_speaker,
    circumvention_claim_payload,
    claim_resolution_payload,
    create_client,
    create_draft_proposal,
    create_hold,
    create_inquiry,
    create_speaker,
    disqualify_payload,
    find_holds_for_speaker,
    find_invoices_for,
    find_remittances_for,
    get_success_data,
    make_client_headers,
    payment_payload,
    proposal_decline_payload,
    proposal_payload,
    qualify_payload,
    read_client,
    read_contract,
    read_engagement,
    read_inquiry,
    read_invoice,
    read_option,
    read_proposal,
    read_remittance,
    read_speaker,
    revision_request_payload,
    select_option_payload,
    set_clock,
    setup_cancelled_engagement,
    setup_contracted_engagement,
    setup_delivered_engagement,
    setup_draft_proposal,
    setup_drafted_contract,
    setup_presented_proposal,
    setup_sent_contract,
    setup_upheld_claim,
    signature_payload,
    travel_expense_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NOVEMBER_BLACKOUT = {
    "hold_start_utc": "2026-11-01T00:00:00Z",
    "hold_end_utc": "2026-11-03T23:59:59Z",
    "reason": "writing retreat",
}


class TestInquiryQualificationBranches:
    def test_the_disqualify_branch_takes_ownership_and_records_the_note(self, api):
        """Both qualification branches claim the enquiry for the caller, so a refusal still stamps the owner.

        PRD: A `BookingAgent` supplies an `outcome` of either `QUALIFY` or `DISQUALIFY` together with an optional `qualification_note`, and in **both** branches the server records the caller's `X-User-ID` as `owning_agent_user_id`, stores the `qualification_note`, and increments the inquiry's `version` by one.
        Design: Corner/state_machines/inquiry_disqualify_branch_is_terminal_and_refuses_proposal_rounds
        """
        set_clock(api)
        client_row = create_client(api)
        inquiry = create_inquiry(api, client_row)
        assert inquiry["status"] == "RECEIVED"
        assert inquiry["owning_agent_user_id"] is None

        decided = validate_success(
            api.qualify_inquiry(
                inquiry["id"],
                disqualify_payload("audience mismatch"),
                AGENT_HEADERS,
            )
        )

        assert decided["status"] == "DISQUALIFIED"
        assert decided["qualification_note"] == "audience mismatch"
        assert decided["owning_agent_user_id"] == AGENT_USER_ID
        assert decided["version"] == inquiry["version"] + 1

    def test_a_disqualified_enquiry_can_never_open_a_quotation_round(self, api):
        """The round is only declared from the two live enquiry states, so the terminal branch refuses it.

        PRD: A `BookingAgent` opens a round on an inquiry that is either `QUALIFIED` or `PROPOSED`, supplying the concurrency token `expected_inquiry_version` described in §2.7 together with `valid_until_utc`, the instant at which the quotation stops being honourable.
        Design: Corner/state_machines/inquiry_disqualify_branch_is_terminal_and_refuses_proposal_rounds
        """
        set_clock(api)
        client_row = create_client(api)
        inquiry = create_inquiry(api, client_row)
        decided = validate_success(
            api.qualify_inquiry(
                inquiry["id"], disqualify_payload("audience mismatch"), AGENT_HEADERS
            )
        )

        validate_error(
            api.create_proposal(
                inquiry["id"], proposal_payload(decided["version"]), AGENT_HEADERS
            ),
            ApiErrorId.ERR_INQUIRY_STATE_INVALID.value,
        )

        assert read_inquiry(api, inquiry["id"])["status"] == "DISQUALIFIED"
        _rows, meta = validate_paginated(
            api.list_proposals(AGENT_HEADERS, params={"inquiry_id": inquiry["id"]})
        )
        assert meta["total_count"] == 0


class TestProposalRounds:
    def test_presentation_stamps_the_clock_and_advances_the_enquiry(self, api):
        """Going out to the client records when it happened and pushes the enquiry into its proposed state.

        PRD: Presentation stamps `presented_at_utc` with the logical clock's current value and drives the inquiry `QUALIFIED → PROPOSED`.
        Design: Corner/state_machines/proposal_present_stamps_presented_at_and_advances_the_inquiry
        """
        bundle = setup_draft_proposal(api)

        presented = validate_success(
            api.present_proposal(bundle["proposal"]["id"], AGENT_HEADERS)
        )

        assert presented["status"] == "PRESENTED"
        assert presented["presented_at_utc"] is not None
        assert presented["presented_at_utc"].startswith("2026-08-01T00:00:00")
        assert presented["round_no"] == 1
        assert presented["options_count"] == 1
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "PROPOSED"
        assert read_option(api, bundle["option"]["id"])["status"] == "OFFERED"

    def test_declining_the_package_sweeps_its_options_and_loses_the_enquiry(self, api):
        """The client's outright refusal retires the package, rejects its live option and closes the enquiry as lost.

        PRD: Declining the package outright, with an optional `decline_reason`, drives `PRESENTED → DECLINED`, moves every `OFFERED` option to `REJECTED`, and drives the inquiry `PROPOSED → LOST`.
        Design: Corner/state_machines/declined_proposal_is_locked_against_present_revision_and_select
        """
        bundle = setup_presented_proposal(api)

        declined = validate_success(
            api.decline_proposal(
                bundle["proposal"]["id"],
                proposal_decline_payload(),
                bundle["client_headers"],
            )
        )

        assert declined["status"] == "DECLINED"
        assert read_option(api, bundle["option"]["id"])["status"] == "REJECTED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "LOST"
        _rows, meta = validate_paginated(
            api.list_engagements(
                AGENT_HEADERS, params={"inquiry_id": bundle["inquiry"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_a_declined_package_refuses_presentation_revision_and_selection(self, api):
        """All three client-facing moves are declared from live states only, so a terminal package answers each the same way.

        PRD: The proposal status enumeration is `DRAFT`, `PRESENTED`, `REVISION_REQUESTED`, `ACCEPTED`, `DECLINED`, `SUPERSEDED` and `CLOSED`, with `DECLINED`, `SUPERSEDED` and `CLOSED` terminal.
        Design: Corner/state_machines/declined_proposal_is_locked_against_present_revision_and_select
        """
        bundle = setup_presented_proposal(api)
        proposal_id = bundle["proposal"]["id"]
        validate_success(
            api.decline_proposal(
                proposal_id, proposal_decline_payload(), bundle["client_headers"]
            )
        )

        validate_error(
            api.present_proposal(proposal_id, AGENT_HEADERS),
            ApiErrorId.ERR_PROPOSAL_STATE_INVALID.value,
        )
        validate_error(
            api.request_proposal_revision(
                proposal_id, revision_request_payload(), bundle["client_headers"]
            ),
            ApiErrorId.ERR_PROPOSAL_STATE_INVALID.value,
        )
        validate_error(
            api.select_proposal_option(
                proposal_id,
                select_option_payload(bundle["option"]["id"]),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_PROPOSAL_STATE_INVALID.value,
        )

        assert read_proposal(api, proposal_id)["status"] == "DECLINED"

    def test_a_new_round_supersedes_the_old_package_and_withdraws_its_options(
        self, api
    ):
        """Opening a second round retires the presented package and drags its live option to the withdrawn dead end.

        PRD: Every existing proposal on the same inquiry sitting in `DRAFT`, `PRESENTED` or `REVISION_REQUESTED` moves to `SUPERSEDED`, and each superseded package takes its live options with it: every option of a superseded proposal in `OFFERED` moves to `WITHDRAWN`.
        Design: Corner/state_machines/superseding_proposal_cascades_down_to_options_and_rewinds_the_inquiry
        """
        bundle = setup_presented_proposal(api)
        inquiry = read_inquiry(api, bundle["inquiry"]["id"])
        assert inquiry["status"] == "PROPOSED"

        replacement = validate_success(
            api.create_proposal(
                inquiry["id"],
                proposal_payload(
                    inquiry["version"], valid_until_utc="2026-09-25T00:00:00Z"
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )

        assert replacement["status"] == "DRAFT"
        assert replacement["round_no"] == 1
        assert replacement["revision_count"] == 0
        assert replacement["options_count"] == 0
        assert replacement["valid_until_utc"].startswith("2026-09-25T00:00:00")

        superseded = read_proposal(api, bundle["proposal"]["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert read_option(api, bundle["option"]["id"])["status"] == "WITHDRAWN"

    def test_the_presented_branch_walks_the_enquiry_back_to_qualified(self, api):
        """With no presented quotation left standing, the enquiry falls back one step rather than staying proposed.

        PRD: The `PRESENTED → SUPERSEDED` branch carries one extra consequence: since the inquiry no longer has any presented quotation, it falls back `PROPOSED → QUALIFIED`.
        Design: Corner/state_machines/superseding_proposal_cascades_down_to_options_and_rewinds_the_inquiry
        """
        bundle = setup_presented_proposal(api)
        inquiry = read_inquiry(api, bundle["inquiry"]["id"])

        validate_success(
            api.create_proposal(
                inquiry["id"],
                proposal_payload(
                    inquiry["version"], valid_until_utc="2026-09-25T00:00:00Z"
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )

        rewound = read_inquiry(api, inquiry["id"])
        assert rewound["status"] == "QUALIFIED"
        _rows, meta = validate_paginated(
            api.list_proposals(AGENT_HEADERS, params={"inquiry_id": inquiry["id"]})
        )
        assert meta["total_count"] == 2

    def test_the_withdrawn_option_can_never_be_selected_again(self, api):
        """Selection on the retired package is refused, so the withdrawn option stays where the cascade left it.

        PRD: A new option starts in `OFFERED`; the enumeration continues `SELECTED`, `REJECTED` and the terminal `WITHDRAWN`.
        Design: Corner/state_machines/superseding_proposal_cascades_down_to_options_and_rewinds_the_inquiry
        """
        bundle = setup_presented_proposal(api)
        inquiry = read_inquiry(api, bundle["inquiry"]["id"])
        validate_success(
            api.create_proposal(
                inquiry["id"],
                proposal_payload(
                    inquiry["version"], valid_until_utc="2026-09-25T00:00:00Z"
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )

        validate_error(
            api.select_proposal_option(
                bundle["proposal"]["id"],
                select_option_payload(bundle["option"]["id"]),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_PROPOSAL_STATE_INVALID.value,
        )

        assert read_option(api, bundle["option"]["id"])["status"] == "WITHDRAWN"


class TestContractSendAndSign:
    def test_sending_the_same_draft_twice_is_refused_on_its_source_state(self, api):
        """Issuing for signature is declared from the draft state only, so the second send finds nothing to move.

        PRD: Sending the drafted agreement out for signature is a `BookingAgent` action that requires the agreement to be in `DRAFT` and the engagement to be `CONFIRMED`, and moves the agreement `DRAFT → SENT`.
        Design: Corner/state_machines/contract_send_twice_is_rejected_by_the_draft_precondition
        """
        bundle = setup_drafted_contract(api)
        contract_id = bundle["contract"]["id"]

        sent = validate_success(api.send_contract(contract_id, AGENT_HEADERS))
        assert sent["status"] == "SENT"

        validate_error(
            api.send_contract(contract_id, AGENT_HEADERS),
            ApiErrorId.ERR_CONTRACT_STATE_INVALID.value,
        )

        after = read_contract(api, contract_id)
        assert after["status"] == "SENT"
        assert after["version"] == sent["version"]
        assert after["speaker_signed_at_utc"] is None
        assert after["client_signed_at_utc"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "booking_status"
        ] == "CONFIRMED"

    def test_the_same_party_cannot_fire_its_own_signature_leg_twice(self, api):
        """A repeat signature from the party that already signed is an idempotency refusal, not a state refusal.

        PRD: A party attempting to sign a leg whose own stamp is already set is refused with `ERR_PARTY_ALREADY_SIGNED`.
        Design: Corner/state_machines/contract_second_signature_by_the_same_party_is_rejected
        """
        bundle = setup_sent_contract(api)
        contract_id = bundle["contract"]["id"]

        signed = validate_success(
            api.sign_contract(
                contract_id,
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            )
        )
        assert signed["status"] == "PARTIALLY_SIGNED"
        assert signed["speaker_signed_at_utc"] is not None

        validate_error(
            api.sign_contract(
                contract_id,
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            ),
            ApiErrorId.ERR_PARTY_ALREADY_SIGNED.value,
        )

        after = read_contract(api, contract_id)
        assert after["status"] == "PARTIALLY_SIGNED"
        assert after["client_signed_at_utc"] is None
        assert after["executed_at_utc"] is None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONFIRMED"
        assert engagement["commission_pct_snapshot"] is None


class TestEngagementSourceStates:
    def test_confirming_an_already_contracted_booking_is_not_a_declared_move(
        self, api
    ):
        """Acceptance is declared from the offered state alone, so a fully contracted booking cannot be accepted again.

        PRD: **Confirmation** requires the engagement to be `OFFERED` and the speaker's `roster_status` to be `ACTIVE`.
        Design: Corner/state_machines/engagement_confirm_from_contracted_state_is_not_a_declared_transition
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])
        assert before["booking_status"] == "CONTRACTED"

        validate_error(
            api.confirm_engagement(before["id"], bundle["speaker_headers"]),
            ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID.value,
        )

        after = read_engagement(api, before["id"])
        assert after["booking_status"] == "CONTRACTED"
        assert after["version"] == before["version"]

        active = [
            hold
            for hold in find_holds_for_speaker(api, bundle["speaker"]["id"])
            if hold["status"] == "ACTIVE"
        ]
        assert len(active) == 1
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 3

    def test_every_freshly_created_row_starts_where_the_contract_says(self, api):
        """Walking the whole chain once shows each entity minted in its declared opening state.

        PRD: Its `booking_status` begins at `OFFERED` and its `settlement_status` at `UNBILLED`.
        Design: Corner/state_machines/initial_states_of_every_freshly_created_row_match_the_declared_defaults
        """
        set_clock(api)
        speaker = create_speaker(api)
        client_row = create_client(api)

        inquiry = create_inquiry(api, client_row)
        assert inquiry["status"] == "RECEIVED"

        inquiry = get_success_data(
            api.qualify_inquiry(inquiry["id"], qualify_payload(), AGENT_HEADERS)
        )
        proposal = create_draft_proposal(api, inquiry)
        assert proposal["status"] == "DRAFT"

        option = add_option(api, proposal, speaker)
        assert option["status"] == "OFFERED"

        get_success_data(api.present_proposal(proposal["id"], AGENT_HEADERS))
        engagement = get_success_data(
            api.select_proposal_option(
                proposal["id"],
                select_option_payload(option["id"]),
                make_client_headers(client_row["id"]),
            )
        )
        assert engagement["booking_status"] == "OFFERED"
        assert engagement["settlement_status"] == "UNBILLED"

    def test_the_booking_dimension_moves_while_the_money_dimension_waits(self, api):
        """Confirmation advances the booking side and leaves the settlement side exactly where it started.

        PRD: The booking dimension does not move while the settlement dimension advances, and vice versa: an engagement whose `booking_status` is already the terminal `DELIVERED` will still travel from `INVOICED` through `PARTIALLY_COLLECTED` and `COLLECTED` to `REMITTED`.
        Design: Corner/state_machines/initial_states_of_every_freshly_created_row_match_the_declared_defaults
        """
        bundle = setup_drafted_contract(api)

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONFIRMED"
        assert engagement["settlement_status"] == "UNBILLED"

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "DRAFT"
        assert contract["executed_at_utc"] is None

    def test_a_manual_blackout_and_a_fresh_receipt_open_in_their_own_states(self, api):
        """The two side entities are minted active and submitted, with nothing computed on the receipt yet.

        PRD: A `BureauAdmin` or a `BookingAgent` may enter a manual blackout by naming the `speaker_id`, an inclusive `hold_start_utc`, an inclusive `hold_end_utc` and an optional free-text `reason`; the resulting hold has `kind` `BLACKOUT`, a null `engagement_id`, and `status` `ACTIVE`.
        Design: Corner/state_machines/initial_states_of_every_freshly_created_row_match_the_declared_defaults
        """
        bundle = setup_drafted_contract(api)

        hold = create_hold(api, bundle["speaker"], **NOVEMBER_BLACKOUT)
        assert hold["kind"] == "BLACKOUT"
        assert hold["engagement_id"] is None
        assert hold["status"] == "ACTIVE"

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


class TestCollectionInstallments:
    def test_a_part_payment_lands_between_the_two_ends_of_the_ledger(self, api):
        """A payment short of the balance leaves the invoice partly paid and the payout still pending.

        PRD: A payment strictly smaller than the remaining balance drives the invoice `ISSUED → PARTIALLY_PAID` and the engagement's settlement dimension `INVOICED → PARTIALLY_COLLECTED`.
        Design: Corner/state_machines/invoice_payments_keep_client_balance_in_sync_across_two_installments
        """
        bundle = setup_delivered_engagement(api)
        invoice = bundle["invoice"]
        assert invoice["amount_due_cents"] == 1_297_313
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 1_297_313

        get_success_data(
            api.create_invoice_payment(
                invoice["id"], payment_payload(1_000_000, method="ACH"), ADMIN_HEADERS
            )
        )

        after = read_invoice(api, invoice["id"])
        assert after["status"] == "PARTIALLY_PAID"
        assert after["amount_paid_cents"] == 1_000_000
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 297_313
        assert read_engagement(api, bundle["engagement"]["id"])[
            "settlement_status"
        ] == "PARTIALLY_COLLECTED"
        assert read_remittance(api, bundle["remittance"]["id"])["status"] == "PENDING"

    def test_the_closing_installment_clears_the_balance_and_approves_the_payout(
        self, api
    ):
        """Settling the remainder finishes the collection and turns the payout approval into arithmetic.

        PRD: A payment exactly equal to the remaining balance drives the invoice to `PAID` — `ISSUED → PAID` when this single payment settles the whole invoice, or `PARTIALLY_PAID → PAID` when earlier partial payments had already landed — drives the settlement dimension to `COLLECTED` by the matching leg, `INVOICED → COLLECTED` in the first case and `PARTIALLY_COLLECTED → COLLECTED` in the second, and, as a cascade, moves that engagement's remittance `PENDING → APPROVED`.
        Design: Corner/state_machines/invoice_payments_keep_client_balance_in_sync_across_two_installments
        """
        bundle = setup_delivered_engagement(api)
        invoice_id = bundle["invoice"]["id"]
        get_success_data(
            api.create_invoice_payment(
                invoice_id, payment_payload(1_000_000, method="ACH"), ADMIN_HEADERS
            )
        )

        get_success_data(
            api.create_invoice_payment(
                invoice_id, payment_payload(297_313, method="WIRE"), ADMIN_HEADERS
            )
        )

        settled = read_invoice(api, invoice_id)
        assert settled["status"] == "PAID"
        assert settled["amount_paid_cents"] == 1_297_313
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 0
        assert read_engagement(api, bundle["engagement"]["id"])[
            "settlement_status"
        ] == "COLLECTED"

        remittance = read_remittance(api, bundle["remittance"]["id"])
        assert remittance["status"] == "APPROVED"
        assert remittance["paid_at_utc"] is None
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 956_250


class TestCreditPostureCascades:
    def _client_on_credit_hold(self, api):
        bundle = setup_upheld_claim(api)
        qualified = create_inquiry(
            api,
            bundle["client"],
            event_start_utc="2027-03-10T16:00:00Z",
            event_end_utc="2027-03-10T18:00:00Z",
        )
        qualified = get_success_data(
            api.qualify_inquiry(
                qualified["id"],
                qualify_payload(qualification_note="budget signed off"),
                AGENT_HEADERS,
            )
        )
        received = create_inquiry(
            api,
            bundle["client"],
            event_start_utc="2027-04-14T16:00:00Z",
            event_end_utc="2027-04-14T18:00:00Z",
        )
        bundle = add_second_engagement_for_speaker(
            api,
            bundle,
            event_start_utc="2026-11-20T16:00:00Z",
            event_end_utc="2026-11-20T18:00:00Z",
            valid_until_utc="2026-10-30T00:00:00Z",
            setup_clock_utc="2026-10-16T00:00:00Z",
        )
        second_claim = get_success_data(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement_2"]["id"],
                    "2026-12-20T18:00:00Z",
                    800_000,
                ),
                ADMIN_HEADERS,
            )
        )
        get_success_data(
            api.resolve_circumvention_claim(
                second_claim["id"], claim_resolution_payload("UPHOLD"), ADMIN_HEADERS
            )
        )
        bundle["blocked_inquiry"] = read_inquiry(api, qualified["id"])
        bundle["received_inquiry"] = read_inquiry(api, received["id"])
        bundle["client"] = read_client(api, bundle["client"]["id"])
        return bundle

    def test_the_second_strike_blocks_only_the_qualified_enquiry(self, api):
        """When the posture collapses, the qualified row is blocked and the untouched row is left alone.

        PRD: `QUALIFIED → BLOCKED` happens only as the fourth hop of the non-circumvention cascade in §3.9, and it is deliberately selective: when a client's credit posture collapses to `HOLD`, only that client's `QUALIFIED` inquiries are blocked, and rows sitting in `RECEIVED` or `PROPOSED` are left untouched.
        Design: Corner/state_machines/clearing_a_credit_hold_conditionally_releases_only_blocked_inquiries
        """
        bundle = self._client_on_credit_hold(api)

        assert bundle["client"]["credit_status"] == "HOLD"
        assert bundle["client"]["circumvention_strikes"] == 2
        assert bundle["blocked_inquiry"]["status"] == "BLOCKED"
        assert bundle["received_inquiry"]["status"] == "RECEIVED"

    def test_clearing_the_hold_releases_only_the_blocked_row(self, api):
        """Restoring the posture returns the blocked enquiry to qualified and leaves the received one where it was.

        PRD: A `BureauAdmin` may subsequently revise `credit_status` and `primary_contact_email`, which increments the client's `version` by one; when the revision moves `credit_status` out of `HOLD` to either `GOOD` or `WATCH`, every inquiry of that client sitting in `BLOCKED` returns to `QUALIFIED` as a cascade.
        Design: Corner/state_machines/clearing_a_credit_hold_conditionally_releases_only_blocked_inquiries
        """
        bundle = self._client_on_credit_hold(api)
        before_version = bundle["client"]["version"]

        cleared = validate_success(
            api.update_client(
                bundle["client"]["id"], {"credit_status": "GOOD"}, ADMIN_HEADERS
            )
        )
        assert cleared["credit_status"] == "GOOD"
        assert cleared["version"] == before_version + 1

        released = read_inquiry(api, bundle["blocked_inquiry"]["id"])
        assert released["status"] == "QUALIFIED"
        assert released["owning_agent_user_id"] == AGENT_USER_ID
        assert released["qualification_note"] == "budget signed off"
        assert read_inquiry(api, bundle["received_inquiry"]["id"])[
            "status"
        ] == "RECEIVED"


class TestSpeakerSideCancellation:
    def test_the_speaker_walking_away_bills_nothing_and_pauses_the_roster_entry(
        self, api
    ):
        """A speaker cancellation two weeks out waives the billing entirely and puts the roster entry on probation.

        PRD: In both cases `cancelled_by` is `SPEAKER`, no retention is computed, the settlement dimension moves `UNBILLED → WAIVED`, and the speaker's `roster_status` moves `ACTIVE → PROBATION`, which immediately makes that speaker unquotable, unconfirmable and unable to sign until a `BureauAdmin` restores them.
        Design: Corner/state_machines/speaker_side_cancellation_waives_billing_and_puts_the_roster_on_probation
        """
        bundle = setup_cancelled_engagement(
            api,
            cancellation_clock_utc="2026-10-01T16:00:00Z",
            cancelled_by_headers_key="speaker_headers",
            cancellation_reason="the speaker fell ill",
        )

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CANCELLED_BY_SPEAKER"
        assert engagement["cancelled_by"] == "SPEAKER"
        assert engagement["cancellation_days_before"] == 14
        assert engagement["settlement_status"] == "WAIVED"

        assert find_invoices_for(api, engagement["id"]) == []
        assert find_remittances_for(api, engagement["id"]) == []

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["roster_status"] == "PROBATION"
        assert speaker["held_days_count"] == 0

    def test_the_executed_agreement_survives_the_cancellation_untouched(self, api):
        """Only unexecuted agreements are voided, so the executed one stays executed after a speaker cancellation.

        PRD: The two speaker-side branches differ only in their collateral: from `CONFIRMED`, an unexecuted agreement in `DRAFT`, `SENT` or `PARTIALLY_SIGNED` moves to `VOID`; from `CONTRACTED`, the agreement is already `EXECUTED` and instead every `ACTIVE` exclusivity grant sourced from this engagement moves to `EXPIRED`.
        Design: Corner/state_machines/speaker_side_cancellation_waives_billing_and_puts_the_roster_on_probation
        """
        bundle = setup_cancelled_engagement(
            api,
            cancellation_clock_utc="2026-10-01T16:00:00Z",
            cancelled_by_headers_key="speaker_headers",
            cancellation_reason="the speaker fell ill",
        )

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "EXECUTED"
        assert contract["executed_at_utc"] is not None
