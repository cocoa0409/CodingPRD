"""Resource-temporal overlap rules: half-open dispatch windows, buffered tow
pickup windows, and closed rate-card effective windows."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    create_dispatch,
    create_dispatch_payload,
    create_rate_card_payload,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_call,
    get_success_data,
    open_triaged_call,
    order_tow,
    parse_iso8601_utc,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _two_triaged_retail_calls():
    """Two retail vehicles with a TRIAGED call each; one AVAILABLE ENGINE
    technician. Returns (call_a, call_b, tech, tech_headers)."""
    create_standard_rate_card()
    veh_a = create_vehicle()
    veh_b = create_vehicle()
    tech, tech_headers = create_technician()
    advance_clock("2026-08-05T08:00:00Z")
    call_a = open_triaged_call(veh_a["id"], severity="DRIVABLE",
                               breakdown_location_text="site A")
    call_b = open_triaged_call(veh_b["id"], severity="DRIVABLE",
                               breakdown_location_text="site B")
    return call_a, call_b, tech, tech_headers


class TestDispatchWindowHalfOpenSemantics:
    def test_dispatch_window_overlap_rejected_for_interior_intersection(
            self, api):
        """PRD: dispatch creation is "refused when the named technician
        already holds a dispatch in `PROPOSED`, `ACCEPTED`, `EN_ROUTE`, or
        `ON_SITE` whose half-open window overlaps the requested one" —
        rejected with `ERR_DISPATCH_WINDOW_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency_allowed_overlap_rejected
        """
        call_a, call_b, tech, _th = _two_triaged_retail_calls()
        create_dispatch(call_a["id"], tech["id"], "2026-08-05T09:00:00Z",
                        "2026-08-05T12:00:00Z")

        resp = api.create_dispatch(
            call_b["id"],
            create_dispatch_payload(
                tech["id"], get_call(call_b["id"])["version"],
                window_start_at="2026-08-05T11:00:00Z",
                window_end_at="2026-08-05T15:00:00Z",
                planned_travel_miles=25),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP)

    def test_dispatch_window_adjacent_touch_allowed(self, api):
        """PRD: "the half-open convention means two windows that merely touch
        at an endpoint do not conflict" — a new window starting exactly at the
        existing window's end is accepted, and the failed overlapping create
        does not advance the call's version.

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency_allowed_overlap_rejected
        """
        call_a, call_b, tech, _th = _two_triaged_retail_calls()
        create_dispatch(call_a["id"], tech["id"], "2026-08-05T09:00:00Z",
                        "2026-08-05T12:00:00Z")
        version_before = get_call(call_b["id"])["version"]

        rejected = api.create_dispatch(
            call_b["id"],
            create_dispatch_payload(
                tech["id"], version_before,
                window_start_at="2026-08-05T11:00:00Z",
                window_end_at="2026-08-05T15:00:00Z",
                planned_travel_miles=25),
            DISPATCHER)
        validate_error(rejected, ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP)
        assert get_call(call_b["id"])["version"] == version_before, (
            "a rejected dispatch create must not mutate the call")

        created = validate_success(api.create_dispatch(
            call_b["id"],
            create_dispatch_payload(
                tech["id"], version_before,
                window_start_at="2026-08-05T12:00:00Z",
                window_end_at="2026-08-05T15:00:00Z",
                planned_travel_miles=25),
            DISPATCHER), 201)
        assert created["status"] == "PROPOSED", (
            "12:00 == existing window_end is adjacency, allowed under "
            "half-open semantics")


class TestTowPickupWindowBuffered:
    def _three_tow_ready_calls(self, api):
        """Three retail calls diagnosed TOW_REQUIRED, using two technicians
        with disjoint dispatch windows so no dispatch overlap occurs."""
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        veh_c = create_vehicle()
        tech, tech_headers = create_technician()
        spare, spare_headers = create_technician(full_name="Sam Spare")
        advance_clock("2026-08-05T07:00:00Z")

        call_a = open_triaged_call(veh_a["id"], severity="BLOCKING",
                                   symptom_description="seized engine",
                                   breakdown_location_text="site A")
        call_a, dispatch_a = drive_call_on_site(
            call_a, tech["id"], tech_headers, "2026-08-05T07:00:00Z",
            "2026-08-05T09:00:00Z", depart_at=None,
            arrive_at="2026-08-05T07:40:00Z", actual_travel_miles=20)
        diagnose_call(call_a["id"], tech_headers,
                      diagnosis_summary="engine seized, not roadside-repairable",
                      resolution_path="TOW_REQUIRED")
        tow_a = order_tow(call_a["id"], tow_unit_id="TT-7",
                          pickup_window_start_at="2026-08-05T10:00:00Z",
                          pickup_window_end_at="2026-08-05T12:00:00Z",
                          tow_fee_cents=85000)
        complete = api.complete_dispatch(dispatch_a["id"], tech_headers)
        assert complete.status_code == 200, complete.text

        call_b = open_triaged_call(veh_b["id"], severity="BLOCKING",
                                   symptom_description="hydrolock",
                                   breakdown_location_text="site B")
        call_b, _db = drive_call_on_site(
            call_b, tech["id"], tech_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T11:00:00Z", depart_at="2026-08-05T09:10:00Z",
            arrive_at="2026-08-05T09:40:00Z", actual_travel_miles=25)
        diagnose_call(call_b["id"], tech_headers,
                      diagnosis_summary="hydrolocked",
                      resolution_path="TOW_REQUIRED")

        call_c = open_triaged_call(veh_c["id"], severity="BLOCKING",
                                   symptom_description="thrown rod",
                                   breakdown_location_text="site C")
        call_c, _dc = drive_call_on_site(
            call_c, spare["id"], spare_headers, "2026-08-05T11:00:00Z",
            "2026-08-05T13:00:00Z", depart_at="2026-08-05T11:10:00Z",
            arrive_at="2026-08-05T11:40:00Z", actual_travel_miles=30)
        diagnose_call(call_c["id"], spare_headers,
                      diagnosis_summary="thrown rod",
                      resolution_path="TOW_REQUIRED")
        return call_b, call_c, tow_a

    def test_tow_window_buffered_touch_conflicts(self, api):
        """PRD: "a new order is rejected with `ERR_TOW_WINDOW_OVERLAP` when
        another order on the same `tow_unit_id` in `REQUESTED` or `HOOKED` has
        a pickup window that intersects the new one after both windows are
        expanded by thirty minutes on each side — and for this buffered check,
        touching endpoints do count as conflict."

        Design: Difficulty/resource_temporal_overlap/tow_pickup_window_buffered_touch_conflicts
        """
        call_b, _call_c, tow_a = self._three_tow_ready_calls(api)
        # A occupies 10:00-12:00, effectively 09:30-12:30 after the buffer;
        # B's 12:00-14:00 expands to 11:30-14:30 and intersects.
        resp = api.create_tow_order(
            call_b["id"],
            {"tow_provider_name": "HeavyHaul", "tow_unit_id": "TT-7",
             "pickup_location_text": "site B",
             "dropoff_location_text": "dealer Denver",
             "pickup_window_start_at": "2026-08-05T12:00:00Z",
             "pickup_window_end_at": "2026-08-05T14:00:00Z",
             "tow_fee_cents": 80000},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_TOW_WINDOW_OVERLAP)
        current = get_success_data(api.get_tow_order(tow_a["id"], DISPATCHER))
        assert current["status"] == "REQUESTED"

    def test_tow_window_one_minute_beyond_buffer_allowed(self, api):
        """PRD: tow windows conflict only when the thirty-minute-expanded
        windows intersect — "for this buffered check, touching endpoints do
        count as conflict", so a window whose expanded start falls strictly
        after the existing expanded end is accepted.

        Design: Difficulty/resource_temporal_overlap/tow_pickup_window_buffered_touch_conflicts
        """
        _call_b, call_c, tow_a = self._three_tow_ready_calls(api)
        # C's 13:01-15:00 expands to 12:31-15:30, strictly clear of A's
        # expanded end at 12:30.
        created = validate_success(api.create_tow_order(
            call_c["id"],
            {"tow_provider_name": "HeavyHaul", "tow_unit_id": "TT-7",
             "pickup_location_text": "site C",
             "dropoff_location_text": "dealer Denver",
             "pickup_window_start_at": "2026-08-05T13:01:00Z",
             "pickup_window_end_at": "2026-08-05T15:00:00Z",
             "tow_fee_cents": 90000},
            DISPATCHER), 201)
        assert created["status"] == "REQUESTED"
        current = get_success_data(api.get_tow_order(tow_a["id"], DISPATCHER))
        assert current["status"] == "REQUESTED"


class TestRateCardClosedWindow:
    def test_rate_card_window_touch_conflicts(self, api):
        """PRD: "Coverage windows of distinct cards must never overlap, and
        because both bounds are inclusive, two windows that merely touch at an
        endpoint already count as overlapping — publishing such a card is
        rejected with `ERR_RATE_CARD_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_card_closed_window_touch_conflicts
        """
        api.create_rate_card(
            create_rate_card_payload(
                name="H1-2026", effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-06-30T23:59:59Z"),
            OPS)
        # 2026-06-30T00:00:00Z falls inside the closed H1 window.
        resp = api.create_rate_card(
            create_rate_card_payload(
                name="H2-2026-TOUCH",
                effective_from="2026-06-30T00:00:00Z",
                effective_to="2026-12-31T23:59:59Z"),
            OPS)
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_WINDOW_OVERLAP)

    def test_rate_card_window_starting_next_instant_allowed(self, api):
        """PRD: "two windows that merely touch at an endpoint already count as
        overlapping" — a card whose window starts strictly after the existing
        card's inclusive `effective_to` shares no instant and is created.

        Design: Difficulty/resource_temporal_overlap/rate_card_closed_window_touch_conflicts
        """
        api.create_rate_card(
            create_rate_card_payload(
                name="H1-2026", effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-06-30T23:59:59Z"),
            OPS)
        created = validate_success(api.create_rate_card(
            create_rate_card_payload(
                name="H2-2026", effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-12-31T23:59:59Z"),
            OPS), 201)
        assert parse_iso8601_utc(created["effective_from"]) == \
            parse_iso8601_utc("2026-07-01T00:00:00Z"), (
            "the created card carries the requested window start instant")
