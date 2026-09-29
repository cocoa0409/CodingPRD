"""
Composite state builders and pytest fixtures.

The runner relaunches the service with an empty database before every test, so
every precondition has to be built from scratch through the documented
endpoints. The builders below assemble the compositions this domain keeps
needing — a staffed desk, a locked pool, a valued pool, a published package, a
live bid, an awarded trade, an approved and settled trade, a transfer whose
three work streams are all finished, and a completed transfer — so an individual
test only has to describe what is unusual about its own scenario.

Every builder takes and returns one mutable environment dict, so layers can be
composed in any combination:

    env = build_published_package(api, scheme="BY_NOTE_RATE")
    env = build_awarded_trade(api, env)

Environment keys, once the corresponding layer has run:

    clock, seller, seller_id, buyer, buyer_id, seller_headers, buyer_headers,
    assumption_set, assumption_set_id, curve, curve_id,
    portfolio, portfolio_id, portfolio_version, loans, loan_ids,
    valuation_run, valuation_run_id,
    package, package_id, package_version, tape_lines, included_loan_ids,
    bid, bid_id, agreement, agreement_id, agreement_version,
    approval_requests, transfer, transfer_id, notices

Nothing here asserts a rule under test: a failure inside a builder means the
precondition could not be established, not that a rule is wrong.
"""

import pytest

from . import constants as C
from . import factories as F
from . import test_users as U
from .api_client import ApiClient
from .types import JsonDict


# ---------------------------------------------------------------------------
# Tier 1 — the desk itself
# ---------------------------------------------------------------------------
def build_desk(api: ApiClient, env: JsonDict = None,
               clock: str = C.CLOCK_DEFAULT,
               seller: JsonDict = None, buyer: JsonDict = None,
               assumptions: JsonDict = None, curve: JsonDict = None) -> JsonDict:
    """
    Move the clock, register the selling and acquiring servicers, create the
    desk-base assumption vector and publish the opening rate curve.
    """
    env = env if env is not None else {}
    F.set_clock(api, clock)
    env["clock"] = clock

    env["seller"] = F.create_counterparty(api, seller or C.SELLER_ALPHA)
    env["seller_id"] = env["seller"]["id"]
    env["seller_headers"] = U.make_seller_headers(env["seller_id"])

    env["buyer"] = F.create_counterparty(api, buyer or C.BUYER_BRAVO)
    env["buyer_id"] = env["buyer"]["id"]
    env["buyer_headers"] = U.make_buyer_headers(env["buyer_id"])

    env["assumption_set"] = F.create_assumption_set(
        api, assumptions or C.ASSUMPTION_DESK_BASE)
    env["assumption_set_id"] = env["assumption_set"]["id"]

    env["curve"] = F.create_rate_curve(api, curve or C.CURVE_C1)
    env["curve_id"] = env["curve"]["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 2 — a locked pool
# ---------------------------------------------------------------------------
def build_locked_portfolio(api: ApiClient, env: JsonDict = None,
                           loans: list = None, name: str = "Pool-T",
                           agency_type: str = "FNMA", lock: bool = True,
                           **desk_kwargs) -> JsonDict:
    """
    Open a portfolio for the registered seller, load it with a pool of loans and
    lock the tape. Defaults to the four-loan pool T.
    """
    env = env if env is not None else build_desk(api, **desk_kwargs)
    if "seller_id" not in env:
        build_desk(api, env, **desk_kwargs)

    env["portfolio"] = F.create_portfolio(
        api, env["seller_id"], name=name, agency_type=agency_type)
    env["portfolio_id"] = env["portfolio"]["id"]
    env["loans"] = F.add_loans(
        api, env["portfolio_id"], env["seller_id"],
        loans if loans is not None else C.LOANS_T)
    env["loan_ids"] = [loan["id"] for loan in env["loans"]]

    if lock:
        env["portfolio"] = F.lock_tape(api, env["portfolio_id"],
                                       env["seller_id"])
    env["portfolio_version"] = env["portfolio"]["version"]
    return env


def refresh_portfolio(api: ApiClient, env: JsonDict) -> JsonDict:
    """Re-read the portfolio so its concurrency token is current."""
    env["portfolio"] = F.read_portfolio(api, env["portfolio_id"])
    env["portfolio_version"] = env["portfolio"]["version"]
    return env["portfolio"]


# ---------------------------------------------------------------------------
# Tier 3 — a valued pool
# ---------------------------------------------------------------------------
def build_valued_portfolio(api: ApiClient, env: JsonDict = None,
                           method: str = "DETERMINISTIC_STATIC",
                           **portfolio_kwargs) -> JsonDict:
    """Run a fair-value valuation against the locked tape."""
    env = env if env is not None else build_locked_portfolio(
        api, **portfolio_kwargs)
    if "portfolio_id" not in env:
        build_locked_portfolio(api, env, **portfolio_kwargs)

    env["valuation_run"] = F.run_valuation(
        api, env["portfolio_id"], env["assumption_set_id"],
        env["portfolio_version"], method=method)
    env["valuation_run_id"] = env["valuation_run"]["id"]
    refresh_portfolio(api, env)
    return env


# ---------------------------------------------------------------------------
# Tier 4 — a published package
# ---------------------------------------------------------------------------
def build_stratified_package(api: ApiClient, env: JsonDict = None,
                             scheme: str = "BY_STATE",
                             floor_pct=C.RESERVE_PRICE_FLOOR_PCT,
                             marketing_start_at: str = C.MARKETING_START_AT,
                             bid_deadline_at: str = C.BID_DEADLINE_AT,
                             **valuation_kwargs) -> JsonDict:
    """Create a bid package on the valued pool and cut its loan-level tape."""
    env = env if env is not None else build_valued_portfolio(
        api, **valuation_kwargs)
    if "valuation_run_id" not in env:
        build_valued_portfolio(api, env, **valuation_kwargs)

    env["package"] = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"], scheme=scheme,
        floor_pct=floor_pct, marketing_start_at=marketing_start_at,
        bid_deadline_at=bid_deadline_at)
    env["package_id"] = env["package"]["id"]
    env["package"] = F.stratify(api, env["package_id"])
    env["package_version"] = env["package"]["version"]
    env["tape_lines"] = F.list_tape_lines(api, env["package_id"])
    env["included_loan_ids"] = [
        line["loan_id"] for line in env["tape_lines"] if line["included"]
    ]
    return env


