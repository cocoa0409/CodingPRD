"""Registry writes and read paths: instruments, strategies, model versions,
accounts and the tax-lot ledger, checked against the SMA Model Delivery PRD."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_account_payload,
    create_model_payload,
    create_model_version_payload,
    create_security_payload,
    deposit,
    get_account,
    is_iso8601_timestamp,
    is_valid_uuid,
    open_account,
    reprice_security,
    setup_platform,
    transfer_in,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["portfolio_manager_headers"]


def _register_alfa(api):
    """Register the ALFA instrument at 10000 cents and return its body."""
    resp = api.create_security(
        create_security_payload(
            ticker="ALFA",
            name="Alfa Industrials",
            asset_class="US_EQUITY",
            last_price_cents=10_000,
        ),
        ADMIN,
    )
    return validate_success(resp, 201)


def _account_with_alfa(securities=None, sleeves=None):
    """Instruments + sponsor + model + PUBLISHED version + one open account."""
    env = setup_platform(
        securities=securities or [("ALFA", "Alfa Industrials", 10_000)],
        sleeves=sleeves or [("ALFA", 10000)],
    )
    env["account"] = open_account(env, "ACC-001")
    return env


# ---------------------------------------------------------------------------
# Registering an instrument
# ---------------------------------------------------------------------------
def test_security_creation_echoes_every_registered_field(api):
    """PRD §3.1: "A `PlatformAdmin` registers each tradable instrument with an uppercase exchange `ticker` of one to eight characters drawn from the letters A through Z, which must be unique across every registered instrument, a human-readable `name` for the issuer or instrument, an `asset_class` chosen from `US_EQUITY`, `GLOBAL_EQUITY`, `FIXED_INCOME` and `CASH_EQUIV`, and a `last_price_cents` mark of at least 1."

    Design: Corner/entities/security_creation_returns_full_body_with_system_fields
    """
    resp = api.create_security(
        create_security_payload(
            ticker="ALFA",
            name="Alfa Industrials",
            asset_class="US_EQUITY",
            last_price_cents=10_000,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)

    assert data["ticker"] == "ALFA", f"ticker must be echoed, got {data['ticker']!r}"
    assert data["name"] == "Alfa Industrials", (
        f"name must be echoed, got {data['name']!r}"
    )
    assert data["asset_class"] == "US_EQUITY", (
        f"asset_class must be echoed, got {data['asset_class']!r}"
    )
    assert data["last_price_cents"] == 10_000, (
        f"last_price_cents must be echoed as an integer 10000, "
        f"got {data['last_price_cents']!r}"
    )
    assert resp.json()["response_type"] == "object", (
        "a single created resource is returned as response_type 'object'"
    )


def test_security_restricted_globally_defaults_to_false(api):
    """PRD §3.1: "An optional `restricted_globally` flag, false unless supplied, is the platform's blanket veto: while it is true, no purchase of that instrument may enter any account whatsoever."

    Design: Corner/entities/security_creation_returns_full_body_with_system_fields
    """
    payload = create_security_payload(ticker="ALFA", last_price_cents=10_000)
    payload.pop("restricted_globally", None)

    data = validate_success(api.create_security(payload, ADMIN), 201)

    assert data["restricted_globally"] is False, (
        "restricted_globally is false unless supplied, got "
        f"{data['restricted_globally']!r}"
    )


def test_security_creation_stamps_server_minted_id_and_version_one(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, whether the mutation was requested directly or arrived as a downstream consequence of some other operation."

    Design: Corner/entities/security_creation_returns_full_body_with_system_fields
    """
    data = _register_alfa(api)

    assert data["version"] == 1, (
        f"a freshly created row carries version 1, got {data['version']!r}"
    )
    assert is_valid_uuid(data["id"]), (
        f"id must be a server-minted UUID with no type prefix, got {data['id']!r}"
    )
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data['created_at']!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data['updated_at']!r}"
    )


