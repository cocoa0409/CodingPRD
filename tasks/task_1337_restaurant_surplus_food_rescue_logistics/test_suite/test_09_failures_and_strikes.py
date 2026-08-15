"""Failures, fault attribution, strike auto-filing, adjudication, and the
suspension cascades (PRD §3.6)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, respond_run, fail_run,
    record_pickup, record_delivery, verify_run,
    make_dispatch_admin_headers, make_volunteer_driver_headers,
    setup_filed_strike_against_donor,
    setup_driver_suspension_cascade_scenario,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]


def _fail_cycle_scenario(api):
    donor = create_donor(legal_name="Fail Bistro", ein="999999999",
                         contact_email="f@bistro.example")
    agency = create_agency()
    driver = create_driver(cold_chain_certified=True)
    add_window(driver["id"])
    cooler = create_cooler(label="C1")
    offer = create_offer(donor["id"], estimated_weight_lbs=30, publish=True)
    set_clock("2026-08-02T09:30:00Z")
    run = dispatch_run(offer["id"], driver_id=driver["id"],
                       agency_id=agency["id"], cooler_ids=[cooler["id"]])
    respond_run(run["id"], driver["id"], "ACCEPT")
    return {"donor": donor, "agency": agency, "driver": driver,
            "cooler": cooler, "offer": offer, "run": run}


class TestPickupFailureCascade:
    def test_fail_files_driver_reported_strike_and_reoffers(self, api):
        """PRD §3.6: "any other reason increments the offer's `failed_attempts`
        by one and sends it back to `OPEN`, or to `EXPIRED` when the increment
        reaches three. When `fault_party` is `DONOR` or `DRIVER`, a strike
        report is auto-filed against the corresponding subject, with
        `reporter_role` set to `DRIVER` when the assigned driver made the call,
        `ADMIN` when a `DispatchAdmin` did, and `SYSTEM` when a cascade did."
        PRD §3.6: "A report opens `FILED` with `adjudicated_by_user_id` and
        `adjudicated_at` null, and a run's reports are listable by admins."

        Design: Difficulty/transitive_cascade/pickup_failure_reoffer_release_cascade
        """
        s = _fail_cycle_scenario(api)
        resp = api.fail_rescue_run(
            s["run"]["id"], {"fault_party": "DONOR", "reason": "DONOR_NO_SHOW"},
            make_volunteer_driver_headers(s["driver"]["id"]))
        run = validate_success(resp)
        assert run["run_status"] == "FAILED_PICKUP"
        resp = api.get_donation_offer(s["offer"]["id"], ADMIN)
        offer = validate_success(resp)
        assert offer["status"] == "OPEN", "first failure re-offers"
        assert offer["failed_attempts"] == 1
        resp = api.list_run_strike_reports(s["run"]["id"], ADMIN)
        strikes = validate_success(resp)
        assert len(strikes) == 1
        strike = strikes[0]
        assert strike["subject_type"] == "DONOR_SITE"
        assert strike["subject_id"] == s["donor"]["id"]
        assert strike["reporter_role"] == "DRIVER"
        assert strike["reporter_user_id"] == s["driver"]["id"]
        assert strike["status"] == "FILED"
        assert strike["reason"] == "DONOR_NO_SHOW"
        # A FILED strike moves no counters until adjudicated UPHELD.
        resp = api.get_donor_site(s["donor"]["id"], ADMIN)
        assert validate_success(resp)["strike_count"] == 0

    def test_fail_releases_cooler_window_and_agency_commitment(self, api):
        """PRD §3.6: "Every pickup-stage failure releases the agency's
        commitment, returns the window to `OPEN`, releases the reservations, and
        frees their coolers to `AVAILABLE`."

        Design: Difficulty/transitive_cascade/pickup_failure_reoffer_release_cascade
        """
        s = _fail_cycle_scenario(api)
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 30
        resp = api.fail_rescue_run(
            s["run"]["id"], {"fault_party": "DONOR", "reason": "DONOR_NO_SHOW"},
            make_volunteer_driver_headers(s["driver"]["id"]))
        validate_success(resp)
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 0
        resp = api.get_cooler(s["cooler"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "AVAILABLE"
        resp = api.list_availability_windows(s["driver"]["id"], ADMIN)
        window = validate_success(resp)[0]
        assert window["status"] == "OPEN"
        assert window["booked_run_id"] is None


class TestUpheldDriverStrikeSuspensionCascade:
    def _trigger(self, api, s):
        """Fail R0 as admin-1 (fault DRIVER) and uphold the strike as admin-2."""
        fail_run(s["runs"][0]["id"], "DRIVER", "DRIVER_NO_SHOW",
                 as_admin_id="admin-1")
        resp = api.list_run_strike_reports(s["runs"][0]["id"], ADMIN)
        strike = validate_success(resp)[0]
        assert strike["reporter_role"] == "ADMIN"
        assert strike["reporter_user_id"] == "admin-1"
        resp = api.adjudicate_strike_report(strike["id"], "UPHELD", ADMIN2)
        return validate_success(resp)

    def test_upheld_strike_drops_score_and_suspends_driver(self, api):
        """PRD §3.6: "Against a driver, `upheld_strike_count` increments by one
        and `reliability_score` drops by 50, floored at zero; if the score then
        falls strictly below 60 the driver is suspended, so a driver sitting at
        exactly 60 remains `ACTIVE`."
        PRD §3.6: "A suspended driver sees each of their `PROPOSED` runs moved
        to `DECLINED` with the full release cascade and the offer reverted from
        `MATCHED` to `OPEN`, and each of their `CONFIRMED` runs moved to
        `FAILED_PICKUP` with `fault_party` `DRIVER` and `reason`
        `DRIVER_NO_SHOW`: the agency commitment releases, the offer's
        `failed_attempts` increments and it returns to `OPEN` or expires on the
        third strike under the three-failures rule, and a `SYSTEM`-reported
        strike is auto-filed against the driver."

        Design: Difficulty/transitive_cascade/upheld_driver_strike_suspension_cascade
        """
        s = setup_driver_suspension_cascade_scenario()
        strike = self._trigger(api, s)
        assert strike["status"] == "UPHELD"
        resp = api.get_volunteer_driver(s["driver"]["id"], ADMIN)
        driver = validate_success(resp)
        assert driver["reliability_score"] == 50, "100 - 50 strike penalty"
        assert driver["upheld_strike_count"] == 1
        assert driver["status"] == "SUSPENDED", "50 is strictly below 60"
        # The CONFIRMED run R1 was failed by the cascade...
        resp = api.get_rescue_run(s["runs"][1]["id"], ADMIN)
        r1 = validate_success(resp)
        assert r1["run_status"] == "FAILED_PICKUP"
        assert r1["fault_party"] == "DRIVER"
        assert r1["failure_reason"] == "DRIVER_NO_SHOW"
        # ...and the cascade auto-filed a SYSTEM-reported strike for it.
        resp = api.list_run_strike_reports(s["runs"][1]["id"], ADMIN)
        sys_strikes = validate_success(resp)
        assert len(sys_strikes) == 1
        assert sys_strikes[0]["reporter_role"] == "SYSTEM"
        assert sys_strikes[0]["reporter_user_id"] is None
        assert sys_strikes[0]["subject_type"] == "DRIVER"
        assert sys_strikes[0]["subject_id"] == s["driver"]["id"]

    def test_suspension_cascade_releases_runs_offers_coolers_windows(self, api):
        """PRD §3.6: "A suspended driver sees each of their `PROPOSED` runs
        moved to `DECLINED` with the full release cascade and the offer reverted
        from `MATCHED` to `OPEN`, and each of their `CONFIRMED` runs moved to
        `FAILED_PICKUP` with `fault_party` `DRIVER` and `reason`
        `DRIVER_NO_SHOW`: the agency commitment releases, the offer's
        `failed_attempts` increments and it returns to `OPEN` or expires on the
        third strike under the three-failures rule, and a `SYSTEM`-reported
        strike is auto-filed against the driver."

        Design: Difficulty/transitive_cascade/upheld_driver_strike_suspension_cascade
        """
        s = setup_driver_suspension_cascade_scenario()
        self._trigger(api, s)
        # CONFIRMED run's offer: re-offered with failed_attempts incremented.
        resp = api.get_donation_offer(s["offers"][1]["id"], ADMIN)
        o1 = validate_success(resp)
        assert o1["status"] == "OPEN"
        assert o1["failed_attempts"] == 1
        # PROPOSED run declined; its offer reverted without a failed attempt.
        resp = api.get_rescue_run(s["runs"][2]["id"], ADMIN)
        assert validate_success(resp)["run_status"] == "DECLINED"
        resp = api.get_donation_offer(s["offers"][2]["id"], ADMIN)
        o2 = validate_success(resp)
        assert o2["status"] == "OPEN"
        assert o2["failed_attempts"] == 0, "a decline is not a failed attempt"
        # Every commitment (three x 20 lbs) is released.
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 0
        # Both coolers are free and no window remains booked.
        for cooler in s["coolers"]:
            resp = api.get_cooler(cooler["id"], ADMIN)
            assert validate_success(resp)["status"] == "AVAILABLE"
        resp = api.list_availability_windows(
            s["driver"]["id"], ADMIN, params={"status": "BOOKED"})
        assert validate_success(resp) == []


class TestAdjudicationRules:
    def test_adjudicating_terminal_report_rejected(self, api):
        """PRD §3.6: "Adjudication is a `DispatchAdmin`'s act with a
        segregation-of-duties guard: the report must still be `FILED` (else
        `ERR_STRIKE_NOT_FILED`), and when `reporter_role` is anything other than
        `SYSTEM`, the adjudicator's `X-User-ID` must differ from
        `reporter_user_id` — a reporter may not judge their own accusation, and
        the attempt answers `ERR_SELF_ADJUDICATION_FORBIDDEN`."
        PRD §3.6: "`WAIVED` changes nothing about the subject and simply closes
        the report."

        Design: Corner/state_machines/adjudicate_terminal_report_rejected
        """
        ctx = setup_filed_strike_against_donor(reporter="driver")
        resp = api.adjudicate_strike_report(ctx["strike"]["id"], "WAIVED", ADMIN2)
        strike = validate_success(resp)
        assert strike["status"] == "WAIVED"
        # WAIVED is terminal: a second adjudication fails regardless of outcome.
        resp = api.adjudicate_strike_report(
            ctx["strike"]["id"], "UPHELD", TEST_USERS["admin3_headers"])
        validate_error(resp, ApiErrorId.ERR_STRIKE_NOT_FILED)
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        assert validate_success(resp)["strike_count"] == 0, (
            "a WAIVED strike never touches the counter"
        )

    def test_reporter_cannot_adjudicate_own_strike(self, api):
        """PRD §3.6: "Adjudication is a `DispatchAdmin`'s act with a
        segregation-of-duties guard: the report must still be `FILED` (else
        `ERR_STRIKE_NOT_FILED`), and when `reporter_role` is anything other than
        `SYSTEM`, the adjudicator's `X-User-ID` must differ from
        `reporter_user_id` — a reporter may not judge their own accusation, and
        the attempt answers `ERR_SELF_ADJUDICATION_FORBIDDEN`."

        Design: Corner/errors/self_adjudication_forbidden_for_non_system_reporter
        """
        ctx = setup_filed_strike_against_donor(reporter="driver")
        # A DispatchAdmin whose X-User-ID collides with the reporter's id.
        resp = api.adjudicate_strike_report(
            ctx["strike"]["id"], "UPHELD",
            make_dispatch_admin_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_ADJUDICATION_FORBIDDEN)
        # A distinct admin identity adjudicates successfully.
        resp = api.adjudicate_strike_report(ctx["strike"]["id"], "UPHELD", ADMIN2)
        strike = validate_success(resp)
        assert strike["status"] == "UPHELD"
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        assert validate_success(resp)["strike_count"] == 1


class TestDonorThirdStrikeSuspension:
    def _setup_three_strikes(self, api):
        donor = create_donor(legal_name="ST Bistro", ein="100000013",
                             contact_email="st@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"])
        offers = [
            create_offer(donor["id"], food_category="SHELF_STABLE",
                         estimated_weight_lbs=10, publish=True)
            for _ in range(4)
        ]
        set_clock("2026-08-02T09:30:00Z")
        strikes = []
        for offer in offers[:3]:
            run = dispatch_run(offer["id"], driver_id=driver["id"],
                               agency_id=agency["id"])
            respond_run(run["id"], driver["id"], "ACCEPT")
            fail_run(run["id"], "DONOR", "DONOR_NO_SHOW",
                     as_driver_id=driver["id"])
            resp = api.list_run_strike_reports(run["id"], ADMIN)
            strikes.append(validate_success(resp)[0])
        return {"donor": donor, "offers": offers, "strikes": strikes}

    def test_third_upheld_strike_suspends_donor_with_cascade(self, api):
        """PRD §3.6: "Against a donor site, `strike_count` increments by one,
        and the third upheld strike — the boundary is inclusive — suspends the
        donor."
        PRD §3.6: "A suspended donor sees every one of its offers in `DRAFT` or
        `OPEN` cancelled outright with no strike, and every offer in `MATCHED`
        or `SCHEDULED` cancelled with its current run torn down to `CANCELLED` —
        window released, reservations released, coolers freed, agency commitment
        released — while offers already `PICKED_UP` or `DELIVERED` are in flight
        and untouched."

        Design: Corner/calculations/donor_third_upheld_strike_suspends_with_cascade
        """
        s = self._setup_three_strikes(api)
        for i, strike in enumerate(s["strikes"], start=1):
            resp = api.adjudicate_strike_report(strike["id"], "UPHELD", ADMIN2)
            validate_success(resp)
            resp = api.get_donor_site(s["donor"]["id"], ADMIN)
            donor = validate_success(resp)
            assert donor["strike_count"] == i
            if i < 3:
                assert donor["status"] == "ACTIVE", f"{i} < 3: not yet suspended"
        assert donor["status"] == "SUSPENDED", (
            "the 3rd upheld strike trips the inclusive threshold"
        )
        # The suspension cascade cancels every non-in-flight offer.
        for offer in s["offers"]:
            resp = api.get_donation_offer(offer["id"], ADMIN)
            assert validate_success(resp)["status"] == "CANCELLED"


class TestReliabilityScoreLifecycle:
    def test_cap_penalty_reset_and_recovery(self, api):
        """PRD §3.7: "The driver's reliability ledger rewards completion:
        `completed_run_count` increments by one and `reliability_score` rises by
        5, capped at 100. Combined with the strike penalties of §3.6, a driver's
        score starts at 100, gains up to 5 per verified rescue, loses 50 per
        upheld strike with a floor of zero, suspends the driver only when it
        falls strictly below 60, and resets to 80 on reinstatement."

        Design: Corner/calculations/reliability_cap_penalty_reset_and_recovery
        """
        donor = create_donor(legal_name="Rel Bistro", ein="100000014",
                             contact_email="rel@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
        add_window(driver["id"], "2026-08-02T12:00:00Z", "2026-08-02T14:00:00Z")
        add_window(driver["id"], "2026-08-02T14:00:00Z", "2026-08-02T17:00:00Z")
        o1 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=10,
                          pickup_window_start="2026-08-02T10:00:00Z",
                          pickup_window_end="2026-08-02T11:00:00Z", publish=True)
        o2 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=10,
                          pickup_window_start="2026-08-02T12:30:00Z",
                          pickup_window_end="2026-08-02T13:30:00Z", publish=True)
        o3 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=10,
                          pickup_window_start="2026-08-02T14:30:00Z",
                          pickup_window_end="2026-08-02T15:30:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        # R1: fully verified — the +5 bonus is capped at 100.
        r1 = dispatch_run(o1["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r1["id"], driver["id"], "ACCEPT")
        record_pickup(r1["id"], driver["id"],
                      pickup_time="2026-08-02T10:15:00Z")
        record_delivery(r1["id"], driver["id"],
                        arrival_time="2026-08-02T11:00:00Z", actual_weight_lbs=10)
        verify_run(r1["id"], agency["id"])
        resp = api.get_volunteer_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["reliability_score"] == 100, "completion bonus capped: min(100, 105)"
        assert d["completed_run_count"] == 1
        # R2: failed by an admin with fault DRIVER; upholding it drops 100->50.
        r2 = dispatch_run(o2["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r2["id"], driver["id"], "ACCEPT")
        fail_run(r2["id"], "DRIVER", "DRIVER_NO_SHOW", as_admin_id="admin-1")
        resp = api.list_run_strike_reports(r2["id"], ADMIN)
        s2 = validate_success(resp)[0]
        resp = api.adjudicate_strike_report(s2["id"], "UPHELD", ADMIN2)
        validate_success(resp)
        resp = api.get_volunteer_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["reliability_score"] == 50
        assert d["status"] == "SUSPENDED", "50 is strictly below 60"
        # Reinstatement resets the score to exactly 80.
        resp = api.patch_volunteer_driver_status(driver["id"], "ACTIVE", ADMIN)
        d = validate_success(resp)
        assert d["reliability_score"] == 80
        assert d["status"] == "ACTIVE"
        # A fresh verified run accrues the +5 bonus from the new baseline.
        r3 = dispatch_run(o3["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r3["id"], driver["id"], "ACCEPT")
        record_pickup(r3["id"], driver["id"],
                      pickup_time="2026-08-02T14:45:00Z")
        record_delivery(r3["id"], driver["id"],
                        arrival_time="2026-08-02T15:15:00Z", actual_weight_lbs=10)
        verify_run(r3["id"], agency["id"])
        resp = api.get_volunteer_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["reliability_score"] == 85
        assert d["completed_run_count"] == 2
