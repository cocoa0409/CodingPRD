"""The stay itself: check-in window boundaries, cancellation fees, no-show
and overstay sweeps, eviction, extension OCC, and ops-run epochs."""
from test_helpers import (
    ADMIN,
    OP_ALICE,
    ApiErrorId,
    api_client,
    assert_booking,
    check_in,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    register_driver,
    register_drivers,
    run_site_ops,
    set_clock,
    settle_booking,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_booked(arrival_date="2026-08-10", num_reservable=1,
                  num_drivers=1, base=5000, night_count=1,
                  arrival_dates=None, **site_overrides):
    """Site with stalls + N drivers + one BOOKED booking per driver.
    `arrival_dates` (one slot per driver, None skips the booking) overrides
    `arrival_date`. Clock ends at 2026-08-01T00:00:00Z."""
    ctx = create_site_with_stalls(num_reservable=num_reservable, base=base,
                                  **site_overrides)
    drivers = register_drivers(num_drivers, "CDL-LC")
    set_clock("2026-08-01T00:00:00Z")
    dates = arrival_dates or [arrival_date] * num_drivers
    bookings = [
        create_reserved_booking(d["id"], ctx["site"]["id"], date, night_count)
        for d, date in zip(drivers, dates)
        if date is not None
    ]
    return {"site": ctx["site"], "stalls": ctx["stalls"], "drivers": drivers,
            "bookings": bookings}


class TestCheckInWindow:

    def test_checkin_at_exact_grace_boundary_succeeds(self):
        """PRD section 3.5: "The driver may check in no earlier than
        `checkin_open_at` (earlier attempts are `ERR_CHECKIN_WINDOW_NOT_OPEN`)
        and no later than `checkin_open_at` plus the site's
        `no_show_grace_minutes`, with the late boundary inclusive — a check-in
        at exactly that instant still succeeds, while anything strictly later
        is `ERR_CHECKIN_GRACE_ELAPSED` if the ops sweep has not already marked
        the booking."
        PRD section 3.5: "A successful check-in stamps `checked_in_at` with
        the current clock and increments the booking's `version` by one."

        Design: Difficulty/boundary_precision_check/checkin_grace_inclusive_minute_boundary
        """
        ctx = _setup_booked(num_reservable=2, num_drivers=2)
        b1 = ctx["bookings"][0]
        assert b1["checkin_open_at"].startswith("2026-08-10T15:00:00"), \
            "checkin_open_at is 15:00:00Z on the arrival date"
        set_clock("2026-08-10T16:00:00Z")
        resp = api_client.check_in_booking(
            b1["id"], make_driver_headers(ctx["drivers"][0]["id"]))
        checked_in = validate_success(resp, expected_status=200)
        assert checked_in["status"] == "CHECKED_IN", \
            "the late boundary is inclusive: exactly open + 60 minutes passes"
        assert checked_in["checked_in_at"].startswith("2026-08-10T16:00:00"), \
            "check-in stamps checked_in_at with the current clock"
        assert checked_in["version"] == b1["version"] + 1

    def test_checkin_one_second_past_grace_rejected(self):
        """PRD section 3.5: "no later than `checkin_open_at` plus the site's
        `no_show_grace_minutes`, with the late boundary inclusive — a check-in
        at exactly that instant still succeeds, while anything strictly later
        is `ERR_CHECKIN_GRACE_ELAPSED` if the ops sweep has not already marked
        the booking."

        Design: Difficulty/boundary_precision_check/checkin_grace_inclusive_minute_boundary
        """
        ctx = _setup_booked(num_reservable=2, num_drivers=2)
        b2 = ctx["bookings"][1]
        set_clock("2026-08-10T16:00:01Z")
        resp = api_client.check_in_booking(
            b2["id"], make_driver_headers(ctx["drivers"][1]["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_GRACE_ELAPSED)

    def test_checkin_before_window_rejected(self):
        """PRD section 3.5: "The driver may check in no earlier than
        `checkin_open_at` (earlier attempts are
        `ERR_CHECKIN_WINDOW_NOT_OPEN`)".

        Design: Corner/validations/checkin_before_window_rejected
        """
        ctx = _setup_booked()
        set_clock("2026-08-10T14:59:59Z")
        resp = api_client.check_in_booking(
            ctx["bookings"][0]["id"],
            make_driver_headers(ctx["drivers"][0]["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_NOT_OPEN)


class TestInvalidLifecycleTransitions:

    def test_checkout_from_booked_returns_invalid_state(self):
        """PRD section 3.5: "Checking out — from either `CHECKED_IN` or
        `OVERSTAY` — moves the booking to `CHECKED_OUT`, stamps
        `checked_out_at`, and runs final settlement in a pinned order."
        PRD section 2.7: "The target resource's own state machine must permit
        the transition — check-in only from `BOOKED`, cancellation only from
        `BOOKED`, waitlist withdrawal only from `QUEUED`, offer acceptance
        only from `OFFERED`, invoice dispute only from the payable-or-`PAID`
        set — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/checkout_from_booked_returns_invalid_state
        """
        ctx = _setup_booked()
        set_clock("2026-08-10T15:30:00Z")
        resp = api_client.check_out_booking(
            ctx["bookings"][0]["id"], {},
            make_driver_headers(ctx["drivers"][0]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_already_cancelled_booking_returns_invalid_state(self):
        """PRD section 2.7: "The target resource's own state machine must
        permit the transition — check-in only from `BOOKED`, cancellation only
        from `BOOKED`, waitlist withdrawal only from `QUEUED`, offer
        acceptance only from `OFFERED`, invoice dispute only from the
        payable-or-`PAID` set — otherwise `ERR_INVALID_STATE` (409)."
        PRD section 3.5: "At or before `checkin_open_at` minus the site's
        `cancellation_free_window_hours` — an inclusive boundary —
        cancellation is free: `fee_cents` is 0 and `billing_status` becomes
        `WAIVED`."

        Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
        """
        ctx = _setup_booked()
        booking, driver = ctx["bookings"][0], ctx["drivers"][0]
        resp = api_client.cancel_booking(booking["id"],
                                         make_driver_headers(driver["id"]))
        cancelled = validate_success(resp, expected_status=200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["fee_cents"] == 0
        assert cancelled["billing_status"] == "WAIVED"

        resp = api_client.cancel_booking(booking["id"],
                                         make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["fee_cents"] == 0, "no fee drift from the rejected cancel"
        assert after["billing_status"] == "WAIVED"


class TestCancellationFeeBoundary:

    def test_cancellation_fee_free_boundary_and_late_fee(self):
        """PRD section 3.5: "At or before `checkin_open_at` minus the site's
        `cancellation_free_window_hours` — an inclusive boundary —
        cancellation is free: `fee_cents` is 0 and `billing_status` becomes
        `WAIVED`. Inside the window, the cancellation fee is half of the first
        pinned night's rate, rounded half up; `final_total_cents` is set to
        that fee and `billing_status` remains `UNBILLED`, leaving the fee to
        be collected."

        Design: Corner/calculations/cancellation_fee_free_boundary_and_late_fee
        """
        ctx = _setup_booked(num_reservable=2, num_drivers=2)
        b1, b2 = ctx["bookings"]
        d1, d2 = ctx["drivers"]

        set_clock("2026-08-09T15:00:00Z")
        resp = api_client.cancel_booking(b1["id"], make_driver_headers(d1["id"]))
        free = validate_success(resp, expected_status=200)
        assert free["fee_cents"] == 0, \
            "cancelling at exactly checkin_open - 24h is the inclusive free boundary"
        assert free["billing_status"] == "WAIVED"

        set_clock("2026-08-09T15:00:01Z")
        resp = api_client.cancel_booking(b2["id"], make_driver_headers(d2["id"]))
        late = validate_success(resp, expected_status=200)
        assert late["fee_cents"] == 2250, (
            f"one second inside the window: rhu(0.5 * 4500), got "
            f"{late['fee_cents']}"
        )
        assert late["final_total_cents"] == 2250
        assert late["billing_status"] == "UNBILLED"


class TestNoShowSweep:

    def test_noshow_sweep_strict_greater_than_boundary(self):
        """PRD section 3.5: "The no-show sweep is stricter than the check-in
        boundary suggests: a booking still `BOOKED` once the clock is strictly
        later than `checkin_open_at` plus `no_show_grace_minutes` becomes
        `NO_SHOW`. The fee is the full first pinned night's rate, never
        discounted, and `final_total_cents` equals it while `billing_status`
        stays `UNBILLED`."

        Design: Corner/state_machines/noshow_sweep_strict_greater_than_boundary
        """
        ctx = _setup_booked()
        booking = ctx["bookings"][0]

        set_clock("2026-08-10T16:00:00Z")
        run_site_ops(ctx["site"]["id"])
        resp = api_client.get_booking(booking["id"], ADMIN)
        at_boundary = validate_success(resp)
        assert at_boundary["status"] == "BOOKED", \
            "the sweep boundary is strict: exactly open + grace survives"

        set_clock("2026-08-10T16:00:01Z")
        run_site_ops(ctx["site"]["id"])
        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "NO_SHOW"
        assert after["fee_cents"] == 4500, \
            "the no-show fee is the full first pinned night's rate"
        assert after["final_total_cents"] == 4500
        assert after["billing_status"] == "UNBILLED"


class TestOverstay:

    def test_overstay_penalty_ceil_started_hours(self):
        """PRD section 3.5: "A booking still `CHECKED_IN` once the clock
        passes strictly beyond `checkout_due_at` plus `overstay_grace_minutes`
        is marked `OVERSTAY` by the site ops-run, stamping `overstayed_at`."
        PRD section 3.5: "The overstay penalty itself is computed from whole
        minutes: the minutes from `checkout_due_at` plus
        `overstay_grace_minutes` until `checked_out_at`, floored at zero. Each
        started hour bills — the minute count divided by 60 is rounded up to a
        whole hour, so zero minutes bills zero hours — and the hourly rate is
        one and a half times the last pinned night's rate divided by 20,
        rounded half up once. The penalty is billable hours times that hourly
        rate."

        Design: Corner/calculations/overstay_penalty_ceil_started_hours
        """
        ctx = _setup_booked()
        booking, driver = ctx["bookings"][0], ctx["drivers"][0]
        set_clock("2026-08-10T15:30:00Z")
        check_in(booking["id"], driver["id"])

        set_clock("2026-08-11T11:30:00Z")
        run_site_ops(ctx["site"]["id"])
        resp = api_client.get_booking(booking["id"], ADMIN)
        at_grace = validate_success(resp)
        assert at_grace["status"] == "CHECKED_IN", \
            "at exactly due + grace the strict sweep boundary leaves CHECKED_IN"

        set_clock("2026-08-11T11:31:00Z")
        run_site_ops(ctx["site"]["id"])
        resp = api_client.get_booking(booking["id"], ADMIN)
        overstayed = validate_success(resp)
        assert overstayed["status"] == "OVERSTAY"

        set_clock("2026-08-11T12:40:00Z")
        resp = api_client.check_out_booking(booking["id"], {},
                                            make_driver_headers(driver["id"]))
        settled = validate_success(resp, expected_status=200)
        assert settled["status"] == "CHECKED_OUT"
        assert settled["fee_cents"] == 676, (
            f"70 minutes past grace bills ceil(70/60) = 2 started hours at "
            f"rhu(1.5 * 4500 / 20) = 338; got {settled['fee_cents']}"
        )
        assert settled["final_total_cents"] == 5176, "4500 parking + 676 fee"

    def test_force_checkout_eviction_records_double_strike(self):
        """PRD section 3.5: "Eviction is the forced variant: a `SiteOperator`
        checks out an `OVERSTAY` booking with `force` set to true, moving it
        to `EVICTED`. Settlement is identical to a normal checkout including
        the full overstay penalty, but an `EVICTION` strike of weight two is
        appended to the driver's `strike_events`, standing is recomputed, and
        the driver-suspension cascade applies if `strikes_90d` reaches at
        least 3".
        PRD section 3.3: "`strikes_90d` of 3 or more means `SUSPENDED`,
        exactly 2 means `PROBATION`, and anything less means `GOOD`."

        Design: Corner/endpoints/force_checkout_eviction_records_double_strike
        """
        ctx = _setup_booked()
        booking, driver = ctx["bookings"][0], ctx["drivers"][0]
        set_clock("2026-08-10T15:30:00Z")
        check_in(booking["id"], driver["id"])
        set_clock("2026-08-11T11:31:00Z")
        run_site_ops(ctx["site"]["id"])

        resp = api_client.check_out_booking(booking["id"], {"force": True},
                                            OP_ALICE)
        evicted = validate_success(resp, expected_status=200)
        assert evicted["status"] == "EVICTED"
        assert evicted["fee_cents"] == 338, (
            f"1 minute past grace bills 1 started hour at 338; got "
            f"{evicted['fee_cents']}"
        )
        assert evicted["final_total_cents"] == 4838, "4500 parking + 338 fee"

        resp = api_client.get_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["strikes_90d"] == 2, "an EVICTION strike weighs two"
        assert d["standing"] == "PROBATION"

    def test_overstay_escalation_auto_creates_security_incident(self):
        """PRD section 3.5: "If the clock has also passed strictly beyond four
        hours past that same grace boundary and `incident_escalated` is still
        false, the sweep auto-creates an incident report with `category`
        `SECURITY`, `severity` `HIGH`, the offending `booking_id`, a null
        `reporter_driver_id`, and `status` `OPEN`, then sets
        `incident_escalated` to true so it happens once; site posture is
        recomputed, though a single `HIGH` incident alone never escalates a
        site."

        Design: Corner/endpoints/overstay_escalation_auto_creates_security_incident
        """
        ctx = _setup_booked()
        booking, driver = ctx["bookings"][0], ctx["drivers"][0]
        set_clock("2026-08-10T15:30:00Z")
        check_in(booking["id"], driver["id"])
        set_clock("2026-08-11T11:31:00Z")
        run_site_ops(ctx["site"]["id"])

        set_clock("2026-08-11T15:31:00Z")
        run_site_ops(ctx["site"]["id"])
        data, meta = validate_paginated(
            api_client.list_incidents(ADMIN,
                                      params={"booking_id": booking["id"]}))
        assert meta["total_count"] == 1, \
            "exactly one auto-incident is created at the escalation threshold"
        inc = data[0]
        assert inc["category"] == "SECURITY"
        assert inc["severity"] == "HIGH"
        assert inc["status"] == "OPEN"
        assert inc["reporter_driver_id"] is None

        run_site_ops(ctx["site"]["id"])
        data, meta = validate_paginated(
            api_client.list_incidents(ADMIN,
                                      params={"booking_id": booking["id"]}))
        assert meta["total_count"] == 1, \
            "the incident_escalated flag prevents duplicates on later sweeps"


class TestExtension:

    def test_occ_booking_extend_stale_version(self):
        """PRD section 2.9: "Extending a booking requires the request to carry
        `expected_booking_version` equal to the booking's current `version`.
        An extension is valid whenever the stall is free for the added window,
        so a second extension built from a stale observed version would
        legitimately succeed on its own terms yet diverge the booked window
        from what the client observed; the stale request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.5: "The added nights are priced at the current dynamic
        rate and appended to `per_night_rates`, `night_count` and
        `checkout_due_at` grow by `added_nights` nights and days respectively,
        `quoted_total_cents` is recomputed, and the booking's `version`
        increments."

        Design: Corner/complexity_layers/occ_booking_extend_stale_version
        """
        ctx = _setup_booked()
        booking, driver = ctx["bookings"][0], ctx["drivers"][0]
        observed_version = booking["version"]

        resp = api_client.extend_booking(
            booking["id"],
            {"added_nights": 1,
             "expected_booking_version": observed_version},
            make_driver_headers(driver["id"]),
        )
        extended = validate_success(resp, expected_status=200)
        assert extended["night_count"] == 2
        assert extended["quoted_total_cents"] == 9000, \
            "the extension night prices at the current dynamic rate (4500)"
        assert extended["version"] == observed_version + 1

        resp = api_client.extend_booking(
            booking["id"],
            {"added_nights": 1,
             "expected_booking_version": observed_version},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["night_count"] == 2, \
            "the stale extension leaves the booked window untouched"

    def test_extension_into_occupied_window_rejected(self):
        """PRD section 3.5: "the stall must be free for the whole extension
        window (`ERR_EXTENSION_CONFLICT`, which also covers an extension that
        would push the total beyond 14 nights)."

        Design: Corner/validations/extension_into_occupied_window_rejected
        """
        # Driver X holds 08-10, driver Y holds 08-11; both land on the lone
        # stall because half-open intervals make that adjacency legal.
        ctx = _setup_booked(num_drivers=2,
                            arrival_dates=["2026-08-10", "2026-08-11"])
        site = ctx["site"]
        b1, b2 = ctx["bookings"]
        d1, d2 = ctx["drivers"]
        assert b2["stall_id"] == b1["stall_id"], \
            "the lone stall serves back-to-back nights"

        resp = api_client.extend_booking(
            b1["id"],
            {"added_nights": 1,
             "expected_booking_version": b1["version"]},
            make_driver_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_CONFLICT)

        resp = api_client.get_booking(b1["id"], ADMIN)
        after = validate_success(resp)
        assert after["night_count"] == 1
        assert after["version"] == b1["version"], \
            "a rejected extension mutates nothing"


class TestOpsRunEpochs:

    def test_ops_run_epoch_idempotent_second_sweep(self):
        """PRD section 3.8: "Each run increments the site's `ops_run_index` by
        one, giving operators a monotonic audit counter that started at 0."
        PRD section 3.5: "a booking still `BOOKED` once the clock is strictly
        later than `checkin_open_at` plus `no_show_grace_minutes` becomes
        `NO_SHOW`."
        PRD section 2.4: "State that derives from the passage of time changes
        only when an operator explicitly triggers a site ops-run (§3.8) or a
        fleet ops-run (§3.9)."

        Design: Corner/complexity_layers/ops_run_epoch_idempotent_second_sweep
        """
        ctx = _setup_booked()
        site, booking = ctx["site"], ctx["bookings"][0]
        driver = ctx["drivers"][0]

        set_clock("2026-08-10T16:00:01Z")
        run_site_ops(site["id"])
        resp = api_client.get_site(site["id"], ADMIN)
        assert validate_success(resp)["ops_run_index"] == 1

        run_site_ops(site["id"])
        resp = api_client.get_site(site["id"], ADMIN)
        assert validate_success(resp)["ops_run_index"] == 2, \
            "the audit counter increments on every run"

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "NO_SHOW"
        assert after["fee_cents"] == 4500, \
            "the second sweep at the same clock charges nothing new"

        resp = api_client.get_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["strikes_90d"] == 1, "no duplicate strike from the epoch re-run"
