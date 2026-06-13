"""Resource creation, computed fields, defaults, uniqueness, not-found,
listing/pagination, and FK-filtered reads.

Corner queue: entities section, endpoints section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_headers,
    ApiErrorId,
    assert_product, assert_lot, assert_customer,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall,
    draft_and_submit_initial_report,
    NON_EXISTENT_RECALL_UUID,
)
from test_helpers import factories as fac

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
AGENT = TEST_USERS["field_service_agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Corner: entities
# ===========================================================================
def test_create_product_returns_201_with_system_fields(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 on creation".
    PRD §3.1: "A product also carries a computed `active_recall_id` ... the field
    is set to null at creation."

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    resp = api.create_product(fac.create_product_payload(sku="P-NEW", name="Widget", regulator="FDA", unit_list_price_cents=5000), ADMIN)
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["version"] == 1, data["version"]
    assert data["active_recall_id"] is None, data["active_recall_id"]


def test_get_recall_not_found_returns_404(api):
    """PRD §2.6: "The first reference that fails to resolve to an existing
    resource causes immediate rejection with `ERR_NOT_FOUND`".

    Design: Corner/entities/get_recall_not_found_returns_404
    """
    resp = api.get_recall(NON_EXISTENT_RECALL_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_regulator_returns_422(api):
    """PRD §2.7: "Body well-formedness comes fourth: a missing required field, an
    invalid enum value, or an out-of-range integer ... yields
    `ERR_INVALID_REQUEST`." PRD §3.1: "a governing `regulator` that is one of
    `FDA` or `CPSC`".

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    resp = api.create_product({"sku": "P-MISS", "name": "NoReg", "unit_list_price_cents": 5000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_product_invalid_regulator_enum_returns_422(api):
    """PRD §2.7: "Body well-formedness comes fourth: a missing required field, an
    invalid enum value, or an out-of-range integer ... yields
    `ERR_INVALID_REQUEST`." PRD §3.1: "a governing `regulator` that is one of
    `FDA` or `CPSC`".

    Design: Corner/entities/create_product_invalid_regulator_enum_returns_422
    """
    resp = api.create_product({"sku": "P-ENUM", "name": "BadReg", "regulator": "EPA", "unit_list_price_cents": 5000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_customer_reachable_defaults_true(api):
    """PRD §3.1: "a `reachable` flag indicating whether that address is currently
    deliverable. The `reachable` flag defaults to true when omitted."

    Design: Corner/entities/customer_reachable_defaults_true_when_omitted
    """
    resp = api.create_customer({"name": "Def", "contact_channel": "EMAIL", "contact_address": "d@x.com"}, AGENT)
    data = validate_success(resp, 201)
    assert data["reachable"] is True, data["reachable"]


def test_lot_manufactured_units_computed_from_range(api):
    """PRD §3.1: "the system computes `manufactured_units` as `serial_end` minus
    `serial_start` plus one — the total count of serial numbers in the range."
    PRD §3.1: "Each lot also exposes a computed `quarantine_status` of either
    `RELEASED` or `HELD`; it is `RELEASED` by default and at creation".

    Design: Corner/entities/lot_manufactured_units_computed_from_serial_range
    """
    product = create_product()
    resp = api.create_lot(fac.create_lot_payload(product["id"], lot_code="MU1", serial_start=1, serial_end=100), COORD)
    data = validate_success(resp, 201)
    assert data["manufactured_units"] == 100, data["manufactured_units"]
    assert data["quarantine_status"] == "RELEASED", data["quarantine_status"]


def test_unit_serial_out_of_lot_range_returns_422(api):
    """PRD §3.1: "The `serial_number` must fall within its lot's inclusive
    `serial_start` to `serial_end` range; a serial outside that range is rejected
    with `ERR_SERIAL_OUT_OF_RANGE`."

    Design: Corner/entities/unit_serial_out_of_lot_range_returns_422
    """
    product = create_product()
    lot = create_lot(product["id"], serial_start=1, serial_end=100)
    cust = create_customer(contact_address="oor@x.com")
    resp = api.create_unit(fac.create_unit_payload(lot["id"], cust["id"], serial_number=200, sale_price_cents=5000), AGENT)
    validate_error(resp, ApiErrorId.ERR_SERIAL_OUT_OF_RANGE.value)


def test_duplicate_product_sku_returns_409(api):
    """PRD §3.1: "The `sku` is globally unique across all products; a collision is
    rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/duplicate_product_sku_returns_409
    """
    api.create_product(fac.create_product_payload(sku="P-DUP", name="First", regulator="FDA", unit_list_price_cents=5000), ADMIN)
    resp = api.create_product(fac.create_product_payload(sku="P-DUP", name="Second", regulator="CPSC", unit_list_price_cents=6000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_list_products_paginated_envelope(api):
    """PRD §2.3: "Every list response includes the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/list_products_paginated_envelope
    """
    create_product(sku="P-L1", name="L1", regulator="FDA")
    create_product(sku="P-L2", name="L2", regulator="CPSC")
    resp = api.list_products(COORD)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2, meta["total_count"]
    assert "has_more" in meta


# ===========================================================================
# Corner: endpoints
# ===========================================================================
def test_list_units_filtered_by_lot_id(api):
    """PRD §2.6: "resources are joined by explicit foreign-key fields carried in
    request bodies". PRD §4 (Units list): "List Units (filter by lot_id,
    customer_id, affected)".

    Design: Corner/endpoints/list_units_filtered_by_lot_id_reverse_reachability
    """
    product = create_product()
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="fl@x.com")
    create_unit(lot["id"], cust["id"], serial_number=1, sale_price_cents=5000)
    create_unit(lot["id"], cust["id"], serial_number=2, sale_price_cents=5000)
    resp = api.list_units(COORD, params={"lot_id": lot["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta["total_count"]
    assert all(u["lot_id"] == lot["id"] for u in data)


def test_report_submit_snapshots_agency_from_product_regulator(api):
    """PRD §3.5: "On submission the system records `signed_by_user_id` as the
    acting officer's `X-User-ID` and snapshots `agency` from the recalled
    product's `regulator`."

    Design: Corner/endpoints/report_submit_snapshots_agency_from_product_regulator
    """
    product = create_product(regulator="CPSC")
    lot = create_lot(product["id"])
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], COORD)
    report = validate_success(
        api.create_report(fac.create_report_payload(recall["id"], report_kind="INITIAL"), COORD), 201
    )
    data = validate_success(api.submit_report(report["id"], OFFICER), 200)
    assert data["agency"] == "CPSC", data["agency"]
    assert data["status"] == "SUBMITTED", data["status"]
