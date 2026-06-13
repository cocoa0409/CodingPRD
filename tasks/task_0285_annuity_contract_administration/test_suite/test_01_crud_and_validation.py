"""CRUD, input validation, computed/system fields, and FK existence.

Each test translates exactly one corner-design instance (queue B) and cites the
verbatim PRD sentence that uniquely determines the asserted outcome.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_product_payload, create_contract_payload, create_premium_payload,
    create_crediting_event_payload,
    assert_product, assert_contract, assert_crediting_event,
    setup_active_fixed_contract,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_product_returns_201_with_defaults(api):
    """PRD §3.1: "A product's `status` is `ACTIVE` when created".
    PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    res = api.create_product(create_product_payload(
        name="Fixed", contract_type="FIXED", fixed_annual_rate_bps=350,
        death_benefit_type="ACCOUNT_VALUE",
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        min_initial_premium_cents=1_000_000), ADMIN)
    product = validate_success(res, 201)
    assert_product(product)
    assert product["status"] == "ACTIVE", "new product starts ACTIVE"
    assert product["version"] == 1, "version starts at 1"
    assert product["contract_type"] == "FIXED"


def test_get_contract_returns_stored_entity(api):
    """PRD §3.2: "A `ContractAdmin` opens a **Contract** by naming the
    `product_id` of an `ACTIVE` product, the `owner_name`, and the
    `annuitant_age`".
    PRD §3.2: "The contract is born in `PENDING` status with an accumulation
    value of zero".

    Design: Corner/entities/get_contract_returns_stored_entity
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    created = validate_success(
        api.create_contract(create_contract_payload(product["id"], owner_name="Ada"), ADMIN), 201)
    retrieved = validate_success(api.get_contract(created["id"], ADMIN), 200)
    assert_contract(retrieved)
    assert retrieved["owner_name"] == "Ada"
    assert retrieved["product_id"] == product["id"]
    assert retrieved["status"] == "PENDING"


def test_list_contracts_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_contracts_paginated_envelope
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    api.create_contract(create_contract_payload(product["id"], owner_name="One"), ADMIN)
    api.create_contract(create_contract_payload(product["id"], owner_name="Two", annuitant_age=61), ADMIN)
    data, meta = validate_paginated(api.list_contracts(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_contract_nonexistent_returns_not_found(api):
    """PRD §2.8: "the server validates existence left to right and rejects the
    first identifier in the path that does not resolve to a live resource with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_contract_nonexistent_returns_not_found
    """
    res = api.get_contract(NONEXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_create_contract_missing_annuitant_age_invalid_request(api):
    """PRD §2.9: "Next comes shape and range validation of the payload —
    required scalar fields present and correctly typed ... which fails with
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.2: "the `annuitant_age`, which must be a whole number of years from
    0 through 85 inclusive."

    Design: Corner/entities/create_contract_missing_required_field_invalid_request
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    payload = {"product_id": product["id"], "owner_name": "NoAge"}
    res = api.create_contract(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_contract_annuitant_age_over_max_invalid_request(api):
    """PRD §3.2: "the `annuitant_age`, which must be a whole number of years
    from 0 through 85 inclusive."
    PRD §2.9: "integers within their stated ranges — which fails with
    `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_contract_annuitant_age_out_of_range_invalid_request
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    res = api.create_contract(
        create_contract_payload(product["id"], owner_name="TooOld", annuitant_age=86), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_product_contract_type_invalid_enum_rejected(api):
    """PRD §3.1: "a `contract_type` that is one of `FIXED`, `VARIABLE`, or
    `INDEXED`."
    PRD §2.9: "Next comes shape and range validation of the payload — required
    scalar fields present and correctly typed, enum values within their declared
    domains, and integers within their stated ranges — which fails with
    `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/product_contract_type_invalid_enum_rejected
    """
    payload = create_product_payload(name="Bad", contract_type="CRYPTO")
    # CRYPTO is outside the enum; fixed_annual_rate_bps is N/A for the rejection path.
    payload.pop("fixed_annual_rate_bps", None)
    res = api.create_product(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_premium_net_computed_from_load_input_ignored(api):
    """PRD §3.2: "the server computes its `net_premium_cents` as the gross
    amount multiplied by one minus the load fraction — that is,
    `gross_premium_cents` times the quantity one minus `premium_load_bps`
    divided by 10000 — rounded half up to a whole cent."
    PRD §3.2: "The net amount is added into both `accumulation_value_cents` and
    `cumulative_premium_cents`".

    Design: Corner/entities/premium_net_computed_from_load_input_ignored
    """
    product = validate_success(api.create_product(create_product_payload(
        min_initial_premium_cents=100_000), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    premium = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"],
        gross_premium_cents=1_000_000, premium_load_bps=250), ADMIN), 201)
    cleared = validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    assert cleared["net_premium_cents"] == 975000
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 975000


def test_system_fields_minted_by_server_on_product(api):
    """PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID,
    with no type prefix."
    PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."

    Design: Corner/entities/system_fields_minted_by_server_on_product
    """
    res = api.create_product(create_product_payload(), ADMIN)
    product = validate_success(res, 201)
    assert is_valid_uuid(product["id"]), "id must be a server-minted UUID"
    assert "_" not in product["id"], "id must have no type prefix"
    assert product["version"] == 1


def test_crediting_event_immutable_no_version_field(api):
    """PRD §2.4: "A `CreditingEvent` is an append-only ledger entry that is
    never modified after it is posted; it therefore carries only `id` and
    `created_at`, and has neither an `updated_at` nor a `version` field."
    PRD §3.3: "the credit is the contract's current `accumulation_value_cents`
    multiplied by the product's `fixed_annual_rate_bps` divided by 10000,
    rounded half up."

    Design: Corner/entities/crediting_event_immutable_no_version_field
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=350)
    event = validate_success(api.create_crediting_event(
        create_crediting_event_payload(contract["id"], "FIXED_GUARANTEED"), CREDITING), 201)
    retrieved = validate_success(api.get_crediting_event(event["id"], ADMIN), 200)
    assert_crediting_event(retrieved)
    assert retrieved["credit_cents"] == 70000


def test_contract_referenced_product_not_found(api):
    """PRD §2.8: "A foreign-key field carried in a request body — such as
    `contract_id`, `product_id` ... that points at a non-existent resource is
    instead rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/contract_referenced_product_not_found
    """
    res = api.create_contract(
        create_contract_payload("11111111-1111-4111-8111-111111111111"), ADMIN)
    validate_error(res, "ERR_REFERENCED_RESOURCE_NOT_FOUND", expected_status=404)


# NOTE: corner instance
# Corner/entities/premiums_filtered_list_by_source_exchange_fk is SKIPPED under the
# PRD-first filter (coverage / unique derivability). The asserted rule is that
# `GET /premiums?source_exchange_id={ex}` filters the premiums list down to the one
# funding premium. PRD prose never states that `GET /premiums` accepts a
# `source_exchange_id` query filter: §2.3 names only `limit`/`offset`, and the §4
# table row is the bare title "List premiums". A faithful PRD-only implementer could
# ship `GET /premiums` that ignores the unknown param and returns all premiums, so
# the filtering behavior is neither verbatim-covered nor uniquely derivable. Gap left
# as a gap.
