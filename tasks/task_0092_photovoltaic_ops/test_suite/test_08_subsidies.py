"""Subsidy declaration validation, submission, approval, arrears
(PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    create_station,
    create_settlement_period,
    create_subsidy_declaration,
    create_subsidy_policy,
    run_sweep,
    setup_confirmed_settlement,
    validate_error,
    validate_success,
)


class TestSubsidySubmitGate:
    """PRD §3.7 ordered preconditions on submit."""

    def test_submit_with_draft_period_rejected(self, api, finance_headers):
        """PRD §3.7: "the referenced settlement period MUST be in
        CONFIRMED or INVOICED (a DRAFT, RECONCILING, or DISPUTED
        period cannot back a subsidy claim), failing with
        ERR_SETTLEMENT_NOT_CONFIRMED."

        Claim: submit when the settlement period is in DRAFT →
        ERR_SETTLEMENT_NOT_CONFIRMED.
        """
        station = create_station(commissioning_date="2025-06-01T00:00:00.000Z")
        period = create_settlement_period(station["id"])  # DRAFT
        policy = create_subsidy_policy()
        decl = create_subsidy_declaration(
            station["id"], policy["id"], period["id"],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_CONFIRMED.value)

    def test_submit_with_period_out_of_window_rejected(
        self, api, finance_headers,
    ):
        """PRD §3.7: "the period's period_end MUST fall within the
        half-open [policy.eligible_from, policy.eligible_to), failing
        with ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW."

        Claim: a confirmed period whose period_end is OUTSIDE the
        policy's eligibility window → ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW.
        """
        result = setup_confirmed_settlement(
            period_start="2025-12-01T00:00:00.000Z",
            period_end="2026-01-01T00:00:00.000Z",  # AT eligible_from edge
            period_end_clock="2026-01-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        # Policy window starts 2026-02 — the period_end (2026-01-01) is
        # OUTSIDE [2026-02, 2027-01).
        policy = create_subsidy_policy(
            eligible_from="2026-02-01T00:00:00.000Z",
            eligible_to="2027-02-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        validate_error(
            resp, ApiErrorId.ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW.value,
        )

    def test_submit_missing_documents_rejected(self, api, finance_headers):
        """PRD §3.7: "the set of document keys in
        policy.required_documents MUST be entirely contained in the
        set of keys present in the declaration's documents ...
        failing with ERR_DOCUMENTS_INCOMPLETE."

        Claim: declaration missing a required document key →
        ERR_DOCUMENTS_INCOMPLETE.
        """
        result = setup_confirmed_settlement(
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        policy = create_subsidy_policy(
            required_documents=["GRID_CONNECTION_CERT", "METER_REPORT",
                                "AUDIT_REPORT"],
        )
        # Declaration only carries two of the three required docs.
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
            documents=[
                {"key": "GRID_CONNECTION_CERT",
                 "ref_url": "https://docs.example/1.pdf"},
                {"key": "METER_REPORT",
                 "ref_url": "https://docs.example/2.pdf"},
            ],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE.value)

    def test_submit_commissioning_outside_bounds_rejected(
        self, api, finance_headers,
    ):
        """PRD §3.7: "when the policy supplies bounds, the station's
        commissioning_date MUST fall within the half-open
        [policy.min_commissioning_date, policy.max_commissioning_date);
        outside that range yields
        ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE."

        Claim: station commissioned BEFORE policy.min_commissioning_date
        → ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE.
        """
        result = setup_confirmed_settlement(
            commissioning_date="2024-01-01T00:00:00.000Z",
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        policy = create_subsidy_policy(
            min_commissioning_date="2025-01-01T00:00:00.000Z",
            max_commissioning_date="2027-01-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE.value,
        )


class TestSubsidyComputation:
    """PRD §3.7 subsidy_amount, minimum payout."""

    def test_submit_computes_subsidy_amount(self, api, finance_headers):
        """PRD §3.7: "the platform fixes claimed_kwh to the period's
        grid_company_confirmed_kwh and computes subsidy_amount_cny
        as claimed_kwh multiplied by the policy's rate_cny_per_kwh,
        rounded half-up to two decimal places..."

        Claim: claimed_kwh = grid_company_confirmed_kwh; amount =
        round(claimed_kwh * rate, 2). With grid_kwh=2000 and
        rate=0.0500, amount=100.00.
        """
        result = setup_confirmed_settlement(
            commissioning_date="2025-06-01T00:00:00.000Z",
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        policy = create_subsidy_policy(
            rate_cny_per_kwh=0.0500,
            eligible_from="2026-01-01T00:00:00.000Z",
            eligible_to="2027-01-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        data = validate_success(resp)
        assert data["state"] == "SUBMITTED"
        assert data["claimed_kwh"] == pytest.approx(2000.0)
        assert data["subsidy_amount_cny"] == pytest.approx(100.00, abs=0.001)

    def test_subsidy_below_threshold_rejected(self, api, finance_headers):
        """PRD §3.7: "If the resulting payout would be strictly less
        than the minimum-payout constant of one hundred yuan, the
        submission is rejected with ERR_SUBSIDY_BELOW_THRESHOLD; the
        boundary is closed, so a payout of exactly one hundred is
        acceptable."

        Claim: grid=1900.0 * rate=0.0500 = 95.00 (< 100) →
        ERR_SUBSIDY_BELOW_THRESHOLD.
        """
        result = setup_confirmed_settlement(
            commissioning_date="2025-06-01T00:00:00.000Z",
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=1900.0,
            grid_company_confirmed_kwh=1900.0,
        )
        policy = create_subsidy_policy(
            rate_cny_per_kwh=0.0500,
            eligible_from="2026-01-01T00:00:00.000Z",
            eligible_to="2027-01-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        resp = api.submit_subsidy_declaration(decl["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSIDY_BELOW_THRESHOLD.value)


class TestSubsidyArrearsWatchdog:
    """PRD §3.7 + §3.2 sweep auto-arrears."""

    def test_approved_past_grace_becomes_arrears(self, api, finance_headers,
                                                  admin_headers):
        """PRD §3.7: "During every sweep run, the platform scans
        SubsidyDeclaration rows in APPROVED and, for any whose
        approval_due_date is more than thirty days in the past — that
        is, where the current instant is strictly greater than the
        approval_due_date plus thirty days — moves the declaration
        into ARREARS."

        Claim: an APPROVED declaration whose approval_due_date is
        more than 30 days behind the clock moves to ARREARS after
        /_sweep/run.
        """
        result = setup_confirmed_settlement(
            commissioning_date="2025-06-01T00:00:00.000Z",
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        policy = create_subsidy_policy(
            rate_cny_per_kwh=0.0500,
            eligible_from="2026-01-01T00:00:00.000Z",
            eligible_to="2027-01-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        submitted = validate_success(api.submit_subsidy_declaration(
            decl["id"], finance_headers,
        ))
        # Approve as admin.
        validate_success(api.approve_subsidy_declaration(
            decl["id"], admin_headers,
        ))
        # approval_due_date = submission + 90 days. Clock at
        # 2026-03-02 → due ~ 2026-05-31. Push >30 days past that.
        advance_clock_to("2026-08-01T00:00:00.000Z")
        run_sweep()
        # Verify state via list.
        resp = api.list_subsidy_declarations(
            finance_headers, params={"station_id": result["station"]["id"]},
        )
        body = resp.json()
        rows = body["data"]
        d = next(d for d in rows if d["id"] == decl["id"])
        assert d["state"] == "ARREARS", (
            f"expected ARREARS after sweep with grace exceeded, got {d['state']}"
        )

    def test_arrears_receive_settles_declaration(
        self, api, finance_headers, admin_headers,
    ):
        """PRD §3.7: "The receipt action then settles the ARREARS
        declaration the same way it settles an APPROVED one."

        Claim: receive on an ARREARS declaration moves it to
        RECEIVED with received_at set.
        """
        # Drive an APPROVED declaration into ARREARS first.
        result = setup_confirmed_settlement(
            commissioning_date="2025-06-01T00:00:00.000Z",
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            period_end_clock="2026-03-02T00:00:00.000Z",
            investor_shares=[("Alpha", 10000)],
            on_grid_kwh=2000.0,
            grid_company_confirmed_kwh=2000.0,
        )
        policy = create_subsidy_policy(
            rate_cny_per_kwh=0.0500,
            eligible_from="2026-01-01T00:00:00.000Z",
            eligible_to="2027-01-01T00:00:00.000Z",
        )
        decl = create_subsidy_declaration(
            result["station"]["id"], policy["id"], result["period"]["id"],
        )
        api.submit_subsidy_declaration(decl["id"], finance_headers)
        api.approve_subsidy_declaration(decl["id"], admin_headers)
        advance_clock_to("2026-08-01T00:00:00.000Z")
        run_sweep()
        # Now receive.
        resp = api.receive_subsidy_declaration(decl["id"], finance_headers)
        received = validate_success(resp)
        assert received["state"] == "RECEIVED"
        assert received["received_at"] is not None
