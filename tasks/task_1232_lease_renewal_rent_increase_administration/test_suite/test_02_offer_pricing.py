"""Renewal-offer pricing, notice tiering, and term staggering (PRD §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_renewal_offer,
    create_lease,
    create_offer_for_lease,
    create_offer_payload,
    create_policy,
    create_property,
    create_resident,
    create_unit,
    get_lease,
    setup_lease_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestMultiInputPricingClamps:
    """Market gap x strategy factor x term discount x statutory cap, plus the
    notice-tier branch on the resulting increase."""

    def _create_band18_balanced_offer(self, api):
        sc = setup_lease_scenario(
            band_min=18, band_max=18, market_rent_cents=220000,
            monthly_rent_cents=200000, property_name="Band-18 Court", unit_number="301",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="BALANCED"),
            LA1)
        return validate_success(resp, 201)

    def test_proposed_rent_multi_input_computation(self, api):
        """PRD §3.3: "First, the market gap: the amount by which the unit's
        `current_market_rent_cents` exceeds the lease's `monthly_rent_cents`, divided
        by the lease's `monthly_rent_cents` and expressed in basis points, rounded
        half-up to a whole basis point, and never below zero. Second, the strategy
        share: `AGGRESSIVE` captures one hundred percent of the gap, `BALANCED` sixty
        percent, and `CONSERVATIVE` thirty percent, with the product rounded half-up
        to a whole basis point. Third, a term discount rewards longer commitments:
        ten basis points for every month of `offered_term_months` beyond twelve,
        capped at one hundred eighty basis points and never below zero. Fourth, the
        discounted increase is the strategy share minus the term discount, never
        below zero. Fifth, the increase is capped at the applicable cap in basis
        points — for this provisional variant, the frozen `cap_bps_snapshot`. Sixth,
        the proposed rent is the lease's `monthly_rent_cents` grown by the capped
        increase, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/proposed_rent_multi_input_clamps
        """
        offer = self._create_band18_balanced_offer(api)
        assert_renewal_offer(offer)
        # gap 1000 bps x 0.6 = 600; term 18 -> discount 60; 540 <= cap 550.
        assert offer["proposed_rent_cents"] == 210800
        assert offer["proposed_increase_bps"] == 540
        assert offer["cap_bps_snapshot"] == 550
        assert offer["offered_term_months"] == 18

    def test_proposed_rent_multi_input_notice_tier(self, api):
        """PRD §3.3: "When `proposed_increase_bps` is strictly greater than the
        policy's `high_increase_threshold_bps`, `notice_days_required` takes the long
        period `notice_days_high`; an increase equal to or below the threshold takes
        `notice_days_low`. The `latest_issue_date` is then the lease's
        `term_end_date` minus the required notice days — or null when the lease is
        `MTM`, where no fixed term end exists and no statutory issue window applies."

        Design: Difficulty/combinatorial_formula/proposed_rent_multi_input_clamps
        """
        offer = self._create_band18_balanced_offer(api)
        # 540 bps > 500 threshold -> long 90-day tier; 2027-06-01 - 90d.
        assert offer["notice_days_required"] == 90
        assert offer["latest_issue_date"] == "2027-03-03"


class TestNoticeThresholdBoundary:
    def _create_threshold_offer(self, api):
        sc = setup_lease_scenario(
            band_min=12, band_max=12, market_rent_cents=210000,
            monthly_rent_cents=200000, property_name="Threshold Court", unit_number="901",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="AGGRESSIVE"),
            LA1)
        return validate_success(resp, 201)

    def test_increase_exactly_at_threshold_pricing(self, api):
        """PRD §3.3: "Second, the strategy share: `AGGRESSIVE` captures one hundred
        percent of the gap, `BALANCED` sixty percent, and `CONSERVATIVE` thirty
        percent, with the product rounded half-up to a whole basis point."

        Design: Difficulty/boundary_precision_check/increase_exactly_at_high_threshold_gets_low_notice
        """
        offer = self._create_threshold_offer(api)
        # gap = round_half_up(10000/200000 * 10000) = 500 bps; AGGRESSIVE x1.0.
        assert offer["proposed_rent_cents"] == 210000
        assert offer["proposed_increase_bps"] == 500

    def test_increase_exactly_at_threshold_gets_low_notice(self, api):
        """PRD §2.8: "The comparison is strict — an increase exactly equal to the
        threshold takes the short period."
        PRD §3.3: "The `latest_issue_date` is then the lease's `term_end_date` minus
        the required notice days — or null when the lease is `MTM`, where no fixed
        term end exists and no statutory issue window applies."

        Design: Difficulty/boundary_precision_check/increase_exactly_at_high_threshold_gets_low_notice
        """
        offer = self._create_threshold_offer(api)
        # 500 > 500 is false -> LOW tier 60 days; 2027-06-01 - 60d = 2027-04-02.
        assert offer["notice_days_required"] == 60
        assert offer["latest_issue_date"] == "2027-04-02"


class TestPricingCornerCases:
    def test_term_discount_capped_at_180(self, api):
        """PRD §3.3: "Third, a term discount rewards longer commitments: ten basis
        points for every month of `offered_term_months` beyond twelve, capped at one
        hundred eighty basis points and never below zero."

        Design: Corner/calculations/term_discount_capped_at_180
        """
        sc = setup_lease_scenario(
            band_min=36, band_max=36, market_rent_cents=220000,
            monthly_rent_cents=200000, property_name="Long Band Court", unit_number="301",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="BALANCED"),
            LA1)
        offer = validate_success(resp, 201)
        # (36-12)*10 = 240 would apply, but the 180 cap binds: 600 - 180 = 420.
        assert offer["offered_term_months"] == 36
        assert offer["proposed_increase_bps"] == 420
        assert offer["proposed_rent_cents"] == 208400

    def test_proposed_rent_round_half_up(self, api):
        """PRD §2.6: "Every calculation step that produces a stored value rounds
        half-up to a whole unit: basis-point intermediates round to a whole basis
        point, and rent results round to a whole cent."

        Design: Corner/calculations/proposed_rent_round_half_up
        """
        sc = setup_lease_scenario(
            band_min=12, band_max=12, market_rent_cents=200498,
            monthly_rent_cents=199998, property_name="Half Up Court", unit_number="H1",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="AGGRESSIVE"),
            LA1)
        offer = validate_success(resp, 201)
        # gap = round_half_up(500/199998*10000) = round_half_up(25.00025) = 25 bps;
        # rent = round_half_up(199998 * 1.0025) = round_half_up(200497.995) = 200498.
        assert offer["proposed_increase_bps"] == 25
        assert offer["proposed_rent_cents"] == 200498

    def test_offer_default_rate_strategy_balanced(self, api):
        """PRD §3.3: "The request may optionally name a `rate_strategy` —
        `AGGRESSIVE`, `BALANCED`, or `CONSERVATIVE` — which defaults to `BALANCED`
        when omitted."

        Design: Corner/entities/offer_default_rate_strategy_balanced
        """
        sc = setup_lease_scenario(
            band_min=18, band_max=18, market_rent_cents=220000,
            monthly_rent_cents=200000, property_name="Default Court", unit_number="103",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"]),  # no rate_strategy
            LA1)
        offer = validate_success(resp, 201)
        assert offer["rate_strategy"] == "BALANCED"
        # BALANCED drove pricing: gap 1000 x 0.6 = 600; discount 60 -> 540 bps.
        assert offer["proposed_rent_cents"] == 210800

    def test_invalid_enum_rate_strategy_rejected(self, api):
        """PRD §2.9: "Required fields must be present, types correct, enum members
        valid, dates well-formed `YYYY-MM-DD`, and integer ranges honored — for
        example `term_months` must be at least 1, a property's `min_term_months` must
        not exceed its `max_term_months`, a resident response's `response_type` must
        be one of `ACCEPT`, `DECLINE`, or `COUNTER`, a `COUNTER` response must carry
        a `counter_rent_cents` greater than zero, and a notice citing
        `LEASE_VIOLATION` must carry an `evidence_ref`. Any failure returns
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_enum_rate_strategy_rejected
        """
        sc = setup_lease_scenario(
            band_min=12, band_max=12, market_rent_cents=210000,
            property_name="Enum Court", unit_number="104",
        )
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="YOLO"),
            LA1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        offers, _meta = validate_paginated(
            api.list_renewal_offers(PM1, params={"lease_id": sc["lease"]["id"]}))
        assert offers == [], "no offer may be persisted on a schema failure"


class TestOfferInitialState:
    def test_offer_initial_state_draft(self, api):
        """PRD §3.3: "The lease's current `monthly_rent_cents` is captured as the
        offer's `base_rent_cents`, the policy's current `effective_cap_bps` is frozen
        onto the offer as `cap_bps_snapshot`, and `offer_round` starts at 1."
        PRD §3.3: "Offers begin life in `DRAFT` with `issued_on_date`,
        `issued_by_user_id`, `response_deadline_date`, `accepted_on_date`,
        `execution_deadline_date`, `executed_rent_cents`, `counter_rent_cents`, and
        `counter_term_months` all null."

        Design: Corner/state_machines/offer_initial_state_draft
        """
        sc = setup_lease_scenario(property_name="Initial Court", unit_number="201")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        assert offer["status"] == "DRAFT"
        assert offer["offer_round"] == 1
        assert offer["issued_on_date"] is None
        assert offer["response_deadline_date"] is None


class TestTermStaggering:
    def _stagger_fixture(self, api, property_name):
        """Property band [6,24]; subject lease 12mo (end 2027-06-01) plus blocker
        leases of 36mo (end 2029-06-01) and 30mo (end 2028-12-01)."""
        policy = create_policy()
        prop = create_property(policy["id"], min_term_months=6, max_term_months=24,
                               name=property_name)
        u1 = create_unit(prop["id"], unit_number="S1")
        u2 = create_unit(prop["id"], unit_number="S2")
        u3 = create_unit(prop["id"], unit_number="S3")
        r1 = create_resident(full_name="St Agger", email="st.agger@x.com")
        r2 = create_resident(full_name="Blo Cker1", email="blo.cker1@x.com")
        r3 = create_resident(full_name="Blo Cker2", email="blo.cker2@x.com")
        subject = create_lease(u1["id"], r1["id"], term_months=12)
        create_lease(u2["id"], r2["id"], term_months=36)
        create_lease(u3["id"], r3["id"], term_months=30)
        return prop, subject

    def test_staggering_selector_prefers_emptiest_month(self, api):
        """PRD §3.3: "The load on a candidate is the count of the property's other
        leases in `ACTIVE`, `RENEWAL_PENDING`, or `NON_RENEWAL_NOTICED` status whose
        `term_end_date` falls in the calendar month containing the projected end,
        plus the count of the property's open offers — those in `DRAFT`, `ISSUED`,
        `COUNTERED`, or `ACCEPTED` — whose own projected end falls in that same
        month. The subject lease and its own offers never contribute to the load.
        The candidate with the smallest load wins, and ties break in favor of the
        longer term."

        Design: Corner/calculations/staggering_selector_prefers_emptiest_month
        """
        _prop, subject = self._stagger_fixture(api, "Stagger Court")
        resp = api.create_renewal_offer(
            subject["id"],
            create_offer_payload(subject["version"], rate_strategy="CONSERVATIVE"),
            LA1)
        offer = validate_success(resp, 201)
        # t=24 lands 2029-06 (load 1 from the 36-month blocker), t=18 lands
        # 2028-12 (load 1 from the 30-month blocker); every other candidate is
        # load 0, and the longest-term tie-break among them picks 23.
        assert offer["offered_term_months"] == 23

    def test_staggering_tie_break_longest_term(self, api):
        """PRD §3.3: "The subject lease and its own offers never contribute to the
        load. The candidate with the smallest load wins, and ties break in favor of
        the longer term."

        Design: Corner/calculations/staggering_tie_break_longest_term
        """
        policy = create_policy()
        prop = create_property(policy["id"], min_term_months=6, max_term_months=24,
                               name="Tie Break Court")
        unit = create_unit(prop["id"], unit_number="T1")
        resident = create_resident(full_name="Ty Break", email="ty.break@x.com")
        lease = create_lease(unit["id"], resident["id"], term_months=12)
        resp = api.create_renewal_offer(
            lease["id"],
            create_offer_payload(lease["version"], rate_strategy="CONSERVATIVE"),
            LA1)
        offer = validate_success(resp, 201)
        # Only the subject lease exists; its own end never counts, so all
        # candidates tie at load 0 and the band maximum 24 wins.
        assert offer["offered_term_months"] == 24

    def test_expiration_forecast_counts(self, api):
        """PRD §3.8: "Given an optional `months_ahead`, it walks each calendar month
        from the current clock month forward through the requested horizon and
        reports two counts per month: the committed expirations — leases in
        `ACTIVE`, `RENEWAL_PENDING`, or `NON_RENEWAL_NOTICED` whose `term_end_date`
        falls in that month — and the projected expirations — open offers in
        `DRAFT`, `ISSUED`, `COUNTERED`, or `ACCEPTED` whose projected end per §3.3
        falls in that month. The response carries a `window_start` and a `months`
        array ordered by month ascending."

        Design: Corner/calculations/expiration_forecast_counts
        """
        prop, subject = self._stagger_fixture(api, "Forecast Court")
        resp = api.create_renewal_offer(
            subject["id"],
            create_offer_payload(subject["version"], rate_strategy="CONSERVATIVE"),
            LA1)
        offer = validate_success(resp, 201)
        assert offer["offered_term_months"] == 23  # projected end 2029-05-01

        data = validate_success(
            api.get_expiration_forecast(prop["id"], PM1, params={"months_ahead": 48}), 200)
        assert str(data["window_start"])[:7] == "2026-05"
        rows = {str(row["month"])[:7]: row for row in data["months"]}
        assert rows["2027-06"]["committed"] == 1   # subject lease end 2027-06-01
        assert rows["2027-06"]["projected"] == 0
        assert rows["2028-12"]["committed"] == 1   # 30-month blocker
        assert rows["2029-06"]["committed"] == 1   # 36-month blocker
        assert rows["2029-05"]["committed"] == 0
        assert rows["2029-05"]["projected"] == 1   # DRAFT offer's term-23 projection
        assert rows["2026-05"]["committed"] == 0
        assert rows["2026-05"]["projected"] == 0
