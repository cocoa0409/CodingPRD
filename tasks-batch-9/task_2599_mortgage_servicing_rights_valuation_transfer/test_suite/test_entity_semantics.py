"""
Entity semantics of the servicing-rights desk: the shapes the resources take.

This module pins the plain structural contract of the desk's resources rather
than any of its cascades. It covers what a registered counterparty and a newly
added loan look like when they come back from the server, which fields the
server mints for itself, which optional inputs fall back to a declared default,
how a portfolio's four aggregates follow from its loans, how a collection
reports its pagination window, which values the shape validator refuses, the
two entities that carry no version at all, and how the loan-level tape line
joins a bid package to a loan.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    NON_EXISTENT_UUID,
    assert_custodial_funds,
    assert_unversioned,
    build_desk,
    build_locked_portfolio,
    build_stratified_package,
    build_valued_portfolio,
    data_of,
    ids_of,
    is_valid_uuid,
    meta_of,
    rows_of,
    validate_error,
    validate_success,
    ERR_ASSUMPTION_SET_NOT_FOUND,
    ERR_BID_PACKAGE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PORTFOLIO_NOT_FOUND,
)


def _draft_portfolio(api: ApiClient, loans: list = None,
                     name: str = "Pool-T") -> JsonDict:
    """A staffed desk plus an unlocked pool, so loan writes are still open."""
    return build_locked_portfolio(api, loans=loans, name=name, lock=False)


# ---------------------------------------------------------------------------
# Registering a counterparty
# ---------------------------------------------------------------------------
def test_counterparty_registration_echoes_every_declared_input(api: ApiClient):
    """
    Registering a seller servicer answers 201 with all five declared inputs echoed.

    PRD: "A `PlatformAdmin` registers each one with its `legal_name` (a non-blank string of 1 to 120 characters), the side of the trade it is allowed to act on as `role_type` — either `SELLER` or `BUYER`, never both — its audited tangible net worth as `net_worth_cents` (zero or more), and its agency servicer rating as `servicer_rating`, one of `TIER_1`, `TIER_2` or `TIER_3`."

    Design: Corner/entities/counterparty_created_with_every_declared_field
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    created = validate_success(
        api.create_counterparty(C.SELLER_ALPHA, U.ADMIN), 201)

    assert created["legal_name"] == "Alpha Servicing LLC"
    assert created["role_type"] == "SELLER"
    assert created["net_worth_cents"] == 500000000
    assert created["servicer_rating"] == "TIER_1"
    assert created["agency_approvals"] == ["FNMA", "FHLMC"]


