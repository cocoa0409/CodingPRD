"""Agency bootstrap, roster management, pagination, and tenancy isolation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_agency,
    assert_agent,
    assert_author,
    close_period,
    close_period_as_accountant,
    create_agency,
    create_agency_payload,
    create_agent,
    create_author,
    create_author_payload,
    create_query_letter_payload,
    make_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAgencyRoster:
    def test_agency_create_applies_defaults(self, api, agency_admin_headers):
        """PRD 3.1: "A freshly created agency starts with `period_index` 0,
        `books_closed_through_period_index` null, and `posture` `NORMAL`."
        PRD 2.5: "`id` (string): a server-minted UUID with no type prefix,
        assigned at creation."

        Design: Corner/entities/agency_create_applies_defaults
        """
        resp = api.create_agency(
            create_agency_payload(name="Agency D", commission_pct=0.15, slush_capacity=50),
            agency_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_agency(data)
        assert data["posture"] == "NORMAL", f"expected posture NORMAL, got {data['posture']}"
        assert data["period_index"] == 0, f"expected period_index 0, got {data['period_index']}"
        assert data["books_closed_through_period_index"] is None, (
            "books_closed_through_period_index must start null"
        )

    def test_author_create_defaults_prospect(self, api, agency_admin_headers):
        """PRD 3.1: "an `Author` carries `agency_id`, `display_name`, and
        `email` (unique within the agency) and begins life as a `PROSPECT`"

        Design: Corner/entities/author_create_defaults_prospect
        """
        agency = create_agency(name="Agency AU")
        resp = api.create_author(
            create_author_payload(agency["id"], display_name="New Author"),
            agency_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_author(data)
        assert data["status"] == "PROSPECT", f"expected PROSPECT, got {data['status']}"

    def test_agent_version_increments_on_toggle(self, api, agency_admin_headers):
        """PRD 3.1: "Administrators may deactivate and later reactivate agents
        and editors; deactivation moves the record from `ACTIVE` to `INACTIVE`
        and reactivation reverses it, each transition incrementing the record's
        `version` by one."

        Design: Corner/entities/agent_version_increments_on_toggle
        """
        agency = create_agency(name="Agency VS")
        agent = create_agent(agency["id"])
        assert_agent(agent)
        v1 = agent["version"]

        deactivated = validate_success(api.deactivate_agent(agent["id"], agency_admin_headers), 200)
        assert deactivated["status"] == "INACTIVE"
        assert deactivated["version"] == v1 + 1, (
            f"deactivation must increment version by one: {v1} -> {deactivated['version']}"
        )

        reactivated = validate_success(api.activate_agent(agent["id"], agency_admin_headers), 200)
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["version"] == v1 + 2, (
            f"reactivation must increment version by one: {v1 + 1} -> {reactivated['version']}"
        )

    def test_agency_create_missing_name_invalid_request(self, api, agency_admin_headers):
        """PRD 3.1: "An `AgencyAdmin` begins by creating the agency itself,
        supplying its legal `name`, the default `commission_pct` fraction the
        agency will withhold from author earnings (used whenever a client
        agreement does not lock an override), and the `slush_capacity` that
        bounds the query pile."
        PRD 2.9: "required fields present, enums valid, ranges valid
        (`eval_score` between 0 and 100 inclusive, `word_count` greater than 0,
        monetary amounts greater than or equal to 0), and no undeclared fields
        (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/agency_create_missing_name_invalid_request
        """
        resp = api.create_agency(
            {"commission_pct": 0.15, "slush_capacity": 50}, agency_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_deal_returns_not_found(self, api, agency_admin_headers):
        """PRD 2.9: "Existence and tenancy — path and body identifiers must
        exist; for `Agent`-role callers the target resource's agency must equal
        the acting agent's agency, and cross-referenced body identifiers must
        belong to the same agency (`ERR_NOT_FOUND`, 404)."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/get_nonexistent_deal_returns_not_found
        """
        create_agency(name="Agency NF")
        resp = api.get_deal(NON_EXISTENT_UUID, agency_admin_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()

    def test_authors_list_pagination_envelope(self, api, agency_admin_headers):
        """PRD 2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of
        100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD 2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/authors_list_pagination_envelope
        """
        agency = create_agency(name="Agency PG")
        for i in range(3):
            create_author(agency["id"], display_name=f"A{i + 1}")

        page1, meta1 = validate_paginated(
            api.list_authors(agency_admin_headers,
                             params={"agency_id": agency["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2, f"page 1 must hold 2 authors, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_authors(agency_admin_headers,
                             params={"agency_id": agency["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"page 2 must hold 1 author, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_close_period_increments_period_and_books_flow(self, api, agency_admin_headers,
                                                           royalties_accountant_headers):
        """PRD 3.1: "Advancing the period — available to both `AgencyAdmin` and
        `RoyaltiesAccountant` — increments `period_index` by one, increments the
        agency's `version` by one, and sets off the lapse, due/late, and
        activation sweeps detailed in later subsections. Closing the books —
        likewise available to both roles — records that everything through the
        period just completed is final: it sets
        `books_closed_through_period_index` to the current `period_index` minus
        one, increments the agency's `version` by one, and is rejected with
        `ERR_INVALID_STATE` while `period_index` is still 0."

        Design: Corner/endpoints/close_period_increments_period_and_books_flow
        """
        agency = create_agency(name="Agency EP")
        assert agency["period_index"] == 0

        err = api.close_books(agency["id"], agency_admin_headers)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE.value)

        after1 = close_period(agency["id"])
        assert after1["period_index"] == 1
        after2 = close_period_as_accountant(agency["id"])
        assert after2["period_index"] == 2

        resp = api.close_books(agency["id"], royalties_accountant_headers)
        closed = validate_success(resp, 200)
        assert closed["books_closed_through_period_index"] == 1, (
            "books_closed_through_period_index must be period_index minus one"
        )

    def test_cross_agency_author_reference_not_found(self, api):
        """PRD 2.4: "The same rule covers cross-referenced identifiers supplied
        in a request body — `author_id`, `editor_id`, `submission_round_id`,
        `manuscript_id`, `agent_id`, `deal_id`, `submission_id`, and the like
        must all belong to the same agency as the resource being created or
        acted upon, or the request fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/cross_agency_author_reference_not_found
        """
        agency_a = create_agency(name="Agency A")
        agency_b = create_agency(name="Agency B")
        agent_a = create_agent(agency_a["id"], display_name="Agent A")
        author_b = create_author(agency_b["id"], display_name="Author B")

        resp = api.create_query_letter(
            create_query_letter_payload(author_b["id"], genre="FICTION", word_count=90000),
            make_agent_headers(agent_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
