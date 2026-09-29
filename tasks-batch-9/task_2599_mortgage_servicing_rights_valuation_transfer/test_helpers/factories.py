"""
Creation helpers for the transfer-desk test suite.

Each function performs one documented call, asserts the documented success code
and returns the resulting object. They exist so a fixture reads as a sequence
of desk actions rather than a sequence of HTTP assertions.
"""

from . import constants as C
from . import test_users as U
from .api_client import ApiClient
from .assertions import data_of, rows_of
from .types import Headers, JsonDict, JsonList


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, when: str) -> None:
    """Move the logical clock to an explicit instant."""
    response = api.set_current_utc({"to_iso8601": when}, U.ADMIN)
    assert response.status_code == 200, (
        f"clock move to {when} failed: {response.status_code} {response.text}"
    )


# ---------------------------------------------------------------------------
# Counterparties
# ---------------------------------------------------------------------------
def create_counterparty(api: ApiClient, payload: JsonDict = None,
                        **overrides) -> JsonDict:
    """Register a counterparty on the desk."""
    body = dict(payload if payload is not None else C.SELLER_ALPHA)
    body.update(overrides)
    return data_of(api.create_counterparty(body, U.ADMIN), 201)


def create_seller(api: ApiClient, **overrides) -> JsonDict:
    """Register the standard selling servicer."""
    return create_counterparty(api, C.SELLER_ALPHA, **overrides)


def create_buyer(api: ApiClient, **overrides) -> JsonDict:
    """Register the standard acquiring servicer."""
    return create_counterparty(api, C.BUYER_BRAVO, **overrides)


def suspend_counterparty(api: ApiClient, counterparty_id: str) -> JsonDict:
    """Suspend a counterparty so it can no longer be named as bidder or buyer."""
    return data_of(api.suspend_counterparty(counterparty_id, U.ADMIN))


# ---------------------------------------------------------------------------
# Portfolios and loans
# ---------------------------------------------------------------------------
def create_portfolio(api: ApiClient, seller_id: str, name: str = "Pool-T",
                     agency_type: str = "FNMA",
                     headers: Headers = None) -> JsonDict:
    """Open a servicing portfolio for sale."""
    body = {
        "seller_id": seller_id,
        "portfolio_name": name,
        "agency_type": agency_type,
    }
    return data_of(
        api.create_portfolio(body, headers or U.make_seller_headers(seller_id)),
        201,
    )


def add_loan(api: ApiClient, portfolio_id: str, seller_id: str,
             payload: JsonDict, **overrides) -> JsonDict:
    """Add one loan to a DRAFT pool."""
    body = dict(payload)
    body.update(overrides)
    return data_of(
        api.create_loan(portfolio_id, body, U.make_seller_headers(seller_id)),
        201,
    )


def add_loans(api: ApiClient, portfolio_id: str, seller_id: str,
              payloads: list) -> JsonList:
    """Add a whole pool of loans, in the order given."""
    return [add_loan(api, portfolio_id, seller_id, item) for item in payloads]


def lock_tape(api: ApiClient, portfolio_id: str, seller_id: str) -> JsonDict:
    """Freeze the pool composition as the pricing basis."""
    return data_of(
        api.lock_tape(portfolio_id, U.make_seller_headers(seller_id))
    )


def read_portfolio(api: ApiClient, portfolio_id: str,
                   headers: Headers = None) -> JsonDict:
    """Read a portfolio and its derived tape aggregates."""
    return data_of(api.get_portfolio(portfolio_id, headers or U.MANAGER))


def read_loan(api: ApiClient, loan_id: str, headers: Headers = None) -> JsonDict:
    """Read one loan."""
    return data_of(api.get_loan(loan_id, headers or U.MANAGER))


def list_loans(api: ApiClient, portfolio_id: str, headers: Headers = None,
               **params) -> JsonList:
    """List the loans of a portfolio."""
    return rows_of(
        api.list_portfolio_loans(portfolio_id, headers or U.MANAGER,
                                 params or None)
    )


