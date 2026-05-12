"""Payroll period creation, overlap, lock, settle, tax computation, and
withholding-for-re-inspection. Covers PRD §3.10."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_payroll_period,
    create_payroll_period_payload,
    finalize_inspection,
    find_ledger_entries,
    get_package,
    get_success_data,
    list_ledger,
    lock_payroll,
    make_annotator_headers,
    setup_inspecting_package,
    setup_payroll_with_one_approved_package,
    settle_payroll,
    start_inspection,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.10 -- Period create + overlap detection
# =========================================================================
class TestPeriodCreate:

    def test_create_open_period(self, api, project_manager_headers):
        """PRD §3.10: 'A new period enters OPEN.'

        Claim: POST /payroll-periods returns OPEN status.
        """
        res = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-01T00:00:00.000Z",
                closes_at="2026-06-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "OPEN"

    def test_overlapping_period_rejected(
        self, api, project_manager_headers,
    ):
        """PRD §3.10: 'two periods on the same calendar may not overlap
        under half-open semantics -- periods overlap if and only if the
        first's opens_at is strictly before the second's closes_at and
        the second's opens_at is strictly before the first's closes_at.
        A creation request that overlaps an existing period is rejected
        with ERR_PERIOD_OVERLAP.'

        Claim: a second period overlapping the first -> 409
        ERR_PERIOD_OVERLAP.
        """
        api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-01T00:00:00.000Z",
                closes_at="2026-06-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        res = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-15T00:00:00.000Z",
                closes_at="2026-06-15T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP.value)

    def test_adjacent_period_allowed_under_half_open(
        self, api, project_manager_headers,
    ):
        """PRD §3.10: 'periods overlap if and only if the first's
        opens_at is strictly before the second's closes_at and the
        second's opens_at is strictly before the first's closes_at.'

        Claim: adjacency case (new.opens_at == existing.closes_at) is
        allowed because of strictly-less-than in the overlap predicate.
        """
        api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-01T00:00:00.000Z",
                closes_at="2026-06-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        res = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-06-01T00:00:00.000Z",
                closes_at="2026-07-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "OPEN"

    @pytest.mark.parametrize("bad_rate", [-0.1, 1.1, 2.0])
    def test_invalid_tax_rate(
        self, api, project_manager_headers, bad_rate,
    ):
        """PRD §3.10: 'a flat tax_rate between 0 and 1 inclusive.'
        PRD §3.1 (parameter ranges): out-of-range parameters are
        rejected with ERR_INVALID_PARAMETER.

        Claim: tax_rate outside [0, 1] -> ERR_INVALID_PARAMETER.
        """
        res = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-01T00:00:00.000Z",
                closes_at="2026-06-01T00:00:00.000Z",
                tax_rate=bad_rate,
            ),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARAMETER.value)


# =========================================================================
# §3.10 -- Lock gating
# =========================================================================
class TestLock:

    def test_lock_before_due_rejected(self, api, project_manager_headers):
        """PRD §3.10: 'A ProjectManager locks the period -- moving status
        from OPEN to LOCKED -- when the current server time has reached
        or passed closes_at; an early lock is rejected with
        ERR_PERIOD_NOT_DUE.'

        Claim: lock before closes_at -> 409 ERR_PERIOD_NOT_DUE.
        """
        # Set the clock first, then create a period whose closes_at is
        # in the future relative to that anchor.
        advance_clock("2026-05-15T00:00:00.000Z", pm_headers=project_manager_headers)
        period_resp = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-06-01T00:00:00.000Z",
                closes_at="2026-07-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        period = get_success_data(period_resp)
        res = api.lock_payroll_period(period["id"], project_manager_headers)
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_DUE.value)


# =========================================================================
# §3.10 -- Settle and tax computation
# =========================================================================
class TestSettle:

    def test_settle_releases_entries_and_writes_tax(
        self, api, project_manager_headers,
    ):
        """PRD §3.10: 'When settle commits, every SalaryLedgerEntry of
        the period transitions from WITHHELD to RELEASED, and a
        per-annotator TAX entry is inserted.'

        Claim: after settle, every WITHHELD entry is RELEASED and a TAX
        entry exists for the period's annotator.
        """
        state = setup_payroll_with_one_approved_package(
            unit_price_cents=100, package_size=10,
            tax_rate=0.10,
        )
        period = state["period"]
        annotator = state["annotator"]
        settle_payroll(period["id"])
        entries = list_ledger(period["id"])
        # All entries for the period are RELEASED (WITHHOLD/RELEASE
        # markers are accounting-only, but their settlement_state should
        # also be RELEASED post-settle per PRD).
        non_marker = [
            e for e in entries if e["kind"] not in ("WITHHOLD", "RELEASE")
        ]
        assert all(
            e["settlement_state"] == "RELEASED" for e in non_marker
        ), f"expected all entries RELEASED, got {non_marker!r}"
        # TAX entry exists for the annotator.
        taxes = find_ledger_entries(
            entries, annotator_id=annotator["id"], kind="TAX",
        )
        assert len(taxes) == 1
        # gross_amount_cents = 800 (PIECE_RATE EASY/JUNIOR/100/10 items).
        # tax_basis = max(0, 800) = 800; tax = round(800*0.10) = 80;
        # signed -80.
        assert taxes[0]["gross_amount_cents"] == -80

    def test_settle_only_on_locked_period(
        self, api, project_manager_headers,
    ):
        """PRD §3.10: 'The settle operation is the gate at which
        withholding is enforced. The period must be in LOCKED (else
        ERR_PERIOD_STATE_INVALID).'

        Claim: settle on an OPEN (never-locked) period -> 409
        ERR_PERIOD_STATE_INVALID.
        """
        period_resp = api.create_payroll_period(
            create_payroll_period_payload(
                opens_at="2026-05-01T00:00:00.000Z",
                closes_at="2026-06-01T00:00:00.000Z",
                tax_rate=0.10,
            ),
            project_manager_headers,
        )
        period = get_success_data(period_resp)
        # Period is OPEN, not LOCKED. Settle must reject with state error.
        res = api.settle_payroll_period(period["id"], project_manager_headers)
        validate_error(res, ApiErrorId.ERR_PERIOD_STATE_INVALID.value)
