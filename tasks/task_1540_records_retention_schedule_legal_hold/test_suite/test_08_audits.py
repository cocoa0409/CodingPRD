"""Hold inventory audits: snapshot semantics, staleness boundary, and
over-preservation costing."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    open_audit,
    register_record,
    set_clock,
    setup_issued_hold,
    setup_schedule,
    setup_schedule_with_record,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestOverPreservationCost:
    def _setup_two_over_preserved_records(self, api):
        """Two identical records, each raw-costing 41.25 cents at audit time."""
        ctx = setup_schedule(months=3, rate=12.5,
                             program_overrides={"over_preservation_warn_pct": 20})
        for title in ("R1", "R2"):
            register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                            ctx["jurisdiction"]["id"], title=title,
                            event_date="2026-04-01T00:00:00Z", size_gb=1.1,
                            auto_delete_enabled=False)
        # Due 2026-07-01; audit at 2026-10-01 -> 92 days over -> 3 months over.
        set_clock("2026-10-01T00:00:00Z")
        return ctx

    def test_over_preservation_cost_rounds_per_record_then_sums(self, api):
        """PRD §3.9: "the per-record cost is the monthly cost times the months
        over, rounded half-up to integer cents. Each per-record cost is rounded
        first, and only then are the per-record costs summed — summing raw
        costs and rounding once at the end is forbidden (two records at 41.25
        raw cents yield 41 plus 41 equals 82, never 83)."

        Design: Difficulty/combinatorial_formula/over_preservation_cost_per_record_rounding
        """
        ctx = self._setup_two_over_preserved_records(api)
        audit = open_audit(ctx["program"]["id"])
        # 1.1 GB x 12.5 cents/GB-month x 3 months = 41.25 -> 41 per record.
        assert audit["over_preservation_cost_cents"] == 82, (
            "per-record rounding then summing yields 41 + 41 = 82; "
            "sum-then-round would wrongly yield 83"
        )

    def test_over_preservation_counts_pct_and_breach(self, api):
        """PRD §3.9: "The snapshot captures `active_hold_count` (holds
        currently `ISSUED`), `held_record_count` (records whose posture is
        `HELD`), `eligible_record_count` (records whose posture is `ELIGIBLE`),
        and `over_preserved_record_count` (those `ELIGIBLE` records with
        `auto_delete_enabled` false)."
        PRD §3.9: "The audit's `threshold_breached` flag is true exactly when
        `over_preservation_pct` reaches the program's
        `over_preservation_warn_pct` — an inclusive comparison, so a percentage
        equal to the threshold breaches."

        Design: Difficulty/combinatorial_formula/over_preservation_cost_per_record_rounding
        """
        ctx = self._setup_two_over_preserved_records(api)
        audit = open_audit(ctx["program"]["id"])
        assert audit["eligible_record_count"] == 2
        assert audit["over_preserved_record_count"] == 2, (
            "both records are ELIGIBLE with auto_delete_enabled false"
        )
        assert audit["over_preservation_pct"] == pytest.approx(100.0, abs=0.001)
        assert audit["threshold_breached"] is True, "100.0 >= warn 20"


class TestStaleHoldBoundary:
    def test_stale_hold_strict_greater_than_boundary(self, api):
        """PRD §3.9: "An issued hold is **stale** when its `last_activity_at`
        is strictly more than the program's `stale_hold_days` before the audit
        creation time — activity exactly `stale_hold_days` ago is not stale."

        Design: Corner/calculations/stale_hold_strict_greater_than_boundary
        """
        scen = setup_issued_hold(
            program_overrides={"stale_hold_days": 30}, matter_ref="M-STALE")
        program_id = scen["ctx"]["program"]["id"]
        # Hold issued at the default clock 2026-08-01 -> last_activity_at then.

        set_clock("2026-08-31T00:00:00Z")
        audit30 = open_audit(program_id)
        assert audit30["active_hold_count"] == 1
        assert audit30["stale_hold_count"] == 0, (
            "exactly 30 days since last activity is not stale (strict >)"
        )

        set_clock("2026-09-01T00:00:00Z")
        audit31 = open_audit(program_id)
        assert audit31["stale_hold_count"] == 1, "31 days is strictly more than 30"


class TestAuditLifecycle:
    def test_audit_lifecycle_open_then_close_lockdown(self, api):
        """PRD §3.9: "An `Auditor` opens a hold inventory audit against a
        `program_id`; the audit is born `OPEN` and its snapshot fields are
        computed once at creation and frozen."
        PRD §3.9: "Closing an audit that is not `OPEN` is rejected with
        `ERR_AUDIT_NOT_OPEN` (HTTP 409)."

        Design: Corner/state_machines/audit_lifecycle_open_then_close_lockdown
        """
        ctx, record = setup_schedule_with_record(months=120,
                                                 event_date="2026-01-15T00:00:00Z")
        assert record["disposition_posture"] == "RETAINED"

        audit = open_audit(ctx["program"]["id"])
        assert audit["status"] == "OPEN"
        assert audit["eligible_record_count"] == 0, (
            "the record is due 2036-01-15 under the 120-month rule"
        )

        closed = validate_success(api.close_hold_audit(audit["id"], AUD), 200)
        assert closed["status"] == "CLOSED"

        again = api.close_hold_audit(audit["id"], AUD)
        validate_error(again, ApiErrorId.ERR_AUDIT_NOT_OPEN)

    def test_hold_audit_snapshot_frozen_at_creation(self, api):
        """PRD §3.9: "the audit is born `OPEN` and its snapshot fields are
        computed once at creation and frozen."
        PRD §3.9: "The audit's `over_preservation_pct` is the over-preserved
        count times 100 divided by the eligible count, rounded half-up to 2
        decimal places; when no records are eligible the percentage is 0."

        Design: Corner/endpoints/hold_audit_snapshot_frozen_at_creation
        """
        ctx = setup_schedule(months=1, rate=10,
                             program_overrides={"over_preservation_warn_pct": 20})
        register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                        ctx["jurisdiction"]["id"], title="R1",
                        auto_delete_enabled=False)
        first = open_audit(ctx["program"]["id"])
        assert first["eligible_record_count"] == 1
        assert first["over_preserved_record_count"] == 1
        assert first["over_preservation_pct"] == pytest.approx(100.0, abs=0.001)

        for title in ("R2", "R3", "R4"):
            register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                            ctx["jurisdiction"]["id"], title=title)

        second = open_audit(ctx["program"]["id"])
        assert second["eligible_record_count"] == 4
        assert second["over_preserved_record_count"] == 1
        assert second["over_preservation_pct"] == pytest.approx(25.0, abs=0.001)

        reread = validate_success(api.get_hold_audit(first["id"], AUD), 200)
        assert reread["eligible_record_count"] == 1, (
            "the earlier audit's snapshot never recomputes"
        )
        assert reread["over_preservation_pct"] == pytest.approx(100.0, abs=0.001)
