"""Corner coverage: escalated price anniversary boundary, amenity trigger
breach via closing, fine tier boundary 30/31, payment certification
floor/excess, and the event budget remaining boundary."""
from test_helpers import (
    api_client,
    create_active_community,
    create_adopted_budget,
    create_amenity_in_state,
    create_and_close_lot,
    create_district_with_advances,
    create_event_payload,
    create_offered_lot,
    create_open_phase,
    create_builder,
    create_phase,
    create_lot,
    create_requested_payment,
    create_resident,
    create_violation_hearing_scheduled,
    create_closing_payload,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestEscalatedPriceAnniversaryBoundary:
    """Agreement executed at the default clock 2026-05-01 with 6% escalation:
    closing 2027-04-30 prices at base+premium (0 anniversaries); closing
    exactly on 2027-05-01 counts the anniversary."""

    def _setup(self):
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)], community_name="Anniversary Arms",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "A1", lot_premium_cents=250000)
        lot2 = create_offered_lot(scenario["phase"]["id"], "A2", lot_premium_cents=250000)
        cl1 = get_success_data(
            api_client.create_closing(
                create_closing_payload(
                    agreement_id=scenario["agreement"]["id"], lot_id=lot1["id"]
                ),
                CTRL,
            )
        )
        cl2 = get_success_data(
            api_client.create_closing(
                create_closing_payload(
                    agreement_id=scenario["agreement"]["id"], lot_id=lot2["id"]
                ),
                CTRL,
            )
        )
        return scenario, cl1, cl2

    def test_closing_before_first_anniversary_prices_at_base(self):
        """PRD §3.4: "The escalated base counts the agreement's anniversaries: the number of calendar dates formed by adding whole years to `execution_date` that fall on or before the `closing_date` — a closing exactly on an anniversary counts that anniversary, and before the first anniversary the count is zero."
        PRD §3.4: "The escalated base counts the agreement's anniversaries: the number of calendar dates formed by adding whole years to `execution_date` that fall on or before the `closing_date` — a closing exactly on an anniversary counts that anniversary, and before the first anniversary the count is zero. `escalated_base_cents` is the agreement's `base_price_per_lot_cents` compounded by `annual_escalation_pct` percent per elapsed anniversary, rounded half-up to a whole cent. `premium_cents` captures the lot's `lot_premium_cents` at the moment of close, and `price_cents` is the escalated base plus the premium."

        Design: Corner/calculations/escalated_price_anniversary_boundary
        """
        scenario, cl1, _ = self._setup()
        set_clock("2027-04-30T00:00:00Z")
        closed = get_success_data(api_client.close_closing(cl1["id"], CTRL))
        assert closed["escalated_base_cents"] == 5000000
        assert closed["price_cents"] == 5250000, (
            f"0 anniversaries: 5000000 + 250000 = 5250000, got {closed['price_cents']}"
        )

    def test_closing_exactly_on_anniversary_counts_it(self):
        """PRD §3.4: "The escalated base counts the agreement's anniversaries: the number of calendar dates formed by adding whole years to `execution_date` that fall on or before the `closing_date` — a closing exactly on an anniversary counts that anniversary, and before the first anniversary the count is zero. `escalated_base_cents` is the agreement's `base_price_per_lot_cents` compounded by `annual_escalation_pct` percent per elapsed anniversary, rounded half-up to a whole cent. `premium_cents` captures the lot's `lot_premium_cents` at the moment of close, and `price_cents` is the escalated base plus the premium.".
        PRD §3.4: "The escalated base counts the agreement's anniversaries: the number of calendar dates formed by adding whole years to `execution_date` that fall on or before the `closing_date` — a closing exactly on an anniversary counts that anniversary, and before the first anniversary the count is zero. `escalated_base_cents` is the agreement's `base_price_per_lot_cents` compounded by `annual_escalation_pct` percent per elapsed anniversary, rounded half-up to a whole cent."

        Design: Corner/calculations/escalated_price_anniversary_boundary
        """
        scenario, cl1, cl2 = self._setup()
        set_clock("2027-04-30T00:00:00Z")
        get_success_data(api_client.close_closing(cl1["id"], CTRL))
        set_clock("2027-05-01T00:00:00Z")
        closed = get_success_data(api_client.close_closing(cl2["id"], CTRL))
        # 5,000,000 * 1.06 = 5,300,000; + 250,000 premium = 5,550,000.
        assert closed["escalated_base_cents"] == 5300000
        assert closed["price_cents"] == 5550000, (
            f"1 anniversary: 5300000 + 250000 = 5550000, got {closed['price_cents']}"
        )


