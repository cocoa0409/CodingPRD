"""Strip layout approval, PPAP review cycle, and order release gates (PRD §2.8, §3.2, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_ppap,
    assert_kg,
    begin_ppap_review,
    create_and_approve_layout,
    create_customer,
    create_layout,
    create_order,
    create_part,
    create_ppap_submission,
    get_part_fresh,
    reject_ppap,
    setup_part_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLayoutApprovalAndSupersede:
    def test_steel_content_resyncs_and_prior_layout_superseded(self, api, process_engineer_headers):
        """PRD §3.2: "When approval succeeds, three things happen together: the part's `steel_content_kg` is synced to the approved layout's `gross_weight_per_part_kg`; any previously `APPROVED` layout for the same part becomes `SUPERSEDED` (a system-driven transition that refreshes its `updated_at`), so that at most one layout per part is ever `APPROVED`; and the part's `version` increments with its `updated_at` refreshed."

        Design: Corner/complexity_layers/derived_steel_content_reconciles_on_layout_supersede
        """
        customer = create_customer(name="Der Co", customer_code="DER")
        part = create_part(customer["id"], part_number="P-DER", material_spec="DC04",
                           thickness_mm=0.8, net_weight_kg=0.5, base_piece_price_cents=900)
        layout_a = create_and_approve_layout(part["id"], gross_weight_per_part_kg=1.0,
                                             revision="A", strip_width_mm=300, pitch_mm=200)
        assert_kg(get_part_fresh(part["id"])["steel_content_kg"], 1.0)

        layout_b = create_layout(part["id"], revision="B", strip_width_mm=320,
                                 pitch_mm=210, gross_weight_per_part_kg=1.2)
        part_now = get_part_fresh(part["id"])
        approved_b = validate_success(
            api.approve_strip_layout(
                layout_b["id"], {"expected_part_version": part_now["version"]},
                process_engineer_headers,
            )
        )
        assert approved_b["status"] == "APPROVED"

        part_after = get_part_fresh(part["id"])
        assert_kg(part_after["steel_content_kg"], 1.2, "steel_content_kg re-synced")
        layout_a_after = validate_success(api.get_strip_layout(layout_a["id"], process_engineer_headers))
        assert layout_a_after["status"] == "SUPERSEDED"

    def test_approve_layout_with_stale_part_version_rejected(self, api, process_engineer_headers):
        """PRD §2.8: "Approving a strip layout requires `expected_part_version`, matched against the part's current `version`."
        PRD §2.8: "If the parent entity's current `version` no longer matches the supplied value — because another writer has legitimately advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is written."

        Design: Corner/errors/err_stale_version_strip_layout
        """
        customer = create_customer(name="OCC Co", customer_code="OCC")
        part = create_part(customer["id"], part_number="P-OCC", material_spec="DC04",
                           thickness_mm=0.8, net_weight_kg=0.5, base_piece_price_cents=900)
        stale_version = part["version"]
        layout_a = create_layout(part["id"], revision="A", gross_weight_per_part_kg=1.0)
        validate_success(
            api.approve_strip_layout(
                layout_a["id"], {"expected_part_version": stale_version},
                process_engineer_headers,
            )
        )
        layout_b = create_layout(part["id"], revision="B", gross_weight_per_part_kg=1.1)
        resp = api.approve_strip_layout(
            layout_b["id"], {"expected_part_version": stale_version},
            process_engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        layout_b_after = validate_success(api.get_strip_layout(layout_b["id"], process_engineer_headers))
        assert layout_b_after["status"] == "DRAFT", "a rejected approval must write nothing"


class TestPpapLifecycle:
    def test_ppap_approval_qualifies_part_die_assignments(self, api, process_engineer_headers):
        """PRD §3.5: "Approval moves the submission to the terminal `APPROVED` state and flips every part–die assignment for the part to `qualified` true — this is the moment the PPAP gate opens."
        PRD §3.3: "The assignment's `qualified` flag starts false and flips to true only when a PPAP submission for the part is approved (§3.5) — this is the PPAP gate that order release later inspects."

        Design: Corner/state_machines/ppap_approve_qualifies_assignments
        """
        ctx = setup_part_ready(approve_ppap_flag=False)
        assert ctx["assignment"]["qualified"] is False, "assignment starts unqualified"
        submission = create_ppap_submission(part_id=ctx["part"]["id"], level=1)
        begin_ppap_review(submission["id"])
        approved = approve_ppap(submission["id"])
        assert approved["status"] == "APPROVED"
        rows, _meta = validate_paginated(
            api.list_part_die_assignments(ctx["part"]["id"], process_engineer_headers)
        )
        assert len(rows) == 1
        assert rows[0]["qualified"] is True, "approval must flip every assignment to qualified"

    def test_ppap_level_mismatch_rejected(self, api, process_engineer_headers):
        """PRD §3.5: "Two submission rules are checked: the submitted `level` must equal the part's `ppap_required_level`, and whenever the level is 2 or higher a control plan must be attached — a violation of either is `ERR_PPAP_LEVEL_MISMATCH` (422)."

        Design: Corner/validations/ppap_level_mismatch_rejected
        """
        customer = create_customer(name="Lvl Co", customer_code="LVL")
        part = create_part(customer["id"], part_number="P-LVL", ppap_required_level=3)
        resp = api.create_ppap_submission(
            {"part_id": part["id"], "level": 2, "control_plan_attached": True},
            process_engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PPAP_LEVEL_MISMATCH)

    def test_ppap_level_two_without_control_plan_rejected(self, api, process_engineer_headers):
        """PRD §3.5: "Two submission rules are checked: the submitted `level` must equal the part's `ppap_required_level`, and whenever the level is 2 or higher a control plan must be attached — a violation of either is `ERR_PPAP_LEVEL_MISMATCH` (422)."

        Design: Corner/validations/ppap_level_mismatch_rejected
        """
        customer = create_customer(name="Lvl2 Co", customer_code="LVL2")
        part = create_part(customer["id"], part_number="P-LVL2", ppap_required_level=2)
        resp = api.create_ppap_submission(
            {"part_id": part["id"], "level": 2, "control_plan_attached": False},
            process_engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PPAP_LEVEL_MISMATCH)

    def test_rejected_submission_resubmits_with_incremented_revision(self, api, quality_engineer_headers):
        """PRD §3.5: "A rejected package is final for that revision; the team resubmits by creating a new submission for the same part, which is accepted only while the part's previous submission sits in `REJECTED`, and the new submission's `submission_revision` is set to the previous maximum revision plus one, restarting the cycle at `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/ppap_submission_rejection_resubmission_cycle
        """
        customer = create_customer(name="Delta EV", customer_code="DELTA")
        part = create_part(customer["id"], part_number="P-400", ppap_required_level=2)
        sub1 = create_ppap_submission(part["id"], level=2, control_plan_attached=True)
        assert sub1["submission_revision"] == 1
        begin_ppap_review(sub1["id"])
        rejected = reject_ppap(sub1["id"], "Control plan missing PFMEA linkage")
        assert rejected["status"] == "REJECTED"

        sub2 = create_ppap_submission(part["id"], level=2, control_plan_attached=True)
        assert sub2["status"] == "SUBMITTED"
        assert sub2["submission_revision"] == 2, (
            f"resubmission must take previous max revision + 1, got {sub2['submission_revision']}"
        )
        sub1_after = validate_success(api.get_ppap_submission(sub1["id"], quality_engineer_headers))
        assert sub1_after["status"] == "REJECTED", "a rejected package is final for that revision"

    def test_second_rejection_cycle_advances_revision_again(self, api):
        """PRD §3.5: "A rejected package is final for that revision; the team resubmits by creating a new submission for the same part, which is accepted only while the part's previous submission sits in `REJECTED`, and the new submission's `submission_revision` is set to the previous maximum revision plus one, restarting the cycle at `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/ppap_submission_rejection_resubmission_cycle
        """
        customer = create_customer(name="Delta2 EV", customer_code="DELTA2")
        part = create_part(customer["id"], part_number="P-401", ppap_required_level=2)
        sub1 = create_ppap_submission(part["id"], level=2, control_plan_attached=True)
        begin_ppap_review(sub1["id"])
        reject_ppap(sub1["id"], "Missing PSW")
        sub2 = create_ppap_submission(part["id"], level=2, control_plan_attached=True)
        assert sub2["submission_revision"] == 2
        begin_ppap_review(sub2["id"])
        reject_ppap(sub2["id"], "Gauge study incomplete")
        sub3 = create_ppap_submission(part["id"], level=2, control_plan_attached=True)
        assert sub3["status"] == "SUBMITTED"
        assert sub3["submission_revision"] == 3, (
            f"second resubmission must advance the monotonic counter, got {sub3['submission_revision']}"
        )


class TestReleaseGates:
    def test_release_blocked_while_ppap_only_under_review(self, api, production_planner_headers):
        """PRD §3.5: "Release moves the order `OPEN` to `RELEASED` and is gated four ways: the order must currently be `OPEN` (otherwise `ERR_INVALID_STATE`); the owning customer must be `active`; at least one part–die assignment for the part must exist with `qualified` true; an `APPROVED` strip layout must exist for the part; and a PPAP submission for the part must stand `APPROVED`. Any unmet gate is rejected with `ERR_RELEASE_GATE_UNMET` (422)."

        Design: Difficulty/cross_entity_state_dependency/order_release_depends_on_ppap_and_layout_states
        """
        # Layout approved, assignment exists but PPAP sits UNDER_REVIEW, so the
        # assignment is still unqualified: two gates are unmet at once.
        ctx = setup_part_ready(approve_ppap_flag=False)
        submission = create_ppap_submission(ctx["part"]["id"], level=1)
        begin_ppap_review(submission["id"])
        order = create_order(ctx["part"]["id"], quantity_ordered=10)
        resp = api.release_production_order(
            order["id"], {"expected_order_version": order["version"]},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_GATE_UNMET)
        order_after = validate_success(api.get_production_order(order["id"], production_planner_headers))
        assert order_after["status"] == "OPEN"

    def test_release_blocked_without_approved_layout(self, api, production_planner_headers):
        """PRD §3.5: "Release moves the order `OPEN` to `RELEASED` and is gated four ways: the order must currently be `OPEN` (otherwise `ERR_INVALID_STATE`); the owning customer must be `active`; at least one part–die assignment for the part must exist with `qualified` true; an `APPROVED` strip layout must exist for the part; and a PPAP submission for the part must stand `APPROVED`. Any unmet gate is rejected with `ERR_RELEASE_GATE_UNMET` (422)."

        Design: Difficulty/cross_entity_state_dependency/order_release_depends_on_ppap_and_layout_states
        """
        # PPAP approved (so assignments qualify) but no layout ever reaches APPROVED.
        ctx = setup_part_ready(approve_layout_flag=False)
        order = create_order(ctx["part"]["id"], quantity_ordered=10)
        resp = api.release_production_order(
            order["id"], {"expected_order_version": order["version"]},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_GATE_UNMET)
        order_after = validate_success(api.get_production_order(order["id"], production_planner_headers))
        assert order_after["status"] == "OPEN"
