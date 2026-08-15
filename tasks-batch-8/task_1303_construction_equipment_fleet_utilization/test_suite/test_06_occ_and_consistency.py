"""Optimistic concurrency, version increments, idle alert, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_damage,
    close_assignment,
    confirm_damage,
    dispute_damage,
    make_active_assignment,
    make_class,
    make_damage_report,
    make_equipment,
    make_fleet_bundle,
    make_project,
    make_reading,
    make_reserved_assignment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

_ADMIN = TEST_USERS["fleet_admin_headers"]


class TestOccAssignmentCreate:
    def test_stale_version_rejected(self, api):
        """PRD section 2.8: "Creating an assignment requires
        `expected_equipment_version` in the request body, carrying the
        `version` of the equipment unit as the client last observed it. If
        the unit's current `version` has advanced past that value ... the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_assignment_create
        """
        cls, project, equip = make_fleet_bundle()
        stale_v = equip["version"]
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-05")
        validate_success(api.cancel_assignment(asg["id"], _ADMIN))
        # After reserve (v -> v+1) and cancel (v -> v+2), stale_v is two behind
        err = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-07",
                "end_date": "2026-08-09",
                "expected_equipment_version": stale_v,
            },
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)
        assert err.status_code == 412

    def test_current_version_retry_succeeds(self, api):
        """PRD section 2.8: "Creating an assignment requires
        `expected_equipment_version` in the request body, carrying the
        `version` of the equipment unit as the client last observed it. If
        the unit's current `version` has advanced past that value ... the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)". Once the
        client re-reads the current version the same create is legal again.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_assignment_create
        """
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-05")
        validate_success(api.cancel_assignment(asg["id"], _ADMIN))
        e_now = validate_success(api.get_equipment(equip["id"], _ADMIN))
        # Reserve bumped version from 1 -> 2, cancel bumped 2 -> 3
        assert e_now["version"] == equip["version"] + 2
        retry = validate_success(api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-07",
                "end_date": "2026-08-09",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        ), expected_status=201)
        assert retry["status"] == "RESERVED"


class TestOccDamageReassess:
    def _setup_disputed_report(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"],
                               line_items=[{"description": "x", "amount_cents": 10000}])
        assess_damage(d["id"])
        disp = dispute_damage(d["id"], "disputed")
        return d, disp

    def test_stale_damage_version_rejected(self, api):
        """PRD section 2.8: "Reassessing a disputed damage report requires
        `expected_damage_report_version`, matching the report's current
        `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_damage_reassess
        """
        d, disp = self._setup_disputed_report(api)
        stale_v = disp["version"] - 1
        err = api.reassess_damage_report(
            d["id"],
            {"line_items": [{"description": "x (revised)", "amount_cents": 7000}],
             "expected_damage_report_version": stale_v},
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)
        assert err.status_code == 412
        # Original charge unchanged
        after = validate_success(api.get_damage_report(d["id"], _ADMIN))
        assert after["assessed_charge_cents"] == 10000
        assert after["status"] == "DISPUTED"

    def test_correct_version_reassess_succeeds(self, api):
        """PRD section 3.8: "the request must carry
        `expected_damage_report_version` equal to the report's current
        `version`"; on success "the report's `version` increments for each
        reassessment round, and the report returns to `ASSESSED`".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_damage_reassess
        """
        d, disp = self._setup_disputed_report(api)
        current_v = disp["version"]
        r = validate_success(api.reassess_damage_report(
            d["id"],
            {"line_items": [{"description": "x (revised)", "amount_cents": 7000}],
             "expected_damage_report_version": current_v},
            _ADMIN,
        ))
        assert r["status"] == "ASSESSED"
        assert r["assessed_charge_cents"] == 7000
        assert r["version"] == current_v + 1


class TestEquipmentVersionIncrement:
    def test_version_increments_on_each_mutation(self, api):
        """PRD section 2.4: "`version` (integer): a system-managed counter
        that increments by exactly 1 on every mutation of the resource."
        PRD section 2.4 also pins: "Every mutation that changes a unit's
        meter, state, or service bookkeeping increments that unit's `version`
        by 1".

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        cls = make_class(class_code="EXC-702", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-702")
        assert equip["version"] == 1

        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=1000, fuel_used_milliliters=500)
        v2 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert v2["version"] == 2

        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        v3 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert v3["version"] == 3

    def test_updated_at_refreshes_on_mutation(self, api):
        """PRD section 2.4: "`updated_at` (string): an ISO 8601 UTC timestamp
        refreshed on every mutation of the resource."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        cls = make_class(class_code="EXC-702", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-702")
        initial_updated_at = equip["updated_at"]
        set_clock("2026-08-05T12:00:00Z")
        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert after["updated_at"] != initial_updated_at


class TestIdleAlertBoundary:
    def test_four_day_streak_does_not_alert(self, api):
        """PRD section 3.7: "The alert flag is true exactly when the streak
        has reached 5 days, inclusive." At 4 consecutive IDLE days the flag
        is false and idle_streak_days == 4.

        Design: Corner/cross_cutting_layers/idle_alert_inclusive_boundary_at_five_days
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="EXC-703")
        equip = make_equipment(cls["id"], unit_tag="UNIT-703")
        set_clock("2026-08-05T00:00:00Z")
        data = validate_success(api.get_redeployment_score(equip["id"], _ADMIN))
        assert data["idle_streak_days"] == 4
        assert data["idle_alert"] is False

    def test_five_day_streak_triggers_alert(self, api):
        """PRD section 3.7: "The alert counts the unit's current run of
        consecutive calendar days spent `IDLE` with `maintenance_status`
        equal to `SERVICE_OK`, with no `RESERVED` assignment and no `PLANNED`
        or `EN_ROUTE` transport outstanding ... The alert flag is true
        exactly when the streak has reached 5 days, inclusive."

        Design: Corner/cross_cutting_layers/idle_alert_inclusive_boundary_at_five_days
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="EXC-703")
        equip = make_equipment(cls["id"], unit_tag="UNIT-703")
        set_clock("2026-08-06T00:00:00Z")
        data = validate_success(api.get_redeployment_score(equip["id"], _ADMIN))
        assert data["idle_streak_days"] == 5
        assert data["idle_alert"] is True


class TestImmediateConsistency:
    def test_ledger_visible_immediately_after_assignment_close(self, api):
        """PRD section 3.6: "All of this lands at once. ... `allocated_cents`
        posts to the project's `billed_total_cents`. The project's
        `active_assignment_count` is recomputed." Window is [08-03, 08-04)
        (one day) with a single active reading -> allocated 10000.

        Design: Corner/consistency_model/ledger_visible_immediately_after_assignment_close
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-800", daily_rate_cents=10000)
        project = make_project(project_code="PRJ-800")
        equip = make_equipment(cls["id"], unit_tag="UNIT-800")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-04")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])

        proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj["billed_total_cents"] == 10000
        assert proj["active_assignment_count"] == 0

    def test_chargeback_visible_immediately_after_confirm(self, api):
        """PRD section 3.8: "A confirmed report moves `ASSESSED` →
        `CONFIRMED`, stamps `confirmed_charge_cents` equal to the assessed
        figure, and posts it to the project's `billed_total_cents`."

        Design: Corner/consistency_model/chargeback_visible_immediately_after_confirm
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"], description="mirror",
                               line_items=[{"description": "mirror", "amount_cents": 10000}])
        assess_damage(d["id"])
        confirmed = confirm_damage(d["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_charge_cents"] == 10000
        proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj["billed_total_cents"] == 10000
