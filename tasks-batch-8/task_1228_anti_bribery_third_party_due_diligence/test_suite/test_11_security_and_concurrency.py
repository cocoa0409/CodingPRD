"""Authentication, authorization, ownership, optimistic concurrency, policy shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    admin_headers,
    create_country,
    create_draft_third_party,
    create_active_policy,
    get_third_party,
    officer_headers,
    policy_payload,
    sponsor_headers,
    validate_error,
    validate_success,
)
from test_helpers.test_users import SPONSOR_2_ID


class TestAuthenticationAuthorization:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
        the acting operator, and `X-User-Role`, naming the operator's role. A
        request missing either header, or presenting a role outside the declared
        set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_third_parties()  # no X-User-ID / X-User-Role at all
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unauthorized_role_beats_not_found(self, api, sponsor_headers):
        """PRD §2.9: "First, authentication: missing or invalid headers yield
        `ERR_UNAUTHENTICATED`. Second, role authorization: an unauthorized role
        yields `ERR_UNAUTHORIZED_ROLE`. Third, existence, evaluated left to right
        across the path: any unresolved identifier — or an unresolvable
        `country_code` at third-party registration — yields `ERR_NOT_FOUND`."

        Design: Corner/validations/unauthorized_role_beats_not_found
        """
        # BusinessSponsor is not in approve's role list; the path id does not
        # exist. Role authorization (tier 2) masks existence (tier 3).
        resp = api.approve_third_party(NON_EXISTENT_UUID, sponsor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnership:
    def test_sponsor_cannot_patch_others_third_party(self, api, sponsor2_headers):
        """PRD §2.8: "Ownership binds a sponsor to their own book of third
        parties. The `sponsor_user_id` stamped at registration is compared
        against the caller's `X-User-ID` whenever a sponsor updates a third-party
        profile, submits a third party for screening, submits questionnaire
        answers, or submits a certification document; acting on another sponsor's
        record is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/sponsor_cannot_patch_others_third_party
        """
        create_country("CH", 80)
        tp = create_draft_third_party("CH", "TECHNOLOGY", "NONE")  # owned by u_sp1

        # u_sp2 reads the CURRENT version (the OCC check passes) and still fails
        # ownership.
        observed = validate_success(
            api.get_third_party(tp["id"], sponsor2_headers), 200)["version"]
        resp = api.patch_third_party(
            tp["id"],
            {"legal_name": "Hijacked Name", "expected_third_party_version": observed},
            sponsor2_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        after = validate_success(api.get_third_party(tp["id"], sponsor2_headers), 200)
        assert after["legal_name"] == "CH Tech GmbH"


class TestOptimisticConcurrency:
    def test_third_party_patch_stale_version_returns_412(self, api, sponsor_headers):
        """PRD §2.7: "Issuing a questionnaire for a third party and updating a
        third party's profile each require the non-optional field
        `expected_third_party_version`, carrying the third party's `version` as
        the client last read it"
        PRD §2.7: "In all three cases a mismatch with the parent's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "While the record remains in `DRAFT`, the owning sponsor may
        correct `legal_name`, `industry`, or `government_touchpoint` through a
        profile update carrying `expected_third_party_version`."
        PRD §3.2: "Each accepted update increments the third party's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/third_party_patch_stale_version_returns_412
        """
        create_country("CH", 80)
        tp = create_draft_third_party("CH", "TECHNOLOGY", "NONE")
        observed = tp["version"]

        first = validate_success(
            api.patch_third_party(
                tp["id"], {"industry": "LOGISTICS", "expected_third_party_version": observed},
                sponsor_headers), 200)
        assert first["version"] == observed + 1
        assert first["industry"] == "LOGISTICS"

        stale = api.patch_third_party(
            tp["id"], {"industry": "CONSULTING", "expected_third_party_version": observed},
            sponsor_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_third_party(tp["id"])
        assert after["industry"] == "LOGISTICS", "the stale replay must not apply"

    def test_policy_activate_stale_version_returns_412(self, api, admin_headers):
        """PRD §2.7: "Activating a scoring policy requires the non-optional field
        `expected_policy_version`, carrying that policy's last-observed
        `version`; activation supersedes whichever policy is currently active, so
        a stale activation would swap the global scoring basis the client never
        reviewed. In all three cases a mismatch with the parent's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.9: "Fourth, optimistic concurrency: a stale
        `expected_third_party_version` or `expected_policy_version` yields
        `ERR_STALE_VERSION`. Fifth, state-machine legality: within this tier the
        terminal-state check is evaluated first and takes precedence, so an
        action against an entity already in a terminal state reports
        `ERR_ALREADY_TERMINAL`, and only otherwise does an illegal from-state
        report `ERR_INVALID_STATE`."
        PRD §3.1: "Activation — which requires `expected_policy_version` per §2.7
        — moves it from `DRAFT` to `ACTIVE`, flips whichever policy was
        previously `ACTIVE` to `SUPERSEDED`, and increments the policy's
        `version` by one, so at most one policy is ever `ACTIVE`."

        Design: Corner/cross_cutting_complexity_layers/policy_activate_stale_version_returns_412
        """
        policy = validate_success(api.create_policy(policy_payload(), admin_headers), 201)
        observed = policy["version"]

        activated = validate_success(
            api.activate_policy(policy["id"], {"expected_policy_version": observed},
                                admin_headers), 200)
        assert activated["policy_status"] == "ACTIVE"
        assert activated["version"] == observed + 1, "activation bumps the version by one"

        # Replaying with the pre-activation version: OCC (tier 4) fires before
        # the from-state check (tier 5) that an ACTIVE policy can no longer be
        # activated.
        stale = api.activate_policy(policy["id"], {"expected_policy_version": observed},
                                    admin_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestPolicyShape:
    def test_policy_weights_not_summing_100_rejected(self, api, admin_headers):
        """PRD §3.1: "Its three component weights — `w_country`, `w_industry`,
        and `w_touchpoint` — must sum to exactly 100, and any other total is a
        malformed request rejected with `ERR_VALIDATION`."

        Design: Corner/validations/policy_weights_not_summing_100_rejected
        """
        resp = api.create_policy(policy_payload(w_touchpoint=30), admin_headers)
        # 50 + 30 + 30 = 110 violates the sum-to-100 constraint.
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