def test_counterparty_registration_opens_active_with_no_open_transfers(
        api: ApiClient):
    """
    A freshly registered counterparty is ACTIVE, unsuspended and carries no transfers.

    PRD: "Registration puts the counterparty in `ACTIVE` `status` with `suspended_at` null and `open_transfer_count` at 0."

    Design: Corner/entities/counterparty_created_with_every_declared_field
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    created = validate_success(
        api.create_counterparty(C.SELLER_ALPHA, U.ADMIN), 201)

    assert created["status"] == "ACTIVE"
    assert created["suspended_at"] is None
    assert created["open_transfer_count"] == 0


# ---------------------------------------------------------------------------
# Reading a loan back
# ---------------------------------------------------------------------------
def test_loan_read_echoes_the_stored_pool_attributes(api: ApiClient):
    """
    Reading a loan by id returns exactly the balances and terms it was added with.

    PRD: "Each loan carries a `loan_number` (non-blank, 1 to 32 characters, unique within its portfolio — a repeat is `ERR_DUPLICATE_LOAN_NUMBER`, HTTP 409), an unpaid principal balance `upb_cents` of at least 1, a `note_rate_pct` greater than 0 and at most 25 expressed in percent with at most 4 decimals, and a contractual `servicing_fee_bps` strip between 1 and 100 basis points of unpaid balance per annum."

    Design: Corner/entities/loan_retrieval_returns_the_stored_field_values
    """
    env = _draft_portfolio(api, loans=[C.LOANS_T[0]])
    loan_id = env["loan_ids"][0]

    loan = F.read_loan(api, loan_id, env["seller_headers"])

    assert loan["loan_number"] == "T-0001"
    assert loan["upb_cents"] == 10000050
    assert float(loan["note_rate_pct"]) == 6.5
    assert loan["servicing_fee_bps"] == 25
    assert loan["escrow_balance_cents"] == 100000
    assert loan["suspense_balance_cents"] == 25000
    assert loan["state_code"] == "CA"
    assert loan["portfolio_id"] == env["portfolio_id"]


def test_loan_read_reports_active_status_with_no_transfer_stamp(api: ApiClient):
    """
    A loan that has never been transferred reads ACTIVE with no transfer stamp.

    PRD: "The loan's own `status` starts at `ACTIVE`; it has exactly one other value, `TRANSFERRED`, reached only by the completion cascade, which also stamps `transferred_at`."

    Design: Corner/entities/loan_retrieval_returns_the_stored_field_values
    """
    env = _draft_portfolio(api, loans=[C.LOANS_T[0]])

    loan = F.read_loan(api, env["loan_ids"][0], env["seller_headers"])

    assert loan["status"] == "ACTIVE"
    assert loan["transferred_at"] is None


def test_loan_read_leaves_the_mapping_snapshots_null_before_any_sweep(
        api: ApiClient):
    """
    The two custodial mapping snapshots stay null until the escrow sweep writes them.

    PRD: "Two further loan fields stay null until the custodial sweep of §3.7 fills them: `escrow_balance_at_mapping_cents` and `suspense_balance_at_mapping_cents`."

    Design: Corner/entities/loan_retrieval_returns_the_stored_field_values
    """
    env = _draft_portfolio(api, loans=[C.LOANS_T[0]])

    loan = F.read_loan(api, env["loan_ids"][0], env["seller_headers"])

    assert loan["escrow_balance_at_mapping_cents"] is None
    assert loan["suspense_balance_at_mapping_cents"] is None


# ---------------------------------------------------------------------------
# The portfolio collection envelope
# ---------------------------------------------------------------------------
def test_portfolio_listing_reports_the_pagination_window_and_has_more(
        api: ApiClient):
    """
    A one-row window over two portfolios reports the total and flags more to come.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when `offset` plus the number of returned rows is less than `total_count`)."

    Design: Corner/entities/portfolio_listing_returns_the_declared_pagination_envelope
    """
    env = build_desk(api)
    first = F.create_portfolio(api, env["seller_id"], name="Pool-T")
    second = F.create_portfolio(api, env["seller_id"], name="Pool-M")

    page = api.list_portfolios(
        U.MANAGER,
        {"seller_id": env["seller_id"], "limit": 1, "offset": 0})
    rows, meta = rows_of(page), meta_of(page)

    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert rows[0]["id"] in (first["id"], second["id"])

    tail = api.list_portfolios(
        U.MANAGER,
        {"seller_id": env["seller_id"], "limit": 1, "offset": 1})
    tail_rows, tail_meta = rows_of(tail), meta_of(tail)

    assert len(tail_rows) == 1
    assert tail_rows[0]["id"] != rows[0]["id"]
    assert tail_meta["total_count"] == 2
    assert tail_meta["offset"] == 1
    assert tail_meta["has_more"] is False


def test_portfolio_listing_applies_the_declared_pagination_defaults(
        api: ApiClient):
    """
    Omitting both query parameters yields a limit of 10 at offset 0.

    PRD: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has a minimum of 0."

    Design: Corner/entities/portfolio_listing_returns_the_declared_pagination_envelope
    """
    env = build_desk(api)
    first = F.create_portfolio(api, env["seller_id"], name="Pool-T")
    second = F.create_portfolio(api, env["seller_id"], name="Pool-M")

    page = api.list_portfolios(U.MANAGER, {"seller_id": env["seller_id"]})
    rows, meta = rows_of(page), meta_of(page)

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert sorted(ids_of(rows)) == sorted([first["id"], second["id"]])


# ---------------------------------------------------------------------------
# Unknown identifiers
# ---------------------------------------------------------------------------
def test_reading_an_unknown_portfolio_returns_the_portfolio_not_found_code(
        api: ApiClient):
    """
    A well-formed but unknown portfolio id is refused as a portfolio not-found.

    PRD: "Each entity has its own not-found code — `ERR_COUNTERPARTY_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_ASSUMPTION_SET_NOT_FOUND`, `ERR_RATE_CURVE_NOT_FOUND`, `ERR_VALUATION_RUN_NOT_FOUND`, `ERR_BID_PACKAGE_NOT_FOUND`, `ERR_TAPE_LINE_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PURCHASE_AGREEMENT_NOT_FOUND`, `ERR_APPROVAL_REQUEST_NOT_FOUND`, `ERR_SERVICING_TRANSFER_NOT_FOUND`, `ERR_ERROR_CASE_NOT_FOUND` and `ERR_HEDGE_POSITION_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/get_absent_portfolio_returns_not_found
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    response = api.get_portfolio(NON_EXISTENT_UUID, U.MANAGER)

    validate_error(response, ERR_PORTFOLIO_NOT_FOUND)