def build_published_package(api: ApiClient, env: JsonDict = None,
                            **stratify_kwargs) -> JsonDict:
    """Publish the stratified package and stamp its reserve price."""
    env = env if env is not None else build_stratified_package(
        api, **stratify_kwargs)
    if "package_id" not in env:
        build_stratified_package(api, env, **stratify_kwargs)

    env["package"] = F.publish(api, env["package_id"])
    env["package_version"] = env["package"]["version"]
    return env


def refresh_package(api: ApiClient, env: JsonDict) -> JsonDict:
    """Re-read the package so its concurrency token is current."""
    env["package"] = F.read_package(api, env["package_id"])
    env["package_version"] = env["package"]["version"]
    return env["package"]


# ---------------------------------------------------------------------------
# Tier 5 — a live bid and an awarded trade
# ---------------------------------------------------------------------------
def build_live_bid(api: ApiClient, env: JsonDict = None, price_bps: int = 118,
                   holdback_pct=6, **package_kwargs) -> JsonDict:
    """Submit one bid from the registered buyer onto the published package."""
    env = env if env is not None else build_published_package(
        api, **package_kwargs)
    if "package_id" not in env:
        build_published_package(api, env, **package_kwargs)

    env["bid"] = F.submit_bid(
        api, env["package_id"], env["buyer_id"], env["package_version"],
        price_bps=price_bps, holdback_pct=holdback_pct)
    env["bid_id"] = env["bid"]["id"]
    refresh_package(api, env)
    return env


