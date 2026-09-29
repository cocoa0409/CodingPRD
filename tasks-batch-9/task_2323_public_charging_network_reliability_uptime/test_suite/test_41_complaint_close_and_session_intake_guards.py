"""The complaint desk's two dimensions and its three intake guards."""
from test_helpers import (
    SUPPORT_HEADERS,
    ApiErrorId,
    api_client,
    assert_session_money_conservation,
    create_customer_complaint_payload,
    decide_refund,
    ingest_and_classify_outage,
    intake_complaint,
    read_complaint,
    read_station,
    request_refund,
    set_clock,
    setup_station,
    triage_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_station_with_one_plain_dispenser():
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[{"dispenser_serial": "DS-1", "terminal_model": "PT-4"}],
        stop_at="DRAFT",
    )
    return scenario["station"]["id"], scenario["ports"][0]["id"]


def test_the_same_close_call_is_refused_before_the_refund_decision_and_allowed_after():
    """The interlock reads the money dimension, not the one being transitioned.

    PRD §3.9: "A triaged complaint is closed by the support agent, advancing
    `TRIAGED → CLOSED`.  Closure is blocked while the money dimension is still in
    flight: it is permitted only when `refund_state` is `NONE`, `DENIED`,
    `SETTLED`, or `REVERSED`, and an attempt while `refund_state` is `REQUESTED`
    or `APPROVED` is rejected with `ERR_REFUND_IN_FLIGHT`."  PRD §3.9 on the
    prorated amount: "`refund_amount_cents` is the charged total less that energy
    value less the idle-fee component, floored at zero"; and on `DENY`: it
    "advances `REQUESTED → DENIED` and rewrites the money split to the no-refund
    position".  PRD §3.9 on the station's exposure: only `SETTLE` "raises the
    station's `refund_liability_cents` by the refund amount".

    Design: Corner/validations/complaint_cannot_be_closed_while_a_refund_request_is_in_flight
    """
    station_id, port_id = _draft_station_with_one_plain_dispenser()

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )

    set_clock("2026-08-01T12:00:00Z")
    complaint = intake_complaint(
        station_id,
        port_id,
        "2026-08-01T10:00:00Z",
        "2026-08-01T10:30:00Z",
        10.000,
        40,
        1000,
        complaint_type="PRICE_MISMATCH",
    )
    triage_complaint(complaint["id"], "LINK_OUTAGE", outage["id"])
    requested = request_refund(complaint["id"], "ENERGY_PRORATED")

    assert requested["state"] == "TRIAGED"
    assert requested["refund_state"] == "REQUESTED"
    assert requested["refund_amount_cents"] == 600, "1000 charged less 400 of energy"
    assert requested["retained_amount_cents"] == 400
    assert_session_money_conservation(requested)
    assert read_station(station_id)["refund_liability_cents"] == 0

    response = api_client.close_customer_complaint(complaint["id"], SUPPORT_HEADERS)

    validate_error(response, ApiErrorId.ERR_REFUND_IN_FLIGHT, 409)

    blocked = read_complaint(complaint["id"])
    assert blocked["state"] == "TRIAGED", "the intake dimension did not move"
    assert blocked["refund_state"] == "REQUESTED"
    assert read_station(station_id)["refund_liability_cents"] == 0

    denied = decide_refund(complaint["id"], "DENY")
    assert denied["refund_state"] == "DENIED"
    assert denied["refund_amount_cents"] == 0
    assert denied["retained_amount_cents"] == 1000
    assert_session_money_conservation(denied)
    assert denied["state"] == "TRIAGED"

    data = validate_success(
        api_client.close_customer_complaint(complaint["id"], SUPPORT_HEADERS)
    )

    assert data["state"] == "CLOSED", "the identical call, now that the money has settled out"
    assert data["refund_state"] == "DENIED"
    assert read_station(station_id)["refund_liability_cents"] == 0, (
        "a denied refund never becomes a liability"
    )


def test_an_idle_fee_equal_to_the_charge_is_accepted_where_one_cent_more_is_not():
    """Two intake guards at different priorities, exercised one at a time.

    PRD §3.9: "Three checks guard intake.  The dispenser must belong to the
    station named — otherwise `ERR_COMPLAINT_PORT_MISMATCH`.  The session must be
    well-formed, with `session_ended_at` strictly after `session_started_at` —
    otherwise `ERR_SESSION_WINDOW_INVALID`.  And the charged total may not be
    smaller than the idle-fee component it is supposed to contain — otherwise
    `ERR_SESSION_CHARGE_INVALID`.  A fresh complaint opens with `state` at
    `INTAKE` and `refund_state` at `NONE`."  PRD §3.9 on the dismissal path:
    "`NO_FAULT` dismisses the complaint, advancing `INTAKE → DISMISSED`, and is
    permitted only while the money dimension is still at `NONE`."

    Design: Corner/validations/session_intake_guards_reject_an_inverted_window_and_an_idle_fee_above_the_charge
    """
    station_id, port_id = _draft_station_with_one_plain_dispenser()

    set_clock("2026-08-01T12:00:00Z")

    def _intake(session_started_at, session_ended_at, **overrides):
        return api_client.create_customer_complaint(
            create_customer_complaint_payload(
                station_id,
                port_id,
                session_started_at,
                session_ended_at,
                0.000,
                40,
                500,
                complaint_type="BLOCKED_STALL",
                **overrides,
            ),
            SUPPORT_HEADERS,
        )

    validate_error(
        _intake("2026-08-01T10:30:00Z", "2026-08-01T10:00:00Z"),
        ApiErrorId.ERR_SESSION_WINDOW_INVALID,
        422,
    )
    validate_error(
        _intake("2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z", session_idle_fee_cents=600),
        ApiErrorId.ERR_SESSION_CHARGE_INVALID,
        422,
    )

    data = validate_success(
        _intake("2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z", session_idle_fee_cents=500), 201
    )

    assert data["session_idle_fee_cents"] == 500, "equal to the charged total is not smaller"
    assert data["session_charged_cents"] == 500
    assert data["state"] == "INTAKE"
    assert data["refund_state"] == "NONE"
    assert data["refund_basis"] is None
    assert data["refund_amount_cents"] is None
    assert data["retained_amount_cents"] is None

    dismissed = triage_complaint(data["id"], "NO_FAULT")
    assert dismissed["state"] == "DISMISSED", "a NO_FAULT triage bypasses TRIAGED entirely"
    assert dismissed["refund_state"] == "NONE"

    rows, meta = validate_paginated(
        api_client.list_customer_complaints(SUPPORT_HEADERS, {"station_id": station_id})
    )
    assert len(rows) == 1, "the two rejected intakes created nothing"
    assert meta["total_count"] == 1
