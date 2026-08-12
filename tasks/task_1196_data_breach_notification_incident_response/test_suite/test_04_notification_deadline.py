"""Notification deadline computation — calendar vs business variants
(difficulty rule dual_variant_calc, corner design calculations section)."""
from test_helpers import (
    TEST_USERS,
    create_incident_in_investigating_state,
    create_jurisdiction_evaluation_payload,
    get_success_data,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]


class TestNotificationDeadlineVariants:
    def test_calendar_vs_business_days_produce_different_deadlines(self, api):
        """PRD §3.5: "If the kind is `CALENDAR_DAYS`, the deadline is the
        calendar date obtained by adding `deadline_days` to the determination
        date, pinned to `23:59:59.999Z` of that final day. If the kind is
        `BUSINESS_DAYS`, the deadline is computed by walking forward from the
        determination instant and counting only Monday-through-Friday days
        that are not in the hardcoded list of US federal holidays for 2026
        ... the result is again pinned to `23:59:59.999Z` of the final day."

        Determination instant = the CONFIRMED transition timestamp
        (2026-05-01T00:00:00Z, a Friday, per PRD §3.13 default logical clock).

        Design: Difficulty/dual_variant_calc/notification_deadline_calendar_vs_business_days
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="CA"
        )
        inc = ctx["incident"]

        je_ca = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="CA",
                    statute_reference="Cal. Civ. Code 1798.82",
                    record_count_threshold=1,
                    deadline_days=10,
                    deadline_kind="CALENDAR_DAYS",
                    requires_ag_notification=True,
                    requires_credit_agencies=False,
                ),
                PC,
            )
        )
        je_ny = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="NY",
                    statute_reference="NY Gen. Bus. 899-aa",
                    record_count_threshold=1,
                    deadline_days=10,
                    deadline_kind="BUSINESS_DAYS",
                    requires_ag_notification=True,
                    requires_credit_agencies=False,
                ),
                PC,
            )
        )
        confirm = api.confirm_incident(inc["id"], IC)
        validate_success(confirm)

        ca_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je_ca["id"], PC)
        )
        ny_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je_ny["id"], PC)
        )
        # CALENDAR_DAYS: 2026-05-01 + 10 days -> 2026-05-11 end-of-day.
        assert ca_after["deadline_at"] == "2026-05-11T23:59:59.999Z"
        # BUSINESS_DAYS: Fri 5/1 -> 10 business days = Fri 5/15 (skip 2 weekends;
        # no 2026 federal holiday in the window).
        assert ny_after["deadline_at"] == "2026-05-15T23:59:59.999Z"
        assert ca_after["deadline_at"] != ny_after["deadline_at"]

    def test_business_days_skips_weekend(self, api):
        """PRD §3.5: BUSINESS_DAYS counts "only Monday-through-Friday days
        that are not in the hardcoded list of US federal holidays for 2026".
        From Friday 2026-05-01 the 5th business day is Friday 2026-05-08
        (weekend 5/2-5/3 skipped).

        Design: Corner/calculations/business_days_skips_weekend
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="NY"
        )
        inc = ctx["incident"]
        je = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="NY",
                    deadline_days=5,
                    deadline_kind="BUSINESS_DAYS",
                ),
                PC,
            )
        )
        api.confirm_incident(inc["id"], IC)
        after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
        )
        assert after["deadline_at"] == "2026-05-08T23:59:59.999Z"
