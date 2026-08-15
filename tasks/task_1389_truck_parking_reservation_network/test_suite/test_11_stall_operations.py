"""Stall operations: half-open interval semantics, out-of-service
reassignment and cancellation fallback, check-in gating on a dead stall, and
the availability conservation invariant."""
from test_helpers import (
    ADMIN,
    OP_ALICE,
    ApiErrorId,
    api_client,
    create_booking_payload,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    register_driver,
    register_drivers,
    set_clock,
    validate_error,
    validate_success,
)


def _availability(site_id, window_start, window_end):
    resp = api_client.get_site_availability(
        site_id, ADMIN,
        params={"window_start": window_start, "window_end": window_end})
    return validate_success(resp)


class TestHalfOpenIntervals:

    def _setup_single_stall_site(self):
        ctx = create_site_with_stalls(num_reservable=1)
        drivers = register_drivers(3, "CDL-Y")
        set_clock("2026-08-01T00:00:00Z")
        return ctx, drivers

    def test_back_to_back_departure_arrival_legal(self):
        """PRD section 3.4: "Two bookings on the same stall may never overlap
        in time — intervals are half-open, so the daily 11:00Z-to-15:00Z
        turnover gap makes same-day back-to-back stays legal — and an
        overlapping non-terminal booking on the requested stall is
        `ERR_STALL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stall_half_open_interval_back_to_back
        """
        ctx, drivers = self._setup_single_stall_site()
        stall = ctx["reservable"][0]
        b1 = create_reserved_booking(drivers[0]["id"], ctx["site"]["id"],
                                     "2026-08-10", 1)
        assert b1["stall_id"] == stall["id"]

        b2 = create_reserved_booking(drivers[1]["id"], ctx["site"]["id"],
                                     "2026-08-11", 1)
        assert b2["stall_id"] == stall["id"], (
            "B1 departs at 11:00Z and B2's window opens at 15:00Z: half-open "
            "adjacency lets the same stall serve both"
        )

    def test_overlapping_request_naming_stall_rejected(self):
        """PRD section 3.4: "Two bookings on the same stall may never overlap
        in time — intervals are half-open, so the daily 11:00Z-to-15:00Z
        turnover gap makes same-day back-to-back stays legal — and an
        overlapping non-terminal booking on the requested stall is
        `ERR_STALL_WINDOW_CONFLICT`."
        PRD section 3.4: "An explicitly supplied `stall_id` is validated
        against the same pool, class, and site rules, with mismatches rejected
        as `ERR_STALL_NOT_RESERVABLE` and window conflicts as
        `ERR_STALL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stall_half_open_interval_back_to_back
        """
        ctx, drivers = self._setup_single_stall_site()
        stall = ctx["reservable"][0]
        create_reserved_booking(drivers[0]["id"], ctx["site"]["id"],
                                "2026-08-10", 1)

        resp = api_client.create_booking(
            create_booking_payload(drivers[2]["id"], ctx["site"]["id"],
                                   "2026-08-10", stall_id=stall["id"]),
            make_driver_headers(drivers[2]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALL_WINDOW_CONFLICT)


class TestAvailabilityConservation:

    WINDOW = ("2026-08-10T15:00:00Z", "2026-08-11T11:00:00Z")

    def _setup_two_stall_site_with_probe(self):
        ctx = create_site_with_stalls(num_reservable=2)
        site = ctx["site"]
        driver = register_driver("CDL-K-1", "K One")
        set_clock("2026-08-01T00:00:00Z")
        free0 = _availability(site["id"], *self.WINDOW)["reservable_free"]
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)
        free1 = _availability(site["id"], *self.WINDOW)["reservable_free"]
        return {"site": site, "driver": driver, "booking": booking,
                "free0": free0, "free1": free1}

    def test_stall_free_count_conserved_across_create_and_cancel(self):
        """PRD section 3.2: "The response reports `reservable_total`,
        `reservable_free`, `first_come_total`, and `first_come_free` for the
        requested window."
        PRD section 3.5: "Either way the stall is released for the booking's
        window and a waitlist offer scan runs at the site."

        Design: Difficulty/compensating_invariant/stall_free_count_conserved_across_create_and_cancel
        """
        ctx = self._setup_two_stall_site_with_probe()
        assert ctx["free0"] == 2
        assert ctx["free1"] == 1, "the create consumes exactly one free stall"

        resp = api_client.cancel_booking(
            ctx["booking"]["id"], make_driver_headers(ctx["driver"]["id"]))
        validate_success(resp, expected_status=200)

        free2 = _availability(ctx["site"]["id"], *self.WINDOW)["reservable_free"]
        assert free2 == 2, (
            f"the cancel restores exactly one free stall: 2 -> 1 -> 2, got "
            f"{free2}"
        )

    def test_cancel_inside_free_window_charges_nothing(self):
        """PRD section 3.5: "At or before `checkin_open_at` minus the site's
        `cancellation_free_window_hours` — an inclusive boundary —
        cancellation is free: `fee_cents` is 0 and `billing_status` becomes
        `WAIVED`."

        Design: Difficulty/compensating_invariant/stall_free_count_conserved_across_create_and_cancel
        """
        ctx = self._setup_two_stall_site_with_probe()
        resp = api_client.cancel_booking(
            ctx["booking"]["id"], make_driver_headers(ctx["driver"]["id"]))
        cancelled = validate_success(resp, expected_status=200)
        assert cancelled["fee_cents"] == 0, (
            "clock 2026-08-01 is at or before the 2026-08-09T15:00Z free "
            "boundary"
        )
        assert cancelled["billing_status"] == "WAIVED"


