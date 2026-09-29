"""
Lifecycle machines of the transfer desk: birth states, the edges that are legal
and the edges that are not.

The desk is a chain of small state machines — a servicing portfolio, a bid
package, a bid, an approval request, a purchase agreement, a servicing transfer
with its three work streams, an error resolution case and a hedge position. This
module pins where each of them starts, which forward transitions carry side
effects with them (the tape lock freezing the pricing basis, a denied consent
unwinding the marketing chain, a conditional consent re-sizing the holdback, the
bounded reopen loop escalating), and which transitions must be refused: adding a
loan after the lock, valuing an unlocked pool, publishing an unstratified
package, replaying a decision, working a portfolio that has already transferred
and attesting notices that do not yet cover the tape.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_APPROVAL_ALREADY_DECIDED,
    ERR_CASE_INVALID_STATE,
    ERR_CONDITION_WAIVER_REQUIRED,
    ERR_MAX_REOPENS_EXCEEDED,
    ERR_NOTICE_COMPLIANCE_INCOMPLETE,
    ERR_PACKAGE_INVALID_STATE,
    ERR_TAPE_LOCKED,
    ERR_TAPE_NOT_LOCKED,
    ERR_TRANSFER_INVALID_STATE,
    assert_holdback_split,
    assert_readiness,
    assert_status,
    build_approved_agreement,
    build_awarded_trade,
    build_completed_transfer,
    build_locked_portfolio,
    build_valued_portfolio,
    data_of,
    rows_of,
    round_half_up,
    validate_error,
)

# Pool T at 118 basis points, cut by state into four single-loan strata.
POOL_T_PURCHASE_PRICE_CENTS = 472004
POOL_T_HOLDBACK_AT_SIX_PCT_CENTS = 28320
POOL_T_WIRE_AT_SIX_PCT_CENTS = 443684
POOL_T_CONDITIONAL_HOLDBACK_CENTS = 70801
POOL_T_CONDITIONAL_WIRE_CENTS = 401203
POOL_T_RESERVE_CENTS = 162997

CONDITION_TEXT = "servicer must remediate the two open escrow analyses"


# ---------------------------------------------------------------------------
# Where the machines start
# ---------------------------------------------------------------------------
def test_new_portfolio_starts_in_draft_with_zeroed_aggregates(api: ApiClient,
                                                              desk: JsonDict):
    """
    A freshly opened servicing portfolio is born DRAFT with every aggregate at
    zero and no lock stamp.

    PRD: "A new portfolio starts in `DRAFT` with `loan_count`, `total_upb_cents` and `custodial_funds_total_cents` at 0, `weighted_avg_note_rate_pct` at 0.0000, `valuation_freshness` at `NONE` and `tape_locked_at` null."

    Design: Corner/state_machines/portfolio_and_children_start_in_their_declared_initial_states
    """
    portfolio = F.create_portfolio(api, desk["seller_id"], name="Pool-T")

    assert_status(portfolio, "DRAFT")
    assert portfolio["loan_count"] == 0
    assert portfolio["total_upb_cents"] == 0
    assert portfolio["custodial_funds_total_cents"] == 0
    assert float(portfolio["weighted_avg_note_rate_pct"]) == 0.0
    assert portfolio["valuation_freshness"] == "NONE"
    assert portfolio["tape_locked_at"] is None
    assert portfolio["version"] == 1


def test_new_hedge_position_starts_open_at_the_active_curve(api: ApiClient,
                                                            desk: JsonDict):
    """
    A hedge opened against the servicing asset starts OPEN, marked flat, with
    its entry rate taken from the snapshot that is active at that moment.

    PRD: "The position records `entry_base_rate_bps` from the `base_rate_bps` of the snapshot active at that moment — so opening a hedge requires an active curve, and fails with `ERR_NO_ACTIVE_RATE_CURVE` when none exists — starts `OPEN` with `mark_to_market_cents` at 0, and leaves `close_base_rate_bps`, `realized_pnl_cents` and `closed_at` null."

    Design: Corner/state_machines/portfolio_and_children_start_in_their_declared_initial_states
    """
    portfolio = F.create_portfolio(api, desk["seller_id"], name="Pool-T")

    position = F.open_hedge(api, portfolio["id"],
                            instrument="SWAPTION_RECEIVER",
                            notional_cents=260000, hedge_ratio_pct=60)

    assert_status(position, "OPEN")
    assert position["entry_base_rate_bps"] == C.CURVE_C1["base_rate_bps"]
    assert position["mark_to_market_cents"] == 0
    assert position["close_base_rate_bps"] is None
    assert position["realized_pnl_cents"] is None
    assert position["closed_at"] is None


def test_new_bid_starts_submitted_in_the_first_round(api: ApiClient,
                                                     published_package: JsonDict):
    """
    A bid filed on a published package is born SUBMITTED in round one with no
    counter terms on it.

    PRD: "A new bid is created in `SUBMITTED` status with `round_number` at 1 and `counter_price_bps` and `counter_expires_at` null; the package's `bid_count` increments and the package's `version` increments by 1."

    Design: Corner/state_machines/portfolio_and_children_start_in_their_declared_initial_states
    """
    env = published_package

    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       env["package_version"], price_bps=118, holdback_pct=6)

    assert_status(bid, "SUBMITTED")
    assert bid["round_number"] == 1
    assert bid["counter_price_bps"] is None
    assert bid["counter_expires_at"] is None
    assert bid["version"] == 1


def test_new_approval_request_is_born_pending_and_undecided(
        api: ApiClient, awarded_trade: JsonDict):
    """
    A consent prerequisite raised on a drafted agreement starts PENDING with no
    decision recorded against it.

    PRD: "A request is born `PENDING` with `decided_by_user_id`, `decided_at` and `condition_text` null."

    Design: Corner/state_machines/portfolio_and_children_start_in_their_declared_initial_states
    """
    request = F.create_approval_request(api, awarded_trade["agreement_id"],
                                        approver_type="AGENCY",
                                        agency_type="FNMA")

    assert_status(request, "PENDING")
    assert request["decided_by_user_id"] is None
    assert request["decided_at"] is None
    assert request["condition_text"] is None


# ---------------------------------------------------------------------------
# The tape lock: the immutability boundary for loan-level data
# ---------------------------------------------------------------------------
def test_lock_tape_freezes_the_pool_aggregates_and_stamps_the_lock(
        api: ApiClient):
    """
    Locking the tape moves the pool DRAFT -> TAPE_LOCKED, stamps the lock from
    the logical clock and freezes the four aggregates as the pricing basis.

    PRD: "Locking the tape requires the acting `X-User-ID` to equal the portfolio's `seller_id` and requires the pool to hold at least one loan; it moves the portfolio `DRAFT → TAPE_LOCKED`, stamps `tape_locked_at` from the logical clock, recomputes all four aggregates and freezes them as **the pricing basis** for everything downstream, and increments `version` by 1."

    Design: Corner/state_machines/lock_tape_freezes_the_portfolio_totals_and_stamps_the_lock
    """
    env = build_locked_portfolio(api, lock=False)

    locked = F.lock_tape(api, env["portfolio_id"], env["seller_id"])

    assert_status(locked, "TAPE_LOCKED")
    assert locked["tape_locked_at"] == "2026-08-01T00:00:00.000Z"
    assert locked["loan_count"] == 4
    assert locked["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert locked["custodial_funds_total_cents"] == C.POOL_T_CUSTODIAL_FUNDS_CENTS
    # One bump per loan insert plus one for the lock, from the initial 1.
    assert locked["version"] == 6


def test_lock_tape_leaves_the_pool_unvalued(api: ApiClient,
                                            locked_portfolio: JsonDict):
    """
    Freezing the tape does not value it: with no eligible run on the pool its
    valuation freshness still reads NONE.

    PRD: "The portfolio's `valuation_freshness` follows directly: `NONE` when there is no eligible run at all, `CURRENT` when the chosen run is `COMPLETED`, and `STALE` when the chosen run is `STALE`."

    Design: Corner/state_machines/lock_tape_freezes_the_portfolio_totals_and_stamps_the_lock
    """
    portfolio_id = locked_portfolio["portfolio_id"]

    portfolio = F.read_portfolio(api, portfolio_id)

    assert_status(portfolio, "TAPE_LOCKED")
    assert portfolio["valuation_freshness"] == "NONE"
    runs = rows_of(
        api.list_valuation_runs(U.ANALYST, {"portfolio_id": portfolio_id})
    )
    assert runs == []


def test_adding_a_loan_after_the_tape_lock_is_refused(
        api: ApiClient, locked_portfolio: JsonDict):
    """
    A locked pool refuses a new loan, so the frozen unpaid balance cannot drift
    under a reserve price stamped later.

    PRD: "Loans are added one at a time by the owning seller, and only while the portfolio is still `DRAFT`; an attempt on a portfolio that has moved on is refused with `ERR_TAPE_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/adding_a_loan_after_tape_lock_is_rejected
    """
    env = locked_portfolio
    late_loan = dict(C.LOANS_T[0])
    late_loan.update({"loan_number": "T-0005", "state_code": "AZ"})

    response = api.create_loan(env["portfolio_id"], late_loan,
                               env["seller_headers"])

    validate_error(response, ERR_TAPE_LOCKED)
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["loan_count"] == 4
    assert portfolio["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert portfolio["version"] == 6
    assert len(F.list_loans(api, env["portfolio_id"])) == 4


# ---------------------------------------------------------------------------
# Valuation needs a frozen tape
# ---------------------------------------------------------------------------
def test_valuation_run_on_a_draft_pool_is_refused(api: ApiClient):
    """
    A pool whose composition can still move is not a valuation basis, so a run
    filed against a DRAFT portfolio is refused and no run row is created.

    PRD: "The portfolio must be `TAPE_LOCKED`: a run against a portfolio still in `DRAFT`, or one already `UNDER_CONTRACT` or `TRANSFERRED`, is refused with `ERR_TAPE_NOT_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/valuation_run_on_a_draft_portfolio_is_rejected
    """
    env = build_locked_portfolio(api, lock=False)
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert_status(portfolio, "DRAFT")
    body = {
        "assumption_set_id": env["assumption_set_id"],
        "method": "DETERMINISTIC_STATIC",
        "expected_portfolio_version": portfolio["version"],
    }

    response = api.create_valuation_run(env["portfolio_id"], body, U.ANALYST)

    # The concurrency token supplied was current, so the state check is what
    # answers rather than the version guard.
    validate_error(response, ERR_TAPE_NOT_LOCKED)
    runs = rows_of(
        api.list_valuation_runs(U.ANALYST,
                                {"portfolio_id": env["portfolio_id"]})
    )
    assert runs == []


def test_valuation_run_succeeds_once_the_tape_is_locked(api: ApiClient):
    """
    The same run that a DRAFT pool refuses is accepted once the tape is frozen,
    and it prices the four-loan pool at the documented model value.

    PRD: "The run's `value_cents` is the sum of those per-loan figures."

    Design: Corner/state_machines/valuation_run_on_a_draft_portfolio_is_rejected
    """
    env = build_locked_portfolio(api, lock=False)
    draft = F.read_portfolio(api, env["portfolio_id"])
    body = {
        "assumption_set_id": env["assumption_set_id"],
        "method": "DETERMINISTIC_STATIC",
        "expected_portfolio_version": draft["version"],
    }
    validate_error(
        api.create_valuation_run(env["portfolio_id"], body, U.ANALYST),
        ERR_TAPE_NOT_LOCKED,
    )

    locked = F.lock_tape(api, env["portfolio_id"], env["seller_id"])
    body["expected_portfolio_version"] = locked["version"]
    run = data_of(
        api.create_valuation_run(env["portfolio_id"], body, U.ANALYST), 201
    )

    assert_status(run, "COMPLETED")
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
    assert run["included_loan_count"] == 4
    assert F.read_portfolio(api,
                            env["portfolio_id"])["valuation_freshness"] == "CURRENT"


# ---------------------------------------------------------------------------
# A package cannot be published before its tape is cut
# ---------------------------------------------------------------------------
def test_publishing_a_package_whose_tape_is_uncut_is_refused(api: ApiClient):
    """
    A package still in DRAFT has no tape to price, so publication is refused and
    the package keeps its opening zeros.

    PRD: "A `TransactionManager` publishes a `STRATIFIED` package, which stamps `published_at` from the logical clock, moves the package `STRATIFIED → PUBLISHED`, increments its `version` by 1, and stamps the reserve price."

    Design: Corner/state_machines/publishing_an_unstratified_package_is_rejected
    """
    env = build_valued_portfolio(api)
    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])
    draft_version = package["version"]

    response = api.publish_bid_package(package["id"], U.MANAGER)

    validate_error(response, ERR_PACKAGE_INVALID_STATE)
    after = F.read_package(api, package["id"])
    assert_status(after, "DRAFT")
    assert after["stratum_count"] == 0
    assert after["tape_upb_cents"] == 0
    assert after["tape_loan_count"] == 0
    assert after["reserve_price_cents"] is None
    assert after["published_at"] is None
    assert after["version"] == draft_version


def test_publishing_after_the_tape_is_cut_stamps_the_reserve(api: ApiClient):
    """
    Cutting the tape first makes the very same publication succeed and stamps the
    reserve at 95 percent of the whole-pool valuation.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/state_machines/publishing_an_unstratified_package_is_rejected
    """
    env = build_valued_portfolio(api)
    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])
    validate_error(api.publish_bid_package(package["id"], U.MANAGER),
                   ERR_PACKAGE_INVALID_STATE)

    stratified = F.stratify(api, package["id"])
    published = F.publish(api, package["id"])

    assert_status(published, "PUBLISHED")
    assert published["tape_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert published["reserve_price_cents"] == POOL_T_RESERVE_CENTS
    assert published["published_at"] == "2026-08-01T00:00:00.000Z"
    assert published["version"] == stratified["version"] + 1


def test_stratifying_a_cut_tape_a_second_time_is_refused(
        api: ApiClient, stratified_package: JsonDict):
    """
    The loan-level tape is cut once and only once, so a second stratification of
    the same package is refused and leaves the cut tape alone.

    PRD: "The tape is cut exactly once: stratifying a package that is no longer `DRAFT` is refused with `ERR_PACKAGE_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/publishing_an_unstratified_package_is_rejected
    """
    env = stratified_package
    before = F.read_package(api, env["package_id"])

    response = api.stratify_bid_package(env["package_id"], U.ANALYST)

    validate_error(response, ERR_PACKAGE_INVALID_STATE)
    after = F.read_package(api, env["package_id"])
    assert_status(after, "STRATIFIED")
    assert after["tape_loan_count"] == before["tape_loan_count"]
    assert after["version"] == before["version"]
    assert len(F.list_tape_lines(api, env["package_id"])) == 4


# ---------------------------------------------------------------------------
# One decision per approval request
# ---------------------------------------------------------------------------
def _agreement_with_two_pending_approvals(api: ApiClient) -> JsonDict:
    """
    An awarded trade carrying two consent prerequisites — the agency approval and
    an investor consent — submitted for approval so both requests are PENDING.
    Two requests keep the agreement in PENDING_APPROVALS after the first
    decision, which is what a replay of that first decision needs.
    """
    env = build_awarded_trade(api)
    agency_request = F.create_approval_request(
        api, env["agreement_id"], approver_type="AGENCY", agency_type="FNMA")
    investor_request = F.create_approval_request(
        api, env["agreement_id"], approver_type="INVESTOR", agency_type=None)
    env["agency_request_id"] = agency_request["id"]
    env["investor_request_id"] = investor_request["id"]
    env["agreement"] = F.submit_for_approval(api, env["agreement_id"])
    return env


def test_deciding_an_already_decided_request_a_second_time_is_refused(
        api: ApiClient):
    """
    A consent is recorded once: replaying the same decision on a request that has
    already been decided is refused and leaves the decision stamp untouched.

    PRD: "The agreement must be `PENDING_APPROVALS`, the request must still be `PENDING` — a second decision on the same request is `ERR_APPROVAL_ALREADY_DECIDED` (HTTP 409) — and the acting operator must not already have decided another request on the same agreement."

    Design: Corner/state_machines/deciding_an_already_decided_approval_request_is_rejected
    """
    env = _agreement_with_two_pending_approvals(api)
    decided = F.decide(api, env["agency_request_id"], decision="APPROVED")
    assert_status(decided, "APPROVED")

    response = api.decide_approval_request(
        env["agency_request_id"], {"decision": "DENIED"}, U.APPROVER)

    validate_error(response, ERR_APPROVAL_ALREADY_DECIDED)
    replayed = data_of(api.get_approval_request(env["agency_request_id"],
                                               U.MANAGER))
    assert_status(replayed, "APPROVED")
    assert replayed["decided_by_user_id"] == decided["decided_by_user_id"]
    assert replayed["decided_at"] == decided["decided_at"]
    assert replayed["version"] == decided["version"]


def test_a_refused_replay_leaves_the_approval_join_intact(api: ApiClient):
    """
    The refused replay changes nothing, so deciding the still-pending sibling
    afterwards drives the agreement to a clean unconditional approval.

    PRD: "When `approval_pending_count` reaches 0 and `condition_count` is 0, the agreement moves `PENDING_APPROVALS → APPROVED` and its `version` increments by 1."

    Design: Corner/state_machines/deciding_an_already_decided_approval_request_is_rejected
    """
    env = _agreement_with_two_pending_approvals(api)
    F.decide(api, env["agency_request_id"], decision="APPROVED")
    validate_error(
        api.decide_approval_request(env["agency_request_id"],
                                    {"decision": "APPROVED"}, U.APPROVER),
        ERR_APPROVAL_ALREADY_DECIDED,
    )
    mid = F.read_agreement(api, env["agreement_id"])
    assert_status(mid, "PENDING_APPROVALS")
    assert mid["approval_pending_count"] == 1
    assert mid["termination_reason"] is None

    F.decide(api, env["investor_request_id"], decision="APPROVED",
             headers=U.APPROVER_2)

    final = F.read_agreement(api, env["agreement_id"])
    assert_status(final, "APPROVED")
    assert final["approval_pending_count"] == 0
    assert final["condition_count"] == 0
    assert final["version"] == mid["version"] + 1


def test_deciding_a_request_after_the_agreement_left_approvals_is_refused(
        api: ApiClient, approved_agreement: JsonDict):
    """
    Once the join has carried the agreement out of PENDING_APPROVALS, a replayed
    decision is answered on agreement-state grounds rather than on the request's
    own decided flag.

    PRD: "The agreement must be `PENDING_APPROVALS`, the request must still be `PENDING` — a second decision on the same request is `ERR_APPROVAL_ALREADY_DECIDED` (HTTP 409) — and the acting operator must not already have decided another request on the same agreement."

    Design: Corner/state_machines/deciding_an_already_decided_approval_request_is_rejected
    """
    env = approved_agreement
    assert_status(env["agreement"], "APPROVED")
    request_id = env["approval_request_id"]

    # A second operator, so nothing but the two state checks is in play, and the
    # agreement's state is the one checked first.
    response = api.decide_approval_request(
        request_id, {"decision": "APPROVED"}, U.APPROVER_2)

    validate_error(response, ERR_AGREEMENT_INVALID_STATE)
    assert_status(F.read_agreement(api, env["agreement_id"]), "APPROVED")
    assert_status(data_of(api.get_approval_request(request_id, U.MANAGER)),
                  "APPROVED")


# ---------------------------------------------------------------------------
# A transferred pool is the end of the line
# ---------------------------------------------------------------------------
def test_transferred_portfolio_refuses_a_fresh_valuation_run(
        api: ApiClient, completed_transfer: JsonDict):
    """
    A pool whose servicing has left the seller is no longer a valuation basis, so
    a run against it is refused on tape-state grounds.

    PRD: "The portfolio must be `TAPE_LOCKED`: a run against a portfolio still in `DRAFT`, or one already `UNDER_CONTRACT` or `TRANSFERRED`, is refused with `ERR_TAPE_NOT_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/transferred_portfolio_is_terminal_and_accepts_no_further_work
    """
    env = completed_transfer
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert_status(portfolio, "TRANSFERRED")
    body = {
        "assumption_set_id": env["assumption_set_id"],
        "method": "DETERMINISTIC_STATIC",
        "expected_portfolio_version": portfolio["version"],
    }

    response = api.create_valuation_run(env["portfolio_id"], body, U.ANALYST)

    validate_error(response, ERR_TAPE_NOT_LOCKED)
    after = F.read_portfolio(api, env["portfolio_id"])
    assert_status(after, "TRANSFERRED")
    assert after["loan_count"] == 0
    assert after["total_upb_cents"] == 0
    assert after["version"] == portfolio["version"]


def test_transferred_portfolio_refuses_a_new_loan(
        api: ApiClient, completed_transfer: JsonDict):
    """
    The terminal pool cannot be restocked: adding a loan to a portfolio that has
    already transferred is refused just as it is on a locked pool.

    PRD: "Loans are added one at a time by the owning seller, and only while the portfolio is still `DRAFT`; an attempt on a portfolio that has moved on is refused with `ERR_TAPE_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/transferred_portfolio_is_terminal_and_accepts_no_further_work
    """
    env = completed_transfer
    replacement = dict(C.LOANS_T[0])
    replacement.update({"loan_number": "T-0009", "state_code": "NV"})

    response = api.create_loan(env["portfolio_id"], replacement,
                               env["seller_headers"])

    validate_error(response, ERR_TAPE_LOCKED)
    after = F.read_portfolio(api, env["portfolio_id"])
    assert_status(after, "TRANSFERRED")
    assert after["loan_count"] == 0
    assert F.list_loans(api, env["portfolio_id"], status="ACTIVE") == []


def test_completing_an_already_completed_transfer_is_refused(
        api: ApiClient, completed_transfer: JsonDict):
    """
    Completion happens once: a second completion on a finished transfer is
    refused and the loans keep the transfer stamp they already carry.

    PRD: "Every step below requires the transfer's overall status to be `IN_PROGRESS`, and a step attempted on a transfer that has already `COMPLETED` — including a second completion — is refused with `ERR_TRANSFER_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/transferred_portfolio_is_terminal_and_accepts_no_further_work
    """
    env = completed_transfer
    before = F.read_transfer(api, env["transfer_id"])
    assert_status(before, "COMPLETED")
    stamped = [F.read_loan(api, loan_id) for loan_id in env["loan_ids"]]

    response = api.complete_transfer(env["transfer_id"], U.MANAGER)

    validate_error(response, ERR_TRANSFER_INVALID_STATE)
    after = F.read_transfer(api, env["transfer_id"])
    assert after["completed_at"] == before["completed_at"]
    assert after["transferred_loan_count"] == before["transferred_loan_count"]
    assert after["version"] == before["version"]
    for loan, original in zip(
            (F.read_loan(api, loan_id) for loan_id in env["loan_ids"]),
            stamped):
        assert_status(loan, "TRANSFERRED")
        assert loan["transferred_at"] == original["transferred_at"]


# ---------------------------------------------------------------------------
# A denial short-circuits the join and unwinds the trade
# ---------------------------------------------------------------------------
def test_a_denied_consent_terminates_the_agreement_at_once(api: ApiClient):
    """
    One denial ends the trade immediately, without waiting for the sibling
    consent that is still outstanding.

    PRD: "The agreement moves `PENDING_APPROVALS → TERMINATED` immediately, with `termination_reason` set to `APPROVAL_DENIED`, without waiting for any sibling request."

    Design: Corner/state_machines/approval_denial_terminates_the_agreement_and_unwinds_the_marketing_chain
    """
    env = _agreement_with_two_pending_approvals(api)
    submitted = F.read_agreement(api, env["agreement_id"])
    assert submitted["approval_pending_count"] == 2

    denied = F.decide(api, env["agency_request_id"], decision="DENIED")

    assert_status(denied, "DENIED")
    agreement = F.read_agreement(api, env["agreement_id"])
    assert_status(agreement, "TERMINATED")
    assert agreement["termination_reason"] == "APPROVAL_DENIED"
    assert agreement["approval_pending_count"] == 1


def test_a_denied_consent_puts_the_pool_back_on_the_shelf(api: ApiClient):
    """
    The termination unwinds the marketing chain: the package is cancelled, the
    accepted bid is rejected and the pool returns to its locked, unsold state.

    PRD: "The agreement moves to `TERMINATED` with `termination_reason` set to `APPROVAL_DENIED`; the awarded bid package moves to `CANCELLED`; the bid that had been `ACCEPTED` on that package moves to `REJECTED`, as does any bid on it still sitting in `SUBMITTED`; and the owning portfolio moves `UNDER_CONTRACT → TAPE_LOCKED` provided the terminated agreement is the only non-`TERMINATED` agreement on that portfolio, putting the pool back on the shelf where it can be re-marketed under a fresh package."

    Design: Corner/state_machines/approval_denial_terminates_the_agreement_and_unwinds_the_marketing_chain
    """
    env = _agreement_with_two_pending_approvals(api)
    assert_status(F.read_package(api, env["package_id"]), "AWARDED")
    assert_status(F.read_bid(api, env["bid_id"]), "ACCEPTED")
    assert_status(F.read_portfolio(api, env["portfolio_id"]), "UNDER_CONTRACT")

    F.decide(api, env["agency_request_id"], decision="DENIED")

    assert_status(F.read_package(api, env["package_id"]), "CANCELLED")
    assert_status(F.read_bid(api, env["bid_id"]), "REJECTED")
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert_status(portfolio, "TAPE_LOCKED")
    assert portfolio["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS


def test_siblings_of_a_denied_consent_become_permanently_undecidable(
        api: ApiClient):
    """
    The consent left pending when the denial short-circuited the join can never
    be decided, because its agreement has left the approval state.

    PRD: "Those siblings are left in `PENDING` and become permanently undecidable: a later decision on them is refused with `ERR_AGREEMENT_INVALID_STATE` (HTTP 409), because the agreement they belong to is no longer `PENDING_APPROVALS`."

    Design: Corner/state_machines/approval_denial_terminates_the_agreement_and_unwinds_the_marketing_chain
    """
    env = _agreement_with_two_pending_approvals(api)
    F.decide(api, env["agency_request_id"], decision="DENIED")
    sibling = data_of(api.get_approval_request(env["investor_request_id"],
                                               U.MANAGER))
    assert_status(sibling, "PENDING")

    response = api.decide_approval_request(
        env["investor_request_id"], {"decision": "APPROVED"}, U.APPROVER_2)

    validate_error(response, ERR_AGREEMENT_INVALID_STATE)
    after = data_of(api.get_approval_request(env["investor_request_id"],
                                            U.MANAGER))
    assert_status(after, "PENDING")
    assert after["decided_by_user_id"] is None
    assert after["decided_at"] is None
    assert after["version"] == sibling["version"]


# ---------------------------------------------------------------------------
# A conditional consent re-sizes the holdback
# ---------------------------------------------------------------------------
def test_conditional_consent_lifts_the_holdback_to_the_fifteen_percent_floor(
        api: ApiClient):
    """
    A six percent holdback negotiated in the bid is lifted to the fifteen percent
    floor when the only consent comes back conditional.

    PRD: "When `approval_pending_count` reaches 0 and `condition_count` is at least 1, the agreement moves `PENDING_APPROVALS → CONDITIONALLY_APPROVED` and the holdback is re-sized upward to a floor: the new `holdback_cents` is the greater of the existing `holdback_cents` and the figure obtained by multiplying `purchase_price_cents` by 15, dividing by 100 and rounding half up to whole cents."

    Design: Corner/state_machines/conditional_approval_resizes_the_holdback_to_the_fifteen_percent_floor
    """
    env = build_awarded_trade(api)
    drafted = env["agreement"]
    assert drafted["purchase_price_cents"] == POOL_T_PURCHASE_PRICE_CENTS
    assert drafted["holdback_cents"] == POOL_T_HOLDBACK_AT_SIX_PCT_CENTS
    assert drafted["settlement_wire_cents"] == POOL_T_WIRE_AT_SIX_PCT_CENTS
    request = F.create_approval_request(api, env["agreement_id"])
    F.submit_for_approval(api, env["agreement_id"])

    F.decide(api, request["id"], decision="CONDITIONALLY_APPROVED",
             condition_text=CONDITION_TEXT)

    floor = round_half_up(POOL_T_PURCHASE_PRICE_CENTS * 15 / 100)
    assert floor == POOL_T_CONDITIONAL_HOLDBACK_CENTS
    agreement = F.read_agreement(api, env["agreement_id"])
    assert_status(agreement, "CONDITIONALLY_APPROVED")
    assert agreement["condition_count"] == 1
    assert agreement["holdback_cents"] == POOL_T_CONDITIONAL_HOLDBACK_CENTS
    assert agreement["settlement_wire_cents"] == POOL_T_CONDITIONAL_WIRE_CENTS
    assert_holdback_split(agreement,
                          retained=POOL_T_CONDITIONAL_HOLDBACK_CENTS,
                          released=0, applied=0)
    # The negotiated percentage is history, not a live driver: only the cash moved.
    assert float(agreement["holdback_pct"]) == 6.0


def test_settling_a_conditional_agreement_without_a_waiver_is_refused(
        api: ApiClient):
    """
    The condition attached by the approver has to be waived in writing, so
    settlement without a waiver reference is refused and nothing settles.

    PRD: "A conditionally approved agreement settled without a non-empty waiver reference fails with `ERR_CONDITION_WAIVER_REQUIRED` (HTTP 422)."

    Design: Corner/state_machines/conditional_approval_resizes_the_holdback_to_the_fifteen_percent_floor
    """
    env = build_approved_agreement(api, decision="CONDITIONALLY_APPROVED",
                                   condition_text=CONDITION_TEXT)
    before = F.read_agreement(api, env["agreement_id"])

    response = api.settle_agreement(
        env["agreement_id"],
        {"sale_date": C.SALE_DATE, "transfer_date": C.TRANSFER_DATE},
        U.MANAGER,
    )

    validate_error(response, ERR_CONDITION_WAIVER_REQUIRED)
    after = F.read_agreement(api, env["agreement_id"])
    assert_status(after, "CONDITIONALLY_APPROVED")
    assert after["holdback_cents"] == POOL_T_CONDITIONAL_HOLDBACK_CENTS
    assert after["sale_date"] is None
    assert after["transfer_date"] is None
    assert after["version"] == before["version"]
    assert rows_of(api.list_servicing_transfers(
        U.MANAGER, {"purchase_agreement_id": env["agreement_id"]})) == []


def test_settling_a_conditional_agreement_carries_the_resized_holdback(
        api: ApiClient):
    """
    With the waiver reference supplied the conditional agreement settles, and the
    cash it retains is the re-sized holdback rather than the bid's six percent.

    PRD: "A `TransactionManager` settles an agreement that is `APPROVED` or `CONDITIONALLY_APPROVED`, supplying the economic `sale_date` and the servicing `transfer_date`, both as `YYYY-MM-DD` calendar dates, plus `condition_waiver_reference` — the external waiver document reference — which is required when the agreement is `CONDITIONALLY_APPROVED` and must be omitted otherwise."

    Design: Corner/state_machines/conditional_approval_resizes_the_holdback_to_the_fifteen_percent_floor
    """
    env = build_approved_agreement(api, decision="CONDITIONALLY_APPROVED",
                                   condition_text=CONDITION_TEXT)

    settled = F.settle(api, env["agreement_id"],
                       condition_waiver_reference="WAIVER-2599-A")

    assert_status(settled, "SETTLED")
    assert settled["condition_waiver_reference"] == "WAIVER-2599-A"
    assert settled["holdback_cents"] == POOL_T_CONDITIONAL_HOLDBACK_CENTS
    assert_holdback_split(settled,
                          retained=POOL_T_CONDITIONAL_HOLDBACK_CENTS,
                          released=0, applied=0)
    transfer = F.find_transfer(api, env["agreement_id"])
    assert_status(transfer, "IN_PROGRESS")
    assert_readiness(transfer, "NOT_READY")


# ---------------------------------------------------------------------------
# The bounded reopen loop of a notice of error
# ---------------------------------------------------------------------------
CASE_OPENED_AT = "2026-09-05T00:00:00Z"
CASE_FIRST_REOPEN_AT = "2026-09-15T00:00:00Z"
CASE_SECOND_REOPEN_AT = "2026-09-25T00:00:00Z"
CASE_THIRD_REOPEN_AT = "2026-10-02T00:00:00Z"


def _transferred_pool_with_open_error_case(api: ApiClient) -> JsonDict:
    """
    A completed transfer of pool T with one notice of error logged four days
    later, against the first loan that moved across.
    """
    env = build_completed_transfer(api)
    F.set_clock(api, CASE_OPENED_AT)
    env["clock"] = CASE_OPENED_AT
    env["case"] = F.open_error_case(
        api, env["transfer_id"], env["loan_ids"][0],
        category="PAYMENT_MISAPPLIED",
        description="September payment applied to the wrong loan after transfer")
    env["case_id"] = env["case"]["id"]
    return env


def _work_one_cycle(api: ApiClient, env: JsonDict, reopen_at: str,
                    remediation_cents: int) -> JsonDict:
    """Reopen the resolved case at the given instant, then acknowledge and
    resolve it again with a further remediation charge."""
    F.set_clock(api, reopen_at)
    env["clock"] = reopen_at
    env["reopened"] = F.reopen_case(api, env["case_id"])
    env["reacknowledged"] = F.acknowledge_case(api, env["case_id"],
                                               env["buyer_id"])
    return F.resolve_case(api, env["case_id"], env["buyer_id"],
                          remediation_cents=remediation_cents)


def test_error_case_opens_with_its_two_statutory_deadlines(api: ApiClient):
    """
    A notice of error logged after the transfer opens OPEN and carries a
    five-day acknowledgement deadline and a thirty-day resolution deadline.

    PRD: "The case records its `servicing_transfer_id`, opens in `OPEN` status with `opened_at` set to the current logical clock, and derives two statutory deadlines from that instant: `ack_deadline_at` five calendar days after it and `resolution_deadline_at` thirty calendar days after it."

    Design: Corner/state_machines/error_case_reopen_loop_escalates_on_the_third_reopen
    """
    env = _transferred_pool_with_open_error_case(api)
    case = env["case"]

    assert_status(case, "OPEN")
    assert case["opened_at"] == "2026-09-05T00:00:00.000Z"
    assert case["ack_deadline_at"] == "2026-09-10T00:00:00.000Z"
    assert case["resolution_deadline_at"] == "2026-10-05T00:00:00.000Z"
    assert case["reopen_count"] == 0
    assert case["remediation_cents"] == 0
    assert case["ack_breached"] is False
    assert case["resolution_breached"] is False


def test_reacknowledging_a_reopened_case_breaches_the_unchanged_deadline(
        api: ApiClient):
    """
    A reopen rewinds the working stamps but not the acknowledgement deadline, so
    the second pass through the loop breaches it and the flag then sticks.

    PRD: "Inside the window, a reopen supplies a `reason`, increments `reopen_count` by 1, clears `acknowledged_at` and `resolved_at` back to null while leaving both breach flags at their worst observed values, and moves the case `RESOLVED → REOPENED`; the buyer then acknowledges again, this time measured against the unchanged `ack_deadline_at`, so a second pass through the loop will usually set `ack_breached`."

    Design: Corner/state_machines/error_case_reopen_loop_escalates_on_the_third_reopen
    """
    env = _transferred_pool_with_open_error_case(api)
    first_ack = F.acknowledge_case(api, env["case_id"], env["buyer_id"])
    assert_status(first_ack, "ACKNOWLEDGED")
    assert first_ack["ack_breached"] is False
    F.resolve_case(api, env["case_id"], env["buyer_id"],
                   remediation_cents=1000)

    resolved = _work_one_cycle(api, env, CASE_FIRST_REOPEN_AT, 2000)

    reopened = env["reopened"]
    assert_status(reopened, "REOPENED")
    assert reopened["reopen_count"] == 1
    assert reopened["acknowledged_at"] is None
    assert reopened["resolved_at"] is None
    reacknowledged = env["reacknowledged"]
    assert_status(reacknowledged, "ACKNOWLEDGED")
    assert reacknowledged["ack_deadline_at"] == "2026-09-10T00:00:00.000Z"
    assert reacknowledged["ack_breached"] is True
    assert_status(resolved, "RESOLVED")
    assert resolved["ack_breached"] is True
    assert resolved["remediation_cents"] == 3000


def test_the_third_reopen_escalates_the_case_instead_of_cycling(api: ApiClient):
    """
    The loop runs twice; the third reopen escalates the case, leaving the counter
    at two and the cumulative remediation intact.

    PRD: "A reopen attempted when `reopen_count` is already 2 does not cycle a third time: it moves the case `RESOLVED → ESCALATED`, which is terminal, leaving the counter at 2."

    Design: Corner/state_machines/error_case_reopen_loop_escalates_on_the_third_reopen
    """
    env = _transferred_pool_with_open_error_case(api)
    F.acknowledge_case(api, env["case_id"], env["buyer_id"])
    F.resolve_case(api, env["case_id"], env["buyer_id"],
                   remediation_cents=1000)
    _work_one_cycle(api, env, CASE_FIRST_REOPEN_AT, 2000)
    second = _work_one_cycle(api, env, CASE_SECOND_REOPEN_AT, 3000)
    assert env["reopened"]["reopen_count"] == 2
    assert_status(second, "RESOLVED")

    F.set_clock(api, CASE_THIRD_REOPEN_AT)
    escalated = F.reopen_case(api, env["case_id"])

    assert_status(escalated, "ESCALATED")
    assert escalated["reopen_count"] == 2
    assert escalated["ack_breached"] is True
    assert escalated["remediation_cents"] == 6000


def test_an_escalated_case_accepts_no_further_work(api: ApiClient):
    """
    Escalation is terminal: a further reopen is turned away on the ceiling and an
    acknowledgement is turned away on the case's state.

    PRD: "An escalated case still counts in the complaint concentration numerator but can no longer be acknowledged, resolved or reopened — acknowledgement and resolution are refused on state grounds with `ERR_CASE_INVALID_STATE`, while a further reopen passes the state check by design and is refused with `ERR_MAX_REOPENS_EXCEEDED` (HTTP 409)."

    Design: Corner/state_machines/error_case_reopen_loop_escalates_on_the_third_reopen
    """
    env = _transferred_pool_with_open_error_case(api)
    F.acknowledge_case(api, env["case_id"], env["buyer_id"])
    F.resolve_case(api, env["case_id"], env["buyer_id"],
                   remediation_cents=1000)
    _work_one_cycle(api, env, CASE_FIRST_REOPEN_AT, 2000)
    _work_one_cycle(api, env, CASE_SECOND_REOPEN_AT, 3000)
    F.set_clock(api, CASE_THIRD_REOPEN_AT)
    escalated = F.reopen_case(api, env["case_id"])

    fourth_reopen = api.reopen_error_case(
        env["case_id"], {"reason": "the committee wants one more pass"},
        U.COMPLIANCE)
    acknowledgement = api.acknowledge_error_case(
        env["case_id"], U.make_buyer_headers(env["buyer_id"]))

    validate_error(fourth_reopen, ERR_MAX_REOPENS_EXCEEDED)
    validate_error(acknowledgement, ERR_CASE_INVALID_STATE)
    after = F.read_error_case(api, env["case_id"])
    assert_status(after, "ESCALATED")
    assert after["reopen_count"] == 2
    assert after["remediation_cents"] == 6000
    assert after["version"] == escalated["version"]


# ---------------------------------------------------------------------------
# Attestation is quantified over the whole awarded tape
# ---------------------------------------------------------------------------
def test_a_transferor_notice_sent_a_month_ahead_is_compliant(
        api: ApiClient, settled_trade: JsonDict):
    """
    A transferor notice sent on 1 August for a 1 September transfer carries 31
    days of lead time and is compliant.

    PRD: "For a `TRANSFEROR_15DAY` or a `COMBINED` notice, `lead_days` is the number of calendar days from the date the notice was sent to the effective date — the effective date less the sent date — and `compliance_status` is `COMPLIANT` when `lead_days` is at least 15, and `LATE` otherwise."

    Design: Corner/state_machines/attesting_notices_before_every_tape_loan_is_noticed_is_rejected
    """
    env = settled_trade

    notice = F.send_notice(api, env["transfer_id"], env["included_loan_ids"][0],
                           env["seller_id"], notice_type="TRANSFEROR_15DAY",
                           effective_date=C.TRANSFER_DATE)

    assert notice["lead_days"] == 31
    assert notice["compliance_status"] == "COMPLIANT"
    assert notice["sent_by_role"] == "SellerServicer"
    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 1
    assert transfer["late_notice_count"] == 0
    assert transfer["notice_status"] == "NOTICES_IN_PROGRESS"


def test_attesting_with_one_tape_loan_unnoticed_is_refused(
        api: ApiClient, settled_trade: JsonDict):
    """
    Three notices on a four-loan tape do not cover the tape, so attestation is
    refused and the notice work stream stays open.

    PRD: "Attestation has two gates, reported in this order: every loan with an included tape line must have at least one `TRANSFEROR_15DAY` or `COMBINED` notice on this transfer, else `ERR_NOTICE_COMPLIANCE_INCOMPLETE` (HTTP 409); and `late_notice_count` must be exactly 0, else `ERR_NOTICE_LATE` (HTTP 409)."

    Design: Corner/state_machines/attesting_notices_before_every_tape_loan_is_noticed_is_rejected
    """
    env = settled_trade
    assert len(env["included_loan_ids"]) == 4
    F.send_notices(api, env["transfer_id"], env["included_loan_ids"][:3],
                   env["seller_id"])
    before = F.read_transfer(api, env["transfer_id"])
    assert before["notice_count"] == 3
    assert before["notice_status"] == "NOTICES_IN_PROGRESS"

    response = api.attest_notices(env["transfer_id"], U.COMPLIANCE)

    validate_error(response, ERR_NOTICE_COMPLIANCE_INCOMPLETE)
    after = F.read_transfer(api, env["transfer_id"])
    assert after["notice_status"] == "NOTICES_IN_PROGRESS"
    assert after["notice_attested_at"] is None
    assert after["notice_attested_by_user_id"] is None
    assert_readiness(after, "NOT_READY")


def test_a_duplicate_notice_does_not_buy_tape_coverage(
        api: ApiClient, settled_trade: JsonDict):
    """
    Noticing the same borrower twice raises the notice count without covering the
    fourth loan, so attestation is still refused.

    PRD: "Attestation has two gates, reported in this order: every loan with an included tape line must have at least one `TRANSFEROR_15DAY` or `COMBINED` notice on this transfer, else `ERR_NOTICE_COMPLIANCE_INCOMPLETE` (HTTP 409); and `late_notice_count` must be exactly 0, else `ERR_NOTICE_LATE` (HTTP 409)."

    Design: Corner/state_machines/attesting_notices_before_every_tape_loan_is_noticed_is_rejected
    """
    env = settled_trade
    F.send_notices(api, env["transfer_id"], env["included_loan_ids"][:3],
                   env["seller_id"])
    validate_error(api.attest_notices(env["transfer_id"], U.COMPLIANCE),
                   ERR_NOTICE_COMPLIANCE_INCOMPLETE)

    F.send_notice(api, env["transfer_id"], env["included_loan_ids"][0],
                  env["seller_id"])

    padded = F.read_transfer(api, env["transfer_id"])
    assert padded["notice_count"] == 4
    validate_error(api.attest_notices(env["transfer_id"], U.COMPLIANCE),
                   ERR_NOTICE_COMPLIANCE_INCOMPLETE)
    assert F.read_transfer(api, env["transfer_id"])["notice_status"] == (
        "NOTICES_IN_PROGRESS")


def test_attesting_after_the_last_tape_loan_is_noticed_closes_the_dimension(
        api: ApiClient, settled_trade: JsonDict):
    """
    Once the fourth borrower is noticed the same attestation succeeds and closes
    the notice work stream with the attesting officer recorded.

    PRD: "A `ComplianceOfficer` closes the dimension by attesting compliance, which moves `notice_status` `NOTICES_IN_PROGRESS → NOTICES_ATTESTED`, stamps `notice_attested_at` and records `notice_attested_by_user_id` — the identifier that later blocks the same officer from releasing the holdback."

    Design: Corner/state_machines/attesting_notices_before_every_tape_loan_is_noticed_is_rejected
    """
    env = settled_trade
    F.send_notices(api, env["transfer_id"], env["included_loan_ids"][:3],
                   env["seller_id"])
    validate_error(api.attest_notices(env["transfer_id"], U.COMPLIANCE),
                   ERR_NOTICE_COMPLIANCE_INCOMPLETE)

    F.send_notice(api, env["transfer_id"], env["included_loan_ids"][3],
                  env["seller_id"])
    attested = F.attest_notices(api, env["transfer_id"])

    assert attested["notice_status"] == "NOTICES_ATTESTED"
    assert attested["notice_count"] == 4
    assert attested["late_notice_count"] == 0
    assert attested["notice_attested_at"] == "2026-08-01T00:00:00.000Z"
    assert attested["notice_attested_by_user_id"] == C.COMPLIANCE_ID
