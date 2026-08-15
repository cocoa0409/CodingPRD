"""Line-speed governance: waiver lifecycle, half-open window overlap, clock-driven
activation/expiry, staffing bands, and speed clamping."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_waiver_payload,
    make_line, set_clock,
    setup_running_shift_with_run,
    make_usda_inspector_headers,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
OP = TEST_USERS["line_operator_headers"]
USDA = TEST_USERS["usda_inspector_headers"]


def _create_and_advance(api, line, max_speed_bpm, effective_from, effective_to,
                        submit=True, approve=True, inspector="usda-1"):
    waiver = get_success_data(api.create_waiver(
        line["id"], create_waiver_payload(
            line["version"], max_speed_bpm=max_speed_bpm,
            effective_from=effective_from, effective_to=effective_to), PM))
    if submit:
        get_success_data(api.advance_waiver(waiver["id"], {"to_status": "SUBMITTED"}, PM))
    if approve:
        waiver = get_success_data(api.advance_waiver(
            waiver["id"], {"to_status": "APPROVED"}, make_usda_inspector_headers(inspector)))
    line = get_success_data(api.get_line(line["id"], PM))
    return waiver, line


class TestWaiverWindows:

    def test_waiver_windows_half_open_adjacency(self, api):
        """PRD §3.1: "Two windows that merely touch, one ending exactly when the
        other begins, do not intersect and are allowed; a genuine overlap is
        rejected with `ERR_WAIVER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/waiver_windows_half_open_adjacency
        """
        line = make_line()
        wa, line = _create_and_advance(api, line, 195,
                                       "2026-08-01T06:00:00Z", "2026-08-01T14:00:00Z")
        # Adjacent window: B.from == A.to -> half-open, allowed
        wb = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=190,
                effective_from="2026-08-01T14:00:00Z",
                effective_to="2026-08-01T22:00:00Z"), PM))
        get_success_data(api.advance_waiver(wb["id"], {"to_status": "SUBMITTED"}, PM))
        wb = validate_success(api.advance_waiver(
            wb["id"], {"to_status": "APPROVED"}, make_usda_inspector_headers("usda-1")))
        assert wb["status"] in ("APPROVED", "ACTIVE")

        line = get_success_data(api.get_line(line["id"], PM))
        # Overlapping window C [13:00,15:00) intersects A [06:00,14:00)
        wc = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=192,
                effective_from="2026-08-01T13:00:00Z",
                effective_to="2026-08-01T15:00:00Z"), PM))
        get_success_data(api.advance_waiver(wc["id"], {"to_status": "SUBMITTED"}, PM))
        resp = api.advance_waiver(wc["id"], {"to_status": "APPROVED"},
                                  make_usda_inspector_headers("usda-1"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_WINDOW_OVERLAP)
        after = get_success_data(api.get_waiver(wc["id"], PM))
        assert after["status"] == "SUBMITTED"

    def test_waiver_approve_after_window_expired(self, api):
        """PRD §3.1: "advancing it to `APPROVED` is permitted only while the
        logical clock reads strictly earlier than the waiver's `effective_to` —
        an approval attempted at or after the window's end is rejected with
        `ERR_WAIVER_WINDOW_EXPIRED`".

        Design: Corner/validations/waiver_approve_after_window_expired
        """
        line = make_line()
        # Window entirely before the default logical clock 2026-08-01T00:00:00Z
        waiver = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=195,
                effective_from="2026-07-01T06:00:00Z",
                effective_to="2026-07-02T06:00:00Z"), PM))
        get_success_data(api.advance_waiver(waiver["id"], {"to_status": "SUBMITTED"}, PM))
        resp = api.advance_waiver(waiver["id"], {"to_status": "APPROVED"},
                                  make_usda_inspector_headers("usda-1"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_WINDOW_EXPIRED)
        after = get_success_data(api.get_waiver(waiver["id"], PM))
        assert after["status"] == "SUBMITTED"

    def test_waiver_auto_activates_and_expires_with_clock(self, api):
        """PRD §2.5: "Setting the clock is the trigger that evaluates every
        clock-driven system transition in the plant: line-speed waivers
        activate when the clock reaches their window and expire when it passes
        their window's end, and flock lots progress from on-line to chilled
        once their chill hold has elapsed."
        PRD §3.1: "An `APPROVED` waiver becomes `ACTIVE` by the system once the
        logical clock reaches `effective_from` while remaining earlier than
        `effective_to` (evaluated on clock-set and lazily on waiver and speed
        reads)".

        Design: Corner/state_machines/waiver_auto_activates_and_expires_with_clock
        """
        line = make_line()
        waiver = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=195,
                effective_from="2026-08-02T06:00:00Z",
                effective_to="2026-08-02T14:00:00Z"), PM))
        get_success_data(api.advance_waiver(waiver["id"], {"to_status": "SUBMITTED"}, PM))
        waiver = get_success_data(api.advance_waiver(
            waiver["id"], {"to_status": "APPROVED"}, make_usda_inspector_headers("usda-1")))
        assert waiver["status"] == "APPROVED"  # default clock is before the window

        set_clock("2026-08-02T07:00:00Z")
        w1 = get_success_data(api.get_waiver(waiver["id"], PM))
        assert w1["status"] == "ACTIVE"

        set_clock("2026-08-02T14:00:00Z")  # effective_to is exclusive
        w2 = get_success_data(api.get_waiver(waiver["id"], PM))
        assert w2["status"] == "EXPIRED"


class TestSpeedCeilings:

    def test_effective_speed_nested_min_waiver_staffing(self, api):
        """PRD §3.1: "when the ratio is at least 0.9 but below 1.0, the cap is
        the `rated_speed_bpm` multiplied by 0.9, again rounded down".
        PRD §3.1: "the effective maximum is the smallest of the line's rated
        speed, the regulatory cap, and the staffing cap."
        PRD §3.2: "A successful update increments the shift's `version` by one
        and immediately recomputes the effective speed ceiling (§3.1) for every
        `RUNNING` run of the shift; any run whose `current_speed_bpm` now
        exceeds its new ceiling is clamped down to it and flagged with
        `speed_clamped` set to true."

        Design: Difficulty/combinatorial_formula/effective_speed_nested_min_waiver_staffing
        """
        env = setup_running_shift_with_run(waiver_max_speed_bpm=195)
        rid, sid = env["run"]["id"], env["shift"]["id"]

        # Full staffing (ratio 1.0): min(200 rated, 195 waiver, 200 staffing) = 195
        sp = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 195}, OP))
        assert sp["current_speed_bpm"] == 195

        # Cut shacklers 10 -> 9: ratio exactly 0.9 -> staffing cap floor(200*0.9)=180
        shift = get_success_data(api.get_shift(sid, SUP))
        get_success_data(api.set_shift_staffing(
            sid, {"shacklers_present": 9, "eviscerators_present": 20,
                  "deboners_present": 12, "qa_techs_present": 2,
                  "expected_shift_version": shift["version"]}, SUP))
        run = get_success_data(api.get_line_run(rid, OP))
        assert run["current_speed_bpm"] == 180
        assert run["speed_clamped"] is True

    def test_staffing_speed_evaluation_order_pinned(self, api):
        """PRD §3.1: "when the ratio falls below 0.9, the cap collapses to the
        regulatory base cap for the line type and any waiver is void."
        PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."

        Design: Difficulty/combinatorial_formula/staffing_speed_evaluation_order_pinned
        """
        env = setup_running_shift_with_run(
            waiver_max_speed_bpm=195,
            staffing={"shacklers_present": 8, "eviscerators_present": 20,
                      "deboners_present": 12, "qa_techs_present": 2})
        rid = env["run"]["id"]
        # ratio 0.8 < 0.9 -> cap is the EVISCERATION base cap 175 despite the ACTIVE 195 waiver
        ok = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 175}, OP))
        assert ok["current_speed_bpm"] == 175
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 176}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)
        after = get_success_data(api.get_line_run(rid, OP))
        assert after["current_speed_bpm"] == 175

    def test_staffing_ratio_exactly_0_9_band(self, api):
        """PRD §3.1: "when the ratio is at least 0.9 but below 1.0, the cap is
        the `rated_speed_bpm` multiplied by 0.9, again rounded down".
        PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."

        Design: Difficulty/boundary_precision_check/staffing_ratio_exactly_0_9_band
        """
        env = setup_running_shift_with_run(
            waiver_max_speed_bpm=195,
            staffing={"shacklers_present": 9, "eviscerators_present": 20,
                      "deboners_present": 12, "qa_techs_present": 2})
        rid = env["run"]["id"]
        # 9/10 shacklers == ratio 0.9 exactly -> reduced band -> cap floor(200*0.9) = 180
        ok = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 180}, OP))
        assert ok["current_speed_bpm"] == 180
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 181}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)

    def test_waiver_revoke_clamps_running_speed(self, api):
        """PRD §3.1: "A `USDAInspector` may also advance an `APPROVED` or
        `ACTIVE` waiver to `REVOKED` with a `reason`; revocation of an `ACTIVE`
        waiver triggers the same recomputation, clamping `current_speed_bpm`
        down to the recomputed cap where needed and setting `speed_clamped` to
        true on each clamped run."
        PRD §3.1: "`EXPIRED`, `REVOKED`, and `SUPERSEDED` are terminal."

        Design: Corner/state_machines/waiver_revoke_clamps_running_speed
        """
        env = setup_running_shift_with_run(waiver_max_speed_bpm=195)
        rid = env["run"]["id"]
        get_success_data(api.set_line_run_speed(rid, {"new_speed_bpm": 195}, OP))
        # Find the line's ACTIVE waiver
        line = get_success_data(api.get_line(env["line"]["id"], PM))
        data = get_success_data(api.list_line_waivers(line["id"], PM))
        waivers = data if isinstance(data, list) else data.get("data", data)
        waiver = next(w for w in waivers if w["status"] in ("ACTIVE", "APPROVED"))

        revoked = validate_success(api.advance_waiver(
            waiver["id"], {"to_status": "REVOKED", "reason": "inspector observation"},
            make_usda_inspector_headers("usda-1")))
        assert revoked["status"] == "REVOKED"
        run = get_success_data(api.get_line_run(rid, OP))
        assert run["current_speed_bpm"] == 175  # base cap after revocation
        assert run["speed_clamped"] is True