def test_the_same_unknown_id_on_a_bid_package_returns_the_package_code(
        api: ApiClient):
    """
    The not-found code names the entity the path addressed, not a generic resource.

    PRD: "Each entity has its own not-found code — `ERR_COUNTERPARTY_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_ASSUMPTION_SET_NOT_FOUND`, `ERR_RATE_CURVE_NOT_FOUND`, `ERR_VALUATION_RUN_NOT_FOUND`, `ERR_BID_PACKAGE_NOT_FOUND`, `ERR_TAPE_LINE_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PURCHASE_AGREEMENT_NOT_FOUND`, `ERR_APPROVAL_REQUEST_NOT_FOUND`, `ERR_SERVICING_TRANSFER_NOT_FOUND`, `ERR_ERROR_CASE_NOT_FOUND` and `ERR_HEDGE_POSITION_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/get_absent_portfolio_returns_not_found
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    validate_error(api.get_bid_package(NON_EXISTENT_UUID, U.MANAGER),
                   ERR_BID_PACKAGE_NOT_FOUND)
    validate_error(api.get_portfolio(NON_EXISTENT_UUID, U.MANAGER),
                   ERR_PORTFOLIO_NOT_FOUND)


# ---------------------------------------------------------------------------
# Required loan inputs
# ---------------------------------------------------------------------------
def test_adding_a_loan_without_an_unpaid_balance_is_a_shape_violation(
        api: ApiClient):
    """
    The unpaid principal balance has no default, so omitting it is refused outright.

    PRD: "Request shape: body parses, required fields present, every value satisfying its declared type, enum, range and decimal-place constraints, and no attempt to write a system-maintained or computed field — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_loan_missing_required_upb_returns_invalid_request
    """
    env = _draft_portfolio(api, loans=[])
    body = dict(C.LOANS_T[0])
    del body["upb_cents"]

    response = api.create_loan(env["portfolio_id"], body,
                               env["seller_headers"])

    validate_error(response, ERR_INVALID_REQUEST)


def test_every_other_required_loan_field_is_refused_the_same_way(
        api: ApiClient):
    """
    Loan number, note rate, servicing fee strip and property state are all mandatory.

    PRD: "Request shape: body parses, required fields present, every value satisfying its declared type, enum, range and decimal-place constraints, and no attempt to write a system-maintained or computed field — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_loan_missing_required_upb_returns_invalid_request
    """
    env = _draft_portfolio(api, loans=[])

    for field in ("loan_number", "note_rate_pct", "servicing_fee_bps",
                  "state_code"):
        body = dict(C.LOANS_T[0])
        del body[field]
        response = api.create_loan(env["portfolio_id"], body,
                                   env["seller_headers"])
        validate_error(response, ERR_INVALID_REQUEST)


def test_a_refused_loan_add_leaves_the_portfolio_aggregates_untouched(
        api: ApiClient):
    """
    The pool is unchanged after a loan add that failed its shape validation.

    PRD: "Rejected requests never mutate anything."

    Design: Corner/entities/create_loan_missing_required_upb_returns_invalid_request
    """
    env = _draft_portfolio(api, loans=[])
    body = dict(C.LOANS_T[0])
    del body["upb_cents"]

    validate_error(
        api.create_loan(env["portfolio_id"], body, env["seller_headers"]),
        ERR_INVALID_REQUEST)

    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["loan_count"] == 0
    assert portfolio["total_upb_cents"] == 0
    assert F.list_loans(api, env["portfolio_id"]) == []


# ---------------------------------------------------------------------------
# Declared defaults for omitted optional inputs
# ---------------------------------------------------------------------------
_MINIMAL_LOAN = {
    "loan_number": "D-0001",
    "upb_cents": 10000050,
    "note_rate_pct": 6.5,
    "servicing_fee_bps": 25,
    "state_code": "CA",
}


def test_counterparty_without_agency_approvals_defaults_to_an_empty_list(
        api: ApiClient):
    """
    A counterparty registered with no agency approvals holds an empty list, not null.

    PRD: "The optional `agency_approvals` field lists the agency seller/servicer approvals the institution currently holds, drawn without repetition from `FNMA`, `FHLMC` and `GNMA`; it defaults to an empty list."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    created = validate_success(
        api.create_counterparty(
            {
                "legal_name": "Delta Servicing LLC",
                "role_type": "SELLER",
                "net_worth_cents": 500000000,
                "servicer_rating": "TIER_2",
            },
            U.ADMIN),
        201)

    assert created["agency_approvals"] == []
    assert created["agency_approvals"] is not None


