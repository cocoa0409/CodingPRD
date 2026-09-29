"""Where every row starts, the bounded review loop that returns to a state it already
occupied, and the two forward transitions that fire whole side-effect sets at once."""

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_complaint,
    assert_delivery,
    assert_entitlement_for_tier,
    assert_fund,
    assert_hotel,
    assert_ledger_entry,
    assert_member,
    assert_purchase,
    assert_redemption,
    assert_stay,
    count_entries_of_type,
    entries_of_type,
    fixtures as fx,
    make_admin_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    read_entity,
    validate_error,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _initial_state_inn_with_a_funded_member(api):
    """An ACTIVE property selling standard award nights at twenty thousand points, and a
    member holding forty thousand points from one settled direct purchase."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Initial State Inn",
        brand_code="ISI",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    fx.publish_standard_pricing(
        api,
        bundle["hotel"]["id"],
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    member = fx.enroll_member(
        api, email="is1@example.com", full_name="Halldor Sig",
        enrollment_date="2026-01-02",
    )
    purchase = fx.record_purchase(api, member["id"], 40_000, channel="DIRECT_PURCHASE")
    fx.settle_purchase(api, purchase["id"])

    bundle["member"] = member
    bundle["member_headers"] = make_member_headers(member["id"])
    return bundle


def _complaint_under_review_with_a_solvent_fund(api):
    """One member with an entirely empty ledger, and one complaint of theirs already
    taken under review by the care queue."""
    member = fx.enroll_member(
        api, email="cl1@example.com", full_name="Miriam Osei",
        enrollment_date="2026-01-20",
    )
    member_headers = make_member_headers(member["id"])
    agent = make_care_agent_headers("care-cl-01")
    complaint = fx.file_complaint(
        api, member["id"], subject_type="POINT_SHORTFALL", headers=member_headers
    )
    complaint = fx.review_complaint(api, complaint["id"], headers=agent)

    return {
        "member": member,
        "member_headers": member_headers,
        "agent": agent,
        "complaint": complaint,
    }


def _escalation_house_with_an_upheld_denial(api):
    """A SILVER guest whose upgrade the property refused, with the resulting complaint
    already resolved against the guest and therefore open to escalation."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Escalation House",
        brand_code="ESH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=150,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    owner = make_hotel_owner_headers(hotel_id)
    member = fx.enroll_member(
        api, email="es1@example.com", full_name="Lior Shaked",
        enrollment_date="2026-01-08",
    )
    member_headers = make_member_headers(member["id"])
    agent = make_care_agent_headers("care-es-01")

    fx.posted_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"],
        "2026-06-01", "2026-06-11", 100_000,
    )
    second = fx.posted_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"],
        "2026-06-15", "2026-06-17", 40_000,
    )
    obligation = fx.obligation_of_type(api, second["id"], "UPGRADE")
    obligation = fx.deny_obligation(
        api, obligation["id"], reason="No upgrade inventory on arrival.", headers=owner
    )
    complaint = fx.file_complaint(
        api, member["id"], subject_type="BENEFIT_DENIAL",
        related_delivery_id=obligation["id"], headers=member_headers,
    )
    fx.review_complaint(api, complaint["id"], headers=agent)
    complaint = fx.resolve_complaint(
        api, complaint["id"],
        resolution="Property confirms no inventory was available.", headers=agent,
    )

    bundle["member"] = member
    bundle["member_headers"] = member_headers
    bundle["agent"] = agent
    bundle["owner"] = owner
    bundle["second_stay"] = second
    bundle["obligation"] = obligation
    bundle["complaint"] = complaint
    return bundle


