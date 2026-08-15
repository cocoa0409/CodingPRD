"""Records, retention due-date computation, posture ladder, and the logical clock."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_instant_equals,
    assert_record,
    create_hold,
    register_custodian,
    register_record,
    set_clock,
    setup_schedule,
    setup_schedule_with_record,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


class TestRecordReads:
    def test_get_record_not_found_returns_404(self, api):
        """PRD §2.4: "Path parameters are validated for existence
        left-to-right; the first missing identifier yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_record_not_found_returns_404
        """
        rec = api.get_record(NON_EXISTENT_UUID, RM)
        validate_error(rec, ApiErrorId.ERR_NOT_FOUND)
        hold = api.get_legal_hold(NON_EXISTENT_UUID, LC)
        validate_error(hold, ApiErrorId.ERR_NOT_FOUND)

    def test_record_create_computes_retention_fields(self, api):
        """PRD §3.4: "At creation the record is `ACTIVE`, and its
        `retention_due_date` and `governing_rule_id` are computed immediately
        from the current schedule."
        PRD §3.4: "Under `EVENT_DATE`, the anchor is the record's raw
        `event_date`."
        PRD §3.4: "The due date is then the anchor plus the rule's
        `retention_months`"

        Design: Corner/entities/record_create_computes_retention_fields
        """
        ctx = setup_schedule(months=2)
        resp = api.create_record(
            {
                "program_id": ctx["program"]["id"],
                "record_class_id": ctx["record_class"]["id"],
                "jurisdiction_id": ctx["jurisdiction"]["id"],
                "title": "Computed",
                "source_system": "ERP",
                "event_date": "2026-05-10T00:00:00Z",
                "size_gb": 3,
            },
            RM,
        )
        record = validate_success(resp, 201)
        assert_record(record)
        assert_instant_equals(record["retention_due_date"], "2026-07-10T00:00:00Z")
        assert record["governing_rule_id"] == ctx["rule"]["id"]
        assert record["disposition_posture"] == "ELIGIBLE", (
            "due 2026-07-10 is on or before the default clock 2026-08-01"
        )
        assert record["active_hold_count"] == 0
        assert record["auto_delete_suspended"] is False
        assert record["status"] == "ACTIVE"

    def test_record_unscheduled_when_no_rule_covers_event(self, api):
        """PRD §3.4: "zero candidates means the record is `UNSCHEDULED` with a
        null `retention_due_date` and null `governing_rule_id`."
        PRD §3.8: "The sweep destroys every record of the program whose posture
        is `ELIGIBLE`, whose `auto_delete_enabled` is `true`, and whose
        `auto_delete_suspended` is `false`."

        Design: Corner/entities/record_unscheduled_when_no_rule_covers_event
        """
        ctx = setup_schedule(months=6, effective_from="2025-01-01T00:00:00Z",
                             effective_to="2026-01-01T00:00:00Z")
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="Old",
            event_date="2021-06-01T00:00:00Z")
        assert record["governing_rule_id"] is None
        assert record["retention_due_date"] is None
        assert record["disposition_posture"] == "UNSCHEDULED", (
            "event 2021-06-01 falls outside the window [2025-01-01, 2026-01-01)"
        )

        sweep = api.run_auto_delete_sweep(ctx["program"]["id"], "SECURE_ERASE", RM)
        result = validate_success(sweep, 200)
        assert result["destroyed_count"] == 0, "UNSCHEDULED is never eligible"

    def test_list_records_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`
        (the maximum number of items returned) and `offset` (the number of
        items skipped before returning results)."
        PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`, where `has_more` indicates
        whether additional items exist beyond the returned window."

        Design: Corner/entities/list_records_pagination_envelope
        """
        ctx = setup_schedule(months=120)
        for title in ("A", "B", "C"):
            register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                            ctx["jurisdiction"]["id"], title=title,
                            event_date="2026-01-15T00:00:00Z")

        page1, meta1 = validate_paginated(
            api.list_records(RM, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_records(RM, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestDueDateVariants:
    def test_event_date_basis_anchors_on_raw_event(self, api):
        """PRD §3.4: "Under `EVENT_DATE`, the anchor is the record's raw
        `event_date`."
        PRD §3.4: "The due date is then the anchor plus the rule's
        `retention_months`"
        PRD §3.4: "then `ELIGIBLE` (the current logical time is on or after
        `retention_due_date`, inclusive), else `RETAINED`."

        Design: Difficulty/dual_variant_calc/retention_due_date_event_vs_fiscal_basis
        """
        ctx = setup_schedule(months=12, basis="EVENT_DATE", fye_month=6,
                             fye_day=30, rule_code="R-EV", class_code="CL_EVT")
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="Rec X",
            event_date="2026-03-15T00:00:00Z", size_gb=2)
        assert_instant_equals(record["retention_due_date"], "2027-03-15T00:00:00Z")
        assert record["disposition_posture"] == "RETAINED", (
            "due 2027-03-15 is after the default clock 2026-08-01"
        )

    def test_fiscal_year_end_basis_anchors_on_fye(self, api):
        """PRD §3.4: "Under `FISCAL_YEAR_END`, the anchor is the first program
        fiscal-year-end date on or after the `event_date`"
        PRD §3.4: "so an `event_date` on or before that year's fiscal-year-end
        anchors to that same fiscal-year-end (an event exactly on the
        fiscal-year-end anchors to that same day), and an `event_date` after
        that year's fiscal-year-end anchors to the following year's."

        Design: Difficulty/dual_variant_calc/retention_due_date_event_vs_fiscal_basis
        """
        ctx = setup_schedule(months=12, basis="FISCAL_YEAR_END", fye_month=6,
                             fye_day=30, rule_code="R-FY", class_code="CL_FY")
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="Rec Y",
            event_date="2026-03-15T00:00:00Z", size_gb=2)
        # event 2026-03-15 <= FYE 2026-06-30 -> anchor 2026-06-30, +12 months.
        assert_instant_equals(record["retention_due_date"], "2027-06-30T00:00:00Z")
        assert record["disposition_posture"] == "RETAINED"
        # The same event_date under a raw EVENT_DATE rule would be due
        # 2027-03-15; the fiscal anchor pushes the due date later.
        assert record["retention_due_date"][:10] != "2027-03-15"

    def test_fiscal_anchor_on_exact_fye_date(self, api):
        """PRD §3.4: "an event exactly on the fiscal-year-end anchors to that
        same day"
        PRD §3.4: "The due date is then the anchor plus the rule's
        `retention_months`"

        Design: Corner/calculations/fiscal_anchor_on_exact_fye_date
        """
        ctx = setup_schedule(months=6, basis="FISCAL_YEAR_END", fye_month=6,
                             fye_day=30, rule_code="R-FY6", class_code="FIN")
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="FY Edge", source_system="GL",
            event_date="2026-06-30T00:00:00Z")
        # anchor = FYE 2026-06-30 itself, + 6 months.
        assert_instant_equals(record["retention_due_date"], "2026-12-30T00:00:00Z")

    def test_add_months_clamps_to_short_month(self, api):
        """PRD §3.4: "The due date is then the anchor plus the rule's
        `retention_months`, computed with month arithmetic that clamps to the
        target month's last day when the anchor's day-of-month exceeds it (so
        2026-01-31 plus one month lands on 2026-02-28 in a non-leap year)."

        Design: Corner/calculations/add_months_clamps_to_short_month
        """
        ctx = setup_schedule(months=1)
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="Clamp",
            event_date="2026-01-31T00:00:00Z")
        assert_instant_equals(record["retention_due_date"], "2026-02-28T00:00:00Z")