class TestAmenityTriggerBreachViaClosing:
    """trigger_unit_count 1: the closing that makes the phase count EQUAL (1)
    is safe; the next closing (count 2 > 1) breaches."""

    def _setup(self):
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)], community_name="Trigger Terrace",
            earnest_money_cents=1000000,
        )
        amenity = create_amenity_in_state(
            scenario["community"]["id"], "UNDER_CONSTRUCTION", "CLUBHOUSE",
            hard_deadline_date="2027-12-31T00:00:00Z",
            trigger_phase_id=scenario["phase"]["id"], trigger_unit_count=1,
        )
        # Scheduled at the default clock: amenity UNDER_CONSTRUCTION passes the
        # safety gate; lead time is 40 days.
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=scenario["community"]["id"], title="Hard Hat Tour",
                    venue="CLUBHOUSE", start_at="2026-06-10T10:00:00Z",
                    end_at="2026-06-10T12:00:00Z", capacity=20,
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        lot1 = create_offered_lot(scenario["phase"]["id"], "T1")
        lot2 = create_offered_lot(scenario["phase"]["id"], "T2")
        set_clock("2026-06-01T00:00:00Z")
        return scenario, amenity, event, lot1, lot2

    def test_count_equal_to_trigger_is_safe_then_breach_cascades(self):
        """PRD §3.2: "Two independent breach conditions drop a not-yet-open amenity into `DELINQUENT`: the sweep passing its `hard_deadline_date`, or a closing-driven trigger breach — whenever the trigger phase's `closed_lot_count` increments, every amenity keyed to that phase whose status is not already `OPEN` or `DELINQUENT` is checked, and a count strictly greater than `trigger_unit_count` breaches it (the closing that makes the count exactly equal to `trigger_unit_count` is safe)."
        PRD §3.2: "Entering `DELINQUENT` stamps `delinquency_recorded_at` with the logical clock and fires a three-part cascade: every `SCHEDULED` community event whose venue maps to this amenity's type is cancelled, with its RSVPs cancelled in turn (this is reachable precisely because scheduling an event only requires the venue's amenity to be under construction); and a `DRAFT` resident notice of type `AMENITY_DELINQUENCY` is auto-created for the community."

        Design: Corner/calculations/amenity_trigger_breach_via_closing
        """
        scenario, amenity, event, lot1, lot2 = self._setup()
        create_and_close_lot(scenario["agreement"]["id"], lot1["id"])
        mid = get_success_data(api_client.get_amenity(amenity["id"], EXEC))
        assert mid["status"] == "UNDER_CONSTRUCTION", (
            f"count 1 == trigger 1 is safe, got {mid['status']}"
        )

        create_and_close_lot(scenario["agreement"]["id"], lot2["id"])
        post = get_success_data(api_client.get_amenity(amenity["id"], EXEC))
        assert post["status"] == "DELINQUENT"
        assert post["delinquency_recorded_at"] == "2026-06-01T00:00:00.000Z"

        event_read = get_success_data(api_client.get_event(event["id"], LIFESTYLE))
        assert event_read["status"] == "CANCELLED"

        notices = get_success_data(
            api_client.list_notices(LIFESTYLE, params={"community_id": scenario["community"]["id"]})
        )
        auto = [n for n in notices if n["notice_type"] == "AMENITY_DELINQUENCY"]
        assert len(auto) == 1
        assert auto[0]["status"] == "DRAFT"


