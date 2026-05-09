"""Co-ownership and access grants — invariants, duplicates (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_co_owner_payload, create_access_grant_payload,
    setup_active_individual_objective,
    setup_confidential_objective,
    create_user, make_employee_headers,
)


# ---------------------------------------------------------------------------
# Difficulty-design: compensating_invariant/co_owner_add_remove_weight_sum_invariant
# ---------------------------------------------------------------------------

class TestCoOwnerWeightSumInvariant:
    """# difficulty: compensating_invariant/co_owner_add_remove_weight_sum_invariant"""

    def test_add_then_remove_co_owner_restores_weight_sum_invariant(self, api):
        """PRD §3.6: "Adding a co-owner is an owner-gated action (or `PlatformAdmin` override) that returns the new `CoOwnership` row with status `ACTIVE`".
        PRD §3.6: "Removing a co-owner advances the row to `REMOVED`. The list view of co-owners returns the active set."

        Claim: baseline list has 0 ACTIVE rows; add → 1 ACTIVE row; remove → 0 ACTIVE rows.
        Sum of contribution_weight returns to 0.0 after compensating.
        # difficulty: compensating_invariant/co_owner_add_remove_weight_sum_invariant
        """
        s = setup_active_individual_objective()
        org = s["org"]
        # Create distinct co-owner candidate
        co_owner_user = create_user(org["department"]["id"], role_type="EMPLOYEE",
                                    manager_id=org["manager_user"]["id"])
        owner_headers = org["employee_headers"]

        # Baseline
        baseline = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        baseline_rows = baseline if isinstance(baseline, list) else []
        # validate_success returns data; for list it's the data array.
        baseline_active = [r for r in baseline_rows if r["status"] == "ACTIVE"]
        baseline_sum = sum(float(r["contribution_weight"]) for r in baseline_active)
        assert len(baseline_active) == 0
        assert baseline_sum == pytest.approx(0.0, abs=1e-9)

        # Forward: add
        add_resp = api.add_co_owner(
            s["objective"]["id"],
            create_co_owner_payload(co_owner_user["id"], 0.3000),
            owner_headers,
        )
        validate_success(add_resp, expected_status=201)

        after_add = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        after_add_rows = after_add if isinstance(after_add, list) else []
        after_add_active = [r for r in after_add_rows if r["status"] == "ACTIVE"]
        after_add_sum = sum(float(r["contribution_weight"]) for r in after_add_active)
        assert len(after_add_active) == 1
        assert after_add_sum == pytest.approx(0.3, abs=1e-6)

        # Compensating: remove
        rm_resp = api.remove_co_owner(s["objective"]["id"], co_owner_user["id"], owner_headers)
        # 204 with empty body
        assert rm_resp.status_code == 204

        after_rm = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        after_rm_rows = after_rm if isinstance(after_rm, list) else []
        after_rm_active = [r for r in after_rm_rows if r["status"] == "ACTIVE"]
        after_rm_sum = sum(float(r["contribution_weight"]) for r in after_rm_active)
        assert len(after_rm_active) == 0
        assert after_rm_sum == pytest.approx(0.0, abs=1e-9)
        # Invariant: baseline sum == post-compensating sum
        assert after_rm_sum == pytest.approx(baseline_sum, abs=1e-9)


# ---------------------------------------------------------------------------
# Co-owner constraints
# ---------------------------------------------------------------------------