def build_awarded_trade(api: ApiClient, env: JsonDict = None,
                        rep_warrant_days: int = 30,
                        indemnification_days: int = 45,
                        **bid_kwargs) -> JsonDict:
    """Award the package to the live bid and draft the purchase agreement."""
    env = env if env is not None else build_live_bid(api, **bid_kwargs)
    if "bid_id" not in env:
        build_live_bid(api, env, **bid_kwargs)

    env["agreement"] = F.award(
        api, env["package_id"], env["bid_id"],
        rep_warrant_days=rep_warrant_days,
        indemnification_days=indemnification_days)
    env["agreement_id"] = env["agreement"]["id"]
    env["agreement_version"] = env["agreement"]["version"]
    return env


def refresh_agreement(api: ApiClient, env: JsonDict) -> JsonDict:
    """Re-read the agreement so its concurrency token is current."""
    env["agreement"] = F.read_agreement(api, env["agreement_id"])
    env["agreement_version"] = env["agreement"]["version"]
    return env["agreement"]


# ---------------------------------------------------------------------------
# Tier 6 — approvals and settlement
# ---------------------------------------------------------------------------
def build_approved_agreement(api: ApiClient, env: JsonDict = None,
                             decision: str = "APPROVED",
                             condition_text: str = None,
                             approver_type: str = "AGENCY",
                             agency_type: str = "FNMA",
                             **award_kwargs) -> JsonDict:
    """
    Raise one approval prerequisite, submit the agreement for approval and record
    a single decision on it.
    """
    env = env if env is not None else build_awarded_trade(api, **award_kwargs)
    if "agreement_id" not in env:
        build_awarded_trade(api, env, **award_kwargs)

    request = F.create_approval_request(
        api, env["agreement_id"], approver_type=approver_type,
        agency_type=agency_type if approver_type == "AGENCY" else None)
    env["approval_requests"] = [request]
    env["approval_request_id"] = request["id"]
    F.submit_for_approval(api, env["agreement_id"])
    env["approval_requests"][0] = F.decide(
        api, request["id"], decision=decision, condition_text=condition_text)
    refresh_agreement(api, env)
    return env


def build_settled_trade(api: ApiClient, env: JsonDict = None,
                        sale_date: str = C.SALE_DATE,
                        transfer_date: str = C.TRANSFER_DATE,
                        condition_waiver_reference: str = None,
                        **approval_kwargs) -> JsonDict:
    """Settle the approved trade, which opens the servicing transfer."""
    env = env if env is not None else build_approved_agreement(
        api, **approval_kwargs)
    if "approval_requests" not in env:
        build_approved_agreement(api, env, **approval_kwargs)

    env["agreement"] = F.settle(
        api, env["agreement_id"], sale_date=sale_date,
        transfer_date=transfer_date,
        condition_waiver_reference=condition_waiver_reference)
    env["agreement_version"] = env["agreement"]["version"]
    env["transfer_date"] = transfer_date
    env["transfer"] = F.find_transfer(api, env["agreement_id"])
    env["transfer_id"] = env["transfer"]["id"]
    return env


def refresh_transfer(api: ApiClient, env: JsonDict) -> JsonDict:
    """Re-read the transfer and its three dimensions."""
    env["transfer"] = F.read_transfer(api, env["transfer_id"])
    return env["transfer"]


# ---------------------------------------------------------------------------
# Tier 7 — the three transfer work streams
# ---------------------------------------------------------------------------
def build_reconciled_data(api: ApiClient, env: JsonDict = None,
                          mapping_scheme: str = "MSP_TO_MSP",
                          **settle_kwargs) -> JsonDict:
    """Walk the data work stream from mapping through the custodial sweep to
    reconciliation."""
    env = env if env is not None else build_settled_trade(api, **settle_kwargs)
    if "transfer_id" not in env:
        build_settled_trade(api, env, **settle_kwargs)

    F.map_data(api, env["transfer_id"], env["buyer_id"],
               mapping_scheme=mapping_scheme)
    F.map_escrow(api, env["transfer_id"], env["buyer_id"])
    env["transfer"] = F.reconcile(api, env["transfer_id"], env["buyer_id"])
    return env


