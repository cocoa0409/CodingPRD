"""Compensating actions must return derived aggregates to their prior values."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    file_election,
    read_agreement,
    read_distributor,
    read_election,
    read_negotiation,
    read_offer,
    read_station,
    setup_draft_election,
    setup_issued_settlement,
    setup_submitted_station_offer,
    validate_error,
    validate_success,
    void_settlement_payload,
    withdraw_election_payload,
)


def test_voiding_a_settlement_restores_the_agreement_lifetime_ledger(api):
    """The voided row drops out of both lifetime sums, back to the pre-issuance value.

    PRD §3.9: "Voiding moves `status` to `VOIDED`, and because the agreement's
    lifetime totals sum only over settlements in `ISSUED` or `TRUED_UP`, this row's
    amounts drop straight out of both `lifetime_gross_fee_cents` and
    `lifetime_net_retained_cents`, restoring the ledger to exactly the value it held
    before that settlement was issued."

    Design: Difficulty/compensating_invariant/settlement_void_restores_agreement_lifetime_money_ledger
    """
    ctx = setup_issued_settlement()
    assert ctx["settlement"]["gross_fee_cents"] == 25000000
    assert ctx["settlement"]["net_retained_cents"] == 11250000
    ledger = read_agreement(ctx["agreement"]["id"])
    assert ledger["lifetime_gross_fee_cents"] == 25000000
    assert ledger["lifetime_net_retained_cents"] == 11250000

    response = api.void_fee_settlement(
        ctx["settlement"]["id"],
        void_settlement_payload(),
        TEST_USERS["second_group_counsel_headers"],
    )
    voided = validate_success(response, 200)

    assert voided["status"] == "VOIDED"
    assert voided["gross_fee_cents"] == 25000000
    assert voided["net_retained_cents"] == 11250000

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 0
    assert agreement["lifetime_net_retained_cents"] == 0
    assert read_distributor(ctx["distributor"]["id"])["open_true_up_count"] == 0


def test_the_issuing_counsel_may_not_void_their_own_settlement(api):
    """Segregation of duties blocks the void and leaves the ledger where it was.

    PRD §3.9: "The voiding counsel's `X-User-ID` must differ from the settlement's
    `issued_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/compensating_invariant/settlement_void_restores_agreement_lifetime_money_ledger
    """
    ctx = setup_issued_settlement()
    assert ctx["settlement"]["issued_by_user_id"] == "counsel-1"

    response = api.void_fee_settlement(
        ctx["settlement"]["id"],
        void_settlement_payload(),
        TEST_USERS["group_counsel_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 25000000
    assert agreement["lifetime_net_retained_cents"] == 11250000


def test_withdrawing_a_filed_election_returns_the_counter_to_its_prior_value(api):
    """Filing raises filed_election_count and withdrawal puts it back.

    PRD §3.3: "The supplied reason is captured on the election as
    `withdrawal_reason` and `filed_at_utc` is cleared back to null, and the station's
    `filed_election_count` is recomputed - which, because filing raised it and
    withdrawal lowers it, returns the count to exactly its pre-filing value."

    Design: Difficulty/compensating_invariant/election_withdraw_restores_station_filed_election_count
    """
    ctx = setup_draft_election()
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0

    filed = file_election(ctx["election"]["id"], ctx["station"]["id"])
    assert filed["status"] == "NEGOTIATING"
    assert filed["filed_at_utc"] == "2026-08-01T00:00:00Z"
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 1

    response = api.withdraw_election(
        ctx["election"]["id"],
        withdraw_election_payload(),
        ctx["negotiator_headers"],
    )
    withdrawn = validate_success(response, 200)

    assert withdrawn["status"] == "DRAFT"
    assert withdrawn["filed_at_utc"] is None
    assert withdrawn["withdrawal_reason"] == (
        "Station group elects must-carry in this market instead"
    )
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0


def test_withdrawal_cascades_to_the_negotiation_and_its_outstanding_offer(api):
    """Cancelling the negotiation expires every offer still on the table.

    PRD §3.3: "On the `NEGOTIATING -> DRAFT` branch, a three-level cascade follows:
    the negotiation created by filing moves to `CANCELLED`; because that negotiation
    is now `CANCELLED`, every offer on it still in `SUBMITTED` moves to `EXPIRED` and
    every blackout notice on it still in `SERVED` moves to `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/election_withdraw_restores_station_filed_election_count
    """
    ctx = setup_submitted_station_offer()
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 1

    response = api.withdraw_election(
        ctx["election"]["id"],
        withdraw_election_payload(),
        ctx["negotiator_headers"],
    )
    validate_success(response, 200)

    assert read_election(ctx["election"]["id"])["status"] == "DRAFT"
    assert read_negotiation(ctx["negotiation"]["id"])["status"] == "CANCELLED"
    assert read_offer(ctx["offer"]["id"])["status"] == "EXPIRED"
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0
