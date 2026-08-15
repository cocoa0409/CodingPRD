"""Site season lifecycle, season-window calendar rules, and closure gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    apply_pest_treatment,
    certify_unit,
    create_building,
    create_pest_treatment,
    create_season_window,
    create_site,
    create_unit,
    drive_site,
    get_site,
    get_statement,
    open_site,
    set_clock,
    setup_active_tenancy,
    setup_certified_site,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
LEAD = TEST_USERS["maintenance_lead_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _get_window(api, window_id):
    return validate_success(api.get_season_window(window_id, ADMIN))


class TestSeasonWindowCalendarRules:
    """Difficulty instance: closed-interval overlap, maintenance gap, smallest
    legal separation (PRD §3.1)."""

    def _setup_open_site(self, api):
        ctx = setup_certified_site(site_name="Site SW")
        return ctx

    def test_season_window_overlap_and_gap_rejections(
            self, api, operator_admin_headers):
        """PRD §3.1: "Overlap is checked first: because intervals are closed,
        the new window intersects an existing one whenever its
        `planned_open_date` falls on or before the existing window's
        `planned_close_date` while its `planned_close_date` falls on or after
        the existing window's `planned_open_date`, and an intersecting create
        is rejected with `ERR_SEASON_WINDOW_OVERLAP`."
        PRD §3.1: "the free span between the intervals must exceed fourteen
        days, so a gap of one to fourteen days in either direction is rejected
        with `ERR_SEASON_GAP_TOO_SHORT`"

        Design: Difficulty/resource_temporal_overlap/season_window_closed_interval_gap_rule
        """
        ctx = self._setup_open_site(api)
        site = get_site(ctx["site"]["id"])

        # Abutting window: open == prior close is an overlap on closed
        # intervals.
        overlap = api.create_season_window(
            {"site_id": site["id"], "label": "W2",
             "planned_open_date": "2026-11-30",
             "planned_close_date": "2027-03-01",
             "expected_site_version": site["version"]},
            operator_admin_headers)
        validate_error(overlap, ApiErrorId.ERR_SEASON_WINDOW_OVERLAP)

        # 14-day gap (2026-12-14 - 2026-11-30) is not > 14.
        short = api.create_season_window(
            {"site_id": site["id"], "label": "W3",
             "planned_open_date": "2026-12-14",
             "planned_close_date": "2027-03-01",
             "expected_site_version": site["version"]},
            operator_admin_headers)
        validate_error(short, ApiErrorId.ERR_SEASON_GAP_TOO_SHORT)

    def test_season_window_smallest_legal_gap_succeeds(
            self, api, operator_admin_headers):
        """PRD §3.1: "exactly fifteen days is the smallest legal separation,
        and a new window that opens on the very day an existing one closes
        already fails the overlap rule."
        PRD §3.1: "creating a window supersedes any existing `PLANNED` window
        for the same site: the older window moves `PLANNED → SUPERSEDED`"

        Design: Difficulty/resource_temporal_overlap/season_window_closed_interval_gap_rule
        """
        ctx = self._setup_open_site(api)
        site = get_site(ctx["site"]["id"])
        w1 = ctx["window"]

        # 15-day gap: 2026-11-30 -> 2026-12-15.
        created = validate_success(api.create_season_window(
            {"site_id": site["id"], "label": "W4",
             "planned_open_date": "2026-12-15",
             "planned_close_date": "2027-03-01",
             "expected_site_version": site["version"]},
            operator_admin_headers), expected_status=201)
        assert created["status"] == "PLANNED"

        # The failed creates mutated nothing; the ACTIVE window is never
        # superseded (only PLANNED windows are superseded).
        w1_after = _get_window(api, w1["id"])
        assert w1_after["status"] == "ACTIVE"


class TestSiteSeasonFullCycle:
    """Difficulty instance: DRAFT -> OPENING -> OPEN -> CLOSING -> CLOSED ->
    OPENING, with the window driven PLANNED -> ACTIVE -> COMPLETED."""

    def _setup_closable_site(self, api):
        """Site with one CERTIFIED unit, a PLANNED window, and a pest
        treatment scheduled at season start with a zero-day buffer."""
        site = create_site(name="Site C")
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        cert = certify_unit(unit["id"])
        window = create_season_window(site["id"], "W1", "2026-08-01",
                                      "2026-11-30")
        treatment = create_pest_treatment(unit["id"], "ROUTINE",
                                          "2026-08-01", 0)
        return {"site": site, "building": building, "unit": unit,
                "cert": cert, "window": window, "treatment": treatment}

    def test_site_closure_completes_window(self, api, operator_admin_headers):
        """PRD §3.1: "Closing then cascades: the `ACTIVE` window becomes
        `COMPLETED`; a certification expiry sweep flips every `PASSED`
        certification whose `expiry_date` is before the clock date to
        `EXPIRED`, and each affected unit in `CERTIFIED` that holds no other
        valid `PASSED` certification falls back to `REGISTERED`; and the
        site's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/site_season_full_cycle
        """
        ctx = self._setup_closable_site(api)
        site_id = ctx["site"]["id"]

        drive_site(site_id, "OPENING")
        opened = drive_site(site_id, "OPEN")
        assert opened["status"] == "OPEN"

        # Apply the in-season treatment, then clear it once the clock passes
        # the zero-day buffer end.
        apply_resp = api.update_pest_treatment(
            ctx["treatment"]["id"], {"status": "APPLIED"}, MANAGER)
        assert apply_resp.status_code == 200, "Setup failed applying treatment"
        set_clock("2026-08-02T00:00:00Z")
        clear_resp = api.update_pest_treatment(
            ctx["treatment"]["id"], {"status": "CLEARED"}, MANAGER)
        assert clear_resp.status_code == 200, "Setup failed clearing treatment"

        drive_site(site_id, "CLOSING")
        closed = drive_site(site_id, "CLOSED")
        assert closed["status"] == "CLOSED", (
            "Closure gates pass: no live tenancies, no open work orders, and "
            "the unit's treatment (applied 2026-08-01) sits inside the ACTIVE "
            "window [2026-08-01, 2026-11-30]")

        window_after = _get_window(api, ctx["window"]["id"])
        assert window_after["status"] == "COMPLETED"

    def test_closed_site_reopens_with_new_window(self, api,
                                                 operator_admin_headers):
        """PRD §3.1: "A closed site reopens cyclically — `CLOSED → OPENING` —
        under the same covering-window requirement as the first opening."
        PRD §3.1: "exactly fifteen days is the smallest legal separation"

        Design: Difficulty/non_linear_state_machine/site_season_full_cycle
        """
        ctx = self._setup_closable_site(api)
        site_id = ctx["site"]["id"]

        drive_site(site_id, "OPENING")
        drive_site(site_id, "OPEN")
        api.update_pest_treatment(ctx["treatment"]["id"],
                                  {"status": "APPLIED"}, MANAGER)
        set_clock("2026-08-02T00:00:00Z")
        api.update_pest_treatment(ctx["treatment"]["id"],
                                  {"status": "CLEARED"}, MANAGER)
        drive_site(site_id, "CLOSING")
        closed = drive_site(site_id, "CLOSED")
        assert closed["status"] == "CLOSED", "Setup failed closing site"

        # New window 15 days after the COMPLETED window's close: legal.
        w2 = create_season_window(site_id, "W2", "2026-12-15", "2027-03-31")
        assert w2["status"] == "PLANNED"

        # Move the clock inside W2 and reopen.
        set_clock("2026-12-20T00:00:00Z")
        reopen = drive_site(site_id, "OPENING")
        assert reopen["status"] == "OPENING", (
            "The CLOSED -> OPENING cycle repeats with the new covering window")


class TestSiteOpeningGates:
    def test_err_no_covering_season_window(self, api, operator_admin_headers):
        """PRD §3.1: "Moving `DRAFT → OPENING` requires a `PLANNED` window
        whose closed date interval covers the clock date; without one the
        transition is rejected with `ERR_NO_COVERING_SEASON_WINDOW`."

        Design: Corner/errors/err_no_covering_season_window
        """
        site = create_site(name="S")
        resp = api.update_housing_site(site["id"], {"status": "OPENING"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_SEASON_WINDOW)

    def test_err_no_certified_unit_on_open(self, api, operator_admin_headers):
        """PRD §3.1: "Completing the opening, `OPENING → OPEN`, requires at
        least one unit of the site to hold `CERTIFIED` status
        (`ERR_NO_CERTIFIED_UNIT`)"

        Design: Corner/errors/err_no_certified_unit_on_open
        """
        site = create_site(name="S")
        building = create_building(site["id"])
        create_unit(site["id"], building["id"])  # stays REGISTERED, no cert
        create_season_window(site["id"])
        drive_site(site["id"], "OPENING")
        resp = api.update_housing_site(site["id"], {"status": "OPEN"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_UNIT)


class TestSeasonWindowDeleteAndOcc:
    def test_delete_window_cancels_then_invalid_state(
            self, api, operator_admin_headers):
        """PRD §3.1: "An `OperatorAdmin` may also abandon a planned window
        outright, moving it `PLANNED → CANCELLED` through a delete-style
        operation that returns no content."
        PRD §3.1: "`COMPLETED`, `SUPERSEDED`, and `CANCELLED` are the window's
        terminal states."

        Design: Corner/endpoints/delete_window_cancels_then_invalid_state
        """
        site = create_site(name="S")
        window = create_season_window(site["id"], "W")

        first = api.delete_season_window(window["id"], operator_admin_headers)
        assert first.status_code == 204, (
            f"Expected 204 cancelling a PLANNED window, got "
            f"{first.status_code}: {first.text}")

        after = _get_window(api, window["id"])
        assert after["status"] == "CANCELLED"

        second = api.delete_season_window(window["id"],
                                          operator_admin_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_stale_season_window_create(self, api, operator_admin_headers):
        """PRD §2.7: "Creating a season window requires
        `expected_site_version` ... When another write has advanced the
        parent's `version` since the client last read it, the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "creating a window supersedes any existing `PLANNED` window
        for the same site"

        Design: Corner/validations/occ_stale_season_window_create
        """
        site = create_site(name="S")
        observed_version = site["version"]
        w1 = validate_success(api.create_season_window(
            {"site_id": site["id"], "label": "W1",
             "planned_open_date": "2026-08-01",
             "planned_close_date": "2026-11-30",
             "expected_site_version": observed_version},
            operator_admin_headers), expected_status=201)

        # The first create advanced the site version; replaying the stale
        # version is rejected even though the calendar itself is legal.
        stale = api.create_season_window(
            {"site_id": site["id"], "label": "W2",
             "planned_open_date": "2026-12-15",
             "planned_close_date": "2027-03-31",
             "expected_site_version": observed_version},
            operator_admin_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        w1_after = _get_window(api, w1["id"])
        assert w1_after["status"] == "PLANNED", (
            "The rejected create must not supersede the existing PLANNED "
            "window")


class TestSeasonClosureGates:
    def test_err_season_pest_treatment_missing_on_closure(
            self, api, operator_admin_headers):
        """PRD §3.1: "And every unit standing in `CERTIFIED`, `OCCUPIED`, or
        `HABITABILITY_HOLD` must show at least one pest treatment in `APPLIED`
        or `CLEARED` whose `applied_date` falls within the `ACTIVE` window's
        planned dates (`ERR_SEASON_PEST_TREATMENT_MISSING`)."

        Design: Corner/errors/err_season_pest_treatment_missing_on_closure
        """
        ctx = setup_certified_site(site_name="S")  # OPEN; no pest treatments
        site_id = ctx["site"]["id"]
        drive_site(site_id, "CLOSING")
        resp = api.update_housing_site(site_id, {"status": "CLOSED"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_PEST_TREATMENT_MISSING)

    def test_err_active_tenancies_remain_on_closure(
            self, api, operator_admin_headers):
        """PRD §3.1: "No tenancy on any unit of the site may remain in
        `ACTIVE` or `NOTICE` (`ERR_ACTIVE_TENANCIES_REMAIN`)."

        Design: Corner/errors/err_active_tenancies_remain_on_closure
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam AT",
                                   move_in_date="2026-08-05")
        site_id = ctx["site"]["id"]

        # Satisfy the pest gate: applied in-window with a zero-day buffer,
        # then cleared after the buffer elapses.
        treatment = create_pest_treatment(ctx["unit"]["id"], "ROUTINE",
                                          "2026-08-01", 0)
        applied = api.update_pest_treatment(treatment["id"],
                                            {"status": "APPLIED"}, MANAGER)
        assert applied.status_code == 200, "Setup failed applying treatment"
        set_clock("2026-08-02T00:00:00Z")
        cleared = api.update_pest_treatment(treatment["id"],
                                            {"status": "CLEARED"}, MANAGER)
        assert cleared.status_code == 200, "Setup failed clearing treatment"

        drive_site(site_id, "CLOSING")
        resp = api.update_housing_site(site_id, {"status": "CLOSED"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TENANCIES_REMAIN)

    def test_err_open_work_orders_remain_on_closure(
            self, api, operator_admin_headers, maintenance_lead_headers):
        """PRD §3.1: "No work order on any unit of the site may remain in
        `REPORTED`, `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, or
        `REOPENED` (`ERR_OPEN_WORK_ORDERS_REMAIN`)."

        Design: Corner/errors/err_open_work_orders_remain_on_closure
        """
        ctx = setup_certified_site(site_name="S")
        site_id = ctx["site"]["id"]

        # Pest gate satisfied (applied in-window, zero buffer, then cleared).
        treatment = create_pest_treatment(ctx["unit"]["id"], "ROUTINE",
                                          "2026-08-01", 0)
        applied = api.update_pest_treatment(treatment["id"],
                                            {"status": "APPLIED"}, MANAGER)
        assert applied.status_code == 200, "Setup failed applying treatment"
        set_clock("2026-08-02T00:00:00Z")
        cleared = api.update_pest_treatment(treatment["id"],
                                            {"status": "CLEARED"}, MANAGER)
        assert cleared.status_code == 200, "Setup failed clearing treatment"

        # One MINOR work order left open blocks closure.
        wo = api.create_work_order(
            {"unit_id": ctx["unit"]["id"], "category": "OTHER",
             "severity": "MINOR", "description": "loose hinge"},
            maintenance_lead_headers)
        assert wo.status_code == 201, "Setup failed creating work order"

        drive_site(site_id, "CLOSING")
        resp = api.update_housing_site(site_id, {"status": "CLOSED"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_WORK_ORDERS_REMAIN)
