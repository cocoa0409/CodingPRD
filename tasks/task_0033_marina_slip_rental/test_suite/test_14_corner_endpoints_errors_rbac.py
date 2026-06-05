"""Corner — endpoints, errors, and rbac sections.

Action endpoints, RBAC forbidden paths, missing-auth, and OCC stale-version
sequential rejection.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    create_lease_payload,
    set_clock_payload,
    reserve_lease,
    ApiErrorId,
    TEST_USERS,
    make_tenant_headers,
)


class TestClockSetEndpointReturnsNowUtc:

    def test_set_clock_returns_200(self, api):
        """PRD §2.10: "To support deterministic testing, an admin-only test-driving capability allows the clock to be pinned to a supplied instant via a payload containing `to_iso8601`."
        PRD §4: "All endpoints return HTTP 200 on successful retrieval or modification of an existing resource."

        Design: Corner/endpoints/clock_set_endpoint_returns_now_utc
        """
        res = api.set_clock(
            set_clock_payload("2026-08-15T00:00:00Z"),
            TEST_USERS["harbor_master_headers"],
        )
        validate_success(res, expected_status=200)


class TestErrorStaleVersionAlreadyCoveredByConcurrency:

    def test_second_lease_with_outdated_slip_version_returns_stale_version(self, api):
        """PRD §2.6: "If the slip's current `version` has advanced past that value — because another tenant successfully reserved the same slip in the interim, or because the harbor master decommissioned and the row mutated — the create is rejected with `ERR_STALE_VERSION` and HTTP 412, preventing the writer from layering a new reservation on top of a slip whose state has moved beyond their view."

        Design: Corner/errors/error_stale_version_already_covered_by_concurrency
        """
        # Note: PRD §3.4's state check fires before the OCC check, so for a
        # subsequent /leases with the *original* slip_version to surface as
        # ERR_STALE_VERSION rather than ERR_INVALID_STATE, the slip must be
        # AVAILABLE at the moment of the second create. We cancel the first
        # lease to restore the slip to AVAILABLE, then attempt the second
        # create with the now-stale original version.
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="SV-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        original_version = slip["version"]
        t1 = create_tenant(full_name="TSV1")
        t2 = create_tenant(full_name="TSV2")
        v1 = create_vessel(t1["id"], name="VSV1", loa_ft=40, beam_ft=12)
        v2 = create_vessel(t2["id"], name="VSV2", loa_ft=40, beam_ft=12)
        # First reservation advances slip.version by 1.
        lease1 = reserve_lease(
            marina["id"], slip["id"], t1["id"], v1["id"],
            "2026-10-01", "2026-10-05", original_version,
        )
        # Cancel restores slip to AVAILABLE and advances version once more.
        from test_helpers import cancel_lease
        cancel_lease(lease1["id"], t1["id"])
        # Second tenant attempts to reserve with the (now stale) original_version.
        res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=t2["id"],
                vessel_id=v2["id"],
                start_date="2026-11-01",
                end_date="2026-11-05",
                expected_slip_version=original_version,
            ),
            make_tenant_headers(t2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


class TestTenantCannotDecommissionSlip:

    def test_tenant_role_calling_decommission_returns_forbidden(self, api):
        """PRD §3.1: "Only a `HarborMaster` may create or decommission slips."
        PRD §2.1: "Authenticated requests whose role lacks authority for the targeted endpoint are rejected with `ERR_FORBIDDEN` and HTTP 403."

        Design: Corner/rbac/tenant_cannot_decommission_slip
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="RB-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tenant = create_tenant()
        res = api.decommission_slip(slip["id"], make_tenant_headers(tenant["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestMarinastaffCannotApproveLiveaboard:

    def test_marinastaff_calling_liveaboard_approve_returns_forbidden(self, api):
        """PRD §2.1: "Authenticated requests whose role lacks authority for the targeted endpoint are rejected with `ERR_FORBIDDEN` and HTTP 403."
        PRD §4: "| POST | /tenants/{id}/liveaboard-approve | Approve a pending liveaboard application. | HarborMaster |"

        Design: Corner/rbac/marinastaff_cannot_approve_liveaboard
        """
        marina = create_marina(liveaboard_cap=1)
        tenant = create_tenant()
        # Put tenant in PENDING so the only failing rule is RBAC.
        api.apply_liveaboard(
            tenant["id"], {"marina_id": marina["id"]},
            make_tenant_headers(tenant["id"]),
        )
        res = api.approve_liveaboard(
            tenant["id"], {"marina_id": marina["id"]},
            TEST_USERS["marina_staff_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestMissingAuthHeaderReturnsUnauthenticated:

    def test_create_marina_without_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying which class of operator is acting. Requests that omit either header — or supply either as an empty string — are rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        # Empty headers dict: neither X-User-Role nor X-User-ID present.
        res = api.create_marina(
            {"name": "MUA", "harbor_code": "MUA", "liveaboard_cap": 1},
            {},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
