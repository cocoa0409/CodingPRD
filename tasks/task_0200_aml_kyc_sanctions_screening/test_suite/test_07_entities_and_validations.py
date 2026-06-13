"""Customer/account/UBO CRUD, structural validations, and auth."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_customer_payload, create_legal_entity_payload, create_account_payload,
    create_transaction_payload,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, build_user_headers,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]
AN = TEST_USERS["analyst_headers"]
SF = TEST_USERS["system_feed_headers"]


# ==========================================================================
# Queue B — entities (Customer creation, retrieval, listing)
# ==========================================================================
def test_create_customer_individual_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created customer begins life in `NEW` `cdd_status` with
    a null `risk_rating` and null `risk_score`."
    PRD §3.1: "The customer may also self-declare politically-exposed-person
    status through `is_pep_self_declared`, which defaults to false when omitted."
    PRD §2.4: "`version` — a system-managed integer that begins at its initial
    value on creation and increments by exactly one on every mutation".

    Design: Corner/entities/create_customer_individual_returns_201_with_defaults
    """
    cust = validate_success(api.create_customer(
        {"legal_name": "Jane Doe", "customer_type": "INDIVIDUAL",
         "country_code": "US", "date_of_birth": "1980-01-01"}, CO), 201)
    assert cust["cdd_status"] == "NEW"
    assert cust["risk_rating"] is None
    assert cust["is_pep_self_declared"] is False
    assert cust["version"] == 1


def test_get_customer_returns_stored_entity(api):
    """PRD §3.1: "Customers may be fetched individually or listed with pagination
    and an optional filter on `cdd_status`."

    Design: Corner/entities/get_customer_returns_stored_entity
    """
    cust = validate_success(api.create_customer(
        create_legal_entity_payload(legal_name="Read Me", country_code="GB",
                                    incorporation_date="2005-05-05"), CO), 201)
    fetched = validate_success(api.get_customer(cust["id"], AN))
    assert fetched["legal_name"] == "Read Me"
    assert fetched["country_code"] == "GB"


