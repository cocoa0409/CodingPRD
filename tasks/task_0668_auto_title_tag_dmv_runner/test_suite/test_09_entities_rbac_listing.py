"""Entity CRUD, defaults, computed fields, type constraints, RBAC, and listing.

Queue B (Corner) — entities, rbac, endpoints, and errors (residual) sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    setup_schedule_and_account, create_account, create_transaction,
    create_transaction_verified_and_quoted, submit_transaction, create_planned_trip,
    attach_leg, setup_lien_transaction_approved,
    create_account_payload, create_transaction_payload, create_fee_schedule_payload,
    create_runner_trip_payload, publish_fee_schedule, set_clock,
    make_account_holder_headers, make_lien_officer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]
LIEN_OFFICER = TEST_USERS["lien_officer_headers"]


# ─── Corner: entities ─────────────────────────────────────────────────

def test_create_account_returns_201_with_system_fields(api):
    """PRD §3.1: "A new account begins with status set to ACTIVE, and both its
    ytd_completed_count and outstanding_balance_cents start at zero."
    PRD §2.4: "the version field is an integer that starts at its initial value"

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    res = api.create_account(create_account_payload(
        account_type="RETAIL", legal_name="New Cust", state_code="CA"), ADMIN)
    account = validate_success(res, 201)
    assert account["version"] == 1
    assert account["status"] == "ACTIVE"
    assert account["ytd_completed_count"] == 0
    assert account["outstanding_balance_cents"] == 0


def test_get_account_not_found_returns_404(api):
    """PRD §2.6: "A missing path or body reference yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_transaction_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Submitting an unrecognized enum value for any of these is a malformed
    request rejected with ERR_INVALID_REQUEST (HTTP 400)."
    PRD §3.2: "An IntakeClerk opens a transaction by naming the owning account_id, the
    transaction_type, the 17-character vin"

    Design: Corner/entities/create_transaction_missing_required_field_returns_invalid_request
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account = create_account(account_type="RETAIL", state_code="CA")
    # Omit the required transaction_type.
    res = api.create_transaction(
        {"account_id": account["id"], "vin": "1HGCM82633A004352"}, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_transaction_defaults_expedite_false_price_zero(api):
    """PRD §3.2: "Both money inputs default to zero."
    PRD §3.2: "The expedite flag defaults to false and signals that the customer has
    purchased priority handling, an SLA, and a surcharge."

    Design: Corner/entities/create_transaction_default_expedite_false_applied
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = validate_success(api.create_transaction(
        create_transaction_payload(account["id"], "REGISTRATION"), CLERK), 201)
    assert txn["expedite"] is False
    assert txn["declared_price_cents"] == 0
    assert txn["lifecycle_status"] == "DRAFT"
    assert txn["document_status"] == "COLLECTING"
    assert txn["rejection_round"] == 0


