"""Parade creation, reads, posture derivation, and the lock gate."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, assert_parade,
)


class TestParadeCreation:

    def test_create_parade_born_with_draft_restricted_defaults(self, api):
        """PRD §3.1: "The edition is born with `status` set to `DRAFT`, `posture`
        computed as `RESTRICTED`, `script_finalized` false, both derived counters
        `approved_entry_count` and `sponsor_seconds_allocated` at zero, and
        `version` 1."

        Design: Corner/entities/create_parade_success_with_defaults
        """
        resp = api.create_parade(
            th.create_parade_payload(name="Founders Day Parade"),
            th.TEST_USERS["committee_admin_headers"],
        )
        parade = validate_success(resp, 201)
        assert_parade(parade)
        assert parade["status"] == "DRAFT", f"expected DRAFT, got {parade['status']}"
        assert parade["posture"] == "RESTRICTED", f"expected RESTRICTED, got {parade['posture']}"
        assert parade["approved_entry_count"] == 0
        assert parade["sponsor_seconds_allocated"] == 0
        assert parade["script_finalized"] is False
        assert parade["version"] == 1

    def test_get_parade_not_found(self, api):
        """PRD §2.6: "the request is rejected at the first path segment whose
        `{id}` does not resolve, with the not-found error that corresponds to
        that segment's resource type."

        Design: Corner/entities/get_parade_not_found_returns_404
        """
        resp = api.get_parade(NON_EXISTENT_UUID, th.TEST_USERS["committee_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PARADE_NOT_FOUND)

    def test_route_segment_under_missing_parade_not_found(self, api):
        """PRD §2.6: "The server first resolves the parade identifier, then the
        intermediate resource identifier (permit, entry, float, and so on), then
        the child identifier; the request is rejected at the first path segment
        whose `{id}` does not resolve, with the not-found error that corresponds
        to that segment's resource type."

        Design: Corner/entities/route_segment_under_missing_parade_returns_not_found
        """
        resp = api.create_route_segment(
            NON_EXISTENT_UUID,
            th.create_route_segment_payload(),
            th.TEST_USERS["committee_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PARADE_NOT_FOUND)


class TestPostureComputation:

    def test_posture_restricted_before_grant_despite_approved_plan(self, api):
        """PRD §2.4: "Otherwise, the posture is `OPERATIONAL` exactly when three
        conditions hold together: the permit is `GRANTED`, a dispersal plan of
        the parade is `APPROVED`, and the parade's own status is one of
        `PERMIT_GRANTED`, `LOCKED`, or `LINEUP_PUBLISHED`. In every remaining
        situation the posture is `RESTRICTED`."

        Design: Corner/endpoints/posture_computed_read_transitions_with_permit_and_plan
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Posture Parade")
        th.add_route_segment(parade["id"])
        th.add_staging_area(parade["id"])
        th.approve_dispersal_plan_for_parade(parade["id"])
        permit = th.create_permit(parade["id"])
        endorsements = th.request_all_endorsements(permit)
        get_success_data(api.submit_parade_permit(parade["id"], committee))
        get_success_data(api.submit_permit(permit["id"], committee))
        for endorsement in endorsements:
            get_success_data(
                api.endorse_endorsement(endorsement["id"], th.TEST_USERS["agency_reviewer_headers"])
            )

        pre = validate_success(api.get_parade(parade["id"], committee))
        assert pre["posture"] == "RESTRICTED", (
            f"posture must be RESTRICTED before grant even with the plan APPROVED, got {pre['posture']}"
        )

    def test_posture_operational_immediately_after_grant(self, api):
        """PRD §3.2: "Granting requires that each of the four agency types hold
        at least one `ENDORSED` endorsement — otherwise `ERR_INVALID_STATE` —
        and moves the permit from `AGENCY_REVIEW` to `GRANTED`; the same write
        flips the parade from `PERMIT_PENDING` to `PERMIT_GRANTED` and
        recomputes its posture."
        PRD §2.4: "Otherwise, the posture is `OPERATIONAL` exactly when three
        conditions hold together: the permit is `GRANTED`, a dispersal plan of
        the parade is `APPROVED`, and the parade's own status is one of
        `PERMIT_GRANTED`, `LOCKED`, or `LINEUP_PUBLISHED`."

        Design: Corner/endpoints/posture_computed_read_transitions_with_permit_and_plan
        """
        ctx = th.setup_operational_parade(name="Posture Parade")
        assert ctx["parade"]["status"] == "PERMIT_GRANTED"
        assert ctx["parade"]["posture"] == "OPERATIONAL", (
            f"posture must flip to OPERATIONAL in the same write as the grant, got {ctx['parade']['posture']}"
        )


class TestLockGate:

    def test_lock_before_permit_grant_rejected(self, api):
        """PRD §3.9: "When the permit is not `GRANTED`, the lock attempt is
        rejected with `ERR_PERMIT_NOT_GRANTED`; other from-state mismatches
        surface `ERR_INVALID_STATE`."

        Design: Corner/validations/lock_before_permit_grant_rejected
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        ctx = th.setup_permit_pending_parade(name="Lock Parade")
        th.approve_dispersal_plan_for_parade(ctx["parade"]["id"])
        get_success_data(api.submit_permit(ctx["permit"]["id"], committee))

        resp = api.lock_parade(ctx["parade"]["id"], committee)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_GRANTED)

        parade = validate_success(api.get_parade(ctx["parade"]["id"], committee))
        assert parade["status"] == "PERMIT_PENDING"
        assert parade["posture"] == "RESTRICTED"
