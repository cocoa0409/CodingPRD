"""Valuation-run lifecycle: compute gating, voiding, OCC, and accrual input sets."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_actuary_headers,
    make_senior_actuary_headers,
    create_plan,
    register_prep_and_review_actuaries,
    create_census_batch,
    add_participants,
    submit_screening,
    lock_census_batch,
    create_locked_census,
    create_assumption_set,
    submit_assumption_set,
    approve_assumption_set,
    lock_assumption_set,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan_version,
    get_run,
    list_accruals,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


class TestComputeGating:
    def test_compute_requires_census_and_assumptions_locked(self, api):
        """PRD §3.5: "Computing the run (`INITIATED` → `COMPUTED`) is gated on the
        references being final: the referenced census batch must be `LOCKED`, the
        referenced assumption set must be `LOCKED`, and the referenced asset
        valuation must exist and belong to the same plan — any failure is rejected
        with `ERR_REFERENCE_NOT_LOCKED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/compute_requires_census_and_assumptions_locked
        """
        plan = create_plan(sponsor_name="Gate Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        # Census VALIDATED but NOT locked
        batch = create_census_batch(plan_id)
        add_participants(batch["id"], [
            {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        submit_screening(batch["id"])  # -> VALIDATED
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(plan_id)
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])

        resp = api.compute_valuation_run(run["id"], make_actuary_headers(prep["id"]))
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_LOCKED, 422)
        # Run remains INITIATED and no accrual rows were created
        assert get_run(run["id"])["status"] == "INITIATED"
        accruals = list_accruals(run["id"])
        assert accruals == []

    def test_compute_with_unlocked_assumption_set_rejected(self, api):
        """PRD §3.5: "the referenced assumption set must be `LOCKED` ... any failure
        is rejected with `ERR_REFERENCE_NOT_LOCKED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/compute_requires_census_and_assumptions_locked
        """
        plan = create_plan(sponsor_name="Gate 2 Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        # Assumption set APPROVED but NOT locked
        aset = create_assumption_set(plan_id, prep["id"])
        submit_assumption_set(aset["id"], prep["id"])
        approve_assumption_set(aset["id"], rev["id"])
        create_asset_statement(plan_id)
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])

        resp = api.compute_valuation_run(run["id"], make_actuary_headers(prep["id"]))
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_LOCKED, 422)


class TestRunVoidAndCertifyStates:
    def test_void_certified_run_is_invalid_state(self, api):
        """PRD §3.5: "A run still in `INITIATED` or `COMPUTED` may be voided by
        either actuary role." A CERTIFIED run has no void transition.
        PRD §2.8: from-state violations reject as `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/void_certified_run_is_invalid_state
        """
        fx = setup_certified_plan(
            sponsor_name="Void Co",
            participant_rows=[
                {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
                 "current_annual_benefit": 1000},
            ],
            market_value_begin=1000, benefits_paid=50, investment_return=50,
            prior_aftap_pct=90.00,
        )
        run_id = fx["run"]["id"]
        assert fx["run"]["status"] == "CERTIFIED"
        resp = api.void_valuation_run(run_id, make_actuary_headers(fx["prep"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_run(run_id)["status"] == "CERTIFIED"

    def test_certify_twice_is_invalid_state(self, api):
        """PRD §3.6: "Certification — `COMPUTED` → `CERTIFIED` — is reserved for a
        `SeniorActuary` whose `enrollment_status` is `ENROLLED`". A CERTIFIED run is
        not COMPUTED, so per §2.8 "the generic from-state validity of the target
        entity — rejected as `ERR_INVALID_STATE` (HTTP 409)" fires on the second
        certification.

        Design: Corner/state_machines/certify_twice_is_invalid_state
        """
        fx = setup_certified_plan(
            sponsor_name="Twice Co",
            participant_rows=[
                {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
                 "current_annual_benefit": 1000},
            ],
            market_value_begin=1000, benefits_paid=50, investment_return=50,
            prior_aftap_pct=90.00,
        )
        run_id = fx["run"]["id"]
        plan_v2 = get_plan_version(fx["plan"]["id"])
        resp = api.certify_valuation_run(
            run_id,
            {"expected_plan_version": plan_v2},
            make_senior_actuary_headers(fx["rev"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestNormalCostInputSet:
    def test_normal_cost_input_set_excludes_non_active(self, api):
        """PRD §3.5: "Normal cost accrues only from `ACTIVE` participants."
        PRD §3.5: "For a `TERMINATED_VESTED` participant ... the normal-cost share
        is 0.00. For a `RETIREE` ... with a normal-cost share of 0.00."

        Design: Corner/calculations/normal_cost_input_set_excludes_non_active
        """
        plan = create_plan(sponsor_name="Filter Co", prior_aftap_pct=90.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "T1", "date_of_birth": "1968-06-01", "status": "TERMINATED_VESTED",
             "deferred_benefit_annual": 8000},
            {"external_ref": "R1", "date_of_birth": "1965-06-01", "status": "RETIREE",
             "current_annual_benefit": 5000},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        # FT = 8000*0.8034 + 5000*1.0000 = 6427.20 + 5000.00 = 11427.20
        create_asset_statement(
            plan_id, market_value_begin=11427.20, contributions_received=0,
            benefits_paid=571.36, investment_return=571.36,
        )
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        computed = compute_run(run["id"], prep["id"])
        assert computed["funding_target"] == 11427.20
        assert computed["normal_cost"] == 0.00
        accruals = list_accruals(run["id"])
        assert len(accruals) == 2
        for row in accruals:
            assert row["normal_cost_share"] == 0.00


class TestOCCStaleVersion:
    def test_certify_stale_plan_version_returns_412(self, api):
        """PRD §2.7: "Certifying a valuation run requires the request to carry
        `expected_plan_version` equal to the plan's current `version`; a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "The plan's `version` increments by one on plan termination, on
        run certification, and on election creation".

        Design: Corner/cross_cutting_layers/certify_stale_plan_version_returns_412
        """
        plan = create_plan(sponsor_name="OCC Co", prior_aftap_pct=90.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(plan_id)
        ava = create_asset_valuation(plan_id, prep["id"])
        run1 = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        compute_run(run1["id"], prep["id"])
        run2 = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        compute_run(run2["id"], prep["id"])

        plan_v = get_plan_version(plan_id)
        # First certify succeeds and bumps Plan.version
        certify_run(run1["id"], rev["id"], plan_v)
        # Second certify with the same observed version is stale
        resp = api.certify_valuation_run(
            run2["id"],
            {"expected_plan_version": plan_v},
            make_senior_actuary_headers(rev["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_run(run2["id"])["status"] == "COMPUTED"
