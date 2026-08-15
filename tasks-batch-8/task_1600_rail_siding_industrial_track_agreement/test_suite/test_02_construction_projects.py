"""ConstructionProject spec cycle, dual cost-share variants, and settlement
ledger (PRD §2.10, §3.3).
"""
from test_helpers import (
    ENGINEER,
    RCM,
    SHIPPER,
    ApiErrorId,
    assert_construction_project,
    assert_project_ledger_invariant,
    create_project_payload,
    get_project,
    make_active_agreement,
    make_completed_project,
    make_project,
    submit_project_spec,
    validate_error,
    validate_success,
)


class TestProjectCreation:
    def test_project_create_applies_default_share_pct(self, api):
        """PRD §3.3: "The shipper's share percentage for the project,
        `shipper_share_pct`, may be omitted, in which case it defaults to the
        agreement's `shipper_cost_share_pct` as captured at project creation;
        either way it must lie between 0 and 100."
        PRD §3.3: "A new project starts in `DRAFT` with `spec_revision_no` 0
        and `amount_paid_cents` 0"

        Design: Corner/entities/project_create_applies_default_share_pct
        """
        agreement = make_active_agreement()
        res = api.create_project(
            create_project_payload(agreement["id"]),
            SHIPPER,  # shipper_share_pct omitted entirely
        )
        project = validate_success(res, 201)
        assert_construction_project(project)
        assert project["shipper_share_pct"] == 40
        assert project["spec_revision_no"] == 0
        assert project["amount_paid_cents"] == 0
        assert project["status"] == "DRAFT"


class TestSpecRevisionCycle:
    def test_spec_resubmission_increments_revision(self, api):
        """PRD §3.3: "Rejection, which requires a `rejection_reason`, returns
        the project to `SPEC_REJECTED`; the shipper may then resubmit, and any
        previously approved estimate remains untouched until a new approval
        overwrites it."
        PRD §3.3: "each submission overwrites the three spec fields and
        increments `spec_revision_no` by 1, landing the project in
        `SPEC_SUBMITTED`"

        Design: Difficulty/non_linear_state_machine/project_spec_reject_resubmit_cycle
        """
        agreement = make_active_agreement()
        project = make_project(agreement["id"])
        first = submit_project_spec(
            project["id"],
            rail_weight_lb_per_yard=115,
            tie_material="WOOD",
            ballast_depth_inches=8,
        )
        assert first["spec_revision_no"] == 1
        assert first["status"] == "SPEC_SUBMITTED"
        rejected = validate_success(
            api.reject_spec(
                project["id"],
                {"rejection_reason": "Ballast depth below standard"},
                ENGINEER,
            )
        )
        assert rejected["status"] == "SPEC_REJECTED"
        second = submit_project_spec(
            project["id"],
            rail_weight_lb_per_yard=136,
            tie_material="CONCRETE",
            ballast_depth_inches=12,
        )
        assert second["spec_revision_no"] == 2
        assert second["status"] == "SPEC_SUBMITTED"

    def test_approval_pins_latest_revision_fields(self, api):
        """PRD §3.3: "Approval moves `SPEC_SUBMITTED` to `SPEC_APPROVED` and
        computes the estimated cost share: `shipper_estimated_share_cents` is
        `estimated_cost_cents` multiplied by `shipper_share_pct`, divided by
        100, rounded half-up to whole cents — and this figure is pinned to the
        `spec_revision_no` current at approval."

        Design: Difficulty/non_linear_state_machine/project_spec_reject_resubmit_cycle
        """
        agreement = make_active_agreement()
        project = make_project(agreement["id"])
        submit_project_spec(
            project["id"],
            rail_weight_lb_per_yard=115,
            tie_material="WOOD",
            ballast_depth_inches=8,
        )
        validate_success(
            api.reject_spec(
                project["id"],
                {"rejection_reason": "Ballast depth below standard"},
                ENGINEER,
            )
        )
        submit_project_spec(
            project["id"],
            rail_weight_lb_per_yard=136,
            tie_material="CONCRETE",
            ballast_depth_inches=12,
        )
        approved = validate_success(
            api.approve_spec(
                project["id"],
                ENGINEER,
            )
        )
        assert approved["status"] == "SPEC_APPROVED"
        assert approved["spec_revision_no"] == 2
        assert approved["tie_material"] == "CONCRETE"
        assert approved["ballast_depth_inches"] == 12
        assert approved["rail_weight_lb_per_yard"] == 136
        # round_half_up(500000 * 40 / 100) = 200000
        assert approved["shipper_estimated_share_cents"] == 200000


