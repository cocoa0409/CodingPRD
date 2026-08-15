"""Gate check-in: waiver safety, arrival windows, zone capacity/type, and the
lowest-free-spot selector."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_open_event, create_registrant_with_vehicle, create_registration,
    create_paid_registration, sign_waiver, check_in, get_zone,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]

WINDOW = {
    "arrival_window_start": "2026-08-15T08:00:00Z",
    "arrival_window_end": "2026-08-15T10:00:00Z",
}
ARRIVAL_CLOCK = "2026-08-15T08:30:00Z"


def _confirmed_with_window(api, waiver=True, zone_overrides=None, registrant_overrides=None):
    """Open event + windowed zone + paid registration (optionally waivered).

    Returns dict(event, cls, zone, registrant, vehicle, registration)."""
    ev, cls, zone = create_open_event(zone_overrides={**WINDOW, **(zone_overrides or {})})
    kwargs = registrant_overrides or {}
    reg, veh = create_registrant_with_vehicle(**kwargs)
    if waiver:
        sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"],
                    guardian_name="Parent Racer" if reg.get("is_minor") else None)
    registration = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
    get_success_data(api.set_clock({"to_iso8601": ARRIVAL_CLOCK}, ORG))
    return {"event": ev, "cls": cls, "zone": zone,
            "registrant": reg, "vehicle": veh, "registration": registration}


class TestCheckinRequiresWaiver:
    def test_checkin_without_waiver_rejected_then_sign_unblocks(self, api):
        """PRD §3.3: "a waiver must exist for the registrant and event, else
        `ERR_WAIVER_NOT_SIGNED`".

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_signed_waiver
        """
        s = _confirmed_with_window(api, waiver=False)
        resp = api.check_in_registration(s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_SIGNED)
        sign_waiver(s["event"]["id"], s["registrant"]["id"],
                    signature_name=s["registrant"]["full_name"])
        ok = validate_success(api.check_in_registration(
            s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK))
        assert ok["status"] == "CHECKED_IN"
        assert ok["spot_number"] == 1

    def test_checkin_success_sets_spot_and_zone_count(self, api):
        """PRD §3.3: "A successful check-in parks the car deterministically:
        `assigned_zone_id` is set to the chosen zone, `spot_number` receives the
        lowest free spot integer in that zone — spots are numbered from 1 up to
        `capacity` — `checked_in_at` records the clock, the zone's
        `assigned_count` rises by one".

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_signed_waiver
        """
        s = _confirmed_with_window(api)
        ok = validate_success(api.check_in_registration(
            s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK))
        assert ok["status"] == "CHECKED_IN"
        assert ok["spot_number"] == 1
        assert ok["assigned_zone_id"] == s["zone"]["id"]
        zone_after = get_zone(s["event"]["id"], s["zone"]["id"])
        assert zone_after["assigned_count"] == 1


class TestCheckinStateBeatsWaiverSafety:
    def _setup_withdrawn_no_waiver(self, api):
        """Registration withdrawn inside 48h (0% tier -> straight WITHDRAWN);
        no waiver ever signed; clock inside the arrival window."""
        s = _confirmed_with_window(api, waiver=False)
        # 08:30 on show day is 30 minutes before gates: 0% tier, direct WITHDRAWN.
        get_success_data(api.withdraw_registration(
            s["registration"]["id"], {"reason": "changed mind"}, DESK))
        return s

    def test_withdrawn_registration_checkin_reports_state_not_waiver(self, api):
        """PRD §2.9: "Because state preconditions sit at level 6, above safety at
        level 7, a stale registration state surfaces before a missing waiver is
        even considered — at the gate, `ERR_INVALID_REGISTRATION_STATE` beats
        `ERR_WAIVER_NOT_SIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_waiver_safety
        """
        s = self._setup_withdrawn_no_waiver(api)
        resp = api.check_in_registration(s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_STATE)

    def test_withdrawn_registration_checkin_leaves_no_spot(self, api):
        """PRD §3.4: "A zero tier — withdrawal inside 48 hours of gates open —
        terminates immediately in `WITHDRAWN`". PRD §3.3: "the registration must
        be `CONFIRMED`, else `ERR_INVALID_REGISTRATION_STATE` — and this state
        check is reported before any safety check is even considered."

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_waiver_safety
        """
        s = self._setup_withdrawn_no_waiver(api)
        api.check_in_registration(s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK)
        after = validate_success(api.get_registration(s["registration"]["id"], ORG))
        assert after["status"] == "WITHDRAWN"
        assert after["spot_number"] is None
        zone_after = get_zone(s["event"]["id"], s["zone"]["id"])
        assert zone_after["assigned_count"] == 0


class TestCheckinSideEffects:
    def test_checkin_assigns_lowest_spot_and_timestamp(self, api):
        """PRD §3.3: "`assigned_zone_id` is set to the chosen zone, `spot_number`
        receives the lowest free spot integer in that zone — spots are numbered
        from 1 up to `capacity` — `checked_in_at` records the clock, the zone's
        `assigned_count` rises by one, and the registration's `version`
        increments."

        Design: Corner/state_machines/checkin_assigns_lowest_spot_and_timestamp
        """
        s = _confirmed_with_window(api)
        ok = validate_success(api.check_in_registration(
            s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK))
        assert ok["status"] == "CHECKED_IN"
        assert ok["spot_number"] == 1
        assert ok["assigned_zone_id"] == s["zone"]["id"]
        assert ok["checked_in_at"] == ARRIVAL_CLOCK, "checked_in_at records the logical clock"
        assert get_zone(s["event"]["id"], s["zone"]["id"])["assigned_count"] == 1


class TestMinorWaiverGuardian:
    def test_minor_waiver_requires_guardian_rejected(self, api):
        """PRD §3.3: "when the registrant's `is_minor` flag is set,
        `guardian_name` is required and its absence is rejected with
        `ERR_GUARDIAN_SIGNATURE_REQUIRED`."

        Design: Corner/validations/minor_waiver_requires_guardian_rejected
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle(
            name="Kid", email="kid@example.com", is_minor=True)
        resp = api.create_waiver(
            {"event_id": ev["id"], "registrant_id": reg["id"],
             "signature_name": "Kid Racer"}, DESK)
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED)
        ok = validate_success(api.create_waiver(
            {"event_id": ev["id"], "registrant_id": reg["id"],
             "signature_name": "Kid Racer", "guardian_name": "Parent Racer"}, DESK),
            expected_status=201)
        assert ok["signed_at"], "signed_at is stamped from the logical clock"


class TestArrivalWindowAndZoneRules:
    def test_checkin_outside_arrival_window_rejected(self, api):
        """PRD §3.3: "when the chosen zone declares an arrival window, the logical
        clock must sit inside the half-open interval from `arrival_window_start`
        to `arrival_window_end`, else `ERR_OUTSIDE_ARRIVAL_WINDOW`."

        Design: Corner/validations/checkin_outside_arrival_window_rejected
        """
        s = _confirmed_with_window(api)
        # The window end is exclusive: exactly 10:00:00 is outside.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T10:00:00Z"}, ORG))
        resp = api.check_in_registration(s["registration"]["id"], {"zone_id": s["zone"]["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_ARRIVAL_WINDOW)
        after = validate_success(api.get_registration(s["registration"]["id"], ORG))
        assert after["status"] == "CONFIRMED"
        assert after["spot_number"] is None

    def test_zone_full_at_checkin_rejected(self, api):
        """PRD §3.3: "the zone must still have room, `assigned_count` below
        `capacity`, else `ERR_ZONE_FULL`."

        Design: Corner/validations/zone_full_at_checkin_rejected
        """
        ev, cls, zone = create_open_event(zone_overrides={**WINDOW, "capacity": 1})
        regs = []
        for i, (yr, make, model) in enumerate([(1970, "Ford", "Mustang"),
                                               (1971, "Chevrolet", "Chevelle")]):
            reg, veh = create_registrant_with_vehicle(
                name=f"F{i}", email=f"f{i}@example.com",
                vehicle_overrides={"year": yr, "make": make, "model": model})
            sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
            regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"]))
        get_success_data(api.set_clock({"to_iso8601": ARRIVAL_CLOCK}, ORG))
        first = validate_success(api.check_in_registration(regs[0]["id"], {"zone_id": zone["id"]}, DESK))
        assert first["spot_number"] == 1
        resp = api.check_in_registration(regs[1]["id"], {"zone_id": zone["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_ZONE_FULL)
        after = validate_success(api.get_registration(regs[1]["id"], ORG))
        assert after["status"] == "CONFIRMED"

    def test_checkin_into_vendor_zone_rejected(self, api):
        """PRD §3.3: "the zone's `zone_type` must be `SHOW_FIELD` or `OVERFLOW` —
        driving a show car into a `VENDOR_ROW` is rejected with
        `ERR_ZONE_TYPE_INELIGIBLE`".

        Design: Corner/validations/checkin_into_vendor_zone_rejected
        """
        ev, cls, zone = create_open_event(
            zone_overrides={"name": "Vendor Row", "zone_type": "VENDOR_ROW",
                            "capacity": 10, "has_power": True})
        reg, veh = create_registrant_with_vehicle(name="ZT2", email="zt2@example.com")
        sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
        registration = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        get_success_data(api.set_clock({"to_iso8601": ARRIVAL_CLOCK}, ORG))
        resp = api.check_in_registration(registration["id"], {"zone_id": zone["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_ZONE_TYPE_INELIGIBLE)


class TestZoneOccupancyConservation:
    def _setup_three_confirmed(self, api):
        ev, cls, zone = create_open_event(
            zone_overrides={**WINDOW, "capacity": 10})
        regs = []
        for i, (yr, make, model) in enumerate([(1970, "Ford", "Mustang"),
                                               (1971, "Chevrolet", "Chevelle"),
                                               (1972, "Pontiac", "GTO")]):
            reg, veh = create_registrant_with_vehicle(
                name=f"S{i}", email=f"s{i}@example.com",
                vehicle_overrides={"year": yr, "make": make, "model": model})
            sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
            regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"]))
        get_success_data(api.set_clock({"to_iso8601": ARRIVAL_CLOCK}, ORG))
        return ev, zone, regs

    def test_spot_sequence_and_count_consistency(self, api):
        """PRD §3.3: "A successful check-in parks the car deterministically:
        `assigned_zone_id` is set to the chosen zone, `spot_number` receives the
        lowest free spot integer in that zone". PRD §3.1: "on `SHOW_FIELD` and
        `OVERFLOW` zones it is the number of registrations parked there with
        status `CHECKED_IN`".

        Design: Difficulty/compensating_invariant/zone_occupancy_conserved_checkin_withdraw
        """
        ev, zone, regs = self._setup_three_confirmed(api)
        c1 = check_in(regs[0]["id"], zone["id"])
        c2 = check_in(regs[1]["id"], zone["id"])
        assert c1["spot_number"] == 1
        assert c2["spot_number"] == 2
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 2

    def test_freed_spot_reused_as_lowest_free(self, api):
        """PRD §3.3: "When a checked-in car later pulls out, its freed spot
        returns to the pool and can be handed out again as the lowest free spot."

        Design: Difficulty/compensating_invariant/zone_occupancy_conserved_checkin_withdraw
        """
        ev, zone, regs = self._setup_three_confirmed(api)
        check_in(regs[0]["id"], zone["id"])
        check_in(regs[1]["id"], zone["id"])
        get_success_data(api.withdraw_registration(regs[0]["id"], {"reason": "engine trouble"}, DESK))
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 1
        c3 = check_in(regs[2]["id"], zone["id"])
        assert c3["spot_number"] == 1, "freed spot 1 is reused (lowest free spot)"
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 2
