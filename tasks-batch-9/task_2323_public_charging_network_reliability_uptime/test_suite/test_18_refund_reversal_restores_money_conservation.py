"""Reversing a settled refund unwinds both the complaint and the station ledger."""
from test_helpers import (
    act_on_refund_ledger,
    assert_instant_equals,
    assert_session_money_conservation,
    decide_refund,
    read_complaint,
    read_station,
    request_refund,
    setup_triaged_complaint_on_open_fault,
)

SESSION = {
    "outage_detected_at": "2026-06-22T09:00:00Z",
    "session_started_at": "2026-06-22T09:30:00Z",
    "session_ended_at": "2026-06-22T10:00:00Z",
    "session_energy_kwh": 12.500,
    "session_price_per_kwh_cents": 48,
    "session_charged_cents": 1850,
    "session_idle_fee_cents": 250,
}


def _triaged_complaint_on_a_still_open_critical_fault():
    return setup_triaged_complaint_on_open_fault(
        clock="2026-06-22T12:00:00Z",
        station_clock="2026-06-22T08:00:00Z",
        site_code="HS-INV-2",
        station_code="ST-INV-2",
        fault_class="CRITICAL",
        fault_code="EVSE-CRIT-02",
        **SESSION,
    )


def test_settling_a_prorated_refund_raises_the_station_liability():
    """The split holds at every step and the liability appears only on settlement.

    PRD §3.9: "the refund and the retained amount always sum to exactly what the
    driver was charged, at every point in the money dimension", and "`SETTLE` ...
    advances `refund_state` from `APPROVED` to `SETTLED`, stamps
    `refund_settled_at` from the logical clock, and raises the station's
    `refund_liability_cents` by the refund amount."

    Design: Difficulty/compensating_invariant/refund_reversal_restores_session_money_conservation_and_station_liability
    """
    scenario = _triaged_complaint_on_a_still_open_critical_fault()
    complaint_id = scenario["complaints"][0]["id"]
    station_id = scenario["station"]["id"]

    assert read_station(station_id)["refund_liability_cents"] == 0

    requested = request_refund(complaint_id, "ENERGY_PRORATED")
    assert requested["refund_state"] == "REQUESTED"
    assert requested["refund_amount_cents"] == 1000, (
        "1850 charged less 600 cents of delivered energy less the 250-cent idle fee"
    )
    assert requested["retained_amount_cents"] == 850
    assert_session_money_conservation(requested)

    approved = decide_refund(complaint_id, "APPROVE")
    assert approved["refund_state"] == "APPROVED"
    assert approved["refund_amount_cents"] == 1000
    assert approved["retained_amount_cents"] == 850
    assert_session_money_conservation(approved)

    settled = act_on_refund_ledger(complaint_id, "SETTLE")
    assert settled["refund_state"] == "SETTLED"
    assert_instant_equals(settled["refund_settled_at"], "2026-06-22T12:00:00Z", "refund_settled_at")

    assert read_station(station_id)["refund_liability_cents"] == 1000


def test_reversing_the_settlement_restores_both_ledgers_with_no_drift():
    """Two ledgers unwind together, and the intake dimension never moves.

    PRD §3.9: "`REVERSE` is the auditor's compensating action: it advances
    `SETTLED → REVERSED`, clears `refund_settled_at` back to null, lowers the
    station's `refund_liability_cents` by the refund amount — restoring it to its
    exact pre-settlement value — and rewrites the money split to the no-refund
    position, setting `refund_amount_cents` to zero and `retained_amount_cents` to
    the full `session_charged_cents`."

    Design: Difficulty/compensating_invariant/refund_reversal_restores_session_money_conservation_and_station_liability
    """
    scenario = _triaged_complaint_on_a_still_open_critical_fault()
    complaint_id = scenario["complaints"][0]["id"]
    station_id = scenario["station"]["id"]

    request_refund(complaint_id, "ENERGY_PRORATED")
    decide_refund(complaint_id, "APPROVE")
    act_on_refund_ledger(complaint_id, "SETTLE")

    reversed_complaint = act_on_refund_ledger(complaint_id, "REVERSE")

    assert reversed_complaint["refund_state"] == "REVERSED"
    assert reversed_complaint["refund_settled_at"] is None
    assert reversed_complaint["refund_amount_cents"] == 0
    assert reversed_complaint["retained_amount_cents"] == 1850
    assert_session_money_conservation(reversed_complaint)

    assert read_station(station_id)["refund_liability_cents"] == 0, (
        "the liability must return to its exact pre-settlement value"
    )
    assert read_complaint(complaint_id)["state"] == "TRIAGED", (
        "the intake dimension stayed still while the money dimension cycled"
    )
