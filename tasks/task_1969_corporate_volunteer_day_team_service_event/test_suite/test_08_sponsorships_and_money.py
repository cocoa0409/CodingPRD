"""Sponsorship dual variants (provisional vs settled), cap boundary, net event cost,
spend-position variants, repeat-booking bonus, and sponsorship state rules."""
from test_helpers import (
    ApiErrorId,
    GLOVES_LINES,
    TEST_USERS,
    approve_order,
    begin_ready_event,
    check_in_registration,
    commit_sponsorship,
    complete_event,
    create_event,
    create_impact_record,
    create_manifest,
    create_order,
    create_sponsorship,
    create_vehicle,
    get_event,
    get_sponsorship,
    get_registration,
    lock_event_registration,
    make_employee_volunteer_headers,
    make_staff_lead_headers,
    open_event_registration,
    setup_matched_scenario,
    setup_ready_event,
    submit_order,
    submit_survey,
    validate_error,
    validate_success,
    verify_impact_record,
    verify_waiver,
)

FC = TEST_USERS["finance_headers"]


class TestSponsorshipDualVariant:
    def _setup_checkin_divergence(self):
        """Two CONFIRMED adults; only reg1's waiver is VERIFIED (only reg1 can check in).
        PER_CHECK_IN sponsorship (rate 2500, cap 100000) COMMITTED."""
        sc = setup_ready_event(
            event_name="Day A", num_adults=2, verify_waivers=False
        )
        verify_waiver(sc["registrations"][0]["id"])  # reg1 VERIFIED; reg2 stays SIGNED
        sponsorship = create_sponsorship(
            sc["event"]["id"],
            sponsor_name="CorpCo",
            match_type="PER_CHECK_IN",
            rate_cents=2500,
            pledge_cap_cents=100000,
        )
        commit_sponsorship(sponsorship["id"])
        sc["sponsorship"] = sponsorship
        return sc

    def test_provisional_counts_confirmed_headcount_forward_looking(self, api):
        """PRD §3.8: "The estimate's base depends on `match_type`: for `FLAT`, the base is simply `rate_cents`; for `PER_CHECK_IN`, the base is `rate_cents` multiplied by the event's `confirmed_headcount` (confirmed plus checked-in registrations); for `PER_VERIFIED_HOUR`, the base is `rate_cents` multiplied by the event's `confirmed_headcount` multiplied by the event's scheduled hours — the duration from `event_start_at` to `event_end_at` in hours — rounded half-up to whole cents. The provisional amount is the smaller of that base and `effective_cap_cents`."

        Design: Difficulty/dual_variant_calc/sponsorship_provisional_vs_settled_checkin_divergence
        """
        sc = self._setup_checkin_divergence()
        # 2 confirmed, 0 checked in: forward-looking set counts both
        sponsorship = get_sponsorship(sc["sponsorship"]["id"])
        assert sponsorship["provisional_amount_cents"] == 5000  # 2 x 2500
        assert sponsorship["effective_cap_cents"] == 100000

    def test_settled_counts_only_actual_checkins(self, api):
        """PRD §3.8: "for `PER_CHECK_IN`, the base is `rate_cents` multiplied by the event's `checked_in_headcount` — actual check-ins only, so a no-show who was counted in the provisional estimate drops out; for `PER_VERIFIED_HOUR`, the base is `rate_cents` multiplied by the event's `total_verified_hours`, rounded half-up to whole cents. The settled amount is again the smaller of the base and `effective_cap_cents`."
        PRD §3.7: "Along with the version increment and a full recompute of headcounts, spend, and posture, completing the event moves every registration still in `CONFIRMED` to `NO_SHOW` (the volunteers who never checked in; their `transport_manifest_id` is cleared), every `LOCKED` project of the event to `COMPLETED`, every manifest in `BOOKED` or `CONFIRMED` to `COMPLETED`, and every meal plan in `ORDERED` to `FULFILLED`."

        Design: Difficulty/dual_variant_calc/sponsorship_provisional_vs_settled_checkin_divergence
        """
        sc = self._setup_checkin_divergence()
        event_id = sc["event"]["id"]
        reg1, reg2 = sc["registrations"]

        begin_ready_event(event_id)
        # The assigned lead checks in reg1 (waiver VERIFIED); reg2 never checks in
        check_in_registration(reg1["id"], make_staff_lead_headers(sc["lead"]["id"]))
        complete_event(event_id)
        assert get_registration(reg2["id"])["rsvp_status"] == "NO_SHOW"

        settled = validate_success(
            api.settle_sponsorship(sc["sponsorship"]["id"], FC), 200
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 2500  # 1 checked-in x 2500
        # The two variants legitimately diverge on identical underlying data
        assert settled["settled_amount_cents"] != 5000


class TestSponsorshipCapEquality:
    def _setup_cap_equality(self):
        sc = setup_ready_event(event_name="Day L", verify_waivers=True)
        sponsorship = create_sponsorship(
            sc["event"]["id"],
            sponsor_name="HourlyCorp",
            match_type="PER_VERIFIED_HOUR",
            rate_cents=500,
            pledge_cap_cents=3000,
        )
        commit_sponsorship(sponsorship["id"])
        sc["sponsorship"] = sponsorship
        begin_ready_event(sc["event"]["id"])
        reg = sc["registrations"][0]
        check_in_registration(reg["id"], make_staff_lead_headers(sc["lead"]["id"]))
        np_id = sc["partner"]["id"]
        for hours in (3.5, 2.5):
            rec = create_impact_record(reg["id"], sc["project"]["id"], np_id, hours)
            verify_impact_record(rec["id"])
        complete_event(sc["event"]["id"])
        return sc

    def test_settled_amount_at_exact_cap_is_inclusive(self, api):
        """PRD §3.8: "The settled amount is again the smaller of the base and `effective_cap_cents`."
        PRD §3.8: "The cap a sponsor's money is actually capped at is `effective_cap_cents`: when the event's `repeat_booking_bonus` is true, it is `pledge_cap_cents` increased by 10 percent and rounded half-up to whole cents; otherwise it equals `pledge_cap_cents`."

        Design: Difficulty/boundary_precision_check/sponsorship_cap_exact_equality_settlement
        """
        sc = self._setup_cap_equality()
        settled = validate_success(
            api.settle_sponsorship(sc["sponsorship"]["id"], FC), 200
        )
        # base = 500 x 6.0 verified hours == 3000 == cap; min returns exactly the cap
        assert settled["effective_cap_cents"] == 3000
        assert settled["settled_amount_cents"] == 3000

    def test_verified_hours_total_feeds_the_base(self, api):
        """PRD §3.9: "Verification moves `SUBMITTED` → `VERIFIED` and recomputes verified hours everywhere: the registration's `verified_hours_credit` — the sum of its own impact records' `hours_attended` in `VERIFIED` or `PUBLISHED` status — and the event's `total_verified_hours`, the same sum across all impact records of the event."

        Design: Difficulty/boundary_precision_check/sponsorship_cap_exact_equality_settlement
        """
        sc = self._setup_cap_equality()
        event = get_event(sc["event"]["id"])
        assert event["total_verified_hours"] == 6.0
        assert get_registration(sc["registrations"][0]["id"])["verified_hours_credit"] == 6.0


class TestNetEventCost:
    def test_net_event_cost_offset_capped_at_half_gross(self, api, any_headers):
        """PRD §3.8: "The event's net cost is computed in a fixed evaluation order, because the sponsorship credit reduces net cost while the offset itself is capped by gross spend. First, gross is the event's `committed_spend_cents` from §2.8. Second, the credit is the sum over the event's sponsorships of `settled_amount_cents` for those `SETTLED` and `provisional_amount_cents` for those `COMMITTED`; `PLEDGED` and `WITHDRAWN` sponsorships contribute zero. Third, the offset is the smaller of that credit and one half of gross rounded half-up to whole cents — sponsors can defray at most half the committed spend. Fourth, `net_event_cost_cents` is gross minus the offset."

        Design: Corner/calculations/net_event_cost_offset_capped_at_half_gross
        """
        sc = setup_matched_scenario(
            event_name="Day 10", budget_cents=1000000, open_registration=False
        )
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=GLOVES_LINES)
        submit_order(order["id"])
        approve_order(order["id"])  # committed gross: round_half_up(2 x 500 x 1.0875) = 1088
        sponsorship = create_sponsorship(
            sc["event"]["id"],
            sponsor_name="FlatCorp",
            match_type="FLAT",
            rate_cents=10000,
            pledge_cap_cents=20000,
        )
        commit_sponsorship(sponsorship["id"])

        event = get_event(sc["event"]["id"])
        assert event["committed_spend_cents"] == 1088
        assert event["sponsorship_credit_cents"] == 10000  # COMMITTED provisional FLAT
        # offset = min(10000, round_half_up(0.5 x 1088) = 544) = 544; net = 1088 - 544
        assert event["net_event_cost_cents"] == 544


