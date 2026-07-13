"""Standing up a fleet: accounts, vehicles, drivers, and the fuel-card lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_fleet_account,
    assert_fuel_card,
    create_fleet_account_payload,
    create_fuel_card_payload,
    create_vehicle_payload,
    make_fleet_account,
    make_fleet_manager_headers,
    make_fuel_card,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_create_fleet_account_returns_201_with_defaults(api):
    """PRD §3.1: "A `ProgramAdmin` stands up a fleet by creating a `FleetAccount`,
    supplying its `company_name`, `base_jurisdiction`, and `credit_limit_cents`
    (which must be zero or greater), optionally its `rebate_tiers` and its `status`."
    PRD §2.7: "An account additionally has a `company_name`, a `base_jurisdiction`
    (its home two-letter IFTA state code), a `status` that is one of `ACTIVE`,
    `SUSPENDED`, or `CLOSED` (defaulting to `ACTIVE`), and a `rebate_tiers`
    schedule (§3.5)."
    PRD §4: "Operations that create a new stand-alone resource return `201 Created`."

    Design: Corner/entities/create_fleet_account_returns_201_with_fields
    """
    payload = create_fleet_account_payload(
        company_name="New Co", base_jurisdiction="CA", credit_limit_cents=500_000
    )
    account = validate_success(api.create_fleet_account(payload, ADMIN), 201)

    assert_fleet_account(account)
    assert account["company_name"] == "New Co"
    assert account["credit_limit_cents"] == 500_000
    assert account["status"] == "ACTIVE", "status defaults to ACTIVE"


def test_fresh_account_available_credit_equals_limit(api):
    """PRD §2.7: "`outstanding_holds_cents` is the sum of `gross_amount_cents`
    over the account's transactions whose `posting_status` is `AUTHORIZED` or
    `CAPTURED`."
    PRD §2.7: "`available_credit_cents` is `credit_limit_cents` minus
    `outstanding_holds_cents` minus `settled_spend_cents`."

    Design: Corner/entities/fresh_account_available_credit_equals_limit
    """
    account = make_fleet_account(api, company_name="Ledger Co", credit_limit_cents=500_000)

    fetched = validate_success(api.get_fleet_account(account["id"], ADMIN))

    assert fetched["outstanding_holds_cents"] == 0, "no transactions means no holds"
    assert fetched["settled_spend_cents"] == 0
    assert fetched["available_credit_cents"] == 500_000, (
        "with no holds and no settled spend, available credit is the whole limit"
    )


def test_card_hour_window_defaults_applied(api):
    """PRD §3.2: "That window is `allowed_start_hour` (inclusive, UTC hour 0–23,
    defaulting to 0) through `allowed_end_hour` (exclusive, UTC hour 1–24,
    defaulting to 24), where `allowed_start_hour` must be strictly less than
    `allowed_end_hour` and `allowed_end_hour` at most 24; the permitted window is
    the half-open range from `allowed_start_hour` up to but not including
    `allowed_end_hour`."
    PRD §3.2: "A card's `status` is system-managed and moves through `ISSUED`,
    `ACTIVE`, `SUSPENDED`, and the terminal `CANCELLED`, starting at `ISSUED`."

    Design: Corner/entities/card_default_hours_applied
    """
    account = make_fleet_account(api, company_name="Def Co", credit_limit_cents=500_000)
    payload = create_fuel_card_payload(
        account["id"], last4="0400", allowed_products=["DIESEL"],
        daily_dollar_limit_cents=100_000, per_txn_gallon_limit=100,
    )

    card = validate_success(
        api.create_fuel_card(payload, make_fleet_manager_headers(account["id"])), 201
    )

    assert_fuel_card(card)
    assert card["allowed_start_hour"] == 0
    assert card["allowed_end_hour"] == 24
    assert card["status"] == "ISSUED"


def test_vehicle_missing_tank_capacity_rejected(api):
    """PRD §3.1: "A vehicle is created with its owning `fleet_account_id`, a
    `plate`, a `tank_capacity_gallons` (strictly greater than zero, later used by
    the over-tank fraud check), an acceptable fuel-economy band expressed as
    `expected_mpg_min` (strictly greater than zero) and `expected_mpg_max` (which
    must be at least `expected_mpg_min`), a `home_jurisdiction`, and optionally a
    `starting_odometer` (zero or greater, defaulting to 0)."
    PRD §2.9: "Malformed input — a missing required field, a value of the wrong
    type, or an unrecognized enum value — is rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/vehicle_missing_required_field_rejected
    """
    account = make_fleet_account(api, company_name="Req Co", credit_limit_cents=500_000)
    payload = create_vehicle_payload(account["id"], plate="VX")
    payload.pop("tank_capacity_gallons")

    resp = api.create_vehicle(payload, make_fleet_manager_headers(account["id"]))

    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_vehicle_unknown_fleet_account_fk_not_found(api):
    """PRD §2.9: "When a request references resources by path segment or by
    foreign-key body field, each referenced resource must exist; existence is
    checked left to right, and the first missing reference produces the
    corresponding not-found error (`ERR_FLEET_ACCOUNT_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
    `ERR_FAULT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, all 404)."

    Design: Corner/entities/vehicle_bad_fleet_fk_not_found
    """
    payload = create_vehicle_payload(UNKNOWN_UUID, plate="VY")

    resp = api.create_vehicle(payload, make_fleet_manager_headers(UNKNOWN_UUID))

    validate_error(resp, ApiErrorId.ERR_FLEET_ACCOUNT_NOT_FOUND.value)


def test_get_unknown_vehicle_not_found(api):
    """PRD §2.9: "When a request references resources by path segment or by
    foreign-key body field, each referenced resource must exist; existence is
    checked left to right, and the first missing reference produces the
    corresponding not-found error (`ERR_FLEET_ACCOUNT_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
    `ERR_FAULT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, all 404)."

    Design: Corner/entities/vehicle_not_found_on_get
    """
    resp = api.get_vehicle(UNKNOWN_UUID, ADMIN)

    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)


def test_card_with_unknown_product_enum_rejected(api):
    """PRD §3.2: "A `FleetManager` issues a `FuelCard` against its account,
    supplying `fleet_account_id`, the display-only `last4`, and the card's
    purchase controls: `allowed_products` (a subset of `UNLEADED`, `PREMIUM`,
    `DIESEL`, and `DEF`), a `daily_dollar_limit_cents` (zero or greater) capping
    the card's held-plus-settled spend per UTC calendar day, a
    `per_txn_gallon_limit` (strictly greater than zero) capping a single fill, and
    an optional purchase-hour window."
    PRD §2.9: "Malformed input — a missing required field, a value of the wrong
    type, or an unrecognized enum value — is rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/card_invalid_product_enum_rejected
    """
    account = make_fleet_account(api, company_name="Enum Co", credit_limit_cents=500_000)
    payload = create_fuel_card_payload(
        account["id"], last4="0401", allowed_products=["KEROSENE"],
        daily_dollar_limit_cents=100_000, per_txn_gallon_limit=100,
    )

    resp = api.create_fuel_card(payload, make_fleet_manager_headers(account["id"]))

    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_new_card_starts_in_issued(api):
    """PRD §3.2: "A card's `status` is system-managed and moves through `ISSUED`,
    `ACTIVE`, `SUSPENDED`, and the terminal `CANCELLED`, starting at `ISSUED`."

    Design: Corner/state_machines/new_card_initial_state_issued
    """
    account = make_fleet_account(api, company_name="Init Co", credit_limit_cents=500_000)
    payload = create_fuel_card_payload(
        account["id"], last4="0503", allowed_products=["DIESEL"],
        daily_dollar_limit_cents=100_000, per_txn_gallon_limit=100,
    )

    card = validate_success(
        api.create_fuel_card(payload, make_fleet_manager_headers(account["id"])), 201
    )

    assert_fuel_card(card)
    assert card["status"] == "ISSUED", "a newly issued card starts in ISSUED"
    assert isinstance(card["version"], int)


def test_activate_increments_card_version_by_one(api):
    """PRD §2.5: "`version` is an integer that starts at its initial value and
    increments by one on every mutation of the resource; it exists so clients can
    detect concurrent modification."
    PRD §3.2: "A `FleetManager` activates a card that is currently `ISSUED` or
    `SUSPENDED`, moving it to `ACTIVE` and incrementing its `version`; activating
    a card that is `SUSPENDED` is a reinstatement."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_activate
    """
    account = make_fleet_account(api, company_name="Ver Co", credit_limit_cents=500_000)
    fm = make_fleet_manager_headers(account["id"])
    card = make_fuel_card(
        api, account["id"], last4="1001", daily_dollar_limit_cents=100_000,
        per_txn_gallon_limit=100,
    )
    version_before = card["version"]

    activated = validate_success(api.activate_fuel_card(card["id"], fm))

    assert activated["status"] == "ACTIVE"
    assert activated["version"] == version_before + 1, (
        f"activate must increment version by exactly one: "
        f"{version_before} -> {activated['version']}"
    )


def test_activate_cancelled_card_rejected(api):
    """PRD §3.2: "A `FleetManager` cancels a card from any non-`CANCELLED` state,
    moving it to the terminal `CANCELLED` and incrementing its `version`;
    cancellation ends every `ACTIVE` card assignment on the card (moving each to
    `ENDED`)."
    PRD §3.2: "Activating a card that is neither `ISSUED` nor `SUSPENDED` is
    rejected with `ERR_INVALID_CARD_STATE`."

    Design: Corner/state_machines/activate_cancelled_card_rejected_terminal
    """
    account = make_fleet_account(api, company_name="Term Co", credit_limit_cents=500_000)
    fm = make_fleet_manager_headers(account["id"])
    card = make_fuel_card(
        api, account["id"], last4="0501", daily_dollar_limit_cents=100_000,
        per_txn_gallon_limit=100,
    )
    cancelled = validate_success(api.cancel_fuel_card(card["id"], fm))
    assert cancelled["status"] == "CANCELLED"

    resp = api.activate_fuel_card(card["id"], fm)

    validate_error(resp, ApiErrorId.ERR_INVALID_CARD_STATE.value)
