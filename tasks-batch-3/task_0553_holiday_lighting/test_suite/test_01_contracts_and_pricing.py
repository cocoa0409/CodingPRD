"""Seasonal-contract lifecycle and early-bird pricing.

Covers contract signing/pricing (the pinned subtotal -> early-bird -> tier -> discount
-> price order), the inclusive cutoff boundary, renewal, invalid-state transitions,
default storage handling, and contract listing/pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_draft_contract, sign_contract,
    setup_active_contract,
)
from test_helpers.factories import create_contract_payload, renew_contract_payload

SALES = TEST_USERS["salesrep_headers"]


# ── Difficulty/combinatorial_formula/early_bird_tier_on_subtotal_mode_c ───────

def test_early_bird_discount_tier_keyed_on_pre_discount_subtotal(api):
    """PRD §3.1: "Third it selects a discount rate from a tier keyed on the pre-discount
    `subtotal_cents`, never on the final price: if the contract is not early-bird the rate
    is zero; otherwise, when the subtotal is at least 100000 cents the rate is ten percent,
    when the subtotal is at least 50000 cents (but below the higher tier) the rate is five
    percent, and when the subtotal is below 50000 cents the rate is zero even for an
    early-bird contract."
    PRD §3.1: "Fourth it computes `discount_cents` as the subtotal multiplied by that rate,
    rounded half up to whole cents (zero when not early-bird). Finally it sets
    `contract_price_cents` to `subtotal_cents` minus `discount_cents`."

    subtotal 80000+25000=105000 keys the 10% tier (not the 94500 final price), so
    discount is 10500 and price 94500.

    Design: Difficulty/combinatorial_formula/early_bird_tier_on_subtotal_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer(name="Eve Owner", service_address="5 Ash St",
                               roofline_feet=180)
    draft = create_draft_contract(
        customer["id"], contract_type="SEASONAL_RENTAL", season_year=2026,
        base_season_fee_cents=80000, early_bird_cutoff="2026-08-15T00:00:00Z",
        storage_included=True, storage_surcharge_cents=25000)
    active = sign_contract(draft["id"])
    assert active["discount_cents"] == 10500, active
    assert active["contract_price_cents"] == 94500, active


