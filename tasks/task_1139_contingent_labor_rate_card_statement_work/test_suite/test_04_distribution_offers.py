"""Supplier distribution: selector ranking, empty pool, offer lifecycle,
bubble-up, withdrawal and the ops-run expiry sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_distribution_offer,
    create_engagement_in_open,
    get_engagement,
    get_success_data,
    get_supplier,
    make_supplier_coordinator_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]


class TestSelectorRanking:
    def _setup_four_suppliers_and_open_engagement(self, api):
        set_logical_clock("2026-05-01T00:00:00Z")
        p1 = onboard_supplier(tier="PREFERRED", name="P1", supplier_code="SUP-PPP")
        a3 = onboard_supplier(tier="APPROVED", name="A3", supplier_code="SUP-CCC")
        a1 = onboard_supplier(tier="APPROVED", name="A1", supplier_code="SUP-AAA")
        a2 = onboard_supplier(tier="APPROVED", name="A2", supplier_code="SUP-BBB")
        engagement = create_engagement_in_open(title="Selector")
        return p1, a1, a2, a3, engagement

    def test_distribution_offers_ordered_by_selection_rank(self, api):
        """PRD: "The eligible pool is ranked by a deterministic total order:
        first by tier, `PREFERRED` before `APPROVED`; then by `tier_score`
        descending, with a null score treated as exactly 70; then by
        `created_at` ascending; and finally by `supplier_code` ascending as
        the deterministic tie-break."
        PRD: "The distribution response returns the created offers ordered by
        selection rank, best first."
        PRD: "entities created while the clock is frozen share identical
        `created_at` values."

        Design: Corner/calculations/selector_top3_tiebreak_by_supplier_code
        """
        p1, a1, a2, _a3, engagement = self._setup_four_suppliers_and_open_engagement(api)
        offers = validate_success(
            api.distribute_engagement(engagement["id"], ADMIN), expected_status=201
        )
        assert len(offers) == 3, "fanout is the top 3 of the ranked pool"
        for offer in offers:
            assert_distribution_offer(offer)
        assert offers[0]["supplier_id"] == p1["id"], "PREFERRED ranks first"
        assert offers[1]["supplier_id"] == a1["id"], (
            "APPROVED tie (null scores read as 70, frozen created_at) falls to "
            "supplier_code ASC: SUP-AAA before SUP-BBB"
        )
        assert offers[2]["supplier_id"] == a2["id"]

    def test_fourth_ranked_supplier_receives_no_offer(self, api):
        """PRD: "No supplier `id` ever participates in ranking. The top 3
        suppliers of the ranked pool each receive a `DistributionOffer`"

        Design: Corner/calculations/selector_top3_tiebreak_by_supplier_code
        """
        _p1, _a1, _a2, a3, engagement = self._setup_four_suppliers_and_open_engagement(api)
        offers = validate_success(
            api.distribute_engagement(engagement["id"], ADMIN), expected_status=201
        )
        assert len(offers) == 3
        _, meta = validate_paginated(
            api.list_distribution_offers(ADMIN, params={"supplier_id": a3["id"]})
        )
        assert meta["total_count"] == 0, (
            "SUP-CCC ranks fourth on the supplier_code tie-break and gets no offer"
        )
        a3_after = get_supplier(a3["id"])
        assert a3_after["offers_made_count"] == 0
        assert a3_after["open_offers_count"] == 0


class TestSelectorEmptyPool:
    def test_distribute_empty_pool_rejected(self, api):
        """PRD: "if the eligible pool is empty the distribution is rejected
        with `ERR_NO_ELIGIBLE_SUPPLIER` (422) and no offer is created."
        PRD: "Eligibility is strict: a candidate supplier must be `ACTIVE`,
        must hold tier `PREFERRED` or `APPROVED`, and must have headroom under
        its parallel-offer cap"

        Design: Corner/calculations/selector_empty_pool_returns_error
        """
        onboard_supplier(tier="PROBATION", name="Prob Co", supplier_code="SUP-XP")
        engagement = create_engagement_in_open(title="Empty pool")
        resp = api.distribute_engagement(engagement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUPPLIER)

    def test_distribute_empty_pool_creates_no_offers(self, api):
        """PRD: "if the eligible pool is empty the distribution is rejected
        with `ERR_NO_ELIGIBLE_SUPPLIER` (422) and no offer is created."

        Design: Corner/calculations/selector_empty_pool_returns_error
        """
        supplier = onboard_supplier(tier="PROBATION", name="Prob Co",
                                    supplier_code="SUP-XP")
        engagement = create_engagement_in_open(title="Empty pool")
        validate_error(
            api.distribute_engagement(engagement["id"], ADMIN),
            ApiErrorId.ERR_NO_ELIGIBLE_SUPPLIER,
        )
        after = get_engagement(engagement["id"])
        assert after["status"] == "OPEN", "rejected distribution leaves the engagement OPEN"
        supplier_after = get_supplier(supplier["id"])
        assert supplier_after["offers_made_count"] == 0
        assert supplier_after["open_offers_count"] == 0
        _, meta = validate_paginated(api.list_distribution_offers(ADMIN))
        assert meta["total_count"] == 0


class TestFirstAcceptBubble:
    def _setup_two_supplier_filling_engagement(self, api):
        set_logical_clock("2026-05-01T00:00:00Z")
        s1 = onboard_supplier(tier="PREFERRED", name="First Co", supplier_code="SUP-F1")
        s2 = onboard_supplier(tier="APPROVED", name="Second Co", supplier_code="SUP-F2")
        engagement = create_engagement_in_open(title="Bubble")
        offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
        o1 = pick_offer_for_supplier(offers, s1["id"])
        o2 = pick_offer_for_supplier(offers, s2["id"])
        return s1, s2, engagement, o1, o2

    def test_first_accept_bubbles_engagement_active_and_pins_awarded_supplier(self, api):
        """PRD: "if the engagement is still `FILLING`, the first acceptance
        moves it to `ACTIVE` and sets `awarded_supplier_id` to the accepting
        supplier, but only while that field is still null."

        Design: Corner/state_machines/first_offer_accept_bubbles_engagement_active
        """
        s1, s2, engagement, _o1, o2 = self._setup_two_supplier_filling_engagement(api)
        accepted = validate_success(
            api.respond_to_offer(
                o2["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s2["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"
        after = get_engagement(engagement["id"])
        assert after["status"] == "ACTIVE", "first ACCEPT bubbles FILLING -> ACTIVE"
        assert after["awarded_supplier_id"] == s2["id"], (
            "S2 responded first, so S2 is pinned as the awarded supplier"
        )

    def test_second_accept_does_not_overwrite_awarded_supplier(self, api):
        """PRD: "if the engagement is still `FILLING`, the first acceptance
        moves it to `ACTIVE` and sets `awarded_supplier_id` to the accepting
        supplier, but only while that field is still null."
        PRD: "Either response requires the offer to still be `OFFERED`,
        decrements the supplier's `open_offers_count` by one, and stamps
        `responded_at` from the logical clock."

        Design: Corner/state_machines/first_offer_accept_bubbles_engagement_active
        """
        s1, s2, engagement, o1, o2 = self._setup_two_supplier_filling_engagement(api)
        validate_success(
            api.respond_to_offer(
                o2["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s2["id"])
            )
        )
        second = validate_success(
            api.respond_to_offer(
                o1["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s1["id"])
            )
        )
        assert second["status"] == "ACCEPTED"
        after = get_engagement(engagement["id"])
        assert after["awarded_supplier_id"] == s2["id"], (
            "first-accept wins and is never overwritten"
        )
        assert get_supplier(s1["id"])["open_offers_count"] == 0


def test_withdraw_declined_offer_rejected(api):
    """PRD: "A `ProgramAdmin` may also withdraw an `OFFERED` offer outright,
    moving it to `WITHDRAWN` with the same counter decrement."
    PRD: "State validity — the target resource must be in a valid from-state
    for the requested transition. A generic wrong-from-state rejection is
    `ERR_INVALID_STATE` (409)"

    Design: Corner/state_machines/withdraw_declined_offer_rejected
    """
    s1 = onboard_supplier(tier="APPROVED", name="Decline Co", supplier_code="SUP-DC")
    engagement = create_engagement_in_open(title="Decline")
    offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
    offer = pick_offer_for_supplier(offers, s1["id"])
    declined = get_success_data(
        api.respond_to_offer(
            offer["id"], {"action": "DECLINE"}, make_supplier_coordinator_headers(s1["id"])
        )
    )
    assert declined["status"] == "DECLINED"

    resp = api.withdraw_offer(offer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_distribution_offer(offer["id"], ADMIN))
    assert after["status"] == "DECLINED", "DECLINED is terminal for the respond flow"


class TestOfferSlotInvariant:
    def _setup_three_supplier_filling_engagement(self, api):
        set_logical_clock("2026-05-01T00:00:00Z")
        s1 = onboard_supplier(tier="PREFERRED", name="Sup Pref", supplier_code="SUP-P")
        s2 = onboard_supplier(tier="APPROVED", name="Sup A", supplier_code="SUP-A")
        s3 = onboard_supplier(tier="APPROVED", name="Sup B", supplier_code="SUP-B")
        engagement = create_engagement_in_open(title="Slots")
        offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
        return s1, s2, s3, engagement, offers

    def test_distribute_creates_one_offer_per_selected_supplier_ranked(self, api):
        """PRD: "The top 3 suppliers of the ranked pool each receive a
        `DistributionOffer`"
        PRD: "Each created offer starts `OFFERED`, stamped with `offered_at`
        from the logical clock and a `response_due_at` exactly 7 days later.
        Every selected supplier's `offers_made_count` and `open_offers_count`
        each increase by one."
        PRD: "The distribution response returns the created offers ordered by
        selection rank, best first."

        Design: Difficulty/compensating_invariant/offer_withdraw_expire_restores_slot_invariant
        """
        s1, s2, s3, _engagement, offers = self._setup_three_supplier_filling_engagement(api)
        assert len(offers) == 3
        assert offers[0]["supplier_id"] == s1["id"], "PREFERRED supplier ranks first"
        assert offers[1]["supplier_id"] == s2["id"], (
            "created_at ties under the frozen clock fall to supplier_code ASC"
        )
        assert offers[2]["supplier_id"] == s3["id"]
        for supplier in (s1, s2, s3):
            current = get_supplier(supplier["id"])
            assert current["offers_made_count"] == 1
            assert current["open_offers_count"] == 1

    def test_slot_counters_return_to_baseline_after_withdraw_and_expiry(self, api):
        """PRD: "A `ProgramAdmin` may also withdraw an `OFFERED` offer
        outright, moving it to `WITHDRAWN` with the same counter decrement."
        PRD: "Offers that outlive their window are reaped by an ops-run expiry
        sweep: a checkpoint operation over all offers that moves every
        `OFFERED` offer whose `response_due_at` is earlier than the logical
        clock to `EXPIRED`, decrementing the owning supplier's
        `open_offers_count` once per expired offer and returning an
        `expired_count`."

        Design: Difficulty/compensating_invariant/offer_withdraw_expire_restores_slot_invariant
        """
        s1, s2, s3, _engagement, offers = (
            self._setup_three_supplier_filling_engagement(api)
        )
        first_offer_id = offers[0]["id"]

        withdrawn = validate_success(api.withdraw_offer(first_offer_id, ADMIN))
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_supplier(s1["id"])["open_offers_count"] == 0

        set_logical_clock("2026-05-09T00:00:00Z")
        sweep = validate_success(api.expire_offers_sweep(ADMIN))
        assert sweep["expired_count"] == 2, (
            "the other two offers are past response_due_at 2026-05-08T00:00:00Z"
        )
        for supplier in (s1, s2, s3):
            assert get_supplier(supplier["id"])["open_offers_count"] == 0, (
                "every counter returns to its pre-distribute baseline"
            )
        _, meta = validate_paginated(
            api.list_distribution_offers(ADMIN, params={"status": "OFFERED"})
        )
        assert meta["total_count"] == 0, "no OFFERED offers remain anywhere"


class TestExpireSweepWindow:
    def _setup_two_engagements_two_suppliers(self, api):
        set_logical_clock("2026-05-01T00:00:00Z")
        s1 = onboard_supplier(tier="PREFERRED", name="Sweep One", supplier_code="SUP-S1")
        s2 = onboard_supplier(tier="APPROVED", name="Sweep Two", supplier_code="SUP-S2")
        e1 = create_engagement_in_open(title="E1")
        get_success_data(api.distribute_engagement(e1["id"], ADMIN))
        set_logical_clock("2026-05-05T00:00:00Z")
        e2 = create_engagement_in_open(title="E2")
        get_success_data(api.distribute_engagement(e2["id"], ADMIN))
        return s1, s2, e1, e2

    def test_expire_sweep_expires_only_past_due_offers(self, api):
        """PRD: "a checkpoint operation over all offers that moves every
        `OFFERED` offer whose `response_due_at` is earlier than the logical
        clock to `EXPIRED`, decrementing the owning supplier's
        `open_offers_count` once per expired offer and returning an
        `expired_count`."
        PRD: "Each created offer starts `OFFERED`, stamped with `offered_at`
        from the logical clock and a `response_due_at` exactly 7 days later."

        Design: Corner/cross_cutting/expire_sweep_only_expires_past_due
        """
        _s1, _s2, e1, e2 = self._setup_two_engagements_two_suppliers(api)
        set_logical_clock("2026-05-09T00:00:00Z")
        sweep = validate_success(api.expire_offers_sweep(ADMIN))
        assert sweep["expired_count"] == 2, (
            "E1's offers are due 2026-05-08 < 2026-05-09; E2's are due 2026-05-12"
        )
        expired, meta_expired = validate_paginated(
            api.list_distribution_offers(ADMIN, params={"engagement_id": e1["id"],
                                                        "status": "EXPIRED"})
        )
        assert meta_expired["total_count"] == 2
        _, meta_still = validate_paginated(
            api.list_distribution_offers(ADMIN, params={"engagement_id": e2["id"],
                                                        "status": "OFFERED"})
        )
        assert meta_still["total_count"] == 2, (
            "offers inside their 7-day window are untouched"
        )

    def test_expire_sweep_decrements_counters_per_expired_offer(self, api):
        """PRD: "decrementing the owning supplier's `open_offers_count` once
        per expired offer and returning an `expired_count`."

        Design: Corner/cross_cutting/expire_sweep_only_expires_past_due
        """
        s1, s2, _e1, _e2 = self._setup_two_engagements_two_suppliers(api)
        assert get_supplier(s1["id"])["open_offers_count"] == 2
        assert get_supplier(s2["id"])["open_offers_count"] == 2

        set_logical_clock("2026-05-09T00:00:00Z")
        validate_success(api.expire_offers_sweep(ADMIN))
        assert get_supplier(s1["id"])["open_offers_count"] == 1, (
            "only E2's offer is still outstanding for S1"
        )
        assert get_supplier(s2["id"])["open_offers_count"] == 1
