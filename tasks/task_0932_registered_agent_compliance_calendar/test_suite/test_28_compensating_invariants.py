"""Quantities that survive a compensating action: money, and the agent of record."""
from test_helpers import (
    ADMIN,
    DE_RULE_FULL,
    OFFICER,
    assert_allocation_split,
    assert_payment_identity,
    capture,
    count_of_record,
    draft_obligation_filing,
    find_by_id,
    new_obligation,
    new_payment,
    propose_appointment,
    read_appointment,
    read_client,
    read_filing,
    read_payment,
    read_registration,
    record_filing_outcome,
    setup_active_home_registration,
    submit_filing,
    accept_appointment,
    validate_paginated,
    validate_success,
)


def _rejected_and_funded_filing():
    """A fully funded annual-report filing that the jurisdiction has rejected."""
    scene = setup_active_home_registration(DE_RULE_FULL)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", expedite_tier="NONE")
    payment = new_payment(scene["client"]["id"], 9900)
    capture(payment["id"], 9900)
    submit_filing(filing["id"])
    record_filing_outcome(filing["id"], "REJECTED", "Officer signature block missing")
    scene["obligation"] = obligation
    scene["filing"] = filing
    scene["payment"] = payment
    return scene


def _transferred_agent_scene():
    """An ACTIVE registration whose incumbent agent has just been superseded."""
    scene = setup_active_home_registration(DE_RULE_FULL)
    registration = read_registration(scene["registration"]["id"])
    successor = propose_appointment(
        registration, provider_name="Keystone Agent Services", appointed_on="2026-06-01"
    )
    accept_appointment(successor["id"])
    scene["successor"] = successor
    return scene


def test_abandoning_returns_the_service_portion_and_conserves_the_payment(api):
    """PRD §3.7: "The server sums the `service_portion_cents` of the forward allocation
    rows that funded this filing — reversal rows are excluded from that sum, as they are
    from the parallel sum of `state_portion_cents` — and creates a reversal
    `PaymentAllocation` against the funding payment with `is_reversal` true,
    `amount_cents` equal to the negated allocated service sum, `state_portion_cents` 0
    and `service_portion_cents` equal to the same negated figure."
    PRD §3.7: "That amount is added to the funding `Payment`'s `refunded_amount_cents`
    and to the owning `Client`'s `credit_balance_cents`, and the payment moves to
    `PARTIALLY_REFUNDED`, or straight to `REFUNDED` when the reversal brings
    `refunded_amount_cents` up to equal `captured_amount_cents`."
    PRD §2.7: "For every `Client`, `credit_balance_cents` equals the sum of
    `refunded_amount_cents` over all of that client's payments, again as an exact
    integer equality."

    Design: Difficulty/compensating_invariant/abandon_reverses_service_portion_and_conserves_payment_funds
    """
    scene = _rejected_and_funded_filing()

    validate_success(api.abandon_filing(scene["filing"]["id"], OFFICER))

    payment = read_payment(scene["payment"]["id"])
    assert payment["captured_amount_cents"] == 9900
    # The 9900 allocation split 5000 state / 4900 service; only the service half is
    # compensated, leaving 9900 - 4900 = 5000 still allocated.
    assert payment["allocated_amount_cents"] == 5000
    assert payment["unallocated_amount_cents"] == 0
    assert payment["refunded_amount_cents"] == 4900
    assert_payment_identity(payment)
    assert payment["status"] == "PARTIALLY_REFUNDED"

    assert read_client(scene["client"]["id"])["credit_balance_cents"] == 4900


def test_the_abandoned_filing_keeps_the_state_portion_and_shows_the_reversal_row(api):
    """PRD §3.7: "On success the filing moves `REJECTED → ABANDONED` and its `version`
    increases by 1, and the service money it consumed is compensated back to the
    client."
    PRD §3.7: "The allocated state sum is forfeited on this path exactly as it is on the
    refile path — the state portion is never returned under either."
    PRD §3.7: "and sets `refile_window_end` to `outcome_recorded_on` plus 15 calendar
    days."

    Design: Difficulty/compensating_invariant/abandon_reverses_service_portion_and_conserves_payment_funds
    """
    scene = _rejected_and_funded_filing()

    validate_success(api.abandon_filing(scene["filing"]["id"], OFFICER))

    filing = read_filing(scene["filing"]["id"])
    assert filing["status"] == "ABANDONED"
    # Rejected at the default clock date 2026-05-01, plus 15 calendar days.
    assert filing["refile_window_end"] == "2026-05-16"
    assert filing["paid_amount_cents"] == 5000

    rows, meta = validate_paginated(
        api.list_payment_allocations(scene["payment"]["id"], ADMIN)
    )
    assert meta["total_count"] == 2
    reversals = [row for row in rows if row["is_reversal"] is True]
    assert len(reversals) == 1
    reversal = reversals[0]
    assert reversal["amount_cents"] == -4900
    assert reversal["state_portion_cents"] == 0
    assert reversal["service_portion_cents"] == -4900
    assert_allocation_split(reversal)


def test_a_provider_transfer_retires_the_incumbent_and_names_its_successor(api):
    """PRD §3.3: "On success, any sibling appointment on the same registration that was
    in status `APPOINTED` is moved to `TRANSFERRED_OUT` and has its
    `superseded_by_appointment_id` set to the accepted appointment's `id` and its
    `of_record` set to false; that sibling's own `version` increases by 1 as well."
    PRD §3.3: "The agent-of-record selection is then re-run across the registration,
    refreshing `agent_of_record_id` on the registration and `of_record` on every
    appointment."

    Design: Difficulty/compensating_invariant/agent_transfer_conserves_exactly_one_of_record
    """
    scene = _transferred_agent_scene()

    incumbent = read_appointment(scene["appointment"]["id"])
    successor = read_appointment(scene["successor"]["id"])

    assert incumbent["status"] == "TRANSFERRED_OUT"
    assert incumbent["of_record"] is False
    assert incumbent["superseded_by_appointment_id"] == scene["successor"]["id"]
    assert successor["status"] == "APPOINTED"
    assert successor["of_record"] is True
    assert (
        read_registration(scene["registration"]["id"])["agent_of_record_id"]
        == scene["successor"]["id"]
    )


def test_exactly_one_appointment_is_of_record_after_the_transfer(api):
    """PRD §3.3: "For every registration in status `ACTIVE` or `DELINQUENT`, exactly one
    appointment is of record before a provider transfer and exactly one is of record
    after it — that count is a conserved quantity of the transfer."
    PRD §3.3: "Because `superseded_by_appointment_id` points from the outgoing
    appointment to its successor, the appointment list endpoint's
    `superseded_by_appointment_id` filter walks the transfer chain; it also accepts
    `registration_id` and `status` filters."

    Design: Difficulty/compensating_invariant/agent_transfer_conserves_exactly_one_of_record
    """
    scene = _transferred_agent_scene()

    rows, meta = validate_paginated(
        api.list_agent_appointments(
            ADMIN, params={"registration_id": scene["registration"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert count_of_record(rows) == 1

    chained, chained_meta = validate_paginated(
        api.list_agent_appointments(
            ADMIN, params={"superseded_by_appointment_id": scene["successor"]["id"]}
        )
    )
    assert chained_meta["total_count"] == 1
    assert find_by_id(chained, scene["appointment"]["id"]) is not None
