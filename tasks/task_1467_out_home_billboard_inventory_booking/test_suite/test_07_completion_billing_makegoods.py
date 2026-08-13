"""Flight completion, campaign billing dimension, make-goods, and ledgers."""
from test_helpers import (
    FA,
    OA,
    SM,
    SP,
    ApiErrorId,
    api_client,
    append_impression_entry,
    confirm_flight,
    create_advertiser,
    create_campaign,
    create_face_with_permit,
    create_make_good_payload,
    create_published_rate_card,
    get_success_data,
    hold_flight,
    make_finance_analyst_headers,
    make_operations_auditor_headers,
    report_posting,
    set_clock,
    setup_art_cleared_flight,
    setup_booked_flight,
    setup_held_flight,
    setup_live_flight,
    submit_and_approve_campaign,
    validate_error,
    validate_success,
    verify_posting,
)


class TestParallelStatusBillingDimensions:

    def test_invoice_while_active_keeps_dimensions_independent(self):
        """PRD section 3.4: "Billing runs on a parallel dimension,
        `billing_status`, independent of `status`. A `FinanceAnalyst` moves
        `UNINVOICED` → `INVOICED` only while the campaign's `status` is
        `ACTIVE` or `COMPLETED`, otherwise `ERR_INVALID_STATE`, and moves
        `INVOICED` → `SETTLED` only when zero make-goods across all of the
        campaign's flights remain in `PROPOSED` or `APPROVED`, otherwise
        `ERR_UNRESOLVED_MAKE_GOODS`."
        PRD section 3.7: "When no successor flight on the face holds a
        verified posting, the flight slips into `HOLDOVER` — the copy is still
        up beyond its paid window — and the campaign posture recomputes to
        `AT_RISK`."

        Design: Difficulty/non_linear_state_machine/campaign_parallel_status_billing_dimensions
        """
        bundle = setup_live_flight()
        campaign_id = bundle["campaign"]["id"]

        invoiced = validate_success(api_client.update_campaign(
            campaign_id, {"billing_status": "INVOICED"}, FA), 200)
        assert invoiced["status"] == "ACTIVE"
        assert invoiced["billing_status"] == "INVOICED"

        set_clock("2026-09-07T00:00:00Z")  # end_date + 1: LIVE -> HOLDOVER
        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "HOLDOVER"
        campaign = validate_success(api_client.get_campaign(campaign_id, SP), 200)
        assert campaign["billing_status"] == "INVOICED", (
            f"the end-of-flight sweep must not disturb the billing "
            f"dimension: got {campaign['billing_status']}"
        )

    def test_takedown_completion_leaves_billing_untouched(self):
        """PRD section 3.7: "Completion prices the overstay: holdover days run
        from the day after `end_date` through the clock's current date,
        `holdover_weeks` is that day count divided by seven and rounded up,
        and `holdover_charge_cents` is the number of holdover weeks multiplied
        by the premium weekly rate — `pinned_weekly_cents` increased by ten
        percent (a multiplier of 1.10), rounded half-up to whole cents."
        PRD section 3.4: "Completion is likewise automatic: once every flight
        of the campaign has reached `COMPLETED`, `CANCELLED`, `EXPIRED`, or
        `RELEASED`, the campaign moves `ACTIVE` → `COMPLETED`, and at that
        moment each `COMPLETED` flight is evaluated for an under-delivery
        make-good per §3.9."
        PRD section 3.4: "The `contracted_cents` ledger sums `gross_cents`
        plus `holdover_charge_cents` over flights in `BOOKED`, `ART_CLEARED`,
        `LIVE`, `MISSED`, `HOLDOVER`, and `COMPLETED`; flights in `HELD`,
        `EXPIRED`, `RELEASED`, or `CANCELLED` never count, and cancellation
        fees never count."

        Design: Difficulty/non_linear_state_machine/campaign_parallel_status_billing_dimensions
        """
        bundle = setup_live_flight()
        campaign_id = bundle["campaign"]["id"]
        validate_success(api_client.update_campaign(
            campaign_id, {"billing_status": "INVOICED"}, FA), 200)

        set_clock("2026-09-07T00:00:00Z")
        completed = validate_success(api_client.update_flight(
            bundle["flight"]["id"],
            {"status": "COMPLETED", "takedown_confirmed": True},
            make_operations_auditor_headers("auditor-1"),
        ), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["holdover_weeks"] == 1, (
            f"one holdover day (2026-09-07) ceils to one week: "
            f"got {completed['holdover_weeks']}"
        )
        assert completed["holdover_charge_cents"] == 316_250, (
            f"1 week at round_half_up(287500 x 1.10) = 316250: "
            f"got {completed['holdover_charge_cents']}"
        )

        campaign = validate_success(api_client.get_campaign(campaign_id, SP), 200)
        assert campaign["status"] == "COMPLETED", (
            f"all flights terminal bubbles up to the campaign: "
            f"got {campaign['status']}"
        )
        assert campaign["billing_status"] == "INVOICED", (
            f"the billing dimension is not reset by completion: "
            f"got {campaign['billing_status']}"
        )
        assert campaign["contracted_cents"] == 1_466_250, (
            f"1150000 gross + 316250 holdover: expected 1466250, "
            f"got {campaign['contracted_cents']}"
        )


class TestHoldoverBillingVariant:

    def test_holdover_billing_variant_two_weeks(self):
        """PRD section 3.7: "A `HOLDOVER` flight completes in two ways: manual
        takedown confirmation by an `OperationsAuditor`, which requires
        `takedown_confirmed` to be true and is rejected with
        `ERR_INVALID_REQUEST` otherwise, or the same successor-verification
        cascade. Completion prices the overstay: holdover days run from the
        day after `end_date` through the clock's current date,
        `holdover_weeks` is that day count divided by seven and rounded up,
        and `holdover_charge_cents` is the number of holdover weeks multiplied
        by the premium weekly rate — `pinned_weekly_cents` increased by ten
        percent (a multiplier of 1.10), rounded half-up to whole cents."

        Design: Corner/calculations/holdover_billing_variant_two_weeks
        """
        bundle = setup_live_flight(campaign_end="2026-10-31")
        set_clock("2026-09-07T00:00:00Z")
        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "HOLDOVER", (
            f"end_date + 1 with no verified successor posting slips into "
            f"HOLDOVER: got {flight['status']}"
        )

        set_clock("2026-09-16T00:00:00Z")
        completed = validate_success(api_client.update_flight(
            bundle["flight"]["id"],
            {"status": "COMPLETED", "takedown_confirmed": True},
            make_operations_auditor_headers("auditor-1"),
        ), 200)
        assert completed["holdover_weeks"] == 2, (
            f"10 holdover days (2026-09-07..2026-09-16) ceil to 2 weeks: "
            f"got {completed['holdover_weeks']}"
        )
        assert completed["holdover_charge_cents"] == 632_500, (
            f"2 x 316250: expected 632500, "
            f"got {completed['holdover_charge_cents']}"
        )

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["contracted_cents"] == 1_782_500, (
            f"1150000 gross + 632500 holdover: expected 1782500, "
            f"got {campaign['contracted_cents']}"
        )


class TestCampaignSettleGate:

    def _setup_late_posting_with_makegood(self):
        """ART_CLEARED flight swept to MISSED at start+3 days, then verified
        late: MISSED -> LIVE with an auto MISSED_POSTING make-good."""
        bundle = setup_art_cleared_flight()
        set_clock("2026-08-13T00:00:00Z")  # start_date + 3 days: ART_CLEARED -> MISSED
        posting = report_posting(bundle["flight"]["id"], posted_on="2026-08-13",
                                 photo_proof_url="https://proof.example/late.jpg")
        verify_posting(posting["id"])
        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "LIVE"
        assert flight["missed_days"] == 3
        validate_success(api_client.update_campaign(
            bundle["campaign"]["id"], {"billing_status": "INVOICED"}, FA), 200)
        return bundle

    def test_settle_blocked_while_makegood_proposed(self):
        """PRD section 3.6: "When `posted_on` is later than two days after
        `start_date`, the flight moves `MISSED` → `LIVE` as a late posting:
        `missed_days` is set to the days elapsed from `start_date` to
        `posted_on`, and a make-good with reason `MISSED_POSTING` is
        auto-created in `PROPOSED` with `proposed_by` set to `system` and
        credit per §3.9."
        PRD section 3.9: "For `MISSED_POSTING`, the credit is the flight's
        `pinned_weekly_cents` multiplied by `missed_days` and divided by
        seven, rounded half-up; when a `MISSED` flight is cancelled,
        `missed_days` is the full booked length of `weeks` times seven, so the
        credit equals the entire `gross_cents`."
        PRD section 3.4: "A `FinanceAnalyst` moves `UNINVOICED` → `INVOICED`
        only while the campaign's `status` is `ACTIVE` or `COMPLETED`,
        otherwise `ERR_INVALID_STATE`, and moves `INVOICED` → `SETTLED` only
        when zero make-goods across all of the campaign's flights remain in
        `PROPOSED` or `APPROVED`, otherwise `ERR_UNRESOLVED_MAKE_GOODS`."

        Design: Difficulty/cross_entity_state_dependency/campaign_settle_gated_by_makegood_resolution
        """
        bundle = self._setup_late_posting_with_makegood()
        mgs = get_success_data(api_client.list_flight_make_goods(
            bundle["flight"]["id"], FA))
        assert len(mgs) == 1
        mg = mgs[0]
        assert mg["reason"] == "MISSED_POSTING"
        assert mg["status"] == "PROPOSED"
        assert mg["proposed_by"] == "system"
        assert mg["credit_cents"] == 123_214, (
            f"round_half_up(287500 x 3/7): expected 123214, "
            f"got {mg['credit_cents']}"
        )

        blocked = api_client.update_campaign(
            bundle["campaign"]["id"], {"billing_status": "SETTLED"}, FA)
        validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_MAKE_GOODS)

    def test_apply_lands_credit_and_unblocks_settle(self):
        """PRD section 3.9: "Applying (the `APPROVED` → `APPLIED` transition)
        adds `credit_cents` to the advertiser account's
        `credit_balance_cents` — the advertiser is resolved by following the
        flight's `campaign_id` to its campaign's `advertiser_id` — and
        recomputes the campaign's `delivery_posture`. Only `APPLIED` credits
        enter the balance ledger."
        PRD section 3.9: "Approval (the `PROPOSED` → `APPROVED` transition)
        enforces the segregation rule of §2.11: when `proposed_by` holds a
        user id, the approver must be a different user, otherwise
        `ERR_SEGREGATION_OF_DUTIES`; system-proposed credits may be approved
        by any finance analyst."

        Design: Difficulty/cross_entity_state_dependency/campaign_settle_gated_by_makegood_resolution
        """
        bundle = self._setup_late_posting_with_makegood()
        mgs = get_success_data(api_client.list_flight_make_goods(
            bundle["flight"]["id"], FA))
        mg = mgs[0]

        approved = validate_success(api_client.update_make_good(
            mg["id"], {"status": "APPROVED"},
            make_finance_analyst_headers("fin-1"),
        ), 200)
        assert approved["status"] == "APPROVED"
        applied = validate_success(api_client.update_make_good(
            mg["id"], {"status": "APPLIED"},
            make_finance_analyst_headers("fin-1"),
        ), 200)
        assert applied["status"] == "APPLIED"

        account = validate_success(
            api_client.get_advertiser(bundle["advertiser"]["id"], FA), 200)
        assert account["credit_balance_cents"] == 123_214, (
            f"the applied credit lands on the advertiser ledger: expected "
            f"123214, got {account['credit_balance_cents']}"
        )

        settled = validate_success(api_client.update_campaign(
            bundle["campaign"]["id"], {"billing_status": "SETTLED"}, FA), 200)
        assert settled["billing_status"] == "SETTLED"


