"""Response envelope shape, list pagination, and immediate consistency of
mutations (including the auto-created budget ledger)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cycle,
    create_cycle_payload,
    create_framework,
    get_ledger,
    transition_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
DIRECTOR = TEST_USERS["curriculum_director_headers"]
SPECIALIST = TEST_USERS["instructional_specialist_headers"]
TEACHER = TEST_USERS["teacher_headers"]


class TestListPaginationAndEnvelope:
    def test_list_pagination_and_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry four pagination fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §4: "frameworks by `subject_area` and `status`"

        Design: Corner/endpoints/list_pagination_and_envelope
        """
        for i, (code, subject, band) in enumerate([
                ("FW-1", "MATHEMATICS", "K_5"),
                ("FW-2", "SCIENCE", "K_5"),
                ("FW-3", "SCIENCE", "GRADES_6_8")]):
            create_framework(code=code, subject_area=subject, grade_band=band)

        resp1 = api.list_frameworks(TEACHER, params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(page1) == 2 and meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_frameworks(TEACHER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1 and meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(
            api.list_frameworks(TEACHER, params={"subject_area": "SCIENCE"}))
        assert len(filtered) == 2 and meta3["total_count"] == 2
        assert all(f["subject_area"] == "SCIENCE" for f in filtered)

        for resp in (resp1,):
            body = resp.json()
            assert isinstance(body["meta"]["api_request_id"], str)
            assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_pagination_parameters_validated(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, and any value below 1 or above 100 is
        rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). The
        `offset` parameter states how many items to skip; it defaults to 0,
        and a negative value is likewise rejected with
        `ERR_INVALID_PAGINATION_PARAMETERS`."

        Design: Corner/validations/pagination_parameters_validated
        """
        create_framework()
        validate_error(api.list_frameworks(ADMIN, params={"limit": 0}),
                       ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)
        validate_error(api.list_frameworks(ADMIN, params={"limit": 101}),
                       ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)
        validate_error(api.list_frameworks(ADMIN, params={"offset": -1}),
                       ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)
        data, meta = validate_paginated(
            api.list_frameworks(ADMIN, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 1 and len(data) == 1


class TestErrorEnvelope:
    def test_error_envelope_shape_on_business_error(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a data
        object carrying "`error_id`" and "`message`".

        Design: Corner/errors/error_envelope_shape_on_business_error
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")
        resp = api.transition_cycle(cycle["id"], {"to_state": "PILOT_OPEN"},
                                    SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_NO_VETTED_MATERIALS)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip(), "message must be non-empty"
        assert isinstance(body["meta"]["api_request_id"], str)


class TestImmediateConsistency:
    def test_mutation_visible_in_response(self, api):
        """PRD §3.1: "A new cycle starts in `DRAFT` status, and its budget
        ledger is created alongside it with all totals at zero."
        PRD §3.1: "a `DistrictAdmin` posts an `amount`, which must be greater
        than zero, and that amount is added to the ledger's
        `appropriation_total`."

        Design: Corner/consistency_model/mutation_visible_in_response
        """
        framework = create_framework()
        payload = create_cycle_payload(framework_id=framework["id"])
        created = validate_success(api.create_cycle(payload, DIRECTOR),
                                   expected_status=201)
        assert created["status"] == "DRAFT"
        assert isinstance(created["version"], int)

        # The auto-created ledger is readable in the very next request.
        ledger = get_ledger(created["id"])
        assert ledger["appropriation_total"] == 0
        assert ledger["available_balance"] == 0
        assert ledger["encumbered_total"] == 0
        assert ledger["expended_total"] == 0

        # The appropriation response itself shows the new totals.
        updated = validate_success(api.post_appropriation(
            created["id"], {"amount": 5000}, ADMIN))
        assert updated["appropriation_total"] == 5000.00
        assert updated["available_balance"] == 5000.00
