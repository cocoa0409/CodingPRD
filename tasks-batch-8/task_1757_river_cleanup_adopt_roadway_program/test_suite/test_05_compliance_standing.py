"""Compliance standing: rolling window, anniversary windows, counters
(PRD §2.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    brief_event,
    complete_event,
    create_adult_waiver,
    create_event,
    get_agreement,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestCleanupCountBoundary:
    def test_cleanup_count_exactly_three_vs_two(self, api):
        """PRD §2.6: "the agreement is `COMPLIANT` when the count is at least
        three — exactly three qualifies. Below three, the agreement remains
        `NOT_EVALUATED` while its age, measured as today minus
        `term_start_date`, is under 180 days; once the agreement is at least
        180 days old with a count still below three, it becomes
        `NON_COMPLIANT`."
        PRD §2.6: "The auto-suspension sweep acts only on agreements that are
        at least 180 days old and whose rolling count is below three."

        Design: Difficulty/boundary_precision_check/cleanup_count_exactly_three_vs_two
        """
        # Agreement X: 3 completions in window.
        gx, sx, agx = setup_active_agreement(
            group_name="Group X", contact_email="x@x.org",
            route_name="Alpha Rd", segment_type="ROADWAY", water_adjacent=False,
        )
        wx = create_adult_waiver(agx["id"], gx["id"], name="Ada Adult")
        # Agreement Y: 2 completions in window.
        gy, sy, agy = setup_active_agreement(
            group_name="Group Y", org_type="SCHOOL", contact_email="y@y.org",
            route_name="Beta Rd", mile_marker_start=10.0, mile_marker_end=12.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        wy = create_adult_waiver(agy["id"], gy["id"], name="Ben Adult",
                                 dob="1988-03-15")

        ex1 = create_event(agx["id"], gx["id"], scheduled_date="2026-09-10",
                           expected_volunteers=3)
        brief_event(ex1["id"], gx["id"], [wx["id"]])
        ex2 = create_event(agx["id"], gx["id"], scheduled_date="2026-09-12",
                           expected_volunteers=3)
        brief_event(ex2["id"], gx["id"], [wx["id"]])
        ex3 = create_event(agx["id"], gx["id"], scheduled_date="2026-09-14",
                           expected_volunteers=3)
        brief_event(ex3["id"], gx["id"], [wx["id"]])
        ey1 = create_event(agy["id"], gy["id"], scheduled_date="2026-09-10",
                           expected_volunteers=3)
        brief_event(ey1["id"], gy["id"], [wy["id"]])
        ey2 = create_event(agy["id"], gy["id"], scheduled_date="2026-09-12",
                           expected_volunteers=3)
        brief_event(ey2["id"], gy["id"], [wy["id"]])

        set_clock("2026-09-10T10:00:00Z")
        complete_event(ex1["id"], gx["id"])
        complete_event(ey1["id"], gy["id"])
        set_clock("2026-09-12T10:00:00Z")
        complete_event(ex2["id"], gx["id"])
        complete_event(ey2["id"], gy["id"])
        set_clock("2026-09-14T10:00:00Z")
        complete_event(ex3["id"], gx["id"])

        # Sweep at 2027-02-01: both agreements older than 180 days.
        set_clock("2027-02-01T09:00:00Z")
        x = get_agreement(agx["id"])
        y = get_agreement(agy["id"])
        assert x["cleanups_completed_in_window"] == 3
        assert x["standing"] == "COMPLIANT"
        assert x["status"] == "ACTIVE"
        assert y["cleanups_completed_in_window"] == 2
        assert y["standing"] == "NON_COMPLIANT"
        assert y["status"] == "SUSPENDED"

    def test_two_completions_fails_threshold_after_grace(self, api):
        """PRD §2.6: "once the agreement is at least 180 days old with a count
        still below three, it becomes `NON_COMPLIANT`."
        PRD §2.6: "The auto-suspension sweep acts only on agreements that are
        at least 180 days old and whose rolling count is below three."

        Design: Difficulty/boundary_precision_check/cleanup_count_exactly_three_vs_two
        """
        group, segment, agreement = setup_active_agreement(
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        waiver = create_adult_waiver(agreement["id"], group["id"])
        # Create and brief both events at the setup clock so each satisfies the
        # 14-day lead time; only then advance the clock to complete them.
        events = []
        for day in ("2026-09-10", "2026-09-12"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [waiver["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2027-02-01T09:00:00Z")
        ag = get_agreement(agreement["id"])
        assert ag["cleanups_completed_in_window"] == 2
        assert ag["standing"] == "NON_COMPLIANT"
        assert ag["status"] == "SUSPENDED"


class TestRollingWindowInclusiveBound:
    def test_rolling_window_inclusive_lower_bound(self, api):
        """PRD §2.6: "The counter is the number of the agreement's cleanup
        events in status `COMPLETED` whose `scheduled_date` — the service date,
        not the completion date — falls within the trailing 365-day window that
        begins 365 days before today and ends today, both boundary days
        included."

        Design: Corner/calculations/rolling_window_inclusive_lower_bound
        """
        group, segment, agreement = setup_active_agreement()
        waiver = create_adult_waiver(agreement["id"], group["id"])
        events = []
        for day in ("2026-08-20", "2026-09-10", "2026-09-15"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [waiver["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        # At 2027-08-20 the window is [2026-08-20, 2027-08-20]: all 3 count.
        set_clock("2027-08-20T09:00:00Z")
        d0 = get_agreement(agreement["id"])
        assert d0["cleanups_completed_in_window"] == 3
        assert d0["status"] == "ACTIVE"

        # At 2027-08-21 the oldest cleanup ages out: count 2 -> sweep suspends.
        set_clock("2027-08-21T09:00:00Z")
        d1 = get_agreement(agreement["id"])
        assert d1["cleanups_completed_in_window"] == 2
        assert d1["status"] == "SUSPENDED"

    def test_rolling_window_ages_out_oldest_cleanup(self, api):
        """PRD §2.6: "the trailing 365-day window that begins 365 days before
        today and ends today, both boundary days included."

        Design: Corner/calculations/rolling_window_inclusive_lower_bound
        """
        group, segment, agreement = setup_active_agreement()
        waiver = create_adult_waiver(agreement["id"], group["id"])
        events = []
        for day in ("2026-08-20", "2026-09-10", "2026-09-15"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [waiver["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        # Window slides one day past the oldest completion.
        set_clock("2027-08-21T09:00:00Z")
        ag = get_agreement(agreement["id"])
        assert ag["cleanups_completed_in_window"] == 2
        assert ag["standing"] == "NON_COMPLIANT"


class TestRollingVsAnniversary:
    def test_standing_rolling_vs_anniversary_windows(self, api):
        """PRD §2.6: "Every one of these windows must hold at least three
        `COMPLETED` cleanups for renewal approval to be eligible; membership is
        again by `scheduled_date`. Because the two measures are anchored
        differently, the same completion history can be `COMPLIANT` under the
        rolling measure yet ineligible for renewal under the anniversary
        measure."

        Design: Difficulty/dual_variant_calc/standing_rolling_vs_anniversary_windows
        """
        group, segment, agreement = setup_active_agreement()
        # Two adults because the first waiver expires before 2028 (signed
        # 2026-08-01, expiry 2027-08-01).
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        e1 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=4)
        brief_event(e1["id"], group["id"], [w1["id"]])
        e2 = create_event(agreement["id"], group["id"],
                          scheduled_date="2027-08-10", expected_volunteers=4)
        brief_event(e2["id"], group["id"], [w1["id"]])
        e3 = create_event(agreement["id"], group["id"],
                          scheduled_date="2027-08-20", expected_volunteers=4)
        brief_event(e3["id"], group["id"], [w1["id"]])

        set_clock("2026-09-10T10:00:00Z")
        complete_event(e1["id"], group["id"])
        set_clock("2027-08-10T10:00:00Z")
        complete_event(e2["id"], group["id"])
        set_clock("2027-08-20T10:00:00Z")
        complete_event(e3["id"], group["id"])

        # Mid-chain: rolling window [2026-08-25, 2027-08-25] holds 3 -> COMPLIANT.
        set_clock("2027-08-25T10:00:00Z")
        mid = get_agreement(agreement["id"])
        assert mid["status"] == "ACTIVE"
        assert mid["standing"] == "COMPLIANT"
        assert mid["cleanups_completed_in_window"] == 3

        # Second waiver signed at 2027-08-25 (w1 expired 2027-08-01).
        w2 = create_adult_waiver(agreement["id"], group["id"], name="Ben Adult",
                                 dob="1988-03-15")
        e4 = create_event(agreement["id"], group["id"],
                          scheduled_date="2028-04-01", expected_volunteers=4)
        brief_event(e4["id"], group["id"], [w2["id"]])
        e5 = create_event(agreement["id"], group["id"],
                          scheduled_date="2028-04-15", expected_volunteers=4)
        brief_event(e5["id"], group["id"], [w2["id"]])
        e6 = create_event(agreement["id"], group["id"],
                          scheduled_date="2028-05-01", expected_volunteers=4)
        brief_event(e6["id"], group["id"], [w2["id"]])

        set_clock("2028-04-01T10:00:00Z")
        complete_event(e4["id"], group["id"])
        set_clock("2028-04-15T10:00:00Z")
        complete_event(e5["id"], group["id"])
        set_clock("2028-05-01T10:00:00Z")
        complete_event(e6["id"], group["id"])

        # Clock inside the renewal window [2028-05-03, 2028-08-01].
        set_clock("2028-05-10T10:00:00Z")
        gl = make_group_leader_headers(group["id"])
        rr = validate_success(api.renewal_request(agreement["id"], gl), 200)
        assert rr["status"] == "RENEWAL_REVIEW"
        assert rr["renewal_count"] == 0

        # Rolling count at 2028-05-10 is 5 (COMPLIANT), but the ANNIVERSARY
        # window [2026-08-01, 2027-08-01) holds only 1 completion (< 3).
        resp = api.renewal_decision(agreement["id"], {"decision": "APPROVE"}, COORD)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE)

    def test_renewal_denied_when_first_anniversary_window_deficient(self, api):
        """PRD §3.8: "every 12-month term window must hold at least three
        `COMPLETED` cleanups, and no hazard report on the segment may sit in
        `REPORTED` or `ACKNOWLEDGED` — failing either condition draws
        `ERR_RENEWAL_NOT_ELIGIBLE`."

        Design: Difficulty/dual_variant_calc/standing_rolling_vs_anniversary_windows
        """
        # Completions clustered entirely in the second anniversary window.
        group, segment, agreement = setup_active_agreement()
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        # Three completions all in window 2 (2027-08-01 .. 2028-08-01): the
        # first anniversary window holds zero completions. Brief every event
        # up front: BRIEFING_DONE events are deliberately untouched by the
        # suspension cascade (PRD §3.2), so they survive the clock jumps that
        # would otherwise cancel SCHEDULED events once the agreement crosses
        # 180 days of age with an empty rolling window.
        events = []
        for day in ("2028-04-01", "2028-04-15", "2028-05-01"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [w1["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2028-05-10T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        validate_success(api.renewal_request(agreement["id"], gl), 200)
        resp = api.renewal_decision(agreement["id"], {"decision": "APPROVE"}, COORD)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE)


class TestAgreementCounterReconciliation:
    def test_agreement_counter_reconciles_after_each_completion(self, api):
        """PRD §2.6: "Both the counter and the standing are recomputed on every
        debris-report submission and on every clock sweep."
        PRD §2.6: "Below three, the agreement remains `NOT_EVALUATED` while its
        age, measured as today minus `term_start_date`, is under 180 days"

        Design: Corner/cross_cutting_complexity_layers/agreement_counter_reconciles_after_each_completion
        """
        group, segment, agreement = setup_active_agreement()
        waiver = create_adult_waiver(agreement["id"], group["id"])
        e1 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=2)
        brief_event(e1["id"], group["id"], [waiver["id"]])
        e2 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-12", expected_volunteers=2)
        brief_event(e2["id"], group["id"], [waiver["id"]])

        c0 = get_agreement(agreement["id"])
        assert c0["cleanups_completed_in_window"] == 0
        assert c0["standing"] == "NOT_EVALUATED"

        set_clock("2026-09-10T10:00:00Z")
        complete_event(e1["id"], group["id"])
        c1 = get_agreement(agreement["id"])
        assert c1["cleanups_completed_in_window"] == 1
        assert c1["standing"] == "NOT_EVALUATED"

        set_clock("2026-09-12T10:00:00Z")
        complete_event(e2["id"], group["id"])
        c2 = get_agreement(agreement["id"])
        assert c2["cleanups_completed_in_window"] == 2
        assert c2["standing"] == "NOT_EVALUATED"

    def test_counter_stays_in_grace_before_180_days(self, api):
        """PRD §2.6: "Below three, the agreement remains `NOT_EVALUATED` while
        its age, measured as today minus `term_start_date`, is under 180 days"

        Design: Corner/cross_cutting_complexity_layers/agreement_counter_reconciles_after_each_completion
        """
        group, segment, agreement = setup_active_agreement()
        # Zero completions but only ~40 days of age: no suspension yet.
        set_clock("2026-09-10T09:00:00Z")
        ag = get_agreement(agreement["id"])
        assert ag["cleanups_completed_in_window"] == 0
        assert ag["standing"] == "NOT_EVALUATED"
        assert ag["status"] == "ACTIVE"
