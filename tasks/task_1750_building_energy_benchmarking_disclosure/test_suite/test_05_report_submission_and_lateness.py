"""Report lifecycle: draft defaults, submission gates, lateness, YoY check (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_open_cycle,
    create_owner,
    create_report,
    create_verifier,
    get_report,
    make_owner_headers,
    set_clock,
    setup_report_scenario,
    setup_submitted_report,
    setup_verified_report,
    submit_report,
    upload_usage,
    validate_error,
    validate_paginated,
    validate_success,
    verify_report,
)

OFFICER = TEST_USERS["officer_headers"]


class TestReportCreationDefaults:
    def test_report_created_in_draft_with_zero_aggregates(self, api):
        """PRD §3.5: "The new report starts in `DRAFT` with `revision_number` zero,
        `is_late` false, `days_late` zero, and `submitted_at`, `verified_at`,
        `verified_site_eui`, `target_eui`, both score fields, and `label_grade` all
        null until the lifecycle reaches them, and the system immediately computes
        its `aggregated_kbtu`, `site_eui`, and `data_completeness_pct` so the draft
        reflects the data on hand."

        Design: Corner/state_machines/s_report_created_in_draft
        """
        ctx = setup_report_scenario(consent_indexes=())
        report = ctx["report"]
        assert report["status"] == "DRAFT"
        assert report["revision_number"] == 0
        assert report["is_late"] is False
        assert report["days_late"] == 0
        assert report["aggregated_kbtu"] == 0, "no usage yet"
        assert report["submitted_at"] is None
        assert report["verified_at"] is None
        assert report["verified_site_eui"] is None
        assert report["target_eui"] is None
        assert report["score_as_reported"] is None
        assert report["score_weather_normalized"] is None
        assert report["label_grade"] is None


class TestSubmissionStateGate:
    def test_submit_from_verified_rejected(self, api):
        """PRD §3.5: "The report must be in `DRAFT` or `FLAGGED` (any other state
        yields `ERR_INVALID_STATE_TRANSITION`)"

        Design: Corner/state_machines/s_submit_from_verified_returns_invalid_state
        """
        ctx = setup_verified_report()
        assert ctx["report"]["status"] == "VERIFIED"

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = get_report(ctx["report"]["id"])
        assert still["status"] == "VERIFIED"

    def test_submit_blocked_while_anomaly_open(self, api):
        """PRD §3.5: "No anomaly flag with status `OPEN` may exist on the report
        (`ERR_OPEN_ANOMALIES_EXIST`)."

        Design: Corner/state_machines/s_submit_blocked_while_anomaly_open
        """
        ctx = setup_submitted_report()
        flag = validate_success(
            api.create_anomaly_flag(
                ctx["report"]["id"], {"detail": "Officer audit hold"}, OFFICER
            ),
            201,
        )
        assert flag["status"] == "OPEN"
        assert get_report(ctx["report"]["id"])["status"] == "FLAGGED"

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_ANOMALIES_EXIST)
        still = get_report(ctx["report"]["id"])
        assert still["status"] == "FLAGGED", "report remains FLAGGED while the anomaly is OPEN"


class TestFlaggedResubmissionCycle:
    def _flag_resolve_resubmit(self, api, ctx, detail, note):
        flag = validate_success(
            api.create_anomaly_flag(ctx["report"]["id"], {"detail": detail}, OFFICER), 201
        )
        validate_success(
            api.resolve_anomaly_flag(
                flag["id"], {"resolution_note": note}, make_owner_headers(ctx["owner"]["id"])
            )
        )
        return submit_report(ctx["report"]["id"], ctx["owner"]["id"])

    def test_first_flag_resubmit_increments_revision(self, api):
        """PRD §3.5: "a resubmission out of `FLAGGED` additionally increments
        `revision_number` by one."
        PRD §3.6: "A `ComplianceOfficer` may raise a manual review on any report in
        `SUBMITTED`, `VERIFIED`, or `CERTIFIED` by supplying a `detail`; the report
        falls to `FLAGGED` and an `AnomalyFlag` of `anomaly_type` `MANUAL_REVIEW`
        opens with that detail."

        First pass through the FLAGGED -> SUBMITTED revision loop: 0 -> 1.

        Design: Difficulty/non_linear_state_machine/report_flagged_resubmission_cycle
        """
        ctx = setup_submitted_report()
        assert ctx["report"]["revision_number"] == 0

        resubmitted = self._flag_resolve_resubmit(
            api, ctx, "Meter mismatch on account E-1", "Re-read confirmed meter E-1 correct"
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_number"] == 1

    def test_second_flag_resubmit_cycle_increments_revision_again(self, api):
        """PRD §3.5: "a resubmission out of `FLAGGED` additionally increments
        `revision_number` by one."

        The report revisits SUBMITTED twice through the cyclic machine: 0 -> 1 -> 2.

        Design: Difficulty/non_linear_state_machine/report_flagged_resubmission_cycle
        """
        ctx = setup_submitted_report()

        first = self._flag_resolve_resubmit(
            api, ctx, "Meter mismatch on account E-1", "Re-read confirmed meter E-1 correct"
        )
        assert first["revision_number"] == 1

        second = self._flag_resolve_resubmit(
            api, ctx, "Second audit query on E-1", "Second review also confirms data"
        )
        assert second["status"] == "SUBMITTED"
        assert second["revision_number"] == 2


class TestLateness:
    def test_submit_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.5: "A submission at or before the effective deadline is on time —
        lateness uses a strict comparison."
        PRD §3.5: "`is_late` is true exactly when `days_late` exceeds zero — so a
        submission inside the first twenty-four hours past the deadline is not late."

        Design: Corner/calculations/c_submit_exactly_at_deadline_not_late
        """
        ctx = setup_report_scenario()
        set_clock("2027-06-01T00:00:00Z")

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["is_late"] is False
        assert submitted["days_late"] == 0

        fines, meta = validate_paginated(
            api.list_fine_assessments(OFFICER, params={"building_id": ctx["building"]["id"]})
        )
        assert meta["total_count"] == 0, "on-time filing accrues no fine"

    def test_late_fine_capped_at_cycle_cap_days(self, api):
        """PRD §3.7: "The provisional variant, frozen onto the fine at assessment,
        measures days from the effective deadline to submission: the fine's
        `days_late` records the report's uncapped days late at that moment (for
        `NON_COMPLIANCE` and `PERFORMANCE_SHORTFALL` fines, `days_late` is always
        zero), and `provisional_amount_cents` is the smaller of `days_late` and the
        cycle's `late_fine_cap_days`, multiplied by the cycle's
        `late_fine_daily_rate_cents`."

        92 whole days late: the fine charges min(92, 60) * 5000 = 300000 while both
        the report and the fine record the uncapped 92.

        Design: Corner/calculations/c_late_fine_capped_at_cap_days
        """
        ctx = setup_report_scenario()
        set_clock("2027-09-01T00:00:00Z")

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["is_late"] is True
        assert submitted["days_late"] == 92, "uncapped whole-day count"

        fines, meta = validate_paginated(
            api.list_fine_assessments(OFFICER, params={"building_id": ctx["building"]["id"]})
        )
        assert meta["total_count"] == 1
        fine = fines[0]
        assert fine["days_late"] == 92, "fine records the uncapped days late"
        assert fine["provisional_amount_cents"] == 300000, "cap of 60 days applied to money"

    def test_submit_response_carries_late_fields_immediately(self, api):
        """PRD §2.10: "The system's consistency model is immediate: every side effect
        of an operation is applied atomically with the operation itself and is
        visible in that operation's response and in every subsequent read."
        PRD §3.5: "When `days_late` exceeds zero, the system creates a
        `FineAssessment` of `fine_type` `LATE_SUBMISSION` in `ASSESSED` status whose
        `provisional_amount_cents` is the provisional late-fine variant of §3.7, and
        recomputes the owner's exposure; when `days_late` is zero, no fine is created."

        Design: Corner/consistency_model/m_submit_response_immediate_visibility
        """
        ctx = setup_report_scenario()
        set_clock("2027-06-03T12:00:00Z")

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["is_late"] is True
        assert submitted["days_late"] == 2

        fines, meta = validate_paginated(
            api.list_fine_assessments(OFFICER, params={"building_id": ctx["building"]["id"]})
        )
        assert meta["total_count"] == 1
        assert fines[0]["status"] == "ASSESSED"
        assert fines[0]["fine_type"] == "LATE_SUBMISSION"
        assert fines[0]["provisional_amount_cents"] == 10000


