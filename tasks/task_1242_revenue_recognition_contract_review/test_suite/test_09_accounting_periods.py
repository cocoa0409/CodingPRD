"""Accounting calendar: creation, overlap, close, reopen (PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_accounting_period_payload,
    create_period, get_period, set_clock,
    setup_active_contract_with_pob,
    TEST_USERS,
    assert_accounting_period, assert_revenue_entry,
)


class TestPeriodOverlap:
    def test_intersecting_period_rejected(self, api, controller_headers):
        """PRD §3.9: "Period windows are half-open: a period covers every date
        from its `start_date` up to but not including its `end_date`. No two
        periods may overlap — though adjacency is allowed, so one period's
        `start_date` may equal another's `end_date` — and an overlapping
        creation is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_period_half_open_adjacency_allowed
        """
        create_period(period_code="2026-05", start_date="2026-05-01", end_date="2026-06-01")
        resp = api.create_accounting_period(
            create_accounting_period_payload(
                period_code="2026-05B", start_date="2026-05-15", end_date="2026-07-01"),
            controller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP, 409)

    def test_adjacent_period_accepted(self, api, controller_headers):
        """PRD §3.9: "No two periods may overlap — though adjacency is allowed,
        so one period's `start_date` may equal another's `end_date`".

        Design: Difficulty/resource_temporal_overlap/overlap_period_half_open_adjacency_allowed
        """
        create_period(period_code="2026-05", start_date="2026-05-01", end_date="2026-06-01")
        resp = api.create_accounting_period(
            create_accounting_period_payload(
                period_code="2026-06", start_date="2026-06-01", end_date="2026-07-01"),
            controller_headers,
        )
        period = validate_success(resp, 201)
        assert_accounting_period(period)
        assert period["status"] == "OPEN"
        assert period["reopened_once"] is False
        assert period["recognized_total_cents"] == 0


class TestSspWindowOverlap:
    def test_touching_windows_conflict(self, api, manager_headers):
        """PRD §3.3: "Two records for the same product-and-region pair may not
        have windows that overlap or even touch — a shared boundary date is
        already a conflict — and any such collision is rejected with
        `ERR_SSP_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_ssp_window_closed_interval_touching_conflicts
        """
        from test_helpers import create_ssp
        create_ssp("GADGET", region="US", ssp_cents=50000,
                   effective_from="2026-01-01", effective_to="2026-03-31")
        resp = api.create_ssp_price(
            {"product_code": "GADGET", "region": "US", "ssp_cents": 52000,
             "effective_from": "2026-03-31", "effective_to": "2026-06-30"},
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SSP_WINDOW_OVERLAP, 409)

    def test_non_touching_window_accepted(self, api, manager_headers):
        """PRD §3.3: "The window is closed at both ends: `effective_from` is the
        first covered date and `effective_to` the last, and `effective_to` may
        not precede `effective_from`."

        Design: Difficulty/resource_temporal_overlap/overlap_ssp_window_closed_interval_touching_conflicts
        """
        from test_helpers import create_ssp
        create_ssp("GADGET", region="US", ssp_cents=50000,
                   effective_from="2026-01-01", effective_to="2026-03-31")
        resp = api.create_ssp_price(
            {"product_code": "GADGET", "region": "US", "ssp_cents": 52000,
             "effective_from": "2026-04-01", "effective_to": "2026-06-30"},
            manager_headers,
        )
        ssp = validate_success(resp, 201)
        assert ssp["status"] == "ACTIVE"
        assert ssp["ssp_cents"] == 52000


class TestReopenLimit:
    def _close_reopen_close(self, api, controller_headers):
        period = create_period()
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        validate_success(api.reopen_accounting_period(period["id"], controller_headers))
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        return period

    def test_second_reopen_rejected(self, api, controller_headers):
        """PRD §3.9: "Reopening is the controlled exception, moving a period
        `CLOSED → REOPENED`, and it is allowed at most once per period and only
        while no later period — one whose `start_date` comes after this
        period's — is `CLOSED`; either violation is rejected with
        `ERR_PERIOD_REOPEN_LIMIT` (HTTP 409)."

        Design: Corner/state_machines/period_second_reopen_returns_reopen_limit
        """
        period = self._close_reopen_close(api, controller_headers)
        resp = api.reopen_accounting_period(period["id"], controller_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_REOPEN_LIMIT, 409)

    def test_period_remains_closed_after_rejected_reopen(self, api, controller_headers):
        """PRD §3.9: "it is allowed at most once per period and only while no
        later period — one whose `start_date` comes after this period's — is
        `CLOSED`; either violation is rejected with `ERR_PERIOD_REOPEN_LIMIT`
        (HTTP 409)."

        Design: Corner/state_machines/period_second_reopen_returns_reopen_limit
        """
        period = self._close_reopen_close(api, controller_headers)
        validate_error(api.reopen_accounting_period(period["id"], controller_headers),
                       ApiErrorId.ERR_PERIOD_REOPEN_LIMIT, 409)
        after = get_period(period["id"])
        assert after["status"] == "CLOSED"
        assert after["reopened_once"] is True


class TestPeriodLocking:
    def test_close_locks_posted_entries(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "Closing moves a period from `OPEN` or `REOPENED` to
        `CLOSED` and locks its contents: every revenue entry with a
        `posting_date` inside the period and status `POSTED` becomes `LOCKED`".

        Design: Corner/validations/locked_entry_reversal_rejected
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 10000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        validate_success(api.close_accounting_period(setup["period"]["id"], controller_headers))
        entries = validate_paginated(
            api.list_revenue_entries(accountant_headers, params={"pob_id": pob["id"]})
        )[0]
        assert len(entries) == 1
        assert_revenue_entry(entries[0])
        assert entries[0]["status"] == "LOCKED"
