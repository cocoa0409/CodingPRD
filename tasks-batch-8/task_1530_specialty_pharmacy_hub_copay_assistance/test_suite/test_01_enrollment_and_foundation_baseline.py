"""Enrollment creation/readback, benefits-investigation immutability,
foundation-pool initialization, listing/pagination, and empty sub-resource
reads — the baseline contract surface."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_benefits_investigation,
    assert_enrollment,
    assert_foundation_pool,
    create_bi_payload,
    create_enrollment,
    create_enrollment_payload,
    create_pool,
    create_program,
    get_enrollment,
    is_valid_uuid,
    make_case_manager_headers,
    record_benefits_investigation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
PR = TEST_USERS["payer_reviewer_headers"]


class TestEnrollmentCreation:

    def test_enrollment_creation_returns_initial_state(self):
        """PRD section 3.2: "The new Enrollment opens in `INTAKE`, with the
        creator's header identity stamped into `case_manager_id` for audit
        purposes only."
        PRD section 3.2: "Its counters begin at zero —
        `training_sessions_completed` and `fills_delivered_count` both start
        at 0, and `payer_accumulated_oop_cents` starts at 0 — while
        `remaining_oop_cents` stays null until a benefits investigation
        exists and `therapy_start_date` stays null until the first delivery."
        PRD section 2.4: "The `id` is a server-minted UUID with no type
        prefix."

        Design: Corner/entities/enrollment_creation_returns_initial_state
        """
        prog = create_program(name="ProgE1")
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                prog["id"], patient_ref="PAT-001", diagnosis_code="C50"),
            CM)
        data = validate_success(resp, expected_status=201)
        assert_enrollment(data)
        assert data["status"] == "INTAKE", \
            f"initial state must be INTAKE, got {data['status']}"
        assert data["training_sessions_completed"] == 0
        assert data["fills_delivered_count"] == 0
        assert data["payer_accumulated_oop_cents"] == 0
        assert data["therapy_start_date"] is None
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"

    def test_enrollment_create_extra_system_fields_input_ignored(self):
        """PRD section 2.4: "The `id` is a server-minted UUID with no type
        prefix."
        PRD section 3.2: "The new Enrollment opens in `INTAKE`, with the
        creator's header identity stamped into `case_manager_id` for audit
        purposes only."

        Design: Corner/entities/enrollment_create_extra_system_fields_input_ignored
        """
        prog = create_program(name="ProgE3")
        supplied_id = "11111111-2222-4333-8444-555555555555"
        payload = create_enrollment_payload(
            prog["id"], patient_ref="PAT-003", diagnosis_code="C50")
        payload["id"] = supplied_id
        payload["version"] = 99
        payload["created_at"] = "2020-01-01T00:00:00Z"
        resp = api_client.create_enrollment(payload, CM)
        if resp.status_code == 201:
            data = validate_success(resp, expected_status=201)
            assert data["id"] != supplied_id, \
                "server must mint its own id, never honor the client value"
            assert is_valid_uuid(data["id"])
            assert data["version"] != 99, \
                "client-supplied version hint must not govern"
            assert data["created_at"] != "2020-01-01T00:00:00Z"
            assert data["status"] == "INTAKE"
        else:
            # A strict-schema server rejects the unknown system fields
            # instead of ignoring them; both honor the minted-values rule.
            validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_enrollment_create_missing_required_program_id(self):
        """PRD section 2.6: "Request body schema. Required fields present,
        types valid, enum values in range, and dates parseable — including
        the two date-sanity rules that a `requested_delivery_date` must fall
        on or after the current logical clock date and an `awareness_at`
        must be no later than the current logical clock time; failures yield
        `ERR_VALIDATION` (HTTP 400)."
        PRD section 3.2: "A `CaseManager` enrolls a patient into a program by
        submitting a payload containing the target `program_id`, an external
        de-identified `patient_ref`, and the patient's `diagnosis_code`,
        which later drives foundation eligibility matching."

        Design: Corner/entities/enrollment_create_missing_required_program_id
        """
        resp = api_client.create_enrollment(
            {"patient_ref": "PAT-X", "diagnosis_code": "C50"}, CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api_client.list_enrollments(CM))
        assert meta["total_count"] == 0, "a rejected create must persist nothing"


class TestEnrollmentRetrieval:

    def test_enrollment_retrieval_matches_created_data(self):
        """PRD section 2.1: "When `X-User-Role` is `CaseManager`, the server
        records the identifier as `case_manager_id` on each Enrollment the
        operator creates (audit only; no ownership restriction follows)".
        PRD section 4: "Read one enrollment including computed adherence and
        OOP fields | Any authenticated role".

        Design: Corner/entities/enrollment_retrieval_matches_created_data
        """
        prog = create_program(name="ProgE2")
        cm7 = make_case_manager_headers("cm-7")
        enr = create_enrollment(
            prog["id"], patient_ref="PAT-002", diagnosis_code="C50",
            as_headers=cm7)
        resp = api_client.get_enrollment(enr["id"], PR)
        data = validate_success(resp, expected_status=200)
        assert_enrollment(data)
        assert data["patient_ref"] == "PAT-002"
        assert data["diagnosis_code"] == "C50"
        assert data["program_id"] == prog["id"]
        assert data["case_manager_id"] == "cm-7", \
            "case_manager_id must be stamped from the creator's X-User-ID"

    def test_enrollment_get_not_found_returns_404(self):
        """PRD section 2.7: "Each resource type carries its own not-found
        code: `ERR_DRUG_PROGRAM_NOT_FOUND` (including enrollment creation
        that names an unknown program), `ERR_FOUNDATION_POOL_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PRIOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_COPAY_ASSISTANCE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
        `ERR_NURSE_VISIT_NOT_FOUND`, `ERR_ADVERSE_EVENT_NOT_FOUND`, and
        `ERR_OUTCOME_REPORT_NOT_FOUND`."

        Design: Corner/entities/enrollment_get_not_found_returns_404
        """
        resp = api_client.get_enrollment(NON_EXISTENT_UUID, CM)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)


class TestEnrollmentListing:

    def test_enrollment_list_pagination_and_filter(self):
        """PRD section 3.2: "The enrollment listing supports optional
        filtering by `status` and `program_id` alongside the standard
        `limit` and `offset` pagination parameters."
        PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return: it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0."

        Design: Corner/entities/enrollment_list_pagination_and_filter
        """
        prog_1 = create_program(name="ProgL1")
        prog_2 = create_program(
            name="ProgL2", diagnosis_code="E11")
        create_enrollment(prog_1["id"], patient_ref="PAT-L1")
        create_enrollment(prog_1["id"], patient_ref="PAT-L2")
        create_enrollment(prog_2["id"], patient_ref="PAT-L3",
                          diagnosis_code="E11")

        resp = api_client.list_enrollments(
            CM, params={"program_id": prog_1["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, \
            f"program_id filter must scope the count, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        resp = api_client.list_enrollments(
            CM, params={"program_id": prog_1["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert len(data) == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10 when omitted"
        assert meta["offset"] == 0, "default offset is 0 when omitted"
        assert all(e["program_id"] == prog_1["id"] for e in data), \
            "the E11 enrollment must be excluded by the program_id filter"


class TestBenefitsInvestigationRecord:

    def test_bi_record_immutable_without_version(self):
        """PRD section 2.4: "One entity is exempt from the full set: a
        BenefitsInvestigation is immutable once created and therefore
        carries only `id` and `created_at` — both `updated_at` and `version`
        are absent from it."
        PRD section 3.2: "Reading the investigation back returns an array of
        length zero or one."

        Design: Corner/entities/bi_record_immutable_without_version
        """
        prog = create_program(name="ProgBI")
        enr = create_enrollment(prog["id"], patient_ref="PAT-BI")
        resp = api_client.create_benefits_investigation(
            enr["id"],
            create_bi_payload(
                member_id="M-BI", requires_prior_auth=True,
                plan_has_accumulator=True),
            CM)
        bi = validate_success(resp, expected_status=201)
        assert_benefits_investigation(bi)

        read = api_client.get_benefits_investigation(enr["id"], CM)
        data, meta = validate_paginated(read)
        assert len(data) == 1, "exactly one investigation may exist"
        assert_benefits_investigation(data[0])
        assert data[0]["id"] == bi["id"]
        assert data[0]["requires_prior_auth"] is True
        assert data[0]["plan_has_accumulator"] is True
        assert meta["total_count"] == 1

    def test_enrollment_computed_fields_null_before_therapy(self):
        """PRD section 3.2: "The adherence projections `pdc_confirmed_pct`
        and `pdc_provisional_pct` are likewise null until `therapy_start_date`
        is set."
        PRD section 3.2: "Creating the investigation while the enrollment is
        in `INTAKE` — with no prior investigation on file — moves the
        enrollment to `BENEFITS_VERIFIED` and sets `remaining_oop_cents` to
        the reported `oop_max_cents`."
        PRD section 3.2: "When the plan does not require prior authorization,
        the same creation immediately advances the enrollment from
        `BENEFITS_VERIFIED` to `APPROVED`, again setting `remaining_oop_cents`
        to `oop_max_cents`".

        Design: Corner/entities/enrollment_computed_fields_null_before_therapy
        """
        prog = create_program(name="ProgE4")
        enr = create_enrollment(prog["id"], patient_ref="PAT-004")
        assert enr["remaining_oop_cents"] is None, \
            "remaining_oop_cents stays null until a benefits investigation exists"

        record_benefits_investigation(enr["id"], member_id="M-4")
        data = get_enrollment(enr["id"])
        assert data["status"] == "APPROVED"
        assert data["remaining_oop_cents"] == 500_000
        assert data["pdc_confirmed_pct"] is None, \
            "no therapy start yet: confirmed PDC must be null, not 0.0"
        assert data["pdc_provisional_pct"] is None, \
            "no therapy start yet: provisional PDC must be null, not 0.0"


class TestFoundationPoolCreation:

    def test_foundation_pool_creation_initializes_computed_balance(self):
        """PRD section 3.1: "At creation, the pool's `remaining_balance_cents`
        initializes to `total_funding_cents`; thereafter it decreases by
        `grant_amount_cents` each time a patient is matched against the pool
        and increases by a grant's undisbursed remainder whenever a grant is
        released or superseded."

        Design: Corner/entities/foundation_pool_creation_initializes_computed_balance
        """
        resp = api_client.create_foundation_pool(
            {
                "name": "FundC",
                "diagnosis_code": "C50",
                "total_funding_cents": 5_000_000,
                "grant_amount_cents": 200_000,
                "coverage_pct": 80,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "remaining_balance_cents": 1,
            },
            TEST_USERS["hub_admin_headers"],
        )
        pool = validate_success(resp, expected_status=201)
        assert_foundation_pool(pool)
        assert pool["remaining_balance_cents"] == 5_000_000, \
            "computed initializer must equal total_funding_cents, not client input"


class TestEmptySubResourceLists:

    def test_sub_resource_lists_return_empty_arrays(self):
        """PRD section 3.2: "Reading the investigation back returns an array
        of length zero or one."
        PRD section 2.2: "The `data` field contains the resource object or an
        array of resource objects."
        PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/sub_resource_lists_return_empty_arrays
        """
        prog = create_program(name="ProgP1")
        enr = create_enrollment(prog["id"], patient_ref="PAT-P1")

        list_calls = [
            ("shipments", api_client.list_shipments),
            ("benefits-investigation", api_client.get_benefits_investigation),
            ("prior-authorizations", api_client.list_prior_authorizations),
            ("copay-assistances", api_client.list_copay_assistances),
            ("nurse-visits", api_client.list_nurse_visits),
            ("adverse-events", api_client.list_adverse_events),
            ("outcome-reports", api_client.list_outcome_reports),
        ]
        for label, call in list_calls:
            resp = call(enr["id"], CM)
            body = resp.json()
            data, meta = validate_paginated(resp)
            assert body["response_type"] == "array", \
                f"{label}: response_type must be 'array'"
            assert data == [], f"{label}: fresh enrollment must list []"
            assert meta["total_count"] == 0, f"{label}: total_count must be 0"
            assert meta["has_more"] is False, f"{label}: has_more must be false"
