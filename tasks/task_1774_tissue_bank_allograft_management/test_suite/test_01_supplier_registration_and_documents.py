"""Supplier onboarding: registration defaults, regulatory documents,
qualification gates, segregation of duties, and terminal lockdown."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_document_payload,
    create_implant_case_payload,
    create_recall_payload,
    create_supplier_payload,
    get_success_data,
    is_valid_uuid,
    setup_qualified_supplier,
    validate_error,
    validate_success,
)

QM = TEST_USERS["quality_headers"]
CO = TEST_USERS["compliance_headers"]
CO2 = TEST_USERS["compliance2_headers"]
SURG = TEST_USERS["surgeon_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestSupplierCreation:
    def test_supplier_create_applies_defaults(self, api):
        """PRD §3.1: "New suppliers begin in `PENDING_QUALIFICATION` with both
        qualification scores at 100 and `suspended_at` unset — it remains null
        until the supplier's first suspension."
        PRD §2.5: "`version` is an integer that starts at its initial value on
        creation and increments by one on every mutation of the resource."

        Design: Corner/entities/supplier_create_applies_defaults
        """
        data = validate_success(
            api.create_supplier(
                create_supplier_payload(
                    legal_name="Acme Tissue Source", license_number="LIC-001"
                ),
                QM,
            ),
            201,
        )
        assert data["status"] == "PENDING_QUALIFICATION"
        assert data["qualification_score_provisional"] == 100
        assert data["qualification_score_final"] == 100
        assert data["suspended_at"] is None
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

    def test_supplier_create_missing_license_number_rejected(self, api):
        """PRD §2.8: "4. **Request shape** — required fields present, types
        correct, enum members valid, strings at or above their minimum lengths,
        arrays non-empty where required, and window or range sanity:
        `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, and
        `ERR_INVALID_TEMP_RANGE` (all 400)."
        PRD §3.1: "A `QualityManager` onboards a new tissue source by
        registering a supplier with its `legal_name` and `license_number`."

        Design: Corner/entities/supplier_create_missing_required_returns_invalid_request
        """
        resp = api.create_supplier({"legal_name": "No License Labs"}, QM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDocumentLifecycle:
    def test_document_verify_twice_rejected(self, api):
        """PRD §3.1: "Both actions are defined only from `SUBMITTED` — acting
        on a document in any other status fails with
        `ERR_DOCUMENT_INVALID_STATE`."

        Design: Corner/state_machines/document_verify_twice_rejected
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        doc = get_success_data(
            api.create_supplier_document(supplier["id"], create_document_payload(), QM)
        )
        verified = validate_success(
            api.verify_document(supplier["id"], doc["id"], QM)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "qm-1"

        resp = api.verify_document(supplier["id"], doc["id"], TEST_USERS["quality2_headers"])
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE)
        after = validate_success(
            api.get_supplier(supplier["id"], QM)  # supplier read is unaffected
        )
        assert after["status"] == "PENDING_QUALIFICATION"

    def test_supplier_approve_when_already_qualified_rejected(self, api):
        """PRD §3.1: "A `ComplianceOfficer` qualifies a supplier whose `status`
        is `PENDING_QUALIFICATION` or `SUSPENDED`; any other starting state is
        rejected with `ERR_SUPPLIER_INVALID_STATE`."

        Design: Corner/state_machines/supplier_approve_when_already_qualified_rejected
        """
        supplier = setup_qualified_supplier()
        assert supplier["status"] == "QUALIFIED"
        resp = api.approve_supplier(supplier["id"], CO)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_INVALID_STATE)
        after = validate_success(api.get_supplier(supplier["id"], CO))
        assert after["status"] == "QUALIFIED"

    def test_supplier_disqualified_terminal_lockdown(self, api):
        """PRD §3.1: "Finally, disqualification is permanent: a
        `ComplianceOfficer` may move a supplier from `PENDING_QUALIFICATION` or
        `SUSPENDED` to the terminal `DISQUALIFIED` state, and any mutation
        attempted against a `DISQUALIFIED` supplier — including a fresh
        approval — is rejected with `ERR_SUPPLIER_INVALID_STATE`."

        Design: Corner/state_machines/supplier_disqualified_terminal_lockdown
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        disqualified = validate_success(api.disqualify_supplier(supplier["id"], CO))
        assert disqualified["status"] == "DISQUALIFIED"

        validate_error(
            api.suspend_supplier(supplier["id"], CO),
            ApiErrorId.ERR_SUPPLIER_INVALID_STATE,
        )
        validate_error(
            api.reinstate_supplier(supplier["id"], CO),
            ApiErrorId.ERR_SUPPLIER_INVALID_STATE,
        )
        validate_error(
            api.approve_supplier(supplier["id"], CO),
            ApiErrorId.ERR_SUPPLIER_INVALID_STATE,
        )
        after = validate_success(api.get_supplier(supplier["id"], CO))
        assert after["status"] == "DISQUALIFIED"


class TestQualificationGates:
    def test_supplier_approve_blocked_when_approver_verified_documents(self, api):
        """PRD §2.10: "First, the `ComplianceOfficer` who approves a supplier
        must not be the operator recorded as `verified_by_user_id` on the most
        recently verified required-type document of that supplier."
        PRD §2.10: "Any violation of these three pairings is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/state_machines/supplier_approve_blocked_when_approver_verified_documents
        """
        verifier_as_co1 = build_user_headers("co-1", "QualityManager")
        approver_as_co1 = build_user_headers("co-1", "ComplianceOfficer")
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        doc_a = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="AATB_ACCREDITATION", document_ref="AATB-1"
                ),
                QM,
            )
        )
        get_success_data(
            api.verify_document(supplier["id"], doc_a["id"], verifier_as_co1)
        )
        doc_f = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="FDA_REGISTRATION", document_ref="FDA-1"
                ),
                QM,
            )
        )
        get_success_data(
            api.verify_document(supplier["id"], doc_f["id"], verifier_as_co1)
        )

        resp = api.approve_supplier(supplier["id"], approver_as_co1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_supplier(supplier["id"], CO2))
        assert approved["status"] == "QUALIFIED"

    def test_approve_without_required_documents(self, api):
        """PRD §3.1: "Approval requires documentary coverage: at least one
        `VERIFIED` document of type `AATB_ACCREDITATION` whose `valid_to` is on
        or after the current clock, and at least one `VERIFIED` document of
        type `FDA_REGISTRATION` meeting the same condition — a lapse in either
        is rejected with `ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED`."

        Design: Corner/errors/error_approve_without_required_documents
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        doc_a = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="AATB_ACCREDITATION", document_ref="AATB-1"
                ),
                QM,
            )
        )
        get_success_data(api.verify_document(supplier["id"], doc_a["id"], QM))
        # FDA_REGISTRATION present but only SUBMITTED (never verified).
        get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="FDA_REGISTRATION", document_ref="FDA-1"
                ),
                QM,
            )
        )
        resp = api.approve_supplier(supplier["id"], CO)
        validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED)
        after = validate_success(api.get_supplier(supplier["id"], CO))
        assert after["status"] == "PENDING_QUALIFICATION"


class TestWindowValidation:
    def test_invalid_window_on_case_document_and_recall(self, api):
        """PRD §3.5: "the window must be strictly ordered, with an end at or
        before the start rejected as `ERR_INVALID_WINDOW`."
        PRD §3.1: "The window is a closed interval, inclusive at both ends, and
        `valid_to` must not fall before `valid_from` (reversed windows are
        rejected with `ERR_INVALID_WINDOW`)."
        PRD §3.6: "a received window from `received_window_start` to
        `received_window_end` — a closed interval inclusive at both ends, with
        an end before the start rejected as `ERR_INVALID_WINDOW`"

        Design: Corner/errors/error_invalid_window_three_surfaces
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        # Implant case: scheduled_end == scheduled_start is not strictly after.
        resp_case = api.create_implant_case(
            create_implant_case_payload(
                scheduled_start="2026-09-01T12:00:00Z",
                scheduled_end="2026-09-01T12:00:00Z",
            ),
            SURG,
        )
        validate_error(resp_case, ApiErrorId.ERR_INVALID_WINDOW)
        # Supplier document: valid_to before valid_from.
        resp_doc = api.create_supplier_document(
            supplier["id"],
            create_document_payload(
                doc_type="ISO_CERTIFICATE",
                document_ref="ISO-1",
                valid_from="2026-06-01T00:00:00Z",
                valid_to="2026-05-01T00:00:00Z",
            ),
            QM,
        )
        validate_error(resp_doc, ApiErrorId.ERR_INVALID_WINDOW)
        # Recall: received_window_end before received_window_start.
        resp_recall = api.create_recall(
            create_recall_payload(
                supplier["id"],
                received_window_start="2026-12-31T00:00:00Z",
                received_window_end="2026-01-01T00:00:00Z",
                reason="Inverted window",
            ),
            QM,
        )
        validate_error(resp_recall, ApiErrorId.ERR_INVALID_WINDOW)


class TestDocumentValidityOverlap:
    def test_document_touching_validity_windows_conflict(self, api):
        """PRD §3.1: "One supplier may not hold overlapping validity windows
        for the same `doc_type` among its `SUBMITTED` and `VERIFIED` documents:
        because the interval is closed, windows that merely touch at an
        endpoint still conflict, and the submission is rejected with
        `ERR_DOC_VALIDITY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/supplier_document_closed_interval_touching_conflict
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        doc1 = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="FDA_REGISTRATION",
                    document_ref="FDA-1",
                    valid_from="2026-01-01T00:00:00Z",
                    valid_to="2026-12-31T00:00:00Z",
                ),
                QM,
            )
        )
        # Closed interval: new valid_from == existing valid_to shares a point.
        resp = api.create_supplier_document(
            supplier["id"],
            create_document_payload(
                doc_type="FDA_REGISTRATION",
                document_ref="FDA-2",
                valid_from="2026-12-31T00:00:00Z",
                valid_to="2027-12-31T00:00:00Z",
            ),
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_DOC_VALIDITY_OVERLAP)
        docs = get_success_data(api.list_supplier_documents(supplier["id"], QM))
        assert len(docs) == 1
        assert docs[0]["id"] == doc1["id"]
        assert docs[0]["status"] == "SUBMITTED"

    def test_document_disjoint_window_and_other_doc_type_allowed(self, api):
        """PRD §3.1: "One supplier may not hold overlapping validity windows
        for the same `doc_type` among its `SUBMITTED` and `VERIFIED` documents:
        because the interval is closed, windows that merely touch at an
        endpoint still conflict, and the submission is rejected with
        `ERR_DOC_VALIDITY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/supplier_document_closed_interval_touching_conflict
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="FDA_REGISTRATION",
                    document_ref="FDA-1",
                    valid_from="2026-01-01T00:00:00Z",
                    valid_to="2026-12-31T00:00:00Z",
                ),
                QM,
            )
        )
        # Disjoint window: no shared point with [2026-01-01, 2026-12-31].
        disjoint = validate_success(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="FDA_REGISTRATION",
                    document_ref="FDA-3",
                    valid_from="2027-01-01T00:00:00Z",
                    valid_to="2027-12-31T00:00:00Z",
                ),
                QM,
            ),
            201,
        )
        assert disjoint["status"] == "SUBMITTED"
        # Overlapping window but a different doc_type resource.
        other_type = validate_success(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(
                    doc_type="AATB_ACCREDITATION",
                    document_ref="AATB-1",
                    valid_from="2026-06-01T00:00:00Z",
                    valid_to="2026-12-31T00:00:00Z",
                ),
                QM,
            ),
            201,
        )
        assert other_type["status"] == "SUBMITTED"
        docs = get_success_data(api.list_supplier_documents(supplier["id"], QM))
        assert len(docs) == 3
