"""Degreening rooms and sessions: aggregate-capacity overlap semantics,
exact-fit boundary, duration bounds with the QualityInspector override,
variety-driven degreening requirement, and room maintenance gates."""
from test_helpers import (
    ApiErrorId,
    create_delivery_payload,
    create_session_payload,
    get_delivery,
    get_session,
    get_success_data,
    juice_spec,
    set_clock,
    setup_delivery_received,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import create_room
from test_helpers.test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _receive_deliveries(scenario, gross_list):
    deliveries = []
    for gross in gross_list:
        deliveries.append(get_success_data(api_client.create_delivery(
            create_delivery_payload(scenario["grove"]["id"],
                                    scenario["assignment"]["id"],
                                    gross, 0), SUPERVISOR)))
    return deliveries


class TestDegreeningCapacityExactFit:
    def test_exact_fit_at_capacity_accepted(self, api):
        """PRD §3.4: "the new session is rejected if and only if there exists
        some instant within its reserved interval at which the boxes of all
        still-`CONDITIONING` sessions whose reserved intervals cover that
        instant, plus the new session's `boxes`, would exceed the room's
        `capacity_boxes`; equality at every instant is permitted".

        Design: Difficulty/boundary_precision_check/degreening_capacity_exact_fit
        """
        scenario = setup_delivery_received("DC1", gross_boxes=60, planned_boxes=200)
        room = create_room("RM-DC1", capacity_boxes=100, min_hours=12, max_hours=72)
        d1 = scenario["delivery"]
        d2, d3 = _receive_deliveries(scenario, [40, 1])
        s1 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d1["id"], 60, planned_hours=24),
            make_operator_headers("op-dc1")), expected_status=201)
        s2 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d2["id"], 40, planned_hours=24),
            make_operator_headers("op-dc1")), expected_status=201)
        assert s1["status"] == "CONDITIONING" and s2["status"] == "CONDITIONING"
        # 60 + 40 == 100 == capacity: the exact fit is permitted.
        assert get_delivery(d1["id"])["processing_status"] == "IN_DEGREENING"
        assert get_delivery(d2["id"])["processing_status"] == "IN_DEGREENING"
        assert get_delivery(d3["id"])["processing_status"] == "RECEIVED"

    def test_one_box_over_capacity_rejected(self, api):
        """PRD §3.4: the aggregate rule above plus "the room's aggregate
        capacity may never be exceeded (`ERR_ROOM_CAPACITY_EXCEEDED`)" — a
        third overlapping session pushing the instant sum to 101 of 100 is
        refused.

        Design: Difficulty/boundary_precision_check/degreening_capacity_exact_fit
        """
        scenario = setup_delivery_received("DC1B", gross_boxes=60, planned_boxes=200)
        room = create_room("RM-DC1B", capacity_boxes=100, min_hours=12, max_hours=72)
        d1 = scenario["delivery"]
        d2, d3 = _receive_deliveries(scenario, [40, 1])
        validate_success(api_client.create_session(
            create_session_payload(room["id"], d1["id"], 60, planned_hours=24),
            make_operator_headers("op-dc1")), expected_status=201)
        validate_success(api_client.create_session(
            create_session_payload(room["id"], d2["id"], 40, planned_hours=24),
            make_operator_headers("op-dc1")), expected_status=201)
        resp = api_client.create_session(
            create_session_payload(room["id"], d3["id"], 1, planned_hours=24),
            make_operator_headers("op-dc1"))
        validate_error(resp, ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED)
        assert get_delivery(d3["id"])["processing_status"] == "RECEIVED", \
            "the rejected session never moves its delivery"


