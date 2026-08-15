"""Production creation defaults, fetch/list behavior, access control, and
computed talent fields (PRD sections 2.1, 2.3, 2.5, 3.1, 3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_production,
    create_production_payload,
    create_talent_payload,
    is_valid_uuid,
    make_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import create_agent, create_production, create_talent, set_clock


class TestProductionCreation:
    def test_create_returns_201_and_defaults(self, api, director_headers):
        """PRD section 3.1: "A new production begins in `SETUP` status."
        PRD section 2.5: "- **`id` (string):** a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 4: "Operations that create new resources return `201 Created`;
        operations that modify an existing resource's state return `200 OK`."
        PRD section 2.9: "A production's `active_breakdown_count` is the count of
        its child breakdowns whose status is either `RELEASED_AGENT_ONLY` or
        `RELEASED_OPEN`, recomputed on every breakdown release, close, or cancel."

        Design: Corner/entities/production_create_returns_201_and_defaults
        """
        resp = api.create_production(create_production_payload(title="NewProd"), director_headers)
        data = validate_success(resp, expected_status=201)
        assert_production(data)
        assert data["status"] == "SETUP", "new production must begin in SETUP"
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        # PRD 2.9: active_breakdown_count counts child breakdowns in a released
        # status; a fresh production has none.
        assert data["active_breakdown_count"] == 0

    def test_get_nonexistent_production_returns_404(self, api, director_headers):
        """PRD section 2.8: "Existence of path-templated resources, validated
        strictly **left to right** along the URL: a request naming a production
        and a breakdown beneath it checks the production first, then the
        breakdown, then any deeper child, and the first identifier that does not
        correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/production_get_not_found_returns_404
        """
        resp = api.get_production(NON_EXISTENT_UUID, director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_missing_required_field_returns_400(self, api, director_headers):
        """PRD section 3.1: "Missing or ill-typed values — including a wrap date
        that precedes the start date — are rejected with `ERR_INVALID_REQUEST`."
        PRD section 2.8: "Finally, required-field presence and well-typedness of
        the payload — missing fields, bad enum spellings, and out-of-domain
        values such as a `wrap_date` earlier than its `start_date` produce
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/production_create_missing_required_field_returns_400
        """
        payload = create_production_payload()
        del payload["title"]
        resp = api.create_production(payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_pagination_envelope_defaults(self, api, director_headers):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number of
        items to return; if not provided, it defaults to 10, with a minimum of 1
        and a maximum of 100."
        PRD section 2.3: "List-based responses include the following pagination
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/production_list_pagination_envelope
        """
        first = create_production(title="L1")
        second = create_production(title="L2")
        resp = api.list_productions(director_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected 2 productions, got {len(data)}"
        ids = {row["id"] for row in data}
        assert first["id"] in ids and second["id"] in ids
        assert meta["total_count"] == 2
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    def test_agent_cannot_create_production(self, api, director_headers):
        """PRD section 2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "| POST | `/casting/productions` | Create a production |
        CastingDirector |".

        Design: Corner/rbac/agent_cannot_create_production
        """
        agent = create_agent()
        resp = api.create_production(create_production_payload(title="X"), make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestTalentComputedFields:
    def test_is_minor_computed_on_read(self, api, director_headers):
        """PRD section 3.3: "Two talent fields are computed rather than entered:
        `is_minor`, true whenever the talent's age at the current logical clock
        is under 18, recomputed on every read of the talent and again at booking
        time; and `union_engagement_count_365d`, the rolling union-engagement
        aggregate defined in §3.9."

        Design: Corner/entities/talent_is_minor_computed_on_read
        """
        set_clock("2026-08-01T00:00:00Z")
        talent = create_talent(full_name="Kid", date_of_birth="2012-06-01T00:00:00Z")
        resp = api.get_talent(talent["id"], director_headers)
        data = validate_success(resp)
        assert data["is_minor"] is True, "DOB 2012-06-01 is age 14 at clock 2026-08-01"

    def test_is_minor_false_for_adult(self, api, director_headers):
        """PRD section 3.3: "Two talent fields are computed rather than entered:
        `is_minor`, true whenever the talent's age at the current logical clock
        is under 18, recomputed on every read of the talent and again at booking
        time; and `union_engagement_count_365d`, the rolling union-engagement
        aggregate defined in §3.9."

        Design: Corner/entities/talent_is_minor_computed_on_read
        """
        set_clock("2026-08-01T00:00:00Z")
        talent = create_talent(full_name="Adult", date_of_birth="1990-01-01T00:00:00Z")
        resp = api.get_talent(talent["id"], director_headers)
        data = validate_success(resp)
        assert data["is_minor"] is False, "DOB 1990-01-01 is age 36 at clock 2026-08-01"
