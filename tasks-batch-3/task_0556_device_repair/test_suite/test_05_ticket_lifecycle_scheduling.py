"""Diagnosis scheduling (technician overlap, interval validity) and ticket-state
lifecycle guards (re-diagnose, terminal-state cancel).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_technician_headers,
    create_customer, create_device, create_technician, create_bay, create_ticket,
    diagnose_ticket, setup_diagnosed_ticket, setup_completed_ticket,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / technician_double_booking_half_open
# ---------------------------------------------------------------------------
def test_technician_double_booked_overlapping_window_rejected(api):
    """PRD §3.2: "The assigned technician may not be double-booked: treating each
    technician's window as half-open — including its start instant but excluding its end
    instant — no other non-terminal ticket on that technician may overlap this window,
    or the request is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_double_booking_half_open
    """
    cust = create_customer()
    dev1 = create_device(cust["id"])
    dev2 = create_device(cust["id"])
    tech = create_technician("STANDARD")
    bay1 = create_bay()
    bay2 = create_bay()
    tkt1 = create_ticket(dev1["id"], cust["id"])
    diagnose_ticket(tkt1["id"], tech["id"], bay1["id"],
                    "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    tkt2 = create_ticket(dev2["id"], cust["id"])
    resp = api.diagnose(tkt2["id"],
                        {"assigned_technician_id": tech["id"], "assigned_bay_id": bay2["id"],
                         "scheduled_start_at": "2026-05-02T10:30:00Z",
                         "scheduled_end_at": "2026-05-02T11:30:00Z"},
                        make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED.value, 409)
    tkt2_now = validate_success(api.get_repair_ticket(tkt2["id"], SM))
    assert tkt2_now["status"] == "INTAKE"


def test_technician_adjacent_half_open_window_allowed(api):
    """PRD §3.2: "The assigned technician may not be double-booked: treating each
    technician's window as half-open — including its start instant but excluding its end
    instant — no other non-terminal ticket on that technician may overlap this window,
    or the request is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_double_booking_half_open
    """
    # Second window starts exactly at the first window's excluded end instant -> no overlap.
    # A different bay is used so the bay check cannot interfere.
    cust = create_customer()
    dev1 = create_device(cust["id"])
    dev2 = create_device(cust["id"])
    tech = create_technician("STANDARD")
    bay1 = create_bay()
    bay2 = create_bay()
    tkt1 = create_ticket(dev1["id"], cust["id"])
    diagnose_ticket(tkt1["id"], tech["id"], bay1["id"],
                    "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    tkt2 = create_ticket(dev2["id"], cust["id"])
    diagnosed = validate_success(api.diagnose(
        tkt2["id"],
        {"assigned_technician_id": tech["id"], "assigned_bay_id": bay2["id"],
         "scheduled_start_at": "2026-05-02T11:00:00Z",
         "scheduled_end_at": "2026-05-02T12:00:00Z"},
        make_technician_headers(tech["id"])))
    assert diagnosed["status"] == "DIAGNOSING"


# ---------------------------------------------------------------------------
# Corner: validations / diagnose_invalid_interval_rejected
# ---------------------------------------------------------------------------
def test_diagnose_invalid_interval_rejected(api):
    """PRD §3.2: "The window must be non-empty: `scheduled_end_at` must be strictly later
    than `scheduled_start_at`, otherwise `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/diagnose_invalid_interval_rejected
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=1000)
    tech = create_technician("STANDARD")
    bay = create_bay()
    tkt = create_ticket(dev["id"], cust["id"], spend_cap_cents=1000)
    resp = api.diagnose(tkt["id"],
                        {"assigned_technician_id": tech["id"], "assigned_bay_id": bay["id"],
                         "scheduled_start_at": "2026-05-02T11:00:00Z",
                         "scheduled_end_at": "2026-05-02T10:00:00Z"},
                        make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)


# ---------------------------------------------------------------------------
# Corner: state_machines / diagnose_twice_returns_409_invalid_state
# ---------------------------------------------------------------------------
def test_diagnose_already_diagnosing_ticket_returns_invalid_state(api):
    """PRD §3.2: "Diagnosis is the technician's move that advances a ticket from
    `INTAKE` to `DIAGNOSING`."
    PRD §2.11: "Fifth, the target resource's state is checked against the requested
    transition, yielding the relevant invalid-state error."

    Design: Corner/state_machines/diagnose_twice_returns_409_invalid_state
    """
    scn = setup_diagnosed_ticket(market_value_cents=1000, spend_cap_cents=1000)
    resp = api.diagnose(scn["ticket"]["id"],
                        {"assigned_technician_id": scn["technician"]["id"],
                         "assigned_bay_id": scn["bay"]["id"],
                         "scheduled_start_at": "2026-05-02T13:00:00Z",
                         "scheduled_end_at": "2026-05-02T14:00:00Z"},
                        make_technician_headers(scn["technician"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_completed_ticket_from_terminal_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_completed_ticket_returns_invalid_state(api):
    """PRD §3.6: "A `ServiceAdvisor` may cancel a ticket while it is still in `INTAKE`,
    `DIAGNOSING`, or `AWAITING_APPROVAL`; any other state is rejected with
    `ERR_TICKET_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_ticket_from_terminal_returns_invalid_state
    """
    scn = setup_completed_ticket(market_value_cents=40000, spend_cap_cents=100000,
                                 labor_hours=2, actual_labor_hours=2)
    resp = api.cancel_ticket(scn["ticket"]["id"], SA)
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value, 409)
    tkt = validate_success(api.get_repair_ticket(scn["ticket"]["id"], SM))
    assert tkt["status"] == "COMPLETED"
