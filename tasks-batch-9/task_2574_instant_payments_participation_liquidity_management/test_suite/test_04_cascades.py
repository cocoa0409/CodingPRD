"""Single requests whose consequences travel through five records.

Settling one transfer posts a ledger entry, re-bands the account, opens an alert,
freezes the bank and parks a sibling transfer that the request never named — and
that last hop feeds back into the reservation figure the second hop reported.

Honouring a return runs the reverse chain, but it is not the mirror image: it mints
a new compensating inbound payment instead of rewinding the irrevocable original,
and its last hop is the release waterfall. A reviewer's block is the third chain,
and its blast radius is the customer account rather than the whole bank.
"""

from test_helpers import (
    accept_transfer,
    alpha_scenario,
    assert_account_position,
    assert_alert,
    assert_instant,
    assert_ledger_entry,
    assert_transfer_dimensions,
    assign_review,
    decide_review,
    honor_return_request,
    list_alerts,
    list_ledger_entries,
    list_transfers,
    lodge_return_request,
    read_account,
    read_customer_account,
    read_participant,
    read_transfer,
    register_customer_account,
    send_from_alpha,
    set_clock,
    settle_transfer,
    sole_fraud_review,
)


def _settlement_cascade_world(api, settled_amount, sibling_amount=1_000_000):
    """Alpha with one accepted transfer and one unaccepted sibling, ready to settle."""
    scenario = alpha_scenario(api, with_beta=True)
    primary = send_from_alpha(api, scenario, settled_amount)
    accept_transfer(api, primary["id"])
    set_clock(api, "2026-08-03T13:05:00Z")
    sibling = send_from_alpha(api, scenario, sibling_amount)
    set_clock(api, "2026-08-03T13:10:00Z")
    return scenario, primary, sibling


def test_settlement_walks_from_ledger_entry_to_a_parked_sibling(api):
    """One settlement debit ends in a freeze that parks a transfer nobody named.

    PRD 3.6: "**Fifth**, that freeze parks the bank's remaining `INITIATED` transfers
    into `QUEUED_THROTTLED` with `queued_at` stamped, releasing their reservations."

    Design: Difficulty/transitive_cascade/settlement_cascade_five_hops_to_sibling_parking
    """
    scenario, primary, sibling = _settlement_cascade_world(api, 250_000_000)

    settled = settle_transfer(api, primary["id"])
    assert_transfer_dimensions(settled, "SETTLED", "NONE")
    assert_instant(settled["settled_at"], "2026-08-03T13:10:00Z", "settled_at")
    assert settled["settlement_business_date"] == "2026-08-03"

    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 1
    assert_ledger_entry(
        entries[0],
        entry_type="TRANSFER_DEBIT",
        amount_cents=-250_000_000,
        balance_after_cents=950_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )

    account = read_account(api, scenario.alpha.account_id)
    assert account["alert_tier"] == "RED"
    assert_account_position(
        account,
        current_balance_cents=950_000_000,
        reserved_cents=0,
        available_cents=950_000_000,
        alert_tier="RED",
    )

    alerts = list_alerts(api, scenario.alpha.account_id)
    assert len(alerts) == 1
    assert_alert(
        alerts[0],
        tier="RED",
        status="OPEN",
        threshold_cents=1_000_000_000,
        observed_balance_cents=950_000_000,
    )

    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"

    parked = read_transfer(api, sibling["id"])
    assert_transfer_dimensions(parked, "QUEUED_THROTTLED", "NONE")
    assert_instant(parked["queued_at"], "2026-08-03T13:10:00Z", "queued_at")

    customer = read_customer_account(api, scenario.alpha.customer_account_id)
    assert customer["daily_sent_amount_cents"] == 250_000_000


def test_settlement_into_amber_stops_the_cascade_before_the_parking_hop(api):
    """A throttled bank keeps its in-flight traffic: only a freeze parks transfers.

    PRD 2.9: "**First**, if the new posture is `SEND_FROZEN` or `OFFLINE`, every
    `CreditTransfer` of that participant whose `clearing_status` is `INITIATED` becomes
    `QUEUED_THROTTLED` with `queued_at` stamped, taken in ascending `created_at` order,
    which removes each of them from the reservation input set."

    Design: Difficulty/transitive_cascade/settlement_cascade_five_hops_to_sibling_parking
    """
    scenario, primary, sibling = _settlement_cascade_world(api, 150_000_000)

    settle_transfer(api, primary["id"])

    account = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        account,
        current_balance_cents=1_050_000_000,
        reserved_cents=1_000_000,
        available_cents=1_049_000_000,
        alert_tier="AMBER",
    )

    alerts = list_alerts(api, scenario.alpha.account_id)
    assert len(alerts) == 1
    assert_alert(
        alerts[0],
        tier="AMBER",
        status="OPEN",
        threshold_cents=1_100_000_000,
        observed_balance_cents=1_050_000_000,
    )

    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "THROTTLED"
    still_flying = read_transfer(api, sibling["id"])
    assert_transfer_dimensions(still_flying, "INITIATED", "NONE")
    assert still_flying["queued_at"] is None


