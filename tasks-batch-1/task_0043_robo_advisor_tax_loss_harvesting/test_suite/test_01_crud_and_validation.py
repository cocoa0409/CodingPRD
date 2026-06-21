"""CRUD, input validation, system fields, and the test-driving clock.

Translates queue-B (Corner) instances from sections `entities`, `endpoints`,
and the new-account / clock claims. Every test cites verbatim PRD prose and
carries one source-instance tag line.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_account_payload,
    create_security_payload,
    create_model_portfolio_payload,
    create_tax_lot_payload,
    create_questionnaire_payload,
    set_clock_payload,
    assert_account,
    assert_tax_lot,
    assert_questionnaire,
    set_clock,
    create_active_account,
    create_security,
    create_model,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_open_account_returns_201_pending_profile(api):
    """PRD §3.2: "A freshly opened account starts in `PENDING_PROFILE` status with `cash_balance_cents` of zero, a `version` of 1, and a `model_portfolio_id` and `risk_score` of null until the first questionnaire is accepted."

    Design: Corner/entities/create_account_returns_201_pending_profile
    """
    set_clock("2026-05-01T00:00:00.000Z")
    res = api.create_account(create_account_payload(client_email="new@x.com"), ADVISOR)
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["status"] == "PENDING_PROFILE"
    assert acct["cash_balance_cents"] == 0
    assert acct["version"] == 1
    assert acct["model_portfolio_id"] is None
    assert acct["risk_score"] is None


def test_get_account_returns_stored_entity(api):
    """PRD §3.2: "A client relationship begins when an advisor opens an account by supplying a `client_email`, which must be unique across all accounts". PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="getme@x.com"), ADVISOR)
    )
    res = api.get_account(acct["id"], COMPLIANCE)
    fetched = validate_success(res, 200)
    assert fetched["id"] == acct["id"]
    assert fetched["client_email"] == "getme@x.com"


def test_list_securities_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_securities_paginated_envelope
    """
    create_security("LST1", "US_EQUITY", 10000)
    create_security("LST2", "BOND", 9000)
    res = api.list_securities(ADVISOR, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_account_not_found_returns_404(api):
    """PRD §2.5: "the server validates those identifiers left-to-right and rejects the first one that does not resolve to an existing entity with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account(NON_EXISTENT_UUID, ADVISOR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_open_account_missing_client_email_returns_422(api):
    """PRD §2.10: "the body is then validated for well-formedness — required fields present, enum members valid, numeric ranges respected — yielding `ERR_INVALID_REQUEST` when violated".

    Design: Corner/entities/create_account_missing_required_field_returns_422
    """
    res = api.create_account({}, ADVISOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_model_targets_not_summing_100_returns_422(api):
    """PRD §3.1: "the `target_pct` values must sum to exactly 100; a model whose targets do not sum to 100 is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/model_targets_not_summing_100_returns_422
    """
    res = api.create_model_portfolio(
        create_model_portfolio_payload(
            name="Bad",
            min_risk_score=0,
            max_risk_score=100,
            targets=[
                {"asset_class": "US_EQUITY", "target_pct": 60},
                {"asset_class": "BOND", "target_pct": 30},
            ],
            drift_threshold_pct=5,
        ),
        ADVISOR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_tax_lot_quantity_zero_returns_422(api):
    """PRD §3.3: "a `quantity` of shares (which must be greater than 0)". PRD §2.10:
    "the body is then validated for well-formedness — required fields present, enum members valid, numeric ranges respected — yielding `ERR_INVALID_REQUEST` when violated".

    Design: Corner/entities/tax_lot_quantity_zero_returns_422
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="Q0", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    sec = create_security("Z0", "US_EQUITY", 10000)
    acct = create_active_account("q0@x.com")
    res = api.create_tax_lot(
        create_tax_lot_payload(
            account_id=acct["id"], security_id=sec["id"], quantity=0, cost_basis_cents=10000
        ),
        ADVISOR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_ticker_returns_409(api):
    """PRD §3.1: "Attempting to create a security whose `ticker` already exists is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_ticker_returns_409
    """
    create_security("DUP", "US_EQUITY", 10000)
    res = api.create_security(
        create_security_payload(ticker="DUP", asset_class="BOND", price_cents=9000), ADVISOR
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_tax_lot_acquired_at_and_status_system_generated(api):
    """PRD §3.3: "At creation the lot's `acquired_at` is stamped from the server clock, its `status` is `OPEN`, its `disposed_at` and `proceeds_cents` are null, and its `closed_by_harvest_id` is null."

    Design: Corner/entities/tax_lot_acquired_at_and_status_system_generated
    """
    set_clock("2026-08-08T12:00:00.000Z")
    create_model(name="SF", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    sec = create_security("SF1", "US_EQUITY", 10000)
    acct = create_active_account("sf@x.com")
    lot = get_success_data(
        api.create_tax_lot(
            create_tax_lot_payload(
                account_id=acct["id"], security_id=sec["id"], quantity=2, cost_basis_cents=20000
            ),
            ADVISOR,
        )
    )
    assert_tax_lot(lot)
    assert lot["status"] == "OPEN"
    assert lot["acquired_at"] == "2026-08-08T12:00:00.000Z"


def test_questionnaire_has_no_version_field(api):
    """PRD §2.4: "The risk questionnaire is the sole exception: it carries only `id` and `created_at`. A questionnaire has no `updated_at` and no `version`."

    Design: Corner/entities/questionnaire_immutable_no_version_field
    """
    create_model(name="QV", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="imm@x.com"), ADVISOR)
    )
    q = get_success_data(
        api.create_questionnaire(create_questionnaire_payload(account_id=acct["id"]), ADVISOR)
    )
    res = api.get_questionnaire(q["id"], ADVISOR)
    fetched = validate_success(res, 200)
    assert "id" in fetched and "created_at" in fetched
    assert "version" not in fetched
    assert "updated_at" not in fetched
    assert_questionnaire(fetched)


def test_new_account_initial_state_pending_profile(api):
    """PRD §3.2: "A freshly opened account starts in `PENDING_PROFILE` status with `cash_balance_cents` of zero, a `version` of 1, and a `model_portfolio_id` and `risk_score` of null until the first questionnaire is accepted."

    Design: Corner/state_machines/new_account_initial_state_pending_profile
    """
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="init@x.com"), ADVISOR)
    )
    assert acct["status"] == "PENDING_PROFILE"
    assert acct["risk_score"] is None


def test_clock_set_returns_current_utc(api):
    """PRD §3.10: "A clock-setting capability accepts a `to_iso8601` instant and advances or resets the server's current UTC to it, returning the new `current_utc`."

    Design: Corner/endpoints/clock_set_returns_current_utc
    """
    res = api.set_clock(set_clock_payload("2027-01-01T00:00:00.000Z"), ADVISOR)
    data = validate_success(res, 200)
    assert data["current_utc"] == "2027-01-01T00:00:00.000Z"