class TestRoomAggregateOverlapSemantics:
    def test_overlapping_sessions_within_aggregate_capacity(self, api):
        """PRD §3.4: "The capacity check has aggregate semantics, unlike the
        crew's exclusive occupancy" — sessions whose reservations all cover
        the same instants coexist while their box sum stays within capacity.

        Design: Difficulty/resource_temporal_overlap/room_aggregate_capacity_overlap
        """
        scenario = setup_delivery_received(
            "OV2", gross_boxes=30, planned_boxes=200,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-02T12:00:00Z")
        room = create_room("RM-OV2", capacity_boxes=100, min_hours=12, max_hours=72)
        d1 = scenario["delivery"]
        d2, d3, d4 = _receive_deliveries(scenario, [50, 20, 20])
        s1 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d1["id"], 30, planned_hours=48),
            make_operator_headers("op-ov2")), expected_status=201)
        s2 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d2["id"], 50, planned_hours=24),
            make_operator_headers("op-ov2")), expected_status=201)
        s3 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d3["id"], 20, planned_hours=12),
            make_operator_headers("op-ov2")), expected_status=201)
        for sid in (s1["id"], s2["id"], s3["id"]):
            assert get_session(sid)["status"] == "CONDITIONING"
        # 30 + 50 + 20 == 100 at every shared instant: all three coexist.

    def test_expired_reservation_frees_aggregate_capacity(self, api):
        """PRD §3.4: a session "reserves the half-open interval from
        `started_at` through `started_at` plus `planned_hours`" — after a
        reservation's interval expires it no longer occupies, so a new session
        summing to exactly capacity is accepted ("equality at every instant is
        permitted").

        Design: Difficulty/resource_temporal_overlap/room_aggregate_capacity_overlap
        """
        scenario = setup_delivery_received(
            "OV2B", gross_boxes=30, planned_boxes=200,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-02T12:00:00Z")
        room = create_room("RM-OV2B", capacity_boxes=100, min_hours=12, max_hours=72)
        d1 = scenario["delivery"]
        d2, d3, d4 = _receive_deliveries(scenario, [50, 20, 20])
        s1 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d1["id"], 30, planned_hours=48),
            make_operator_headers("op-ov2")), expected_status=201)
        s2 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d2["id"], 50, planned_hours=24),
            make_operator_headers("op-ov2")), expected_status=201)
        s3 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d3["id"], 20, planned_hours=12),
            make_operator_headers("op-ov2")), expected_status=201)
        # At 13:00 the 12h reservation of s3 ([00:00, 12:00)) has expired, so
        # occupying boxes are 30 + 50 = 80 and a 20-box session fits exactly.
        set_clock("2026-08-01T13:00:00Z")
        s4 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d4["id"], 20, planned_hours=12),
            make_operator_headers("op-ov2")), expected_status=201)
        for sid in (s1["id"], s2["id"], s3["id"], s4["id"]):
            assert get_session(sid)["status"] == "CONDITIONING", \
                "release is a separate explicit transition; all four remain CONDITIONING"


class TestDurationBoundsAndOverride:
    def test_degreening_duration_bounds_and_override(self, api):
        """PRD §3.4: "The duration must lie within the room's `min_hours` to
        `max_hours`, both bounds inclusive, unless a `QualityInspector`
        supplies the override; an out-of-bounds release without it fails with
        `ERR_DEGREENING_DURATION_OUT_OF_BOUNDS`." PRD §3.4: "A `LineOperator`
        may release within bounds; a `QualityInspector` may release with
        `override_approved` set true to override the duration bounds." PRD
        §3.4: "When the released plus aborted boxes of a delivery reach its
        `net_boxes`, the delivery's processing advances `IN_DEGREENING` →
        `READY_TO_SORT` with a version bump."

        Design: Corner/errors/degreening_duration_bounds_and_override
        """
        scenario = setup_delivery_received("ER4", gross_boxes=40, planned_boxes=100)
        room = create_room("RM-ER4", capacity_boxes=100, min_hours=12, max_hours=72)
        d1 = scenario["delivery"]
        (d2,) = _receive_deliveries(scenario, [40])
        s1 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d1["id"], 40, planned_hours=12),
            make_operator_headers("op-er4")), expected_status=201)
        s2 = validate_success(api_client.create_session(
            create_session_payload(room["id"], d2["id"], 40, planned_hours=80),
            make_operator_headers("op-er4")), expected_status=201)
        # At 11h (< min 12): rejected.
        set_clock("2026-08-01T11:00:00Z")
        resp = api_client.release_session(s1["id"], {}, make_operator_headers("op-er4"))
        validate_error(resp, ApiErrorId.ERR_DEGREENING_DURATION_OUT_OF_BOUNDS)
        # At exactly 12h (inclusive minimum): released with duration 12.0.
        set_clock("2026-08-01T12:00:00Z")
        released = validate_success(api_client.release_session(
            s1["id"], {}, make_operator_headers("op-er4")))
        assert released["status"] == "RELEASED"
        assert released["duration_hours"] == 12.0
        assert get_delivery(d1["id"])["processing_status"] == "READY_TO_SORT"
        # At 73h (> max 72): the override flag does not help a LineOperator.
        set_clock("2026-08-04T01:00:00Z")
        resp = api_client.release_session(
            s2["id"], {"override_approved": True}, make_operator_headers("op-er4"))
        validate_error(resp, ApiErrorId.ERR_DEGREENING_DURATION_OUT_OF_BOUNDS)
        # A QualityInspector with override_approved true releases at 73h.
        overridden = validate_success(api_client.release_session(
            s2["id"], {"override_approved": True},
            make_inspector_headers("qi-er4")))
        assert overridden["status"] == "RELEASED"
        assert overridden["duration_hours"] == 73.0
        assert get_delivery(d2["id"])["processing_status"] == "READY_TO_SORT"


