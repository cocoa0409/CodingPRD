"""Distributor accounts, request authentication/validation, and the response
envelope."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_distributor,
    create_distributor,
    create_distributor_payload,
    get_distributor,
    validate_error,
    validate_success,
)

TEST_HEADERS_ADMIN = TEST_USERS["plant_admin_headers"]

# PRD §2.2: api_request_timestamp is ISO 8601 UTC with three fractional digits.
_ISO8601_3F_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestDistributorCreation:
    def test_distributor_creation_applies_defaults(self, api):
        """PRD §3.1: "New accounts begin with `status` `ACTIVE`, both ledger
        fields at zero, and `version` 1."
        PRD §4: "Operations that create a new stand-alone resource or add a
        new resource to a collection return a `201 Created` status code."

        Design: Corner/entities/distributor_creation_applies_defaults
        """
        resp = api.create_distributor(
            create_distributor_payload(distributor_code="D-DEF",
                                       name="Defaults Co",
                                       volume_discount_pct=0.1),
            TEST_HEADERS_ADMIN)
        data = validate_success(resp, 201)
        assert_distributor(data)
        assert data["status"] == "ACTIVE", (
            f"new distributor must start ACTIVE, got {data['status']}")
        assert data["deposits_held_cents"] == 0
        assert data["credit_balance_cents"] == 0
        assert data["version"] == 1, (
            f"new distributor must start at version 1, got {data['version']}")

    def test_get_missing_distributor_returns_not_found(self, api):
        """PRD §2.8: "For any request whose path contains resource identifiers,
        existence is validated left-to-right: the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not
        resolve, before any body-referenced identifier is examined."

        Design: Corner/entities/get_missing_distributor_returns_not_found
        """
        resp = api.get_distributor(NON_EXISTENT_UUID, TEST_HEADERS_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_distributor_missing_required_field_rejected(self, api):
        """PRD §2.8: "request-body well-formedness (`ERR_VALIDATION`, HTTP 400
        — required fields present, no undeclared fields, enum values within
        their declared sets, types correct, numeric ranges respected,
        `scheduled_end` strictly after `scheduled_start`, `ended_at` strictly
        after `started_at`)".

        Design: Corner/entities/distributor_missing_required_field_rejected
        """
        payload = create_distributor_payload(distributor_code="D-MISS",
                                             name="Missing Ltd")
        del payload["credit_limit_cents"]
        resp = api.create_distributor(payload, TEST_HEADERS_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_distributor_invalid_emissions_enum_rejected(self, api):
        """PRD §3.1: "the market's `emissions_requirement` (one of `FEDERAL` or
        `CALIFORNIA`)".
        PRD §2.8: "then request-body well-formedness (`ERR_VALIDATION`, HTTP
        400 — required fields present, no undeclared fields, enum values
        within their declared sets, types correct, numeric ranges respected,
        `scheduled_end` strictly after `scheduled_start`, `ended_at` strictly
        after `started_at`), and only then existence."

        Design: Corner/entities/distributor_invalid_emissions_enum_rejected
        """
        resp = api.create_distributor(
            create_distributor_payload(distributor_code="D-ENUM",
                                       emissions_requirement="EURO6"),
            TEST_HEADERS_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestRequestGatekeeping:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Failure to provide both headers, or presenting an
        `X-User-Role` value that is not one of the declared roles, will result
        in an `ERR_UNAUTHENTICATED` error (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.create_distributor(
            create_distributor_payload(distributor_code="D-NA", name="No Auth"),
            {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_body_field_rejected(self, api):
        """PRD §2.8: "then request-body well-formedness (`ERR_VALIDATION`, HTTP
        400 — required fields present, no undeclared fields, enum values
        within their declared sets, types correct, numeric ranges respected,
        `scheduled_end` strictly after `scheduled_start`, `ended_at` strictly
        after `started_at`), and only then existence."

        Design: Corner/validations/unknown_body_field_rejected
        """
        payload = create_distributor_payload(distributor_code="D-XTRA",
                                             name="Extra Field Co")
        payload["bogus_field"] = "x"
        resp = api.create_distributor(payload, TEST_HEADERS_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        resp = api.create_distributor(
            create_distributor_payload(distributor_code="D-ENV",
                                       name="Envelope Co"),
            TEST_HEADERS_ADMIN)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert set(("meta", "response_type", "data")) <= set(body.keys())
        request_id = body["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id.startswith("req_"), (
            f"api_request_id must start with 'req_': {request_id!r}")
        assert _ISO8601_3F_RE.match(body["meta"]["api_request_timestamp"] or ""), (
            "api_request_timestamp must be ISO 8601 UTC with three fractional "
            f"digits: {body['meta']['api_request_timestamp']!r}")
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict) and body["data"]["id"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_distributor(NON_EXISTENT_UUID, TEST_HEADERS_ADMIN)
        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}, (
            f"error meta must contain only api_request_id and "
            f"api_request_timestamp: {sorted(body['meta'].keys())}")
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()


class TestDistributorUpdate:
    def test_patch_immediately_visible(self, api, plant_admin_headers):
        """PRD §3.1: "A `PlantAdmin` may update an account's
        `credit_limit_cents`, `volume_discount_pct`, or `status`."
        PRD §3.1: "Each such update increments the distributor's `version`
        by 1."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/patch_immediately_visible
        """
        distributor = create_distributor(distributor_code="D-IC",
                                         name="Immediate Co",
                                         volume_discount_pct=0.10)

        resp = api.patch_distributor(distributor["id"],
                                     {"volume_discount_pct": 0.25},
                                     plant_admin_headers)
        patched = validate_success(resp, 200)
        assert_distributor(patched)
        assert patched["volume_discount_pct"] == 0.25, (
            "PATCH response must reflect the mutation in the same request")
        assert patched["version"] == distributor["version"] + 1

        reread = get_distributor(distributor["id"])
        assert reread["volume_discount_pct"] == 0.25, (
            "a subsequent GET must return the patched value (no lag)")