def test_early_bird_subtotal_includes_storage_surcharge(api):
    """PRD §3.1: "First it fixes the pre-discount `subtotal_cents` as the
    `base_season_fee_cents` plus, only when `storage_included` is true, the
    `storage_surcharge_cents` (and plus nothing otherwise)."
    PRD §3.1: "Second it sets the `early_bird` flag to true exactly when the captured
    `signed_date` is on or before the `early_bird_cutoff`, treating the cutoff instant
    itself as still eligible (an inclusive boundary), and false otherwise."

    Design: Difficulty/combinatorial_formula/early_bird_tier_on_subtotal_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer(name="Eve Owner", service_address="5 Ash St",
                               roofline_feet=180)
    draft = create_draft_contract(
        customer["id"], contract_type="SEASONAL_RENTAL", season_year=2026,
        base_season_fee_cents=80000, early_bird_cutoff="2026-08-15T00:00:00Z",
        storage_included=True, storage_surcharge_cents=25000)
    active = sign_contract(draft["id"])
    assert active["subtotal_cents"] == 105000, active
    assert active["early_bird"] is True, active


# ── Difficulty/boundary_precision_check/early_bird_cutoff_inclusive_boundary ──

def test_signed_date_equal_to_cutoff_is_early_bird_eligible(api):
    """PRD §3.1: "Second it sets the `early_bird` flag to true exactly when the captured
    `signed_date` is on or before the `early_bird_cutoff`, treating the cutoff instant
    itself as still eligible (an inclusive boundary), and false otherwise."

    signed_date exactly equal to the cutoff (2026-08-15T00:00:00Z) still qualifies.

    Design: Difficulty/boundary_precision_check/early_bird_cutoff_inclusive_boundary
    """
    set_clock("2026-08-15T00:00:00Z")
    customer = create_customer(name="Lee Owner", service_address="12 Cliff St",
                               roofline_feet=175)
    draft = create_draft_contract(
        customer["id"], contract_type="SEASONAL_RENTAL", season_year=2026,
        base_season_fee_cents=80000, early_bird_cutoff="2026-08-15T00:00:00Z",
        storage_included=True, storage_surcharge_cents=25000)
    active = sign_contract(draft["id"])
    assert active["early_bird"] is True, active


def test_cutoff_boundary_applies_ten_percent_discount(api):
    """PRD §3.1: "Fourth it computes `discount_cents` as the subtotal multiplied by that
    rate, rounded half up to whole cents (zero when not early-bird). Finally it sets
    `contract_price_cents` to `subtotal_cents` minus `discount_cents`."

    At the inclusive boundary the 105000 subtotal still earns the 10% discount (10500),
    yielding price 94500.

    Design: Difficulty/boundary_precision_check/early_bird_cutoff_inclusive_boundary
    """
    set_clock("2026-08-15T00:00:00Z")
    customer = create_customer(name="Lee Owner", service_address="12 Cliff St",
                               roofline_feet=175)
    draft = create_draft_contract(
        customer["id"], contract_type="SEASONAL_RENTAL", season_year=2026,
        base_season_fee_cents=80000, early_bird_cutoff="2026-08-15T00:00:00Z",
        storage_included=True, storage_surcharge_cents=25000)
    active = sign_contract(draft["id"])
    assert active["discount_cents"] == 10500, active
    assert active["contract_price_cents"] == 94500, active


# ── Corner/entities/contract_default_storage_included_false ──────────────────

def test_contract_default_storage_included_false_excludes_surcharge(api):
    """PRD §3.1: "Optionally the rep marks `storage_included` (whether off-season storage
    of the customer's lights is bundled, defaulting to not included) and a
    `storage_surcharge_cents` to be added when storage is bundled (defaulting to 0)."
    PRD §3.1: "First it fixes the pre-discount `subtotal_cents` as the
    `base_season_fee_cents` plus, only when `storage_included` is true, the
    `storage_surcharge_cents` (and plus nothing otherwise)."

    Omitting storage_included defaults it to false, so subtotal == base (60000); at the
    5% tier discount is 3000 and price 57000.

    Design: Corner/entities/contract_default_storage_included_false
    """
    customer = create_customer(name="Def Owner", service_address="102 Main St",
                               roofline_feet=120)
    draft = create_draft_contract(
        customer["id"], contract_type="SEASONAL_RENTAL", season_year=2026,
        base_season_fee_cents=60000, early_bird_cutoff="2027-01-01T00:00:00Z")
    active = sign_contract(draft["id"])
    assert active["storage_included"] is False, active
    assert active["subtotal_cents"] == 60000, active
    assert active["discount_cents"] == 3000, active
    assert active["contract_price_cents"] == 57000, active


# ── Corner/entities/contract_invalid_enum_contract_type_returns_invalid_request

def test_contract_invalid_contract_type_enum_rejected(api):
    """PRD §2.8: "the system validates the request body itself: required fields must be
    present, enum fields must carry one of their allowed values, and integer fields must
    satisfy their declared bounds. A failure here is reported as `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/contract_invalid_enum_contract_type_returns_invalid_request
    """
    customer = create_customer(name="Enum Owner", service_address="103 Main St",
                               roofline_feet=110)
    resp = api.create_contract(create_contract_payload(
        customer["id"], contract_type="LEASE", season_year=2026,
        base_season_fee_cents=50000, early_bird_cutoff="2027-01-01T00:00:00Z"), SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ── Corner/state_machines/sign_non_draft_contract_returns_invalid_state ──────

def test_sign_already_active_contract_rejected(api):
    """PRD §3.1: "Signing a draft advances the contract from `DRAFT` to `ACTIVE` and is
    permitted only when the contract is currently in `DRAFT`; a sign attempt against any
    other state is rejected with `ERR_CONTRACT_NOT_SIGNABLE`."

    Design: Corner/state_machines/sign_non_draft_contract_returns_invalid_state
    """
    customer, active = setup_active_contract()
    resp = api.sign_contract(active["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_SIGNABLE.value, 409)


# ── Corner/errors/contract_renew_non_active_returns_not_renewable ────────────

def test_renew_draft_contract_rejected(api):
    """PRD §3.1: "A `SalesRep` may renew a contract only while it is `ACTIVE`; a renew
    attempt against any other state is rejected with `ERR_CONTRACT_NOT_RENEWABLE`."

    Design: Corner/errors/contract_renew_non_active_returns_not_renewable
    """
    customer = create_customer(name="Rnw Owner", service_address="123 Main St",
                               roofline_feet=100)
    draft = create_draft_contract(customer["id"])
    resp = api.renew_contract(draft["id"], renew_contract_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_RENEWABLE.value, 409)


# ── Corner/state_machines/renew_creates_child_contract ───────────────────────

def test_renew_active_contract_creates_next_season_draft(api):
    """PRD §3.1: "Renewal moves the prior contract from `ACTIVE` to `RENEWED` (a terminal
    state for it) and, as its side effect, creates a brand-new contract for the next
    season in `DRAFT` status whose `renewed_from_id` points back to the prior contract's
    `id` and which inherits the same `customer_id` and `contract_type`."

    Design: Corner/state_machines/renew_creates_child_contract
    """
    customer, active = setup_active_contract()
    new_contract = validate_success(
        api.renew_contract(active["id"], renew_contract_payload(
            season_year=2027, base_season_fee_cents=52000,
            early_bird_cutoff="2027-08-15T00:00:00Z"), SALES), 201)
    assert new_contract["renewed_from_id"] == active["id"], new_contract
    assert new_contract["status"] == "DRAFT", new_contract
    prior = validate_success(api.get_contract(active["id"], SALES), 200)
    assert prior["status"] == "RENEWED", prior


# ── Corner/endpoints/contracts_list_pagination_envelope ──────────────────────

def test_contracts_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, with a minimum accepted value of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes the following fields inside the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Two contracts exist; limit=1 returns one item, total_count 2, has_more true.

    Design: Corner/endpoints/contracts_list_pagination_envelope
    """
    customer = create_customer(name="Pag Owner", service_address="122 Main St",
                               roofline_feet=100)
    create_draft_contract(customer["id"], season_year=2026,
                          base_season_fee_cents=50000)
    create_draft_contract(customer["id"], season_year=2027,
                          base_season_fee_cents=52000,
                          early_bird_cutoff="2027-08-15T00:00:00Z")
    data, meta = validate_paginated(
        api.list_contracts(SALES, params={"customer_id": customer["id"],
                                          "limit": 1, "offset": 0}))
    assert len(data) == 1, data
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
