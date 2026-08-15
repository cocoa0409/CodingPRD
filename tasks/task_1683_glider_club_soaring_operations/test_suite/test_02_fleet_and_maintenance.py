"""Fleet registry, maintenance log, airframe currency, and grounding cascades."""
import pytest

from test_helpers import (
    assert_aircraft,
    assert_maintenance_record,
    book_reservation,
    checkout_reservation,
    close_ops_day,
    complete_flight,
    create_aircraft,
    create_maintenance_record,
    create_member,
    create_tier,
    create_tow_slot,
    get_aircraft,
    get_flight,
    get_reservation,
    land_flight,
    post_flight,
    set_clock,
    validate_paginated,
    validate_success,
)


class TestMaintenanceLog:
    def test_maintenance_record_is_immutable_log_entry(self, api, club_admin_headers):
        """PRD §2.4: "The one exception is the maintenance log. A
        `MaintenanceRecord` is an immutable log entry and carries only `id`
        and `created_at`; both `updated_at` and `version` are absent from it."

        Design: Corner/entities/maintenance_record_immutable_no_version
        """
        aircraft = create_aircraft("N001G", "GLIDER", "2027-01-01T00:00:00Z")
        resp = api.create_maintenance_record(
            aircraft["id"],
            {
                "kind": "REPAIR",
                "performed_at": "2026-08-05T10:00:00Z",
                "hobbs_hours_at_service": 12.5,
                "notes": "canopy latch",
            },
            club_admin_headers,
        )
        record = validate_success(resp, 201)
        assert_maintenance_record(record)
        assert record["aircraft_id"] == aircraft["id"]
        assert record["kind"] == "REPAIR"

        list_resp = api.list_maintenance_records(aircraft["id"], club_admin_headers)
        entries, _ = validate_paginated(list_resp)
        assert len(entries) == 1
        assert entries[0]["id"] == record["id"]
        assert_maintenance_record(entries[0])


def _fly_glider_hours(tier_code, registration, land_clock_takeoff, landed_at):
    """One reconciled flight on a fresh glider; returns (glider, tow_pilot).

    The slot window spans 2026-08-19 so both the takeoff and a multi-day
    airborne sortie are legal; dues-free tier with 99 included tows keeps the
    ledger out of the picture.
    """
    tier = create_tier(tier_code=tier_code, monthly_dues_cents=0, included_tows_per_month=99)
    pilot = create_member(tier["id"], full_name="Boundary Pilot")
    tow_pilot = create_member(tier["id"], full_name="Boundary Tow", is_tow_pilot=True)
    glider = create_aircraft(registration, "GLIDER")
    tow_plane = create_aircraft(registration + "T", "TOW_PLANE")
    slot = create_tow_slot(
        tow_plane["id"], tow_pilot["id"],
        "2026-08-19T08:00:00Z", "2026-08-19T23:00:00Z", 10,
    )
    set_clock("2026-08-19T08:10:00Z")
    complete_flight(
        pilot["id"], glider["id"], slot["id"],
        res_start="2026-08-19T08:00:00Z", res_end="2026-08-19T23:00:00Z",
        takeoff_at=land_clock_takeoff, landed_at=landed_at,
        reconcile_officer_id=tow_pilot["id"],
    )
    return glider, tow_pilot


