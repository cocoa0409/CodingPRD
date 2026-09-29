"""Benefit adjudication across two obligations that diverged, the seven-clear-day
blackout buffer, and the compensating unwind of a wholesale point sale."""

from test_helpers import (
    ApiErrorId,
    assert_blackout_window,
    assert_complaint,
    assert_delivery,
    assert_fund,
    assert_hotel,
    assert_ledger_entry,
    assert_member,
    assert_partner,
    assert_purchase,
    assert_scoped_ledger_sum_is_zero,
    entries_of_type,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_care_agent_headers,
    make_member_headers,
    read_entity,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _waybrook_with_one_honoured_and_one_denied_upgrade(api):
    """A SILVER guest with two short stays at the same property: one upgrade was
    honoured, the other refused, and both are contested by upheld complaints."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-WAU",
        rate_category="TRANSIENT",
        name="Waybrook Union",
        brand_code="WAU",
        market_tier="URBAN",
        program_fee_pct=0.03,
        rooms_count=130,
        trailing_12m_occupancy_pct=0.77,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(api)
    member_headers = make_member_headers(member["id"])
    agent_headers = make_care_agent_headers("care-01")

    fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-05-01", "2026-05-11", 300_000
    )
    honoured_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-06-01", "2026-06-04", 60_000
    )
    denied_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-06-10", "2026-06-12", 40_000
    )

    honoured = fx.obligation_of_type(api, honoured_stay["id"], "UPGRADE")
    honoured = fx.deliver_obligation(api, honoured["id"])
    denied = fx.obligation_of_type(api, denied_stay["id"], "UPGRADE")
    denied = fx.deny_obligation(
        api, denied["id"], reason="No upgrade inventory on the arrival date"
    )

    complaints = []
    for obligation in (honoured, denied):
        complaint = fx.file_complaint(
            api,
            member["id"],
            subject_type="BENEFIT_DENIAL",
            related_delivery_id=obligation["id"],
            headers=member_headers,
        )
        fx.review_complaint(api, complaint["id"], headers=agent_headers)
        complaint = fx.resolve_complaint(
            api,
            complaint["id"],
            resolution="Property records reviewed; the denial stands.",
            headers=agent_headers,
        )
        complaints.append(complaint)

    bundle["member"] = member
    bundle["member_headers"] = member_headers
    bundle["agent_headers"] = agent_headers
    bundle["honoured_stay"] = honoured_stay
    bundle["denied_stay"] = denied_stay
    bundle["honoured_obligation"] = honoured
    bundle["denied_obligation"] = denied
    bundle["complaint_about_honoured"] = complaints[0]
    bundle["complaint_about_denied"] = complaints[1]
    return bundle


def _bayhurst_with_one_active_and_two_drafted_blackouts(api):
    """A resort holding one active five-day November blackout, plus two overlapping
    drafts - one six clear days away, one seven."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-BHR",
        rate_category="TRANSIENT",
        name="Bayhurst Reserve",
        brand_code="BHR",
        market_tier="RESORT",
        program_fee_pct=0.045,
        rooms_count=70,
        trailing_12m_occupancy_pct=0.66,
        trailing_12m_adr_cents=41_000,
    )
    hotel_id = bundle["hotel"]["id"]

    first = fx.create_active_blackout(
        api, hotel_id, "2026-11-01", "2026-11-05", scope="ALL_REDEMPTIONS"
    )
    six_day_gap = fx.draft_blackout(
        api, hotel_id, "2026-11-12", "2026-11-14", scope="ALL_REDEMPTIONS"
    )
    seven_day_gap = fx.draft_blackout(
        api, hotel_id, "2026-11-13", "2026-11-15", scope="STANDARD_ONLY"
    )

    bundle["active_window"] = first
    bundle["six_day_gap"] = six_day_gap
    bundle["seven_day_gap"] = seven_day_gap
    return bundle


def _northwind_settled_wholesale_purchase(api):
    """A settled 200,000-point wholesale sale: the programme's cash, the member's
    balance, the partner's month and the member's annual cap all rest on it."""
    partner = fx.create_partner(
        api,
        name="Northwind Air Rewards",
        partner_type="AIRLINE",
        points_cost_per_1000_cents=5_000,
        monthly_cap_points=500_000,
    )
    member = fx.enroll_member(api)
    purchase = fx.record_purchase(
        api, member["id"], 200_000, channel="PARTNER_SALE", partner_id=partner["id"]
    )
    purchase = fx.settle_purchase(api, purchase["id"])

    return {
        "partner": partner,
        "member": member,
        "member_headers": make_member_headers(member["id"]),
        "purchase": purchase,
    }


