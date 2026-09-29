"""
Refusal behaviour of the servicing-rights transfer desk.

The desk is judged as much on what it turns away as on what it accepts, and the
identifier it reports is part of the contract. The tests here pin that surface:
every entity read discriminates its own identifier space with its own 404, a bid
filed on a package that is not open to the market is refused on state grounds
before any price is looked at, a bid may only be revised as the answer to a
counter, the three transfer work streams refuse steps taken out of order (each
with the specific code its own rule names), a borrower notice may only be issued
by the side the notice type belongs to, a package cannot be published on a
valuation the market has already invalidated, and holdback is not released while
borrower complaint concentration sits in the blocking tier.
"""

from test_helpers import (
    C,
    F,
    U,
    ApiClient,
    JsonDict,
    ERR_ASSUMPTION_SET_NOT_FOUND,
    ERR_APPROVAL_REQUEST_NOT_FOUND,
    ERR_BID_INVALID_STATE,
    ERR_BID_NOT_FOUND,
    ERR_BID_PACKAGE_NOT_FOUND,
    ERR_COMPLAINT_TIER_BLOCKS_RELEASE,
    ERR_COUNTERPARTY_NOT_FOUND,
    ERR_ERROR_CASE_NOT_FOUND,
    ERR_ESCROW_NOT_MAPPED,
    ERR_HEDGE_POSITION_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_NOTICE_SENDER_ROLE_MISMATCH,
    ERR_PACKAGE_NOT_ACCEPTING_BIDS,
    ERR_PORTFOLIO_NOT_FOUND,
    ERR_PURCHASE_AGREEMENT_NOT_FOUND,
    ERR_RATE_CURVE_NOT_FOUND,
    ERR_SERVICING_TRANSFER_NOT_FOUND,
    ERR_TAPE_LINE_NOT_FOUND,
    ERR_TRANSFER_INVALID_STATE,
    ERR_TRANSFER_NOT_READY,
    ERR_VALUATION_RUN_NOT_FOUND,
    ERR_VALUATION_STALE,
    assert_dimensions,
    assert_holdback_split,
    assert_readiness,
    assert_status,
    is_iso8601_timestamp,
    refresh_portfolio,
    rows_of,
    round_half_up,
    validate_error,
    validate_success,
)


def _unknown_id(suffix: str) -> str:
    """A well-formed identifier that no row on the desk carries."""
    return f"00000000-0000-0000-0000-0000000000{suffix}"