def test_loan_without_custodial_balances_defaults_both_to_zero(api: ApiClient):
    """
    A loan added without escrow or suspense balances carries zero of each.

    PRD: "Custodial balances are optional and default to 0: `escrow_balance_cents` holds the borrower's tax-and-insurance escrow and `suspense_balance_cents` holds unapplied funds, both zero or more."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    env = _draft_portfolio(api, loans=[], name="Pool-D")

    loan = validate_success(
        api.create_loan(env["portfolio_id"], dict(_MINIMAL_LOAN),
                        env["seller_headers"]),
        201)

    assert loan["escrow_balance_cents"] == 0
    assert loan["suspense_balance_cents"] == 0
    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]), 0)


def test_loan_without_stratum_attributes_defaults_to_current_and_none(
        api: ApiClient):
    """
    The two stratum-bearing loan attributes fall back to CURRENT and NONE.

    PRD: "Two stratum-bearing attributes are also optional: `delinquency_bucket` defaults to `CURRENT` and may instead be `DQ_30_59`, `DQ_60_89`, `DQ_90_PLUS` or `FORECLOSURE`, and `loss_mit_status` defaults to `NONE` and may instead be `TRIAL_MOD`, `PERMANENT_MOD` or `FORBEARANCE`."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    env = _draft_portfolio(api, loans=[], name="Pool-D")

    loan = validate_success(
        api.create_loan(env["portfolio_id"], dict(_MINIMAL_LOAN),
                        env["seller_headers"]),
        201)

    assert loan["delinquency_bucket"] == "CURRENT"
    assert loan["loss_mit_status"] == "NONE"


# ---------------------------------------------------------------------------
# Portfolio aggregates derived from the loan rows
# ---------------------------------------------------------------------------
def test_each_loan_add_recomputes_the_aggregates_and_bumps_the_portfolio(
        api: ApiClient):
    """
    Every loan add re-derives the pool aggregates and moves the portfolio version on.

    PRD: "Adding a loan recomputes four portfolio aggregates and increments the portfolio's `version` by 1."

    Design: Corner/entities/portfolio_aggregates_are_computed_from_its_loans
    """
    env = build_desk(api)
    portfolio = F.create_portfolio(api, env["seller_id"], name="Pool-V")
    assert portfolio["version"] == 1
    assert portfolio["loan_count"] == 0

    for index, payload in enumerate(C.LOANS_V, start=1):
        F.add_loan(api, portfolio["id"], env["seller_id"], payload)
        current = F.read_portfolio(api, portfolio["id"])
        assert current["loan_count"] == index
        assert current["version"] == index + 1


def test_portfolio_note_rate_average_is_weighted_by_unpaid_balance(
        api: ApiClient):
    """
    The mixed pool averages 6.5833 by unpaid balance, not the unweighted 6.5000.

    PRD: "`loan_count` is the number of loans in the portfolio whose status is `ACTIVE`; `total_upb_cents` is the sum of their `upb_cents`; `custodial_funds_total_cents` follows the definition in §2.11; and `weighted_avg_note_rate_pct` is the unpaid-balance-weighted note rate — for the `ACTIVE` loans, the sum of each loan's `upb_cents` multiplied by its `note_rate_pct`, divided by the sum of their `upb_cents`, rounded half up to 4 decimals, and reported as 0.0000 whenever `loan_count` is 0."

    Design: Corner/entities/portfolio_aggregates_are_computed_from_its_loans
    """
    env = build_desk(api)
    portfolio = F.create_portfolio(api, env["seller_id"], name="Pool-V")

    F.add_loan(api, portfolio["id"], env["seller_id"], C.LOANS_V[0])
    after_one = F.read_portfolio(api, portfolio["id"])
    assert after_one["loan_count"] == 1
    assert after_one["total_upb_cents"] == 20000000
    assert float(after_one["weighted_avg_note_rate_pct"]) == 6.5

    for payload in C.LOANS_V[1:]:
        F.add_loan(api, portfolio["id"], env["seller_id"], payload)

    after_all = F.read_portfolio(api, portfolio["id"])
    assert after_all["loan_count"] == 3
    assert after_all["total_upb_cents"] == C.POOL_V_TOTAL_UPB_CENTS
    assert float(after_all["weighted_avg_note_rate_pct"]) == 6.5833


