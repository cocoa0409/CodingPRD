"""
Price negotiation on a single bid, and the three work streams of a servicing
transfer.

The first half follows one bid row around the counter / revise loop: the desk
counters, the buyer revises, the desk counters again, and the round counter is
the only thing that ever stops the cycle. The second half drives one servicing
transfer along its notice, data and pipeline dimensions in an order the desk did
not plan for, undoes the custodial sweep, and checks what the transfer will and
will not let the desk complete.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_MAX_NEGOTIATION_ROUNDS, ERR_TRANSFER_NOT_READY,
    assert_dimensions, assert_readiness, assert_status,
    validate_error,
)

# The desk's three successive counters on the same bid.
COUNTER_ROUND_1_BPS = 126
COUNTER_ROUND_2_BPS = 128
COUNTER_ROUND_3_BPS = 130
COUNTER_EXPIRES_AT = "2026-08-10T00:00:00Z"

# Pool T carries 40000200 cents of tape unpaid balance, so a revised offer of
# 121 bps prices at 484002 cents and one of 124 bps at 496002 cents.
REVISED_121_VALUE_CENTS = 484002
REVISED_124_VALUE_CENTS = 496002


def _advance_pipeline(api: ApiClient, env: JsonDict) -> JsonDict:
    """Hand the loss-mitigation pipeline over to the acquiring servicer."""
    return F.transfer_pipeline(api, env["transfer_id"], env["buyer_id"])


def _advance_notices(api: ApiClient, env: JsonDict) -> JsonDict:
    """Notice every borrower on the awarded tape and attest compliance."""
    F.send_notices(api, env["transfer_id"], env["included_loan_ids"],
                   env["seller_id"], effective_date=env["transfer_date"])
    return F.attest_notices(api, env["transfer_id"])


def _advance_data(api: ApiClient, env: JsonDict) -> tuple:
    """Walk the data dimension: mapping template, custodial sweep, reconcile."""
    mapped = F.map_data(api, env["transfer_id"], env["buyer_id"])
    swept = F.map_escrow(api, env["transfer_id"], env["buyer_id"])
    reconciled = F.reconcile(api, env["transfer_id"], env["buyer_id"])
    return mapped, swept, reconciled


def _advance_data_to_sweep(api: ApiClient, env: JsonDict) -> JsonDict:
    """
    Walk the data dimension only as far as the custodial sweep, leaving
    `data_status` at `ESCROW_MAPPED` — the one state a rollback accepts, since
    PRD refuses "a rollback attempted while `data_status` is anything other
    than `ESCROW_MAPPED`" with `ERR_TRANSFER_INVALID_STATE`.
    """
    F.map_data(api, env["transfer_id"], env["buyer_id"])
    return F.map_escrow(api, env["transfer_id"], env["buyer_id"])


def _negotiate_to_countered_round_three(api: ApiClient,
                                        env: JsonDict) -> JsonDict:
    """
    Counter, revise, counter, revise, counter — leaving one bid row sitting in
    its third negotiation round with the desk's latest counter on the table.
    """
    F.counter(api, env["bid_id"], COUNTER_ROUND_1_BPS, COUNTER_EXPIRES_AT)
    F.revise(api, env["bid_id"], env["buyer_id"], 121)
    F.counter(api, env["bid_id"], COUNTER_ROUND_2_BPS, COUNTER_EXPIRES_AT)
    F.revise(api, env["bid_id"], env["buyer_id"], 124)
    return F.counter(api, env["bid_id"], COUNTER_ROUND_3_BPS,
                     COUNTER_EXPIRES_AT)


def test_counter_and_revise_cycle_advances_round_number(api, live_bid):
    """
    One bid row loops between COUNTERED and REVISED, and only the round counter
    moves as it does.

    PRD: "An accepted revision replaces `price_bps` and `holdback_pct` from the request, recomputes `bid_value_cents` on the same single-rounding basis, increments `round_number` by 1, clears `counter_price_bps` and `counter_expires_at` back to null, moves the bid `COUNTERED → REVISED`, and increments its `version` by 1."

    Design: Difficulty/non_linear_state_machine/bid_negotiation_cycles_countered_and_revised_until_round_cap
    """
    env = live_bid
    submitted = F.read_bid(api, env["bid_id"])
    assert_status(submitted, "SUBMITTED")
    assert submitted["round_number"] == 1

    countered_once = F.counter(api, env["bid_id"], COUNTER_ROUND_1_BPS,
                               COUNTER_EXPIRES_AT)
    assert_status(countered_once, "COUNTERED")
    assert countered_once["counter_price_bps"] == COUNTER_ROUND_1_BPS
    assert countered_once["round_number"] == 1

    revised_round_two = F.revise(api, env["bid_id"], env["buyer_id"], 121)
    assert_status(revised_round_two, "REVISED")
    assert revised_round_two["round_number"] == 2
    assert revised_round_two["bid_value_cents"] == REVISED_121_VALUE_CENTS

    countered_twice = F.counter(api, env["bid_id"], COUNTER_ROUND_2_BPS,
                                COUNTER_EXPIRES_AT)
    assert_status(countered_twice, "COUNTERED")
    assert countered_twice["counter_price_bps"] == COUNTER_ROUND_2_BPS
    assert countered_twice["round_number"] == 2

    revised_round_three = F.revise(api, env["bid_id"], env["buyer_id"], 124)
    assert_status(revised_round_three, "REVISED")
    assert revised_round_three["round_number"] == 3
    assert revised_round_three["bid_value_cents"] == REVISED_124_VALUE_CENTS


def test_revision_clears_counter_fields_so_the_next_counter_restamps(
        api, live_bid):
    """
    The counter terms are stamped on the bid, wiped by the buyer's revision, and
    stamped afresh by the desk's next counter.

    PRD: "Countering moves the bid to `COUNTERED`, stamps both fields from the request, leaves `round_number` where it was, and increments the bid's `version` by 1."

    Design: Difficulty/non_linear_state_machine/bid_negotiation_cycles_countered_and_revised_until_round_cap
    """
    env = live_bid
    countered = F.counter(api, env["bid_id"], COUNTER_ROUND_1_BPS,
                          COUNTER_EXPIRES_AT)
    assert countered["counter_price_bps"] == COUNTER_ROUND_1_BPS
    assert countered["counter_expires_at"] is not None
    assert countered["round_number"] == 1

    revised = F.revise(api, env["bid_id"], env["buyer_id"], 121)
    assert revised["counter_price_bps"] is None
    assert revised["counter_expires_at"] is None

    stored = F.read_bid(api, env["bid_id"])
    assert stored["counter_price_bps"] is None
    assert stored["counter_expires_at"] is None

    countered_again = F.counter(api, env["bid_id"], COUNTER_ROUND_2_BPS,
                                COUNTER_EXPIRES_AT)
    assert_status(countered_again, "COUNTERED")
    assert countered_again["counter_price_bps"] == COUNTER_ROUND_2_BPS
    assert countered_again["counter_expires_at"] is not None
    assert countered_again["round_number"] == 2


def test_revision_from_round_three_refused_for_the_negotiation_ceiling(
        api, live_bid):
    """
    A third counter is still allowed at the round cap, but the buyer can no
    longer answer it.

    PRD: "The buyer answers by revising: the acting `X-User-ID` must equal the bid's `bidder_id`, the bid must be `COUNTERED`, the package must still be `PUBLISHED`, the logical clock must be strictly before `counter_expires_at` (otherwise `ERR_BID_DEADLINE_PASSED`), and `round_number` must be strictly less than 3 — a revision filed from round 3 exceeds the three-round negotiation ceiling and is refused with `ERR_MAX_NEGOTIATION_ROUNDS` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/bid_negotiation_cycles_countered_and_revised_until_round_cap
    """
    env = live_bid
    countered_at_cap = _negotiate_to_countered_round_three(api, env)
    assert_status(countered_at_cap, "COUNTERED")
    assert countered_at_cap["round_number"] == 3
    assert countered_at_cap["counter_price_bps"] == COUNTER_ROUND_3_BPS

    response = api.revise_bid(
        env["bid_id"], {"price_bps": 127, "holdback_pct": 6},
        U.make_buyer_headers(env["buyer_id"]))
    validate_error(response, ERR_MAX_NEGOTIATION_ROUNDS, 409)


def test_refused_revision_leaves_the_bid_and_package_untouched(api, live_bid):
    """
    The refusal at the round ceiling writes nothing: the bid keeps the desk's
    third counter and the whole cycle produced exactly one bid row.

    PRD: "Rejected requests never mutate anything."

    Design: Difficulty/non_linear_state_machine/bid_negotiation_cycles_countered_and_revised_until_round_cap
    """
    env = live_bid
    countered_at_cap = _negotiate_to_countered_round_three(api, env)
    version_before = countered_at_cap["version"]

    response = api.revise_bid(
        env["bid_id"], {"price_bps": 127, "holdback_pct": 6},
        U.make_buyer_headers(env["buyer_id"]))
    validate_error(response, ERR_MAX_NEGOTIATION_ROUNDS, 409)

    stored = F.read_bid(api, env["bid_id"])
    assert_status(stored, "COUNTERED")
    assert stored["round_number"] == 3
    assert stored["counter_price_bps"] == COUNTER_ROUND_3_BPS
    assert stored["price_bps"] == 124
    assert stored["bid_value_cents"] == REVISED_124_VALUE_CENTS
    assert stored["version"] == version_before

    package = F.read_package(api, env["package_id"])
    assert package["bid_count"] == 1


def test_settlement_opens_all_three_dimensions_not_started(api, settled_trade):
    """
    Settlement opens the transfer with every work stream at its starting value,
    so its derived readiness reads NOT_READY.

    PRD: "Settlement also opens the operational work: exactly one `ServicingTransfer` is created for the agreement, recording its `purchase_agreement_id` and a `transfer_date` copied from the agreement, in overall status `IN_PROGRESS`, with `notice_status`, `data_status` and `pipeline_status` all `NOT_STARTED`, `readiness` `NOT_READY`, `escrow_transferred_cents` and `suspense_transferred_cents` at 0, `notice_count`, `late_notice_count`, `loss_mit_pipeline_count` and `transferred_loan_count` at 0, `mapping_scheme` null, and its onboarding blackout materialised as `onboarding_window_start` (the transfer date less 30 calendar days, inclusive) and `onboarding_window_end` (the transfer date plus 30 calendar days, inclusive)."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    transfer = F.read_transfer(api, settled_trade["transfer_id"])
    assert_status(transfer, "IN_PROGRESS")
    assert_dimensions(transfer, notice="NOT_STARTED", data="NOT_STARTED",
                      pipeline="NOT_STARTED")
    assert_readiness(transfer, "NOT_READY")


