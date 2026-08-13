"""Rescue run lifecycle: the decline/re-offer cycle, parallel status
dimensions, and compensating capacity/cooler invariants (PRD §3.3-§3.7)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, respond_run, fail_run,
    make_volunteer_driver_headers, make_agency_coordinator_headers,
    setup_picked_up_run,
)

ADMIN = TEST_USERS["admin_headers"]


def _cycle_setup(api):
    donor = create_donor(legal_name="Cycle Bistro", ein="666666666",
                         contact_email="c@bistro.example")
    agency = create_agency()
    driver = create_driver(cold_chain_certified=True)
    add_window(driver["id"])
    cooler = create_cooler(label="C1")
    offer = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
    set_clock("2026-08-02T09:30:00Z")
    return {"donor": donor, "agency": agency, "driver": driver,
            "cooler": cooler, "offer": offer}


class TestDeclineRematchCycle:
    def test_decline_reverts_offer_and_releases_resources(self, api):
        """PRD §3.4: "Responding `DECLINE` from `PROPOSED` moves the run to
        `DECLINED` and unwinds everything dispatch reserved: the offer reverts
        from `MATCHED` to `OPEN`, the window returns to `OPEN`, the reservations
        flip to `RELEASED`, their coolers return to `AVAILABLE`, and the
        agency's commitment is released."
        PRD §3.2: "If the assigned driver declines, the offer reverts from
        `MATCHED` to `OPEN` with `failed_attempts` unchanged, ready to be
        dispatched again."

        Design: Difficulty/non_linear_state_machine/offer_decline_rematch_cycle
        """
        s = _cycle_setup(api)
        run = dispatch_run(s["offer"]["id"], driver_id=s["driver"]["id"],
                           agency_id=s["agency"]["id"],
                           cooler_ids=[s["cooler"]["id"]])
        run = respond_run(run["id"], s["driver"]["id"], "DECLINE")
        assert run["run_status"] == "DECLINED"
        resp = api.get_donation_offer(s["offer"]["id"], ADMIN)
        offer = validate_success(resp)
        assert offer["status"] == "OPEN"
        assert offer["failed_attempts"] == 0, "a decline is not a failed attempt"
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 0
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "AVAILABLE"
        resp = api.list_availability_windows(s["driver"]["id"], ADMIN)
        window = validate_success(resp)[0]
        assert window["status"] == "OPEN"
        assert window["booked_run_id"] is None

    def test_reverted_offer_dispatches_again_rebooking_same_resources(self, api):
        """PRD §3.2: "If the assigned driver declines, the offer reverts from
        `MATCHED` to `OPEN` with `failed_attempts` unchanged, ready to be
        dispatched again. Once the driver accepts, the offer advances from
        `MATCHED` to `SCHEDULED`;"
        PRD §2.5: "`version` is an integer that increments on every mutation of
        the resource and anchors the optimistic-concurrency rules of §2.6."

        Design: Difficulty/non_linear_state_machine/offer_decline_rematch_cycle
        """
        s = _cycle_setup(api)
        v_created = s["offer"]["version"]
        r1 = dispatch_run(s["offer"]["id"], driver_id=s["driver"]["id"],
                          agency_id=s["agency"]["id"],
                          cooler_ids=[s["cooler"]["id"]])
        respond_run(r1["id"], s["driver"]["id"], "DECLINE")
        # The OPEN-again offer accepts a second dispatch (MATCHED -> OPEN ->
        # MATCHED), re-booking the same window and cooler that were released.
        r2 = dispatch_run(s["offer"]["id"], driver_id=s["driver"]["id"],
                          agency_id=s["agency"]["id"],
                          cooler_ids=[s["cooler"]["id"]])
        respond_run(r2["id"], s["driver"]["id"], "ACCEPT")
        resp = api.get_donation_offer(s["offer"]["id"], ADMIN)
        offer = validate_success(resp)
        assert offer["status"] == "SCHEDULED"
        # v_created was captured after create_offer(publish=True), which
        # already accounts for both the creation and the publish. Since then:
        # dispatch, decline, dispatch, accept — four further mutations, each
        # incrementing version by one.
        assert offer["version"] == v_created + 4
        assert offer["failed_attempts"] == 0
        resp = api.list_availability_windows(s["driver"]["id"], ADMIN)
        window = validate_success(resp)[0]
        assert window["status"] == "BOOKED"
        assert window["booked_run_id"] == r2["id"], (
            "the window was released by the decline and re-booked to run 2"
        )
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "RESERVED"


class TestParallelStatusDimensions:
    def _setup(self, api):
        ctx = setup_picked_up_run(
            driver_window=("2026-08-02T09:00:00Z", "2026-08-02T19:00:00Z"),
            pickup_time="2026-08-02T10:15:00Z", pickup_temp_f=35.0)
        return ctx

    def test_violation_moves_only_safety_status(self, api):
        """PRD §3.4: "A cold-chain verdict of violation rejects the delivery
        with `ERR_SAFETY_VERDICT_VIOLATION`, persists `safety_status` as
        `VERIFIED_VIOLATION`, and leaves the run in `PICKED_UP` so the failure
        path can take over."

        Design: Difficulty/non_linear_state_machine/run_parallel_status_dims_survive_violation
        """
        ctx = self._setup(api)
        set_clock("2026-08-02T18:17:00Z")
        # Span 482 min, T0=35.0 safe / T1=47.0 dangerous, crossing at midpoint:
        # danger = 482 * 6 / 12 = 241 > 240.
        resp = api.record_delivery(
            ctx["run"]["id"],
            {"arrival_time": "2026-08-02T18:17:00Z", "arrival_temp_f": 47.0,
             "actual_weight_lbs": 50},
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VERDICT_VIOLATION)
        resp = api.get_rescue_run(ctx["run"]["id"], ADMIN)
        run = validate_success(resp)
        assert run["run_status"] == "PICKED_UP", "the logistics dim must not move"
        assert run["safety_status"] == "VERIFIED_VIOLATION", (
            "only the safety dim moved"
        )

    def test_safety_disposal_moves_only_run_status_and_quarantines(self, api):
        """PRD §3.6: "`SAFETY_DISPOSAL` is the signature reason here: it is
        admissible only when the run's `safety_status` is already
        `VERIFIED_VIOLATION` — otherwise `ERR_RUN_NOT_IN_EXPECTED_STATE` — and
        it demands non-empty `disposal_method` and `disposal_notes` documenting
        the destruction, with `fault_party` fixed at `NONE`."
        PRD §3.6: "a `SAFETY_DISPOSAL` holds the reservations in
        `QUARANTINED_HOLD` and quarantines their coolers with `cleaning_ends_at`
        240 minutes — four hours — past the failure clock, while any other
        reason returns the reservations to `RETURNED` and sends the coolers to
        the ordinary 45-minute `CLEANING`."

        Design: Difficulty/non_linear_state_machine/run_parallel_status_dims_survive_violation
        """
        ctx = self._setup(api)
        set_clock("2026-08-02T18:17:00Z")
        resp = api.record_delivery(
            ctx["run"]["id"],
            {"arrival_time": "2026-08-02T18:17:00Z", "arrival_temp_f": 47.0,
             "actual_weight_lbs": 50},
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VERDICT_VIOLATION)
        set_clock("2026-08-02T18:20:00Z")
        resp = api.fail_rescue_run(
            ctx["run"]["id"],
            {"fault_party": "NONE", "reason": "SAFETY_DISPOSAL",
             "disposal_method": "ON_SITE_COMPOST",
             "disposal_notes": "241 danger minutes; disposed per protocol"},
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        run = validate_success(resp)
        assert run["run_status"] == "FAILED_DELIVERY", "the run dim moved"
        assert run["safety_status"] == "VERIFIED_VIOLATION", (
            "the safety dim stays put"
        )
        resp = api.get_cooler(ctx["cooler"]["id"], ADMIN)
        cooler = validate_success(resp)
        assert cooler["status"] == "QUARANTINED"
        assert cooler["cleaning_ends_at"].startswith("2026-08-02T22:20"), (
            "fail clock 18:20 + 240-minute deep clean"
        )
        # Lazy release once the clock reaches cleaning_ends_at (inclusive).
        set_clock("2026-08-02T22:20:00Z")
        resp = api.get_cooler(ctx["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "AVAILABLE"
        resp = api.get_donation_offer(ctx["offer"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "DISCARDED"


class TestAgencyCommitmentRoundtrip:
    def _setup(self, api):
        donor = create_donor(legal_name="Inv Bistro", ein="246824682",
                             contact_email="i@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"])
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=45, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        return {"donor": donor, "agency": agency, "driver": driver,
                "cooler": cooler, "offer": offer}

    def _committed(self, api, agency_id):
        resp = api.get_recipient_agency(agency_id, ADMIN)
        return validate_success(resp)

    def test_commitment_reserved_at_dispatch_not_doubled_at_accept(self, api):
        """PRD §3.7: "Dispatch reserves by adding the snapshot to that committed
        set, and the capacity gate — committed plus the new estimate no greater
        than the ceiling, equality allowed — is evaluated both at dispatch and
        again at acceptance, where the run's own snapshot is already inside the
        committed total."

        Design: Difficulty/compensating_invariant/agency_commitment_roundtrip_invariant
        """
        s = self._setup(api)
        run = dispatch_run(s["offer"]["id"], driver_id=s["driver"]["id"],
                           agency_id=s["agency"]["id"],
                           cooler_ids=[s["cooler"]["id"]])
        agency = self._committed(api, s["agency"]["id"])
        assert agency["committed_cold_held_lbs"] == 45, (
            "the reservation begins at dispatch, not at accept"
        )
        respond_run(run["id"], s["driver"]["id"], "ACCEPT")
        agency = self._committed(api, s["agency"]["id"])
        assert agency["committed_cold_held_lbs"] == 45, (
            "accept must not double-count the already-reserved run"
        )

    def test_fail_exactly_restores_pre_dispatch_commitment(self, api):
        """PRD §3.7: "Declines, failures, and cancellations release the
        commitment without touching received totals."

        Design: Difficulty/compensating_invariant/agency_commitment_roundtrip_invariant
        """
        s = self._setup(api)
        run = dispatch_run(s["offer"]["id"], driver_id=s["driver"]["id"],
                           agency_id=s["agency"]["id"],
                           cooler_ids=[s["cooler"]["id"]])
        respond_run(run["id"], s["driver"]["id"], "ACCEPT")
        fail_run(run["id"], "DONOR", "DONOR_NO_SHOW",
                 as_driver_id=s["driver"]["id"])
        agency = self._committed(api, s["agency"]["id"])
        assert agency["committed_cold_held_lbs"] == 0, (
            "the compensating fail exactly restores the pre-dispatch value"
        )
        assert agency["received_total_lbs"] == 0, "no delivery occurred"


class TestCoolerSingleActiveReservation:
    def _setup(self, api):
        donor = create_donor(legal_name="Cool Bistro", ein="112358132",
                             contact_email="cool@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z")
        add_window(driver["id"], "2026-08-02T13:00:00Z", "2026-08-02T15:00:00Z")
        cooler = create_cooler(label="C1")
        o1 = create_offer(donor["id"], estimated_weight_lbs=10, publish=True)
        o2 = create_offer(donor["id"], estimated_weight_lbs=10,
                          pickup_window_start="2026-08-02T13:00:00Z",
                          pickup_window_end="2026-08-02T14:00:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        return {"donor": donor, "agency": agency, "driver": driver,
                "cooler": cooler, "o1": o1, "o2": o2}

    def test_dispatch_then_decline_roundtrips_cooler_to_available(self, api):
        """PRD §3.1: "A reservation's own `status` moves from `RESERVED` to
        `CHECKED_OUT` at pickup, to `RETURNED` on an ordinary return, to
        `QUARANTINED_HOLD` when its cooler is quarantined (and lazily from
        `QUARANTINED_HOLD` to `RETURNED` when the cooler clears), or directly to
        `RELEASED` when its run dies before pickup — that is, when the reserving
        run reaches `DECLINED`, `FAILED_PICKUP`, or `CANCELLED`."
        PRD §3.4: "Responding `DECLINE` from `PROPOSED` moves the run to
        `DECLINED` and unwinds everything dispatch reserved: the offer reverts
        from `MATCHED` to `OPEN`, the window returns to `OPEN`, the reservations
        flip to `RELEASED`, their coolers return to `AVAILABLE`, and the
        agency's commitment is released."

        Design: Difficulty/compensating_invariant/cooler_single_active_reservation_invariant
        """
        s = self._setup(api)
        run = dispatch_run(s["o1"]["id"], driver_id=s["driver"]["id"],
                           agency_id=s["agency"]["id"],
                           cooler_ids=[s["cooler"]["id"]])
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "RESERVED"
        resp = api.list_cooler_reservations(
            s["cooler"]["id"], ADMIN, params={"status": "RESERVED"})
        reservations = validate_success(resp)
        assert len(reservations) == 1
        assert reservations[0]["status"] == "RESERVED"
        respond_run(run["id"], s["driver"]["id"], "DECLINE")
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "AVAILABLE"
        resp = api.list_cooler_reservations(
            s["cooler"]["id"], ADMIN, params={"status": "RESERVED"})
        assert validate_success(resp) == [], (
            "the decline restores both sides of the correspondence"
        )

    def test_released_cooler_can_be_reserved_again(self, api):
        """PRD §3.4: "Responding `DECLINE` from `PROPOSED` moves the run to
        `DECLINED` and unwinds everything dispatch reserved: the offer reverts
        from `MATCHED` to `OPEN`, the window returns to `OPEN`, the reservations
        flip to `RELEASED`, their coolers return to `AVAILABLE`, and the
        agency's commitment is released."

        Design: Difficulty/compensating_invariant/cooler_single_active_reservation_invariant
        """
        s = self._setup(api)
        r1 = dispatch_run(s["o1"]["id"], driver_id=s["driver"]["id"],
                          agency_id=s["agency"]["id"],
                          cooler_ids=[s["cooler"]["id"]])
        respond_run(r1["id"], s["driver"]["id"], "DECLINE")
        # Release was complete, so the SAME cooler is a legal candidate again.
        r2 = dispatch_run(s["o2"]["id"], driver_id=s["driver"]["id"],
                          agency_id=s["agency"]["id"],
                          cooler_ids=[s["cooler"]["id"]])
        assert r2["run_status"] == "PROPOSED"
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "RESERVED"


class TestVerifyBeforeDelivery:
    def test_verify_on_picked_up_run_rejected_without_mutation(self, api):
        """PRD §3.7: "The rescue formally closes when the destination agency's
        own `AgencyCoordinator` countersigns a `DELIVERED` run — any other state
        answers `ERR_RUN_NOT_IN_EXPECTED_STATE`, and any other caller is masked
        out per §2.7."

        Design: Corner/state_machines/verify_before_delivery_rejected
        """
        ctx = setup_picked_up_run(pickup_time="2026-08-02T10:15:00Z",
                                  pickup_temp_f=35.0)
        assert ctx["run"]["run_status"] == "PICKED_UP"
        assert ctx["run"]["safety_status"] == "PROVISIONAL_COMPLIANT"
        resp = api.verify_delivery(
            ctx["run"]["id"],
            make_agency_coordinator_headers(ctx["agency"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_IN_EXPECTED_STATE)
        resp = api.get_rescue_run(ctx["run"]["id"], ADMIN)
        run = validate_success(resp)
        assert run["run_status"] == "PICKED_UP"
        assert run["safety_status"] == "PROVISIONAL_COMPLIANT", (
            "a rejected countersignature mutates nothing"
        )
