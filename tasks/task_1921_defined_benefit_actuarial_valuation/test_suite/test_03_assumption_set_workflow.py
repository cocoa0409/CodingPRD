"""Assumption-set drafting, dual-control review, and lifecycle tests."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_actuary_headers,
    make_senior_actuary_headers,
    create_plan,
    register_actuary,
    register_prep_and_review_actuaries,
    create_assumption_set,
    submit_assumption_set,
    approve_assumption_set,
    lock_assumption_set,
    create_locked_assumption_set,
    create_census_batch,
    add_participants,
    submit_screening,
    lock_census_batch,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


class TestAssumptionSetInitialState:
    def test_assumption_set_initial_state_is_draft(self, api):
        """PRD §3.3: "The server stamps `prepared_by_actuary_id` from the caller's
        `X-User-ID`; the set begins `DRAFT` with `approved_by_actuary_id` null."

        Design: Corner/state_machines/assumption_set_initial_state_is_draft
        """
        plan = create_plan(sponsor_name="Init Co")
        prep = register_actuary("Prep Act", "EA-1", "ENROLLED")
        aset = create_assumption_set(plan["id"], prep["id"])
        assert aset["status"] == "DRAFT"
        assert aset["approved_by_actuary_id"] is None
        assert aset["prepared_by_actuary_id"] == prep["id"]
        assert aset["version"] == 1


class TestAssumptionSetInvalidTransitions:
    def test_assumption_approve_from_draft_is_invalid_state(self, api):
        """PRD §3.3: "From `IN_REVIEW`, a `SeniorActuary` either approves or
        rejects." A DRAFT set is not IN_REVIEW.
        PRD §2.8: the from-state check rejects "a `DRAFT` assumption set is
        approved" as `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/assumption_approve_from_draft_is_invalid_state
        """
        plan = create_plan(sponsor_name="SM2 Co")
        rev = register_actuary("Rev Act", "EA-2", "ENROLLED")
        # Created by the reviewer themself (SeniorActuary role) so SoD is not the fault
        aset = create_assumption_set(plan["id"], rev["id"])
        resp = api.approve_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_reopen_locked_assumption_set_is_invalid_state(self, api):
        """PRD §3.3: "an `APPROVED` set may be reopened" — a LOCKED set is not
        APPROVED, so the from-state gate rejects with `ERR_INVALID_STATE` (HTTP 409)
        per §2.8.

        Design: Corner/validations/reopen_locked_assumption_set_is_invalid_state
        """
        plan = create_plan(sponsor_name="Reopen Co")
        prep, rev = register_prep_and_review_actuaries()
        aset = create_locked_assumption_set(plan["id"], prep["id"], rev["id"])
        assert aset["status"] == "LOCKED"
        resp = api.reopen_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAssumptionSetConstraints:
    def test_assumption_retirement_age_must_match_plan(self, api):
        """PRD §3.3: "Two assumption constraints are enforced at creation, both
        rejected as `ERR_ASSUMPTION_MISMATCH` (HTTP 422): ... the retirement age
        must equal the plan's `normal_retirement_age`."

        Design: Corner/validations/assumption_retirement_age_must_match_plan
        """
        plan = create_plan(sponsor_name="RetAge Co")  # NRA 62
        prep = register_actuary("Prep Act", "EA-1", "ENROLLED")
        resp = api.create_assumption_set(
            plan["id"],
            {
                "plan_year": 2028, "label": "bad", "mortality_table": "TEST_TABLE_4AGE",
                "funding_discount_rate": 0.05, "disclosure_discount_rate": 0.04,
                "retirement_age": 63,
            },
            make_actuary_headers(prep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_MISMATCH, 422)

    def test_assumption_year_conflict_on_second_lock(self, api):
        """PRD §3.3: "Only one assumption set per plan may be `LOCKED` for a given
        plan year; a conflicting lock is rejected with `ERR_ASSUMPTION_YEAR_CONFLICT`
        (HTTP 409)."

        Design: Corner/errors/assumption_year_conflict_on_second_lock
        """
        plan = create_plan(sponsor_name="TwoSet Co")
        prep, rev = register_prep_and_review_actuaries()
        s1 = create_locked_assumption_set(plan["id"], prep["id"], rev["id"], label="s1")
        assert s1["status"] == "LOCKED"

        s2 = create_assumption_set(plan["id"], prep["id"], label="s2")
        submit_assumption_set(s2["id"], prep["id"])
        approve_assumption_set(s2["id"], rev["id"])
        resp = api.lock_assumption_set(s2["id"], make_senior_actuary_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_YEAR_CONFLICT, 409)
        # S2 remains APPROVED
        fetched = validate_success(api.get_assumption_set(s2["id"], PLAN_ADMIN), 200)
        assert fetched["status"] == "APPROVED"

    def test_reopen_approved_set_in_use_by_live_run_rejected(self, api):
        """PRD §3.3: "reopening is forbidden while any valuation run in `INITIATED`,
        `COMPUTED`, or `CERTIFIED` references the set, and such an attempt is
        rejected with `ERR_UNIQUENESS_VIOLATION`."

        Design: Corner/validations/reopen_approved_set_in_use_by_live_run_rejected
        """
        plan = create_plan(sponsor_name="InUse Co")
        prep, rev = register_prep_and_review_actuaries()
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        submit_screening(batch["id"])
        lock_census_batch(batch["id"])
        # S2 approved but NOT locked
        s2 = create_assumption_set(plan["id"], prep["id"], label="s2")
        submit_assumption_set(s2["id"], prep["id"])
        approve_assumption_set(s2["id"], rev["id"])
        stmt = create_asset_statement(plan["id"])
        ava = create_asset_valuation(plan["id"], prep["id"])
        run = create_valuation_run(plan["id"], prep["id"], batch["id"], s2["id"], ava["id"])
        # run is INITIATED and references S2
        resp = api.reopen_assumption_set(s2["id"], make_senior_actuary_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION, 409)
        fetched = validate_success(api.get_assumption_set(s2["id"], PLAN_ADMIN), 200)
        assert fetched["status"] == "APPROVED"


class TestAssumptionSetReviewCycle:
    def test_assumption_set_reject_loop_returns_to_draft(self, api):
        """PRD §3.3: "Rejection returns the set `IN_REVIEW` → `DRAFT` for revision,
        and the submit-review loop may repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/assumption_set_review_revision_cycle
        """
        plan = create_plan(sponsor_name="Cycle Co")
        prep, rev = register_prep_and_review_actuaries()
        aset = create_assumption_set(plan["id"], prep["id"])
        v0 = aset["version"]
        submit_assumption_set(aset["id"], prep["id"])
        rejected = validate_success(
            api.reject_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"])), 200
        )
        assert rejected["status"] == "DRAFT"

    def test_assumption_set_full_cycle_to_locked(self, api):
        """PRD §3.3: "Submitting moves a `DRAFT` set to `IN_REVIEW`"; "Approval ...
        lands the set in `APPROVED`"; "an `APPROVED` set may be reopened, returning
        it `APPROVED` → `DRAFT` and clearing `approved_by_actuary_id` to null";
        "An `APPROVED` set may be locked by a `SeniorActuary` ... moving it
        `APPROVED` → `LOCKED`".

        Design: Difficulty/non_linear_state_machine/assumption_set_review_revision_cycle
        """
        plan = create_plan(sponsor_name="Cycle 2 Co")
        prep, rev = register_prep_and_review_actuaries()
        aset = create_assumption_set(plan["id"], prep["id"])
        v0 = aset["version"]

        # DRAFT -> IN_REVIEW -> DRAFT (reject loop)
        submit_assumption_set(aset["id"], prep["id"])
        api.reject_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"]))
        # DRAFT -> IN_REVIEW -> APPROVED -> DRAFT (reopen arm)
        submit_assumption_set(aset["id"], prep["id"])
        approve_assumption_set(aset["id"], rev["id"])
        reopened = validate_success(
            api.reopen_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"])), 200
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["approved_by_actuary_id"] is None
        # DRAFT -> IN_REVIEW -> APPROVED -> LOCKED
        submit_assumption_set(aset["id"], prep["id"])
        approve_assumption_set(aset["id"], rev["id"])
        locked = lock_assumption_set(aset["id"], rev["id"])
        assert locked["status"] == "LOCKED"
        assert locked["approved_by_actuary_id"] == rev["id"]
        # 8 transitions applied, one version increment each
        assert locked["version"] == v0 + 8
