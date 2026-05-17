"""Auth headers, role-based access control, NotFound, envelope.

PRD §2.1 (auth headers / role identity), §2.2 (envelope), §2.3
(pagination), §2.5 (left-to-right path resolution / body-FK separation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    create_catalog_bundle,
    create_lab_order_payload,
    create_patient_payload,
    create_test_panel_payload,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# PRD §2.1 Auth headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1 mandates X-User-ID and X-User-Role on every request."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or carrying an
        empty value for either, are rejected with `ERR_AUTH_REQUIRED`."

        Claim: a request with neither header set returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or carrying an
        empty value for either, are rejected with `ERR_AUTH_REQUIRED`."

        Claim: omitting X-User-ID alone returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "OrderingProvider"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or carrying an
        empty value for either, are rejected with `ERR_AUTH_REQUIRED`."

        Claim: omitting X-User-Role alone returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "any"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or carrying an
        empty value for either, are rejected with `ERR_AUTH_REQUIRED`."

        Claim: an empty X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "",
                     "X-User-Role": "OrderingProvider"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_role_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or carrying an
        empty value for either, are rejected with `ERR_AUTH_REQUIRED`."

        Claim: an empty X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "x-1", "X-User-Role": ""},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# PRD §2.1 / §4 RBAC
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1 / §4 deny endpoints to roles not listed in §4."""

    def test_ordering_provider_cannot_create_clinician(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: OrderingProvider POST /clinicians -> ERR_FORBIDDEN
        (per PRD §4 the endpoint is LabDirector-only).
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        from test_helpers import create_clinician_payload
        res = api.create_clinician(
            create_clinician_payload(role_kind="LAB_TECH"), op_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_lab_tech_cannot_create_test_panel(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: LabTech POST /test-panels -> ERR_FORBIDDEN (PRD §4
        restricts the endpoint to LabDirector).
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        tech_headers = make_lab_tech_headers(bundle["lab_tech"]["id"])
        res = api.create_test_panel(
            create_test_panel_payload(), tech_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_lab_tech_cannot_place_lab_order(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: LabTech POST /lab-orders -> ERR_FORBIDDEN (PRD §4
        restricts the endpoint to OrderingProvider).
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        tech_headers = make_lab_tech_headers(bundle["lab_tech"]["id"])
        payload = create_lab_order_payload(
            patient_id=bundle["patient"]["id"],
            ordering_provider_id=bundle["ordering_provider"]["id"],
            panel_id=bundle["panel"]["id"],
        )
        res = api.create_lab_order(payload, tech_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_ordering_provider_cannot_release_result(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: OrderingProvider POST /results/{id}/release ->
        ERR_FORBIDDEN (PRD §4 restricts the endpoint to LabDirector).
        """
        from test_helpers import (
            anchor_clock, critical_measurements_high, release_result_payload,
            resultate, walk_order_to_received,
        )
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        result = resultate(
            bundle, walked["order"],
            measurements=critical_measurements_high(
                bundle["panel"]["analytes"], value=400.0,
            ),
            resulted_by=bundle["lab_tech"],
        )
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        payload = release_result_payload(
            released_by_id=bundle["director2"]["id"],
        )
        res = api.release_result(result["id"], payload, op_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_lab_tech_cannot_run_sweep(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: LabTech POST /_sweep/run -> ERR_FORBIDDEN (PRD §4
        restricts the endpoint to LabDirector).
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        tech_headers = make_lab_tech_headers(bundle["lab_tech"]["id"])
        res = api.run_sweep(tech_headers)
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# PRD §2.2 Envelope shape
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: every 2xx response carries meta + response_type + data."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: a successful GET produces an envelope with
        meta.api_request_id starting with 'req_'.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        res = api.get_patient(bundle["patient"]["id"], op_headers)
        validate_success(res, 200)
        body = res.json()
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_'"
        )
        assert "api_request_timestamp" in body["meta"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable
        string that identifies the specific error."

        Claim: an error response carries data.error_id and
        data.message, with response_type 'error'.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# PRD §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit in [1, 100], offset >= 0; out-of-range rejected
    with `ERR_INVALID_PAGINATION`."""

    def test_list_returns_pagination_meta(self, api):
        """PRD §2.3: "List responses include the fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta`
        object of the response envelope."

        Claim: a list endpoint's meta contains those four pagination
        fields.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        for _ in range(3):
            api.create_patient(create_patient_payload(), op_headers)
        data, meta = validate_paginated(api.list_patients(op_headers))
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: "Pagination parameters outside these bounds are
        rejected with `ERR_INVALID_PAGINATION`."

        Claim: limit=101 (above max=100) -> ERR_INVALID_PAGINATION.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        res = api.list_patients(op_headers, params={"limit": 101})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_limit_below_min_rejected(self, api):
        """PRD §2.3: "Pagination parameters outside these bounds are
        rejected with `ERR_INVALID_PAGINATION`."

        Claim: limit=0 (below min=1) -> ERR_INVALID_PAGINATION.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        res = api.list_patients(op_headers, params={"limit": 0})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_offset_negative_rejected(self, api):
        """PRD §2.3: "Pagination parameters outside these bounds are
        rejected with `ERR_INVALID_PAGINATION`."

        Claim: offset=-1 -> ERR_INVALID_PAGINATION.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        res = api.list_patients(op_headers, params={"offset": -1})
        validate_error(res, "ERR_INVALID_PAGINATION")


# ===========================================================================
# PRD §2.5 NotFound — path-segment vs body-FK
# ===========================================================================
class TestNotFound:
    """PRD §2.5: strict left-to-right path resolution and body-FK
    resolution both report `ERR_NOT_FOUND`."""

    def test_get_patient_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "the first segment that fails to resolve to a
        live row terminates the request with `ERR_NOT_FOUND`."

        Claim: GET /patients/{unknown} -> ERR_NOT_FOUND.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        res = api.get_patient(NON_EXISTENT_UUID, op_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_lab_order_with_unknown_patient_returns_not_found(
        self, api,
    ):
        """PRD §2.5: "Body-referenced foreign keys are likewise
        resolved before any state or business check; when `POST
        /lab-orders` is invoked with a `patient_id`,
        `ordering_provider_id`, or `panel_id` that does not resolve,
        the same `ERR_NOT_FOUND` is returned, as it is for unresolved
        `collected_by_id`, `resulted_by_id`, `released_by_id`, or
        `acknowledged_by_id` on their respective endpoints."

        Claim: POST /lab-orders with unknown patient_id ->
        ERR_NOT_FOUND.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        payload = create_lab_order_payload(
            patient_id=NON_EXISTENT_UUID,
            ordering_provider_id=bundle["ordering_provider"]["id"],
            panel_id=bundle["panel"]["id"],
        )
        res = api.create_lab_order(payload, op_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_lab_order_with_unknown_panel_returns_not_found(
        self, api,
    ):
        """PRD §2.5: "Body-referenced foreign keys are likewise
        resolved before any state or business check; when `POST
        /lab-orders` is invoked with a `patient_id`,
        `ordering_provider_id`, or `panel_id` that does not resolve,
        the same `ERR_NOT_FOUND` is returned, as it is for unresolved
        `collected_by_id`, `resulted_by_id`, `released_by_id`, or
        `acknowledged_by_id` on their respective endpoints."

        Claim: POST /lab-orders with unknown panel_id -> ERR_NOT_FOUND.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        payload = create_lab_order_payload(
            patient_id=bundle["patient"]["id"],
            ordering_provider_id=bundle["ordering_provider"]["id"],
            panel_id=NON_EXISTENT_UUID,
        )
        res = api.create_lab_order(payload, op_headers)
        validate_error(res, "ERR_NOT_FOUND")