class TestInspectionBoundary:
    def test_99_9_hours_stays_airworthy_after_close(self, api):
        """PRD §2.8: "An airframe is currency-legal only while **both** of the
        following hold: `hours_since_inspection` is strictly below 100.0 hours
        — exactly 100.0 hours fails — and `annual_due_date` lies strictly in
        the future — a deadline exactly equal to the current instant fails."
        PRD §3.9: "The same close sweeps the fleet per §2.8: every `AIRWORTHY`
        airframe whose `hours_since_inspection` has reached 100.0 hours, or
        whose `annual_due_date` has arrived, moves to `GROUNDED` with the
        corresponding reason".

        Design: Difficulty/boundary_precision_check/inspection_100h_exact_boundary
        """
        # 5994-minute sortie = 99.9 hours, strictly below the 100.0 limit.
        glider, _ = _fly_glider_hours(
            "BND", "N900G", "2026-08-19T08:15:00Z", "2026-08-23T12:09:00Z"
        )
        set_clock("2026-08-23T13:00:00Z")
        close_ops_day()
        after = get_aircraft(glider["id"])
        assert_aircraft(after)
        assert after["hours_since_inspection"] == pytest.approx(99.9)
        assert after["status"] == "AIRWORTHY", "99.9 < 100.0 passes the currency sweep"

    def test_100_0_hours_grounds_after_close(self, api):
        """PRD §2.8: "An airframe is currency-legal only while **both** of the
        following hold: `hours_since_inspection` is strictly below 100.0 hours
        — exactly 100.0 hours fails — and `annual_due_date` lies strictly in
        the future — a deadline exactly equal to the current instant fails."
        PRD §3.9: "The same close sweeps the fleet per §2.8: every `AIRWORTHY`
        airframe whose `hours_since_inspection` has reached 100.0 hours, or
        whose `annual_due_date` has arrived, moves to `GROUNDED` with the
        corresponding reason — `INSPECTION_OVERDUE` winning when both fail
        together".

        Design: Difficulty/boundary_precision_check/inspection_100h_exact_boundary
        """
        # 6000-minute sortie = exactly 100.0 hours; the strict less-than fails.
        glider, _ = _fly_glider_hours(
            "BND2", "N901G", "2026-08-19T08:15:00Z", "2026-08-23T12:15:00Z"
        )
        set_clock("2026-08-23T13:00:00Z")
        close_ops_day()
        after = get_aircraft(glider["id"])
        assert_aircraft(after)
        assert after["hours_since_inspection"] == pytest.approx(100.0)
        assert after["status"] == "GROUNDED"
        assert after["grounded_reason"] == "INSPECTION_OVERDUE"


def _setup_cascade_scenario():
    """Glider at 99.5 hours (one reconciled 5970-minute flight), a future
    BOOKED reservation standing on it, and a second reservation checked out
    for the triggering 30-minute sortie."""
    tier = create_tier(tier_code="CASC", monthly_dues_cents=0, included_tows_per_month=99)
    pilot = create_member(tier["id"], full_name="Cascade Pilot")
    booker = create_member(tier["id"], full_name="Future Booker")
    tow_pilot = create_member(tier["id"], full_name="Cascade Tow", is_tow_pilot=True)
    glider = create_aircraft("N500G", "GLIDER")
    tow_plane = create_aircraft("N501T", "TOW_PLANE")
    slot = create_tow_slot(
        tow_plane["id"], tow_pilot["id"],
        "2026-08-10T07:00:00Z", "2026-08-19T20:00:00Z", 5,
    )
    # First sortie: 5970 minutes = 99.5 hours, reconciled.
    set_clock("2026-08-10T08:05:00Z")
    complete_flight(
        pilot["id"], glider["id"], slot["id"],
        res_start="2026-08-10T08:00:00Z", res_end="2026-08-10T20:00:00Z",
        takeoff_at="2026-08-10T08:10:00Z", landed_at="2026-08-14T11:40:00Z",
        reconcile_officer_id=tow_pilot["id"],
    )
    # Future BOOKED reservation the grounding cascade must cancel.
    future_res = book_reservation(
        glider["id"], booker["id"], "2026-08-25T10:00:00Z", "2026-08-25T12:00:00Z"
    )
    # Second reservation for the triggering sortie.
    set_clock("2026-08-19T08:05:00Z")
    trigger_res = book_reservation(
        glider["id"], pilot["id"], "2026-08-19T08:00:00Z", "2026-08-19T10:00:00Z"
    )
    checkout_reservation(trigger_res["id"], pilot["id"])
    flight = post_flight(
        trigger_res["id"], slot["id"], 1500, "2026-08-19T08:10:00Z", pilot["id"]
    )
    return {
        "pilot": pilot, "booker": booker, "tow_pilot": tow_pilot,
        "glider": glider, "slot": slot, "future_res": future_res,
        "trigger_res": trigger_res, "flight": flight,
    }


