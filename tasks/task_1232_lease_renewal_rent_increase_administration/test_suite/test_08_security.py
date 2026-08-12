"""Authentication, role authorization, ownership, and property OCC (PRD §2.1, §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    ca_oak_policy_payload,
    create_lease,
    create_offer_for_lease,
    create_policy,
    create_property,
    create_property_payload,
    create_resident,
    create_unit,
    issue_offer,
    make_resident_headers,
    respond_accept_payload,
    setup_issued_offer_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PM1 = TEST_USERS["pm_1_headers"]


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. A request missing either header, or naming a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.create_property(
            create_property_payload("00000000-0000-4000-8000-0000000000d1",
                                    name="No Auth"),
            {},  # no X-User-ID / X-User-Role headers at all
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_resident_role_forbidden_on_policy_create(self, api):
        """PRD §2.1: "Beyond authentication, each endpoint authorizes a fixed list of
        roles; a caller whose role is not on the list for the endpoint they invoked
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.1: "`PlatformAdmin` is the platform operator, responsible for rent-cap
        policies, properties, units, resident onboarding, and the logical clock."

        Design: Corner/rbac/resident_role_forbidden_on_policy_create
        """
        resident = create_resident(full_name="Role Test", email="role.test@x.com")
        payload = ca_oak_policy_payload()
        payload.update({
            "jurisdiction_code": "XX-YYY",
            "base_cap_bps": 1, "cpi_adjustment_bps": 1, "hard_ceiling_bps": 1,
            "high_increase_threshold_bps": 1, "notice_days_low": 1,
            "notice_days_high": 1, "non_renewal_notice_days": 1,
        })
        resp = api.create_rent_cap_policy(payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnership:
    def test_resident_cannot_respond_for_other_lease(self, api):
        """PRD §2.1: "When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of
        the acting `Resident` record; ownership checks on any resource that chains to
        a `Lease` — an offer through its lease, a renewal document through its lease,
        or the lease itself — compare the lease's `resident_id` to `X-User-ID`, and a
        mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."
        PRD §3.4: "Ownership per §2.1 is enforced with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/resident_cannot_respond_for_other_lease
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Ownership Court")
        u1 = create_unit(prop["id"], unit_number="O1")
        u2 = create_unit(prop["id"], unit_number="O2")
        ra = create_resident(full_name="Own ErA", email="own.era@x.com")
        rb = create_resident(full_name="Own ErB", email="own.erb@x.com")
        lease_a = create_lease(u1["id"], ra["id"])
        create_lease(u2["id"], rb["id"])
        offer = create_offer_for_lease(lease_a, rate_strategy="CONSERVATIVE")
        issue_offer(offer["id"])
        # Resident B holds the right role but not the right identity.
        resp = api.respond_to_offer(
            offer["id"], respond_accept_payload(), make_resident_headers(rb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        from test_helpers import get_offer
        assert get_offer(offer["id"])["status"] == "ISSUED"


class TestPropertyOcc:
    def test_occ_property_patch_stale_version(self, api):
        """PRD §2.7: "Updating a property's name or staggering band requires
        `expected_property_version` in the same way. A mismatch with the property's
        current `version` is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412).
        No other endpoint accepts a version field; all other mutations proceed
        without an OCC check."

        Design: Corner/cross_cutting_layers/occ_property_patch_stale_version
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Patch Court")
        observed = prop["version"]
        resp = api.patch_property(
            prop["id"], {"min_term_months": 9, "expected_property_version": observed},
            ADMIN)
        data = validate_success(resp, 200)
        assert data["min_term_months"] == 9
        assert data["version"] == observed + 1
        # Replaying the stale version is rejected even though the payload is valid.
        resp = api.patch_property(
            prop["id"], {"min_term_months": 10, "expected_property_version": observed},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_PROPERTY_VERSION)
        current = validate_success(api.get_property(prop["id"], ADMIN), 200)
        assert current["min_term_months"] == 9
