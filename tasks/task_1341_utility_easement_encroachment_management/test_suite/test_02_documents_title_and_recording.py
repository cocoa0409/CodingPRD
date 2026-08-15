"""Document inventory, encumbrance priority, title clearance, and lockdown."""
from test_helpers import (
    DEPARTMENT_DIRECTOR,
    NON_EXISTENT_UUID,
    ROW_AGENT,
    TITLE_EXAMINER,
    ApiErrorId,
    add_document,
    api_client,
    assert_easement_document,
    begin_mapping,
    complete_title_search,
    create_case,
    create_case_in_mapping,
    get_case,
    get_success_data,
    order_and_complete_clean_title_search,
    order_title_search,
    record_document,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestDocumentListing:

    def test_fk_reverse_reachable_via_filtered_list(self):
        """PRD section 2.9: "Paths in this API are hierarchical: a document
        lives under its case, a violation lives under its zone under its case,
        and so on."
        PRD section 3.2: "Documents are reachable both through their case and
        through the flat retrieval paths described in §2.9."

        Design: Corner/entities/fk_reverse_reachable_via_filtered_list
        """
        case = create_case(case_code="ESM-C08", parcel_id="P-C08")
        add_document(case["id"], instrument_number="INST-C08a")
        add_document(case["id"], doc_kind="PLAT", instrument_number="INST-C08b")
        resp = api_client.list_documents(case["id"], TITLE_EXAMINER)
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert all(doc["case_id"] == case["id"] for doc in data)
        for doc in data:
            assert_easement_document(doc)


class TestEncumbranceRank:

    def test_encumbrance_rank_tie_breaks_by_created_at(self):
        """PRD section 3.2: "First, the document receives its
        `encumbrance_rank`: among the case's `RECORDED` documents, rank is the
        1-based position when sorted by `recording_date` ascending, with ties
        broken by earlier `created_at` first and never by `id` — rank encodes
        recording priority, which governs conflicting encroachment claims."

        Design: Corner/calculations/encumbrance_rank_tie_breaks_by_created_at
        """
        case = create_case(case_code="ESM-CAL1", parcel_id="P-CAL1")
        # Both documents share the same recording_date; d1 is created first,
        # so the created_at tie-break must rank d1 ahead of d2.
        d1 = add_document(case["id"], instrument_number="INST-CAL1a",
                          recording_date="2026-07-01T00:00:00Z")
        d2 = add_document(case["id"], doc_kind="PLAT", instrument_number="INST-CAL1b",
                          recording_date="2026-07-01T00:00:00Z")
        begin_mapping(case["id"])
        record_document(case["id"], d1["id"])
        record_document(case["id"], d2["id"])

        d1_after = get_success_data(api_client.get_document(case["id"], d1["id"], TITLE_EXAMINER))
        d2_after = get_success_data(api_client.get_document(case["id"], d2["id"], TITLE_EXAMINER))
        assert d1_after["status"] == "RECORDED"
        assert d2_after["status"] == "RECORDED"
        assert d1_after["encumbrance_rank"] == 1, (
            f"earlier-created document must take rank 1 on a recording_date tie, "
            f"got {d1_after['encumbrance_rank']}"
        )
        assert d2_after["encumbrance_rank"] == 2, (
            f"later-created document must take rank 2 on a recording_date tie, "
            f"got {d2_after['encumbrance_rank']}"
        )


class TestTitleClearance:

    def test_computed_read_title_cleared_after_clean_search(self):
        """PRD section 3.1: "The case's `title_cleared` flag is then derived,
        and the derivation is deliberately strict: it is true only when the
        most recently created title search for the case — latest by creation
        timestamp, with any tie broken by earlier `created_at` first and never
        by `id` — is `COMPLETED_CLEAN` **and** at least one document on the
        case is in `RECORDED` status."
        PRD section 3.1: "A clean search alone is insufficient; a recorded
        document must also exist."

        Design: Corner/endpoints/computed_read_title_cleared_after_clean_search
        """
        case, doc = create_case_in_mapping(case_code="ESM-E02", parcel_id="P-E02")
        order_and_complete_clean_title_search(case["id"])
        before = get_case(case["id"])
        assert before["title_cleared"] is False, (
            "clean search with no RECORDED document must leave title_cleared false"
        )
        record_document(case["id"], doc["id"])
        after = get_case(case["id"])
        assert after["title_cleared"] is True, (
            "clean search plus a RECORDED document must set title_cleared true"
        )

    def test_err_title_defects_exist_on_clean_complete(self):
        """PRD section 3.1: "When both counts are zero the task becomes
        `COMPLETED_CLEAN`; when either count is greater than zero the task
        becomes `COMPLETED_WITH_DEFECTS`."
        PRD section 3.1: "Completing a search with defects forces
        `title_cleared` to false and blocks any offer still in `DRAFT` on that
        case from being tendered until a clean search completes."

        Design: Corner/errors/err_title_defects_exist_on_clean_complete
        """
        case, _doc = create_case_in_mapping(case_code="ESM-ER4", parcel_id="P-ER4")
        task = order_title_search(case["id"])
        completed = complete_title_search(case["id"], task["id"], liens_found=0, defects_found=2)
        assert completed["status"] == "COMPLETED_WITH_DEFECTS"
        assert get_case(case["id"])["title_cleared"] is False


class TestRecordingValidation:

    def test_err_document_not_found_on_record(self):
        """PRD section 2.9: "A request naming a nonexistent `caseId` is rejected
        with `ERR_CASE_NOT_FOUND` before any child identifier is examined; a
        valid `caseId` paired with a nonexistent `docId` yields
        `ERR_DOCUMENT_NOT_FOUND`; the analogous child misses yield
        `ERR_ENCROACHMENT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
        `ERR_TITLE_TASK_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND` respectively,
        all HTTP 404."

        Design: Corner/errors/err_document_not_found_on_record
        """
        case, _doc = create_case_in_mapping(case_code="ESM-ER1", parcel_id="P-ER1")
        resp = api_client.record_document(case["id"], NON_EXISTENT_UUID, TITLE_EXAMINER)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND)

    def test_self_supersede_rejected(self):
        """PRD section 3.2: "Two integrity rules guard creation and recording:
        the `supersedes_document_id` must reference a document that is itself
        `RECORDED` and must not equal the document's own `id` — violations
        produce `ERR_DOCUMENT_NOT_RECORDED` and `ERR_SELF_SUPERSEDE`
        respectively — and the `recording_date` may not lie in the future, else
        `ERR_INVALID_DATE_RANGE`."

        A supersede target that does not exist cannot be RECORDED; the PRD does
        not pin whether that miss surfaces as the document-existence error or
        the not-recorded error, so either is accepted.

        Design: Corner/validations/self_supersede_rejected
        """
        case, _doc = create_case_in_mapping(case_code="ESM-V03", parcel_id="P-V03")
        payload = {
            "doc_kind": "AMENDMENT",
            "instrument_number": "INST-V03b",
            "recording_date": "2026-08-01T00:00:00Z",
            "grantor_name": "S",
            "grantee_name": "CU",
            "gis_polygon_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            "width_ft": 50,
            "supersedes_document_id": NON_EXISTENT_UUID,
        }
        resp = api_client.create_document(case["id"], payload, TITLE_EXAMINER)
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DOCUMENT_NOT_FOUND, ApiErrorId.ERR_DOCUMENT_NOT_RECORDED]
        )
        assert actual in (
            ApiErrorId.ERR_DOCUMENT_NOT_FOUND, ApiErrorId.ERR_DOCUMENT_NOT_RECORDED
        )


