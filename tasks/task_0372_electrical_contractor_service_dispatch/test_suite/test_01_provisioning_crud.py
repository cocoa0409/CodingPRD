"""Catalog provisioning: customer/technician/SKU/truck-stock CRUD, defaults,
computed fields, system fields, and input well-formedness.

Queue B (Corner): entities, endpoints, cross_cutting_concerns sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_customer, assert_technician, assert_truck_stock_item,
    create_customer_payload, create_technician_payload,
    create_service_job_payload,
    make_customer, make_technician, make_sku, stock_truck,
    make_membership_plan, enroll_membership, make_job, current_job_version,
)

DISP = TEST_USERS["dispatcher_headers"]


def test_create_customer_returns_201_with_all_fields(api):
    """PRD §3.1: "A `Customer` record carries the customer's `full_name`, an `email`,
    a service-address `service_zip`, and a `phone`."
    PRD §2.4: "The `version` field is an integer that begins at 1 when the resource is created."

    Design: Corner/entities/create_customer_returns_201_with_all_fields
    """
    resp = api.create_customer(
        {"full_name": "Jane Doe", "email": "jane@x.com", "service_zip": "12345", "phone": "555-1000"},
        DISP,
    )
    data = validate_success(resp, 201)
    assert data["full_name"] == "Jane Doe"
    assert data["email"] == "jane@x.com"
    assert data["service_zip"] == "12345"
    assert data["phone"] == "555-1000"
    assert data["version"] == 1
    assert isinstance(data["id"], str) and len(data["id"]) > 0
    assert_customer(data)


def test_get_customer_returns_stored_entity(api):
    """PRD §4 routing for GET /v1/customers/{customerId} plus PRD §2.4:
    "Every persisted resource is assigned a server-minted `id` that is a UUID with no type prefix."

    Design: Corner/entities/get_customer_returns_stored_entity
    """
    created = make_customer(full_name="Get Me", email="getme@x.com", service_zip="22222", phone="555")
    resp = api.get_customer(created["id"], DISP)
    data = validate_success(resp, 200)
    assert data["id"] == created["id"]
    assert data["email"] == "getme@x.com"


def test_list_customers_paginated_envelope(api):
    """PRD §2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in its `meta` object: `total_count` is the count of
    all records matching the query before pagination is applied, and `has_more` is true
    when records remain beyond the current page."

    Design: Corner/entities/list_customers_paginated_envelope
    """
    make_customer(full_name="L1", email="l1@x.com", service_zip="30000", phone="1")
    make_customer(full_name="L2", email="l2@x.com", service_zip="30001", phone="2")
    resp = api.list_customers(DISP, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_customer_not_found(api):
    """PRD §2.7: "Every path identifier is resolved left-to-right; if any referenced
    resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_customer_not_found
    """
    resp = api.get_customer("00000000-0000-0000-0000-000000000000", DISP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_customer_missing_required_field(api):
    """PRD §2.6: "Request-body well-formedness covers required fields being present...
    any of these failing yields `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1 names `email` as a required Customer field.

    Design: Corner/entities/create_customer_missing_required_field
    """
    resp = api.create_customer({"full_name": "No Email", "service_zip": "44444", "phone": "9"}, DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_technician_oncall_default_false(api):
    """PRD §3.1: "an `on_call` boolean that defaults to false and marks the technician
    as eligible for emergency dispatch."

    Design: Corner/entities/technician_oncall_default_false
    """
    resp = api.create_technician(
        {"full_name": "Def Tech", "license_class": "JOURNEYMAN", "service_zone": "120", "hourly_rate_cents": 9000},
        DISP,
    )
    data = validate_success(resp, 201)
    assert data["on_call"] is False
    assert_technician(data)


def test_servicejob_requires_permit_computed_for_panel(api):
    """PRD §3.3: "`requires_permit` is set true when the `scope` is either `PANEL` or
    `EV_CHARGER` and false for `OUTLET` work ... `total_due_cents` is initialized to 0;
    and the job's `status` is `DRAFT`."

    Design: Corner/entities/servicejob_requires_permit_computed_for_panel
    """
    cust = make_customer(full_name="RP Cust", email="rp@x.com", service_zip="55555", phone="5")
    resp = api.create_service_job({"customer_id": cust["id"], "scope": "PANEL", "job_class": "INSTALL"}, DISP)
    data = validate_success(resp, 201)
    assert data["requires_permit"] is True
    assert data["scope"] == "PANEL"
    assert data["status"] == "DRAFT"
    assert data["total_due_cents"] == 0


def test_servicejob_membership_snapshot_on_create(api):
    """PRD §3.3: "`membership_id` is snapshotted from the customer's currently `ACTIVE`
    membership at the moment of job creation, or left null if the customer has no active
    membership."

    Design: Corner/entities/servicejob_membership_snapshot_on_create
    """
    plan = make_membership_plan(name="Basic", tier="BASIC", monthly_fee_cents=1000, labor_discount_pct=0.10)
    mem = make_customer(full_name="Mem", email="memsnap@x.com", service_zip="60000", phone="6")
    mship = enroll_membership(mem["id"], plan["id"])
    job = make_job(mem["id"], scope="OUTLET", job_class="SERVICE")
    assert job["membership_id"] == mship["id"]


def test_servicejob_membership_null_when_no_active_membership(api):
    """PRD §3.3: "`membership_id` is snapshotted from the customer's currently `ACTIVE`
    membership at the moment of job creation, or left null if the customer has no active
    membership."

    Design: Corner/entities/servicejob_membership_snapshot_on_create
    """
    non = make_customer(full_name="NoMem", email="nomemsnap@x.com", service_zip="60001", phone="6")
    job = make_job(non["id"], scope="OUTLET", job_class="SERVICE")
    assert job["membership_id"] is None


def test_system_fields_generated_ignored_on_input(api):
    """PRD §2.4: "Every persisted resource is assigned a server-minted `id` that is a UUID
    with no type prefix ... The `version` field is an integer that begins at 1 when the
    resource is created and increments by one on every mutation of that resource."

    Design: Corner/entities/system_fields_generated_ignored_on_input
    """
    resp = api.create_customer(
        {"full_name": "Sys", "email": "sys@x.com", "service_zip": "70000", "phone": "7"}, DISP
    )
    data = validate_success(resp, 201)
    assert data["version"] == 1
    assert isinstance(data["created_at"], str) and len(data["created_at"]) > 0
    assert_customer(data)  # asserts id is a valid UUID


def test_invalid_enum_scope_rejected(api):
    """PRD §2.6: "Request-body well-formedness covers ... enum-typed fields carrying a
    recognized value ... any of these failing yields `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.3 restricts scope to `OUTLET`, `PANEL`, or `EV_CHARGER`.

    Design: Corner/entities/invalid_enum_scope_rejected
    """
    cust = make_customer(full_name="Enum Cust", email="enum@x.com", service_zip="80000", phone="8")
    resp = api.create_service_job({"customer_id": cust["id"], "scope": "FURNACE", "job_class": "SERVICE"}, DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_dispatch_window_start_not_before_end_rejected(api):
    """PRD §2.6: "Request-body well-formedness covers ... any arrival window having its
    `window_start` strictly before its `window_end`; any of these failing yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/dispatch_window_start_not_before_end_rejected
    """
    cust = make_customer(full_name="WIN Cust", email="win@x.com", service_zip="13001", phone="1")
    tech = make_technician(full_name="WIN Tech", service_zone="130", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    from test_helpers import quote_and_accept
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    v = current_job_version(job["id"])
    resp = api.create_dispatch(
        {"job_id": job["id"], "technician_id": tech["id"],
         "window_start": "2026-08-01T11:00:00Z", "window_end": "2026-08-01T11:00:00Z",
         "expected_job_version": v},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_fk_integrity_dispatch_references_missing_technician(api):
    """PRD §2.7: "The same existence check applies to identifiers carried in request bodies,
    such as the `customer_id`, `plan_id`, `job_id`, `technician_id`, and `sku_id` foreign keys."
    PRD §2.6 places existence (`ERR_NOT_FOUND`) before all business checks.

    Design: Corner/entities/fk_integrity_dispatch_references_missing_technician
    """
    cust = make_customer(full_name="FK Cust", email="fkdisp@x.com", service_zip="12001", phone="1")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    from test_helpers import quote_and_accept
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    v = current_job_version(job["id"])
    resp = api.create_dispatch(
        {"job_id": job["id"], "technician_id": "00000000-0000-0000-0000-000000000000",
         "window_start": "2026-08-01T09:00:00Z", "window_end": "2026-08-01T10:00:00Z",
         "expected_job_version": v},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_truckstock_low_stock_computed_on_create(api):
    """PRD §3.2: "a computed `low_stock` flag, which is true exactly when the
    `quantity_on_hand` is at or below the `reorder_threshold`."

    Design: Corner/entities/truckstock_low_stock_computed_on_create
    """
    tech = make_technician(full_name="LS Tech", service_zone="140", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    sku = make_sku(sku_code="LS-SKU", description="Nut", unit_price_cents=100, taxable=True)
    resp = api.create_truck_stock_item(
        {"technician_id": tech["id"], "sku_id": sku["id"], "quantity_on_hand": 2, "reorder_threshold": 3}, DISP
    )
    data = validate_success(resp, 201)
    assert data["low_stock"] is True
    assert data["quantity_on_hand"] == 2
    assert_truck_stock_item(data)


def test_restock_increments_quantity_and_recomputes_low_stock(api):
    """PRD §3.2: "A dispatcher may add units to an existing stock item via a restock that
    takes an `add_quantity`; the units are added to `quantity_on_hand` and `low_stock` is
    recomputed."

    Design: Corner/endpoints/restock_increments_quantity_and_recomputes_low_stock
    """
    tech = make_technician(full_name="RS Tech", service_zone="390", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    sku = make_sku(sku_code="RS-SKU", description="Wire nut", unit_price_cents=50, taxable=True)
    stock = stock_truck(tech["id"], sku["id"], quantity_on_hand=2, reorder_threshold=3)
    assert stock["low_stock"] is True
    resp = api.restock_truck_stock_item(stock["id"], {"add_quantity": 5}, DISP)
    data = validate_success(resp, 200)
    assert data["quantity_on_hand"] == 7
    assert data["low_stock"] is False


def test_rate_threshold_low_stock_at_boundary(api):
    """PRD §3.2: "a computed `low_stock` flag, which is true exactly when the
    `quantity_on_hand` is at or below the `reorder_threshold`, and is recomputed on every
    change to the on-hand quantity."

    Design: Corner/cross_cutting_concerns/rate_threshold_low_stock_at_boundary
    """
    tech = make_technician(full_name="RT Tech", service_zone="520", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    sku = make_sku(sku_code="RT-SKU", description="Lug", unit_price_cents=100, taxable=True)
    stock = stock_truck(tech["id"], sku["id"], quantity_on_hand=3, reorder_threshold=3)
    assert stock["low_stock"] is True  # 3 <= 3
    resp = api.restock_truck_stock_item(stock["id"], {"add_quantity": 1}, DISP)
    data = validate_success(resp, 200)
    assert data["quantity_on_hand"] == 4
    assert data["low_stock"] is False  # 4 > 3


def test_occ_version_increments_on_estimate_create(api):
    """PRD §2.5: "Successfully creating an estimate itself increments the parent
    `ServiceJob.version` by one."

    Design: Corner/cross_cutting_concerns/occ_version_increments_on_estimate_create
    """
    cust = make_customer(full_name="OK Cust", email="ok@x.com", service_zip="50001", phone="1")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 10000},
        DISP,
    )
    after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert after["version"] == v0 + 1


def test_membership_cancel_sets_cancelled(api):
    """PRD §3.1: "A membership may later be cancelled, which moves its `status` to `CANCELLED`."

    Design: Corner/endpoints/membership_cancel_sets_cancelled
    """
    plan = make_membership_plan(name="Cncl", tier="BASIC", monthly_fee_cents=1000, labor_discount_pct=0.05)
    cust = make_customer(full_name="MC Cust", email="mc@x.com", service_zip="42001", phone="1")
    ch = make_customer_headers(cust["id"])
    mship = validate_success(api.create_membership({"customer_id": cust["id"], "plan_id": plan["id"]}, ch), 201)
    resp = api.cancel_membership(mship["id"], ch)
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"
