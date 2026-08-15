"""Regulatory survey audits: deterministic sampling, slot evaluation as of
window_end, the dual validity rates, pinned per-stratum projection rounding, vacuous
empty-sample rates, and the close gate (PRD §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    begin_fieldwork,
    book_shift,
    create_audit_run,
    create_requirement,
    create_unit,
    get_audit_run,
    issue_findings,
    list_run_findings,
    run_shift_to_completion,
    set_clock,
    setup_credentialed_nurse,
    setup_survey_nurse,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

CO1 = TEST_USERS["compliance_1"]


class TestDualValidityRates:
    """Difficulty instance: audit_validity_rate_point_in_time_vs_shift_incidence —
    POINT_IN_TIME scores slot validity as of window_end while SHIFT_INCIDENCE reads
    the was_clear_at_start stamps over completed shifts; identical data, different
    numbers, because the nurse's BLS expired after her shifts ran."""

    def _setup_evelyn_run_in_field_work(self):
        set_clock("2026-07-01T00:00:00Z")
        req = create_requirement(code="ANNUAL_SKILLS", name="Annual Skills",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        unit = create_unit(name="MED-SURG", required_cert_types=[])
        ctx = setup_credentialed_nurse(
            full_name="Evelyn Audit", email="evelyn.audit@x.com",
            hire_date="2026-06-01", bls_expires_on="2026-07-31",
            completed_on="2026-06-15", requirement=req,
        )
        nurse = ctx["nurse"]
        sh1 = book_shift(nurse["id"], unit["id"],
                         "2026-07-10T07:00:00Z", "2026-07-10T19:00:00Z")
        sh2 = book_shift(nurse["id"], unit["id"],
                         "2026-07-20T07:00:00Z", "2026-07-20T19:00:00Z")
        run_shift_to_completion(sh1["id"], "2026-07-10T07:30:00Z")
        run_shift_to_completion(sh2["id"], "2026-07-20T07:30:00Z")

        set_clock("2026-08-15T00:00:00Z")
        run = create_audit_run(window_start="2026-07-01", window_end="2026-08-15",
                               per_unit_sample_size=10)
        begin_fieldwork(run["id"])
        return ctx, run

    def test_point_in_time_rate_reflects_window_end_slots(self):
        """PRD §3.10: "The `point_in_time_rate` pools all sampled nurses: one hundred
        times the number of valid slots divided by the total number of slots across
        every sampled nurse, rounded half up to 2 decimals — and 100.0 when there are
        no slots at all."
        PRD §3.10: "The BLS slot is valid when she holds a `BLS` certification with
        `expires_on` on or after `window_end` that is not `REVOKED`."
        PRD §3.10: "Every deficient slot produces one `OPEN` audit finding — linked
        back through `audit_run_id` and `nurse_id` — with the matching `finding_type`
        of `LICENSE_NOT_CURRENT_IN_WINDOW`,
        `CERTIFICATION_NOT_CURRENT_IN_WINDOW`, or
        `COMPETENCY_NOT_CURRENT_IN_WINDOW`, and a `detail` naming the deficient slot,
        such as the certification type or the requirement code."

        Design: Difficulty/dual_variant_calc/audit_validity_rate_point_in_time_vs_shift_incidence
        """
        ctx, run = self._setup_evelyn_run_in_field_work()
        done = issue_findings(run["id"])
        # Slots as of window_end 2026-08-15: license (2027-06-30) valid, competency
        # (2027-06-15) valid, BLS (2026-07-31) deficient -> 2/3.
        assert done["point_in_time_rate"] == pytest.approx(66.67, abs=0.01)
        assert done["status"] == "FINDINGS_ISSUED"

        findings = list_run_findings(run["id"])
        assert len(findings) == 1
        assert findings[0]["finding_type"] == "CERTIFICATION_NOT_CURRENT_IN_WINDOW"
        assert findings[0]["nurse_id"] == ctx["nurse"]["id"]
        assert findings[0]["status"] == "OPEN"

    def test_shift_incidence_rate_reads_clear_at_start_stamps(self):
        """PRD §3.10: "The `shift_incidence_rate` looks instead at the sampled nurses'
        `COMPLETED` assignments whose start dates fall inside the window: one hundred
        times the number of those shifts stamped `was_clear_at_start`, divided by the
        total number of those shifts, rounded half up to 2 decimals — and 100.0,
        vacuous compliance, when no such shifts exist. A nurse whose BLS expired only
        after her shifts ran therefore scores below 100 on the first rate but not the
        second."

        Design: Difficulty/dual_variant_calc/audit_validity_rate_point_in_time_vs_shift_incidence
        """
        _ctx, run = self._setup_evelyn_run_in_field_work()
        done = issue_findings(run["id"])
        assert done["shift_incidence_rate"] == pytest.approx(100.0, abs=0.01), (
            "both completed shifts ran while she was CLEAR"
        )
        assert done["point_in_time_rate"] != done["shift_incidence_rate"], (
            "identical underlying data, different numbers per variant"
        )


class TestSurveyProjectionPerStratumRounding:
    """Difficulty instance: survey_projection_per_stratum_rounding — each stratum is
    rounded to 2 decimals BEFORE summation, then the sum is rounded to a whole number;
    the pinned ordering (2.5 + 1.5 -> 4) beats integer-first (3 + 2 = 5)."""

    def _setup_two_unit_run(self):
        set_clock("2026-07-01T00:00:00Z")
        req = create_requirement(code="ANNUAL_SKILLS", name="Annual Skills",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        unit_a = create_unit(name="UNIT-A", required_cert_types=[])
        unit_b = create_unit(name="UNIT-B", required_cert_types=[])
        # Unit A: 5 nurses; A1 is deficient (BLS expires 2026-07-20) with 2 shifts.
        # Phase 1: create every nurse and book every shift while the clock is still
        # 2026-07-01 — booking a 07-06 shift after the clock has moved past it would
        # be ERR_SHIFT_IN_PAST (PRD §3.6).
        a = {}
        for idx in range(1, 6):
            a[idx] = setup_survey_nurse(
                unit_a["id"], req["id"],
                bls_expires_on="2026-07-20" if idx == 1 else "2027-03-31",
                shift_dates=["2026-07-06", "2026-07-07"] if idx == 1 else ["2026-07-06"],
                full_name=f"Nurse A{idx}",
            )
        b = {}
        for idx in range(1, 4):
            b[idx] = setup_survey_nurse(
                unit_b["id"], req["id"],
                bls_expires_on="2026-07-20" if idx == 1 else "2027-03-31",
                shift_dates=["2026-07-06", "2026-07-07"] if idx == 1 else ["2026-07-06"],
                full_name=f"Nurse B{idx}",
            )
        # Phase 2: run each booked shift to completion; the clock moves into each
        # shift's own window (setting the clock mutates no entity, PRD §2.5).
        for group in (a, b):
            for ctx in group.values():
                for shift in ctx["shifts"]:
                    date = shift["starts_at"][:10]
                    run_shift_to_completion(shift["id"], f"{date}T07:30:00Z")

        set_clock("2026-08-01T00:00:00Z")
        run = create_audit_run(window_start="2026-07-01", window_end="2026-08-01",
                               per_unit_sample_size=2)
        begin_fieldwork(run["id"])
        return run, a, b

    def test_projection_rounds_strata_before_summing(self):
        """PRD §3.10: "...the stratum projection is the deficient count divided by the
        sampled count, multiplied by the candidate count, rounded half up to 2 decimals
        first; the run's projection is then the sum of those rounded strata, itself
        rounded half up to a whole number. This order is normative — rounding strata to
        integers before summing, or summing unrounded fractions, yields different
        numbers."
        PRD §3.10: "Candidates rank by their completed-shift count in that unit,
        descending, with ties broken by the nurse's own `created_at`, ascending. The
        first `per_unit_sample_size` candidates of each unit are taken."

        Design: Difficulty/combinatorial_formula/survey_projection_per_stratum_rounding
        """
        run, a, b = self._setup_two_unit_run()
        after_fieldwork = get_audit_run(run["id"])
        sample = after_fieldwork["sampled_nurse_ids"]
        assert len(sample) == 4, "2 per unit across 2 units"
        assert a[1]["nurse"]["id"] in sample, "A1 leads unit A (2 completed shifts)"
        assert b[1]["nurse"]["id"] in sample, "B1 leads unit B (2 completed shifts)"

        done = issue_findings(run["id"])
        # Unit A: d=1, s=2, P=5 -> round(2.5, 2) = 2.5; unit B: d=1, s=2, P=3 -> 1.5;
        # sum 4.0 -> integer round 4. (Integer-first would give 3 + 2 = 5.)
        assert done["projected_deficiency_count"] == pytest.approx(4, abs=0.01)

        findings = list_run_findings(run["id"])
        assert len(findings) == 2
        assert {f["finding_type"] for f in findings} == {
            "CERTIFICATION_NOT_CURRENT_IN_WINDOW"
        }
        assert {f["nurse_id"] for f in findings} == {
            a[1]["nurse"]["id"], b[1]["nurse"]["id"],
        }

    def test_companion_rates_over_the_sample(self):
        """PRD §3.10: "The `point_in_time_rate` pools all sampled nurses: one hundred
        times the number of valid slots divided by the total number of slots across
        every sampled nurse, rounded half up to 2 decimals — and 100.0 when there are
        no slots at all."
        PRD §3.10: "The `shift_incidence_rate` looks instead at the sampled nurses'
        `COMPLETED` assignments whose start dates fall inside the window: ... and
        100.0, vacuous compliance, when no such shifts exist."

        Design: Difficulty/combinatorial_formula/survey_projection_per_stratum_rounding
        """
        run, _a, _b = self._setup_two_unit_run()
        done = issue_findings(run["id"])
        # 4 sampled nurses x 3 slots (practice authority, BLS, annual competency);
        # A1 and B1 each lose only the BLS slot -> 10/12.
        assert done["point_in_time_rate"] == pytest.approx(83.33, abs=0.01)
        assert done["shift_incidence_rate"] == pytest.approx(100.0, abs=0.01), (
            "every completed shift in the window was started while CLEAR"
        )


class TestAuditEmptySample:
    def test_audit_empty_sample_vacuous_rates(self):
        """PRD §3.10: "...and 100.0 when there are no slots at all."
        PRD §3.10: "...and 100.0, vacuous compliance, when no such shifts exist."
        PRD §3.10: "Units with zero candidates contribute nothing, and when no unit
        has candidates the projection is 0."
        PRD §3.10: "Closing a run moves it from `FINDINGS_ISSUED` to `CLOSED` — any
        other state is `ERR_INVALID_AUDIT_STATE` — and requires every finding of the
        run resolved in some way: ..."

        Design: Corner/calculations/audit_empty_sample_vacuous_rates
        """
        set_clock()
        run = create_audit_run(window_start="2026-07-01", window_end="2026-08-01",
                               per_unit_sample_size=5)
        after_fieldwork = begin_fieldwork(run["id"])
        assert after_fieldwork["sampled_nurse_ids"] == []

        done = issue_findings(run["id"])
        assert done["point_in_time_rate"] == pytest.approx(100.0, abs=0.01)
        assert done["shift_incidence_rate"] == pytest.approx(100.0, abs=0.01)
        assert done["projected_deficiency_count"] == pytest.approx(0, abs=0.01)
        assert list_run_findings(run["id"]) == []

        closed = validate_success(api_client.close_audit_run(run["id"], CO1), 200)
        assert closed["status"] == "CLOSED", "no OPEN findings block the close"


class TestAuditCloseGate:
    def test_audit_close_blocked_until_findings_resolved(self):
        """PRD §3.10: "Closing a run moves it from `FINDINGS_ISSUED` to `CLOSED` — any
        other state is `ERR_INVALID_AUDIT_STATE` — and requires every finding of the
        run resolved in some way: a close attempted while any finding still stands
        `OPEN` is rejected with `ERR_AUDIT_FINDINGS_OPEN`. Findings themselves move
        from `OPEN` to the terminal states `REMEDIATED` or `ACCEPTED_RISK` through the
        remediate and accept-risk actions; a finding in any state other than `OPEN`
        rejects with `ERR_INVALID_FINDING_STATE`."

        Design: Corner/validations/audit_close_blocked_until_findings_resolved
        """
        set_clock("2026-07-05T00:00:00Z")
        req = create_requirement(code="ANNUAL_SKILLS", name="Annual Skills",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        unit = create_unit(name="MED", required_cert_types=[])
        ctx = setup_credentialed_nurse(
            full_name="Open Finding", email="open.finding@x.com",
            hire_date="2026-06-01", bls_expires_on="2026-07-20",
            completed_on="2026-06-15", requirement=req,
        )
        # The nurse is ACTIVE/CLEAR; her BLS stays valid through 2026-07-20.
        shift = book_shift(ctx["nurse"]["id"], unit["id"],
                           "2026-07-10T07:00:00Z", "2026-07-10T19:00:00Z")
        run_shift_to_completion(shift["id"], "2026-07-10T07:30:00Z")

        set_clock("2026-08-01T00:00:00Z")
        run = create_audit_run(window_start="2026-07-01", window_end="2026-08-01",
                               per_unit_sample_size=5)
        begin_fieldwork(run["id"])
        issue_findings(run["id"])
        findings = list_run_findings(run["id"])
        assert len(findings) == 1, "the BLS slot lapsed before window_end 2026-08-01"
        finding = findings[0]

        resp_close = api_client.close_audit_run(run["id"], CO1)
        validate_error(resp_close, ApiErrorId.ERR_AUDIT_FINDINGS_OPEN)

        remediated = validate_success(
            api_client.remediate_audit_finding(finding["id"], CO1), 200
        )
        assert remediated["status"] == "REMEDIATED"

        resp_twice = api_client.remediate_audit_finding(finding["id"], CO1)
        validate_error(resp_twice, ApiErrorId.ERR_INVALID_FINDING_STATE)

        closed = validate_success(api_client.close_audit_run(run["id"], CO1), 200)
        assert closed["status"] == "CLOSED"


class TestAuditCreationAndStateRules:
    def test_audit_window_invalid_rejected(self):
        """PRD §3.10: "The window is inclusive at both ends; `window_start` must be
        strictly before `window_end`, and `window_end` must not lie after the current
        date — violations are `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/audit_window_invalid_rejected
        """
        set_clock()
        resp_inverted = api_client.create_audit_run(
            {"window_start": "2026-08-10", "window_end": "2026-08-01",
             "per_unit_sample_size": 5},
            CO1,
        )
        validate_error(resp_inverted, ApiErrorId.ERR_INVALID_DATE_RANGE)
        resp_future = api_client.create_audit_run(
            {"window_start": "2026-07-01", "window_end": "2026-08-02",
             "per_unit_sample_size": 5},
            CO1,
        )
        validate_error(resp_future, ApiErrorId.ERR_INVALID_DATE_RANGE)
        _data, meta = validate_paginated(api_client.list_audit_runs(CO1))
        assert meta["total_count"] == 0

    def test_audit_issue_findings_from_initiated_rejected(self):
        """PRD §3.10: "Issuing findings moves the run from `FIELD_WORK` to
        `FINDINGS_ISSUED` — again, any other state is `ERR_INVALID_AUDIT_STATE` — and
        evaluates each sampled nurse's credential slots as of `window_end`, purely from
        dates, regardless of sweep-driven statuses."
        PRD §3.10: "Two rates and a projection are computed and stored at this point;
        all three stay null until issue-findings."

        Design: Corner/state_machines/audit_issue_findings_from_initiated_rejected
        """
        set_clock()
        run = create_audit_run(window_start="2026-07-01", window_end="2026-08-01",
                               per_unit_sample_size=5)
        resp = api_client.issue_audit_findings(run["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE)
        after = get_audit_run(run["id"])
        assert after["status"] == "INITIATED"
        assert after["point_in_time_rate"] is None
        assert after["shift_incidence_rate"] is None
        assert after["projected_deficiency_count"] is None
