"""Response envelope, pagination, authentication, authorization and
existence checks (PRD §2.1, §2.2, §2.3, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_staff_member,
    assert_episode,
    create_episode,
    create_episode_payload,
    create_site,
    create_site_activation_payload,
    designate_site,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)


class TestExistenceAndEnvelope:
    def test_episode_not_found_returns_not_found(self, api, eoc_manager_headers):
        """PRD §2.9: "Existence is third: path identifiers are validated left
        to right, a nested child must belong to its path parent, and
        body-referenced identifiers (such as `site_id`, `guest_id`,
        `staff_member_id`, `vehicle_id`, `target_site_activation_id` and every
        element of `guest_ids`) must exist, with any failure yielding
        `ERR_NOT_FOUND`."

        Design: Corner/entities/episode_not_found_returns_not_found
        """
        resp = api.get_episode(NON_EXISTENT_UUID, eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_response_envelope_shape_on_success_and_error(self, api,
                                                          eoc_manager_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        episode = create_episode()

        ok = api.get_episode(episode["id"], eoc_manager_headers)
        body = ok.json()
        assert ok.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert_episode(body["data"])
        assert body["data"]["id"] == episode["id"]

        err = api.get_episode(NON_EXISTENT_UUID, eoc_manager_headers)
        err_body = err.json()
        assert err.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0

    def test_list_pagination_limit_offset_has_more(self, api,
                                                   eoc_manager_headers):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; `offset` defaults to 0. The `meta` object of a list
        response carries the pagination fields `limit`, `offset`,
        `total_count` and `has_more`."

        Design: Corner/endpoints/list_pagination_limit_offset_has_more
        """
        add_staff_member("A One", ["SITE_LEAD"])
        add_staff_member("B Two", ["INTAKE"])
        add_staff_member("C Three", ["MEDICAL"])

        page1, meta1 = validate_paginated(
            api.list_staff_members(eoc_manager_headers, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_staff_members(eoc_manager_headers,
                                   params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestAuth:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        that is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        episode = create_episode()
        # Deliberately send no X-User-ID / X-User-Role headers at all.
        resp = api.get_episode(episode["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_intake_staff_cannot_create_episode(self, api, intake_staff_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/episodes is authorized for EOCManager only.

        Design: Corner/validations/intake_staff_cannot_create_episode
        """
        resp = api.create_episode(create_episode_payload(), intake_staff_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_body_fk_reference_not_found(self, api, eoc_manager_headers):
        """PRD §2.9: "Existence is third: path identifiers are validated left
        to right, a nested child must belong to its path parent, and
        body-referenced identifiers (such as `site_id`, `guest_id`,
        `staff_member_id`, `vehicle_id`, `target_site_activation_id` and every
        element of `guest_ids`) must exist, with any failure yielding
        `ERR_NOT_FOUND`."

        Design: Corner/errors/body_fk_reference_not_found
        """
        episode = create_episode()
        resp = api.create_site_activation(
            episode["id"],
            create_site_activation_payload(NON_EXISTENT_UUID),
            eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_transport_coordinator_cannot_open_site(
            self, api, transport_coordinator_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/site-activations/{id}/open is authorized for
        SiteLead only.

        Design: Corner/rbac/transport_coordinator_cannot_open_site
        """
        episode = create_episode(mode="WARMING", threshold_f=32.0)
        site = create_site(name="Armory", address="9 Oak Ave", bed_capacity=10)
        sa = designate_site(episode["id"], site["id"])
        resp = api.open_site_activation(sa["id"], transport_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
