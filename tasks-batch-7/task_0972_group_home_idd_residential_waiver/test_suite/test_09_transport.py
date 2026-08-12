"""Day-program transport: vehicle overlap, capacity slots, per-leg DAY_PROG
authorization, clock-driven completion (PRD 3.9).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    admit_resident,
    create_active_isp,
    create_active_authorization,
    create_transport_leg_payload,
    create_transport_trip_payload,
    get_success_data,
    set_clock,
    setup_agency_with_core_staff,
    setup_enrolled_individual,
    setup_home,
    api_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]


def _setup_trip_ready(api):
    """Home + resident moved in + ACTIVE ISP + ACTIVE DAY_PROG authorization."""
    base = setup_agency_with_core_staff()
    agency, cm, q = base["agency"], base["cm"], base["q"]
    home = setup_home(agency, certified_bed_count=2)
    ind = setup_enrolled_individual(agency, cm, q)
    set_clock("2026-06-01T00:00:00Z")
    isp = create_active_isp(ind, cm, q)
    auth = create_active_authorization(ind, isp, cm, q, service_code="DAY_PROG")
    admit_resident(home, ind, cm, q, bed_label="R1", move_in_date="2026-06-01")
    return {"base": base, "home": home, "ind": ind, "auth": auth, "cm": cm, "q": q}


class TestVehicleOverlapAdjacency:
    """Vehicle half-open overlap keyed by (vehicle_id, trip_date) (PRD 3.9)."""

    def test_adjacent_departure_at_prior_return_accepted(self, api):
        """PRD 3.9: "The vehicle-overlap rule rejects any new trip whose
        half-open window from `depart_at` to `return_at` intersects an existing
        non-`CANCELLED` trip for the same key, with touching endpoints
        permitted".

        Design: Corner/validations/vehicle_overlap_adjacency_allowed
        """
        s = _setup_trip_ready(api)
        legs = [create_transport_leg_payload(s["ind"]["id"])]
        get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(s["home"]["id"], legs), ADMIN,
        ))
        # Adjacent: departs exactly at the first trip's return_at.
        legs2 = [create_transport_leg_payload(
            s["ind"]["id"],
            pickup_at="2026-06-02T11:00:00Z", dropoff_at="2026-06-02T12:00:00Z",
        )]
        t2 = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], legs2,
                depart_at="2026-06-02T11:00:00Z", return_at="2026-06-02T12:30:00Z",
            ), ADMIN,
        ))
        assert t2["status"] == "SCHEDULED"

    def test_overlapping_same_vehicle_rejected_but_other_vehicle_ok(self, api):
        """PRD 3.9: "a violation rejects with `ERR_VEHICLE_OVERLAP` (HTTP 409)"
        and "the vehicle-overlap resource key is the pair of `vehicle_id` and
        `trip_date`".

        Design: Corner/validations/vehicle_overlap_adjacency_allowed
        """
        s = _setup_trip_ready(api)
        legs = [create_transport_leg_payload(s["ind"]["id"])]
        get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(s["home"]["id"], legs), ADMIN,
        ))
        # Overlapping window on the SAME vehicle -> rejected.
        bad_legs = [create_transport_leg_payload(
            s["ind"]["id"],
            pickup_at="2026-06-02T10:30:00Z", dropoff_at="2026-06-02T11:00:00Z",
        )]
        resp = api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], bad_legs,
                depart_at="2026-06-02T10:30:00Z", return_at="2026-06-02T12:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_OVERLAP)
        # Same window on a DIFFERENT vehicle -> accepted (different key).
        t3 = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], bad_legs, vehicle_id="VAN-2",
                depart_at="2026-06-02T10:30:00Z", return_at="2026-06-02T12:00:00Z",
            ), ADMIN,
        ))
        assert t3["status"] == "SCHEDULED"


class TestVehicleCapacityWheelchairSlots:
    """Wheelchair legs consume 2 slots; total must not exceed 8 (PRD 3.9)."""

    def _setup_five_wheelchair_individuals(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=6)
        inds = [
            setup_enrolled_individual(agency, cm, q, legal_name=f"Ind {n}", mobility_level="WHEELCHAIR")
            for n in ("1", "2", "3", "4", "5")
        ]
        set_clock("2026-06-01T00:00:00Z")
        return home, inds

    def test_five_wheelchair_legs_exceed_capacity(self, api):
        """PRD 3.9: "The trip's `occupied_slots` is the sum over legs of 2 for
        a wheelchair seat and 1 otherwise, and the total must not exceed 8; a
        violation rejects with `ERR_VEHICLE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/vehicle_capacity_wheelchair_double_slots
        """
        home, inds = self._setup_five_wheelchair_individuals(api)
        legs = [
            create_transport_leg_payload(ind["id"], wheelchair_seat=True)
            for ind in inds
        ]
        resp = api_client.create_transport_trip(
            create_transport_trip_payload(home["id"], legs), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED)

    def test_ambulatory_leg_counts_one_slot(self, api):
        """PRD 3.9: "the sum over legs of 2 for a wheelchair seat and 1
        otherwise".

        Design: Corner/state_machines/transport_trip_auto_completes_after_return
        """
        s = _setup_trip_ready(api)
        legs = [create_transport_leg_payload(s["ind"]["id"], wheelchair_seat=False)]
        trip = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(s["home"]["id"], legs), ADMIN,
        ))
        assert trip["occupied_slots"] == 1


class TestTransportLegDayProgGate:
    """Each leg individual needs an ACTIVE DAY_PROG authorization (PRD 3.9)."""

    def test_leg_with_only_res_hab_rejected(self, api):
        """PRD 3.9: "must hold an `ACTIVE` `DAY_PROG` authorization whose span
        covers `trip_date` — otherwise the create is rejected with
        `ERR_NO_DAY_PROG_AUTHORIZATION` (HTTP 409)."

        Design: Corner/validations/transport_leg_requires_day_prog_authorization
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        isp = create_active_isp(ind, cm, q)
        # RES_HAB only — no DAY_PROG.
        create_active_authorization(
            ind, isp, cm, q, service_code="RES_HAB", unit_type="DAY",
            authorized_units=300, rate_cents=15000,
        )
        admit_resident(home, ind, cm, q, bed_label="R1")
        resp = api_client.create_transport_trip(
            create_transport_trip_payload(
                home["id"], [create_transport_leg_payload(ind["id"])],
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NO_DAY_PROG_AUTHORIZATION)

    def test_leg_with_active_day_prog_accepted(self, api):
        """PRD 3.9: "must hold an `ACTIVE` `DAY_PROG` authorization whose span
        covers `trip_date`" — the satisfied gate lets the trip be created.

        Design: Corner/validations/transport_leg_requires_day_prog_authorization
        """
        s = _setup_trip_ready(api)
        trip = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], [create_transport_leg_payload(s["ind"]["id"])],
            ), ADMIN,
        ))
        assert trip["status"] == "SCHEDULED"


class TestTransportTripAutoCompletes:
    """Clock-driven SCHEDULED -> COMPLETED (PRD 3.9)."""

    def test_trip_completes_after_clock_passes_return(self, api):
        """PRD 3.9: "The system clock moves a `SCHEDULED` trip to the terminal
        state `COMPLETED` when it advances past `return_at`."

        Design: Corner/state_machines/transport_trip_auto_completes_after_return
        """
        s = _setup_trip_ready(api)
        trip = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], [create_transport_leg_payload(s["ind"]["id"])],
            ), ADMIN,
        ))
        assert trip["status"] == "SCHEDULED"
        set_clock("2026-06-03T00:00:00Z")
        after = get_success_data(api_client.get_transport_trip(trip["id"], ANY))
        assert after["status"] == "COMPLETED"

    def test_trip_remains_scheduled_before_return(self, api):
        """PRD 3.9: the clock moves a trip to COMPLETED only "when it advances
        past `return_at`" — before that the trip stays SCHEDULED.

        Design: Corner/state_machines/transport_trip_auto_completes_after_return
        """
        s = _setup_trip_ready(api)
        trip = get_success_data(api_client.create_transport_trip(
            create_transport_trip_payload(
                s["home"]["id"], [create_transport_leg_payload(s["ind"]["id"])],
            ), ADMIN,
        ))
        before = get_success_data(api_client.get_transport_trip(trip["id"], ANY))
        assert before["status"] == "SCHEDULED"