class TestCoOwnerConstraints:
    def test_duplicate_active_co_owner_rejected(self, api):
        """PRD §3.6: "an attempt to add a second `ACTIVE` co-ownership for the same (`objective_id`, `co_owner_user_id`) pair is rejected with `ERR_DUPLICATE_CO_OWNER`."
        """
        s = setup_active_individual_objective()
        org = s["org"]
        co_user = create_user(org["department"]["id"], role_type="EMPLOYEE",
                              manager_id=org["manager_user"]["id"])
        # First add succeeds
        api.add_co_owner(
            s["objective"]["id"],
            create_co_owner_payload(co_user["id"], 0.3),
            org["employee_headers"],
        )
        # Second add for same pair → ERR_DUPLICATE_CO_OWNER
        resp = api.add_co_owner(
            s["objective"]["id"],
            create_co_owner_payload(co_user["id"], 0.2),
            org["employee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CO_OWNER.value)


# ---------------------------------------------------------------------------
# Difficulty-design: compensating_invariant/access_grant_grant_revoke_count_invariant
# ---------------------------------------------------------------------------

class TestAccessGrantCountInvariant:
    """# difficulty: compensating_invariant/access_grant_grant_revoke_count_invariant"""

    def test_grant_then_revoke_restores_active_count_invariant(self, api):
        """PRD §3.8: "Granting access creates an `AccessGrant` row tying the parent `objective_id` to a `user_id` with `granted_by_user_id` captured from `X-User-ID` and `status` initialized to `ACTIVE`".
        PRD §3.8: "Revoking advances the grant's `status` from `ACTIVE` to `REVOKED`. The list view returns active grants only".

        Claim: baseline count of ACTIVE rows = 0; grant → 1; revoke → 0.
        # difficulty: compensating_invariant/access_grant_grant_revoke_count_invariant
        """
        s = setup_confidential_objective()
        owner_headers = s["org"]["employee_headers"]
        reader = s["reader_user"]

        # Baseline
        baseline = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        baseline_rows = baseline if isinstance(baseline, list) else []
        assert len(baseline_rows) == 0

        # Forward
        validate_success(api.create_access_grant(
            s["objective"]["id"],
            create_access_grant_payload(reader["id"]),
            owner_headers,
        ), expected_status=201)
        after_grant = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        after_grant_rows = after_grant if isinstance(after_grant, list) else []
        assert len(after_grant_rows) == 1
        assert after_grant_rows[0]["status"] == "ACTIVE"

        # Compensating
        rm_resp = api.revoke_access_grant(s["objective"]["id"], reader["id"], owner_headers)
        assert rm_resp.status_code == 204
        after_revoke = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        after_revoke_rows = after_revoke if isinstance(after_revoke, list) else []
        assert len(after_revoke_rows) == 0


# ---------------------------------------------------------------------------
# Confidential visibility
# ---------------------------------------------------------------------------

class TestConfidentialVisibility:
    def test_confidential_read_by_outside_employee_returns_err_not_visible(self, api):
        """PRD §3.8: "A confidential objective is not returned to readers outside its access list... and direct read returns `ERR_NOT_VISIBLE`."

        Claim: Employee not on access list reads → ERR_NOT_VISIBLE.
        """
        s = setup_confidential_objective()
        resp = api.get_objective(s["objective"]["id"], s["reader_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_VISIBLE.value)

    def test_confidential_read_by_owner_succeeds(self, api):
        """PRD §3.8: "the primary `owner_user_id` always sees it"."""
        s = setup_confidential_objective()
        resp = api.get_objective(s["objective"]["id"], s["org"]["employee_headers"])
        validate_success(resp)

    def test_confidential_read_by_grantee_succeeds_after_grant(self, api):
        """PRD §3.8: "any user named in an `ACTIVE` `AccessGrant` for the objective sees it."""
        s = setup_confidential_objective()
        # Grant access to reader
        api.create_access_grant(
            s["objective"]["id"],
            create_access_grant_payload(s["reader_user"]["id"]),
            s["org"]["employee_headers"],
        )
        # Reader can now see
        resp = api.get_objective(s["objective"]["id"], s["reader_headers"])
        validate_success(resp)


# ---------------------------------------------------------------------------
# Duplicate access grants
# ---------------------------------------------------------------------------

class TestDuplicateAccessGrant:
    def test_duplicate_active_access_grant_rejected(self, api):
        """PRD §3.8: "A second `ACTIVE` grant for the same (`objective_id`, `user_id`) pair is rejected with `ERR_DUPLICATE_GRANT`."
        """
        s = setup_confidential_objective()
        owner_headers = s["org"]["employee_headers"]
        api.create_access_grant(
            s["objective"]["id"],
            create_access_grant_payload(s["reader_user"]["id"]),
            owner_headers,
        )
        resp = api.create_access_grant(
            s["objective"]["id"],
            create_access_grant_payload(s["reader_user"]["id"]),
            owner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GRANT.value)