class TestConfirmThenCancelInvariant:

    def test_confirm_then_cancel_restores_contracted_to_zero(self):
        """PRD section 3.5: "Cancelling a flight out of `BOOKED` or
        `ART_CLEARED` (a `SalesPlanner` action) charges a tiered fee on the
        days between the clock's current date and the flight's `start_date`:
        at least 28 days out, the fee is ten percent of `gross_cents`; from 14
        to 27 days out, twenty-five percent; under 14 days, fifty percent. The
        fee is recorded on the flight as `cancellation_fee_cents` and
        accumulated into the campaign's `cancellation_fees_cents` — never into
        `contracted_cents` — while contracted, net, and exposure ledgers
        recompute and the face's occupancy is freed."

        Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_contracted
        """
        bundle = setup_booked_flight()  # confirmed at clock 2026-08-01
        campaign_id = bundle["campaign"]["id"]
        mid = validate_success(api_client.get_campaign(campaign_id, SP), 200)
        assert mid["contracted_cents"] == 1_150_000

        cancelled = validate_success(api_client.update_flight(
            bundle["flight"]["id"], {"status": "CANCELLED"}, SP), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 575_000, (
            f"2026-08-10 start is 9 days after the 2026-08-01 clock: the "
            f"under-14-days tier charges 50% of gross 1150000; "
            f"got {cancelled['cancellation_fee_cents']}"
        )

        after = validate_success(api_client.get_campaign(campaign_id, SP), 200)
        assert after["contracted_cents"] == 0, (
            f"contracted must return to zero exactly after the cancel: "
            f"got {after['contracted_cents']}"
        )

    def test_cancellation_fee_tracked_separately_from_contracted(self):
        """PRD section 3.4: "Fees accumulate instead in
        `cancellation_fees_cents`, tracked separately."
        PRD section 3.4: "Exposure is a computed ledger: it sums `net_cents`
        across the advertiser's flights in `BOOKED`, `ART_CLEARED`, `LIVE`,
        `MISSED`, or `HOLDOVER`, and adds those flights'
        `holdover_charge_cents` on top."

        Design: Difficulty/compensating_invariant/confirm_then_cancel_restores_contracted
        """
        bundle = setup_booked_flight()
        validate_success(api_client.update_flight(
            bundle["flight"]["id"], {"status": "CANCELLED"}, SP), 200)

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["cancellation_fees_cents"] == 575_000, (
            f"the fee accumulates in its own ledger, not in contracted: "
            f"got {campaign['cancellation_fees_cents']}"
        )
        assert campaign["contracted_cents"] == 0

        account = validate_success(
            api_client.get_advertiser(bundle["advertiser"]["id"], FA), 200)
        assert account["exposure_cents"] == 0, (
            f"a CANCELLED flight leaves the exposure ledger: expected 0, "
            f"got {account['exposure_cents']}"
        )


class TestCancellationFeeTiers:

    def test_cancellation_fee_tier_boundaries(self):
        """PRD section 3.5: "Cancelling a flight out of `BOOKED` or
        `ART_CLEARED` (a `SalesPlanner` action) charges a tiered fee on the
        days between the clock's current date and the flight's `start_date`:
        at least 28 days out, the fee is ten percent of `gross_cents`; from 14
        to 27 days out, twenty-five percent; under 14 days, fifty percent. The
        fee is recorded on the flight as `cancellation_fee_cents` and
        accumulated into the campaign's `cancellation_fees_cents` — never into
        `contracted_cents` — while contracted, net, and exposure ledgers
        recompute and the face's occupancy is freed."

        Design: Corner/calculations/cancellation_fee_tier_boundaries
        """
        card = create_published_rate_card()
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], start_date="2026-08-01",
                                   end_date="2026-10-31")
        specs = {
            "F-2A": ("2026-08-29", "2026-09-25"),  # 28 days out at cancel
            "F-2B": ("2026-08-28", "2026-09-24"),  # 27 days out
            "F-2C": ("2026-08-14", "2026-09-10"),  # 13 days out
        }
        flights = {}
        for code, (start, end) in specs.items():
            face, _permit = create_face_with_permit(
                face_code=code, illuminated=False, daily_traffic_count=50_000,
                permit_number=f"P-{code}",
            )
            flights[code] = hold_flight(campaign["id"], face["id"], card["id"],
                                        start_date=start, end_date=end)
        submit_and_approve_campaign(campaign["id"])
        for fl in flights.values():
            confirm_flight(fl["id"], campaign["id"])

        cancelled = {}
        for code, fl in flights.items():
            cancelled[code] = validate_success(api_client.update_flight(
                fl["id"], {"status": "CANCELLED"}, SP), 200)

        # clock is still 2026-08-01; gross per flight is 800000
        assert cancelled["F-2A"]["cancellation_fee_cents"] == 80_000, (
            f"28 days out bills 10%: got "
            f"{cancelled['F-2A']['cancellation_fee_cents']}"
        )
        assert cancelled["F-2B"]["cancellation_fee_cents"] == 200_000, (
            f"27 days out bills 25%: got "
            f"{cancelled['F-2B']['cancellation_fee_cents']}"
        )
        assert cancelled["F-2C"]["cancellation_fee_cents"] == 400_000, (
            f"13 days out bills 50%: got "
            f"{cancelled['F-2C']['cancellation_fee_cents']}"
        )

        campaign_after = validate_success(
            api_client.get_campaign(campaign["id"], SP), 200)
        assert campaign_after["cancellation_fees_cents"] == 680_000


