"""Security role grants: approval authority checks, SoD, windows, expiry, revocation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    approve_grant_record,
    create_data_field_record,
    create_grant_record,
    create_position_record,
    create_worker_change_request_record,
    create_worker_record,
    list_audit_entries,
    make_security_admin_headers,
    provision_grant,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

SECADMIN = TEST_USERS["security_admin_headers"]
STEWARD = TEST_USERS["steward_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestGrantLifecycle:
    def test_grant_approved_then_provisioned_on_valid_from_sweep(self, api):
        """PRD §3.8: "A successful approval records `approved_by` as the
        approver's `X-User-ID`, writes an audit entry with action `GRANT_APPROVE`,
        and — when the clock date has already reached `valid_from` — provisions
        the grant immediately rather than leaving it waiting."
        PRD §3.8: "Thereafter the clock drives the window: an `APPROVED` grant
        becomes `PROVISIONED` once the clock date sits inside the inclusive
        window, and an `APPROVED` or `PROVISIONED` grant becomes `EXPIRED` once
        the clock passes `valid_until`."

        Design: Corner/state_machines/grant_approved_then_provisioned_on_valid_from_sweep
        """
        grant = create_grant_record(
            "op-7", "HRIS_ANALYST", valid_from="2026-09-01", valid_until="2027-03-01",
        )
        approved = approve_grant_record(grant["id"], approver_user_id="secadmin-1")
        assert approved["status"] == "APPROVED"

        advance_clock("2026-09-01T00:00:00Z")

        resp = api.list_security_role_assignments(SECADMIN, params={"user_id": "op-7"})
        from test_helpers import get_success_data
        grants = get_success_data(resp)
        assert grants[0]["status"] == "PROVISIONED"

    def test_grant_invalid_window_rejected(self, api):
        """PRD §3.8: "Approving a grant runs the authority tier of §2.8 in order.
        The grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver
        may not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`);
        segregation of duties forbids one operator from holding both roles of a
        conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or
        `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or
        `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED`
        grant for the same `user_id` and `role_code` may have a closed window
        overlapping the new one, with touching endpoints counting as overlap
        (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from`
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/grant_invalid_window_rejected
        """
        create_position_record()  # DB non-empty
        resp = api.create_security_role_assignment(
            {
                "user_id": "op-8",
                "role_code": "DATA_STEWARD",
                "valid_from": "2026-09-01",
                "valid_until": "2026-08-01",
            },
            SECADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_grant_window_overlap_touching_rejected_disjoint_allowed(self, api):
        """PRD §3.8: "Approving a grant runs the authority tier of §2.8 in order.
        The grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver
        may not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`);
        segregation of duties forbids one operator from holding both roles of a
        conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or
        `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or
        `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED`
        grant for the same `user_id` and `role_code` may have a closed window
        overlapping the new one, with touching endpoints counting as overlap
        (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from`
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/grant_window_overlap_touching_rejected_disjoint_allowed
        """
        g1 = create_grant_record(
            "op-9", "DATA_STEWARD", valid_from="2026-08-01", valid_until="2026-12-31",
        )
        approve_grant_record(g1["id"], approver_user_id="secadmin-2")
        g2 = create_grant_record(
            "op-9", "DATA_STEWARD", valid_from="2026-12-31", valid_until="2027-06-30",
        )
        g3 = create_grant_record(
            "op-9", "DATA_STEWARD", valid_from="2027-01-01", valid_until="2027-06-30",
        )

        err = api.approve_security_role_assignment(g2["id"], make_security_admin_headers("secadmin-1"))
        validate_error(err, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)

        approved3 = validate_success(
            api.approve_security_role_assignment(g3["id"], make_security_admin_headers("secadmin-1"))
        )
        # valid_from 2027-01-01 is ahead of the default clock: APPROVED, not yet PROVISIONED.
        assert approved3["status"] == "APPROVED"

        from test_helpers import get_success_data
        grants = get_success_data(
            api.list_security_role_assignments(SECADMIN, params={"user_id": "op-9"})
        )
        by_id = {g["id"]: g for g in grants}
        assert by_id[g2["id"]]["status"] == "REQUESTED"

    def test_revoke_provisioned_grant_writes_audit(self, api):
        """PRD §3.8: "A `SecurityAdmin` may also revoke a grant from `APPROVED` or
        `PROVISIONED` — from any other state, `ERR_GRANT_INVALID_STATE` —
        supplying an optional `reason`, which lands the grant in `REVOKED` and
        writes an audit entry with action `GRANT_REVOKE`."
        PRD §3.8: "A successful approval records `approved_by` as the approver's
        `X-User-ID`, writes an audit entry with action `GRANT_APPROVE`, and —
        when the clock date has already reached `valid_from` — provisions the
        grant immediately rather than leaving it waiting."

        Design: Corner/state_machines/revoke_provisioned_grant_writes_audit
        """
        grant = create_grant_record(
            "op-11", "HRIS_ANALYST", valid_from="2026-08-01", valid_until="2027-08-01",
        )
        approved = approve_grant_record(grant["id"], approver_user_id="secadmin-2")
        assert approved["status"] == "PROVISIONED"

        revoked = validate_success(
            api.revoke_security_role_assignment(
                grant["id"], {"reason": "offboarding"},
                make_security_admin_headers("secadmin-2"),
            )
        )
        assert revoked["status"] == "REVOKED"

        audits = list_audit_entries()
        assert [a["action"] for a in audits] == ["GRANT_APPROVE", "GRANT_REVOKE"]

    def test_revoke_requested_grant_rejected(self, api):
        """PRD §3.8: "A `SecurityAdmin` may also revoke a grant from `APPROVED` or
        `PROVISIONED` — from any other state, `ERR_GRANT_INVALID_STATE` —
        supplying an optional `reason`, which lands the grant in `REVOKED` and
        writes an audit entry with action `GRANT_REVOKE`."

        Design: Corner/state_machines/revoke_requested_grant_rejected
        """
        grant = create_grant_record(
            "op-12", "INTEGRATION_OPERATOR", valid_from="2026-08-01", valid_until="2027-08-01",
        )

        err = api.revoke_security_role_assignment(
            grant["id"], {"reason": "premature"}, make_security_admin_headers("secadmin-1")
        )
        validate_error(err, ApiErrorId.ERR_GRANT_INVALID_STATE)

    def test_grant_expires_on_clock_sweep_and_loses_authority(self, api):
        """PRD §3.8: "Thereafter the clock drives the window: an `APPROVED` grant
        becomes `PROVISIONED` once the clock date sits inside the inclusive
        window, and an `APPROVED` or `PROVISIONED` grant becomes `EXPIRED` once
        the clock passes `valid_until`."
        PRD §3.8: "Only a `PROVISIONED` grant confers acting authority such as the
        change-approval power of §3.4."

        Design: Corner/state_machines/grant_expires_on_clock_sweep_and_loses_authority
        """
        provision_grant(
            "appr-9", "CHANGE_APPROVER",
            valid_from="2026-08-01", valid_until="2026-08-10",
        )
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W761", legal_name="Gx")
        field = create_data_field_record(channels=[])
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )

        advance_clock("2026-08-11T00:00:00Z")

        from test_helpers import get_success_data
        grants = get_success_data(
            api.list_security_role_assignments(SECADMIN, params={"user_id": "appr-9"})
        )
        assert grants[0]["status"] == "EXPIRED"

        from test_helpers import make_approver_headers
        err = api.approve_change_request(cr["id"], make_approver_headers("appr-9"))
        validate_error(err, ApiErrorId.ERR_GRANT_NOT_PROVISIONED)


class TestSegregationOfDuties:
    def test_grant_approve_self_approval_beats_window_overlap(self, api):
        """PRD §2.8: "7. **Approval authority** — within this tier the checks run
        in a fixed order: first the caller must hold a `PROVISIONED` grant with
        `role_code` `CHANGE_APPROVER` (`ERR_GRANT_NOT_PROVISIONED`, 403), then
        self-approval is forbidden (`ERR_SELF_APPROVAL_FORBIDDEN`, 403), then
        segregation-of-duties conflicts are screened (`ERR_SOD_CONFLICT`, which —
        unlike its tier-mates — carries 409)."
        PRD §3.8: "Approving a grant runs the authority tier of §2.8 in order. The
        grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver may
        not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`);
        segregation of duties forbids one operator from holding both roles of a
        conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or
        `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or
        `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED`
        grant for the same `user_id` and `role_code` may have a closed window
        overlapping the new one, with touching endpoints counting as overlap
        (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from`
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Difficulty/priority_pair_validation_conflict/grant_approve_self_approval_beats_window_overlap
        """
        g1 = create_grant_record(
            "secadmin-1", "DATA_STEWARD", valid_from="2026-08-01", valid_until="2026-12-31",
        )
        approve_grant_record(g1["id"], approver_user_id="secadmin-2")
        g2 = create_grant_record(
            "secadmin-1", "DATA_STEWARD", valid_from="2026-10-01", valid_until="2027-03-01",
        )

        # The approver is the grantee AND the window overlaps g1: self-approval wins.
        err = api.approve_security_role_assignment(g2["id"], make_security_admin_headers("secadmin-1"))
        validate_error(err, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

        from test_helpers import get_success_data
        grants = get_success_data(
            api.list_security_role_assignments(SECADMIN, params={"user_id": "secadmin-1"})
        )
        by_id = {g["id"]: g for g in grants}
        assert by_id[g2["id"]]["status"] == "REQUESTED"

    def test_grant_approve_self_approval_beats_window_overlap_exact_window(self, api):
        """PRD §3.8: "Approving a grant runs the authority tier of §2.8 in order.
        The grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver
        may not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`);
        segregation of duties forbids one operator from holding both roles of a
        conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or
        `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or
        `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED`
        grant for the same `user_id` and `role_code` may have a closed window
        overlapping the new one, with touching endpoints counting as overlap
        (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from`
        is rejected with `ERR_INVALID_REQUEST`."

        Same self-vs-overlap pair, exact duplicate window: the reported error is
        still the self-approval error, not the window-overlap error.

        Design: Difficulty/priority_pair_validation_conflict/grant_approve_self_approval_beats_window_overlap
        """
        g1 = create_grant_record(
            "secadmin-1", "DATA_STEWARD", valid_from="2026-08-01", valid_until="2026-12-31",
        )
        approve_grant_record(g1["id"], approver_user_id="secadmin-2")
        g2 = create_grant_record(
            "secadmin-1", "DATA_STEWARD", valid_from="2026-08-01", valid_until="2026-12-31",
        )

        err = api.approve_security_role_assignment(g2["id"], make_security_admin_headers("secadmin-1"))
        validate_error(err, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_sod_conflicting_grant_pair_rejected(self, api):
        """PRD §3.8: "Approving a grant runs the authority tier of §2.8 in order.
        The grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver
        may not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`);
        segregation of duties forbids one operator from holding both roles of a
        conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or
        `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or
        `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED`
        grant for the same `user_id` and `role_code` may have a closed window
        overlapping the new one, with touching endpoints counting as overlap
        (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from`
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/rbac/sod_conflicting_grant_pair_rejected
        """
        g1 = create_grant_record(
            "op-20", "HRIS_ANALYST", valid_from="2026-08-01", valid_until="2027-08-01",
        )
        approved1 = approve_grant_record(g1["id"], approver_user_id="secadmin-2")
        assert approved1["status"] == "PROVISIONED"
        g2 = create_grant_record(
            "op-20", "CHANGE_APPROVER", valid_from="2026-08-01", valid_until="2027-08-01",
        )

        err = api.approve_security_role_assignment(g2["id"], make_security_admin_headers("secadmin-1"))
        validate_error(err, ApiErrorId.ERR_SOD_CONFLICT)
