"""Employer onboarding, RBAC denials, and authentication (PRD §2.1, §2.3, §3.1)."""
import re

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    create_employer_payload,
    create_plan_payload,
    assert_employer,
    setup_locked_census_401k,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestEmployerCreation:
    def test_employer_create_returns_system_fields(self):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three
        fractional digits."
        PRD §3.1: "A new employer starts life `ACTIVE`"

        Design: Corner/entities/employer_create_returns_201_with_system_fields
        """
        payload = create_employer_payload(
            legal_name="Sierra Corp", ein="111222333", entity_type="S_CORPORATION"
        )
        resp = api_client.create_employer(payload, PLATFORM)
        data = validate_success(resp, expected_status=201)
        assert_employer(data)
        assert data["status"] == "ACTIVE", "new employer must start ACTIVE"
        assert isinstance(data["version"], int) and data["version"] >= 1
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}",
                        data["created_at"]), "created_at must carry three fractional digits"

        fetched = validate_success(api_client.get_employer(data["id"], AUDITOR))
        assert fetched["status"] == "ACTIVE"
        assert is_valid_uuid(fetched["id"])

    def test_employer_create_missing_ein_rejected(self):
        """PRD §2.8: "Temporal checks follow: date-interval sanity, then the safe
        harbor notice window."
        PRD §3.1: "A `PlatformAdmin` onboards each sponsoring employer by supplying its
        `legal_name`, its `ein`, and its `entity_type`."

        Design: Corner/entities/employer_create_missing_ein_returns_invalid_request
        """
        resp = api_client.create_employer(
            {"legal_name": "No Ein Corp", "entity_type": "CORPORATION"}, PLATFORM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employer_get_nonexistent_returns_not_found(self):
        """PRD §2.9: "If any identifier does not resolve, or a child exists but hangs
        off a different parent than the path claims, the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/employer_get_nonexistent_returns_not_found
        """
        resp = api_client.get_employer("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", AUDITOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_employer_list_pagination_defaults(self):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`, defaulting
        to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0.
        Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside its `meta` object so a client can page deterministically through the
        result set."

        Design: Corner/entities/employer_list_pagination_defaults
        """
        for i in range(1, 13):
            api_client.create_employer(
                create_employer_payload(legal_name=f"P{i:02d}", ein=f"100000{i:03d}"),
                PLATFORM,
            )
        page1, meta1 = validate_paginated(api_client.list_employers(AUDITOR))
        assert meta1["limit"] == 10 and meta1["offset"] == 0
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_employers(AUDITOR, params={"offset": 10})
        )
        assert len(page2) == 2
        assert meta2["has_more"] is False

    def test_invalid_enum_value_rejected(self):
        """PRD §3.1: "The `entity_type` declares the employer's legal form and must be
        one of `CORPORATION`, `S_CORPORATION`, `PARTNERSHIP`, `LLC`,
        `SOLE_PROPRIETORSHIP`, `NONPROFIT`, or `GOVERNMENTAL`"

        Design: Corner/entities/invalid_enum_value_rejected
        """
        resp = api_client.create_employer(
            {"legal_name": "BadEnum", "ein": "200000003", "entity_type": "B_CORP"},
            PLATFORM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self):
        """PRD §2.1: "A request missing either header, carrying a malformed header, or
        naming a role the system does not declare is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        headers = {"X-User-ID": "auditor-1", "Content-Type": "application/json"}
        resp = api_client.get_employer(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRbacDenials:
    def test_auditor_cannot_create_employer(self):
        """PRD §2.1: "Only a `PlatformAdmin` may create and archive employers, publish
        regulatory limits, and drive the logical clock."
        PRD §2.1: "`Auditor` — a read-only external auditor with access to every
        retrieval endpoint and no write capability at all."

        Design: Corner/rbac/auditor_cannot_create_employer
        """
        employer = validate_success(
            api_client.create_employer(
                create_employer_payload(legal_name="Charlie3 Corp", ein="800000001"),
                PLATFORM,
            ),
            expected_status=201,
        )
        denied = api_client.create_employer(
            create_employer_payload(legal_name="Auditor Forge", ein="800000002"),
            AUDITOR,
        )
        validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        allowed = api_client.get_employer(employer["id"], AUDITOR)
        validate_success(allowed)

    def test_plan_admin_cannot_create_test_run(self):
        """PRD §2.1: "`ComplianceAnalyst` — the testing analyst. This role queues and
        finalizes test runs, voids queued runs, and proposes corrections."
        PRD §3.6: "Once the census is locked, a `ComplianceAnalyst` queues test runs
        against it."

        Design: Corner/rbac/plan_admin_cannot_create_test_run
        """
        parts = setup_locked_census_401k(
            legal_name="Echo3 Corp", nhce_specs=((9000000, 0),), hce_spec=(30000000, 0, 6)
        )
        resp = api_client.create_test_run(
            parts["plan_year"]["id"],
            {"test_scope": "ADP_401K", "run_mode": "FINAL"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
