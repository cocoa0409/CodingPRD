"""Immediate consistency on confirm; logical-clock default
(corner design — consistency_model and cross-cutting-complexity-layers)."""
from test_helpers import (
    TEST_USERS,
    create_incident,
    create_incident_in_investigating_state,
    get_success_data,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]


class TestImmediateConsistency:
    def test_confirm_result_visible_on_immediate_get(self, api):
        """PRD §3.6: confirm advances `investigation_status` from
        `INVESTIGATING` to `CONFIRMED` and "`notification_status` flips to
        `EVALUATING`". PRD §2.9: derived counters are "recomputed eagerly
        whenever their inputs change, and ... readers may rely on as an
        internally consistent snapshot at a given `version`". The very next
        read reflects the post-confirm state.

        Design: Corner/consistency_model/immediate_consistency_on_confirm_cascade
        """
        ctx = create_incident_in_investigating_state(subject_count=1)
        inc = ctx["incident"]
        confirm_resp = api.confirm_incident(inc["id"], IC)
        validate_success(confirm_resp)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["investigation_status"] == "CONFIRMED"
        # Notification dimension transitioned in the same request.
        assert after["notification_status"] in ("EVALUATING", "REQUIRED", "NOT_REQUIRED")


class TestLogicalClockDefault:
    def test_default_clock_is_2026_05_01(self, api):
        """PRD §3.13: "The startup default of the logical clock is exactly
        `2026-05-01T00:00:00Z`, and the logical clock never falls back to
        wall-clock time." A resource created before any clock manipulation
        carries a `created_at` from that logical instant.

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_default_clock
        """
        inc = create_incident()
        assert inc["created_at"].startswith("2026-05-01"), (
            f"expected logical-clock default date, got {inc['created_at']}"
        )
