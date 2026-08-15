"""Preemption and the make-good cycle: recovery loop, conservation of booked
seconds, make-good uniqueness and rating floor, and political protection."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    assert_week_booked_seconds,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_order,
    create_program,
    get_avail_unit,
    get_spot,
    get_success_data,
    list_line_spots,
    place_spot_fresh,
    place_spot_payload,
    preempt_payload,
    setup_preempted_spot,
    setup_scheduled_scenario,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]


class TestMakeGoodCycle:
    def test_preempt_offer_place_completes_recovery_loop(self, api):
        """PRD §3.6: "Offering a make-good against a `PREEMPTED` spot creates a new spot row on the same order line, in `MAKE_GOOD_OFFERED` status, carrying the same `spot_class` as the original and pointing back at it through `make_good_of_spot_id`."
        PRD §3.6: "The offered make-good is then placed through the ordinary placement flow of §3.5 — same headroom, same separation, same version guard — evaluated against its own line, with one additional gate: the comparable-or-better rule."

        Design: Difficulty/non_linear_state_machine/spot_preemption_makegood_cycle
        """
        ctx = setup_preempted_spot(
            airs_weekday=5, air_date="2026-08-07", daypart="PRIME",
            rating_estimate=5.0, num_units=2, total_seconds=60,
            gross_rate_cents=12000, offer=True,
        )
        original = ctx["preempted"]
        make_good = ctx["make_good"]
        assert original["status"] == "PREEMPTED"
        assert original["preempt_reason"] == "OVERSOLD"
        assert make_good["status"] == "MAKE_GOOD_OFFERED"
        assert make_good["make_good_of_spot_id"] == original["id"]
        assert make_good["order_line_id"] == ctx["line"]["id"]

        unit_b = ctx["units"][1]
        placed = place_spot_fresh(make_good["id"], unit_b["id"])
        assert placed["status"] == "SCHEDULED"
        assert placed["make_good_of_spot_id"] == original["id"]
        assert get_spot(original["id"])["status"] == "PREEMPTED"
        assert get_avail_unit(ctx["units"][0]["id"])["booked_commercial_seconds"] == 0
        assert get_avail_unit(unit_b["id"])["booked_commercial_seconds"] == 30

    def test_declined_make_good_leaves_original_preempted(self, api):
        """PRD §3.6: "The advertiser's side of the cycle belongs to the `SalesRep`, who may decline an offered make-good, moving it from `MAKE_GOOD_OFFERED` to `CANCELLED`. When the originating preempted spot has no other make-good outstanding in `MAKE_GOOD_OFFERED` or `SCHEDULED`, no further action is taken on it: the preempted spot simply remains `PREEMPTED` until the order completion sweep of §3.4."

        Design: Difficulty/non_linear_state_machine/spot_preemption_makegood_cycle
        """
        ctx = setup_preempted_spot(airs_weekday=5, air_date="2026-08-07", offer=True)
        original = ctx["preempted"]
        make_good = ctx["make_good"]
        declined = validate_success(api.decline_make_good(make_good["id"], SALESREP))
        assert declined["status"] == "CANCELLED"
        assert get_spot(original["id"])["status"] == "PREEMPTED"


class TestBookedSecondsConservation:
    def test_preempt_then_makegood_conserves_week_total(self, api):
        """PRD §3.6: "Preemption records the supplied reason on the spot, moves it from `SCHEDULED` to `PREEMPTED`, releases the line's `spot_length_seconds` from the unit's booked counter for the spot's class bucket, and advances both the spot's and the avail unit's `version`."
        PRD §3.5: "A successful placement writes the spot's `avail_unit_id`, copies the unit's air date into the spot's `scheduled_air_date`, adds the line's `spot_length_seconds` to the unit's booked counter for the spot's class bucket, and advances both the spot's `version` and the avail unit's `version`."

        Design: Difficulty/compensating_invariant/preempt_makegood_conserves_week_booked_seconds
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=5, air_date="2026-08-07", daypart="PRIME",
            rating_estimate=5.0, num_units=2, total_seconds=60,
            gross_rate_cents=9000,
        )
        unit_a, unit_c = ctx["units"]
        spot = ctx["placed"][0]
        assert_week_booked_seconds([get_avail_unit(u["id"]) for u in ctx["units"]], 30)

        preempted = validate_success(
            api.preempt_spot(spot["id"], preempt_payload("NEWS_OVERRIDE"), TRAFFIC)
        )
        assert preempted["status"] == "PREEMPTED"
        assert get_avail_unit(unit_a["id"])["booked_commercial_seconds"] == 0
        assert_week_booked_seconds([get_avail_unit(u["id"]) for u in ctx["units"]], 0)

        make_good = validate_success(api.offer_make_good(spot["id"], TRAFFIC), 201)
        placed = place_spot_fresh(make_good["id"], unit_c["id"])
        assert placed["status"] == "SCHEDULED"
        assert get_avail_unit(unit_c["id"])["booked_commercial_seconds"] == 30
        assert_week_booked_seconds([get_avail_unit(u["id"]) for u in ctx["units"]], 30)

    def test_order_cancel_releases_scheduled_seconds(self, api):
        """PRD §3.4: "From `APPROVED`, cancellation requires that no spot of the order has aired — again rejected with `ERR_INVALID_STATE` otherwise — and applies the same spot teardown as revision: spots in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` are cancelled, and `SCHEDULED` spots on non-finalized log dates are cancelled with their booked seconds released."
        PRD §2.6: "placing a spot adds its duration to the bucket matching its class, and preempting or cancelling a scheduled spot releases its duration back."

        Design: Difficulty/compensating_invariant/preempt_makegood_conserves_week_booked_seconds
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=5, air_date="2026-08-07", total_seconds=60
        )
        unit = ctx["units"][0]
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30
        cancelled = validate_success(api.cancel_order(ctx["order"]["id"], SALESREP))
        assert cancelled["status"] == "CANCELLED"
        # No log day covers the air date, so the scheduled spot is cancelled
        # and its seconds flow back — the week's booked total returns to 0.
        assert get_spot(ctx["placed"][0]["id"])["status"] == "CANCELLED"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 0


class TestMakeGoodGuards:
    def test_duplicate_make_good_rejected(self, api):
        """PRD §3.6: "Only one outstanding make-good may exist per preempted spot: if another spot already references the same original through `make_good_of_spot_id` and stands in `MAKE_GOOD_OFFERED` or `SCHEDULED`, the offer is rejected with `ERR_AVAIL_OVERFLOW`."
        PRD §3.6: "The make-goods created for any preempted spot can be read back through the original spot's make-good listing."

        Design: Corner/state_machines/duplicate_make_good_for_same_preempted_spot_rejected
        """
        ctx = setup_preempted_spot(airs_weekday=5, air_date="2026-08-07", offer=True)
        original = ctx["preempted"]
        resp = api.offer_make_good(original["id"], TRAFFIC)
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERFLOW)
        data, meta = validate_paginated(api.list_spot_make_goods(original["id"], TRAFFIC))
        assert len(data) == 1
        assert data[0]["id"] == ctx["make_good"]["id"]

    def test_make_good_rating_downgrade_rejected(self, api):
        """PRD §3.6: "A make-good must target an avail unit whose program's `rating_estimate` is at least the `rating_estimate` of the program whose unit the original spot was preempted from; a downgrade is rejected with `ERR_REFERENCE_MISMATCH`."

        Design: Corner/endpoints/make_good_rating_downgrade_rejected
        """
        advertiser = create_advertiser(name="MG")
        program_hi = create_program(
            title="Fri MG", daypart_code="PRIME", airs_weekday=5, rating_estimate=5.0
        )
        program_lo = create_program(
            title="Fri MG Low", daypart_code="LATE_FRINGE", airs_weekday=5, rating_estimate=1.0
        )
        week = create_avail_week("2026-08-03")
        unit_hi = create_avail_unit(week["id"], program_hi["id"], "2026-08-07", total_seconds=60)
        unit_lo = create_avail_unit(week["id"], program_lo["id"], "2026-08-07", total_seconds=60)
        order = create_order(advertiser["id"])
        line = add_order_line(
            order["id"], program_hi["id"], spots_per_week=1, gross_rate_cents=12000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        spot = list_line_spots(line["id"])[0]
        place_spot_fresh(spot["id"], unit_hi["id"])
        preempt_spot_resp = api.preempt_spot(spot["id"], preempt_payload("NEWS_OVERRIDE"), TRAFFIC)
        validate_success(preempt_spot_resp)
        make_good = validate_success(api.offer_make_good(spot["id"], TRAFFIC), 201)
        mg_id = make_good["id"]

        # Target unit belongs to a lower-rated program (1.0 < 5.0).
        resp = api.place_spot(
            mg_id,
            place_spot_payload(unit_lo["id"], get_avail_unit(unit_lo["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)
        assert get_spot(mg_id)["status"] == "MAKE_GOOD_OFFERED"


class TestPreemptionGuards:
    def test_political_priority_cannot_preempt_political_spot(self, api):
        """PRD §3.6: "Political-priority preemption is itself fenced: it may target only `COMMERCIAL` spots, because political spots cannot be preempted for political priority — attempting it against a `POLITICAL` spot is rejected with `ERR_POLITICAL_RESERVE`."

        Design: Corner/validations/preempt_political_priority_against_political_spot_rejected
        """
        ctx = setup_scheduled_scenario(
            category="POLITICAL", airs_weekday=6, air_date="2026-08-08",
            daypart="PRIME", rating_estimate=5.0, is_political_window=True,
            reserved_political_seconds=30, total_seconds=60,
        )
        spot = ctx["placed"][0]
        assert spot["spot_class"] == "POLITICAL"
        resp = api.preempt_spot(spot["id"], preempt_payload("POLITICAL_PRIORITY"), TRAFFIC)
        validate_error(resp, ApiErrorId.ERR_POLITICAL_RESERVE)
        assert get_spot(spot["id"])["status"] == "SCHEDULED"

    def test_preempt_rejected_once_log_finalized(self, api):
        """PRD §3.6: "A `TrafficManager` may preempt only while the spot's `scheduled_air_date` is not yet covered by a `FINALIZED` or `RECONCILED` log day — a spot locked into a finalized log cannot be manually preempted, and the attempt is rejected with `ERR_INVALID_STATE`; misses there surface at reconciliation instead."

        Design: Corner/state_machines/preempt_on_finalized_log_rejected
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="EARLY_NEWS",
            rating_estimate=4.0, total_seconds=60, log_date="2026-08-04",
            finalize=True,
        )
        spot = ctx["placed"][0]
        resp = api.preempt_spot(spot["id"], preempt_payload("NEWS_OVERRIDE"), TRAFFIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_spot(spot["id"])["status"] == "SCHEDULED"