def test_every_entity_read_reports_its_own_not_found_code(api: ApiClient) -> None:
    """
    Thirteen reads of thirteen unknown identifiers answer with thirteen distinct
    not-found identifiers, none of them a shared generic code.

    PRD: "Each entity has its own not-found code — `ERR_COUNTERPARTY_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_ASSUMPTION_SET_NOT_FOUND`, `ERR_RATE_CURVE_NOT_FOUND`, `ERR_VALUATION_RUN_NOT_FOUND`, `ERR_BID_PACKAGE_NOT_FOUND`, `ERR_TAPE_LINE_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PURCHASE_AGREEMENT_NOT_FOUND`, `ERR_APPROVAL_REQUEST_NOT_FOUND`, `ERR_SERVICING_TRANSFER_NOT_FOUND`, `ERR_ERROR_CASE_NOT_FOUND` and `ERR_HEDGE_POSITION_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/every_entity_read_with_an_unknown_id_returns_its_own_not_found
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    reads = [
        ("counterparty", api.get_counterparty, "c1", ERR_COUNTERPARTY_NOT_FOUND),
        ("loan", api.get_loan, "c2", ERR_LOAN_NOT_FOUND),
        ("assumption set", api.get_assumption_set, "c3",
         ERR_ASSUMPTION_SET_NOT_FOUND),
        ("rate curve", api.get_rate_curve, "c4", ERR_RATE_CURVE_NOT_FOUND),
        ("valuation run", api.get_valuation_run, "c5", ERR_VALUATION_RUN_NOT_FOUND),
        ("bid package", api.get_bid_package, "c6", ERR_BID_PACKAGE_NOT_FOUND),
        ("tape line", api.get_tape_line, "c7", ERR_TAPE_LINE_NOT_FOUND),
        ("bid", api.get_bid, "c8", ERR_BID_NOT_FOUND),
        ("purchase agreement", api.get_purchase_agreement, "c9",
         ERR_PURCHASE_AGREEMENT_NOT_FOUND),
        ("approval request", api.get_approval_request, "ca",
         ERR_APPROVAL_REQUEST_NOT_FOUND),
        ("servicing transfer", api.get_servicing_transfer, "cb",
         ERR_SERVICING_TRANSFER_NOT_FOUND),
        ("error case", api.get_error_case, "cc", ERR_ERROR_CASE_NOT_FOUND),
        ("hedge position", api.get_hedge_position, "cd",
         ERR_HEDGE_POSITION_NOT_FOUND),
    ]

    reported = []
    for label, read, suffix, expected_error in reads:
        response = read(_unknown_id(suffix), U.ADMIN)
        assert response.status_code == 404, (
            f"reading an unknown {label} should answer 404, got "
            f"{response.status_code}"
        )
        error = validate_error(response, expected_error, 404)
        reported.append(error["error_id"])

    assert len(set(reported)) == len(reads), (
        f"expected one distinct not-found code per entity, got {reported}"
    )


def test_unknown_identifier_in_a_request_body_reports_that_entity_not_found(
        api: ApiClient, published_package: JsonDict) -> None:
    """
    An unresolvable identifier carried in the body, not the path, still reports
    the not-found code of the entity it should have named.

    PRD: "The same catalogue applies to identifiers carried in a request body rather than the path: an unresolvable `seller_id`, `bidder_id`, `loan_id`, `winning_bid_id`, `assumption_set_id`, `valuation_run_id` or `portfolio_id` produces the matching not-found error for the entity it should have named."

    Design: Corner/errors/every_entity_read_with_an_unknown_id_returns_its_own_not_found
    """
    env = published_package

    run_response = api.create_valuation_run(
        env["portfolio_id"],
        {
            "assumption_set_id": _unknown_id("c3"),
            "method": "DETERMINISTIC_STATIC",
            "expected_portfolio_version": env["portfolio_version"],
        },
        U.ANALYST,
    )
    validate_error(run_response, ERR_ASSUMPTION_SET_NOT_FOUND, 404)

    award_response = api.award_bid_package(
        env["package_id"],
        {
            "winning_bid_id": _unknown_id("c8"),
            "rep_warrant_days": 30,
            "indemnification_days": 45,
        },
        U.MANAGER,
    )
    validate_error(award_response, ERR_BID_NOT_FOUND, 404)


def test_unknown_path_identifier_outranks_an_unknown_body_identifier(
        api: ApiClient) -> None:
    """
    When the path names a portfolio that does not exist and the body names an
    assumption set that does not exist either, the path identifier is the one
    reported, because path resolution is checked before body resolution.

    PRD: "Checks are evaluated in a fixed order and the first violated check wins:"

    Design: Corner/errors/every_entity_read_with_an_unknown_id_returns_its_own_not_found
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    response = api.create_valuation_run(
        _unknown_id("cf"),
        {
            "assumption_set_id": _unknown_id("c3"),
            "method": "DETERMINISTIC_STATIC",
            "expected_portfolio_version": 1,
        },
        U.ANALYST,
    )
    validate_error(response, ERR_PORTFOLIO_NOT_FOUND, 404)


