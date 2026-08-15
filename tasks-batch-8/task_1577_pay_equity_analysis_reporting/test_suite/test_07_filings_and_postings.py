"""Jurisdiction rules, report filings, and transparency postings (PRD §2.3, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    band_rows_as_set,
    create_filing,
    create_filing_payload,
    create_jurisdiction,
    create_jurisdiction_rule_payload,
    create_posting,
    create_posting_payload,
    create_study,
    is_valid_uuid,
    member_spec,
    setup_privileged_final_study,
    sweep_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_REPORTER = TEST_USERS["compliance_reporter_headers"]


def _reporter():
    return _REPORTER

class TestJurisdictionRules:
    def test_jurisdiction_duplicate_code_rejected(
        self, api, people_ops_admin_headers
    ):
        """PRD §3.5: "A `PeopleOpsAdmin` registers jurisdiction rules, each keyed by a `jurisdiction_code` that must be unique (a repeat is rejected with `ERR_DUPLICATE_JURISDICTION`)."

        Design: Corner/entities/jurisdiction_duplicate_code_rejected
        """
        validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(
                    jurisdiction_code="CA",
                    range_disclosure_required=True,
                    max_range_spread_pct=50,
                    min_posting_duration_days=30,
                ),
                people_ops_admin_headers,
            ),
            201,
        )
        res = api.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(
                jurisdiction_code="CA", range_disclosure_required=False
            ),
            people_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_JURISDICTION)

    def test_jurisdiction_create_id_input_ignored(
        self, api, people_ops_admin_headers
    ):
        """PRD §2.5: "**`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix."
        PRD §2.4: "Before any client call sets it, the logical clock reads exactly 2026-08-01T00:00:00Z as a fixed startup default; the server never falls back to the host's wall clock."
        PRD §2.4: "Timestamps stamped by the system — such as when a run is finalized, a filing is submitted, or a posting is published or closed — always read from this logical clock."

        Design: Corner/entities/jurisdiction_create_id_input_ignored
        """
        client_id = "11111111-2222-4333-8444-555555555555"
        rule = validate_success(
            api.create_jurisdiction_rule(
                {"id": client_id, "jurisdiction_code": "CO"},
                people_ops_admin_headers,
            ),
            201,
        )
        # The server mints its own identifier.
        assert rule["id"] != client_id
        assert is_valid_uuid(rule["id"])
        # created_at reads from the logical clock at its startup default.
        assert rule["created_at"].startswith("2026-08-01T00:00:00")

    def test_jurisdiction_list_pagination(self, api, people_ops_admin_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order."

        Design: Corner/entities/jurisdiction_list_pagination
        """
        for code in ("CA", "CO", "NYC"):
            create_jurisdiction(code)
        page1, meta1 = validate_paginated(
            api.list_jurisdiction_rules(people_ops_admin_headers, {"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_jurisdiction_rules(people_ops_admin_headers, {"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        # Creation-ascending order puts NYC (created last) on the final page.
        assert page2[0]["jurisdiction_code"] == "NYC"
        assert meta2["has_more"] is False


class TestReportFilings:
    def test_filing_lifecycle_terminal_lockdown_and_reopen_recompile(self, api):
        """PRD §3.5: "A new filing begins in `COMPILING` with `band_rows`, `total_headcount`, `submitted_at`, and `late_submission` all null."
        PRD §3.5: "Compilation moves the filing from `COMPILING` to `INTERNAL_REVIEW` (from any other state, `ERR_FILING_INVALID_STATE`) and computes the workforce band table."
        PRD §3.5: "A rejected filing is not the end: reopening it returns it from `REJECTED` to `COMPILING` (otherwise `ERR_FILING_INVALID_STATE`) and clears `band_rows`, `total_headcount`, `submitted_at`, and `late_submission` back to null so the resubmission loop can begin with a fresh compile."
        PRD §3.5: "The regulator's outcome is then recorded against a `SUBMITTED` filing (otherwise `ERR_FILING_INVALID_STATE`) by supplying a `decision`: a `decision` of `ACCEPTED` moves the filing to the terminal `ACCEPTED` status, while a `decision` of `REJECTED` moves it to `REJECTED`; optional `notes` may accompany the recorded decision."

        Design: Corner/state_machines/filing_lifecycle_terminal_lockdown_and_reopen_recompile
        """
        ctx = setup_privileged_final_study(
            name="FL", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
            member_specs=[
                member_spec("FLM1", "MALE", 10000000),
                member_spec("FLF1", "FEMALE", 9000000),
            ],
            group_name="GFL", min_group_size=2,
        )
        filing = create_filing(
            ctx["study"]["id"], report_type="EEO_WORKFORCE_COMP",
            reporting_year=2025, due_date="2026-12-31",
        )
        assert filing["status"] == "COMPILING"
        assert filing["band_rows"] is None
        assert filing["total_headcount"] is None

        compiled = validate_success(api.compile_filing(filing["id"], _reporter()))
        assert compiled["status"] == "INTERNAL_REVIEW"
        # MALE 10000000 -> BAND_D, FEMALE 9000000 -> BAND_C.
        assert band_rows_as_set(compiled["band_rows"]) == {
            ("BAND_D", "MALE", 1),
            ("BAND_C", "FEMALE", 1),
        }
        assert compiled["total_headcount"] == 2
        rows_first = band_rows_as_set(compiled["band_rows"])

        submitted = validate_success(api.submit_filing(filing["id"], _reporter()))
        assert submitted["status"] == "SUBMITTED"
        # The 2026-08-01 default clock is before the 2026-12-31 due date.
        assert submitted["late_submission"] is False

        rejected = validate_success(
            api.record_filing_decision(
                filing["id"],
                {"decision": "REJECTED", "notes": "Resubmit with corrections"},
                _reporter(),
            )
        )
        assert rejected["status"] == "REJECTED"

        reopened = validate_success(api.reopen_filing(filing["id"], _reporter()))
        assert reopened["status"] == "COMPILING"
        # The resubmission loop begins with a fresh compile: computed fields cleared.
        assert reopened["band_rows"] is None
        assert reopened["total_headcount"] is None
        assert reopened["submitted_at"] is None
        assert reopened["late_submission"] is None

        recompiled = validate_success(api.compile_filing(filing["id"], _reporter()))
        # Recompiling the unchanged population reproduces the identical band table.
        assert band_rows_as_set(recompiled["band_rows"]) == rows_first
        assert recompiled["total_headcount"] == 2

        validate_success(api.submit_filing(filing["id"], _reporter()))
        accepted = validate_success(
            api.record_filing_decision(filing["id"], {"decision": "ACCEPTED"}, _reporter())
        )
        assert accepted["status"] == "ACCEPTED"
        # ACCEPTED is terminal: a second record-decision fails on state.
        res = api.record_filing_decision(filing["id"], {"decision": "ACCEPTED"}, _reporter())
        validate_error(res, ApiErrorId.ERR_FILING_INVALID_STATE)

    def test_eeo_band_edge_lower_inclusive(self, api):
        """PRD §3.5: "Every employee snapshot of the filing's study is placed into exactly one band by its `annualized_base_cents`, using lower-inclusive, upper-exclusive edges: `BAND_A` covers zero up to but not including 5,000,000 cents; `BAND_B` covers 5,000,000 up to but not including 7,500,000 cents; `BAND_C` covers 7,500,000 up to but not including 10,000,000 cents; `BAND_D` covers 10,000,000 up to but not including 15,000,000 cents; and `BAND_E` covers 15,000,000 cents and above. An employee at exactly 5,000,000 cents therefore falls in `BAND_B`."
        PRD §3.5: "Compilation is conservative in the accounting sense: because every snapshot lands in exactly one band with no rounding, `total_headcount` must equal the study's `snapshot_count` at compile time."

        Design: Corner/calculations/eeo_band_edge_lower_inclusive
        """
        ctx = setup_privileged_final_study(
            name="BE", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
            member_specs=[
                member_spec("BEM1", "MALE", 5000000),
                member_spec("BEF1", "FEMALE", 4999999),
            ],
            group_name="GBE", min_group_size=2,
        )
        filing = create_filing(
            ctx["study"]["id"], report_type="EEO_WORKFORCE_COMP",
            reporting_year=2025, due_date="2026-12-31",
        )
        compiled = validate_success(api.compile_filing(filing["id"], _reporter()))
        rows = band_rows_as_set(compiled["band_rows"])
        # 5000000 is the lower-inclusive edge of BAND_B; 4999999 stays in BAND_A.
        assert ("BAND_B", "MALE", 1) in rows
        assert ("BAND_A", "FEMALE", 1) in rows
        # Conservation: every snapshot lands in exactly one band.
        assert compiled["total_headcount"] == 2

    def test_filing_late_submission_flag_boundary(self, api, people_ops_admin_headers):
        """PRD §3.5: "Submitting the filing — again by a `ComplianceReporter` — moves it from `INTERNAL_REVIEW` to `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`), stamps `submitted_at` from the logical clock, and derives `late_submission`: the filing is late only when the clock's UTC calendar date falls strictly after the `due_date`, so a submission exactly on the due date is not late."
        PRD §3.5: "Filings are unique per study, report type, and reporting year: a duplicate combination is rejected with `ERR_DUPLICATE_FILING`."
        PRD §3.5: "a filing against a study still in `DRAFT`, `MODELING`, or `UNDER_LEGAL_REVIEW` is rejected with `ERR_STUDY_NOT_REPORTABLE`."

        Design: Corner/validations/filing_late_submission_flag_boundary
        """
        ctx = setup_privileged_final_study(
            name="LF", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
            member_specs=[
                member_spec("LFM1", "MALE", 10000000),
                member_spec("LFF1", "FEMALE", 9000000),
            ],
            group_name="GLF", min_group_size=2,
        )
        draft_study = create_study(
            name="LATE2", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31",
        )
        jurisdiction = create_jurisdiction(
            "JRL", pay_data_report_required=True,
            filing_due_month=5, filing_due_day=31,
        )
        f_eeo = create_filing(
            ctx["study"]["id"], report_type="EEO_WORKFORCE_COMP",
            reporting_year=2025, due_date="2026-05-31",
        )
        f_state = create_filing(
            ctx["study"]["id"], report_type="STATE_PAY_DATA",
            reporting_year=2025, due_date="2026-05-31",
            jurisdiction_rule_id=jurisdiction["id"],
        )
        validate_success(api.compile_filing(f_eeo["id"], _reporter()))
        validate_success(api.compile_filing(f_state["id"], _reporter()))

        # The (study, report_type, reporting_year) triple is unique.
        res_dup = api.create_filing(
            create_filing_payload(
                ctx["study"]["id"], report_type="EEO_WORKFORCE_COMP",
                reporting_year=2025, due_date="2026-05-31",
            ),
            _reporter(),
        )
        validate_error(res_dup, ApiErrorId.ERR_DUPLICATE_FILING)
        # A DRAFT study is not reportable.
        res_draft = api.create_filing(
            create_filing_payload(
                draft_study["id"], report_type="EEO_WORKFORCE_COMP",
                reporting_year=2024, due_date="2026-05-31",
            ),
            _reporter(),
        )
        validate_error(res_draft, ApiErrorId.ERR_STUDY_NOT_REPORTABLE)

        # Submission exactly on the due date is NOT late.
        sweep_clock("2026-05-31T00:00:00Z")
        on_time = validate_success(api.submit_filing(f_eeo["id"], _reporter()))
        assert on_time["late_submission"] is False
        # One day later IS late.
        sweep_clock("2026-06-01T00:00:00Z")
        late = validate_success(api.submit_filing(f_state["id"], _reporter()))
        assert late["late_submission"] is True


class TestTransparencyPostings:
    def test_posting_duplicate_ref_rejected(self, api, compliance_reporter_headers):
        """PRD §3.5: "A `ComplianceReporter` creates a posting in `DRAFT` under a jurisdiction rule, supplying the `jurisdiction_rule_id`, a `job_posting_ref` that must be unique across the system (a repeat is rejected with `ERR_DUPLICATE_POSTING_REF`), a `title`, and optionally the `min_salary_cents` and `max_salary_cents` range bounds, which are nullable until provided."

        Design: Corner/entities/posting_duplicate_ref_rejected
        """
        jurisdiction = create_jurisdiction("WA")
        create_posting(
            jurisdiction["id"], job_posting_ref="POST-1",
            title="Engineer", min_salary_cents=10000000, max_salary_cents=12000000,
        )
        res = api.create_posting(
            create_posting_payload(
                jurisdiction["id"], job_posting_ref="POST-1", title="Other",
                min_salary_cents=9000000, max_salary_cents=9900000,
            ),
            compliance_reporter_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_POSTING_REF)

    def test_posting_publish_validation_ladder(self, api):
        """PRD §3.5: "Publishing enforces the jurisdiction's disclosure regime, with the checks applied in order. First, if the posting is not in `DRAFT` the publish is rejected with `ERR_POSTING_INVALID_STATE`. Second — the safety check of §2.8 — when the jurisdiction's `range_disclosure_required` is true, both `min_salary_cents` and `max_salary_cents` must be present, otherwise the publish is rejected with `ERR_RANGE_DISCLOSURE_REQUIRED`. Third, when both bounds are present, the ceiling must be no lower than the floor, otherwise `ERR_INVALID_SALARY_RANGE`. Fourth, when the jurisdiction's `max_range_spread_pct` is non-null and both bounds are present, the range spread — the ceiling minus the floor, divided by the floor, expressed as a percentage — must not exceed the cap, otherwise `ERR_RANGE_SPREAD_EXCEEDED`."

        Design: Corner/validations/posting_publish_validation_ladder
        """
        jrd = create_jurisdiction("JRD", range_disclosure_required=True)
        jrs = create_jurisdiction("JRS", max_range_spread_pct=50)
        jrn = create_jurisdiction("JRN")

        p_disc = create_posting(
            jrd["id"], job_posting_ref="P-DISC", title="Analyst",
            min_salary_cents=10000000,
        )
        p_sprd = create_posting(
            jrs["id"], job_posting_ref="P-SPRD", title="Analyst",
            min_salary_cents=10000000, max_salary_cents=16000000,
        )
        p_invr = create_posting(
            jrn["id"], job_posting_ref="P-INVR", title="Analyst",
            min_salary_cents=10000000, max_salary_cents=9000000,
        )
        p_norange = create_posting(
            jrn["id"], job_posting_ref="P-NORANGE", title="Analyst",
        )

        # Disclosure-required jurisdiction, max missing.
        res1 = api.publish_posting(p_disc["id"], _reporter())
        validate_error(res1, ApiErrorId.ERR_RANGE_DISCLOSURE_REQUIRED)
        # (16000000 - 10000000) / 10000000 * 100 == 60 > cap 50.
        res2 = api.publish_posting(p_sprd["id"], _reporter())
        validate_error(res2, ApiErrorId.ERR_RANGE_SPREAD_EXCEEDED)
        # Ceiling below the floor.
        res3 = api.publish_posting(p_invr["id"], _reporter())
        validate_error(res3, ApiErrorId.ERR_INVALID_SALARY_RANGE)
        # No range needed when the jurisdiction does not require disclosure.
        ok = validate_success(api.publish_posting(p_norange["id"], _reporter()))
        assert ok["status"] == "PUBLISHED"
        # published_at stamps from the logical clock (startup default).
        assert ok["published_at"].startswith("2026-08-01T00:00:00")

    def test_posting_close_min_duration_boundary(self, api):
        """PRD §3.5: "A posting in `PUBLISHED` (otherwise `ERR_POSTING_INVALID_STATE`) may close once the clock's UTC calendar date is at least the date of `published_at` plus the jurisdiction's `min_posting_duration_days`; the boundary is inclusive, so closing exactly when the duration has elapsed is permitted, and an earlier close is rejected with `ERR_MIN_POSTING_DURATION_NOT_MET`."

        Design: Corner/validations/posting_close_min_duration_boundary
        """
        jurisdiction = create_jurisdiction(
            "JRD30", range_disclosure_required=True, min_posting_duration_days=30,
        )
        p30 = create_posting(
            jurisdiction["id"], job_posting_ref="P-30", title="Engineer",
            min_salary_cents=10000000, max_salary_cents=12000000,
        )
        p_draft = create_posting(
            jurisdiction["id"], job_posting_ref="P-DRAFT", title="Engineer",
            min_salary_cents=10000000, max_salary_cents=12000000,
        )
        # A DRAFT posting cannot close.
        res0 = api.close_posting(p_draft["id"], _reporter())
        validate_error(res0, ApiErrorId.ERR_POSTING_INVALID_STATE)

        published = validate_success(api.publish_posting(p30["id"], _reporter()))
        assert published["published_at"].startswith("2026-08-01T00:00:00")
        # Day 29: 2026-08-30 < 2026-08-01 + 30 days -> too early.
        sweep_clock("2026-08-30T00:00:00Z")
        res1 = api.close_posting(p30["id"], _reporter())
        validate_error(res1, ApiErrorId.ERR_MIN_POSTING_DURATION_NOT_MET)
        # Exactly day 30 (2026-08-31): the inclusive boundary permits closing.
        sweep_clock("2026-08-31T00:00:00Z")
        closed = validate_success(api.close_posting(p30["id"], _reporter()))
        assert closed["status"] == "CLOSED"