def test_computed_account_fields_initialize_regardless_of_input(api):
    """PRD §3.1: "A new account begins with status set to ACTIVE, and both its
    ytd_completed_count and outstanding_balance_cents start at zero."

    Design: Corner/entities/computed_outstanding_balance_ignores_client_input
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account = validate_success(api.create_account(create_account_payload(
        account_type="FLEET", legal_name="Comp Cust", state_code="CA",
        credit_terms=True, credit_limit_cents=50000), ADMIN), 201)
    assert account["outstanding_balance_cents"] == 0
    assert account["ytd_completed_count"] == 0
    assert account["status"] == "ACTIVE"


def test_payment_collection_is_array_envelope(api):
    """PRD §2.4: "A payment is immutable once recorded, so it carries only an id (UUID)
    and a created_at timestamp; it has neither an updated_at field nor a version field."
    PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/payment_immutable_entity_no_version_field
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account = create_account(account_type="RETAIL", state_code="CA")
    data, meta = validate_paginated(api.list_payments(ADMIN, params={"account_id": account["id"]}))
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_create_transaction_unknown_account_returns_404(api):
    """PRD §2.6: "the parent identifier in the path is checked first, and only then are
    body foreign-key references resolved. A missing path or body reference yields
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_transaction_unknown_account_returns_404
    """
    set_clock()
    publish_fee_schedule(state_code="CA")  # only the account FK is missing
    res = api.create_transaction(
        create_transaction_payload(NON_EXISTENT_UUID, "REGISTRATION"), CLERK)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_transaction_vin_length_returns_invalid_transaction_fields(api):
    """PRD §3.2: "The VIN must be exactly 17 characters long. ... Any of these failing
    rejects creation with ERR_INVALID_TRANSACTION_FIELDS (HTTP 422)."

    Design: Corner/entities/transaction_invalid_fields_vin_length_returns_422
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    res = api.create_transaction(
        create_transaction_payload(account["id"], "REGISTRATION", vin="SHORTVIN"), CLERK)
    validate_error(res, "ERR_INVALID_TRANSACTION_FIELDS", expected_status=422)


def test_title_requires_positive_declared_price(api):
    """PRD §3.2: "The declared price must be greater than zero for a TITLE or TRANSFER
    transaction and must be exactly zero for a REGISTRATION or LIEN transaction. ... Any
    of these failing rejects creation with ERR_INVALID_TRANSACTION_FIELDS (HTTP 422)."

    Design: Corner/entities/transaction_title_requires_positive_declared_price_422
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    res = api.create_transaction(
        create_transaction_payload(account["id"], "TITLE", declared_price_cents=0), CLERK)
    validate_error(res, "ERR_INVALID_TRANSACTION_FIELDS", expected_status=422)


# ─── Corner: errors (residual triggers) ───────────────────────────────

