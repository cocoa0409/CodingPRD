"""Requests refused because of a state that lives on another record entirely.

A return request carries a perfectly valid payload from the right side of the payment and
is still refused, because returnability is a property of the transfer's clearing status.
A reconciliation run is refused or admitted depending on the state of the cycle it names
*and* on the variant asked for, so the gate is a pair rather than a single state. And a
settlement is refused because of a cycle the transfer has no reference to at all — the
cycle is found by business date, and only the settlement hop is gated, not acceptance.
"""

from test_helpers import (
    accept_transfer,
    alpha_and_beta_scenario,
    alpha_scenario,
    assert_instant,
    assert_return_request_shape,
    assert_transfer_dimensions,
    CORE_BANKING_SYSTEM,
    cutoff_cycle,
    ERR_CYCLE_NOT_OPEN,
    ERR_CYCLE_NOT_RECONCILABLE,
    ERR_TRANSFER_NOT_SETTLED,
    list_ledger_entries,
    list_return_requests,
    list_runs_with_meta,
    lodge_return_request,
    NETWORK_OPERATOR,
    open_settlement_cycle,
    PAYMENT_OPERATOR_BETA,
    read_account,
    read_cycle,
    read_transfer,
    reconciliation_run_payload,
    return_request_payload,
    send_from_alpha,
    set_clock,
    settle_transfer,
    submit_reconciliation_run,
    validate_error,
)


def _accepted_but_unsettled(api):
    """Alpha's 250,000,000-cent payment to Beta, accepted and deliberately not settled."""
    scenario = alpha_and_beta_scenario(api)
    transfer = send_from_alpha(api, scenario, 250_000_000)
    accept_transfer(api, transfer["id"])
    set_clock(api, "2026-08-03T13:20:00Z")
    return scenario, transfer


def test_return_request_against_an_accepted_transfer_is_refused(api):
    """The refusal is about the transfer's clearing status, not about the payload.

    PRD 3.8: "The referenced transfer must be in `SETTLED` clearing status — an
    `INITIATED`, `FRAUD_HOLD`, `ACCEPTED`, `QUEUED_THROTTLED`, `DIVERTED` or `REJECTED`
    transfer is simply not returnable, and the attempt is refused with
    `ERR_TRANSFER_NOT_SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/return_request_requires_transfer_settled
    """
    scenario, transfer = _accepted_but_unsettled(api)

    response = api.create_return_request(
        return_request_payload(
            transfer["id"],
            scenario.beta.id,
            reason_code="WRONG_BENEFICIARY",
            returned_amount_cents=250_000_000,
            narrative="Beneficiary unknown at our institution.",
        ),
        PAYMENT_OPERATOR_BETA,
    )
    validate_error(response, ERR_TRANSFER_NOT_SETTLED)

    assert list_return_requests(api) == []
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "ACCEPTED", "NONE")
    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 250_000_000
    assert account["current_balance_cents"] == 1_200_000_000


def test_identical_return_request_succeeds_once_the_transfer_settles(api):
    """Nothing about the request changed, so the transfer's state was the whole reason.

    PRD 3.8: "A successful lodgement creates the request in `REQUESTED` with
    `original_amount_cents` copied from the transfer as it stands, with
    `response_deadline_at` set to the lodgement instant plus 1,440 minutes (twenty-four
    hours), and with a null `decline_reason_code` and null `honored_transfer_id`; the
    transfer's `exception_status` moves `NONE → RETURN_REQUESTED` while its
    `clearing_status` stays `SETTLED`, and the transfer's `version` is incremented."

    Design: Difficulty/cross_entity_state_dependency/return_request_requires_transfer_settled
    """
    scenario, transfer = _accepted_but_unsettled(api)

    set_clock(api, "2026-08-03T13:30:00Z")
    settle_transfer(api, transfer["id"])
    request = lodge_return_request(
        api,
        transfer["id"],
        scenario.beta.id,
        reason_code="WRONG_BENEFICIARY",
        returned_amount_cents=250_000_000,
        narrative="Beneficiary unknown at our institution.",
    )

    assert_return_request_shape(request)
    assert request["status"] == "REQUESTED"
    assert request["original_amount_cents"] == 250_000_000
    assert request["returned_amount_cents"] == 250_000_000
    assert_instant(request["response_deadline_at"], "2026-08-04T13:30:00Z", "response_deadline_at")
    assert request["decline_reason_code"] is None
    assert request["honored_transfer_id"] is None
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_REQUESTED")


def _open_cycle_world(api):
    """Alpha live with an OPEN cycle and no traffic at all, clock at 15:00."""
    scenario = alpha_scenario(api)
    set_clock(api, "2026-08-03T15:00:00Z")
    return scenario