# ---------------------------------------------------------------------------
# Assumptions and curves
# ---------------------------------------------------------------------------
def create_assumption_set(api: ApiClient, payload: JsonDict = None,
                          **overrides) -> JsonDict:
    """Create an immutable valuation assumption vector."""
    body = dict(payload if payload is not None else C.ASSUMPTION_DESK_BASE)
    body.update(overrides)
    return data_of(api.create_assumption_set(body, U.ANALYST), 201)


def create_rate_curve(api: ApiClient, payload: JsonDict = None,
                      **overrides) -> JsonDict:
    """Publish a rate curve snapshot, superseding the incumbent."""
    body = dict(payload if payload is not None else C.CURVE_C1)
    body.update(overrides)
    return data_of(api.create_rate_curve(body, U.HEDGE), 201)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------
def run_valuation(api: ApiClient, portfolio_id: str, assumption_set_id: str,
                  expected_version: int,
                  method: str = "DETERMINISTIC_STATIC",
                  headers: Headers = None) -> JsonDict:
    """Execute a fair-value run against the locked tape."""
    body = {
        "assumption_set_id": assumption_set_id,
        "method": method,
        "expected_portfolio_version": expected_version,
    }
    return data_of(
        api.create_valuation_run(portfolio_id, body, headers or U.ANALYST),
        201,
    )


def read_valuation_run(api: ApiClient, run_id: str,
                       headers: Headers = None) -> JsonDict:
    """Read one valuation run."""
    return data_of(api.get_valuation_run(run_id, headers or U.ANALYST))


# ---------------------------------------------------------------------------
# Bid packages and the loan-level tape
# ---------------------------------------------------------------------------
def create_bid_package(api: ApiClient, portfolio_id: str, valuation_run_id: str,
                       scheme: str = "BY_STATE",
                       floor_pct=C.RESERVE_PRICE_FLOOR_PCT,
                       marketing_start_at: str = C.MARKETING_START_AT,
                       bid_deadline_at: str = C.BID_DEADLINE_AT,
                       headers: Headers = None) -> JsonDict:
    """Create a marketing vehicle bound to a locked tape and a valuation run."""
    body = {
        "portfolio_id": portfolio_id,
        "valuation_run_id": valuation_run_id,
        "stratification_scheme": scheme,
        "reserve_price_floor_pct": floor_pct,
        "marketing_start_at": marketing_start_at,
        "bid_deadline_at": bid_deadline_at,
    }
    return data_of(api.create_bid_package(body, headers or U.MANAGER), 201)


def stratify(api: ApiClient, package_id: str,
             headers: Headers = None) -> JsonDict:
    """Cut the loan-level tape and assign strata."""
    return data_of(api.stratify_bid_package(package_id, headers or U.ANALYST))


def list_tape_lines(api: ApiClient, package_id: str, headers: Headers = None,
                    **params) -> JsonList:
    """List the loan-level tape of a package."""
    return rows_of(
        api.list_package_tape_lines(package_id, headers or U.ANALYST,
                                    params or None)
    )


def set_tape_line_inclusion(api: ApiClient, tape_line_id: str, included: bool,
                            exclusion_reason: str = None,
                            headers: Headers = None) -> JsonDict:
    """Include or exclude a single tape line."""
    body = {"included": included}
    if exclusion_reason is not None:
        body["exclusion_reason"] = exclusion_reason
    return data_of(
        api.patch_tape_line(tape_line_id, body, headers or U.ANALYST)
    )


def publish(api: ApiClient, package_id: str,
            headers: Headers = None) -> JsonDict:
    """Publish a package to the market and stamp its reserve price."""
    return data_of(api.publish_bid_package(package_id, headers or U.MANAGER))


def read_package(api: ApiClient, package_id: str,
                 headers: Headers = None) -> JsonDict:
    """Read one bid package."""
    return data_of(api.get_bid_package(package_id, headers or U.MANAGER))


# ---------------------------------------------------------------------------
# Bids and negotiation
# ---------------------------------------------------------------------------
def submit_bid(api: ApiClient, package_id: str, bidder_id: str,
               expected_version: int, price_bps: int = 118, holdback_pct=6,
               headers: Headers = None) -> JsonDict:
    """Submit a bid on a published package."""
    body = {
        "bidder_id": bidder_id,
        "price_bps": price_bps,
        "holdback_pct": holdback_pct,
        "expected_bid_package_version": expected_version,
    }
    return data_of(
        api.create_bid(package_id, body,
                       headers or U.make_buyer_headers(bidder_id)),
        201,
    )