def _sideeffect_grand_with_a_platinum_snapshot(api):
    """A guest carried to PLATINUM by one posted fifty-night stay, with a second
    two-night stay captured afterwards so its snapshot is the top tier."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Sideeffect Grand",
        brand_code="SEG",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=200,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    owner = make_hotel_owner_headers(hotel_id)
    member = fx.enroll_member(
        api, email="se1@example.com", full_name="Dorotea Kis",
        enrollment_date="2026-01-03",
    )
    first = fx.posted_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"],
        "2026-06-01", "2026-07-21", 500_000,
    )
    second = fx.capture_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"],
        "2026-07-22", "2026-07-24", 20_000, headers=owner,
    )

    bundle["member"] = member
    bundle["owner"] = owner
    bundle["first_stay"] = first
    bundle["second_stay"] = second
    return bundle


# ----------------------------------------------------------------------
# Where every row starts
# ----------------------------------------------------------------------
class TestDeclaredInitialStates:
    def test_a_second_property_and_a_fresh_purchase_and_stay_open_where_declared(
        self, api
    ):
        """A brand-new property is never trading yet, an unsettled point sale has moved
        nothing, and a captured stay is waiting to be posted.

        PRD: "The purchase is created in status `PENDING` with `refund_reason` null."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        bundle = _initial_state_inn_with_a_funded_member(api)

        second_property = fx.create_onboarding_hotel(
            api,
            name="Second Initial Inn",
            brand_code="SII",
            market_tier="SELECT",
            program_fee_pct=0.03,
            rooms_count=60,
            trailing_12m_occupancy_pct=0.70,
            trailing_12m_adr_cents=12_000,
        )
        pending = fx.record_purchase(
            api, bundle["member"]["id"], 20_000, channel="DIRECT_PURCHASE"
        )
        stay = fx.capture_stay(
            api, bundle["hotel"]["id"], bundle["member"]["id"],
            bundle["rate_plan"]["id"], "2026-07-05", "2026-07-07", 40_000,
        )

        assert_hotel(second_property, status="ONBOARDING")
        assert_purchase(pending, status="PENDING", points_quantity=20_000)
        assert pending["refund_reason"] is None, pending["refund_reason"]
        assert_stay(stay, status="PENDING_POSTING")

    def test_the_award_booking_initialises_both_of_its_dimensions_independently(self, api):
        """One row carries two state machines, and creation puts each of them in its own
        declared opening state.

        PRD: "On success the booking is created with `fulfillment_status` `HELD` and
        `reimbursement_status` `NOT_DUE`, both `estimated_reimbursement_cents` and
        `settled_reimbursement_cents` at 0, `batch_id` null and `cancel_reason` null."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        bundle = _initial_state_inn_with_a_funded_member(api)

        booking = fx.book_award(
            api, bundle["member"]["id"], bundle["hotel"]["id"],
            "2026-09-10", "2026-09-12", headers=bundle["member_headers"],
        )

        assert_redemption(
            booking,
            fulfillment_status="HELD",
            reimbursement_status="NOT_DUE",
            points_charged=40_000,
            estimated_cents=0,
            settled_cents=0,
        )
        assert booking["batch_id"] is None, booking["batch_id"]
        assert booking["cancel_reason"] is None, booking["cancel_reason"]

    def test_a_freshly_opened_batch_has_priced_nothing_and_named_no_operator(self, api):
        """Opening a batch is a declaration of intent: every money field is zero and the
        two operator slots are still empty.

        PRD: "The batch opens in `OPEN` with `item_count`,
        `gross_reimbursement_cents`, `fee_offset_base_cents`,
        `delinquency_surcharge_cents`, `total_fee_offset_cents` and `net_payable_cents`
        all 0, `occupancy_pct_at_release` at 0.0, `adr_cents_at_release` at 0, and
        `released_by_user_id`, `approved_by_user_id` and `rejection_reason` all null."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        bundle = _initial_state_inn_with_a_funded_member(api)

        batch = fx.open_batch(api, bundle["hotel"]["id"], "2026-09")

        assert_batch(
            batch,
            status="OPEN",
            item_count=0,
            gross_cents=0,
            fee_offset_base_cents=0,
            surcharge_cents=0,
            total_fee_offset_cents=0,
            net_payable_cents=0,
            occupancy_at_release=0.0,
            adr_at_release=0,
        )
        assert batch["released_by_user_id"] is None, batch["released_by_user_id"]
        assert batch["approved_by_user_id"] is None, batch["approved_by_user_id"]
        assert batch["rejection_reason"] is None, batch["rejection_reason"]

    def test_a_filed_complaint_has_asked_for_nothing_and_decided_nothing(self, api):
        """Filing records the grievance and nothing else: no information requested, no
        goodwill granted and no outcome.

        PRD: "The complaint opens in `OPEN` with `info_request_count` and
        `goodwill_points_granted` both 0, and `resolution` and `adjudication_outcome` both
        null."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        bundle = _initial_state_inn_with_a_funded_member(api)

        complaint = fx.file_complaint(
            api, bundle["member"]["id"], subject_type="POINT_SHORTFALL",
            headers=make_care_agent_headers("care-is-01"),
        )

        assert_complaint(
            complaint,
            status="OPEN",
            info_request_count=0,
            goodwill_points_granted=0,
            subject_type="POINT_SHORTFALL",
        )
        assert complaint["resolution"] is None, complaint["resolution"]
        assert complaint["adjudication_outcome"] is None, complaint["adjudication_outcome"]
        assert complaint["related_delivery_id"] is None, complaint["related_delivery_id"]

    def test_the_fund_reports_the_ratio_of_banked_cash_over_the_valued_liability(self, api):
        """One settled purchase banks 47,500 cents against a 19,200-cent liability, which
        is comfortably solvent.

        PRD: "The `solvency_ratio` is `cash_balance_cents` divided by
        `point_liability_cents`, rounded half up to four decimal places, and is pinned to
        exactly 999.0000 when the liability is zero rather than dividing by zero — so a
        programme with an empty ledger reads `HEALTHY`, not impaired."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        _initial_state_inn_with_a_funded_member(api)

        fund = fx.read_fund(api)

        assert_fund(
            fund,
            status="HEALTHY",
            cash_cents=47_500,
            outstanding_points=40_000,
            liability_cents=19_200,
            solvency_ratio=2.4740,
        )


