"""Negotiation loop gates, concession authority tiers, and SoD (PRD §3.4–§3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_concession,
    get_offer,
    make_resident_headers,
    respond_counter_payload,
    set_clock,
    setup_countered_offer_scenario,
    setup_issued_offer_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]
LA2 = TEST_USERS["la_2_headers"]
RD1 = TEST_USERS["rd_1_headers"]


class TestRespondAndReviseGuards:
    def test_counter_term_outside_band_rejected(self, api):
        """PRD §3.4: "It must carry a `counter_rent_cents` greater than zero and may
        carry an optional `counter_term_months`; a countered term outside the
        property's staggering band is rejected with
        `ERR_TERM_OUTSIDE_STAGGERING_BAND`."

        Design: Corner/validations/counter_term_outside_band_rejected
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="BALANCED", band_min=18, band_max=18,
            market_rent_cents=220000, property_name="Band Gate", unit_number="B1")
        resp = api.respond_to_offer(
            sc["offer"]["id"],
            respond_counter_payload(205000, counter_term_months=99),
            make_resident_headers(sc["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TERM_OUTSIDE_STAGGERING_BAND)
        offer = get_offer(sc["offer"]["id"])
        assert offer["status"] == "ISSUED"
        assert offer["counter_term_months"] is None

    def test_revise_below_proposed_without_approval_rejected(self, api):
        """PRD §3.4: "If the revised rent is below the current `proposed_rent_cents`,
        an `APPROVED` concession approval for this offer whose `requested_rent_cents`
        exactly equals the revised rent must already exist, else
        `ERR_CONCESSION_APPROVAL_REQUIRED`."
        PRD §3.4: "The revision takes optional `revised_rent_cents` and
        `revised_term_months`: the rent defaults to the resident's
        `counter_rent_cents` and the term defaults to the current
        `offered_term_months` when omitted."

        Design: Corner/validations/revise_below_proposed_without_approval_rejected
        """
        sc = setup_countered_offer_scenario(
            counter_rent_cents=205000, property_name="Gate Court", unit_number="G1")
        # Empty payload -> revised rent defaults to the countered 205000, which is
        # below proposed 210800 and has no APPROVED approval behind it.
        resp = api.revise_offer(sc["offer"]["id"], {}, LA1)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_APPROVAL_REQUIRED)
        offer = get_offer(sc["offer"]["id"])
        assert offer["status"] == "COUNTERED"
        assert offer["offer_round"] == 1

    def test_revise_above_cap_rejected(self, api):
        """PRD §3.4: "The recomputed increase over `base_rent_cents` must fit within
        the policy's *current* `effective_cap_bps`, else `ERR_RENT_CAP_EXCEEDED`."

        Design: Corner/validations/revise_above_cap_rejected
        """
        sc = setup_countered_offer_scenario(
            counter_rent_cents=205000, property_name="Cap Court", unit_number="C1")
        # 212000 over base 200000 is 600 bps > current effective cap 550.
        resp = api.revise_offer(sc["offer"]["id"], {"revised_rent_cents": 212000}, LA1)
        validate_error(resp, ApiErrorId.ERR_RENT_CAP_EXCEEDED)
        offer = get_offer(sc["offer"]["id"])
        assert offer["status"] == "COUNTERED"
        assert offer["proposed_rent_cents"] == 210800


class TestPriorityPairs:
    def test_state_beats_cap_on_revise_wrong_state_error(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline, and
        the first failing stage wins: the response reports exactly one error, drawn
        from the earliest stage that fails."
        PRD §3.4: "Staff close a counter by issuing a revised round on the
        `COUNTERED` offer — revising an offer in any other state returns
        `ERR_OFFER_NOT_COUNTERED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_cap_on_revise_wrong_state
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="BALANCED", band_min=18, band_max=18,
            market_rent_cents=220000, property_name="Priority Court", unit_number="801")
        # The offer is ISSUED (state failure) AND 212000 implies 600 bps > cap 550
        # (rent-cap failure). The state stage runs before the statutory cap stage.
        resp = api.revise_offer(sc["offer"]["id"], {"revised_rent_cents": 212000}, LA1)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_COUNTERED)

    def test_state_beats_cap_on_revise_offer_unchanged(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline, and
        the first failing stage wins: the response reports exactly one error, drawn
        from the earliest stage that fails."
        PRD §3.4: "Staff close a counter by issuing a revised round on the
        `COUNTERED` offer — revising an offer in any other state returns
        `ERR_OFFER_NOT_COUNTERED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_cap_on_revise_wrong_state
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="BALANCED", band_min=18, band_max=18,
            market_rent_cents=220000, property_name="Priority Court", unit_number="801")
        api.revise_offer(sc["offer"]["id"], {"revised_rent_cents": 212000}, LA1)
        offer = get_offer(sc["offer"]["id"])
        assert offer["status"] == "ISSUED"
        assert offer["proposed_rent_cents"] == 210800

    def _window_missed_fixture(self, api):
        sc = setup_issued_offer_scenario(
            rate_strategy="BALANCED", band_min=18, band_max=18,
            market_rent_cents=220000, property_name="Window Court", unit_number="802")
        # The fixture issued at the default clock; re-issue inside the window near
        # its close: rebuild at clock 2027-02-20 instead.
        return sc

    def _window_missed_countered(self, api):
        # Offer proposed 210800 -> 540 bps > 500 -> high tier, latest_issue
        # 2027-03-03. Issue at 2027-02-20 (in window); counter; then advance to
        # 2027-03-04 (past the high-tier window, before response deadline).
        from test_helpers import (create_offer_for_lease, issue_offer,
                                  resident_counter, setup_lease_scenario)
        sc = setup_lease_scenario(
            band_min=18, band_max=18, market_rent_cents=220000,
            monthly_rent_cents=200000, property_name="Window Court", unit_number="802")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="BALANCED")
        set_clock("2027-02-20T00:00:00Z")
        offer = issue_offer(offer["id"])
        assert offer["response_deadline_date"] == "2027-03-06"
        offer = resident_counter(offer["id"], sc["resident"]["id"], 205000)
        assert offer["status"] == "COUNTERED"
        set_clock("2027-03-04T00:00:00Z")
        return sc, offer

    def test_temporal_beats_term_band_on_revise_error(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline, and
        the first failing stage wins: the response reports exactly one error, drawn
        from the earliest stage that fails."
        PRD §3.4: "And when the recomputed increase crosses into the high-notice
        tier, the clock date must be no later than the lease's `term_end_date` minus
        `notice_days_high`, else `ERR_NOTICE_WINDOW_MISSED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_term_band_on_revise
        """
        _sc, offer = self._window_missed_countered(api)
        # 211000 -> 550 bps crosses into the high tier after its window closed
        # (2027-03-04 > 2027-03-03); term 99 is also outside the [18,18] band.
        # Statutory temporal windows run before domain constraints.
        resp = api.revise_offer(
            offer["id"], {"revised_rent_cents": 211000, "revised_term_months": 99}, LA1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_MISSED)

    def test_temporal_beats_term_band_on_revise_offer_unchanged(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline, and
        the first failing stage wins: the response reports exactly one error, drawn
        from the earliest stage that fails."
        PRD §3.4: "And when the recomputed increase crosses into the high-notice
        tier, the clock date must be no later than the lease's `term_end_date` minus
        `notice_days_high`, else `ERR_NOTICE_WINDOW_MISSED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_term_band_on_revise
        """
        _sc, offer = self._window_missed_countered(api)
        api.revise_offer(
            offer["id"], {"revised_rent_cents": 211000, "revised_term_months": 99}, LA1)
        after = get_offer(offer["id"])
        assert after["status"] == "COUNTERED"
        assert after["proposed_rent_cents"] == 210800
        assert after["offered_term_months"] == 18


class TestConcessionSubmission:
    def test_concession_absolute_max_at_submit_rejected(self, api):
        """PRD §3.5: "At submission the system computes `concession_bps`: the
        difference between the offer's current `proposed_rent_cents` and the
        `requested_rent_cents`, divided by the `proposed_rent_cents`, expressed in
        basis points and rounded half-up. A request whose implied discount exceeds
        the absolute ceiling of 2,000 basis points is refused on the spot with
        `ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX`."

        Design: Corner/validations/concession_absolute_max_at_submit_rejected
        """
        sc = setup_countered_offer_scenario(
            counter_rent_cents=168618, property_name="Deep Cut Court", unit_number="D1")
        # (210800 - 168618) / 210800 -> round_half_up(2001.04...) = 2001 > 2000.
        resp = api.create_concession_approval(
            sc["offer"]["id"], {"requested_rent_cents": 168618, "reason": "too deep"}, LA1)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX)
        concessions, _meta = validate_paginated(
            api.list_concession_approvals(PM1, params={"offer_id": sc["offer"]["id"]}))
        assert concessions == [], "no ConcessionApproval may persist past the fiscal floor"


class TestConcessionDecision:
    def _submitted_concession(self, api, counter_rent, property_name, unit_number):
        sc = setup_countered_offer_scenario(
            counter_rent_cents=counter_rent, property_name=property_name,
            unit_number=unit_number)
        resp = api.create_concession_approval(
            sc["offer"]["id"],
            {"requested_rent_cents": counter_rent, "reason": "retention"},
            LA1)
        concession = validate_success(resp, 201)
        return sc, concession

    def test_sod_self_approve_rejected(self, api):
        """PRD §3.5: "Two further checks bind every decision: the linked offer must
        still be `COUNTERED` for an approval (`ERR_OFFER_NOT_COUNTERED` otherwise),
        and segregation of duties forbids the requester from deciding their own
        request — an approver or denier whose identity matches `requested_by_user_id`
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_self_approve_rejected
        """
        sc, concession = self._submitted_concession(api, 205000, "SoD Court", "SD1")
        assert concession["concession_bps"] == 275
        # user_la_1 submitted; user_la_1 cannot approve — the PERSON is checked.
        resp = api.approve_concession(concession["id"], LA1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_concession(concession["id"])["status"] == "SUBMITTED"

    def test_approve_denied_concession_rejected(self, api):
        """PRD §3.5: "Deciding a request that has left `SUBMITTED` returns
        `ERR_CONCESSION_NOT_SUBMITTED`."

        Design: Corner/state_machines/approve_denied_concession_rejected
        """
        _sc, concession = self._submitted_concession(api, 205000, "Denied Court", "213")
        validate_success(api.deny_concession(concession["id"], PM1), 200)
        resp = api.approve_concession(concession["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_NOT_SUBMITTED)
        assert get_concession(concession["id"])["status"] == "DENIED"

    def test_tier_boundary_exactly_300_agent_approves(self, api):
        """PRD §3.5: "Approval authority is tiered by role, with each tier's limit an
        inclusive upper bound on `concession_bps`: a `LeasingAgent` may approve up to
        300 basis points, a `PropertyManager` up to 800, and a `RegionalDirector` up
        to the absolute ceiling of 2,000."
        PRD §3.5: "A successful decision records `decided_by_user_id` and moves the
        request to `APPROVED` or `DENIED`."

        Design: Corner/validations/tier_boundary_exactly_300_agent_approves
        """
        _sc, concession = self._submitted_concession(api, 204476, "Tier Court", "TC1")
        # round_half_up(6324/210800 * 10000) = 300 — exactly the agent tier cap.
        assert concession["concession_bps"] == 300
        resp = api.approve_concession(concession["id"], LA2)  # a DIFFERENT agent
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["decided_by_user_id"] == "user_la_2"

    def test_tier_exceeded_agent_500bps_rejected_then_manager_approves(self, api):
        """PRD §3.5: "Approval authority is tiered by role, with each tier's limit an
        inclusive upper bound on `concession_bps`: a `LeasingAgent` may approve up to
        300 basis points, a `PropertyManager` up to 800, and a `RegionalDirector` up
        to the absolute ceiling of 2,000. An approver whose tier does not cover the
        requested discount is rejected with `ERR_CONCESSION_TIER_EXCEEDED`."

        Design: Corner/validations/tier_exceeded_agent_500bps_rejected_then_manager_approves
        """
        _sc, concession = self._submitted_concession(api, 200260, "Ladder Court", "LC1")
        assert concession["concession_bps"] == 500  # (210800-200260)/210800
        resp = api.approve_concession(concession["id"], LA2)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_TIER_EXCEEDED)
        assert get_concession(concession["id"])["status"] == "SUBMITTED"
        data = validate_success(api.approve_concession(concession["id"], PM1), 200)
        assert data["status"] == "APPROVED"

    def test_director_approves_1500bps_after_manager_denied_by_tier(self, api):
        """PRD §3.5: "Approval authority is tiered by role, with each tier's limit an
        inclusive upper bound on `concession_bps`: a `LeasingAgent` may approve up to
        300 basis points, a `PropertyManager` up to 800, and a `RegionalDirector` up
        to the absolute ceiling of 2,000. An approver whose tier does not cover the
        requested discount is rejected with `ERR_CONCESSION_TIER_EXCEEDED`."

        Design: Corner/validations/director_approves_1500bps_after_manager_denied_by_tier
        """
        _sc, concession = self._submitted_concession(api, 179180, "Director Court", "DR1")
        assert concession["concession_bps"] == 1500  # (210800-179180)/210800
        resp = api.approve_concession(concession["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_TIER_EXCEEDED)
        data = validate_success(api.approve_concession(concession["id"], RD1), 200)
        assert data["status"] == "APPROVED"


class TestCrossEntityConcessionGate:
    def _orphaned_concession_fixture(self, api):
        sc = setup_countered_offer_scenario(
            counter_rent_cents=205000, property_name="Orphan Gate House", unit_number="1002")
        resp = api.create_concession_approval(
            sc["offer"]["id"],
            {"requested_rent_cents": 205000, "reason": "retention"},
            LA1)
        concession = validate_success(resp, 201)
        # Revise to 211000 (>= proposed 210800: no concession gate; 550 bps <= cap;
        # window open at the default clock) -> the offer leaves COUNTERED.
        offer = validate_success(
            api.revise_offer(sc["offer"]["id"], {"revised_rent_cents": 211000}, LA1), 200)
        return sc, offer, concession

    def test_concession_approve_orphaned_by_revise_offer_state(self, api):
        """PRD §3.4: "A successful revise increments `offer_round` by one, overwrites
        `proposed_rent_cents` with the revised rent, recomputes
        `proposed_increase_bps`, `notice_days_required`, and `latest_issue_date`,
        adopts the revised term as `offered_term_months`, restamps `issued_on_date`
        with the clock date, resets the `response_deadline_date` to the earlier of
        fourteen days out and the term end, returns the offer to `ISSUED`, and marks
        the consumed concession approval `APPLIED`."

        Design: Difficulty/cross_entity_state_dependency/concession_approve_blocked_when_offer_not_countered
        """
        _sc, offer, concession = self._orphaned_concession_fixture(api)
        assert offer["status"] == "ISSUED"
        assert offer["offer_round"] == 2
        # The revise did not price at the concession's requested rent, so the
        # pending request is untouched (still SUBMITTED), merely orphaned.
        assert get_concession(concession["id"])["status"] == "SUBMITTED"

    def test_concession_approve_blocked_when_offer_not_countered(self, api):
        """PRD §3.5: "Two further checks bind every decision: the linked offer must
        still be `COUNTERED` for an approval (`ERR_OFFER_NOT_COUNTERED` otherwise),
        and segregation of duties forbids the requester from deciding their own
        request — an approver or denier whose identity matches `requested_by_user_id`
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/concession_approve_blocked_when_offer_not_countered
        """
        _sc, _offer, concession = self._orphaned_concession_fixture(api)
        # The concession itself is SUBMITTED (its own state precondition holds),
        # yet approval fails because the linked offer left COUNTERED.
        resp = api.approve_concession(concession["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_COUNTERED)
        assert get_concession(concession["id"])["status"] == "SUBMITTED"