def counter(api: ApiClient, bid_id: str, counter_price_bps: int,
            expires_at: str = "2026-08-10T00:00:00Z",
            headers: Headers = None) -> JsonDict:
    """Counter a bid, opening a negotiation round with an expiry."""
    body = {
        "counter_price_bps": counter_price_bps,
        "counter_expires_at": expires_at,
    }
    return data_of(api.counter_bid(bid_id, body, headers or U.MANAGER))


def revise(api: ApiClient, bid_id: str, bidder_id: str, price_bps: int,
           holdback_pct=6, headers: Headers = None) -> JsonDict:
    """Revise a countered bid."""
    body = {"price_bps": price_bps, "holdback_pct": holdback_pct}
    return data_of(
        api.revise_bid(bid_id, body,
                       headers or U.make_buyer_headers(bidder_id))
    )


def read_bid(api: ApiClient, bid_id: str, headers: Headers = None) -> JsonDict:
    """Read one bid."""
    return data_of(api.get_bid(bid_id, headers or U.MANAGER))


# ---------------------------------------------------------------------------
# Award, approvals and settlement
# ---------------------------------------------------------------------------
def award(api: ApiClient, package_id: str, winning_bid_id: str,
          rep_warrant_days: int = 30, indemnification_days: int = 45,
          headers: Headers = None) -> JsonDict:
    """Award the package to a bid and draft the purchase agreement."""
    body = {
        "winning_bid_id": winning_bid_id,
        "rep_warrant_days": rep_warrant_days,
        "indemnification_days": indemnification_days,
    }
    return data_of(
        api.award_bid_package(package_id, body, headers or U.MANAGER), 201
    )


def create_approval_request(api: ApiClient, agreement_id: str,
                            approver_type: str = "AGENCY",
                            agency_type: str = "FNMA",
                            headers: Headers = None) -> JsonDict:
    """Raise an agency or investor approval prerequisite."""
    body = {"approver_type": approver_type}
    if agency_type is not None:
        body["agency_type"] = agency_type
    return data_of(
        api.create_approval_request(agreement_id, body, headers or U.MANAGER),
        201,
    )


def submit_for_approval(api: ApiClient, agreement_id: str,
                        headers: Headers = None) -> JsonDict:
    """Move the agreement into its approval-pending state."""
    return data_of(
        api.submit_for_approval(agreement_id, headers or U.MANAGER)
    )


def decide(api: ApiClient, approval_request_id: str, decision: str = "APPROVED",
           condition_text: str = None, headers: Headers = None) -> JsonDict:
    """Record an agency or investor decision."""
    body = {"decision": decision}
    if condition_text is not None:
        body["condition_text"] = condition_text
    return data_of(
        api.decide_approval_request(approval_request_id, body,
                                    headers or U.APPROVER)
    )


def settle(api: ApiClient, agreement_id: str, sale_date: str = C.SALE_DATE,
           transfer_date: str = C.TRANSFER_DATE,
           condition_waiver_reference: str = None,
           headers: Headers = None) -> JsonDict:
    """Settle the trade and open the servicing transfer."""
    body = {"sale_date": sale_date, "transfer_date": transfer_date}
    if condition_waiver_reference is not None:
        body["condition_waiver_reference"] = condition_waiver_reference
    return data_of(api.settle_agreement(agreement_id, body,
                                        headers or U.MANAGER))


def read_agreement(api: ApiClient, agreement_id: str,
                   headers: Headers = None) -> JsonDict:
    """Read one purchase agreement."""
    return data_of(
        api.get_purchase_agreement(agreement_id, headers or U.MANAGER)
    )


def release_holdback(api: ApiClient, agreement_id: str, expected_version: int,
                     headers: Headers = None) -> JsonDict:
    """Release holdback against the complaint concentration tier."""
    body = {"expected_purchase_agreement_version": expected_version}
    return data_of(
        api.create_holdback_release(agreement_id, body,
                                    headers or U.COMPLIANCE_2)
    )