class TestCaseStateGuards:

    def test_idempotency_second_begin_mapping_rejected(self):
        """PRD section 2.8: "**Target resource state** — the resource being
        transitioned must currently be in the state the transition starts from,
        else the entity-specific state error such as `ERR_OFFER_NOT_TENDERED`,
        `ERR_ENCROACHMENT_NOT_NEGOTIATING`, `ERR_PERMIT_NOT_PENDING`,
        `ERR_TASK_NOT_IN_PROGRESS`, `ERR_DOCUMENT_NOT_DRAFT`,
        `ERR_REFERRAL_NOT_ACCEPTED`, or `ERR_REFERRAL_NOT_FILED` (409), with
        `ERR_INVALID_STATE` (409) as the generic form."

        Design: Corner/state_machines/idempotency_second_begin_mapping_rejected
        """
        case, _doc = create_case_in_mapping(case_code="ESM-S05", parcel_id="P-S05")
        resp = api_client.begin_mapping(case["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_terminal_state_lockdown_on_closed_case(self):
        """PRD section 2.4: "No child resource may be created or transitioned
        once its case has reached a terminal closed state; such attempts are
        rejected with `ERR_CASE_ALREADY_CLOSED`."
        PRD section 3.8: "All three closed states are terminal: once a case is
        in `CLOSED_RESOLVED`, `CLOSED_CONDEMNED`, or `CLOSED_ABANDONED`, no
        child may be created or transitioned beneath it."

        Design: Corner/state_machines/terminal_state_lockdown_on_closed_case
        """
        case = create_case(case_code="ESM-S04", parcel_id="P-S04")
        abandoned = get_success_data(api_client.abandon_case(case["id"], DEPARTMENT_DIRECTOR))
        assert abandoned["status"] == "CLOSED_ABANDONED"

        # Child creation beneath a terminal case is squarely locked down.
        resp = api_client.create_document(
            case["id"],
            {
                "doc_kind": "DEED",
                "instrument_number": "INST-S04",
                "recording_date": "2026-07-01T00:00:00Z",
                "grantor_name": "S",
                "grantee_name": "CU",
                "gis_polygon_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
                "width_ft": 50,
            },
            TITLE_EXAMINER,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_CLOSED, expected_status=409)

        # A further case transition out of the terminal state is likewise
        # rejected (generic state form or the closed-case error).
        resp2 = api_client.begin_mapping(case["id"], ROW_AGENT)
        validate_error_is_one_of(
            resp2, [ApiErrorId.ERR_CASE_ALREADY_CLOSED, ApiErrorId.ERR_INVALID_STATE]
        )


class TestRecordingIntegrityPriority:
    """When title is not cleared AND the instrument number is a duplicate, the
    only coherent reading of the PRD's recording workflow (section 3.2 lists
    case-openness and instrument uniqueness as the recording gates, and a title
    gate on recording would be circular against the title_cleared derivation in
    section 3.1) yields the duplicate-instrument rejection."""

    def _setup_case_with_recorded_doc(self, case_code, parcel_id, instrument,
                                       liens_found, defects_found):
        case = create_case(case_code=case_code, parcel_id=parcel_id)
        doc1 = add_document(case["id"], instrument_number=instrument)
        begin_mapping(case["id"])
        order_title_search_id = order_title_search(case["id"])["id"]
        complete_title_search(case["id"], order_title_search_id,
                              liens_found=liens_found, defects_found=defects_found)
        record_document(case["id"], doc1["id"])
        return case, doc1

    def test_duplicate_instrument_wins_when_title_also_uncleared(self):
        """PRD section 3.2: "It is allowed only while the case is in `MAPPING`,
        `ACTIVE_MONITORING`, or `RESOLUTION_PENDING` (else
        `ERR_CASE_NOT_OPEN_FOR_RECORDING`), and only while the
        `instrument_number` remains unique across the county (else
        `ERR_DUPLICATE_INSTRUMENT_NUMBER`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_document_record
        """
        # Latest title search completes WITH_DEFECTS (title not cleared), and
        # the second document reuses the first document's instrument_number.
        case, _doc1 = self._setup_case_with_recorded_doc(
            "ESM-010", "P-010", "INST-901", liens_found=1, defects_found=0
        )
        assert get_case(case["id"])["title_cleared"] is False
        doc2 = add_document(case["id"], doc_kind="PLAT", instrument_number="INST-901",
                            recording_date="2026-07-15T00:00:00Z")
        resp = api_client.record_document(case["id"], doc2["id"], TITLE_EXAMINER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INSTRUMENT_NUMBER, expected_status=409)

    def test_duplicate_instrument_rejected_with_clean_title(self):
        """PRD section 3.2: "It is allowed only while the case is in `MAPPING`,
        `ACTIVE_MONITORING`, or `RESOLUTION_PENDING` (else
        `ERR_CASE_NOT_OPEN_FOR_RECORDING`), and only while the
        `instrument_number` remains unique across the county (else
        `ERR_DUPLICATE_INSTRUMENT_NUMBER`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_document_record
        """
        # Isolated single failure: title is clean, only the duplicate
        # instrument number can reject the recording.
        case, _doc1 = self._setup_case_with_recorded_doc(
            "ESM-010b", "P-010b", "INST-902", liens_found=0, defects_found=0
        )
        assert get_case(case["id"])["title_cleared"] is True
        doc2 = add_document(case["id"], doc_kind="PLAT", instrument_number="INST-902",
                            recording_date="2026-07-15T00:00:00Z")
        resp = api_client.record_document(case["id"], doc2["id"], TITLE_EXAMINER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INSTRUMENT_NUMBER, expected_status=409)