def build_attested_notices(api: ApiClient, env: JsonDict = None,
                           notice_type: str = "TRANSFEROR_15DAY",
                           **settle_kwargs) -> JsonDict:
    """Notice every borrower on the awarded tape and attest compliance."""
    env = env if env is not None else build_settled_trade(api, **settle_kwargs)
    if "transfer_id" not in env:
        build_settled_trade(api, env, **settle_kwargs)

    sender_id = (
        env["buyer_id"] if notice_type == "TRANSFEREE_15DAY"
        else env["seller_id"]
    )
    env["notices"] = F.send_notices(
        api, env["transfer_id"], env["included_loan_ids"], sender_id,
        notice_type=notice_type,
        effective_date=env.get("transfer_date", C.TRANSFER_DATE))
    env["transfer"] = F.attest_notices(api, env["transfer_id"])
    return env


def build_ready_transfer(api: ApiClient, env: JsonDict = None,
                         **settle_kwargs) -> JsonDict:
    """Finish all three work streams so the transfer stands READY."""
    env = env if env is not None else build_settled_trade(api, **settle_kwargs)
    if "transfer_id" not in env:
        build_settled_trade(api, env, **settle_kwargs)

    build_reconciled_data(api, env)
    build_attested_notices(api, env)
    env["transfer"] = F.transfer_pipeline(api, env["transfer_id"],
                                          env["buyer_id"])
    return env


def build_completed_transfer(api: ApiClient, env: JsonDict = None,
                             complete_at: str = C.CLOCK_TRANSFER_DAY,
                             **ready_kwargs) -> JsonDict:
    """Complete the transfer of servicing on the transfer date."""
    env = env if env is not None else build_ready_transfer(api, **ready_kwargs)
    if "transfer_id" not in env:
        build_ready_transfer(api, env, **ready_kwargs)

    if complete_at is not None:
        F.set_clock(api, complete_at)
        env["clock"] = complete_at
    env["transfer"] = F.complete_transfer(api, env["transfer_id"])
    refresh_agreement(api, env)
    return env


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def desk(api: ApiClient) -> JsonDict:
    """Clock at the default instant, both servicers, desk-base assumptions and
    the opening rate curve."""
    return build_desk(api)


@pytest.fixture
def locked_portfolio(api: ApiClient) -> JsonDict:
    """A staffed desk plus the four-loan pool T with its tape locked."""
    return build_locked_portfolio(api)


@pytest.fixture
def valued_portfolio(api: ApiClient) -> JsonDict:
    """Pool T locked and valued under the static method."""
    return build_valued_portfolio(api)


@pytest.fixture
def stratified_package(api: ApiClient) -> JsonDict:
    """A bid package on pool T whose tape is cut by state."""
    return build_stratified_package(api)


@pytest.fixture
def published_package(api: ApiClient) -> JsonDict:
    """A published package on pool T carrying a stamped reserve price."""
    return build_published_package(api)


@pytest.fixture
def live_bid(api: ApiClient) -> JsonDict:
    """A published package with one live bid from the registered buyer."""
    return build_live_bid(api)


@pytest.fixture
def awarded_trade(api: ApiClient) -> JsonDict:
    """An awarded package and the drafted purchase agreement."""
    return build_awarded_trade(api)


@pytest.fixture
def approved_agreement(api: ApiClient) -> JsonDict:
    """An agreement carrying one unconditional agency approval."""
    return build_approved_agreement(api)


@pytest.fixture
def settled_trade(api: ApiClient) -> JsonDict:
    """A settled trade with its servicing transfer open."""
    return build_settled_trade(api)


@pytest.fixture
def ready_transfer(api: ApiClient) -> JsonDict:
    """A transfer whose notice, data and pipeline work streams are all done."""
    return build_ready_transfer(api)


@pytest.fixture
def completed_transfer(api: ApiClient) -> JsonDict:
    """A transfer completed on the transfer date, with the loans moved over."""
    return build_completed_transfer(api)
