"""
Resource shapes: what a create returns, what a read returns, what defaults and
derived quantities land on a row, and which malformed or dangling inputs are
refused before a row is ever written.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_fields_equal,
    assert_instant_equals,
    assert_pagination_meta,
)
from test_helpers.constants import CLOCK_BASE_UTC
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    make_lender_headers,
    make_warehouse_operator_headers,
)

UNUSED_WAREHOUSE_ID = "00000000-0000-4000-8000-000000000000"
UNUSED_BIN_ID = "00000000-0000-4000-8000-0000000000bb"


class TestWarehouseReceiptShape:
    def test_issuing_a_receipt_returns_every_declared_field(self, api, base_pre):
        """
        The 201 body carries the full receipt: the three identifiers copied off
        the ticket's agreement and bin, the 949-bushel quantity, the pinned
        420-cent face price, a 5694-cent receiving charge (949 x 6), a
        provisional storage charge that is the 500-cent minimum rather than the
        332 cents one day actually accrues, and the untouched collateral fields.

        PRD: "`receiving_charge_cents` is the quantity at issuance multiplied by
        the agreement's `receiving_charge_cents_per_bushel`, rounded half up to
        whole cents, and becomes a fixed component of the warehouseman's lien for
        the life of the receipt."

        PRD: "If the raw charge is exactly zero the storage charge is zero;
        otherwise the storage charge is the greater of the raw charge and a
        500-cent (five dollar) minimum."

        Design: Corner/entities/receipt_creation_returns_full_declared_field_set
        """
        headers = base_pre["operator_headers"]
        warehouse = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], headers), 200
        )

        response = api.create_receipt(
            f.receipt_payload(
                base_pre["ticket_id"], base_pre["depositor_id"], warehouse["version"]
            ),
            headers,
        )
        receipt = get_success_data(response, 201)
        body = response.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object"

        assert_fields_equal(
            receipt,
            {
                "warehouse_id": base_pre["warehouse_id"],
                "storage_agreement_id": base_pre["agreement_id"],
                "bin_id": base_pre["bin_id"],
                "quantity_bushels": 949,
                "grade": "US_NO_1",
                "moisture_pct": 15.0,
                "face_price_cents_per_bushel": 420,
                "receiving_charge_cents": 5694,
                "provisional_storage_charge_cents": 500,
                "receipt_state": "ISSUED",
                "encumbrance_state": "UNENCUMBERED",
                "quality_flag": "SOUND",
                "registry_control_party_id": None,
                "transfer_log": [],
                "version": 1,
            },
        )
        assert_instant_equals(receipt["issued_at"], CLOCK_BASE_UTC, "issued_at")

        ticket = get_success_data(
            api.get_deposit_ticket(base_pre["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "RECEIPTED"

    def test_reading_a_receipt_returns_the_stored_row_without_bumping_its_version(
        self, api, base_full
    ):
        """
        The holder reads back exactly the row the issuance minted — receipt
        number WR-0001 over 949 bushels — and the read itself is not a mutation,
        so the version is still 1.

        PRD: "`version` (integer): a counter that increments by one on every
        mutation of the row."

        Design: Corner/entities/receipt_retrieval_returns_stored_receipt
        """
        response = api.get_receipt(
            base_full["receipt_id"], base_full["depositor_headers"]
        )
        receipt = get_success_data(response, 200)

        assert response.json()["response_type"] == "object"
        assert_fields_equal(
            receipt,
            {
                "receipt_number": "WR-0001",
                "quantity_bushels": 949,
                "version": 1,
            },
        )


class TestDepositTicketListing:
    @pytest.fixture
    def three_tickets_on_one_bin(self, base_full, weighed_ticket):
        """The receipted load plus two further weighed loads on later days."""
        second = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-06T09:00:00Z",
            fill_end_at="2026-08-06T11:00:00Z",
        )
        third = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=600,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-07T09:00:00Z",
            fill_end_at="2026-08-07T11:00:00Z",
        )
        return {"second_id": second["id"], "third_id": third["id"]}

    def test_a_two_row_page_reports_the_full_total_count_and_more_to_come(
        self, api, base_full, three_tickets_on_one_bin
    ):
        """
        Three tickets sit on bin B1. A page of two reports the full total of
        three with has_more true, and the next page returns the single remaining
        row with has_more false.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope described in §2.2."

        Design: Corner/entities/deposit_ticket_listing_paginates_with_total_count_and_has_more
        """
        params = {"bin_id": base_full["bin_id"], "limit": 2, "offset": 0}
        first_page = api.list_deposit_tickets(params, base_full["operator_headers"])
        rows, meta = validate_paginated(first_page)

        assert first_page.json()["response_type"] == "array"
        assert len(rows) == 2
        assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

        rows, meta = validate_paginated(
            api.list_deposit_tickets(
                {"bin_id": base_full["bin_id"], "limit": 2, "offset": 2},
                base_full["operator_headers"],
            )
        )
        assert len(rows) == 1
        assert_pagination_meta(meta, offset=2, total_count=3, has_more=False)

    def test_the_two_unaccepted_loads_hold_soft_reservations_on_the_bin(
        self, api, base_full, three_tickets_on_one_bin
    ):
        """
        Both later loads are still merely WEIGHED, so their 500 and 600 net
        bushels together reserve 1100 bushels of inbound space.

        PRD: "A new ticket lands in `ticket_state` `WEIGHED`, with `accepted_at`
        null, and raises the bin's `scheduled_inbound_bushels` by its
        `net_bushels` as a soft reservation."

        Design: Corner/entities/deposit_ticket_listing_paginates_with_total_count_and_has_more
        """
        headers = base_full["operator_headers"]
        for ticket_id in (
            three_tickets_on_one_bin["second_id"],
            three_tickets_on_one_bin["third_id"],
        ):
            ticket = get_success_data(api.get_deposit_ticket(ticket_id, headers), 200)
            assert ticket["ticket_state"] == "WEIGHED"

        storage_bin = get_success_data(
            api.get_bin(base_full["bin_id"], headers), 200
        )
        assert storage_bin["scheduled_inbound_bushels"] == 1100


class TestResolutionFailures:
    def test_an_unused_warehouse_id_is_a_404_not_an_empty_success(
        self, api, base_clock
    ):
        """
        A syntactically valid UUID that names no warehouse fails resolution, and
        a failed resolution is an error response, never a 200 with nothing in it.

        PRD: "The full set of resolution failures is
        `ERR_WAREHOUSE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_TICKET_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` and `ERR_PARTY_NOT_FOUND`, each HTTP 404."

        Design: Corner/entities/warehouse_not_found_on_unknown_id
        """
        response = api.get_warehouse(UNUSED_WAREHOUSE_ID, REGULATOR_HEADERS)

        validate_error(response, E.ERR_WAREHOUSE_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"

    def test_an_action_endpoint_resolves_its_path_id_before_its_body(
        self, api, licensed_warehouse
    ):
        """
        A condition assessment aimed at a bin that does not exist is a 404 even
        though the body it carries is perfectly well-formed.

        PRD: "In a path such as `/warehouses/{warehouse_id}/position-summary` or
        `/bins/{bin_id}/condition-assessment` the path identifier is resolved
        before any body field is examined."

        Design: Corner/entities/bin_not_found_on_condition_assessment
        """
        warehouse = licensed_warehouse()

        response = api.assess_bin_condition(
            UNUSED_BIN_ID,
            f.condition_assessment_payload(13.0, 60),
            make_warehouse_operator_headers(warehouse["id"]),
        )

        validate_error(response, E.ERR_BIN_NOT_FOUND, 404)

    def test_a_body_borne_receipt_reference_is_existence_checked_too(
        self, api, base_full
    ):
        """
        The delivery-order request names its receipt in the body rather than the
        path, and that reference is resolved before any quantity or lane rule
        runs.

        PRD: "The first identifier that fails to resolve determines the response,
        so a lien request naming a non-existent receipt and a non-existent lender
        party reports `ERR_RECEIPT_NOT_FOUND` rather than `ERR_PARTY_NOT_FOUND`."

        Design: Corner/entities/receipt_not_found_on_delivery_order_creation
        """
        response = api.create_delivery_order(
            f.delivery_order_payload(
                NON_EXISTENT_UUID,
                100,
                "2026-08-20T09:00:00Z",
                "2026-08-20T11:00:00Z",
            ),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_RECEIPT_NOT_FOUND, 404)


class TestRequestShapeRefusals:
    def test_an_agreement_without_its_free_day_count_is_refused(
        self, api, licensed_warehouse, new_producer
    ):
        """
        `free_storage_days` is a required commercial term with no default, so an
        agreement that omits it is a request-shape failure and no agreement row
        is written.

        PRD: "Request-shape failures — a missing required field, an enum value
        outside its declared set, an integer outside its declared bounds, a
        malformed ISO date or datetime, or an interval whose end instant is not
        strictly after its start instant — are all reported as `ERR_VALIDATION`
        (HTTP 422)."

        Design: Corner/entities/storage_agreement_missing_free_storage_days_rejected
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        headers = make_warehouse_operator_headers(warehouse["id"])

        response = api.create_storage_agreement(
            f.storage_agreement_payload(
                warehouse["id"], producer["id"], free_storage_days=None
            ),
            headers,
        )

        validate_error(response, E.ERR_VALIDATION, 422)

        _rows, meta = validate_paginated(
            api.list_storage_agreements({"warehouse_id": warehouse["id"]}, headers)
        )
        assert meta["total_count"] == 0

    def test_a_licence_programme_outside_the_declared_pair_is_refused(
        self, api, base_clock
    ):
        """
        `license_program` admits only STATE and FEDERAL, so COUNTY is refused as
        a request-shape failure and the application is never filed.

        PRD: "Request-shape failures — a missing required field, an enum value
        outside its declared set, an integer outside its declared bounds, a
        malformed ISO date or datetime, or an interval whose end instant is not
        strictly after its start instant — are all reported as `ERR_VALIDATION`
        (HTTP 422)."

        Design: Corner/entities/warehouse_license_program_rejects_unknown_enum_member
        """
        response = api.create_warehouse(
            f.warehouse_payload(license_program="COUNTY"), REGULATOR_HEADERS
        )

        validate_error(response, E.ERR_VALIDATION, 422)

        _rows, meta = validate_paginated(api.list_warehouses({}, REGULATOR_HEADERS))
        assert meta["total_count"] == 0

    def test_an_appointment_that_ends_before_it_starts_is_refused(
        self, api, base_full
    ):
        """
        The interval bound is checked as request shape, ahead of the lane search,
        so no lane is taken and no grain is held.

        PRD: "The request names the `receipt_id`, the `requested_bushels`
        demanded out of store (at least one), and the `appointment_start_at` and
        `appointment_end_at` bounds of the loadout appointment, the end strictly
        after the start."

        Design: Corner/entities/delivery_order_appointment_end_before_start_rejected
        """
        response = api.create_delivery_order(
            f.delivery_order_payload(
                base_full["receipt_id"],
                100,
                "2026-08-20T11:00:00Z",
                "2026-08-20T09:00:00Z",
            ),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_VALIDATION, 422)

        storage_bin = get_success_data(
            api.get_bin(base_full["bin_id"], base_full["operator_headers"]), 200
        )
        assert storage_bin["held_bushels"] == 0


