"""Inbound receipt creation and inspection — PRD §3.2.

Inspection moves PENDING_INSPECTION → INSPECTED, computes
temp_chain_intact and nonconformance_reason via a strict priority
cascade.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    assert_receipt,
    create_inspected_receipt,
    create_pending_receipt,
    create_product,
    create_supplier,
    create_warehouse,
    create_zone,
    create_bin,
    create_receipt_payload,
    inspect_receipt,
    setup_basic_topology,
    setup_qualified_supplier_and_product,
    validate_error,
)


class TestReceiptCreation:

    def test_create_receipt_initial_state_pending_inspection(self, api):
        """PRD §3.2: "The receipt is born in `PENDING_INSPECTION` with
        a null `assigned_bin_id`, a null `acceptance_certificate_no`,
        a null `temp_chain_intact`, and a `nonconformance_reason` not
        yet computed."

        Claim: a fresh receipt is in PENDING_INSPECTION with the four
        named nulls.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        r = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=5,
        )
        assert r["status"] == "PENDING_INSPECTION"
        assert r.get("assigned_bin_id") is None
        assert r.get("acceptance_certificate_no") is None
        assert r.get("temp_chain_intact") is None
        assert_receipt(r)

    def test_create_receipt_with_missing_supplier_returns_err_not_found(
        self, api,
    ):
        """PRD §2.4: "Body-referenced foreign keys — for example
        `supplier_id`, `product_id`, and `customer_id` on receipt and
        shipment creation — must point at existing resources; a missing
        target yields `ERR_NOT_FOUND` (HTTP 404)."

        Claim: supplier_id pointing at unknown UUID yields
        ERR_NOT_FOUND.
        """
        topology = setup_basic_topology()
        product = create_product(required_zone_type="REFRIGERATED")
        payload = create_receipt_payload(
            supplier_id=NON_EXISTENT_UUID,
            product_id=product["id"],
            quantity_units=1,
        )
        res = api.create_receipt(
            topology["warehouse"]["id"], payload,
            TEST_USERS["receiver_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestInspectionLoggerDataValidation:

    def test_empty_logger_readings_rejected_with_err_logger_data_invalid(
        self, api,
    ):
        """PRD §3.2: "The inspect call requires that
        `carrier_logger_readings` is non-empty ... violating either of
        these surfaces as `ERR_LOGGER_DATA_INVALID` (HTTP 422)."

        Claim: empty carrier_logger_readings on inspect →
        ERR_LOGGER_DATA_INVALID / 422.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            carrier_logger_readings=[],
            quantity_units=1,
        )
        res = api.inspect_receipt(
            receipt["id"], TEST_USERS["receiver_headers"],
        )
        validate_error(res, ApiErrorId.ERR_LOGGER_DATA_INVALID.value)

    def test_non_monotonic_logger_readings_rejected(self, api):
        """PRD §3.2: "the readings array must additionally be monotonic
        in `minutes` (each entry's `minutes` is greater than or equal
        to the previous entry's), and violating either of these
        surfaces as `ERR_LOGGER_DATA_INVALID` (HTTP 422)."

        Claim: descending minutes in readings → ERR_LOGGER_DATA_INVALID.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            carrier_logger_readings=[
                {"minutes": 5, "temp_c": 5.0},
                {"minutes": 1, "temp_c": 5.0},  # NOT monotonic
            ],
            quantity_units=1,
        )
        res = api.inspect_receipt(
            receipt["id"], TEST_USERS["receiver_headers"],
        )
        validate_error(res, ApiErrorId.ERR_LOGGER_DATA_INVALID.value)


class TestInspectionTempChainComputation:

    def test_all_in_range_readings_yield_temp_chain_intact_true(self, api):
        """PRD §3.2: "the system computes `temp_chain_intact` as true
        if and only if every entry's `temp_c` falls within the
        permitted operating range of the product's `required_zone_type`".

        Claim: all REFRIGERATED-range readings → temp_chain_intact=true,
        nonconformance_reason=NONE (since visual_pass=true, supplier
        & product qualified, lot not expired).
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1,
            visual_pass=True,
            carrier_logger_readings=[
                {"minutes": 0, "temp_c": 5.0},
                {"minutes": 1, "temp_c": 5.0},
            ],
        )
        assert receipt["status"] == "INSPECTED"
        assert receipt["temp_chain_intact"] is True
        assert receipt["nonconformance_reason"] == "NONE"

    def test_out_of_range_reading_yields_temp_excursion(self, api):
        """PRD §3.2: nonconformance_reason cascade tail — "TEMP_EXCURSION
        (`temp_chain_intact` is false)".

        Claim: any logger reading outside the REFRIGERATED 2..8 band
        on an otherwise-qualified receipt → temp_chain_intact=false
        and nonconformance_reason=='TEMP_EXCURSION'.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1,
            visual_pass=True,
            carrier_logger_readings=[
                {"minutes": 0, "temp_c": 5.0},
                # 12 C is above the REFRIGERATED target_temp_high_c==8.
                {"minutes": 1, "temp_c": 12.0},
            ],
        )
        assert receipt["temp_chain_intact"] is False
        assert receipt["nonconformance_reason"] == "TEMP_EXCURSION"


class TestNonconformancePriorityCascade:
    """PRD §3.2 priority cascade:
    UNQUALIFIED_SUPPLIER > UNQUALIFIED_PRODUCT > EXPIRED_ON_ARRIVAL >
    VISUAL_FAIL > TEMP_EXCURSION; first match wins, else NONE.
    """

    def test_unqualified_supplier_wins_priority(self, api):
        """PRD §3.2: "The priority order is: `UNQUALIFIED_SUPPLIER`
        (the supplier's `qualified` flag is false or
        `qualification_expiry_minutes` is less than or equal to the
        warehouse's `clock_minutes`), then `UNQUALIFIED_PRODUCT` ...,
        then `EXPIRED_ON_ARRIVAL` ..., then `VISUAL_FAIL` ..., then
        `TEMP_EXCURSION`."

        Claim: supplier with qualified=false AND product with
        qualified=false AND visual_pass=false → wins UNQUALIFIED_SUPPLIER.
        """
        topology = setup_basic_topology()
        supplier = create_supplier(qualified=False,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED", qualified=False,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        assert receipt["nonconformance_reason"] == "UNQUALIFIED_SUPPLIER"

    def test_unqualified_product_when_supplier_ok(self, api):
        """Claim: supplier qualified, product qualified=false → reason
        is UNQUALIFIED_PRODUCT.
        """
        topology = setup_basic_topology()
        supplier, _ = setup_qualified_supplier_and_product()
        bad_product = create_product(
            required_zone_type="REFRIGERATED", qualified=False,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], bad_product["id"],
            quantity_units=1, visual_pass=False,
        )
        assert receipt["nonconformance_reason"] == "UNQUALIFIED_PRODUCT"

    def test_expired_on_arrival_when_supplier_and_product_ok(self, api):
        """PRD §3.2: cascade middle — "`EXPIRED_ON_ARRIVAL` (the lot's
        `expiry_minutes` is less than or equal to the warehouse's
        `clock_minutes`)".

        Claim: supplier+product qualified, but expiry_minutes <=
        warehouse.clock_minutes → reason is EXPIRED_ON_ARRIVAL even
        with visual_pass=false.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        # Advance clock past 0 so we can submit an expired lot.
        advance_clock(topology["warehouse"]["id"], 100)
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
            # expiry_minutes <= warehouse.clock_minutes (which is 100
            # after the advance) triggers EXPIRED_ON_ARRIVAL.
            expiry_minutes=50,
        )
        assert receipt["nonconformance_reason"] == "EXPIRED_ON_ARRIVAL"

    def test_visual_fail_when_only_visual_pass_false(self, api):
        """Claim: supplier+product qualified, lot fresh, only
        visual_pass=false → reason is VISUAL_FAIL.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        assert receipt["nonconformance_reason"] == "VISUAL_FAIL"