# ----------------------------------------------------------------------
# Escalation needs a live denial to argue about.
# ----------------------------------------------------------------------
class TestEscalationBlockedByAnHonouredBenefit:
    def test_escalation_is_refused_when_the_obligation_was_honoured(self, api):
        """The complaint is in the one status escalation accepts, but the benefit it
        contests was delivered, so there is nothing left to argue about.

        PRD: "When the complaint's `subject_type` is `BENEFIT_DENIAL`, the obligation
        named by `related_delivery_id` must still be in `DENIED`, else
        `ERR_DELIVERY_NOT_DENIED` — a property that has since honoured the benefit
        leaves nothing to argue about"

        Design: Difficulty/cross_entity_state_dependency/complaint_escalation_blocked_because_the_related_delivery_was_honoured_meanwhile
        """
        bundle = _waybrook_with_one_honoured_and_one_denied_upgrade(api)
        complaint = bundle["complaint_about_honoured"]
        assert_complaint(complaint, status="RESOLVED_UPHELD")
        assert_delivery(
            bundle["honoured_obligation"], status="DELIVERED", cost_recovery_cents=4_500
        )

        response = api.escalate_complaint(complaint["id"], bundle["member_headers"])

        validate_error(response, ApiErrorId.ERR_DELIVERY_NOT_DENIED.value)
        assert_complaint(
            fx.read_complaint(api, complaint["id"]), status="RESOLVED_UPHELD"
        )

    def test_the_live_denial_escalates_and_takes_its_obligation_with_it(self, api):
        """The sibling complaint contests an obligation still sitting in DENIED, so
        both the complaint and the obligation advance.

        PRD: "and on success that obligation advances `DENIED → ESCALATED` and the
        property's `benefit_denial_count` is recomputed, which leaves the figure
        unchanged because `ESCALATED` remains inside the counted set."

        Design: Difficulty/cross_entity_state_dependency/complaint_escalation_blocked_because_the_related_delivery_was_honoured_meanwhile
        """
        bundle = _waybrook_with_one_honoured_and_one_denied_upgrade(api)

        escalated = fx.escalate_complaint(
            api,
            bundle["complaint_about_denied"]["id"],
            headers=bundle["member_headers"],
        )

        assert_complaint(escalated, status="ESCALATED")
        assert_delivery(
            fx.obligation_of_type(api, bundle["denied_stay"]["id"], "UPGRADE"),
            status="ESCALATED",
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]), benefit_denial_count=1
        )

    def test_ordering_delivery_pays_the_recovery_and_clears_the_denial_count(self, api):
        """The property is paid what honouring the benefit would have earned, and the
        obligation leaves the counted set on its way out.

        PRD: "An `ESCALATED` obligation advances `ESCALATED → DELIVERED` when
        adjudication orders delivery — in which case the cost recovery above is
        computed and both `benefit_denial_count` and `benefit_recovery_owed_cents` are
        recomputed, since the obligation both left the denied set and entered the
        delivered one"

        Design: Difficulty/cross_entity_state_dependency/complaint_escalation_blocked_because_the_related_delivery_was_honoured_meanwhile
        """
        bundle = _waybrook_with_one_honoured_and_one_denied_upgrade(api)
        fx.escalate_complaint(
            api,
            bundle["complaint_about_denied"]["id"],
            headers=bundle["member_headers"],
        )

        closed = fx.adjudicate_complaint(
            api,
            bundle["complaint_about_denied"]["id"],
            adjudication_outcome="DELIVERY_ORDERED",
        )

        assert_complaint(
            closed, status="CLOSED", adjudication_outcome="DELIVERY_ORDERED"
        )
        assert_delivery(
            fx.obligation_of_type(api, bundle["denied_stay"]["id"], "UPGRADE"),
            status="DELIVERED",
            cost_recovery_cents=4_500,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            benefit_recovery_owed_cents=9_000,
            benefit_denial_count=0,
        )

    def test_adjudication_moves_no_points_even_when_the_member_wins(self, api):
        """Winning an escalation buys the benefit, not a point credit.

        PRD: "Adjudication moves **no** points under any outcome.
        `goodwill_points_granted` is unchanged by adjudication even when the member
        wins, because goodwill is granted only by resolving a complaint or by an
        explicit point adjustment; a member whose escalation succeeds gets the benefit
        ordered delivered at the property's expense, not a point credit."

        Design: Difficulty/cross_entity_state_dependency/complaint_escalation_blocked_because_the_related_delivery_was_honoured_meanwhile
        """
        bundle = _waybrook_with_one_honoured_and_one_denied_upgrade(api)
        fx.escalate_complaint(
            api,
            bundle["complaint_about_denied"]["id"],
            headers=bundle["member_headers"],
        )

        closed = fx.adjudicate_complaint(
            api,
            bundle["complaint_about_denied"]["id"],
            adjudication_outcome="DELIVERY_ORDERED",
        )

        assert_complaint(closed, goodwill_points_granted=0)
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="SILVER",
            qualifying_nights=15,
            point_balance=42_000,
        )


