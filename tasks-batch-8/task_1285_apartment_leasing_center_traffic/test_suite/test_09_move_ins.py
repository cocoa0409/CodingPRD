"""Move-ins: executed-lease gate, one-active constraint, UTC day-bucket capacity,
utility-transfer gating, and first-period proration (both methods, pinned
rounding order)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_executed_lease,
    add_issued_lease,
    create_move_in,
    create_move_in_payload,
    get_move_in,
    make_leasing_agent_headers,
    setup_site,
    sign_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]
MOVE_DAY = "2026-08-20T00:00:00Z"


class TestExecutedLeaseGate:
    def test_movein_rejected_while_lease_issued(self, api):
        """PRD §3.7: "With an `EXECUTED` lease in hand, an agent schedules the
        move-in by submitting the `lease_id` and a `scheduled_date` whose day bucket
        is read as a UTC calendar date. Scheduling against a lease in any other
        state is rejected with `ERR_LEASE_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/movein_requires_executed_lease
        """
        site = setup_site(floorplan_overrides={"total_units": 1})
        bundle = add_issued_lease(site)  # ISSUED, never signed

        resp = api.create_move_in(
            create_move_in_payload(bundle["lease"]["id"], scheduled_date=MOVE_DAY),
            make_leasing_agent_headers(site["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_EXECUTED)
        data, _ = validate_paginated(api.list_move_ins(
            PM, params={"lease_id": bundle["lease"]["id"]}))
        assert data == []

    def test_movein_rejected_while_lease_signed_by_applicant(self, api):
        """PRD §3.7: "With an `EXECUTED` lease in hand, an agent schedules the
        move-in by submitting the `lease_id` and a `scheduled_date` whose day bucket
        is read as a UTC calendar date. Scheduling against a lease in any other
        state is rejected with `ERR_LEASE_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/movein_requires_executed_lease
        """
        site = setup_site(floorplan_overrides={"total_units": 1})
        bundle = add_issued_lease(site)
        signed = sign_lease(bundle["lease"]["id"], bundle["application"]["id"])
        assert signed["status"] == "SIGNED_BY_APPLICANT"  # still not EXECUTED

        resp = api.create_move_in(
            create_move_in_payload(bundle["lease"]["id"], scheduled_date=MOVE_DAY),
            make_leasing_agent_headers(site["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_EXECUTED)


class TestUtilityGating:
    def test_movein_utility_gate_and_direct_completion(self, api):
        """PRD §3.7: "Confirming utilities advances the move-in from `SCHEDULED` to
        `READY` and sets `utility_confirmed` true; from any other state the
        confirmation is `ERR_MOVEIN_INVALID_STATE`. Completing the move-in is always
        permitted from `READY`. Completing directly from `SCHEDULED` is permitted
        only when the property's `utility_transfer_required` is false; when the
        property requires the transfer, a direct completion is rejected with
        `ERR_UTILITY_CONFIRMATION_REQUIRED`, and attempts from any state other than
        `READY` or an eligible `SCHEDULED` are `ERR_MOVEIN_INVALID_STATE`."
        PRD §3.7: "Cancellation is permitted from `SCHEDULED` or `READY` — anything
        else is `ERR_MOVEIN_INVALID_STATE` — and a lease cancellation cancels the
        lease's active move-ins outright, as part of the unwind chain of §2.9."

        Design: Corner/endpoints/movein_utility_gate_and_direct_completion
        """
        # Property requiring the utility transfer.
        site_req = setup_site(property_overrides={"utility_transfer_required": True},
                              floorplan_overrides={"total_units": 1})
        bundle_req = add_executed_lease(site_req)
        move_req = create_move_in(bundle_req["lease"]["id"], MOVE_DAY,
                                  site_req["agent"]["id"])

        # Property allowing direct completion.
        site_open = setup_site(property_overrides={"name": "Open House",
                                                   "code": "OP2",
                                                   "utility_transfer_required": False},
                               floorplan_overrides={"total_units": 1})
        bundle_open = add_executed_lease(site_open)
        move_open = create_move_in(bundle_open["lease"]["id"], MOVE_DAY,
                                   site_open["agent"]["id"])

        # Required-true: direct completion is gated.
        resp = api.complete_move_in(
            move_req["id"], make_leasing_agent_headers(site_req["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UTILITY_CONFIRMATION_REQUIRED)

        ready = validate_success(api.confirm_move_in_utilities(
            move_req["id"], make_leasing_agent_headers(site_req["agent"]["id"])))
        assert ready["status"] == "READY"
        assert ready["utility_confirmed"] is True

        completed = validate_success(api.complete_move_in(
            move_req["id"], make_leasing_agent_headers(site_req["agent"]["id"])))
        assert completed["status"] == "COMPLETED"

        # Required-false: SCHEDULED -> COMPLETED directly.
        direct = validate_success(api.complete_move_in(
            move_open["id"], make_leasing_agent_headers(site_open["agent"]["id"])))
        assert direct["status"] == "COMPLETED"

        # COMPLETED is terminal: cancel is an invalid transition.
        cancel = api.cancel_move_in(
            move_open["id"], make_leasing_agent_headers(site_open["agent"]["id"]))
        validate_error(cancel, ApiErrorId.ERR_MOVEIN_INVALID_STATE)


class TestOneActiveMoveIn:
    def test_movein_second_active_for_lease_rejected(self, api):
        """PRD §3.7: "A lease supports at most one active move-in — one in
        `SCHEDULED` or `READY` — and a second attempt is rejected with
        `ERR_MOVEIN_ALREADY_ACTIVE`."

        Design: Corner/endpoints/movein_second_active_for_lease_rejected
        """
        site = setup_site(property_overrides={"max_moveins_per_day": 5})
        bundle = add_executed_lease(site)
        agent_id = site["agent"]["id"]
        move1 = create_move_in(bundle["lease"]["id"], MOVE_DAY, agent_id)

        # Even on a different (empty) day bucket, the second active move-in fails.
        resp = api.create_move_in(
            create_move_in_payload(bundle["lease"]["id"],
                                   scheduled_date="2026-08-21T00:00:00Z"),
            make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_MOVEIN_ALREADY_ACTIVE)

        cancelled = validate_success(api.cancel_move_in(
            move1["id"], make_leasing_agent_headers(agent_id)))
        assert cancelled["status"] == "CANCELLED"
        move2 = create_move_in(bundle["lease"]["id"], "2026-08-21T00:00:00Z", agent_id)
        assert move2["status"] == "SCHEDULED"


class TestMoveInDayBucket:
    def test_movein_day_bucket_admits_up_to_daily_cap(self, api):
        """PRD §3.7: "And when the count of `SCHEDULED` or `READY` move-ins already
        on that UTC date at the lease's property has reached the property's
        `max_moveins_per_day`, the request is rejected with
        `ERR_MOVEIN_DAY_FULL`."

        Design: Difficulty/resource_temporal_overlap/movein_day_bucket_rejects_beyond_daily_cap
        """
        site = setup_site(property_overrides={"max_moveins_per_day": 2},
                          floorplan_overrides={"total_units": 3})
        agent_id = site["agent"]["id"]
        bundle1 = add_executed_lease(site, inquiry_overrides={
            "contact_name": "K1", "contact_email": "k1@x.com"})
        bundle2 = add_executed_lease(site, inquiry_overrides={
            "contact_name": "K2", "contact_email": "k2@x.com"})

        # Two move-ins on the same UTC date fill the cap-2 bucket.
        move1 = create_move_in(bundle1["lease"]["id"], MOVE_DAY, agent_id)
        move2 = create_move_in(bundle2["lease"]["id"], MOVE_DAY, agent_id)
        assert move1["status"] == "SCHEDULED"
        assert move2["status"] == "SCHEDULED"

    def test_movein_day_bucket_rejects_beyond_daily_cap(self, api):
        """PRD §3.7: "And when the count of `SCHEDULED` or `READY` move-ins already
        on that UTC date at the lease's property has reached the property's
        `max_moveins_per_day`, the request is rejected with
        `ERR_MOVEIN_DAY_FULL`."

        Design: Difficulty/resource_temporal_overlap/movein_day_bucket_rejects_beyond_daily_cap
        """
        site = setup_site(property_overrides={"max_moveins_per_day": 2},
                          floorplan_overrides={"total_units": 3})
        agent_id = site["agent"]["id"]
        bundles = [
            add_executed_lease(site, inquiry_overrides={
                "contact_name": f"K{i}", "contact_email": f"k{i}@x.com"})
            for i in (1, 2, 3)
        ]
        create_move_in(bundles[0]["lease"]["id"], MOVE_DAY, agent_id)
        create_move_in(bundles[1]["lease"]["id"], MOVE_DAY, agent_id)

        # The third move-in on 2026-08-20 exceeds the cap-2 day bucket.
        resp = api.create_move_in(
            create_move_in_payload(bundles[2]["lease"]["id"],
                                   scheduled_date=MOVE_DAY),
            make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_MOVEIN_DAY_FULL)
        data, _ = validate_paginated(api.list_move_ins(
            PM, params={"lease_id": bundles[2]["lease"]["id"]}))
        assert data == []

        # A different UTC date is a different bucket: the retry succeeds.
        move3 = create_move_in(bundles[2]["lease"]["id"], "2026-08-21T00:00:00Z",
                               agent_id)
        assert move3["status"] == "SCHEDULED"


class TestProratedRent:
    def test_prorated_rent_calendar_method(self, api):
        """PRD §3.7: "Under `CALENDAR`, the divisor is the actual number of days in
        the calendar month of `scheduled_date` — anywhere from 28 to 31 — and the
        occupied-day count is that divisor minus the move-in's day of month plus
        one, so the move-in day itself counts."
        PRD §2.6: "One rounding rule is pinned by contract because the alternative
        produces different cents: when prorating, the daily rate is rounded to whole
        cents first, and only then multiplied by the number of occupied days."

        Design: Difficulty/dual_variant_calc/prorated_rent_calendar_vs_fixed30_diverge
        """
        site = setup_site(property_overrides={"prorate_method": "CALENDAR"},
                          floorplan_overrides={"base_rent_cents": 210000,
                                               "total_units": 1})
        bundle = add_executed_lease(site)
        move = create_move_in(bundle["lease"]["id"], "2026-08-16T00:00:00Z",
                              site["agent"]["id"])
        # August has 31 days; days_occupied = 31 - 16 + 1 = 16;
        # round_half_up(210000 / 31) = 6774 daily; 6774 * 16 = 108384.
        assert move["prorated_rent_cents"] == 108384

    def test_prorated_rent_fixed30_method(self, api):
        """PRD §3.7: "Under `FIXED_30`, the divisor is always 30, the day of month
        is clamped at 30 — a move-in on the 31st is treated as the 30th and occupies
        exactly one day — and the occupied-day count is 30 minus the clamped day
        plus one."
        PRD §2.6: "One rounding rule is pinned by contract because the alternative
        produces different cents: when prorating, the daily rate is rounded to whole
        cents first, and only then multiplied by the number of occupied days."

        Design: Difficulty/dual_variant_calc/prorated_rent_calendar_vs_fixed30_diverge
        """
        site = setup_site(property_overrides={"name": "Thirty Court", "code": "P30",
                                              "prorate_method": "FIXED_30"},
                          floorplan_overrides={"base_rent_cents": 210000,
                                               "total_units": 1})
        bundle = add_executed_lease(site)
        move = create_move_in(bundle["lease"]["id"], "2026-08-16T00:00:00Z",
                              site["agent"]["id"])
        # divisor 30; days_occupied = 30 - 16 + 1 = 15; 210000 / 30 = 7000 daily;
        # 7000 * 15 = 105000 — diverging from the CALENDAR variant's 108384.
        assert move["prorated_rent_cents"] == 105000

    def test_prorated_rent_rounds_daily_rate_before_days(self, api):
        """PRD §2.6: "One rounding rule is pinned by contract because the
        alternative produces different cents: when prorating, the daily rate is
        rounded to whole cents first, and only then multiplied by the number of
        occupied days. Multiplying first and rounding the product is not used."

        Design: Difficulty/combinatorial_formula/prorated_rent_rounds_daily_rate_before_days
        """
        site = setup_site(property_overrides={"prorate_method": "CALENDAR"},
                          floorplan_overrides={"name": "Studio", "bedrooms": 0,
                                               "base_rent_cents": 100001,
                                               "total_units": 1})
        bundle = add_executed_lease(
            site, app_overrides={"annual_income_cents": 5000000})
        move = create_move_in(bundle["lease"]["id"], "2026-08-16T00:00:00Z",
                              site["agent"]["id"])
        # Pinned order: round_half_up(100001 / 31) = 3226 daily; 3226 * 16 = 51616.
        assert move["prorated_rent_cents"] == 51616
        # The unpinned multiply-first alternative (100001 * 16 / 31 -> 51613) would
        # produce a different cent value.
        assert move["prorated_rent_cents"] != 51613

    def test_prorated_rent_rounds_daily_rate_first_full_month(self, api):
        """PRD §2.6: "One rounding rule is pinned by contract because the
        alternative produces different cents: when prorating, the daily rate is
        rounded to whole cents first, and only then multiplied by the number of
        occupied days. Multiplying first and rounding the product is not used."
        PRD §3.7: "Under `CALENDAR`, the divisor is the actual number of days in the
        calendar month of `scheduled_date` — anywhere from 28 to 31 — and the
        occupied-day count is that divisor minus the move-in's day of month plus
        one, so the move-in day itself counts."

        Design: Difficulty/combinatorial_formula/prorated_rent_rounds_daily_rate_before_days
        """
        site = setup_site(property_overrides={"prorate_method": "CALENDAR"},
                          floorplan_overrides={"name": "Studio", "bedrooms": 0,
                                               "base_rent_cents": 100001,
                                               "total_units": 1})
        bundle = add_executed_lease(
            site, app_overrides={"annual_income_cents": 5000000})
        # A month-start move-in occupies all 31 days: 3226 * 31 = 100006 under the
        # pinned order (multiply-first would yield exactly 100001).
        move = create_move_in(bundle["lease"]["id"], "2026-08-01T00:00:00Z",
                              site["agent"]["id"])
        assert move["prorated_rent_cents"] == 100006
