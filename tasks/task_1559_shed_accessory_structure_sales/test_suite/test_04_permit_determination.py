"""Permit determination under a pinned rule set: inclusive threshold, cascades,
denial revert loop, stale rule sets, terminal decisions (PRD §3.4)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    setup_book, create_draft_order, submit_site_check, file_report,
    get_order, get_only_application, list_order_applications,
    approve_application, deny_application, drive_order_to_permit_review,
    PERMIT_FEE_120_SQFT, QUOTED_10X12_NOOPT_CASH,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]


class TestPermitThresholdInclusiveBoundary:
    def test_area_equal_threshold_requires_permit(self, api):
        """PRD §3.4: "`permit_required`, true exactly when the snapshot area is at least
        the jurisdiction's `permit_threshold_sqft` — an order landing exactly on the
        threshold needs a permit — and `fee_cents`, which is zero when no permit is
        required and otherwise the jurisdiction's base fee plus its per-square-foot rate
        times the area, rounded half-up to whole cents."

        Design: Difficulty/boundary_precision_check/permit_threshold_inclusive_boundary
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"])  # 10x12 = 120 sqft
        asm = submit_site_check(order["id"])
        file_report(asm["id"])
        app = get_only_application(order["id"])
        assert app["permit_required"] is True, "area 120 >= threshold 120 (inclusive)"
        assert app["fee_cents"] == PERMIT_FEE_120_SQFT  # 15000 + 120*50
        assert app["status"] == "SUBMITTED"
        assert get_order(order["id"])["status"] == "PERMIT_REVIEW"

    def test_area_below_threshold_not_required(self, api):
        """PRD §3.4: "`permit_required`, true exactly when the snapshot area is at least
        the jurisdiction's `permit_threshold_sqft` — an order landing exactly on the
        threshold needs a permit"
        PRD §3.4: "When no permit is required, the application is recorded directly in
        `NOT_REQUIRED`, and that creation outcome itself advances the order from
        `PERMIT_REVIEW` to `READY_TO_SCHEDULE` with no human touch."

        Design: Difficulty/boundary_precision_check/permit_threshold_inclusive_boundary
        """
        jur, model, cust = setup_book()
        order = create_draft_order(
            cust["id"], model["id"], jur["id"], width_ft=10, depth_ft=11.9  # 119 < 120
        )
        asm = submit_site_check(order["id"])
        file_report(asm["id"])
        app = get_only_application(order["id"])
        assert app["permit_required"] is False
        assert app["fee_cents"] == 0
        assert app["status"] == "NOT_REQUIRED"
        assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"


