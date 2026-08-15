"""Neighbor notifications: blackout dates, quiet hours, daily delivery cap."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS,
    create_project_payload, create_neighbor_notification_payload,
    create_project, set_clock,
    assert_iso8601_instant,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]


class TestDeliveryRules:
    def test_deliver_on_blackout_date_rejected(self):
        """PRD §3.6: "One: the logical-clock calendar date must not appear in the
        project's `blackout_dates`, else `ERR_BLACKOUT_DATE`."

        Design: Corner/validations/deliver_on_blackout_date_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="Blackout", address="64 Pine St", lot_area_sqft=12000,
                                 blackout_dates=["2026-08-10"])
        nn = get_success_data(
            api_client.create_neighbor_notification(
                project["id"],
                create_neighbor_notification_payload(address="66 Pine St",
                                                     scheduled_delivery_date="2026-08-10"),
                SUPERVISOR,
            )
        )
        set_clock("2026-08-10T10:00:00Z")
        resp = api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_DATE)
        listed, _ = validate_paginated(
            api_client.list_neighbor_notifications(project["id"], SUPERVISOR)
        )
        assert listed[0]["status"] == "PENDING_DELIVERY"

    def test_quiet_hours_delivery_occupation_window(self):
        """PRD §3.6: "Two: the delivery's occupation — the half-open interval from
        the current logical time to thirty minutes later — must not intersect the
        nightly quiet window, the half-open interval from 19:00 inclusive to
        07:00 exclusive UTC; a delivery whose occupation touches that window is
        rejected with `ERR_QUIET_HOURS`."

        Design: Difficulty/resource_temporal_overlap/quiet_hours_delivery_occupation_window
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="Quiet Lot", address="75 Elm St", lot_area_sqft=20000,
                                 blackout_dates=["2026-08-10"])
        pid = project["id"]
        n1 = get_success_data(
            api_client.create_neighbor_notification(
                pid, create_neighbor_notification_payload(address="77 Elm St"), SUPERVISOR)
        )
        n2 = get_success_data(
            api_client.create_neighbor_notification(
                pid, create_neighbor_notification_payload(
                    address="79 Elm St", notice_method="DOOR_HANGER"), SUPERVISOR)
        )
        n3 = get_success_data(
            api_client.create_neighbor_notification(
                pid, create_neighbor_notification_payload(
                    address="81 Elm St", notice_method="POSTING"), SUPERVISOR)
        )
        # 07:00:00 — occupation [07:00, 07:30) clears the quiet window.
        set_clock("2026-08-03T07:00:00Z")
        d1 = get_success_data(
            api_client.transition_neighbor_notification(n1["id"], {"action": "DELIVER"}, SUPERVISOR)
        )
        assert_iso8601_instant(d1["delivered_at"], "2026-08-03T07:00:00Z")
        # 18:30:00 — occupation [18:30, 19:00) ends exactly at quiet start: allowed.
        set_clock("2026-08-03T18:30:00Z")
        d2 = get_success_data(
            api_client.transition_neighbor_notification(n2["id"], {"action": "DELIVER"}, SUPERVISOR)
        )
        assert_iso8601_instant(d2["delivered_at"], "2026-08-03T18:30:00Z")
        # 18:45:00 — occupation [18:45, 19:15) crosses 19:00: rejected.
        set_clock("2026-08-03T18:45:00Z")
        resp = api_client.transition_neighbor_notification(n3["id"], {"action": "DELIVER"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_QUIET_HOURS)

    def test_quiet_hours_deep_night_delivery_rejected(self):
        """PRD §3.6: "Two: the delivery's occupation — the half-open interval from
        the current logical time to thirty minutes later — must not intersect the
        nightly quiet window, the half-open interval from 19:00 inclusive to
        07:00 exclusive UTC; a delivery whose occupation touches that window is
        rejected with `ERR_QUIET_HOURS`."

        Design: Difficulty/resource_temporal_overlap/quiet_hours_delivery_occupation_window
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="QuietNight", address="75B Elm St", lot_area_sqft=20000)
        nn = get_success_data(
            api_client.create_neighbor_notification(
                project["id"], create_neighbor_notification_payload(address="83 Elm St"),
                SUPERVISOR)
        )
        # 23:00 is deep inside [19:00, 07:00).
        set_clock("2026-08-03T23:00:00Z")
        resp = api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_QUIET_HOURS)

    def test_daily_delivery_cap_fourth_rejected(self):
        """PRD §3.6: "Three: fewer than three other notifications of the same
        project may already stand `DELIVERED` on the same UTC calendar date; the
        fourth delivery on one date is rejected with `ERR_DAILY_DELIVERY_CAP`."
        PRD §2.5: "no more than three notification deliveries may land on the
        same project on the same UTC date"

        Design: Corner/validations/daily_delivery_cap_fourth_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="CapDay", address="68 Pine St", lot_area_sqft=12000)
        pid = project["id"]
        ids = []
        for i, method in enumerate(("CERTIFIED_MAIL", "DOOR_HANGER", "POSTING", "CERTIFIED_MAIL")):
            nn = get_success_data(
                api_client.create_neighbor_notification(
                    pid,
                    create_neighbor_notification_payload(
                        address=f"N{i + 1}", notice_method=method,
                        scheduled_delivery_date="2026-08-03"),
                    SUPERVISOR,
                )
            )
            ids.append(nn["id"])
        for hour, nn_id in zip((8, 9, 10), ids[:3]):
            set_clock(f"2026-08-03T{hour:02d}:00:00Z")
            get_success_data(
                api_client.transition_neighbor_notification(nn_id, {"action": "DELIVER"}, SUPERVISOR)
            )
        # Fourth delivery on the same UTC date is rejected.
        set_clock("2026-08-03T11:00:00Z")
        resp = api_client.transition_neighbor_notification(ids[3], {"action": "DELIVER"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_DAILY_DELIVERY_CAP)
        # The same notification delivers successfully on the next UTC date.
        set_clock("2026-08-04T08:00:00Z")
        ok = get_success_data(
            api_client.transition_neighbor_notification(ids[3], {"action": "DELIVER"}, SUPERVISOR)
        )
        assert ok["status"] == "DELIVERED"

    def test_third_delivery_same_date_allowed(self):
        """PRD §3.6: "Three: fewer than three other notifications of the same
        project may already stand `DELIVERED` on the same UTC calendar date; the
        fourth delivery on one date is rejected with `ERR_DAILY_DELIVERY_CAP`."

        Design: Corner/validations/daily_delivery_cap_fourth_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="CapThree", address="68B Pine St", lot_area_sqft=12000)
        pid = project["id"]
        for i in range(3):
            nn = get_success_data(
                api_client.create_neighbor_notification(
                    pid,
                    create_neighbor_notification_payload(address=f"M{i + 1}"),
                    SUPERVISOR,
                )
            )
            set_clock(f"2026-08-03T{8 + i:02d}:00:00Z")
            ok = get_success_data(
                api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
            )
            assert ok["status"] == "DELIVERED"
