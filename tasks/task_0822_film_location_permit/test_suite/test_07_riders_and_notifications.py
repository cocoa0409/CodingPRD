"""Drone-rider safety/temporal precedence and neighborhood-notification lead time."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


class TestRiderSafetyBeatsTemporal:
    def test_missing_aviation_coverage_reported_over_flight_window(self, api):
        """PRD §3.6: "If the rider's rider_type is DRONE, the application must already have a
        VERIFIED InsuranceCertificate whose aviation_coverage is true; if none exists, the rider
        is rejected with ERR_AVIATION_COVERAGE_MISSING (HTTP 422)."
        PRD §3.6: "When both apply, aviation coverage is checked before the flight-window
        containment."

        Design: Difficulty/priority_pair_validation_conflict/rider_safety_beats_temporal
        """
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="P5b", contact_email="5b@x.test", primary_contact="E")
        app = th.make_application(api, pc["id"], title="P5b", synopsis="x")  # shoot 06-01 08:00..18:00
        resp = api.add_rider(app["id"], {"rider_type": "DRONE", "faa_waiver_number": "FAA-Z",
                                         "max_altitude_ft": 300, "flight_start_at": "2026-06-05T09:00:00Z",
                                         "flight_end_at": "2026-06-05T12:00:00Z"},
                             th.make_production_company_headers(pc["id"]))
        validate_error(resp, ApiErrorId.ERR_AVIATION_COVERAGE_MISSING.value)

    def test_temporal_error_not_returned_when_coverage_also_missing(self, api):
        """PRD §3.6: "When both apply, aviation coverage is checked before the flight-window
        containment."
        PRD §3.6: "Additionally, a drone rider's flight window — from flight_start_at to
        flight_end_at — must lie entirely within the application's shoot window from
        shoot_start_at to shoot_end_at; a flight window that starts before the shoot begins or
        ends after the shoot ends is rejected with ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/rider_safety_beats_temporal
        """
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="P5b2", contact_email="5b2@x.test", primary_contact="E2")
        app = th.make_application(api, pc["id"], title="P5b2", synopsis="x")
        # Flight window also outside the shoot, and no aviation COI: safety pre-empts temporal.
        resp = api.add_rider(app["id"], {"rider_type": "DRONE", "faa_waiver_number": "FAA-Y",
                                         "max_altitude_ft": 250, "flight_start_at": "2026-07-01T09:00:00Z",
                                         "flight_end_at": "2026-07-01T12:00:00Z"},
                             th.make_production_company_headers(pc["id"]))
        err = validate_error(resp, ApiErrorId.ERR_AVIATION_COVERAGE_MISSING.value)
        assert err["error_id"] != ApiErrorId.ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT.value


class TestNotificationLeadDaysBoundary:
    def _app_shoot_seven_days_out(self, api, company_name):
        th.set_clock(api, "2026-06-01T08:00:00Z")
        pc = th.make_company(api, legal_name=company_name, contact_email=f"{company_name}@x.test", primary_contact="F")
        app = th.make_application(api, pc["id"], title=company_name, synopsis="x",
                                  shoot_start_at="2026-06-08T08:00:00Z",
                                  shoot_end_at="2026-06-08T20:00:00Z")
        return app

    def test_notification_accepted_at_exactly_seven_days(self, api):
        """PRD §3.7: "That lead time must be at least 7 days; if lead_days is fewer than 7, the
        notification is rejected with ERR_NOTICE_TOO_LATE (HTTP 422)."

        Design: Difficulty/boundary_precision_check/notification_lead_days_boundary
        """
        app = self._app_shoot_seven_days_out(api, "P6aCo")
        resp = api.create_notification(app["id"], {"geo_zone": "Z1", "notice_method": "MAILED"},
                                       th.make_coordinator_headers())
        validate_success(resp, 201)

    def test_lead_days_computed_as_seven_at_boundary(self, api):
        """PRD §3.7: "the system ... derives lead_days as the whole number of days between the
        notice and the shoot start — specifically, the difference between the application's
        shoot_start_at and the current clock value, divided into whole 86,400-second days and
        rounded down."

        Design: Difficulty/boundary_precision_check/notification_lead_days_boundary
        """
        app = self._app_shoot_seven_days_out(api, "P6a2Co")
        resp = api.create_notification(app["id"], {"geo_zone": "Z1", "notice_method": "POSTED"},
                                       th.make_coordinator_headers())
        data = validate_success(resp, 201)
        assert data["lead_days"] == 7


def test_notification_too_late_below_boundary(api):
    """PRD §3.7: "That lead time must be at least 7 days; if lead_days is fewer than 7, the
    notification is rejected with ERR_NOTICE_TOO_LATE (HTTP 422)."

    Design: Corner/validations/notification_too_late_boundary_fail
    """
    th.set_clock(api, "2026-06-02T08:00:00Z")
    pc = th.make_company(api, legal_name="Late Co", contact_email="lt@x.test", primary_contact="EE")
    app = th.make_application(api, pc["id"], title="Late", synopsis="x",
                              shoot_start_at="2026-06-08T08:00:00Z",
                              shoot_end_at="2026-06-08T20:00:00Z")  # 6 days out
    resp = api.create_notification(app["id"], {"geo_zone": "Z1", "notice_method": "MAILED"},
                                   th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_NOTICE_TOO_LATE.value)


def test_drone_flight_window_outside_shoot_with_verified_coi(api):
    """PRD §3.6: "Additionally, a drone rider's flight window — from flight_start_at to
    flight_end_at — must lie entirely within the application's shoot window from shoot_start_at
    to shoot_end_at; a flight window that starts before the shoot begins or ends after the shoot
    ends is rejected with ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT (HTTP 422)."

    Design: Corner/validations/drone_flight_outside_shoot_with_verified_coi
    """
    th.set_clock(api, th.DEFAULT_CLOCK)
    pc = th.make_company(api, legal_name="Fly Co", contact_email="fly@x.test", primary_contact="GG")
    app = th.make_application(api, pc["id"], title="Fly", synopsis="x")  # shoot 06-01 08:00..18:00
    coi = th.add_coi(api, app["id"], pc["id"], policy_number="POL-Fly", aviation_coverage=True)
    th.verify_coi(api, coi["id"])
    resp = api.add_rider(app["id"], {"rider_type": "DRONE", "faa_waiver_number": "FAA-Q",
                                     "max_altitude_ft": 150, "flight_start_at": "2026-06-10T09:00:00Z",
                                     "flight_end_at": "2026-06-10T12:00:00Z"},
                         th.make_production_company_headers(pc["id"]))
    validate_error(resp, ApiErrorId.ERR_FLIGHT_WINDOW_OUTSIDE_SHOOT.value)
