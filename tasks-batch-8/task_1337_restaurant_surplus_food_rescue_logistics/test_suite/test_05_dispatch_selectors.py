"""Dispatch-time selector policies, quota gates, and atomic side effects
(PRD §3.3)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, get_offer_version,
    make_volunteer_driver_headers,
)
from test_helpers.factories import create_donation_offer_payload

ADMIN = TEST_USERS["admin_headers"]


class TestSelectorAndQuotaErrorVariants:
    def _setup(self, api):
        donor = create_donor(legal_name="Sel Bistro", ein="100000020",
                             contact_email="sel@bistro.example")
        anc = create_agency(name="ANC", accepts_categories=("PRODUCE",),
                            capacity_produce_lbs=100)
        vsmall = create_driver(full_name="V Small", email="vs@example.com",
                               vehicle_capacity_lbs=10, cold_chain_certified=True)
        add_window(vsmall["id"])
        vnowin = create_driver(full_name="V NoWin", email="vnw@example.com",
                               cold_chain_certified=True)
        vok = create_driver(full_name="V Ok", email="vo@example.com",
                            cold_chain_certified=True)
        ct1 = create_cooler(label="CT1", capacity_liters=5)
        ct2 = create_cooler(label="CT2", capacity_liters=5)
        offer = create_offer(donor["id"], food_category="COLD_HELD",
                             estimated_weight_lbs=50, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        ov = get_offer_version(offer["id"])
        return {"donor": donor, "anc": anc, "vsmall": vsmall, "vnowin": vnowin,
                "vok": vok, "ct1": ct1, "ct2": ct2, "offer": offer, "ov": ov}

    def _dispatch(self, api, offer_id, version, **pins):
        payload = {"offer_id": offer_id, "expected_offer_version": version}
        payload.update(pins)
        return api.create_rescue_run(payload, ADMIN)

    def test_dispatch_failure_modes_map_to_distinct_errors(self, api):
        """PRD §3.3: "When `driver_id` is pinned instead, each eligibility rule
        surfaces as its own error: a driver not `ACTIVE` answers
        `ERR_DRIVER_NOT_ACTIVE`, a missing cold-chain certificate on a
        cold-chain offer answers `ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED`,
        insufficient vehicle capacity answers `ERR_DRIVER_CAPACITY_EXCEEDED`,
        and the absence of a covering `OPEN` window answers
        `ERR_DRIVER_WINDOW_MISSING`."

        Design: Corner/errors/selector_and_quota_error_variants
        """
        s = self._setup(api)
        o, ov = s["offer"]["id"], s["ov"]
        # 1. Auto-match with an empty driver pool (VSMALL too small, the other
        #    two have no covering window yet).
        resp = self._dispatch(api, o, ov)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DRIVER)
        # Give VOK a covering window so later pinned calls pass window checks.
        add_window(s["vok"]["id"])
        # 2. Pinned driver without a covering window (agency pinned but its
        #    category check is a LOWER priority tier, so the window error wins).
        resp = self._dispatch(api, o, ov, driver_id=s["vnowin"]["id"],
                              agency_id=s["anc"]["id"])
        validate_error(resp, ApiErrorId.ERR_DRIVER_WINDOW_MISSING)
        # 3. Pinned agency that does not accept the offer's category.
        resp = self._dispatch(api, o, ov, driver_id=s["vok"]["id"],
                              agency_id=s["anc"]["id"])
        validate_error(resp, ApiErrorId.ERR_AGENCY_CATEGORY_NOT_ACCEPTED)
        # 4. Auto-match with an empty agency pool (ANC accepts only PRODUCE).
        resp = self._dispatch(api, o, ov, driver_id=s["vok"]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_AGENCY)
        # 5. Pinned driver whose vehicle is too small.
        aok = create_agency(name="AOK", accepts_categories=("COLD_HELD",),
                            capacity_cold_held_lbs=100)
        resp = self._dispatch(api, o, ov, driver_id=s["vsmall"]["id"],
                              agency_id=aok["id"])
        validate_error(resp, ApiErrorId.ERR_DRIVER_CAPACITY_EXCEEDED)
        # 6. Pinned coolers summing below the required liters (5+5 < 25).
        resp = self._dispatch(api, o, ov, driver_id=s["vok"]["id"],
                              agency_id=aok["id"],
                              cooler_ids=[s["ct1"]["id"], s["ct2"]["id"]])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COOLER_CAPACITY)
        # 7. A fully-valid dispatch succeeds. Failed dispatches mutate nothing:
        #    the offer is still OPEN at the version captured before all of them.
        cbig = create_cooler(label="CBIG", capacity_liters=30)
        resp = self._dispatch(api, o, ov, driver_id=s["vok"]["id"],
                              agency_id=aok["id"], cooler_ids=[cbig["id"]])
        run = validate_success(resp, 201)
        assert run["run_status"] == "PROPOSED"
        resp = api.get_donation_offer(o, ADMIN)
        offer = validate_success(resp)
        assert offer["status"] == "MATCHED"
        assert offer["version"] == ov + 1, (
            "only the successful dispatch bumped the offer version"
        )


class TestDriverSelectorTiebreak:
    def test_window_created_at_breaks_reliability_and_start_ties(self, api):
        """PRD §3.3: "Eligible drivers are ranked by `reliability_score`
        descending, then by the covering window's `window_start` ascending, then
        by that window's `created_at` ascending — identifiers never participate
        in ranking."

        Design: Corner/cross_cutting_complexity_layers/selector_driver_tiebreak_uses_window_created_at
        """
        donor = create_donor(legal_name="TB Bistro", ein="100000031",
                             contact_email="tb@bistro.example")
        agency = create_agency(name="AG", accepts_categories=("COLD_HELD",),
                               capacity_cold_held_lbs=200)
        va = create_driver(full_name="V A", email="va@example.com",
                           cold_chain_certified=True)
        vb = create_driver(full_name="V B", email="vb@example.com",
                           cold_chain_certified=True)
        # Identical windows; VB's is created one logical second before VA's.
        set_clock("2026-08-01T10:00:00Z")
        add_window(vb["id"])
        set_clock("2026-08-01T10:00:01Z")
        add_window(va["id"])
        c1 = create_cooler(label="C1")
        c2 = create_cooler(label="C2")
        o1 = create_offer(donor["id"], publish=True)
        o2 = create_offer(donor["id"], publish=True)
        set_clock("2026-08-02T09:30:00Z")
        r1 = dispatch_run(o1["id"])  # full auto-match
        assert r1["driver_id"] == vb["id"], (
            "identical reliability and window_start: earliest-created window wins"
        )
        assert r1["agency_id"] == agency["id"]
        # VB's only window is now BOOKED, so VB is ineligible for the next one.
        r2 = dispatch_run(o2["id"])
        assert r2["driver_id"] == va["id"]


class TestAgencySelectorBestFit:
    def test_smallest_slack_wins_then_falls_to_next_fit(self, api):
        """PRD §3.3: "Ranking is best fit: the agency whose remaining slack
        after this offer — capacity minus committed minus estimated — is
        smallest comes first, ties broken by the agency's `created_at`
        ascending."

        Design: Corner/cross_cutting_complexity_layers/selector_agency_best_fit_smallest_slack
        """
        donor = create_donor(legal_name="BF Bistro", ein="100000032",
                             contact_email="bf@bistro.example")
        a_big = create_agency(name="A_BIG", accepts_categories=("SHELF_STABLE",),
                              capacity_shelf_stable_lbs=200)
        a_small = create_agency(name="A_SMALL", accepts_categories=("SHELF_STABLE",),
                                capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z")
        add_window(driver["id"], "2026-08-02T13:00:00Z", "2026-08-02T18:00:00Z")
        o1 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=60, publish=True)
        o2 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=60,
                          pickup_window_start="2026-08-02T13:30:00Z",
                          pickup_window_end="2026-08-02T15:00:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        r1 = dispatch_run(o1["id"], driver_id=driver["id"])
        assert r1["agency_id"] == a_small["id"], (
            "slack 100-60=40 beats 200-60=140 (smallest non-negative slack first)"
        )
        # A_SMALL no longer fits (60+60 > 100); only A_BIG remains eligible.
        r2 = dispatch_run(o2["id"], driver_id=driver["id"])
        assert r2["agency_id"] == a_big["id"]


class TestCoolerAllocation:
    def test_auto_mode_greedy_descending_stops_at_requirement(self, api):
        """PRD §3.3: "In auto mode — `cooler_ids` omitted — candidates are
        sorted by `capacity_liters` descending with ties broken by `created_at`
        ascending, and accumulated in that order while the running total remains
        below the required liters and the selection count remains below the
        assigned driver's `cooler_slot_count`;"

        Design: Corner/cross_cutting_complexity_layers/cooler_auto_allocation_greedy_descending
        """
        donor = create_donor(legal_name="GA Bistro", ein="100000033",
                             contact_email="ga@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"])
        c10 = create_cooler(label="C10", capacity_liters=10)
        c30 = create_cooler(label="C30", capacity_liters=30)
        c20 = create_cooler(label="C20", capacity_liters=20)
        offer = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        run = dispatch_run(offer["id"], driver_id=driver["id"],
                           agency_id=agency["id"])
        resp = api.list_run_cooler_reservations(run["id"], ADMIN)
        reservations = validate_success(resp)
        # 25 liters required; the greedy descent takes C30 alone and stops.
        assert len(reservations) == 1, "greedy stops once the requirement is met"
        assert reservations[0]["cooler_id"] == c30["id"]
        assert reservations[0]["status"] == "RESERVED"

    def test_pinned_cooler_exact_fit_is_inclusive(self, api):
        """PRD §3.3: "The requirement is the offer's `estimated_weight_lbs`
        scaled by half a liter per pound and rounded up to a whole liter."
        PRD §3.3: "and the pinned set must fit within the driver's
        `cooler_slot_count` while summing to at least the required liters, else
        `ERR_INSUFFICIENT_COOLER_CAPACITY`."
        PRD §3.1: "a blocked interval whose `blocked_start` is the offer's
        `pickup_window_start` at dispatch time and whose `blocked_end` is the
        offer's `pickup_window_end` plus 135 minutes — a 90-minute return
        allowance followed by a 45-minute cleaning buffer."

        Design: Corner/calculations/cooler_liters_exact_fit_inclusive
        """
        donor = create_donor(legal_name="Fit Bistro", ein="100000015",
                             contact_email="fit@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True, cooler_slot_count=1)
        add_window(driver["id"])
        cx = create_cooler(label="CX", capacity_liters=13)
        offer = create_offer(donor["id"], estimated_weight_lbs=25, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        # ceil(25 x 0.5) == 13 and 13 >= 13: the exact fit must be accepted.
        run = dispatch_run(offer["id"], driver_id=driver["id"],
                           agency_id=agency["id"], cooler_ids=[cx["id"]])
        resp = api.list_run_cooler_reservations(run["id"], ADMIN)
        reservations = validate_success(resp)
        assert len(reservations) == 1
        res = reservations[0]
        assert res["cooler_id"] == cx["id"]
        assert res["status"] == "RESERVED"
        assert res["blocked_start"].startswith("2026-08-02T10:00")
        assert res["blocked_end"].startswith("2026-08-02T14:15"), (
            "blocked_end = pickup_window_end + 135 minutes"
        )


class TestAgencyCapacityInclusiveBoundary:
    def _setup(self, api):
        """Agency with exactly 100 lbs of cold capacity; offers of 60, 40, and
        1 lbs wait OPEN with non-overlapping pickup windows."""
        donor = create_donor(legal_name="Cap Bistro", ein="787878787",
                             contact_email="cap@bistro.example")
        agency = create_agency(name="AG", capacity_cold_held_lbs=100)
        driver = create_driver(cold_chain_certified=True, cooler_slot_count=3)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
        add_window(driver["id"], "2026-08-02T12:00:00Z", "2026-08-02T14:00:00Z")
        add_window(driver["id"], "2026-08-02T14:00:00Z", "2026-08-02T17:00:00Z")
        c1 = create_cooler(label="C1")
        c2 = create_cooler(label="C2", capacity_liters=20)
        o1 = create_offer(donor["id"], estimated_weight_lbs=60,
                          pickup_window_start="2026-08-02T10:00:00Z",
                          pickup_window_end="2026-08-02T11:00:00Z", publish=True)
        o2 = create_offer(donor["id"], estimated_weight_lbs=40,
                          pickup_window_start="2026-08-02T12:30:00Z",
                          pickup_window_end="2026-08-02T13:30:00Z", publish=True)
        o3 = create_offer(donor["id"], estimated_weight_lbs=1,
                          pickup_window_start="2026-08-02T14:30:00Z",
                          pickup_window_end="2026-08-02T15:30:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        return {"donor": donor, "agency": agency, "driver": driver,
                "c1": c1, "c2": c2, "o1": o1, "o2": o2, "o3": o3}

    def test_exactly_full_capacity_accepted(self, api):
        """PRD §3.3: "the agency selector admits agencies whose
        `accepts_categories` contains the offer's `food_category` and whose
        committed load for that category plus the offer's `estimated_weight_lbs`
        does not exceed the matching capacity ceiling — the boundary is
        inclusive, so exactly filling a category is allowed."

        Design: Difficulty/boundary_precision_check/agency_capacity_exactly_full_boundary
        """
        s = self._setup(api)
        dispatch_run(s["o1"]["id"], driver_id=s["driver"]["id"],
                     agency_id=s["agency"]["id"], cooler_ids=[s["c1"]["id"]])
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 60
        # 60 + 40 == 100: exactly filling the category must be accepted.
        dispatch_run(s["o2"]["id"], driver_id=s["driver"]["id"],
                     agency_id=s["agency"]["id"], cooler_ids=[s["c2"]["id"]])
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 100

    def test_one_pound_over_full_capacity_rejected(self, api):
        """PRD §3.3: "A pinned agency that does not accept the category is
        rejected with `ERR_AGENCY_CATEGORY_NOT_ACCEPTED`, and one whose capacity
        would be exceeded answers `ERR_AGENCY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/agency_capacity_exactly_full_boundary
        """
        s = self._setup(api)
        dispatch_run(s["o1"]["id"], driver_id=s["driver"]["id"],
                     agency_id=s["agency"]["id"], cooler_ids=[s["c1"]["id"]])
        dispatch_run(s["o2"]["id"], driver_id=s["driver"]["id"],
                     agency_id=s["agency"]["id"], cooler_ids=[s["c2"]["id"]])
        # A fresh cooler so the priority-9 ERR_COOLER_UNAVAILABLE check does
        # not pre-empt the priority-11 ERR_AGENCY_CAPACITY_EXCEEDED being
        # exercised here (PRD §2.5 fixed order).
        c3 = create_cooler(label="C3")
        # 100 + 1 > 100: a single pound over is rejected.
        payload = {"offer_id": s["o3"]["id"],
                   "expected_offer_version": get_offer_version(s["o3"]["id"]),
                   "driver_id": s["driver"]["id"],
                   "agency_id": s["agency"]["id"],
                   "cooler_ids": [c3["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGENCY_CAPACITY_EXCEEDED)
        resp = api.get_recipient_agency(s["agency"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 100


class TestImmediateConsistency:
    def test_dispatch_side_effects_visible_on_immediate_reads(self, api):
        """PRD §3.3: "A successful dispatch lands a bundle of effects as one
        atomic act. The offer moves from `OPEN` to `MATCHED`, its `version`
        increments by one, and `current_run_id` is set to the new run."
        PRD §3.3: "The selected window goes from `OPEN` to `BOOKED` with
        `booked_run_id` pointing at the run. Each selected cooler moves from
        `AVAILABLE` to `RESERVED` under a fresh `RESERVED` reservation carrying
        the buffered blocked interval. And the agency's committed counter for
        the offer's category rises by the snapshot weight, reserving capacity
        per the accounting of §3.7."

        Design: Corner/consistency_model/immediate_visibility_of_dispatch_side_effects
        """
        donor = create_donor(legal_name="IM Bistro", ein="100000034",
                             contact_email="im@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"])
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        ov = get_offer_version(offer["id"])
        run = dispatch_run(offer["id"], driver_id=driver["id"],
                           agency_id=agency["id"], cooler_ids=[cooler["id"]])
        assert run["run_status"] == "PROPOSED"
        assert run["estimated_weight_snapshot"] == 50, "estimate pinned at dispatch"
        resp = api.get_donation_offer(offer["id"], ADMIN)
        o = validate_success(resp)
        assert o["status"] == "MATCHED"
        assert o["version"] == ov + 1
        assert o["current_run_id"] == run["id"]
        resp = api.get_recipient_agency(agency["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 50
        resp = api.get_cooler(cooler["id"], ADMIN)
        assert validate_success(resp)["status"] == "RESERVED"
        resp = api.list_availability_windows(driver["id"], ADMIN)
        windows = validate_success(resp)
        assert windows[0]["status"] == "BOOKED"
        assert windows[0]["booked_run_id"] == run["id"]