class TestLandingAccrualGroundingCascade:
    def test_landing_accrual_grounds_airframe_at_100h(self, api):
        """PRD §3.6: "The glider's `total_time_hours` and
        `hours_since_inspection` each grow by `flight_minutes` converted to
        hours."
        PRD §3.6: "Immediately after accrual, both airframes are re-checked
        against the §2.8 currency rule: if the new hours pushed
        `hours_since_inspection` to 100.0 or beyond, or the annual deadline
        has arrived, that airframe grounds in-request with the matching
        `grounded_reason`, and the full §3.3 grounding cascade fires".

        Design: Difficulty/transitive_cascade/land_accrual_grounds_airframe_cancels_reservation
        """
        ctx = _setup_cascade_scenario()
        resp = land_flight(ctx["flight"]["id"], "2026-08-19T08:40:00Z", ctx["pilot"]["id"])
        assert resp["status"] == "LANDED", "the triggering flight itself completes normally"

        glider = get_aircraft(ctx["glider"]["id"])
        assert glider["hours_since_inspection"] == pytest.approx(100.0), (
            "99.5 h accrued plus the 30-minute sortie must total exactly 100.0"
        )
        assert glider["status"] == "GROUNDED"
        assert glider["grounded_reason"] == "INSPECTION_OVERDUE"

    def test_grounding_cascade_cancels_future_booked_reservation(self, api):
        """PRD §3.6: "that airframe grounds in-request with the matching
        `grounded_reason`, and the full §3.3 grounding cascade fires — future
        `BOOKED` reservations on it cancel, and for the tow plane, future
        `SCHEDULED` slots cancel."
        PRD §3.3: "Whatever the route, grounding an airframe cancels every
        `BOOKED` reservation on that airframe whose `start_at` lies in the
        future".

        Design: Difficulty/transitive_cascade/land_accrual_grounds_airframe_cancels_reservation
        """
        ctx = _setup_cascade_scenario()
        land_flight(ctx["flight"]["id"], "2026-08-19T08:40:00Z", ctx["pilot"]["id"])

        cancelled = get_reservation(ctx["future_res"]["id"])
        assert cancelled["status"] == "CANCELLED", (
            "the grounding cascade cancels future BOOKED reservations on the airframe"
        )
        flight = get_flight(ctx["flight"]["id"])
        assert flight["status"] == "LANDED"


class TestMaintenanceRestoresCurrency:
    def test_inspection_record_restores_currency(self, api):
        """PRD §3.3: "An `INSPECTION_100H` record resets the airframe's
        `hours_since_inspection` to 0."
        PRD §3.3: "When a logged record restores currency on a grounded
        airframe whose `grounded_reason` is anything other than `MANUAL`, the
        airframe returns to `AIRWORTHY` and `grounded_reason` clears; a
        manually grounded airframe is not restored by paperwork."

        Design: Corner/endpoints/maintenance_record_restores_currency
        """
        tier = create_tier(tier_code="MX", monthly_dues_cents=0, included_tows_per_month=99)
        pilot = create_member(tier["id"], full_name="Maint Pilot")
        tow_pilot = create_member(tier["id"], full_name="Maint Tow", is_tow_pilot=True)
        glider = create_aircraft("N018G", "GLIDER")
        tow_plane = create_aircraft("N019T", "TOW_PLANE")
        slot = create_tow_slot(
            tow_plane["id"], tow_pilot["id"],
            "2026-08-19T08:00:00Z", "2026-08-19T23:00:00Z", 3,
        )
        set_clock("2026-08-19T08:10:00Z")
        # 6000 minutes = exactly 100.0 hours; the landing grounds the glider
        # in-request (PRD §3.6).
        ctx_res = complete_flight(
            pilot["id"], glider["id"], slot["id"],
            res_start="2026-08-19T08:00:00Z", res_end="2026-08-19T23:00:00Z",
            takeoff_at="2026-08-19T08:15:00Z", landed_at="2026-08-23T12:15:00Z",
        )
        assert ctx_res["status"] == "LANDED"
        grounded = get_aircraft(glider["id"])
        assert grounded["status"] == "GROUNDED"
        assert grounded["hours_since_inspection"] == pytest.approx(100.0)

        create_maintenance_record(
            glider["id"], "INSPECTION_100H", "2026-08-23T13:00:00Z", 100.0
        )
        restored = get_aircraft(glider["id"])
        assert restored["hours_since_inspection"] == pytest.approx(0.0)
        assert restored["status"] == "AIRWORTHY"
        assert restored["grounded_reason"] is None