def clawback_holdback(api: ApiClient, agreement_id: str, amount_cents: int,
                      reason: str = "wire recalled after the post-transfer audit",
                      headers: Headers = None) -> JsonDict:
    """Claw a released holdback amount back into the retained balance."""
    body = {"amount_cents": amount_cents, "reason": reason}
    return data_of(
        api.create_holdback_clawback(agreement_id, body,
                                     headers or U.COMPLIANCE_2)
    )


# ---------------------------------------------------------------------------
# Servicing transfer work streams
# ---------------------------------------------------------------------------
def find_transfer(api: ApiClient, agreement_id: str,
                  headers: Headers = None) -> JsonDict:
    """
    The transfer opened by settling an agreement. Listing is the only discovery
    channel, because the transfer is created by the settle cascade.
    """
    rows = rows_of(
        api.list_servicing_transfers(headers or U.MANAGER,
                                     {"purchase_agreement_id": agreement_id})
    )
    assert len(rows) == 1, (
        f"expected exactly one transfer for agreement {agreement_id}, "
        f"found {len(rows)}"
    )
    return rows[0]


def read_transfer(api: ApiClient, transfer_id: str,
                  headers: Headers = None) -> JsonDict:
    """Read one servicing transfer with its three dimensions."""
    return data_of(
        api.get_servicing_transfer(transfer_id, headers or U.MANAGER)
    )


def map_data(api: ApiClient, transfer_id: str, buyer_id: str,
             mapping_scheme: str = "MSP_TO_MSP",
             headers: Headers = None) -> JsonDict:
    """Record the loan-level data mapping scheme."""
    body = {"mapping_scheme": mapping_scheme}
    return data_of(
        api.map_data(transfer_id, body,
                     headers or U.make_buyer_headers(buyer_id))
    )


def map_escrow(api: ApiClient, transfer_id: str, buyer_id: str,
               headers: Headers = None) -> JsonDict:
    """Sweep custodial escrow and suspense balances onto the transfer."""
    return data_of(
        api.map_escrow(transfer_id, headers or U.make_buyer_headers(buyer_id))
    )


def rollback_escrow(api: ApiClient, transfer_id: str, buyer_id: str,
                    reason: str = "custodial account number wrong on the "
                                  "transferee side",
                    headers: Headers = None) -> JsonDict:
    """Reverse the custodial sweep."""
    body = {"reason": reason}
    return data_of(
        api.rollback_escrow_mapping(
            transfer_id, body, headers or U.make_buyer_headers(buyer_id))
    )


def reconcile(api: ApiClient, transfer_id: str, buyer_id: str,
              headers: Headers = None) -> JsonDict:
    """Reconcile swept custodial funds against the frozen portfolio total."""
    return data_of(
        api.reconcile(transfer_id, headers or U.make_buyer_headers(buyer_id))
    )


def transfer_pipeline(api: ApiClient, transfer_id: str, buyer_id: str,
                      headers: Headers = None) -> JsonDict:
    """Hand over the loss-mitigation pipeline."""
    return data_of(
        api.transfer_pipeline(transfer_id,
                              headers or U.make_buyer_headers(buyer_id))
    )


def send_notice(api: ApiClient, transfer_id: str, loan_id: str,
                sender_id: str, notice_type: str = "TRANSFEROR_15DAY",
                effective_date: str = C.TRANSFER_DATE,
                headers: Headers = None) -> JsonDict:
    """Send one statutory servicing-transfer notice to a borrower."""
    body = {
        "notice_type": notice_type,
        "loan_id": loan_id,
        "effective_date": effective_date,
    }
    if headers is None:
        headers = (
            U.make_buyer_headers(sender_id)
            if notice_type == "TRANSFEREE_15DAY"
            else U.make_seller_headers(sender_id)
        )
    return data_of(api.create_notice(transfer_id, body, headers), 201)