class TestSpendPositionVariants:
    def test_spend_position_projected_exceeds_committed_gap(self, api):
        """PRD §2.8: "`projected_spend_cents` is the forward-looking pipeline: the sum of `order_total_cents` over the event's procurement orders in `SUBMITTED`, `APPROVED`, or `RECEIVED` status, plus the sum of `total_cost_cents` over its meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over its transport manifests in `BOOKED`, `CONFIRMED`, or `COMPLETED` status."
        PRD §2.8: "`committed_spend_cents` is the firmed-liability position: the sum of `order_total_cents` over orders in `APPROVED` or `RECEIVED` status, plus the sum of `total_cost_cents` over meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over manifests in `CONFIRMED` or `COMPLETED` status. Submitted-but-unapproved orders and booked-but-unconfirmed manifests are deliberately excluded."

        Design: Corner/calculations/spend_position_projected_exceeds_committed_gap
        """
        sc = setup_matched_scenario(
            event_name="Day 14", budget_cents=1000000, open_registration=False
        )
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=GLOVES_LINES)
        submit_order(order["id"])  # SUBMITTED: in projected, not committed
        vehicle = create_vehicle()
        create_manifest(sc["event"]["id"], vehicle["id"], cost_cents=5000)  # BOOKED: same split

        event = get_event(sc["event"]["id"])
        assert event["projected_spend_cents"] == 1088 + 5000
        assert event["committed_spend_cents"] == 0
        assert event["available_budget_cents"] == 1000000 - 6088


