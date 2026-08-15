"""Customer / catalog / unit creation corners (entities section)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    SHOP_MANAGER,
    TECHNICIAN,
    NON_EXISTENT_UUID,
    api_client,
    assert_customer,
    create_customer,
    create_part,
    create_unit,
    customer_payload,
    is_valid_uuid,
    part_payload,
    unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_customer_creation_defaults_and_system_fields(api):
    """PRD §3.1: "An optional `penalty_delay_rule` selects the TAT penalty
    variant: it defaults to `ADJUSTED`, which excludes customer-delay hours
    from the penalty basis, while `CALENDAR` uses raw elapsed hours (§3.6).
    A new customer starts with `status` set to `ACTIVE` — the only value,
    suspension being out of scope — and `current_exposure_cents` at zero."
    PRD §2.4: "version (integer): a system-managed integer that increments
    by exactly 1 on every mutation of the resource."

    Design: Corner/entities/customer_creation_defaults_and_system_fields
    """
    res = api.create_customer(customer_payload(), SHOP_MANAGER)
    data = validate_success(res, 201)
    assert_customer(data)
    assert is_valid_uuid(data["id"]) and "-" in data["id"]
    assert data["version"] == 1
    assert data["penalty_delay_rule"] == "ADJUSTED"
    assert data["current_exposure_cents"] == 0
    assert data["credit_hold"] is False
    assert data["status"] == "ACTIVE"


def test_customer_create_missing_required_credit_limit_returns_400(api):
    """PRD §2.2 (error envelope) and §5: missing required field triggers
    `ERR_INVALID_REQUEST`. The `credit_limit_cents` field is a required input
    in §3.1 ("`credit_limit_cents`, the maximum allowed outstanding
    exposure") with no stated default.

    Design: Corner/entities/customer_create_missing_required_credit_limit_returns_400
    """
    payload = {
        "name": "NoLimit",
        "certificate_number": "AIR-X",
        "contract_tat_hours": 100,
        "tat_penalty_rate_cents_per_hour": 5000,
        "tat_penalty_cap_pct": 50,
    }
    res = api.create_customer(payload, SHOP_MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_unit_create_missing_required_owner_returns_invalid_request(api):
    """PRD §3.2: "a CustomerServiceRep registers each serialized unit ... an
    `ownership` of `SHOP` (pool or lease stock) or `CUSTOMER`, and an
    `owner_customer_id` that is required exactly when `ownership` is
    `CUSTOMER` and must be null when `SHOP`."  Violations are rejected with
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/unit_create_missing_required_owner_returns_invalid_request
    """
    part = create_part()
    payload = {
        "part_id": part["id"],
        "serial_number": "SN-NO1",
        "ownership": "CUSTOMER",
        "condition_status": "UNSERVICEABLE",
        "custody_status": "OFF_SITE",
        "total_cycles": 100,
        "cycles_since_overhaul": 100,
        "manufactured_at": "2020-01-01",
    }
    res = api.create_unit(payload, CSR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_unit_duplicate_serial_rejected(api):
    """PRD §3.2: "a globally unique `serial_number` (reuse rejected with
    `ERR_DUPLICATE_SERIAL`, HTTP 409)".

    Design: Corner/entities/unit_duplicate_serial_rejected
    """
    part = create_part()
    first = unit_payload(
        part["id"], serial_number="SN-DUP",
        ownership="SHOP", condition_status="SERVICEABLE",
        custody_status="IN_POOL", total_cycles=100, cycles_since_overhaul=10,
        manufactured_at="2020-01-01")
    res1 = api.create_unit(first, CSR)
    validate_success(res1, 201)

    second = unit_payload(
        part["id"], serial_number="SN-DUP",
        ownership="SHOP", condition_status="SERVICEABLE",
        custody_status="IN_POOL", total_cycles=200, cycles_since_overhaul=20,
        manufactured_at="2021-01-01")
    res2 = api.create_unit(second, CSR)
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_SERIAL.value, expected_status=409)


def test_work_order_create_rejects_extra_status_field(api):
    """PRD §3.2: induction is "a `CustomerServiceRep` creates a work order
    with a `customer_id`, a `unit_id`, and a `work_scope` of `REPAIR` or
    `OVERHAUL`" — no `status` field is a legitimate input; clients cannot
    force an initial state. PRD §5 names `ERR_INVALID_REQUEST` for malformed
    requests including unknown fields.

    Design: Corner/entities/work_order_create_rejects_extra_status_field
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    payload = {
        "customer_id": customer["id"],
        "unit_id": unit["id"],
        "work_scope": "OVERHAUL",
        "status": "CLOSED",
    }
    res = api.create_work_order(payload, CSR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_work_order_get_not_found_returns_404(api):
    """PRD §2.8: "Each resource family has its own 404 code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND` ...".

    Design: Corner/entities/work_order_get_not_found_returns_404
    """
    res = api.get_work_order(NON_EXISTENT_UUID, SHOP_MANAGER)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value, expected_status=404)


def test_units_list_pagination_with_filters(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter specifies how many items to skip and defaults to
    0." PRD §3.2: "The unit list supports optional filters `part_id`,
    `owner_customer_id`, `ownership`, `custody_status`, and
    `condition_status`".

    Design: Corner/entities/units_list_pagination_with_filters
    """
    part = create_part()
    for serial in ("SN-P1", "SN-P2", "SN-P3"):
        create_unit(part["id"], serial_number=serial,
                    ownership="SHOP", condition_status="SERVICEABLE",
                    custody_status="IN_POOL")

    page1, meta1 = validate_paginated(api.list_units(
        SHOP_MANAGER,
        params={"ownership": "SHOP", "custody_status": "IN_POOL",
                "limit": 2, "offset": 0}))
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = validate_paginated(api.list_units(
        SHOP_MANAGER,
        params={"ownership": "SHOP", "custody_status": "IN_POOL",
                "limit": 2, "offset": 2}))
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1


def test_traceability_records_immutable_append_only(api):
    """PRD §2.4: "Three resource families are immutable ledgers and carry
    only `id` and `created_at`: DirectiveRecord, ReleaseCertificate, and
    TraceabilityRecord. On those three, both `updated_at` and `version` are
    absent." PRD §2.11: the unit's records are "retrievable as a chronological
    list, ascending by `event_at` and then by `created_at`." PRD §3.2:
    registration "appends a `BIRTH` traceability event"; induction "appends
    an `INDUCT` traceability event".

    Design: Corner/entities/traceability_records_immutable_append_only
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    create_work_order_payload = {
        "customer_id": customer["id"],
        "unit_id": unit["id"],
        "work_scope": "OVERHAUL",
    }
    res = api.create_work_order(create_work_order_payload, CSR)
    validate_success(res, 201)

    data, meta = validate_paginated(api.list_unit_traceability(unit["id"], SHOP_MANAGER))
    assert len(data) == 2
    assert data[0]["event_type"] == "BIRTH"
    assert data[1]["event_type"] == "INDUCT"
    for record in data:
        assert "id" in record and "created_at" in record
        assert "updated_at" not in record, "ledger record must not expose updated_at"
        assert "version" not in record, "ledger record must not expose version"
