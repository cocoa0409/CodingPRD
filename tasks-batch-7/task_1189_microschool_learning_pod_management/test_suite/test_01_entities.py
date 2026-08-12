"""Entity-surface claims: required fields, defaults, computed fields,
system fields, parent-existence, not-found, and listing pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_envelope_object,
    assert_pod,
    create_facility_site_payload,
    create_family_payload,
    create_pod_payload,
    create_student_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import create_family, create_site, create_student

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestPodCreation:
    def test_pod_creation_requires_all_required_fields(self, api):
        """PRD 2.4: "Any request body that is missing a required field,
        supplies a value of the wrong type, or fails basic format validation
        — a malformed enum value or a negative amount, for instance — is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any deeper rule
        is evaluated."

        Design: Corner/entities/pod_creation_requires_all_required_fields
        """
        site = create_site(site_name="S1")
        payload = create_pod_payload(site["id"], name="NoCap")
        payload.pop("seat_capacity")
        resp = api.create_pod(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_pod_computed_enrolled_count_input_ignored(self, api):
        """PRD 3.1: "A new pod's `status` is `DRAFT`, its `enrolled_count` is
        a derived count of seats currently `ENROLLED`, and its `dissolved_at`
        remains null until dissolution finalizes."
        PRD 2.8: "Posture is never set directly by clients; it is recomputed
        by the server as lifecycle transitions and compliance evaluations
        unfold, as detailed throughout §3."

        Design: Corner/entities/pod_computed_enrolled_count_input_ignored
        """
        site = create_site(site_name="Comp")
        payload = create_pod_payload(site["id"], name="C", enrolled_count=99)
        data = validate_success(api.create_pod(payload, OPERATOR), expected_status=201)
        assert data["enrolled_count"] == 0, (
            f"derived enrolled_count must be 0 at creation, got {data['enrolled_count']}"
        )
        assert data["status"] == "DRAFT"
        assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN", "CLOSED"]
        assert_pod(data)

    def test_system_fields_id_created_at_updated_at_version(self, api):
        """PRD 2.4: "`id` (string): a server-minted UUID with no type prefix.
        ... `version` (integer): starts at 1 and increments by exactly 1 on
        every mutation of the resource, including mutations the server
        performs as cascade side effects."

        Design: Corner/entities/system_fields_id_created_at_updated_at_version
        """
        site = create_site(site_name="Sys")
        data = validate_success(
            api.create_pod(create_pod_payload(site["id"], name="SysPod"), OPERATOR),
            expected_status=201,
        )
        assert is_valid_uuid(data["id"]), "id must be a UUID"
        assert data["version"] == 1, f"version must start at 1, got {data['version']}"
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestFacilitySiteDefaults:
    def test_facility_site_default_status_available(self, api):
        """PRD 3.1: "A site's `site_status` begins at `AVAILABLE`, moves to
        `LEASED` the moment a pod referencing it opens enrollment, and may be
        soft-deleted to `ARCHIVED` by a `PlatformAdmin` provided no pod in
        any status other than `DISSOLVED` references it; archived sites
        cannot host new pods but remain queryable."

        Design: Corner/entities/facility_site_default_status_available
        """
        payload = create_facility_site_payload(
            site_name="Defaults", zoning_class="COMMERCIAL"
        )
        data = validate_success(
            api.create_facility_site(payload, ADMIN), expected_status=201
        )
        assert data["site_status"] == "AVAILABLE", (
            f"default site_status must be AVAILABLE, got {data['site_status']}"
        )


class TestParentAndExistence:
    def test_seat_requires_valid_pod_parent(self, api):
        """PRD 2.6: "Each path-templated identifier must resolve to an
        existing resource, and the request is rejected with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not — a request aimed
        at a seat beneath a non-existent pod fails on the pod before the
        seat is ever consulted."

        Design: Corner/entities/seat_requires_valid_pod_parent
        """
        family = create_family(family_name="Orphan")
        student = create_student(family["id"], legal_first_name="Or",
                                 legal_last_name="Phan")
        resp = api.create_seat(
            NON_EXISTENT_UUID,
            {"student_id": student["id"], "enrolled_on": "2026-09-01"},
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_get_pod_not_found_returns_404(self, api):
        """PRD 2.6: "Requests that address nested resources are validated
        left to right along the URL path. Each path-templated identifier must
        resolve to an existing resource, and the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not —
        a request aimed at a seat beneath a non-existent pod fails on the
        pod before the seat is ever consulted."

        Design: Corner/entities/get_pod_not_found_returns_404
        """
        resp = api.get_pod(NON_EXISTENT_UUID, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestListing:
    def test_list_pods_returns_paginated_array(self, api):
        """PRD 2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 when omitted, and any value below 1 or above 100 is
        rejected. `offset` sets the number of items skipped and defaults to
        0. ... The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pods_returns_paginated_array
        """
        site = create_site(site_name="Lp")
        for name in ("P1", "P2", "P3"):
            validate_success(
                api.create_pod(create_pod_payload(site["id"], name=name), OPERATOR),
                expected_status=201,
            )
        resp = api.list_pods(OPERATOR, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3, (
            f"expected total_count 3, got {meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert len(data) == 2
