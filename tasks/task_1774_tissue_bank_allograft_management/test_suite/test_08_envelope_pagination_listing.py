"""Response envelope, pagination, listing semantics, and the not-found
vocabulary."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_shipment,
    create_supplier_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_manifest_item,
    setup_supplier_and_freezer,
    validate_error,
    validate_paginated,
)

QM = TEST_USERS["quality_headers"]
COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestPagination:
    def test_supplier_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults to
        0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/supplier_list_pagination_envelope
        """
        for i in range(1, 13):
            get_success_data(
                api.create_supplier(
                    create_supplier_payload(
                        legal_name=f"S{i:02d}", license_number=f"LIC-{i:03d}"
                    ),
                    QM,
                )
            )
        page1, meta1 = validate_paginated(api.list_suppliers(QM))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(api.list_suppliers(QM, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["has_more"] is False
        resp = api.list_suppliers(QM, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestListingSemantics:
    def test_unit_list_filter_combination_and_serial_sort(self, api):
        """PRD §3.4: "The full unit roster is sorted by `serial_number`
        ascending and supports the optional filters `supplier_id`,
        `freezer_id`, `shipment_id`, `status`, `tissue_type`, `lot_number`, and
        `implanted_case_id`; the per-freezer unit listing follows the same
        serial ordering."

        Design: Corner/endpoints/unit_list_filter_combination_and_serial_sort
        """
        supplier, freezer = setup_supplier_and_freezer()
        # Manifest deliberately lists serials out of order.
        create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-002"),
                make_manifest_item(serial_number="U-001"),
            ],
        )
        create_shipment(
            supplier["id"],
            freezer["id"],
            [make_manifest_item(tissue_type="SKIN", lot_number="L2",
                                serial_number="U-101", unit_cost_cents=7000)],
        )
        data, meta = validate_paginated(
            api.list_tissue_units(
                QM, params={"status": "QUARANTINED", "tissue_type": "BONE"}
            )
        )
        assert meta["total_count"] == 2
        assert [u["serial_number"] for u in data] == ["U-001", "U-002"]
        assert all(u["tissue_type"] == "BONE" for u in data)

    def test_fk_reverse_reachability_subresources(self, api):
        """PRD §3.1: "the document list is ordered by `created_at` ascending
        with ties broken by `document_ref` ascending, and supports the optional
        `doc_type` filter."
        PRD §3.4: "the per-freezer unit listing follows the same serial
        ordering."
        PRD §3.4: "The full unit roster is sorted by `serial_number` ascending
        and supports the optional filters `supplier_id`, `freezer_id`,
        `shipment_id`, `status`, `tissue_type`, `lot_number`, and
        `implanted_case_id`"

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        supplier, freezer = setup_supplier_and_freezer()
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ],
        )
        docs = get_success_data(api.list_supplier_documents(supplier["id"], QM))
        assert len(docs) == 2
        supplier_shipments = get_success_data(
            api.list_supplier_shipments(supplier["id"], QM)
        )
        assert len(supplier_shipments) == 1
        assert supplier_shipments[0]["id"] == shipment["id"]
        freezer_units = get_success_data(api.list_freezer_units(freezer["id"], QM))
        assert len(freezer_units) == 2
        assert freezer_units[0]["serial_number"] == "U-001"
        freezer_shipments = get_success_data(api.list_freezer_shipments(freezer["id"], QM))
        assert len(freezer_shipments) == 1
        by_supplier = get_success_data(
            api.list_tissue_units(QM, params={"supplier_id": supplier["id"]})
        )
        assert len(by_supplier) == 2
        assert {u["id"] for u in by_supplier} == {u["id"] for u in freezer_units}


class TestResponseEnvelope:
    def test_response_envelope_shape_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        ok = api.get_supplier(supplier["id"], QM)
        assert ok.status_code == 200
        body = ok.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        err = api.get_supplier(NON_EXISTENT_UUID, QM)
        assert err.status_code == 404
        ebody = err.json()
        assert ebody["response_type"] == "error"
        assert ebody["data"]["error_id"] == "ERR_SUPPLIER_NOT_FOUND"
        assert isinstance(ebody["data"]["message"], str) and ebody["data"]["message"]


class TestNotFoundVocabulary:
    def test_resource_not_found_family_returns_specific_404(self, api):
        """PRD §2.6: "The full not-found vocabulary is:
        `ERR_SUPPLIER_NOT_FOUND` for suppliers, `ERR_DOCUMENT_NOT_FOUND` for
        supplier documents, `ERR_SHIPMENT_NOT_FOUND` for shipments,
        `ERR_UNIT_NOT_FOUND` for tissue units, `ERR_FREEZER_NOT_FOUND` for
        freezers, `ERR_EXCURSION_NOT_FOUND` for temperature excursions,
        `ERR_CASE_NOT_FOUND` for implant cases, `ERR_RESERVATION_NOT_FOUND` for
        reservations, `ERR_RECALL_NOT_FOUND` for recalls,
        `ERR_ADVERSE_REACTION_NOT_FOUND` for adverse reaction cases,
        `ERR_POLICY_NOT_FOUND` for par-level policies, and
        `ERR_DISPOSITION_NOT_FOUND` for disposition records."

        Design: Corner/entities/resource_not_found_family_returns_specific_404
        """
        validate_error(api.get_tissue_unit(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_UNIT_NOT_FOUND)
        validate_error(api.get_freezer(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_FREEZER_NOT_FOUND)
        validate_error(api.get_supplier(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_SUPPLIER_NOT_FOUND)

    def test_not_found_family_nested_and_leaf(self, api):
        """PRD §2.6: "Endpoints whose paths contain more than one identifier
        validate those identifiers sequentially from left to right — the parent
        segment before the child segment — and the request is rejected with the
        404 error corresponding to the first identifier that does not resolve."
        PRD §2.6: "A verification call naming a document under a nonexistent
        supplier therefore fails with `ERR_SUPPLIER_NOT_FOUND` before the
        document identifier `docId` is ever examined; an unknown document under
        a real supplier fails with `ERR_DOCUMENT_NOT_FOUND`."

        Design: Corner/errors/error_not_found_family_nested_and_leaf
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        # Parent segment validated before the child segment.
        validate_error(
            api.verify_document(NON_EXISTENT_UUID, NON_EXISTENT_UUID, QM),
            ApiErrorId.ERR_SUPPLIER_NOT_FOUND,
        )
        validate_error(
            api.verify_document(supplier["id"], NON_EXISTENT_UUID, QM),
            ApiErrorId.ERR_DOCUMENT_NOT_FOUND,
        )
        validate_error(api.get_recall(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_RECALL_NOT_FOUND)
        validate_error(api.get_excursion(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_EXCURSION_NOT_FOUND)
        validate_error(api.get_adverse_reaction(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_ADVERSE_REACTION_NOT_FOUND)
        validate_error(api.get_par_policy(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_POLICY_NOT_FOUND)
        validate_error(api.get_disposition_record(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_DISPOSITION_NOT_FOUND)
        validate_error(api.get_shipment(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_SHIPMENT_NOT_FOUND)
        validate_error(api.get_implant_case(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_CASE_NOT_FOUND)
        validate_error(api.get_reservation(NON_EXISTENT_UUID, QM),
                       ApiErrorId.ERR_RESERVATION_NOT_FOUND)


class TestAuthHeaders:
    def test_supplier_list_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value outside these five, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/supplier_list_missing_auth_header_returns_400
        """
        resp = api.list_suppliers({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