def test_bid_on_a_stratified_package_is_refused_before_any_price_check(
        api: ApiClient, stratified_package: JsonDict) -> None:
    """
    A package whose tape is cut but which has never been published accepts no
    bid, and the refusal names the package's state rather than its economics —
    there is no reserve price to test the offer against yet.

    PRD: "The package must be `PUBLISHED`; a `DRAFT`, `STRATIFIED`, `BIDDING_SUSPENDED`, `AWARDED` or `CANCELLED` package accepts nothing and refuses with `ERR_PACKAGE_NOT_ACCEPTING_BIDS` (HTTP 409)."

    Design: Corner/errors/bid_on_a_stratified_but_unpublished_package_is_rejected
    """
    env = stratified_package
    assert_status(env["package"], "STRATIFIED")
    assert env["package"]["reserve_price_cents"] is None, (
        "an unpublished package must not carry a reserve price: "
        f"{env['package']['reserve_price_cents']!r}"
    )

    response = api.create_bid(
        env["package_id"],
        {
            "bidder_id": env["buyer_id"],
            "price_bps": 118,
            "holdback_pct": 6,
            "expected_bid_package_version": env["package_version"],
        },
        env["buyer_headers"],
    )
    validate_error(response, ERR_PACKAGE_NOT_ACCEPTING_BIDS, 409)

    package = F.read_package(api, env["package_id"])
    assert_status(package, "STRATIFIED")
    assert package["bid_count"] == 0, (
        f"expected bid_count 0 after the refusal, got {package['bid_count']}"
    )
    assert package["version"] == env["package_version"], (
        f"expected version {env['package_version']} to be untouched by the "
        f"refusal, got {package['version']}"
    )
    assert package["reserve_price_cents"] is None
    assert package["published_at"] is None


def test_the_same_bid_clears_once_the_package_is_published(
        api: ApiClient, stratified_package: JsonDict) -> None:
    """
    Publishing the package stamps its reserve and opens it, and the identical
    offer that was just refused on state grounds is then accepted.

    PRD: "The package must be `PUBLISHED`; a `DRAFT`, `STRATIFIED`, `BIDDING_SUSPENDED`, `AWARDED` or `CANCELLED` package accepts nothing and refuses with `ERR_PACKAGE_NOT_ACCEPTING_BIDS` (HTTP 409)."

    Design: Corner/errors/bid_on_a_stratified_but_unpublished_package_is_rejected
    """
    env = stratified_package

    package = F.publish(api, env["package_id"])
    assert_status(package, "PUBLISHED")
    assert package["reserve_price_cents"] == 162997, (
        f"expected reserve 162997, got {package['reserve_price_cents']}"
    )

    response = api.create_bid(
        env["package_id"],
        {
            "bidder_id": env["buyer_id"],
            "price_bps": 118,
            "holdback_pct": 6,
            "expected_bid_package_version": package["version"],
        },
        env["buyer_headers"],
    )
    bid = validate_success(response, 201)
    assert_status(bid, "SUBMITTED")
    assert bid["bid_value_cents"] == 472002, (
        f"expected bid_value_cents 472002, got {bid['bid_value_cents']}"
    )
    assert F.read_package(api, env["package_id"])["bid_count"] == 1


def test_revising_a_bid_that_was_never_countered_is_refused(
        api: ApiClient, live_bid: JsonDict) -> None:
    """
    A revision is only legal as the answer to a counter, so a bid still sitting
    in `SUBMITTED` cannot re-price itself, and the refusal names the bid state.

    PRD: "Attempting an action from a state that does not allow it is `ERR_BID_INVALID_STATE` (HTTP 409): countering a bid that is neither `SUBMITTED` nor `REVISED`, revising a bid that is not `COUNTERED`, or nominating for award a bid that is neither `SUBMITTED` nor `REVISED` — including a bid that has `LAPSED`."

    Design: Corner/errors/revising_a_bid_that_was_never_countered_is_rejected
    """
    env = live_bid
    assert_status(env["bid"], "SUBMITTED")
    assert env["bid"]["round_number"] == 1

    response = api.revise_bid(
        env["bid_id"], {"price_bps": 124, "holdback_pct": 6},
        env["buyer_headers"])
    validate_error(response, ERR_BID_INVALID_STATE, 409)

    bid = F.read_bid(api, env["bid_id"])
    assert_status(bid, "SUBMITTED")
    assert bid["price_bps"] == 118, (
        f"expected price_bps 118 to be untouched, got {bid['price_bps']}"
    )
    assert bid["bid_value_cents"] == 472002, (
        f"expected bid_value_cents 472002 to be untouched, got "
        f"{bid['bid_value_cents']}"
    )
    assert bid["round_number"] == 1
    assert bid["version"] == env["bid"]["version"], (
        f"expected version {env['bid']['version']} to be untouched by the "
        f"refusal, got {bid['version']}"
    )


