"""Issuance, expiration, renewal, and closeout: validation precedence
(state before fiscal), OCC stale-version rejection on issue and renew, the
version bump on a clean issue, the zero-balance gate, the renewal-fee accrual,
the expire sweep, and the finalize gates (no-certificate, work-stopped).

PRD §3.6 (issue/expire/renew), §3.10 (finalize), §2.6 (order), §2.9 (OCC).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_jurisdiction,
    create_contractor,
    create_permit,
    create_approved_permit,
    create_issued_permit,
    create_expired_permit,
    create_permit_with_certificate,
    pay_in_full,
    pay_permit,
    current_version,
    issue_stop_work,
    set_clock,
    advance_clock,
    make_clerk_headers,
    make_official_headers,
    make_applicant_headers,
)


class TestStateBeatsFiscalOnIssue:
    def test_submitted_permit_with_balance_due_reports_invalid_state(self, api):
        """PRD §2.6: "then the target's state suitability for the requested
        transition (`ERR_INVALID_STATE`)".
        PRD §2.6: "A check earlier in this order masks a later one when both
        would fail."
        PRD §3.6: "It is permitted only while the permit's `status` is `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_issue
        """
        # SUBMITTED (never approved), unpaid (balance 165.00): state check masks fiscal.
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"],
                              work_class="REPAIR", fee_method="VALUATION",
                              declared_valuation=2000)
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submitted_permit_issue_returns_409(self, api):
        """PRD §3.6: "It is permitted only while the permit's `status` is
        `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_issue
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"],
                              work_class="REPAIR", fee_method="VALUATION",
                              declared_valuation=2000)
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"


class TestOccStaleVersion:
    def test_issue_stale_version_rejected(self, api):
        """PRD §2.9: "the request must carry `expected_permit_application_version`
        equal to the target permit's current `version`. If another clerk has
        already advanced the permit's version since the caller last read it ...
        the stale request is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_issue_returns_412
        """
        permit, _review, _rev = create_approved_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv - 1},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION.value)

    def test_renew_stale_version_rejected(self, api):
        """PRD §2.9: "Renewal behaves identically: its
        `expected_permit_application_version` must match the permit's current
        `version`, and a mismatch ... is rejected with `ERR_STALE_PERMIT_VERSION`
        (HTTP 412), so the renewal fee can never be applied twice."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_renew_returns_412
        """
        expired, _rev = create_expired_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pv2 = current_version(expired["id"])
        resp = api.renew_permit(expired["id"],
                                {"expected_permit_application_version": pv2 - 1},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION.value)


class TestIssueVersionBump:
    def test_issue_with_correct_version_succeeds_and_bumps_version(self, api):
        """PRD §3.6: "the permit advances from `APPROVED` to `ISSUED`: `issued_at`
        is set to the current clock instant, `expires_at` is set to `issued_at`
        plus the jurisdiction's `permit_valid_days` days, `work_status` becomes
        `ACTIVE`, an `ISSUED` audit event is appended, and the version is bumped."

        Design: Corner/cross_cutting_complexity_layers/issue_correct_version_increments_version
        """
        permit, _review, _rev = create_approved_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        data = validate_success(resp)
        assert data["status"] == "ISSUED"
        assert data["version"] == pv + 1


class TestBalanceDueGate:
    def test_underpaid_permit_blocks_issue(self, api):
        """PRD §3.6: "The permit's `balance_due` must be exactly zero, or the
        request is rejected with `ERR_BALANCE_DUE`."

        Design: Corner/validations/balance_due_blocks_issue_when_underpaid
        """
        permit, _review, _rev = create_approved_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_permit(permit["id"], 164.99)
        permit_read = validate_success(api.get_permit(permit["id"], make_clerk_headers()))
        assert permit_read["balance_due"] == 0.01
        pv = permit_read["version"]
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_BALANCE_DUE.value)


class TestRenewal:
    def test_renew_adds_renewal_fee_and_returns_to_issued(self, api):
        """PRD §3.6: "Renewal computes a renewal charge equal to the
        `total_permit_fee` multiplied by the jurisdiction's `renewal_fee_pct`,
        rounded to two decimal places, round half up, and adds that charge to
        `accrued_renewal_fees` (which feeds back into `balance_due`)."

        Design: Corner/calculations/renew_adds_renewal_fee_and_resets_expiry
        """
        expired, _rev = create_expired_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pv2 = current_version(expired["id"])
        resp = api.renew_permit(expired["id"],
                                {"expected_permit_application_version": pv2},
                                make_clerk_headers())
        data = validate_success(resp)
        assert data["status"] == "ISSUED"
        assert data["accrued_renewal_fees"] == 82.50
        assert data["balance_due"] == 82.50


class TestExpireSweep:
    def test_expire_after_clock_advance_moves_to_expired_and_stops_work(self, api):
        """PRD §3.6: "When it fires, the permit moves from `ISSUED` to `EXPIRED`,
        its `work_status` is set to `STOPPED` ... an `EXPIRED` audit event is
        appended, and the version is bumped."

        Design: Corner/state_machines/expire_issued_permit_after_clock_advance
        """
        set_clock("2026-01-01T00:00:00Z")
        jur = create_jurisdiction(permit_valid_days=180)
        issued, _rev = create_issued_permit(
            jurisdiction_id=jur["id"], work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        advance_clock(200)
        resp = api.expire_permit(issued["id"], make_official_headers())
        data = validate_success(resp)
        assert data["status"] == "EXPIRED"
        assert data["work_status"] == "STOPPED"


class TestFinalizeGates:
    def test_finalize_without_certificate_rejected(self, api):
        """PRD §3.10: "It requires a standing certificate of occupancy: a
        `CertificateOfOccupancy` with `co_status` `ISSUED` must exist for the
        permit, or the attempt is rejected with `ERR_NO_CERTIFICATE`."

        Design: Corner/validations/finalize_without_certificate_returns_no_certificate
        """
        issued, _rev = create_issued_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        resp = api.finalize_permit(issued["id"], make_official_headers())
        validate_error(resp, ApiErrorId.ERR_NO_CERTIFICATE.value)

    def test_finalize_blocked_by_active_stop_work(self, api):
        """PRD §3.10: "It requires that the permit's `work_status` not be
        `STOPPED` — an active stop-work order blocks closeout with
        `ERR_WORK_STOPPED`."

        Design: Corner/rbac/work_stopped_blocks_finalize
        """
        issued, _rev = create_issued_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        issue_stop_work(issued["id"], reason="Active hazard")
        permit_read = validate_success(api.get_permit(issued["id"], make_official_headers()))
        assert permit_read["work_status"] == "STOPPED"
        resp = api.finalize_permit(issued["id"], make_official_headers())
        validate_error(resp, ApiErrorId.ERR_WORK_STOPPED.value)
