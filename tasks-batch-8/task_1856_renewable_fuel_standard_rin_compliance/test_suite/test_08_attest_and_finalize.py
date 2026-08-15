"""Attest engagements: remediation loop, close guards, windows, finalize (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_account_and_year,
    create_engagement,
    create_report,
    create_year,
    decide_report,
    get_success_data,
    make_auditor_headers,
    make_compliance_manager_headers,
    submit_report,
    validate_error,
    validate_success,
    api_client,
)


class TestAttestRemediationLoop:
    def _setup_in_remediation(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        eng = create_engagement(yr["id"], auditor_user_id="aud-1")
        aud = make_auditor_headers("aud-1")
        get_success_data(api.begin_fieldwork(eng["id"], aud))
        get_success_data(api.issue_findings(eng["id"], {"findings": "ADVERSE"}, aud))
        get_success_data(api.remediate_engagement(eng["id"], CM))
        return eng

    def test_remediation_loops_back_to_fieldwork(self, api):
        """PRD §3.6: "Remediation loops back into examination: the auditor begins fieldwork again, moving `REMEDIATION` → `FIELDWORK`."

        Design: Difficulty/non_linear_state_machine/attest_engagement_remediation_loop
        """
        eng = self._setup_in_remediation(api, "EPA-ACME-6")
        data = get_success_data(
            api.begin_fieldwork(eng["id"], make_auditor_headers("aud-1")),
        )
        assert data["status"] == "FIELDWORK"

    def test_second_clean_findings_close_engagement(self, api):
        """PRD §3.6: "Clean findings close the engagement: the auditor moves `FINDINGS_ISSUED` → `CLOSED_CLEAN`, admissible only when `findings` stands `CLEAN`"
        PRD §3.6: "Issuing findings — a `findings` value of `CLEAN` or `ADVERSE`, any other value rejected with `ERR_INVALID_REQUEST` — moves `FIELDWORK` → `FINDINGS_ISSUED`."

        Design: Difficulty/non_linear_state_machine/attest_engagement_remediation_loop
        """
        eng = self._setup_in_remediation(api, "EPA-ACME-6B")
        aud = make_auditor_headers("aud-1")
        get_success_data(api.begin_fieldwork(eng["id"], aud))
        get_success_data(api.issue_findings(eng["id"], {"findings": "CLEAN"}, aud))
        data = get_success_data(api.close_engagement(eng["id"], aud))
        assert data["status"] == "CLOSED_CLEAN"
        assert data["findings"] == "CLEAN"


class TestAttestCloseGuards:
    def _setup_adverse(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        eng = create_engagement(yr["id"], auditor_user_id="aud-1")
        aud = make_auditor_headers("aud-1")
        get_success_data(api.begin_fieldwork(eng["id"], aud))
        get_success_data(api.issue_findings(eng["id"], {"findings": "ADVERSE"}, aud))
        return eng

    def test_close_on_adverse_findings_rejected(self, api):
        """PRD §3.6: "attempting to close on adverse findings is `ERR_INVALID_STATE`, since remediation must come first."

        Design: Corner/state_machines/attest_close_with_adverse_findings_rejected
        """
        eng = self._setup_adverse(api, "EPA-SM-6")
        resp = api.close_engagement(eng["id"], make_auditor_headers("aud-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_attest_engagement(eng["id"], CM))
        assert after["status"] == "FINDINGS_ISSUED"


class TestFieldworkWindowsHalfOpen:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        yr_a = create_year(acct["id"], year=2026)
        yr_b = create_year(acct["id"], year=2027)
        eng1 = create_engagement(
            yr_a["id"], auditor_user_id="aud-1",
            fieldwork_start="2026-09-01T00:00:00Z",
            fieldwork_end="2026-10-01T00:00:00Z",
        )
        return yr_b, eng1

    def test_touching_window_allowed(self, api):
        """PRD §3.6: "One auditor may not hold overlapping fieldwork windows: a new engagement whose half-open window overlaps another engagement for the same `auditor_user_id` that has not reached `CLOSED_CLEAN` is rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP`, while windows that merely touch — one ending exactly as the next begins — are allowed."

        Design: Difficulty/resource_temporal_overlap/attest_fieldwork_windows_half_open
        """
        yr_b, _eng1 = self._setup(api, "EPA-ACME-15")
        eng2 = create_engagement(
            yr_b["id"], auditor_user_id="aud-1",
            fieldwork_start="2026-10-01T00:00:00Z",
            fieldwork_end="2026-11-01T00:00:00Z",
        )
        assert eng2["status"] == "ENGAGED"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.6: "a new engagement whose half-open window overlaps another engagement for the same `auditor_user_id` that has not reached `CLOSED_CLEAN` is rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/attest_fieldwork_windows_half_open
        """
        yr_b, _eng1 = self._setup(api, "EPA-ACME-15B")
        payload = {
            "obligation_year_id": yr_b["id"],
            "auditor_user_id": "aud-1",
            "fieldwork_start": "2026-09-15T00:00:00Z",
            "fieldwork_end": "2026-10-15T00:00:00Z",
        }
        resp = api.create_attest_engagement(payload, CM)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)


