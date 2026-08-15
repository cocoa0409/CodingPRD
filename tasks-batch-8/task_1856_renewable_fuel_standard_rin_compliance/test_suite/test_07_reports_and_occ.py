"""Compliance reports: cycles, OCC, supersede, lateness, segregation (PRD §2.7, §3.6)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_account_and_year,
    create_engagement,
    create_report,
    decide_report,
    drive_engagement_to_closed_clean,
    get_success_data,
    get_year_version,
    make_compliance_manager_headers,
    set_clock,
    submit_report,
    validate_error,
    validate_success,
    api_client,
)


class TestReportRevisionAndAmendmentCycles:
    def _setup(self, api, epa_id):
        """QUARTERLY report driven: submit -> REJECT -> reopen -> submit -> ACCEPT."""
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        rep = create_report(yr["id"], report_type="QUARTERLY",
                            quarter_end_date="2026-06-30T00:00:00Z")
        submit_report(rep["id"])
        decide_report(rep["id"], "REJECT")
        get_success_data(api.reopen_compliance_report(rep["id"], CM))
        submit_report(rep["id"])
        decide_report(rep["id"], "ACCEPT")
        return rep

    def test_accepted_report_reopen_returns_to_draft(self, api):
        """PRD §3.6: "and an accepted report may be voluntarily amended the same way — reopening an `ACCEPTED` report returns it to `DRAFT`, clears `submitted_at` and `is_late`, and additionally resets `amendment_required` to false."

        Design: Difficulty/non_linear_state_machine/compliance_report_revision_and_amendment_cycles
        """
        rep = self._setup(api, "EPA-ACME-5")
        data = get_success_data(api.reopen_compliance_report(rep["id"], CM))
        assert data["status"] == "DRAFT"

    def test_reopen_resets_submission_fields(self, api):
        """PRD §3.6: "reopening an `ACCEPTED` report returns it to `DRAFT`, clears `submitted_at` and `is_late`, and additionally resets `amendment_required` to false."

        Design: Difficulty/non_linear_state_machine/compliance_report_revision_and_amendment_cycles
        """
        rep = self._setup(api, "EPA-ACME-5B")
        get_success_data(api.reopen_compliance_report(rep["id"], CM))
        after = validate_success(api.get_compliance_report(rep["id"], CM))
        assert after["submitted_at"] is None
        assert after["is_late"] is False
        assert after["amendment_required"] is False


class TestReportTerminalSuperseded:
    def _setup(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        r1 = create_report(yr["id"], report_type="QUARTERLY",
                           quarter_end_date="2026-06-30T00:00:00Z")
        r2 = create_report(yr["id"], report_type="QUARTERLY",
                           quarter_end_date="2026-06-30T00:00:00Z")
        return r1, r2

    def test_superseded_draft_cannot_be_submitted(self, api):
        """PRD §3.6: "Creation enforces one live draft per type for the year: a prior `DRAFT` report of the same `report_type` moves to `SUPERSEDED`, while a same-type report standing `SUBMITTED`, `ACCEPTED`, or `REJECTED` blocks creation outright with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/report_terminal_superseded_lockdown
        """
        r1, _r2 = self._setup(api, "EPA-SM-5")
        r1_after = validate_success(api.get_compliance_report(r1["id"], CM))
        assert r1_after["status"] == "SUPERSEDED"
        resp = api.submit_compliance_report(r1["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_superseding_report_remains_live_draft(self, api):
        """PRD §3.6: "The new report stands `DRAFT`"

        Design: Corner/state_machines/report_terminal_superseded_lockdown
        """
        _r1, r2 = self._setup(api, "EPA-SM-5B")
        r2_after = validate_success(api.get_compliance_report(r2["id"], CM))
        assert r2_after["status"] == "DRAFT"


class TestReportCreateSupersede:
    def _setup(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        r1 = create_report(yr["id"], report_type="QUARTERLY",
                           quarter_end_date="2026-06-30T00:00:00Z")
        r2 = create_report(yr["id"], report_type="QUARTERLY",
                           quarter_end_date="2026-06-30T00:00:00Z")
        submit_report(r2["id"])
        return yr, r1, r2

    def test_second_create_supersedes_prior_draft(self, api):
        """PRD §3.6: "a prior `DRAFT` report of the same `report_type` moves to `SUPERSEDED`"

        Design: Corner/endpoints/report_create_supersedes_prior_draft
        """
        _yr, r1, r2 = self._setup(api, "EPA-EP-1")
        r1_after = validate_success(api.get_compliance_report(r1["id"], CM))
        r2_after = validate_success(api.get_compliance_report(r2["id"], CM))
        assert r1_after["status"] == "SUPERSEDED"
        assert r2_after["status"] == "SUBMITTED"

    def test_same_type_non_draft_blocks_creation(self, api):
        """PRD §3.6: "while a same-type report standing `SUBMITTED`, `ACCEPTED`, or `REJECTED` blocks creation outright with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/report_create_supersedes_prior_draft
        """
        yr, _r1, _r2 = self._setup(api, "EPA-EP-1B")
        payload = {
            "obligation_year_id": yr["id"],
            "report_type": "QUARTERLY",
            "quarter_end_date": "2026-06-30T00:00:00Z",
            "expected_obligation_year_version": get_year_version(yr["id"]),
        }
        resp = api.create_compliance_report(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestStaleYearVersionOcc:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        yr_v1 = None
        payload = {
            "account_id": acct["id"],
            "year": 2026,
            "projected_volume_gal": 1000,
            "std_cellulosic_pct": 10.0,
            "std_biomass_diesel_pct": 20.0,
            "std_advanced_pct": 30.0,
            "std_total_pct": 40.0,
        }
        yr = get_success_data(api.create_obligation_year(payload, CM))
        yr_v1 = yr["version"]
        # First create bumps the year's version 1 -> 2.
        create_report(yr["id"], report_type="QUARTERLY",
                      quarter_end_date="2026-06-30T00:00:00Z",
                      expected_obligation_year_version=yr_v1)
        return yr, yr_v1

    def test_stale_expected_version_rejected(self, api):
        """PRD §2.7: "If the year's current `version` no longer matches that value — for instance because another writer has since created a report for the same year, an action that legitimately supersedes the prior same-type draft and advances the year's version — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/validations/stale_year_version_occ_conflict
        """
        yr, yr_v1 = self._setup(api, "EPA-VAL-1")
        payload = {
            "obligation_year_id": yr["id"],
            "report_type": "ANNUAL",
            "expected_obligation_year_version": yr_v1,
        }
        resp = api.create_compliance_report(payload, CM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_rejection_creates_no_report(self, api):
        """PRD §2.7: "Creating a compliance report is the single operation guarded by optimistic concurrency control. The creation request must carry `expected_obligation_year_version`, holding the version of the obligation year the client last observed."

        Design: Corner/validations/stale_year_version_occ_conflict
        """
        yr, yr_v1 = self._setup(api, "EPA-VAL-1B")
        before = validate_success(
            api.list_compliance_reports(CM, params={"obligation_year_id": yr["id"]}),
        )
        payload = {
            "obligation_year_id": yr["id"],
            "report_type": "ANNUAL",
            "expected_obligation_year_version": yr_v1,
        }
        validate_error(
            api.create_compliance_report(payload, CM),
            ApiErrorId.ERR_STALE_VERSION,
        )
        after = validate_success(
            api.list_compliance_reports(CM, params={"obligation_year_id": yr["id"]}),
        )
        assert len(after) == len(before)


class TestAnnualQuarterEndDateForbidden:
    def test_annual_report_with_quarter_end_date_rejected(self, api):
        """PRD §3.6: "A quarterly report must supply `quarter_end_date`, the last day of the reported quarter, while an annual report must not — omitting it on a quarterly report or supplying it on an annual one is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/annual_quarter_end_date_forbidden
        """
        _acct, yr = create_account_and_year(epa_registration_id="EPA-VAL-5")
        payload = {
            "obligation_year_id": yr["id"],
            "report_type": "ANNUAL",
            "quarter_end_date": "2026-06-30T00:00:00Z",
            "expected_obligation_year_version": get_year_version(yr["id"]),
        }
        resp = api.create_compliance_report(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLateQuarterlyReport:
    def _setup(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        rep = create_report(yr["id"], report_type="QUARTERLY",
                            quarter_end_date="2026-06-30T00:00:00Z")
        set_clock("2026-08-30T00:00:00Z")
        return rep

    def test_submit_after_due_date_sets_is_late(self, api):
        """PRD §3.6: "A successful submission stamps `submitted_at` from the logical clock and computes `is_late`, which is true exactly when the submission instant falls after the report's `due_date`."
        PRD §2.10: "An annual report's `due_date` falls at that same instant, while a quarterly report's `due_date` falls sixty days after its `quarter_end_date`."

        Design: Corner/endpoints/late_quarterly_report_flagged
        """
        rep = self._setup(api, "EPA-EP-2")
        data = get_success_data(api.submit_compliance_report(rep["id"], CM))
        assert data["status"] == "SUBMITTED"
        assert data["is_late"] is True

    def test_due_date_is_quarter_end_plus_sixty_days(self, api):
        """PRD §2.10: "while a quarterly report's `due_date` falls sixty days after its `quarter_end_date`."

        Design: Corner/endpoints/late_quarterly_report_flagged
        """
        rep = self._setup(api, "EPA-EP-2B")
        after = validate_success(api.get_compliance_report(rep["id"], CM))
        # PRD pins the instant (quarter_end_date + 60 days), not the string
        # format — compare parsed instants (quarter end 2026-06-30 + 60 days).
        due = datetime.fromisoformat(after["due_date"].replace("Z", "+00:00"))
        assert due == datetime(2026, 8, 29, 0, 0, 0, tzinfo=timezone.utc)


class TestSegregationAuditorCannotSubmit:
    def _setup(self, api, epa_id):
        _acct, yr = create_account_and_year(epa_registration_id=epa_id)
        eng = create_engagement(yr["id"], auditor_user_id="aud-1")
        drive_engagement_to_closed_clean(eng["id"], auditor_user_id="aud-1")
        rep = create_report(yr["id"], report_type="ANNUAL",
                            headers=make_compliance_manager_headers("cm-1"))
        return rep

    def test_auditor_submission_rejected_segregation(self, api):
        """PRD §3.6: "Segregation first: the submitter must not be an auditor on the same year, so if any attest engagement on the obligation year has an `auditor_user_id` equal to the submitter's `X-User-ID`, submission is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_auditor_cannot_submit_own_year_report
        """
        rep = self._setup(api, "EPA-RBAC-5")
        resp = api.submit_compliance_report(
            rep["id"], make_compliance_manager_headers("aud-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rejected_submission_leaves_report_draft(self, api):
        """PRD §3.6: "The new report stands `DRAFT`"

        Design: Corner/rbac/segregation_auditor_cannot_submit_own_year_report
        """
        rep = self._setup(api, "EPA-RBAC-5B")
        resp = api.submit_compliance_report(
            rep["id"], make_compliance_manager_headers("aud-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_compliance_report(rep["id"], CM))
        assert after["status"] == "DRAFT"
