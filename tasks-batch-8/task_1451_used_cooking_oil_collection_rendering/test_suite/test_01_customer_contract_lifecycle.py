"""Customer onboarding and contract lifecycle tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_contract,
    create_contract_payload,
    create_customer,
    create_customer_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_customer_contact_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BILL, FOPS


# ---------------------------------------------------------------------------
# Corner: entities
# ---------------------------------------------------------------------------

def test_customer_creation_defaults(api, field_ops_headers):
    """PRD §3.1: "A newly registered customer starts in `PROSPECT` status, with
    `missed_pickup_count` at zero and `rebate_balance_cents` at zero."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    one with every modification to the resource"

    Design: Corner/entities/c_customer_creation_defaults
    """
    resp = api.create_customer(
        create_customer_payload(
            name="New Site", site_address="100 Grease Ln",
            site_max_container_gal=5000,
        ),
        field_ops_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PROSPECT"
    assert data["missed_pickup_count"] == 0
    assert data["rebate_balance_cents"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_customer_not_found_returns_404(api, field_ops_headers):
    """PRD §2.8: "third, existence — every resource identifier in the request
    path must exist (`ERR_NOT_FOUND`)"

    Design: Corner/entities/c_customer_not_found_returns_404
    """
    resp = api.get_customer("123e4567-e89b-42d3-a456-426614174000", field_ops_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_customer_computed_field_input_ignored(api, field_ops_headers):
    """PRD §3.1: "A newly registered customer starts in `PROSPECT` status, with
    `missed_pickup_count` at zero and `rebate_balance_cents` at zero."
    PRD §2.10: "Each customer carries an open rebate ledger balance,
    `rebate_balance_cents`, defined as the sum of `final_total_cents` across
    that customer's settlements currently in `FINALIZED` status"

    Design: Corner/entities/c_customer_computed_field_input_ignored
    """
    payload = create_customer_payload(
        name="Sneaky Site", site_address="101 Grease Ln",
        site_max_container_gal=5000,
    )
    payload["rebate_balance_cents"] = 999
    resp = api.create_customer(payload, field_ops_headers)
    data = validate_success(resp, expected_status=201)
    assert data["rebate_balance_cents"] == 0, (
        "client-supplied rebate_balance_cents must be ignored"
    )


def test_customers_list_pagination_envelope(api, field_ops_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and rejects values
    above the maximum of 100. The `offset` parameter specifies how many items
    to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the response
    envelope."

    Design: Corner/entities/c_customers_list_pagination_envelope
    """
    api.create_customer(
        create_customer_payload(name="P1", site_address="1 Pg Way",
                                site_max_container_gal=100),
        field_ops_headers,
    )
    api.create_customer(
        create_customer_payload(name="P2", site_address="2 Pg Way",
                                site_max_container_gal=100),
        field_ops_headers,
    )
    resp = api.list_customers(field_ops_headers)
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert resp.json()["response_type"] == "array"
    assert resp.json()["meta"]["api_request_id"]


# ---------------------------------------------------------------------------
# Corner: validations (auth / schema / role)
# ---------------------------------------------------------------------------