class TestEligibilityBoundary:
    def test_record_retained_one_second_before_due(self, api):
        """PRD §3.4: "then `ELIGIBLE` (the current logical time is on or after
        `retention_due_date`, inclusive), else `RETAINED`."

        Design: Difficulty/boundary_precision_check/eligibility_at_exact_due_date
        """
        set_clock("2026-07-31T23:59:59Z")
        ctx, record = setup_schedule_with_record(
            months=1, event_date="2026-07-01T00:00:00Z", title="Due Soon")
        assert_instant_equals(record["retention_due_date"], "2026-08-01T00:00:00Z")

        before = validate_success(api.get_record(record["id"], RM), 200)
        assert before["disposition_posture"] == "RETAINED", (
            "one second before the due instant the record is still RETAINED"
        )

        set_clock("2026-08-01T00:00:00Z")
        at = validate_success(api.get_record(record["id"], RM), 200)
        assert_instant_equals(at["retention_due_date"], "2026-08-01T00:00:00Z")
        assert at["disposition_posture"] == "ELIGIBLE", (
            "at exactly the due instant the inclusive comparison makes it ELIGIBLE"
        )

    def test_auto_delete_sweep_destroys_at_exact_due_instant(self, api):
        """PRD §3.4: "then `ELIGIBLE` (the current logical time is on or after
        `retention_due_date`, inclusive), else `RETAINED`."
        PRD §3.8: "The sweep destroys every record of the program whose posture
        is `ELIGIBLE`, whose `auto_delete_enabled` is `true`, and whose
        `auto_delete_suspended` is `false`."

        Design: Difficulty/boundary_precision_check/eligibility_at_exact_due_date
        """
        set_clock("2026-07-31T23:59:59Z")
        ctx, record = setup_schedule_with_record(
            months=1, event_date="2026-07-01T00:00:00Z", title="Due Soon")
        assert record["auto_delete_enabled"] is True, "auto_delete_enabled defaults to true"

        set_clock("2026-08-01T00:00:00Z")
        sweep = api.run_auto_delete_sweep(ctx["program"]["id"], "SECURE_ERASE", RM)
        result = validate_success(sweep, 200)
        assert result["destroyed_count"] == 1, (
            "the sweep at the exact due instant destroys the now-ELIGIBLE record"
        )
        after = validate_success(api.get_record(record["id"], RM), 200)
        assert after["status"] == "DESTROYED"