def test_portfolio_custodial_total_sums_escrow_and_suspense_over_its_loans(
        api: ApiClient):
    """
    The custodial total is escrow plus suspense across the whole pool.

    PRD: "A portfolio's `custodial_funds_total_cents` is defined as the sum of `escrow_balance_cents` plus `suspense_balance_cents` over the loans in that portfolio, plus the sum of `escrow_transferred_cents` plus `suspense_transferred_cents` over the servicing transfers reachable from that portfolio through its bid packages and their purchase agreements."

    Design: Corner/entities/portfolio_aggregates_are_computed_from_its_loans
    """
    env = build_locked_portfolio(api, loans=C.LOANS_V, name="Pool-V",
                                lock=False)

    portfolio = F.read_portfolio(api, env["portfolio_id"])

    assert_custodial_funds(portfolio, 700000)


def test_portfolio_valuation_freshness_stays_none_until_a_run_exists(
        api: ApiClient):
    """
    A pool that has never been valued reports no valuation freshness at all.

    PRD: "The portfolio's `valuation_freshness` follows directly: `NONE` when there is no eligible run at all, `CURRENT` when the chosen run is `COMPLETED`, and `STALE` when the chosen run is `STALE`."

    Design: Corner/entities/portfolio_aggregates_are_computed_from_its_loans
    """
    env = build_locked_portfolio(api, loans=C.LOANS_V, name="Pool-V",
                                lock=False)

    portfolio = F.read_portfolio(api, env["portfolio_id"])

    assert portfolio["valuation_freshness"] == "NONE"


# ---------------------------------------------------------------------------
# Server-minted identity, stamps and version on a bid package
# ---------------------------------------------------------------------------
def test_bid_package_id_is_a_server_minted_uuid_without_a_type_prefix(
        api: ApiClient):
    """
    The package identifier is a bare UUID the server generated for itself.

    PRD: "Every resource carries a server-minted `id`: a UUID string with no type prefix, generated by the server and never accepted from the client."

    Design: Corner/entities/system_fields_are_minted_by_the_server_and_client_input_ignored
    """
    env = build_valued_portfolio(api)

    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])

    assert is_valid_uuid(package["id"])
    assert "_" not in package["id"]


def test_bid_package_created_at_is_stamped_from_the_logical_clock(
        api: ApiClient):
    """
    A package created at the default desk instant carries that instant as created_at.

    PRD: "Every resource carries `created_at`, an ISO 8601 UTC timestamp with exactly three fractional-second digits."

    Design: Corner/entities/system_fields_are_minted_by_the_server_and_client_input_ignored
    """
    env = build_valued_portfolio(api)

    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])

    assert package["created_at"] == "2026-08-01T00:00:00.000Z"


def test_bid_package_version_starts_at_one_and_advances_by_one_per_mutation(
        api: ApiClient):
    """
    Cutting the tape moves the package version from 1 to 2 and refreshes updated_at.

    PRD: "Most resources additionally carry `updated_at` (same format, refreshed on every mutation) and `version`, an integer that starts at 1 when the row is created and increments by exactly 1 on each accepted mutation of that row."

    Design: Corner/entities/system_fields_are_minted_by_the_server_and_client_input_ignored
    """
    env = build_valued_portfolio(api)
    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])
    assert package["version"] == 1
    assert package["updated_at"] == package["created_at"]

    F.set_clock(api, C.CLOCK_AUG_10)
    stratified = F.stratify(api, package["id"])

    assert stratified["version"] == 2
    assert stratified["created_at"] == package["created_at"]
    assert stratified["updated_at"] == "2026-08-10T00:00:00.000Z"


def test_bid_package_status_and_publication_stamp_are_not_client_inputs(
        api: ApiClient):
    """
    A new package opens in DRAFT with an unstamped reserve and no publication time.

    PRD: "A new package sits in `DRAFT` with `tape_upb_cents`, `tape_loan_count`, `stratum_count` and `bid_count` at 0, and with `reserve_price_cents`, `published_at` and `suspended_reason` all null."

    Design: Corner/entities/system_fields_are_minted_by_the_server_and_client_input_ignored
    """
    env = build_valued_portfolio(api)

    package = F.create_bid_package(api, env["portfolio_id"],
                                   env["valuation_run_id"])

    assert package["status"] == "DRAFT"
    assert package["published_at"] is None
    assert package["reserve_price_cents"] is None
    assert package["suspended_reason"] is None
    assert package["tape_upb_cents"] == 0
    assert package["tape_loan_count"] == 0
    assert package["stratum_count"] == 0
    assert package["bid_count"] == 0


