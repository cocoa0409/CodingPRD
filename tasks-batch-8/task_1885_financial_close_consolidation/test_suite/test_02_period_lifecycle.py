"""Close period lifecycle: listing, retrieval, open-exclusion, OCC, posture gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, assert_close_period,
    create_period_payload, create_entity_payload,
    set_clock, create_period, create_entity, open_period, get_period_version,
    setup_open_period_with_entity, drive_entity_period_to_ready,
    soft_lock_period, setup_soft_locked_period, setup_hard_locked_period,
    CONTROLLER, PREPARER, APPROVER, AUDITOR,
)
from test_helpers import api_client


class TestPeriodListing:
    def test_list_periods_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_periods_pagination_envelope
        """
        set_clock()
        for fp, ps, pe in ((1, "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"),
                            (2, "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z"),
                            (3, "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")):
            create_period(fiscal_period=fp, period_start=ps, period_end=pe)

        data, meta = validate_paginated(api.list_periods(CONTROLLER, params={"limit": 2, "offset": 0}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert len(data) == 2

        # Default limit is 10 when omitted.
        data2, meta2 = validate_paginated(api.list_periods(CONTROLLER))
        assert meta2["limit"] == 10

    def test_get_period_returns_stored_fields(self, api):
        """PRD §3.1: "a `Controller` creates a close period by supplying
        `fiscal_year` (for example 2026), `fiscal_period` (an integer from 1
        through 13 within the year), `period_start` and `period_end` instants in
        UTC with the end strictly after the start, the consolidation
        `reporting_currency` (again one of `USD`, `EUR`, `GBP`, `JPY`), and
        `materiality_threshold_minor`".
        PRD §3.1: "A freshly created period starts in `SCHEDULED` status with its
        posture computed as `OPEN`."

        Design: Corner/endpoints/get_period_returns_stored_fields
        """
        set_clock()
        period = create_period(
            fiscal_year=2026, fiscal_period=7,
            period_start="2026-07-01T00:00:00Z", period_end="2026-07-31T00:00:00Z",
            reporting_currency="EUR", materiality_threshold_minor=2500,
        )
        fetched = validate_success(api.get_period(period["id"], AUDITOR), 200)
        assert_close_period(fetched)
        assert fetched["fiscal_year"] == 2026
        assert fetched["fiscal_period"] == 7
        assert fetched["reporting_currency"] == "EUR"
        assert fetched["status"] == "SCHEDULED"
        assert fetched["close_posture"] == "OPEN"


class TestSingleOpenPeriod:
    def test_open_second_period_rejected_period_already_open(self, api):
        """PRD §3.1: "Only one close may be open at a time: if any other period is
        currently `IN_PROGRESS` or `UNDER_REVIEW`, the open attempt is rejected with
        `ERR_PERIOD_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/single_open_close_period_mutual_exclusion
        """
        set_clock()
        p1 = create_period()
        open_period(p1["id"])
        p2 = create_period(fiscal_period=2,
                            period_start="2026-02-01T00:00:00Z",
                            period_end="2026-02-28T00:00:00Z")
        # Advance the clock past p2's period_start so the tier-9 temporal gate
        # (ERR_PERIOD_NOT_YET_OPEN) does not mask the tier-11 single-open gate
        # (PRD §2.9: earlier tiers mask later ones).
        set_clock("2026-02-15T00:00:00Z")
        res = api.open_period(p2["id"], CONTROLLER)
        validate_error(res, ApiErrorId.ERR_PERIOD_ALREADY_OPEN, expected_status=409)

    def test_open_second_period_leaves_status_scheduled(self, api):
        """PRD §3.1: "Only one close may be open at a time: if any other period is
        currently `IN_PROGRESS` or `UNDER_REVIEW`, the open attempt is rejected with
        `ERR_PERIOD_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/single_open_close_period_mutual_exclusion
        """
        set_clock()
        p1 = create_period()
        open_period(p1["id"])
        p2 = create_period(fiscal_period=2,
                            period_start="2026-02-01T00:00:00Z",
                            period_end="2026-02-28T00:00:00Z")
        # Advance past p2's period_start so the open attempt reaches the
        # single-open gate (ERR_PERIOD_ALREADY_OPEN) this test targets.
        set_clock("2026-02-15T00:00:00Z")
        api.open_period(p2["id"], CONTROLLER)
        fetched = validate_success(api.get_period(p2["id"], CONTROLLER), 200)
        assert fetched["status"] == "SCHEDULED"


class TestOccVersioning:
    def test_occ_version_increments_on_every_period_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every mutation, including mutations caused by cascade side effects
        originating on other resources."
        PRD §3.1: "A successful open moves the period from `SCHEDULED` to
        `IN_PROGRESS`, sets the posture to `OPEN`, increments the period's `version`
        by one, appends a `PERIOD_OPENED` audit event, and fans out one
        entity-period row per registered entity".

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_period_mutation
        """
        set_clock()
        period = create_period()
        v_create = period["version"]
        assert v_create == 1, f"expected version 1 at create, got {v_create}"
        opened = validate_success(api.open_period(period["id"], CONTROLLER), 200)
        assert opened["version"] == v_create + 1

    def test_stale_period_version_on_soft_lock(self, api):
        """PRD §2.8: "Four `Controller` operations on a close period — soft-locking
        it, hard-locking it, reopening it, and finalizing it — each require a
        non-optional input field `expected_close_period_version` carrying the
        caller's last observed `version` of the period. If that value does not match
        the period's current `version`, the request is rejected with
        `ERR_STALE_PERIOD_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_period_version_on_soft_lock
        """
        period, entity, ep = setup_open_period_with_entity()
        stale_version = period["version"]  # version at create, before open bump
        drive_entity_period_to_ready(period["id"], ep["id"], fx_currency="USD")
        res = api.soft_lock_period(period["id"],
                                    {"expected_close_period_version": stale_version},
                                    CONTROLLER)
        validate_error(res, ApiErrorId.ERR_STALE_PERIOD_VERSION, expected_status=412)
        # posture unchanged
        fetched = validate_success(api.get_period(period["id"], CONTROLLER), 200)
        assert fetched["close_posture"] == "OPEN"


class TestReopenGate:
    def test_reopen_hard_closed_period_returns_period_hard_locked(self, api):
        """PRD §3.9: "A `Controller` reopens a period — OCC-guarded like the locks —
        only while its posture is `SOFT_CLOSED`; attempting to reopen a
        `HARD_CLOSED` or `UNDER_REVIEW` period is rejected with
        `ERR_PERIOD_HARD_LOCKED`".

        Design: Corner/state_machines/reopen_hard_closed_period_returns_period_hard_locked
        """
        period, entity, ep = setup_hard_locked_period()
        fetched = validate_success(api.get_period(period["id"], CONTROLLER), 200)
        assert fetched["close_posture"] == "HARD_CLOSED"
        v = fetched["version"]
        res = api.reopen_period(period["id"],
                                  {"expected_close_period_version": v,
                                   "reopened_reason": "late adjustment"},
                                  CONTROLLER)
        validate_error(res, ApiErrorId.ERR_PERIOD_HARD_LOCKED, expected_status=409)
        # posture unchanged
        fetched2 = validate_success(api.get_period(period["id"], CONTROLLER), 200)
        assert fetched2["close_posture"] == "HARD_CLOSED"
