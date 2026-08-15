"""Restricted-license approval workflow: the two-stage legal/engineering
review, withdrawal and resubmission, approval expiry, and clock-driven
scheduled transitions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    SPEC_RESTRICTED,
    approve_license_request,
    create_gate,
    create_scan,
    evaluate_gate,
    fulfill_all_obligation_tickets,
    generate_notice,
    get_success_data,
    list_approvals,
    process_scan,
    set_clock,
    setup_product_with_approval_request,
    validate_error,
    validate_success,
)

LEGAL = TEST_USERS["legal_headers"]


class TestWithdrawResubmitCycle:
    def test_withdraw_at_legal_review_then_resubmit(self, api):
        """PRD §3.4: "The originating analyst may withdraw a request while it
        is `PENDING` or in `LEGAL_REVIEW`, moving it to `WITHDRAWN`". PRD
        §3.3: "any `RESTRICTED` entry lacking an approval spawns a license
        approval request in `PENDING`". A fresh scan of the still-unapproved
        component therefore starts the cycle again.

        Design: Difficulty/non_linear_state_machine/license_approval_cyclic_withdraw_resubmit
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "CYCLE-TEST"})
        product_id = ctx["product"]["id"]
        first = ctx["approval"]
        assert first["status"] == "PENDING"

        get_success_data(api.assign_legal(product_id, first["id"], LEGAL))
        withdrawn = validate_success(api.withdraw_license_approval(
            product_id, first["id"], ctx["analyst_headers"]))
        assert withdrawn["status"] == "WITHDRAWN"

        # Rescan the same manifest: the new BOM's restricted entry lacks any
        # approval, so a second request appears in PENDING.
        scan2 = create_scan(product_id, [SPEC_RESTRICTED],
                            analyst=ctx["analyst_headers"])
        process_scan(scan2["id"])

        approvals = list_approvals(product_id, ctx["analyst_headers"])
        assert len(approvals) == 2
        by_id = {a["id"]: a for a in approvals}
        assert by_id[first["id"]]["status"] == "WITHDRAWN"
        second = [a for a in approvals if a["id"] != first["id"]]
        assert len(second) == 1
        assert second[0]["status"] == "PENDING"
        assert second[0]["component_id"] == first["component_id"]

    def test_withdraw_from_pending_then_no_legal_assignment(self, api):
        """PRD §3.4: "The originating analyst may withdraw a request while it
        is `PENDING` or in `LEGAL_REVIEW`, moving it to `WITHDRAWN`". PRD
        §3.4: "assigning legal review on a request that is not `PENDING`
        fails with `ERR_REQUEST_NOT_PENDING` (HTTP 409)" — a `WITHDRAWN`
        request is not `PENDING`.

        Design: Difficulty/non_linear_state_machine/license_approval_cyclic_withdraw_resubmit
        """
        ctx = setup_product_with_approval_request()
        product_id = ctx["product"]["id"]
        request_id = ctx["approval"]["id"]

        withdrawn = validate_success(api.withdraw_license_approval(
            product_id, request_id, ctx["analyst_headers"]))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.assign_legal(product_id, request_id, LEGAL)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_PENDING, 409)