# ----------------------------------------------------------------------
# The bounded review loop
# ----------------------------------------------------------------------
class TestInformationRequestLoopIsBounded:
    def test_returning_to_a_visited_state_does_not_rewind_the_counter(self, api):
        """The complaint occupies UNDER_REVIEW twice, yet the request tally only ever
        climbs.

        PRD: "That cycle is what bounds the loop: `info_request_count` is **never**
        decremented on the way back, so it accumulates."

        Design: Corner/state_machines/complaint_info_loop_returns_to_under_review_twice_then_refuses_a_third_request
        """
        bundle = _complaint_under_review_with_a_solvent_fund(api)
        complaint_id = bundle["complaint"]["id"]

        first_request = fx.request_complaint_info(api, complaint_id, headers=bundle["agent"])
        first_return = fx.provide_complaint_info(
            api, complaint_id, headers=bundle["member_headers"]
        )
        second_request = fx.request_complaint_info(api, complaint_id, headers=bundle["agent"])
        second_return = fx.provide_complaint_info(
            api, complaint_id, headers=bundle["member_headers"]
        )

        assert_complaint(first_request, status="INFO_REQUESTED", info_request_count=1)
        assert_complaint(first_return, status="UNDER_REVIEW", info_request_count=1)
        assert_complaint(second_request, status="INFO_REQUESTED", info_request_count=2)
        assert_complaint(second_return, status="UNDER_REVIEW", info_request_count=2)

    def test_the_third_request_is_refused_and_leaves_the_complaint_under_review(self, api):
        """Two trips are reachable and the third is not, and the refusal leaves the
        complaint exactly where the second return put it.

        PRD: "A request for information is permitted only while `info_request_count` is
        below 2, else `ERR_INFO_REQUEST_LIMIT` — the second trip to `INFO_REQUESTED` is
        reachable and a third is refused, leaving the complaint stuck in `UNDER_REVIEW`
        until it is resolved."

        Design: Corner/state_machines/complaint_info_loop_returns_to_under_review_twice_then_refuses_a_third_request
        """
        bundle = _complaint_under_review_with_a_solvent_fund(api)
        complaint_id = bundle["complaint"]["id"]
        for _ in range(2):
            fx.request_complaint_info(api, complaint_id, headers=bundle["agent"])
            fx.provide_complaint_info(api, complaint_id, headers=bundle["member_headers"])

        response = api.request_complaint_info(complaint_id, bundle["agent"])

        validate_error(response, ApiErrorId.ERR_INFO_REQUEST_LIMIT.value)
        assert_complaint(
            fx.read_complaint(api, complaint_id),
            status="UNDER_REVIEW",
            info_request_count=2,
        )

    def test_the_exhausted_loop_still_admits_a_goodwill_resolution(self, api):
        """The bounded loop poisons nothing: the care agent can still close the complaint
        out with a credit, which writes one entry and revalues the fund.

        PRD: "When `goodwill_points` is greater than zero the complaint moves
        `UNDER_REVIEW → RESOLVED_GOODWILL`: `resolution` is recorded,
        `goodwill_points_granted` is set to the requested figure, one `GOODWILL` ledger
        entry is written crediting the complaining member with that many points, the
        member's `point_balance` and `lifetime_points_earned` are recomputed, and the
        fund's `outstanding_points`, `point_liability_cents`, `solvency_ratio` and
        `status` are recomputed."

        Design: Corner/state_machines/complaint_info_loop_returns_to_under_review_twice_then_refuses_a_third_request
        """
        bundle = _complaint_under_review_with_a_solvent_fund(api)
        complaint_id = bundle["complaint"]["id"]
        member_id = bundle["member"]["id"]
        for _ in range(2):
            fx.request_complaint_info(api, complaint_id, headers=bundle["agent"])
            fx.provide_complaint_info(api, complaint_id, headers=bundle["member_headers"])
        api.request_complaint_info(complaint_id, bundle["agent"])

        resolved = fx.resolve_complaint(
            api, complaint_id,
            resolution="Missing points credited as goodwill.",
            goodwill_points=5_000,
            headers=bundle["agent"],
        )

        assert_complaint(
            resolved, status="RESOLVED_GOODWILL", goodwill_points_granted=5_000
        )
        assert_member(fx.read_member(api, member_id), point_balance=5_000)
        entries = fx.ledger_of_member(api, member_id)
        assert count_entries_of_type(entries, "GOODWILL") == 1, (
            f"exactly one goodwill entry should exist, got {len(entries)} entries in total"
        )
        assert_fund(
            fx.read_fund(api),
            status="IMPAIRED",
            outstanding_points=5_000,
            liability_cents=2_400,
            solvency_ratio=0.0,
        )


