"""Amnesty windows (half-open membership, freeze, cancellation), load units,
and the projected-vs-committed route fullness pair."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_item,
    create_amnesty_window_payload,
    create_draft_request,
    create_household,
    create_route_day,
    dispatch_route,
    get_ledger_row,
    get_request,
    get_request_items,
    get_route_day,
    get_success_data,
    make_resident_headers,
    set_clock,
    setup_scheduled_request,
    submit_request,
    validate_error,
    validate_success,
)

DRIVER = TEST_USERS["driver_headers"]


def _make_window(api, dispatcher_headers, label, starts_at, ends_at):
    return api.create_amnesty_window(
        create_amnesty_window_payload(
            label=label, starts_at=starts_at, ends_at=ends_at
        ),
        dispatcher_headers,
    )


def _build_request_on(api, household_id, items):
    """Draft -> items -> submit on an existing household. items: tuples
    (sequence_no, category, is_oversize, preparation_ack)."""
    req = create_draft_request(household_id)
    for (seq, cat, oversize, ack) in items:
        add_item(household_id, req["id"], seq, cat, oversize, ack)
    submit_request(household_id, req["id"])
    return get_request(household_id, req["id"])


def _schedule(api, household_id, request_id, route_day):
    return api.schedule_pickup_request(
        request_id,
        {
            "route_day_id": route_day["id"],
            "expected_route_day_version": route_day["version"],
        },
        make_resident_headers(household_id),
    )


class TestProjectedVsCommittedFullness:
    def _setup_two_stops_one_completed(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(
            service_zone="ZONE_EAST", route_date="2026-08-10",
            max_load_units=40, max_stops=25,
        )
        _, req_a, _, _ = setup_scheduled_request(
            street_address="10 Oak Ave", service_zone="ZONE_EAST",
            annual_allowance_items=4, route_day=rd,
        )
        setup_scheduled_request(
            street_address="12 Oak Ave", service_zone="ZONE_EAST",
            annual_allowance_items=4, route_day=rd,
        )
        set_clock("2026-08-10T07:00:00Z")
        dispatch_route(rd["id"])
        get_success_data(api.complete_pickup_request(req_a["id"], {}, DRIVER))
        return rd

    def test_committed_counters_include_completed_stop(self, api):
        """PRD §3.7: "The stored committed counters — `committed_load_units`
        and `committed_stops` — count requests in `SCHEDULED` or `COMPLETED`;
        this is the capacity-and-billing truth, the figure capacity
        enforcement uses, and it means a completed stop still occupies
        capacity for the rest of the day."

        Design: Difficulty/dual_variant_calc/routeday_projected_vs_committed_fullness
        """
        rd = self._setup_two_stops_one_completed(api)
        route = get_route_day(rd["id"])
        assert route["committed_load_units"] == 4
        assert route["committed_stops"] == 2

    def test_projected_view_drops_completed_stop(self, api):
        """PRD §3.7: "The projected view, recomputed on every read of the
        route day, counts only requests currently in `SCHEDULED`:
        `projected_load_units` sums those requests' `load_units`, and
        `projected_fullness_pct` is 100 times that sum divided by
        `max_load_units`, rounded half-up to a whole percentage point."

        Design: Difficulty/dual_variant_calc/routeday_projected_vs_committed_fullness
        """
        rd = self._setup_two_stops_one_completed(api)
        route = get_route_day(rd["id"])
        assert route["projected_load_units"] == 2
        assert route["projected_fullness_pct"] == 5
        assert route["projected_load_units"] != route["committed_load_units"]


class TestAmnestyWindowOverlap:
    def test_touching_window_endpoints_allowed(self, api, dispatcher_headers):
        """PRD §3.6: "the window includes its start instant and excludes its
        end instant, so `starts_at` must be strictly earlier than `ends_at`,
        and the new window must not intersect any existing `ACTIVE` window
        (touching endpoints are allowed, since an instant that ends one window
        is excluded from it)."

        Design: Difficulty/resource_temporal_overlap/amnesty_window_half_open_overlap
        """
        set_clock("2026-08-05T00:00:00Z")
        r1 = _make_window(api, dispatcher_headers, "Fall week 1",
                          "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z")
        validate_success(r1, expected_status=201)
        r2 = _make_window(api, dispatcher_headers, "Fall week 2 touching",
                          "2026-09-14T00:00:00Z", "2026-09-21T00:00:00Z")
        data = validate_success(r2, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_intersecting_window_rejected(self, api, dispatcher_headers):
        """PRD §3.6: "Violating either temporal rule at declaration is
        `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/amnesty_window_half_open_overlap
        """
        set_clock("2026-08-05T00:00:00Z")
        r1 = _make_window(api, dispatcher_headers, "Fall week 1",
                          "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z")
        validate_success(r1, expected_status=201)
        r3 = _make_window(api, dispatcher_headers, "Overlapping",
                          "2026-09-13T23:00:00Z", "2026-09-22T00:00:00Z")
        validate_error(r3, ApiErrorId.ERR_TEMPORAL_CONFLICT)
        assert r3.status_code == 422


class TestAmnestyFeeFreeze:
    def test_amnesty_waives_over_allowance_but_keeps_refrigerant(
        self, api, dispatcher_headers
    ):
        """PRD §3.3: "when amnesty applies, the 2500-cent over-allowance
        component is waived to zero for every item, while the refrigerant,
        oversize, and mattress components and the 8.5 percent surcharge stand
        unchanged."
        PRD §3.2: "Refrigerant recovery is never discounted or waived at any
        point in the lifecycle — not even by an amnesty week."
        PRD §3.6: "the allowance ledger itself is untouched — amnesty forgives
        the fee, not the slot."

        Design: Corner/calculations/amnesty_freezes_zero_over_allowance_but_keeps_refrigerant
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("41 Amnesty Ave", "ZONE_SOUTH",
                              annual_allowance_items=0)
        validate_success(_make_window(
            api, dispatcher_headers, "Fall amnesty",
            "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z",
        ), expected_status=201)
        rd = create_route_day(service_zone="ZONE_SOUTH", route_date="2026-09-08")

        req = _build_request_on(api, hh["id"], (
            (1, "APPLIANCE_WITH_REFRIGERANT", False, True),
            (2, "STANDARD_FURNITURE", False, True),
        ))
        data = validate_success(_schedule(api, hh["id"], req["id"], rd))
        assert data["amnesty_applied"] is True
        # item1: refrigerant 4500 stands; surcharge round_half_up(382.5)=383.
        # item2: all components waived.
        assert data["provisional_total_cents"] == 4883

        items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        by_seq = {i["sequence_no"]: i for i in items}
        assert by_seq[1]["item_fee_cents"] == 4883
        assert by_seq[2]["item_fee_cents"] == 0

        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["over_allowance_items"] == 2

    def test_amnesty_membership_half_open_at_date_midnight(
        self, api, dispatcher_headers
    ):
        """PRD §3.3: "It freezes `amnesty_applied`: true if and only if an
        `ACTIVE` amnesty window exists whose half-open interval contains the
        scheduled date's midnight instant — that is, the window's `starts_at`
        is at or before midnight at the start of `scheduled_date`, and that
        midnight is strictly before `ends_at`."

        Design: Corner/calculations/amnesty_boundary_endpoints_half_open_membership
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("43 Boundary Blvd", "ZONE_NORTH",
                              annual_allowance_items=0)
        validate_success(_make_window(
            api, dispatcher_headers, "Fall amnesty",
            "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z",
        ), expected_status=201)
        rd_in = create_route_day(service_zone="ZONE_NORTH", route_date="2026-09-07")
        rd_out = create_route_day(service_zone="ZONE_NORTH", route_date="2026-09-14")

        req_in = _build_request_on(
            api, hh["id"], ((1, "STANDARD_FURNITURE", False, True),)
        )
        validate_success(_schedule(api, hh["id"], req_in["id"], rd_in))

        req_out = _build_request_on(
            api, hh["id"], ((1, "STANDARD_FURNITURE", False, True),)
        )
        validate_success(_schedule(api, hh["id"], req_out["id"], rd_out))

        got_in = get_request(hh["id"], req_in["id"])
        got_out = get_request(hh["id"], req_out["id"])
        assert got_in["amnesty_applied"] is True
        assert got_in["provisional_total_cents"] == 0
        assert got_out["amnesty_applied"] is False
        assert got_out["provisional_total_cents"] == 2713

    def test_cancelled_amnesty_window_keeps_frozen_quotes(
        self, api, dispatcher_headers
    ):
        """PRD §3.6: "A `Dispatcher` may cancel a window, moving it `ACTIVE →
        CANCELLED` with a version bump; requests already scheduled under it
        keep their frozen quotes, with no retroactive repricing."

        Design: Corner/calculations/cancelled_amnesty_window_keeps_frozen_quotes
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("45 Frozen Ft", "ZONE_EAST",
                              annual_allowance_items=0)
        win = get_success_data(_make_window(
            api, dispatcher_headers, "Doomed amnesty",
            "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z",
        ))
        rd = create_route_day(service_zone="ZONE_EAST", route_date="2026-09-08")

        req = _build_request_on(
            api, hh["id"], ((1, "STANDARD_FURNITURE", False, True),)
        )
        validate_success(_schedule(api, hh["id"], req["id"], rd))

        win_after = validate_success(
            api.cancel_amnesty_window(win["id"], dispatcher_headers)
        )
        assert win_after["status"] == "CANCELLED"

        req_after = get_request(hh["id"], req["id"])
        assert req_after["amnesty_applied"] is True
        assert req_after["provisional_total_cents"] == 0


class TestLoadUnits:
    def test_load_units_oversize_multiplier_and_recompute(self, api):
        """PRD §3.2: "The request's `load_units` are the sum over its items of
        the category's base load, doubled for oversize items: standard
        furniture contributes 2 units, a mattress 3, a non-refrigerant
        appliance 4, a refrigerant appliance 5, electronics 2, and tires 1,
        each multiplied by 2 when the item is oversize and by 1 otherwise.
        This figure is recomputed on every item change while drafting and
        re-validated at scheduling."
        PRD §3.2: "Adding or removing an item recomputes the request's
        `load_units` and bumps the request's `version` by 1; items may be
        removed only while the request is in `DRAFT`"

        Design: Corner/calculations/load_units_oversize_multiplier
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("31 Load Ln", "ZONE_NORTH")
        req = create_draft_request(hh["id"])
        add_item(hh["id"], req["id"], 1, "STANDARD_FURNITURE", True, True)
        it2 = add_item(hh["id"], req["id"], 2, "STANDARD_FURNITURE", False, True)

        with_both = get_request(hh["id"], req["id"])
        assert with_both["load_units"] == 6  # (2*2) + 2

        resp = api.remove_item(req["id"], it2["id"], make_resident_headers(hh["id"]))
        assert resp.status_code == 204
        after = get_request(hh["id"], req["id"])
        assert after["load_units"] == 4
