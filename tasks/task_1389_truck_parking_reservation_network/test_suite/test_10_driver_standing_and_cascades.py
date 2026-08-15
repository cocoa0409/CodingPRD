"""Driver standing: strikes, the SUSPENDED threshold, and the
suspension cascade over future bookings."""
from test_helpers import (
    ADMIN,
    OP_ALICE,
    ApiErrorId,
    api_client,
    check_in,
    create_booking_payload,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    register_driver,
    run_site_ops,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_driver_with_four_bookings():
    """Driver with four 1-night bookings: 08-03, 08-04, 08-05 (the no-show
    strikes) and 08-20 (the future booking the cascade cancels)."""
    ctx = create_site_with_stalls(num_reservable=2)
    site = ctx["site"]
    driver = register_driver("CDL-N-1", "N One")
    set_clock("2026-08-01T00:00:00Z")
    b1 = create_reserved_booking(driver["id"], site["id"], "2026-08-03", 1)
    b2 = create_reserved_booking(driver["id"], site["id"], "2026-08-04", 1)
    b3 = create_reserved_booking(driver["id"], site["id"], "2026-08-05", 1)
    b4 = create_reserved_booking(driver["id"], site["id"], "2026-08-20", 1)
    return {"site": site, "driver": driver, "b1": b1, "b2": b2, "b3": b3,
            "b4": b4}


def _run_three_noshow_sweeps(site_id):
    for day in ("2026-08-03", "2026-08-04", "2026-08-05"):
        set_clock(f"{day}T16:00:01Z")
        run_site_ops(site_id)


class TestNoShowSuspensionCascade:

    def test_third_noshow_suspends_driver(self):
        """PRD section 3.3: "The `strikes_90d` counter sums the weights of
        entries whose `at` falls on or after the clock minus 90 days. Standing
        derives from it: `strikes_90d` of 3 or more means `SUSPENDED`, exactly
        2 means `PROBATION`, and anything less means `GOOD`."
        PRD section 3.5: "a `NO_SHOW` strike of weight one is appended to the
        driver's `strike_events` with standing recomputed. If the recomputed
        `strikes_90d` reaches at least 3, the driver's `standing` becomes
        `SUSPENDED`".

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_cancels_future_booking
        """
        ctx = _setup_driver_with_four_bookings()
        _run_three_noshow_sweeps(ctx["site"]["id"])

        resp = api_client.get_driver(ctx["driver"]["id"], ADMIN)
        d = validate_success(resp)
        assert d["strikes_90d"] == 3, \
            "the third no-show crosses the >= 3 threshold"
        assert d["standing"] == "SUSPENDED"

        resp = api_client.get_booking(ctx["b1"]["id"], ADMIN)
        b1 = validate_success(resp)
        assert b1["status"] == "NO_SHOW"
        assert b1["fee_cents"] == 4500, \
            "the no-show fee is the full first pinned night's rate"

    def test_suspension_cancels_future_bookings_fee_free(self):
        """PRD section 3.5: "If the recomputed `strikes_90d` reaches at least
        3, the driver's `standing` becomes `SUSPENDED` and every other
        `BOOKED` booking of that driver whose `checkin_open_at` is still in
        the future is cancelled with `fee_cents` 0 and `billing_status`
        `WAIVED`, each releasing its stall and triggering its own waitlist
        offer scan."
        PRD section 3.5: "Cancellations issued by the system itself — the
        fleet-overdue cascade, a fleet closure, the driver-suspension cascade,
        or a failed stall reassignment — never charge: `fee_cents` and
        `final_total_cents` are both 0 and `billing_status` becomes `WAIVED`".

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_cancels_future_booking
        """
        ctx = _setup_driver_with_four_bookings()
        _run_three_noshow_sweeps(ctx["site"]["id"])

        resp = api_client.get_booking(ctx["b4"]["id"], ADMIN)
        b4 = validate_success(resp)
        assert b4["status"] == "CANCELLED", \
            "the unrelated future booking is cascade-cancelled"
        assert b4["billing_status"] == "WAIVED"
        assert b4["fee_cents"] == 0


class TestSuspendedDriverBlocked:

    def test_suspended_driver_cannot_create_booking(self):
        """PRD section 3.3: "A `SUSPENDED` driver cannot create bookings, join
        waitlists, or accept waitlist offers — each attempt is rejected with
        `ERR_DRIVER_SUSPENDED`".
        PRD section 3.3: "the `kind` — `NO_SHOW` weighing one strike,
        `EVICTION` weighing two".

        Design: Corner/validations/suspended_driver_cannot_create_booking
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-SU-1", "S You")
        set_clock("2026-08-01T00:00:00Z")
        b1 = create_reserved_booking(driver["id"], site["id"], "2026-08-10", 1)
        b2 = create_reserved_booking(driver["id"], site["id"], "2026-08-11", 1)

        # First two strikes: an eviction (weight 2) after an overstay sweep.
        set_clock("2026-08-10T15:30:00Z")
        check_in(b1["id"], driver["id"])
        set_clock("2026-08-11T11:31:00Z")
        run_site_ops(site["id"])
        resp = api_client.check_out_booking(b1["id"], {"force": True}, OP_ALICE)
        validate_success(resp, expected_status=200)

        # Third strike: the second booking no-shows.
        set_clock("2026-08-11T16:00:01Z")
        run_site_ops(site["id"])

        resp = api_client.get_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["strikes_90d"] == 3, "EVICTION (2) + NO_SHOW (1)"
        assert d["standing"] == "SUSPENDED"

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], site["id"], "2026-08-20"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_SUSPENDED)
