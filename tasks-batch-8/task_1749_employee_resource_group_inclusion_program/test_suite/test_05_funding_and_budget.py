"""Funding negotiation and the group budget ledger: submission gates,
counter/revise cycle, matching top-up approval, reserve/disburse/reconcile
conservation, and segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_group_budget_partition,
    create_active_group,
    create_funding_request,
    create_open_program,
    create_sponsor,
    make_group_leader_headers,
    make_sponsor_headers,
    set_sponsor_status,
    setup_active_group_with_leader,
    setup_endorsed_request,
    setup_locked_group_with_leader,
    sponsor_decide_funding,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestSubmissionGates:
    def test_funding_create_in_leadership_gap_rejected(self, api):
        """PRD §3.4: "Submission requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`), and the caller to be the leader of the group's `ACTIVE` leadership term — a group with no active leader rejects with `ERR_LEADERSHIP_GAP`, and a caller who is not that leader rejects with `ERR_NOT_GROUP_LEADER`."

        Design: Corner/validations/funding_create_in_leadership_gap_rejected
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp34", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Leaderless", "AFFINITY", "emp_l51"
        )
        # No leadership term was ever created: the group has no active leader.
        resp = api.create_funding_request(
            {
                "group_id": group["id"],
                "category": "EVENT",
                "purpose": "No leader",
                "requested_cents": 10000,
                "external_matching_cents": 0,
            },
            make_group_leader_headers("emp_l51"),
        )
        validate_error(resp, ApiErrorId.ERR_LEADERSHIP_GAP.value, 409)

    def test_non_leader_cannot_submit_funding(self, api):
        """PRD §3.4: "Submission requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`), and the caller to be the leader of the group's `ACTIVE` leadership term — a group with no active leader rejects with `ERR_LEADERSHIP_GAP`, and a caller who is not that leader rejects with `ERR_NOT_GROUP_LEADER`."

        Design: Corner/rbac/non_leader_cannot_submit_funding
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp40", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Owned Group", "AFFINITY", "emp_l60", "emp_f01"
        )
        # The caller is a GroupLeader (charter creator) but not the ACTIVE-term leader.
        resp = api.create_funding_request(
            {
                "group_id": group["id"],
                "category": "EVENT",
                "purpose": "Not my group",
                "requested_cents": 10000,
                "external_matching_cents": 0,
            },
            make_group_leader_headers("emp_l60"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_GROUP_LEADER.value, 403)

    def test_state_gate_fires_on_suspended_group_even_for_huge_amount(self, api):
        """PRD §2.6: "Every request passes through the same ordered validation pipeline, and when several checks could fail the earliest one determines the error surfaced."
        PRD §3.4: "Submission requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`), and the caller to be the leader of the group's `ACTIVE` leadership term — a group with no active leader rejects with `ERR_LEADERSHIP_GAP`, and a caller who is not that leader rejects with `ERR_NOT_GROUP_LEADER`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_funding_create
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp11", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Prio One", "AFFINITY", "emp_l11", "emp_f01"
        )
        validate_success(
            api.set_group_status(group["id"], {"to_status": "SUSPENDED"}, DEI_HEADERS), 200
        )
        # The caller is the legitimate term leader and the program is OPEN, so
        # the group-state gate is the earliest check that can fire.
        resp = api.create_funding_request(
            {
                "group_id": group["id"],
                "category": "EVENT",
                "purpose": "Too expensive and suspended",
                "requested_cents": 999999999,
                "external_matching_cents": 0,
            },
            make_group_leader_headers("emp_f01"),
        )
        error_data = validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE.value, 409)
        assert error_data["error_id"] != ApiErrorId.ERR_INSUFFICIENT_GROUP_BUDGET.value

    def test_state_gate_fires_on_suspended_group_for_small_amount(self, api):
        """PRD §3.4: "Submission requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`), and the caller to be the leader of the group's `ACTIVE` leadership term — a group with no active leader rejects with `ERR_LEADERSHIP_GAP`, and a caller who is not that leader rejects with `ERR_NOT_GROUP_LEADER`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_funding_create
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp11", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Prio One", "AFFINITY", "emp_l11", "emp_f01"
        )
        validate_success(
            api.set_group_status(group["id"], {"to_status": "SUSPENDED"}, DEI_HEADERS), 200
        )
        # Isolation: an affordable amount is still rejected on the state gate.
        resp = api.create_funding_request(
            {
                "group_id": group["id"],
                "category": "EVENT",
                "purpose": "Suspended but affordable",
                "requested_cents": 10000,
                "external_matching_cents": 0,
            },
            make_group_leader_headers("emp_f01"),
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE.value, 409)


class TestSponsorReview:
    def test_funding_endorse_requires_active_sponsor(self, api):
        """PRD §3.4: "As with charters, the sponsor's `X-User-ID` must match the group's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/funding_endorse_requires_active_sponsor
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp15", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Sponsor Gate", "AFFINITY", "emp_l15", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "TRAINING", "Gated endorsement", 50000, 0
        )
        set_sponsor_status(sponsor["id"], "ON_LEAVE")
        resp = api.funding_sponsor_decision(
            request["id"], {"decision": "ENDORSE"}, make_sponsor_headers(sponsor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE.value, 409)

    def test_rejected_endorsement_leaves_request_submitted(self, api):
        """PRD §3.4: "A `decision` of `ENDORSE` moves the request `SUBMITTED` → `ENDORSED`."
        PRD §3.4: "As with charters, the sponsor's `X-User-ID` must match the group's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/funding_endorse_requires_active_sponsor
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp15", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Sponsor Gate", "AFFINITY", "emp_l15", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "TRAINING", "Gated endorsement", 50000, 0
        )
        set_sponsor_status(sponsor["id"], "ON_LEAVE")
        validate_error(
            api.funding_sponsor_decision(
                request["id"], {"decision": "ENDORSE"}, make_sponsor_headers(sponsor["id"])
            ),
            ApiErrorId.ERR_SPONSOR_NOT_ACTIVE.value,
            409,
        )
        data = validate_success(api.get_funding_request(request["id"], DEI_HEADERS), 200)
        assert data["status"] == "SUBMITTED", "rejected endorsement leaves the request untouched"

    def test_sponsor_self_endorsement_segregation(self, api):
        """PRD §3.4: "Segregation of duties applies: a sponsor whose own `employee_id` equals the request's `created_by_employee_id` may not endorse or counter it and is refused with `ERR_SPONSOR_SELF_ENDORSEMENT` (HTTP 403)."

        Design: Corner/validations/sponsor_self_endorsement_segregation
        """
        program = create_open_program(100000)
        # The sponsor's employee_id matches the group leader who will submit.
        sponsor = create_sponsor("emp_f01", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Segregated", "AFFINITY", "emp_l48", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Self-dealing test", 50000, 0
        )
        resp = api.funding_sponsor_decision(
            request["id"], {"decision": "ENDORSE"}, make_sponsor_headers(sponsor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_SELF_ENDORSEMENT.value, 403)


class TestCounterReviseCycle:
    def test_counter_records_amount_and_moves_to_countered(self, api):
        """PRD §3.4: "A `decision` of `COUNTER` requires a `counter_amount_cents` greater than zero (its absence or a non-positive value is `ERR_INVALID_REQUEST`), records that amount on the request, and moves it `SUBMITTED` → `COUNTERED`."

        Design: Difficulty/non_linear_state_machine/funding_counter_revise_cycle
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp7", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Negotiators", "AFFINITY", "emp_l7", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Summit", 500000, 0
        )
        data = sponsor_decide_funding(request["id"], sponsor["id"], "COUNTER", 250000)
        assert data["status"] == "COUNTERED"
        assert data["counter_amount_cents"] == 250000

    def test_revise_rewrites_amount_and_cycle_is_unbounded(self, api):
        """PRD §3.4: "Revision moves the request `COUNTERED` → `SUBMITTED` and replaces `requested_cents` with the new amount; this negotiation cycle between `COUNTERED` and `SUBMITTED` is unbounded."
        PRD §3.4: "A `decision` of `ENDORSE` moves the request `SUBMITTED` → `ENDORSED`."

        Design: Difficulty/non_linear_state_machine/funding_counter_revise_cycle
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp7", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Negotiators", "AFFINITY", "emp_l7", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Summit", 500000, 0
        )
        sponsor_decide_funding(request["id"], sponsor["id"], "COUNTER", 250000)

        data = validate_success(
            api.revise_funding_request(
                request["id"],
                {"requested_cents": 250000},
                make_group_leader_headers("emp_f01"),
            ),
            200,
        )
        assert data["status"] == "SUBMITTED", "revise cycles back into review"
        assert data["requested_cents"] == 250000, "revise replaces the requested amount"

        data = sponsor_decide_funding(request["id"], sponsor["id"], "ENDORSE")
        assert data["status"] == "ENDORSED"


class TestApproval:
    def test_dei_approve_skips_sponsor_endorsement_rejected(self, api):
        """PRD §3.4: "On success the request moves `ENDORSED` → `APPROVED`, `approved_cents` is written, and the group reserves the money: `reserved_cents` rises by `approved_cents`, dropping `available_cents` correspondingly."
        PRD §2.6: "6. **Lifecycle state gates** — the target resource's current state permits the transition, including terminal-state lockdown (state-category errors such as `ERR_INVALID_STATE_TRANSITION`, `ERR_GROUP_NOT_ACTIVE`, `ERR_PROGRAM_NOT_OPEN`, `ERR_PROGRAM_IN_CLIMATE_REVIEW`, `ERR_ALLOCATION_NOT_LOCKED`, `ERR_SURVEY_NOT_OPEN`, `ERR_EVENT_NOT_PUBLISHED`, `ERR_SPONSOR_NOT_ACTIVE`, `ERR_LEADERSHIP_GAP`, 409)."

        Design: Corner/state_machines/dei_approve_skips_sponsor_endorsement_rejected
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp20", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Chain Group", "AFFINITY", "emp_l26", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Skip step", 50000, 0
        )
        # APPROVE requires ENDORSED; the request is still SUBMITTED.
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    def test_approve_before_allocation_lock_rejected(self, api):
        """PRD §3.4: "Approval belongs to the DEI office and is only possible once the program's allocation is locked — an approval attempt on a program not in `ALLOCATION_LOCKED` is rejected with `ERR_ALLOCATION_NOT_LOCKED`."

        Design: Corner/validations/approve_before_allocation_lock_rejected
        """
        program = create_open_program(500000)  # never locked
        sponsor = create_sponsor("emp_sp36", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Too Early", "AFFINITY", "emp_l53", "emp_f01"
        )
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Pre-lock approval", requested_cents=50000,
            external_matching_cents=0,
        )
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_LOCKED.value, 409)

    def test_approve_over_available_rejected(self, api):
        """PRD §3.4: "The award must not exceed the group's `available_cents` — equality is allowed, and a shortfall is rejected with `ERR_INSUFFICIENT_GROUP_BUDGET` (HTTP 402)."

        Design: Corner/validations/approve_over_available_rejected
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp35", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Over Budget", "AFFINITY", "emp_l52", "emp_f01"
        )
        # The sole eligible group was allocated the whole 100000 pool.
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Too big", requested_cents=150000,
            external_matching_cents=0,
        )
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_GROUP_BUDGET.value, 402)

        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["reserved_cents"] == 0, "no reservation leaked by the failed approval"

    def test_approve_at_exact_available_balance(self, api):
        """PRD §3.4: "The award must not exceed the group's `available_cents` — equality is allowed, and a shortfall is rejected with `ERR_INSUFFICIENT_GROUP_BUDGET` (HTTP 402)."
        PRD §3.4: "On success the request moves `ENDORSED` → `APPROVED`, `approved_cents` is written, and the group reserves the money: `reserved_cents` rises by `approved_cents`, dropping `available_cents` correspondingly."

        Design: Difficulty/boundary_precision_check/approve_at_exact_available_balance
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp13", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Exact Budget", "AFFINITY", "emp_l13", "emp_f01"
        )
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Exact-fit request", requested_cents=500000,
            external_matching_cents=0,
        )
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["approved_cents"] == 500000, "match on external 0 is 0"

    def test_exact_approval_drives_available_to_zero(self, api):
        """PRD §3.4: "On success the request moves `ENDORSED` → `APPROVED`, `approved_cents` is written, and the group reserves the money: `reserved_cents` rises by `approved_cents`, dropping `available_cents` correspondingly."

        Design: Difficulty/boundary_precision_check/approve_at_exact_available_balance
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp13", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Exact Budget", "AFFINITY", "emp_l13", "emp_f01"
        )
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Exact-fit request", requested_cents=500000,
            external_matching_cents=0,
        )
        validate_success(
            api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS), 200
        )
        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["reserved_cents"] == 500000
        assert group_data["available_cents"] == 0, "exact-equality approval is allowed"
        assert_group_budget_partition(group_data)

    def test_matching_topup_tier_keyed_on_provisional_total(self, api):
        """PRD §3.4: "1. A provisional total is formed as `requested_cents` plus 10% of `external_matching_cents`."
        PRD §3.4: "2. If that provisional total is at most 1,000,000 cents, the match rate is 20%; otherwise it is 5%."
        PRD §3.4: "3. The match amount is the match rate multiplied by `external_matching_cents`, rounded half-up to whole cents."
        PRD §3.4: "4. `approved_cents` is `requested_cents` plus the match amount."

        Design: Difficulty/combinatorial_formula/matching_topup_tier_evaluation_order
        """
        program = create_open_program(2000000)
        sponsor = create_sponsor("emp_sp5", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Delta Leaders", "PROFESSIONAL", "emp_l5", "emp_f01"
        )
        # provisional_total = 990000 + 0.10*200000 = 1010000 > 1000000 -> LOW 5%.
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="TRAINING", purpose="Bias-interrupter training",
            requested_cents=990000, external_matching_cents=200000,
        )
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["approved_cents"] == 1000000, (
            "LOW 5% tier: match 10000; keying on requested_cents alone would wrongly yield 1030000"
        )

    def test_matching_topup_reserves_full_award_on_group(self, api):
        """PRD §3.4: "On success the request moves `ENDORSED` → `APPROVED`, `approved_cents` is written, and the group reserves the money: `reserved_cents` rises by `approved_cents`, dropping `available_cents` correspondingly."

        Design: Difficulty/combinatorial_formula/matching_topup_tier_evaluation_order
        """
        program = create_open_program(2000000)
        sponsor = create_sponsor("emp_sp5", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Delta Leaders", "PROFESSIONAL", "emp_l5", "emp_f01"
        )
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="TRAINING", purpose="Bias-interrupter training",
            requested_cents=990000, external_matching_cents=200000,
        )
        validate_success(
            api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS), 200
        )
        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["allocated_cents"] == 2000000
        assert group_data["reserved_cents"] == 1000000
        assert group_data["available_cents"] == 1000000
        assert_group_budget_partition(group_data)


class TestLedgerConservation:
    def test_reserve_and_disburse_preserve_partition(self, api):
        """PRD §2.10: "Each `ErgGroup` carries a conserved three-way partition of its allocation: `allocated_cents` always equals the sum of `available_cents`, `reserved_cents`, and `spent_cents`."
        PRD §3.4: "Disbursement by a `DeiAdmin` moves an `APPROVED` request to `DISBURSED`, sets `disbursed_cents` to `approved_cents`, and moves the money on the group ledger: `reserved_cents` falls by `approved_cents` and `spent_cents` rises by `approved_cents`."

        Design: Difficulty/compensating_invariant/budget_reserve_disburse_reconcile_conservation
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp17", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Ledger Group", "AFFINITY", "emp_l17", "emp_f01"
        )
        # provisional_total = 300000 + 0.10*50000 = 305000 <= 1000000 -> HIGH 20%.
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="TRAINING", purpose="Ledger walk",
            requested_cents=300000, external_matching_cents=50000,
        )
        resp = api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
        data = validate_success(resp, 200)
        assert data["approved_cents"] == 310000, "300000 + round_half_up(0.20 * 50000)"

        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["allocated_cents"] == 500000
        assert group_data["reserved_cents"] == 310000
        assert group_data["spent_cents"] == 0
        assert group_data["available_cents"] == 190000
        assert_group_budget_partition(group_data)

        validate_success(api.disburse_funding_request(request["id"], DEI_HEADERS), 200)
        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["allocated_cents"] == 500000
        assert group_data["reserved_cents"] == 0
        assert group_data["spent_cents"] == 310000
        assert group_data["available_cents"] == 190000
        assert_group_budget_partition(group_data)

    def test_reconcile_refund_restores_program_pool(self, api):
        """PRD §3.4: "The refund is `disbursed_cents` minus `actual_spend_cents`; the group's `spent_cents` and `allocated_cents` each fall by the refund, and the program's `unallocated_pool_cents` rises by the refund. The request moves to the terminal `RECONCILED` state."
        PRD §2.10: "At program level the pool is likewise conserved: `pool_total_cents` always equals `unallocated_pool_cents` plus the sum of `allocated_cents` over all groups of the program."

        Design: Difficulty/compensating_invariant/budget_reserve_disburse_reconcile_conservation
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp17", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Ledger Group", "AFFINITY", "emp_l17", "emp_f01"
        )
        request = setup_endorsed_request(
            group["id"], sponsor["id"], "emp_f01",
            category="TRAINING", purpose="Ledger walk",
            requested_cents=300000, external_matching_cents=50000,
        )
        validate_success(
            api.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS), 200
        )
        validate_success(api.disburse_funding_request(request["id"], DEI_HEADERS), 200)

        # Refund = 310000 - 300000 = 10000 flows spent/allocated -> unallocated.
        resp = api.reconcile_funding_request(
            request["id"], {"actual_spend_cents": 300000},
            make_group_leader_headers("emp_f01"),
        )
        data = validate_success(resp, 200)
        assert data["status"] == "RECONCILED"

        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["allocated_cents"] == 490000
        assert group_data["reserved_cents"] == 0
        assert group_data["spent_cents"] == 300000
        assert group_data["available_cents"] == 190000
        assert_group_budget_partition(group_data)

        program_data = validate_success(api.get_program(program["id"], DEI_HEADERS), 200)
        assert program_data["unallocated_pool_cents"] == 10000
        assert program_data["pool_total_cents"] == (
            program_data["unallocated_pool_cents"] + group_data["allocated_cents"]
        ), "program-level pool conservation"