class TestYearOverYearAnomaly:
    def _setup_two_year_scenario(self, current_therms):
        """Building with a VERIFIED 2027 report on 40000 therms (4000000 kBtu),
        then 2028 usage of `current_therms` and a DRAFT 2028 report."""
        owner = create_owner()
        verifier = create_verifier()
        c27 = create_and_open_cycle()
        c28 = create_and_open_cycle(
            cycle_year=2028, filing_deadline_at="2028-06-01T00:00:00Z"
        )

        ctx = setup_report_scenario(
            owner=owner,
            cycle=c27,
            building_overrides={"gross_floor_area_sqft": 40000},
            unit_specs=[("U1", 20000, "OFFICE"), ("U2", 10000, "RETAIL")],
            consent_indexes=(0, 1),
            consent_window=("2027-01-01", "2028-12-31"),
            usage_records=[
                {
                    "period_start": "2027-01-01T00:00:00Z",
                    "period_end": "2028-01-01T00:00:00Z",
                    "consumption_value": 40000,
                }
            ],
            account_overrides={"commodity": "NATURAL_GAS"},
        )
        submit_ctx_report = submit_report(ctx["report"]["id"], owner["id"])
        assert submit_ctx_report["status"] == "SUBMITTED"
        verify_report(ctx, verifier)
        assert ctx["report"]["status"] == "VERIFIED"
        assert ctx["report"]["aggregated_kbtu"] == 4000000

        # 2028 usage + 2028 report
        upload_usage(
            ctx["account"]["id"],
            "2028-01-01T00:00:00Z",
            "2029-01-01T00:00:00Z",
            current_therms,
        )
        ctx["report"] = create_report(ctx["building"]["id"], c28["id"], owner["id"])
        ctx["cycle"] = c28
        return ctx

    def test_yoy_delta_exactly_at_threshold_does_not_flag(self, api):
        """PRD §3.5: "If that delta is strictly greater than the cycle's
        `anomaly_yoy_threshold_pct` — a delta at exactly the threshold does not flag
        — and no `CONSUMPTION_SPIKE` flag has ever existed on this report, the system
        creates an `AnomalyFlag` of `anomaly_type` `CONSUMPTION_SPIKE` in `OPEN`
        status and the report lands in `FLAGGED` instead of `SUBMITTED`."

        50000 therms vs 40000 therms is a delta of exactly 25.00 percent.

        Design: Corner/calculations/c_yoy_anomaly_exactly_at_threshold_no_flag
        """
        ctx = self._setup_two_year_scenario(current_therms=50000)
        set_clock("2028-05-15T00:00:00Z")

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["status"] == "SUBMITTED", "exactly at the threshold does not flag"
        assert submitted["aggregated_kbtu"] == 5000000

    def test_yoy_delta_above_threshold_flags_consumption_spike(self, api):
        """PRD §3.5: "If that delta is strictly greater than the cycle's
        `anomaly_yoy_threshold_pct` — a delta at exactly the threshold does not flag
        — and no `CONSUMPTION_SPIKE` flag has ever existed on this report, the system
        creates an `AnomalyFlag` of `anomaly_type` `CONSUMPTION_SPIKE` in `OPEN`
        status and the report lands in `FLAGGED` instead of `SUBMITTED`."
        PRD §3.5: "The submission still succeeds; the response simply shows the
        report in `FLAGGED`."

        50100 therms vs 40000 therms is a delta of 25.25 percent.

        Design: Corner/calculations/c_yoy_anomaly_exactly_at_threshold_no_flag
        """
        ctx = self._setup_two_year_scenario(current_therms=50100)
        set_clock("2028-05-15T00:00:00Z")

        submitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert submitted["status"] == "FLAGGED"

        flags, meta = validate_paginated(
            api.list_anomaly_flags(OFFICER, params={"report_id": ctx["report"]["id"]})
        )
        assert meta["total_count"] == 1
        assert flags[0]["anomaly_type"] == "CONSUMPTION_SPIKE"
        assert flags[0]["status"] == "OPEN"