class TestFineTierBoundary3031:
    """Same-community sibling violations both noticed at the default clock
    share the 2026-05-15 cure deadline; levy one at day 30 and the other at
    day 31."""

    def _setup_pair(self):
        community = create_active_community("Tier Terrace", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot1 = create_lot(phase["id"], "B1")
        lot2 = create_lot(phase["id"], "B2")
        resident = create_resident(community["id"], "Tim Tier", "tim@x.com")
        from test_helpers import create_violation
        ids = []
        for lot in (lot1, lot2):
            v = create_violation(
                community["id"], lot["id"],
                respondent_resident_id=resident["id"], violation_type="LANDSCAPE_DEADLINE",
            )
            get_success_data(
                api_client.send_violation_notice(v["id"], TEST_USERS["design_reviewer_headers"])
            )
            ids.append(v["id"])
        set_clock("2026-05-16T00:00:00Z")
        for vid in ids:
            get_success_data(
                api_client.escalate_violation(vid, TEST_USERS["design_reviewer_headers"])
            )
            get_success_data(
                api_client.schedule_hearing(vid, {"hearing_date": "2026-06-01T00:00:00Z"}, DIRECTOR)
            )
        return ids

    def test_exactly_30_vs_31_days(self):
        """PRD §3.7: "Levying the fine moves it to `FINED`, stamps `fined_by_user_id`, freezes `days_late`, and computes `fine_cents` on a tiered schedule at the levy timestamp: the first thirty days late accrue 5000 cents per day, days thirty-one through sixty accrue 10000 cents per day, and every day beyond sixty accrues 20000 cents per day, with the total capped at 1000000 cents; no days late means no fine.".
        PRD §3.7: "The violation's `days_late` measures the calendar days from `cure_deadline` to the earliest of the cure timestamp, the fine timestamp, and the current clock — zero while the deadline has not passed.".

        Design: Corner/calculations/fine_tier_boundary_30_31
        """
        v1_id, v2_id = self._setup_pair()
        set_clock("2026-06-14T00:00:00Z")
        fined30 = get_success_data(api_client.levy_fine(v1_id, DIRECTOR))
        assert fined30["days_late"] == 30
        assert fined30["fine_cents"] == 150000
        set_clock("2026-06-15T00:00:00Z")
        fined31 = get_success_data(api_client.levy_fine(v2_id, DIRECTOR))
        assert fined31["days_late"] == 31
        assert fined31["fine_cents"] == 160000, (
            f"30*5000 + 1*10000 = 160000, got {fined31['fine_cents']}"
        )


class TestPaymentCertificationInterestFloorAndExcess:
    def _setup(self):
        community = create_active_community("Waterfall Wash", 10)
        district, _ = create_district_with_advances(
            community["id"], [(100000, "2026-04-30T00:00:00Z")], district_name="MUD 1"
        )
        return district

    def test_excess_and_below_floor_rejected_exact_interest_certifies(self):
        """PRD §3.6: "The claimed `amount_cents` may not exceed the district's `outstanding_principal_cents` plus the daily-compound interest accrued across all advances to the certification moment (`ERR_PAYMENT_EXCEEDS_OBLIGATION`). The certified interest, `certified_interest_cents`, is the sum of the daily-compound interest over all advances to that timestamp, and the certified principal, `certified_principal_cents`, is the claim amount minus that interest — a claim too small to cover the interest due would make that figure negative and is likewise rejected `ERR_PAYMENT_EXCEEDS_OBLIGATION`."

        Design: Corner/calculations/payment_certification_interest_floor_and_excess
        """
        district = self._setup()
        # Single 100,000c advance dated 2026-04-30, 1 day outstanding at the
        # default clock: round_half_up(100000 * ((1+0.05/365)^1 - 1)) = 14c.
        pay_big = create_requested_payment(district["id"], 200000)
        pay_small = create_requested_payment(district["id"], 10)
        pay_exact = create_requested_payment(district["id"], 14)

        resp_big = api_client.certify_payment(pay_big["id"], DIRECTOR)
        validate_error(resp_big, ApiErrorId.ERR_PAYMENT_EXCEEDS_OBLIGATION)

        resp_small = api_client.certify_payment(pay_small["id"], DIRECTOR)
        validate_error(resp_small, ApiErrorId.ERR_PAYMENT_EXCEEDS_OBLIGATION)

        certified = get_success_data(api_client.certify_payment(pay_exact["id"], DIRECTOR))
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_interest_cents"] == 14
        assert certified["certified_principal_cents"] == 0
        read = get_success_data(api_client.get_district(district["id"], CTRL))
        assert read["outstanding_principal_cents"] == 100000


class TestEventBudgetRemainingBoundary:
    def _setup_budgets(self):
        """FY2027 budget ADOPTED with EVENTS_PROGRAMMING 100,000c; FY2028
        budget ADOPTED with no events line. Clock left at 2026-06-02."""
        community = create_active_community("Budget Basin", 10)
        bud27 = create_adopted_budget(
            community["id"], 2027, [("EVENTS_PROGRAMMING", 100000)],
            notice_send_at="2026-05-02T00:00:00Z", adopt_at="2026-05-17T00:00:00Z",
        )
        bud28 = create_adopted_budget(
            community["id"], 2028, [("MANAGEMENT", 50000)],
            notice_send_at="2026-05-18T00:00:00Z", adopt_at="2026-06-02T00:00:00Z",
        )
        return community, bud27, bud28

    def test_exact_remaining_passes_and_one_cent_over_fails(self):
        """PRD §3.8: "Finally the fiscal gate for costed events: the charged budget must be `ADOPTED`, and its `EVENTS_PROGRAMMING` line (zero when the line is absent) minus the `cost_cents` of events already `SCHEDULED` or `COMPLETED` against that budget must leave room for this `cost_cents` (`ERR_EVENT_BUDGET_EXCEEDED`); a cost exactly equal to the remaining room passes."

        Design: Corner/calculations/event_budget_remaining_boundary
        """
        community, bud27, bud28 = self._setup_budgets()

        def make_event(title, day, cost, budget_id):
            return get_success_data(
                api_client.create_event(
                    create_event_payload(
                        community_id=community["id"], title=title,
                        start_at=f"2026-07-0{day}T10:00:00Z", end_at=f"2026-07-0{day}T12:00:00Z",
                        cost_cents=cost, charged_budget_id=budget_id,
                    ),
                    LIFESTYLE,
                )
            )

        ea = make_event("EA", 1, 60000, bud27["id"])
        eb = make_event("EB", 2, 40000, bud27["id"])
        ec = make_event("EC", 3, 1, bud27["id"])
        ed = make_event("ED", 4, 5000, bud28["id"])

        assert get_success_data(api_client.schedule_event(ea["id"], LIFESTYLE))["status"] == "SCHEDULED"
        assert get_success_data(api_client.schedule_event(eb["id"], LIFESTYLE))["status"] == "SCHEDULED", (
            "40,000 exactly exhausts the remaining 40,000 of the 100,000 line (inclusive)"
        )

        resp_ec = api_client.schedule_event(ec["id"], LIFESTYLE)
        validate_error(resp_ec, ApiErrorId.ERR_EVENT_BUDGET_EXCEEDED)

        resp_ed = api_client.schedule_event(ed["id"], LIFESTYLE)
        validate_error(resp_ed, ApiErrorId.ERR_EVENT_BUDGET_EXCEEDED)
