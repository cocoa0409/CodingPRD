"""Order entry, budget recompute, the approval pipeline, the revision loop,
and the clock-driven completion sweep."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    as_run_entry,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_order,
    create_program,
    finalize_log_day,
    get_avail_unit,
    get_order,
    get_success_data,
    list_line_spots,
    place_spot_fresh,
    reconcile_log_day,
    set_clock,
    setup_scheduled_scenario,
    submit_order,
    validate_error,
    validate_success,
    create_received_copy,
    create_log_day,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]


class TestOrderEntry:
    def test_new_order_starts_in_draft_with_zeroed_fields(self, api):
        """PRD §3.4: "A buy starts as an order in `DRAFT`."
        PRD §3.4: "A new order carries a `gross_budget_cents` of zero and a `revision_no` of zero."

        Design: Corner/state_machines/order_initial_state_is_draft
        """
        advertiser = create_advertiser(name="Init", credit_limit_cents=100000)
        order = validate_success(
            api.create_order(
                {
                    "advertiser_id": advertiser["id"],
                    "flight_start_date": "2026-08-03",
                    "flight_end_date": "2026-08-09",
                },
                SALESREP,
            ),
            201,
        )
        assert order["status"] == "DRAFT"
        assert order["revision_no"] == 0
        assert order["gross_budget_cents"] == 0

    def test_flight_end_before_start_rejected(self, api):
        """PRD §3.4: "A `SalesRep` creates it with the buying `advertiser_id`, a `flight_start_date`, and a `flight_end_date`; the flight end is inclusive and must not precede the flight start, else the create is rejected with `ERR_DATE_WINDOW`."

        Design: Corner/validations/order_flight_end_before_start_rejected
        """
        advertiser = create_advertiser(name="DW", credit_limit_cents=100000)
        resp = api.create_order(
            {
                "advertiser_id": advertiser["id"],
                "flight_start_date": "2026-08-09",
                "flight_end_date": "2026-08-03",
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_WINDOW)

    def test_line_add_recomputes_gross_budget(self, api):
        """PRD §3.4: "The order's `gross_budget_cents` is maintained automatically: it is the sum over the order's non-cancelled lines of the line's `gross_rate_cents` multiplied by its `spots_per_week` multiplied by its `weeks_requested`, recomputed every time a line is added or cancelled."

        Design: Corner/endpoints/order_lines_add_recomputes_gross_budget
        """
        advertiser = create_advertiser(name="GB")
        program = create_program(daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0)
        order = create_order(advertiser["id"])
        add_order_line(
            order["id"], program["id"],
            weeks_requested=1, spots_per_week=2, spot_length_seconds=30,
            gross_rate_cents=10000, guaranteed_rating=0,
        )
        add_order_line(
            order["id"], program["id"],
            weeks_requested=2, spots_per_week=1, spot_length_seconds=30,
            gross_rate_cents=7000, guaranteed_rating=0,
        )
        order = get_order(order["id"])
        # line1: 10000*2*1 = 20000; line2: 7000*1*2 = 14000.
        assert order["gross_budget_cents"] == 34000

    def test_invalid_spot_length_rejected(self, api):
        """PRD §3.4: "Spot length must be one of 15, 30, 60, or 120 seconds, the gross rate must be positive, and the guaranteed rating must not be negative — a guarantee of 0 means the line carries no audience guarantee at all. Violations of these field constraints are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_spot_length_rejected
        """
        advertiser = create_advertiser(name="SL", credit_limit_cents=100000)
        program = create_program(daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0)
        order = create_order(advertiser["id"])
        resp = api.add_order_line(
            order["id"],
            {
                "program_id": program["id"],
                "weeks_requested": 1,
                "spots_per_week": 1,
                "spot_length_seconds": 45,
                "gross_rate_cents": 5000,
                "guaranteed_rating": 0,
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_submit_without_active_lines_rejected(self, api):
        """PRD §3.4: "An order with no `ACTIVE` line cannot be submitted; the attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/order_submit_without_lines_rejected
        """
        advertiser = create_advertiser(name="Empty", credit_limit_cents=100000)
        order = create_order(advertiser["id"])
        resp = api.submit_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_cancelled_order_is_terminal(self, api):
        """PRD §3.4: "`CANCELLED` is terminal, as is `COMPLETED`."

        Design: Corner/state_machines/order_terminal_cancelled_lockdown
        """
        advertiser = create_advertiser(name="Canc", credit_limit_cents=100000)
        order = create_order(advertiser["id"])
        validate_success(api.cancel_order(order["id"], SALESREP))
        resp = api.submit_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRevisionLoop:
    def test_approved_revised_resubmitted_approved_cycle(self, api):
        """PRD §3.4: "On approval, the system spawns the order's entire spot inventory: for each `ACTIVE` line, `weeks_requested` multiplied by `spots_per_week` spot rows, each beginning in `PENDING_PLACEMENT` and recording its owning line through `order_line_id`."
        PRD §3.4: "The order's `revision_no` increments by one on each return to `REVISED`, and its `version` advances as well."

        Design: Difficulty/non_linear_state_machine/order_revision_loop_approved_revised_submitted
        """
        advertiser = create_advertiser(name="A5")
        program = create_program(
            title="Thu Prime", daypart_code="PRIME", airs_weekday=4, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        create_avail_unit(week["id"], program["id"], "2026-08-06", total_seconds=120)
        order = create_order(advertiser["id"])
        line = add_order_line(
            order["id"], program["id"], spots_per_week=1, gross_rate_cents=15000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        first_gen = list_line_spots(line["id"])
        assert len(first_gen) == 1 and first_gen[0]["status"] == "PENDING_PLACEMENT"

        revised = validate_success(api.revise_order(order["id"], SALESREP))
        assert revised["status"] == "REVISED"
        assert revised["revision_no"] == 1

        validate_success(api.submit_order(order["id"], SALESREP))
        reapproved = approve_order(order["id"])
        assert reapproved["status"] == "APPROVED"
        assert reapproved["revision_no"] == 1, "revision_no increments only on return to REVISED"

        spots = list_line_spots(line["id"])
        cancelled = [s for s in spots if s["status"] == "CANCELLED"]
        pending = [s for s in spots if s["status"] == "PENDING_PLACEMENT"]
        assert [s["id"] for s in cancelled] == [first_gen[0]["id"]], (
            "the first-generation spot must be cancelled by the revision"
        )
        assert len(pending) == 1, "the second approval must re-spawn exactly 1 spot"

    def test_revision_blocked_once_a_spot_has_aired(self, api):
        """PRD §3.4: "a `SalesRep` can pull an `APPROVED` order back to `REVISED`, but only while no spot of the order has reached `AIRED`; if any spot has aired, the revision is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/order_revision_loop_approved_revised_submitted
        """
        ctx = setup_scheduled_scenario(log_date="2026-08-03", finalize=True)
        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(ctx["placed"][0]["id"], True, actual_rating=2.0)],
        )
        assert get_success_data(api.get_spot(ctx["placed"][0]["id"], TRAFFIC))["status"] == "AIRED"
        resp = api.revise_order(ctx["order"]["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExposureConservation:
    def test_approve_revise_cancel_returns_exposure_to_zero(self, api):
        """PRD §3.1: "An advertiser's outstanding exposure is the sum of `gross_budget_cents` across its orders currently in `APPROVED` or `COMPLETED` status"
        PRD §3.4: "Revision tears down the un-aired inventory — every spot in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` is set to `CANCELLED`, and every `SCHEDULED` spot whose `scheduled_air_date` is not covered by a `FINALIZED` or `RECONCILED` log day — whether no log day exists for that date or it is still in `DRAFT` — is likewise set to `CANCELLED`, with the line's `spot_length_seconds` released from the corresponding avail unit's booked counter for the spot's class bucket."

        Design: Difficulty/compensating_invariant/approve_then_revise_cancel_conserves_exposure_cents
        """
        advertiser = create_advertiser(name="A19", credit_limit_cents=1000000)
        program = create_program(
            title="Mon Daytime 19", daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-03", total_seconds=120)
        order = create_order(advertiser["id"])
        line = add_order_line(
            order["id"], program["id"], spots_per_week=1, gross_rate_cents=80000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        assert get_order(order["id"])["gross_budget_cents"] == 80000
        spot = list_line_spots(line["id"])[0]
        place_spot_fresh(spot["id"], unit["id"])
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

        validate_success(api.revise_order(order["id"], SALESREP))
        # No log day covers 2026-08-03, so the scheduled spot is torn down.
        assert get_spot_status(api, spot["id"]) == "CANCELLED"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 0

        cancelled = validate_success(api.cancel_order(order["id"], SALESREP))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["gross_budget_cents"] == 80000, (
            "order cancel is not a line operation, so the recorded budget is unchanged"
        )

        # Exposure probe: a fresh order whose budget exactly equals the credit
        # limit approves only if outstanding exposure returned to 0.
        probe = create_order(advertiser["id"])
        add_order_line(
            probe["id"], program["id"], spots_per_week=1, gross_rate_cents=1000000
        )
        submit_order(probe["id"])
        approved_probe = approve_order(probe["id"])
        assert approved_probe["status"] == "APPROVED", (
            "exposure must have returned to exactly 0 after approve -> revise -> cancel"
        )

    def test_line_cancel_recomputes_budget_before_exposure_check(self, api):
        """PRD §3.4: "A single line can be cancelled while the order is in `DRAFT` or `REVISED`: the line moves to `CANCELLED`, its spots still in `PENDING_PLACEMENT`, `PREEMPTED`, or `MAKE_GOOD_OFFERED` are cancelled outright, its `SCHEDULED` spots whose air dates are not yet locked into a finalized log are cancelled with their booked seconds released from the affected avail units, and the budget is recomputed."
        PRD §3.4: "the advertiser's outstanding exposure — the summed `gross_budget_cents` of its `APPROVED` and `COMPLETED` orders — plus this order's `gross_budget_cents` must not exceed the advertiser's `credit_limit_cents`, or approval is rejected with `ERR_CREDIT_LIMIT`; a total exactly equal to the limit passes."

        Design: Difficulty/compensating_invariant/approve_then_revise_cancel_conserves_exposure_cents
        """
        advertiser = create_advertiser(name="A19b", credit_limit_cents=40000)
        program = create_program(
            title="Mon Daytime 19b", daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0
        )
        create_avail_week("2026-08-03")
        order = create_order(advertiser["id"])
        keep = add_order_line(
            order["id"], program["id"], spots_per_week=1, gross_rate_cents=40000
        )
        drop = add_order_line(
            order["id"], program["id"], spots_per_week=1, gross_rate_cents=60000
        )
        assert get_order(order["id"])["gross_budget_cents"] == 100000
        validate_success(api.cancel_order_line(drop["id"], SALESREP))
        order = get_order(order["id"])
        assert order["gross_budget_cents"] == 40000, "budget recompute follows line cancel"
        submit_order(order["id"])
        approved = approve_order(order["id"])
        assert approved["status"] == "APPROVED", (
            "exposure 0 + recomputed 40000 must pass a credit limit of exactly 40000"
        )
        assert keep["status"] == "ACTIVE"


class TestCompletionSweep:
    def test_clock_advance_completes_fully_terminal_order(self, api):
        """PRD §3.4: "This completion sweep runs whenever the logical clock is advanced per §2.5: orders whose flight end falls strictly before the new clock date and whose spots are all terminal are completed at that moment."
        PRD §2.5: "A `StationAdmin` may advance the clock through an admin-only capability that accepts a payload carrying `to_iso8601` and returns the new reading as `current_utc`."

        Design: Corner/endpoints/order_completion_sweep_on_clock_advance
        """
        ctx = setup_scheduled_scenario(log_date="2026-08-03", finalize=True)
        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(ctx["placed"][0]["id"], True, actual_rating=2.0)],
        )
        clock = set_clock("2026-08-10T00:00:00Z")
        assert clock["current_utc"] == "2026-08-10T00:00:00Z"
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "COMPLETED", (
            "flight end 2026-08-09 is strictly before the new clock date and the "
            "order's only spot is AIRED (terminal)"
        )


def get_spot_status(api, spot_id):
    return get_success_data(api.get_spot(spot_id, TRAFFIC))["status"]