# ----------------------------------------------------------------------
# The blackout buffer counts clear days between inclusive endpoints.
# ----------------------------------------------------------------------
class TestBlackoutWindowsNeedSevenClearDays:
    def test_a_six_day_gap_is_refused(self, api):
        """A window ending on the fifth followed by one starting on the twelfth leaves
        six clear days, one short of the buffer.

        PRD: "Because the endpoints are inclusive, a window ending on the fifth of
        December followed by one starting on the thirteenth leaves exactly seven clear
        days and is accepted, while a start on the twelfth leaves six and is refused;
        direct adjacency leaves zero clear days and any overlap leaves fewer than
        zero, so both are refused as well."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_need_seven_clear_days_so_a_six_day_gap_is_refused
        """
        bundle = _bayhurst_with_one_active_and_two_drafted_blackouts(api)
        assert_blackout_window(bundle["active_window"], status="ACTIVE", day_count=5)
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), blackout_days_used=5)

        response = api.activate_blackout_window(
            bundle["six_day_gap"]["id"], make_admin_headers()
        )

        validate_error(response, ApiErrorId.ERR_BLACKOUT_WINDOW_BUFFER_CONFLICT.value)
        assert_blackout_window(
            read_entity(
                api.get_blackout_window,
                bundle["six_day_gap"]["id"],
                make_admin_headers(),
            ),
            status="DRAFT",
        )

    def test_the_refused_activation_consumed_none_of_the_annual_allowance(self, api):
        """A draft blocks nothing and costs nothing, so the consumed allowance is still
        the active window's five days.

        PRD: "Only `ACTIVE` windows participate in either check: `DRAFT` and `REVOKED`
        windows neither block an activation nor consume the annual allowance."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_need_seven_clear_days_so_a_six_day_gap_is_refused
        """
        bundle = _bayhurst_with_one_active_and_two_drafted_blackouts(api)

        api.activate_blackout_window(bundle["six_day_gap"]["id"], make_admin_headers())

        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), blackout_days_used=5)

    def test_seven_clear_days_is_accepted_and_adds_its_days_to_the_allowance(self, api):
        """One day later the buffer is met exactly, and activation consumes the
        window's inclusive day count.

        PRD: "On success the window moves `DRAFT → ACTIVE`, its `day_count` is added
        to the property's consumed allowance, and the window's `version` increments."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_need_seven_clear_days_so_a_six_day_gap_is_refused
        """
        bundle = _bayhurst_with_one_active_and_two_drafted_blackouts(api)
        api.activate_blackout_window(bundle["six_day_gap"]["id"], make_admin_headers())

        activated = fx.activate_blackout(api, bundle["seven_day_gap"]["id"])

        assert_blackout_window(
            activated, status="ACTIVE", day_count=3, scope="STANDARD_ONLY"
        )
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), blackout_days_used=8)

    def test_the_still_drafted_window_did_not_block_its_overlapping_sibling(self, api):
        """The two drafts overlap each other, yet the second activates cleanly because
        only active windows are compared.

        PRD: "That comparison is made pairwise: for each other `ACTIVE` window of the
        property, order the two windows by `start_date` ascending, breaking a tie by
        `created_at` ascending, and count the clear days strictly between them as the
        number of days from the earlier window's `end_date` to the later window's
        `start_date`, minus one."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_need_seven_clear_days_so_a_six_day_gap_is_refused
        """
        bundle = _bayhurst_with_one_active_and_two_drafted_blackouts(api)

        fx.activate_blackout(api, bundle["seven_day_gap"]["id"])

        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), blackout_days_used=8)