class TestDegreeningRequiredVariety:
    def test_degreening_required_variety_gate(self, api):
        """PRD §3.5: "if the delivery's variety requires degreening and the
        delivery is still sitting in `RECEIVED`, the run is refused with
        `ERR_DEGREENING_REQUIRED`." PRD §3.3: "its `requires_degreening` flag
        is derived from the variety: true for `RED_GRAPEFRUIT` and
        `TANGERINE`, false for `HAMLIN` and `VALENCIA`."

        Design: Corner/errors/degreening_required_variety_gate
        """
        scenario = setup_delivery_received(
            "ER5", variety="RED_GRAPEFRUIT", gross_boxes=30, planned_boxes=50,
            channel_specs=[juice_spec("JU-ER5", "RED_GRAPEFRUIT")])
        delivery = scenario["delivery"]
        assert delivery["requires_degreening"] is True
        resp = api_client.create_sort_run(
            {"delivery_id": delivery["id"], "fancy_boxes": 30, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 0, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": delivery["version"]},
            make_operator_headers("op-er5"))
        validate_error(resp, ApiErrorId.ERR_DEGREENING_REQUIRED)
        # Full degreening release advances the delivery to READY_TO_SORT.
        room = create_room("RM-ER5", capacity_boxes=100, min_hours=12, max_hours=72)
        session = validate_success(api_client.create_session(
            create_session_payload(room["id"], delivery["id"], 30, planned_hours=12),
            make_operator_headers("op-er5")), expected_status=201)
        assert get_delivery(delivery["id"])["processing_status"] == "IN_DEGREENING"
        set_clock("2026-08-01T13:00:00Z")
        validate_success(api_client.release_session(
            session["id"], {}, make_operator_headers("op-er5")))
        ready = get_delivery(delivery["id"])
        assert ready["processing_status"] == "READY_TO_SORT"
        run = validate_success(api_client.create_sort_run(
            {"delivery_id": delivery["id"], "fancy_boxes": 30, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 0, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": ready["version"]},
            make_operator_headers("op-er5")), expected_status=201)
        assert run["status"] == "OPEN"


class TestRoomMaintenance:
    def test_room_maintenance_gates(self, api):
        """PRD §3.4: "Taking a room out of service moves it `AVAILABLE` →
        `MAINTENANCE` and is refused with `ERR_ROOM_NOT_AVAILABLE` while any
        session in the room is still `CONDITIONING`; returning it moves
        `MAINTENANCE` → `AVAILABLE`. Loading fruit into a room that is in
        `MAINTENANCE` likewise fails with `ERR_ROOM_NOT_AVAILABLE`."

        Design: Corner/errors/room_maintenance_gates
        """
        scenario = setup_delivery_received("ER6", gross_boxes=20, planned_boxes=50)
        (d2,) = _receive_deliveries(scenario, [5])
        room = create_room("RM-ER6", capacity_boxes=100, min_hours=12, max_hours=72)
        session = validate_success(api_client.create_session(
            create_session_payload(room["id"], scenario["delivery"]["id"], 20,
                                   planned_hours=24),
            make_operator_headers("op-er6")), expected_status=201)
        # Enter-maintenance is refused while a session is CONDITIONING.
        resp = api_client.enter_maintenance(room["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)
        # Release the session (25h duration is within [12, 72]) and retry.
        set_clock("2026-08-02T01:00:00Z")
        validate_success(api_client.release_session(
            session["id"], {}, make_operator_headers("op-er6")))
        maintenance = validate_success(api_client.enter_maintenance(room["id"], ADMIN))
        assert maintenance["status"] == "MAINTENANCE"
        # A MAINTENANCE room accepts no new sessions.
        resp = api_client.create_session(
            create_session_payload(room["id"], d2["id"], 5, planned_hours=12),
            make_operator_headers("op-er6"))
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)
        restored = validate_success(api_client.exit_maintenance(room["id"], ADMIN))
        assert restored["status"] == "AVAILABLE"