def test_final_run_is_refused_while_the_cycle_is_still_open(api):
    """The gate is the cycle's state, and the refused run leaves the cycle untouched.

    PRD 3.10: "A `FINAL` run requires the cycle to be in `CUTOFF`, `RECONCILING` or
    `OUT_OF_BALANCE`; a `PROVISIONAL` run accepts those three and additionally `OPEN`;
    neither variant is accepted once the cycle is `RECONCILED`, and any mismatch is refused
    with `ERR_CYCLE_NOT_RECONCILABLE`."

    Design: Difficulty/cross_entity_state_dependency/final_reconciliation_requires_cycle_past_cutoff
    """
    scenario = _open_cycle_world(api)

    response = api.create_reconciliation_run(
        reconciliation_run_payload(scenario.cycle_id, scenario.alpha.id, 0, "FINAL"),
        CORE_BANKING_SYSTEM,
    )
    validate_error(response, ERR_CYCLE_NOT_RECONCILABLE)

    runs, _ = list_runs_with_meta(api, {"settlement_cycle_id": scenario.cycle_id})
    assert runs == []
    cycle = read_cycle(api, scenario.cycle_id)
    assert cycle["status"] == "OPEN"
    assert cycle["cutoff_at"] is None


def test_same_payload_as_provisional_is_admitted_against_the_open_cycle(api):
    """The variant is half of the gate: PROVISIONAL accepts what FINAL refuses.

    PRD 3.10: "The `PROVISIONAL` variant's debit side admits the participant's outbound
    transfers in either `ACCEPTED` or `SETTLED`, matching an accepted-but-unsettled
    transfer to the cycle by the UTC date of its `accepted_at` because its
    `settlement_business_date` is still null; it ignores `exception_status` entirely, so an
    already honoured return is still counted as a debit; its `fee_component_cents` is
    always 0; and it never changes the cycle's status."

    Design: Difficulty/cross_entity_state_dependency/final_reconciliation_requires_cycle_past_cutoff
    """
    scenario = _open_cycle_world(api)

    provisional = submit_reconciliation_run(
        api, scenario.cycle_id, scenario.alpha.id, 0, "PROVISIONAL"
    )
    assert provisional["variance_cents"] == 0
    assert provisional["outcome"] == "BALANCED"
    assert provisional["revision"] == 1
    assert read_cycle(api, scenario.cycle_id)["status"] == "OPEN"

    set_clock(api, "2026-08-03T23:00:00Z")
    cutoff_cycle(api, scenario.cycle_id)
    final = submit_reconciliation_run(api, scenario.cycle_id, scenario.alpha.id, 0, "FINAL")
    assert final["outcome"] == "BALANCED"
    assert final["revision"] == 1
    assert read_cycle(api, scenario.cycle_id)["status"] == "RECONCILING"


def _cut_off_cycle_with_accepted_transfer(api):
    """A transfer accepted after its date was cut off, so only settlement is left blocked."""
    scenario = alpha_scenario(api)
    transfer = send_from_alpha(api, scenario, 250_000_000)
    assert_transfer_dimensions(transfer, "INITIATED", "NONE")
    set_clock(api, "2026-08-03T23:00:00Z")
    cutoff_cycle(api, scenario.cycle_id)
    set_clock(api, "2026-08-03T23:05:00Z")
    accepted = accept_transfer(api, transfer["id"])
    assert_transfer_dimensions(accepted, "ACCEPTED", "NONE")
    return scenario, transfer


def test_settlement_is_refused_when_the_dates_cycle_is_no_longer_open(api):
    """The blocking record is found by business date, and acceptance was never gated.

    PRD 3.6: "Settlement advances `ACCEPTED → SETTLED` and requires an open cycle for
    today: a settlement cycle whose `business_date` equals the UTC date of the logical
    clock must exist with `status` `OPEN`, otherwise the attempt is refused with
    `ERR_CYCLE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_open_settlement_cycle
    """
    scenario, transfer = _cut_off_cycle_with_accepted_transfer(api)

    response = api.settle_credit_transfer(transfer["id"], NETWORK_OPERATOR)
    validate_error(response, ERR_CYCLE_NOT_OPEN)

    stalled = read_transfer(api, transfer["id"])
    assert_transfer_dimensions(stalled, "ACCEPTED", "NONE")
    assert stalled["settled_at"] is None
    assert stalled["settlement_business_date"] is None

    cycle = read_cycle(api, scenario.cycle_id)
    assert cycle["status"] == "CUTOFF"
    assert_instant(cycle["cutoff_at"], "2026-08-03T23:00:00Z", "cutoff_at")
    assert cycle["assessed_fee_total_cents"] == 0

    assert list_ledger_entries(api, scenario.alpha.account_id) == []
    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 1_200_000_000
    assert account["reserved_cents"] == 250_000_000


def test_a_freshly_opened_cycle_for_the_new_date_lets_the_same_transfer_settle(api):
    """Resolution is by date and status, so the next date's open cycle unblocks the hop.

    PRD 3.6: "**First**, `settled_at` is stamped and `settlement_business_date` is set to
    the open cycle's `business_date`, and the amount leaves the reservation set."

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_open_settlement_cycle
    """
    scenario, transfer = _cut_off_cycle_with_accepted_transfer(api)

    set_clock(api, "2026-08-04T09:00:00Z")
    next_cycle = open_settlement_cycle(api, "2026-08-04")
    assert next_cycle["status"] == "OPEN"

    settled = settle_transfer(api, transfer["id"])
    assert_transfer_dimensions(settled, "SETTLED", "NONE")
    assert_instant(settled["settled_at"], "2026-08-04T09:00:00Z", "settled_at")
    assert settled["settlement_business_date"] == "2026-08-04"

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 950_000_000
    assert account["reserved_cents"] == 0
    assert read_cycle(api, scenario.cycle_id)["status"] == "CUTOFF"
