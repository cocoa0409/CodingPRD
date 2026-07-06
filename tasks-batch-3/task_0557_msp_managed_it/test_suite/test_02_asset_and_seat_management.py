"""Assets, seat assignment/unassignment, seat adjustments, and the compensating
invariants that keep seat and credit accounting drift-free."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_client,
    create_site,
    create_contract,
    activate_contract,
    create_asset,
    assign_asset_to_contract,
    unassign_asset,
    create_seat_adjustment,
    setup_active_contract,
    setup_assigned_asset,
    create_procurement_order,
    place_procurement_order,
    cancel_procurement_order,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue B: entities / asset_system_fields_ignored_on_create
# ---------------------------------------------------------------------------
# PRD §3.3 states the create defaults verbatim; the assertion only reads those
# defaults from the response, so this is uniquely derivable.

def test_asset_create_defaults_monitoring_status_and_patch_compliance(api):
    """PRD §3.3: "A new asset opens with `monitoring_status` `UNMONITORED`, a
    null `contract_id`, and a `patch_compliance_pct` of 100.0."

    Design: Corner/entities/asset_system_fields_ignored_on_create
    """
    client = create_client(company_name="Gamma", primary_contact_email="g@gamma.test")
    site = create_site(client["id"])
    resp = api.create_asset(
        {"client_id": client["id"], "site_id": site["id"],
         "asset_type": "LAPTOP", "hostname": "l1"},
        TEST_USERS[SM],
    )
    data = validate_success(resp, expected_status=201)
    assert data["monitoring_status"] == "UNMONITORED"
    assert data["patch_compliance_pct"] == 100.0


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / seat_availability_conserved_assign_unassign
# ---------------------------------------------------------------------------

def test_asset_assign_decrements_seats_available(api):
    """PRD §3.3: "On success the asset moves `UNMONITORED` → `ACTIVE`, its
    `contract_id` is set to the target, the contract's `seats_available` is
    recomputed (falling by one as the newly active asset is now counted), and
    the asset's `version` increments by one."

    Design: Difficulty/compensating_invariant/seat_availability_conserved_assign_unassign
    """
    client, site, contract, asset = setup_assigned_asset(seat_count=5)
    # After assign, seats_available must be 4 (5 - 1 ACTIVE assigned asset).
    contract_after = validate_success(
        api.get_contract(contract["id"], TEST_USERS[SM])
    )
    assert contract_after["seats_available"] == 4


def test_asset_unassign_restores_seats_available_with_no_drift(api):
    """PRD §3.3: "The asset moves `ACTIVE` → `UNMONITORED`, its `contract_id`
    is cleared to null, the contract's `seats_available` is recomputed (rising
    by one, compensating the earlier assignment), and the asset's `version`
    increments by one."

    Design: Difficulty/compensating_invariant/seat_availability_conserved_assign_unassign
    """
    client, site, contract, asset = setup_assigned_asset(seat_count=5)
    unassign_asset(asset["id"])
    contract_after = validate_success(
        api.get_contract(contract["id"], TEST_USERS[SM])
    )
    assert contract_after["seats_available"] == 5
    # seats_available now equals seat_count — no drift.
    assert contract_after["seats_available"] == contract_after["seat_count"]


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / client_credit_conserved_place_cancel
# ---------------------------------------------------------------------------

def test_place_order_debits_credit_available_by_total_cents(api):
    """PRD §3.7: "On success the order moves `DRAFT` → `PLACED` and the client's
    `credit_available_cents` is recomputed, debited by `total_cents`."

    Design: Difficulty/compensating_invariant/client_credit_conserved_place_cancel
    """
    client = create_client(
        company_name="Sig", primary_contact_email="s@sig.test",
        credit_limit_cents=1_000_000,
    )
    # PRD §3.7 pins per-line rounding: round(333*1.10)=366 + round(334*1.10)=367 = 733.
    order = create_procurement_order(
        client["id"],
        line_items=[
            {"description": "cable", "unit_price_cents": 333, "qty": 1},
            {"description": "clip", "unit_price_cents": 334, "qty": 1},
        ],
        tax_rate=0.10,
    )
    assert order["total_cents"] == 733
    place_procurement_order(order["id"])
    client_after = validate_success(api.get_client(client["id"], TEST_USERS[SM]))
    assert client_after["credit_available_cents"] == 1_000_000 - 733


def test_cancel_placed_order_refunds_credit_with_no_drift(api):
    """PRD §3.7: "Cancelling moves the order to `CANCELLED`, and if it had been
    `PLACED`, the client's `credit_available_cents` is recomputed, refunding
    `total_cents` and compensating the earlier debit."

    Design: Difficulty/compensating_invariant/client_credit_conserved_place_cancel
    """
    client = create_client(
        company_name="Sig2", primary_contact_email="s2@sig.test",
        credit_limit_cents=1_000_000,
    )
    order = create_procurement_order(
        client["id"],
        line_items=[
            {"description": "cable", "unit_price_cents": 333, "qty": 1},
            {"description": "clip", "unit_price_cents": 334, "qty": 1},
        ],
        tax_rate=0.10,
    )
    place_procurement_order(order["id"])
    cancel_procurement_order(order["id"])
    client_after = validate_success(api.get_client(client["id"], TEST_USERS[SM]))
    assert client_after["credit_available_cents"] == 1_000_000
    assert client_after["credit_available_cents"] == client_after["credit_limit_cents"]


# ---------------------------------------------------------------------------
# Queue B: validations / seat_adjustment_below_assigned_floor_returns_422
# ---------------------------------------------------------------------------

def test_seat_adjustment_below_assigned_floor_returns_seat_floor_violation(api):
    """PRD §3.2: "if applying the `delta` would push `seat_count` below the
    number of assets currently assigned to the contract with `monitoring_status`
    `ACTIVE`, it is rejected with `ERR_SEAT_FLOOR_VIOLATION`."

    Design: Corner/validations/seat_adjustment_below_assigned_floor_returns_422
    """
    client, site, contract, asset = setup_assigned_asset(seat_count=1)
    # After assign, contract.version has advanced; refresh via GET to capture it.
    current = validate_success(api.get_contract(contract["id"], TEST_USERS[SM]))
    resp = api.create_seat_adjustment(
        contract["id"],
        {"delta": -1, "effective_at": "2026-05-02T00:00:00Z",
         "expected_contract_version": current["version"]},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_FLOOR_VIOLATION)


# ---------------------------------------------------------------------------
# Queue B: validations / no_seats_available_on_assign_returns_422
# ---------------------------------------------------------------------------

def test_assign_asset_when_no_seats_available_returns_no_seats_available(api):
    """PRD §3.3: "the contract must have at least one free seat — its
    `seats_available` must be greater than zero, otherwise `ERR_NO_SEATS_AVAILABLE`."

    Design: Corner/validations/no_seats_available_on_assign_returns_422
    """
    client, site, contract, asset1 = setup_assigned_asset(seat_count=1)
    # A second UNMONITORED asset for the same client/site.
    asset2 = create_asset(client["id"], site["id"], asset_type="DESKTOP", hostname="pc2")
    resp = api.assign_contract_to_asset(
        asset2["id"], {"contract_id": contract["id"]}, TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEATS_AVAILABLE)


# ---------------------------------------------------------------------------
# Queue B: validations / seat_adjustment_zero_delta_returns_422
# ---------------------------------------------------------------------------

def test_seat_adjustment_zero_delta_returns_invalid_seat_delta(api):
    """PRD §3.2: "The `delta` must be non-zero; a zero delta is rejected with
    `ERR_INVALID_SEAT_DELTA`."

    Design: Corner/validations/seat_adjustment_zero_delta_returns_422
    """
    client, contract = setup_active_contract()
    resp = api.create_seat_adjustment(
        contract["id"],
        {"delta": 0, "effective_at": "2026-05-02T00:00:00Z",
         "expected_contract_version": contract["version"]},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SEAT_DELTA)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / patch_create_requires_monitored_asset
# ---------------------------------------------------------------------------

def test_patch_job_on_unmonitored_asset_returns_asset_not_monitored(api):
    """PRD §3.4: "The asset must be actively monitored: scheduling a patch job
    on an asset whose `monitoring_status` is not `ACTIVE` is rejected with
    `ERR_ASSET_NOT_MONITORED`."

    Design: Difficulty/cross_entity_state_dependency/patch_create_requires_monitored_asset
    """
    client, contract = setup_active_contract()
    site = create_site(client["id"])
    asset = create_asset(client["id"], site["id"], asset_type="SERVER", hostname="srv-01")
    resp = api.create_patch_job(
        asset["id"],
        {"window_start": "2026-05-05T00:00:00Z",
         "window_end": "2026-05-05T01:00:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_MONITORED)


def test_patch_job_after_assign_contract_succeeds(api):
    """PRD §3.4: "A `Dispatcher` or `Technician` schedules one on an asset by
    supplying a maintenance window: a `window_start` (inclusive) and a
    `window_end` (exclusive)"
    PRD §3.4: "A newly scheduled patch job opens in `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/patch_create_requires_monitored_asset
    """
    client, site, contract, asset = setup_assigned_asset()
    resp = api.create_patch_job(
        asset["id"],
        {"window_start": "2026-05-05T00:00:00Z",
         "window_end": "2026-05-05T01:00:00Z"},
        TEST_USERS["dispatcher_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / ticket_create_requires_active_contract
# ---------------------------------------------------------------------------

def test_ticket_create_on_draft_contract_returns_contract_not_active(api):
    """PRD §3.5: "The governing contract must be `ACTIVE`; opening a ticket
    against a contract that is not `ACTIVE` is rejected with
    `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_active_contract
    """
    client = create_client(company_name="Nu", primary_contact_email="n@nu.test")
    contract = create_contract(client["id"])
    # contract is DRAFT; not activated.
    resp = api.create_ticket(
        {"client_id": client["id"], "contract_id": contract["id"],
         "priority": "P3", "subject": "early"},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


def test_ticket_create_after_activation_succeeds_in_new_status(api):
    """PRD §3.5: "A new ticket opens in `NEW`, with its `owner_technician_id`,
    `first_response_at`, and `resolved_at` all null."

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_active_contract
    """
    client, contract = setup_active_contract()
    resp = api.create_ticket(
        {"client_id": client["id"], "contract_id": contract["id"],
         "priority": "P3", "subject": "later"},
        TEST_USERS[SM],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "NEW"
    assert data["owner_technician_id"] is None
    assert data["first_response_at"] is None
    assert data["resolved_at"] is None
