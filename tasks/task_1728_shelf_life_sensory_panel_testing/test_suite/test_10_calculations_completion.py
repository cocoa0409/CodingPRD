"""Computed quantities and study completion: session power sizing with the
pinned evaluation order, per-session settlement rounding, the retain sweep's
strict boundary, and abort compensation."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_arm,
    add_time_point,
    analyze_session,
    assign_panelist,
    attach_and_submit_report,
    create_chamber,
    create_client,
    create_draft_study,
    create_draft_report,
    create_lab_result_payload,
    create_qualified_panelist,
    create_session,
    get_chamber,
    get_client,
    get_report,
    get_session,
    get_study,
    get_success_data,
    list_sample_units,
    lock_session,
    open_session,
    propose_and_accept_recommendation,
    pull_units,
    set_clock,
    setup_completed_study,
    submit_all_scores,
    submit_and_approve,
    walk_report_to_client_review,
    activate,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]
AN = TEST_USERS["analyst_headers"]


class TestSessionPowerSizing:
    def _power_scenario(self, api):
        """Study (delta 2.0) with control+variant arms; S1 (control, tp0,
        10:00-11:00) created while SCHEDULED, then fully ANALYZED with OVERALL
        scores 7,8,7,8,7,8,7,8,7. Returns (study, arm_v, tp0, s1_created_count,
        s1_id)."""
        set_clock()
        client = create_client(topup_hours=100)
        study = create_draft_study(client["id"],
                                   product_name="Salsa",
                                   min_detectable_difference=2.0)
        arm_c = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        arm_v = add_arm(study["id"], "MAP", is_control=False)
        tp0 = add_time_point(study["id"], 0)
        chamber = create_chamber(chamber_code="CH-P", temp_c=20,
                                 capacity_units=30)
        submit_and_approve(study["id"])
        s1 = create_session(study["id"], tp0["id"], arm_c["id"],
                            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        s1_required_at_creation = s1["required_panelist_count"]
        activate(study["id"])
        pull_units(tp0["id"], chamber["id"], arm_c["id"], quantity=9,
                   unit_purpose="EVALUATION")
        panelists = [create_qualified_panelist() for _ in range(9)]
        assignments = [assign_panelist(s1["id"], p["id"]) for p in panelists]
        set_clock("2026-08-01T10:00:00Z")
        open_session(s1["id"])
        overalls = [7, 8, 7, 8, 7, 8, 7, 8, 7]
        for i, overall in enumerate(overalls):
            submit_all_scores(assignments[i]["id"], panelists[i]["id"],
                              uniform_score=9, overall_score=overall)
        s1_locked = lock_session(s1["id"])
        analyze_session(s1["id"])
        return study, arm_v, tp0, s1_required_at_creation, s1_locked

    def test_default_variance_sizes_first_session(self, api):
        """PRD §3.5: "First, the variance figure: the sample variance — denominator one less than the count — of all `OVERALL` attribute scores belonging to this study's sessions in `ANALYZED` status; when the study has no `ANALYZED` session yet, the variance defaults to 2.25. Second, the detectable difference is the study's `min_detectable_difference`. Third, the raw panel size is two times the square of the sum of 1.96 and 0.84, multiplied by that variance, and divided by the square of the detectable difference. Fourth and last, the raw size is rounded up to a whole number and only then clamped: below 4 it rises to 4, above 12 it falls to 12."
        PRD §3.5: "The session's `overall_mean` is computed as the mean of the `OVERALL` scores across its `SUBMITTED` assignments only"

        Design: Difficulty/combinatorial_formula/session_quorum_power_sizing
        """
        _study, _arm_v, _tp0, s1_required, s1_locked = self._power_scenario(api)
        # no ANALYZED session existed: variance 2.25, delta 2.0
        # n_raw = 2 * (1.96 + 0.84)^2 * 2.25 / 4 = 8.82 -> ceil 9
        assert s1_required == 9
        # mean of 7,8,7,8,7,8,7,8,7 = 67/9 = 7.4444 -> 7.44 (2dp half-up)
        assert s1_locked["overall_mean"] == pytest.approx(7.44, abs=0.005)

    def test_observed_variance_resizes_and_never_resizes_existing(self, api):
        """PRD §3.5: "The result is frozen on the session as `required_panelist_count` at creation; sessions analyzed later never retroactively resize existing sessions."
        PRD §3.5: "Fourth and last, the raw size is rounded up to a whole number and only then clamped: below 4 it rises to 4, above 12 it falls to 12."

        Design: Difficulty/combinatorial_formula/session_quorum_power_sizing
        """
        study, arm_v, tp0, s1_required, s1_locked = self._power_scenario(api)
        s1_id = s1_locked["id"]

        # the ANALYZED S1 now supplies the observed sample variance:
        # scores 7x5 / 8x4 -> ss 2.222222 / (9-1) = 0.277778
        # n_raw = 2 * (1.96 + 0.84)^2 * 0.277778 / 4 = 1.088889 -> ceil 2
        # -> clamped up to the floor of 4
        s2 = validate_success(api.create_session(
            {"study_id": study["id"], "time_point_id": tp0["id"],
             "arm_id": arm_v["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_end_utc": "2026-08-01T13:00:00Z"}, PC), 201)
        assert s2["required_panelist_count"] == 4

        assert get_session(s1_id)["required_panelist_count"] == 9, (
            "the count is frozen at creation; later analysis does not resize it")
        assert s1_required == 9


class TestSettlementRoundingOrder:
    def _settlement_scenario(self, api):
        """Client topped 50; study (2 arms, tp0; reserve 20); S1 25-min and S2
        35-min, each ANALYZED with 4 SUBMITTED assignments; one APC 3.0 (no
        trip); both arms' recommendations ACCEPTED; report in CLIENT_REVIEW.
        Returns (env, report)."""
        set_clock()
        client = create_client(topup_hours=50)
        study = create_draft_study(client["id"], product_name="Hummus")
        arm_c = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        arm_v = add_arm(study["id"], "HIGH_BARRIER", is_control=False)
        tp0 = add_time_point(study["id"], 0)
        chamber = create_chamber(chamber_code="CH-R", temp_c=20,
                                 capacity_units=20)
        submit_and_approve(study["id"])
        s1 = create_session(study["id"], tp0["id"], arm_c["id"],
                            "2026-08-01T10:00:00Z", "2026-08-01T10:25:00Z")
        s2 = create_session(study["id"], tp0["id"], arm_v["id"],
                            "2026-08-01T11:00:00Z", "2026-08-01T11:35:00Z")
        activate(study["id"])
        pull_units(tp0["id"], chamber["id"], arm_c["id"], quantity=4)
        pull_units(tp0["id"], chamber["id"], arm_v["id"], quantity=4)
        panelists = [create_qualified_panelist() for _ in range(4)]
        a_s1 = [assign_panelist(s1["id"], p["id"]) for p in panelists]
        a_s2 = [assign_panelist(s2["id"], p["id"]) for p in panelists]

        set_clock("2026-08-01T10:00:00Z")
        open_session(s1["id"])
        for i, p in enumerate(panelists):
            submit_all_scores(a_s1[i]["id"], p["id"], uniform_score=9)
        lock_session(s1["id"])
        analyze_session(s1["id"])

        set_clock("2026-08-01T11:00:00Z")
        open_session(s2["id"])
        for i, p in enumerate(panelists):
            submit_all_scores(a_s2[i]["id"], p["id"], uniform_score=9)
        lock_session(s2["id"])
        analyze_session(s2["id"])

        # APC 3.0 stays below the 6.0 trip limit; it still bills 1.5 hours
        get_success_data(api.create_lab_result(
            create_lab_result_payload(study["id"], arm_c["id"], tp0["id"],
                                      "APC", 3.0), AN))
        get_success_data(api.close_fieldwork(study["id"], SCI))
        rec_c = propose_and_accept_recommendation(study["id"], arm_c["id"])
        propose_and_accept_recommendation(study["id"], arm_v["id"])
        report = create_draft_report(study["id"])
        attach_and_submit_report(report["id"], rec_c["id"])
        walk_report_to_client_review(report["id"])
        env = {"client": client, "study": study, "chamber": chamber}
        return env, report

    def test_consumed_hours_use_per_session_quantum(self, api):
        """PRD §3.7: "Session room time is charged per `ANALYZED` session and **rounded per session first**: each session's duration in minutes is divided by 15 and rounded up to a whole number of quarter-hour quanta, then multiplied by 0.25 hours, and the session's charge adds half an hour — 0.5 — per `SUBMITTED` assignment."
        PRD §3.7: "The pinned order matters: summing raw durations before quantizing yields a different, wrong total — two sessions of 25 and 35 minutes with 4 submitted assignments apiece must bill 0.50 + 2.00 + 0.75 + 2.00 = 5.25 hours, not the 5.00 a sum-first order would produce."

        Design: Difficulty/combinatorial_formula/retainer_per_session_rounding_order
        """
        env, report = self._settlement_scenario(api)
        validate_success(api.release_report(report["id"], LD))

        study = get_study(env["study"]["id"])
        assert study["status"] == "COMPLETED"
        assert get_report(report["id"])["status"] == "RELEASED"
        # S1: ceil(25/15)*0.25 = 0.50 room + 4*0.5 = 2.00 -> 2.50
        # S2: ceil(35/15)*0.25 = 0.75 room + 2.00 -> 2.75; APC 1.50
        assert study["consumed_hours"] == pytest.approx(6.75, abs=0.005), (
            "per-session ceil first: 2.50 + 2.75 + 1.50 = 6.75, not 6.50")
        assert study["reserved_hours_escrow"] == 0

    def test_settlement_credits_reserve_minus_consumed(self, api):
        """PRD §3.7: "Settlement then credits the client's `retainer_hours_balance` with the difference between the `reserved_hours_escrow` and `consumed_hours`, and zeroes the escrow; when consumption exceeded the reserve the difference is negative and the balance is debited accordingly — a balance may go negative."

        Design: Difficulty/combinatorial_formula/retainer_per_session_rounding_order
        """
        env, report = self._settlement_scenario(api)
        # reserve = 10 + 2*1 + 4*2 = 20; balance after activation = 50 - 20 = 30
        validate_success(api.release_report(report["id"], LD))

        client = get_client(env["client"]["id"])
        # 30 + (20 - 6.75) = 43.25
        assert client["retainer_hours_balance"] == pytest.approx(43.25, abs=0.005), (
            "refund of reserve minus consumed lands on the balance")
        assert client["active_study_count"] == 0


class TestRetainSweep:
    def test_retain_sweep_strict_expiry_boundary(self, api):
        """PRD §3.3: "A `LabDirector` may then run the **retain sweep**, an administrative capability that expires every `RETAIN` unit whose `retention_until_utc` is set and falls strictly before the logical clock, moving each such unit `STORED → EXPIRED` and decrementing its chamber's `reserved_units` by 1 per unit; the sweep reports how many units expired via `expired_count` and their identifiers via `expired_unit_ids`"
        PRD §3.3: "every unit of the study whose `unit_purpose` is `RETAIN` and whose status is `STORED` or `CHECKED_OUT` receives a `retention_until_utc` equal to the completion instant plus 90 days"

        Design: Corner/cross_cutting_layers/retain_sweep_strict_expiry_boundary
        """
        env = setup_completed_study()
        unit = env["retain_unit"]
        assert unit["retention_until_utc"] is not None
        assert unit["retention_until_utc"].replace("Z", "+00:00").startswith(
            "2026-10-30T00:00:00"), (
            f"release at 2026-08-01 + 90 days; got {unit['retention_until_utc']}")
        chamber_id = env["chamber"]["id"]
        assert get_chamber(chamber_id)["reserved_units"] == 1

        set_clock("2026-10-29T23:59:59Z")  # retention - 1s
        sweep1 = validate_success(api.retain_sweep(LD))
        assert sweep1["expired_count"] == 0, "strictly-before: not yet expired"

        set_clock("2026-10-30T00:00:00Z")  # exactly at retention
        sweep2 = validate_success(api.retain_sweep(LD))
        assert sweep2["expired_count"] == 0, "equality is not strictly before"

        set_clock("2026-10-30T00:00:01Z")  # retention + 1s
        sweep3 = validate_success(api.retain_sweep(LD))
        assert sweep3["expired_count"] == 1
        assert unit["id"] in sweep3["expired_unit_ids"]
        refreshed = get_success_data(api.get_sample_unit(unit["id"], LD))
        assert refreshed["status"] == "EXPIRED"
        assert get_chamber(chamber_id)["reserved_units"] == 0


class TestAbortCompensation:
    def test_abort_cascades_compensate_children(self, api):
        """PRD §3.2: "Abortion is fully compensating: the entire `reserved_hours_escrow` is credited back to the client's `retainer_hours_balance` and the escrow zeroed (no consumption is charged); when the study was in `SCHEDULED` or `IN_PROGRESS`, the client's `active_study_count` decreases by 1; all of the study's evaluation sessions in `PLANNED` or `OPEN` are cancelled and their assignments in `ASSIGNED` are excused; all of the study's sample units in `STORED` or `CHECKED_OUT` are discarded with chamber occupancy recomputed per §2.9; and every date-code recommendation of the study in `PROPOSED` or `ACCEPTED` is superseded"

        Design: Corner/cross_cutting_layers/abort_cascades_compensate_children
        """
        set_clock()
        client = create_client(topup_hours=50)
        study = create_draft_study(client["id"], product_name="Sriracha")
        arm = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        tp0 = add_time_point(study["id"], 0)
        chamber = create_chamber(chamber_code="CH-AB", temp_c=20,
                                 capacity_units=10)
        submit_and_approve(study["id"])
        session = create_session(study["id"], tp0["id"], arm["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        activate(study["id"])
        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=2,
                   unit_purpose="RETAIN")
        panelist = create_qualified_panelist()
        assignment = assign_panelist(session["id"], panelist["id"])
        assert get_client(client["id"])["retainer_hours_balance"] == 34, (
            "50 - 16 reserved at activation")

        aborted = validate_success(api.abort_study(study["id"], LD))
        assert aborted["status"] == "ABORTED"
        assert aborted["reserved_hours_escrow"] == 0

        assert get_session(session["id"])["status"] == "CANCELLED"
        assert get_success_data(api.get_assignment(assignment["id"], PC))[
            "status"] == "EXCUSED", "second-level cascade via the session cancel"

        units = list_sample_units(study_id=study["id"])
        assert len(units) == 2
        assert all(u["status"] == "DISCARDED" for u in units)
        assert get_chamber(chamber["id"])["reserved_units"] == 0

        client_after = get_client(client["id"])
        assert client_after["retainer_hours_balance"] == 50, (
            "the 16-hour escrow is fully refunded")
        assert client_after["active_study_count"] == 0
