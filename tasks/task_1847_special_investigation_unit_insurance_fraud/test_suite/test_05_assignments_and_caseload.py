"""Investigator assignment, caseload capacity, OCC on case, reassignment branch."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, make_investigator_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    setup_case_under_investigation,
)
from test_helpers.api_client import api_client


class TestAssignmentBranching:
    """Difficulty/non_linear_state_machine/assignment_branching_reassign_vs_terminate"""

    def test_reassign_flips_old_assignment_and_keeps_case_under_investigation(self, api):
        """PRD §3.3: "When a case already has an `ACTIVE` assignment, posting a new
        one automatically flips the existing assignment to `REASSIGNED`, decrements
        the previous investigator's `active_case_count` by one, activates the new
        assignment, and raises the new investigator's count by one — the handoff is
        atomic, and each assignment records its `assigned_at` timestamp."

        Design: Difficulty/non_linear_state_machine/assignment_branching_reassign_vs_terminate
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv1, _ = create_investigator(manager_headers=mh)
        inv2, _ = create_investigator(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg1, case = assign_investigator(case, inv1, manager_headers=mh)
        # Reassign: post new assignment for inv2
        asg2, case = assign_investigator(case, inv2, manager_headers=mh)
        # Verify old assignment flipped
        asg1_fresh = get_success_data(api_client.get_assignment(asg1["id"], mh))
        assert asg1_fresh["status"] == "REASSIGNED"
        assert asg2["status"] == "ACTIVE"
        i1 = get_success_data(api_client.get_investigator(inv1["id"], mh))
        i2 = get_success_data(api_client.get_investigator(inv2["id"], mh))
        assert i1["active_case_count"] == 0
        assert i2["active_case_count"] == 1
        assert case["status"] == "UNDER_INVESTIGATION"
        assert case["assigned_investigator_id"] == inv2["id"]

    def test_terminate_demotes_case_to_open_and_nulls_assignee(self, api):
        """PRD §3.3: "termination moves the assignment to `TERMINATED`, decrements
        the investigator's count, clears the case's `assigned_investigator_id` to
        null, and — when the case was `UNDER_INVESTIGATION` — demotes it back to
        `OPEN`."

        Design: Difficulty/non_linear_state_machine/assignment_branching_reassign_vs_terminate
        """
        ctx = setup_case_under_investigation()
        mh = ctx["manager_headers"]
        case = ctx["case"]
        inv = ctx["investigator"]
        asg = ctx["assignment"]
        resp = api_client.terminate_assignment(asg["id"], {"reason": "closing"}, mh)
        validate_success(resp)
        asg_fresh = get_success_data(api_client.get_assignment(asg["id"], mh))
        assert asg_fresh["status"] == "TERMINATED"
        case_fresh = get_success_data(api_client.get_case(case["id"], mh))
        assert case_fresh["status"] == "OPEN"
        assert case_fresh["assigned_investigator_id"] is None
        inv_fresh = get_success_data(api_client.get_investigator(inv["id"], mh))
        assert inv_fresh["active_case_count"] == 0


class TestCaseloadConservation:
    """Difficulty/compensating_invariant/investigator_caseload_conservation_across_terminate_and_reassign"""

    def test_active_count_conserved_across_reassign(self, api):
        """PRD §3.3: "The first `ACTIVE` assignment on a case ... raises that
        investigator's `active_case_count` by one" and "posting a new one
        automatically flips the existing assignment to `REASSIGNED`, decrements the
        previous investigator's `active_case_count` by one, activates the new
        assignment, and raises the new investigator's count by one"

        Design: Difficulty/compensating_invariant/investigator_caseload_conservation_across_terminate_and_reassign
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv1, _ = create_investigator(manager_headers=mh)
        inv2, _ = create_investigator(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg1, case = assign_investigator(case, inv1, manager_headers=mh)
        asg2, case = assign_investigator(case, inv2, manager_headers=mh)
        i1 = get_success_data(api_client.get_investigator(inv1["id"], mh))
        i2 = get_success_data(api_client.get_investigator(inv2["id"], mh))
        # Conservation: 0 + 1 == 1 (was 1 + 0 before)
        assert i1["active_case_count"] + i2["active_case_count"] == 1
        assert i1["active_case_count"] == 0
        assert i2["active_case_count"] == 1

    def test_active_count_conserved_across_terminate(self, api):
        """PRD §3.3: "termination moves the assignment to `TERMINATED`, decrements
        the investigator's count"

        Design: Difficulty/compensating_invariant/investigator_caseload_conservation_across_terminate_and_reassign
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv1, _ = create_investigator(manager_headers=mh)
        inv2, _ = create_investigator(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg1, case = assign_investigator(case, inv1, manager_headers=mh)
        asg2, case = assign_investigator(case, inv2, manager_headers=mh)
        # Terminate the now-active asg2
        resp = api_client.terminate_assignment(asg2["id"], {"reason": "closing"}, mh)
        validate_success(resp)
        i1 = get_success_data(api_client.get_investigator(inv1["id"], mh))
        i2 = get_success_data(api_client.get_investigator(inv2["id"], mh))
        assert i1["active_case_count"] == 0
        assert i2["active_case_count"] == 0
        # Sum across both == 0
        assert i1["active_case_count"] + i2["active_case_count"] == 0
        asg1_fresh = get_success_data(api_client.get_assignment(asg1["id"], mh))
        asg2_fresh = get_success_data(api_client.get_assignment(asg2["id"], mh))
        assert asg1_fresh["status"] == "REASSIGNED"
        assert asg2_fresh["status"] == "TERMINATED"


class TestCaseloadCapacity:
    """Difficulty/resource_temporal_overlap/investigator_caseload_capacity_overlap"""

    def _make_open_case(self, adj, ah, inv, mh, policy_number):
        claim = create_claim(adj, policy_number=policy_number)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        return open_case(case, manager_headers=mh)

    def test_assignment_at_capacity_returns_ineligible(self, api):
        """PRD §3.3: "their `active_case_count` must be below `max_active_cases`;
        any failure is `ERR_INVESTIGATOR_INELIGIBLE`."

        Design: Difficulty/resource_temporal_overlap/investigator_caseload_capacity_overlap
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, _ = create_investigator(max_active_cases=2, manager_headers=mh)
        k1 = self._make_open_case(adj, ah, inv, mh, "P1")
        assign_investigator(k1, inv, manager_headers=mh)
        k2 = self._make_open_case(adj, ah, inv, mh, "P2")
        assign_investigator(k2, inv, manager_headers=mh)
        k3 = self._make_open_case(adj, ah, inv, mh, "P3")
        resp = api_client.create_assignment(
            k3["id"],
            {"investigator_id": inv["id"], "expected_case_version": k3["version"]},
            mh)
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_INELIGIBLE)

    def test_active_case_count_at_capacity_remains_at_max(self, api):
        """PRD §3.3: "their `active_case_count` must be below `max_active_cases`"

        Design: Difficulty/resource_temporal_overlap/investigator_caseload_capacity_overlap
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, _ = create_investigator(max_active_cases=2, manager_headers=mh)
        k1 = self._make_open_case(adj, ah, inv, mh, "P1")
        assign_investigator(k1, inv, manager_headers=mh)
        k2 = self._make_open_case(adj, ah, inv, mh, "P2")
        assign_investigator(k2, inv, manager_headers=mh)
        inv_fresh = get_success_data(api_client.get_investigator(inv["id"], mh))
        assert inv_fresh["active_case_count"] == 2


class TestStaleVersionOnAssignment:
    def test_assignment_with_stale_case_version_returns_412(self, api):
        """PRD §2.8: "Assigning an investigator to a case requires
        `expected_case_version`, compared against the case's current `version`."
        PRD §2.8: "if that value does not match the parent resource's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and
        nothing is mutated."

        Design: Corner/validations/occ_stale_version_returns_412
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv1, _ = create_investigator(manager_headers=mh)
        inv2, _ = create_investigator(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        initial_v = case["version"]
        # First assignment advances version
        assign_investigator(case, inv1, manager_headers=mh)
        # Now try with stale version
        resp = api_client.create_assignment(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": initial_v - 1},
            mh)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
