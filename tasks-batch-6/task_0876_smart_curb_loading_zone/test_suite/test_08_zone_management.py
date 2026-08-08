"""Zone management: OCC redesignation, sensor-derived occupancy, actual-minutes ceiling,
retire guard, enum validation, immediate consistency.

All corner-queue (breadth) coverage over the zone / sensor surface.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_curb_planner_headers,
    make_platform_admin_headers,
    advance_clock,
    make_policy,
    make_zone,
    open_session,
    close_session,
    record_occupancy,
    setup_confirmed_reservation,
    create_zone_payload,
)


def test_redesignate_with_stale_version_rejected(api):
    """PRD §2.7: "If expected_zone_version does not equal the zone's current version, the
    write is refused with ERR_STALE_VERSION (HTTP 412), on the grounds that another
    redesignation has legitimately superseded the client's view and the client is acting
    on a stale copy of the zone."

    Design: Corner/cross_cutting_complexity_layers/occ_redesignate_stale_version_conflict
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    assert zone["version"] == 1
    # First redesignation with the observed version succeeds: version 1 -> 2.
    first = validate_success(api.redesignate_zone(
        zone["id"], {"designation": "VALET", "expected_zone_version": 1},
        make_curb_planner_headers("planner1")))
    assert first["version"] == 2 and first["designation"] == "VALET"
    # Second redesignation still carrying the stale version 1 is refused.
    resp = api.redesignate_zone(
        zone["id"], {"designation": "TNC", "expected_zone_version": 1},
        make_curb_planner_headers("planner1"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    unchanged = validate_success(api.get_zone(zone["id"], make_curb_planner_headers("planner1")))
    assert unchanged["designation"] == "VALET", "rejected write leaves designation unchanged"


def test_sensor_occupancy_state_derived_from_open_session(api):
    """PRD §3.1: "A zone's sensor_occupancy_state is OCCUPIED exactly while it holds at
    least one open occupancy session and reverts to VACANT otherwise."

    Design: Corner/cross_cutting_complexity_layers/zone_sensor_occupancy_derived_field
    """
    advance_clock(api, "2026-06-01T08:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    sess = open_session(api, zone["id"])
    occupied = validate_success(api.get_zone(zone["id"], make_curb_planner_headers("planner1")))
    assert occupied["sensor_occupancy_state"] == "OCCUPIED"
    advance_clock(api, "2026-06-01T08:30:00Z")
    closed = close_session(api, sess["id"])
    assert closed["session_status"] == "CLOSED"
    assert closed["actual_minutes"] == 30
    vacant = validate_success(api.get_zone(zone["id"], make_curb_planner_headers("planner1")))
    assert vacant["sensor_occupancy_state"] == "VACANT"


def test_actual_minutes_ceils_partial_minute(api):
    """PRD §3.5: "The observed actual_minutes is the elapsed time from entered_at to
    exited_at measured in seconds, divided by 60 and rounded up to the next whole minute,
    so that a 62-second stay counts as 2 minutes while a zero-length stay counts as 0."

    Design: Corner/calculations/occupancy_actual_minutes_ceiling
    """
    advance_clock(api, "2026-06-01T08:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    session = record_occupancy(api, zone["id"], None, "2026-06-01T08:00:00Z", "2026-06-01T08:01:02Z")
    assert session["actual_minutes"] == 2, "ceil(62 seconds) == 2 minutes"


def test_retire_zone_with_future_reservation_rejected(api):
    """PRD §3.1: "A planner may move an ACTIVE zone to RETIRED only when the zone holds no
    CONFIRMED reservation whose end instant lies in the future relative to the logical
    clock; if any such reservation exists the retirement is refused with
    ERR_ZONE_HAS_ACTIVE_RESERVATIONS."

    Design: Corner/state_machines/retire_zone_with_active_reservations
    """
    ctx = setup_confirmed_reservation(api)  # clock 2026-05-20, reservation ends 2026-06-01
    resp = api.set_zone_status(ctx["zone_id"], "RETIRED", make_curb_planner_headers("planner1"))
    validate_error(resp, ApiErrorId.ERR_ZONE_HAS_ACTIVE_RESERVATIONS)
    zone = validate_success(api.get_zone(ctx["zone_id"], make_curb_planner_headers("planner1")))
    assert zone["status"] == "ACTIVE"


def test_zone_create_unknown_designation_rejected(api):
    """PRD §2.9: "An enum field that carries a value outside its permitted set — a bad
    target_status, decision, or violation_type — is reported as ERR_INVALID_ENUM (HTTP 422)."

    Design: Corner/endpoints/zone_create_invalid_designation_enum
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    resp = api.create_zone(
        create_zone_payload(policy["id"], name="Zx", designation="BIKE_LANE"),
        make_curb_planner_headers("planner1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_zone_immediately_visible_after_create(api):
    """PRD §3.1: "A newly created zone opens with status of ACTIVE, a sensor_occupancy_state
    of VACANT, revenue_accrued_cents of zero, and version 1."

    Design: Corner/consistency_model/immediate_visibility_after_create
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"], name="Z1", designation="LOADING")
    fetched = validate_success(api.get_zone(zone["id"], make_curb_planner_headers("planner1")))
    assert fetched["name"] == "Z1"
    assert fetched["designation"] == "LOADING"
    assert fetched["status"] == "ACTIVE"
    assert fetched["version"] == 1
