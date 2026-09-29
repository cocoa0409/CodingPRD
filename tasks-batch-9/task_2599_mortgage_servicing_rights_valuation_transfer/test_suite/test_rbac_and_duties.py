"""
Who may act on the transfer desk, and under whose identity.

This module pins the access-control layer of the servicing-rights desk: the
authentication header every business call must carry (and the single
clock-control exemption), the exhaustive per-endpoint role lists that keep the
eight desk roles' write surfaces disjoint, the entity-backed identity that ties
a selling or acquiring servicer to its own counterparty row, the three
segregation-of-duties pairs that keep one operator from taking both halves of a
control, and the positive half of the matrix — every role driving its own
operations from onboarding through to the completed transfer.
"""

from test_helpers import (
    C, F, U,
    ApiClient, Headers, JsonDict,
    assert_holdback_split, assert_readiness, build_completed_transfer,
    build_locked_portfolio,
    data_of, ids_of, refresh_agreement, rows_of, validate_error,
    ERR_NOT_RESOURCE_OWNER, ERR_SEGREGATION_OF_DUTIES, ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

# A loan Delta Servicing tries to push into a pool that is not its own, and
# then adds to its own pool under the very same loan number.
_DELTA_LOAN = {
    "loan_number": "D-0001",
    "upb_cents": 5000000,
    "note_rate_pct": 6.25,
    "servicing_fee_bps": 25,
    "escrow_balance_cents": 0,
    "suspense_balance_cents": 0,
    "delinquency_bucket": "CURRENT",
    "loss_mit_status": "NONE",
    "state_code": "OR",
}

# A fifth loan, offered to a pool whose tape is already frozen.
_EXTRA_LOAN = dict(
    C.LOANS_T[0], loan_number="T-9001", state_code="AZ",
    escrow_balance_cents=0, suspense_balance_cents=0,
)

# Pool T priced by the desk-base case at curve C1: the static valuation is
# 171576 cents, so a 95 percent reserve floor over the whole tape stamps
# 171576 * 95 / 100 = 162997.2 -> 162997 cents.
_POOL_T_RESERVE_CENTS = 162997

# The four strata of pool T each price at 10000050 * 118 / 10000 = 118000.59
# -> 118001 cents, so the contractual purchase price is 472004 cents; a 6
# percent holdback of that is 28320.24 -> 28320, leaving a 443684 cent wire.
_PURCHASE_PRICE_CENTS = 472004
_HOLDBACK_CENTS = 28320
_SETTLEMENT_WIRE_CENTS = 443684


def _writes_owned_by_other_roles(api: ApiClient, env: JsonDict,
                                 headers: Headers) -> list:
    """
    Four desk writes, each the exclusive operation of a different role, as
    labelled callables issued under the given caller's headers: adding a loan
    (the selling servicer), running a valuation (the analyst), bidding (the
    acquiring servicer) and publishing a rate curve (the hedge desk).
    """
    valuation_body = {
        "assumption_set_id": env["assumption_set_id"],
        "method": "DETERMINISTIC_STATIC",
        "expected_portfolio_version": env["portfolio_version"],
    }
    bid_body = {
        "bidder_id": env["buyer_id"],
        "price_bps": 118,
        "holdback_pct": 6,
        "expected_bid_package_version": env["package_version"],
    }
    return [
        ("add a loan to the pool",
         lambda: api.create_loan(env["portfolio_id"], _EXTRA_LOAN, headers)),
        ("run a valuation",
         lambda: api.create_valuation_run(env["portfolio_id"], valuation_body,
                                          headers)),
        ("submit a bid",
         lambda: api.create_bid(env["package_id"], bid_body, headers)),
        ("publish a rate curve",
         lambda: api.create_rate_curve(C.CURVE_C2, headers)),
    ]


def test_lock_tape_without_a_user_id_header_is_unauthenticated(api: ApiClient):
    """
    Freezing a pool from a caller that declares the right role but no identity
    at all is refused before anything else is considered, and changes nothing.

    PRD: "A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/a_write_with_no_user_id_header_returns_unauthenticated
    """
    env = build_locked_portfolio(api, lock=False)
    before = F.read_portfolio(api, env["portfolio_id"])

    absent = api.lock_tape(env["portfolio_id"],
                           U.headers_without_user_id(U.SELLER_SERVICER))
    validate_error(absent, ERR_UNAUTHENTICATED)

    blank = api.lock_tape(env["portfolio_id"],
                          U.headers_with_empty_user_id(U.SELLER_SERVICER))
    validate_error(blank, ERR_UNAUTHENTICATED)

    untouched = F.read_portfolio(api, env["portfolio_id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["tape_locked_at"] is None
    assert untouched["version"] == before["version"]

    locked = F.lock_tape(api, env["portfolio_id"], env["seller_id"])
    assert locked["status"] == "TAPE_LOCKED"
    assert locked["tape_locked_at"] is not None


def test_only_the_clock_control_answers_without_an_identity(api: ApiClient):
    """
    The logical-clock control is the one endpoint that works with no
    authentication headers at all, while a business read still needs an
    identity.

    PRD: "It is the one endpoint that does not require authentication headers, though it is authorized for `PlatformAdmin`; it changes no entity state."

    Design: Corner/rbac/a_write_with_no_user_id_header_returns_unauthenticated
    """
    env = build_locked_portfolio(api, lock=False)

    anonymous_clock = api.set_current_utc({"to_iso8601": C.CLOCK_AUG_10},
                                          U.NO_HEADERS)
    assert data_of(anonymous_clock)["current_utc"].startswith("2026-08-10")

    anonymous_read = api.get_portfolio(
        env["portfolio_id"], U.headers_without_user_id(U.SELLER_SERVICER))
    validate_error(anonymous_read, ERR_UNAUTHENTICATED)


def test_analyst_cannot_publish_the_package_it_cut_the_tape_for(
        api: ApiClient, valued_portfolio: JsonDict):
    """
    The analyst who created and stratified a package is still not on the
    publication endpoint's role list, so the publish is refused and the reserve
    is left unstamped until the transaction manager takes it.

    PRD: "The Authorized Role(s) column is exhaustive: a request whose `X-User-Role` is not listed for the endpoint it calls is refused with `ERR_UNAUTHORIZED` (HTTP 403), and a request with a missing or empty `X-User-ID` is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before the role is even considered."

    Design: Corner/rbac/an_analyst_publishing_a_package_returns_forbidden
    """
    env = valued_portfolio
    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"], headers=U.ANALYST)
    stratified = F.stratify(api, package["id"])
    assert stratified["status"] == "STRATIFIED"

    refused = api.publish_bid_package(package["id"], U.ANALYST)
    validate_error(refused, ERR_UNAUTHORIZED)

    unchanged = F.read_package(api, package["id"])
    assert unchanged["status"] == "STRATIFIED"
    assert unchanged["published_at"] is None
    assert unchanged["reserve_price_cents"] is None
    assert unchanged["version"] == stratified["version"]

    published = F.publish(api, package["id"])
    assert published["status"] == "PUBLISHED"
    assert published["reserve_price_cents"] == _POOL_T_RESERVE_CENTS


def test_an_unknown_role_name_is_also_refused_on_publish(
        api: ApiClient, stratified_package: JsonDict):
    """
    A role name the desk does not define is refused with the same
    authorization error as a known but unlisted role.

    PRD: "A request whose `X-User-Role` is absent, is not one of the eight roles enumerated below, or is a valid role that is simply not authorized for the endpoint being called, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/an_analyst_publishing_a_package_returns_forbidden
    """
    env = stratified_package

    unknown = api.publish_bid_package(
        env["package_id"], U.headers_with_unknown_role(C.MANAGER_ID))
    validate_error(unknown, ERR_UNAUTHORIZED)

    roleless = api.publish_bid_package(env["package_id"],
                                       U.headers_without_role(C.MANAGER_ID))
    validate_error(roleless, ERR_UNAUTHORIZED)

    unchanged = F.read_package(api, env["package_id"])
    assert unchanged["status"] == "STRATIFIED"
    assert unchanged["reserve_price_cents"] is None


def test_platform_admin_is_refused_on_every_desk_write(
        api: ApiClient, published_package: JsonDict):
    """
    The admin that onboarded both counterparties and drives the clock is
    refused on four consecutive writes that belong to other roles, and none of
    the four refusals moves any state.

    PRD: "Their write surfaces are deliberately disjoint: no role may perform another role's exclusive operations, and `PlatformAdmin` is emphatically **not** a hierarchical override — it onboards and suspends counterparties and drives the logical clock, and it may read anything, but it cannot value a pool, publish a package, bid, award, decide an approval, attest notices or release a holdback."

    Design: Corner/rbac/platform_admin_cannot_perform_any_desk_write
    """
    env = published_package
    before = F.read_portfolio(api, env["portfolio_id"])

    for label, attempt in _writes_owned_by_other_roles(api, env, U.ADMIN):
        response = attempt()
        assert response.status_code == 403, (
            f"the platform admin was allowed to {label}: "
            f"{response.status_code} {response.text}"
        )
        validate_error(response, ERR_UNAUTHORIZED)

    after = F.read_portfolio(api, env["portfolio_id"])
    assert after["status"] == "TAPE_LOCKED"
    assert after["loan_count"] == 4
    assert after["version"] == before["version"]

    package = F.read_package(api, env["package_id"])
    assert package["bid_count"] == 0
    assert package["version"] == env["package_version"]

    curves = rows_of(api.list_rate_curves(U.ADMIN))
    assert ids_of(curves) == [env["curve_id"]]


def test_platform_admin_keeps_its_own_onboarding_and_clock_operations(
        api: ApiClient, desk: JsonDict):
    """
    The same admin identity still registers and suspends counterparties, drives
    the logical clock, opens a portfolio for a seller and reads what it opened.

    PRD: "A `PlatformAdmin` registers and suspends counterparties, may open a portfolio jointly with a `SellerServicer`, and drives the logical clock."

    Design: Corner/rbac/platform_admin_cannot_perform_any_desk_write
    """
    env = desk

    extra = F.create_counterparty(api, C.BUYER_CHARLIE)
    assert extra["status"] == "ACTIVE"
    suspended = F.suspend_counterparty(api, extra["id"])
    assert suspended["status"] == "SUSPENDED"

    F.set_clock(api, C.CLOCK_AUG_10)

    opened = data_of(api.create_portfolio(
        {"seller_id": env["seller_id"], "portfolio_name": "Pool-Admin",
         "agency_type": "FNMA"}, U.ADMIN), 201)
    assert opened["status"] == "DRAFT"
    assert opened["seller_id"] == env["seller_id"]

    read_back = data_of(api.get_portfolio(opened["id"], U.ADMIN))
    assert read_back["id"] == opened["id"]


def test_agency_approver_and_hedge_desk_are_confined_to_their_own_writes(
        api: ApiClient, published_package: JsonDict):
    """
    The same four writes are refused for the agency approver and for the hedge
    desk, except the curve publication that is the hedge desk's own operation.

    PRD: "Their write surfaces are deliberately disjoint: no role may perform another role's exclusive operations, and `PlatformAdmin` is emphatically **not** a hierarchical override — it onboards and suspends counterparties and drives the logical clock, and it may read anything, but it cannot value a pool, publish a package, bid, award, decide an approval, attest notices or release a holdback."

    Design: Corner/rbac/platform_admin_cannot_perform_any_desk_write
    """
    env = published_package
    own_operations = {
        U.AGENCY_APPROVER: set(),
        U.HEDGE_DESK: {"publish a rate curve"},
    }

    for headers in (U.APPROVER, U.HEDGE):
        role = headers["X-User-Role"]
        for label, attempt in _writes_owned_by_other_roles(api, env, headers):
            if label in own_operations[role]:
                continue
            response = attempt()
            assert response.status_code == 403, (
                f"{role} was allowed to {label}: "
                f"{response.status_code} {response.text}"
            )
            validate_error(response, ERR_UNAUTHORIZED)

    package = F.read_package(api, env["package_id"])
    assert package["bid_count"] == 0

    curve = F.create_rate_curve(api, C.CURVE_C2)
    assert curve["status"] == "ACTIVE"


def test_seller_cannot_add_loans_or_lock_another_sellers_portfolio(
        api: ApiClient):
    """
    A second selling servicer, correctly authenticated as its own counterparty
    row, is refused on both writes against a pool whose seller is somebody else,
    and both writes succeed once it works on the pool it does own.

    PRD: "`SellerServicer` and `BuyerServicer` are entity-backed roles: when `X-User-Role` is `SellerServicer`, `X-User-ID` is the `id` of the acting `Counterparty`, and ownership checks compare it to the `seller_id` of the `ServicingPortfolio` the operation touches."

    Design: Corner/rbac/a_seller_cannot_write_to_another_sellers_portfolio
    """
    env = build_locked_portfolio(api, lock=False)
    before = F.read_portfolio(api, env["portfolio_id"])
    delta = F.create_seller(api, legal_name="Delta Servicing LLC")
    delta_headers = U.make_seller_headers(delta["id"])

    intruding_loan = api.create_loan(env["portfolio_id"], _DELTA_LOAN,
                                     delta_headers)
    validate_error(intruding_loan, ERR_NOT_RESOURCE_OWNER)

    intruding_lock = api.lock_tape(env["portfolio_id"], delta_headers)
    validate_error(intruding_lock, ERR_NOT_RESOURCE_OWNER)

    untouched = F.read_portfolio(api, env["portfolio_id"])
    assert untouched["loan_count"] == 4
    assert untouched["status"] == "DRAFT"
    assert untouched["version"] == before["version"]

    own_pool = F.create_portfolio(api, delta["id"], name="Pool-D",
                                  headers=delta_headers)
    own_loan = F.add_loan(api, own_pool["id"], delta["id"], _DELTA_LOAN)
    assert own_loan["loan_number"] == "D-0001"
    own_locked = F.lock_tape(api, own_pool["id"], delta["id"])
    assert own_locked["status"] == "TAPE_LOCKED"


def test_buyer_cannot_revise_a_bid_placed_by_another_bidder(
        api: ApiClient, live_bid: JsonDict):
    """
    A revision to a countered bid is refused when the acquiring servicer making
    it is not the bidder on record, and the bid keeps its countered price until
    the true bidder revises.

    PRD: "When `X-User-Role` is `BuyerServicer`, `X-User-ID` is likewise the `id` of the acting `Counterparty`, and ownership checks compare it to the `bidder_id` of the `Bid` being revised or to the `buyer_id` of the `PurchaseAgreement` behind the transfer or error case being worked, whichever the operation implies."

    Design: Corner/rbac/a_seller_cannot_write_to_another_sellers_portfolio
    """
    env = live_bid
    countered = F.counter(api, env["bid_id"], 122)
    assert countered["status"] == "COUNTERED"

    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)
    intruding = api.revise_bid(env["bid_id"],
                               {"price_bps": 121, "holdback_pct": 6},
                               U.make_buyer_headers(charlie["id"]))
    validate_error(intruding, ERR_NOT_RESOURCE_OWNER)

    unchanged = F.read_bid(api, env["bid_id"])
    assert unchanged["status"] == "COUNTERED"
    assert unchanged["price_bps"] == 118

    revised = F.revise(api, env["bid_id"], env["buyer_id"], 121)
    assert revised["status"] == "REVISED"
    assert revised["price_bps"] == 121


def test_buyer_cannot_map_data_on_another_buyers_transfer(
        api: ApiClient, settled_trade: JsonDict):
    """
    The data-mapping step on a live transfer is refused for an acquiring
    servicer that is not the buyer on the agreement behind it, and the work
    stream stays untouched until the real buyer runs it.

    PRD: "A mismatch is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/a_seller_cannot_write_to_another_sellers_portfolio
    """
    env = settled_trade
    charlie = F.create_counterparty(api, C.BUYER_CHARLIE)

    intruding = api.map_data(env["transfer_id"],
                             {"mapping_scheme": "MSP_TO_MSP"},
                             U.make_buyer_headers(charlie["id"]))
    validate_error(intruding, ERR_NOT_RESOURCE_OWNER)

    untouched = F.read_transfer(api, env["transfer_id"])
    assert untouched["data_status"] == "NOT_STARTED"

    mapped = F.map_data(api, env["transfer_id"], env["buyer_id"])
    assert mapped["data_status"] == "MAPPED"


def test_same_approver_cannot_decide_a_second_request_on_one_agreement(
        api: ApiClient, awarded_trade: JsonDict):
    """
    An agreement needing both an agency and an investor consent takes the first
    decision from one approver and refuses that approver's second decision, so
    the trade only reaches approval once a different officer signs.

    PRD: "When an `AgencyApprover` records a decision, the acting `X-User-ID` must differ from `decided_by_user_id` of *every* approval request on the same agreement that has already been decided."

    Design: Corner/rbac/segregation_of_duties_blocks_the_second_approval_decision
    """
    env = awarded_trade
    agency_request = F.create_approval_request(api, env["agreement_id"],
                                               "AGENCY", "FNMA")
    investor_request = F.create_approval_request(api, env["agreement_id"],
                                                 "INVESTOR", agency_type=None)
    pending = F.submit_for_approval(api, env["agreement_id"])
    assert pending["status"] == "PENDING_APPROVALS"
    assert pending["approval_pending_count"] == 2

    first = F.decide(api, agency_request["id"], headers=U.APPROVER)
    assert first["status"] == "APPROVED"
    assert first["decided_by_user_id"] == C.AGENCY_ID
    assert F.read_agreement(api, env["agreement_id"])[
        "approval_pending_count"] == 1

    second = api.decide_approval_request(investor_request["id"],
                                         {"decision": "APPROVED"}, U.APPROVER)
    validate_error(second, ERR_SEGREGATION_OF_DUTIES)

    still_pending = data_of(
        api.get_approval_request(investor_request["id"], U.MANAGER))
    assert still_pending["status"] == "PENDING"
    assert still_pending["decided_by_user_id"] is None

    other = F.decide(api, investor_request["id"], headers=U.APPROVER_2)
    assert other["decided_by_user_id"] == C.AGENCY_ID_2
    approved = F.read_agreement(api, env["agreement_id"])
    assert approved["status"] == "APPROVED"
    assert approved["approval_pending_count"] == 0


def test_attesting_officer_cannot_release_the_holdback(api: ApiClient):
    """
    The compliance officer who certified the borrower notices is refused when
    the holdback comes due, and a second officer releases the whole retained
    balance.

    PRD: "When a `ComplianceOfficer` releases holdback, the acting `X-User-ID` must differ from the `notice_attested_by_user_id` recorded on the bound servicing transfer."

    Design: Corner/rbac/segregation_of_duties_blocks_the_second_approval_decision
    """
    env = build_completed_transfer(api)
    assert env["transfer"]["notice_attested_by_user_id"] == C.COMPLIANCE_ID
    eligible_at = env["agreement"]["holdback_release_eligible_at"]
    assert eligible_at.startswith("2026-10-01")

    F.set_clock(api, "2026-10-01T00:00:00Z")
    attester = api.create_holdback_release(
        env["agreement_id"],
        {"expected_purchase_agreement_version": env["agreement_version"]},
        U.COMPLIANCE)
    validate_error(attester, ERR_SEGREGATION_OF_DUTIES)

    untouched = refresh_agreement(api, env)
    assert untouched["status"] == "SETTLED"
    assert_holdback_split(untouched, retained=_HOLDBACK_CENTS, released=0,
                          applied=0)

    released = F.release_holdback(api, env["agreement_id"],
                                  untouched["version"])
    assert released["status"] == "HOLDBACK_RELEASED"
    assert_holdback_split(released, retained=0, released=_HOLDBACK_CENTS,
                          applied=0)


def test_manager_cannot_award_against_its_own_valuation_run(
        api: ApiClient, live_bid: JsonDict):
    """
    An award signed by the same operator identity that ran the mark behind the
    package is refused, and the trade is only drafted once a different manager
    takes the award.

    PRD: "When a `TransactionManager` awards a package, the acting `X-User-ID` must differ from `run_by_user_id` of the valuation run the package is bound to."

    Design: Corner/rbac/segregation_of_duties_blocks_the_second_approval_decision
    """
    env = live_bid
    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["run_by_user_id"] == C.ANALYST_ID

    self_award = api.award_bid_package(
        env["package_id"],
        {"winning_bid_id": env["bid_id"], "rep_warrant_days": 30,
         "indemnification_days": 45},
        U.make_manager_headers(C.ANALYST_ID))
    validate_error(self_award, ERR_SEGREGATION_OF_DUTIES)

    assert F.read_package(api, env["package_id"])["status"] == "PUBLISHED"
    assert F.read_bid(api, env["bid_id"])["status"] == "SUBMITTED"

    agreement = F.award(api, env["package_id"], env["bid_id"])
    assert agreement["status"] == "DRAFTED"
    assert agreement["drafted_by_user_id"] == C.MANAGER_ID


def test_both_trade_sides_read_the_same_settled_agreement(
        api: ApiClient, settled_trade: JsonDict):
    """
    The selling and the acquiring servicer are both on the read lists for the
    agreement and for the transfer, and the two sides of the trade see exactly
    the same economics and the same operational readiness.

    PRD: "The Authorized Role(s) column is exhaustive: a request whose `X-User-Role` is not listed for the endpoint it calls is refused with `ERR_UNAUTHORIZED` (HTTP 403), and a request with a missing or empty `X-User-ID` is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before the role is even considered."

    Design: Corner/rbac/both_trade_sides_may_read_the_agreement_they_are_party_to
    """
    env = settled_trade

    seller_view = F.read_agreement(api, env["agreement_id"],
                                   headers=env["seller_headers"])
    buyer_view = F.read_agreement(api, env["agreement_id"],
                                  headers=env["buyer_headers"])

    for view in (seller_view, buyer_view):
        assert view["status"] == "SETTLED"
        assert view["purchase_price_cents"] == _PURCHASE_PRICE_CENTS
        assert view["settlement_wire_cents"] == _SETTLEMENT_WIRE_CENTS
        assert view["holdback_cents"] == _HOLDBACK_CENTS
    assert seller_view == buyer_view

    seller_transfer = F.read_transfer(api, env["transfer_id"],
                                      headers=env["seller_headers"])
    buyer_transfer = F.read_transfer(api, env["transfer_id"],
                                     headers=env["buyer_headers"])
    assert_readiness(seller_transfer, "NOT_READY")
    assert_readiness(buyer_transfer, "NOT_READY")
    assert seller_transfer == buyer_transfer


def test_neither_trade_side_may_write_on_the_agreement_or_transfer(
        api: ApiClient, settled_trade: JsonDict):
    """
    Settling and completing belong to the transaction manager alone, so the
    seller is refused on the settle and the buyer on the completion even though
    both are party to the trade, and the refusal outranks the state of either
    object.

    PRD: "Their write surfaces are deliberately disjoint: no role may perform another role's exclusive operations, and `PlatformAdmin` is emphatically **not** a hierarchical override — it onboards and suspends counterparties and drives the logical clock, and it may read anything, but it cannot value a pool, publish a package, bid, award, decide an approval, attest notices or release a holdback."

    Design: Corner/rbac/both_trade_sides_may_read_the_agreement_they_are_party_to
    """
    env = settled_trade

    seller_settle = api.settle_agreement(
        env["agreement_id"],
        {"sale_date": C.SALE_DATE, "transfer_date": C.TRANSFER_DATE},
        env["seller_headers"])
    validate_error(seller_settle, ERR_UNAUTHORIZED)

    buyer_complete = api.complete_transfer(env["transfer_id"],
                                           env["buyer_headers"])
    validate_error(buyer_complete, ERR_UNAUTHORIZED)

    assert F.read_agreement(api, env["agreement_id"])["status"] == "SETTLED"
    assert F.read_transfer(api, env["transfer_id"])["status"] == "IN_PROGRESS"


def test_every_role_executes_its_own_operations_through_to_completion(
        api: ApiClient):
    """
    One trade is driven from onboarding to a completed transfer of servicing
    with every step taken by the single role that owns it, so no operation ever
    needs an administrator standing in for somebody else.

    PRD: "Their write surfaces are deliberately disjoint: no role may perform another role's exclusive operations, and `PlatformAdmin` is emphatically **not** a hierarchical override — it onboards and suspends counterparties and drives the logical clock, and it may read anything, but it cannot value a pool, publish a package, bid, award, decide an approval, attest notices or release a holdback."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations_end_to_end
    """
    # The administrator drives the clock and onboards both servicers.
    F.set_clock(api, C.CLOCK_DEFAULT)
    seller = F.create_seller(api)
    buyer = F.create_buyer(api)

    # The analyst owns the model inputs; the hedge desk owns the curve.
    assumptions = F.create_assumption_set(api)
    curve = F.create_rate_curve(api)
    assert curve["status"] == "ACTIVE"

    # The selling servicer builds the pool and freezes the tape.
    portfolio = F.create_portfolio(api, seller["id"])
    loans = F.add_loans(api, portfolio["id"], seller["id"], C.LOANS_T)
    loan_ids = [loan["id"] for loan in loans]
    locked = F.lock_tape(api, portfolio["id"], seller["id"])
    assert locked["status"] == "TAPE_LOCKED"

    # The analyst values the frozen tape; the manager markets it.
    run = F.run_valuation(api, portfolio["id"], assumptions["id"],
                          locked["version"])
    assert run["run_by_user_id"] == C.ANALYST_ID
    package = F.create_bid_package(api, portfolio["id"], run["id"])
    F.stratify(api, package["id"])
    published = F.publish(api, package["id"])
    assert published["reserve_price_cents"] == _POOL_T_RESERVE_CENTS

    # The acquiring servicer bids; the manager awards and drafts the trade.
    bid = F.submit_bid(api, package["id"], buyer["id"], published["version"])
    agreement = F.award(api, package["id"], bid["id"])
    assert agreement["drafted_by_user_id"] == C.MANAGER_ID
    assert agreement["purchase_price_cents"] == _PURCHASE_PRICE_CENTS

    # The manager raises the consent prerequisite; the approver decides it.
    request = F.create_approval_request(api, agreement["id"], "AGENCY", "FNMA")
    F.submit_for_approval(api, agreement["id"])
    decided = F.decide(api, request["id"], headers=U.APPROVER)
    assert decided["decided_by_user_id"] == C.AGENCY_ID

    # The manager settles, which opens the operational transfer.
    settled = F.settle(api, agreement["id"])
    assert settled["status"] == "SETTLED"
    assert settled["settlement_wire_cents"] == _SETTLEMENT_WIRE_CENTS
    transfer = F.find_transfer(api, agreement["id"])

    # The acquiring servicer runs the data, custodial and pipeline streams.
    F.map_data(api, transfer["id"], buyer["id"])
    F.map_escrow(api, transfer["id"], buyer["id"])
    F.reconcile(api, transfer["id"], buyer["id"])
    F.transfer_pipeline(api, transfer["id"], buyer["id"])

    # The seller notices every borrower; the compliance officer attests.
    F.send_notices(api, transfer["id"], loan_ids, seller["id"])
    attested = F.attest_notices(api, transfer["id"])
    assert attested["notice_attested_by_user_id"] == C.COMPLIANCE_ID

    # The administrator moves the clock to the effective date; the manager
    # completes the transfer of servicing.
    F.set_clock(api, C.CLOCK_TRANSFER_DAY)
    F.complete_transfer(api, transfer["id"])

    final = F.read_transfer(api, transfer["id"], headers=U.COMPLIANCE)
    assert final["status"] == "COMPLETED"
    assert_readiness(final, "READY")
    assert final["escrow_transferred_cents"] == 400000
    assert final["transferred_loan_count"] == 4

    emptied = F.read_portfolio(api, portfolio["id"])
    assert emptied["status"] == "TRANSFERRED"
    assert emptied["loan_count"] == 0