class TestAnnualReportGatedByAttest:
    def _setup(self, api, epa_id):
        """Engagement in FIELDWORK; ANNUAL draft exists."""
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        eng = create_engagement(yr["id"], auditor_user_id="aud-1")
        get_success_data(
            api.begin_fieldwork(eng["id"], make_auditor_headers("aud-1")),
        )
        rep = create_report(yr["id"], report_type="ANNUAL",
                            headers=make_compliance_manager_headers("cm-1"))
        return eng, rep

    def test_annual_submit_rejected_until_attest_clean(self, api):
        """PRD §3.6: "an `ANNUAL` report may be submitted only while an attest engagement for the year stands `CLOSED_CLEAN`, otherwise submission is rejected with `ERR_ATTEST_NOT_CLEAN`"

        Design: Difficulty/cross_entity_state_dependency/annual_report_gated_by_attest_engagement
        """
        _eng, rep = self._setup(api, "EPA-ACME-14")
        resp = api.submit_compliance_report(
            rep["id"], make_compliance_manager_headers("cm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_ATTEST_NOT_CLEAN)

    def test_annual_submit_succeeds_after_attest_closed_clean(self, api):
        """PRD §3.6: "A `CLOSED_CLEAN` engagement is what unlocks submission of the year's annual report."

        Design: Difficulty/cross_entity_state_dependency/annual_report_gated_by_attest_engagement
        """
        eng, rep = self._setup(api, "EPA-ACME-14B")
        resp = api.submit_compliance_report(
            rep["id"], make_compliance_manager_headers("cm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_ATTEST_NOT_CLEAN)
        aud = make_auditor_headers("aud-1")
        get_success_data(api.issue_findings(eng["id"], {"findings": "CLEAN"}, aud))
        get_success_data(api.close_engagement(eng["id"], aud))
        data = get_success_data(
            api.submit_compliance_report(
                rep["id"], make_compliance_manager_headers("cm-1"),
            ),
        )
        assert data["status"] == "SUBMITTED"
        # Default clock 2026-08-01 is before the annual due 2027-03-31T23:59:59Z.
        assert data["is_late"] is False


class TestFinalizePreconditions:
    def test_finalize_without_annual_report_and_attest_rejected(self, api):
        """PRD §3.6: "From `VOLUME_CLOSED`, a `ComplianceManager` finalizes the year only when an `ANNUAL` report for the year stands `ACCEPTED` and an attest engagement for the year stands `CLOSED_CLEAN`; if either is missing the attempt is rejected with `ERR_YEAR_NOT_FINALIZABLE`."

        Design: Corner/state_machines/year_finalize_requires_report_and_attest
        """
        _acct, yr = create_account_and_year(epa_registration_id="EPA-SM-7")
        get_success_data(api.close_volume(yr["id"], {"actual_volume_gal": 1000}, CM))
        resp = api.finalize_year(yr["id"], CM)
        validate_error(resp, ApiErrorId.ERR_YEAR_NOT_FINALIZABLE)
        after = validate_success(api.get_obligation_year(yr["id"], CM))
        assert after["status"] == "VOLUME_CLOSED"
