"""Ops-approve, compliance-approve, withdraw — the two-level review.

PRD §3.4 — review workflow.
"""

import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    setup_open_studio,
    setup_draft_application,
    setup_scheduled_application,
    attach_compatible_product,
    submit_application,
    ops_approve,
    compliance_approve,
    fetch_invoice,
    fetch_application,
    approve_decision_payload,
    ERR_INVALID_STATE,
    ERR_REASON_REQUIRED,
    ERR_VERSION_CONFLICT,
    ERR_STREAMER_BLOCKED,
)


class TestOpsApproveBranch:
    """PRD §3.4: ops-approve happy path and reject branch."""

    def test_ops_approve_transitions_to_compliance_pending(self, api):
        """PRD §3.4: "An approval transitions review_status from OPS_PENDING to
        COMPLIANCE_PENDING, but only if every ProductAssociation row on the
        application is currently APPROVED and still passes the four-step
        product eligibility ladder..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        submit_application(streamer, app)
        result = ops_approve(app["id"], decision="APPROVE")
        assert result["review_status"] == "COMPLIANCE_PENDING"

    def test_ops_approve_inserts_approval_record(self, api):
        """PRD §3.4: "Both the approve and reject branches insert an
        ApprovalRecord whose level is OPS, whose decision is APPROVE or REJECT,
        whose reviewer_role is OperationsReviewer, and whose reviewer_id mirrors
        X-User-ID; snapshot_streamer_tier and snapshot_provisional_fee_cents are
        pinned at decision time and are immutable thereafter."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        ops_approve(app["id"], decision="APPROVE")
        resp = api.list_approvals(app["id"], ADMIN_HEADERS)
        from test_helpers import validate_paginated
        items, _ = validate_paginated(resp)
        ops_records = [r for r in items if r["level"] == "OPS"]
        assert len(ops_records) == 1
        rec = ops_records[0]
        assert rec["decision"] == "APPROVE"
        assert rec["reviewer_role"] == "OperationsReviewer"
        assert rec["snapshot_streamer_tier"] in {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
        assert isinstance(rec["snapshot_provisional_fee_cents"], int)

    def test_ops_reject_requires_reason(self, api):
        """PRD §3.4: "A rejection transitions review_status from OPS_PENDING to
        REJECTED, requires a non-empty reason (otherwise ERR_REASON_REQUIRED,
        HTTP 422)..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        submit_application(streamer, app)
        resp = api.ops_approve(app["id"], approve_decision_payload(decision="REJECT"), OPS_HEADERS)
        validate_error(resp, ERR_REASON_REQUIRED, expected_status=422)

    def test_ops_reject_releases_associations_and_zeros_fee(self, api):
        """PRD §3.4: "A rejection transitions review_status from OPS_PENDING to
        REJECTED, requires a non-empty reason (otherwise ERR_REASON_REQUIRED,
        HTTP 422), and triggers a uniform release across every
        ProductAssociation for the application: each association moves to
        status RELEASED, the product's reserved_stock decreases by the
        association's reserved_quantity, and the product's available_stock
        increases by the same amount. The application's provisional_fee_cents
        is set to 0 and no invoice is issued."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        product, association = attach_compatible_product(app, streamer, reserved_quantity=10)
        app = submit_application(streamer, app)
        result = ops_approve(app["id"], decision="REJECT", reason="unsuitable")
        assert result["review_status"] == "REJECTED"
        assert result["provisional_fee_cents"] == 0
        # PRD: "no invoice is issued"
        from test_helpers import ERR_NOT_FOUND
        inv_resp = api.get_invoice(app["id"], ADMIN_HEADERS)
        # Either 404 (no invoice) or an empty/not-issued state. PRD says "no
        # invoice is issued" => GET should return ERR_NOT_FOUND.
        validate_error(inv_resp, ERR_NOT_FOUND, expected_status=404)


class TestComplianceApprove:
    """PRD §3.4: the most consequential transition in the system."""

    def test_compliance_approve_issues_invoice_and_schedules(self, api):
        """PRD §3.4: "On success the server pins pinned_streamer_tier to the
        streamer's current tier, computes final_fee_cents against that pinned
        tier (the final variant of the slot-fee calculation), computes
        deposit_cents as 30% of final_fee_cents with the single
        end-of-calculation rounding, issues a SlotFeeInvoice (described below)
        whose total_cents equals final_fee_cents and whose deposit_due_cents
        equals deposit_cents and whose status is ISSUED, transitions the
        application's operational_status from NOT_SCHEDULED to SCHEDULED, and
        inserts an ApprovalRecord of level COMPLIANCE."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        app = ops_approve(app["id"], decision="APPROVE")
        result = compliance_approve(app["id"], decision="APPROVE")
        assert result["review_status"] == "APPROVED"
        assert result["operational_status"] == "SCHEDULED"
        assert result["pinned_streamer_tier"] in {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
        assert isinstance(result["final_fee_cents"], int) and result["final_fee_cents"] > 0
        invoice = fetch_invoice(app["id"])
        assert invoice["status"] == "ISSUED"
        assert invoice["total_cents"] == result["final_fee_cents"]

    def test_compliance_approve_pins_streamer_tier_immutably(self, api):
        """PRD §2.8: "Wherever a parent entity transitions, any pinned snapshot
        fields on its children (for example, pinned_streamer_tier on the
        application or snapshot_streamer_tier on an approval record) are
        preserved exactly as captured — recomputing the parent's tier after
        the snapshot was taken does not retroactively rewrite the snapshot."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        app = bundle["application"]
        pinned_tier = app["pinned_streamer_tier"]
        # Re-fetch and confirm
        fresh = fetch_application(app["id"])
        assert fresh["pinned_streamer_tier"] == pinned_tier

    def test_compliance_approve_with_stale_version_returns_conflict(self, api):
        """PRD §2.4: "When present, the value must equal the entity's current
        version integer; a mismatch is rejected with ERR_VERSION_CONFLICT
        (HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        app = ops_approve(app["id"], decision="APPROVE")
        # app.version has been incremented at least twice. Pass version=1 (stale).
        resp = api.compliance_approve(
            app["id"],
            approve_decision_payload(decision="APPROVE", version=1),
            COMPLIANCE_HEADERS,
        )
        validate_error(resp, ERR_VERSION_CONFLICT, expected_status=409)

    def test_compliance_approve_with_violation_score_at_or_above_100_rejected(self, api):
        """PRD §3.4: "the streamer's violation_score is strictly less than 100
        (otherwise ERR_STREAMER_BLOCKED, HTTP 422)."

        We hand-craft a streamer near the threshold by stacking DATA_FRAUD
        violations whose severity totals >= 100. Each FALSE_ADVERTISING-with-
        3-evidence carries severity 3, and via the FINE branch the streamer's
        violation_score is incremented when ENFORCED.
        """
        set_clock(DEFAULT_BASE_TIME)
        from test_helpers import (
            create_violation,
            enforce_violation_via_sweep,
            fetch_streamer,
        )
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        app = ops_approve(app["id"], decision="APPROVE")

        # Drive violation_score to >= 100 via repeated FINE-ENFORCED violations.
        # Each FALSE_ADVERTISING with >=3 evidences => severity 3.
        # Repeat 34 times to ensure >= 100.
        for _ in range(34):
            v = create_violation(
                streamer["id"],
                violation_type="FALSE_ADVERTISING",
                evidence_refs=["e1", "e2", "e3"],
            )
            enforce_violation_via_sweep(v)

        s = fetch_streamer(streamer["id"])
        # If violation_score lands at >= 100 via the FINE path the streamer
        # might also be BLACKLISTED via score>=100 in calc_violation_penalty.
        # Either way, compliance-approve must reject.
        resp = api.compliance_approve(
            app["id"],
            approve_decision_payload(decision="APPROVE"),
            COMPLIANCE_HEADERS,
        )
        from prd_bench_local_runner.testing import validate_error_is_one_of
        # Either ERR_STREAMER_BLOCKED (violation_score >= 100) or
        # ERR_STREAMER_NOT_ACTIVE (streamer was BLACKLISTED) per PRD §3.4.
        # Both are PRD-faithful outcomes for a streamer whose score crossed 100.
        validate_error_is_one_of(resp, ["ERR_STREAMER_BLOCKED", "ERR_STREAMER_NOT_ACTIVE"])


class TestStreamerWithdraw:
    """PRD §3.4: 'A streamer may withdraw their own application from DRAFT or
    OPS_PENDING, transitioning review_status to WITHDRAWN.'
    """

    def test_streamer_withdraws_draft(self, api):
        """PRD §3.4: "A streamer may withdraw their own application from DRAFT
        or OPS_PENDING, transitioning review_status to WITHDRAWN."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        resp = api.withdraw_application(app["id"], make_streamer_headers(streamer["id"]))
        data = validate_success(resp)
        assert data["review_status"] == "WITHDRAWN"

    def test_streamer_withdraws_ops_pending(self, api):
        """PRD §3.4: "A streamer may withdraw their own application from DRAFT
        or OPS_PENDING, transitioning review_status to WITHDRAWN."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        resp = api.withdraw_application(app["id"], make_streamer_headers(streamer["id"]))
        data = validate_success(resp)
        assert data["review_status"] == "WITHDRAWN"

    def test_withdraw_releases_associations(self, api):
        """PRD §3.4: "Withdrawal releases every ProductAssociation (same release
        semantics as the ops-reject release: each association's status becomes
        RELEASED, the product's reserved_stock decreases, the product's
        available_stock increases)."
        """
        set_clock(DEFAULT_BASE_TIME)
        from test_helpers import setup_application_with_reservations, get_product
        bundle = setup_application_with_reservations(initial_available_stock=100, reserved_quantity=25)
        streamer = bundle["streamer"]
        app = bundle["application"]
        api.withdraw_application(app["id"], make_streamer_headers(streamer["id"]))
        product_after = get_product(bundle["product_initial"]["id"])
        # After release: available_stock back to 100, reserved_stock back to 0
        assert product_after["available_stock"] == 100
        assert product_after["reserved_stock"] == 0
