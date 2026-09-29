"""Two money guards read off boundary values: a 0.00 withhold tier and a refund
that is exactly the whole charge."""
from test_helpers import (
    PROGRAM_ADMIN_1,
    PROGRAM_ADMIN_HEADERS,
    SUPPORT_AGENT_1,
    ApiErrorId,
    act_on_refund_ledger,
    api_client,
    assert_instant_equals,
    assert_session_money_conservation,
    decide_refund,
    read_claim,
    read_complaint,
    read_station,
    request_refund,
    set_clock,
    setup_claim_in_review,
    setup_operational_station,
    setup_triaged_complaint_on_open_fault,
    validate_error,
    validate_success,
)


def test_a_flawless_report_leaves_approve_as_the_only_legal_decision():
    """Writing a zero withhold instead of refusing would pay the claim twice over.

    PRD §3.8 on tier selection: "`withhold_rate` is selected from
    `effective_uptime_pct` by walking the tiers from the top with an inclusive
    comparison at each step: an effective figure of at least 97.00 withholds nothing
    (a rate of `0.00`)".  PRD §3.8 on the three decisions: "`WITHHOLD` requires the
    snapshotted `withhold_rate` to be strictly greater than `0.00` and strictly less
    than `1.00`; a rate of `0.00` or `1.00` is rejected with
    `ERR_WITHHOLD_RATE_MISMATCH`."; "`DENY` requires the snapshotted `withhold_rate`
    to be exactly `1.00`; anything else is rejected with
    `ERR_WITHHOLD_RATE_MISMATCH`."; and "`APPROVE` requires the snapshotted
    `withhold_rate` to be exactly `0.00`, that is an `effective_uptime_pct` of at
    least 97.00. ... It moves the claim `REVIEW → APPROVED`, sets
    `withheld_amount_cents` to zero and `approved_amount_cents` to
    `requested_amount_cents`."

    Design: Corner/errors/claim_decision_must_match_the_withhold_tier_it_was_reviewed_at
    """
    scenario = setup_operational_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    set_clock("2026-07-15T00:00:00Z")
    money = setup_claim_in_review(
        scenario["station"]["id"],
        scenario["ports"][0]["id"],
        "2026-06-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
        amounts_cents=[2500],
    )
    claim = money["claim"]

    assert float(money["report"]["uptime_pct"]) == 100.00, "the dispenser never faulted"
    assert claim["state"] == "REVIEW"
    assert float(claim["effective_uptime_pct"]) == 100.00
    assert float(claim["withhold_rate"]) == 0.00
    assert claim["requested_amount_cents"] == 2500

    withhold = api_client.decide_reimbursement_claim(
        claim["id"], "WITHHOLD", PROGRAM_ADMIN_HEADERS
    )
    validate_error(withhold, ApiErrorId.ERR_WITHHOLD_RATE_MISMATCH, 422)

    deny = api_client.decide_reimbursement_claim(claim["id"], "DENY", PROGRAM_ADMIN_HEADERS)
    validate_error(deny, ApiErrorId.ERR_WITHHOLD_RATE_MISMATCH, 422)

    still_open = read_claim(claim["id"])
    assert still_open["state"] == "REVIEW", "a refused decision is not a terminal one"
    assert still_open["decided_by_user_id"] is None
    assert still_open["withheld_amount_cents"] is None
    assert still_open["approved_amount_cents"] is None

    decided = validate_success(
        api_client.decide_reimbursement_claim(claim["id"], "APPROVE", PROGRAM_ADMIN_HEADERS)
    )

    assert decided["state"] == "APPROVED"
    assert decided["withheld_amount_cents"] == 0
    assert decided["approved_amount_cents"] == 2500
    assert decided["decided_by_user_id"] == PROGRAM_ADMIN_1


def test_a_goodwill_refund_of_the_entire_charge_clears_the_approval_guard():
    """The guard sits exactly on this value, so a strict comparison fails here.

    PRD §3.9: "`APPROVE` advances `refund_state` from `REQUESTED` to `APPROVED`, but
    only when `refund_amount_cents` does not exceed `session_charged_cents`; a
    refund larger than the charge is rejected with
    `ERR_REFUND_EXCEEDS_SESSION_CHARGE`."  PRD §3.9 on the basis that lands on the
    boundary: "When the gate clears, `refund_amount_cents` is the entire
    `session_charged_cents`, idle fee included."  PRD §3.9 on the pairing: "
    `retained_amount_cents` is always `session_charged_cents` less
    `refund_amount_cents`."  PRD §3.9 on settlement: "`SETTLE` is the support
    agent's action: it advances `refund_state` from `APPROVED` to `SETTLED`, stamps
    `refund_settled_at` from the logical clock, and raises the station's
    `refund_liability_cents` by the refund amount."  PRD §3.9 on the other basis:
    "`refund_amount_cents` is the charged total less that energy value less the
    idle-fee component, floored at zero".

    Design: Corner/errors/refund_approval_guard_is_inclusive_at_the_full_session_charge
    """
    scenario = setup_triaged_complaint_on_open_fault(
        clock="2026-06-10T12:00:00Z",
        station_clock="2026-05-01T00:00:00Z",
        outage_detected_at="2026-06-10T11:00:00Z",
        session_started_at="2026-06-10T10:00:00Z",
        session_ended_at="2026-06-10T12:00:00Z",
        session_energy_kwh=20.500,
        session_price_per_kwh_cents=45,
        session_charged_cents=4200,
        session_idle_fee_cents=200,
        fault_class="CRITICAL",
        fault_code="EVSE-CRIT-01",
        site_code="HS-1",
        station_code="ST-1",
        complaint_count=2,
    )
    station_id = scenario["station"]["id"]
    goodwill_complaint, prorated_complaint = scenario["complaints"]

    assert scenario["outage"]["cleared_at"] is None, "the fault window runs on unbounded"
    assert read_station(station_id)["refund_liability_cents"] == 0

    requested = request_refund(goodwill_complaint["id"], "FULL_SESSION_GOODWILL")

    assert requested["refund_state"] == "REQUESTED"
    assert requested["refund_basis"] == "FULL_SESSION_GOODWILL"
    assert requested["refund_amount_cents"] == 4200, "the whole charge, idle fee included"
    assert requested["retained_amount_cents"] == 0
    assert requested["refund_requested_by_user_id"] == SUPPORT_AGENT_1
    assert_session_money_conservation(requested)

    approved = decide_refund(goodwill_complaint["id"], "APPROVE")

    assert approved["refund_state"] == "APPROVED", "4200 does not exceed 4200"
    assert approved["refund_amount_cents"] == 4200
    assert_session_money_conservation(approved)
    assert read_station(station_id)["refund_liability_cents"] == 0, "approval moves no money"

    settled = act_on_refund_ledger(goodwill_complaint["id"], "SETTLE")

    assert settled["refund_state"] == "SETTLED"
    assert_instant_equals(settled["refund_settled_at"], "2026-06-10T12:00:00Z", "refund_settled_at")
    assert_session_money_conservation(settled)
    assert read_station(station_id)["refund_liability_cents"] == 4200

    counterpart = request_refund(prorated_complaint["id"], "ENERGY_PRORATED")

    assert counterpart["refund_amount_cents"] == 3077, "4200 - round_half_up(20.500 x 45) - 200"
    assert counterpart["retained_amount_cents"] == 1123
    assert_session_money_conservation(counterpart)
    assert read_complaint(goodwill_complaint["id"])["refund_amount_cents"] == 4200
    assert read_station(station_id)["refund_liability_cents"] == 4200, "only settled refunds count"