class TestUnderDeliveryAccounting:

    def _setup_completed_with_shortfall(self):
        """LIVE flight with four weekly AUDIENCE_MEASURED entries of 2000000,
        then completed by manual takedown at end_date + 1."""
        bundle = setup_live_flight()
        fl = bundle["flight"]["id"]
        for period_start, period_end in (
            ("2026-08-10", "2026-08-16"), ("2026-08-17", "2026-08-23"),
            ("2026-08-24", "2026-08-30"), ("2026-08-31", "2026-09-06"),
        ):
            append_impression_entry(fl, period_start, period_end,
                                    "AUDIENCE_MEASURED", 2_000_000)
        set_clock("2026-09-07T00:00:00Z")
        completed = validate_success(api_client.update_flight(
            fl, {"status": "COMPLETED", "takedown_confirmed": True},
            make_operations_auditor_headers("auditor-1"),
        ), 200)
        return bundle, completed

    def test_under_delivery_ratio_and_posture(self):
        """PRD section 3.8: "The delivered total is the sum of the per-period
        values, and `delivery_ratio` is `delivered_impressions` divided by
        `estimated_impressions`, rounded half-up to 4 decimal places — and 0
        when no entries exist at all."
        PRD section 3.4: "Finally, `delivery_posture` compounds delivery
        health: it is `UNDER_DELIVERED` when any `COMPLETED` flight has a
        `delivery_ratio` below 0.9; otherwise `AT_RISK` when any flight sits
        in `MISSED` or `HOLDOVER`, has `suspension_started_at` set, or carries
        `suspension_days_accrued` above zero; otherwise `ON_TRACK`."

        Design: Corner/calculations/under_delivery_make_good_at_completion
        """
        bundle, completed = self._setup_completed_with_shortfall()
        assert completed["status"] == "COMPLETED"
        assert completed["delivered_impressions"] == 8_000_000
        assert completed["delivery_ratio"] == 0.8503, (
            f"8000000 / 9408000 rounded half-up to 4 decimals: expected "
            f"0.8503, got {completed['delivery_ratio']}"
        )

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["delivery_posture"] == "UNDER_DELIVERED", (
            f"a COMPLETED flight at ratio 0.8503 < 0.9 tips the campaign: "
            f"got {campaign['delivery_posture']}"
        )

    def test_under_delivery_manual_proposal_computes_credit(self):
        """PRD section 3.9: "An `OperationsAuditor` may additionally propose
        one manually — but only with reason `UNDER_DELIVERY` and only against
        a `COMPLETED` flight; the manual record is born `PROPOSED` with
        `proposed_by` set to the auditor's `X-User-ID`."
        PRD section 3.9: "For `UNDER_DELIVERY`, the guarantee is ninety
        percent (0.90) of `estimated_impressions`, and a credit exists only
        when `delivered_impressions` falls below that guarantee at completion;
        the credit base is the booked net — `gross_cents` reduced by the
        flight's locked `discount_pct`, rounded half-up, excluding holdover
        charges — and the credit is that base multiplied by the shortfall (the
        guarantee minus the delivered impressions) and divided by the
        guarantee, rounded half-up."
        PRD section 3.9: "The `credit_cents` amount is always computed
        server-side from the flight's economics — it is never accepted from
        the request body — and no credit ever exceeds the flight's
        `gross_cents`, the cap applied after rounding."

        Design: Corner/calculations/under_delivery_make_good_at_completion
        """
        bundle, completed = self._setup_completed_with_shortfall()
        resp = api_client.create_make_good(
            create_make_good_payload(completed["id"], reason="UNDER_DELIVERY"),
            make_operations_auditor_headers("auditor-1"),
        )
        mg = validate_success(resp, 201)
        assert mg["status"] == "PROPOSED"
        assert mg["reason"] == "UNDER_DELIVERY"
        assert mg["proposed_by"] == "auditor-1"
        # guarantee 8467200 = 0.90 x 9408000; shortfall 467200;
        # base = booked net 1150000 (locked discount 0, holdover excluded);
        # credit = round_half_up(1150000 x 467200 / 8467200).
        assert mg["credit_cents"] == 63_454, (
            f"expected 63454, got {mg['credit_cents']}"
        )


