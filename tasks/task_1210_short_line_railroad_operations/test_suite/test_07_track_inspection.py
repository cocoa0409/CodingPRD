"""Track inspection day-spacing, defect filing and speed caps, the overdue sweep
boundary, and the CRITICAL-defect cascade into movements and crew calls
(PRD §2.10, §3.4, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_call,
    create_crew_call_for_movement,
    create_crew_member,
    create_inspection,
    create_movement,
    create_segment,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]
INSPECTOR = TEST_USERS["track_inspector_headers"]


def _critical_defect_setup():
    """CLASS_3 segment + PLANNED movement + a CALLED crew call + scheduled inspection."""
    segment = create_segment(name="Main MP 20-26", milepost_start=20, milepost_end=26, fra_class="CLASS_3")
    movement = create_movement([segment["id"]], symbol="GW-301")
    member = create_crew_member(name="D. Engineer", craft="ENGINEER")
    call = create_crew_call_for_movement(
        member["id"], movement["id"], start="2026-05-02T06:00:00Z", end="2026-05-02T18:00:00Z"
    )
    inspection = create_inspection(segment["id"], scheduled_date="2026-05-01")
    return segment, movement, member, call, inspection


class TestInspectionDateSpacing:
    def test_inspection_next_day_rejected(self, api, track_inspector_headers):
        """PRD §3.6: "Two inspections on the same segment must be separated by at
        least one full day: a new inspection whose date falls less than two days
        from an existing inspection on that segment is rejected with
        `ERR_INSPECTION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/inspection_closed_day_buffer_overlap
        """
        segment = create_segment(name="Branch MP 2-6", milepost_start=2, milepost_end=6, fra_class="CLASS_2")
        create_inspection(segment["id"], scheduled_date="2026-05-10")
        resp = api.create_track_inspection(
            {"segment_id": segment["id"], "scheduled_date": "2026-05-11"}, track_inspector_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_OVERLAP)

    def test_inspection_two_days_later_allowed(self, api, track_inspector_headers):
        """PRD §3.6: "Two inspections on the same segment must be separated by at
        least one full day: a new inspection whose date falls less than two days
        from an existing inspection on that segment is rejected with
        `ERR_INSPECTION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/inspection_closed_day_buffer_overlap
        """
        segment = create_segment(name="Branch MP 2-6", milepost_start=2, milepost_end=6, fra_class="CLASS_2")
        create_inspection(segment["id"], scheduled_date="2026-05-10")
        resp = api.create_track_inspection(
            {"segment_id": segment["id"], "scheduled_date": "2026-05-12"}, track_inspector_headers
        )
        inspection = validate_success(resp, expected_status=201)
        assert inspection["status"] == "SCHEDULED", (
            f"a date exactly two days out satisfies the full-day gap, got {inspection['status']}"
        )


class TestCriticalDefectCascade:
    def test_critical_defect_restricts_segment_and_caps_speed(self, api, system_admin_headers, track_inspector_headers):
        """PRD §3.6: "When the inspector files with `defect_found` true, a
        `defect_severity` of `MONITOR` or `CRITICAL` is required, the inspector's
        narrative is recorded in `findings`, and the inspection becomes
        `DEFECT_FILED`: the segment's `defect_open` goes true,
        `open_defect_severity` takes the filed severity, and `effective_speed_mph`
        is recomputed under the defect cap. A `CRITICAL` filing additionally
        forces the segment from `IN_SERVICE` to `RESTRICTED`, triggering the
        movement cascade of §2.10 and §3.4 — planned and ready movements over the
        segment annulled, their called and accepted crew calls expired, departed
        movements held."
        PRD §3.6: "the lesser of that base and the defect cap, which is 25 mph for
        a `MONITOR` defect and 10 mph for a `CRITICAL` one."

        Design: Difficulty/transitive_cascade/critical_defect_cascade_depth4
        """
        segment, movement, member, call, inspection = _critical_defect_setup()
        filed = validate_success(
            api.file_track_inspection(
                inspection["id"],
                {"defect_found": True, "defect_severity": "CRITICAL", "findings": "crushed rail head at MP 23.2"},
                track_inspector_headers,
            )
        )
        assert filed["status"] == "DEFECT_FILED", f"filing a defect must stand DEFECT_FILED, got {filed['status']}"

        seg = validate_success(api.get_track_segment(segment["id"], system_admin_headers))
        assert seg["status"] == "RESTRICTED", f"CRITICAL defect must restrict the segment, got {seg['status']}"
        assert seg["defect_open"] is True
        assert seg["open_defect_severity"] == "CRITICAL"
        assert seg["effective_speed_mph"] == 10, (
            f"min(CLASS_3 base 40, CRITICAL cap 10) must yield 10, got {seg['effective_speed_mph']}"
        )

    def test_critical_defect_annuls_movement_and_expires_call(self, api, dispatcher_headers, track_inspector_headers):
        """PRD §2.10: "When a track segment passes from `IN_SERVICE` to
        `RESTRICTED`, planned and ready movements routed over it are annulled,
        departed movements routed over it are held, and the crew calls attached to
        an annulled movement expire."
        PRD §3.4: "Annulment is never a client action. When a route segment passes
        from `IN_SERVICE` to `RESTRICTED` — whether because a `CRITICAL` defect
        was filed or because the overdue sweep restricted it — every movement in
        `PLANNED` or `READY` routed over that segment is annulled, and every such
        movement's crew calls in `CALLED` or `ACCEPTED` expire, moving to
        `EXPIRED`."

        Design: Difficulty/transitive_cascade/critical_defect_cascade_depth4
        """
        segment, movement, member, call, inspection = _critical_defect_setup()
        validate_success(
            api.file_track_inspection(
                inspection["id"],
                {"defect_found": True, "defect_severity": "CRITICAL", "findings": "crushed rail head at MP 23.2"},
                track_inspector_headers,
            )
        )

        mov = validate_success(api.get_train_movement(movement["id"], dispatcher_headers))
        assert mov["status"] == "ANNULLED", (
            f"the PLANNED movement over the restricted segment must be annulled, got {mov['status']}"
        )
        call_now = validate_success(api.get_crew_call(call["id"], CALLER))
        assert call_now["status"] == "EXPIRED", (
            f"the annulled movement's CALLED crew call must expire, got {call_now['status']}"
        )


class TestDefectSpeedCap:
    def test_effective_speed_monitor_defect_cap(self, api, system_admin_headers, track_inspector_headers):
        """PRD §3.6: "Each segment carries a computed `effective_speed_mph`: the
        base speed for its class — 10 mph for `EXCEPTED`, 10 for `CLASS_1`, 25 for
        `CLASS_2`, 40 for `CLASS_3`, 60 for `CLASS_4`, and 80 for `CLASS_5` — and,
        while a defect is open on the segment, the lesser of that base and the
        defect cap, which is 25 mph for a `MONITOR` defect and 10 mph for a
        `CRITICAL` one."
        PRD §3.6: "A `CRITICAL` filing additionally forces the segment from
        `IN_SERVICE` to `RESTRICTED`, triggering the movement cascade of §2.10 and
        §3.4 — planned and ready movements over the segment annulled, their called
        and accepted crew calls expired, departed movements held."

        Design: Corner/calculations/effective_speed_monitor_defect_cap
        """
        segment = create_segment(name="Main MP 29-34", milepost_start=29, milepost_end=34, fra_class="CLASS_4")
        inspection = create_inspection(segment["id"], scheduled_date="2026-05-01")
        validate_success(
            api.file_track_inspection(
                inspection["id"],
                {"defect_found": True, "defect_severity": "MONITOR", "findings": "surface wear"},
                track_inspector_headers,
            )
        )
        seg = validate_success(api.get_track_segment(segment["id"], system_admin_headers))
        assert seg["effective_speed_mph"] == 25, (
            f"min(CLASS_4 base 60, MONITOR cap 25) must yield 25, got {seg['effective_speed_mph']}"
        )
        assert seg["status"] == "IN_SERVICE", (
            f"only CRITICAL restricts; a MONITOR defect must leave IN_SERVICE, got {seg['status']}"
        )
        assert seg["defect_open"] is True


class TestOverdueSweep:
    def test_inspection_overdue_boundary_seconds(self, api, system_admin_headers):
        """PRD §3.6: "A segment's inspection deadline is its `last_inspection_at`
        plus the frequency for its class: 30 days for `EXCEPTED`, 7 days for
        `CLASS_1`, 7 days for `CLASS_2`, 3 days for `CLASS_3`, 2 days for
        `CLASS_4`, and 1 day for `CLASS_5`. The segment is overdue when the clock
        is strictly later than the deadline — a clock reading exactly at the
        deadline is not overdue, and the comparison is made to the second. An
        overdue segment has `is_overdue` set, and if it is still `IN_SERVICE` it
        moves to `RESTRICTED` with the same movement cascade as a critical
        defect."

        Design: Corner/calculations/inspection_overdue_boundary_seconds
        """
        segment = create_segment(name="Main MP 25-28", milepost_start=25, milepost_end=28, fra_class="CLASS_3")

        set_clock("2026-05-04T00:00:00Z")  # exactly last_inspection_at + 3 days
        at_deadline = validate_success(api.get_track_segment(segment["id"], system_admin_headers))
        assert at_deadline["is_overdue"] is False, "a clock reading exactly at the deadline is not overdue"
        assert at_deadline["status"] == "IN_SERVICE", (
            f"at the exact deadline the segment must stay IN_SERVICE, got {at_deadline['status']}"
        )

        set_clock("2026-05-04T00:00:01Z")  # one second strictly past the deadline
        past = validate_success(api.get_track_segment(segment["id"], system_admin_headers))
        assert past["is_overdue"] is True, "one second past the deadline the segment is overdue"
        assert past["status"] == "RESTRICTED", (
            f"the overdue sweep must restrict the segment, got {past['status']}"
        )


class TestDefectCascadeConditional:
    def test_defect_cascade_holds_departed_movement(self, api, dispatcher_headers, track_inspector_headers):
        """PRD §3.4: "Annulment is never a client action. When a route segment
        passes from `IN_SERVICE` to `RESTRICTED` — whether because a `CRITICAL`
        defect was filed or because the overdue sweep restricted it — every
        movement in `PLANNED` or `READY` routed over that segment is annulled, and
        every such movement's crew calls in `CALLED` or `ACCEPTED` expire, moving
        to `EXPIRED`. A `DEPARTED` movement routed over the newly restricted
        segment is instead held."

        Design: Corner/state_machines/defect_cascade_holds_departed_movement
        """
        segment = create_segment(name="Main MP 12-16", milepost_start=12, milepost_end=16, fra_class="CLASS_3")
        member = create_crew_member(name="M. Engineer", craft="ENGINEER")
        movement = create_movement([segment["id"]], symbol="GW-902")
        call = create_crew_call_for_movement(member["id"], movement["id"])
        call = accept_call(call["id"], member["id"])
        validate_success(api.ready_train_movement(movement["id"], DISPATCH))
        validate_success(api.depart_train_movement(movement["id"], DISPATCH))

        inspection = create_inspection(segment["id"], scheduled_date="2026-05-02")
        validate_success(
            api.file_track_inspection(
                inspection["id"],
                {"defect_found": True, "defect_severity": "CRITICAL", "findings": "broken joint bar"},
                track_inspector_headers,
            )
        )

        mov = validate_success(api.get_train_movement(movement["id"], dispatcher_headers))
        assert mov["status"] == "HELD", (
            f"a DEPARTED movement over the restricted segment is held, not annulled, got {mov['status']}"
        )
        seg = validate_success(api.get_track_segment(segment["id"], dispatcher_headers))
        assert seg["status"] == "RESTRICTED"
        call_now = validate_success(api.get_crew_call(call["id"], CALLER))
        assert call_now["status"] == "ACCEPTED", (
            f"call expiry only fires for calls of ANNULLED movements; the HELD movement's call "
            f"must persist, got {call_now['status']}"
        )
