"""Access control: context headers, role exclusivity, and entity-backed
ownership (PRD §2.1, §2.9, §3.4, §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers, make_director_headers, make_coordinator_headers,
    make_booking_env, make_renter,
    make_under_review_request, make_approved_permit_in_env,
    capture_deposit, set_clock, get_single_work_order,
    create_request_payload, create_rate_policy_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestContextHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the caller's
        operational capacity. A request missing either header, or carrying a
        malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        # No headers at all — auth is checked before the 404 the unknown id
        # would otherwise produce.
        res = api.get_site(NON_EXISTENT_UUID, None)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)
        # Only one of the two headers present.
        partial = api.get_site(NON_EXISTENT_UUID, {"X-User-ID": "someone"})
        validate_error(partial, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)


class TestRoleEnforcement:
    def test_role_denied_on_exclusive_operation(self, api):
        """PRD §2.1: "Any attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.1: "A `DistrictAdmin` registers a site with a district-wide unique
        `site_code` and a human-readable `display_name`; the `rental_timezone`
        may be supplied and otherwise defaults to `America/Los_Angeles`."

        Design: Corner/validations/role_denied_on_exclusive_operation
        """
        org = make_renter("Riverview PTA")
        res = api.create_site(
            {"site_code": "HACK", "display_name": "Unauthorized Site"},
            make_renter_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_entity_backed_ownership_enforcement(self, api):
        """PRD §2.1: "A `RenterOrgRep` whose `X-User-ID` does not equal the
        organization identifier in the path is acting on another organization's
        resources and is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/validations/entity_backed_ownership_enforcement
        """
        env = make_booking_env(insurance=False)
        org_b = make_renter("Org B")
        # The rep of the env's organization writes into Org B's path.
        res = api.create_request(
            org_b["id"],
            create_request_payload(env["facility"]["id"], event_title="Intrusion",
                                   headcount_estimate=50,
                                   starts_at="2026-12-01T01:00:00Z",
                                   ends_at="2026-12-01T03:00:00Z"),
            make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_rbac_exclusive_operations_enforced(self, api):
        """PRD §2.1: "Any attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.4: "Approval (`UNDER_REVIEW` → `APPROVED`) is reserved for the
        `FacilitiesDirector` and carries the optimistic-concurrency field
        `expected_request_version` per §2.8 — a stale view is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "A `DistrictAdmin` authors a policy with a unique
        `policy_code`, the `rate_class` and `facility_tier` it prices, an
        `hourly_rate_cents` of at least zero — and exactly zero for `INTERNAL`,
        since the district does not charge itself — a `deposit_basis_points`
        between 0 and 10000, a `custodial_hourly_cents` labor rate for that
        class, and an effective window from `effective_from` to `effective_to`,
        where `effective_to` may be null for an open-ended policy and otherwise
        must be strictly after `effective_from`."
        PRD §3.8: "Intake belongs to the `SiteCoordinator`: on a `COMPLETED`
        permit, they record a **DamageAssessment** whose `line_items` form a
        non-empty array, each entry carrying a `description` and a
        `repair_cost_cents` strictly greater than zero — an empty array or any
        non-positive cost is rejected with `ERR_EMPTY_DAMAGE_CLAIM`."

        Design: Corner/rbac/rbac_exclusive_operations_enforced
        """
        env = make_booking_env()
        # An UNDER_REVIEW request (for the approve denial).
        req1 = make_under_review_request(
            env, event_title="Auction", headcount_estimate=100,
            starts_at="2026-09-13T00:00:00Z", ends_at="2026-09-13T03:00:00Z")
        # A completed permit with a work order (for the verify/intake denials).
        req2, permit2 = make_approved_permit_in_env(
            env, event_title="Second Night", headcount_estimate=100,
            starts_at="2026-09-14T00:00:00Z", ends_at="2026-09-14T03:00:00Z")
        capture_deposit(env, permit2["id"], 10000, "dep-rbac-1")
        set_clock("2026-09-14T12:00:00Z")
        validate_success(api.complete_permit(permit2["id"], COORDINATOR))
        order = get_single_work_order(permit2["id"])

        # Approve is FacilitiesDirector-reserved: SiteCoordinator is denied.
        res1 = api.approve_request(
            req1["id"], {"expected_request_version": req1["version"]}, COORDINATOR)
        validate_error(res1, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        # Rate policy authorship is DistrictAdmin-only: CustodialSupervisor denied.
        res2 = api.create_rate_policy(
            create_rate_policy_payload(policy_code="HACK", hourly_rate_cents=1,
                                       custodial_hourly_cents=1),
            SUPERVISOR)
        validate_error(res2, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        # Verification is the CustodialSupervisor's act: RenterOrgRep denied.
        res3 = api.verify_work_order(order["id"], {"actual_hours": 3.0},
                                     make_renter_headers(env["org"]["id"]))
        validate_error(res3, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        # Damage intake belongs to the SiteCoordinator: FacilitiesDirector denied.
        res4 = api.create_damage_assessment(
            permit2["id"],
            {"line_items": [{"description": "Dent", "repair_cost_cents": 5000}]},
            DIRECTOR)
        validate_error(res4, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestSharedReads:
    def test_rbac_shared_read_access(self, api):
        """PRD §4: "GET | `/district/sites/{site_id}` | Get a site | All roles".
        PRD §4: "GET | `/district/facilities/{facility_id}` | Get a facility |
        All roles".
        PRD §4: "GET | `/district/renters/{org_id}` | Get a renter organization |
        FacilitiesDirector, DistrictAdmin, SiteCoordinator, RenterOrgRep".

        Design: Corner/rbac/rbac_shared_read_access
        """
        env = make_booking_env(insurance=False)
        site = validate_success(api.get_site(env["site"]["id"], COORDINATOR))
        assert site["id"] == env["site"]["id"]
        facility = validate_success(api.get_facility(env["facility"]["id"], SUPERVISOR))
        assert facility["id"] == env["facility"]["id"]
        org = validate_success(api.get_renter(
            env["org"]["id"], make_renter_headers(env["org"]["id"])))
        assert org["id"] == env["org"]["id"]
        org2 = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org2["org_name"] == env["org"]["org_name"]
