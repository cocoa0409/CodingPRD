"""Arithmetic that hinges on which branch, which table and which inputs count.

The travel calculation short-circuits on a virtual delivery and consults an
entirely different set of constants under each policy code; the reimbursable
aggregate counts approved receipts only, and every downstream figure inherits
that filter; the cancellation ladder is a second constant table read at a pinned
order of steps; and a commission adjustment re-prices the provisional figure on
the spot.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    commission_adjustment_payload,
    create_speaker,
    find_invoices_for,
    find_remittances_for,
    read_client,
    read_engagement,
    read_speaker,
    read_travel_expense,
    set_clock,
    setup_cancelled_engagement,
    setup_contracted_engagement,
    setup_engagement_with_approved_travel,
    travel_expense_payload,
    travel_rejection_payload,
    validate_success,
)

POLICY_A = {"travel_policy_code": "POLICY_A"}
POLICY_B = {"travel_policy_code": "POLICY_B"}
STRICT_SCHEDULE = {"cancellation_schedule_code": "STRICT"}
ALLOWANCE_OPTION = {"travel_allowance_cents": 70_000}
VIRTUAL_INQUIRY = {"is_virtual": True}


class TestVirtualDeliveryShortCircuitsTravel:
    def test_the_virtual_flag_is_copied_from_the_enquiry_onto_the_engagement(
        self, api
    ):
        """The engagement snapshots the flag rather than pointing back at the enquiry for it.

        PRD: It records `inquiry_id`, `speaker_id` and `selected_option_id` for traceability, copies `owning_agent_user_id` from the inquiry so that segregation of duties has an anchor, copies `event_start_utc`, `event_end_utc` and `is_virtual` from the inquiry, and copies `quoted_fee_cents` and `travel_allowance_cents` from the selected option.
        Design: Corner/calculations/travel_reimbursable_is_zero_for_a_virtual_engagement
        """
        bundle = setup_contracted_engagement(
            api,
            inquiry_overrides=VIRTUAL_INQUIRY,
            contract_overrides=POLICY_A,
            option_overrides=ALLOWANCE_OPTION,
        )

        engagement = read_engagement(api, bundle["engagement"]["id"])
        assert engagement["is_virtual"] is True
        assert engagement["travel_allowance_cents"] == 70_000
        assert engagement["travel_reimbursable_cents"] == 0

    def test_a_virtual_engagement_reimburses_nothing_even_for_real_receipts(self, api):
        """Approval on a virtual booking pays 0, ignoring both the receipts and the negotiated allowance.

        PRD: If the engagement's `is_virtual` is true, `reimbursable_cents` is 0. No travel occurs for a virtual delivery, and no other input is even consulted.
        Design: Corner/calculations/travel_reimbursable_is_zero_for_a_virtual_engagement
        """
        bundle = setup_contracted_engagement(
            api,
            inquiry_overrides=VIRTUAL_INQUIRY,
            contract_overrides=POLICY_A,
            option_overrides=ALLOWANCE_OPTION,
        )
        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(
                    receipts_cents=30_000,
                    travel_days=1,
                    distance_band="LOCAL",
                    memo="home studio courier",
                ),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )

        approved = validate_success(
            api.approve_travel_expense(expense["id"], AGENT_HEADERS)
        )

        assert approved["status"] == "APPROVED"
        assert approved["reimbursable_cents"] == 0
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 0


class TestPolicyBIsAHardAllowanceCap:
    def test_the_allowance_caps_the_payout_and_the_distance_table_is_ignored(
        self, api
    ):
        """Three national days at a premium class still pay only the negotiated allowance.

        PRD: Otherwise the agreement is on `POLICY_B`, a hard allowance cap: the ceiling is simply the engagement's `travel_allowance_cents`, and `reimbursable_cents` is the lesser of `receipts_cents` and that ceiling. The distance schedule and the travel class are not consulted at all.
        Design: Corner/calculations/travel_policy_b_caps_at_the_allowance_and_ignores_the_distance_schedule
        """
        bundle = setup_contracted_engagement(
            api, contract_overrides=POLICY_B, option_overrides=ALLOWANCE_OPTION
        )
        assert bundle["speaker"]["travel_class"] == "PREMIUM"

        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(
                    receipts_cents=200_000,
                    travel_days=3,
                    distance_band="NATIONAL",
                    memo="flights and two nights",
                ),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )

        approved = validate_success(
            api.approve_travel_expense(expense["id"], AGENT_HEADERS)
        )

        assert approved["reimbursable_cents"] == 70_000
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 70_000


class TestPerformanceReadWithoutFeedback:
    def test_a_speaker_with_no_feedback_scores_null_rather_than_zero(self, api):
        """The empty weighted mean answers null, and the counter reports no ratings at all.

        PRD: Until the first feedback exists both `rolling_score` and `lifetime_score` are null; a computed performance read for a speaker with no feedback answers with a null `score` and a `feedback_count` of 0.
        Design: Corner/calculations/speaker_performance_with_no_feedback_returns_a_null_score
        """
        set_clock(api)
        speaker = create_speaker(api, topics=["AI_STRATEGY"])

        rolling = validate_success(
            api.get_speaker_performance(speaker["id"], ADMIN_HEADERS)
        )
        lifetime = validate_success(
            api.get_speaker_performance(
                speaker["id"], ADMIN_HEADERS, params={"variant": "LIFETIME"}
            )
        )

        assert rolling["score"] is None
        assert rolling["feedback_count"] == 0
        assert lifetime["score"] is None
        assert lifetime["feedback_count"] == 0

    def test_the_computed_read_reports_the_variant_the_tier_and_the_rate(self, api):
        """Both variants come back with the roster posture attached, and the default variant is the rolling one.

        PRD: That computed read returns six fields — `speaker_id`, the `variant` that was applied, the resulting `score`, `feedback_count`, `roster_tier` and `default_commission_pct` — and accepts a `variant` query parameter of `ROLLING` or `LIFETIME`, defaulting to `ROLLING`.
        Design: Corner/calculations/speaker_performance_with_no_feedback_returns_a_null_score
        """
        set_clock(api)
        speaker = create_speaker(api, topics=["AI_STRATEGY"])

        rolling = validate_success(
            api.get_speaker_performance(speaker["id"], ADMIN_HEADERS)
        )
        lifetime = validate_success(
            api.get_speaker_performance(
                speaker["id"], ADMIN_HEADERS, params={"variant": "LIFETIME"}
            )
        )

        assert rolling["speaker_id"] == speaker["id"]
        assert rolling["variant"] == "ROLLING"
        assert lifetime["variant"] == "LIFETIME"
        for row in (rolling, lifetime):
            assert row["roster_tier"] == "BRONZE"
            assert row["default_commission_pct"] == pytest.approx(0.25, abs=0.001)


class TestOnlyApprovedReceiptsReachTheLedger:
    def _approved_and_rejected_receipts(self, api):
        bundle = setup_engagement_with_approved_travel(
            api, contract_overrides=POLICY_A, option_overrides=ALLOWANCE_OPTION
        )
        rejected = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(
                    receipts_cents=40_000,
                    travel_days=1,
                    distance_band="LOCAL",
                    memo="unrelated dinner",
                ),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.reject_travel_expense(
                rejected["id"],
                travel_rejection_payload(rejection_reason="not covered by the rider"),
                AGENT_HEADERS,
            )
        )
        bundle["rejected_expense"] = read_travel_expense(api, rejected["id"])
        return bundle

    def test_a_rejected_receipt_adds_nothing_to_the_engagement_total(self, api):
        """The refused receipt keeps a null amount and leaves the running travel total on the approved figure alone.

        PRD: Rejection is a `BookingAgent` action on a `SUBMITTED` receipt, takes an optional `rejection_reason`, drives `SUBMITTED → REJECTED`, leaves `reimbursable_cents` null, and adds nothing whatever to the engagement's `travel_reimbursable_cents`.
        Design: Corner/calculations/invoice_travel_line_aggregates_only_approved_receipts
        """
        bundle = self._approved_and_rejected_receipts(api)

        assert bundle["travel_expense"]["status"] == "APPROVED"
        assert bundle["travel_expense"]["reimbursable_cents"] == 63_750
        assert bundle["rejected_expense"]["status"] == "REJECTED"
        assert bundle["rejected_expense"]["reimbursable_cents"] is None
        assert read_engagement(api, bundle["engagement"]["id"])[
            "travel_reimbursable_cents"
        ] == 63_750

    def test_the_invoice_travel_line_and_surcharge_use_the_filtered_total(self, api):
        """The travel line bills only the approved receipt, and each line is surcharged and rounded on its own.

        PRD: The processing surcharge is then computed at a rate of 1.75 percent — that is, 0.0175 — and the **order of operations is normative**: the server multiplies each of the three lines by the surcharge rate separately, rounds each of those three products half up to a whole number of cents, and only then adds the three rounded parts together to obtain `surcharge_cents`.
        Design: Corner/calculations/invoice_travel_line_aggregates_only_approved_receipts
        """
        bundle = self._approved_and_rejected_receipts(api)
        set_clock(api, "2026-10-15T20:00:00Z")
        validate_success(
            api.deliver_engagement(bundle["engagement"]["id"], AGENT_HEADERS)
        )

        invoices = find_invoices_for(api, bundle["engagement"]["id"])
        assert len(invoices) == 1
        invoice = invoices[0]

        assert invoice["fee_line_cents"] == 1_275_000
        assert invoice["recording_line_cents"] == 0
        assert invoice["travel_line_cents"] == 63_750
        assert invoice["surcharge_cents"] == 23_429
        assert invoice["amount_due_cents"] == 1_362_179
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 1_362_179

    def test_the_remittance_passes_through_only_the_approved_travel(self, api):
        """The payout carries the same filtered travel figure, and the three parts still reconcile to the invoice.

        PRD: Fourth, a `Remittance` is created in `status` `PENDING`, recording `engagement_id` and the payee as `speaker_id`, with `paid_at_utc` null. For a delivery, its `gross_fee_cents` is the commissionable base `quoted_fee_cents` plus `recording_fee_cents`; its `commission_cents` is the engagement's `final_commission_cents`; its `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, which is passed straight through to the speaker and is never commissioned; and its `net_payable_cents` is `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`.
        Design: Corner/calculations/invoice_travel_line_aggregates_only_approved_receipts
        """
        bundle = self._approved_and_rejected_receipts(api)
        set_clock(api, "2026-10-15T20:00:00Z")
        validate_success(
            api.deliver_engagement(bundle["engagement"]["id"], AGENT_HEADERS)
        )

        remittances = find_remittances_for(api, bundle["engagement"]["id"])
        assert len(remittances) == 1
        remittance = remittances[0]

        assert remittance["gross_fee_cents"] == 1_275_000
        assert remittance["commission_cents"] == 318_750
        assert remittance["travel_passthrough_cents"] == 63_750
        assert remittance["net_payable_cents"] == 1_020_000
        assert 1_020_000 + 318_750 + 23_429 == 1_362_179
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 1_020_000


class TestStrictLadderAtSixtyDays:
    def _cancelled_under_strict(self, api):
        return setup_cancelled_engagement(
            api,
            cancellation_clock_utc="2026-08-16T16:00:00Z",
            contract_overrides=STRICT_SCHEDULE,
            cancellation_reason="internal reorganisation",
        )

    def test_the_strict_ladder_still_retains_a_quarter_at_sixty_days_out(self, api):
        """Exactly sixty days out the strict schedule keeps a quarter of the fee where the standard one would keep nothing.

        PRD: Under `STRICT`: 60 or more days before the event still retains 0.25; from 21 to 59 days inclusive retains 0.75; fewer than 21 days retains 1.00.
        Design: Corner/calculations/cancellation_strict_ladder_at_sixty_days_retains_a_quarter
        """
        bundle = self._cancelled_under_strict(api)
        engagement = read_engagement(api, bundle["engagement"]["id"])

        assert engagement["booking_status"] == "CANCELLED_BY_CLIENT"
        assert engagement["cancellation_days_before"] == 60
        assert engagement["settlement_status"] == "INVOICED"
        assert engagement["retention_net_cents"] == 302_812

    def test_the_rebate_band_is_keyed_on_the_gross_and_the_commission_on_the_net(
        self, api
    ):
        """A gross retention inside the middle band earns five percent, and the commission is taken on what is left.

        PRD: `retention_commission_cents` is `retention_net_cents` multiplied by `commission_pct_snapshot`, rounded half up — the bureau commissions the **net** retention, never the gross.
        Design: Corner/calculations/cancellation_strict_ladder_at_sixty_days_retains_a_quarter
        """
        bundle = self._cancelled_under_strict(api)
        engagement = read_engagement(api, bundle["engagement"]["id"])

        assert engagement["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert engagement["retention_net_cents"] == 318_750 - 15_938
        assert engagement["retention_commission_cents"] == 75_703

    def test_the_retention_invoice_bills_the_net_with_no_recording_line(self, api):
        """The cancellation invoice carries a different line composition from a fee invoice.

        PRD: When `retention_net_cents` plus the engagement's `travel_reimbursable_cents` is greater than 0, an `Invoice` is issued with `kind` `CANCELLATION_RETENTION` and `status` `ISSUED`, and its line composition differs from a fee invoice: `fee_line_cents` is `retention_net_cents`, `recording_line_cents` is always 0 on a retention invoice, and `travel_line_cents` is again the engagement's `travel_reimbursable_cents`.
        Design: Corner/calculations/cancellation_strict_ladder_at_sixty_days_retains_a_quarter
        """
        bundle = self._cancelled_under_strict(api)
        invoice = bundle["retention_invoice"]

        assert invoice is not None
        assert invoice["kind"] == "CANCELLATION_RETENTION"
        assert invoice["status"] == "ISSUED"
        assert invoice["fee_line_cents"] == 302_812
        assert invoice["recording_line_cents"] == 0
        assert invoice["travel_line_cents"] == 0
        assert invoice["surcharge_cents"] == 5_299
        assert invoice["amount_due_cents"] == 308_111

    def test_the_retention_remittance_pays_the_net_less_its_commission(self, api):
        """The speaker's share of a cancellation is the net retention minus the commission struck on it.

        PRD: The settlement dimension moves `UNBILLED → INVOICED`, the client's `outstanding_balance_cents` grows by `amount_due_cents`, and a `Remittance` is created in `PENDING` whose `gross_fee_cents` is `retention_net_cents`, whose `commission_cents` is `retention_commission_cents`, whose `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, and whose `net_payable_cents` is again `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`; the speaker's `pending_remittance_cents` grows accordingly.
        Design: Corner/calculations/cancellation_strict_ladder_at_sixty_days_retains_a_quarter
        """
        bundle = self._cancelled_under_strict(api)

        remittances = find_remittances_for(api, bundle["engagement"]["id"])
        assert len(remittances) == 1
        remittance = remittances[0]

        assert remittance["status"] == "PENDING"
        assert remittance["gross_fee_cents"] == 302_812
        assert remittance["commission_cents"] == 75_703
        assert remittance["travel_passthrough_cents"] == 0
        assert remittance["net_payable_cents"] == 227_109
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 308_111
        assert read_speaker(api, bundle["speaker"]["id"])[
            "pending_remittance_cents"
        ] == 227_109


class TestCommissionAdjustmentAtTheFloorRate:
    def test_repricing_to_the_floor_rate_rewrites_the_provisional_figure(self, api):
        """The adjustment moves the snapshot to the lowest permitted rate and re-prices the provisional commission with it.

        PRD: An accepted adjustment overwrites `commission_pct_snapshot` with `new_commission_pct`, rewrites `provisional_commission_cents` using the provisional formula at the new rate — `quoted_fee_cents` multiplied by the new snapshot, rounded half up — and increments `commission_adjustment_count` by one.
        Design: Corner/calculations/commission_adjustment_at_the_minimum_rate_recomputes_provisional
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])
        assert before["provisional_commission_cents"] == 318_750
        assert before["commission_adjustment_count"] == 0

        adjusted = validate_success(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.10, before["version"]),
                ADMIN_HEADERS,
            )
        )

        assert adjusted["commission_pct_snapshot"] == pytest.approx(0.10, abs=0.001)
        assert adjusted["provisional_commission_cents"] == 127_500
        assert adjusted["commission_adjustment_count"] == 1

    def test_the_final_figure_is_untouched_and_the_engagement_version_moves_once(
        self, api
    ):
        """Only the provisional variant is rewritten, and the engagement records exactly one mutation.

        PRD: Almost all resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that resource — including mutations the server performs on its own initiative as a cascade, and including rewrites of purely derived fields.
        Design: Corner/calculations/commission_adjustment_at_the_minimum_rate_recomputes_provisional
        """
        bundle = setup_contracted_engagement(api)
        before = read_engagement(api, bundle["engagement"]["id"])

        validate_success(
            api.create_commission_adjustment(
                before["id"],
                commission_adjustment_payload(0.10, before["version"]),
                ADMIN_HEADERS,
            )
        )

        after = read_engagement(api, before["id"])
        assert after["version"] == before["version"] + 1
        assert after["final_commission_cents"] is None
        assert after["booking_status"] == "CONTRACTED"