def test_list_customers_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Two customers, limit 1 -> total_count 2 and has_more true.

    Design: Corner/entities/list_customers_paginated_envelope
    """
    validate_success(api.create_customer(
        create_customer_payload(legal_name="C One", date_of_birth="1981-01-01"), CO), 201)
    validate_success(api.create_customer(
        create_customer_payload(legal_name="C Two", date_of_birth="1982-02-02"), CO), 201)
    data, meta = validate_paginated(api.list_customers(CO, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_customer_not_found_returns_404(api):
    """PRD §2.6: "The server validates the existence of every identifier in the
    path from left to right, rejecting the request with `ERR_NOT_FOUND` at the
    first path segment that does not resolve to an existing resource."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    validate_error(api.get_customer(NON_EXISTENT_UUID, CO), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_customer_missing_required_returns_invalid_request(api):
    """PRD §2.7: "then body well-formedness — required fields present, enum values
    valid, numeric ranges honored, types correct (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "A `ComplianceOfficer` or `PlatformAdmin` onboards one by supplying
    its `legal_name`, its `customer_type` — either `INDIVIDUAL` or `LEGAL_ENTITY`
    — and its `country_code`, a two-letter uppercase ISO country code."

    Missing legal_name -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_customer_missing_required_returns_invalid_request
    """
    validate_error(api.create_customer(
        {"customer_type": "INDIVIDUAL", "country_code": "US", "date_of_birth": "1980-01-01"}, CO),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_customer_invalid_enum_returns_invalid_request(api):
    """PRD §2.7: "then body well-formedness — required fields present, enum values
    valid, numeric ranges honored, types correct (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "its `customer_type` — either `INDIVIDUAL` or `LEGAL_ENTITY`".

    customer_type "PARTNERSHIP" is not a valid enum -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_customer_invalid_enum_customer_type_returns_invalid_request
    """
    validate_error(api.create_customer(
        {"legal_name": "Bad Enum", "customer_type": "PARTNERSHIP", "country_code": "US"}, CO),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_customer_type_field_mismatch(api):
    """PRD §3.1: "a `date_of_birth` is required when the customer is an
    `INDIVIDUAL` and must be null for a `LEGAL_ENTITY`, while an
    `incorporation_date` is required when the customer is a `LEGAL_ENTITY` and
    must be null for an `INDIVIDUAL`. Violating either conditional — supplying the
    wrong date field for the type, or omitting the required one — is rejected with
    `ERR_TYPE_FIELD_MISMATCH`."

    INDIVIDUAL with incorporation_date (and no DOB) -> ERR_TYPE_FIELD_MISMATCH.

    Design: Corner/entities/create_customer_type_field_mismatch_individual_with_incorporation_date
    """
    validate_error(api.create_customer(
        {"legal_name": "Mismatch", "customer_type": "INDIVIDUAL",
         "country_code": "US", "incorporation_date": "2000-01-01"}, CO),
        ApiErrorId.ERR_TYPE_FIELD_MISMATCH.value)


def test_system_fields_minted_input_ignored(api):
    """PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID,
    with no type prefix."
    PRD §2.4: "`version` — a system-managed integer that begins at its initial
    value on creation and increments by exactly one on every mutation of the
    resource."

    Design: Corner/entities/system_fields_generated_input_ignored
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Sys Fields", date_of_birth="1983-03-03"), CO), 201)
    assert cust["version"] == 1
    assert is_valid_uuid(cust["id"])


def test_account_requires_existing_customer(api):
    """PRD §2.6: "A request for the beneficial owners of a non-existent customer
    fails on the customer before the server ever considers the child collection."

    Opening an account under a non-existent customer -> ERR_NOT_FOUND.

    Design: Corner/entities/parent_relationship_account_requires_existing_customer
    """
    validate_error(api.create_account(
        NON_EXISTENT_UUID, create_account_payload(account_ref="AC-NOPARENT"), CO),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_alert_fk_integrity_account_and_customer(api):
    """PRD §3.7: "an alert carries its `account_id`, the denormalized
    `customer_id` of the owning customer (used for case routing)".

    A minted alert resolves to both its originating account and that account's
    owning customer.

    Design: Corner/entities/graph_topology_alert_fk_integrity_account_and_customer
    """
    cust = fx.create_legal_entity(legal_name="Graph Co", incorporation_date="2019-09-09")
    acct = fx.create_account(cust["id"], account_ref="AC-GRAPH-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-12T08:00:00Z", counterparty_country="US"), SF), 201)
    alerts, _ = fx._list(api.list_alerts(AN, params={"account_id": acct["id"]}))
    assert alerts[0]["account_id"] == acct["id"]
    assert alerts[0]["customer_id"] == cust["id"]


# ==========================================================================
# Queue B — validations
# ==========================================================================
def test_ubo_on_individual_returns_409(api):
    """PRD §3.4: "A beneficial owner may be added only to a `LEGAL_ENTITY`
    customer; attempting to add one to an `INDIVIDUAL` customer is rejected with
    `ERR_UBO_ON_INDIVIDUAL`."

    Design: Corner/validations/ubo_on_individual_returns_409
    """
    cust = fx.create_customer(legal_name="Ind Co", date_of_birth="1995-05-05")
    validate_error(api.create_beneficial_owner(
        cust["id"], {"full_name": "Owner X", "ownership_pct": 50.00, "country_code": "US"}, CO),
        ApiErrorId.ERR_UBO_ON_INDIVIDUAL.value)


def test_ubo_ownership_exceeds_100(api):
    """PRD §3.4: "the sum of `ownership_pct` across all of a customer's beneficial
    owners must never exceed 100.00 percent; an addition that would push the
    aggregate above that ceiling is rejected with `ERR_OWNERSHIP_EXCEEDS_100`."

    Two UBOs at 60.00% each: the second pushes aggregate to 120.00% -> rejected.

    Design: Corner/validations/ubo_ownership_exceeds_100_aggregate
    """
    cust = fx.create_legal_entity(legal_name="Own Co", incorporation_date="1997-07-07")
    validate_success(api.create_beneficial_owner(
        cust["id"], {"full_name": "Owner A", "ownership_pct": 60.00,
                     "country_code": "US", "is_control_person": True}, CO), 201)
    validate_error(api.create_beneficial_owner(
        cust["id"], {"full_name": "Owner B", "ownership_pct": 60.00, "country_code": "GB"}, CO),
        ApiErrorId.ERR_OWNERSHIP_EXCEEDS_100.value)


def test_pagination_invalid_limit_returns_422(api):
    """PRD §2.3: "A request whose `limit` falls outside 1 through 100, or whose
    `offset` is negative, is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/endpoints/pagination_invalid_limit_returns_422
    """
    validate_error(api.list_customers(CO, params={"limit": 0, "offset": 0}),
                   ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role`
    that is not one of the recognized roles, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    validate_error(api.list_customers({}), ApiErrorId.ERR_UNAUTHENTICATED.value)
