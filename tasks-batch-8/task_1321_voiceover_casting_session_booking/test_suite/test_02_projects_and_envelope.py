"""Project creation shape rules, envelope structure, and ownership preconditions."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_project,
    create_client,
    create_project_payload,
    make_client_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_project_payload as project_payload


class TestProjectCreation:
    def test_project_initial_state_draft(self, api):
        """PRD §3.2: "A project begins when a `Client` creates it in `DRAFT`
        status."

        Design: Corner/state_machines/project_initial_state_draft
        """
        client = create_client()
        resp = api.create_project(
            project_payload(client["id"]), make_client_headers(client["id"]))
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["status"] == "DRAFT"

    def test_project_term_months_required_for_term_usage(self, api):
        """PRD §3.2: "A payload violating these shape rules — an unrecognized
        enum member, a missing `term_months` on a `TERM` project, a
        `spots_count` below 1 — is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/project_term_months_required_for_term_usage
        """
        client = create_client()
        payload = project_payload(client["id"], usage_type="TERM")
        assert "term_months" not in payload
        resp = api.create_project(payload, make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_project_parent_client_link(self, api):
        """PRD §2.8: "referenced resources are validated for existence in a
        fixed order: path identifiers first, evaluated left to right along the
        URL, then foreign keys carried in the request body. Any identifier that
        does not resolve to an existing resource produces `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/project_parent_client_link
        """
        payload = project_payload(NON_EXISTENT_UUID)
        resp = api.create_project(payload, make_client_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_project_computed_buyout_quote_input_ignored(self, api):
        """PRD §3.2: "Opening casting triggers the provisional buyout quote,
        stored on `buyout_quote_cents` and used for budgeting while talent is
        still unknown." PRD §3.2: "The project record carries
        `selected_talent_id`, which stays null until casting completes, and the
        two computed buyout figures `buyout_quote_cents` and
        `buyout_final_cents`."

        Design: Corner/entities/project_computed_buyout_quote_input_ignored
        """
        client = create_client()
        payload = project_payload(client["id"], buyout_quote_cents=999999)
        resp = api.create_project(payload, make_client_headers(client["id"]))
        data = validate_success(resp, expected_status=201)
        # The quote is computed only when casting opens; a client-supplied
        # value in the creation payload cannot take effect.
        assert data.get("buyout_quote_cents") is None, (
            "buyout_quote_cents must stay unset until open_casting computes it; "
            f"got {data.get('buyout_quote_cents')}"
        )
        assert data.get("buyout_final_cents") is None

    def test_get_project_returns_envelope_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." PRD §2.2: "The
        `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/endpoints/get_project_returns_envelope_shape
        """
        client = create_client()
        created = validate_success(
            api.create_project(project_payload(client["id"]),
                               make_client_headers(client["id"])),
            expected_status=201,
        )
        resp = api.get_project(created["id"], make_client_headers(client["id"]))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        assert body["data"]["id"] == created["id"]