# ----------------------------------------------------------------------
# The denial loop walked end to end
# ----------------------------------------------------------------------
class TestDenialEscalationAndAdjudicatedDelivery:
    def test_the_members_escalation_drags_the_obligation_out_of_denied(self, api):
        """Escalating the upheld complaint is what moves the obligation, and the denial
        tally does not move because the new status is still counted.

        PRD: "and on success that obligation advances `DENIED → ESCALATED` and the
        property's `benefit_denial_count` is recomputed, which leaves the figure unchanged
        because `ESCALATED` remains inside the counted set."

        Design: Corner/state_machines/denied_benefit_escalates_through_the_complaint_and_adjudication_orders_delivery
        """
        bundle = _escalation_house_with_an_upheld_denial(api)
        assert_complaint(bundle["complaint"], status="RESOLVED_UPHELD")

        escalated = fx.escalate_complaint(
            api, bundle["complaint"]["id"], headers=bundle["member_headers"]
        )

        assert_complaint(escalated, status="ESCALATED")
        obligation = read_entity(
            api.get_benefit_delivery, bundle["obligation"]["id"], make_admin_headers()
        )
        assert_delivery(obligation, status="ESCALATED", benefit_type="UPGRADE")
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), benefit_denial_count=1)

    def test_ordering_delivery_closes_the_complaint_and_prices_the_recovery_only_then(
        self, api
    ):
        """The cash recovery is computed when the obligation is finally delivered, not
        when it was denied, and a 30,000-cent daily rate recovers 4,500.

        PRD: "An `UPGRADE` recovers fifteen percent of the property's
        `trailing_12m_adr_cents` as read at delivery time, rounded half up to the cent and
        then capped at 9,000 cents; the rounding happens before the cap, and the cap is a
        hard ceiling, so an average daily rate of 30,000 cents recovers 4,500 while a rate
        of 80,000 cents recovers 9,000 rather than 12,000."

        Design: Corner/state_machines/denied_benefit_escalates_through_the_complaint_and_adjudication_orders_delivery
        """
        bundle = _escalation_house_with_an_upheld_denial(api)
        fx.escalate_complaint(
            api, bundle["complaint"]["id"], headers=bundle["member_headers"]
        )
        assert_delivery(
            read_entity(
                api.get_benefit_delivery, bundle["obligation"]["id"], make_admin_headers()
            ),
            cost_recovery_cents=0,
        )

        closed = fx.adjudicate_complaint(
            api, bundle["complaint"]["id"], adjudication_outcome="DELIVERY_ORDERED"
        )

        assert_complaint(closed, status="CLOSED", adjudication_outcome="DELIVERY_ORDERED")
        assert_delivery(
            read_entity(
                api.get_benefit_delivery, bundle["obligation"]["id"], make_admin_headers()
            ),
            status="DELIVERED",
            cost_recovery_cents=4_500,
        )

    def test_the_denial_tally_falls_back_and_adjudication_moves_no_points(self, api):
        """Delivering the obligation takes it out of the counted set, credits the
        property the recovery, and leaves the guest's balance exactly as the two postings
        left it.

        PRD: "`goodwill_points_granted` is unchanged by adjudication even when the member
        wins, because goodwill is granted only by resolving a complaint or by an explicit
        point adjustment; a member whose escalation succeeds gets the benefit ordered
        delivered at the property's expense, not a point credit."

        Design: Corner/state_machines/denied_benefit_escalates_through_the_complaint_and_adjudication_orders_delivery
        """
        bundle = _escalation_house_with_an_upheld_denial(api)
        fx.escalate_complaint(
            api, bundle["complaint"]["id"], headers=bundle["member_headers"]
        )

        closed = fx.adjudicate_complaint(
            api, bundle["complaint"]["id"], adjudication_outcome="DELIVERY_ORDERED"
        )

        assert_complaint(closed, goodwill_points_granted=0)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            benefit_denial_count=0,
            benefit_recovery_owed_cents=4_500,
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=14_800)


