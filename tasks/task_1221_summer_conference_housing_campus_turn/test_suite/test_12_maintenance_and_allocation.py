"""Maintenance windows (conflicts, deadline, lifecycle) and revenue allocation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    assert_allocation_buckets_sum_to_gross,
    create_allocation_run_payload,
    create_building,
    create_building_payload,
    create_building_turn_active,
    create_group,
    create_maintenance_window_payload,
    create_revision_payload,
    get_building,
    get_group,
    get_room,
    get_success_data,
    make_coordinator_headers,
    set_clock,
    setup_paid_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _fresh_building_version(api, building_id):
    return get_building(building_id)["version"]


class TestBufferedInclusiveConflict:
    def _building_with_late_july_stay(self, api):
        """Building TURN_ACTIVE; a RESERVED assignment occupying nights
        2026-07-28 .. 2026-07-31 (checkout date 2026-08-01 does not count)."""
        building, rooms = create_building_turn_active(name="Reed Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 1),))
        group = create_group(building["id"], client_name="Finance Summit",
                             arrival_date="2026-07-28", departure_date="2026-08-01",
                             deposit_paid_cents=5000)
        participant = add_participant(group["id"], date_of_birth="1972-02-02")
        headers = make_coordinator_headers(group["id"])
        version = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version, [{
                "participant_id": participant["id"], "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-07-28T15:00:00Z",
                "checkout_at": "2026-08-01T11:00:00Z",
            }]), headers))
        return building, rooms

    def test_buffered_window_colliding_occupied_night_rejected(self, api):
        """PRD: "the conflict check — the inclusive blocked interval must not
        intersect the occupied nights of any RESERVED or CHECKED_IN assignment in
        the building (a stay occupies each night from its check-in date through
        the day before its checkout date), nor the blocked interval of any other
        CONFIRMED or IN_PROGRESS window on the same building, else
        ERR_MAINTENANCE_CONFLICT"

        Design: Difficulty/resource_temporal_overlap/maintenance_buffered_inclusive_window_conflict
        """
        building, _rooms = self._building_with_late_july_stay(api)
        version = _fresh_building_version(api, building["id"])
        window = get_success_data(api.create_maintenance_window(
            building["id"],
            create_maintenance_window_payload(version, start_date="2026-08-01",
                                              end_date="2026-08-03", buffer_days=1),
            FACILITIES))
        # Blocked interval 2026-07-31 .. 2026-08-04 (inclusive) meets the
        # occupied night of 2026-07-31.
        resp = api.confirm_maintenance_window(window["id"], FACILITIES)
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_CONFLICT)
        after = get_success_data(api.get_maintenance_window(window["id"], FACILITIES))
        assert after["status"] == "PLANNED"

    def test_buffered_window_clearing_occupied_nights_confirms(self, api):
        """PRD: "`blocked_start_date` is `buffer_days` before `start_date`, and
        `blocked_end_date` is `buffer_days` after `end_date`."
        PRD: "Confirming a window moves `PLANNED` to `CONFIRMED` and runs its
        checks in order"

        Design: Difficulty/resource_temporal_overlap/maintenance_buffered_inclusive_window_conflict
        """
        building, _rooms = self._building_with_late_july_stay(api)
        version = _fresh_building_version(api, building["id"])
        window = get_success_data(api.create_maintenance_window(
            building["id"],
            create_maintenance_window_payload(version, start_date="2026-08-02",
                                              end_date="2026-08-04", buffer_days=1),
            FACILITIES))
        # Blocked interval 2026-08-01 .. 2026-08-05 (inclusive); the stay's last
        # occupied night is 2026-07-31, so the inclusive interval does not meet it.
        confirmed = validate_success(
            api.confirm_maintenance_window(window["id"], FACILITIES))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["blocked_start_date"] == "2026-08-01"
        assert confirmed["blocked_end_date"] == "2026-08-05"


class TestFallDeadline:
    def test_fall_deadline_equality_fails(self, api):
        """PRD: "then the fall-deadline check — `blocked_end_date` must be
        strictly before the building's `fall_opening_date`, with equality failing
        as `ERR_FALL_DEADLINE_IMMINENT`."

        Design: Corner/validations/fall_deadline_equality_fails
        """
        building, _rooms = create_building_turn_active(name="Ward Hall",
                                                       key_pool_size=5,
                                                       rooms=(("R1", 1),))
        version = _fresh_building_version(api, building["id"])
        w1 = get_success_data(api.create_maintenance_window(
            building["id"],
            create_maintenance_window_payload(version, start_date="2026-08-17",
                                              end_date="2026-08-19", buffer_days=1),
            FACILITIES))
        # blocked_end_date 2026-08-20 == fall_opening_date: equality fails.
        validate_error(api.confirm_maintenance_window(w1["id"], FACILITIES),
                       ApiErrorId.ERR_FALL_DEADLINE_IMMINENT)
        version2 = _fresh_building_version(api, building["id"])
        w2 = get_success_data(api.create_maintenance_window(
            building["id"],
            create_maintenance_window_payload(version2, start_date="2026-08-16",
                                              end_date="2026-08-18", buffer_days=1),
            FACILITIES))
        # blocked_end_date 2026-08-19 < 2026-08-20: strictly before passes.
        confirmed = validate_success(api.confirm_maintenance_window(w2["id"], FACILITIES))
        assert confirmed["status"] == "CONFIRMED"


class TestMaintenanceLifecycle:
    def test_maintenance_window_full_lifecycle_restores_rooms(self, api):
        """PRD: "the start cascades every room of the building in RELEASED or
        READY to OUT_OF_SERVICE, stamping each room's out_of_service_window_id
        with the window's id and raising out_of_service_room_count by the number
        of rooms taken. Completing the window moves IN_PROGRESS to its terminal
        COMPLETED state and restores every room holding that window's id from
        OUT_OF_SERVICE to READY, clearing out_of_service_window_id and lowering
        the count by the rooms restored"

        Design: Corner/endpoints/maintenance_window_full_lifecycle_restores_rooms
        """
        building, rooms = create_building_turn_active(name="Lima Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        version = _fresh_building_version(api, building["id"])
        window = get_success_data(api.create_maintenance_window(
            building["id"],
            create_maintenance_window_payload(version, start_date="2026-08-10",
                                              end_date="2026-08-12", buffer_days=1),
            FACILITIES))
        get_success_data(api.confirm_maintenance_window(window["id"], FACILITIES))
        set_clock("2026-08-10T08:00:00Z")
        started = validate_success(api.start_maintenance_window(window["id"], FACILITIES))
        assert started["status"] == "IN_PROGRESS"
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "OUT_OF_SERVICE"
        assert room["out_of_service_window_id"] == window["id"]
        assert get_building(building["id"])["out_of_service_room_count"] == 1

        completed = validate_success(
            api.complete_maintenance_window(window["id"], FACILITIES))
        assert completed["status"] == "COMPLETED"
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "READY"
        assert room["out_of_service_window_id"] is None
        assert get_building(building["id"])["out_of_service_room_count"] == 0


class TestRevenueAllocation:
    def _building_with_paid_invoice(self, api):
        """One PAID invoice of total 36000, paid_at 2026-06-19T12:00:00Z."""
        building, rooms = create_building_turn_active(name="Foster Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, invoice = setup_paid_group(
            building, rooms, client_name="Chess Camp",
            participant_specs=[("P One", "1990-01-01", "ATTENDEE"),
                               ("P Two", "1990-01-02", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            contracted_bed_count=2, deposit_paid_cents=20000,
            checkin_clock="2026-06-15T16:00:00Z",
            checkout_clock="2026-06-19T10:00:00Z",
            payment_clock="2026-06-19T12:00:00Z")
        assert invoice["total_cents"] == 36000 and invoice["status"] == "PAID"
        return building

    def test_ordered_waterfall_revenue_allocation(self, api):
        """PRD: "first overhead_cents is twelve percent of gross, rounded
        half-up; second reserve_cents is eight percent of gross-minus-overhead,
        rounded half-up — the reserve keys off the net-of-overhead remainder,
        never the gross; third ops_cents is whatever remains, the remainder
        bucket absorbing any rounding drift."

        Design: Difficulty/combinatorial_formula/ordered_waterfall_revenue_allocation
        """
        building = self._building_with_paid_invoice(api)
        run = validate_success(api.create_allocation_run(
            building["id"],
            create_allocation_run_payload(period_start="2026-06-01",
                                          period_end="2026-07-01"),
            FINANCE), expected_status=201)
        assert run["gross_cents"] == 36000, "the only PAID invoice in the period"
        assert run["overhead_cents"] == 4320, "round_half_up(36000 * 12%)"
        assert run["reserve_cents"] == 2534, \
            "round_half_up((36000 - 4320) * 8%) — keys off net-of-overhead, not gross"
        assert run["reserve_cents"] != 2880, "8% of gross would prove the wrong order"
        assert run["ops_cents"] == 29146, "remainder bucket absorbs the rounding drift"
        assert_allocation_buckets_sum_to_gross(run)

    def test_allocation_buckets_invariant_holds(self, api):
        """PRD: "The three buckets always sum to gross exactly."
        PRD: "The run's gross_cents is the sum of total_cents over PAID invoices
        of groups hosted by the building whose paid_at falls on or after
        period_start and strictly before period_end"

        Design: Difficulty/combinatorial_formula/ordered_waterfall_revenue_allocation
        """
        building = self._building_with_paid_invoice(api)
        run = get_success_data(api.create_allocation_run(
            building["id"],
            create_allocation_run_payload(period_start="2026-06-01",
                                          period_end="2026-07-01"),
            FINANCE))
        assert_allocation_buckets_sum_to_gross(run)
        assert run["status"] == "OPEN"
        # A period window that ends before the payment excludes the invoice.
        empty_run = get_success_data(api.create_allocation_run(
            building["id"],
            create_allocation_run_payload(period_start="2026-06-01",
                                          period_end="2026-06-19"),
            FINANCE))
        assert empty_run["gross_cents"] == 0, \
            "paid_at 2026-06-19T12:00:00Z is not strictly before period_end 2026-06-19"

    def test_allocation_empty_period_zero_buckets(self, api):
        """PRD: "The run's `gross_cents` is the sum of `total_cents` over `PAID`
        invoices of groups hosted by the building whose `paid_at` falls on or
        after `period_start` and strictly before `period_end`; an empty set
        yields zero."

        Design: Corner/calculations/allocation_empty_period_zero_buckets
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Otis Hall", key_pool_size=5), ADMIN))
        run = validate_success(api.create_allocation_run(
            building["id"],
            create_allocation_run_payload(period_start="2026-06-01",
                                          period_end="2026-09-01"),
            FINANCE), expected_status=201)
        assert run["gross_cents"] == 0
        assert run["overhead_cents"] == 0
        assert run["reserve_cents"] == 0
        assert run["ops_cents"] == 0
        assert run["status"] == "OPEN"
        assert_allocation_buckets_sum_to_gross(run)

    def test_allocation_lock_freezes_buckets(self, api):
        """PRD: "A run begins `OPEN`; locking it moves it to its terminal
        `LOCKED` state and freezes the bucket values."

        Design: Corner/endpoints/allocation_lock_freezes_buckets
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Mira Hall", key_pool_size=5), ADMIN))
        run = get_success_data(api.create_allocation_run(
            building["id"],
            create_allocation_run_payload(period_start="2026-06-01",
                                          period_end="2026-09-01"),
            FINANCE))
        locked = validate_success(api.lock_allocation_run(run["id"], FINANCE))
        assert locked["status"] == "LOCKED"
        validate_error(api.lock_allocation_run(run["id"], FINANCE),
                       ApiErrorId.ERR_INVALID_STATE)