class TestEstimatedVsFinalCostShare:
    def test_estimated_share_computed_at_spec_approval(self, api):
        """PRD §3.3: "Approval moves `SPEC_SUBMITTED` to `SPEC_APPROVED` and
        computes the estimated cost share: `shipper_estimated_share_cents` is
        `estimated_cost_cents` multiplied by `shipper_share_pct`, divided by
        100, rounded half-up to whole cents — and this figure is pinned to the
        `spec_revision_no` current at approval."

        Design: Difficulty/dual_variant_calc/construction_estimated_vs_final_cost_share
        """
        agreement = make_active_agreement()
        project = make_project(agreement["id"], estimated_cost_cents=500000)
        submit_project_spec(project["id"])
        approved = validate_success(
            api.approve_spec(
                project["id"],
                ENGINEER,
            )
        )
        assert approved["status"] == "SPEC_APPROVED"
        assert approved["shipper_estimated_share_cents"] == 200000
        assert approved["shipper_final_share_cents"] is None

    def test_final_share_recomputed_at_completion(self, api):
        """PRD §3.3: "a project estimated at 500000 cents but completed at
        450000 cents with a 40 percent share yields an estimate of 200000 and a
        final of 180000, and it is the final figure that settlement
        reconciles."
        PRD §3.3: "`outstanding_share_cents` is set to the final share minus
        `amount_paid_cents`"

        Design: Difficulty/dual_variant_calc/construction_estimated_vs_final_cost_share
        """
        agreement = make_active_agreement()
        project = make_project(agreement["id"], estimated_cost_cents=500000)
        submit_project_spec(project["id"])
        approved = validate_success(
            api.approve_spec(
                project["id"],
                ENGINEER,
            )
        )
        assert approved["shipper_estimated_share_cents"] == 200000
        completed = validate_success(
            api.complete_project(
                project["id"],
                {"actual_cost_cents": 450000},
                SHIPPER,
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["shipper_final_share_cents"] == 180000
        assert completed["shipper_final_share_cents"] != 200000
        assert completed["amount_paid_cents"] == 0
        assert completed["outstanding_share_cents"] == 180000
        assert_project_ledger_invariant(completed)


class TestSettlement:
    def test_payment_updates_ledger_preserving_invariant(self, api):
        """PRD §3.3: "Each call adds `payment_cents` to `amount_paid_cents` and
        recomputes `outstanding_share_cents` as the final share minus the
        running total, preserving the invariant that `amount_paid_cents` plus
        `outstanding_share_cents` always equals `shipper_final_share_cents`."

        Design: Difficulty/compensating_invariant/construction_payment_refund_invariant
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"], actual_cost_cents=450000)
        settled = validate_success(
            api.settle_project(project["id"], {"payment_cents": 100000}, RCM)
        )
        assert settled["amount_paid_cents"] == 100000
        assert settled["outstanding_share_cents"] == 80000
        assert_project_ledger_invariant(settled)
        assert settled["status"] == "COMPLETED"

    def test_refund_restores_prior_ledger_state(self, api):
        """PRD §3.3: "Settlement is a `RailroadContractsManager` function that
        records one `payment_cents` amount per call: a positive value is a
        payment, a negative value is a refund correction."
        PRD §3.3: "Each call adds `payment_cents` to `amount_paid_cents` and
        recomputes `outstanding_share_cents` as the final share minus the
        running total, preserving the invariant that `amount_paid_cents` plus
        `outstanding_share_cents` always equals `shipper_final_share_cents`."

        Design: Difficulty/compensating_invariant/construction_payment_refund_invariant
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"], actual_cost_cents=450000)
        validate_success(api.settle_project(project["id"], {"payment_cents": 100000}, RCM))
        restored = validate_success(
            api.settle_project(project["id"], {"payment_cents": -100000}, RCM)
        )
        assert restored["amount_paid_cents"] == 0
        assert restored["outstanding_share_cents"] == 180000
        assert_project_ledger_invariant(restored)
        assert restored["status"] == "COMPLETED", (
            "outstanding is back to 180000, so the project must not be SETTLED"
        )

    def test_settle_overpayment_and_excess_refund_rejected(self, api):
        """PRD §3.3: "a positive payment exceeding the outstanding share is
        rejected with `ERR_OVERPAYMENT`, as is a payment of exactly zero; a
        refund whose magnitude exceeds what has actually been paid is rejected
        with `ERR_REFUND_EXCEEDS_PAID`."

        Design: Corner/validations/settle_overpayment_and_excess_refund_rejected
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"], actual_cost_cents=450000)
        # outstanding is 180000; 180001 exceeds it.
        over = api.settle_project(project["id"], {"payment_cents": 180001}, RCM)
        validate_error(over, ApiErrorId.ERR_OVERPAYMENT, 402)
        # Nothing paid yet; any refund magnitude exceeds amount_paid_cents 0.
        refund = api.settle_project(project["id"], {"payment_cents": -1}, RCM)
        validate_error(refund, ApiErrorId.ERR_REFUND_EXCEEDS_PAID, 402)
        after = get_project(project["id"])
        assert after["amount_paid_cents"] == 0
        assert after["status"] == "COMPLETED", "rejected calls must not mutate"

    def test_settle_on_uncompleted_project_reports_state_error(self, api):
        """PRD §2.10: "When several validation rules could reject the same
        request, the order in which they fire is part of the contract — the
        first matching failure determines the error returned."
        PRD §2.10: "sixth, whether the target resource's own status permits the
        transition (the per-entity invalid-state errors such as
        `ERR_AGREEMENT_INVALID_STATE` or `ERR_ORDER_INVALID_STATE`)"
        PRD §2.10: "twelfth, money checks (`ERR_OVERPAYMENT`,
        `ERR_REFUND_EXCEEDS_PAID`)"

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_fiscal_overpayment
        """
        agreement = make_active_agreement()
        project = make_project(agreement["id"], estimated_cost_cents=500000)
        submit_project_spec(project["id"])
        validate_success(
            api.approve_spec(
                project["id"],
                ENGINEER,
            )
        )
        # SPEC_APPROVED does not permit settle; 999999 would also overpay, but
        # the own-status check (sixth) fires before the money check (twelfth).
        res = api.settle_project(project["id"], {"payment_cents": 999999}, RCM)
        validate_error(res, ApiErrorId.ERR_PROJECT_INVALID_STATE, 409)
        after = get_project(project["id"])
        assert after["status"] == "SPEC_APPROVED"
        assert after["amount_paid_cents"] == 0

    def test_settle_on_settled_project_reports_state_error(self, api):
        """PRD §3.3: "When a payment drives the outstanding share to exactly
        zero, the project automatically transitions from `COMPLETED` to
        `SETTLED` — the project's terminal state — within the same operation."
        PRD §2.10: "sixth, whether the target resource's own status permits the
        transition (the per-entity invalid-state errors such as
        `ERR_AGREEMENT_INVALID_STATE` or `ERR_ORDER_INVALID_STATE`)"
        PRD §2.10: "twelfth, money checks (`ERR_OVERPAYMENT`,
        `ERR_REFUND_EXCEEDS_PAID`)"

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_fiscal_overpayment
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"], actual_cost_cents=450000)
        settled = validate_success(
            api.settle_project(project["id"], {"payment_cents": 180000}, RCM)
        )
        assert settled["status"] == "SETTLED"
        assert settled["outstanding_share_cents"] == 0
        # SETTLED is terminal; any further payment (which would also exceed the
        # zero outstanding share) must draw the state error, not the fiscal one.
        res = api.settle_project(project["id"], {"payment_cents": 100}, RCM)
        validate_error(res, ApiErrorId.ERR_PROJECT_INVALID_STATE, 409)

    def test_settle_visibility_is_immediate(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "Each call adds `payment_cents` to `amount_paid_cents` and
        recomputes `outstanding_share_cents` as the final share minus the
        running total, preserving the invariant that `amount_paid_cents` plus
        `outstanding_share_cents` always equals `shipper_final_share_cents`."

        Design: Corner/consistency_model/immediate_visibility_after_settle
        """
        agreement = make_active_agreement()
        project = make_completed_project(agreement["id"], actual_cost_cents=450000)
        settled = validate_success(
            api.settle_project(project["id"], {"payment_cents": 100000}, RCM)
        )
        assert settled["amount_paid_cents"] == 100000
        assert settled["outstanding_share_cents"] == 80000
        fetched = get_project(project["id"])
        assert fetched["amount_paid_cents"] == 100000
        assert fetched["outstanding_share_cents"] == 80000