class TestApprovalPreconditions:
    def test_assign_legal_twice_rejected(self, api):
        """PRD §3.4: "`LegalCounsel` takes the request from `PENDING` to
        `LEGAL_REVIEW`, recording themselves as `legal_reviewer_id`;
        assigning legal review on a request that is not `PENDING` fails with
        `ERR_REQUEST_NOT_PENDING` (HTTP 409)."

        Design: Corner/state_machines/license_approval_precondition_wrong_state
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "PRECOND"})
        product_id = ctx["product"]["id"]
        request_id = ctx["approval"]["id"]

        assigned = validate_success(
            api.assign_legal(product_id, request_id, LEGAL))
        assert assigned["status"] == "LEGAL_REVIEW"
        assert assigned["legal_reviewer_id"] is not None

        resp = api.assign_legal(product_id, request_id, LEGAL)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_PENDING, 409)


class TestApprovalExpiryWindow:
    def test_evaluation_past_approval_expiry_rejected(self, api):
        """PRD §3.4: "on approval the request becomes `APPROVED` with
        `final_decision` set to `APPROVED`, `decision_effective_at` stamped at
        the decision moment, `expiry_at` set ninety days after approval".
        PRD §2.5: "an approval request relied upon past its `expiry_at` fails
        with `ERR_APPROVAL_EXPIRED` (HTTP 409), enforced at release-gate
        evaluation and at BOM finalization." PRD §2.9: "license approval
        requests past their expiry move to `EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/approval_expiry_vs_evaluation_window
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "TEMP-1"})
        product_id = ctx["product"]["id"]
        approved = approve_license_request(product_id, ctx["approval"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["expiry_at"].startswith("2026-10-30"), (
            f"approval on 2026-08-01 expires ninety days out, got "
            f"{approved['expiry_at']!r}")

        # Past the expiry, the sweep retires the approval...
        set_clock("2026-10-31T00:00:00Z")
        stale = get_success_data(api.get_license_approval(
            product_id, approved["id"], ctx["analyst_headers"]))
        assert stale["status"] == "EXPIRED"

        # ...and a gate evaluation that would rely on it is refused.
        generate_notice(product_id, ctx["bom"]["id"], ctx["analyst_headers"])
        gate = create_gate(product_id, ctx["bom"]["id"])
        resp = evaluate_gate(product_id, gate["id"])
        validate_error(resp, ApiErrorId.ERR_APPROVAL_EXPIRED, 409)

    def test_evaluation_within_approval_window_proceeds(self, api):
        """PRD §3.4: "on approval the request becomes `APPROVED` with
        `final_decision` set to `APPROVED`, `decision_effective_at` stamped at
        the decision moment, `expiry_at` set ninety days after approval".
        Inside the validity window the approval stands, so the temporal guard
        does not fire and the evaluation runs the verdict ladder of §3.7 —
        here the BOM's obligation tickets are unresolved, and "The verdict
        ladder is strict and ordered: ... obligations below one hundred
        percent fail it".

        Design: Difficulty/resource_temporal_overlap/approval_expiry_vs_evaluation_window
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "TEMP-1B"})
        product_id = ctx["product"]["id"]
        approve_license_request(product_id, ctx["approval"]["id"])

        generate_notice(product_id, ctx["bom"]["id"], ctx["analyst_headers"])
        gate = create_gate(product_id, ctx["bom"]["id"])
        evaluated = validate_success(evaluate_gate(product_id, gate["id"]))
        assert evaluated["evaluation_result"] == "FAIL"


class TestScheduledExpirySweep:
    def test_clock_sweep_expires_gate_but_not_unexpired_approval(self, api):
        """PRD §3.7: "a passing evaluation sets `evaluation_expires_at`
        thirty days out." PRD §2.9: "Advancing the clock re-evaluates every
        time-dependent rule in the system as a single sweep: ... license
        approval requests past their expiry move to `EXPIRED`, release gates
        past their `evaluation_expires_at` move to `EXPIRED`". A gate
        evaluated at the 2026-08-01 startup clock expires at 2026-08-31; an
        approval granted the same day lives until 2026-10-30.

        Design: Corner/cross_cutting/scheduled_deferred_action_expiry
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "SCHEDULED"})
        product_id = ctx["product"]["id"]
        approved = approve_license_request(product_id, ctx["approval"]["id"])

        fulfill_all_obligation_tickets(product_id, ctx["analyst_headers"])
        generate_notice(product_id, ctx["bom"]["id"], ctx["analyst_headers"])
        gate = create_gate(product_id, ctx["bom"]["id"])
        evaluated = validate_success(evaluate_gate(product_id, gate["id"]))
        assert evaluated["evaluation_result"] == "PASS"
        assert evaluated["evaluation_expires_at"].startswith("2026-08-31")

        set_clock("2026-09-01T00:00:00Z")
        gate_after = get_success_data(api.get_release_gate(
            product_id, gate["id"], TEST_USERS["release_manager_headers"]))
        assert gate_after["gate_status"] == "EXPIRED"

        approval_after = get_success_data(api.get_license_approval(
            product_id, approved["id"], ctx["analyst_headers"]))
        assert approval_after["status"] == "APPROVED"
        assert approval_after["expiry_at"].startswith("2026-10-30")