def send_notices(api: ApiClient, transfer_id: str, loan_ids: list,
                 sender_id: str, notice_type: str = "TRANSFEROR_15DAY",
                 effective_date: str = C.TRANSFER_DATE) -> JsonList:
    """Notice every borrower on the awarded tape."""
    return [
        send_notice(api, transfer_id, loan_id, sender_id, notice_type,
                    effective_date)
        for loan_id in loan_ids
    ]


def attest_notices(api: ApiClient, transfer_id: str,
                   headers: Headers = None) -> JsonDict:
    """Attest that every transferred borrower was noticed in time."""
    return data_of(
        api.attest_notices(transfer_id, headers or U.COMPLIANCE)
    )


def complete_transfer(api: ApiClient, transfer_id: str,
                      headers: Headers = None) -> JsonDict:
    """Complete the transfer of servicing."""
    return data_of(
        api.complete_transfer(transfer_id, headers or U.MANAGER)
    )


# ---------------------------------------------------------------------------
# Post-transfer error resolution
# ---------------------------------------------------------------------------
def open_error_case(api: ApiClient, transfer_id: str, loan_id: str,
                    category: str = "ESCROW",
                    description: str = "escrow disbursement missed after "
                                       "transfer",
                    headers: Headers = None) -> JsonDict:
    """Open a notice-of-error case against a transferred loan."""
    body = {
        "loan_id": loan_id,
        "category": category,
        "description": description,
    }
    return data_of(
        api.create_error_case(transfer_id, body, headers or U.COMPLIANCE), 201
    )


def acknowledge_case(api: ApiClient, case_id: str, buyer_id: str,
                     headers: Headers = None) -> JsonDict:
    """Acknowledge a notice of error."""
    return data_of(
        api.acknowledge_error_case(case_id,
                                   headers or U.make_buyer_headers(buyer_id))
    )


def resolve_case(api: ApiClient, case_id: str, buyer_id: str,
                 remediation_cents: int = 0,
                 resolution_note: str = "escrow disbursement reissued",
                 headers: Headers = None) -> JsonDict:
    """Resolve a notice of error, recording any borrower remediation."""
    body = {
        "remediation_cents": remediation_cents,
        "resolution_note": resolution_note,
    }
    return data_of(
        api.resolve_error_case(case_id, body,
                               headers or U.make_buyer_headers(buyer_id))
    )


def reopen_case(api: ApiClient, case_id: str,
                reason: str = "borrower reports the correction never posted",
                headers: Headers = None) -> JsonDict:
    """Reopen a resolved case."""
    body = {"reason": reason}
    return data_of(
        api.reopen_error_case(case_id, body, headers or U.COMPLIANCE)
    )


def read_error_case(api: ApiClient, case_id: str,
                    headers: Headers = None) -> JsonDict:
    """Read one error resolution case."""
    return data_of(api.get_error_case(case_id, headers or U.COMPLIANCE))


# ---------------------------------------------------------------------------
# Hedging
# ---------------------------------------------------------------------------
def open_hedge(api: ApiClient, portfolio_id: str, instrument: str = "TBA_LONG",
               notional_cents: int = 260000, hedge_ratio_pct=60,
               headers: Headers = None) -> JsonDict:
    """Open a hedge against the servicing asset at the current curve."""
    body = {
        "portfolio_id": portfolio_id,
        "instrument": instrument,
        "notional_cents": notional_cents,
        "hedge_ratio_pct": hedge_ratio_pct,
    }
    return data_of(api.create_hedge_position(body, headers or U.HEDGE), 201)


def close_hedge(api: ApiClient, hedge_id: str,
                headers: Headers = None) -> JsonDict:
    """Close a hedge position."""
    return data_of(api.close_hedge_position(hedge_id, headers or U.HEDGE))


def read_hedge(api: ApiClient, hedge_id: str,
               headers: Headers = None) -> JsonDict:
    """Read one hedge position with its current mark."""
    return data_of(api.get_hedge_position(hedge_id, headers or U.HEDGE))


def hedge_effectiveness(api: ApiClient, portfolio_id: str,
                        headers: Headers = None) -> JsonDict:
    """Read the portfolio's hedge effectiveness summary."""
    return data_of(
        api.get_hedge_effectiveness(portfolio_id, headers or U.HEDGE)
    )