def test_countering_an_already_countered_bid_is_refused(
        api: ApiClient, live_bid: JsonDict) -> None:
    """
    A counter is only legal against a bid that is `SUBMITTED` or `REVISED`, so a
    second counter filed before the buyer answers is refused on the same grounds.

    PRD: "Attempting an action from a state that does not allow it is `ERR_BID_INVALID_STATE` (HTTP 409): countering a bid that is neither `SUBMITTED` nor `REVISED`, revising a bid that is not `COUNTERED`, or nominating for award a bid that is neither `SUBMITTED` nor `REVISED` — including a bid that has `LAPSED`."

    Design: Corner/errors/revising_a_bid_that_was_never_countered_is_rejected
    """
    env = live_bid

    countered = F.counter(api, env["bid_id"], 112)
    assert_status(countered, "COUNTERED")
    assert countered["round_number"] == 1

    response = api.counter_bid(
        env["bid_id"],
        {"counter_price_bps": 110, "counter_expires_at": "2026-08-12T00:00:00Z"},
        U.MANAGER,
    )
    validate_error(response, ERR_BID_INVALID_STATE, 409)

    bid = F.read_bid(api, env["bid_id"])
    assert_status(bid, "COUNTERED")
    assert bid["counter_price_bps"] == 112, (
        f"expected the first counter price 112 to stand, got "
        f"{bid['counter_price_bps']}"
    )
    assert bid["version"] == countered["version"], (
        f"expected version {countered['version']} to be untouched by the "
        f"refusal, got {bid['version']}"
    )


def test_a_countered_bid_can_be_revised_into_the_second_round(
        api: ApiClient, live_bid: JsonDict) -> None:
    """
    Countering first makes the same revision legal: it re-prices the offer,
    advances the negotiation round and clears the counter terms.

    PRD: "An accepted revision replaces `price_bps` and `holdback_pct` from the request, recomputes `bid_value_cents` on the same single-rounding basis, increments `round_number` by 1, clears `counter_price_bps` and `counter_expires_at` back to null, moves the bid `COUNTERED → REVISED`, and increments its `version` by 1."

    Design: Corner/errors/revising_a_bid_that_was_never_countered_is_rejected
    """
    env = live_bid
    F.counter(api, env["bid_id"], 112)

    revised = validate_success(
        api.revise_bid(env["bid_id"], {"price_bps": 124, "holdback_pct": 6},
                       env["buyer_headers"])
    )
    assert_status(revised, "REVISED")
    assert revised["round_number"] == 2, (
        f"expected round_number 2, got {revised['round_number']}"
    )
    assert revised["price_bps"] == 124
    assert revised["bid_value_cents"] == 496002, (
        f"expected bid_value_cents 496002, got {revised['bid_value_cents']}"
    )
    assert revised["counter_price_bps"] is None
    assert revised["counter_expires_at"] is None


