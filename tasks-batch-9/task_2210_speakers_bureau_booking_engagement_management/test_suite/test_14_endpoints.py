"""Endpoint surfaces: partial update, action endpoints, a computed read and links.

Each case here is about what one endpoint is contractually obliged to do: which
fields a PATCH may move, what a terminal action forecloses, what a derived read
reports, how a conditional release changes a later verdict, and how a three-way
link computes and locks its figures.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    circumvention_claim_payload,
    create_speaker,
    exclusivity_waiver_payload,
    find_holds_for_speaker,
    find_invoices_for,
    find_remittances_for,
    read_claim,
    read_engagement,
    read_grant,
    read_speaker,
    read_travel_expense,
    set_clock,
    setup_cancelled_engagement,
    setup_contracted_engagement,
    setup_delivered_engagement,
    setup_delivered_engagement_with_feedback,
    setup_exclusivity_grant_scenario,
    speaker_update_payload,
    travel_expense_payload,
    travel_rejection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECT_EVENT_DATE_UTC = "2026-12-14T18:00:00Z"
DIRECT_FEE_CENTS = 1_000_000
POLICY_A = {"travel_policy_code": "POLICY_A"}
ALLOWANCE_OPTION = {"travel_allowance_cents": 70_000}


class TestRosterMaintenanceUpdate:
    def test_a_partial_update_moves_only_the_supplied_terms(self, api):
        """The new fee range and travel class land, the version steps once and nothing else on the row moves.

        PRD: A `BureauAdmin` may revise `roster_status`, `tax_form_status`, `fee_floor_cents`, `fee_ceiling_cents`, `travel_class` and `travel_buffer_days` on an existing speaker; each such edit increments the speaker's `version` by one.
        Design: Corner/endpoints/patch_speaker_updates_the_fee_range_and_bumps_the_version
        """
        set_clock(api)
        speaker = create_speaker(api)
        assert speaker["version"] == 1

        updated = validate_success(
            api.update_speaker(speaker["id"], speaker_update_payload(), ADMIN_HEADERS)
        )
        assert updated["fee_floor_cents"] == 1_200_000
        assert updated["fee_ceiling_cents"] == 2_400_000
        assert updated["travel_class"] == "BUSINESS"
        assert updated["version"] == 2

        stored = read_speaker(api, speaker["id"])
        assert stored["full_name"] == "Dana Reyes"
        assert stored["topics"] == ["AI_STRATEGY", "LEADERSHIP"]
        assert stored["travel_buffer_days"] == 1
        assert stored["tax_form_status"] == "ON_FILE"
        assert stored["updated_at"] != stored["created_at"]

    def test_a_partial_update_never_re_tiers_the_speaker(self, api):
        """The tier and the commission rate are derived, so a terms edit leaves them and the counters alone.

        PRD: `roster_tier` and `default_commission_pct` are never writable this way — they are derived, and the only thing that moves them is the tiering rule.
        Design: Corner/endpoints/patch_speaker_updates_the_fee_range_and_bumps_the_version
        """
        set_clock(api)
        speaker = create_speaker(api)

        updated = validate_success(
            api.update_speaker(speaker["id"], speaker_update_payload(), ADMIN_HEADERS)
        )
        assert updated["roster_status"] == "ACTIVE"
        assert updated["roster_tier"] == "BRONZE"
        assert updated["default_commission_pct"] == pytest.approx(0.25, abs=0.001)

        stored = read_speaker(api, speaker["id"])
        assert stored["roster_tier"] == "BRONZE"
        assert stored["default_commission_pct"] == pytest.approx(0.25, abs=0.001)
        assert stored["engagements_delivered_count"] == 0
        assert stored["lifetime_gross_fees_cents"] == 0
        assert stored["feedback_count"] == 0


class TestTravelReceiptRejectionIsTerminal:
    def _submitted_receipt(self, api) -> dict:
        bundle = setup_contracted_engagement(
            api, contract_overrides=POLICY_A, option_overrides=ALLOWANCE_OPTION
        )
        bundle["expense"] = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )
        return bundle

    def test_a_rejected_receipt_keeps_a_null_amount_and_adds_nothing(self, api):
        """Refusing the receipt leaves its computed amount unwritten and the engagement's travel line at zero.

        PRD: Rejection is a `BookingAgent` action on a `SUBMITTED` receipt, takes an optional `rejection_reason`, drives `SUBMITTED → REJECTED`, leaves `reimbursable_cents` null, and adds nothing whatever to the engagement's `travel_reimbursable_cents`.
        Design: Corner/endpoints/travel_expense_reject_then_approve_is_refused_by_the_state_check
        """
        bundle = self._submitted_receipt(api)
        assert bundle["expense"]["status"] == "SUBMITTED"
        assert bundle["expense"]["reimbursable_cents"] is None

        rejected = validate_success(
            api.reject_travel_expense(
                bundle["expense"]["id"], travel_rejection_payload(), AGENT_HEADERS
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reimbursable_cents"] is None

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["travel_reimbursable_cents"] == 0

    def test_a_rejected_receipt_cannot_be_approved_afterwards(self, api):
        """Approval is declared only from SUBMITTED, so the terminal receipt answers with its own state error.

        PRD: The codes are `ERR_INQUIRY_STATE_INVALID`, `ERR_PROPOSAL_STATE_INVALID`, `ERR_ENGAGEMENT_STATE_INVALID`, `ERR_CONTRACT_STATE_INVALID`, `ERR_TRAVEL_EXPENSE_STATE_INVALID`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_REMITTANCE_NOT_APPROVED`, `ERR_CLAIM_NOT_OPEN` and `ERR_GRANT_NOT_ACTIVE`, all HTTP 409.
        Design: Corner/endpoints/travel_expense_reject_then_approve_is_refused_by_the_state_check
        """
        bundle = self._submitted_receipt(api)
        validate_success(
            api.reject_travel_expense(
                bundle["expense"]["id"], travel_rejection_payload(), AGENT_HEADERS
            )
        )

        validate_error(
            api.approve_travel_expense(bundle["expense"]["id"], AGENT_HEADERS),
            ApiErrorId.ERR_TRAVEL_EXPENSE_STATE_INVALID.value,
            expected_status=409,
        )

        still_rejected = read_travel_expense(api, bundle["expense"]["id"])
        assert still_rejected["status"] == "REJECTED"
        assert still_rejected["reimbursable_cents"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 0


class TestPerformanceComputedRead:
    def test_the_default_read_reports_the_rolling_figure_after_one_rating(self, api):
        """With a single candidate the truncated weight renormalises to one, so the rolling figure is the composite itself.

        PRD: `rolling_score` is the sum of each candidate's `composite_score` multiplied by its renormalised weight, rounded half up to two decimal places.
        Design: Corner/endpoints/performance_computed_read_reports_score_tier_and_default_rate
        """
        bundle = setup_delivered_engagement_with_feedback(api)
        assert bundle["feedback"]["composite_score"] == pytest.approx(4.60, abs=0.01)

        performance = validate_success(
            api.get_speaker_performance(
                bundle["speaker"]["id"], bundle["speaker_headers"]
            )
        )
        assert performance["speaker_id"] == bundle["speaker"]["id"]
        assert performance["variant"] == "ROLLING"
        assert performance["score"] == pytest.approx(4.60, abs=0.01)
        assert performance["feedback_count"] == 1

    def test_the_lifetime_read_coincides_with_the_rolling_one_at_a_single_rating(
        self, api
    ):
        """The equal-weight mean of one observation is that observation, so both variants answer 4.60.

        PRD: `lifetime_score` is the equal-weight arithmetic mean of `composite_score` across **all** candidates, rounded half up to two decimal places.
        Design: Corner/endpoints/performance_computed_read_reports_score_tier_and_default_rate
        """
        bundle = setup_delivered_engagement_with_feedback(api)

        lifetime = validate_success(
            api.get_speaker_performance(
                bundle["speaker"]["id"], ADMIN_HEADERS, params={"variant": "LIFETIME"}
            )
        )
        assert lifetime["variant"] == "LIFETIME"
        assert lifetime["score"] == pytest.approx(4.60, abs=0.01)
        assert lifetime["feedback_count"] == 1

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["rolling_score"] == pytest.approx(4.60, abs=0.01)
        assert speaker["lifetime_score"] == pytest.approx(4.60, abs=0.01)

    def test_a_high_score_alone_does_not_promote_the_speaker(self, api):
        """The silver gate wants two deliveries as well as the score, and only one delivery has happened.

        PRD: Both conditions of a tier must hold and the highest satisfied tier wins: `GOLD` requires `engagements_delivered_count` of at least 4 **and** a `rolling_score` of at least 4.50; `SILVER` requires `engagements_delivered_count` of at least 2 **and** a `rolling_score` of at least 4.00; otherwise the speaker is `BRONZE`, and a speaker whose `rolling_score` is still null is always `BRONZE`.
        Design: Corner/endpoints/performance_computed_read_reports_score_tier_and_default_rate
        """
        bundle = setup_delivered_engagement_with_feedback(api)

        performance = validate_success(
            api.get_speaker_performance(bundle["speaker"]["id"], ADMIN_HEADERS)
        )
        assert performance["roster_tier"] == "BRONZE"
        assert performance["default_commission_pct"] == pytest.approx(0.25, abs=0.001)

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["engagements_delivered_count"] == 1
        assert speaker["roster_tier"] == "BRONZE"
        assert speaker["default_commission_pct"] == pytest.approx(0.25, abs=0.001)


class TestExclusivityWaiver:
    def test_waiving_a_grant_releases_it_without_touching_its_window(self, api):
        """The release is a status move only: the effective window stays exactly as execution wrote it.

        PRD: A `BureauAdmin` may also deliberately release one, supplying an optional `waiver_reason`, which drives `ACTIVE → WAIVED` so the speaker can be confirmed for a competing client; waiving a grant that is already `EXPIRED` or `WAIVED` is refused with `ERR_GRANT_NOT_ACTIVE`.
        Design: Corner/endpoints/exclusivity_waiver_conditionally_unblocks_a_competing_confirmation
        """
        bundle = setup_exclusivity_grant_scenario(api)
        grant = bundle["grant"]
        assert grant["status"] == "ACTIVE"

        waived = validate_success(
            api.waive_exclusivity_grant(
                grant["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            )
        )
        assert waived["status"] == "WAIVED"
        assert waived["effective_from_utc"] == grant["effective_from_utc"]
        assert waived["effective_to_utc"] == grant["effective_to_utc"]
        assert waived["version"] == grant["version"] + 1

    def test_the_same_confirmation_is_refused_before_the_waiver_and_admitted_after(
        self, api
    ):
        """One competing confirmation, two verdicts: the screen only consults grants that are still ACTIVE.

        PRD: Only then does the exclusivity screen run over the surviving `ACTIVE` grants: if any grant for this same `speaker_id`, carrying the same `industry_code` as this engagement's client, and whose `beneficiary_client_id` is a *different* client, covers this engagement's `event_start_utc` within the half-open window running from `effective_from_utc` inclusive to `effective_to_utc` exclusive, the confirmation is refused with `ERR_EXCLUSIVITY_CONFLICT`.
        Design: Corner/endpoints/exclusivity_waiver_conditionally_unblocks_a_competing_confirmation
        """
        bundle = setup_exclusivity_grant_scenario(api)
        competing_id = bundle["competitor_engagement"]["id"]

        validate_error(
            api.confirm_engagement(competing_id, bundle["speaker_headers"]),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            expected_status=409,
        )
        assert read_engagement(api, competing_id)["booking_status"] == "OFFERED"

        validate_success(
            api.waive_exclusivity_grant(
                bundle["grant"]["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            )
        )

        confirmed = validate_success(
            api.confirm_engagement(competing_id, bundle["speaker_headers"])
        )
        assert confirmed["booking_status"] == "CONFIRMED"

        holds = find_holds_for_speaker(api, bundle["speaker"]["id"])
        engagement_holds = [
            hold
            for hold in holds
            if hold["kind"] == "ENGAGEMENT" and hold["status"] == "ACTIVE"
        ]
        assert len(engagement_holds) == 2
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 6

    def test_a_waiver_is_single_use(self, api):
        """The waiver endpoint is declared from ACTIVE only, so a second release is refused.

        PRD: A `BureauAdmin` may also deliberately release one, supplying an optional `waiver_reason`, which drives `ACTIVE → WAIVED` so the speaker can be confirmed for a competing client; waiving a grant that is already `EXPIRED` or `WAIVED` is refused with `ERR_GRANT_NOT_ACTIVE`.
        Design: Corner/endpoints/exclusivity_waiver_conditionally_unblocks_a_competing_confirmation
        """
        bundle = setup_exclusivity_grant_scenario(api)
        waived = validate_success(
            api.waive_exclusivity_grant(
                bundle["grant"]["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            )
        )

        validate_error(
            api.waive_exclusivity_grant(
                bundle["grant"]["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_GRANT_NOT_ACTIVE.value,
            expected_status=409,
        )

        after = read_grant(api, bundle["grant"]["id"])
        assert after["status"] == "WAIVED"
        assert after["version"] == waived["version"]


class TestCircumventionClaimLink:
    def _delivered_source(self, api) -> dict:
        bundle = setup_delivered_engagement(api)
        bundle["claim"] = validate_success(
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
        return bundle

    def test_a_new_claim_records_all_three_parties_and_opens_unsettled(self, api):
        """The filing is a three-way link, and filing alone adjudicates nothing.

        PRD: When a client books a speaker directly after the bureau introduced them, a `BureauAdmin` or `BookingAgent` opens a claim naming the `client_id` accused, the `speaker_id` rebooked, the `source_engagement_id` of the bureau-brokered engagement that opened the protection window, the `direct_event_date_utc` of the directly booked event, and the `direct_fee_cents` the client paid the speaker directly.
        Design: Corner/endpoints/circumvention_claim_links_client_speaker_and_source_engagement
        """
        bundle = self._delivered_source(api)
        claim = read_claim(api, bundle["claim"]["id"])

        assert claim["client_id"] == bundle["client"]["id"]
        assert claim["speaker_id"] == bundle["speaker"]["id"]
        assert claim["source_engagement_id"] == bundle["engagement"]["id"]
        assert claim["direct_fee_cents"] == DIRECT_FEE_CENTS
        assert claim["status"] == "OPEN"
        assert claim["settled_cents"] is None

        client_row = validate_success(
            api.get_client(bundle["client"]["id"], ADMIN_HEADERS)
        )
        assert client_row["circumvention_strikes"] == 0

    def test_the_day_count_runs_from_the_source_event_end(self, api):
        """Sixty whole days separate the delivered event's end from the directly booked date.

        PRD: `days_after_source` is the whole days from the source engagement's `event_end_utc` to `direct_event_date_utc`, computed as the difference in seconds divided by 86400 and floored; a direct event on or before the source engagement's end therefore gives a count of zero or less, which sits comfortably inside the full-protection band.
        Design: Corner/endpoints/circumvention_claim_links_client_speaker_and_source_engagement
        """
        bundle = self._delivered_source(api)

        assert bundle["engagement"]["event_end_utc"].startswith("2026-10-15T18:00:00")
        assert read_claim(api, bundle["claim"]["id"])["days_after_source"] == 60

    def test_the_commission_due_is_the_triple_product_at_full_protection(self, api):
        """Sixty days is inside the first six months, so the whole rate applies to the direct fee.

        PRD: `protection_factor` is 1.00 when `days_after_source` is at most 180 — the first six months — and 0.50 when `days_after_source` is greater than 180 but at most 365; a `days_after_source` greater than 365 means the protection has lapsed entirely and the claim is refused with `ERR_OUTSIDE_PROTECTION_WINDOW`. `commission_due_cents` is `direct_fee_cents` multiplied by the source engagement's `commission_pct_snapshot` multiplied by `protection_factor`, that single triple product rounded half up to a whole number of cents.
        Design: Corner/endpoints/circumvention_claim_links_client_speaker_and_source_engagement
        """
        bundle = self._delivered_source(api)
        claim = read_claim(api, bundle["claim"]["id"])

        assert bundle["engagement"]["commission_pct_snapshot"] == pytest.approx(
            0.25, abs=0.001
        )
        assert claim["protection_factor"] == pytest.approx(1.00, abs=0.001)
        assert claim["commission_due_cents"] == 250_000

    def test_a_second_filing_on_the_same_triple_is_refused(self, api):
        """The uniqueness key is the whole triple, and the first claim is still live.

        PRD: The source engagement must be `DELIVERED` and must carry a non-null `commission_pct_snapshot`, and at most one claim in `OPEN` or `UPHELD` may exist for any given combination of client, speaker and source engagement — a second is refused with `ERR_DUPLICATE_CLAIM`.
        Design: Corner/endpoints/circumvention_claim_links_client_speaker_and_source_engagement
        """
        bundle = self._delivered_source(api)

        validate_error(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement"]["id"],
                    "2026-12-20T18:00:00Z",
                    800_000,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_CLAIM.value,
            expected_status=409,
        )

        _rows, meta = validate_paginated(
            api.list_circumvention_claims(
                ADMIN_HEADERS,
                params={"source_engagement_id": bundle["engagement"]["id"]},
            )
        )
        assert meta["total_count"] == 1


class TestBureauCancellationTakesItsSideFromTheBody:
    def _bureau_cancelled_for_the_speaker(self, api) -> dict:
        return setup_cancelled_engagement(
            api,
            cancellation_clock_utc="2026-09-25T16:00:00Z",
            cancelled_by_headers_key="admin_headers",
            cancellation_reason="the speaker withdrew through the bureau",
            extra_cancel_fields={"on_behalf_of": "SPEAKER"},
        )

    def test_the_declared_side_and_not_the_caller_decides_the_branch(self, api):
        """A BureauAdmin acting for the speaker lands the speaker-side terminal state twenty days out.

        PRD: In every branch the server records `cancelled_by` from the acting side — `CLIENT` or `SPEAKER`, taken from `on_behalf_of` when a `BureauAdmin` acts — and records `cancellation_days_before` as the whole days from the logical clock to `event_start_utc`, computed as the difference in seconds divided by 86400 and floored.
        Design: Corner/endpoints/bureau_cancellation_takes_its_side_from_on_behalf_of
        """
        bundle = self._bureau_cancelled_for_the_speaker(api)
        engagement = bundle["engagement"]

        assert engagement["booking_status"] == "CANCELLED_BY_SPEAKER"
        assert engagement["cancelled_by"] == "SPEAKER"
        assert engagement["cancellation_days_before"] == 20

    def test_the_speaker_side_branch_bills_nothing_and_demotes_the_roster(self, api):
        """No retention, no paperwork downstream, and the speaker leaves the active roster.

        PRD: In both cases `cancelled_by` is `SPEAKER`, no retention is computed, the settlement dimension moves `UNBILLED → WAIVED`, and the speaker's `roster_status` moves `ACTIVE → PROBATION`, which immediately makes that speaker unquotable, unconfirmable and unable to sign until a `BureauAdmin` restores them.
        Design: Corner/endpoints/bureau_cancellation_takes_its_side_from_on_behalf_of
        """
        bundle = self._bureau_cancelled_for_the_speaker(api)

        assert bundle["engagement"]["settlement_status"] == "WAIVED"
        assert find_invoices_for(api, bundle["engagement"]["id"]) == []
        assert find_remittances_for(api, bundle["engagement"]["id"]) == []

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["roster_status"] == "PROBATION"
        assert speaker["held_days_count"] == 0