# ---------------------------------------------------------------------------
# Ranges, closed enumerations and cross-field ordering
# ---------------------------------------------------------------------------
def test_loan_note_rate_above_the_declared_maximum_is_refused(api: ApiClient):
    """
    A note rate of 26.5 percent sits outside the declared range and is refused.

    PRD: "Each loan carries a `loan_number` (non-blank, 1 to 32 characters, unique within its portfolio — a repeat is `ERR_DUPLICATE_LOAN_NUMBER`, HTTP 409), an unpaid principal balance `upb_cents` of at least 1, a `note_rate_pct` greater than 0 and at most 25 expressed in percent with at most 4 decimals, and a contractual `servicing_fee_bps` strip between 1 and 100 basis points of unpaid balance per annum."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected
    """
    env = _draft_portfolio(api, loans=[])
    body = dict(C.LOANS_T[0], loan_number="T-9999", note_rate_pct=26.5)

    validate_error(
        api.create_loan(env["portfolio_id"], body, env["seller_headers"]),
        ERR_INVALID_REQUEST)

    assert F.read_portfolio(api, env["portfolio_id"])["loan_count"] == 0


def test_loan_delinquency_bucket_outside_the_closed_enum_is_refused(
        api: ApiClient):
    """
    A delinquency bucket the desk does not define is not accepted on a loan.

    PRD: "Two stratum-bearing attributes are also optional: `delinquency_bucket` defaults to `CURRENT` and may instead be `DQ_30_59`, `DQ_60_89`, `DQ_90_PLUS` or `FORECLOSURE`, and `loss_mit_status` defaults to `NONE` and may instead be `TRIAL_MOD`, `PERMANENT_MOD` or `FORBEARANCE`."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected
    """
    env = _draft_portfolio(api, loans=[])
    body = dict(C.LOANS_T[0], loan_number="T-9998",
                delinquency_bucket="DQ_120_PLUS")

    validate_error(
        api.create_loan(env["portfolio_id"], body, env["seller_headers"]),
        ERR_INVALID_REQUEST)

    assert F.read_portfolio(api, env["portfolio_id"])["loan_count"] == 0


def test_rate_curve_base_rate_outside_the_declared_band_is_refused(
        api: ApiClient):
    """
    A benchmark rate of 9000 basis points is out of band while 4000 publishes.

    PRD: "Publishing a `RateCurveSnapshot` supplies the market date `as_of_date` as a calendar date in `YYYY-MM-DD` form, the benchmark par mortgage rate `base_rate_bps` (at least 100 and at most 8000 basis points), and `primary_secondary_spread_bps` (0 to 200, recorded as 25 when not supplied), which exists purely for disclosure and enters no formula anywhere in this system."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected
    """
    build_desk(api)

    validate_error(
        api.create_rate_curve(
            {"as_of_date": "2026-08-20", "base_rate_bps": 9000,
             "primary_secondary_spread_bps": 85},
            U.HEDGE),
        ERR_INVALID_REQUEST)

    accepted = validate_success(
        api.create_rate_curve(
            {"as_of_date": "2026-08-20", "base_rate_bps": 4000,
             "primary_secondary_spread_bps": 85},
            U.HEDGE),
        201)
    assert accepted["base_rate_bps"] == 4000
    assert accepted["status"] == "ACTIVE"


