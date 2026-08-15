"""Expense approval routing tiers, authority caps, segregation of duties,
resubmission, and the validation-priority pair state-vs-fiscal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_team_member,
    create_artist,
    create_expense_payload,
    file_expense,
    get_success_data,
    list_requests_for_target,
    make_agent_headers,
    make_business_manager_headers,
    setup_artist_team,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]


class TestApprovalValidationPriority:
    def _setup_dual_bm_expense(self, api):
        """Expense 200000 (tier 2: BUSINESS_MANAGER + ARTIST requests) filed by
        the agent; BM1 (cap 500000) has already approved the BUSINESS_MANAGER
        request; BM2 (cap 50000) watches."""
        sc = setup_artist_team(stage_name="Prio Act", bm_cap=500000)
        bm2 = add_team_member(sc["artist"]["id"], "BUSINESS_MANAGER", "BM Two",
                              authority_cap=50000)
        expense = file_expense(sc, 200000, category="PRODUCTION",
                               incurred_date="2026-03-01", description="Staging")
        requests = list_requests_for_target(sc, expense["id"])
        bm_request = next(r for r in requests
                          if r["required_approver"] == "BUSINESS_MANAGER")
        get_success_data(api.approve_request(bm_request["id"], sc["bm_headers"]))
        return sc, expense, bm_request, bm2

    def test_double_approve_with_fiscal_violation_returns_invalid_state(self, api):
        """PRD: "When a request violates several rules at once, the server reports
        the earliest failure in a fixed evaluation order:"
        PRD: "State-machine preconditions — the target is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`, including its
        specialized forms such as `ERR_EVENT_ALREADY_SETTLED` and
        `ERR_EXPENSE_NOT_REJECTED`)."
        PRD: "Monetary limits last — approver authority caps and settlement
        amount ranges (`ERR_APPROVAL_AUTHORITY_EXCEEDED`,
        `ERR_AMOUNT_OUT_OF_RANGE`)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_fiscal_authority
        """
        sc, expense, bm_request, bm2 = self._setup_dual_bm_expense(api)
        # Dual failure: the request is already APPROVED (state, priority 8) AND
        # 200000 exceeds BM2's cap 50000 (fiscal, priority 14).
        resp = api.approve_request(bm_request["id"],
                                   make_business_manager_headers(bm2["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        expense_after = validate_success(api.get_expense(expense["id"], ADMIN))
        assert expense_after["status"] == "PENDING_APPROVAL", (
            "No side effects leaked from the rejected call"
        )

    def test_double_approve_without_fiscal_violation_also_invalid_state(self, api):
        """PRD: "State-machine preconditions — the target is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`, including its
        specialized forms such as `ERR_EVENT_ALREADY_SETTLED` and
        `ERR_EXPENSE_NOT_REJECTED`)."
        PRD: "Approval stamps `decided_by_user_id`, and when the last pending
        request for an expense is approved the expense moves to `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_fiscal_authority
        """
        sc, expense, bm_request, _bm2 = self._setup_dual_bm_expense(api)
        # Control: the same already-APPROVED request re-approved by a BM whose
        # cap (500000) comfortably covers 200000 — the only violation is state.
        other_bm = add_team_member(sc["artist"]["id"], "BUSINESS_MANAGER",
                                   "BM Three", authority_cap=500000)
        resp = api.approve_request(bm_request["id"],
                                   make_business_manager_headers(other_bm["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        request_after = validate_success(
            api.get_approval_request(bm_request["id"], ADMIN))
        assert request_after["status"] == "APPROVED"
        expense_after = validate_success(api.get_expense(expense["id"], ADMIN))
        assert expense_after["status"] == "PENDING_APPROVAL", (
            "The ARTIST request is still pending, so the expense has not flipped"
        )


class TestApprovalRules:
    def test_approver_authority_cap_enforced(self, api):
        """PRD: "a `BusinessManager` deciding an expense request may approve only
        amounts up to their own `authority_expense_cap_cents`; beyond the cap the
        approval fails with `ERR_APPROVAL_AUTHORITY_EXCEEDED`."

        Design: Corner/validations/approver_authority_cap_enforced
        """
        sc = setup_artist_team(stage_name="Cap Act", bm_cap=50000)
        expense = file_expense(sc, 90000, category="TRAVEL",
                               incurred_date="2026-07-01",
                               description="Tour bus deposit")
        requests = list_requests_for_target(sc, expense["id"])
        assert len(requests) == 1
        request = requests[0]

        resp = api.approve_request(request["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_APPROVAL_AUTHORITY_EXCEEDED)

        request_after = validate_success(
            api.get_approval_request(request["id"], ADMIN))
        assert request_after["status"] == "PENDING"
        expense_after = validate_success(api.get_expense(expense["id"], ADMIN))
        assert expense_after["status"] == "PENDING_APPROVAL"

    def test_expense_routing_tier_boundaries(self, api):
        """PRD: "Routing tiers key off the amount, with inclusive upper bounds: an
        amount up to and including 100000 cents ($1,000) needs only a
        `BUSINESS_MANAGER`; above that, up to and including 1000000 cents
        ($10,000), it needs the `BUSINESS_MANAGER` and the `ARTIST`"
        PRD: "Exactly 100000 cents therefore routes to the business manager alone"
        PRD: "when the last pending request for an expense is approved the expense
        moves to `APPROVED`."

        Design: Corner/validations/expense_routing_tier_boundaries
        """
        sc = setup_artist_team(stage_name="Tier Act", bm_cap=500000)
        exp_low = file_expense(sc, 100000, category="TRAVEL",
                               incurred_date="2026-07-01",
                               description="At tier1 boundary")
        exp_high = file_expense(sc, 100001, category="TRAVEL",
                                incurred_date="2026-07-01",
                                description="One cent into tier2")

        low_requests = list_requests_for_target(sc, exp_low["id"])
        assert len(low_requests) == 1
        assert low_requests[0]["required_approver"] == "BUSINESS_MANAGER"

        high_requests = list_requests_for_target(sc, exp_high["id"])
        assert len(high_requests) == 2
        assert sorted(r["required_approver"] for r in high_requests) == [
            "ARTIST", "BUSINESS_MANAGER"]

        # Approving the single tier-1 request flips the expense to APPROVED.
        get_success_data(api.approve_request(low_requests[0]["id"], sc["bm_headers"]))
        expense_after = validate_success(api.get_expense(exp_low["id"], ADMIN))
        assert expense_after["status"] == "APPROVED"

    def test_resubmit_only_from_rejected(self, api):
        """PRD: "resubmission — open to the same three filing roles — requires the
        `REJECTED` state (anything else fails with `ERR_EXPENSE_NOT_REJECTED`)"

        Design: Corner/validations/resubmit_only_from_rejected
        """
        sc = setup_artist_team(stage_name="Re Act")
        expense = file_expense(sc, 5000, category="OTHER",
                               incurred_date="2026-07-01", description="Misc")

        resp = api.resubmit_expense(expense["id"], {"amount_cents": 6000},
                                    sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_EXPENSE_NOT_REJECTED)

        after = validate_success(api.get_expense(expense["id"], ADMIN))
        assert after["status"] == "PENDING_APPROVAL"
        assert after["amount_cents"] == 5000

    def test_sod_expense_submitter_cannot_self_approve(self, api):
        """PRD: "The decider must not be the raiser (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/validations/sod_expense_submitter_cannot_self_approve
        """
        artist = create_artist(stage_name="Sod Act")
        bm = add_team_member(artist["id"], "BUSINESS_MANAGER", "BM Sd",
                             authority_cap=500000)
        bm_headers = make_business_manager_headers(bm["id"])
        expense = get_success_data(api.create_expense(
            create_expense_payload(artist["id"], category="OTHER",
                                   amount_cents=5000, description="Supplies"),
            bm_headers))
        data, _meta = validate_paginated(
            api.list_approval_requests(bm_headers,
                                       params={"artist_id": artist["id"],
                                               "target_id": expense["id"]}))
        request = data[0]

        resp = api.approve_request(request["id"], bm_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        request_after = validate_success(api.get_approval_request(request["id"], ADMIN))
        assert request_after["status"] == "PENDING"
        expense_after = validate_success(api.get_expense(expense["id"], ADMIN))
        assert expense_after["status"] == "PENDING_APPROVAL"