# ---------------------------------------------------------------------------
# Reading a row that does not exist
# ---------------------------------------------------------------------------
def test_account_read_with_unknown_id_returns_account_not_found(api):
    """PRD §2.6: "The failure code names the missing type: `ERR_SECURITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_MODEL_VERSION_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_TRADE_ORDER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_TAX_LOT_NOT_FOUND`, `ERR_HARVEST_PROPOSAL_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/account_get_with_unknown_id_returns_account_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)

    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_account_not_found_uses_the_standard_error_envelope(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/account_get_with_unknown_id_returns_account_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)

    body = resp.json()
    assert body["response_type"] == "error", (
        f"error responses carry response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the meta object of an error response carries only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert "error_id" in body["data"] and "message" in body["data"], (
        f"error data must carry error_id and message, got {sorted(body['data'].keys())}"
    )


# ---------------------------------------------------------------------------
# Request-shape failures
# ---------------------------------------------------------------------------
def test_model_creation_without_base_fee_bps_is_rejected(api):
    """PRD §2.6: "Every required input field is present; every value matches its declared type, its enum membership and its numeric range; `max_position_bps` is present when `restriction_type` is `MAX_POSITION` and absent for the other two restriction types; `period_end` is strictly later than `period_start`; and `effective_until`, when it is not null, is strictly later than `effective_from`. Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/model_create_missing_required_field_returns_invalid_request
    """
    payload = create_model_payload(strategy_code="CORE")
    payload.pop("base_fee_bps")

    validate_error(
        api.create_model(payload, MANAGER), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    # The rejected request wrote nothing, so CORE is still a free strategy_code.
    retry = api.create_model(create_model_payload(strategy_code="CORE"), MANAGER)
    validate_success(retry, 201)


def test_security_with_unknown_asset_class_is_rejected(api):
    """PRD §2.6: "Every required input field is present; every value matches its declared type, its enum membership and its numeric range; `max_position_bps` is present when `restriction_type` is `MAX_POSITION` and absent for the other two restriction types; `period_end` is strictly later than `period_start`; and `effective_until`, when it is not null, is strictly later than `effective_from`. Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/security_invalid_asset_class_enum_rejected
    """
    bad = create_security_payload(
        ticker="ALFA",
        name="Alfa Industrials",
        asset_class="CRYPTO",
        last_price_cents=10_000,
    )

    validate_error(
        api.create_security(bad, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    # Nothing was written, so the ALFA ticker is still free.
    retry = api.create_security(
        create_security_payload(
            ticker="ALFA",
            name="Alfa Industrials",
            asset_class="US_EQUITY",
            last_price_cents=10_000,
        ),
        ADMIN,
    )
    validate_success(retry, 201)


# ---------------------------------------------------------------------------
# Body reference resolution
# ---------------------------------------------------------------------------
def test_model_version_against_unknown_model_returns_model_not_found(api):
    """PRD §2.6: "Every reference identifier carried in the request body resolves to an existing row, validated in the order the fields are listed in that endpoint's input. The failure code is one of `ERR_SECURITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_MODEL_VERSION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND` or `ERR_TRADE_ORDER_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/model_version_create_against_unknown_model_returns_model_not_found
    """
    resp = api.create_model_version(
        create_model_version_payload(NON_EXISTENT_UUID), MANAGER
    )

    validate_error(resp, ApiErrorId.ERR_MODEL_NOT_FOUND.value)

    rows, meta = validate_paginated(api.list_model_versions(MANAGER))
    assert rows == [], f"no model version may be written, got {len(rows)} rows"
    assert meta["total_count"] == 0, (
        f"total_count must stay 0, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Opening an account
# ---------------------------------------------------------------------------
def test_account_optional_inputs_fall_back_to_declared_defaults(api):
    """PRD §3.4: "Four optional customization inputs may accompany the request: `cash_reserve_bps`, an integer from 0 to 2000 defaulting to 100, which is the fraction of market value the generator of §3.5 holds back from investment; `drift_basis`, either `SETTLED` or `TRADE_DATE` and defaulting to `SETTLED`, which selects the account's default drift convention; `tax_overlay_enabled`, a boolean defaulting to false, which is the master switch for tax-loss harvesting; and `harvest_budget_cents`, a non-negative integer defaulting to 0, which is the annual ceiling on realized losses."

    Design: Corner/entities/account_optional_inputs_fall_back_to_declared_defaults
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)], sleeves=[("ALFA", 10000)]
    )

    resp = api.create_account(
        create_account_payload(
            env["sponsor"]["id"], env["model"]["id"], account_number="ACC-001"
        ),
        env["sponsor_headers"],
    )
    account = validate_success(resp, 201)

    assert account["cash_reserve_bps"] == 100, (
        f"cash_reserve_bps defaults to 100, got {account['cash_reserve_bps']!r}"
    )
    assert account["drift_basis"] == "SETTLED", (
        f"drift_basis defaults to SETTLED, got {account['drift_basis']!r}"
    )
    assert account["tax_overlay_enabled"] is False, (
        f"tax_overlay_enabled defaults to false, got {account['tax_overlay_enabled']!r}"
    )
    assert account["harvest_budget_cents"] == 0, (
        f"harvest_budget_cents defaults to 0, got {account['harvest_budget_cents']!r}"
    )


