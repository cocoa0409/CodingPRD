"""Entity CRUD, defaults, computed fields, immutability, and FK reachability
(breadth queue B — entities section).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    assert_property, assert_lease, assert_sales_report,
    create_property_payload, create_tenant_payload, create_lease_payload,
    create_expense_pool_payload, create_line_item_payload, create_sales_report_payload,
    create_property, create_tenant, create_active_lease,
    make_tenant_headers, NON_EXISTENT_UUID,
    PM_HEADERS, ACCT_HEADERS,
)


def test_create_property_initializes_occupancy_and_version(api):
    """PRD §3.1: "On creation the property's occupied_sqft is initialized to 0 and
    grows only as leases activate."
    PRD §2.4: "an integer version that starts at 1 and increases by exactly one on
    every mutation."

    Design: Corner/entities/create_property_returns_201_with_fields
    """
    res = api.create_property(
        create_property_payload(name="Riverside", total_rentable_sqft=50000), PM_HEADERS)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["occupied_sqft"] == 0
    assert prop["version"] == 1
    assert prop["gross_up_occupancy_pct"] == 0.95


def test_get_lease_returns_stored_entity_with_zero_computed(api):
    """PRD §3.3: "A new lease begins in status DRAFT with outstanding_balance_cents
    and ti_drawn_cents both at 0."

    Design: Corner/entities/get_lease_returns_stored_entity
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = get_success_data(api.create_lease(
        create_lease_payload(prop["id"], tenant["id"], leased_sqft=1000,
                             base_rent_cents_annual=5000000), PM_HEADERS))
    fetched = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert fetched["ti_drawn_cents"] == 0
    assert fetched["outstanding_balance_cents"] == 0
    assert fetched["status"] == "DRAFT"


def test_list_properties_paginated_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/entities/list_properties_paginated_envelope
    """
    create_property(total_rentable_sqft=1000, name="A")
    create_property(total_rentable_sqft=2000, name="B")
    data, meta = validate_paginated(
        api.list_properties(PM_HEADERS, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_get_property_not_found(api):
    """PRD §2.6: "the first identifier in the path that does not resolve to an
    existing resource yields ERR_NOT_FOUND before any deeper lookup is attempted."

    Design: Corner/entities/get_property_not_found_returns_404
    """
    res = api.get_property("00000000-0000-4000-8000-000000000000", PM_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_lease_missing_required_leased_sqft(api):
    """PRD §2.9: "Only then is the body checked for well-formedness — required
    fields present, enum values in range, constrained integers non-negative
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_lease_missing_required_field_returns_invalid_request
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    res = api.create_lease(
        {"property_id": prop["id"], "tenant_id": tenant["id"],
         "base_rent_cents_annual": 5000000}, PM_HEADERS)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_pool_defaults_applied_when_omitted(api):
    """PRD §3.1: "The pro_rata_denominator selects which figure becomes the
    denominator of every tenant's share ... it defaults to TOTAL_RENTABLE. The
    admin_fee_pct is an administrative fee layered on top of recoverable expenses
    ... defaulting to 0.0. A new pool opens in status OPEN"

    Design: Corner/entities/pool_admin_fee_default_applied
    """
    prop = create_property(total_rentable_sqft=10000)
    pool = validate_success(api.create_expense_pool(
        create_expense_pool_payload(prop["id"], pool_year=2025), ACCT_HEADERS), 201)
    assert pool["admin_fee_pct"] == 0.0
    assert pool["pro_rata_denominator"] == "TOTAL_RENTABLE"
    assert pool["status"] == "OPEN"


def test_computed_occupied_sqft_ignores_client_input(api):
    """PRD §3.1: "On creation the property's occupied_sqft is initialized to 0 and
    grows only as leases activate."

    Design: Corner/entities/computed_occupied_sqft_input_ignored
    """
    payload = create_property_payload(name="ComputedProp", total_rentable_sqft=10000)
    payload["occupied_sqft"] = 9999
    prop = validate_success(api.create_property(payload, PM_HEADERS), 201)
    assert prop["occupied_sqft"] == 0


def test_invalid_recoverability_enum_rejected(api):
    """PRD §3.2: "The recoverability is RECOVERABLE (the expense enters the pool),
    NON_RECOVERABLE (it is excluded entirely), or CAPPED_CONTROLLABLE"
    PRD §2.9: "enum values in range, constrained integers non-negative
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/invalid_enum_recoverability_rejected
    """
    prop = create_property(total_rentable_sqft=10000)
    pool = get_success_data(api.create_expense_pool(
        create_expense_pool_payload(prop["id"], pool_year=2025), ACCT_HEADERS))
    res = api.add_line_item(
        pool["id"],
        {"category": "UTILITIES", "amount_cents": 1000, "recoverability": "MAYBE"},
        ACCT_HEADERS)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_sales_report_is_append_only_no_version(api):
    """PRD §2.4: "Append-only entities — SalesReport and LedgerEntry — carry only
    id and created_at; they have neither an updated_at nor a version field, because
    once written they are never modified in place."

    Design: Corner/entities/salesreport_immutable_no_version_field
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0)
    sr = validate_success(api.create_sales_report(
        create_sales_report_payload(lease["id"], period_year=2025, gross_sales_cents=100000),
        make_tenant_headers(tenant["id"])), 201)
    assert sr["gross_sales_cents"] == 100000
    assert "version" not in sr or sr.get("version") is None


def test_create_lease_unknown_property_fk(api):
    """PRD §2.9: "then foreign keys named in the body — property_id, tenant_id,
    pool_id, lease_id, and source_reconciliation_id — are resolved
    (ERR_FK_NOT_FOUND)."

    Design: Corner/entities/create_lease_unknown_property_fk_returns_404
    """
    tenant = create_tenant()
    res = api.create_lease(
        create_lease_payload("00000000-0000-4000-8000-000000000000", tenant["id"],
                             leased_sqft=1000, base_rent_cents_annual=0), PM_HEADERS)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_list_leases_by_tenant_reverse_reachability(api):
    """PRD §4 (endpoint table): "GET /tenants/{id}/leases — List leases for a
    tenant"
    PRD §2.4: "Every resource is identified by a server-minted id, a UUID with no
    type prefix"

    Design: Corner/entities/flat_fk_reverse_reachability_leases_by_tenant
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    get_success_data(api.create_lease(
        create_lease_payload(prop["id"], tenant["id"], leased_sqft=1000,
                             base_rent_cents_annual=0), PM_HEADERS))
    get_success_data(api.create_lease(
        create_lease_payload(prop["id"], tenant["id"], leased_sqft=2000,
                             base_rent_cents_annual=0), PM_HEADERS))
    data, meta = validate_paginated(api.list_tenant_leases(tenant["id"], PM_HEADERS))
    assert len(data) == 2
