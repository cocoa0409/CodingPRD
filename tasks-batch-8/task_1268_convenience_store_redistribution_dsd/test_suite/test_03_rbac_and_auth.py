"""Authentication, role gating, and ownership scoping."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_delivery_manifest_payload,
    create_product_payload,
    create_retailer_payload,
    get_success_data,
    make_store_manager_headers,
    validate_error,
)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api_client.list_products({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_store_manager_cannot_create_product(api, admin_headers):
    """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4);
    a caller whose role is not admitted ... is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §4 lists POST /products under WholesaleAdmin only.

    Design: Corner/rbac/store_manager_cannot_create_product
    """
    retailer = get_success_data(api_client.create_retailer(create_retailer_payload(), admin_headers))
    sm = make_store_manager_headers(retailer["id"])
    resp = api_client.create_product(create_product_payload(sku="PX"), sm)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_store_manager_scoped_to_own_retailer(api, admin_headers):
    """PRD §2.1: "When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id`
    of the acting `Retailer`; ownership checks on any resource that references
    a retailer ... compare the resource's `retailer_id` foreign key to
    `X-User-ID`, and a store manager may only read and act on their own store's
    resources."

    Design: Corner/rbac/store_manager_scoped_to_own_retailer
    """
    ret_a = get_success_data(api_client.create_retailer(
        create_retailer_payload(store_name="A", jurisdiction_code="CA_NORTH",
                                credit_terms="NET7", delivery_day="MON"),
        admin_headers,
    ))
    ret_b = get_success_data(api_client.create_retailer(
        create_retailer_payload(store_name="B", jurisdiction_code="NV_CLARK",
                                credit_terms="COD", credit_limit_cents=500000,
                                delivery_day="TUE", tobacco_license_id=None),
        admin_headers,
    ))
    sm_a = make_store_manager_headers(ret_a["id"])
    resp = api_client.get_retailer(ret_b["id"], sm_a)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_credit_manager_cannot_close_manifest(api, admin_headers, credit_manager_headers):
    """PRD §2.1: "a caller whose role is not admitted ... is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST /delivery-manifests/{id}/close
    under WholesaleAdmin only.

    Design: Corner/rbac/credit_manager_cannot_close_manifest
    """
    manifest = get_success_data(api_client.create_delivery_manifest(
        create_delivery_manifest_payload(), admin_headers,
    ))
    manifest = get_success_data(api_client.begin_loading(manifest["id"], admin_headers))
    resp = api_client.close_manifest(
        manifest["id"],
        {"expected_manifest_version": manifest["version"]},
        credit_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
