"""Engagement-creation gates (Daubert bar, roster standing, safety ordering, capacity)
and close-out guards."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_engagement, ApiErrorId,
    create_expert, create_case, open_request, screen_candidate,
    create_draft_engagement, propose_engagement, sign_engagement, terminate_engagement,
    create_conflict_check_payload, create_credential_review_payload,
    create_report, submit_report,
    setup_scenario, setup_active_engagement,
    TEST_USERS, make_expert_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
CONFLICT = TEST_USERS["conflict_analyst_headers"]
CREDENTIAL = TEST_USERS["credential_analyst_headers"]


class TestDaubertBar:

    def _screened_request_for(self, expert, case):
        request = open_request(case["id"])
        screen_candidate(request["id"], expert["id"])
        return request

    def test_exclusion_count_two_passes(self, api):
        """PRD §3.3: "then the Daubert bar — an expert with three or more
        `daubert_exclusion_count` is barred with `ERR_EXPERT_DAUBERT_BARRED`, while exactly
        two still passes".

        Design: Difficulty/boundary_precision_check/daubert_count_exactly_three_barred
        """
        expert = create_expert(full_name="N Ade", daubert_exclusion_count=2)
        case = create_case()
        request = self._screened_request_for(expert, case)
        engagement = create_draft_engagement(request["id"], expert["id"])
        assert_engagement(engagement)
        assert engagement["status"] == "DRAFT"

    def test_exclusion_count_three_barred(self, api):
        """PRD §3.3: "then the Daubert bar — an expert with three or more
        `daubert_exclusion_count` is barred with `ERR_EXPERT_DAUBERT_BARRED`, while exactly
        two still passes".

        Design: Difficulty/boundary_precision_check/daubert_count_exactly_three_barred
        """
        expert = create_expert(full_name="O Bex", daubert_exclusion_count=3)
        case = create_case()
        request = self._screened_request_for(expert, case)
        res = api.create_engagement(
            {"engagement_request_id": request["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_EXPERT_DAUBERT_BARRED)


class TestRosterGate:

    def _setup_probated_ready(self, api):
        """Expert manually probated (no engagements), then a request screened to READY."""
        expert = create_expert(full_name="S Fox")
        probated = validate_success(api.set_roster_status(
            expert["id"], {"to_status": "PROBATION", "rationale": "quality review"}, ADMIN), 200)
        assert probated["roster_status"] == "PROBATION"
        case = create_case()
        request = open_request(case["id"])
        screen_candidate(request["id"], expert["id"])
        return expert, request

    def test_probation_expert_rejected_despite_ready_request(self, api):
        """PRD §3.3: "then roster standing — the expert must be `ACTIVE`, with `PROBATION`
        or `REMOVED` experts rejected as `ERR_EXPERT_ROSTER_INELIGIBLE`".

        Design: Difficulty/cross_entity_state_dependency/engagement_create_requires_expert_roster_active
        """
        expert, request = self._setup_probated_ready(api)
        res = api.create_engagement(
            {"engagement_request_id": request["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_EXPERT_ROSTER_INELIGIBLE)

    def test_reinstated_expert_can_be_engaged(self, api):
        """PRD §3.1: "A `PlatformAdmin` may also move an expert between standings manually
        by submitting a `to_status` with a `rationale`: `ACTIVE` → `PROBATION` (which fires
        the same cascade as the automatic path), `PROBATION` → `ACTIVE` for rehabilitation,
        and `ACTIVE` → `REMOVED` or `PROBATION` → `REMOVED` for removal."
        PRD §3.3: "then roster standing — the expert must be `ACTIVE`, with `PROBATION` or
        `REMOVED` experts rejected as `ERR_EXPERT_ROSTER_INELIGIBLE`".

        Design: Difficulty/cross_entity_state_dependency/engagement_create_requires_expert_roster_active
        """
        expert, request = self._setup_probated_ready(api)
        res = api.create_engagement(
            {"engagement_request_id": request["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_EXPERT_ROSTER_INELIGIBLE)

        reinstated = validate_success(api.set_roster_status(
            expert["id"], {"to_status": "ACTIVE", "rationale": "reinstated"}, ADMIN), 200)
        assert reinstated["roster_status"] == "ACTIVE"

        engagement = create_draft_engagement(request["id"], expert["id"])
        assert engagement["status"] == "DRAFT"


class TestSafetyBeatsConstraint:

    def _setup_flagged_plus_duplicate(self, api):
        """Case with request R1: expert X cleared+passed, engagement E1 (DRAFT).
        Second request R2 on the same case: expert X FLAGGED, expert Y cleared+passed
        (so R2 is READY)."""
        expert_x = create_expert(full_name="K Tan", specialty_area="ip")
        expert_y = create_expert(full_name="L Ueda", specialty_area="ip")
        case = create_case()

        r1 = open_request(case["id"], specialty_area="ip")
        screen_candidate(r1["id"], expert_x["id"])
        e1 = create_draft_engagement(r1["id"], expert_x["id"], hourly_rate_cents=50_000)

        r2 = open_request(case["id"], specialty_area="ip")
        ccx = get_success_data(api.create_conflict_check(
            r2["id"], create_conflict_check_payload(expert_x["id"], adverse_parties=["BB Ltd"]),
            CONFLICT))
        get_success_data(api.resolve_conflict_check(
            ccx["id"], {"outcome": "FLAGGED", "rationale": "prior adverse work"}, CONFLICT))
        screen_candidate(r2["id"], expert_y["id"], adverse_parties=["BB Ltd"])

        req2 = validate_success(api.get_engagement_request(r2["id"], CM), 200)
        assert req2["status"] == "READY"
        return expert_x, r2, e1

    def test_flagged_conflict_reports_conflict_not_cleared(self, api):
        """PRD §3.3: "Creation is gated by seven business-safety checks, evaluated in this
        order after the global ladder of §2.11: first conflict clearance — the expert's
        check under the request must be `CLEARED` or `WAIVED`, else
        `ERR_CONFLICT_NOT_CLEARED`".

        Design: Difficulty/priority_pair_validation_conflict/create_engagement_safety_beats_constraint
        """
        expert_x, r2, e1 = self._setup_flagged_plus_duplicate(api)
        res = api.create_engagement(
            {"engagement_request_id": r2["id"], "expert_id": expert_x["id"],
             "hourly_rate_cents": 50000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_CONFLICT_NOT_CLEARED)

    def test_duplicate_constraint_does_not_mask_safety_error(self, api):
        """PRD §3.3: "first conflict clearance — the expert's check under the request must
        be `CLEARED` or `WAIVED`, else `ERR_CONFLICT_NOT_CLEARED`" and "then uniqueness — no
        other engagement for the same `case_id` and `expert_id` pair may exist in any
        non-terminal state (`DRAFT`, `PROPOSED`, `NEGOTIATING`, `SIGNED`, or `ACTIVE`), else
        `ERR_DUPLICATE_CASE_ENGAGEMENT`" — the pinned order runs conflict clearance before
        uniqueness.

        Design: Difficulty/priority_pair_validation_conflict/create_engagement_safety_beats_constraint
        """
        expert_x, r2, e1 = self._setup_flagged_plus_duplicate(api)
        assert e1["status"] == "DRAFT", "a non-terminal engagement already exists for (case, expert X)"

        res = api.create_engagement(
            {"engagement_request_id": r2["id"], "expert_id": expert_x["id"],
             "hourly_rate_cents": 50000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] != "ERR_DUPLICATE_CASE_ENGAGEMENT", (
            "safety gate (conflict clearance) runs before the uniqueness constraint")

        req2 = validate_success(api.get_engagement_request(r2["id"], CM), 200)
        assert req2["status"] == "READY", "rejected creation leaves the request untouched"


class TestCapacitySlotConservation:

    def _setup_expert_at_cap(self, api):
        """Expert with max_concurrent_engagements 2; three READY requests on three cases;
        two engagements signed."""
        expert = create_expert(full_name="W Kam", max_concurrent_engagements=2)
        engagements = []
        requests = []
        for i in range(3):
            case = create_case()
            request = open_request(case["id"])
            screen_candidate(request["id"], expert["id"])
            requests.append(request)
        for request in requests[:2]:
            eng = create_draft_engagement(request["id"], expert["id"])
            propose_engagement(eng["id"])
            eng = sign_engagement(eng["id"], expert["id"])
            engagements.append(eng)
        return expert, requests, engagements

    def test_creation_rejected_exactly_at_cap(self, api):
        """PRD §3.3: "and finally capacity — the expert's `active_engagement_count` must be
        strictly below `max_concurrent_engagements`, with equality at the cap failing as
        `ERR_EXPERT_CAPACITY_FULL`."
        PRD §3.1: "`active_engagement_count`, the number of this expert's engagements
        currently in `SIGNED` or `ACTIVE` status".

        Design: Difficulty/compensating_invariant/expert_active_engagement_slot_conservation
        """
        expert, requests, engagements = self._setup_expert_at_cap(api)
        assert len(engagements) == 2

        res = api.create_engagement(
            {"engagement_request_id": requests[2]["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_EXPERT_CAPACITY_FULL)

    def test_termination_frees_slot_and_count_recomputed(self, api):
        """PRD §3.1: "because `SIGNED` and `ACTIVE` engagements both count, activating an
        engagement never changes `active_engagement_count`, while signing, terminating, and
        closing do."
        PRD §3.3: "the expert's `active_engagement_count` must be strictly below
        `max_concurrent_engagements`, with equality at the cap failing as
        `ERR_EXPERT_CAPACITY_FULL`."

        Design: Difficulty/compensating_invariant/expert_active_engagement_slot_conservation
        """
        expert, requests, engagements = self._setup_expert_at_cap(api)

        res = api.create_engagement(
            {"engagement_request_id": requests[2]["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_EXPERT_CAPACITY_FULL)

        terminate_engagement(engagements[0]["id"], reason="settlement")

        created = create_draft_engagement(requests[2]["id"], expert["id"])
        assert created["status"] == "DRAFT", "slot freed by the compensating termination"

        expert_after = validate_success(api.get_expert(expert["id"], CM), 200)
        assert expert_after["active_engagement_count"] == 1, (
            "only the remaining SIGNED engagement counts; the new DRAFT does not")


class TestEngagementCloseGuard:

    def test_close_blocked_by_open_report(self, api):
        """PRD §3.8: "A `CaseManager` closes an engagement from `ACTIVE` only when no report
        on it remains in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED`, or `FINALIZED`, no
        session remains in `PROPOSED` or `CONFIRMED`, and every invoice is in `PAID` or
        `REJECTED`; any of these blockers rejects the close with
        `ERR_ENGAGEMENT_NOT_CLOSABLE`."

        Design: Corner/endpoints/engagement_close_blocked_by_open_report
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"])
        submit_report(report["id"], sc["expert"]["id"])  # IN_REVIEW

        res = api.close_engagement(sc["engagement"]["id"], CM)
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_NOT_CLOSABLE)
