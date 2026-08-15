"""Estimate revision lifecycle: forks, supersession, locks, and create-time guards."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_estimate,
    create_case,
    create_charge_item,
    create_contract_with_rates,
    create_estimate,
    create_patient,
    create_snapshot,
    present_estimate,
    price_estimate,
    set_clock,
    setup_accepted_insured_estimate,
    setup_insured_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestPresentedForkDivergentSideEffects:
    """PRESENTED forks to ACCEPTED (case-mutating) or SUPERSEDED (quiet)."""

    def _setup_two_presented_cases(self):
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000,
                           requires_auth_prior=False)
        create_contract_with_rates(
            bundling_rule="MULTIPLE_PROCEDURE_REDUCTION", reduction_pct=50,
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-F-1")
        snapshot = create_snapshot(patient["id"])
        case_a = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Knee A")
        est_a = create_estimate(case_a["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=snapshot["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        price_estimate(est_a["id"])
        present_estimate(est_a["id"])
        case_b = create_case(patient["id"], service_date="2026-08-21",
                             service_description="Knee B")
        est_b = create_estimate(case_b["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=snapshot["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        price_estimate(est_b["id"])
        present_estimate(est_b["id"])
        return patient, snapshot, case_a, est_a, case_b, est_b

    def test_accept_branch_mutates_case_deposit_and_status(self, api):
        """PRD §3.5: "the estimate becomes the case's `active_estimate_id`; the
        case's `required_deposit_cents` is set to twenty-five percent of the
        accepted `patient_responsibility_cents`, rounded half up; ... and a
        case still sitting in `OPEN` automatically advances to `IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/estimate_presented_fork_divergent_side_effects
        """
        _patient, _snap, case_a, est_a, case_b, est_b = self._setup_two_presented_cases()
        accept_estimate(est_a["id"])
        case_a_after = validate_success(api.get_case(case_a["id"], COUNSELOR), 200)
        assert case_a_after["required_deposit_cents"] == 125000
        assert case_a_after["status"] == "IN_REVIEW"
        assert case_a_after["active_estimate_id"] == est_a["id"]
        # Case B is untouched by case A's acceptance.
        case_b_after = validate_success(api.get_case(case_b["id"], COUNSELOR), 200)
        assert case_b_after["required_deposit_cents"] == 0
        assert case_b_after["status"] == "OPEN"

    def test_supersede_branch_carries_no_case_side_effects(self, api):
        """PRD §3.4: "Supersession is deliberately quiet: it carries no
        case-level financial side effects, no deposit requirement, no status
        change on the case."
        PRD §3.4: "any estimate of the case in `DRAFT`, `PRICED`, or
        `PRESENTED` moves to `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/estimate_presented_fork_divergent_side_effects
        """
        _patient, snapshot, _case_a, _est_a, case_b, est_b = (
            self._setup_two_presented_cases())
        est_b2 = create_estimate(case_b["id"], pricing_mode="INSURED",
                                 eligibility_snapshot_id=snapshot["id"],
                                 lines=[{"cpt_code": "27447", "quantity": 1}])
        est_b_after = validate_success(api.get_estimate(est_b["id"], COUNSELOR), 200)
        assert est_b_after["status"] == "SUPERSEDED"
        assert est_b2["status"] == "DRAFT"
        case_b_after = validate_success(api.get_case(case_b["id"], COUNSELOR), 200)
        assert case_b_after["required_deposit_cents"] == 0, (
            "supersede carries no deposit requirement")
        assert case_b_after["status"] == "OPEN", "no status change on the case"
        assert case_b_after["active_estimate_id"] == est_b2["id"]


class TestSupersedeCardinality:
    """Exactly one live estimate per case across create+supersede pairs."""

    def _create_three_revisions(self):
        ctx = setup_insured_scenario(mrn="MRN-S-1")
        case_id = ctx["case"]["id"]
        snap_id = ctx["snapshot"]["id"]
        est1 = ctx["estimate"]
        est2 = create_estimate(case_id, pricing_mode="INSURED",
                               eligibility_snapshot_id=snap_id,
                               lines=[{"cpt_code": "27447", "quantity": 1}])
        est3 = create_estimate(case_id, pricing_mode="INSURED",
                               eligibility_snapshot_id=snap_id,
                               lines=[{"cpt_code": "27447", "quantity": 1}])
        return ctx, est1, est2, est3

    def test_revisions_increment_and_prior_estimates_supersede(self, api):
        """PRD §3.4: "Otherwise the new estimate starts in `DRAFT`, receives a
        `revision` number one higher than the case's previous estimate (1 for
        the first), and supersedes the prior revision — any estimate of the
        case in `DRAFT`, `PRICED`, or `PRESENTED` moves to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/estimate_supersede_active_cardinality_conservation
        """
        _ctx, est1, est2, est3 = self._create_three_revisions()
        assert (est1["revision"], est2["revision"], est3["revision"]) == (1, 2, 3)
        assert validate_success(api.get_estimate(est1["id"], COUNSELOR), 200)["status"] == "SUPERSEDED"
        assert validate_success(api.get_estimate(est2["id"], COUNSELOR), 200)["status"] == "SUPERSEDED"
        assert est3["status"] == "DRAFT"

    def test_exactly_one_live_estimate_and_active_pointer_conserved(self, api):
        """PRD §3.3: "`active_estimate_id` names the latest estimate on the
        case that is not superseded, cancelled, or expired — null when no such
        estimate exists."

        Design: Difficulty/compensating_invariant/estimate_supersede_active_cardinality_conservation
        """
        ctx, _est1, _est2, est3 = self._create_three_revisions()
        data, meta = validate_paginated(
            api.list_case_estimates(ctx["case"]["id"], COUNSELOR))
        assert meta["total_count"] == 3
        live = [e for e in data
                if e["status"] not in ("SUPERSEDED", "CANCELLED", "EXPIRED")]
        assert len(live) == 1, "active-estimate cardinality conserved at 1"
        assert live[0]["id"] == est3["id"]
        case = validate_success(api.get_case(ctx["case"]["id"], COUNSELOR), 200)
        assert case["active_estimate_id"] == est3["id"]


class TestEstimateListing:
    def test_estimates_list_pagination_and_status_filter(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. `offset` sets the number of items skipped and defaults
        to 0."
        PRD §2.3: "the estimate list filters by `case_id`,
        `eligibility_snapshot_id`, or `status`."
        PRD §3.4: "Otherwise the new estimate starts in `DRAFT`, receives a
        `revision` number one higher than the case's previous estimate (1 for
        the first), and supersedes the prior revision — any estimate of the
        case in `DRAFT`, `PRICED`, or `PRESENTED` moves to `SUPERSEDED`."

        Design: Corner/entities/estimates_list_pagination_and_status_filter
        """
        ctx = setup_insured_scenario(mrn="MRN-E-3", bundling_rule="NONE",
                                     reduction_pct=None)
        case_id = ctx["case"]["id"]
        est1 = ctx["estimate"]
        est2 = create_estimate(case_id, pricing_mode="INSURED",
                               eligibility_snapshot_id=ctx["snapshot"]["id"],
                               lines=[{"cpt_code": "27447", "quantity": 1}])
        assert est1["status"] == "DRAFT", "a fresh estimate starts in DRAFT"
        assert est2["status"] == "DRAFT"

        data, meta = validate_paginated(api.list_case_estimates(case_id, COUNSELOR))
        assert meta["total_count"] == 2
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(data) == 2

        filtered, meta_f = validate_paginated(api.list_estimates(
            COUNSELOR, params={"case_id": case_id, "status": "DRAFT"}))
        assert meta_f["total_count"] == 1
        assert filtered[0]["id"] == est2["id"], (
            "only the newest revision is still DRAFT; the first is SUPERSEDED")

        page, meta_p = validate_paginated(api.list_case_estimates(
            case_id, COUNSELOR, params={"limit": 1, "offset": 0}))
        assert len(page) == 1
        assert meta_p["total_count"] == 2
        assert meta_p["has_more"] is True