class TestLogicalClockDefault:
    def test_clock_default_governs_without_any_set_call(self, api):
        """PRD §2.5: "At server startup, before any administrative adjustment,
        the logical clock reads exactly 2026-08-01T00:00:00Z; it never silently
        falls back to wall-clock time."
        PRD §3.4: "then `ELIGIBLE` (the current logical time is on or after
        `retention_due_date`, inclusive), else `RETAINED`."

        Design: Corner/endpoints/clock_default_governs_without_any_set_call
        """
        ctx = setup_schedule(months=1)
        record = register_record(
            ctx["program"]["id"], ctx["record_class"]["id"],
            ctx["jurisdiction"]["id"], title="R",
            event_date="2026-07-01T00:00:00Z")
        assert_instant_equals(record["retention_due_date"], "2026-08-01T00:00:00Z")
        assert record["disposition_posture"] == "ELIGIBLE", (
            "the untouched logical clock sits at 2026-08-01T00:00:00Z, on the due date"
        )


class TestImmediateConsistency:
    def test_immediate_consistency_on_read_after_write(self, api):
        """PRD §2.7: "Whenever any of these inputs change, the dependent
        aggregates are updated atomically within the same request — every
        mutation, including multi-entity cascades, is atomic per request."
        PRD §3.5: "Every `PENDING_ISSUANCE` scope item becomes `ACTIVE` with
        `activated_at` set; for each item, the record's `active_hold_count` is
        incremented by 1, its `auto_delete_suspended` is set to `true`, its
        posture is recomputed"

        Design: Corner/consistency_model/immediate_consistency_on_read_after_write
        """
        ctx, record = setup_schedule_with_record(months=1)
        assert record["disposition_posture"] == "ELIGIBLE", (
            "the creation response already carries the computed posture (no lag)"
        )
        assert record["active_hold_count"] == 0

        custodian = register_custodian(ctx["program"]["id"])
        hold = create_hold(ctx["program"]["id"], "M-IMM", [custodian["id"]],
                           [record["id"]])
        issued = validate_success(api.issue_legal_hold(hold["id"], LC), 200)
        assert issued["active_scope_count"] == 1, (
            "the issue response reflects the scope activation in-request"
        )

        after = validate_success(api.get_record(record["id"], RM), 200)
        assert after["disposition_posture"] == "HELD"
        assert after["active_hold_count"] == 1
        assert after["auto_delete_suspended"] is True
