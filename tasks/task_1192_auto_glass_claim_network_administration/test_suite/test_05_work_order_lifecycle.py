"""Work order lifecycle: accept/decline/complete/cancel, calibration gating."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    schedule_payload, make_shop_operator_headers,
    make_shop, get_work_order, get_claim, get_policyholder, set_clock,
    setup_network, setup_work_order_offered,
    setup_work_order_accepted, setup_work_order_scheduled,
    setup_work_order_completed, setup_calibration_event,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAcceptDecline:
    def test_work_order_accept_from_accepted_rejected(self, api):
        """PRD §3.4: "A `ShopOperator` accepts an `OFFERED` work order ... the
        work order is in fact `OFFERED` (else `ERR_WORK_ORDER_NOT_OFFERED`)."

        Design: Corner/state_machines/work_order_accept_from_accepted_rejected
        """
        ctx = setup_work_order_accepted()
        wo = ctx["work_order"]
        resp = api.accept_work_order(
            wo["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_OFFERED)
        assert get_work_order(wo["id"])["status"] == "ACCEPTED"

    def test_work_order_decline_bubbles_claim_to_coverage_verified(self, api):
        """PRD §3.4: "Declining, with an optional `decline_reason`, moves it
        `OFFERED` → `DECLINED`; when no other non-terminal work order remains
        for the claim, the claim bubbles back down from `WORK_AUTHORIZED` to
        `COVERAGE_VERIFIED` and its `assigned_shop_id` is cleared to null..."

        Design: Corner/state_machines/work_order_decline_bubbles_claim_to_coverage_verified
        """
        ctx = setup_work_order_offered()
        wo = ctx["work_order"]
        resp = api.decline_work_order(
            wo["id"], {"decline_reason": "too busy"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(resp, 200)["status"] == "DECLINED"
        claim = get_claim(ctx["claim"]["id"])
        assert claim["status"] == "COVERAGE_VERIFIED"
        assert claim["assigned_shop_id"] is None


class TestTerminalCompletedLockdown:
    def test_work_order_terminal_completed_lockdown(self, api):
        """PRD §3.4: "A `ClaimAdjuster` may also cancel any work order in
        `OFFERED`, `ACCEPTED`, or `SCHEDULED` (else
        `ERR_WORK_ORDER_NOT_CANCELLABLE`)..."
        PRD §3.4: "A work order in any state other than `ACCEPTED`, `SCHEDULED`,
        or `NO_SHOW` cannot be scheduled (`ERR_WORK_ORDER_NOT_SCHEDULABLE`)..."

        Design: Corner/state_machines/work_order_terminal_completed_lockdown
        """
        ctx = setup_work_order_completed()
        wo = ctx["work_order"]
        cancel = api.cancel_work_order(wo["id"], {}, ADJUSTER)
        validate_error(cancel, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE)
        sched = api.schedule_work_order(
            wo["id"],
            schedule_payload(wo["version"],
                             scheduled_start="2026-05-03T10:00:00Z",
                             scheduled_end="2026-05-03T11:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(sched, ApiErrorId.ERR_WORK_ORDER_NOT_SCHEDULABLE)
        assert get_work_order(wo["id"])["status"] == "COMPLETED"


class TestShopOwnership:
    def test_ownership_mismatch_shop_acts_on_others_work_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `ShopOperator`, `X-User-ID` is the
        `id` of the acting GlassShop; ownership checks on any resource that
        references a GlassShop compare the resource's foreign-key field — for
        example a work order's `shop_id` — to `X-User-ID`."
        PRD §2.8: "Violations surface as `ERR_RESOURCE_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/ownership_mismatch_shop_acts_on_others_work_order
        """
        net = setup_network(with_shop=False, with_part=False)
        shop_a = make_shop(shop_name="Shop A", agreement_tier="PLATINUM")
        shop_b = make_shop(shop_name="Shop B", agreement_tier="STANDARD")
        ctx = setup_work_order_offered(net, requested_shop_id=shop_a["id"])
        resp = api.accept_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(shop_b["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP_MISMATCH)
        assert get_work_order(ctx["work_order"]["id"])["status"] == "OFFERED"


class TestCalibrationOutcomes:
    def test_calibration_verify_from_verified_rejected(self, api):
        """PRD §3.4: "Recording the outcome of a `SCHEDULED` event (else
        `ERR_CALIBRATION_NOT_SCHEDULED`) takes an `outcome`..."

        Design: Corner/state_machines/calibration_verify_from_verified_rejected
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        cal = setup_calibration_event(ctx)
        verified = api.verify_calibration_event(
            cal["id"], {"outcome": "VERIFIED", "report_reference": "R1"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(verified, 200)["status"] == "VERIFIED"
        again = api.verify_calibration_event(
            cal["id"], {"outcome": "FAILED", "report_reference": "R2"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(again, ApiErrorId.ERR_CALIBRATION_NOT_SCHEDULED)
        events, _ = validate_paginated(
            api.list_calibration_events(ctx["work_order"]["id"], ADMIN))
        assert events[0]["status"] == "VERIFIED"

    def test_rbac_shop_operator_cannot_waive_calibration(self, api):
        """PRD §3.4: "`WAIVED` may only be recorded by a `NetworkAuditor`, and
        any other role attempting it is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/rbac_shop_operator_cannot_waive_calibration
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        cal_1 = setup_calibration_event(
            ctx, "2026-05-02T12:30:00Z", "2026-05-02T13:00:00Z", "STATIC")
        cal_2 = setup_calibration_event(
            ctx, "2026-05-02T13:00:00Z", "2026-05-02T13:30:00Z", "DYNAMIC")
        waive = api.verify_calibration_event(
            cal_1["id"], {"outcome": "WAIVED"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(waive, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        events, _ = validate_paginated(
            api.list_calibration_events(ctx["work_order"]["id"], ADMIN))
        by_id = {e["id"]: e for e in events}
        assert by_id[cal_1["id"]]["status"] == "SCHEDULED"
        ok = api.verify_calibration_event(
            cal_2["id"], {"outcome": "VERIFIED", "report_reference": "R-1"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(ok, 200)["status"] == "VERIFIED"

    def test_rbac_auditor_waives_calibration(self, api):
        """PRD §3.4: "`WAIVED` may only be recorded by a `NetworkAuditor`..."
        PRD §3.4: "when the claim requires ADAS calibration, at least one linked
        CalibrationEvent must be in `VERIFIED` or `WAIVED` (else
        `ERR_CALIBRATION_NOT_VERIFIED`, HTTP 422)..."

        Design: Corner/rbac/rbac_auditor_waives_calibration
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        cal = setup_calibration_event(ctx)
        waived = api.verify_calibration_event(cal["id"], {"outcome": "WAIVED"}, AUDITOR)
        assert validate_success(waived, 200)["status"] == "WAIVED"
        set_clock("2026-05-02T14:00:00Z")
        done = api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(done, 200)["status"] == "COMPLETED"


class TestRapidCompletionBoundary:
    def test_rapid_completion_exactly_45_minutes_no_signal(self, api):
        """PRD §3.6: "The `RAPID_COMPLETION` signal, worth 25 points, fires at
        work-order completion when fewer than forty-five minutes elapsed between
        `scheduled_start` and `completed_at` and the claim's `part_category` is
        `WINDSHIELD`."

        Design: Corner/calculations/rapid_completion_exactly_45_minutes_no_signal
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z")
        set_clock("2026-05-02T10:45:00Z")  # exactly 45 minutes after start
        done = api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(done, 200)["status"] == "COMPLETED"
        alerts, meta = validate_paginated(api.list_fraud_alerts(
            TEST_USERS["investigator_headers"],
            params={"claim_id": ctx["claim"]["id"]}))
        assert meta["total_count"] == 0
        assert get_policyholder(ctx["policyholder"]["id"])["fraud_score"] == 0


# ---------------------------------------------------------------------------
# Difficulty: complete depends on calibration state
# ---------------------------------------------------------------------------

class TestCompleteDependsOnCalibration:
    def _setup_adas_with_unverified_event(self):
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        cal = setup_calibration_event(ctx)
        set_clock("2026-05-02T14:00:00Z")
        return ctx, cal

    def test_complete_with_unverified_calibration_rejected(self, api):
        """PRD §3.4: "when the claim requires ADAS calibration, at least one
        linked CalibrationEvent must be in `VERIFIED` or `WAIVED` (else
        `ERR_CALIBRATION_NOT_VERIFIED`, HTTP 422)..."

        Design: Difficulty/cross_entity_state_dependency/work_order_complete_depends_on_calibration_state
        """
        ctx, _cal = self._setup_adas_with_unverified_event()
        resp = api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_NOT_VERIFIED)
        assert get_work_order(ctx["work_order"]["id"])["status"] == "SCHEDULED"

    def test_complete_succeeds_after_calibration_verified(self, api):
        """PRD §3.4: "Completion stamps `completed_at` from the logical clock,
        releases the reserved capacity, cascades the claim `WORK_AUTHORIZED` →
        `WORK_COMPLETED`..."

        Design: Difficulty/cross_entity_state_dependency/work_order_complete_depends_on_calibration_state
        """
        ctx, cal = self._setup_adas_with_unverified_event()
        api.verify_calibration_event(
            cal["id"], {"outcome": "VERIFIED", "report_reference": "CAL-REPORT-1"},
            make_shop_operator_headers(ctx["shop"]["id"]))
        done = api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(done, 200)["status"] == "COMPLETED"
        assert get_claim(ctx["claim"]["id"])["status"] == "WORK_COMPLETED"


# ---------------------------------------------------------------------------
# Difficulty: state (P5) masks business safety (P6) on complete
# ---------------------------------------------------------------------------

class TestStateMasksSafetyOnComplete:
    def _setup_accepted_adas(self):
        return setup_work_order_accepted(
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 120000},
            shop_overrides={"adas_certified": True})

    def test_complete_from_accepted_yields_state_error(self, api):
        """PRD §2.8: "a failure in an earlier category masks the evaluation of
        later categories: ... 5. **State and request shape** — the target
        resource must be in the state the transition requires ... 6. **Business
        safety** — ADAS certification, calibration verification..."
        PRD §3.4: "Completing the work requires `SCHEDULED` as well, plus two
        further gates..."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_complete
        """
        ctx = self._setup_accepted_adas()  # ACCEPTED, no calibration event
        resp = api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        # State (P5) wins over the ADAS calibration gate (P6).
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_SCHEDULED)

    def test_failed_complete_leaves_claim_and_work_order_unchanged(self, api):
        """PRD §2.8: "a failure in an earlier category masks the evaluation of
        later categories" (the masked safety gate never fires, so nothing
        mutates).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_complete
        """
        ctx = self._setup_accepted_adas()
        api.complete_work_order(
            ctx["work_order"]["id"], make_shop_operator_headers(ctx["shop"]["id"]))
        assert get_work_order(ctx["work_order"]["id"])["status"] == "ACCEPTED"
        assert get_claim(ctx["claim"]["id"])["status"] == "WORK_AUTHORIZED"
