"""The contractual response deadline: severity, power class, corridor, access."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    TECHNICIAN_HV,
    assert_instant_equals,
    create_dispatch,
    parse_instant,
    ingest_and_classify_outage,
    read_charging_port,
    read_outage_event,
    set_clock,
    setup_station,
)


def _corridor_dcfc_350_station_behind_a_restricted_gate():
    """A corridor-designated DCFC_350 station whose host site opens at 06:00 UTC
    and closes at 22:00 UTC."""
    return setup_station(
        clock="2026-06-01T00:00:00Z",
        site_code="HS-DL-1",
        station_code="ST-DL-1",
        committed_service_capacity_kw=1200.00,
        power_class="DCFC_350",
        declared_port_count=1,
        corridor_designated=True,
        host_site_overrides={
            "parking_enforcement_mode": "SIGNAGE_ONLY",
            "access_hours_mode": "RESTRICTED",
            "access_open_minute": 360,
            "access_close_minute": 1320,
        },
        ports=[
            dict(
                FULLY_COMPLIANT_PORT,
                dispenser_serial="DS-DL-1",
                connector_type="NACS",
                roaming_ocpi_version="V2_3_0",
            )
        ],
    )


def test_response_deadline_is_pushed_forward_to_the_access_window_opening():
    """The four-input allowance lands before opening, so the deadline moves.

    PRD §3.5 chooses "twelve hours for `MAJOR`", scales it "halved for
    `DCFC_350`", subtracts "one hour" because the station is
    `corridor_designated`, clamps into the regulatory band, and then: "When it
    falls before `access_open_minute`, the deadline is pushed forward to
    `access_open_minute` on the same UTC date, with seconds and milliseconds
    zeroed."

    Design: Difficulty/combinatorial_formula/dispatch_deadline_mode_a_nested_min_max_then_restricted_access_window_push
    """
    scenario = _corridor_dcfc_350_station_behind_a_restricted_gate()
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-06-10T21:00:00Z")
    outage = ingest_and_classify_outage(
        port_id, "2026-06-10T20:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )

    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-06-10T22:00:00Z",
        window_end_at="2026-06-11T08:00:00Z",
        technician_user_id=TECHNICIAN_HV,
        technician_certification_class="DCFC_HV",
    )

    assert_instant_equals(
        dispatch["response_deadline_at"],
        "2026-06-11T06:00:00Z",
        "response_deadline_at (720 minutes halved to 360, less 60 for the corridor, "
        "gives 300 minutes after 2026-06-10T20:00:00Z, i.e. 01:00 — before the 06:00 "
        "opening, so the deadline is pushed to 06:00 on the same date)",
    )
    assert parse_instant(dispatch["response_deadline_at"]) != parse_instant(
        "2026-06-11T01:00:00Z"
    ), "the unreconciled provisional instant must not be published as the deadline"


def test_dispatch_creation_pins_the_deadline_and_leaves_arrival_unsettled():
    """Creation propagates to the outage and the dispenser but settles no arrival.

    PRD §3.5: "The dispatch opens in `CREATED` with `arrived_at`, `response_met`,
    `promised_repair_at` and `total_hold_minutes` all null" and "The outage
    advances `CLASSIFIED → DISPATCHED` ... and the dispenser's repair posture
    moves `NONE → DISPATCH_PENDING`".

    Design: Difficulty/combinatorial_formula/dispatch_deadline_mode_a_nested_min_max_then_restricted_access_window_push
    """
    scenario = _corridor_dcfc_350_station_behind_a_restricted_gate()
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-06-10T21:00:00Z")
    outage = ingest_and_classify_outage(
        port_id, "2026-06-10T20:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )

    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-06-10T22:00:00Z",
        window_end_at="2026-06-11T08:00:00Z",
        technician_user_id=TECHNICIAN_HV,
        technician_certification_class="DCFC_HV",
    )

    assert dispatch["state"] == "CREATED"
    assert dispatch["arrived_at"] is None
    assert dispatch["response_met"] is None, "response_met stays null until arrival is posted"
    assert read_outage_event(outage["id"])["state"] == "DISPATCHED"
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"
