"""Income reporting, agreement posture gates, commission variants, sunset rates,
settlement bounds, voids, adjustments, segregation of duties, and listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    add_rate_schedule,
    advance_clock,
    assert_income_event,
    confirm_engagement,
    create_approved_expense,
    create_hold_engagement,
    create_income_event_payload,
    create_verified_and_settled_event,
    create_and_verify_event,
    get_success_data,
    make_business_manager_headers,
    refresh_agreement,
    report_event,
    setup_artist_team,
    settle_event,
    settle_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_event,
)

ADMIN = TEST_USERS["firm_admin_headers"]


class TestAgreementPostureGate:
    def test_verify_against_draft_agreement_rejected(self, api):
        """PRD: "Verification requires the event to be `REPORTED` (`ERR_INVALID_STATE`
        otherwise), the resolved agreement to be in a commissionable posture —
        `ACTIVE`, `SUPERSEDED`, `TERMINATED`, `EXPIRED`, or `SUNSET`, with `DRAFT`
        and `CLOSED` rejected as `ERR_AGREEMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/income_verify_gated_on_agreement_posture
        """
        sc = setup_artist_team(stage_name="Gate Act", activate=False)
        assert sc["agreement"]["status"] == "DRAFT"
        event = report_event(sc, gross_amount_cents=200000,
                             recognition_date="2026-03-10", source_name="Promoter Ga")

        resp = api.verify_income_event(event["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "REPORTED"
        assert after["commission_amount_cents"] is None

    def test_verify_succeeds_after_activation(self, api):
        """PRD: "Verification requires the event to be `REPORTED` (`ERR_INVALID_STATE`
        otherwise), the resolved agreement to be in a commissionable posture —
        `ACTIVE`, `SUPERSEDED`, `TERMINATED`, `EXPIRED`, or `SUNSET`, with `DRAFT`
        and `CLOSED` rejected as `ERR_AGREEMENT_NOT_ACTIVE`"
        PRD: "When the recognition date is on or before the effective end,
        `term_relation` is `IN_TERM` and `applied_rate_bps` is the schedule's
        `in_term_rate_bps`."

        Design: Difficulty/cross_entity_state_dependency/income_verify_gated_on_agreement_posture
        """
        sc = setup_artist_team(stage_name="Gate Act 2", activate=False)
        event = report_event(sc, gross_amount_cents=200000,
                             recognition_date="2026-03-10", source_name="Promoter Ga")
        activate_agreement(sc["agreement"]["id"])

        verified = validate_success(api.verify_income_event(event["id"], sc["bm_headers"]))
        assert verified["status"] == "VERIFIED"
        assert verified["term_relation"] == "IN_TERM"
        assert verified["applied_rate_bps"] == 1500
        assert verified["commission_amount_cents"] == 30000
        assert verified["artist_net_cents"] == 170000
        assert verified["applied_schedule_id"] == sc["schedules"]["TOURING"]["id"]


class TestTouringCommissionBaseVariants:
    def _setup_variant_artist(self, api, stage_name, touring_base):
        """Artist with a CONFIRMED engagement, a 30000 APPROVED engagement-linked
        expense, and a REPORTED 200000 TOURING event linked to the engagement."""
        sc = setup_artist_team(stage_name=stage_name, primary_genre="rock",
                                   touring_commission_base=touring_base,
                                   bm_cap=1000000)
        engagement = create_hold_engagement(
            sc, start="2026-09-10T18:00:00Z", end="2026-09-10T23:00:00Z",
            buffer_hours=0, guarantee_cents=200000, counterparty_name="Promoter G")
        confirm_engagement(sc, engagement["id"])
        expense = create_approved_expense(
            sc, 30000, category="PRODUCTION", incurred_date="2026-03-10",
            description="Backline", engagement_id=engagement["id"])
        assert expense["status"] == "APPROVED"
        event = report_event(sc, gross_amount_cents=200000,
                             recognition_date="2026-03-10", source_name="Promoter G",
                             linked_engagement_id=engagement["id"])
        return sc, engagement, event

    def test_gross_base_touring_commission(self, api):
        """PRD: "For a concrete reading: a gross of 200000 with 30000 of approved
        engagement expenses and a 1500-basis-point rate yields a commission of
        30000 under `GROSS` but 25500 under `NET_OF_EXPENSES`."

        Design: Difficulty/dual_variant_calc/touring_commission_gross_vs_net_of_expenses
        """
        sc, _engagement, event = self._setup_variant_artist(api, "Gross Act", "GROSS")
        verified = validate_success(api.verify_income_event(event["id"], sc["bm_headers"]))
        assert verified["commission_amount_cents"] == 30000, (
            "GROSS base: commission is the full gross times the rate"
        )
        assert verified["artist_net_cents"] == 170000
        assert verified["applied_rate_bps"] == 1500

    def test_net_of_expenses_base_touring_commission(self, api):
        """PRD: "when the agreement's `touring_commission_base` is `NET_OF_EXPENSES`
        and the event is a `TOURING` event linked to an engagement, the base is
        reduced by the sum of `amount_cents` over that engagement's expenses in
        `APPROVED` or `REIMBURSED` status — pending and rejected expenses are
        excluded — and the result is floored at zero."
        PRD: "For a concrete reading: a gross of 200000 with 30000 of approved
        engagement expenses and a 1500-basis-point rate yields a commission of
        30000 under `GROSS` but 25500 under `NET_OF_EXPENSES`."

        Design: Difficulty/dual_variant_calc/touring_commission_gross_vs_net_of_expenses
        """
        sc_net, _eng_n, event_net = self._setup_variant_artist(
            api, "Net Act", "NET_OF_EXPENSES")
        verified_net = validate_success(
            api.verify_income_event(event_net["id"], sc_net["bm_headers"]))
        assert verified_net["commission_amount_cents"] == 25500, (
            "NET_OF_EXPENSES base: (200000 - 30000) x 1500bps"
        )
        assert verified_net["artist_net_cents"] == 174500

        sc_gross, _eng_g, event_gross = self._setup_variant_artist(
            api, "Gross Act 2", "GROSS")
        verified_gross = validate_success(
            api.verify_income_event(event_gross["id"], sc_gross["bm_headers"]))
        assert verified_gross["gross_amount_cents"] == verified_net["gross_amount_cents"]
        assert verified_gross["applied_rate_bps"] == verified_net["applied_rate_bps"]
        assert (verified_gross["commission_amount_cents"]
                - verified_net["commission_amount_cents"]) == 4500, (
            "The commissions differ by exactly 1500bps of the 30000 expense"
        )


class TestSunsetRates:
    def _setup_terminated_artist(self, api, stage_name, termination_date="2026-06-15"):
        sc = setup_artist_team(stage_name=stage_name)
        get_success_data(api.terminate_agreement(sc["agreement"]["id"],
                                                 termination_date, ADMIN))
        return sc

    def test_sunset_rate_applies_inside_sunset_window(self, api):
        """PRD: "Otherwise the sunset test runs: the sunset end for this income
        type is the effective end plus the schedule's `sunset_months` calendar
        months (calendrical arithmetic — a month added to January 31 lands on
        February 28), and the event is inside the window when its recognition date
        is on or before that sunset end."
        PRD: "Only when both conditions hold does the event take `term_relation`
        `SUNSET` at the schedule's `sunset_rate_bps`"
        PRD: "`sunset_end_date` is `sunset_start_date` plus the largest
        `sunset_months` found among the agreement's rate schedules, minus one day"

        Design: Corner/calculations/sunset_rate_applies_inside_sunset_window
        """
        sc = self._setup_terminated_artist(api, "Sun Act")
        event = report_event(sc, gross_amount_cents=200000,
                             recognition_date="2027-03-01", source_name="Royalty flow")

        verified = validate_success(api.verify_income_event(event["id"], sc["bm_headers"]))
        assert verified["term_relation"] == "SUNSET"
        assert verified["applied_rate_bps"] == 750
        assert verified["commission_amount_cents"] == 15000, "200000 x 750bps"
        assert verified["artist_net_cents"] == 185000

        agreement = get_success_data(api.get_agreement(sc["agreement"]["id"], ADMIN))
        assert agreement["sunset_start_date"] == "2026-06-16"
        assert agreement["sunset_end_date"] == "2027-06-15", (
            "termination 2026-06-15 + 12 months - 1 day, window opened 2026-06-16"
        )

    def test_post_term_exempt_after_sunset_end(self, api):
        """PRD: "Only when both conditions hold does the event take `term_relation`
        `SUNSET` at the schedule's `sunset_rate_bps`; otherwise it is
        `POST_TERM_EXEMPT` with an `applied_rate_bps` of 0."
        PRD: "an agreement whose sunset window has already passed for this income
        type still resolves, and the event simply verifies as exempt."

        Design: Corner/calculations/post_term_exempt_after_sunset_end
        """
        sc = self._setup_terminated_artist(api, "Post Act")
        # Sunset window runs 2026-06-16..2027-06-15; this recognition is one day past.
        event = report_event(sc, gross_amount_cents=200000,
                             recognition_date="2027-06-16", source_name="Late royalty")

        verified = validate_success(api.verify_income_event(event["id"], sc["bm_headers"]))
        assert verified["term_relation"] == "POST_TERM_EXEMPT"
        assert verified["applied_rate_bps"] == 0
        assert verified["commission_amount_cents"] == 0
        assert verified["artist_net_cents"] == 200000, (
            "Zero commission is still a VERIFIED event, not an error"
        )

    def test_sunset_linked_engagement_must_be_confirmed_in_term(self, api):
        """PRD: "The deal itself counts as in-term when the event has no
        `linked_engagement_id`, or when the linked engagement's `confirmed_at`
        date-part is on or before the effective end. Only when both conditions hold
        does the event take `term_relation` `SUNSET` at the schedule's
        `sunset_rate_bps`; otherwise it is `POST_TERM_EXEMPT` with an
        `applied_rate_bps` of 0."

        Design: Corner/calculations/sunset_linked_engagement_must_be_confirmed_in_term
        """
        sc = setup_artist_team(stage_name="Link Sun", primary_genre="rock")
        # Confirmed at the default clock 2026-08-01, before termination.
        eng_old = create_hold_engagement(
            sc, start="2026-12-10T18:00:00Z", end="2026-12-10T23:00:00Z",
            buffer_hours=0, counterparty_name="Venue Old")
        confirm_engagement(sc, eng_old["id"])
        get_success_data(api.terminate_agreement(sc["agreement"]["id"],
                                                 "2026-08-15", ADMIN))
        advance_clock("2026-08-20T00:00:00Z")
        # Confirmed at 2026-08-20, after the termination date.
        eng_new = create_hold_engagement(
            sc, start="2027-01-10T18:00:00Z", end="2027-01-10T23:00:00Z",
            buffer_hours=0, counterparty_name="Venue New")
        confirm_engagement(sc, eng_new["id"])

        ev_old = report_event(sc, gross_amount_cents=200000,
                              recognition_date="2026-12-20",
                              source_name="Venue Old payout",
                              linked_engagement_id=eng_old["id"])
        ev_new = report_event(sc, gross_amount_cents=200000,
                              recognition_date="2026-12-20",
                              source_name="Venue New payout",
                              linked_engagement_id=eng_new["id"])

        verified_old = validate_success(api.verify_income_event(ev_old["id"],
                                                                sc["bm_headers"]))
        assert verified_old["term_relation"] == "SUNSET"
        assert verified_old["commission_amount_cents"] == 15000, (
            "Engagement confirmed 2026-08-01 <= termination 2026-08-15"
        )

        verified_new = validate_success(api.verify_income_event(ev_new["id"],
                                                                sc["bm_headers"]))
        assert verified_new["term_relation"] == "POST_TERM_EXEMPT"
        assert verified_new["commission_amount_cents"] == 0, (
            "Engagement confirmed after the term's effective end"
        )


class TestIncomeEventLifecycleErrors:
    def test_settle_from_reported_returns_invalid_state(self, api):
        """PRD: "Settling — again a `BusinessManager` action — is allowed from
        `VERIFIED` or `POSTED`"
        PRD: "State-machine preconditions — the target is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`"

        Design: Corner/state_machines/settle_from_reported_returns_invalid_state
        """
        sc = setup_artist_team(stage_name="Rep Act")
        event = report_event(sc, gross_amount_cents=100000,
                             recognition_date="2026-03-10", source_name="PRe")

        resp = api.settle_income_event(
            event["id"], settle_payload("2026-03-12", 100000), sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "REPORTED"
        assert after["received_amount_cents"] is None

    def test_income_event_create_without_covering_agreement(self, api):
        """PRD: "At creation the server resolves and pins `agreement_id`: among
        the artist's agreements whose `term_start_date` is on or before the
        recognition date, the one with the greatest `term_start_date` wins, with
        ties broken by the earliest `created_at`."
        PRD: "When no agreement qualifies, creation fails with
        `ERR_NO_COVERING_AGREEMENT`."

        Design: Corner/validations/income_event_create_without_covering_agreement
        """
        sc = setup_artist_team(stage_name="Old Act", primary_genre="jazz")
        resp = api.create_income_event(
            create_income_event_payload(sc["artist"]["id"],
                                        gross_amount_cents=100000,
                                        recognition_date="2025-06-01",
                                        source_name="Ancient promoter"),
            sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_AGREEMENT)
        _data, meta = validate_paginated(
            api.list_income_events(ADMIN, params={"artist_id": sc["artist"]["id"]}))
        assert meta["total_count"] == 0, "No income event may be persisted"

    def test_verify_without_matching_rate_schedule(self, api):
        """PRD: "a rate schedule for the agreement and income type whose effective
        window covers the recognition date (`ERR_NO_RATE_SCHEDULE`)"

        Design: Corner/validations/verify_without_matching_rate_schedule
        """
        sc = setup_artist_team(stage_name="NoRate Act", income_types=("TOURING",))
        event = report_event(sc, gross_amount_cents=100000,
                             recognition_date="2026-03-10", income_type="ENDORSEMENT",
                             source_name="Brand")

        resp = api.verify_income_event(event["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_RATE_SCHEDULE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "REPORTED"
        assert after["applied_schedule_id"] is None

    def test_void_settled_event_rejected(self, api):
        """PRD: "An event that has reached `SETTLED` or `POSTED` can never be
        voided — the attempt fails with `ERR_EVENT_ALREADY_SETTLED`, and
        corrections must instead be filed as an `ADJUSTMENT` child event."

        Design: Corner/validations/void_settled_event_rejected
        """
        sc = setup_artist_team(stage_name="Void Act")
        event = create_verified_and_settled_event(
            sc, gross_amount_cents=200000, recognition_date="2026-03-10",
            received_date="2026-03-12")

        resp = api.void_income_event(event["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_SETTLED)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "SETTLED"
        assert after["commission_amount_cents"] == 30000

    def test_adjustment_event_requires_settled_parent(self, api):
        """PRD: "`kind`, defaulting to `ORIGINAL`, may be `ADJUSTMENT` for
        corrections, in which case `parent_event_id` must point at an event
        already in `SETTLED` or `POSTED` — a missing parent or a parent in any
        other state is rejected with `ERR_ADJUSTMENT_PARENT_INVALID`."

        Design: Corner/validations/adjustment_event_requires_settled_parent
        """
        sc = setup_artist_team(stage_name="Adj Act")
        parent = report_event(sc, gross_amount_cents=200000,
                              recognition_date="2026-03-10", source_name="PAd")

        resp = api.create_income_event(
            create_income_event_payload(sc["artist"]["id"],
                                        gross_amount_cents=50000,
                                        recognition_date="2026-03-15",
                                        source_name="PAd correction",
                                        kind="ADJUSTMENT",
                                        parent_event_id=parent["id"]),
            sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_PARENT_INVALID)

    def test_settle_amount_out_of_range_both_sides(self, api):
        """PRD: "the received amount must be greater than zero, no greater than
        `gross_amount_cents`, and no less than `commission_amount_cents`, or the
        request fails with `ERR_AMOUNT_OUT_OF_RANGE`."

        Design: Corner/validations/settle_amount_out_of_range_both_sides
        """
        sc = setup_artist_team(stage_name="Range Act")
        event = create_and_verify_event(sc, gross_amount_cents=200000,
                                        recognition_date="2026-03-10")
        assert event["commission_amount_cents"] == 30000

        resp_low = api.settle_income_event(
            event["id"], settle_payload("2026-03-12", 25000), sc["bm_headers"])
        validate_error(resp_low, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE)

        resp_high = api.settle_income_event(
            event["id"], settle_payload("2026-03-12", 200001), sc["bm_headers"])
        validate_error(resp_high, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "VERIFIED"
        assert after["received_amount_cents"] is None

    def test_sod_income_reporter_cannot_self_verify(self, api):
        """PRD: "Verification is the `BusinessManager`'s desk and is deliberately
        separated from reporting: the caller's identity must differ from
        `reported_by_user_id`, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_income_reporter_cannot_self_verify
        """
        sc = setup_artist_team(stage_name="Dual Act", with_agent=False)
        bm2 = get_success_data(api.create_team_member(
            {"artist_id": sc["artist"]["id"], "member_role": "BUSINESS_MANAGER",
             "display_name": "BM Two", "window_start_date": "2026-01-01"}, ADMIN))
        event = report_event(sc, gross_amount_cents=100000,
                             recognition_date="2026-03-10", source_name="PDu",
                             reporter="bm")

        resp = api.verify_income_event(event["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(api.verify_income_event(
            event["id"], make_business_manager_headers(bm2["id"])))
        assert verified["status"] == "VERIFIED"
        assert verified["commission_amount_cents"] == 15000


class TestIncomeListingAndConsistency:
    def test_income_event_list_pagination_and_filter(self, api):
        """PRD: "Income events can be listed by `artist_id`, `agreement_id`,
        `linked_engagement_id`, `parent_event_id`, `statement_id`,
        `recoup_statement_id`, `applied_schedule_id`, `status`, and
        `income_type`."
        PRD: "The `meta` object of list responses carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/income_event_list_pagination_and_filter
        """
        sc = setup_artist_team(stage_name="List Act")
        for gross, day in ((100000, "2026-03-05"), (200000, "2026-03-06"),
                           (300000, "2026-03-07")):
            report_event(sc, gross_amount_cents=gross, recognition_date=day,
                         source_name=f"P{day[-1]}")

        page1, meta1 = validate_paginated(api.list_income_events(
            sc["agent_headers"],
            params={"artist_id": sc["artist"]["id"], "income_type": "TOURING",
                    "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert isinstance(meta1["api_request_id"], str)
        assert isinstance(meta1["api_request_timestamp"], str)

        page2, meta2 = validate_paginated(api.list_income_events(
            sc["agent_headers"],
            params={"artist_id": sc["artist"]["id"], "income_type": "TOURING",
                    "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        for event in page1 + page2:
            assert event["artist_id"] == sc["artist"]["id"]
            assert event["status"] == "REPORTED"
            assert_income_event(event)

    def test_immediate_consistency_read_after_write(self, api):
        """PRD: "The commission itself is computed once, per event, and never
        re-derived."
        PRD: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        sc = setup_artist_team(stage_name="Imm Act", income_types=("RECORDING",))
        event = report_event(sc, gross_amount_cents=300000,
                             recognition_date="2026-02-10", income_type="RECORDING",
                             source_name="Label")

        verified = validate_success(api.verify_income_event(event["id"],
                                                            sc["bm_headers"]))
        assert verified["commission_amount_cents"] == 60000, "20% of 300000"
        assert verified["artist_net_cents"] == 240000

        fetched = validate_success(api.get_income_event(event["id"], sc["bm_headers"]))
        assert fetched["commission_amount_cents"] == verified["commission_amount_cents"]
        assert fetched["artist_net_cents"] == verified["artist_net_cents"]
        assert fetched["applied_rate_bps"] == 2000
        assert fetched["term_relation"] == "IN_TERM"
