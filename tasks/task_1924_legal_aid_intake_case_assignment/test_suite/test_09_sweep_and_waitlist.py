"""Daily sweep pinned order: advice auto-close, waitlist promotion waterfall
(skip semantics, ranking, and the cross-step capacity handoff)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_client,
    create_application,
    create_eligible_application,
    create_openable_application,
    open_case_from_application,
    screen_application,
    decide_application,
    set_clock,
    run_sweep,
    make_supervising_attorney_headers,
    make_intake_specialist_headers,
    make_program_director_headers,
)


class TestAdviceAutoClose:
    def test_advice_case_auto_closed_after_window_via_sweep(self, api):
        """PRD §3.8: "The daily sweep auto-closes every `ADVICE_ONLY` case
        still `OPEN` whose `advice_deadline` lies strictly before the clock,
        stamping `outcome_code` as `ADMINISTRATIVE` and `closure_reason` as
        `ADVICE_WINDOW_EXPIRED`, and firing the full closure side effects
        above — attorney load release, grant release (the outcome is
        non-billable), and referral completion."
        PRD §3.6: "The first arrival at `OPEN` stamps `opened_at` from the
        logical clock, and when the case is `ADVICE_ONLY` it also sets
        `advice_deadline` to exactly 30 days after `opened_at`."

        Design: Corner/state_machines/advice_case_auto_closed_after_window_via_sweep
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"], max_units=40)
        headers_sup = make_supervising_attorney_headers(sup["id"])
        client = create_client(intake["id"], full_name="Cli Auto")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"], service_level="ADVICE_ONLY")
        # assigned (to sup, doubling as attorney) at 2026-08-01 -> deadline 2026-08-31
        validate_success(api.assign_case(
            case["id"], {"attorney_id": sup["id"],
                         "expected_case_version": case["version"]}, headers_sup))
        set_clock("2026-09-01T00:00:00Z")
        sweep = run_sweep()
        assert sweep["auto_closed_cases"] == 1
        c = validate_success(api.get_case(case["id"], make_program_director_headers()))
        assert c["status"] == "CLOSED"
        assert c["outcome_code"] == "ADMINISTRATIVE"
        assert c["closure_reason"] == "ADVICE_WINDOW_EXPIRED"
        load = validate_success(api.get_caseload(sup["id"], make_program_director_headers()))
        assert load["weighted_open_units"] == 0


