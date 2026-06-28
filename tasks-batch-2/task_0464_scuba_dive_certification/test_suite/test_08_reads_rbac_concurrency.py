"""FK-filtered reads, an action endpoint, the clock default, RBAC denials,
optimistic-concurrency outcomes, and immediate-consistency on create.

Queue B (Corner): sections endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_shop_admin_headers, make_instructor_headers, make_diver_headers,
    make_unknown_role_headers,
    create_diver, create_course, create_instructor, create_boat, create_enrollment,
    create_session, create_dive_trip, create_rental, sign_waiver,
    create_waiver_cleared_diver, set_clock, book_seat, certify_diver_open_water,
    setup_trip_with_certified_diver,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


class TestFilteredReadsAndActions:
    def test_gear_service_cancel_success(self, api):
        """PRD 3.9: "A `ShopAdmin` may instead cancel an `OPEN` order, driving it
        `OPEN → CANCELLED` with no further side effects".

        Design: Corner/endpoints/gear_service_cancel_success
        """
        diver = create_diver(full_name="Gsc Gus")
        order = get_success_data(
            api.create_gear_service_order(
                f.create_gear_service_order_payload(diver["id"], service_type="VIP"), ADMIN
            )
        )
        cancelled = validate_success(api.cancel_gear_service_order(order["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED", cancelled

    def test_list_fill_services_by_diver(self, api):
        """PRD 3.9: "Fill services can be fetched individually or listed (optionally
        filtered by `diver_id`)."
        PRD 3.9: "An `AIR` fill is priced at the base alone." (base 1200)

        Design: Corner/endpoints/list_fill_services_by_diver
        """
        diver = create_diver(full_name="Fl Flo")
        get_success_data(
            api.create_fill_service(
                f.create_fill_service_payload(
                    diver["id"], gas="AIR", o2_pct=21, tank_capacity_liters=10
                ), ADMIN,
            )
        )
        data, meta = validate_paginated(
            api.list_fill_services(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert data[0]["price_cents"] == 1200, data

    def test_list_gear_service_orders_by_diver(self, api):
        """PRD 3.9: "Orders can be fetched individually or listed (optionally
        filtered by `diver_id`)."

        Design: Corner/endpoints/list_gear_service_orders_by_diver
        """
        diver = create_diver(full_name="Gso Gabe")
        order = get_success_data(
            api.create_gear_service_order(
                f.create_gear_service_order_payload(diver["id"], service_type="HYDRO"), ADMIN
            )
        )
        data, meta = validate_paginated(
            api.list_gear_service_orders(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(o["id"] == order["id"] for o in data), data

    def test_list_sessions_by_instructor(self, api):
        """PRD 3.4: a session references "the `primary_instructor_id` who will lead
        it" and per the endpoint table sessions are listable "(optionally by course
        or instructor)".

        Design: Corner/endpoints/list_sessions_by_instructor
        """
        course = create_course()
        instructor = create_instructor(full_name="Ls Lou")
        session = create_session(
            course["id"], instructor["id"], session_type="POOL",
            starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T10:00:00Z",
        )
        data, meta = validate_paginated(
            api.list_sessions(ADMIN, params={"primary_instructor_id": instructor["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(s["id"] == session["id"] for s in data), data

    def test_list_dive_trips_by_boat(self, api):
        """PRD 3.7: "A `ShopAdmin` schedules a dive trip on a boat, supplying the
        `boat_id`" and trips are listable "(optionally by boat)".

        Design: Corner/endpoints/list_dive_trips_by_boat
        """
        boat = create_boat(name="Lst Boat", capacity=6)
        trip = create_dive_trip(
            boat["id"], starts_at="2026-07-01T08:00:00Z",
            ends_at="2026-07-01T12:00:00Z", min_cert_level="OPEN_WATER",
            base_fare_cents=10000, fill_addon_cents=0,
        )
        data, meta = validate_paginated(
            api.list_dive_trips(ADMIN, params={"boat_id": boat["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(t["id"] == trip["id"] for t in data), data

    def test_list_waivers_by_diver(self, api):
        """PRD 3.1: "waivers can be retrieved individually or listed (optionally
        filtered by `diver_id`)."

        Design: Corner/endpoints/list_waivers_by_diver
        """
        set_clock("2026-06-01T00:00:00Z")
        diver = create_diver(full_name="Wl Walt")
        waiver = sign_waiver(diver["id"])
        data, meta = validate_paginated(
            api.list_waivers(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(w["id"] == waiver["id"] for w in data), data

    def test_list_session_bookings_by_session(self, api):
        """PRD 3.5: "Bookings can be retrieved individually or listed (optionally
        filtered by `session_id` or `enrollment_id`)."

        Design: Corner/endpoints/list_session_bookings_by_session
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Sbl Inst")
        diver = create_waiver_cleared_diver(full_name="Sbl Sal")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], session["version"])
        data, meta = validate_paginated(
            api.list_session_bookings(ADMIN, params={"session_id": session["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(b["id"] == booking["id"] for b in data), data

    def test_list_rentals_by_diver(self, api):
        """PRD 3.8: "Agreements can be fetched individually or listed (optionally
        filtered by `diver_id`)."

        Design: Corner/endpoints/list_rentals_by_diver
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Rl Ray")
        rental = create_rental(
            diver["id"], item_description="Fins",
            daily_rate_cents=4500, deposit_cents=10000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        data, meta = validate_paginated(
            api.list_rental_agreements(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(r["id"] == rental["id"] for r in data), data

    def test_list_trip_bookings_by_diver(self, api):
        """PRD 3.7: "Trip bookings can be fetched individually or listed (optionally
        filtered by `trip_id` or `diver_id`)."

        Design: Corner/endpoints/list_trip_bookings_by_diver
        """
        boat, trip, diver = setup_trip_with_certified_diver(
            trip_overrides={"min_cert_level": "OPEN_WATER",
                            "base_fare_cents": 10000, "fill_addon_cents": 0},
            diver_full_name="Tbl Tess",
        )
        trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
        tb = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver["id"], trip_now["version"], tanks=0, party_size=1
                ), ADMIN,
            ), expected_status=201,
        )
        data, meta = validate_paginated(
            api.list_trip_bookings(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(b["id"] == tb["id"] for b in data), data

    def test_list_certification_cards_by_enrollment(self, api):
        """PRD 3.6: "Cards are immutable; they can be fetched individually or
        listed, optionally filtered by `diver_id` or `enrollment_id`."
        PRD 3.6: "a `level` mirroring the course's `course_type`".

        Design: Corner/endpoints/list_certification_cards_by_enrollment
        """
        diver, course, enr, _card = certify_diver_open_water(diver_full_name="Cce Cleo")
        data, meta = validate_paginated(
            api.list_certification_cards(ADMIN, params={"enrollment_id": enr["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert data[0]["level"] == "OPEN_WATER", data
        assert data[0]["enrollment_id"] == enr["id"], data


class TestClockDefault:
    def test_clock_default_before_any_set(self, api):
        """PRD 2.4: "On startup the clock reads exactly `2026-01-01T00:00:00Z`, and
        until it is explicitly set it remains at that value and never falls back to
        the host's wall-clock time."
        PRD 3.1: "computes `expires_at` as `signed_at` plus exactly 365 days."

        Design: Corner/errors/clock_set_then_default_behavior
        """
        diver = create_diver(full_name="Def Dot")
        waiver = validate_success(
            api.create_waiver(
                f.create_waiver_payload(diver["id"], medical_flagged=False), ADMIN
            ), expected_status=201,
        )
        assert waiver["signed_at"].startswith("2026-01-01T00:00:00"), waiver
        assert waiver["expires_at"].startswith("2027-01-01T00:00:00"), waiver


class TestRbac:
    def test_diver_cannot_create_course(self, api):
        """PRD 2.1: "When a request carries valid headers but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD 3.2: "The shop's offerings are defined by a `ShopAdmin`."

        Design: Corner/rbac/diver_cannot_create_course
        """
        diver = create_diver(full_name="Rb Rob")
        resp = api.create_course(
            {"title": "Sneaky", "course_type": "OPEN_WATER",
             "required_pool_sessions": 0, "required_open_water_sessions": 1,
             "price_cents": 50000},
            make_diver_headers(diver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    def test_diver_cannot_complete_session(self, api):
        """PRD 2.1: "When a request carries valid headers but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD 3.4: completing a session is reserved to "An `Instructor` who is the
        session's `primary_instructor_id`".

        Design: Corner/rbac/diver_cannot_complete_session
        """
        course = create_course()
        instructor = create_instructor(full_name="Rb2 Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T10:00:00Z",
        )
        diver = create_diver(full_name="Rb Rita")
        resp = api.complete_session(session["id"], make_diver_headers(diver["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_instructor_cannot_complete_other_instructors_session(self, api):
        """PRD 2.1: "an `Instructor` may complete a session or record attendance
        only when that session's `primary_instructor_id` equals `X-User-ID`."
        PRD 2.1: "When an entity-backed actor attempts to mutate a resource it does
        not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/instructor_cannot_complete_other_instructors_session
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        inst_a = create_instructor(full_name="Inst A")
        inst_b = create_instructor(full_name="Inst B")
        session = create_session(
            course["id"], inst_a["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        set_clock("2026-06-04T09:00:00Z")
        resp = api.complete_session(session["id"], make_instructor_headers(inst_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_unknown_role_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing, or if `X-User-Role` does not name
        a role the system recognizes, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles,
        spelled precisely as follows: `ShopAdmin`, `Instructor`, and `Diver`."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        resp = api.list_divers(make_unknown_role_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestOptimisticConcurrency:
    def test_session_book_correct_version_succeeds(self, api):
        """PRD 3.5: "A successful booking begins `BOOKED`, increments the session's
        `confirmed_seats`, and increments the session's `version` by one."
        PRD 2.7: "the request must carry `expected_session_version` holding the
        client's last observed `version` of that session."

        Design: Corner/cross_cutting_complexity_layers/occ_session_book_correct_version_succeeds
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Occ Inst")
        diver = create_waiver_cleared_diver(full_name="Occ Ola")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        booking = validate_success(
            api.create_session_booking(
                f.create_session_booking_payload(
                    session["id"], enr["id"], session["version"]
                ), ADMIN,
            ), expected_status=201,
        )
        assert booking["status"] == "BOOKED", booking
        sess_after = get_success_data(api.get_session(session["id"], ADMIN))
        assert sess_after["confirmed_seats"] == 1, sess_after
        assert sess_after["version"] == session["version"] + 1, sess_after

    def test_session_book_stale_version_conflict(self, api):
        """PRD 2.7: "a request whose `expected_session_version` does not equal the
        session's current `version` — meaning another writer has advanced the
        session since the client read it — is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_session_book_stale_version_conflict
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Stale Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        stale_version = session["version"]
        d1 = create_waiver_cleared_diver(full_name="Stale A")
        d2 = create_waiver_cleared_diver(full_name="Stale B")
        e1 = create_enrollment(d1["id"], course["id"])
        e2 = create_enrollment(d2["id"], course["id"])
        book_seat(session["id"], e1["id"], stale_version)  # advances version
        resp = api.create_session_booking(
            f.create_session_booking_payload(session["id"], e2["id"], stale_version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    def test_trip_book_stale_version_conflict(self, api):
        """PRD 2.7: "a request whose `expected_trip_version` does not equal the
        trip's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_trip_book_stale_version_conflict
        """
        boat, trip, diver1 = setup_trip_with_certified_diver(
            trip_overrides={"min_cert_level": "OPEN_WATER",
                            "base_fare_cents": 10000, "fill_addon_cents": 0},
            diver_full_name="Occ A",
        )
        diver2 = certify_diver_open_water(diver_full_name="Occ B")[0]
        diver2 = get_success_data(api.get_diver(diver2["id"], ADMIN))
        stale_version = get_success_data(api.get_dive_trip(trip["id"], ADMIN))["version"]
        # first booking advances trip.version
        validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver1["id"], stale_version, tanks=0, party_size=1
                ), ADMIN,
            ), expected_status=201,
        )
        resp = api.create_trip_booking(
            f.create_trip_booking_payload(
                trip["id"], diver2["id"], stale_version, tanks=0, party_size=1
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestImmediateConsistency:
    def test_completion_pct_present_on_create(self, api):
        """PRD 3.3: "A new enrollment begins in `ACTIVE` status with `elearning_pct`
        at 0, both attendance counters (`pool_sessions_attended` and
        `open_water_sessions_attended`) at 0, a freshly computed `completion_pct`".

        Design: Corner/consistency_model/immediate_visibility_on_create
        """
        course = create_course(
            title="OW Cert Full", course_type="OPEN_WATER",
            required_pool_sessions=1, required_open_water_sessions=1, price_cents=50000,
        )
        diver = create_diver(full_name="Imm Ivy")
        enr = validate_success(
            api.create_enrollment(
                f.create_enrollment_payload(diver["id"], course["id"]), ADMIN
            ), expected_status=201,
        )
        assert enr["completion_pct"] == 0, enr
        assert enr["status"] == "ACTIVE", enr
