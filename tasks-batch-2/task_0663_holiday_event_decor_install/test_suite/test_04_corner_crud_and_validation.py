"""Breadth queue B — entities, validations, endpoints, errors, and RBAC corners.

One test per non-stub corner-design instance. Stubs with excluded_because: are owned by the
cited difficulty instance and are NOT translated here.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    build_user_headers,
    NON_EXISTENT_UUID,
    create_client_payload,
    create_contract_payload,
    create_inventory_item_payload,
    create_design_proposal_payload,
    create_line_item_payload,
    create_storage_bay_payload,
    create_storage_lot_payload,
    create_client,
    create_draft_contract,
    create_inventory_item,
    create_storage_bay,
    setup_active_contract,
    make_client_contact_headers,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# =====================================================================
# Entities
# =====================================================================
def test_create_client_returns_201_with_system_fields():
    """PRD §3.1: "A new client is born with `status` set to `ACTIVE`; the account `status` has
    no further lifecycle transitions in this system and remains `ACTIVE`."

    Design: Corner/entities/create_client_returns_201_with_system_fields
    """
    res = api_client.create_client(create_client_payload(legal_name="Tango Co"), AM)
    client = validate_success(res, 201)
    assert client["status"] == "ACTIVE"
    assert client["version"] == 1


def test_get_contract_nonexistent_returns_not_found():
    """PRD §2.5: "The system validates path identifiers left to right and rejects the request
    with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve
    to an existing resource."

    Design: Corner/entities/get_contract_nonexistent_returns_not_found
    """
    res = api_client.get_contract(NON_EXISTENT_UUID, AM)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_create_contract_missing_required_field_returns_invalid_request():
    """PRD §2.6: "required body fields must be present and well-typed, every enum value must
    fall within its allowed set, and numeric constraints must hold ... any violation yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_contract_missing_required_field_returns_invalid_request
    """
    client = create_client(account_type="COMMERCIAL")
    payload = {"season_year": 2026, "early_bird_deadline": "2026-03-01T00:00:00Z"}
    res = api_client.create_contract(client["id"], payload, AM)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_create_contract_default_surcharge_zero_applied():
    """PRD §3.1: "optionally a `custom_design_surcharge_cents` flat surcharge for bespoke work
    (defaulting to 0, and never negative)."

    Design: Corner/entities/create_contract_default_surcharge_zero_applied
    """
    client = create_client(account_type="COMMERCIAL")
    res = api_client.create_contract(
        client["id"], create_contract_payload(contract_type="COMMERCIAL"), AM)
    contract = validate_success(res, 201)
    assert contract["custom_design_surcharge_cents"] == 0


def test_create_client_bad_enum_account_type_returns_invalid_request():
    """PRD §2.6: "required body fields must be present and well-typed, every enum value must
    fall within its allowed set, and numeric constraints must hold ... any violation yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_contract_bad_enum_account_type_returns_invalid_request
    """
    res = api_client.create_client(
        create_client_payload(legal_name="Whiskey Co", account_type="LUXURY"), AM)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_storage_lot_released_on_not_after_stored_from_returns_invalid_request():
    """PRD §2.6: "a storage lot's `released_on` strictly after its `stored_from`; any violation
    yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/storage_lot_released_on_not_after_stored_from_returns_invalid_request
    """
    client = create_client(account_type="COMMERCIAL")
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    bay = create_storage_bay(bay_code="BAY-X-CORN", capacity_units=50)
    res = api_client.create_storage_lot(
        create_storage_lot_payload(contract["id"], bay["id"], unit_count=10,
                                   stored_from="2027-01-01T00:00:00Z",
                                   released_on="2027-01-01T00:00:00Z"), FS)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_line_item_reverse_reachable_by_inventory_item():
    """PRD §4 (Endpoint Definitions): GET `/inventory-items/{id}/proposal-line-items` "List
    line items referencing this SKU".

    Design: Corner/entities/line_item_reverse_reachable_by_inventory_item
    """
    client = create_client(account_type="COMMERCIAL")
    item = create_inventory_item(sku="TREE-Y-CORN", on_hand_qty=10)
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal = get_success_data(api_client.create_design_proposal(
        contract["id"], create_design_proposal_payload(theme="T"), AM))
    line = get_success_data(api_client.create_line_item(
        proposal["id"], create_line_item_payload(item["id"], quantity=3, unit_install_cents=5000), AM))
    data, _meta = validate_paginated(api_client.list_item_proposal_line_items(item["id"], AM))
    assert len(data) == 1
    assert data[0]["id"] == line["id"]


# =====================================================================
# Validations
# =====================================================================
def test_contract_type_mismatch_returns_error():
    """PRD §3.1: "The `contract_type` must equal the owning client's `account_type`; a mismatch
    is rejected with `ERR_CONTRACT_TYPE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/contract_type_mismatch_returns_error
    """
    client = create_client(account_type="COMMERCIAL")
    res = api_client.create_contract(
        client["id"], create_contract_payload(contract_type="HOA"), AM)
    validate_error(res, "ERR_CONTRACT_TYPE_MISMATCH", 422)


def test_duplicate_sku_returns_error():
    """PRD §3.8: "Each is created with a `sku` code (unique across the catalog; a collision is
    rejected with `ERR_DUPLICATE_CODE`)."

    Design: Corner/validations/duplicate_sku_returns_error
    """
    get_success_data(api_client.create_inventory_item(
        create_inventory_item_payload(sku="DUP-1", category="TREE", unit_replacement_cents=9000), PA))
    res = api_client.create_inventory_item(
        create_inventory_item_payload(sku="DUP-1", category="WREATH", unit_replacement_cents=8000), PA)
    validate_error(res, "ERR_DUPLICATE_CODE", 409)


def test_proposal_accept_when_sibling_already_accepted_returns_already_decided():
    """PRD §3.2: "Acceptance advances `SUBMITTED` to `ACCEPTED` and requires the proposal to be
    `SUBMITTED`, the owning contract to be `PROPOSED`, and no sibling proposal under the same
    contract to already be `ACCEPTED`; if the contract is not `PROPOSED` or a sibling has
    already been accepted, the request is rejected with `ERR_PROPOSAL_ALREADY_DECIDED`
    (HTTP 409)."

    Design: Corner/validations/proposal_accept_when_sibling_already_accepted_returns_already_decided
    """
    client = create_client(account_type="COMMERCIAL")
    item = create_inventory_item(sku="TREE-M2-CORN", on_hand_qty=10)
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal_a = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan A"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_a["id"], create_line_item_payload(item["id"], quantity=4, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_a["id"], AM))
    proposal_b = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan B"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_b["id"], create_line_item_payload(item["id"], quantity=6, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_b["id"], AM))
    proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
    cc = make_client_contact_headers(client["id"])
    get_success_data(api_client.accept_proposal(
        proposal_a["id"], {"expected_contract_version": proposed["version"]}, cc))
    # B was superseded by A's acceptance. Carry the contract's *current* version so the
    # OCC guard (priority 7) passes and the request reaches the proposal-decision layer.
    # Under §2.6 the state-machine guard (priority 8) precedes the business rule
    # (ERR_PROPOSAL_ALREADY_DECIDED): a superseded loser may surface as ERR_INVALID_STATE
    # before the sibling-already-accepted business rule is consulted.
    current = get_success_data(api_client.get_contract(contract["id"], AM))
    res = api_client.accept_proposal(
        proposal_b["id"], {"expected_contract_version": current["version"]}, cc)
    validate_error_is_one_of(res, ["ERR_PROPOSAL_ALREADY_DECIDED", "ERR_INVALID_STATE"])


def test_body_fk_reference_not_found():
    """PRD §2.5: "every foreign-key reference carried in the body — a `client_id`,
    `contract_id`, `proposal_id`, `inventory_item_id`, `storage_bay_id`, `crew_id`,
    `work_order_id`, or `damage_report_id` — must point to a resource that exists; a dangling
    body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/body_fk_reference_not_found
    """
    client = create_client(account_type="COMMERCIAL")
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "T"}, AM))
    res = api_client.create_line_item(
        proposal["id"],
        {"inventory_item_id": NON_EXISTENT_UUID, "quantity": 3, "unit_install_cents": 5000},
        AM)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", 404)


# =====================================================================
# Endpoints
# =====================================================================
def test_list_contracts_pagination_envelope():
    """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_contracts_pagination_envelope
    """
    client = create_client(account_type="COMMERCIAL")
    create_draft_contract(client["id"], contract_type="COMMERCIAL")
    res = api_client.list_client_contracts(client["id"], AM)
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# =====================================================================
# Errors (OCC stale-version)
# =====================================================================
def test_stale_contract_version_on_renewal_offer_create():
    """PRD §2.7: "The second guarded write is renewal-offer creation against a contract: the
    first creation advances the contract's `version` as it moves the contract into its
    renewal-offered posture, so a later creation carrying the stale
    `expected_contract_version` is likewise rejected."

    Design: Corner/errors/stale_contract_version_on_renewal_offer_create
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-P2-CORN", sku_overrides={"on_hand_qty": 10},
        line_quantity=4, unit_install_cents=5000)
    active = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
    observed_version = active["version"]
    # First create succeeds and bumps the contract version.
    get_success_data(api_client.create_renewal_offer(
        ctx["contract_id"],
        {"expires_at": "2026-12-31T00:00:00Z", "expected_contract_version": observed_version},
        AM))
    # Second create carrying the now-stale version is rejected.
    res = api_client.create_renewal_offer(
        ctx["contract_id"],
        {"expires_at": "2026-12-31T00:00:00Z", "expected_contract_version": observed_version},
        AM)
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", 412)


def test_stale_contract_version_on_proposal_accept():
    """PRD §2.7: "Accepting a `DesignProposal` advances the owning contract's `version` as it
    supersedes the sibling proposals; a subsequent acceptance that still carries the
    now-outdated `expected_contract_version` is rejected on the stale-version check rather than
    allowed to act on a contract it has not re-observed."

    Design: Corner/errors/stale_contract_version_on_proposal_accept
    """
    client = create_client(account_type="COMMERCIAL")
    item = create_inventory_item(sku="TREE-Q2-CORN", on_hand_qty=10)
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal_a = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan A"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_a["id"], create_line_item_payload(item["id"], quantity=4, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_a["id"], AM))
    proposal_b = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan B"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_b["id"], create_line_item_payload(item["id"], quantity=6, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_b["id"], AM))
    proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
    cc = make_client_contact_headers(client["id"])
    get_success_data(api_client.accept_proposal(
        proposal_a["id"], {"expected_contract_version": proposed["version"]}, cc))
    # Accepting A advanced the contract's version (PRD §2.7); accept B carrying the
    # now-outdated version observed before that acceptance is rejected on OCC (priority 7),
    # which precedes the state-machine guard.
    res = api_client.accept_proposal(
        proposal_b["id"], {"expected_contract_version": proposed["version"]}, cc)
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", 412)


# =====================================================================
# RBAC
# =====================================================================
def test_field_supervisor_cannot_create_client():
    """PRD §2.1: "A syntactically authenticated request whose role is not permitted to perform
    the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/field_supervisor_cannot_create_client
    """
    res = api_client.create_client(create_client_payload(legal_name="Romeo2 Co"), FS)
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


def test_wrong_client_contact_cannot_sign_other_clients_contract():
    """PRD §2.1: "For each such action the system resolves the `Client` that owns the targeted
    `Contract`, `DesignProposal`, or `RenewalOffer` (following `client_id` and the
    `contract_id` chain) and compares that owning client's `id` to `X-User-ID`. A mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/wrong_client_contact_cannot_sign_other_clients_contract
    """
    client_a = create_client(account_type="COMMERCIAL", legal_name="Sierra2 A")
    client_b = create_client(account_type="COMMERCIAL", legal_name="Sierra2 B")
    item = create_inventory_item(sku="TREE-S2-CORN", on_hand_qty=10)
    contract = create_draft_contract(client_a["id"], contract_type="COMMERCIAL")
    proposal = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "T"}, AM))
    get_success_data(api_client.create_line_item(
        proposal["id"], create_line_item_payload(item["id"], quantity=4, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal["id"], AM))
    proposed = get_success_data(api_client.propose_contract(client_a["id"], contract["id"], AM))
    cc_a = make_client_contact_headers(client_a["id"])
    get_success_data(api_client.accept_proposal(
        proposal["id"], {"expected_contract_version": proposed["version"]}, cc_a))
    # Client B's contact attempts to sign Client A's contract.
    cc_b = make_client_contact_headers(client_b["id"])
    res = api_client.sign_contract(client_a["id"], contract["id"], cc_b)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", 403)


def test_unknown_role_returns_unauthenticated():
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that is not one
    of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    res = api_client.list_clients(build_user_headers("nobody-1", "Nobody"))
    validate_error(res, "ERR_UNAUTHENTICATED", 401)
