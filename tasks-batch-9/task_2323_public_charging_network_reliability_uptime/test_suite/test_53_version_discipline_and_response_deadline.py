"""Version is the currency of both concurrency guards, and response_met is a
one-shot threshold read at arrival."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    TECHNICIAN_2,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_dispatch,
    ingest_and_classify_outage,
    post_progress,
    read_charging_port,
    read_dispatch,
    read_host_site,
    read_station,
    set_clock,
    setup_station,
    validate_error,
    validate_success,
)


def test_a_no_op_amendment_still_costs_a_version_while_a_rejected_one_does_not():
    """A version that moves on a rejected write, or twice on an accepted one, breaks
    every optimistic-concurrency client.

    PRD §2.4: `version` is "a counter that increments by one on every mutation".  PRD
    §3.1: "Whenever `access_hours_mode` is `RESTRICTED`, the opening minute must be
    strictly earlier than the closing minute; if it is not, the request fails with
    `ERR_INVALID_ACCESS_WINDOW`.  This rule is checked both when the site is
    registered and every time it is amended."  PRD §3.1 on the accepted path: an
    amendment "increments the host site's `version`".  PRD §3.2: "The four
    interoperability attributes remain amendable afterwards by a `NetworkOperator` —
    an amendment may carry any subset of `contactless_enabled`,
    `plug_and_charge_enabled`, `price_display_verified`, and `roaming_ocpi_version` —
    and each amendment recomputes the station's `payment_interop_score` and increments
    the dispenser's `version`."  PRD §3.3: "A
    station's lifecycle dimension, `status`, runs over `DRAFT`, `COMMISSIONING`,
    `OPERATIONAL`, `SUSPENDED`, and `DECOMMISSIONED` ... Most moves are driven by a
    `NetworkOperator` naming the desired `target_status`; every one of them increments
    the station's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_advances_on_accepted_writes_and_stands_still_on_rejected_ones
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-1")],
        stop_at="DRAFT",
    )
    site_id = scenario["host_site"]["id"]
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    assert read_host_site(site_id)["version"] == 1, "registration is one write"
    assert read_charging_port(port_id)["version"] == 2, "installation, then certification"
    station_version = read_station(station_id)["version"]
    assert float(read_station(station_id)["payment_interop_score"]) == 100.00

    amended = validate_success(
        api_client.update_host_site(
            site_id, {"committed_service_capacity_kw": 450.00}, OPERATOR_HEADERS
        )
    )
    assert amended["version"] == 2
    assert float(amended["committed_service_capacity_kw"]) == 450.00

    validate_error(
        api_client.update_host_site(
            site_id,
            {
                "access_hours_mode": "RESTRICTED",
                "access_open_minute": 1200,
                "access_close_minute": 600,
            },
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_ACCESS_WINDOW,
        422,
    )

    spared = read_host_site(site_id)
    assert spared["version"] == 2, "a rejected amendment must not consume a version"
    assert spared["access_hours_mode"] == "TWENTY_FOUR_SEVEN"

    rewritten = validate_success(
        api_client.update_charging_port(port_id, {"contactless_enabled": True}, OPERATOR_HEADERS)
    )

    assert rewritten["contactless_enabled"] is True
    assert rewritten["version"] == 3, "an accepted write that changes nothing still counts once"
    assert (
        float(read_station(station_id)["payment_interop_score"]) == 100.00
    ), "the rescore ran and landed on the same figure"

    validate_error(
        api_client.transition_station_status(station_id, "OPERATIONAL", OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    untouched_station = read_station(station_id)
    assert untouched_station["status"] == "DRAFT"
    assert untouched_station["version"] == station_version


def test_arriving_on_the_deadline_minute_counts_while_the_next_minute_does_not():
    """The comparison is inclusive and it is evaluated exactly once, at arrival.

    PRD §3.5: "First, a base allowance is chosen from the outage's severity: four
    hours for `CRITICAL` ... Second, that base is scaled by the station's power class
    — halved for `DCFC_350` ... with the scaled product rounded down to a whole
    number of minutes.  Third, if the station is `corridor_designated`, one hour is
    subtracted from the scaled figure; otherwise nothing is subtracted.  Fourth, the
    result is clamped into the regulatory band: it is raised to two hours if it fell
    below two hours, and capped at three days if it rose above three days.  The
    clamped allowance is added to the outage's `detected_at` to give a provisional
    deadline instant."  PRD §3.5: "If the host site's `access_hours_mode` is
    `TWENTY_FOUR_SEVEN`, the provisional instant is the deadline."  PRD §3.5 on the
    threshold: "`ARRIVE` advances `EN_ROUTE → ON_SITE`, stamps `arrived_at` from the
    logical clock, and settles `response_met` once and for all: it is true when
    `arrived_at` is at or before `response_deadline_at` and false otherwise, and it
    stays null until arrival is posted."  PRD §3.3: "whenever a dispenser on an
    operational station enters `OUT_OF_SERVICE` and the station's out-of-service count
    is therefore at least one, the station moves `OPERATIONAL → SUSPENDED` with
    `suspension_source` set to `AUTOMATIC`".

    Design: Corner/cross_cutting_complexity_layers/response_met_flips_on_the_minute_the_response_deadline_passes
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_350",
        declared_port_count=2,
        ports=[
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-1"),
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-2", connector_type="NACS"),
        ],
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    first_port, second_port = (port["id"] for port in scenario["ports"])

    first_outage = ingest_and_classify_outage(
        first_port, "2026-08-01T00:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-01"
    )
    second_outage = ingest_and_classify_outage(
        second_port, "2026-08-01T00:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-02"
    )
    punctual = create_dispatch(
        first_outage["id"],
        first_port,
        window_start_at="2026-08-01T00:30:00Z",
        window_end_at="2026-08-01T06:00:00Z",
        technician_user_id=TECHNICIAN_1,
        technician_certification_class="DCFC_HV",
    )
    late = create_dispatch(
        second_outage["id"],
        second_port,
        window_start_at="2026-08-01T00:30:00Z",
        window_end_at="2026-08-01T06:00:00Z",
        technician_user_id=TECHNICIAN_2,
        technician_certification_class="DCFC_HV",
    )

    for dispatch in (punctual, late):
        assert_instant_equals(
            dispatch["response_deadline_at"],
            "2026-08-01T02:00:00Z",
            "response_deadline_at",
        )
        assert dispatch["response_met"] is None
        assert dispatch["arrived_at"] is None

    post_progress(punctual["id"], "EN_ROUTE", TECHNICIAN_1)
    post_progress(late["id"], "EN_ROUTE", TECHNICIAN_2)

    set_clock("2026-08-01T02:00:00Z")
    on_time = post_progress(punctual["id"], "ARRIVE", TECHNICIAN_1)

    assert on_time["state"] == "ON_SITE"
    assert_instant_equals(on_time["arrived_at"], "2026-08-01T02:00:00Z", "arrived_at")
    assert on_time["response_met"] is True, "arrival exactly on the deadline counts as met"

    set_clock("2026-08-01T02:01:00Z")
    missed = post_progress(late["id"], "ARRIVE", TECHNICIAN_2)

    assert missed["state"] == "ON_SITE"
    assert_instant_equals(missed["arrived_at"], "2026-08-01T02:01:00Z", "arrived_at")
    assert missed["response_met"] is False, "one minute past the deadline is a miss"

    assert (
        read_dispatch(punctual["id"])["response_met"] is True
    ), "the verdict is pinned at arrival and never re-evaluated"

    assert read_charging_port(first_port)["maintenance_state"] == "UNDER_REPAIR"
    assert read_charging_port(second_port)["maintenance_state"] == "UNDER_REPAIR"

    station = read_station(station_id)
    assert station["status"] == "SUSPENDED"
    assert station["suspension_source"] == "AUTOMATIC"
    assert station["out_of_service_port_count"] == 2