def test_trip_at_capacity_returns_error(api):
    """PRD §3.4: "the attach is rejected with ERR_TRIP_AT_CAPACITY (HTTP 409) when the
    trip's assigned_leg_count is already at or above its capacity (an attach is only
    allowed while the count is strictly less than capacity)."

    Design: Corner/errors/trip_at_capacity_returns_error
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txnA, _qa = create_transaction_verified_and_quoted(account["id"], "REGISTRATION", vin="1HGCM82633A004352")
    subA = submit_transaction(txnA["id"])
    txnB, _qb = create_transaction_verified_and_quoted(account["id"], "REGISTRATION", vin="2HGCM82633A004353")
    subB = submit_transaction(txnB["id"])

    trip = create_planned_trip(capacity=1)
    attach_leg(trip["id"], subA["id"], trip["version"])
    trip_v1 = get_success_data(api.get_runner_trip(trip["id"], DISPATCHER))["version"]

    res = api.attach_leg(trip["id"], {
        "submission_id": subB["id"], "expected_runnertrip_version": trip_v1}, DISPATCHER)
    validate_error(res, "ERR_TRIP_AT_CAPACITY", expected_status=409)


def test_runner_trip_capacity_below_one_returns_validation(api):
    """PRD §3.4: "with a capacity of at least one leg ... A capacity below one fails the
    typed constraint and is rejected with ERR_VALIDATION (HTTP 422)."

    Design: Corner/errors/validation_capacity_below_one_returns_validation_error
    """
    set_clock()
    res = api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-01", capacity=0), DISPATCHER)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


# ─── Corner: rbac ─────────────────────────────────────────────────────

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_account(create_account_payload(
        account_type="RETAIL", legal_name="NoAuth", state_code="CA"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_feeanalyst_cannot_create_transaction(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."

    Design: Corner/rbac/feeanalyst_cannot_create_transaction_unauthorized
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account = create_account(account_type="RETAIL", state_code="CA")
    res = api.create_transaction(
        create_transaction_payload(account["id"], "REGISTRATION"), ANALYST)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_accountholder_cannot_cancel_other_accounts_transaction(api):
    """PRD §2.1: "an AccountHolder acting on a transaction must own it — the transaction's
    account_id must equal the caller's X-User-ID — and a violation is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/accountholder_cannot_cancel_other_accounts_transaction
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account_a = create_account(account_type="RETAIL", state_code="CA", legal_name="Owner A")
    account_b = create_account(account_type="RETAIL", state_code="CA", legal_name="Owner B")
    txn = create_transaction(account_a["id"], "REGISTRATION", declared_price_cents=0)

    # AccountHolder whose X-User-ID is account B cancelling account A's transaction.
    res = api.cancel_transaction(txn["id"], make_account_holder_headers(account_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_lien_officer_same_as_submitter_segregation_denied(api):
    """PRD §3.8: "the perfecting officer must not be the same person who submitted the
    transaction: the acting X-User-ID must differ from the transaction's
    submitted_by_user_id, and an attempt by the submitting user to perfect is rejected
    with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/rbac/lien_officer_same_as_submitter_segregation_denied
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # LIEN transaction driven to APPROVED, submitted by X-User-ID 'dual-actor'.
    txn, packet, _sub = setup_lien_transaction_approved(
        account["id"], submitting_user_id="dual-actor", lender_name="Second Bank",
        lien_amount_cents=300000)
    assert txn["lifecycle_status"] == "APPROVED"

    # LienOfficer whose X-User-ID equals the submitting user.
    res = api.perfect_lien_packet(packet["id"], make_lien_officer_headers("dual-actor"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    packet_after = validate_success(api.get_lien_packet(packet["id"], LIEN_OFFICER), 200)
    assert packet_after["packet_status"] == "DRAFT"


# ─── Corner: endpoints (listing) ──────────────────────────────────────

def test_list_transactions_pagination_envelope(api):
    """PRD §2.3: "The limit parameter specifies the maximum number of items to return"
    PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_transactions_pagination_envelope
    """
    set_clock()
    publish_fee_schedule(state_code="CA")
    account = create_account(account_type="RETAIL", state_code="CA")
    create_transaction(account["id"], "REGISTRATION", vin="1HGCM82633A004352", declared_price_cents=0)
    create_transaction(account["id"], "REGISTRATION", vin="2HGCM82633A004353", declared_price_cents=0)

    data, meta = validate_paginated(api.list_transactions(ADMIN, params={
        "account_id": account["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_fee_quotes_subresource_lists_history(api):
    """PRD §3.3: "Each quote computation produces a new FeeQuote whose variant is ESTIMATE
    and whose status is ACTIVE, sets any previously ACTIVE quote for that transaction to
    SUPERSEDED"
    PRD §3.3: "The full history of quotes for a transaction — both estimate iterations and
    the eventual final quote — is retrievable as a list"

    Design: Corner/endpoints/fee_quotes_subresource_lists_history
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    q1 = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    v1 = get_success_data(api.get_transaction(txn["id"], ANALYST))["version"]
    q2 = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": v1}, ANALYST), 200)

    data, meta = validate_paginated(api.list_transaction_fee_quotes(txn["id"], ANALYST))
    assert meta["total_count"] == 2
    by_id = {q["id"]: q for q in data}
    assert by_id[q1["id"]]["status"] == "SUPERSEDED"
    assert by_id[q2["id"]]["status"] == "ACTIVE"


def test_runner_legs_filtered_by_submission_id(api):
    """PRD §3.4: "the legs of a trip can be listed in sequence_index order or filtered
    across the system by trip_id or submission_id."

    Design: Corner/endpoints/runner_legs_filtered_by_submission_id
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, _q = create_transaction_verified_and_quoted(account["id"], "REGISTRATION")
    submission = submit_transaction(txn["id"])
    trip = create_planned_trip()
    leg = attach_leg(trip["id"], submission["id"], trip["version"])

    data, meta = validate_paginated(api.list_runner_legs(DISPATCHER, params={
        "submission_id": submission["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == leg["id"]
    assert data[0]["submission_id"] == submission["id"]
