"""Venue registration, show booking schema rules, contract pricing, and the
show-window turnaround buffer."""
from test_helpers import (
    ApiErrorId,
    create_show_event_payload,
    create_site,
    create_site_payload,
    get_success_data,
    is_valid_uuid,
    set_clock,
    setup_authorized_show,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PLANNER = TEST_USERS["planner_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


class TestSiteRegistration:
    def test_site_create_and_get_roundtrip(self, api):
        """PRD: "A `ProductionPlanner` registers a Site by supplying its display
        `name`, its geographic position as `latitude` (between −90 and 90 degrees
        inclusive) and `longitude` (between −180 and 180 degrees inclusive), the
        usable ground rectangle as `ground_length_m` and `ground_width_m` (both
        strictly positive — the launch grid and the safety perimeter must
        physically fit inside it), and the venue's hard environmental ceilings"
        PRD: "All five roles may use every read endpoint."

        Design: Corner/entities/site_create_and_get_roundtrip
        """
        payload = create_site_payload(
            name="Harbor Front", latitude=34.5, longitude=-118.25,
            ground_length_m=600, ground_width_m=450, site_max_wind_kt=15,
            site_max_gust_kt=20, site_max_altitude_ft=400)
        resp = api.create_site(payload, PLANNER)
        site = validate_success(resp, 201)
        assert is_valid_uuid(site["id"]), "id is a server-minted UUID"
        assert isinstance(site["version"], int), "version is a system-managed integer"

        fetched = validate_success(api.get_site(site["id"], FLEET))
        for field, value in payload.items():
            assert fetched[field] == value, \
                f"GET must return {field} verbatim: expected {value}, got {fetched[field]}"

    def test_site_latitude_out_of_range_rejected(self, api):
        """PRD: "A `ProductionPlanner` registers a Site by supplying its display
        `name`, its geographic position as `latitude` (between −90 and 90 degrees
        inclusive)" and "Values outside these ranges are rejected with
        `ERR_VALIDATION`."

        Design: Corner/entities/site_coordinate_range_enforced
        """
        resp = api.create_site(
            create_site_payload(name="Bad Site", latitude=95), PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_site_missing_name_rejected(self, api):
        """PRD: "required fields present, types valid, enum values in range, and
        numeric constraints honored" and "All such failures carry
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/site_missing_name_returns_invalid_request
        """
        payload = create_site_payload()
        del payload["name"]
        resp = api.create_site(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestShowBookingSchema:
    def test_show_window_inverted_rejected(self, api):
        """PRD: "a `window_end` that is not after `window_start` fails schema
        validation with `ERR_VALIDATION`."

        Design: Corner/entities/show_window_inverted_rejected
        """
        site = create_site()
        set_clock()
        resp = api.create_show_event(
            create_show_event_payload(
                site["id"], name="Bad Show",
                window_start="2026-08-10T19:30:00Z",
                window_end="2026-08-10T19:00:00Z"),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_backup_window_under_24h_gap_rejected(self, api):
        """PRD: "the backup start must fall at least 24 hours after the main
        window's end; and the backup end must be after the backup start.
        Violations of the backup pairing or the 24-hour gap are `ERR_VALIDATION`
        failures."

        Design: Corner/entities/backup_window_24h_minimum_enforced
        """
        site = create_site()
        set_clock()
        # Backup start 12h after window_end violates the 24h minimum gap.
        resp = api.create_show_event(
            create_show_event_payload(
                site["id"], backup_window_start="2026-08-11T07:30:00Z",
                backup_window_end="2026-08-11T08:00:00Z"),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_show_create_computes_pricing_and_rejects_computed_input(self, api):
        """PRD: "The drone fee is tiered by the booked count: 2,500 cents for
        each of the first 100 drones" ... "A logistics surcharge is then applied
        to that subtotal: 8 percent when the pre-surcharge subtotal is at least
        1,000,000 cents (ten thousand dollars), otherwise 5 percent"
        PRD: "A freshly booked show carries `lifecycle_status` `PLANNING` and
        `payment_status` `DEPOSIT_DUE` — two parallel state dimensions that
        evolve independently."
        PRD: "Computed or system-managed fields supplied in a request body are
        likewise rejected."

        Design: Corner/entities/show_create_computes_pricing_and_rejects_computed_input
        """
        site = create_site()
        set_clock()
        resp = api.create_show_event(
            create_show_event_payload(site["id"], drone_count_planned=10), PLANNER)
        show = validate_success(resp, 201)
        # 10 drones: fee 25000; subtotal 525000; 5% surcharge 26250.
        assert show["contract_value_cents"] == 551250
        assert show["deposit_cents"] == 165375
        assert show["balance_cents"] == 385875
        assert show["lifecycle_status"] == "PLANNING"
        assert show["payment_status"] == "DEPOSIT_DUE"
        assert show["readiness_posture"] == "NOT_READY"
        assert show["assigned_count"] == 0

        resp = api.create_show_event(
            create_show_event_payload(
                site["id"], name="Show X",
                window_start="2026-08-14T19:00:00Z",
                window_end="2026-08-14T19:30:00Z",
                contract_value_cents=1),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestContractPricingTiers:
    def test_pricing_marginal_drone_fee_at_101(self, api):
        """PRD: "The drone fee is tiered by the booked count: 2,500 cents for
        each of the first 100 drones, 2,200 cents for each of the next 200
        drones (the 101st through the 300th), and 2,000 cents for every drone
        beyond 300."

        Design: Corner/calculations/pricing_marginal_drone_fee_at_101
        """
        site = create_site()
        set_clock()
        show100 = validate_success(api.create_show_event(
            create_show_event_payload(site["id"], name="Show 100",
                                      drone_count_planned=100), PLANNER), 201)
        show101 = validate_success(api.create_show_event(
            create_show_event_payload(site["id"], name="Show 101",
                                      window_start="2026-08-12T19:00:00Z",
                                      window_end="2026-08-12T19:30:00Z",
                                      drone_count_planned=101), PLANNER), 201)
        # 100 drones: fee 250000, subtotal 750000, 5% surcharge 37500.
        assert show100["contract_value_cents"] == 787500
        # The 101st drone is billed at the marginal 2200-cent tier:
        # fee 252200, subtotal 752200, 5% surcharge 37610.
        assert show101["contract_value_cents"] == 789810

    def test_surcharge_tier_keyed_on_pre_surcharge_subtotal_below(self, api):
        """PRD: "A logistics surcharge is then applied to that subtotal: 8
        percent when the pre-surcharge subtotal is at least 1,000,000 cents (ten
        thousand dollars), otherwise 5 percent — note that the surcharge tier is
        keyed on the pre-surcharge subtotal, never on the final total that
        itself contains the surcharge."

        Design: Difficulty/combinatorial_formula/pricing_surcharge_tier_pinned_evaluation_order
        """
        site = create_site()
        set_clock()
        show = validate_success(api.create_show_event(
            create_show_event_payload(site["id"], name="Show 213",
                                      drone_count_planned=213), PLANNER), 201)
        # 213 drones: fee 498600, pre-surcharge subtotal 998600 < 1000000 -> 5%.
        # Keying on the final total (1048530 >= 1e6) would wrongly apply 8%.
        assert show["contract_value_cents"] == 1048530
        assert show["deposit_cents"] == 314559
        assert show["balance_cents"] == 733971

    def test_surcharge_tier_keyed_on_pre_surcharge_subtotal_above(self, api):
        """PRD: "A logistics surcharge is then applied to that subtotal: 8
        percent when the pre-surcharge subtotal is at least 1,000,000 cents (ten
        thousand dollars), otherwise 5 percent — note that the surcharge tier is
        keyed on the pre-surcharge subtotal, never on the final total that
        itself contains the surcharge."
        PRD: "The `deposit_cents` is 30 percent of the contract value, rounded
        half up to integer cents, and the `balance_cents` is the contract value
        minus the deposit."

        Design: Difficulty/combinatorial_formula/pricing_surcharge_tier_pinned_evaluation_order
        """
        site = create_site()
        set_clock()
        show = validate_success(api.create_show_event(
            create_show_event_payload(site["id"], name="Show 214",
                                      drone_count_planned=214), PLANNER), 201)
        # 214 drones: fee 500800, pre-surcharge subtotal 1000800 >= 1000000 -> 8%.
        assert show["contract_value_cents"] == 1080864
        assert show["deposit_cents"] == 324259
        assert show["balance_cents"] == 756605


class TestShowWindowTurnaround:
    def test_show_window_90_minute_gap_conflicts(self, api):
        """PRD: "Two shows at the same venue must respect a turnaround buffer of
        120 minutes between one show's window end and the next show's start."
        and "Any other arrangement is rejected with `ERR_SHOW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/show_window_turnaround_buffer_semantics
        """
        site = create_site()
        set_clock()
        get_success_data(api.create_show_event(
            create_show_event_payload(site["id"], name="Show A"), PLANNER))
        # 21:00 is only 90 minutes after Show A's 19:30 end.
        resp = api.create_show_event(
            create_show_event_payload(site["id"], name="Show B",
                                      window_start="2026-08-10T21:00:00Z",
                                      window_end="2026-08-10T21:30:00Z",
                                      drone_count_planned=5),
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHOW_WINDOW_CONFLICT)

    def test_show_window_exactly_120_minutes_allowed(self, api):
        """PRD: "the new window is clear of the other only when it starts at or
        after 120 minutes past the other's window end, or ends at or before 120
        minutes before the other's window start."

        Design: Difficulty/resource_temporal_overlap/show_window_turnaround_buffer_semantics
        """
        site = create_site()
        set_clock()
        get_success_data(api.create_show_event(
            create_show_event_payload(site["id"], name="Show A"), PLANNER))
        # 21:30 is exactly 120 minutes after Show A's 19:30 end.
        show_c = validate_success(api.create_show_event(
            create_show_event_payload(site["id"], name="Show C",
                                      window_start="2026-08-10T21:30:00Z",
                                      window_end="2026-08-10T22:00:00Z",
                                      drone_count_planned=5),
            PLANNER), 201)
        assert show_c["lifecycle_status"] == "PLANNING"