class TestWaitlistWaterfall:
    def _enqueue(self, api, intake, client, case_type, opposing):
        app = create_application(intake["id"], client["id"], case_type=case_type,
                                 opposing_party_name=opposing)
        screen_application(app["id"], intake["id"])
        decide_application(app["id"], "ELIGIBLE", intake["id"])
        headers = make_intake_specialist_headers(intake["id"])
        validate_success(api.enqueue_waitlist(app["id"], headers))
        return app

    def test_waitlist_waterfall_skips_oversized_entry(self, api):
        """PRD §3.4: "Entries are considered in ranking order:
        `priority_score_snapshot` descending, ties broken by `created_at`
        ascending, with no further tie-breakers. An entry whose
        `required_weight` fits within the remaining pool is promoted: its
        application moves from `WAITLISTED` back to `ELIGIBLE`, the
        application's `promoted_from_waitlist` flag becomes true, the entry
        is deleted, and the pool shrinks by that entry's `required_weight`.
        An entry that does not fit is skipped without blocking later entries
        — there is no head-of-line blocking — and entries surviving the sweep
        remain waitlisted with their original snapshots."

        Design: Corner/calculations/waitlist_waterfall_skips_oversized_entry
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="EXPUNGEMENT",
                          venue="SUPERIOR_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist()
        # single attorney doubles as supervisor identity; max 9, one EXTENDED case -> pool 4
        att = create_attorney(full_name="Att Solo", max_units=9,
                              practice_areas=["EVICTION_DEFENSE", "FAMILY_DV"])
        headers_att_sup = make_supervising_attorney_headers(att["id"])
        headers_in = make_intake_specialist_headers(intake["id"])

        client2 = create_client(intake["id"], full_name="Cli Funded", household_size=2,
                                vulnerability_factors=["DV_SURVIVOR"])
        app_f = create_openable_application(intake["id"], client2["id"],
                                            case_type="FAMILY_DV", opposing_party_name="Abuser")
        case_f = open_case_from_application(app_f["id"], att["id"], service_level="EXTENDED")
        validate_success(api.assign_case(case_f["id"], {"attorney_id": att["id"],
                                                        "expected_case_version": case_f["version"]},
                                         headers_att_sup))

        client = create_client(intake["id"], full_name="Cli W")
        app_a = self._enqueue(api, intake, client, "EVICTION_DEFENSE", "L")      # 70.00 -> 5
        app_b = self._enqueue(api, intake, client, "BENEFITS_APPEAL", "Agency")  # 50.00 -> 2
        app_c = self._enqueue(api, intake, client, "CONSUMER_DEBT", "C1")        # 30.00 -> 2 (earlier)
        app_d = self._enqueue(api, intake, client, "EXPUNGEMENT", "State")       # 30.00 -> 2 (later)

        sweep = run_sweep()
        assert sweep["promoted_applications"] == 2

        st_a = validate_success(api.get_application(app_a["id"], headers_in))
        assert st_a["status"] == "WAITLISTED"  # skipped: 5 > pool 4, no head-of-line blocking
        st_b = validate_success(api.get_application(app_b["id"], headers_in))
        assert st_b["status"] == "ELIGIBLE" and st_b["promoted_from_waitlist"] is True
        st_c = validate_success(api.get_application(app_c["id"], headers_in))
        assert st_c["status"] == "ELIGIBLE" and st_c["promoted_from_waitlist"] is True
        st_d = validate_success(api.get_application(app_d["id"], headers_in))
        assert st_d["status"] == "WAITLISTED"  # pool exhausted

    def test_selector_waitlist_ranking_tie_break(self, api):
        """PRD §3.4: "Entries are considered in ranking order:
        `priority_score_snapshot` descending, ties broken by `created_at`
        ascending, with no further tie-breakers."
        PRD §3.4: "The waitlist listing presents entries in this same ranking
        order and can be filtered by `application_id`."
        PRD §3.4: "doing so creates a `WaitlistEntry` that freezes the
        application's current `priority_score` into `priority_score_snapshot`
        and computes a `required_weight` of 5 when that snapshot is at least
        60.00, or 2 otherwise."

        Design: Corner/calculations/selector_waitlist_ranking_tie_break
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="EXPUNGEMENT",
                          venue="SUPERIOR_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli W",
                               vulnerability_factors=["ELDERLY"])
        app_a = self._enqueue(api, intake, client, "EVICTION_DEFENSE", "L")      # 50*1.15+20=77.50
        app_b = self._enqueue(api, intake, client, "BENEFITS_APPEAL", "Agency")  # 40*1.15+10=56.00
        app_c = self._enqueue(api, intake, client, "CONSUMER_DEBT", "C1")        # 30*1.15=34.50 first
        app_d = self._enqueue(api, intake, client, "EXPUNGEMENT", "State")       # 34.50 second

        entries, meta = validate_paginated(api.list_waitlist_entries(
            make_supervising_attorney_headers(intake["id"])))
        assert meta["total_count"] == 4
        order = [e["application_id"] for e in entries]
        assert order == [app_a["id"], app_b["id"], app_c["id"], app_d["id"]]
        snapshots = {e["application_id"]: e["priority_score_snapshot"] for e in entries}
        assert snapshots[app_a["id"]] == pytest.approx(77.50, abs=0.001)
        assert snapshots[app_b["id"]] == pytest.approx(56.00, abs=0.001)
        assert snapshots[app_c["id"]] == pytest.approx(34.50, abs=0.001)
        weights = {e["application_id"]: e["required_weight"] for e in entries}
        assert weights[app_a["id"]] == 5   # 77.50 >= 60.00
        assert weights[app_b["id"]] == 2
        assert weights[app_c["id"]] == 2
        assert weights[app_d["id"]] == 2

    def test_sweep_autoclose_frees_capacity_for_same_sweep_promotion(self, api):
        """PRD §3.9: "The daily sweep, a `ProgramDirector` capability, is the
        system's scheduled conscience, and its four steps execute in a pinned
        order because the order is observable. First, conflict-check expiry:
        every `ConflictCheck` in `CLEAR` or `WAIVED` whose `valid_until` lies
        strictly before the current logical clock becomes `EXPIRED`. Second,
        referral expiry: every referral in `OFFERED` whose `response_deadline`
        lies strictly before the clock becomes `EXPIRED`. Third, advice
        auto-close per §3.8. Fourth, the waitlist promotion waterfall of §3.4
        runs against the capacity remaining after step three, so closures in
        the same sweep free units that promotion immediately consumes."

        Design: Corner/cross_cutting_complexity_layers/sweep_autoclose_frees_capacity_for_same_sweep_promotion
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        att = create_attorney(full_name="Att Solo", max_units=7,
                              practice_areas=["FAMILY_DV", "CONSUMER_DEBT"])
        headers_att_sup = make_supervising_attorney_headers(att["id"])
        headers_in = make_intake_specialist_headers(intake["id"])

        # EXTENDED case (5 units) on the solo attorney
        cl_e = create_client(intake["id"], full_name="Cli E", household_size=2,
                             vulnerability_factors=["DV_SURVIVOR"])
        app_e = create_openable_application(intake["id"], cl_e["id"], case_type="FAMILY_DV",
                                            opposing_party_name="Abuser")
        case_e = open_case_from_application(app_e["id"], att["id"], service_level="EXTENDED")
        validate_success(api.assign_case(case_e["id"], {"attorney_id": att["id"],
                                                        "expected_case_version": case_e["version"]},
                                         headers_att_sup))
        # ADVICE_ONLY case (2 units) -> attorney fully loaded at 7/7
        cl_a = create_client(intake["id"], full_name="Cli Adv")
        app_a = create_openable_application(intake["id"], cl_a["id"], case_type="CONSUMER_DEBT",
                                            opposing_party_name="Collector")
        case_a = open_case_from_application(app_a["id"], att["id"], service_level="ADVICE_ONLY")
        validate_success(api.assign_case(case_a["id"], {"attorney_id": att["id"],
                                                        "expected_case_version": case_a["version"]},
                                         headers_att_sup))
        # one waitlisted application requiring 2 units
        cl_w = create_client(intake["id"], full_name="Cli W")
        app_w = create_eligible_application(intake["id"], cl_w["id"], case_type="CONSUMER_DEBT",
                                            opposing_party_name="Other Collector")
        validate_success(api.enqueue_waitlist(app_w["id"], headers_in))

        # advice deadline 2026-08-31 passed at 2026-09-01; conflict checks valid until 2026-09-15
        set_clock("2026-09-01T00:00:00Z")
        sweep = run_sweep()
        assert sweep["auto_closed_cases"] == 1
        # promotion possible ONLY because the auto-close freed 2 units first
        assert sweep["promoted_applications"] == 1
        w = validate_success(api.get_application(app_w["id"], headers_in))
        assert w["status"] == "ELIGIBLE"
        assert w["promoted_from_waitlist"] is True
        load = validate_success(api.get_caseload(att["id"], make_program_director_headers()))
        assert load["weighted_open_units"] == 5  # 7 - 2 freed
        e = validate_success(api.get_case(case_e["id"], make_program_director_headers()))
        assert e["status"] == "OPEN"  # EXTENDED case untouched