def test_bid_package_deadline_equal_to_the_window_start_is_refused(
        api: ApiClient):
    """
    A marketing window that closes at the instant it opens is not a valid window.

    PRD: "The window's start is inclusive and its end is exclusive: bids are refused at or after the deadline instant, and `bid_deadline_at` must be strictly greater than `marketing_start_at`."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected
    """
    env = build_valued_portfolio(api)

    response = api.create_bid_package(
        {
            "portfolio_id": env["portfolio_id"],
            "valuation_run_id": env["valuation_run_id"],
            "stratification_scheme": "BY_STATE",
            "reserve_price_floor_pct": 95,
            "marketing_start_at": C.MARKETING_START_AT,
            "bid_deadline_at": C.MARKETING_START_AT,
        },
        U.MANAGER)

    validate_error(response, ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# The immutable assumption vector
# ---------------------------------------------------------------------------
def test_assumption_set_carries_no_version_and_no_update_stamp(api: ApiClient):
    """
    The assumption vector is written once and exposes no bookkeeping fields.

    PRD: "Two entities are exceptions and are deliberately immutable once written: an `AssumptionSet` and a `BorrowerNotice` carry only `id` and `created_at` — for those two entities both `updated_at` and `version` are absent from the representation entirely."

    Design: Corner/entities/assumption_set_is_immutable_and_carries_no_version
    """
    F.set_clock(api, C.CLOCK_DEFAULT)

    created = validate_success(
        api.create_assumption_set(C.ASSUMPTION_DESK_BASE, U.ANALYST), 201)

    assert_unversioned(created)
    assert_unversioned(
        data_of(api.get_assumption_set(created["id"], U.ANALYST)))


def test_assumption_set_read_returns_the_vector_it_was_written_with(
        api: ApiClient):
    """
    Reading the assumption set back returns the same model inputs, unedited.

    PRD: "An `AssumptionSet` carries `assumption_name` (non-blank, 1 to 80 characters, for example "Desk Base Case Aug-2026"), the annual constant prepayment rate `cpr_pct` in percent (greater than 0 and strictly less than 100, at most 4 decimals), the nominal annual `discount_rate_pct` in percent (greater than 0 and at most 40, at most 4 decimals), the base direct annual cost of servicing one performing loan as `cost_to_service_annual_cents` (zero or more), the annual `float_earnings_rate_pct` credited on escrow float (zero or more and at most 40, at most 4 decimals), and `projection_years`, the number of whole projection years in the cash-flow model, at least 1 and at most 10, which the server records as 3 when the caller does not supply it."

    Design: Corner/entities/assumption_set_is_immutable_and_carries_no_version
    """
    F.set_clock(api, C.CLOCK_DEFAULT)
    created = F.create_assumption_set(api, C.ASSUMPTION_DESK_BASE)

    read_back = data_of(api.get_assumption_set(created["id"], U.ANALYST))

    assert read_back["assumption_name"] == "desk-base"
    assert float(read_back["cpr_pct"]) == 8.0
    assert float(read_back["discount_rate_pct"]) == 10.0
    assert read_back["cost_to_service_annual_cents"] == 9000
    assert float(read_back["float_earnings_rate_pct"]) == 4.0
    assert read_back["projection_years"] == 3


# ---------------------------------------------------------------------------
# Children reached through an absent parent
# ---------------------------------------------------------------------------
def test_adding_a_loan_under_an_unknown_portfolio_is_a_portfolio_not_found(
        api: ApiClient):
    """
    A loan add addressed at a portfolio that does not exist is a 404 on the pool.

    PRD: "Every id in the URL path resolves to a live row — the matching not-found error."

    Design: Corner/entities/loan_creation_under_an_absent_portfolio_returns_not_found
    """
    env = _draft_portfolio(api, loans=[])

    response = api.create_loan(NON_EXISTENT_UUID, dict(C.LOANS_T[0]),
                               env["seller_headers"])

    validate_error(response, ERR_PORTFOLIO_NOT_FOUND)
    assert F.list_loans(api, env["portfolio_id"]) == []


def test_valuation_run_naming_an_absent_assumption_set_is_a_body_not_found(
        api: ApiClient):
    """
    An unresolvable assumption set in the body answers with that entity's own 404.

    PRD: "The same catalogue applies to identifiers carried in a request body rather than the path: an unresolvable `seller_id`, `bidder_id`, `loan_id`, `winning_bid_id`, `assumption_set_id`, `valuation_run_id` or `portfolio_id` produces the matching not-found error for the entity it should have named."

    Design: Corner/entities/loan_creation_under_an_absent_portfolio_returns_not_found
    """
    env = build_locked_portfolio(api)

    response = api.create_valuation_run(
        env["portfolio_id"],
        {
            "assumption_set_id": NON_EXISTENT_UUID,
            "method": "DETERMINISTIC_STATIC",
            "expected_portfolio_version": env["portfolio_version"],
        },
        U.ANALYST)

    validate_error(response, ERR_ASSUMPTION_SET_NOT_FOUND)


# ---------------------------------------------------------------------------
# The tape line as the junction between a package and a loan
# ---------------------------------------------------------------------------
def _two_stratified_packages(api: ApiClient) -> JsonDict:
    """Pool T cut twice: once by state and once by delinquency bucket."""
    env = build_stratified_package(api, scheme="BY_STATE")
    env["package_by_state"] = env["package"]
    second = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"],
        scheme="BY_DELINQUENCY", marketing_start_at="2026-08-15T00:00:00Z",
        bid_deadline_at="2026-08-29T00:00:00Z")
    env["package_by_delinquency"] = F.stratify(api, second["id"])
    return env


