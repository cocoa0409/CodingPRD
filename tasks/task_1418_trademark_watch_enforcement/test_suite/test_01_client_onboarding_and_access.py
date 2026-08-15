"""Client onboarding, record registration basics, and access control."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client,
    assert_trademark_record,
    create_client_payload,
    create_record_payload,
    is_valid_uuid,
    make_client_contact_headers,
    validate_error,
    validate_success,
)


class TestClientOnboarding:
    def test_create_client_applies_computed_defaults(self, api, platform_admin_headers):
        """PRD §3.1: "At creation the ledger fields initialize themselves:
        `budget_spent_cents` starts at zero, `budget_remaining_cents` starts equal to
        `enforcement_budget_cents`, `exposure_index` starts at zero, and
        `watch_posture` starts `STANDARD`."
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/create_client_applies_computed_defaults
        """
        res = api.create_client(
            create_client_payload(enforcement_budget_cents=500000), platform_admin_headers
        )
        body = res.json()
        client = validate_success(res, 201)
        assert_client(client)
        assert client["budget_spent_cents"] == 0
        assert client["budget_remaining_cents"] == 500000
        assert client["exposure_index"] == 0
        assert client["watch_posture"] == "STANDARD"
        assert is_valid_uuid(client["id"])
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_create_client_missing_required_field_returns_validation(
        self, api, platform_admin_headers
    ):
        """PRD §2.10: "the request body satisfies the endpoint's input schema:
        required fields present, no unknown fields, enum values valid, assessment
        weights summing to 1.0, `hit_index` in range, and seizure-line entries
        positive integers, else `ERR_VALIDATION`."
        PRD §3.1: "A `PlatformAdmin` onboards a brand owner by creating a client with
        its legal `name`, its `industry` vertical, and a total
        `enforcement_budget_cents`."

        Design: Corner/entities/create_client_missing_required_field_returns_validation
        """
        res = api.create_client(
            {"name": "No Budget Co", "industry": "toys"}, platform_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestRecordBasics:
    def test_get_record_not_found_returns_404(self, api, paralegal_headers):
        """PRD §2.10: "Existence — path identifiers exist, validated left to right,
        and body-referenced foreign keys (`client_id`, `enforcement_matter_id`, every
        element of `evidence_item_ids`, `supersedes_recordation_id`) exist, else
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_record_not_found_returns_404
        """
        res = api.get_trademark_record(NON_EXISTENT_UUID, paralegal_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_create_record_with_computed_status_input_rejected(
        self, api, platform_admin_headers, paralegal_headers
    ):
        """PRD §2.10: "the request body satisfies the endpoint's input schema:
        required fields present, no unknown fields, enum values valid, assessment
        weights summing to 1.0, `hit_index` in range, and seizure-line entries
        positive integers, else `ERR_VALIDATION`."
        PRD §3.2: "The record is born in `APPLICATION_PENDING` status with
        `verified_evidence_count` at zero."

        Design: Corner/entities/create_record_with_computed_status_input_rejected
        """
        client = validate_success(
            api.create_client(create_client_payload(), platform_admin_headers), 201
        )
        payload = create_record_payload(client["id"], nice_classes=[9])
        payload["status"] = "REGISTERED"
        res = api.create_trademark_record(payload, paralegal_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_trademark_record_list_filters_isolate_client_and_status(
        self, api, platform_admin_headers, paralegal_headers
    ):
        """PRD §3.2: "Records can be listed with optional `client_id` and `status`
        filters alongside the standard `limit` and `offset`."

        Design: Corner/entities/trademark_record_list_filters_isolate_client_and_status
        """
        client_a = validate_success(
            api.create_client(create_client_payload(name="Alpha", industry="tech"),
                              platform_admin_headers), 201)
        client_b = validate_success(
            api.create_client(create_client_payload(name="Beta", industry="food"),
                              platform_admin_headers), 201)
        rec_a = validate_success(
            api.create_trademark_record(
                create_record_payload(client_a["id"], mark_text="ALPHA",
                                      nice_classes=[9], application_number="US-A1"),
                paralegal_headers), 201)
        validate_success(
            api.publish_record(rec_a["id"], {"publication_date": "2026-08-03T00:00:00Z"},
                               paralegal_headers), 200)
        rec_b = validate_success(
            api.create_trademark_record(
                create_record_payload(client_b["id"], mark_text="BETA",
                                      nice_classes=[30], application_number="US-B1"),
                paralegal_headers), 201)

        res_a = api.list_trademark_records(paralegal_headers,
                                           params={"client_id": client_a["id"]})
        data_a, meta_a = res_a.json()["data"], res_a.json()["meta"]
        assert meta_a["total_count"] == 1
        assert len(data_a) == 1 and data_a[0]["id"] == rec_a["id"]
        assert data_a[0]["id"] != rec_b["id"]

        res_p = api.list_trademark_records(paralegal_headers,
                                           params={"status": "PUBLISHED"})
        data_p, meta_p = res_p.json()["data"], res_p.json()["meta"]
        assert meta_p["total_count"] == 1
        assert len(data_p) == 1 and data_p[0]["id"] == rec_a["id"]
        assert_trademark_record(data_p[0])


class TestAccessControl:
    def test_watchservice_cannot_create_client_returns_forbidden(
        self, api, watch_service_headers
    ):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the
        endpoint's authorized role list, or the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`WatchService` — an external watch-service integration permitted
        only to submit alert intake batches."

        Design: Corner/rbac/watchservice_cannot_create_client_returns_forbidden
        """
        res = api.create_client(create_client_payload(), watch_service_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_clientcontact_cannot_read_other_client_record(
        self, api, platform_admin_headers, paralegal_headers
    ):
        """PRD §2.1: "A `ClientContact` may only access resources whose `client_id`
        equals their `X-User-ID`; touching another client's resource is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/clientcontact_cannot_read_other_client_record
        """
        client_a = validate_success(
            api.create_client(create_client_payload(name="Alpha", industry="tech"),
                              platform_admin_headers), 201)
        client_b = validate_success(
            api.create_client(create_client_payload(name="Beta", industry="food"),
                              platform_admin_headers), 201)
        rec_a = validate_success(
            api.create_trademark_record(
                create_record_payload(client_a["id"], mark_text="ALPHA",
                                      nice_classes=[9], application_number="US-A1"),
                paralegal_headers), 201)

        res = api.get_trademark_record(
            rec_a["id"], make_client_contact_headers(client_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        ok = api.get_trademark_record(
            rec_a["id"], make_client_contact_headers(client_a["id"]))
        record = validate_success(ok, 200)
        assert record["id"] == rec_a["id"]

    def test_request_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
        """
        res = api.get_client(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