class TestAssessmentReportReadyCascade:
    """Depth-3 automatic chain for a below-threshold order: report -> order advances ->
    PermitApplication created -> NOT_REQUIRED outcome itself advances the order."""

    def _setup_site_review(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
        asm = submit_site_check(order["id"])
        return jur, order, asm

    def test_report_advances_order_to_ready(self, api):
        """PRD §3.3: "On `SUITABLE` or `SUITABLE_WITH_PREP`, the order advances from
        `SITE_REVIEW` to `PERMIT_REVIEW` and a permit application is created as described
        in §3.4"
        PRD §3.4: "When no permit is required, the application is recorded directly in
        `NOT_REQUIRED`, and that creation outcome itself advances the order from
        `PERMIT_REVIEW` to `READY_TO_SCHEDULE` with no human touch."

        Design: Difficulty/transitive_cascade/assessment_report_ready_cascade_depth3
        """
        _, order, asm = self._setup_site_review(api)
        filed = file_report(asm["id"])
        assert filed["status"] == "REPORTED"
        assert filed["verdict"] == "SUITABLE"
        assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"

    def test_cascade_creates_not_required_application(self, api):
        """PRD §3.4: "The application copies `jurisdiction_id` from the order, pins the
        jurisdiction's current `version` into `jurisdiction_version`, snapshots the
        order's `area_sqft`, and computes two derived values: `permit_required`, true
        exactly when the snapshot area is at least the jurisdiction's
        `permit_threshold_sqft`"
        PRD §3.4: "`fee_cents`, which is zero when no permit is required"

        Design: Difficulty/transitive_cascade/assessment_report_ready_cascade_depth3
        """
        jur, order, asm = self._setup_site_review(api)
        file_report(asm["id"])
        app = get_only_application(order["id"])
        assert app["permit_required"] is False
        assert app["status"] == "NOT_REQUIRED"
        assert app["fee_cents"] == 0
        assert app["area_sqft"] == 64
        assert app["jurisdiction_id"] == jur["id"]
        assert app["jurisdiction_version"] == jur["version"]


class TestPermitDenialRevertCascade:
    """Depth-2 chain from the deny trigger: SUBMITTED -> DENIED reverts the order
    PERMIT_REVIEW -> DRAFT."""

    def _setup_permit_review(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"])  # 10x12 no options
        _, app = drive_order_to_permit_review(order)
        assert app["status"] == "SUBMITTED"
        return order, app

    def test_deny_reverts_order_to_draft(self, api):
        """PRD §3.4: "Denial sets `decided_at`, records the coordinator's optional
        `decision_note`, and reverts the order from `PERMIT_REVIEW` to `DRAFT` for
        reconfiguration — the denial itself is what triggers that revert."

        Design: Difficulty/transitive_cascade/permit_denial_revert_cascade_depth2
        """
        order, app = self._setup_permit_review(api)
        denied = deny_application(app["id"], decision_note="HOA easement conflict")
        assert denied["status"] == "DENIED"
        assert denied["decision_note"] == "HOA easement conflict"
        assert denied.get("decided_at"), "decided_at must be stamped"
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_revert_preserves_quote_and_bumps_version(self, api):
        """PRD §3.4: "Denial sets `decided_at`, records the coordinator's optional
        `decision_note`, and reverts the order from `PERMIT_REVIEW` to `DRAFT` for
        reconfiguration — the denial itself is what triggers that revert. Each automatic
        order move increments the order's `version`."

        Design: Difficulty/transitive_cascade/permit_denial_revert_cascade_depth2
        """
        order, app = self._setup_permit_review(api)
        before = get_order(order["id"])
        deny_application(app["id"], decision_note="setback documentation insufficient")
        after = get_order(order["id"])
        assert after["status"] == "DRAFT"
        # No reconfiguration yet: the quote is unchanged from the PERMIT_REVIEW snapshot.
        assert after["quoted_total_cents"] == before["quoted_total_cents"] == QUOTED_10X12_NOOPT_CASH
        assert after["version"] > before["version"], "automatic revert increments version"


class TestPermitDenialRevertCycle:
    """Non-linear order machine: denial reverts to DRAFT, and the order loops through a
    second, fresh site check and determination."""

    def _denied_order(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"])
        _, app1 = drive_order_to_permit_review(order)
        deny_application(app1["id"], decision_note="setback documentation insufficient")
        return order, app1

    def test_second_loop_with_fresh_assessment(self, api):
        """PRD §3.3: "On `UNSUITABLE`, the order falls back from `SITE_REVIEW` to `DRAFT`
        for reconfiguration, and a later submission creates an entirely new assessment
        rather than resurrecting the old one."
        PRD §3.4: "When no permit is required, the application is recorded directly in
        `NOT_REQUIRED`, and that creation outcome itself advances the order from
        `PERMIT_REVIEW` to `READY_TO_SCHEDULE` with no human touch."

        Design: Difficulty/non_linear_state_machine/order_permit_denial_revert_cycle
        """
        order, app1 = self._denied_order(api)
        reverted = get_order(order["id"])
        assert reverted["status"] == "DRAFT"
        amended = validate_success(
            api.amend_order(
                order["id"],
                {"expected_order_version": reverted["version"], "width_ft": 8,
                 "depth_ft": 8},
                SALES,
            ),
            200,
        )
        asm2 = submit_site_check(order["id"], scheduled_date="2026-08-03")
        file_report(asm2["id"])
        # 8x8 = 64 < threshold 120 -> NOT_REQUIRED -> auto-advance
        assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"

        asms, meta = validate_paginated(api.list_order_site_assessments(order["id"], SALES))
        assert meta["total_count"] == 2, "one assessment per submit cycle"

        apps = list_order_applications(order["id"])
        assert len(apps) == 2
        second = next(a for a in apps if a["id"] != app1["id"])
        assert second["status"] == "NOT_REQUIRED"
        assert second["fee_cents"] == 0

    def test_first_application_stays_terminal(self, api):
        """PRD §3.4: "`APPROVED`, `DENIED`, `NOT_REQUIRED`, and `WITHDRAWN` are terminal."
        PRD §2.8: "**State preconditions** — the target resource must be in a state that
        allows the requested transition (`ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/order_permit_denial_revert_cycle
        """
        order, app1 = self._denied_order(api)
        # Re-loop the order so both applications exist.
        reverted = get_order(order["id"])
        validate_success(
            api.amend_order(
                order["id"],
                {"expected_order_version": reverted["version"], "width_ft": 8,
                 "depth_ft": 8},
                SALES,
            ),
            200,
        )
        asm2 = submit_site_check(order["id"], scheduled_date="2026-08-03")
        file_report(asm2["id"])

        first = validate_success(api.get_permit_application(app1["id"], PERMIT), 200)
        assert first["status"] == "DENIED", "terminal decision unchanged by the re-loop"
        res = api.approve_permit_application(app1["id"], PERMIT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_permit_double_approve_rejected(api):
    """PRD §3.4: "`APPROVED`, `DENIED`, `NOT_REQUIRED`, and `WITHDRAWN` are terminal."
    PRD §2.8: "**State preconditions** — the target resource must be in a state that allows
    the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/permit_double_approve_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"])
    _, app = drive_order_to_permit_review(order)
    approved = approve_application(app["id"])
    assert approved["status"] == "APPROVED"
    res = api.approve_permit_application(app["id"], PERMIT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    refreshed = validate_success(api.get_permit_application(app["id"], PERMIT), 200)
    assert refreshed["status"] == "APPROVED"


def test_stale_rule_set_rejected(api):
    """PRD §3.4: "if the jurisdiction's rule set has been edited since determination, so
    that the application's `jurisdiction_version` no longer equals the jurisdiction's
    current `version`, the decision is rejected with `ERR_STALE_RULE_SET` (HTTP 409)"

    Design: Corner/validations/stale_rule_set_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"])
    _, app = drive_order_to_permit_review(order)
    assert app["jurisdiction_version"] == jur["version"]
    # Edit the rule book: jurisdiction version advances, pinning the application stale.
    updated = validate_success(
        api.update_jurisdiction(
            jur["id"],
            {"expected_jurisdiction_version": jur["version"],
             "permit_base_fee_cents": 17500},
            PERMIT,
        ),
        200,
    )
    assert updated["version"] == jur["version"] + 1

    res = api.approve_permit_application(app["id"], PERMIT)
    validate_error(res, ApiErrorId.ERR_STALE_RULE_SET, expected_status=409)
    refreshed = validate_success(api.get_permit_application(app["id"], PERMIT), 200)
    assert refreshed["status"] == "SUBMITTED", "rejected decision records nothing"
    assert get_order(order["id"])["status"] == "PERMIT_REVIEW"
