"""Adjustment cycles: gating, OCC + budget ladder, allocation invariant,
apply timing, and effective-date overlap (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    analyst_headers,
    approve_adjustment,
    bootstrap_org,
    create_draft_adjustment,
    create_open_cycle,
    get_adjustment,
    get_cycle,
    get_success_data,
    mgr_headers,
    setup_published_job,
    submit_adjustment,
    validate_error,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


class TestCycleOpenLockedBranching:
    def test_lock_then_unlock_returns_cycle_to_open(self, api):
        """PRD §3.7: "Locking a cycle — `OPEN` to `LOCKED`, by a `CompManager`
        — requires that no child adjustment remain in `PENDING_APPROVAL`
        (`ERR_CYCLE_HAS_PENDING`) and emits `CYCLE_LOCK`; a locked cycle may
        be unlocked back to `OPEN` (emitting `CYCLE_UNLOCK`) if further work
        is needed."

        Design: Difficulty/non_linear_state_machine/cycle_open_locked_open_branching
        """
        bundle = bootstrap_org()
        cycle = create_open_cycle(bundle)
        locked = validate_success(api.lock_cycle(cycle["id"],
                                                 mgr_headers(bundle)))
        assert locked["status"] == "LOCKED"
        unlocked = validate_success(api.unlock_cycle(cycle["id"],
                                                     mgr_headers(bundle)))
        assert unlocked["status"] == "OPEN", (
            f"Unlock must branch the cycle back to OPEN, got "
            f"{unlocked['status']}")

    def test_version_advances_on_each_cycle_mutation(self, api):
        """PRD §2.5: "The `version` field is an integer that increments by one
        on every mutation, including mutations performed by the server itself
        as side effects of operations on related resources."

        Create -> lock -> unlock advances the cycle version from 1 to 3.

        Design: Difficulty/non_linear_state_machine/cycle_open_locked_open_branching
        """
        bundle = bootstrap_org()
        cycle = create_open_cycle(bundle)
        assert cycle["version"] == 1
        locked = validate_success(api.lock_cycle(cycle["id"],
                                                 mgr_headers(bundle)))
        assert locked["version"] == cycle["version"] + 1
        unlocked = validate_success(api.unlock_cycle(cycle["id"],
                                                     mgr_headers(bundle)))
        assert unlocked["version"] == locked["version"] + 1, (
            f"Each mutation increments version by one; got "
            f"{cycle['version']} -> {locked['version']} -> "
            f"{unlocked['version']}")


class TestCycleEffectiveOverlap:
    def test_effective_date_inside_existing_window_rejected(self, api):
        """PRD §3.7: "a new cycle's `effective_date` must not fall inside the
        window spanning any other `OPEN` or `LOCKED` cycle's creation date
        through its own `effective_date` (inclusive at both ends) for the same
        organization; a collision is rejected with
        `ERR_CYCLE_EFFECTIVE_OVERLAP`."

        C1 spans [2026-08-01, 2026-12-31]; C2's effective_date 2026-10-15
        falls inside it.

        Design: Difficulty/resource_temporal_overlap/cycle_effective_date_point_in_window
        """
        bundle = bootstrap_org()
        create_open_cycle(bundle, name="C1", effective_date="2026-12-31")
        resp = api.create_cycle(bundle["org"]["id"],
                                {"name": "C2", "effective_date": "2026-10-15",
                                 "budget_cents": 500000},
                                mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_CYCLE_EFFECTIVE_OVERLAP)

    def test_effective_date_outside_existing_window_accepted(self, api):
        """PRD §3.7: "a new cycle's `effective_date` must not fall inside the
        window spanning any other `OPEN` or `LOCKED` cycle's creation date
        through its own `effective_date` (inclusive at both ends) for the same
        organization; a collision is rejected with
        `ERR_CYCLE_EFFECTIVE_OVERLAP`."

        C3's effective_date 2027-03-01 falls outside [2026-08-01, 2026-12-31].

        Design: Difficulty/resource_temporal_overlap/cycle_effective_date_point_in_window
        """
        bundle = bootstrap_org()
        create_open_cycle(bundle, name="C1", effective_date="2026-12-31")
        c3 = validate_success(api.create_cycle(
            bundle["org"]["id"],
            {"name": "C3", "effective_date": "2027-03-01",
             "budget_cents": 500000},
            mgr_headers(bundle)), 201)
        assert c3["status"] == "OPEN"


class TestSubmitDependsOnCycleOpen:
    def test_submit_succeeds_while_cycle_open(self, api):
        """PRD §3.7: "Submitting a draft — the analyst moving it from `DRAFT`
        to `PENDING_APPROVAL` — runs its checks in ladder order: the parent
        cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/adjustment_submit_depends_on_cycle_open
        """
        bundle = setup_published_job()
        cycle = create_open_cycle(bundle)
        adj = create_draft_adjustment(bundle, cycle)
        submitted = submit_adjustment(bundle, adj["id"])
        assert submitted["status"] == "PENDING_APPROVAL"
        assert isinstance(submitted["pre_adjustment_compa_ratio_bp"], int)
        assert isinstance(submitted["post_adjustment_compa_ratio_bp"], int)

    def test_submit_rejected_after_cycle_locked(self, api):
        """PRD §3.7: "Submitting a draft — the analyst moving it from `DRAFT`
        to `PENDING_APPROVAL` — runs its checks in ladder order: the parent
        cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/adjustment_submit_depends_on_cycle_open
        """
        bundle = setup_published_job()
        cycle = create_open_cycle(bundle)
        adj1 = create_draft_adjustment(bundle, cycle,
                                       proposed_amount_cents=100000)
        adj2 = create_draft_adjustment(bundle, cycle,
                                       proposed_amount_cents=50000)
        submit_adjustment(bundle, adj1["id"])
        # Retract adj1 (proposer) so the cycle has nothing PENDING at lock.
        validate_success(api.retract_adjustment(adj1["id"],
                                                analyst_headers(bundle)))
        validate_success(api.lock_cycle(cycle["id"], mgr_headers(bundle)))

        resp = api.submit_adjustment(adj2["id"], analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)
        adj2_after = get_adjustment(bundle, adj2["id"])
        assert adj2_after["status"] == "DRAFT", (
            "Rejected submit must leave the adjustment in DRAFT")


class TestCycleGates:
    def test_lock_with_pending_adjustment_rejected(self, api):
        """PRD §3.7: "Locking a cycle — `OPEN` to `LOCKED`, by a `CompManager`
        — requires that no child adjustment remain in `PENDING_APPROVAL`
        (`ERR_CYCLE_HAS_PENDING`)".

        Design: Corner/state_machines/cycle_lock_with_pending_adjustment_rejected
        """
        bundle = setup_published_job()
        cycle = create_open_cycle(bundle)
        adj = create_draft_adjustment(bundle, cycle)
        submit_adjustment(bundle, adj["id"])
        resp = api.lock_cycle(cycle["id"], mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_PENDING)

    def test_submit_without_published_composite_rejected(self, api):
        """PRD §3.7: "the employee's job must have a published composite, that
        is, a non-null `current_market_composite_id`
        (`ERR_NO_PUBLISHED_COMPOSITE`)".

        Design: Corner/validations/adjustment_submit_without_published_composite_rejected
        """
        bundle = bootstrap_org()  # no strategy, survey, or composite
        cycle = create_open_cycle(bundle)
        adj = create_draft_adjustment(bundle, cycle)
        resp = api.submit_adjustment(adj["id"], analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_COMPOSITE)

    def test_apply_before_effective_date_rejected(self, api):
        """PRD §3.7: "Applying an approved adjustment — `APPROVED` to
        `APPLIED` — requires the parent cycle to be `LOCKED`
        (`ERR_CYCLE_NOT_LOCKED`) and the current date to be on or after the
        cycle's `effective_date` (`ERR_ADJUSTMENT_NOT_YET_EFFECTIVE`)".

        The logical clock reads 2026-08-01 and the cycle's effective_date is
        2026-12-01.

        Design: Corner/validations/adjustment_apply_before_effective_date_rejected
        """
        bundle = setup_published_job()
        cycle = create_open_cycle(bundle, effective_date="2026-12-01")
        adj = create_draft_adjustment(bundle, cycle)
        submit_adjustment(bundle, adj["id"])
        approve_adjustment(bundle, adj["id"])
        validate_success(api.lock_cycle(cycle["id"], mgr_headers(bundle)))
        resp = api.apply_adjustment(adj["id"], mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_NOT_YET_EFFECTIVE)


class TestAllocationInvariantAndBudget:
    def _setup_two_approved(self, api, budget=1000000,
                            effective_date="2026-08-01"):
        bundle = setup_published_job()
        subject2 = get_success_data(api.create_employee(
            bundle["org"]["id"],
            {"full_name": "Subject2", "email": "s2@x.com",
             "job_id": bundle["job"]["id"], "geo_code": "US-SF",
             "base_salary_annual_cents": 8000000, "hire_date": "2024-06-01"},
            mgr_headers(bundle)))
        cycle = create_open_cycle(bundle, budget_cents=budget,
                                  effective_date=effective_date)
        adj1 = create_draft_adjustment(bundle, cycle,
                                       proposed_amount_cents=100000)
        adj2 = create_draft_adjustment(bundle, cycle, employee=subject2,
                                       proposed_amount_cents=50000)
        submit_adjustment(bundle, adj1["id"])
        submit_adjustment(bundle, adj2["id"])
        return bundle, cycle, adj1, adj2

    def test_allocated_cents_accumulates_on_approve(self, api):
        """PRD §3.7: "The cycle's `allocated_cents` is computed, never written
        directly: it is the sum of `proposed_amount_cents` over child
        adjustments in `APPROVED` or `APPLIED` status, recomputed eagerly each
        time an adjustment enters `APPROVED`, and it changes only then."

        Design: Difficulty/compensating_invariant/cycle_allocated_cents_invariant
        """
        bundle, cycle, adj1, adj2 = self._setup_two_approved(api)
        assert get_cycle(bundle, cycle["id"])["allocated_cents"] == 0
        approve_adjustment(bundle, adj1["id"])
        assert get_cycle(bundle, cycle["id"])["allocated_cents"] == 100000
        approve_adjustment(bundle, adj2["id"])
        assert get_cycle(bundle, cycle["id"])["allocated_cents"] == 150000

    def test_allocated_cents_conserved_across_apply(self, api):
        """PRD §3.7: "it is the sum of `proposed_amount_cents` over child
        adjustments in `APPROVED` or `APPLIED` status, recomputed eagerly each
        time an adjustment enters `APPROVED`, and it changes only then."

        Applying moves adjustments APPROVED -> APPLIED, both inside the
        conserved set, so the total is unchanged.

        Design: Difficulty/compensating_invariant/cycle_allocated_cents_invariant
        """
        bundle, cycle, adj1, adj2 = self._setup_two_approved(api)
        approve_adjustment(bundle, adj1["id"])
        approve_adjustment(bundle, adj2["id"])
        validate_success(api.lock_cycle(cycle["id"], mgr_headers(bundle)))
        # effective_date 2026-08-01 equals the default clock reading.
        validate_success(api.apply_adjustment(adj1["id"], mgr_headers(bundle)))
        validate_success(api.apply_adjustment(adj2["id"], mgr_headers(bundle)))
        assert get_cycle(bundle, cycle["id"])["allocated_cents"] == 150000
        assert get_adjustment(bundle, adj1["id"])["status"] == "APPLIED"
        assert get_adjustment(bundle, adj2["id"])["status"] == "APPLIED"

    def test_approval_beyond_budget_rejected(self, api):
        """PRD §3.7: "then the budget ceiling — the cycle's current
        `allocated_cents` is read, the candidate's `proposed_amount_cents` is
        added to it, and the sum must not exceed `budget_cents`
        (`ERR_BUDGET_EXCEEDED`), with the amount added only after the check
        passes."

        Design: Corner/errors/error_budget_exceeded
        """
        bundle = setup_published_job()
        cycle = create_open_cycle(bundle, budget_cents=100000,
                                  effective_date="2026-08-01")
        adj1 = create_draft_adjustment(bundle, cycle,
                                       proposed_amount_cents=80000)
        adj2 = create_draft_adjustment(bundle, cycle,
                                       proposed_amount_cents=50000)
        submit_adjustment(bundle, adj1["id"])
        submit_adjustment(bundle, adj2["id"])
        approve_adjustment(bundle, adj1["id"])  # 80000 <= 100000
        cycle_now = get_cycle(bundle, cycle["id"])
        resp = api.approve_adjustment(
            adj2["id"], {"expected_cycle_version": cycle_now["version"]},
            mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
