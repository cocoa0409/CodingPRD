"""Desk staffing: shift windows, rest buffer, overlap, desk capacity,
desk auto-selection, and the desk quota invariant (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_desk_quota_invariants,
    create_desk_payload,
    create_desk_shift_payload,
    create_dispatcher_payload,
    make_dispatcher_headers,
    setup_reference_data,
    add_leg,
    add_second_leg,
    set_clock,
    validate_error,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


def _make_dispatcher(name, license_no):
    return validate_success(
        api_client.create_dispatcher(
            create_dispatcher_payload(name=name, license_no=license_no), SUP
        ),
        201,
    )


def _make_desk(code, max_dispatchers=2):
    return validate_success(
        api_client.create_desk(
            create_desk_payload(code=code, max_dispatchers=max_dispatchers), SUP
        ),
        201,
    )


class TestShiftRestBuffer:
    def test_shift_rest_buffer_rejects_adjacency(self, api):
        """PRD §3.1: "Two shifts of the same dispatcher whose half-open windows
        intersect are rejected with `ERR_SHIFT_OVERLAP`, and two non-overlapping
        shifts of the same dispatcher separated by less than a thirty-minute
        rest buffer are rejected with `ERR_REST_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_rejects_adjacency
        """
        d5 = _make_dispatcher("Dana Five", "D005")
        k5 = _make_desk("K5")
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(d5["id"], desk_id=k5["id"]),
                                  SUP),
            201,
        )
        # Back-to-back: gap 0 < 30 minutes.
        res = api.create_desk_shift(
            create_desk_shift_payload(
                d5["id"], desk_id=k5["id"],
                shift_start_utc="2026-05-01T14:00:00Z",
                shift_end_utc="2026-05-01T22:00:00Z",
            ),
            SUP,
        )
        validate_error(res, ApiErrorId.ERR_REST_VIOLATION.value)

    def test_shift_rest_buffer_exactly_thirty_minutes_accepted(self, api):
        """PRD §3.1: "two non-overlapping shifts of the same dispatcher
        separated by less than a thirty-minute rest buffer are rejected with
        `ERR_REST_VIOLATION`" — a separation of exactly thirty minutes is not
        less than the buffer, so the create is accepted.

        Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_rejects_adjacency
        """
        d5 = _make_dispatcher("Dana Five", "D005")
        k5 = _make_desk("K5")
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(d5["id"], desk_id=k5["id"]),
                                  SUP),
            201,
        )
        res = api.create_desk_shift(
            create_desk_shift_payload(
                d5["id"], desk_id=k5["id"],
                shift_start_utc="2026-05-01T14:30:00Z",
                shift_end_utc="2026-05-01T22:00:00Z",
            ),
            SUP,
        )
        created = validate_success(res, 201)
        assert created["dispatcher_id"] == d5["id"]
        assert created["desk_id"] == k5["id"]


class TestShiftOverlap:
    def test_shift_overlap_rejected(self, api):
        """PRD §3.1: "Two shifts of the same dispatcher whose half-open windows
        intersect are rejected with `ERR_SHIFT_OVERLAP`"

        Design: Corner/validations/shift_overlap_rejected
        """
        d5 = _make_dispatcher("Dana Five", "D005")
        k5 = _make_desk("K5")
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(d5["id"], desk_id=k5["id"]),
                                  SUP),
            201,
        )
        res = api.create_desk_shift(
            create_desk_shift_payload(
                d5["id"], desk_id=k5["id"],
                shift_start_utc="2026-05-01T13:00:00Z",
                shift_end_utc="2026-05-01T15:00:00Z",
            ),
            SUP,
        )
        validate_error(res, ApiErrorId.ERR_SHIFT_OVERLAP.value)


class TestDeskOverload:
    def test_desk_overloaded_rejected(self, api):
        """PRD §3.1: "Desk capacity is enforced at every covered instant: if
        accepting the shift would make the number of concurrent shifts at the
        desk exceed `max_dispatchers` at any moment of the window, the create is
        rejected with `ERR_DESK_OVERLOADED`."

        Design: Corner/validations/desk_overloaded_rejected
        """
        da = _make_dispatcher("Dana A", "D00A")
        db = _make_dispatcher("Dana B", "D00B")
        kt = _make_desk("KT", max_dispatchers=1)
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(da["id"], desk_id=kt["id"]),
                                  SUP),
            201,
        )
        res = api.create_desk_shift(
            create_desk_shift_payload(
                db["id"], desk_id=kt["id"],
                shift_start_utc="2026-05-01T08:00:00Z",
                shift_end_utc="2026-05-01T12:00:00Z",
            ),
            SUP,
        )
        validate_error(res, ApiErrorId.ERR_DESK_OVERLOADED.value)


class TestDeskQuotaInvariant:
    def test_desk_quota_conserved_while_shift_active(self, api):
        """PRD §3.1: "Reading a desk reports the computed `active_shift_count` —
        the number of shift rows whose window covers the current logical clock
        under half-open semantics (start inclusive, end exclusive) — and
        `free_slots`, which is `max_dispatchers` minus `active_shift_count`."

        Design: Difficulty/compensating_invariant/desk_quota_conserved_across_shift_lifecycle
        """
        d6 = _make_dispatcher("Dana Six", "D006")
        ka = _make_desk("KA", max_dispatchers=1)
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(d6["id"], desk_id=ka["id"]),
                                  SUP),
            201,
        )
        validate_success(api.set_clock("2026-05-01T10:00:00Z", SUP), 200)
        desk = validate_success(api.get_desk(ka["id"], SUP), 200)
        assert desk["active_shift_count"] == 1
        assert desk["free_slots"] == 0
        assert_desk_quota_invariants(desk)

    def test_desk_quota_conserved_after_shift_ends(self, api):
        """PRD §3.1: "`free_slots`, which is `max_dispatchers` minus
        `active_shift_count`" — once the clock passes the shift's exclusive end,
        occupancy returns to zero and the conserved sum equals max_dispatchers.

        Design: Difficulty/compensating_invariant/desk_quota_conserved_across_shift_lifecycle
        """
        d6 = _make_dispatcher("Dana Six", "D006")
        ka = _make_desk("KA", max_dispatchers=1)
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(d6["id"], desk_id=ka["id"]),
                                  SUP),
            201,
        )
        validate_success(api.set_clock("2026-05-01T15:00:00Z", SUP), 200)
        desk = validate_success(api.get_desk(ka["id"], SUP), 200)
        assert desk["active_shift_count"] == 0
        assert desk["free_slots"] == 1
        assert_desk_quota_invariants(desk)


class TestDeskAutoSelect:
    def test_selector_desk_auto_assign_lowest_load(self, api):
        """PRD §3.1: "When `desk_id` is omitted, the server selects the desk
        itself: every desk whose `active_shift_count` is strictly below its
        `max_dispatchers` is eligible; eligible desks are ranked by the sum of
        the `weighted_load_score` values of the dispatchers currently holding an
        active shift there, ascending (an empty desk scores 0); ties break by
        desk `created_at` ascending, never by id."

        Design: Corner/complexity_layers/selector_desk_auto_assign_lowest_load
        """
        ctx = setup_reference_data(with_alternate=False,
                                   dispatcher_overrides={"name": "Dana A",
                                                         "license_no": "D00A"})
        da = ctx["dispatcher"]
        # Two legs for D_A: dep +1h (tier 3) and dep +10h (tier 1) from the
        # 08:00 clock -> weighted_load_score 4.
        add_leg(ctx, flight_no="FD840", distance_nm=400,
                sched_dep_utc="2026-05-01T09:00:00Z",
                sched_arr_utc="2026-05-01T10:00:00Z")
        add_second_leg(ctx, flight_no="FD841", distance_nm=400,
                       sched_dep_utc="2026-05-01T18:00:00Z",
                       sched_arr_utc="2026-05-01T19:00:00Z")
        ka = _make_desk("KA", max_dispatchers=2)
        kb = _make_desk("KB", max_dispatchers=2)
        validate_success(
            api.create_desk_shift(create_desk_shift_payload(da["id"], desk_id=ka["id"]),
                                  SUP),
            201,
        )
        dn = _make_dispatcher("Dana N", "D00N")
        set_clock(ctx, "2026-05-01T08:00:00Z")

        res = api.create_desk_shift(
            create_desk_shift_payload(
                dn["id"],
                shift_start_utc="2026-05-01T07:00:00Z",
                shift_end_utc="2026-05-01T12:00:00Z",
            ),
            SUP,
        )
        shift = validate_success(res, 201)
        assert shift["desk_id"] == kb["id"], (
            "empty desk (load 0) must beat the desk holding D_A's active shift "
            f"(load 4); got desk_id {shift['desk_id']}"
        )


class TestWindowInvalid:
    def test_window_invalid_rejected(self, api):
        """PRD §3.1: "The window must be well-formed — the end strictly after
        the start — or the request is rejected with `ERR_WINDOW_INVALID`."
        PRD §3.7: "The window must be well-formed — `valid_to_utc` strictly
        after `valid_from_utc` — or the publish is rejected with
        `ERR_WINDOW_INVALID`."

        Design: Corner/validations/window_invalid_rejected
        """
        from test_helpers import create_station_payload, create_weather_package_payload

        stw = validate_success(
            api.create_station(
                create_station_payload(iata_code="KWTH", alternate_distance_nm=50), SUP
            ),
            201,
        )
        d5 = _make_dispatcher("Dana Five", "D005")
        k5 = _make_desk("K5")

        wx_res = api.create_weather_package(
            create_weather_package_payload(
                stw["id"],
                valid_from_utc="2026-05-01T09:00:00Z",
                valid_to_utc="2026-05-01T09:00:00Z",
            ),
            SUP,
        )
        validate_error(wx_res, ApiErrorId.ERR_WINDOW_INVALID.value)

        shift_res = api.create_desk_shift(
            create_desk_shift_payload(
                d5["id"], desk_id=k5["id"],
                shift_start_utc="2026-05-01T14:00:00Z",
                shift_end_utc="2026-05-01T06:00:00Z",
            ),
            SUP,
        )
        validate_error(shift_res, ApiErrorId.ERR_WINDOW_INVALID.value)