def _frozen_world_with_parked_sibling(api):
    """Alpha frozen by a settled 250,000,000-cent transfer, with a parked sibling."""
    scenario, primary, sibling = _settlement_cascade_world(api, 250_000_000)
    settle_transfer(api, primary["id"])
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"
    return scenario, read_transfer(api, primary["id"]), read_transfer(api, sibling["id"])


def test_honouring_a_return_mints_a_credit_and_releases_the_queue(api):
    """The reverse chain ends in the waterfall, and the original row never rewinds.

    PRD 3.8: "**Fifth**, with no non-cleared alert left, the posture derivation lifts
    the participant back to `NORMAL` and the queue release pass runs over its
    `QUEUED_THROTTLED` transfers in the pinned priority order."

    Design: Difficulty/transitive_cascade/return_honor_cascade_five_hops_to_queue_release
    """
    scenario, primary, sibling = _frozen_world_with_parked_sibling(api)

    set_clock(api, "2026-08-03T13:20:00Z")
    request = lodge_return_request(
        api,
        primary["id"],
        scenario.beta.id,
        reason_code="DUPLICATE_PAYMENT",
        returned_amount_cents=250_000_000,
        narrative="Duplicate of instruction INV-4410 already funded.",
    )
    set_clock(api, "2026-08-03T13:25:00Z")
    honored = honor_return_request(api, request["id"])

    assert honored["status"] == "HONORED"
    assert honored["returned_amount_cents"] == 250_000_000
    assert honored["honored_transfer_id"] is not None

    compensating = list_transfers(api, {"compensating_for_transfer_id": primary["id"]})
    assert len(compensating) == 1
    credit = compensating[0]
    assert credit["id"] == honored["honored_transfer_id"]
    assert credit["direction"] == "INBOUND"
    assert credit["rail"] == "INSTANT"
    assert credit["amount_cents"] == 250_000_000
    assert credit["fraud_score"] == 0
    assert_transfer_dimensions(credit, "SETTLED", "NONE")

    original = read_transfer(api, primary["id"])
    assert_transfer_dimensions(original, "SETTLED", "RETURN_HONORED")

    entries = list_ledger_entries(api, scenario.alpha.account_id)
    assert len(entries) == 2
    assert_ledger_entry(
        entries[1],
        entry_type="RETURN_CREDIT",
        amount_cents=250_000_000,
        balance_after_cents=1_200_000_000,
        sequence_no=2,
        business_date="2026-08-03",
    )

    account = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        account,
        current_balance_cents=1_200_000_000,
        reserved_cents=1_000_000,
        available_cents=1_199_000_000,
        alert_tier="GREEN",
    )

    alerts = list_alerts(api, scenario.alpha.account_id)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "CLEARED"
    assert_instant(alerts[0]["cleared_at"], "2026-08-03T13:25:00Z", "cleared_at")

    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"

    released = read_transfer(api, sibling["id"])
    assert_transfer_dimensions(released, "INITIATED", "NONE")
    assert released["queued_at"] is None
    assert read_customer_account(api, scenario.alpha.customer_account_id)["daily_sent_amount_cents"] == 0


def test_partial_return_that_leaves_the_band_red_releases_nothing(api):
    """The credit is worth only the returned amount, so the chain stops at re-banding.

    PRD 3.8: "**Fourth**, the restored balance is re-banded, and if it comes back to
    `GREEN` every alert on that account whose `status` is `OPEN`, `ACKNOWLEDGED` or
    `ESCALATED` becomes `CLEARED` with `cleared_at` stamped."

    Design: Difficulty/transitive_cascade/return_honor_cascade_five_hops_to_queue_release
    """
    scenario, primary, sibling = _frozen_world_with_parked_sibling(api)

    set_clock(api, "2026-08-03T13:20:00Z")
    request = lodge_return_request(
        api,
        primary["id"],
        scenario.beta.id,
        reason_code="DUPLICATE_PAYMENT",
        returned_amount_cents=20_000_000,
    )
    set_clock(api, "2026-08-03T13:25:00Z")
    honor_return_request(api, request["id"])

    account = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        account,
        current_balance_cents=970_000_000,
        reserved_cents=0,
        available_cents=970_000_000,
        alert_tier="RED",
    )

    alerts = list_alerts(api, scenario.alpha.account_id)
    assert len(alerts) == 1
    assert alerts[0]["status"] == "OPEN"
    assert alerts[0]["cleared_at"] is None

    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "SEND_FROZEN"
    assert_transfer_dimensions(read_transfer(api, sibling["id"]), "QUEUED_THROTTLED", "NONE")


