"""Registration lifecycle: payment, the wave selector, withdrawal refunds,
and waitlist promotion."""
from test_helpers import (
    ApiErrorId,
    assert_registration,
    create_athlete,
    create_confirmed_registration,
    create_event,
    create_paid_registration,
    create_permitted_event,
    create_published_event,
    get_success_data,
    make_athlete_headers,
    make_race_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegistrationCreation:
    def test_missing_required_field_returns_400(self, api,
                                                race_director_headers):
        """PRD §3.4: "It is created — by a `RaceDirector`, or by an
        `Athlete`-role caller registering themselves — with an `athlete_id`, a
        `division` of `AGE_GROUP` or `ELITE`, and an `entry_fee_cents` amount
        paid".
        PRD §2.10: "then request-body validation: required fields, enum
        membership, field formats, datetime ordering where an end must be
        strictly later than its start, and the `reduced_seconds` range on
        appeal decisions, all under `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/registration_missing_required_field_returns_400
        """
        event = create_event()
        athlete = create_athlete(event["id"])
        resp = api.create_registration(
            event["id"],
            {"athlete_id": athlete["id"], "division": "AGE_GROUP"},
            make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_registration_listing_pagination_envelope(self, api,
                                                      race_director_headers):
        """PRD §2.3: "`limit` specifies the maximum number of items to return;
        it defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/registration_listing_pagination_envelope
        """
        event = create_event()
        a1 = create_athlete(event["id"], license_number="USAT-1")
        a2 = create_athlete(event["id"], full_name="Bob B",
                            birth_date="1992-05-05", license_number="USAT-2")
        for a in (a1, a2):
            get_success_data(api.create_registration(
                event["id"],
                {"athlete_id": a["id"], "division": "AGE_GROUP",
                 "entry_fee_cents": 10000},
                make_athlete_headers(a["id"])))

        resp = api.list_registrations(event["id"], race_director_headers)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestWaveSelector:
    def test_selector_waitlists_when_no_eligible_wave(self, api,
                                                     race_director_headers):
        """PRD §3.4: "A wave is eligible when it is `OPEN`, its
        `assigned_count` is below `capacity`, its `division` equals the
        registration's `division`, and the athlete's `age_at_event` falls
        within the wave's `age_band_min` to `age_band_max` inclusive... When
        the eligible pool is empty the registration moves from `PAID` to
        `WAITLISTED` with no `wave_id`."

        Design: Corner/calculations/selector_waitlists_when_no_eligible_wave
        """
        ctx = create_published_event(water_pool_units=100)
        athlete, registration = create_paid_registration(
            ctx["event"]["id"], full_name="Old O", birth_date="1986-12-31",
            license_number="USAT-9")
        # Age at event = 2026 - 1986 = 40, outside the 18-39 band.
        result = validate_success(
            api.confirm_registration(registration["id"], race_director_headers))
        assert result["status"] == "WAITLISTED", \
            "age 40 above band max 39 leaves no eligible wave"
        assert result["wave_id"] is None

    def test_age_boundary_39_eligible(self, api, race_director_headers):
        """PRD §3.4: "the athlete's `age_at_event` falls within the wave's
        `age_band_min` to `age_band_max` inclusive."
        PRD §3.2: "Age for band purposes is computed calendar-year-wise: an
        athlete's `age_at_event` is the year of the event's `start_date` minus
        the year of the athlete's `birth_date`."

        Design: Corner/calculations/age_boundary_39_eligible
        """
        ctx = create_published_event(water_pool_units=100)
        wave = ctx["waves"][0]
        athlete, registration = create_paid_registration(
            ctx["event"]["id"], full_name="Edgy E", birth_date="1987-01-01",
            license_number="USAT-10")
        # Age at event = 2026 - 1987 = 39, exactly the inclusive band maximum.
        result = validate_success(
            api.confirm_registration(registration["id"], race_director_headers))
        assert_registration(result)
        assert result["status"] == "CONFIRMED"
        assert result["wave_id"] == wave["id"]
        assert result["age_at_event"] == 39, \
            "inclusive band boundary accepts age 39"


class TestWithdrawalRefunds:
    def test_refund_provisional_vs_final_tier_crossing(self, api):
        """PRD §3.4: "Sixty or more days out, the refundable base is 75
        percent of `entry_fee_cents`; from 30 up to and including 59 days out,
        50 percent; fewer than 30 days out, zero."
        PRD §3.7: "withdrawals whose refunds have not settled receive
        `refund_final_cents`, recomputed by the same tier rule as §3.4 but
        keyed to the processing date — so when processing lands in a lower
        tier than the withdrawal date did, the final amount differs from the
        provisional estimate".

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_tier_crossing
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=500)
        athlete, registration = create_paid_registration(
            event["id"], full_name="Bob B", birth_date="1992-05-05",
            license_number="USAT-2", entry_fee_cents=20000)

        # Withdraw 56 days before the 2026-10-15 start -> 50% tier.
        get_success_data(api.set_clock("2026-08-20T00:00:00Z", rd))
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-123"}))
        assert withdrawn["refund_estimate_cents"] == 9000, (
            "50% tier: base floor(20000*0.50)=10000, "
            "fee ceil(10000*0.10)=1000, estimate 10000-1000=9000")
        assert withdrawn["refund_final_cents"] is None, \
            "final refund stays null pending settlement"

        # Settle at 25 days before start -> 0% tier.
        get_success_data(api.set_clock("2026-09-20T00:00:00Z", rd))
        get_success_data(api.run_ops(event["id"], rd))
        settled = validate_success(api.get_registration(registration["id"], rd))
        assert settled["refund_final_cents"] == 0, \
            "processing date lands in the 0% tier"
        assert settled["refund_estimate_cents"] != settled["refund_final_cents"], \
            "provisional estimate and final settlement differ across the tier crossing"

    def test_refund_final_settles_at_same_tier_when_no_crossing(self, api):
        """PRD §3.7: "withdrawals whose refunds have not settled receive
        `refund_final_cents`, recomputed by the same tier rule as §3.4 but
        keyed to the processing date". When withdraw and processing land in
        the same tier, the two amounts coincide.

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_tier_crossing
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=500)
        athlete, registration = create_paid_registration(
            event["id"], entry_fee_cents=20000)
        # Default clock 2026-08-01 is 75 days before the 2026-10-15 start.
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"}))
        assert withdrawn["refund_estimate_cents"] == 13500

        get_success_data(api.set_clock("2026-08-05T00:00:00Z", rd))
        get_success_data(api.run_ops(event["id"], rd))
        settled = validate_success(api.get_registration(registration["id"], rd))
        assert settled["refund_final_cents"] == 13500, \
            "processing still in the >=60-day tier settles at the same amount"

    def test_refund_nested_rounding_order_pinned(self, api):
        """PRD §2.7: "refund arithmetic uses a pinned rounding order: the
        refundable base is rounded down to a whole cent first, the processing
        fee is then computed on that rounded base and rounded up to a whole
        cent, and the fee is subtracted from the base. The two rounding steps
        are never combined into a single sum-then-round."
        PRD §3.4: "The base is rounded down to whole cents, a processing fee
        of 10 percent of that rounded base is rounded up to whole cents, and
        `refund_estimate_cents` is the base minus the fee."

        Design: Difficulty/combinatorial_formula/refund_nested_rounding_order_pinned
        """
        event = create_event(water_pool_units=100)
        athlete, registration = create_paid_registration(
            event["id"], full_name="Cid C", birth_date="1988-03-03",
            license_number="USAT-3", entry_fee_cents=20005)
        # Default clock 2026-08-01 -> 75 days out -> 75% tier.
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-9"}))
        # base = floor(20005 * 0.75) = floor(15003.75) = 15003
        # fee  = ceil(15003 * 0.10)  = ceil(1500.3)   = 1501
        # estimate = 15003 - 1501 = 13502
        assert withdrawn["refund_estimate_cents"] == 13502, (
            "floor-then-ceil-then-subtract: 15003 - 1501 = 13502; "
            "a sum-then-round implementation would give 13503")

    def test_refund_rounding_order_odd_fee_at_half_tier(self, api):
        """PRD §2.7: "The two rounding steps are never combined into a single
        sum-then-round." At the 50% tier with an odd base the pinned order is
        again observable: floor(20001 * 0.50) = 10000, ceil(10000 * 0.10) =
        1000, estimate 9000.

        Design: Difficulty/combinatorial_formula/refund_nested_rounding_order_pinned
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=100)
        athlete, registration = create_paid_registration(
            event["id"], full_name="Dee D", birth_date="1991-07-07",
            license_number="USAT-4", entry_fee_cents=20001)
        get_success_data(api.set_clock("2026-08-20T00:00:00Z", rd))  # 56 days -> 50%
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-7"}))
        assert withdrawn["refund_estimate_cents"] == 9000, \
            "floor(20001*0.50)=10000 base, ceil fee 1000, estimate 9000"

    def test_refund_tier_boundary_60_days(self, api):
        """PRD §3.4: "The provisional refund is tiered on how far out the
        withdrawal lands: let the days until the event be the whole number of
        days between `withdrawn_at` and the event's `start_date`. Sixty or
        more days out, the refundable base is 75 percent of
        `entry_fee_cents`; from 30 up to and including 59 days out, 50
        percent; fewer than 30 days out, zero."

        Design: Corner/calculations/refund_tier_boundary_60_days
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=100)
        a1, r1 = create_paid_registration(event["id"], license_number="USAT-1",
                                          entry_fee_cents=20000)
        a2, r2 = create_paid_registration(event["id"], full_name="Bob B",
                                          birth_date="1992-05-05",
                                          license_number="USAT-2",
                                          entry_fee_cents=20000)

        # Exactly 60 * 86400 seconds before the 2026-10-15T08:00:00Z start.
        get_success_data(api.set_clock("2026-08-16T08:00:00Z", rd))
        w1 = validate_success(api.withdraw_registration(
            r1["id"], make_athlete_headers(a1["id"]),
            payload={"refund_destination": "card-1"}))
        assert w1["refund_estimate_cents"] == 13500, \
            "exactly 60 days out lands in the 75% tier"

        # One second past the 60-day mark -> 59 whole days -> 50% tier.
        get_success_data(api.set_clock("2026-08-17T08:00:01Z", rd))
        w2 = validate_success(api.withdraw_registration(
            r2["id"], make_athlete_headers(a2["id"]),
            payload={"refund_destination": "card-2"}))
        assert w2["refund_estimate_cents"] == 9000, \
            "59 whole days out lands in the 50% tier"

    def test_withdraw_without_destination_positive_refund_rejected(self, api):
        """PRD §3.4: "when the computed provisional refund is above zero a
        `refund_destination` payout destination must be supplied
        (`ERR_REFUND_DESTINATION_REQUIRED`, HTTP 400)."

        Design: Corner/validations/withdraw_without_destination_positive_refund_rejected
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=100)
        a1, r1 = create_paid_registration(event["id"], license_number="USAT-1",
                                          entry_fee_cents=20000)
        a2, r2 = create_paid_registration(event["id"], full_name="Bob B",
                                          birth_date="1992-05-05",
                                          license_number="USAT-2",
                                          entry_fee_cents=20000)

        # Default clock -> 75% tier -> positive estimate -> destination required.
        resp = api.withdraw_registration(
            r1["id"], make_athlete_headers(a1["id"]), payload={})
        validate_error(resp, ApiErrorId.ERR_REFUND_DESTINATION_REQUIRED.value)
        still = validate_success(api.get_registration(r1["id"], rd))
        assert still["status"] == "PAID"

        # At the 0% tier the estimate is zero, so no destination is required.
        get_success_data(api.set_clock("2026-09-20T00:00:00Z", rd))
        w2 = validate_success(api.withdraw_registration(
            r2["id"], make_athlete_headers(a2["id"]), payload={}))
        assert w2["status"] == "WITHDRAWN"
        assert w2["refund_estimate_cents"] == 0

    def test_withdraw_terminal_lockdown(self, api):
        """PRD §3.4: "`WITHDRAWN` is terminal, as are `EXPIRED` and `DSQ`."
        A second withdrawal targets a resource no longer in a valid
        from-state.
        PRD §2.10: "then state-machine from-state validity
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/withdraw_terminal_lockdown
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=100)
        athlete, registration = create_paid_registration(
            event["id"], entry_fee_cents=20000)
        first = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"}))
        assert first["refund_estimate_cents"] == 13500

        resp = api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"})
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        after = validate_success(api.get_registration(registration["id"], rd))
        assert after["refund_estimate_cents"] == 13500, \
            "a rejected retry does not recompute the stored estimate"

    def test_withdraw_cascade_frees_slot_and_promotes(self, api):
        """PRD §3.4: "A withdrawal from `CONFIRMED` or `RACKED` additionally
        frees the wave slot — `assigned_count` drops by one and a `FULL` wave
        reopens to `OPEN` — and immediately promotes the oldest eligible
        waitlisted registration into the freed slot".
        PRD §3.4: "Whenever a slot frees... the oldest eligible `WAITLISTED`
        registration, ordered by the registration's `created_at` ascending, is
        promoted into the wave through exactly the same eligibility predicate:
        its `wave_id` is set, its `age_at_event` is stamped, the wave's count
        is incremented, and `FULL` is re-derived at capacity."

        Design: Difficulty/transitive_cascade/withdraw_cascade_frees_slot_and_promotes
        """
        rd = make_race_director_headers()
        ctx = create_published_event(wave_overrides=[{"capacity": 1}],
                                     water_pool_units=1000)
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        a1, r1 = create_confirmed_registration(event_id, entry_fee_cents=20000)
        a2, r2 = create_paid_registration(event_id, full_name="Bob B",
                                          birth_date="1992-05-05",
                                          license_number="USAT-2",
                                          entry_fee_cents=20000)
        waitlisted = validate_success(api.confirm_registration(r2["id"], rd))
        assert waitlisted["status"] == "WAITLISTED"
        wave_full = validate_success(api.get_wave(wave["id"], rd))
        assert wave_full["status"] == "FULL", "capacity 1 filled by R1"

        withdrawn = validate_success(api.withdraw_registration(
            r1["id"], make_athlete_headers(a1["id"]),
            payload={"refund_destination": "card-1"}))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["refund_estimate_cents"] == 13500, \
            "default clock is 75 days out: 75% tier, base 15000, fee 1500"

        wave_after = validate_success(api.get_wave(wave["id"], rd))
        assert wave_after["assigned_count"] == 1, \
            "the freed slot was immediately refilled by the promoted waitlistee"
        assert wave_after["status"] == "FULL", \
            "FULL re-derived at capacity after the promotion"

        promoted = validate_success(api.get_registration(r2["id"], rd))
        assert promoted["status"] == "CONFIRMED"
        assert promoted["wave_id"] == wave["id"]
        assert promoted["age_at_event"] == 34, "2026 - 1992 = 34"

    def test_promotion_respects_waitlist_fifo_order(self, api):
        """PRD §3.4: "the oldest eligible `WAITLISTED` registration, ordered
        by the registration's `created_at` ascending, is promoted into the
        wave". With two waitlisted athletes, the earlier-created registration
        wins the freed slot.

        Design: Difficulty/transitive_cascade/withdraw_cascade_frees_slot_and_promotes
        """
        rd = make_race_director_headers()
        ctx = create_published_event(wave_overrides=[{"capacity": 1}],
                                     water_pool_units=1000)
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        a1, r1 = create_confirmed_registration(event_id, entry_fee_cents=10000)
        a2, r2 = create_paid_registration(event_id, full_name="Bob B",
                                          birth_date="1992-05-05",
                                          license_number="USAT-2",
                                          entry_fee_cents=10000)
        a3, r3 = create_paid_registration(event_id, full_name="Cat C",
                                          birth_date="1993-06-06",
                                          license_number="USAT-3",
                                          entry_fee_cents=10000)
        assert validate_success(api.confirm_registration(r2["id"], rd))["status"] == "WAITLISTED"
        assert validate_success(api.confirm_registration(r3["id"], rd))["status"] == "WAITLISTED"

        get_success_data(api.withdraw_registration(
            r1["id"], make_athlete_headers(a1["id"]),
            payload={"refund_destination": "card-1"}))

        r2_after = validate_success(api.get_registration(r2["id"], rd))
        r3_after = validate_success(api.get_registration(r3["id"], rd))
        assert r2_after["status"] == "CONFIRMED", \
            "oldest waitlisted registration is promoted first"
        assert r2_after["wave_id"] == wave["id"]
        assert r3_after["status"] == "WAITLISTED"
        assert r3_after["wave_id"] is None


