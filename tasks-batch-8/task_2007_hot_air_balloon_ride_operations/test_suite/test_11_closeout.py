"""Post-landing closeout: the chase crew track, the flight CLOSE gate, photo
package delivery at the post-flight ceremony, and pilot internal currency from
closed flights (PRD §2.10, §3.6, §3.8)."""
from test_helpers import (
    assert_chase_assignment,
    assert_photo_package_record,
    chase_event,
    get_pilot,
    get_success_data,
    mark_flown,
    setup_landed_flight,
)


class TestChaseLifecycleAndCloseGate:
    def test_chase_assignment_full_lifecycle_and_close_gate(self, api, ops_headers):
        """PRD §3.6: "Dispatching moves the assignment `ASSIGNED → EN_ROUTE`.
        Arriving at the landing site — permitted only while the flight is
        `AIRBORNE` or `LANDED` — moves the assignment to `AT_LANDING` and
        records the `landing_lat` and `landing_lon` coordinates supplied with
        the event. Recovery moves it `AT_LANDING → RECOVERED`, and the final
        debrief moves it `RECOVERED → DEBRIEFED`."
        PRD §3.6: "Closing the flight is the final act, moving it `LANDED →
        CLOSED`, and it is permitted only when every chase assignment for the
        flight has reached `RECOVERED` or `DEBRIEFED` and every `CHECKED_IN`
        reservation has been advanced to `FLOWN` (or cancelled)."

        Design: Corner/state_machines/chase_assignment_full_lifecycle_and_close_gate
        """
        ctx = setup_landed_flight(party_weights=(180,), duration_hours=1.2)
        chase = ctx["chase"]
        reservation = ctx["reservation"]
        assert ctx["flight"]["status"] == "LANDED"
        assert ctx["flight"]["duration_hours"] == 1.2

        # The CLOSE gate requires every CHECKED_IN reservation advanced first.
        mark_flown(reservation)

        assert chase_event(chase["id"], "DISPATCH")["status"] == "EN_ROUTE"
        arrived = chase_event(
            chase["id"], "ARRIVE_AT_LANDING", landing_lat=35.18, landing_lon=-106.59
        )
        assert_chase_assignment(arrived)
        assert arrived["status"] == "AT_LANDING"
        assert arrived["landing_lat"] == 35.18
        assert arrived["landing_lon"] == -106.59
        assert chase_event(chase["id"], "RECOVER")["status"] == "RECOVERED"
        assert chase_event(chase["id"], "DEBRIEF")["status"] == "DEBRIEFED"

        closed = get_success_data(
            api.flight_event(ctx["flight"]["id"], {"event_type": "CLOSE"}, ops_headers)
        )
        assert closed["status"] == "CLOSED"


class TestPhotoPackageDelivery:
    def test_photo_package_delivered_on_complete(self, api, ops_headers):
        """PRD §3.4: "When `photo_package_tier` is anything other than `NONE`,
        the booking cascade-creates a `PhotoPackageRecord` for the reservation
        in `PENDING` status, with its `tier` copied from the reservation."
        PRD §3.6: "if a `PhotoPackageRecord` exists for the reservation in
        `PENDING`, it flips to `DELIVERED` with `photo_count` copied from the
        event payload and `delivered_at` stamped with the current instant."

        Design: Corner/cross_cutting_layers/photo_package_delivered_on_complete
        """
        ctx = setup_landed_flight(party_weights=(180,), photo_tier="STANDARD",
                                  duration_hours=1.0)
        reservation = ctx["reservation"]

        packages = get_success_data(api.list_photo_packages(reservation["id"], ops_headers))
        assert len(packages) == 1
        record = packages[0]
        assert_photo_package_record(record)
        assert record["tier"] == "STANDARD"
        assert record["status"] == "PENDING"
        assert record["photo_count"] == 0

        mark_flown(reservation)
        completed = get_success_data(
            api.reservation_event(
                reservation["id"], {"event_type": "COMPLETE", "photo_count": 24},
                ops_headers,
            )
        )
        assert completed["booking_status"] == "COMPLETED"

        packages_after = get_success_data(
            api.list_photo_packages(reservation["id"], ops_headers)
        )
        delivered = packages_after[0]
        assert delivered["id"] == record["id"]
        assert delivered["status"] == "DELIVERED"
        assert delivered["photo_count"] == 24, "photo_count copied from the ceremony payload"
        assert delivered["delivered_at"] is not None


class TestPilotInternalCurrency:
    def test_pilot_internal_currency_from_closed_flight(self, api, ops_headers):
        """PRD §3.6: "At close, the flight begins contributing to the pilot's
        internal currency: `internal_pic_hours_180d` and
        `internal_takeoffs_landings_90d` are recomputed, and with them the
        currency fields of §2.10."
        PRD §2.10: "`pic_hours_180d_total` is the sum of
        `external_pic_hours_180d` and `internal_pic_hours_180d`, and
        `takeoffs_landings_90d_total` is the sum of
        `external_takeoffs_landings_90d` and `internal_takeoffs_landings_90d`."

        Design: Corner/cross_cutting_layers/pilot_internal_currency_from_closed_flight
        """
        ctx = setup_landed_flight(with_booking=False, duration_hours=1.0)
        pilot_before = get_pilot(ctx["pilot"]["id"])
        assert pilot_before["internal_pic_hours_180d"] == 0
        assert pilot_before["internal_takeoffs_landings_90d"] == 0
        assert pilot_before["pic_hours_180d_total"] == 20.0
        assert pilot_before["takeoffs_landings_90d_total"] == 5

        chase = ctx["chase"]
        chase_event(chase["id"], "DISPATCH")
        chase_event(chase["id"], "ARRIVE_AT_LANDING", landing_lat=35.18,
                    landing_lon=-106.59)
        chase_event(chase["id"], "RECOVER")

        closed = get_success_data(
            api.flight_event(ctx["flight"]["id"], {"event_type": "CLOSE"}, ops_headers)
        )
        assert closed["status"] == "CLOSED"

        pilot_after = get_pilot(ctx["pilot"]["id"])
        assert pilot_after["internal_pic_hours_180d"] == 1.0, (
            "the closed 1.0-hour flight now feeds internal PIC hours"
        )
        assert pilot_after["internal_takeoffs_landings_90d"] == 1
        assert pilot_after["pic_hours_180d_total"] == 21.0
        assert pilot_after["takeoffs_landings_90d_total"] == 6
        assert pilot_after["currency_status"] == "CURRENT"
