"""Production milestone plan construction (weight total, lock), the
submit/verify/reject cycle, progress aggregation, and immediate visibility."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_buyer,
    create_factory,
    create_milestone,
    create_quotation,
    create_sourcing_request,
    get_purchase_order,
    make_factory_rep_headers,
    make_grade_a_factory,
    make_sourcing_agent_headers,
    setup_po_scenario,
    submit_milestone,
    verify_milestone,
    reject_milestone,
    validate_error,
    validate_success,
)


def _po_ctx():
    return setup_po_scenario(ordered_qty=10, unit_price_cents=100, with_docs=False)


class TestMilestonePlanLock:
    def test_milestone_submit_before_plan_locked(self, api):
        """PRD: "Submission requires the milestone to be `PLANNED` or `REJECTED` (`ERR_MILESTONE_NOT_SUBMITTABLE` otherwise), the caller to belong to the PO's `factory_id`, the plan to be locked (`ERR_MILESTONE_PLAN_INCOMPLETE` otherwise), and the PO to be `ACTIVE` (`ERR_PO_NOT_ACTIVE` otherwise)."
        PRD: "New milestones land in `PLANNED`, and `production_status` stays `PLACED` until the first factory submit."

        Design: Corner/state_machines/milestone_submit_before_plan_locked
        """
        ctx = _po_ctx()
        milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"],
                                     name="CUTTING", weight_pct=60)
        validate_error(
            api.submit_milestone(
                milestone["id"], {"evidence_note": "early"},
                make_factory_rep_headers(ctx["factory"]["id"]),
            ),
            ApiErrorId.ERR_MILESTONE_PLAN_INCOMPLETE,
        )
        po = get_purchase_order(ctx["po"]["id"])
        assert po["production_status"] == "PLACED"
        assert po["milestone_plan_locked"] is False

    def test_milestone_weight_total_over_100_rejected_then_lock(self, api):
        """PRD: "A creation that would push the cumulative weight above 100 is rejected with `ERR_INVALID_WEIGHT_TOTAL`; one attempted after the plan is locked is rejected with `ERR_MILESTONE_PLAN_LOCKED`."
        PRD: "After each creation, if the cumulative weight across all of the PO's milestones equals exactly 100, `milestone_plan_locked` flips to true — the plan is locked."

        Design: Corner/state_machines/milestone_weight_total_over_100_rejected_then_lock
        """
        ctx = _po_ctx()
        create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="CUTTING", weight_pct=60)
        validate_error(
            api.create_milestone(
                ctx["po"]["id"], {"name": "SEWING", "weight_pct": 50},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_INVALID_WEIGHT_TOTAL,
        )
        create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="PACKING", weight_pct=40)
        assert get_purchase_order(ctx["po"]["id"])["milestone_plan_locked"] is True
        validate_error(
            api.create_milestone(
                ctx["po"]["id"], {"name": "EXTRA", "weight_pct": 1},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_MILESTONE_PLAN_LOCKED,
        )


class TestMilestoneVerification:
    def test_milestone_verify_bubbles_to_production_complete(self, api):
        """PRD: "Verification adds the milestone's `weight_pct` into `po.progress_pct`; rejection does not change progress."
        PRD: "When all of the PO's milestones reach `VERIFIED`, `production_status` advances to `PRODUCTION_COMPLETE`."
        PRD: "The first submission on the PO advances `production_status` from `PLACED` to `IN_PRODUCTION`."

        Design: Corner/state_machines/milestone_verify_bubbles_to_production_complete
        """
        ctx = _po_ctx()
        mA = create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="CUTTING", weight_pct=30)
        mB = create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="PACKING", weight_pct=70)
        submit_milestone(mA["id"], ctx["factory"]["id"], "cut done")
        submit_milestone(mB["id"], ctx["factory"]["id"], "pack done")

        verified_a = verify_milestone(mA["id"], ctx["agent"]["id"])
        assert verified_a["status"] == "VERIFIED"
        mid = get_purchase_order(ctx["po"]["id"])
        assert mid["progress_pct"] == 30
        assert mid["production_status"] == "IN_PRODUCTION"

        verify_milestone(mB["id"], ctx["agent"]["id"])
        end = get_purchase_order(ctx["po"]["id"])
        assert end["progress_pct"] == 100
        assert end["production_status"] == "PRODUCTION_COMPLETE"

    def test_milestone_reject_resubmit_loop(self, api):
        """PRD: "Submission requires the milestone to be `PLANNED` or `REJECTED` (`ERR_MILESTONE_NOT_SUBMITTABLE` otherwise), the caller to belong to the PO's `factory_id`, the plan to be locked (`ERR_MILESTONE_PLAN_INCOMPLETE` otherwise), and the PO to be `ACTIVE` (`ERR_PO_NOT_ACTIVE` otherwise)."
        PRD: "Verification adds the milestone's `weight_pct` into `po.progress_pct`; rejection does not change progress."

        Design: Corner/state_machines/milestone_reject_resubmit_loop
        """
        ctx = _po_ctx()
        milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="FULL", weight_pct=100)
        submit_milestone(milestone["id"], ctx["factory"]["id"], "v1")

        rejected = reject_milestone(milestone["id"], ctx["agent"]["id"])
        assert rejected["status"] == "REJECTED"
        resubmitted = submit_milestone(milestone["id"], ctx["factory"]["id"], "v2")
        assert resubmitted["status"] == "SUBMITTED"
        verified = verify_milestone(milestone["id"], ctx["agent"]["id"])
        assert verified["status"] == "VERIFIED"
        po = get_purchase_order(ctx["po"]["id"])
        assert po["progress_pct"] == 100
        assert po["production_status"] == "PRODUCTION_COMPLETE"

    def test_progress_pct_input_set_excludes_rejected(self, api):
        """PRD: "Verification adds the milestone's `weight_pct` into `po.progress_pct`; rejection does not change progress."
        PRD: "When all of the PO's milestones reach `VERIFIED`, `production_status` advances to `PRODUCTION_COMPLETE`."

        Design: Corner/calculations/progress_pct_input_set_excludes_rejected
        """
        ctx = _po_ctx()
        mA = create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="CUTTING", weight_pct=30)
        mB = create_milestone(ctx["po"]["id"], ctx["agent"]["id"], name="PACKING", weight_pct=70)
        submit_milestone(mA["id"], ctx["factory"]["id"])
        submit_milestone(mB["id"], ctx["factory"]["id"])
        verify_milestone(mA["id"], ctx["agent"]["id"])
        reject_milestone(mB["id"], ctx["agent"]["id"])

        po = get_purchase_order(ctx["po"]["id"])
        assert po["progress_pct"] == 30
        assert po["production_status"] == "IN_PRODUCTION"


class TestMilestoneAuthorization:
    def test_rbac_factoryrep_cannot_submit_other_factorys_milestone(self, api):
        """PRD: "Submission requires the milestone to be `PLANNED` or `REJECTED` (`ERR_MILESTONE_NOT_SUBMITTABLE` otherwise), the caller to belong to the PO's `factory_id`, the plan to be locked (`ERR_MILESTONE_PLAN_INCOMPLETE` otherwise), and the PO to be `ACTIVE` (`ERR_PO_NOT_ACTIVE` otherwise)."
        PRD: "Ownership scoping (`BuyerManager` checks `buyer_id`, `SourcingAgent` checks `assigned_agent_id`, `FactoryRep` checks `factory_id`, `Inspector` checks `inspector_id`) is enforced on every role-scoped write endpoint. A violation is rejected with `ERR_OWNERSHIP_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/roles/rbac_factoryrep_cannot_submit_other_factorys_milestone
        """
        ctx = _po_ctx()
        other_factory = make_grade_a_factory(ctx["agent"]["id"], name="F2",
                                             country_code="VN")
        milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"],
                                     name="FULL", weight_pct=100)
        validate_error(
            api.submit_milestone(
                milestone["id"], {"evidence_note": "intruder"},
                make_factory_rep_headers(other_factory["id"]),
            ),
            ApiErrorId.ERR_OWNERSHIP_SCOPE_VIOLATION,
        )
        assert api.get_milestone(
            milestone["id"], make_sourcing_agent_headers(ctx["agent"]["id"])
        ).json()["data"]["status"] == "PLANNED"


class TestImmediateVisibility:
    def test_immediate_visibility_of_writes(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD: "Verification adds the milestone's `weight_pct` into `po.progress_pct`; rejection does not change progress."
        PRD: "When all of the PO's milestones reach `VERIFIED`, `production_status` advances to `PRODUCTION_COMPLETE`."
        The verify response carries the milestone mutation, and an immediate GET
        on the PO reflects the cascaded progress and production status.

        Design: Corner/consistency_model/immediate_visibility_of_writes
        """
        ctx = _po_ctx()
        milestone = create_milestone(ctx["po"]["id"], ctx["agent"]["id"],
                                     name="FULL", weight_pct=100)
        submit_milestone(milestone["id"], ctx["factory"]["id"])
        verified = verify_milestone(milestone["id"], ctx["agent"]["id"])
        assert verified["status"] == "VERIFIED"

        po = get_purchase_order(ctx["po"]["id"])
        assert po["progress_pct"] == 100
        assert po["production_status"] == "PRODUCTION_COMPLETE"