class TestConfirmWindow:
    def test_confirm_window_closed_temporal(self, api, race_director_headers):
        """PRD §3.4: "the logical clock must be strictly earlier than 24 hours
        before the event's `start_date` (`ERR_CONFIRM_WINDOW_CLOSED`)".

        Design: Corner/validations/confirm_window_closed_temporal
        """
        ctx = create_published_event(wave_overrides=[{"capacity": 3}],
                                     water_pool_units=100)
        event_id = ctx["event"]["id"]
        _, r1 = create_paid_registration(event_id, license_number="USAT-1",
                                         entry_fee_cents=10000)
        _, r2 = create_paid_registration(event_id, full_name="Bob B",
                                         birth_date="1992-05-05",
                                         license_number="USAT-2",
                                         entry_fee_cents=10000)

        # One hour before the deadline (start - 24h = 2026-10-14T08:00:00Z).
        get_success_data(api.set_clock("2026-10-14T07:00:00Z",
                                       race_director_headers))
        confirmed = validate_success(
            api.confirm_registration(r1["id"], race_director_headers))
        assert confirmed["status"] == "CONFIRMED"

        # Exactly at the deadline: "strictly earlier" fails.
        get_success_data(api.set_clock("2026-10-14T08:00:00Z",
                                       race_director_headers))
        resp = api.confirm_registration(r2["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_CONFIRM_WINDOW_CLOSED.value)

    def test_run_ops_expires_unconfirmed_paid(self, api, race_director_headers):
        """PRD §3.7: "Each run increments the event's `ops_run_index` by one
        and performs four sweeps: registrations still `PAID` once the logical
        clock has moved strictly past the instant 24 hours before `start_date`
        lapse to `EXPIRED`".

        Design: Corner/calculations/run_ops_expires_unconfirmed_paid
        """
        ctx = create_published_event(wave_overrides=[{"capacity": 3}],
                                     water_pool_units=100)
        event_id = ctx["event"]["id"]
        _, r1 = create_paid_registration(event_id, license_number="USAT-1",
                                         entry_fee_cents=10000)
        _, r2 = create_paid_registration(event_id, full_name="Bob B",
                                         birth_date="1992-05-05",
                                         license_number="USAT-2",
                                         entry_fee_cents=10000)
        get_success_data(api.confirm_registration(r2["id"],
                                                  race_director_headers))
        # Past the confirm deadline (2026-10-14T08:00:00Z).
        get_success_data(api.set_clock("2026-10-14T12:00:00Z",
                                       race_director_headers))
        event_after = validate_success(api.run_ops(event_id,
                                                   race_director_headers))
        assert event_after["ops_run_index"] == 1

        r1_after = validate_success(api.get_registration(r1["id"],
                                                         race_director_headers))
        r2_after = validate_success(api.get_registration(r2["id"],
                                                         race_director_headers))
        assert r1_after["status"] == "EXPIRED", \
            "PAID past the confirm deadline lapses to EXPIRED"
        assert r2_after["status"] == "CONFIRMED", \
            "CONFIRMED registrations are untouched by the expiry sweep"
