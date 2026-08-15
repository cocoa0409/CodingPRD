"""Point-to-point testing: sessions, result recording, completion gates, abort."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_test_point,
    create_test_point_payload,
    create_test_session_payload,
    get_success_data,
    make_technician_headers,
    new_customer,
    new_job,
    new_panel,
    new_test_point,
    setup_panel_with_bom,
    validate_error,
    validate_paginated,
    validate_success,
    walk_panel_to_design_approved,
    walk_panel_to_procurement_cleared,
)


def _panel_in_point_to_point(api, sl_headers, company="UD Co", job_number="J-UD1",
                             panel_tag="P-UD1", designer="de-ud", qa="qa-ud"):
    """Panel walked to POINT_TO_POINT with no test points yet."""
    ctx = setup_panel_with_bom(
        company_name=company, job_number=job_number, quoted_price_cents=100000,
        panel_tag=panel_tag, design_engineer_id=designer,
        component_spec={
            "part_number": f"BPD-{panel_tag}", "component_class": "BRANCH_PROTECTIVE",
            "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 100,
            "heat_dissipation_w": 8,
        },
    )
    panel_id = ctx["panel"]["id"]
    walk_panel_to_design_approved(panel_id, qa_user_id=qa)
    walk_panel_to_procurement_cleared(panel_id)
    get_success_data(api.start_wiring(panel_id, sl_headers), 200)
    return ctx


class TestImmutableTestPoint:
    def test_immutable_testpoint_has_no_version_field_update_path(self, api, de_headers):
        """PRD §2.4: "The two exceptions are `TestPoint` and `ProgramVersion`, which
        carry `id` and `created_at` only — both `updated_at` and `version` are absent
        on those two resources."
        PRD §3.4: "Every test point begins with `result` set to `UNTESTED`."

        Design: Corner/entities/immutable_testpoint_has_no_version_field_update_path
        """
        customer = new_customer(company_name="Imm Co")
        job = new_job(customer["id"], job_number="J-IM1", quoted_price_cents=100000)
        panel = new_panel(job["id"], design_engineer_id="de-im", panel_tag="P-IM1")
        point = validate_success(
            api.create_test_point(
                panel["id"],
                create_test_point_payload(
                    point_label="TP-IM1", expected_signal="CONTINUITY", sequence_no=1
                ),
                de_headers,
            ),
            201,
        )
        assert_test_point(point)
        assert point["result"] == "UNTESTED"


class TestCompletionGates:
    def test_test_session_complete_with_undecided_points_rejected(self, api, sl_headers,
                                                                  pm_headers):
        """PRD §3.4: "Completion requires every test point of the panel to be decided
        — no `UNTESTED` points may remain, though `SKIPPED` is allowed" and "A
        complete call with any `UNTESTED` point outstanding is rejected with
        `ERR_TEST_POINTS_UNDECIDED`."

        Design: Corner/validations/test_session_complete_with_undecided_points_rejected
        """
        ctx = _panel_in_point_to_point(api, sl_headers)
        panel_id = ctx["panel"]["id"]
        tp1 = new_test_point(panel_id, point_label="TP-UD1", expected_signal="CONTINUITY",
                             sequence_no=1)
        new_test_point(panel_id, point_label="TP-UD2", expected_signal="ISOLATION",
                       sequence_no=2)
        get_success_data(api.begin_test(panel_id, sl_headers), 200)
        session = get_success_data(
            api.create_test_session(panel_id, create_test_session_payload(technician_id="tt-ud"),
                                    make_technician_headers("tt-ud")),
            201,
        )
        tech = make_technician_headers("tt-ud")
        get_success_data(
            api.record_result(session["id"], {"test_point_id": tp1["id"], "outcome": "PASS"},
                              tech),
            200,
        )

        resp = api.complete_test_session(session["id"], tech)
        validate_error(resp, ApiErrorId.ERR_TEST_POINTS_UNDECIDED, 422)

        session_after = validate_success(api.get_test_session(session["id"], pm_headers), 200)
        assert session_after["status"] == "OPEN"
        panel_after = validate_success(api.get_panel(panel_id, pm_headers), 200)
        assert panel_after["status"] == "POINT_TO_POINT"

    def test_record_result_on_decided_point_rejected(self, api, sl_headers, pm_headers):
        """PRD §3.4: "Recording a result requires the parent session to be `OPEN` and
        the point to currently be `UNTESTED`; violations of either are rejected with
        `ERR_TEST_POINTS_UNDECIDED` (HTTP 422)."
        PRD §3.4: "A `PASS` outcome increments the session's `pass_count` by one; a
        `FAIL` increments `fail_count` by one; a `SKIPPED` increments neither."

        Design: Corner/endpoints/record_result_on_decided_point_rejected
        """
        ctx = _panel_in_point_to_point(api, sl_headers, company="RR Co",
                                       job_number="J-RR1", panel_tag="P-RR1",
                                       designer="de-rr", qa="qa-rr")
        panel_id = ctx["panel"]["id"]
        tp1 = new_test_point(panel_id, point_label="TP-RR1", expected_signal="CONTINUITY",
                             sequence_no=1)
        new_test_point(panel_id, point_label="TP-RR2", expected_signal="ISOLATION",
                       sequence_no=2)
        get_success_data(api.begin_test(panel_id, sl_headers), 200)
        session = get_success_data(
            api.create_test_session(panel_id, create_test_session_payload(technician_id="tt-rr"),
                                    make_technician_headers("tt-rr")),
            201,
        )
        tech = make_technician_headers("tt-rr")
        get_success_data(
            api.record_result(session["id"], {"test_point_id": tp1["id"], "outcome": "PASS"},
                              tech),
            200,
        )

        resp = api.record_result(
            session["id"], {"test_point_id": tp1["id"], "outcome": "FAIL"}, tech
        )
        validate_error(resp, ApiErrorId.ERR_TEST_POINTS_UNDECIDED, 422)

        points, _ = validate_paginated(api.list_test_points(panel_id, pm_headers))
        decided = {p["id"]: p for p in points}[tp1["id"]]
        assert decided["result"] == "PASS", "decided point must keep its recorded result"
        session_after = validate_success(api.get_test_session(session["id"], pm_headers), 200)
        assert session_after["pass_count"] == 1
        assert session_after["fail_count"] == 0

    def test_test_session_complete_by_other_technician_rejected(self, api, sl_headers,
                                                                pm_headers):
        """PRD §3.4: "Completion requires every test point of the panel to be decided
        — no `UNTESTED` points may remain, though `SKIPPED` is allowed — and the
        acting `TestTechnician`'s id must equal the session's `technician_id` (only
        the executing technician completes the session)."
        PRD §2.1: "A request whose role is authenticated but not listed in the target
        endpoint's Authorized Role(s) column is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/state_machines/test_session_complete_by_other_technician_rejected
        """
        ctx = _panel_in_point_to_point(api, sl_headers, company="Tech Co",
                                       job_number="J-TC1", panel_tag="P-TC1",
                                       designer="de-tc", qa="qa-tc")
        panel_id = ctx["panel"]["id"]
        tp = new_test_point(panel_id, point_label="TP-TC1", expected_signal="CONTINUITY",
                            sequence_no=1)
        get_success_data(api.begin_test(panel_id, sl_headers), 200)
        session = get_success_data(
            api.create_test_session(panel_id,
                                    create_test_session_payload(technician_id="tt-x1"),
                                    make_technician_headers("tt-x1")),
            201,
        )
        get_success_data(
            api.record_result(session["id"], {"test_point_id": tp["id"], "outcome": "PASS"},
                              make_technician_headers("tt-x1")),
            200,
        )

        resp = api.complete_test_session(session["id"], make_technician_headers("tt-x2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        session_after = validate_success(api.get_test_session(session["id"], pm_headers), 200)
        assert session_after["status"] == "OPEN"


class TestAbortCompensation:
    def _setup_session_with_results(self, api, sl_headers):
        ctx = _panel_in_point_to_point(api, sl_headers, company="Tau Foods",
                                       job_number="J-9402", panel_tag="P-A1",
                                       designer="de-015", qa="qa-910")
        panel_id = ctx["panel"]["id"]
        points = [
            new_test_point(panel_id, point_label=f"TP-A{n}", expected_signal=signal,
                           sequence_no=n)
            for n, signal in enumerate(
                ("CONTINUITY", "VOLTAGE_24VDC", "ANALOG_4_20MA", "ISOLATION"), start=1
            )
        ]
        get_success_data(api.begin_test(panel_id, sl_headers), 200)
        session = get_success_data(
            api.create_test_session(panel_id,
                                    create_test_session_payload(technician_id="tt-700"),
                                    make_technician_headers("tt-700")),
            201,
        )
        tech = make_technician_headers("tt-700")
        for point, outcome in zip(points, ("PASS", "FAIL", "SKIPPED")):
            get_success_data(
                api.record_result(session["id"],
                                  {"test_point_id": point["id"], "outcome": outcome}, tech),
                200,
            )
        return ctx, session, points

    def test_abort_zeroes_session_counters(self, api, sl_headers, pm_headers):
        """PRD §3.4: "Abort resets every test point recorded by this session — those
        with `result` in `{PASS, FAIL, SKIPPED}` — back to `UNTESTED`, recomputes the
        session's `pass_count` and `fail_count` to zero, transitions the session
        `OPEN → ABORTED`, and increments the session's `version`."

        Design: Difficulty/compensating_invariant/test_session_abort_restores_point_results_and_counts
        """
        _ctx, session, _points = self._setup_session_with_results(api, sl_headers)
        aborted = validate_success(
            api.abort_test_session(session["id"], make_technician_headers("tt-700")), 200
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["pass_count"] == 0, f"pass_count must recompute to 0, got {aborted['pass_count']}"
        assert aborted["fail_count"] == 0, f"fail_count must recompute to 0, got {aborted['fail_count']}"

        session_after = validate_success(api.get_test_session(session["id"], pm_headers), 200)
        assert session_after["status"] == "ABORTED"
        assert session_after["pass_count"] == 0
        assert session_after["fail_count"] == 0

    def test_abort_resets_all_recorded_points_to_untested(self, api, sl_headers, pm_headers):
        """PRD §3.4: "Abort resets every test point recorded by this session — those
        with `result` in `{PASS, FAIL, SKIPPED}` — back to `UNTESTED`, recomputes the
        session's `pass_count` and `fail_count` to zero, transitions the session
        `OPEN → ABORTED`, and increments the session's `version`."

        Design: Difficulty/compensating_invariant/test_session_abort_restores_point_results_and_counts
        """
        ctx, session, points = self._setup_session_with_results(api, sl_headers)
        validate_success(
            api.abort_test_session(session["id"], make_technician_headers("tt-700")), 200
        )

        listed, _ = validate_paginated(api.list_test_points(ctx["panel"]["id"], pm_headers))
        assert len(listed) == 4
        untested = [p for p in listed if p["result"] == "UNTESTED"]
        assert len(untested) == 4, (
            "all four points (PASS, FAIL, SKIPPED, and the untouched one) must be "
            f"UNTESTED after abort, got {[p['result'] for p in listed]}"
        )
        # The panel's own status is unchanged by an abort (PRD §3.4).
        panel = validate_success(api.get_panel(ctx["panel"]["id"], pm_headers), 200)
        assert panel["status"] == "POINT_TO_POINT"
