"""Authentication, role-based access control, and resource-specific 404s."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_approved_supplier,
    create_entry,
    create_product_label_payload,
    create_supplier_payload,
    get_success_data,
    validate_error,
    validate_success,
)

CM = TEST_USERS["compliance_manager_headers"]
IC = TEST_USERS["import_coordinator_headers"]
RI = TEST_USERS["receiving_inspector_headers"]
QA = TEST_USERS["qa_tech_headers"]
PS = TEST_USERS["processing_supervisor_headers"]

MISSING = NON_EXISTENT_UUID


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD: "Failure to provide both headers, or providing a role not among
        those listed, will result in an `ERR_UNAUTHENTICATED` error
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_supplier(
            {"legal_name": "X", "country_code": "US",
             "facility_registration_number": "FRN-V01"},
            {},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_supplier_create_by_inspector_unauthorized(self, api):
        """PRD: "| POST | `/seafood/suppliers` | Register a foreign supplier |
        ComplianceManager |" and "Access to specific operations is restricted
        by role; an attempt to perform an action outside the caller's
        designated role will be rejected with an `ERR_UNAUTHORIZED_ROLE` error
        (HTTP 403)."

        Design: Corner/rbac/supplier_create_by_inspector_unauthorized
        """
        resp = api.create_supplier(
            create_supplier_payload(legal_name="X", country_code="US",
                                    facility_registration_number="FRN-R01"),
            RI,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_peer_roles_cannot_cross_unauthorized(self, api):
        """PRD: "| POST | `/seafood/import-entries/{id}/file-prior-notice` |
        File FDA prior notice (supplier APPROVED; lead-time window) |
        ImportCoordinator |"
        PRD: "| POST | `/seafood/product-labels/{id}/approve` | Approve a DRAFT
        label; supersedes referenced label | ComplianceManager |"
        Calls by other roles are rejected ERR_UNAUTHORIZED_ROLE (HTTP 403).

        Design: Corner/rbac/peer_roles_cannot_cross_unauthorized
        """
        supplier = create_approved_supplier(frn="FRN-R02")
        entry = create_entry(supplier["id"], entry_number="E-R02",
                             species="TUNA", transport_mode="VESSEL",
                             goods_value_cents=1000, freight_cost_cents=0,
                             total_weight_kg=10)
        label = validate_success(api.create_product_label(
            create_product_label_payload(species="COD"), CM), 201)

        resp1 = api.file_prior_notice(entry["id"], PS)
        validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp2 = api.approve_product_label(label["id"], IC)
        validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        entry_after = validate_success(api.get_import_entry(entry["id"], IC))
        assert entry_after["status"] == "DRAFT"
        label_after = validate_success(api.get_product_label(label["id"], CM))
        assert label_after["status"] == "DRAFT"


class TestNotFound:
    def test_supplier_not_found_returns_404(self, api):
        """PRD: "The request is rejected immediately with a `404 Not Found`
        error carrying the resource-specific error ID corresponding to the
        *first* identifier that does not correspond to an existing resource."
        PRD §5: `ERR_SUPPLIER_NOT_FOUND` — 404.

        Design: Corner/entities/supplier_not_found_returns_404
        """
        resp = api.get_supplier("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", CM)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_FOUND)

    def test_not_found_variants_across_resources(self, api):
        """PRD §5 Error Code Catalogue: `ERR_IMPORT_ENTRY_NOT_FOUND`,
        `ERR_RECEIPT_LOT_NOT_FOUND`, `ERR_PROCESSING_BATCH_NOT_FOUND`,
        `ERR_BATCH_INPUT_NOT_FOUND`, `ERR_SPECIES_VERIFICATION_NOT_FOUND`,
        `ERR_PRODUCT_LABEL_NOT_FOUND`, `ERR_FINISHED_LOT_NOT_FOUND`,
        `ERR_CORRECTIVE_ACTION_NOT_FOUND`, `ERR_RECALL_NOT_FOUND` — all 404.
        PRD: "The request is rejected immediately with a `404 Not Found` error
        carrying the resource-specific error ID."

        Design: Corner/errors/not_found_variants_across_resources
        """
        validate_error(api.get_import_entry(MISSING, IC),
                       ApiErrorId.ERR_IMPORT_ENTRY_NOT_FOUND)
        validate_error(api.get_receipt_lot(MISSING, IC),
                       ApiErrorId.ERR_RECEIPT_LOT_NOT_FOUND)
        validate_error(api.get_processing_batch(MISSING, PS),
                       ApiErrorId.ERR_PROCESSING_BATCH_NOT_FOUND)
        validate_error(api.delete_batch_input(MISSING, PS),
                       ApiErrorId.ERR_BATCH_INPUT_NOT_FOUND)
        validate_error(api.resolve_species_verification(
            MISSING, "REJECT_LOT", QA),
            ApiErrorId.ERR_SPECIES_VERIFICATION_NOT_FOUND)
        validate_error(api.approve_product_label(MISSING, CM),
                       ApiErrorId.ERR_PRODUCT_LABEL_NOT_FOUND)
        validate_error(api.get_finished_lot(MISSING, CM),
                       ApiErrorId.ERR_FINISHED_LOT_NOT_FOUND)
        validate_error(api.investigate_corrective_action(MISSING, CM),
                       ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND)
        validate_error(api.get_recall(MISSING, CM),
                       ApiErrorId.ERR_RECALL_NOT_FOUND)
