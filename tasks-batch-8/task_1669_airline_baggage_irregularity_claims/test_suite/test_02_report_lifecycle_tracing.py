"""Report creation state branches, tracing events, and the tracing-timeout sweep
(PRD §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    CLOCK_EPOCH, CLOCK_PLUS_503H59M, CLOCK_PLUS_504H,
    create_report_payload, create_tracing_event_payload,
    create_station, create_carrier, create_passenger, create_bag_tag, create_report,
    set_clock, setup_bag_and_report,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestInitialStateBranches:

    def test_delayed_report_enters_tracing_bag_mishandled(self, api):
        """PRD §3.3: "A `DELAYED` report moves from `OPEN` to `TRACING`, and its bag
        flips from `CHECKED` to `MISHANDLED`."
        PRD §3.3: "In both cases the filing station's `open_report_count` is
        incremented."

        Design: Corner/state_machines/delayed_report_initial_state_tracing_and_bag_mishandled
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"], [carrier["id"]])
        resp = api.create_report(
            create_report_payload(passenger["id"], bag["id"], station["id"],
                                  type="DELAYED"), AGENT)
        data = validate_success(resp, 201)
        # The creation response itself shows the post-cascade state.
        assert data["status"] == "TRACING"
        bag_now = get_success_data(api.get_bag_tag(bag["id"], AGENT))
        assert bag_now["status"] == "MISHANDLED"
        station_now = get_success_data(api.get_station(station["id"], AGENT))
        assert station_now["open_report_count"] == 1

    def test_damaged_report_enters_damage_review(self, api):
        """PRD §3.3: "A `DAMAGED` or `PILFERED` report moves from `OPEN` to
        `DAMAGE_REVIEW`, and its bag flips from `CHECKED` to `DELIVERED_DAMAGED`."

        Design: Corner/state_machines/damaged_report_initial_state_damage_review
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"], [carrier["id"]])
        resp = api.create_report(
            create_report_payload(passenger["id"], bag["id"], station["id"],
                                  type="DAMAGED"), AGENT)
        data = validate_success(resp, 201)
        assert data["status"] == "DAMAGE_REVIEW"
        bag_now = get_success_data(api.get_bag_tag(bag["id"], AGENT))
        assert bag_now["status"] == "DELIVERED_DAMAGED"


class TestLocatedCascade:

    def test_located_event_three_hop_cascade(self, api):
        """PRD §3.4: "A `LOCATED` event triggers the recovery cascade. The report
        moves from `TRACING` to `FOUND_PENDING_DELIVERY`; the bag moves from
        `MISHANDLED` to `IN_RECOVERY`; and the station named by the event's own
        `station_id` — the station where the bag surfaced — has its
        `recovered_bag_count` incremented."

        Design: Difficulty/transitive_cascade/located_event_three_hop_cascade
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        assert ctx["report"]["status"] == "TRACING"
        assert ctx["bag"]["status"] == "MISHANDLED"
        station_before = get_success_data(api.get_station(ctx["station"]["id"], AGENT))
        assert station_before["recovered_bag_count"] == 0

        resp = api.record_tracing_event(
            ctx["report"]["id"],
            create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"],
                                         "LOCATED"), AGENT)
        event = validate_success(resp, 201)
        assert event["event_type"] == "LOCATED"

        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "FOUND_PENDING_DELIVERY"
        bag_now = get_success_data(api.get_bag_tag(ctx["bag"]["id"], AGENT))
        assert bag_now["status"] == "IN_RECOVERY"
        station_now = get_success_data(api.get_station(ctx["station"]["id"], AGENT))
        assert station_now["recovered_bag_count"] == 1

    def test_located_event_recorded_on_file(self, api):
        """PRD §3.4: "a `BaggageServiceAgent` records each WorldTracer message
        against the report as a **Tracing Event**. The agent supplies the sending
        `carrier_id`, the `station_id` the message reports from, and an `event_type`
        of `FORWARDED`, `LOCATED`, `ON_HAND_AT_STATION`, `IN_TRANSIT_TO`,
        `DELIVERY_ARRANGED`, or `MISSCAN_CORRECTED`"
        PRD §3.4: "A `LOCATED` event triggers the recovery cascade."

        Design: Difficulty/transitive_cascade/located_event_three_hop_cascade
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        resp = api.record_tracing_event(
            ctx["report"]["id"],
            create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"],
                                         "LOCATED"), AGENT)
        event = validate_success(resp, 201)
        # The recorded event itself is retrievable and belongs to the report.
        fetched = get_success_data(api.get_tracing_event(event["id"], AGENT))
        assert fetched["id"] == event["id"]
        assert fetched["report_id"] == ctx["report"]["id"]
        assert fetched["event_type"] == "LOCATED"
        assert fetched["carrier_id"] == ctx["carrier"]["id"]
        assert fetched["station_id"] == ctx["station"]["id"]

    def test_second_located_event_rejected(self, api):
        """PRD §3.4: "Recording a message on a report that is no longer in `TRACING`
        is rejected with `ERR_REPORT_NOT_TRACING`."

        Design: Corner/state_machines/second_located_event_rejected
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        get_success_data(api.record_tracing_event(
            ctx["report"]["id"],
            create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"],
                                         "LOCATED"), AGENT))
        resp = api.record_tracing_event(
            ctx["report"]["id"],
            create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"],
                                         "LOCATED"), AGENT)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_TRACING, 409)
        station_now = get_success_data(api.get_station(ctx["station"]["id"], AGENT))
        assert station_now["recovered_bag_count"] == 1


