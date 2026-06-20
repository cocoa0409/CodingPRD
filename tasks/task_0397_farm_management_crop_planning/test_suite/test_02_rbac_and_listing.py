"""Role-based access control and filtered/reverse-FK listings.

Corner queue B: section `rbac`, section `endpoints` (filtered list subset).
"""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_parcel, create_draft_plan, create_seed_product, create_input_lot,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]
SA = TEST_USERS["sales_agent_headers"]


def test_agronomist_cannot_approve_plan(api):
    """PRD §2.1: "is the only role that may approve, close, or abandon a crop plan".
    PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/agronomist_cannot_approve_plan
    """
    parcel = create_parcel(name="RB", acreage=50.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=40.0)
    resp = api.approve_crop_plan(
        plan["id"], {"expected_parcel_version": parcel["version"]}, AG)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_salesagent_cannot_create_parcel(api):
    """PRD §2.1: "A `FarmManager` owns the registries — parcels, input products, input
    lots, equipment assets, and the applicator roster". PRD §2.1: "If the role is
    recognized but is not permitted to perform the requested operation under the access
    matrix, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/salesagent_cannot_create_parcel
    """
    resp = api.create_parcel({"name": "X", "acreage": 10.0, "soil_type": "LOAM"}, SA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or names something the system
    does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.list_parcels({"X-User-ID": "anon-1"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_fk_reverse_input_lots_by_product(api):
    """PRD §4 (GET /input-products/{id}/lots): "List lots of a product". PRD §2.3:
    "Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope, where `total_count` is the count of all matching
    items before pagination".

    Design: Corner/endpoints/fk_reverse_input_lots_by_product
    """
    product = create_seed_product(name="FKP")
    create_input_lot(product["id"], lot_code="A", quantity_received=100.0)
    create_input_lot(product["id"], lot_code="B", quantity_received=200.0)
    resp = api.list_product_lots(product["id"], FM)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected 2 lots for product, got {meta['total_count']}"
    for lot in data:
        assert lot["input_product_id"] == product["id"], "all lots must belong to the product"
