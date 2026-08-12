"""Sponsor registry, capital-program lifecycle, and project field rules (PRD §2.3, §2.9, §3.1, §3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_sponsor, assert_cip_project, assert_capital_program, assert_money,
    create_sponsor_payload, create_program_payload, create_project_payload,
    create_sponsor, create_draft_program, add_project, submit_program, accept_program,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestSponsorRegistry:
    def test_sponsor_creation_returns_active_with_full_npe_available(self):
        """PRD §3.1: "A sponsor's `status` is always `ACTIVE`; sponsors are never deactivated."
        PRD §3.1: "the sponsor record continuously exposes `npe_entitlement_available`, computed as
        `npe_entitlement_total` minus the sum of `entitlement_portion` over every grant of that
        sponsor whose status is not `CLOSED`".

        Design: Corner/entities/sponsor_creation_defaults_and_computed_npe
        """
        res = api_client.create_sponsor(create_sponsor_payload(
            sponsor_name="Sponsor A", airport_size_tier="SMALL_HUB",
            npe_entitlement_total=5_000_000), FAA)
        sponsor = validate_success(res, 201)
        assert_sponsor(sponsor)
        assert sponsor["version"] == 1
        assert sponsor["status"] == "ACTIVE"
        # No grants exist yet, so the full entitlement is available.
        assert_money(sponsor["npe_entitlement_available"], 5_000_000.00,
                     "npe_entitlement_available")

    def test_sponsor_duplicate_loc_id_rejected(self):
        """PRD §3.1: "a `loc_id` that must be exactly three uppercase letters drawn from A
        through Z and unique across all sponsors".
        PRD §3.1: "Violations of these field constraints are rejected with `ERR_VALIDATION`
        (HTTP 422)."

        Design: Corner/entities/sponsor_duplicate_loc_id_rejected
        """
        first = create_sponsor(name="Sponsor A")
        res = api_client.create_sponsor(create_sponsor_payload(
            sponsor_name="Sponsor B", loc_id=first["loc_id"],
            airport_size_tier="NONHUB", npe_entitlement_total=100), FAA)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)

    def test_sponsor_get_not_found_returns_404(self):
        """PRD §2.9: "the first identifier that does not correspond to an existing resource
        aborts the request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/sponsor_get_not_found_returns_404
        """
        res = api_client.get_sponsor(NON_EXISTENT_UUID, SPONSOR)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestProjectFields:
    def test_cip_project_defaults_and_null_scores(self):
        """PRD §3.2: "Two boolean flags refine scoring: `runway_safety_noncompliant` marks a
        project that addresses a runway safety area noncompliance, and `multi_airport_system`
        marks one benefiting a multi-airport system; both default to false when omitted."
        PRD §3.2: "A new project starts in `PROPOSED`, and its three computed scores —
        `priority_score_sponsor`, `priority_score_federal`, and `selection_rank` — remain null
        until the first selection sweep runs."

        Design: Corner/entities/cip_project_defaults_and_null_scores
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        payload = create_project_payload(program["id"], title="Apron",
                                         project_type="CAPACITY", estimated_cost=250_000,
                                         safety_score=5, capacity_score=5,
                                         preservation_score=5, security_score=5,
                                         environmental_score=5)
        del payload["runway_safety_noncompliant"]
        del payload["multi_airport_system"]
        project = validate_success(api_client.create_project(payload, SPONSOR), 201)
        assert_cip_project(project)
        assert project["runway_safety_noncompliant"] is False
        assert project["multi_airport_system"] is False
        assert project["status"] == "PROPOSED"
        assert project["priority_score_sponsor"] is None
        assert project["priority_score_federal"] is None
        assert project["selection_rank"] is None

    def test_cip_project_score_out_of_range_rejected(self):
        """PRD §3.2: "five sponsor-scored component scores — `safety_score`, `capacity_score`,
        `preservation_score`, `security_score`, and `environmental_score` — each an integer
        between 0 and 20 inclusive."
        PRD §3.2: "Field-level violations are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/cip_project_score_out_of_range_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        res = api_client.create_project(create_project_payload(
            program["id"], title="Apron", project_type="CAPACITY", estimated_cost=250_000,
            safety_score=21, capacity_score=5, preservation_score=5, security_score=5,
            environmental_score=5), SPONSOR)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)


class TestProgramLifecycle:
    def test_program_accept_from_draft_rejected(self):
        """PRD §3.1: "A `FAAManager` then accepts a submitted program, moving `SUBMITTED` to
        `ACCEPTED`."
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)".

        Design: Corner/state_machines/program_accept_from_draft_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        add_project(program["id"], title="Apron", project_type="CAPACITY",
                    estimated_cost=250_000, safety_score=5, capacity_score=5,
                    preservation_score=5, security_score=5, environmental_score=5)
        res = api_client.accept_program(program["id"], FAA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_program(program["id"], SPONSOR), 200)
        assert after["status"] == "DRAFT"

    def test_program_amendment_cycle(self):
        """PRD §3.1: "When the sponsor needs to revise an accepted program, beginning an
        amendment moves `ACCEPTED` to `AMENDMENT_DRAFT`; projects may be added to a program
        only while it is in `DRAFT` or `AMENDMENT_DRAFT`".
        PRD §3.1: "Resubmitting from `AMENDMENT_DRAFT` returns the program to `SUBMITTED`
        under the same non-empty precondition".
        PRD §3.1: "Every one of these transitions increments the program's `version` by
        exactly one."

        Design: Corner/state_machines/program_amendment_cycle
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        add_project(program["id"], title="Apron", project_type="CAPACITY",
                    estimated_cost=250_000, safety_score=5, capacity_score=5,
                    preservation_score=5, security_score=5, environmental_score=5)
        submit_program(program["id"])
        accepted = accept_program(program["id"])
        assert accepted["status"] == "ACCEPTED"
        base_version = accepted["version"]

        amended = validate_success(api_client.begin_amendment(program["id"], SPONSOR), 200)
        assert amended["status"] == "AMENDMENT_DRAFT"
        assert amended["version"] == base_version + 1

        # Projects may be added during AMENDMENT_DRAFT.
        p2 = add_project(program["id"], title="Taxiway", project_type="PRESERVATION",
                         estimated_cost=300_000, safety_score=8, capacity_score=8,
                         preservation_score=8, security_score=8, environmental_score=8)
        assert p2["status"] == "PROPOSED"
        assert p2["selection_rank"] is None

        resubmitted = submit_program(program["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] == base_version + 2
        reaccepted = accept_program(program["id"])
        assert_capital_program(reaccepted)
        assert reaccepted["status"] == "ACCEPTED"
        assert reaccepted["version"] == base_version + 3

    def test_program_submit_empty_rejected(self):
        """PRD §3.1: "the submission is refused with `ERR_PROGRAM_EMPTY` (HTTP 422) when the
        program has no child project in `PROPOSED`, `SELECTED`, or `DEFERRED`."

        Design: Corner/validations/program_submit_empty_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        res = api_client.submit_program(program["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PROGRAM_EMPTY, expected_status=422)


class TestListPagination:
    def test_list_pagination_envelope_and_defaults(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return.
        If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_and_defaults
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        for title in ["P1", "P2", "P3"]:
            add_project(program["id"], title=title, project_type="CAPACITY",
                        estimated_cost=100_000, safety_score=5, capacity_score=5,
                        preservation_score=5, security_score=5, environmental_score=5)

        res = api_client.list_projects(SPONSOR,
                                       params={"program_id": program["id"], "limit": 2})
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id present"
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2

        data2, meta2 = validate_paginated(api_client.list_projects(
            SPONSOR, params={"program_id": program["id"], "limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Default page size is 10 when limit is not provided.
        _, meta_default = validate_paginated(api_client.list_projects(
            SPONSOR, params={"program_id": program["id"]}))
        assert meta_default["limit"] == 10
        assert meta_default["offset"] == 0
