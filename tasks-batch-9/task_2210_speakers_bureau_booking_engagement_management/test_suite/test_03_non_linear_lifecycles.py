"""Lifecycles that loop, fork and run on two independent dimensions.

A quotation package can go out three times but be re-quoted only twice; an
agreement needs two signatures that may arrive in either order before it
executes; and an engagement's money track keeps moving long after its booking
track has come to a terminal stop.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    CLIENT_SIGNATURE_NAME,
    SPEAKER_SIGNATURE_NAME,
    assert_booking_and_settlement,
    cancellation_payload,
    find_grants_for_speaker,
    find_remittances_for,
    payment_payload,
    read_contract,
    read_engagement,
    read_inquiry,
    read_invoice,
    read_proposal,
    read_remittance,
    remittance_payout_payload,
    revision_request_payload,
    setup_cancelled_engagement,
    setup_presented_proposal,
    setup_sent_contract,
    signature_payload,
    validate_error,
    validate_success,
)


class TestBoundedRevisionCycle:
    def test_each_revision_walks_the_inquiry_back_and_re_presentation_bumps_the_round(
        self, api
    ):
        """Two revision cycles leave the package on its third outing with two revisions absorbed.

        PRD: The two presentation branches differ in exactly one respect: `DRAFT → PRESENTED` leaves `round_no` at its current value, whereas `REVISION_REQUESTED → PRESENTED` increments `round_no` by one, so the number of times a package has gone out is always observable.
        Design: Difficulty/non_linear_state_machine/non_linear_proposal_revision_cycle_bounded_at_two_rounds
        """
        bundle = setup_presented_proposal(api)
        proposal_id = bundle["proposal"]["id"]

        first = validate_success(
            api.request_proposal_revision(
                proposal_id, revision_request_payload(), bundle["client_headers"]
            )
        )
        assert first["status"] == "REVISION_REQUESTED"
        assert first["revision_count"] == 1
        assert first["round_no"] == 1
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "QUALIFIED"

        second_outing = validate_success(
            api.present_proposal(proposal_id, AGENT_HEADERS)
        )
        assert second_outing["status"] == "PRESENTED"
        assert second_outing["round_no"] == 2

        second = validate_success(
            api.request_proposal_revision(
                proposal_id, revision_request_payload(), bundle["client_headers"]
            )
        )
        assert second["revision_count"] == 2
        assert second["round_no"] == 2

        third_outing = validate_success(
            api.present_proposal(proposal_id, AGENT_HEADERS)
        )
        assert third_outing["round_no"] == 3

    def test_a_third_revision_request_is_refused_and_the_package_stays_presented(
        self, api
    ):
        """The loop is bounded on the revision leg only, so the third re-quote is refused at round three.

        PRD: Asking for a re-quote, with an optional `revision_note`, drives `PRESENTED → REVISION_REQUESTED`, increments `revision_count` by one, and walks the inquiry back `PROPOSED → QUALIFIED`; the loop is bounded on this leg and only on this leg, so a request made when `revision_count` already stands at 2 is refused with `ERR_REVISION_LIMIT_REACHED`.
        Design: Difficulty/non_linear_state_machine/non_linear_proposal_revision_cycle_bounded_at_two_rounds
        """
        bundle = setup_presented_proposal(api)
        proposal_id = bundle["proposal"]["id"]

        for _ in range(2):
            validate_success(
                api.request_proposal_revision(
                    proposal_id, revision_request_payload(), bundle["client_headers"]
                )
            )
            validate_success(api.present_proposal(proposal_id, AGENT_HEADERS))

        validate_error(
            api.request_proposal_revision(
                proposal_id, revision_request_payload(), bundle["client_headers"]
            ),
            ApiErrorId.ERR_REVISION_LIMIT_REACHED.value,
        )

        proposal = read_proposal(api, proposal_id)
        assert proposal["status"] == "PRESENTED"
        assert proposal["round_no"] == 3
        assert proposal["revision_count"] == 2


class TestSignatureForkAndJoin:
    def test_the_first_leg_only_partially_signs_and_prices_nothing(self, api):
        """After the speaker leg alone the agreement is half signed, the engagement is still unpriced and no grant exists.

        PRD: Whichever party signs first drives the agreement `SENT → PARTIALLY_SIGNED`.
        Design: Difficulty/non_linear_state_machine/non_linear_contract_fork_join_requires_both_signature_legs
        """
        bundle = setup_sent_contract(
            api, contract_overrides={"exclusivity_days": 90}
        )
        validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(SPEAKER_SIGNATURE_NAME),
                bundle["speaker_headers"],
            )
        )

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "PARTIALLY_SIGNED"
        assert contract["speaker_signed_at_utc"] is not None
        assert contract["client_signed_at_utc"] is None
        assert contract["executed_at_utc"] is None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONFIRMED"
        assert engagement["commission_pct_snapshot"] is None
        assert engagement["provisional_commission_cents"] is None

        assert find_grants_for_speaker(api, bundle["speaker"]["id"]) == []

    def test_the_engagement_stays_unpriced_until_the_join(self, api):
        """A confirmed engagement carries no commission figures because it has no executed agreement to price against.

        PRD: `commission_pct_snapshot`, `provisional_commission_cents`, `final_commission_cents`, `retention_net_cents` and `retention_commission_cents` are all null on a fresh engagement — indeed they stay null for any engagement in `OFFERED`, `CONFIRMED`, `DECLINED_BY_SPEAKER` or either cancelled booking state, because none of those states has an executed agreement to price against.
        Design: Difficulty/non_linear_state_machine/non_linear_contract_fork_join_requires_both_signature_legs
        """
        bundle = setup_sent_contract(
            api, contract_overrides={"exclusivity_days": 90}
        )
        validate_success(
            api.sign_contract(
                bundle["contract"]["id"],
                signature_payload(CLIENT_SIGNATURE_NAME),
                bundle["client_headers"],
            )
        )

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "PARTIALLY_SIGNED"
        assert contract["client_signed_at_utc"] is not None
        assert contract["speaker_signed_at_utc"] is None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONFIRMED"
        assert engagement["final_commission_cents"] is None
        assert engagement["retention_net_cents"] is None
        assert engagement["retention_commission_cents"] is None

    def test_the_second_leg_executes_the_agreement_and_fans_out(self, api):
        """The join stamps the execution instant, prices the engagement, closes the package and mints the exclusivity window.

        PRD: At the join, the party who has not yet signed drives `PARTIALLY_SIGNED → EXECUTED`, and that second signature must still satisfy its own guard — the speaker's `roster_status` for the speaker leg, the client's `credit_status` for the client leg.
        Design: Difficulty/non_linear_state_machine/non_linear_contract_fork_join_requires_both_signature_legs
        """
        bundle = setup_sent_contract(
            api, contract_overrides={"exclusivity_days": 90}
        )
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

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "EXECUTED"
        assert contract["executed_at_utc"] is not None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONTRACTED"
        assert engagement["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert engagement["provisional_commission_cents"] == 318_750

        assert read_proposal(api, bundle["proposal"]["id"])["status"] == "CLOSED"

    def test_execution_mints_exactly_one_half_open_exclusivity_window(self, api):
        """A ninety-day term produces one active grant running from the event end to the same instant ninety days later.

        PRD: And when `exclusivity_days` is greater than 0, an `ExclusivityGrant` is created in `status` `ACTIVE`, recording `source_engagement_id` as this engagement, `speaker_id` as this speaker, `beneficiary_client_id` as this engagement's client, `industry_code` copied from that beneficiary client, `effective_from_utc` equal to the engagement's `event_end_utc`, and `effective_to_utc` equal to `effective_from_utc` plus `exclusivity_days` days — the window being inclusive at its start and **exclusive** at its end.
        Design: Difficulty/non_linear_state_machine/non_linear_contract_fork_join_requires_both_signature_legs
        """
        bundle = setup_sent_contract(
            api, contract_overrides={"exclusivity_days": 90}
        )
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

        grants = find_grants_for_speaker(api, bundle["speaker"]["id"])
        assert len(grants) == 1
        grant = grants[0]
        assert grant["status"] == "ACTIVE"
        assert grant["source_engagement_id"] == bundle["engagement"]["id"]
        assert grant["beneficiary_client_id"] == bundle["client"]["id"]
        assert grant["industry_code"] == "HEALTHCARE"
        assert grant["effective_from_utc"].startswith("2026-10-15T18:00:00")
        assert grant["effective_to_utc"].startswith("2027-01-13T18:00:00")


class TestSettlementAdvancesOverATerminalBooking:
    def test_the_money_track_reaches_remitted_while_the_booking_stays_cancelled(
        self, api
    ):
        """A cancelled engagement still collects its retention invoice and pays the speaker out.

        PRD: The booking dimension does not move while the settlement dimension advances, and vice versa: an engagement whose `booking_status` is already the terminal `DELIVERED` will still travel from `INVOICED` through `PARTIALLY_COLLECTED` and `COLLECTED` to `REMITTED`.
        Design: Difficulty/non_linear_state_machine/non_linear_engagement_settlement_advances_while_booking_stays_cancelled
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        assert_booking_and_settlement(
            bundle["engagement"], "CANCELLED_BY_CLIENT", "INVOICED"
        )
        invoice = bundle["retention_invoice"]

        validate_success(
            api.create_invoice_payment(
                invoice["id"],
                payment_payload(583_791, method="ACH"),
                bundle["client_headers"],
            )
        )
        assert read_invoice(api, invoice["id"])["status"] == "PAID"
        assert_booking_and_settlement(
            read_engagement(api, bundle["engagement"]["id"]),
            "CANCELLED_BY_CLIENT",
            "COLLECTED",
        )

        remittance = find_remittances_for(api, bundle["engagement"]["id"])[0]
        assert read_remittance(api, remittance["id"])["status"] == "APPROVED"

        validate_success(
            api.pay_remittance(
                remittance["id"],
                remittance_payout_payload("WIRE-77012"),
                ADMIN_HEADERS,
            )
        )
        assert read_remittance(api, remittance["id"])["status"] == "PAID"
        assert_booking_and_settlement(
            read_engagement(api, bundle["engagement"]["id"]),
            "CANCELLED_BY_CLIENT",
            "REMITTED",
        )

    def test_full_collection_approves_the_payout_without_a_manual_step(self, api):
        """Settling the whole balance in one payment moves the remittance to approved as a cascade.

        PRD: A payment exactly equal to the remaining balance drives the invoice to `PAID` — `ISSUED → PAID` when this single payment settles the whole invoice, or `PARTIALLY_PAID → PAID` when earlier partial payments had already landed — drives the settlement dimension to `COLLECTED` by the matching leg, `INVOICED → COLLECTED` in the first case and `PARTIALLY_COLLECTED → COLLECTED` in the second, and, as a cascade, moves that engagement's remittance `PENDING → APPROVED`.
        Design: Difficulty/non_linear_state_machine/non_linear_engagement_settlement_advances_while_booking_stays_cancelled
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        remittance = find_remittances_for(api, bundle["engagement"]["id"])[0]
        assert remittance["status"] == "PENDING"

        validate_success(
            api.create_invoice_payment(
                bundle["retention_invoice"]["id"],
                payment_payload(583_791, method="ACH"),
                bundle["client_headers"],
            )
        )

        assert read_remittance(api, remittance["id"])["status"] == "APPROVED"
        assert read_invoice(api, bundle["retention_invoice"]["id"])[
            "amount_paid_cents"
        ] == 583_791

    def test_a_second_cancellation_of_a_terminal_booking_is_refused(self, api):
        """The booking dimension is already terminal, so cancelling twice is rejected even though the money track moved on.

        PRD: An attempt against an engagement already in one of the four terminal booking states is refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`.
        Design: Difficulty/non_linear_state_machine/non_linear_engagement_settlement_advances_while_booking_stays_cancelled
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        validate_success(
            api.create_invoice_payment(
                bundle["retention_invoice"]["id"],
                payment_payload(583_791, method="ACH"),
                bundle["client_headers"],
            )
        )

        validate_error(
            api.cancel_engagement(
                bundle["engagement"]["id"],
                cancellation_payload("the client tried again"),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_ENGAGEMENT_ALREADY_TERMINAL.value,
        )
        assert_booking_and_settlement(
            read_engagement(api, bundle["engagement"]["id"]),
            "CANCELLED_BY_CLIENT",
            "COLLECTED",
        )