def test_pipeline_dimension_advances_first_and_alone(api, settled_trade):
    """
    Handing over the loss-mitigation pipeline before anything else moves that
    dimension only.

    PRD: "This dimension is genuinely independent: it may be driven first, last or anywhere in between, with identical results."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    env = settled_trade
    after_pipeline = _advance_pipeline(api, env)
    assert_dimensions(after_pipeline, notice="NOT_STARTED",
                      data="NOT_STARTED", pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(after_pipeline, "NOT_READY")

    stored = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(stored, notice="NOT_STARTED", data="NOT_STARTED",
                      pipeline="PIPELINE_TRANSFERRED")
    assert_status(stored, "IN_PROGRESS")


def test_notice_dimension_closes_with_no_data_mapping_yet(api, settled_trade):
    """
    Attestation closes the notice dimension while the data dimension has not
    started, and two of three terminal dimensions is still not ready.

    PRD: "A derived `readiness` reads `READY` if and only if `notice_status` is `NOTICES_ATTESTED` **and** `data_status` is `RECONCILED` **and** `pipeline_status` is `PIPELINE_TRANSFERRED`; in every other combination it reads `NOT_READY`."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    env = settled_trade
    _advance_pipeline(api, env)
    after_notices = _advance_notices(api, env)
    assert_dimensions(after_notices, notice="NOTICES_ATTESTED",
                      data="NOT_STARTED", pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(after_notices, "NOT_READY")


def test_data_dimension_ladder_turns_readiness_ready_last(api, settled_trade):
    """
    The data work stream climbs its own three-step ladder, and readiness flips to
    READY exactly when it reaches the top.

    PRD: "`data_status` runs `NOT_STARTED` → `MAPPED` → `ESCROW_MAPPED` → `RECONCILED`, with a compensating edge from `ESCROW_MAPPED` back to `MAPPED`."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    env = settled_trade
    _advance_pipeline(api, env)
    _advance_notices(api, env)

    mapped, swept, reconciled = _advance_data(api, env)
    assert_dimensions(mapped, notice="NOTICES_ATTESTED", data="MAPPED",
                      pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(mapped, "NOT_READY")

    assert_dimensions(swept, data="ESCROW_MAPPED")
    assert_readiness(swept, "NOT_READY")

    assert_dimensions(reconciled, notice="NOTICES_ATTESTED",
                      data="RECONCILED", pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(reconciled, "READY")


def test_rollback_of_the_custodial_sweep_demotes_only_the_data_dimension(
        api, settled_trade):
    """
    Undoing the custodial sweep walks the data dimension backwards and takes
    readiness with it, leaving the other two work streams alone.

    PRD: "A rollback, which takes a free-text `reason`, restores each included tape loan's `escrow_balance_cents` and `suspense_balance_cents` from their `escrow_balance_at_mapping_cents` and `suspense_balance_at_mapping_cents` snapshots, resets both `escrow_transferred_cents` and `suspense_transferred_cents` to 0, moves `data_status` `ESCROW_MAPPED → MAPPED`, re-derives `readiness` to `NOT_READY`, and increments the transfer's `version` by 1."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    env = settled_trade
    _advance_pipeline(api, env)
    _advance_notices(api, env)
    _advance_data_to_sweep(api, env)

    rolled_back = F.rollback_escrow(api, env["transfer_id"], env["buyer_id"])
    assert_dimensions(rolled_back, notice="NOTICES_ATTESTED", data="MAPPED",
                      pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(rolled_back, "NOT_READY")

    stored = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(stored, notice="NOTICES_ATTESTED", data="MAPPED",
                      pipeline="PIPELINE_TRANSFERRED")
    assert_readiness(stored, "NOT_READY")


def test_completion_refused_until_the_rolled_back_dimension_is_restored(
        api, settled_trade):
    """
    On the transfer date a transfer whose data dimension was rolled back refuses
    to complete, and completes once the sweep and reconciliation are redone.

    PRD: "Completion requires `readiness` to be `READY` — any dimension short of its terminal value is refused with `ERR_TRANSFER_NOT_READY` (HTTP 409) — and requires the current logical clock date to have reached the agreement's `transfer_date`; a transfer cannot complete before its own effective date."

    Design: Difficulty/non_linear_state_machine/servicing_transfer_drives_three_parallel_dimensions_out_of_order
    """
    env = settled_trade
    _advance_pipeline(api, env)
    _advance_notices(api, env)
    _advance_data_to_sweep(api, env)
    F.rollback_escrow(api, env["transfer_id"], env["buyer_id"])
    F.set_clock(api, C.CLOCK_TRANSFER_DAY)

    response = api.complete_transfer(env["transfer_id"], U.MANAGER)
    validate_error(response, ERR_TRANSFER_NOT_READY, 409)

    blocked = F.read_transfer(api, env["transfer_id"])
    assert_status(blocked, "IN_PROGRESS")
    assert blocked["completed_at"] is None
    assert_readiness(blocked, "NOT_READY")

    F.map_escrow(api, env["transfer_id"], env["buyer_id"])
    restored = F.reconcile(api, env["transfer_id"], env["buyer_id"])
    assert_readiness(restored, "READY")

    completed = F.complete_transfer(api, env["transfer_id"])
    assert_status(completed, "COMPLETED")
    assert completed["completed_at"] is not None