# ----------------------------------------------------------------------
# One posting, the whole declared side-effect set
# ----------------------------------------------------------------------
class TestPostingAPlatinumStayFiresEverySideEffect:
    def test_the_award_uses_the_snapshotted_top_tier_multiplier_and_assesses_the_fee(
        self, api
    ):
        """Two thousand base points earn fifteen hundred bonus points at the platinum
        multiplier, and five percent of the room revenue is assessed as fee.

        PRD: "Per stay, the fee is the stay's `room_revenue_cents` multiplied by the
        property's `program_fee_pct`, rounded half up to the whole cent, and stored on the
        stay as `program_fee_assessed_cents`"

        Design: Corner/state_machines/posting_a_platinum_stay_synthesizes_three_obligated_deliveries_and_two_ledger_entries
        """
        bundle = _sideeffect_grand_with_a_platinum_snapshot(api)
        assert_stay(bundle["second_stay"], tier_at_checkin="PLATINUM")

        posted = fx.post_stay(api, bundle["second_stay"]["id"], headers=bundle["owner"])

        assert_stay(
            posted,
            status="POSTED_QUALIFYING",
            base_points=2_000,
            bonus_points=1_500,
            bonus_multiplier=0.75,
            fee_cents=1_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=26_000,
        )

    def test_three_obligations_are_synthesised_and_the_base_tier_stay_produced_none(
        self, api
    ):
        """Entitlement is keyed on the snapshot, so the platinum stay owes all three
        benefits while the stay that carried the guest there owes nothing.

        PRD: "The entitlement matrix reads the stay's `tier_at_checkin`: `UPGRADE` is owed
        at `SILVER`, `GOLD` and `PLATINUM`; `BREAKFAST` is owed at `GOLD` and `PLATINUM`;
        `LATE_CHECKOUT` is owed at `PLATINUM` only; and a `BASE` guest is entitled to
        nothing at all."

        Design: Corner/state_machines/posting_a_platinum_stay_synthesizes_three_obligated_deliveries_and_two_ledger_entries
        """
        bundle = _sideeffect_grand_with_a_platinum_snapshot(api)

        fx.post_stay(api, bundle["second_stay"]["id"], headers=bundle["owner"])

        obligations = fx.obligations_for_stay(api, bundle["second_stay"]["id"])
        assert len(obligations) == 3, (
            f"a platinum stay owes three benefits, got {len(obligations)}"
        )
        assert_entitlement_for_tier(obligations, "PLATINUM")
        for obligation in obligations:
            assert_delivery(obligation, status="OBLIGATED", cost_recovery_cents=0)
            assert obligation["denial_reason"] is None, obligation["denial_reason"]
        assert fx.obligations_for_stay(api, bundle["first_stay"]["id"]) == [], (
            "the stay whose snapshot was BASE synthesises no obligation at all"
        )

    def test_the_same_posting_writes_two_ledger_rows_and_revalues_the_fund(self, api):
        """The base and bonus awards each become their own entry, and because the ledger
        moved the fund's valuation and posture are re-derived.

        PRD: "One `EARN_BASE` entry is written with `points` equal to
        `base_points_awarded` and `source_stay_id` naming the stay; one `EARN_BONUS` entry
        is written with `points` equal to `bonus_points_awarded` and the same
        `source_stay_id`, and that second entry is emitted **only** when
        `bonus_points_awarded` is greater than zero."

        Design: Corner/state_machines/posting_a_platinum_stay_synthesizes_three_obligated_deliveries_and_two_ledger_entries
        """
        bundle = _sideeffect_grand_with_a_platinum_snapshot(api)

        fx.post_stay(api, bundle["second_stay"]["id"], headers=bundle["owner"])

        entries = fx.ledger_for_stay(api, bundle["second_stay"]["id"])
        assert len(entries) == 2, f"one posting writes two entries, got {len(entries)}"
        assert_ledger_entry(
            entries_of_type(entries, "EARN_BASE")[0],
            entry_type="EARN_BASE",
            points=2_000,
            source_stay_id=bundle["second_stay"]["id"],
        )
        assert_ledger_entry(
            entries_of_type(entries, "EARN_BONUS")[0],
            entry_type="EARN_BONUS",
            points=1_500,
            source_stay_id=bundle["second_stay"]["id"],
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="PLATINUM",
            point_balance=53_500,
            lifetime_points_earned=53_500,
            qualifying_nights=52,
        )
        assert_fund(
            fx.read_fund(api),
            status="IMPAIRED",
            outstanding_points=53_500,
            liability_cents=25_680,
            cash_cents=0,
        )