class TestTracingTimeoutSweep:

    def test_sweep_at_exactly_504_hours(self, api):
        """PRD §3.4: "if at least 504 hours — twenty-one days — have elapsed between
        the report's `created_at` and the new clock time, and no `LOCATED` tracing
        event exists for the report, the report is swept to `DECLARED_LOST` and its
        bag moves from `MISHANDLED` to `CLAIMED_LOST`. The clock-setting response
        lists the affected reports in `swept_report_ids`."

        Design: Difficulty/boundary_precision_check/tracing_timeout_exactly_504_hours
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        rpt_id = ctx["report"]["id"]
        # created_at == 2026-08-01T00:00:00Z because the fixture pins the epoch.

        sweep1 = get_success_data(api.set_clock(CLOCK_PLUS_503H59M, ADMIN))
        assert rpt_id not in sweep1["swept_report_ids"]
        report_now = get_success_data(api.get_report(rpt_id, AGENT))
        assert report_now["status"] == "TRACING"

        sweep2 = get_success_data(api.set_clock(CLOCK_PLUS_504H, ADMIN))
        assert rpt_id in sweep2["swept_report_ids"]
        report_now = get_success_data(api.get_report(rpt_id, AGENT))
        assert report_now["status"] == "DECLARED_LOST"
        bag_now = get_success_data(api.get_bag_tag(ctx["bag"]["id"], AGENT))
        assert bag_now["status"] == "CLAIMED_LOST"

    def test_sweep_leaves_located_report_untouched(self, api):
        """PRD §3.4: "if at least 504 hours — twenty-one days — have elapsed between
        the report's `created_at` and the new clock time, and no `LOCATED` tracing
        event exists for the report, the report is swept to `DECLARED_LOST` and its
        bag moves from `MISHANDLED` to `CLAIMED_LOST`."

        Design: Difficulty/boundary_precision_check/tracing_timeout_exactly_504_hours
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        # A LOCATED event takes the report out of TRACING and exempts it from sweep.
        get_success_data(api.record_tracing_event(
            ctx["report"]["id"],
            create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"],
                                         "LOCATED"), AGENT))
        sweep = get_success_data(api.set_clock(CLOCK_PLUS_504H, ADMIN))
        assert ctx["report"]["id"] not in sweep["swept_report_ids"]
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "FOUND_PENDING_DELIVERY"