class TestOutOfService:

    def test_checkin_rejected_when_stall_out_of_service(self):
        """PRD section 3.5: "The assigned stall must still be `ACTIVE`; a
        stall taken out of service after its booking's window opened rejects
        check-in with `ERR_STALL_OUT_OF_SERVICE`."
        PRD section 3.1: "`BOOKED` bookings whose check-in window has already
        opened keep the dead stall, and their check-in attempt then fails with
        `ERR_STALL_OUT_OF_SERVICE`; guests already on site (`CHECKED_IN`,
        `OVERSTAY`) are not displaced."

        Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_stall_out_of_service
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site, stall = ctx["site"], ctx["reservable"][0]
        driver = register_driver("CDL-X-1", "X One")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)

        set_clock("2026-08-10T15:30:00Z")
        resp = api_client.update_stall(site["id"], stall["id"],
                                       {"status": "OUT_OF_SERVICE"}, OP_ALICE)
        validate_success(resp, expected_status=200)

        resp = api_client.check_in_booking(booking["id"],
                                           make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_STALL_OUT_OF_SERVICE)

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "BOOKED", \
            "the rejected check-in leaves the lifecycle untouched"

    def test_dead_stall_kept_once_window_open(self):
        """PRD section 3.1: "`BOOKED` bookings whose check-in window has
        already opened keep the dead stall, and their check-in attempt then
        fails with `ERR_STALL_OUT_OF_SERVICE`; guests already on site
        (`CHECKED_IN`, `OVERSTAY`) are not displaced."
        PRD section 3.1: "Taking a stall out of service triggers a
        reassignment cascade: every `BOOKED` booking on that stall whose
        check-in window has not yet opened — `checkin_open_at` still in the
        future — is moved to a replacement stall".

        Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_stall_out_of_service
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site, stall = ctx["site"], ctx["reservable"][0]
        driver = register_driver("CDL-X-1", "X One")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)
        assert booking["stall_id"] == stall["id"]

        set_clock("2026-08-10T15:30:00Z")
        resp = api_client.update_stall(site["id"], stall["id"],
                                       {"status": "OUT_OF_SERVICE"}, OP_ALICE)
        validate_success(resp, expected_status=200)

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["stall_id"] == stall["id"], (
            "the window had already opened, so the reassignment cascade "
            "spares this booking and it keeps the dead stall"
        )
        assert after["status"] == "BOOKED"

    def test_stall_out_of_service_reassignment_and_cancellation_fallback(self):
        """PRD section 3.1: "Taking a stall out of service triggers a
        reassignment cascade: every `BOOKED` booking on that stall whose
        check-in window has not yet opened — `checkin_open_at` still in the
        future — is moved to a replacement stall chosen from those that are
        `ACTIVE`, in the same pool (`is_reservable`) and `stall_class`, and
        free for the booking's entire window, with the lowest `stall_number`
        in lexicographic order winning; the booking's `stall_id` is updated
        accordingly. When no eligible replacement exists, the booking is
        cancelled instead — fee waived, `billing_status` `WAIVED` — and a
        waitlist offer scan runs."

        Design: Corner/endpoints/stall_out_of_service_reassignment_and_cancellation_fallback
        """
        ctx = create_site_with_stalls(num_reservable=2)
        site = ctx["site"]
        r01, r02 = ctx["reservable"]
        site2_ctx = create_site_with_stalls(num_reservable=1, name="T")
        site2, t01 = site2_ctx["site"], site2_ctx["reservable"][0]
        dx = register_driver("CDL-RA-1", "R Aye")
        dy = register_driver("CDL-RB-1", "R Bee")
        set_clock("2026-08-01T00:00:00Z")
        b1 = create_reserved_booking(dx["id"], site["id"], "2026-08-10", 1)
        assert b1["stall_id"] == r01["id"]
        b2 = create_reserved_booking(dy["id"], site2["id"], "2026-08-10", 1)
        assert b2["stall_id"] == t01["id"]

        resp = api_client.update_stall(site["id"], r01["id"],
                                       {"status": "OUT_OF_SERVICE"}, OP_ALICE)
        validate_success(resp, expected_status=200)
        resp = api_client.update_stall(site2["id"], t01["id"],
                                       {"status": "OUT_OF_SERVICE"}, OP_ALICE)
        validate_success(resp, expected_status=200)

        resp = api_client.get_booking(b1["id"], ADMIN)
        after1 = validate_success(resp)
        assert after1["status"] == "BOOKED"
        assert after1["stall_id"] == r02["id"], \
            "reassigned to R02, the lowest-numbered eligible stall"

        resp = api_client.get_booking(b2["id"], ADMIN)
        after2 = validate_success(resp)
        assert after2["status"] == "CANCELLED", \
            "no eligible replacement exists on the second site"
        assert after2["billing_status"] == "WAIVED"
        assert after2["fee_cents"] == 0
