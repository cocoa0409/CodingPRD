"""Triggering the catalogued error codes and keeping the near-misses apart.

Several of these codes are easy to confuse with a neighbour: two ends of one
numeric band share a code, two fiscal guards on one endpoint do not, and two
sibling-uniqueness constraints have a declared order.  Each test also checks
that the refused call left the world exactly as it found it.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_option,
    circumvention_claim_payload,
    claim_resolution_payload,
    claim_settlement_payload,
    commission_adjustment_payload,
    create_draft_proposal,
    create_second_speaker,
    find_invoices_for,
    find_remittances_for,
    payment_payload,
    proposal_option_payload,
    read_claim,
    read_client,
    read_engagement,
    read_inquiry,
    read_invoice,
    read_proposal,
    read_remittance,
    read_speaker,
    remittance_payout_payload,
    set_clock,
    setup_contracted_engagement,
    setup_delivered_engagement,
    setup_qualified_inquiry,
    validate_error,
    validate_paginated,
    validate_success,
)

INVOICE_TOTAL_CENTS = 1_297_313
NET_PAYABLE_CENTS = 956_250
DIRECT_EVENT_DATE_UTC = "2026-12-14T18:00:00Z"
DIRECT_FEE_CENTS = 1_000_000
COMMISSION_DUE_CENTS = 250_000


class TestNotFoundSweep:
    def test_every_resource_family_answers_with_its_own_not_found_code(self, api):
        """Thirteen reads of the same unused identifier produce thirteen different 404 codes.

        PRD: Each resource type has its own not-found code: `ERR_SPEAKER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_OPTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_TRAVEL_EXPENSE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_GRANT_NOT_FOUND` and `ERR_FEEDBACK_NOT_FOUND`, all HTTP 404.
        Design: Corner/errors/not_found_sweep_across_every_path_parameter_resource
        """
        set_clock(api)

        validate_error(
            api.get_client(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_CLIENT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_inquiry(NON_EXISTENT_UUID, AGENT_HEADERS),
            ApiErrorId.ERR_INQUIRY_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_proposal(NON_EXISTENT_UUID, AGENT_HEADERS),
            ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_proposal_option(NON_EXISTENT_UUID, AGENT_HEADERS),
            ApiErrorId.ERR_OPTION_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_engagement(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_contract(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_speaker_hold(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_HOLD_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_travel_expense(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_TRAVEL_EXPENSE_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_invoice(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_INVOICE_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_remittance(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_REMITTANCE_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_circumvention_claim(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_exclusivity_grant(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_GRANT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_feedback(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_FEEDBACK_NOT_FOUND.value,
            expected_status=404,
        )

    def test_an_error_envelope_carries_only_the_two_meta_fields(self, api):
        """The refusal is still a well-formed envelope with a request identifier and a message.

        PRD: The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
        Design: Corner/errors/not_found_sweep_across_every_path_parameter_resource
        """
        set_clock(api)

        response = api.get_invoice(NON_EXISTENT_UUID, ADMIN_HEADERS)
        error = validate_error(
            response, ApiErrorId.ERR_INVOICE_NOT_FOUND.value, expected_status=404
        )
        assert error["message"].strip() != ""

        body = response.json()
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"] != ""


class TestPaymentBandEnds:
    def test_one_cent_over_and_a_zero_payment_share_the_same_code(self, api):
        """The band is open at the bottom and closed at the top, and both breaches are the same refusal.

        PRD: The amount must be strictly greater than 0 and no greater than the invoice's remaining balance, that is `amount_due_cents` minus `amount_paid_cents`; anything else is refused with `ERR_OVERPAYMENT`.
        Design: Corner/errors/overpayment_and_zero_payment_are_both_rejected
        """
        bundle = setup_delivered_engagement(api)
        invoice = bundle["invoice"]
        assert invoice["amount_due_cents"] == INVOICE_TOTAL_CENTS
        assert invoice["amount_paid_cents"] == 0

        validate_error(
            api.create_invoice_payment(
                invoice["id"], payment_payload(INVOICE_TOTAL_CENTS + 1), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_OVERPAYMENT.value,
            expected_status=409,
        )
        validate_error(
            api.create_invoice_payment(
                invoice["id"], payment_payload(0), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_OVERPAYMENT.value,
            expected_status=409,
        )

        unchanged = read_invoice(api, invoice["id"])
        assert unchanged["status"] == "ISSUED"
        assert unchanged["amount_paid_cents"] == 0
        assert (
            read_client(api, bundle["client"]["id"])["outstanding_balance_cents"]
            == INVOICE_TOTAL_CENTS
        )

    def test_the_exact_balance_settles_the_invoice_and_approves_the_payout(self, api):
        """Once the two out-of-band attempts are refused, the exact remaining balance still collects cleanly.

        PRD: A payment exactly equal to the remaining balance drives the invoice to `PAID` — `ISSUED → PAID` when this single payment settles the whole invoice, or `PARTIALLY_PAID → PAID` when earlier partial payments had already landed — drives the settlement dimension to `COLLECTED` by the matching leg, `INVOICED → COLLECTED` in the first case and `PARTIALLY_COLLECTED → COLLECTED` in the second, and, as a cascade, moves that engagement's remittance `PENDING → APPROVED`.
        Design: Corner/errors/overpayment_and_zero_payment_are_both_rejected
        """
        bundle = setup_delivered_engagement(api)
        invoice = bundle["invoice"]

        validate_error(
            api.create_invoice_payment(
                invoice["id"], payment_payload(INVOICE_TOTAL_CENTS + 1), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_OVERPAYMENT.value,
        )
        validate_error(
            api.create_invoice_payment(
                invoice["id"], payment_payload(0), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_OVERPAYMENT.value,
        )

        paid = validate_success(
            api.create_invoice_payment(
                invoice["id"], payment_payload(INVOICE_TOTAL_CENTS), ADMIN_HEADERS
            )
        )
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == INVOICE_TOTAL_CENTS

        assert (
            read_engagement(api, bundle["engagement"]["id"])["settlement_status"]
            == "COLLECTED"
        )
        assert read_remittance(api, bundle["remittance"]["id"])["status"] == "APPROVED"


class TestFiscalGuardsOnQuoting:
    def _draft_package(self, api) -> dict:
        bundle = setup_qualified_inquiry(api)
        bundle["proposal"] = create_draft_proposal(api, bundle["inquiry"])
        return bundle

    def test_a_quote_below_the_speakers_floor_names_the_range(self, api):
        """The 900,000 quote sits under Dana's floor, so the speaker's own range is what refuses it.

        PRD: Financially, `quoted_fee_cents` must fall inside the offered speaker's range — greater than or equal to `fee_floor_cents` and less than or equal to `fee_ceiling_cents` — or the request is refused with `ERR_FEE_OUTSIDE_SPEAKER_RANGE`.
        Design: Corner/errors/fee_outside_speaker_range_and_quote_above_budget_cap_are_distinct_errors
        """
        bundle = self._draft_package(api)
        assert bundle["speaker"]["fee_floor_cents"] == 1_000_000

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["speaker"]["id"],
                    quoted_fee_cents=900_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_FEE_OUTSIDE_SPEAKER_RANGE.value,
            expected_status=409,
        )
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 0

    def test_total_exposure_above_the_tolerance_names_the_budget(self, api):
        """A quote inside the range still fails when the fee plus the allowance clears the client's 120% cap.

        PRD: Finally the total exposure to the client, `quoted_fee_cents` plus `travel_allowance_cents`, may not exceed the inquiry's budget with a twenty-percent tolerance: the ceiling is `budget_cents` multiplied by 1.20 and rounded half up to a whole number of cents, and a quote above that ceiling is refused with `ERR_QUOTE_EXCEEDS_BUDGET`.
        Design: Corner/errors/fee_outside_speaker_range_and_quote_above_budget_cap_are_distinct_errors
        """
        bundle = self._draft_package(api)
        assert bundle["inquiry"]["budget_cents"] == 1_600_000

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["speaker"]["id"],
                    quoted_fee_cents=1_900_000,
                    travel_allowance_cents=50_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_QUOTE_EXCEEDS_BUDGET.value,
            expected_status=409,
        )
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 0

    def test_exposure_landing_exactly_on_the_tolerance_is_admitted(self, api):
        """1,900,000 plus 20,000 is the ceiling to the cent, and the ceiling is inclusive.

        PRD: Finally the total exposure to the client, `quoted_fee_cents` plus `travel_allowance_cents`, may not exceed the inquiry's budget with a twenty-percent tolerance: the ceiling is `budget_cents` multiplied by 1.20 and rounded half up to a whole number of cents, and a quote above that ceiling is refused with `ERR_QUOTE_EXCEEDS_BUDGET`.
        Design: Corner/errors/fee_outside_speaker_range_and_quote_above_budget_cap_are_distinct_errors
        """
        bundle = self._draft_package(api)

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["speaker"]["id"],
                    quoted_fee_cents=900_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_FEE_OUTSIDE_SPEAKER_RANGE.value,
        )
        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["speaker"]["id"],
                    quoted_fee_cents=1_900_000,
                    travel_allowance_cents=50_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_QUOTE_EXCEEDS_BUDGET.value,
        )

        option = validate_success(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["speaker"]["id"],
                    quoted_fee_cents=1_900_000,
                    travel_allowance_cents=20_000,
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert option["status"] == "OFFERED"
        assert option["quoted_fee_cents"] + option["travel_allowance_cents"] == 1_920_000
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 1


class TestCommissionRateBand:
    def test_a_rate_above_the_band_is_refused_and_changes_nothing(self, api):
        """Forty percent is outside the closed band, so the pinned snapshot and the counter both stand.

        PRD: The rate must lie between 0.10 and 0.35 inclusive, and a value outside that band is refused with `ERR_COMMISSION_PCT_OUT_OF_RANGE`.
        Design: Corner/errors/commission_pct_outside_the_allowed_band_returns_422
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])

        validate_error(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.40, before["version"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_COMMISSION_PCT_OUT_OF_RANGE.value,
            expected_status=422,
        )

        after = read_engagement(api, before["id"])
        assert after["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert after["commission_adjustment_count"] == 0
        assert after["version"] == before["version"]

    def test_the_upper_endpoint_of_the_band_is_accepted_and_re_prices_the_engagement(
        self, api
    ):
        """0.35 is inside the inclusive band, and the accepted adjustment rewrites the provisional figure.

        PRD: An accepted adjustment overwrites `commission_pct_snapshot` with `new_commission_pct`, rewrites `provisional_commission_cents` using the provisional formula at the new rate — `quoted_fee_cents` multiplied by the new snapshot, rounded half up — and increments `commission_adjustment_count` by one.
        Design: Corner/errors/commission_pct_outside_the_allowed_band_returns_422
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])

        validate_error(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.40, before["version"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_COMMISSION_PCT_OUT_OF_RANGE.value,
        )

        adjusted = validate_success(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.35, before["version"]),
                ADMIN_HEADERS,
            )
        )
        assert adjusted["commission_pct_snapshot"] == pytest.approx(0.35, abs=0.001)
        assert adjusted["provisional_commission_cents"] == 446_250
        assert adjusted["commission_adjustment_count"] == 1


class TestRemittancePayoutGate:
    def test_a_pending_remittance_cannot_be_paid_out(self, api):
        """The payout waits on the collection cascade, not on the bureau's willingness to pay.

        PRD: A `BureauAdmin` pays out a remittance whose `status` is `APPROVED`, supplying an optional `payment_reference`; a remittance in any other status is refused with `ERR_REMITTANCE_NOT_APPROVED`, and a payout attempted while the speaker's `tax_form_status` is `MISSING` is refused with `ERR_SPEAKER_TAX_FORM_MISSING`.
        Design: Corner/errors/remittance_payout_before_the_invoice_is_paid_is_rejected
        """
        bundle = setup_delivered_engagement(api)
        remittance = bundle["remittance"]
        assert remittance["status"] == "PENDING"
        assert remittance["net_payable_cents"] == NET_PAYABLE_CENTS
        assert bundle["speaker"]["tax_form_status"] == "ON_FILE"

        validate_error(
            api.pay_remittance(
                remittance["id"], remittance_payout_payload(), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_REMITTANCE_NOT_APPROVED.value,
            expected_status=409,
        )

        unchanged = read_remittance(api, remittance["id"])
        assert unchanged["status"] == "PENDING"
        assert unchanged["paid_at_utc"] is None
        assert unchanged["net_payable_cents"] == NET_PAYABLE_CENTS
        assert (
            read_speaker(api, bundle["speaker"]["id"])["pending_remittance_cents"]
            == NET_PAYABLE_CENTS
        )
        assert (
            read_engagement(api, bundle["engagement"]["id"])["settlement_status"]
            == "INVOICED"
        )


class TestDeliveryWaitsForTheEvent:
    def test_delivery_before_the_window_closes_is_refused(self, api):
        """Complete paperwork does not let the bureau bill an event that has not happened yet.

        PRD: It requires the engagement's `booking_status` to be `CONTRACTED`, the engagement's agreement to be `EXECUTED`, and the logical clock to be at or after the engagement's `event_end_utc`; an attempt before the window closes is refused with `ERR_EVENT_NOT_ENDED`.
        Design: Corner/errors/delivery_before_the_event_window_closes_is_rejected
        """
        bundle = setup_contracted_engagement(api)
        assert bundle["contract"]["status"] == "EXECUTED"

        validate_error(
            api.deliver_engagement(bundle["engagement"]["id"], AGENT_HEADERS),
            ApiErrorId.ERR_EVENT_NOT_ENDED.value,
            expected_status=409,
        )

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["booking_status"] == "CONTRACTED"
        assert engagement["settlement_status"] == "UNBILLED"
        assert engagement["final_commission_cents"] is None

    def test_the_refused_delivery_bills_nothing_at_all(self, api):
        """No invoice, no remittance and no delivery credit follow a refused delivery.

        PRD: Delivery drives `CONTRACTED → DELIVERED` on the booking dimension and `UNBILLED → INVOICED` on the settlement dimension, and it triggers a chain of six consequences.
        Design: Corner/errors/delivery_before_the_event_window_closes_is_rejected
        """
        bundle = setup_contracted_engagement(api)

        validate_error(
            api.deliver_engagement(bundle["engagement"]["id"], AGENT_HEADERS),
            ApiErrorId.ERR_EVENT_NOT_ENDED.value,
        )

        assert find_invoices_for(api, bundle["engagement"]["id"]) == []
        assert find_remittances_for(api, bundle["engagement"]["id"]) == []
        assert (
            read_speaker(api, bundle["speaker"]["id"])["engagements_delivered_count"]
            == 0
        )


class TestEmptyPackageCannotBePresented:
    def test_a_package_with_no_options_cannot_reach_the_client(self, api):
        """There is nothing to quote, so the presentation is refused and the inquiry does not advance.

        PRD: A `BookingAgent` may present a package that is in `DRAFT` or in `REVISION_REQUESTED`, provided `options_count` is at least 1 — otherwise `ERR_PROPOSAL_NO_OPTIONS` — and provided the logical clock is strictly before `valid_until_utc`, an expired quotation being refused with `ERR_PROPOSAL_EXPIRED`.
        Design: Corner/errors/presenting_a_proposal_with_no_options_is_rejected
        """
        bundle = setup_qualified_inquiry(api)
        proposal = create_draft_proposal(api, bundle["inquiry"])
        assert proposal["options_count"] == 0

        validate_error(
            api.present_proposal(proposal["id"], AGENT_HEADERS),
            ApiErrorId.ERR_PROPOSAL_NO_OPTIONS.value,
            expected_status=409,
        )

        unchanged = read_proposal(api, proposal["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["presented_at_utc"] is None
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "QUALIFIED"


class TestSiblingUniquenessOnOptions:
    def _package_with_one_option(self, api) -> dict:
        bundle = setup_qualified_inquiry(api)
        bundle["proposal"] = create_draft_proposal(api, bundle["inquiry"])
        bundle["option"] = add_option(
            api, bundle["proposal"], bundle["speaker"], rank_no=1
        )
        bundle["second_speaker"] = create_second_speaker(api, topics=["AI_STRATEGY"])
        return bundle

    def test_requoting_the_same_speaker_reports_the_speaker_clash(self, api):
        """The same speaker on the same package fails on identity even though the rank also collides.

        PRD: Structurally, a package may carry at most four live options, so a fifth is refused with `ERR_OPTION_LIMIT_REACHED`; no sibling option on the same package may already quote the same `speaker_id`, or the request is refused with `ERR_DUPLICATE_SPEAKER_OPTION`; and no sibling may already use the same `rank_no`, or it is refused with `ERR_DUPLICATE_RANK`.
        Design: Corner/errors/duplicate_speaker_and_duplicate_rank_are_reported_separately
        """
        bundle = self._package_with_one_option(api)

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"], bundle["speaker"]["id"], rank_no=1
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_SPEAKER_OPTION.value,
            expected_status=409,
        )
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 1

    def test_a_fresh_speaker_on_a_used_rank_reports_the_rank_clash(self, api):
        """With the identity check satisfied the next constraint in the band is the presentation order.

        PRD: Structurally, a package may carry at most four live options, so a fifth is refused with `ERR_OPTION_LIMIT_REACHED`; no sibling option on the same package may already quote the same `speaker_id`, or the request is refused with `ERR_DUPLICATE_SPEAKER_OPTION`; and no sibling may already use the same `rank_no`, or it is refused with `ERR_DUPLICATE_RANK`.
        Design: Corner/errors/duplicate_speaker_and_duplicate_rank_are_reported_separately
        """
        bundle = self._package_with_one_option(api)

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["second_speaker"]["id"],
                    quoted_fee_cents=1_150_000,
                    rank_no=1,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RANK.value,
            expected_status=409,
        )
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 1

    def test_a_fresh_speaker_on_a_free_rank_is_admitted(self, api):
        """Neither sibling constraint bites once both the speaker and the rank are new.

        PRD: A new option starts in `OFFERED`; the enumeration continues `SELECTED`, `REJECTED` and the terminal `WITHDRAWN`.
        Design: Corner/errors/duplicate_speaker_and_duplicate_rank_are_reported_separately
        """
        bundle = self._package_with_one_option(api)

        option = validate_success(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"],
                    bundle["second_speaker"]["id"],
                    quoted_fee_cents=1_150_000,
                    rank_no=2,
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert option["status"] == "OFFERED"
        assert option["rank_no"] == 2
        assert read_proposal(api, bundle["proposal"]["id"])["options_count"] == 2


class TestClaimAdjudicationGuards:
    def _upheld_claim(self, api) -> dict:
        bundle = setup_delivered_engagement(api)
        claim = validate_success(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement"]["id"],
                    DIRECT_EVENT_DATE_UTC,
                    DIRECT_FEE_CENTS,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert claim["commission_due_cents"] == COMMISSION_DUE_CENTS
        bundle["uphold_response"] = validate_success(
            api.resolve_circumvention_claim(
                claim["id"], claim_resolution_payload("UPHOLD"), ADMIN_HEADERS
            )
        )
        bundle["claim"] = read_claim(api, claim["id"])
        return bundle

    def test_the_first_strike_upholds_the_claim_without_touching_the_credit_posture(
        self, api
    ):
        """One strike is below the two-strike threshold, so the client keeps its good standing.

        PRD: `UPHOLD` also requires the claim to be `OPEN`, drives `OPEN → UPHELD`, and sets off a four-hop cascade: the client's `circumvention_strikes` rises by one; upon reaching the threshold of 2 strikes the client's `credit_status` becomes `HOLD`; and because the posture became `HOLD`, every inquiry of that client whose `status` is `QUALIFIED` moves to `BLOCKED` — leaving inquiries in `RECEIVED` or `PROPOSED` alone, as noted in §3.2.
        Design: Corner/errors/resolving_a_claim_twice_and_over_settling_are_both_rejected
        """
        bundle = self._upheld_claim(api)

        assert bundle["claim"]["status"] == "UPHELD"
        assert bundle["claim"]["settled_cents"] is None

        client_row = read_client(api, bundle["client"]["id"])
        assert client_row["circumvention_strikes"] == 1
        assert client_row["credit_status"] == "GOOD"

    def test_settling_above_the_computed_commission_is_refused(self, api):
        """The settlement is bounded by what the claim itself computed, and the excess is a body-level refusal.

        PRD: `SETTLE` requires the claim to already be `UPHELD` and carries `settled_cents`, the amount actually collected, which must be at least 0 and no greater than the claim's `commission_due_cents`; a value outside that range is refused with `ERR_INVALID_REQUEST`.
        Design: Corner/errors/resolving_a_claim_twice_and_over_settling_are_both_rejected
        """
        bundle = self._upheld_claim(api)

        validate_error(
            api.resolve_circumvention_claim(
                bundle["claim"]["id"],
                claim_settlement_payload(300_000),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            expected_status=422,
        )

        unchanged = read_claim(api, bundle["claim"]["id"])
        assert unchanged["status"] == "UPHELD"
        assert unchanged["settled_cents"] is None
        assert unchanged["commission_due_cents"] == COMMISSION_DUE_CENTS

    def test_a_settled_claim_refuses_a_further_resolution(self, api):
        """Settlement is the end of the road, and re-adjudicating it answers with the claim's state error.

        PRD: Applying `UPHOLD` or `DISMISS` to a claim that is not `OPEN`, or `SETTLE` to a claim that is not `UPHELD`, is refused with `ERR_CLAIM_NOT_OPEN`.
        Design: Corner/errors/resolving_a_claim_twice_and_over_settling_are_both_rejected
        """
        bundle = self._upheld_claim(api)

        settled = validate_success(
            api.resolve_circumvention_claim(
                bundle["claim"]["id"],
                claim_settlement_payload(COMMISSION_DUE_CENTS),
                ADMIN_HEADERS,
            )
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_cents"] == COMMISSION_DUE_CENTS

        validate_error(
            api.resolve_circumvention_claim(
                bundle["claim"]["id"],
                claim_resolution_payload("UPHOLD"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_CLAIM_NOT_OPEN.value,
            expected_status=409,
        )
        assert read_claim(api, bundle["claim"]["id"])["status"] == "SETTLED"

        _rows, meta = validate_paginated(
            api.list_circumvention_claims(ADMIN_HEADERS, params={"status": "SETTLED"})
        )
        assert meta["total_count"] == 1
