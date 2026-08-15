"""Case creation, retrieval, listing, intake transitions, and access control."""
from datetime import datetime

from test_helpers import (
    CLOCK_START_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_document,
    api_client,
    assert_easement_case,
    create_case,
    create_case_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    ROW_AGENT,
    TITLE_EXAMINER,
)


class TestCaseCreation:

    def test_create_case_with_all_required_fields_returns_201(self):
        """PRD section 3.1: "A freshly created case starts in `INTAKE` with
        `compensation_committed_cents` at 0, `compensation_balance_cents` equal
        to the full `acquisition_budget_cents`, `open_encroachment_count` and
        `encroachment_pressure_score` at 0, `title_cleared` false, and
        `active_permit_count` at 0."
        PRD section 2.5: "`status`-family fields and `version` (integer): the
        `version` starts at 1 and increments on every mutation, and is the
        field on which optimistic concurrency control operates."

        Design: Corner/entities/create_case_with_all_required_fields_returns_201
        """
        payload = create_case_payload(
            case_code="ESM-C01", county="King", parcel_id="P-C01",
            acquisition_budget_cents=50000000,
        )
        resp = api_client.create_case(payload, ROW_AGENT)
        data = validate_success(resp, expected_status=201)
        assert_easement_case(data)
        assert data["case_code"] == "ESM-C01"
        assert data["status"] == "INTAKE"
        assert data["compensation_committed_cents"] == 0
        assert data["compensation_balance_cents"] == 50000000
        assert data["open_encroachment_count"] == 0
        assert data["encroachment_pressure_score"] == 0
        assert data["title_cleared"] is False
        assert data["active_permit_count"] == 0
        assert data["version"] == 1

    def test_get_case_by_id_returns_stored_data(self):
        """PRD section 2.5: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 2.5: "`created_at` (string): an ISO 8601 UTC timestamp with
        three fractional digits (for example, `2026-08-01T09:15:00.123Z`), set
        when the resource is created."

        Design: Corner/entities/get_case_by_id_returns_stored_data
        """
        case = create_case(case_code="ESM-C03", parcel_id="P-C03")
        resp = api_client.get_case(case["id"], ROW_AGENT)
        data = validate_success(resp)
        assert_easement_case(data)
        assert data["case_code"] == "ESM-C03"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])

    def test_list_cases_paginates(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10 when omitted, accepts a minimum of 1, and
        accepts a maximum of 100."
        PRD section 2.3: "The `meta` object of every list response carries
        exactly the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/list_cases_paginates
        """
        for i in ("a", "b", "c"):
            create_case(case_code=f"ESM-C04{i}", parcel_id=f"P-C04{i}")
        resp = api_client.list_cases(ROW_AGENT, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must cap the page at 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_get_nonexistent_case_returns_404(self):
        """PRD section 2.9: "A request naming a nonexistent `caseId` is rejected
        with `ERR_CASE_NOT_FOUND` before any child identifier is examined; a
        valid `caseId` paired with a nonexistent `docId` yields
        `ERR_DOCUMENT_NOT_FOUND`; the analogous child misses yield
        `ERR_ENCROACHMENT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
        `ERR_TITLE_TASK_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND` respectively,
        all HTTP 404."

        Design: Corner/entities/get_nonexistent_case_returns_404
        """
        resp = api_client.get_case(NON_EXISTENT_UUID, ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)

    def test_system_fields_input_ignored_on_case_create(self):
        """PRD section 2.5: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 2.5: "`status`-family fields and `version` (integer): the
        `version` starts at 1 and increments on every mutation, and is the
        field on which optimistic concurrency control operates."
        PRD section 2.10: "At startup the clock reads exactly
        2026-08-01T00:00:00Z, and it must never silently fall back to
        wall-clock time."

        Design: Corner/entities/system_fields_input_ignored_on_case_create
        """
        supplied_id = "11111111-1111-4111-8111-111111111111"
        payload = create_case_payload(case_code="ESM-C05", parcel_id="P-C05")
        payload.update({
            "id": supplied_id,
            "version": 99,
            "created_at": "2000-01-01T00:00:00Z",
        })
        resp = api_client.create_case(payload, ROW_AGENT)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != supplied_id, "server must mint its own UUID"
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1, f"version must start at 1, got {data['version']}"
        # Compare instants, not spellings: PRD section 2.5 mandates three
        # fractional digits on created_at while section 2.10 writes the clock
        # start without them, so a raw string compare misorders equal instants.
        created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        clock_start = datetime.fromisoformat(CLOCK_START_ISO.replace("Z", "+00:00"))
        assert created >= clock_start, (
            f"created_at must come from the logical clock starting at "
            f"{CLOCK_START_ISO}, got {data['created_at']}"
        )


class TestCaseIntakeTransitions:

    def test_case_initial_state_is_intake(self):
        """PRD section 3.1: "A freshly created case starts in `INTAKE` with
        `compensation_committed_cents` at 0, `compensation_balance_cents` equal
        to the full `acquisition_budget_cents`, `open_encroachment_count` and
        `encroachment_pressure_score` at 0, `title_cleared` false, and
        `active_permit_count` at 0."

        Design: Corner/state_machines/case_initial_state_is_intake
        """
        case = create_case(case_code="ESM-S01", parcel_id="P-S01")
        assert case["status"] == "INTAKE"

    def test_begin_mapping_from_intake_succeeds(self):
        """PRD section 3.1: "Beginning mapping moves `INTAKE → MAPPING` and
        requires that at least one document exist on the case, failing with
        `ERR_NO_DOCUMENTS_ON_CASE` otherwise."

        Design: Corner/state_machines/begin_mapping_from_intake_succeeds
        """
        case = create_case(case_code="ESM-S02", parcel_id="P-S02")
        add_document(case["id"], instrument_number="INST-S02")
        resp = api_client.begin_mapping(case["id"], ROW_AGENT)
        data = validate_success(resp)
        assert data["status"] == "MAPPING"

    def test_begin_mapping_with_no_documents_fails(self):
        """PRD section 3.1: "Beginning mapping moves `INTAKE → MAPPING` and
        requires that at least one document exist on the case, failing with
        `ERR_NO_DOCUMENTS_ON_CASE` otherwise."

        Design: Corner/state_machines/begin_mapping_with_no_documents_fails
        """
        case = create_case(case_code="ESM-S03", parcel_id="P-S03")
        resp = api_client.begin_mapping(case["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_NO_DOCUMENTS_ON_CASE)


class TestAccessControl:

    def test_missing_role_header_returns_401(self):
        """PRD section 2.1: "A request whose `X-User-Role` header is missing or
        does not match one of these five values is rejected with
        `ERR_MISSING_OR_INVALID_ROLE` (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_401
        """
        headers = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
        resp = api_client.list_cases(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_ROLE, expected_status=401)

    def test_pagination_filter_by_status(self):
        """PRD section 4: "Query parameters marked optional in Section 3 (such
        as `status`, `county`, `doc_kind`, `severity_tier`, `approval_status`,
        and `permit_type`) act as filters on the corresponding list endpoints."
        PRD section 2.3: "The `meta` object of every list response carries
        exactly the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/cross_cutting_complexity_layers/pagination_filter_by_status
        """
        create_case(case_code="ESM-X03a", parcel_id="P-X03a")
        case_b = create_case(case_code="ESM-X03b", parcel_id="P-X03b")
        create_case(case_code="ESM-X03c", parcel_id="P-X03c")
        add_document(case_b["id"], instrument_number="INST-X03")
        api_client.begin_mapping(case_b["id"], ROW_AGENT)

        resp = api_client.list_cases(ROW_AGENT, params={"status": "INTAKE"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"two INTAKE cases exist, total_count must be 2, got {meta['total_count']}"
        )
        assert all(item["status"] == "INTAKE" for item in data), (
            f"filter status=INTAKE leaked other statuses: "
            f"{[item['status'] for item in data]}"
        )