class TestInvalidEstimateTransitions:
    def test_accept_draft_estimate_returns_invalid_state(self, api):
        """PRD §3.4: "terminal estimates are locked against every further
        transition, and any transition attempted from a state that does not
        offer it is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "`required_deposit_cents` is zero until an estimate on the
        case is accepted".

        Design: Corner/state_machines/accept_draft_estimate_returns_invalid_state
        """
        ctx = setup_insured_scenario(mrn="MRN-SM-1")
        res = api.accept_estimate(ctx["estimate"]["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        est = validate_success(api.get_estimate(ctx["estimate"]["id"], COUNSELOR), 200)
        assert est["status"] == "DRAFT"
        case = validate_success(api.get_case(ctx["case"]["id"], COUNSELOR), 200)
        assert case["status"] == "OPEN"
        assert case["required_deposit_cents"] == 0

    def test_estimate_create_while_accepted_returns_locked(self, api):
        """PRD §3.4: "once any estimate on the case stands `ACCEPTED` or
        `FINALIZED`, creating another revision is rejected with
        `ERR_ESTIMATE_LOCKED` (HTTP 409)."

        Design: Corner/validations/estimate_create_while_accepted_returns_locked
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-V-12")
        case_id = ctx["case"]["id"]
        case_now = validate_success(api.get_case(case_id, COUNSELOR), 200)
        res = api.create_estimate(
            case_id,
            {"expected_case_version": case_now["version"],
             "pricing_mode": "INSURED",
             "eligibility_snapshot_id": ctx["snapshot"]["id"],
             "lines": [{"cpt_code": "27447", "quantity": 2}]},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_ESTIMATE_LOCKED)
        data, meta = validate_paginated(api.list_case_estimates(case_id, COUNSELOR))
        assert meta["total_count"] == 1, "the case still has exactly 1 estimate"


class TestEstimateCreationGuards:
    def test_gfe_estimate_with_snapshot_returns_400(self, api):
        """PRD §3.4: "The snapshot link is required in `INSURED` mode and
        forbidden in `UNINSURED_GFE` mode; either violation, like any other
        body-shape failure, is an `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/gfe_estimate_with_snapshot_returns_400
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        patient = create_patient(mrn="MRN-V-13")
        snapshot = create_snapshot(patient["id"])
        case = create_case(patient["id"])
        res = api.create_estimate(
            case["id"],
            {"expected_case_version": case["version"],
             "pricing_mode": "UNINSURED_GFE",
             "eligibility_snapshot_id": snapshot["id"],
             "lines": [{"cpt_code": "27447", "quantity": 1}]},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_estimate_with_unknown_cpt_returns_422(self, api):
        """PRD §3.1: "every other part of the system that names a CPT code —
        estimate lines, contract rates, authorization requests — resolves
        against this list: an unknown code is rejected with
        `ERR_UNKNOWN_CPT_CODE` (HTTP 422)."

        Design: Corner/validations/estimate_with_unknown_cpt_returns_422
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        patient = create_patient(mrn="MRN-V-5")
        snapshot = create_snapshot(patient["id"])
        case = create_case(patient["id"])
        res = api.create_estimate(
            case["id"],
            {"expected_case_version": case["version"],
             "pricing_mode": "INSURED",
             "eligibility_snapshot_id": snapshot["id"],
             "lines": [{"cpt_code": "00000", "quantity": 1}]},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_UNKNOWN_CPT_CODE)
        _data, meta = validate_paginated(
            api.list_case_estimates(case["id"], COUNSELOR))
        assert meta["total_count"] == 0, "no estimate persisted"

    def test_snapshot_patient_mismatch_returns_422(self, api):
        """PRD §3.4: "an insured estimate's snapshot must belong to the same
        patient as the case (`ERR_SNAPSHOT_PATIENT_MISMATCH`, HTTP 422)."

        Design: Corner/validations/snapshot_patient_mismatch_returns_422
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        patient_a = create_patient(mrn="MRN-V-6A")
        patient_b = create_patient(mrn="MRN-V-6B")
        snapshot_b = create_snapshot(patient_b["id"])
        case_a = create_case(patient_a["id"])
        res = api.create_estimate(
            case_a["id"],
            {"expected_case_version": case_a["version"],
             "pricing_mode": "INSURED",
             "eligibility_snapshot_id": snapshot_b["id"],
             "lines": [{"cpt_code": "27447", "quantity": 1}]},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_SNAPSHOT_PATIENT_MISMATCH)


class TestPricingReferentialGuards:
    def test_price_without_contract_returns_422(self, api):
        """PRD §3.4: "a payer contract must exist for the snapshot's
        `payer_code` (`ERR_NO_ACTIVE_CONTRACT`, HTTP 422)".

        Design: Corner/validations/price_without_contract_returns_422
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        patient = create_patient(mrn="MRN-V-4")
        snapshot = create_snapshot(patient["id"], payer_code="NOPE")
        case = create_case(patient["id"])
        estimate = create_estimate(
            case["id"], pricing_mode="INSURED",
            eligibility_snapshot_id=snapshot["id"],
            lines=[{"cpt_code": "27447", "quantity": 1}])
        res = api.price_estimate(estimate["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_CONTRACT)

    def test_price_with_stale_snapshot_returns_409(self, api):
        """PRD §3.2: "Pricing an insured estimate requires a snapshot that is
        both `ACTIVE` and within that thirty-day freshness window, and
        violations surface as `ERR_SNAPSHOT_STALE` (HTTP 409)."

        Design: Corner/validations/price_with_stale_snapshot_returns_409
        """
        ctx = setup_insured_scenario(mrn="MRN-V-3", bundling_rule="NONE",
                                     reduction_pct=None,
                                     service_date="2026-09-25")
        # Snapshot verified at 2026-08-03T09:00:00Z; +30 days is
        # 2026-09-02T09:00:00Z; the sweep at 2026-09-03 marks it STALE.
        set_clock("2026-09-03T09:00:00Z")
        res = api.price_estimate(ctx["estimate"]["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_SNAPSHOT_STALE)
        est = validate_success(api.get_estimate(ctx["estimate"]["id"], COUNSELOR), 200)
        assert est["status"] == "DRAFT"
