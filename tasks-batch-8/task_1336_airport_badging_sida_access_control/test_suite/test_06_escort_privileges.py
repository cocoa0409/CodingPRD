"""Escort privilege granting, OCC, supersession, and revocation."""
from test_helpers import (
    BO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    get_badge,
    grant_escort_privilege,
    make_security_manager_headers,
    setup_issued_badge,
    suspend_badge,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOptimisticConcurrency:

    def test_escort_grant_stale_version_rejected_412(self):
        """PRD section 2.11: "The request must carry `expected_badge_version`,
        an integer equal to the badge's `version` as last observed by the
        client. If another writer has advanced the badge's version since that
        observation — for any reason, including a prior grant that superseded
        a privilege the client never saw — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/escort_grant_stale_version_rejected_412
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B2501")
        badge = ctx["badge"]
        assert badge["version"] == 1

        ep1 = grant_escort_privilege(badge["id"], badge["version"],
                                     max_escortees=3, manager_id="mgr-1")
        assert ep1["status"] == "GRANTED"
        assert get_badge(badge["id"])["version"] == 2, \
            "the grant advanced the badge version"

        resp = api_client.grant_escort_privilege(
            badge["id"],
            {"max_escortees": 5, "expected_badge_version": badge["version"]},
            make_security_manager_headers("mgr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        lst, meta = validate_paginated(
            api_client.list_escort_privileges(badge["id"], BO))
        assert meta["total_count"] == 1, "no second privilege was created"
        assert lst[0]["status"] == "GRANTED"


class TestSupersession:

    def test_escort_grant_supersedes_prior_grant(self):
        """PRD section 3.6: "A badge holds at most one live privilege, so a
        successful grant supersedes any currently `GRANTED` privilege on the
        same badge, retiring it to `REVOKED` with `revoked_reason`
        `SUPERSEDED`; the grant also increments the badge's `version` by one,
        which is precisely the advance a stale client would fail to match."

        Design: Corner/cross_cutting_layers/escort_grant_supersedes_prior_grant
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B2601")
        badge = ctx["badge"]
        ep1 = grant_escort_privilege(badge["id"], badge["version"],
                                     max_escortees=3, manager_id="mgr-1")
        v2 = get_badge(badge["id"])["version"]
        assert v2 == 2

        ep2 = grant_escort_privilege(badge["id"], v2, max_escortees=5,
                                     manager_id="mgr-2")
        assert ep2["status"] == "GRANTED"
        assert ep2["max_escortees"] == 5

        lst, meta = validate_paginated(
            api_client.list_escort_privileges(badge["id"], BO))
        assert meta["total_count"] == 2
        assert lst[0]["id"] == ep1["id"], "created_at ascending: ep1 first"
        assert lst[0]["status"] == "REVOKED"
        assert lst[0]["revoked_reason"] == "SUPERSEDED"
        assert lst[1]["id"] == ep2["id"]
        assert lst[1]["status"] == "GRANTED", \
            "exactly one GRANTED privilege exists per badge"

        assert get_badge(badge["id"])["version"] == 3, \
            "the superseding grant also advanced the badge"


class TestGrantGuards:

    def test_grant_escort_on_suspended_badge_rejected(self):
        """PRD section 2.11: "The version check is evaluated after the state
        validations, so a grant against a non-`ACTIVE` badge fails with
        `ERR_BADGE_NOT_ACTIVE` even when the supplied version is also wrong."

        Design: Corner/validations/grant_escort_on_suspended_badge_rejected
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1601")
        badge = ctx["badge"]
        suspend_badge(badge["id"], manager_id="mgr-1", reason="review")
        current_version = get_badge(badge["id"])["version"]

        resp = api_client.grant_escort_privilege(
            badge["id"],
            {"max_escortees": 3, "expected_badge_version": current_version},
            make_security_manager_headers("mgr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_NOT_ACTIVE)

    def test_grant_escort_max_out_of_range_returns_invalid_request(self):
        """PRD section 3.6: "carrying a `max_escortees` limit — an integer no
        lower than 1 and no higher than 10, with out-of-range values rejected
        as `ERR_INVALID_REQUEST`".

        Design: Corner/validations/grant_escort_max_out_of_range_returns_invalid_request
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1901")
        badge = ctx["badge"]
        resp = api_client.grant_escort_privilege(
            badge["id"],
            {"max_escortees": 11, "expected_badge_version": badge["version"]},
            make_security_manager_headers("mgr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        lst, meta = validate_paginated(
            api_client.list_escort_privileges(badge["id"], BO))
        assert lst == [] and meta["total_count"] == 0, \
            "a rejected grant must not persist a privilege"


class TestManualRevocation:

    def test_revoke_escort_privilege_twice_rejected(self):
        """PRD section 3.6: "A `SecurityManager` may also revoke a live
        privilege outright, moving it from `GRANTED` to `REVOKED` with
        `revoked_reason` `MANUAL`; acting on a privilege that is not `GRANTED`
        is refused with `ERR_ESCORT_NOT_GRANTED`."

        Design: Corner/state_machines/revoke_escort_privilege_twice_rejected
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B301")
        badge = ctx["badge"]
        ep1 = grant_escort_privilege(badge["id"], badge["version"],
                                     max_escortees=3, manager_id="mgr-1")

        first = api_client.revoke_escort_privilege(
            ep1["id"], make_security_manager_headers("mgr-1"))
        data = validate_success(first)
        assert data["status"] == "REVOKED"
        assert data["revoked_reason"] == "MANUAL"

        second = api_client.revoke_escort_privilege(
            ep1["id"], make_security_manager_headers("mgr-1"))
        validate_error(second, ApiErrorId.ERR_ESCORT_NOT_GRANTED)

    def test_revoke_escort_privilege_not_found_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/revoke_escort_privilege_not_found_returns_404
        """
        resp = api_client.revoke_escort_privilege(
            NON_EXISTENT_UUID, make_security_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_ESCORT_PRIVILEGE_NOT_FOUND)
