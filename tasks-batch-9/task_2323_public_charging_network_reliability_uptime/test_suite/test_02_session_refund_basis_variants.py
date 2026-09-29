"""The two refund bases over byte-identical disputed sessions."""
from test_helpers import (
    assert_session_money_conservation,
    request_refund,
    setup_triaged_complaint_on_open_fault,
)

SESSION = {
    "outage_detected_at": "2026-06-20T09:00:00Z",
    "session_started_at": "2026-06-20T09:30:00Z",
    "session_ended_at": "2026-06-20T10:00:00Z",
    "session_energy_kwh": 12.500,
    "session_price_per_kwh_cents": 48,
    "session_charged_cents": 1850,
    "session_idle_fee_cents": 250,
}


def _two_identical_complaints_on_one_critical_fault():
    return setup_triaged_complaint_on_open_fault(
        clock="2026-06-20T12:00:00Z",
        station_clock="2026-06-20T08:00:00Z",
        site_code="HS-RF-1",
        station_code="ST-RF-1",
        fault_class="CRITICAL",
        fault_code="EVSE-CRIT-02",
        complaint_count=2,
        **SESSION,
    )


def test_energy_prorated_refund_nets_off_the_energy_value_and_the_idle_fee():
    """The prorated basis leaves the driver paying for delivered energy.

    PRD §3.9: "Under **`ENERGY_PRORATED`** ... `refund_amount_cents` is the
    charged total less that energy value less the idle-fee component, floored at
    zero so it can never go negative."  The energy value is "the delivered
    `session_energy_kwh` multiplied by the posted `session_price_per_kwh_cents`,
    with that product rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/session_refund_energy_prorated_and_goodwill_variants_diverge_on_identical_sessions
    """
    scenario = _two_identical_complaints_on_one_critical_fault()
    complaint = scenario["complaints"][0]

    data = request_refund(complaint["id"], "ENERGY_PRORATED")

    assert data["refund_state"] == "REQUESTED"
    assert data["refund_basis"] == "ENERGY_PRORATED"
    assert data["refund_amount_cents"] == 1000, (
        "1850 charged less 600 of energy less 250 of idle fee must give 1000, got "
        f"{data['refund_amount_cents']}"
    )
    assert data["retained_amount_cents"] == 850
    assert_session_money_conservation(data)
    assert data["state"] == "TRIAGED", "the intake dimension does not move on a refund filing"


def test_full_session_goodwill_refunds_the_entire_charge_on_the_same_session():
    """The goodwill basis returns everything once the three-part gate clears.

    PRD §3.9: "When the gate clears, `refund_amount_cents` is the entire
    `session_charged_cents`, idle fee included."  The gate requires a
    `linked_outage_event_id`, a `fault_class` of `CRITICAL`, and an overlap of
    the outage's downtime window with the disputed session.

    Design: Difficulty/dual_variant_calc/session_refund_energy_prorated_and_goodwill_variants_diverge_on_identical_sessions
    """
    scenario = _two_identical_complaints_on_one_critical_fault()
    complaint = scenario["complaints"][1]

    data = request_refund(complaint["id"], "FULL_SESSION_GOODWILL")

    assert data["refund_state"] == "REQUESTED"
    assert data["refund_basis"] == "FULL_SESSION_GOODWILL"
    assert data["refund_amount_cents"] == 1850, (
        "the whole charged total must come back, got " f"{data['refund_amount_cents']}"
    )
    assert data["retained_amount_cents"] == 0
    assert_session_money_conservation(data)
    assert data["state"] == "TRIAGED"


def test_the_two_refund_bases_produce_different_amounts_over_identical_rows():
    """Identical session rows, different remedies, different money.

    PRD §3.9: "Over identical complaint rows the two bases produce different
    refunds whenever the energy value and the idle fee together come to anything
    at all."

    Design: Difficulty/dual_variant_calc/session_refund_energy_prorated_and_goodwill_variants_diverge_on_identical_sessions
    """
    scenario = _two_identical_complaints_on_one_critical_fault()
    first, second = scenario["complaints"]

    prorated = request_refund(first["id"], "ENERGY_PRORATED")
    goodwill = request_refund(second["id"], "FULL_SESSION_GOODWILL")

    assert first["session_charged_cents"] == second["session_charged_cents"]
    assert first["session_energy_kwh"] == second["session_energy_kwh"]
    assert first["session_idle_fee_cents"] == second["session_idle_fee_cents"]
    assert prorated["refund_amount_cents"] != goodwill["refund_amount_cents"], (
        "the two bases must diverge over identical inputs, both gave "
        f"{prorated['refund_amount_cents']}"
    )
    assert prorated["refund_amount_cents"] == 1000
    assert goodwill["refund_amount_cents"] == 1850
