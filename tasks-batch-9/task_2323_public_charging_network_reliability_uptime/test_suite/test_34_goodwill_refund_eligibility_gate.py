"""The goodwill gate runs before any money is written, and it is half-open."""
from test_helpers import (
    ApiErrorId,
    SUPPORT_HEADERS,
    api_client,
    assert_instant_equals,
    assert_session_money_conservation,
    ingest_and_classify_outage,
    intake_complaint,
    read_complaint,
    read_outage_event,
    read_station,
    run_repair_cycle,
    set_clock,
    setup_station,
    triage_complaint,
    validate_error,
    validate_success,
)


def test_a_major_fault_cannot_carry_a_full_session_goodwill_refund():
    """Every gate but the severity one passes, so only the constant can reject it.

    PRD §3.9: "Under **`FULL_SESSION_GOODWILL`**, an eligibility gate runs **before**
    any amount is computed.  The complaint must have a `linked_outage_event_id`; that
    outage's `fault_class` must be `CRITICAL`; and that outage's downtime window must
    overlap the disputed session ... Failing any of the three yields
    `ERR_REFUND_BASIS_NOT_ELIGIBLE`."  PRD §3.9 on the surviving alternative: under
    `ENERGY_PRORATED` "`refund_amount_cents` is the charged total less that energy
    value less the idle-fee component, floored at zero so it can never go negative",
    and "`retained_amount_cents` is always `session_charged_cents` less
    `refund_amount_cents`."

    Design: Corner/calculations/goodwill_refund_requires_a_critical_fault_not_merely_a_major_one
    """
    scenario = setup_station(
        clock="2026-08-01T09:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T09:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )

    set_clock("2026-08-01T12:00:00Z")
    complaint = intake_complaint(
        station_id,
        port_id,
        "2026-08-01T10:00:00Z",
        "2026-08-01T10:40:00Z",
        20.000,
        45,
        1000,
        session_idle_fee_cents=200,
    )
    triage_complaint(complaint["id"], "LINK_OUTAGE", linked_outage_event_id=outage["id"])

    response = api_client.request_session_refund(
        complaint["id"], "FULL_SESSION_GOODWILL", SUPPORT_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_REFUND_BASIS_NOT_ELIGIBLE, 422)

    rejected = read_complaint(complaint["id"])
    assert rejected["refund_state"] == "NONE"
    assert rejected["refund_basis"] is None, "the gate ran before any amount was written"
    assert rejected["refund_amount_cents"] is None
    assert rejected["retained_amount_cents"] is None
    assert rejected["state"] == "TRIAGED"
    assert rejected["linked_outage_event_id"] == outage["id"], "the link survives"
    assert read_station(station_id)["refund_liability_cents"] == 0

    prorated = validate_success(
        api_client.request_session_refund(complaint["id"], "ENERGY_PRORATED", SUPPORT_HEADERS)
    )

    assert prorated["refund_state"] == "REQUESTED"
    assert prorated["refund_basis"] == "ENERGY_PRORATED"
    assert prorated["refund_amount_cents"] == 0, (
        "900 cents of energy plus the 200-cent idle fee already exceed the 1000 charged"
    )
    assert prorated["retained_amount_cents"] == 1000
    assert_session_money_conservation(prorated)


def test_a_fault_cleared_exactly_when_the_session_starts_does_not_overlap_it():
    """A closed-interval intersection test would hand back the whole 1500 cents.

    PRD §3.9: the goodwill gate requires "that outage's downtime window must overlap
    the disputed session under the half-open convention of §2.10, the outage running
    from its `detected_at` inclusive up to its `cleared_at` exclusive (or forward
    without bound while `cleared_at` is null) and the session running from
    `session_started_at` inclusive to `session_ended_at` exclusive, with a
    zero-length touch not counting as an overlap.  Failing any of the three yields
    `ERR_REFUND_BASIS_NOT_ELIGIBLE`."

    Design: Corner/calculations/goodwill_refund_rejected_when_the_fault_window_only_touches_the_session_start
    """
    scenario = setup_station(
        clock="2026-08-01T08:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    cycle = run_repair_cycle(
        port_id,
        detected_at="2026-08-01T08:00:00Z",
        window_start_at="2026-08-01T08:30:00Z",
        window_end_at="2026-08-01T11:00:00Z",
        completed_at="2026-08-01T10:00:00Z",
        fault_class="CRITICAL",
        fault_code="EVSE-CRIT-01",
    )
    outage_id = cycle["outage"]["id"]

    closed = read_outage_event(outage_id)
    assert closed["fault_class"] == "CRITICAL", "the severity gate passes"
    assert_instant_equals(closed["cleared_at"], "2026-08-01T10:00:00Z", "cleared_at")

    set_clock("2026-08-01T12:00:00Z")
    complaint = intake_complaint(
        station_id,
        port_id,
        "2026-08-01T10:00:00Z",
        "2026-08-01T10:30:00Z",
        10.000,
        50,
        1500,
        complaint_type="CHARGER_OFFLINE",
    )
    triage_complaint(complaint["id"], "LINK_OUTAGE", linked_outage_event_id=outage_id)

    response = api_client.request_session_refund(
        complaint["id"], "FULL_SESSION_GOODWILL", SUPPORT_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_REFUND_BASIS_NOT_ELIGIBLE, 422)

    after = read_complaint(complaint["id"])
    assert after["refund_state"] == "NONE"
    assert after["refund_amount_cents"] is None
    assert read_station(station_id)["refund_liability_cents"] == 0