class TestRepeatBookingBonus:
    def test_repeat_booking_bonus_threshold_and_window(self, api, cem_headers):
        """PRD §3.2: "the rebook operation takes a `name`, `event_start_at`, `event_end_at`, and `budget_cents` for the new event and requires the source event to be in `COMPLETED` or `CLOSED` status, failing otherwise with `ERR_REBOOK_NOT_ELIGIBLE` (HTTP 409)."
        PRD §3.2: "The new event's `repeat_booking_bonus` is computed at creation: it is true when the source event has a non-null `avg_feedback_rating` of at least 4.0 and the new event's `event_start_at` is no later than 180 days after the source event's `event_start_at`, and false otherwise."
        PRD §3.8: "The cap a sponsor's money is actually capped at is `effective_cap_cents`: when the event's `repeat_booking_bonus` is true, it is `pledge_cap_cents` increased by 10 percent and rounded half-up to whole cents; otherwise it equals `pledge_cap_cents`."

        Design: Corner/calculations/repeat_booking_bonus_threshold_and_window
        """
        sc = setup_ready_event(event_name="Day 15", num_adults=2, verify_waivers=True)
        event_id = sc["event"]["id"]
        begin_ready_event(event_id)

        # Rebook while the source is still IN_PROGRESS: not eligible
        early = api.rebook_event(
            event_id,
            {
                "name": "Too Early",
                "event_start_at": "2026-11-01T09:00:00Z",
                "event_end_at": "2026-11-01T15:00:00Z",
                "budget_cents": 400000,
            },
            cem_headers,
        )
        validate_error(early, ApiErrorId.ERR_REBOOK_NOT_ELIGIBLE)

        for reg in sc["registrations"]:
            check_in_registration(reg["id"])
        complete_event(event_id)
        submit_survey(sc["registrations"][0]["id"], sc["volunteers"][0], rating=4)
        submit_survey(sc["registrations"][1]["id"], sc["volunteers"][1], rating=5)
        assert get_event(event_id)["avg_feedback_rating"] == 4.5

        # 2026-11-01 is 73 days after the 2026-08-20 source start: within 180 days
        resp = api.rebook_event(
            event_id,
            {
                "name": "Day 15 Encore",
                "event_start_at": "2026-11-01T09:00:00Z",
                "event_end_at": "2026-11-01T15:00:00Z",
                "budget_cents": 400000,
            },
            cem_headers,
        )
        new_event = validate_success(resp, 201)
        assert new_event["repeat_booking_bonus"] is True
        assert new_event["source_event_id"] == event_id

        # The 10% uplift applies to sponsorship caps on the bonus event
        sponsorship = create_sponsorship(
            new_event["id"], match_type="FLAT", rate_cents=900, pledge_cap_cents=1000
        )
        assert get_sponsorship(sponsorship["id"])["effective_cap_cents"] == 1100


class TestSponsorshipStateRules:
    def test_sponsorship_settle_requires_completed_event(self, api, finance_headers):
        """PRD §3.8: "Settlement converts the estimate into chronological actuals, and is only possible once the event is `COMPLETED` or `CLOSED` — settling earlier is rejected with `ERR_EVENT_STATE_FORBIDS_WRITE`."
        PRD §3.8: "A new sponsorship starts in `PLEDGED` with `provisional_amount_cents` zero and `settled_amount_cents` null until settlement."

        Design: Corner/state_machines/sponsorship_settle_requires_completed_event
        """
        event = create_event("Day 7", budget_cents=500000)
        open_event_registration(event["id"])
        sponsorship = create_sponsorship(
            event["id"], match_type="FLAT", rate_cents=5000, pledge_cap_cents=9000
        )
        commit_sponsorship(sponsorship["id"])

        resp = api.settle_sponsorship(sponsorship["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_STATE_FORBIDS_WRITE)
        current = get_sponsorship(sponsorship["id"])
        assert current["status"] == "COMMITTED"
        assert current["settled_amount_cents"] is None

    def test_sponsorship_double_commit_rejected(self, api, finance_headers):
        """PRD §3.8: "Committing moves the pledge `PLEDGED` → `COMMITTED` and brings the provisional amount into the event's sponsorship credit."
        PRD §3.8: "Every other from-state combination in the sponsorship lifecycle is rejected with `ERR_INVALID_SPONSORSHIP_TRANSITION`."

        Design: Corner/errors/sponsorship_double_commit_rejected
        """
        event = create_event("Day 39", budget_cents=500000)
        sponsorship = create_sponsorship(
            event["id"], match_type="FLAT", rate_cents=5000, pledge_cap_cents=9000
        )
        commit_sponsorship(sponsorship["id"])

        resp = api.commit_sponsorship(sponsorship["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SPONSORSHIP_TRANSITION)