def _held_world(api):
    """A held 250,000,000-cent transfer, its queued review and an initiated sibling."""
    scenario = alpha_scenario(
        api, customer_reference="CUST-ALPHA-0002", fraud_risk_baseline=25
    )
    held = send_from_alpha(api, scenario, 250_000_000)
    assert_transfer_dimensions(held, "FRAUD_HOLD", "NONE")
    review = sole_fraud_review(api, held["id"])
    set_clock(api, "2026-08-03T13:05:00Z")
    sibling = send_from_alpha(api, scenario, 200_000)
    return scenario, held, sibling, review


def test_reviewer_block_restricts_the_customer_and_parks_its_siblings(api):
    """The block chain crosses into the customer entity and fans out from there.

    PRD 3.5: "And because that customer is now restricted, every *other* transfer of
    the same customer account still sitting in `INITIATED` is parked into
    `QUEUED_THROTTLED` with `queued_at` stamped, releasing their reservations too — so a
    single blocking decision can free a large amount of previously committed liquidity
    in one request."

    Design: Difficulty/transitive_cascade/fraud_block_cascade_restricts_account_and_parks_siblings
    """
    scenario, held, sibling, review = _held_world(api)

    set_clock(api, "2026-08-03T13:30:00Z")
    assign_review(api, review["id"])
    decided = decide_review(
        api,
        review["id"],
        "BLOCK",
        "Beneficiary institution unverified and amount inconsistent with account history.",
    )

    assert decided["status"] == "BLOCKED"
    assert decided["final_fraud_score"] == 63

    rejected = read_transfer(api, held["id"])
    assert_transfer_dimensions(rejected, "REJECTED", "NONE")
    assert rejected["rejection_reason_code"] == "FRAUD_BLOCK_REVIEW"
    assert rejected["fraud_score"] == 63

    customer = read_customer_account(api, scenario.alpha.customer_account_id)
    assert customer["status"] == "RESTRICTED"
    assert_instant(customer["restricted_at"], "2026-08-03T13:30:00Z", "restricted_at")

    parked = read_transfer(api, sibling["id"])
    assert_transfer_dimensions(parked, "QUEUED_THROTTLED", "NONE")
    assert_instant(parked["queued_at"], "2026-08-03T13:30:00Z", "queued_at")

    account = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        account,
        current_balance_cents=1_200_000_000,
        reserved_cents=0,
        available_cents=1_200_000_000,
        alert_tier="GREEN",
    )
    assert list_ledger_entries(api, scenario.alpha.account_id) == []
    assert read_participant(api, scenario.alpha.id)["operational_posture"] == "NORMAL"


def test_block_fan_out_spares_another_customers_transfer(api):
    """The parking is keyed on the customer account, not on the bank.

    PRD 3.5: "The debtor `CustomerAccount` then flips `ACTIVE -> RESTRICTED` with
    `restricted_at` stamped at the logical clock."

    Design: Difficulty/transitive_cascade/fraud_block_cascade_restricts_account_and_parks_siblings
    """
    scenario, held, sibling, review = _held_world(api)
    bystander_customer = register_customer_account(
        api, scenario.alpha.id, account_reference="CUST-ALPHA-0003", fraud_risk_baseline=20
    )
    bystander = send_from_alpha(
        api, scenario, 300_000, customer_account_id=bystander_customer["id"]
    )

    set_clock(api, "2026-08-03T13:30:00Z")
    assign_review(api, review["id"])
    decide_review(api, review["id"], "BLOCK")

    assert_transfer_dimensions(read_transfer(api, sibling["id"]), "QUEUED_THROTTLED", "NONE")
    assert_transfer_dimensions(read_transfer(api, bystander["id"]), "INITIATED", "NONE")
    assert read_customer_account(api, bystander_customer["id"])["status"] == "ACTIVE"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 300_000