class TestDefaultsAndDerivedFields:
    def test_a_party_registered_without_a_credit_line_reads_zero_not_null(
        self, api, base_clock
    ):
        """
        The optional credit line defaults to zero, and the two derived credit
        figures follow it down to zero rather than to null.

        PRD: "A newly registered party starts with `committed_advance_cents` at
        zero and therefore `available_credit_cents` equal to its credit line."

        Design: Corner/entities/party_credit_line_defaults_to_zero
        """
        party = get_success_data(
            api.create_party(f.producer_payload(), REGULATOR_HEADERS), 201
        )

        assert_fields_equal(
            party,
            {
                "credit_line_cents": 0,
                "committed_advance_cents": 0,
                "available_credit_cents": 0,
                "settlement_balance_cents": 0,
            },
        )

    def test_a_bins_four_derived_quantities_reconcile_after_a_delivery_hold(
        self, api, base_full
    ):
        """
        With 949 bushels stored, 400 promised to a requested delivery order and
        nothing inbound, availability is the difference, 549. The blended grade
        is the worst accepted grade in the bin and the 11 shrink bushels lost at
        acceptance are still on the audit accumulator.

        PRD: "Four derived quantities describe a bin's position at any instant:
        `stored_bushels` is the physical inventory actually on hand;
        `held_bushels` is the sum of `requested_bushels` across delivery orders
        drawn from this bin whose `delivery_state` is `REQUESTED` or `LOADED`;
        `available_bushels` is stored less held; and `scheduled_inbound_bushels`
        is the sum of `net_bushels` across tickets destined for this bin that are
        still merely `WEIGHED`."

        Design: Corner/entities/bin_derived_quantities_reconcile_after_accept_and_delivery_hold
        """
        order = get_success_data(
            api.create_delivery_order(
                f.delivery_order_payload(
                    base_full["receipt_id"],
                    400,
                    "2026-08-20T09:00:00Z",
                    "2026-08-20T11:00:00Z",
                ),
                base_full["depositor_headers"],
            ),
            201,
        )
        assert order["lane_index"] == 0

        headers = base_full["operator_headers"]
        storage_bin = get_success_data(api.get_bin(base_full["bin_id"], headers), 200)
        assert_fields_equal(
            storage_bin,
            {
                "stored_bushels": 949,
                "held_bushels": 400,
                "available_bushels": 549,
                "scheduled_inbound_bushels": 0,
                "cumulative_shrink_bushels": 11,
                "blended_grade": "US_NO_1",
            },
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert warehouse["system_physical_bushels"] == 949

    def test_a_new_deposit_ticket_stamps_its_own_state_and_settlement_variant(
        self, api, licensed_warehouse, new_producer, new_agreement, new_bin
    ):
        """
        None of these values is a client input: the ticket lands WEIGHED with no
        acceptance instant and no rejection reason, its settlement variant is
        taken from the agreement's COMMINGLED storage kind, and both timestamps
        read the logical clock.

        PRD: "A new ticket lands in `ticket_state` `WEIGHED`, with `accepted_at`
        null, and raises the bin's `scheduled_inbound_bushels` by its
        `net_bushels` as a soft reservation."

        PRD: "Which of two settlement variants applies is fixed at weigh-in and
        recorded on the ticket as `settlement_variant`, copied from the
        agreement's `storage_kind`:"

        Design: Corner/entities/deposit_ticket_system_fields_are_server_generated
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])

        ticket = get_success_data(
            api.create_deposit_ticket(
                f.deposit_ticket_payload(agreement["id"], storage_bin["id"]),
                make_warehouse_operator_headers(warehouse["id"]),
            ),
            201,
        )

        assert_fields_equal(
            ticket,
            {
                "ticket_state": "WEIGHED",
                "accepted_at": None,
                "rejection_reason": None,
                "settlement_variant": "COMMINGLED",
                "version": 1,
            },
        )
        assert_instant_equals(ticket["created_at"], CLOCK_BASE_UTC, "created_at")
        assert_instant_equals(ticket["updated_at"], CLOCK_BASE_UTC, "updated_at")


class TestSlotIntegrity:
    def test_a_soybean_bin_cannot_take_a_corn_agreements_load(
        self, api, licensed_warehouse, new_producer, new_agreement, new_bin
    ):
        """
        The commodity mismatch is caught ahead of the grade and capacity tests
        that this load would have passed, and the rejected load reserves nothing.

        PRD: "The bin must belong to the agreement's warehouse, or the request is
        rejected with `ERR_PARTY_KIND_INVALID`; and the bin's `commodity` must
        equal the agreement's `commodity`, or the request is rejected with
        `ERR_COMMODITY_MISMATCH`."

        Design: Corner/entities/bin_commodity_must_match_agreement_commodity
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        headers = make_warehouse_operator_headers(warehouse["id"])
        soybean_bin = new_bin(
            warehouse["id"], bin_code="B2", commodity="SOYBEANS"
        )

        response = api.create_deposit_ticket(
            f.deposit_ticket_payload(agreement["id"], soybean_bin["id"]), headers
        )

        validate_error(response, E.ERR_COMMODITY_MISMATCH, 422)

        storage_bin = get_success_data(api.get_bin(soybean_bin["id"], headers), 200)
        assert storage_bin["scheduled_inbound_bushels"] == 0

    def test_the_lender_slot_refuses_a_producer_depositor_party(self, api, base_full):
        """
        The caller supplies its own party id, so the ownership requirement is
        met; the request still fails because a PRODUCER_DEPOSITOR cannot occupy
        the lender slot, and no lien is recorded against the receipt.

        PRD: "`party_kind` is a hard gate on which slot a party may fill, and a
        party supplied for a slot its kind does not fit is rejected with
        `ERR_PARTY_KIND_INVALID`."

        Design: Corner/entities/lien_lender_slot_rejects_producer_depositor_party
        """
        depositor_id = base_full["depositor_id"]

        response = api.create_collateral_lien(
            f.collateral_lien_payload(base_full["receipt_id"], depositor_id),
            make_lender_headers(depositor_id),
        )

        validate_error(response, E.ERR_PARTY_KIND_INVALID, 422)

        _rows, meta = validate_paginated(
            api.list_collateral_liens(
                {"receipt_id": base_full["receipt_id"]}, base_full["operator_headers"]
            )
        )
        assert meta["total_count"] == 0

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["encumbrance_state"] == "UNENCUMBERED"
