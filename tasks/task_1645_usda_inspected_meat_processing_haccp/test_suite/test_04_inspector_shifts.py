"""Inspector coverage shifts: overlap windows, check-in identity/window,
departure cascade."""
from test_helpers import (
    INSPECTOR_1,
    INSPECTOR_2,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_inspector_shift_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
PROD = TEST_USERS["production_manager_headers"]


class TestShiftOverlapWindow:
    def test_half_open_adjacency_overlap_and_per_inspector_scope(self, api):
        """PRD §3.3: "One inspector may not hold overlapping commitments: a new shift for the same `inspector_user_id` that overlaps an existing shift in `SCHEDULED` or `ON_PREMISE` status is rejected with `ERR_SHIFT_WINDOW_CONFLICT`."
        PRD §3.3: "Intervals are treated as half-open — a new shift whose start equals an existing shift's end (or vice versa) touches without overlapping and is allowed."

        Design: Difficulty/resource_temporal_overlap/inspector_shift_half_open_overlap_adjacency
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-O")
        shift_a = fixtures.schedule_shift(
            plant["id"], inspector_id=INSPECTOR_1,
            scheduled_start="2026-08-01T06:00:00Z",
            scheduled_end="2026-08-01T14:00:00Z",
        )
        assert shift_a["status"] == "SCHEDULED"

        # Adjacent: starts exactly at A's end — allowed (half-open).
        resp_b = api.create_inspector_shift(
            plant["id"],
            create_inspector_shift_payload(
                inspector_user_id=INSPECTOR_1,
                scheduled_start="2026-08-01T14:00:00Z",
                scheduled_end="2026-08-01T20:00:00Z",
            ),
            ADMIN,
        )
        shift_b = validate_success(resp_b, 201)
        assert shift_b["inspector_user_id"] == INSPECTOR_1

        # Overlapping A by one hour — rejected.
        resp_c = api.create_inspector_shift(
            plant["id"],
            create_inspector_shift_payload(
                inspector_user_id=INSPECTOR_1,
                scheduled_start="2026-08-01T13:00:00Z",
                scheduled_end="2026-08-01T15:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp_c, ApiErrorId.ERR_SHIFT_WINDOW_CONFLICT)
        assert resp_c.status_code == 422

        # Same window but a different inspector — the check is per inspector.
        resp_d = api.create_inspector_shift(
            plant["id"],
            create_inspector_shift_payload(
                inspector_user_id=INSPECTOR_2,
                scheduled_start="2026-08-01T13:00:00Z",
                scheduled_end="2026-08-01T15:00:00Z",
            ),
            ADMIN,
        )
        validate_success(resp_d, 201)

    def test_shift_ending_at_existing_start_is_allowed(self, api):
        """PRD §3.3: "Intervals are treated as half-open — a new shift whose start equals an existing shift's end (or vice versa) touches without overlapping and is allowed."

        Design: Difficulty/resource_temporal_overlap/inspector_shift_half_open_overlap_adjacency
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-O2")
        fixtures.schedule_shift(
            plant["id"], inspector_id=INSPECTOR_1,
            scheduled_start="2026-08-01T06:00:00Z",
            scheduled_end="2026-08-01T14:00:00Z",
        )

        # Ends exactly at the existing shift's start — the "(or vice versa)" leg.
        resp = api.create_inspector_shift(
            plant["id"],
            create_inspector_shift_payload(
                inspector_user_id=INSPECTOR_1,
                scheduled_start="2026-08-01T04:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            ),
            ADMIN,
        )
        validate_success(resp, 201)

        # Genuinely overlapping the front of the existing shift — rejected.
        resp2 = api.create_inspector_shift(
            plant["id"],
            create_inspector_shift_payload(
                inspector_user_id=INSPECTOR_1,
                scheduled_start="2026-08-01T05:00:00Z",
                scheduled_end="2026-08-01T07:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp2, ApiErrorId.ERR_SHIFT_WINDOW_CONFLICT)


class TestCheckInOutRules:
    def test_double_checkin_returns_shift_invalid_state(self, api):
        """PRD §3.3: "Among the check-in rules, identity is evaluated first (`ERR_CHECKIN_IDENTITY_MISMATCH` when `X-User-ID` does not match `inspector_user_id`), then the from-state (`ERR_SHIFT_INVALID_STATE` unless the shift is `SCHEDULED`), then the arrival window: check-in is accepted only when the logical clock reads within the inclusive window from fifteen minutes before `scheduled_start` through `scheduled_end`, and is otherwise rejected with `ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW`."

        Design: Corner/state_machines/shift_double_checkin_returns_shift_invalid_state
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-10")
        shift = fixtures.schedule_shift(plant["id"], inspector_id=INSPECTOR_1)
        fixtures.set_clock("2026-08-01T07:00:00Z")

        first = fixtures.check_in_shift(shift["id"], inspector_id=INSPECTOR_1)
        assert first["status"] == "ON_PREMISE"

        resp = api.check_in_shift(
            shift["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE)
        assert resp.status_code == 409

    def test_checkin_with_wrong_user_returns_identity_mismatch(self, api):
        """PRD §2.1: "One further identity rule applies specifically to inspector shift check-in and check-out: the presented `X-User-ID` must equal the shift's recorded `inspector_user_id`, otherwise the request fails with `ERR_CHECKIN_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/validations/checkin_with_wrong_user_returns_identity_mismatch
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-30")
        shift = fixtures.schedule_shift(plant["id"], inspector_id=INSPECTOR_1)
        fixtures.set_clock("2026-08-01T07:00:00Z")

        resp = api.check_in_shift(
            shift["id"], fixtures.make_inspector_headers(INSPECTOR_2)
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_IDENTITY_MISMATCH)
        assert resp.status_code == 403

        after = validate_success(api.get_inspector_shift(shift["id"], ADMIN), 200)
        assert after["status"] == "SCHEDULED"

    def test_checkin_window_boundary_grace_and_outside(self, api):
        """PRD §3.3: "check-in is accepted only when the logical clock reads within the inclusive window from fifteen minutes before `scheduled_start` through `scheduled_end`, and is otherwise rejected with `ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW`."

        Design: Corner/validations/checkin_window_boundary_grace_and_outside
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-31")
        shift = fixtures.schedule_shift(plant["id"], inspector_id=INSPECTOR_1)

        # 04:00 is more than fifteen minutes before the 06:00 start.
        fixtures.set_clock("2026-08-01T04:00:00Z")
        resp = api.check_in_shift(
            shift["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW)
        assert resp.status_code == 422

        # 05:45 is exactly fifteen minutes before the start: inclusive, allowed.
        fixtures.set_clock("2026-08-01T05:45:00Z")
        ok = validate_success(
            api.check_in_shift(
                shift["id"], fixtures.make_inspector_headers(INSPECTOR_1)
            ),
            200,
        )
        assert ok["status"] == "ON_PREMISE"
        assert_instant_equals(ok["checked_in_at"], "2026-08-01T05:45:00Z")


class TestCheckOutCascade:
    def test_checkout_last_inspector_suspends_open_day(self, api):
        """PRD §3.3: "Check-out mirrors the identity and state rules (`ON_PREMISE` required), stamps `checked_out_at`, moves the shift to `DEPARTED`, and then fires the conditional cascade of §2.8: if no other shift of the plant remains `ON_PREMISE`, every `OPEN` production day of that plant is suspended."

        Design: Corner/state_machines/checkout_last_inspector_suspends_open_day
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-11")

        resp = api.check_out_shift(
            env["shift"]["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        shift = validate_success(resp, 200)
        assert shift["status"] == "DEPARTED"
        assert shift.get("checked_out_at"), "check-out must stamp checked_out_at"

        day = validate_success(api.get_production_day(env["day"]["id"], PROD), 200)
        assert day["status"] == "SUSPENDED", (
            "with no ON_PREMISE shift remaining, the OPEN day must suspend"
        )

    def test_checkout_with_second_inspector_present_keeps_day_open(self, api):
        """PRD §2.8: "when an inspector checks out and no other shift of the same plant remains `ON_PREMISE`, every `OPEN` production day of the plant transitions to `SUSPENDED`."

        Design: Corner/state_machines/checkout_with_second_inspector_present_keeps_day_open
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-12")
        # A second inspector is also on premise for the same plant.
        shift_b = fixtures.schedule_shift(env["plant"]["id"], inspector_id=INSPECTOR_2)
        fixtures.check_in_shift(shift_b["id"], inspector_id=INSPECTOR_2)

        resp = api.check_out_shift(
            env["shift"]["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        shift = validate_success(resp, 200)
        assert shift["status"] == "DEPARTED"

        day = validate_success(api.get_production_day(env["day"]["id"], PROD), 200)
        assert day["status"] == "OPEN", (
            "insp-02 is still ON_PREMISE, so the departure cascade must not fire"
        )
