"""Registration, instrument intake, and read-path fundamentals (PRD §2.3, §2.4, §2.8, §3.1, §3.4)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_consignor_payload, create_customer_payload, create_instrument_payload,
    create_order_payload, order_line,
    create_customer, create_instrument, create_available_instrument,
    create_order, get_instrument,
    assert_customer, assert_instrument,
    NON_EXISTENT_UUID,
)


def test_customer_creation_defaults_applied(api, sales_associate_headers):
    """PRD §3.4: "Institutions additionally declare their `institution_type`, may carry
    the `tax_exempt` flag, the `state_contract_ceiling_cents` contract ceiling (null when
    no state contract applies), and a `credit_limit_cents` financing ceiling that defaults
    to zero; every new customer's `risk_score` starts at 700."
    PRD §2.4: "`version` (integer): a system-managed integer beginning at 1 that increments
    by exactly one on every mutation, including mutations performed as side effects of
    another resource's workflow."

    Design: Corner/entities/customer_creation_defaults_applied
    """
    created = validate_success(api.create_customer(
        create_customer_payload(full_name="Dana Default", email="dana@x.com",
                                customer_type="INDIVIDUAL"),
        sales_associate_headers), 201)
    fetched = validate_success(api.get_customer(created["id"], sales_associate_headers), 200)
    assert_customer(fetched)
    assert fetched["risk_score"] == 700, "risk_score starts at 700"
    assert fetched["credit_limit_cents"] == 0, "credit_limit_cents defaults to zero"
    assert fetched["version"] == 1, "server-minted version begins at 1"


def test_instrument_missing_required_serial_returns_invalid_request(api, store_manager_headers):
    """PRD §3.1: "A `StoreManager` intakes an instrument by providing its `serial_number`,
    `category` (one of `GRAND`, `UPRIGHT`, `DIGITAL`, or `HYBRID`), `manufacturer`, `model`,
    four-digit `year_built`, `condition_grade` (`EXCELLENT`, `GOOD`, `FAIR`, or `POOR`), and
    `acquisition_type` (`NEW`, `USED`, or `CONSIGNMENT`), together with the asking
    `list_price_cents` and a `floor_price_cents` floor below which the instrument may not
    be bid."
    PRD §2.8: "Malformed payloads, missing required fields, invalid enum values, inverted
    time windows, and principal mismatches are schema-level rejections under
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/instrument_missing_required_serial_returns_invalid_request
    """
    payload = create_instrument_payload(serial_number="SN-IGNORED")
    del payload["serial_number"]
    res = api.create_instrument(payload, store_manager_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_instrument_invalid_enum_returns_invalid_request(api, store_manager_headers):
    """PRD §3.1: "A `StoreManager` intakes an instrument by providing its `serial_number`,
    `category` (one of `GRAND`, `UPRIGHT`, `DIGITAL`, or `HYBRID`), `manufacturer`, `model`,
    four-digit `year_built`, `condition_grade` (`EXCELLENT`, `GOOD`, `FAIR`, or `POOR`), and
    `acquisition_type` (`NEW`, `USED`, or `CONSIGNMENT`), together with the asking
    `list_price_cents` and a `floor_price_cents` floor below which the instrument may not
    be bid."
    PRD §2.8: "Malformed payloads, missing required fields, invalid enum values, inverted
    time windows, and principal mismatches are schema-level rejections under
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/instrument_invalid_enum_returns_invalid_request
    """
    payload = create_instrument_payload(serial_number="SN-X-ENUM", category="SQUARE")
    res = api.create_instrument(payload, store_manager_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_instrument_duplicate_serial_rejected(api, store_manager_headers):
    """PRD §3.1: "Serial numbers are globally unique across all instruments; a duplicate
    submission is rejected with `ERR_DUPLICATE_SERIAL`."
    PRD §2.4: "`version` (integer): a system-managed integer beginning at 1 that increments
    by exactly one on every mutation, including mutations performed as side effects of
    another resource's workflow."

    Design: Corner/entities/instrument_duplicate_serial_rejected
    """
    first = validate_success(api.create_instrument(
        create_instrument_payload(serial_number="SN-DUP-1", category="UPRIGHT",
                                  manufacturer="Yamaha", model="U1", year_built=2020,
                                  condition_grade="GOOD", acquisition_type="NEW",
                                  list_price_cents=300_000, floor_price_cents=200_000),
        store_manager_headers), 201)
    res = api.create_instrument(
        create_instrument_payload(serial_number="SN-DUP-1", category="GRAND",
                                  manufacturer="Steinway", model="D", year_built=2021,
                                  condition_grade="EXCELLENT", acquisition_type="NEW",
                                  list_price_cents=900_000, floor_price_cents=700_000),
        store_manager_headers)
    validate_error(res, "ERR_DUPLICATE_SERIAL")
    after = validate_success(api.get_instrument(first["id"], store_manager_headers), 200)
    assert after["version"] == 1, "rejected duplicate must not mutate the existing instrument"


def test_consignment_without_consignor_returns_invalid_request(api, store_manager_headers):
    """PRD §3.1: "An instrument acquired as `CONSIGNMENT` must name its `consignor_id`;
    for `NEW` and `USED` stock the `consignor_id` stays null."
    PRD §2.8: "Malformed payloads, missing required fields, invalid enum values, inverted
    time windows, and principal mismatches are schema-level rejections under
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/consignment_without_consignor_returns_invalid_request
    """
    payload = create_instrument_payload(
        serial_number="SN-CONS-1", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2015, condition_grade="FAIR", acquisition_type="CONSIGNMENT",
        list_price_cents=800_000, floor_price_cents=600_000)
    res = api.create_instrument(payload, store_manager_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_institutional_customer_missing_type_returns_invalid_request(api, sales_associate_headers):
    """PRD §3.3: "institutions also declare an `institution_type` of `EDUCATION`,
    `GOVERNMENT`, `NONPROFIT`, or `CORPORATE`; individual customers carry no institution
    type)."
    PRD §2.8: "Malformed payloads, missing required fields, invalid enum values, inverted
    time windows, and principal mismatches are schema-level rejections under
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/institutional_customer_missing_type_returns_invalid_request
    """
    res = api.create_customer(
        create_customer_payload(full_name="Org Without Type", email="org@x.com",
                                customer_type="INSTITUTIONAL"),
        sales_associate_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_instrument_returns_not_found(api, store_manager_headers):
    """PRD §2.8: "Fourth, existence: every path identifier and every body foreign-key
    reference — instrument, customer, consignor, order, appraisal, bid, plan, agreement,
    warranty, referral, event, crew, technician, job, visit — must resolve to an existing
    record, validated left-to-right so the first missing identifier in the path is the one
    reported; any miss yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_instrument_returns_not_found
    """
    res = api.get_instrument(NON_EXISTENT_UUID, store_manager_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_customer_system_fields_input_ignored(api, sales_associate_headers):
    """PRD §2.4: "`version` (integer): a system-managed integer beginning at 1 that
    increments by exactly one on every mutation, including mutations performed as side
    effects of another resource's workflow."

    Design: Corner/entities/customer_system_fields_input_ignored
    """
    payload = create_customer_payload(full_name="Sid System", email="sid@x.com",
                                      customer_type="INDIVIDUAL")
    payload["version"] = 99
    created = validate_success(api.create_customer(payload, sales_associate_headers), 201)
    assert created["version"] == 1, "client-supplied system field must be ignored; version begins at 1"


def test_order_list_pagination_envelope(api, sales_associate_headers, store_manager_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items
    to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/order_list_pagination_envelope
    """
    customer = create_customer(full_name="Pia Page", email="pia@x.com")
    instrument = create_available_instrument(
        serial_number="SN-PG-1", category="DIGITAL", manufacturer="Roland", model="FP30",
        year_built=2024, list_price_cents=100_000, floor_price_cents=80_000)
    create_order(customer["id"], [order_line(instrument["id"], 100_000)])

    data, meta = validate_paginated(api.list_sales_orders(sales_associate_headers))
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0, "default offset is 0"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_immediate_visibility_of_created_resources(api, store_manager_headers):
    """PRD §3.1: "Consignment instruments may also carry `recoverable_costs_cents` (defaulting
    to 0) — preparation and restoration costs the dealer recovers off the top before
    splitting proceeds. Every instrument begins life in `IN_PREP`."
    PRD §2.4: "`version` (integer): a system-managed integer beginning at 1 that increments
    by exactly one on every mutation, including mutations performed as side effects of
    another resource's workflow."

    Design: Corner/consistency_model/immediate_visibility_of_created_resources
    """
    created = validate_success(api.create_instrument(
        create_instrument_payload(serial_number="SN-IM-1", category="HYBRID",
                                  manufacturer="Yamaha", model="N1X", year_built=2024,
                                  condition_grade="EXCELLENT", acquisition_type="NEW",
                                  list_price_cents=700_000, floor_price_cents=550_000),
        store_manager_headers), 201)
    fetched = validate_success(api.get_instrument(created["id"], store_manager_headers), 200)
    assert_instrument(fetched)
    assert fetched["status"] == "IN_PREP"
    assert fetched["version"] == 1