def test_one_loan_carries_a_tape_line_on_each_package_it_appears_on(
        api: ApiClient):
    """
    The same borrower shows up once per package when the pool is cut twice.

    PRD: "Stratification creates one `TapeLine` per loan of the portfolio whose status is `ACTIVE`, each line recording its `bid_package_id`, its `loan_id`, `included` set to true, `exclusion_reason` null, and `upb_snapshot_cents` copied from the loan's `upb_cents` at that moment."

    Design: Corner/entities/tape_line_junction_links_a_bid_package_to_a_loan
    """
    env = _two_stratified_packages(api)
    loan_id = env["loan_ids"][0]

    lines = rows_of(api.list_loan_tape_lines(loan_id, U.ANALYST))

    assert len(lines) == 2
    assert {line["bid_package_id"] for line in lines} == {
        env["package_by_state"]["id"],
        env["package_by_delinquency"]["id"],
    }
    assert {line["loan_id"] for line in lines} == {loan_id}


def test_package_tape_lines_snapshot_every_active_loan_of_the_pool(
        api: ApiClient):
    """
    Cutting the tape gives the package one included line per loan, balance frozen.

    PRD: "Stratification creates one `TapeLine` per loan of the portfolio whose status is `ACTIVE`, each line recording its `bid_package_id`, its `loan_id`, `included` set to true, `exclusion_reason` null, and `upb_snapshot_cents` copied from the loan's `upb_cents` at that moment."

    Design: Corner/entities/tape_line_junction_links_a_bid_package_to_a_loan
    """
    env = _two_stratified_packages(api)
    package_id = env["package_by_state"]["id"]

    lines = rows_of(api.list_package_tape_lines(package_id, U.ANALYST))

    assert len(lines) == 4
    assert sorted(line["loan_id"] for line in lines) == sorted(env["loan_ids"])
    for line in lines:
        assert line["bid_package_id"] == package_id
        assert line["included"] is True
        assert line["exclusion_reason"] is None
        assert line["upb_snapshot_cents"] == 10000050


def test_stratum_count_follows_the_distinct_labels_of_the_chosen_scheme(
        api: ApiClient):
    """
    Four states give four strata while four current loans give one.

    PRD: "The package's `tape_loan_count` is then the number of included lines, `tape_upb_cents` the sum of `upb_snapshot_cents` over included lines, and `stratum_count` the number of distinct `stratum_label` values among included lines; the package moves `DRAFT → STRATIFIED` and its `version` increments by 1."

    Design: Corner/entities/tape_line_junction_links_a_bid_package_to_a_loan
    """
    env = _two_stratified_packages(api)

    by_state = env["package_by_state"]
    by_delinquency = env["package_by_delinquency"]

    assert by_state["stratum_count"] == 4
    assert by_delinquency["stratum_count"] == 1
    for package in (by_state, by_delinquency):
        assert package["status"] == "STRATIFIED"
        assert package["tape_loan_count"] == 4
        assert package["tape_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS


def test_tape_line_labels_come_from_the_packages_stratification_scheme(
        api: ApiClient):
    """
    A by-state cut labels lines with the property state, a by-delinquency cut with
    the bucket.

    PRD: "Each line's `stratum_label` is assigned from the package's scheme — under `BY_STATE` it is the loan's `state_code`; under `BY_DELINQUENCY` it is the loan's `delinquency_bucket`; and under `BY_NOTE_RATE` it is a rate band, namely `LT_600` when the loan's `note_rate_pct` is below 6.00, `600_699` when the note rate is at least 6.00 and below 7.00, and `700_PLUS` when the note rate is 7.00 or above, with the band comparison made against the stored 4-decimal note rate and no rounding first."

    Design: Corner/entities/tape_line_junction_links_a_bid_package_to_a_loan
    """
    env = _two_stratified_packages(api)

    state_lines = rows_of(api.list_package_tape_lines(
        env["package_by_state"]["id"], U.ANALYST))
    bucket_lines = rows_of(api.list_package_tape_lines(
        env["package_by_delinquency"]["id"], U.ANALYST))

    assert {line["stratum_label"] for line in state_lines} == {
        "CA", "TX", "FL", "NY"}
    assert {line["stratum_label"] for line in bucket_lines} == {"CURRENT"}