# ----------------------------------------------------------------------
# A refund is the exact compensating action for a settlement.
# ----------------------------------------------------------------------
class TestPurchaseRefundReturnsCashVolumeAndCap:
    def test_settlement_puts_cash_points_and_partner_volume_on_the_books(self, api):
        """The wholesale price is discounted twelve percent at 200,000 points and
        rounded once, and every derived figure follows from the single entry.

        PRD: "The `cash_due_cents` is the quantity in thousands multiplied by that
        list price, multiplied by one minus the discount, and rounded half up **once**
        at the end of that whole expression — rounding the discount separately or
        rounding the undiscounted price first can differ by a cent."

        Design: Difficulty/compensating_invariant/purchase_refund_returns_program_cash_partner_volume_and_the_annual_purchase_cap
        """
        bundle = _northwind_settled_wholesale_purchase(api)

        assert_purchase(
            bundle["purchase"],
            status="SETTLED",
            cash_due_cents=880_000,
            bonus_points=0,
            volume_discount_pct=0.12,
            channel="PARTNER_SALE",
            points_quantity=200_000,
        )
        assert_fund(
            fx.read_fund(api),
            cash_cents=880_000,
            outstanding_points=200_000,
            liability_cents=96_000,
            solvency_ratio=9.1667,
            status="HEALTHY",
        )
        assert_partner(
            read_entity(api.get_partner, bundle["partner"]["id"], make_admin_headers()),
            purchased_points_mtd=200_000,
        )

    def test_the_refund_reverses_the_one_entry_settlement_wrote(self, api):
        """A wholesale sale carries no bonus, so it takes exactly one reversal, and the
        purchase's ledger scope closes at zero.

        PRD: "One `REVERSAL` entry is written for every existing entry whose
        `source_purchase_id` names this purchase — two entries for a co-brand purchase
        that carried a bonus, one otherwise — each carrying the negation of the
        original entry's `points` and `reversal_of_entry_id` naming it."

        Design: Difficulty/compensating_invariant/purchase_refund_returns_program_cash_partner_volume_and_the_annual_purchase_cap
        """
        bundle = _northwind_settled_wholesale_purchase(api)
        purchase_id = bundle["purchase"]["id"]
        original = entries_of_type(
            fx.ledger_for_purchase(api, purchase_id), "PARTNER_SALE"
        )[0]

        refunded = fx.refund_purchase(
            api, purchase_id, reason="Partner cancelled the wholesale order"
        )

        assert_purchase(
            refunded,
            status="REFUNDED",
            refund_reason="Partner cancelled the wholesale order",
        )
        reversals = entries_of_type(fx.ledger_for_purchase(api, purchase_id), "REVERSAL")
        assert len(reversals) == 1, (
            f"a wholesale sale wrote one entry, so it takes one reversal, saw {len(reversals)}"
        )
        assert_ledger_entry(
            reversals[0],
            entry_type="REVERSAL",
            points=-200_000,
            reversal_of_entry_id=original["id"],
            source_purchase_id=purchase_id,
        )
        assert_scoped_ledger_sum_is_zero(fx.ledger_for_purchase(api, purchase_id))

    def test_the_refund_returns_cash_partner_volume_and_the_annual_cap(self, api):
        """Everything the settlement consumed comes back: programme cash, the
        member's annual purchase allowance and the partner's month-to-date volume.

        PRD: "The member's `point_balance` and `points_purchased_current_year`, the
        partner's `purchased_points_mtd`, and the fund's `outstanding_points`,
        `point_liability_cents`, `solvency_ratio` and `status` are all recomputed, and
        the purchase's `version` increments."

        Design: Difficulty/compensating_invariant/purchase_refund_returns_program_cash_partner_volume_and_the_annual_purchase_cap
        """
        bundle = _northwind_settled_wholesale_purchase(api)

        fx.refund_purchase(api, bundle["purchase"]["id"], reason="Order cancelled")

        assert_fund(
            fx.read_fund(api),
            cash_cents=0,
            outstanding_points=0,
            liability_cents=0,
            solvency_ratio=999.0000,
            status="HEALTHY",
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            point_balance=0,
            points_purchased_current_year=0,
        )
        assert_partner(
            read_entity(api.get_partner, bundle["partner"]["id"], make_admin_headers()),
            purchased_points_mtd=0,
        )

    def test_the_returned_allowances_let_the_same_volume_be_bought_again(self, api):
        """Both caps were released, so an identical wholesale order is accepted - and
        it puts no cash on the books until it is settled.

        PRD: "The purchase is created in status `PENDING` with `refund_reason` null.
        Nothing has happened yet in the programme's books: **no** ledger entry is
        written, **no** points reach the member's balance and **no** cash reaches the
        fund."

        Design: Difficulty/compensating_invariant/purchase_refund_returns_program_cash_partner_volume_and_the_annual_purchase_cap
        """
        bundle = _northwind_settled_wholesale_purchase(api)
        fx.refund_purchase(api, bundle["purchase"]["id"], reason="Order cancelled")

        response = api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["member"]["id"],
                points_quantity=200_000,
                channel="PARTNER_SALE",
                partner_id=bundle["partner"]["id"],
            ),
            make_admin_headers(),
        )

        replacement = validate_success(response, 201)
        assert_purchase(replacement, status="PENDING", cash_due_cents=880_000)
        assert_fund(fx.read_fund(api), cash_cents=0)