def test_custodial_sweep_before_the_mapping_template_is_refused(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    The data work stream enforces its own order: the sweep cannot run until the
    servicing-system mapping template has been recorded, and no custodial money
    moves on the refusal.

    PRD: "Attempting the sweep before the mapping template is recorded is a dimension-ordering violation refused with `ERR_TRANSFER_INVALID_STATE`."

    Design: Corner/errors/transfer_dimension_steps_taken_out_of_order_are_rejected
    """
    env = settled_trade
    assert_dimensions(env["transfer"], notice="NOT_STARTED", data="NOT_STARTED",
                      pipeline="NOT_STARTED")
    assert_readiness(env["transfer"], "NOT_READY")

    response = api.map_escrow(env["transfer_id"], env["buyer_headers"])
    validate_error(response, ERR_TRANSFER_INVALID_STATE, 409)

    transfer = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(transfer, notice="NOT_STARTED", data="NOT_STARTED",
                      pipeline="NOT_STARTED")
    assert_readiness(transfer, "NOT_READY")
    assert transfer["escrow_transferred_cents"] == 0
    assert transfer["suspense_transferred_cents"] == 0
    assert transfer["version"] == env["transfer"]["version"], (
        f"expected version {env['transfer']['version']} to be untouched by the "
        f"refusal, got {transfer['version']}"
    )

    loan = F.read_loan(api, env["loan_ids"][0])
    assert loan["escrow_balance_cents"] == 100000, (
        f"nothing should have been swept, got escrow "
        f"{loan['escrow_balance_cents']}"
    )
    assert loan["suspense_balance_cents"] == 25000
    assert loan["escrow_balance_at_mapping_cents"] is None


def test_rolling_back_a_sweep_that_never_happened_is_refused(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    The compensating move for the custodial sweep is only available once the
    sweep has actually run, so a rollback filed on a freshly opened transfer is
    refused on state grounds.

    PRD: "The custodial total returns to exactly its pre-sweep value with no drift, and a rollback attempted while `data_status` is anything other than `ESCROW_MAPPED` is refused with `ERR_TRANSFER_INVALID_STATE`."

    Design: Corner/errors/transfer_dimension_steps_taken_out_of_order_are_rejected
    """
    env = settled_trade

    response = api.rollback_escrow_mapping(
        env["transfer_id"],
        {"reason": "custodial account number wrong on the transferee side"},
        env["buyer_headers"],
    )
    validate_error(response, ERR_TRANSFER_INVALID_STATE, 409)

    transfer = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(transfer, data="NOT_STARTED")
    assert transfer["escrow_transferred_cents"] == 0
    assert transfer["suspense_transferred_cents"] == 0
    assert transfer["version"] == env["transfer"]["version"]


def test_reconciling_before_the_sweep_reports_the_escrow_prerequisite(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    A reconcile filed before the custodial sweep is not turned away with a
    generic transfer-state error but with the specific escrow prerequisite.

    PRD: "Reconciliation requires that the sweep has happened — `data_status` must be `ESCROW_MAPPED` — and it is one of the three deliberate carve-outs of §2.12: a reconcile filed too early passes the transfer state check so that it can be refused with the specific `ERR_ESCROW_NOT_MAPPED` (HTTP 409) instead of a generic state error."

    Design: Corner/errors/transfer_dimension_steps_taken_out_of_order_are_rejected
    """
    env = settled_trade

    response = api.reconcile(env["transfer_id"], env["buyer_headers"])
    validate_error(response, ERR_ESCROW_NOT_MAPPED, 409)

    transfer = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(transfer, data="NOT_STARTED")
    assert transfer["reconciled_at"] is None
    assert transfer["version"] == env["transfer"]["version"]


def test_completing_a_transfer_short_of_readiness_is_refused(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    Completion refuses on compound readiness rather than on any single work
    stream, even once the effective date has arrived.

    PRD: "Completion requires `readiness` to be `READY` — any dimension short of its terminal value is refused with `ERR_TRANSFER_NOT_READY` (HTTP 409) — and requires the current logical clock date to have reached the agreement's `transfer_date`; a transfer cannot complete before its own effective date."

    Design: Corner/errors/transfer_dimension_steps_taken_out_of_order_are_rejected
    """
    env = settled_trade
    F.set_clock(api, C.CLOCK_TRANSFER_DAY)

    response = api.complete_transfer(env["transfer_id"], U.MANAGER)
    validate_error(response, ERR_TRANSFER_NOT_READY, 409)

    transfer = F.read_transfer(api, env["transfer_id"])
    assert_status(transfer, "IN_PROGRESS")
    assert transfer["completed_at"] is None
    assert transfer["transferred_loan_count"] == 0
    assert_dimensions(transfer, notice="NOT_STARTED", data="NOT_STARTED",
                      pipeline="NOT_STARTED")
    assert F.read_loan(api, env["loan_ids"][0])["status"] == "ACTIVE"


def test_notice_sent_by_the_wrong_side_of_the_trade_is_refused(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    Both servicers may post borrower notices, so this is a content rule rather
    than an access rule: the notice type dictates which side may issue it, and
    the acquiring servicer cannot send the seller's goodbye letter.

    PRD: "A role that does not match the notice type at all is refused with `ERR_NOTICE_SENDER_ROLE_MISMATCH` (HTTP 422); a caller in the right role but acting for the wrong institution is refused earlier, on ownership grounds, with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/errors/transferor_notice_sent_by_the_buyer_is_rejected
    """
    env = settled_trade
    loan_id = env["included_loan_ids"][0]

    for notice_type, headers in (
        ("TRANSFEROR_15DAY", env["buyer_headers"]),
        ("COMBINED", env["buyer_headers"]),
        ("TRANSFEREE_15DAY", env["seller_headers"]),
    ):
        response = api.create_notice(
            env["transfer_id"],
            {
                "notice_type": notice_type,
                "loan_id": loan_id,
                "effective_date": env["transfer_date"],
            },
            headers,
        )
        assert response.status_code == 422, (
            f"a {notice_type} notice from the wrong side should answer 422, got "
            f"{response.status_code}"
        )
        validate_error(response, ERR_NOTICE_SENDER_ROLE_MISMATCH, 422)

    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 0, (
        f"expected notice_count 0 after the refusals, got "
        f"{transfer['notice_count']}"
    )
    assert transfer["late_notice_count"] == 0
    assert_dimensions(transfer, notice="NOT_STARTED")
    assert transfer["version"] == env["transfer"]["version"]

    assert rows_of(api.list_transfer_notices(env["transfer_id"], U.MANAGER)) == []


def test_transferor_notice_sent_by_the_seller_is_accepted(
        api: ApiClient, settled_trade: JsonDict) -> None:
    """
    The identical body issued by the selling servicer is accepted and records
    which side of the trade sent it.

    PRD: "An accepted notice is created with `servicing_transfer_id`, `sent_at` set to the current logical clock, and `sent_by_role` recording which side issued it, either `SellerServicer` or `BuyerServicer`."

    Design: Corner/errors/transferor_notice_sent_by_the_buyer_is_rejected
    """
    env = settled_trade

    notice = validate_success(
        api.create_notice(
            env["transfer_id"],
            {
                "notice_type": "TRANSFEROR_15DAY",
                "loan_id": env["included_loan_ids"][0],
                "effective_date": env["transfer_date"],
            },
            env["seller_headers"],
        ),
        201,
    )
    assert notice["sent_by_role"] == "SellerServicer", (
        f"expected sent_by_role SellerServicer, got {notice['sent_by_role']}"
    )
    assert notice["servicing_transfer_id"] == env["transfer_id"]
    assert is_iso8601_timestamp(notice["sent_at"])

    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 1
    assert_dimensions(transfer, notice="NOTICES_IN_PROGRESS")


def test_publishing_a_package_whose_valuation_went_stale_is_refused(
        api: ApiClient, stratified_package: JsonDict) -> None:
    """
    The package itself is in the right state with a non-empty tape, so the only
    defect is the run it points at: a newer rate curve staled the bound
    valuation, and publication reads that run's status.

    PRD: "First, the bound valuation run must be `COMPLETED`; a `STALE` or `SUPERSEDED` run is not a publishable basis and the attempt is refused with `ERR_VALUATION_STALE` (HTTP 409)."

    Design: Corner/errors/publishing_a_package_whose_valuation_went_stale_is_rejected
    """
    env = stratified_package
    assert_status(env["package"], "STRATIFIED")
    assert env["package"]["tape_loan_count"] == 4

    F.create_rate_curve(api, C.CURVE_C2)

    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert_status(run, "STALE")
    assert is_iso8601_timestamp(run["staled_at"])
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS == 171576, (
        f"the staled run keeps its own figure, got {run['value_cents']}"
    )

    response = api.publish_bid_package(env["package_id"], U.MANAGER)
    validate_error(response, ERR_VALUATION_STALE, 409)

    package = F.read_package(api, env["package_id"])
    assert_status(package, "STRATIFIED")
    assert package["published_at"] is None
    assert package["reserve_price_cents"] is None
    assert package["version"] == env["package_version"], (
        f"expected version {env['package_version']} to be untouched by the "
        f"refusal, got {package['version']}"
    )


def test_a_package_rebuilt_on_a_fresh_run_publishes_against_the_new_curve(
        api: ApiClient, stratified_package: JsonDict) -> None:
    """
    Re-running the model against the new curve restores a publishable basis, and
    the reserve is stamped from that run at the package's floor percentage.

    PRD: "The reserve is the bound run's `value_cents`, multiplied by the package's `reserve_price_floor_pct` and divided by 100, multiplied by the package's `tape_upb_cents` and divided by the portfolio's `total_upb_cents` as frozen at tape lock, with a single half-up rounding to whole cents applied only at the very end and no intermediate rounding."

    Design: Corner/errors/publishing_a_package_whose_valuation_went_stale_is_rejected
    """
    env = stratified_package
    F.create_rate_curve(api, C.CURVE_C2)
    refresh_portfolio(api, env)

    fresh_run = F.run_valuation(
        api, env["portfolio_id"], env["assumption_set_id"],
        env["portfolio_version"])
    assert_status(fresh_run, "COMPLETED")
    assert fresh_run["value_cents"] == 175064, (
        f"expected the fresh run to value the pool at 175064, got "
        f"{fresh_run['value_cents']}"
    )

    package = F.create_bid_package(
        api, env["portfolio_id"], fresh_run["id"],
        marketing_start_at="2026-08-15T00:00:00Z",
        bid_deadline_at="2026-08-30T00:00:00Z")
    stratified = F.stratify(api, package["id"])
    assert stratified["tape_loan_count"] == 4

    published = F.publish(api, package["id"])
    assert_status(published, "PUBLISHED")
    assert published["reserve_price_cents"] == 166311, (
        f"expected reserve 166311, got {published['reserve_price_cents']}"
    )
    assert published["published_at"] is not None


def test_release_above_the_worst_complaint_tier_is_refused_outright(
        api: ApiClient, completed_transfer: JsonDict) -> None:
    """
    Three borrower error cases against four transferred loans put the complaint
    concentration at 75.00 percent, and the worst tier is expressed as a refusal
    rather than as a release of zero, so the retained holdback stays whole.

    PRD: "A ratio strictly above 50.00 releases nothing, and the call itself fails with `ERR_COMPLAINT_TIER_BLOCKS_RELEASE`."

    Design: Corner/errors/release_above_the_tier_three_complaint_ratio_is_rejected
    """
    env = completed_transfer
    for loan_id, category in zip(env["loan_ids"][:3],
                                 ("ESCROW", "PAYMENT_MISAPPLIED", "SUSPENSE")):
        F.open_error_case(api, env["transfer_id"], loan_id, category=category)

    F.set_clock(api, "2026-10-01T00:00:00Z")

    agreement = F.read_agreement(api, env["agreement_id"])
    assert agreement["holdback_cents"] == 28320, (
        f"expected a 28320 cent holdback, got {agreement['holdback_cents']}"
    )
    assert_holdback_split(agreement, retained=28320, released=0, applied=0)
    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["transferred_loan_count"] == 4
    assert round_half_up(3 * 100 / 4, 2) == 75.00

    response = api.create_holdback_release(
        env["agreement_id"],
        {"expected_purchase_agreement_version": agreement["version"]},
        U.COMPLIANCE_2)
    validate_error(response, ERR_COMPLAINT_TIER_BLOCKS_RELEASE, 409)

    after = F.read_agreement(api, env["agreement_id"])
    assert_holdback_split(after, retained=28320, released=0, applied=0)
    assert_status(after, "SETTLED")
    assert after["version"] == agreement["version"], (
        f"expected version {agreement['version']} to be untouched by the "
        f"refusal, got {after['version']}"
    )

    cases = rows_of(api.list_error_cases(
        U.COMPLIANCE, {"servicing_transfer_id": env["transfer_id"]}))
    assert len(cases) == 3, f"expected 3 error cases, got {len(cases)}"
    assert [case["status"] for case in cases] == ["OPEN"] * 3
