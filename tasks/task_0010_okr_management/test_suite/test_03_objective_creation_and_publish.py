"""Objective creation, parent-child rules, and publish (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    create_department, create_user,
    create_cycle, create_open_cycle,
    create_objective,
    add_numeric_kr, add_milestone_kr,
    publish_objective,
    setup_org,
)


# ---------------------------------------------------------------------------
# Objective creation gates
# ---------------------------------------------------------------------------

class TestObjectiveCreationGates:
    def test_create_against_draft_cycle_returns_err_cycle_not_open(self, api):
        """PRD §3.2: "an attempt to create against a cycle that is not open is rejected with `ERR_CYCLE_NOT_OPEN`."

        Claim: cycle in DRAFT → POST /objectives → ERR_CYCLE_NOT_OPEN.
        # difficulty: cross_entity_state_dependency/objective_create_requires_cycle_open
        """
        org = setup_org()
        cycle_draft = create_cycle()  # DRAFT
        payload = {
            "cycle_id": cycle_draft["id"],
            "level": "INDIVIDUAL",
            "department_id": org["department"]["id"],
            "owner_user_id": org["employee_user"]["id"],
            "title": "t",
            "weight": 1.0,
        }
        resp = api.create_objective(payload, org["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value)

    def test_create_after_cycle_opens_succeeds_with_same_payload(self, api):
        """PRD §3.2: "Objective creation is permitted only while the cycle's `status` is `OPEN`".

        Claim: same payload that fails on DRAFT cycle succeeds after the cycle is opened.
        # difficulty: cross_entity_state_dependency/objective_create_requires_cycle_open
        """
        org = setup_org()
        cycle_draft = create_cycle()
        payload = {
            "cycle_id": cycle_draft["id"],
            "level": "INDIVIDUAL",
            "department_id": org["department"]["id"],
            "owner_user_id": org["employee_user"]["id"],
            "title": "t",
            "weight": 1.0,
        }
        # First: rejected
        resp1 = api.create_objective(payload, org["admin_headers"])
        validate_error(resp1, ApiErrorId.ERR_CYCLE_NOT_OPEN.value)
        # Open cycle
        api.open_cycle(cycle_draft["id"], org["admin_headers"])
        # Retry: succeeds
        resp2 = api.create_objective(payload, org["admin_headers"])
        validate_success(resp2, expected_status=201)

    def test_unknown_owner_user_id_returns_err_user_not_found(self, api):
        """PRD §2.6 priority 2: "Bodies that reference foreign-key users (`owner_user_id`, `co_owner_user_id`, granted `user_id`) raise `ERR_USER_NOT_FOUND`"."""
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-UNK")
        payload = {
            "cycle_id": cycle["id"],
            "level": "INDIVIDUAL",
            "department_id": org["department"]["id"],
            "owner_user_id": NON_EXISTENT_UUID,
            "title": "t",
            "weight": 1.0,
        }
        resp = api.create_objective(payload, org["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_USER_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Difficulty-design: existence_vs_state_objective_create
# ---------------------------------------------------------------------------

class TestPriorityExistenceVsState:
    """# difficulty: priority_pair_validation_conflict/existence_vs_state_objective_create"""

    def test_existence_user_not_found_wins_over_cycle_not_open(self, api):
        """PRD §2.6: existence (priority 2) is evaluated before state (priority 4).
        PRD §2.6 priority 2: "Bodies that reference foreign-key users (`owner_user_id`, `co_owner_user_id`, granted `user_id`) raise `ERR_USER_NOT_FOUND`".
        PRD §2.6: "Each existence failure surfaces its own 404 error before any state or business check runs."

        Claim: cycle is DRAFT (would fail state) AND owner_user_id is unknown (fails existence) →
        ERR_USER_NOT_FOUND wins (not ERR_CYCLE_NOT_OPEN).
        # difficulty: priority_pair_validation_conflict/existence_vs_state_objective_create
        """
        org = setup_org()
        cycle_draft = create_cycle()  # DRAFT — would fail state
        payload = {
            "cycle_id": cycle_draft["id"],
            "level": "COMPANY",
            "department_id": org["department"]["id"],
            "owner_user_id": NON_EXISTENT_UUID,  # would fail existence
            "title": "t",
            "weight": 1.0,
        }
        resp = api.create_objective(payload, org["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_USER_NOT_FOUND.value)
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_CYCLE_NOT_OPEN.value


# ---------------------------------------------------------------------------
# Parent-child rules at create time
# ---------------------------------------------------------------------------

class TestParentChildRules:
    def test_parent_level_must_be_one_rank_above(self, api):
        """PRD §3.2: "a `DEPARTMENT` objective may only point to a `COMPANY` parent, a `TEAM` to a `DEPARTMENT`, an `INDIVIDUAL` to a `TEAM`; any other pairing yields `ERR_PARENT_LEVEL_INVALID`."

        Claim: TEAM child pointing to COMPANY parent (skipping a level) → ERR_PARENT_LEVEL_INVALID.
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-LVL")
        # COMPANY parent in DRAFT
        company = create_objective(cycle["id"], org["employee_user"]["id"], level="COMPANY",
                                   department_id=org["department"]["id"])
        # TEAM child pointing to COMPANY (should fail — must point to DEPARTMENT)
        payload = {
            "cycle_id": cycle["id"],
            "level": "TEAM",
            "department_id": org["department"]["id"],
            "owner_user_id": org["employee_user"]["id"],
            "title": "team",
            "weight": 1.0,
            "parent_objective_id": company["id"],
        }
        resp = api.create_objective(payload, org["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PARENT_LEVEL_INVALID.value)

    def test_parent_must_be_in_same_cycle(self, api):
        """PRD §3.2: "cross-cycle parenthood yields `ERR_PARENT_NOT_IN_SAME_CYCLE`."

        Claim: parent in cycle A; child in cycle B → ERR_PARENT_NOT_IN_SAME_CYCLE.
        """
        org = setup_org()
        # Two distinct cycles — let factory pick non-overlapping windows.
        cycle_a = create_open_cycle(cycle_code="2026-Q1-A")
        cycle_b = create_open_cycle(cycle_code="2026-Q2-B")
        parent_in_a = create_objective(cycle_a["id"], org["employee_user"]["id"], level="COMPANY",
                                       department_id=org["department"]["id"])
        payload = {
            "cycle_id": cycle_b["id"],
            "level": "DEPARTMENT",
            "department_id": org["department"]["id"],
            "owner_user_id": org["employee_user"]["id"],
            "title": "d",
            "weight": 1.0,
            "parent_objective_id": parent_in_a["id"],
        }
        resp = api.create_objective(payload, org["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PARENT_NOT_IN_SAME_CYCLE.value)


# ---------------------------------------------------------------------------
# Publish: weight sums and KR/children mutual exclusion
# ---------------------------------------------------------------------------

class TestPublishGates:
    def test_publish_with_kr_weight_sum_outside_tolerance_rejected(self, api):
        """PRD §3.2: "A weight-sum that fails the equality yields `ERR_KR_WEIGHTS_INVALID`".
        PRD §2.5: "A computed sum whose absolute difference from 1 is at most 0.0001 satisfies the equality; a sum whose absolute difference is strictly greater than 0.0001 fails it."

        Claim: KR weights 0.5 + 0.4998 = 0.9998 → |0.9998-1|=0.0002 > 0.0001 → ERR_KR_WEIGHTS_INVALID.
        # difficulty: boundary_precision_check/kr_weight_sum_inclusive_tolerance_at_publish
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-WSO")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=0.5)
        add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=0.4998)
        # Acting role is owner Employee
        resp = api.publish_objective(objective["id"], org["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_KR_WEIGHTS_INVALID.value)

    def test_publish_with_kr_weight_sum_at_inclusive_tolerance_accepted(self, api):
        """PRD §2.5: "A computed sum whose absolute difference from 1 is at most 0.0001 satisfies the equality".

        Claim: KR weights 0.5 + 0.4999 = 0.9999 → |0.9999-1|=0.0001 (at boundary) → publish accepted.
        # difficulty: boundary_precision_check/kr_weight_sum_inclusive_tolerance_at_publish
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-WSI")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=0.5)
        add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=0.4999)
        resp = api.publish_objective(objective["id"], org["employee_headers"])
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"

    def test_publish_requires_owner_or_admin(self, api):
        """PRD §2.1: "When ownership is required but the acting user is neither the objective's `owner_user_id` nor an active co-owner, the response is `ERR_NOT_OWNER` (HTTP 403)."

        Claim: non-owner Employee → ERR_NOT_OWNER on publish.
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-NO")
        # Create another employee (non-owner)
        non_owner = create_user(org["department"]["id"], role_type="EMPLOYEE",
                                manager_id=org["manager_user"]["id"])
        from test_helpers import make_employee_headers
        non_owner_headers = make_employee_headers(non_owner["id"])
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        add_numeric_kr(objective["id"], org["employee_user"]["id"], weight=1.0)
        resp = api.publish_objective(objective["id"], non_owner_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