class TestCampaignSubmitGate:

    def test_campaign_submit_requires_held_flight_rejected(self):
        """PRD section 3.4: "Submitting (the `DRAFT` → `SUBMITTED` transition,
        by a `SalesPlanner`) requires at least one flight of the campaign to
        be sitting in `HELD`, otherwise `ERR_CAMPAIGN_EMPTY`."

        Design: Corner/state_machines/campaign_submit_requires_held_flight_rejected
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])
        resp = api_client.update_campaign(
            campaign["id"], {"status": "SUBMITTED"}, SP)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_EMPTY)
        reread = validate_success(api_client.get_campaign(campaign["id"], SP), 200)
        assert reread["status"] == "DRAFT"


class TestCampaignCreationDefaults:

    def test_campaign_creation_defaults(self):
        """PRD section 3.4: "A new campaign is born `DRAFT` with
        `billing_status` `UNINVOICED` and `delivery_posture` `ON_TRACK`."
        PRD section 3.4: "The `contracted_cents` ledger sums `gross_cents`
        plus `holdover_charge_cents` over flights in `BOOKED`, `ART_CLEARED`,
        `LIVE`, `MISSED`, `HOLDOVER`, and `COMPLETED`; flights in `HELD`,
        `EXPIRED`, `RELEASED`, or `CANCELLED` never count, and cancellation
        fees never count. Fees accumulate instead in
        `cancellation_fees_cents`, tracked separately."

        Design: Corner/entities/campaign_creation_defaults
        """
        advertiser = create_advertiser()
        campaign = validate_success(api_client.create_campaign(
            {
                "advertiser_id": advertiser["id"],
                "name": "C1",
                "start_date": "2026-08-01",
                "end_date": "2026-09-30",
            },
            SP,
        ), 201)
        assert campaign["status"] == "DRAFT"
        assert campaign["billing_status"] == "UNINVOICED"
        assert campaign["delivery_posture"] == "ON_TRACK"
        assert campaign["contracted_cents"] == 0
        assert campaign["cancellation_fees_cents"] == 0
