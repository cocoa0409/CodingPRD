"""Permit lifecycle: revision loop, four-eyes SoD, zones-active gate, RBAC, invalid state.

Covers difficulty queue A: non_linear_state_machine (permit revision cycle),
priority_pair_validation_conflict (SoD beats zone-inactive),
cross_entity_state_dependency (approve requires zones active). Plus corner cases:
approve-from-draft invalid state, officer-cannot-approve RBAC.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_curb_planner_headers,
    make_permit_approver_headers,
    make_enforcement_officer_headers,
    advance_clock,
    make_policy,
    make_zone,
    make_permittee,
    make_permit,
    submit_permit,
    review_permit,
)


def _permit_under_review(api, reviewer="planner1"):
    """Policy + ACTIVE zone + permittee + a permit walked to UNDER_REVIEW."""
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])
    submit_permit(api, permit["id"], permittee["id"])
    review_permit(api, permit["id"], reviewer)
    return {"zone": zone, "permittee": permittee, "permit": permit,
            "zone_id": zone["id"], "permittee_id": permittee["id"], "permit_id": permit["id"]}


class TestPermitRevisionCycle:
    """DRAFT -> SUBMITTED -> UNDER_REVIEW -> DRAFT then forward again to ACTIVE."""

    def _run_cycle(self, api):
        advance_clock(api, "2026-05-20T00:00:00Z")
        policy = make_policy(api)
        zone = make_zone(api, policy["id"])
        permittee = make_permittee(api)
        pid = make_permit(api, permittee["id"], [zone["id"]])["id"]
        pmid = permittee["id"]
        submit_permit(api, pid, pmid)
        review_permit(api, pid, "planner1")
        get_success_data(api.request_changes_permit(pid, "add insurance", make_curb_planner_headers("planner1")))
        submit_permit(api, pid, pmid)
        review_permit(api, pid, "planner1")
        approved = get_success_data(api.approve_permit(pid, make_permit_approver_headers("approver1")))
        return approved

    def test_permit_reenters_draft_then_reaches_active(self, api):
        """PRD §3.2: "From UNDER_REVIEW the planner may send the permit back for
        revision with a note — this records the supplied text as last_change_note and
        returns the permit to DRAFT, forming the revision loop DRAFT -> SUBMITTED ->
        UNDER_REVIEW -> DRAFT that may repeat as many times as needed."

        Design: Difficulty/non_linear_state_machine/permit_revision_cycle
        """
        approved = self._run_cycle(api)
        assert approved["status"] == "ACTIVE"
        assert approved["last_change_note"] == "add insurance"

    def test_version_increments_once_per_mutation_across_cycle(self, api):
        """PRD §2.4: "The version is an integer that starts at 1 on creation and
        increments by one on every subsequent mutation."

        Design: Difficulty/non_linear_state_machine/permit_revision_cycle
        """
        approved = self._run_cycle(api)
        # create(1) + submit + review + request-changes + submit + review + approve = 7
        assert approved["version"] == 7


class TestApproveSoDPrecedence:
    """SoD (priority 5) is surfaced before the zones-active gate (priority 6)."""

    def _setup_sod_and_suspended_zone(self, api):
        ctx = _permit_under_review(api, reviewer="u1")
        # Suspend the permit's only zone so the zones-active gate would also fail.
        get_success_data(api.set_zone_status(ctx["zone_id"], "SUSPENDED", make_curb_planner_headers("planner1")))
        return ctx

    def test_sod_error_wins_over_zone_inactive(self, api):
        """PRD §2.9: "then segregation of duties on permit approval and denial
        (ERR_SEGREGATION_OF_DUTIES), then cross-entity state gates such as zones-active
        and permit-active (ERR_ZONE_NOT_ACTIVE and ERR_PERMIT_NOT_ACTIVE)".

        Design: Difficulty/priority_pair_validation_conflict/approve_sod_beats_zone_inactive
        """
        ctx = self._setup_sod_and_suspended_zone(api)
        # Approver X-User-ID 'u1' equals the recorded reviewer_user_id.
        resp = api.approve_permit(ctx["permit_id"], make_permit_approver_headers("u1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_permit_unchanged_after_sod_rejection(self, api):
        """PRD §2.11: "The X-User-ID performing the approval or denial must differ from
        the recorded reviewer_user_id. If they are equal, the action is refused with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)".

        Design: Difficulty/priority_pair_validation_conflict/approve_sod_beats_zone_inactive
        """
        ctx = self._setup_sod_and_suspended_zone(api)
        api.approve_permit(ctx["permit_id"], make_permit_approver_headers("u1"))
        fetched = validate_success(api.get_permit(ctx["permit_id"], make_curb_planner_headers("planner1")))
        assert fetched["status"] == "UNDER_REVIEW"


class TestApproveRequiresZonesActive:
    """A SUSPENDED zone in permit.zone_ids blocks approval even when SoD passes."""

    def _setup_suspended_zone_distinct_approver(self, api):
        ctx = _permit_under_review(api, reviewer="planner1")
        get_success_data(api.set_zone_status(ctx["zone_id"], "SUSPENDED", make_curb_planner_headers("planner1")))
        return ctx

    def test_suspended_zone_blocks_approval(self, api):
        """PRD §3.2: "Approving an UNDER_REVIEW permit requires that the approver's
        X-User-ID differ from the recorded reviewer_user_id (otherwise
        ERR_SEGREGATION_OF_DUTIES) and that every zone named in zone_ids currently has
        status of ACTIVE (otherwise ERR_ZONE_NOT_ACTIVE)".

        Design: Difficulty/cross_entity_state_dependency/approve_requires_zones_active
        """
        ctx = self._setup_suspended_zone_distinct_approver(api)
        resp = api.approve_permit(ctx["permit_id"], make_permit_approver_headers("approver1"))
        validate_error(resp, ApiErrorId.ERR_ZONE_NOT_ACTIVE)

    def test_permit_stays_under_review_when_zone_inactive(self, api):
        """PRD §3.2: "on success the permit moves to ACTIVE and the approver's X-User-ID
        is recorded as approver_user_id."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_zones_active
        """
        ctx = self._setup_suspended_zone_distinct_approver(api)
        api.approve_permit(ctx["permit_id"], make_permit_approver_headers("approver1"))
        fetched = validate_success(api.get_permit(ctx["permit_id"], make_curb_planner_headers("planner1")))
        assert fetched["status"] == "UNDER_REVIEW"


def test_approve_permit_in_draft_rejected_invalid_state(api):
    """PRD §3.2: "Each of these transitions increments the permit's version by one, and
    each is defined only from UNDER_REVIEW; attempting it from any other state yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_from_draft_invalid_state
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])  # stays DRAFT
    resp = api.approve_permit(permit["id"], make_permit_approver_headers("approver1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_permit(permit["id"], make_curb_planner_headers("planner1")))
    assert fetched["status"] == "DRAFT"


def test_enforcement_officer_cannot_approve_permit(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/officer_cannot_approve_permit
    """
    ctx = _permit_under_review(api, reviewer="planner1")
    resp = api.approve_permit(ctx["permit_id"], make_enforcement_officer_headers("officer1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