def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this declared set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/c_missing_auth_header_unauthenticated
    """
    resp = api.list_customers(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_driver_cannot_create_customer(api):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized role
    list, or that violates an ownership rule, is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /api/customers is authorized for "SystemAdmin, FieldOpsManager"
    only.

    Design: Corner/validations/c_driver_cannot_create_customer
    """
    from test_helpers import make_driver_headers

    resp = api.create_customer(
        create_customer_payload(name="Nope", site_address="0 No Way",
                                site_max_container_gal=100),
        make_driver_headers("drv-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_invalid_pricing_mode_rejected(api, field_ops_headers):
    """PRD §2.8: "fourth, request schema — required fields present, types valid,
    enum values within their declared sets, and numeric bounds such as container
    capacity and positive pump readings (`ERR_VALIDATION`)"
    PRD §3.2: "choosing a `pricing_mode` of `REBATE` or `SERVICE_FEE`"

    Design: Corner/validations/c_invalid_pricing_mode_rejected
    """
    customer = create_customer(name="Enum House", address="28 Fry Way")
    resp = api.create_contract(
        customer["id"],
        {
            "pricing_mode": "BOGUS",
            "index_code": "YG_CBI",
            "term_start": "2026-07-01",
            "term_end": "2027-07-01",
        },
        field_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


# ---------------------------------------------------------------------------
# Corner: terminal lockdown
# ---------------------------------------------------------------------------

def test_terminated_contract_activate_rejected(api, field_ops_headers):
    """PRD §2.8: "fifth, state-machine legality — the requested transition must
    be defined from the entity's current state, including terminal-state
    lockdown (`ERR_INVALID_STATE`)"
    PRD §3.2: "`TERMINATED_VOLUNTARY`, `TERMINATED_POACHED`, and `EXPIRED` are
    the contract's terminal states."

    Design: Corner/state_machines/c_terminated_contract_activate_rejected
    """
    set_clock("2026-07-01T09:00:00Z")
    customer = create_customer(name="TermLock", address="21 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    set_clock("2026-08-20T00:00:00Z")
    terminated = get_success_data(
        api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"}, field_ops_headers)
    )
    assert terminated["status"] == "TERMINATED_VOLUNTARY"

    resp = api.activate_contract(contract["id"], field_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_contract(contract["id"], field_ops_headers))
    assert after["status"] == "TERMINATED_VOLUNTARY"


# ---------------------------------------------------------------------------
# Difficulty: contract renewal offer cycle (2 tests share one scenario each)
# ---------------------------------------------------------------------------

def _renewal_cycle_setup(api):
    set_clock("2026-08-02T00:00:00Z")
    customer = create_customer(name="Cycle House", address="6 Fry Way")
    contract = create_contract(
        customer["id"],
        activate=True,
        term_start="2026-01-01",
        term_end="2026-12-31",
    )
    return customer, contract


def test_renewal_accept_adopts_offered_term(api, field_ops_headers):
    """PRD §3.2: "Acceptance replaces `term_start` and `term_end` with the
    offered values, clears the offered fields and `status_before_renewal`, and
    returns the contract to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/contract_renewal_offer_cycle
    """
    customer, contract = _renewal_cycle_setup(api)
    get_success_data(
        api.offer_renewal(
            contract["id"],
            {"new_term_start": "2027-01-01", "new_term_end": "2027-12-31"},
            field_ops_headers,
        )
    )
    accepted = get_success_data(
        api.respond_renewal(
            contract["id"], {"accept": True},
            make_customer_contact_headers(customer["id"]),
        )
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["term_end"] == "2027-12-31"
    assert accepted["term_start"] == "2027-01-01"


def test_renewal_reject_restores_prior_term_and_version(api, field_ops_headers):
    """PRD §3.2: "Rejection clears the offered fields, leaves the existing term
    unchanged, and returns the contract to the status remembered in
    `status_before_renewal` — `ACTIVE` when the offer was made from `ACTIVE`"
    PRD §3.2: "The `ACTIVE` → `RENEWAL_OFFERED` → `ACTIVE` loop may repeat
    indefinitely."

    Design: Difficulty/non_linear_state_machine/contract_renewal_offer_cycle
    """
    customer, contract = _renewal_cycle_setup(api)
    # Lap 1: offer + accept (term moves to 2027).
    get_success_data(
        api.offer_renewal(
            contract["id"],
            {"new_term_start": "2027-01-01", "new_term_end": "2027-12-31"},
            field_ops_headers,
        )
    )
    get_success_data(
        api.respond_renewal(
            contract["id"], {"accept": True},
            make_customer_contact_headers(customer["id"]),
        )
    )
    # Lap 2: offer + reject (term stays at the 2027 window).
    get_success_data(
        api.offer_renewal(
            contract["id"],
            {"new_term_start": "2028-01-01", "new_term_end": "2028-12-31"},
            field_ops_headers,
        )
    )
    rejected = get_success_data(
        api.respond_renewal(
            contract["id"], {"accept": False},
            make_customer_contact_headers(customer["id"]),
        )
    )
    assert rejected["status"] == "ACTIVE"
    assert rejected["term_end"] == "2027-12-31", (
        "rejection must not apply the 2028 offer"
    )
    # create 1, activate 2, offer 3, accept 4, offer 5, reject 6
    assert rejected["version"] == 6


# ---------------------------------------------------------------------------
# Difficulty: contract term half-open adjacency
# ---------------------------------------------------------------------------

def _adjacency_setup(api):
    set_clock("2026-02-01T00:00:00Z")
    customer = create_customer(name="Overlap House", address="16 Fry Way")
    contract1 = create_contract(
        customer["id"],
        activate=True,
        term_start="2026-01-01",
        term_end="2026-07-01",
    )
    return customer, contract1


def test_adjacent_contract_term_accepted(api, field_ops_headers):
    """PRD §3.2: "Because windows are half-open, adjacency is allowed: a new
    contract whose `term_start` equals an existing contract's `term_end` does
    not overlap it."

    Design: Difficulty/resource_temporal_overlap/contract_term_half_open_adjacency
    """
    customer, _ = _adjacency_setup(api)
    resp = api.create_contract(
        customer["id"],
        create_contract_payload(term_start="2026-07-01", term_end="2027-01-01"),
        field_ops_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["term_start"] == "2026-07-01"


def test_overlapping_contract_term_rejected(api, field_ops_headers):
    """PRD §3.2: "One customer's non-terminal contracts may never have
    overlapping term windows."
    PRD §3.2: "The check runs both when a contract is drafted and when it is
    activated, and a violation is rejected with `ERR_CONTRACT_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_term_half_open_adjacency
    """
    customer, _ = _adjacency_setup(api)
    resp = api.create_contract(
        customer["id"],
        create_contract_payload(term_start="2026-06-30", term_end="2026-12-01"),
        field_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_TERM_OVERLAP, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: OCC on contract amend
# ---------------------------------------------------------------------------

def _occ_contract_setup(api):
    set_clock("2026-08-02T00:00:00Z")
    customer = create_customer(name="OCC House", address="46 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    observed = get_success_data(api.get_contract(contract["id"], FOPS))
    return customer, contract, observed["version"]


def test_contract_amend_with_current_version_succeeds(api, field_ops_headers):
    """PRD §2.7: "Amending a contract requires the request to carry
    `expected_contract_version` equal to the contract's current `version`."
    PRD §3.2: "Amending an `ACTIVE` contract updates rate fields in place as an
    `ACTIVE` → `ACTIVE` self-transition."

    Design: Corner/cross_cutting_layers/c_occ_stale_contract_amend_412
    """
    _, contract, observed_version = _occ_contract_setup(api)
    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": observed_version, "cap_cents_per_gal": 140},
        field_ops_headers,
    )
    data = validate_success(resp, expected_status=200)
    assert data["version"] == observed_version + 1
    assert data["cap_cents_per_gal"] == 140
    assert data["status"] == "ACTIVE"


def test_contract_amend_with_stale_version_rejected(api, field_ops_headers):
    """PRD §2.7: "If another writer has advanced the contract's version since
    the client last read it — each amendment legitimately supersedes the prior
    rate schedule — the amend is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_layers/c_occ_stale_contract_amend_412
    """
    _, contract, observed_version = _occ_contract_setup(api)
    first = get_success_data(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": observed_version, "cap_cents_per_gal": 140},
            field_ops_headers,
        )
    )
    assert first["cap_cents_per_gal"] == 140
    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": observed_version, "cap_cents_per_gal": 130},
        field_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = get_success_data(api.get_contract(contract["id"], field_ops_headers))
    assert after["cap_cents_per_gal"] == 140, "loser's write must not be applied"