def test_account_opens_on_the_published_version_in_synced_and_current(api):
    """PRD §3.4: "Otherwise the new account's `current_model_version_id` is set to exactly that published version, its `pending_model_version_id` is null, its `implementation_status` starts at `SYNCED`, its `billing_status` starts at `CURRENT`, its `cash_cents` starts at 0, its `realized_loss_ytd_cents` and `fees_billed_ytd_cents` both start at 0, its `next_order_sequence` starts at 1, and its `drift_bps`, `drift_basis_used`, `drift_evaluated_at`, `notified_at`, `implementation_deadline`, `last_implementation_lag_days`, `latest_return_bps`, `latest_return_period_end` and `latest_ending_value_cents` all start null, with `implemented_late` starting false."

    Design: Corner/entities/account_optional_inputs_fall_back_to_declared_defaults
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)], sleeves=[("ALFA", 10000)]
    )

    account = validate_success(
        api.create_account(
            create_account_payload(
                env["sponsor"]["id"], env["model"]["id"], account_number="ACC-001"
            ),
            env["sponsor_headers"],
        ),
        201,
    )

    assert account["current_model_version_id"] == env["model_version"]["id"], (
        "current_model_version_id must be exactly the published version "
        f"{env['model_version']['id']}, got {account['current_model_version_id']!r}"
    )
    assert account["pending_model_version_id"] is None, (
        f"pending_model_version_id starts null, got "
        f"{account['pending_model_version_id']!r}"
    )
    assert account["implementation_status"] == "SYNCED", (
        f"implementation_status starts at SYNCED, got "
        f"{account['implementation_status']!r}"
    )
    assert account["billing_status"] == "CURRENT", (
        f"billing_status starts at CURRENT, got {account['billing_status']!r}"
    )
    assert account["cash_cents"] == 0, (
        f"cash_cents starts at 0, got {account['cash_cents']!r}"
    )
    assert account["realized_loss_ytd_cents"] == 0, (
        f"realized_loss_ytd_cents starts at 0, got "
        f"{account['realized_loss_ytd_cents']!r}"
    )
    assert account["fees_billed_ytd_cents"] == 0, (
        f"fees_billed_ytd_cents starts at 0, got {account['fees_billed_ytd_cents']!r}"
    )
    assert account["next_order_sequence"] == 1, (
        f"next_order_sequence starts at 1, got {account['next_order_sequence']!r}"
    )
    assert account["drift_bps"] is None, (
        f"drift_bps starts null, got {account['drift_bps']!r}"
    )
    assert account["drift_basis_used"] is None, (
        f"drift_basis_used starts null, got {account['drift_basis_used']!r}"
    )
    assert account["implemented_late"] is False, (
        f"implemented_late starts false, got {account['implemented_late']!r}"
    )


def test_newly_opened_account_carries_version_one(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, whether the mutation was requested directly or arrived as a downstream consequence of some other operation."

    Design: Corner/entities/account_optional_inputs_fall_back_to_declared_defaults
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)], sleeves=[("ALFA", 10000)]
    )

    account = validate_success(
        api.create_account(
            create_account_payload(
                env["sponsor"]["id"], env["model"]["id"], account_number="ACC-001"
            ),
            env["sponsor_headers"],
        ),
        201,
    )

    assert account["version"] == 1, (
        f"a freshly opened account carries version 1, got {account['version']!r}"
    )
    assert is_valid_uuid(account["id"]), (
        f"id must be a server-minted UUID, got {account['id']!r}"
    )


# ---------------------------------------------------------------------------
# Market value is derived, never supplied
# ---------------------------------------------------------------------------
def test_market_value_is_cash_plus_open_lots_at_the_current_mark(api):
    """PRD §3.4: "It is at all times the account's `cash_cents` plus, summed over every tax lot of that account still in status `OPEN`, that lot's `shares_open` multiplied by the current `last_price_cents` of the lot's security."

    Design: Corner/entities/account_market_value_recomputed_from_open_lots_and_cash
    """
    env = _account_with_alfa()
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]

    deposit(account_id, sponsor_id, 2_500_000)
    transfer_in(
        account_id,
        sponsor_id,
        env["securities"]["ALFA"]["id"],
        1250,
        12_500_000,
        origin="TRANSFER_IN",
    )

    account = validate_success(api.get_account(account_id, ADMIN))
    assert account["cash_cents"] == 2_500_000, (
        f"only the deposit moves cash, got {account['cash_cents']!r}"
    )
    assert account["market_value_cents"] == 15_000_000, (
        "market_value_cents must be 2500000 cash plus 1250 shares at 10000 cents, "
        f"got {account['market_value_cents']!r}"
    )


def test_remark_moves_market_value_but_never_rewrites_stored_basis(api):
    """PRD §3.1: "Every valuation, drift evaluation, order generation and harvest computation performed *after* the re-mark uses the new number, but no account's `drift_bps` is recomputed as a side effect, and figures already committed to storage — the `cost_basis_cents` on existing tax lots and every amount on an existing fee invoice — are never rewritten."

    Design: Corner/entities/account_market_value_recomputed_from_open_lots_and_cash
    """
    env = _account_with_alfa()
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    deposit(account_id, sponsor_id, 2_500_000)
    lot = transfer_in(
        account_id, sponsor_id, alfa_id, 1250, 12_500_000, origin="TRANSFER_IN"
    )

    reprice_security(alfa_id, 12_000)

    account = validate_success(api.get_account(account_id, ADMIN))
    assert account["market_value_cents"] == 17_500_000, (
        "market_value_cents must follow the new mark: 2500000 cash plus 1250 shares "
        f"at 12000 cents, got {account['market_value_cents']!r}"
    )

    stored_lot = validate_success(api.get_tax_lot(lot["id"], ADMIN))
    assert stored_lot["cost_basis_cents"] == 12_500_000, (
        "a re-mark never rewrites a stored tax-lot cost basis, got "
        f"{stored_lot['cost_basis_cents']!r}"
    )


def test_transfer_in_books_an_open_lot_at_the_clock_instant(api):
    """PRD §3.4: "Booking a position creates a tax lot in status `OPEN` whose `open_date` is the current logical clock instant and whose `sequence_number` is drawn from the account's `next_order_sequence` counter."

    Design: Corner/entities/account_market_value_recomputed_from_open_lots_and_cash
    """
    env = _account_with_alfa()
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]

    lot = transfer_in(
        account_id,
        sponsor_id,
        env["securities"]["ALFA"]["id"],
        1250,
        12_500_000,
        origin="TRANSFER_IN",
    )

    assert lot["status"] == "OPEN", (
        f"a booked position is born OPEN, got {lot['status']!r}"
    )
    assert lot["origin"] == "TRANSFER_IN", (
        f"the supplied origin must be recorded, got {lot['origin']!r}"
    )
    assert lot["shares_open"] == 1250, (
        f"shares_open must carry the booked share count, got {lot['shares_open']!r}"
    )
    assert lot["shares_closed"] == 0, (
        f"a freshly booked lot has closed no shares, got {lot['shares_closed']!r}"
    )
    assert lot["sequence_number"] == 1, (
        "the first lot draws sequence number 1 from the account's counter, got "
        f"{lot['sequence_number']!r}"
    )
    assert is_iso8601_timestamp(lot["open_date"]), (
        f"open_date must be an ISO 8601 UTC timestamp, got {lot['open_date']!r}"
    )
    assert lot["open_date"].startswith("2026-08-01T00:00:00"), (
        "open_date must be the untouched logical clock instant 2026-08-01T00:00:00Z, "
        f"got {lot['open_date']!r}"
    )


# ---------------------------------------------------------------------------
# Model versions are numbered by the server
# ---------------------------------------------------------------------------
def test_model_version_numbers_are_server_assigned_and_sequential(api):
    """PRD §3.2: "A `PortfolioManager` opens a new version by naming the owning `model_id`; the platform assigns a `version_number` equal to the strategy's `version_count` plus one, starts the version in status `DRAFT`, and advances both the strategy's `version_count` and the strategy's own `version`."

    Design: Corner/entities/model_version_number_is_server_assigned_and_sequential
    """
    model = validate_success(
        api.create_model(create_model_payload(strategy_code="CORE"), MANAGER), 201
    )

    first = validate_success(
        api.create_model_version(create_model_version_payload(model["id"]), MANAGER),
        201,
    )
    second = validate_success(
        api.create_model_version(create_model_version_payload(model["id"]), MANAGER),
        201,
    )

    assert first["version_number"] == 1, (
        f"the first version of a strategy is numbered 1, got {first['version_number']!r}"
    )
    assert second["version_number"] == 2, (
        f"the second version is numbered 2, got {second['version_number']!r}"
    )
    assert first["status"] == "DRAFT", (
        f"a new version starts in DRAFT, got {first['status']!r}"
    )
    assert second["status"] == "DRAFT", (
        f"a new version starts in DRAFT, got {second['status']!r}"
    )

    refreshed = validate_success(api.get_model(model["id"], MANAGER))
    assert refreshed["version_count"] == 2, (
        f"version_count must count both versions, got {refreshed['version_count']!r}"
    )


def test_freshly_opened_model_version_starts_empty(api):
    """PRD §3.2: "A freshly opened version has an empty `sleeves` array, a `sleeve_count` of 0, a `total_target_weight_bps` of 0, a null `submitted_by_user_id`, a null `approved_by_user_id`, a null `rejection_note`, a null `published_at`, a null `superseded_at`, and a `distribution_count` of 0."

    Design: Corner/entities/model_version_number_is_server_assigned_and_sequential
    """
    model = validate_success(
        api.create_model(create_model_payload(strategy_code="CORE"), MANAGER), 201
    )

    version = validate_success(
        api.create_model_version(create_model_version_payload(model["id"]), MANAGER),
        201,
    )

    assert version["sleeves"] == [], (
        f"sleeves starts as an empty array, got {version['sleeves']!r}"
    )
    assert version["sleeve_count"] == 0, (
        f"sleeve_count starts at 0, got {version['sleeve_count']!r}"
    )
    assert version["total_target_weight_bps"] == 0, (
        f"total_target_weight_bps starts at 0, got "
        f"{version['total_target_weight_bps']!r}"
    )
    assert version["submitted_by_user_id"] is None, (
        f"submitted_by_user_id starts null, got {version['submitted_by_user_id']!r}"
    )
    assert version["approved_by_user_id"] is None, (
        f"approved_by_user_id starts null, got {version['approved_by_user_id']!r}"
    )
    assert version["rejection_note"] is None, (
        f"rejection_note starts null, got {version['rejection_note']!r}"
    )
    assert version["published_at"] is None, (
        f"published_at starts null, got {version['published_at']!r}"
    )
    assert version["superseded_at"] is None, (
        f"superseded_at starts null, got {version['superseded_at']!r}"
    )
    assert version["distribution_count"] == 0, (
        f"distribution_count starts at 0, got {version['distribution_count']!r}"
    )


def test_model_derived_pointers_begin_empty_and_only_version_count_moves(api):
    """PRD §3.1: "A strategy also carries two derived pointers that begin empty: `version_count`, starting at 0 and counting the versions authored against it, and `published_model_version_id`, starting null and holding the identifier of whichever of its versions is currently published."

    Design: Corner/entities/model_version_number_is_server_assigned_and_sequential
    """
    model = validate_success(
        api.create_model(create_model_payload(strategy_code="CORE"), MANAGER), 201
    )
    assert model["version_count"] == 0, (
        f"version_count starts at 0, got {model['version_count']!r}"
    )
    assert model["published_model_version_id"] is None, (
        "published_model_version_id starts null, got "
        f"{model['published_model_version_id']!r}"
    )

    for _ in range(2):
        validate_success(
            api.create_model_version(
                create_model_version_payload(model["id"]), MANAGER
            ),
            201,
        )

    refreshed = validate_success(api.get_model(model["id"], MANAGER))
    assert refreshed["version_count"] == 2, (
        f"version_count counts the versions authored, got {refreshed['version_count']!r}"
    )
    assert refreshed["published_model_version_id"] is None, (
        "published_model_version_id stays null while no version is published, got "
        f"{refreshed['published_model_version_id']!r}"
    )


# ---------------------------------------------------------------------------
# Unique account numbers
# ---------------------------------------------------------------------------
def test_duplicate_account_number_is_refused(api):
    """PRD §3.4: "A `SponsorOperator` opens an account by naming its own `sponsor_id`, the `model_id` of the strategy the account will track, and an `account_number` of three to twenty characters that must be unique across every account on the platform — a collision is refused with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/duplicate_account_number_returns_duplicate_key
    """
    env = _account_with_alfa()

    duplicate = api.create_account(
        create_account_payload(
            env["sponsor"]["id"], env["model"]["id"], account_number="ACC-001"
        ),
        env["sponsor_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_KEY.value)

    rows, meta = validate_paginated(
        api.list_accounts(ADMIN, params={"sponsor_id": env["sponsor"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected duplicate must not be persisted, got {meta['total_count']} rows"
    )
    assert len(rows) == 1 and rows[0]["id"] == env["account"]["id"], (
        "only the originally opened account may survive, got "
        f"{[row['id'] for row in rows]}"
    )


def test_sponsor_account_count_rises_only_for_accepted_accounts(api):
    """PRD §3.1: "A denormalized `account_count` tracks how many accounts the sponsor holds and rises by one each time one is opened."

    Design: Corner/entities/duplicate_account_number_returns_duplicate_key
    """
    env = _account_with_alfa()

    validate_error(
        api.create_account(
            create_account_payload(
                env["sponsor"]["id"], env["model"]["id"], account_number="ACC-001"
            ),
            env["sponsor_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
    )

    sponsor = validate_success(api.get_sponsor(env["sponsor"]["id"], ADMIN))
    assert sponsor["account_count"] == 1, (
        "account_count rises by one per opened account and not at all for a "
        f"refused one, got {sponsor['account_count']!r}"
    )


# ---------------------------------------------------------------------------
# Filtered, ordered, paginated tax-lot reads
# ---------------------------------------------------------------------------
def _account_with_four_lots():
    """One account holding three ALFA lots and one BETA lot."""
    env = _account_with_alfa(
        securities=[("ALFA", "Alfa Industrials", 10_000), ("BETA", "Beta Materials", 5_000)],
        sleeves=[("ALFA", 10000)],
    )
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]
    beta_id = env["securities"]["BETA"]["id"]

    env["lots"] = [
        transfer_in(account_id, sponsor_id, alfa_id, 10, 100_000, origin="TRANSFER_IN"),
        transfer_in(account_id, sponsor_id, alfa_id, 20, 220_000, origin="TRANSFER_IN"),
        transfer_in(account_id, sponsor_id, alfa_id, 30, 360_000, origin="TRADE"),
        transfer_in(account_id, sponsor_id, beta_id, 40, 200_000, origin="TRANSFER_IN"),
    ]
    return env


def test_tax_lot_filters_combine_conjunctively(api):
    """PRD §2.11: "Collection reads narrow their result with query parameters rather than with path segments: model versions filter by `model_id` and `status`; distributions filter by `sponsor_id`, `model_version_id`, `model_id` and `status`; accounts filter by `sponsor_id`, `model_id`, `current_model_version_id`, `pending_model_version_id`, `implementation_status` and `billing_status`; restrictions filter by `account_id`, `security_id` and `status`; trade orders filter by `account_id`, `security_id`, `model_version_id`, `block_id`, `status`, `source` and `side`; blocks filter by `security_id`, `status` and `side`; tax lots filter by `account_id`, `security_id`, `parent_tax_lot_id`, `opening_trade_order_id`, `closing_trade_order_id`, `status` and `origin`; harvest proposals filter by `account_id`, `security_id`, `replacement_security_id` and `status`; and fee invoices filter by `account_id` and `status`."

    Design: Corner/entities/tax_lots_list_filters_by_account_and_security_with_pagination_envelope
    """
    env = _account_with_four_lots()
    account_id = env["account"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    rows, meta = validate_paginated(
        api.list_tax_lots(
            ADMIN, params={"account_id": account_id, "security_id": alfa_id}
        )
    )
    assert meta["total_count"] == 3, (
        f"the account holds exactly three ALFA lots, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {lot["id"] for lot in env["lots"][:3]}, (
        f"only the ALFA lots may match, got {[row['id'] for row in rows]}"
    )

    trade_rows, trade_meta = validate_paginated(
        api.list_tax_lots(
            ADMIN,
            params={
                "account_id": account_id,
                "security_id": alfa_id,
                "origin": "TRADE",
            },
        )
    )
    assert trade_meta["total_count"] == 1, (
        f"only one ALFA lot carries origin TRADE, got {trade_meta['total_count']}"
    )
    assert trade_rows[0]["id"] == env["lots"][2]["id"], (
        f"the TRADE-origin lot must be the third one booked, got {trade_rows[0]['id']}"
    )


def test_tax_lot_listing_reports_the_full_pagination_meta(api):
    """PRD §2.3: "For every list response, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/tax_lots_list_filters_by_account_and_security_with_pagination_envelope
    """
    env = _account_with_four_lots()

    rows, meta = validate_paginated(
        api.list_tax_lots(
            ADMIN,
            params={
                "account_id": env["account"]["id"],
                "security_id": env["securities"]["ALFA"]["id"],
                "limit": 2,
                "offset": 0,
            },
        )
    )

    assert len(rows) == 2, f"the page window holds two rows, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"total_count counts all matching rows before the window, got "
        f"{meta['total_count']}"
    )
    assert meta["limit"] == 2, f"meta.limit echoes the request, got {meta['limit']}"
    assert meta["offset"] == 0, f"meta.offset echoes the request, got {meta['offset']}"
    assert meta["has_more"] is True, (
        f"a third row remains beyond the window, got has_more {meta['has_more']!r}"
    )


def test_tax_lot_listing_is_ordered_by_creation_then_sequence(api):
    """PRD §2.3: "Two collections carry a documented tie-breaker because they are written in bursts within a single operation and can share a timestamp: trade-order listings and tax-lot listings break `created_at` ties by `sequence_number` ascending."

    Design: Corner/entities/tax_lots_list_filters_by_account_and_security_with_pagination_envelope
    """
    env = _account_with_four_lots()

    rows, _meta = validate_paginated(
        api.list_tax_lots(
            ADMIN,
            params={
                "account_id": env["account"]["id"],
                "security_id": env["securities"]["ALFA"]["id"],
            },
        )
    )

    expected = [lot["id"] for lot in env["lots"][:3]]
    assert [row["id"] for row in rows] == expected, (
        f"lots must be listed in booking order {expected}, got "
        f"{[row['id'] for row in rows]}"
    )
    sequences = [row["sequence_number"] for row in rows]
    assert sequences == sorted(sequences), (
        f"sequence numbers must be ascending across the page, got {sequences}"
    )


def test_market_value_sums_every_open_lot_across_securities(api):
    """PRD §3.4: "It is at all times the account's `cash_cents` plus, summed over every tax lot of that account still in status `OPEN`, that lot's `shares_open` multiplied by the current `last_price_cents` of the lot's security."

    Design: Corner/entities/tax_lots_list_filters_by_account_and_security_with_pagination_envelope
    """
    env = _account_with_four_lots()

    account = get_account(env["account"]["id"])

    assert account["cash_cents"] == 0, (
        f"no cash was deposited, got {account['cash_cents']!r}"
    )
    assert account["market_value_cents"] == 800_000, (
        "market_value_cents must be 60 ALFA shares at 10000 cents plus 40 BETA "
        f"shares at 5000 cents, got {account['market_value_cents']!r}"
    )
