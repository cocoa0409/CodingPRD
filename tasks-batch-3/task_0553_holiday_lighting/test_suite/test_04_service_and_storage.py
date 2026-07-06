"""Weather/repair service calls and off-season storage.

Covers the WARRANTY vs BILLABLE resolve branch, the billable resolve cascade
(invoice -> customer balance), the storage-retrieve contract gate, buffered bin
exclusivity, and service-call / storage-record state guards.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    create_customer, create_storage_bin, setup_active_contract,
    setup_scheduled_service_call, setup_stored_record,
)
from test_helpers.factories import (
    create_service_call_payload, create_storage_record_payload,
)

SALES = TEST_USERS["salesrep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billingadmin_headers"]


def _customer_invoices(api, customer_id):
    data, meta = validate_paginated(
        api.list_invoices(BILLING, params={"customer_id": customer_id}))
    return data, meta


# ── Difficulty/non_linear_state_machine/service_call_warranty_vs_billable_branch

def test_billable_resolve_marks_resolved_and_creates_invoice(api):
    """PRD §3.5: "On the `BILLABLE` branch, resolution runs a two-hop cascade: first it
    creates an invoice in `ISSUED` status with `source_type` `SERVICE`, a `customer_id`
    taken from the call's contract, a `job_id` equal to the call's `job_id`, a single line
    item whose `amount_cents` equals the call's `service_fee_cents` and whose `taxable`
    flag is false, and a `tax_rate_bps` of 0; then it recomputes the customer's
    `outstanding_balance_cents`."

    Design: Difficulty/non_linear_state_machine/service_call_warranty_vs_billable_branch
    """
    ctx = setup_scheduled_service_call(classification="BILLABLE", service_fee_cents=8000)
    resolved = validate_success(
        api.resolve_service_call(ctx["service_call"]["id"], BILLING), 200)
    assert resolved["status"] == "RESOLVED", resolved
    assert resolved["classification"] == "BILLABLE", resolved
    invoices, meta = _customer_invoices(api, ctx["customer"]["id"])
    assert meta["total_count"] == 1, meta
    inv = invoices[0]
    assert inv["source_type"] == "SERVICE" and inv["total_cents"] == 8000, inv


def test_billable_resolve_increases_customer_balance(api):
    """PRD §2.11: "It is defined as the sum of `total_cents` across that customer's
    invoices whose `status` is `ISSUED`; invoices in `VOID` or `PAID` status are excluded
    from the sum."

    The billable resolve's ISSUED SERVICE invoice (8000) drives the customer's
    outstanding_balance_cents to 8000.

    Design: Difficulty/non_linear_state_machine/service_call_warranty_vs_billable_branch
    """
    ctx = setup_scheduled_service_call(classification="BILLABLE", service_fee_cents=8000)
    validate_success(api.resolve_service_call(ctx["service_call"]["id"], BILLING), 200)
    customer = validate_success(api.get_customer(ctx["customer"]["id"], BILLING), 200)
    assert customer["outstanding_balance_cents"] == 8000, customer


# ── Difficulty/transitive_cascade/service_resolve_billable_cascade_depth2 ────

def test_billable_resolve_creates_issued_service_invoice(api):
    """PRD §3.5: "first it creates an invoice in `ISSUED` status with `source_type`
    `SERVICE`, a `customer_id` taken from the call's contract, a `job_id` equal to the
    call's `job_id`, a single line item whose `amount_cents` equals the call's
    `service_fee_cents` and whose `taxable` flag is false, and a `tax_rate_bps` of 0; then
    it recomputes the customer's `outstanding_balance_cents`."

    Design: Difficulty/transitive_cascade/service_resolve_billable_cascade_depth2
    """
    ctx = setup_scheduled_service_call(classification="BILLABLE", service_fee_cents=12000,
                                       cause="DEFECT")
    validate_success(api.resolve_service_call(ctx["service_call"]["id"], BILLING), 200)
    invoices, meta = _customer_invoices(api, ctx["customer"]["id"])
    assert meta["total_count"] == 1, meta
    inv = invoices[0]
    assert inv["source_type"] == "SERVICE", inv
    assert inv["total_cents"] == 12000, inv
    assert inv["status"] == "ISSUED", inv


def test_billable_resolve_recomputes_balance_hop2(api):
    """PRD §3.5: "then it recomputes the customer's `outstanding_balance_cents`."

    The second cascade hop moves the customer's balance to the invoice total (12000).

    Design: Difficulty/transitive_cascade/service_resolve_billable_cascade_depth2
    """
    ctx = setup_scheduled_service_call(classification="BILLABLE", service_fee_cents=12000,
                                       cause="DEFECT")
    validate_success(api.resolve_service_call(ctx["service_call"]["id"], BILLING), 200)
    customer = validate_success(api.get_customer(ctx["customer"]["id"], BILLING), 200)
    assert customer["outstanding_balance_cents"] == 12000, customer


# ── Difficulty/cross_entity_state_dependency/storage_retrieve_requires_contract_active

def test_storage_retrieve_refused_when_contract_cancelled(api):
    """PRD §3.6: "A `BillingAdmin` retrieves stored lights by moving a record from
    `STORED` to `RETRIEVED`, permitted only while the record is `STORED` (otherwise
    `ERR_STORAGE_RECORD_NOT_STORED`) and only while the parent contract is `ACTIVE`, since
    lights are released only against a live contract (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."

    After the parent contract is CANCELLED, the STORED record cannot be retrieved.

    Design: Difficulty/cross_entity_state_dependency/storage_retrieve_requires_contract_active
    """
    ctx = setup_stored_record()
    validate_success(api.cancel_contract(ctx["contract"]["id"], SALES), 200)
    resp = api.retrieve_storage_record(ctx["storage_record"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)


def test_storage_record_stays_stored_when_retrieve_refused(api):
    """PRD §3.6: "permitted only while the record is `STORED` (otherwise
    `ERR_STORAGE_RECORD_NOT_STORED`) and only while the parent contract is `ACTIVE`, since
    lights are released only against a live contract (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/storage_retrieve_requires_contract_active
    """
    ctx = setup_stored_record()
    validate_success(api.cancel_contract(ctx["contract"]["id"], SALES), 200)
    api.retrieve_storage_record(ctx["storage_record"]["id"], BILLING)
    record = validate_success(api.get_storage_record(ctx["storage_record"]["id"], BILLING), 200)
    assert record["status"] == "STORED", record


# ── Difficulty/resource_temporal_overlap/storage_bin_buffered_overlap_rejected

def test_buffered_bin_overlap_rejected(api):
    """PRD §3.6: "Before a record is created, the system enforces bin exclusivity with
    buffer: the proposed closed occupancy interval, inflated by the bin's `buffer_days` on
    both the leading and trailing side, must not collide with any other currently `STORED`
    occupancy of the same bin. A collision within that buffered window is rejected with
    `ERR_BIN_OCCUPIED`."

    A new occupancy starting 2026-03-05 falls within 7 buffer days of the prior
    occupancy's 2026-03-01 end, so it collides even though the raw ranges do not overlap.

    Design: Difficulty/resource_temporal_overlap/storage_bin_buffered_overlap_rejected
    """
    customer, contract = setup_active_contract()
    bin_ = create_storage_bin(bin_code="B-07", warehouse_zone="C", buffer_days=7)
    validate_success(api.create_storage_record(create_storage_record_payload(
        contract["id"], bin_["id"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"),
        BILLING), 201)
    resp = api.create_storage_record(create_storage_record_payload(
        contract["id"], bin_["id"], "2026-03-05T00:00:00Z", "2026-04-01T00:00:00Z"),
        BILLING)
    validate_error(resp, ApiErrorId.ERR_BIN_OCCUPIED.value, 409)


def test_non_colliding_bin_occupancy_succeeds(api):
    """PRD §3.6: "the proposed closed occupancy interval, inflated by the bin's
    `buffer_days` on both the leading and trailing side, must not collide with any other
    currently `STORED` occupancy of the same bin."

    A well-separated occupancy (2026-06-01..2026-08-01), far outside the 7-day buffer of
    the prior 2026-03-01 end, is accepted.

    Design: Difficulty/resource_temporal_overlap/storage_bin_buffered_overlap_rejected
    """
    customer, contract = setup_active_contract()
    bin_ = create_storage_bin(bin_code="B-07", warehouse_zone="C", buffer_days=7)
    validate_success(api.create_storage_record(create_storage_record_payload(
        contract["id"], bin_["id"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"),
        BILLING), 201)
    record = validate_success(api.create_storage_record(create_storage_record_payload(
        contract["id"], bin_["id"], "2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z"),
        BILLING), 201)
    assert record["status"] == "STORED", record


# ── Corner/state_machines/classify_non_open_service_call_returns_invalid_state

def test_classify_already_classified_service_call_rejected(api):
    """PRD §3.5: "A `BillingAdmin` classifies an open call, moving it from `OPEN` to
    `CLASSIFIED` (permitted only while `OPEN`)"
    PRD §3.5: "Any classify, schedule, or resolve attempted from the wrong service-call
    state is reported as `ERR_SERVICE_CALL_INVALID_STATE`."

    Design: Corner/state_machines/classify_non_open_service_call_returns_invalid_state
    """
    customer, contract = setup_active_contract()
    sc = validate_success(api.create_service_call(create_service_call_payload(
        contract["id"], reported_issue="flicker", cause="DEFECT",
        service_fee_cents=5000), BILLING), 201)
    validate_success(api.classify_service_call(
        sc["id"], {"classification": "WARRANTY"}, BILLING), 200)
    resp = api.classify_service_call(sc["id"], {"classification": "BILLABLE"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_SERVICE_CALL_INVALID_STATE.value, 409)


# ── Corner/errors/storage_retrieve_twice_returns_not_stored ──────────────────

def test_retrieve_already_retrieved_record_rejected(api):
    """PRD §3.6: "A `BillingAdmin` retrieves stored lights by moving a record from
    `STORED` to `RETRIEVED`, permitted only while the record is `STORED` (otherwise
    `ERR_STORAGE_RECORD_NOT_STORED`)"

    Design: Corner/errors/storage_retrieve_twice_returns_not_stored
    """
    ctx = setup_stored_record()
    validate_success(api.retrieve_storage_record(ctx["storage_record"]["id"], BILLING), 200)
    resp = api.retrieve_storage_record(ctx["storage_record"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_STORAGE_RECORD_NOT_STORED.value, 409)
