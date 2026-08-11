"""Cross-entity state gates: route pass reads the registration's state,
activation reads the holder's compliance dimension, reservation reads the
station's state (PRD §2.6 stage 8, §3.5, §3.7, §3.8).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, deposit, get_holder,
    setup_active_registration, setup_route, setup_station,
    setup_barred_holder, create_full_equipment_lsv,
    create_draft_registration, finalize_inspection_for_registration,
    create_insurance,
    create_route_pass_payload, create_charging_reservation_payload,
    COMMUNITY_ADMIN,
    ApiErrorId,
)


class TestRoutePassRequiresRegistrationActive:
    def test_suspended_registration_rejected_with_not_active(self):
        """PRD §3.7: "Booking requires the route to be `DESIGNATED` (otherwise
        `ERR_ROUTE_NOT_DESIGNATED`, HTTP 422), the registration to be `ACTIVE`
        (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 422), and the holder to be
        `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`)."

        Design: Difficulty/cross_entity_state_dependency/route_pass_requires_registration_active
        """
        ctx = setup_active_registration(
            community_name="C-CE1", fleet_program_enabled=True,
            deposit_cents=100000, insurance_overrides={"policy_number": "N-CE1"})
        holder = ctx["holder"]
        reg = ctx["registration"]
        validate_success(api_client.suspend_registration(reg["id"], COMMUNITY_ADMIN), 200)
        route = setup_route(ctx["community"]["id"], name="R-CE1",
                            route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
        res = api_client.create_route_pass(
            create_route_pass_payload(route["id"], reg["id"], holder["id"]),
            make_permit_holder_headers(holder["id"]))
        validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE, expected_status=422)

    def test_rejected_booking_creates_no_route_pass_row(self):
        """PRD §3.7: "A holder books a route pass by supplying `route_id`,
        `registration_id`, `holder_id`, `start_at`, and `end_at`. Booking requires
        the route to be `DESIGNATED` (otherwise `ERR_ROUTE_NOT_DESIGNATED`, HTTP
        422), the registration to be `ACTIVE` (otherwise
        `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 422), and the holder to be `ELIGIBLE`
        (otherwise `ERR_HOLDER_NOT_ELIGIBLE`)."

        Design: Difficulty/cross_entity_state_dependency/route_pass_requires_registration_active
        """
        ctx = setup_active_registration(
            community_name="C-CE1", fleet_program_enabled=True,
            deposit_cents=100000, insurance_overrides={"policy_number": "N-CE1"})
        holder = ctx["holder"]
        reg = ctx["registration"]
        validate_success(api_client.suspend_registration(reg["id"], COMMUNITY_ADMIN), 200)
        route = setup_route(ctx["community"]["id"], name="R-CE1",
                            route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
        res = api_client.create_route_pass(
            create_route_pass_payload(route["id"], reg["id"], holder["id"]),
            make_permit_holder_headers(holder["id"]))
        assert res.status_code == 422
        _, meta = validate_paginated(
            api_client.list_route_passes(COMMUNITY_ADMIN,
                                         params={"registration_id": reg["id"]}))
        assert meta["total_count"] == 0, "no RoutePass row may be created"


class TestActivationRequiresHolderNotBarred:
    def _setup_ce2(self):
        """ELIGIBLE holder barred via 3 x 4-point UPHELD violations; DRAFT
        registration with PASSED inspection, ACTIVE insurance, wallet 100000."""
        barred = setup_barred_holder(community_name="C-CE2", violations=3,
                                     points_each=4,
                                     occurred_at="2026-04-01T00:00:00Z")
        community = barred["community"]
        holder = barred["holder"]
        assert holder["compliance_status"] == "BARRED"
        holder = deposit(holder["id"], 100000, holder["version"])
        vehicle = create_full_equipment_lsv(holder["id"])
        registration = create_draft_registration(vehicle["id"], holder["id"],
                                                 registration_year=2026)
        finalize_inspection_for_registration(registration["id"], score=90)
        create_insurance(holder["id"], vehicle["id"], policy_number="N-CE2")
        return community, holder, vehicle, registration

    def test_barred_holder_activation_rejected(self):
        """PRD §3.5: "the holder must be `ELIGIBLE` (otherwise
        `ERR_HOLDER_NOT_ELIGIBLE`, HTTP 422) and must not be `BARRED` (otherwise
        `ERR_HOLDER_BARRED`, HTTP 422)"
        PRD §3.9: "Standing follows fixed thresholds — `BARRED` at 12 points or
        more (exactly 12 is `BARRED`), `PROBATION` at 4 through 11 points, and
        `GOOD_STANDING` at 3 or fewer"

        Design: Difficulty/cross_entity_state_dependency/activation_requires_holder_not_barred
        """
        _, holder, _, registration = self._setup_ce2()
        hh = make_permit_holder_headers(holder["id"])
        res = api_client.activate_registration(registration["id"], hh)
        validate_error(res, ApiErrorId.ERR_HOLDER_BARRED, expected_status=422)

    def test_rejected_activation_leaves_draft_and_wallet_unchanged(self):
        """PRD §3.5: "Activation moves a registration `DRAFT` → `ACTIVE` and is
        performed by the holder. It is gated on the full compliance picture: the
        most recently finalized inspection for the registration must be `PASSED`
        (otherwise `ERR_INSPECTION_NOT_PASSED`, HTTP 422); when the community's
        `insurance_required` is true, an `ACTIVE` policy must cover the
        registration's vehicle (otherwise `ERR_INSURANCE_MISSING`, HTTP 422); the
        holder must be `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`, HTTP 422)
        and must not be `BARRED` (otherwise `ERR_HOLDER_BARRED`, HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/activation_requires_holder_not_barred
        """
        _, holder, _, registration = self._setup_ce2()
        hh = make_permit_holder_headers(holder["id"])
        res = api_client.activate_registration(registration["id"], hh)
        assert res.status_code == 422
        reg_after = get_success_data(
            api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
        assert reg_after["status"] == "DRAFT"
        assert get_holder(holder["id"])["wallet_balance_cents"] == 100000


class TestReservationRequiresStationOnline:
    def _setup_ce3(self):
        """Station taken OFFLINE by CommunityAdmin; holder wallet 1000."""
        community = create_community(name="C-CE3")
        holder = create_eligible_holder(community["id"], full_name="H CE3",
                                        birth_date="2010-05-01")
        holder = deposit(holder["id"], 1000, holder["version"])
        station = setup_station(community["id"], name="S-CE3", slot_count=2,
                                rate_cents_per_min=10)
        validate_success(api_client.set_station_offline(station["id"], COMMUNITY_ADMIN), 200)
        return community, holder, station

    def test_offline_station_rejected_with_station_offline(self):
        """PRD §3.8: "The station must be `ONLINE`, or the booking is rejected with
        `ERR_STATION_OFFLINE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_station_online
        """
        _, holder, station = self._setup_ce3()
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        validate_error(res, ApiErrorId.ERR_STATION_OFFLINE, expected_status=409)

    def test_rejected_booking_leaves_wallet_unchanged(self):
        """PRD §3.8: "The fee charged at booking is the reservation's duration in
        minutes — any fractional minute rounded up — multiplied by the station's
        `rate_cents_per_min`, subject to a minimum charge of 200 cents; the
        computed `fee_cents` is debited from the holder's wallet immediately"
        PRD §3.8: "The station must be `ONLINE`, or the booking is rejected with
        `ERR_STATION_OFFLINE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_station_online
        """
        _, holder, station = self._setup_ce3()
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        assert res.status_code == 409
        assert get_holder(holder["id"])["wallet_balance_cents"] == 1000, (
            "no debit may happen on a rejected booking")
