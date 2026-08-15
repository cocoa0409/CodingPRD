"""Supervision assignments: party guards, window rules, allocation, ending."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_wrvu,
    create_effective_agreement,
    create_supervision_assignment,
    get_success_data,
    post_capture,
    register_physician,
    setup_supervision_scenario,
    validate_capture,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]


class TestAllocationRounding:
    def test_rounding_is_per_assignment(self, api):
        """PRD §3.5: "For each assignment it computes the allocation as the APP capture's `credited_wrvu` multiplied by the assignment's `credit_pct`, rounded half-up to 2 decimal places per assignment; rounding per assignment and then summing is the pinned behavior, and summing-then-rounding is explicitly rejected because it produces different totals."
        PRD §3.5: "Each allocation materializes as a `SUPERVISION_CREDIT` capture on the supervisor's own agreement: born directly in `VALIDATED` and `CREDITED`, carrying `cpt_code` `SUPV`, a null `wrvu_value_applied`, the allocated amount as its `credited_wrvu`, a `credited_period` bucketed per the supervisor's plan's attribution mode, `source_capture_id` pointing back to the APP capture"

        Design: Difficulty/combinatorial_formula/supervision_credit_per_assignment_rounding
        """
        scenario = setup_supervision_scenario(
            supervisor_count=2, credit_pcts=(0.3333, 0.3333), npi_base=1000000010
        )
        capture = post_capture(scenario["agr_app"]["id"], units=1,
                               service_date="2026-02-10", posting_date="2026-02-10")
        validated = validate_capture(capture["id"])
        assert_wrvu(validated["credited_wrvu"], 0.97)
        credits, meta = validate_paginated(
            api.list_supervision_credits(capture["id"], ANALYST)
        )
        assert meta["total_count"] == 2, "one SUPERVISION_CREDIT per eligible assignment"
        for credit in credits:
            assert credit["capture_kind"] == "SUPERVISION_CREDIT"
            assert credit["source_capture_id"] == capture["id"]
            assert_wrvu(credit["credited_wrvu"], 0.32)  # round_half_up(0.97*0.3333, 2)

    def test_per_assignment_rounding_rejects_sum_then_round_total(self, api):
        """PRD §3.5: "rounding per assignment and then summing is the pinned behavior, and summing-then-rounding is explicitly rejected because it produces different totals. There is no remainder redistribution — rounding dust stays with the APP."
        PRD §3.5: "Every created supervisor credit in turn recomputes the supervisor agreement's `ytd_wrvu_credited` — a second cascade hop."

        Design: Difficulty/combinatorial_formula/supervision_credit_per_assignment_rounding
        """
        scenario = setup_supervision_scenario(
            supervisor_count=2, credit_pcts=(0.3333, 0.3333), npi_base=1000000010
        )
        capture = post_capture(scenario["agr_app"]["id"], units=1,
                               service_date="2026-02-10", posting_date="2026-02-10")
        validate_capture(capture["id"])
        sup1 = get_success_data(api.get_agreement(scenario["agr_sups"][0]["id"], ANALYST))
        sup2 = get_success_data(api.get_agreement(scenario["agr_sups"][1]["id"], ANALYST))
        assert_wrvu(sup1["ytd_wrvu_credited"], 0.32)
        assert_wrvu(sup2["ytd_wrvu_credited"], 0.32)
        total_allocated = float(sup1["ytd_wrvu_credited"]) + float(sup2["ytd_wrvu_credited"])
        assert total_allocated == 0.64, (
            "sum-then-round would yield round_half_up(0.97*0.6666, 2) = 0.65 — rejected"
        )
        app_agr = get_success_data(api.get_agreement(scenario["agr_app"]["id"], ANALYST))
        assert_wrvu(app_agr["ytd_wrvu_credited"], 0.97)


class TestWindowRules:
    def test_credit_pct_sum_boundary(self, api):
        """PRD §3.5: "three window rules, otherwise `ERR_SUPERVISION_WINDOW_INVALID` — for the same supervisor-APP pair the closed windows must not overlap, across overlapping windows for the same APP the `credit_pct` values must sum to at most 1.0 inclusive"

        Design: Difficulty/boundary_precision_check/supervision_pct_sum_exact_boundary
        """
        scenario = setup_supervision_scenario(
            supervisor_count=3, credit_pcts=(0.6,), npi_base=1000000070
        )
        app_id = scenario["app"]["id"]
        s2 = scenario["supervisors"][1]
        resp_ok = api.create_supervision_assignment(
            {
                "supervisor_physician_id": s2["id"], "app_physician_id": app_id,
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "credit_pct": 0.4, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        asg2 = validate_success(resp_ok, 201)
        assert asg2["status"] == "ACTIVE", "overlapping sum 0.6 + 0.4 == 1.0 is inclusive-allowed"

    def test_credit_pct_sum_above_one_rejected(self, api):
        """PRD §3.5: "across overlapping windows for the same APP the `credit_pct` values must sum to at most 1.0 inclusive"
        PRD §3.5: "The assignment listing accepts optional `supervisor_physician_id`, `app_physician_id`, and `status` filters."

        Design: Difficulty/boundary_precision_check/supervision_pct_sum_exact_boundary
        """
        scenario = setup_supervision_scenario(
            supervisor_count=3, credit_pcts=(0.6,), npi_base=1000000070
        )
        app_id = scenario["app"]["id"]
        s2, s3 = scenario["supervisors"][1], scenario["supervisors"][2]
        get_success_data(api.create_supervision_assignment(
            {
                "supervisor_physician_id": s2["id"], "app_physician_id": app_id,
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "credit_pct": 0.4, "supervised_fte": 0.5,
            },
            ANALYST,
        ))
        resp_over = api.create_supervision_assignment(
            {
                "supervisor_physician_id": s3["id"], "app_physician_id": app_id,
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "credit_pct": 0.0001, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_error(resp_over, ApiErrorId.ERR_SUPERVISION_WINDOW_INVALID)
        rows, meta = validate_paginated(
            api.list_supervision_assignments(ANALYST, params={"app_physician_id": app_id})
        )
        assert meta["total_count"] == 2, "only the 0.6 and 0.4 assignments exist"

    def test_supervisor_fte_capacity_boundary(self, api):
        """PRD §3.5: "on any overlapping day a supervisor's `supervised_fte` commitments must sum to at most 4.0"

        Design: Difficulty/resource_temporal_overlap/supervision_aggregate_capacity_overlap
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.1,), supervised_ftes=(2.0,),
            windows=[("2026-01-01", "2026-06-30")], npi_base=1000000090,
        )
        # Second APP with an overlapping window: 2.0 + 2.0 == 4.0 at the boundary.
        a2 = register_physician(npi="1000000092", full_name="NP A2", specialty="APP-NP",
                                provider_type="APP")
        create_effective_agreement(a2["id"], scenario["plan"]["id"],
                                   benchmark_percentile=40, base_salary_cents=12000000,
                                   period_draw_cents=500000)
        asg2 = create_supervision_assignment(
            scenario["supervisors"][0]["id"], a2["id"],
            start_date="2026-03-01", end_date="2026-09-30",
            credit_pct=0.1, supervised_fte=2.0,
        )
        assert asg2["status"] == "ACTIVE"
        # Third APP overlapping BOTH windows pushes the aggregate to 4.5.
        a3 = register_physician(npi="1000000093", full_name="NP A3", specialty="APP-NP",
                                provider_type="APP")
        create_effective_agreement(a3["id"], scenario["plan"]["id"],
                                   benchmark_percentile=40, base_salary_cents=12000000,
                                   period_draw_cents=500000)
        resp_over = api.create_supervision_assignment(
            {
                "supervisor_physician_id": scenario["supervisors"][0]["id"],
                "app_physician_id": a3["id"],
                "start_date": "2026-04-01", "end_date": "2026-05-31",
                "credit_pct": 0.1, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_error(resp_over, ApiErrorId.ERR_SUPERVISION_WINDOW_INVALID)

    def test_disjoint_window_under_capacity_accepted(self, api):
        """PRD §3.5: "on any overlapping day a supervisor's `supervised_fte` commitments must sum to at most 4.0"
        PRD §3.5: "The assignment listing accepts optional `supervisor_physician_id`, `app_physician_id`, and `status` filters."

        Design: Difficulty/resource_temporal_overlap/supervision_aggregate_capacity_overlap
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.1,), supervised_ftes=(2.0,),
            windows=[("2026-01-01", "2026-06-30")], npi_base=1000000090,
        )
        a2 = register_physician(npi="1000000092", full_name="NP A2", specialty="APP-NP",
                                provider_type="APP")
        create_effective_agreement(a2["id"], scenario["plan"]["id"],
                                   benchmark_percentile=40, base_salary_cents=12000000,
                                   period_draw_cents=500000)
        create_supervision_assignment(
            scenario["supervisors"][0]["id"], a2["id"],
            start_date="2026-03-01", end_date="2026-09-30",
            credit_pct=0.1, supervised_fte=2.0,
        )
        a3 = register_physician(npi="1000000093", full_name="NP A3", specialty="APP-NP",
                                provider_type="APP")
        create_effective_agreement(a3["id"], scenario["plan"]["id"],
                                   benchmark_percentile=40, base_salary_cents=12000000,
                                   period_draw_cents=500000)
        resp_disjoint = api.create_supervision_assignment(
            {
                "supervisor_physician_id": scenario["supervisors"][0]["id"],
                "app_physician_id": a3["id"],
                "start_date": "2026-10-01", "end_date": "2026-12-31",
                "credit_pct": 0.1, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_success(resp_disjoint, 201)
        rows, meta = validate_paginated(api.list_supervision_assignments(
            ANALYST,
            params={"supervisor_physician_id": scenario["supervisors"][0]["id"]},
        ))
        assert meta["total_count"] == 3

    def test_same_pair_touching_windows_overlap(self, api):
        """PRD §3.5: "the inclusive window `start_date` through `end_date` (the end must not precede the start)"
        PRD §3.5: "for the same supervisor-APP pair the closed windows must not overlap"

        Design: Corner/validations/supervision_same_pair_overlap_rejected
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.5,),
            windows=[("2026-01-01", "2026-06-30")], npi_base=1000000254,
        )
        sup_id, app_id = scenario["supervisors"][0]["id"], scenario["app"]["id"]
        resp_touching = api.create_supervision_assignment(
            {
                "supervisor_physician_id": sup_id, "app_physician_id": app_id,
                "start_date": "2026-06-30", "end_date": "2026-12-31",
                "credit_pct": 0.5, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_error(resp_touching, ApiErrorId.ERR_SUPERVISION_WINDOW_INVALID)
        resp_next_day = api.create_supervision_assignment(
            {
                "supervisor_physician_id": sup_id, "app_physician_id": app_id,
                "start_date": "2026-07-01", "end_date": "2026-12-31",
                "credit_pct": 0.5, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_success(resp_next_day, 201)

    def test_party_type_and_agreement_guards(self, api):
        """PRD §3.5: "Creation enforces a fixed sequence after payload shape: the supervisor must have `provider_type` `PHYSICIAN`, the APP must have `provider_type` `APP`, and the two must differ, otherwise `ERR_PROVIDER_TYPE_INVALID`; both parties must hold `EFFECTIVE` agreements on the same plan, otherwise `ERR_NO_EFFECTIVE_AGREEMENT`"

        Design: Corner/validations/supervision_provider_type_and_agreement_guards
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(), npi_base=1000000251
        )  # no pre-built assignment: this test drives creation failures
        np2 = register_physician(npi="1000000253", full_name="NP Two", specialty="APP-NP",
                                 provider_type="APP")  # deliberately no agreement
        app_with_agreement = scenario["app"]
        resp_type = api.create_supervision_assignment(
            {
                "supervisor_physician_id": app_with_agreement["id"],  # APP as supervisor
                "app_physician_id": np2["id"],
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "credit_pct": 0.5, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_error(resp_type, ApiErrorId.ERR_PROVIDER_TYPE_INVALID)
        resp_agr = api.create_supervision_assignment(
            {
                "supervisor_physician_id": scenario["supervisors"][0]["id"],
                "app_physician_id": np2["id"],  # APP holds no EFFECTIVE agreement
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "credit_pct": 0.5, "supervised_fte": 0.5,
            },
            ANALYST,
        )
        validate_error(resp_agr, ApiErrorId.ERR_NO_EFFECTIVE_AGREEMENT)


class TestAssignmentEnd:
    def test_ending_halts_allocation_beyond_new_end_date(self, api):
        """PRD §3.5: "An assignment is born `ACTIVE` and stays `ACTIVE` until explicitly ended; reaching the window's `end_date` does not change `status`, though it does bound allocation. Ending an assignment early accepts a new `end_date`, requires it not to precede the `start_date`, re-validates the window rules against the shrunken window, and moves the assignment to `ENDED`."
        PRD §3.5: "The server collects every `ACTIVE` assignment for that APP whose window contains the capture's `service_date`"

        Design: Corner/state_machines/supervision_end_success_halts_allocation
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.5,), npi_base=1000000214
        )
        assignment = scenario["assignments"][0]
        ended = validate_success(
            api.end_supervision_assignment(assignment["id"], {"end_date": "2026-02-28"},
                                           ANALYST),
            200,
        )
        assert ended["status"] == "ENDED"
        assert ended["end_date"] == "2026-02-28"
        capture = post_capture(scenario["agr_app"]["id"], units=1,
                               service_date="2026-03-05", posting_date="2026-03-05")
        validate_capture(capture["id"])
        credits, meta = validate_paginated(api.list_supervision_credits(capture["id"], ANALYST))
        assert meta["total_count"] == 0 and credits == [], (
            "the service date falls outside the shrunken window, so nothing allocates"
        )
        sup_agr = get_success_data(api.get_agreement(scenario["agr_sups"][0]["id"], ANALYST))
        assert_wrvu(sup_agr["ytd_wrvu_credited"], 0.00)
        app_agr = get_success_data(api.get_agreement(scenario["agr_app"]["id"], ANALYST))
        assert_wrvu(app_agr["ytd_wrvu_credited"], 0.97)

    def test_supervision_credit_reachable_from_both_parents(self, api):
        """PRD §3.4: "one lists the replacement captures whose `reversal_of_capture_id` points at a given capture (the correction trail built by dispute resolution), and another lists the `SUPERVISION_CREDIT` captures whose `source_capture_id` points at a given APP capture."
        PRD §3.5: "Each allocation materializes as a `SUPERVISION_CREDIT` capture on the supervisor's own agreement"

        Design: Corner/endpoints/reverse_reachability_lists_resolve
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.5,), npi_base=1000000261
        )
        capture = post_capture(scenario["agr_app"]["id"], units=10,
                               service_date="2026-02-10", posting_date="2026-02-10")
        validate_capture(capture["id"])
        credits, meta = validate_paginated(api.list_supervision_credits(capture["id"], ANALYST))
        assert meta["total_count"] == 1
        credit = credits[0]
        assert credit["capture_kind"] == "SUPERVISION_CREDIT"
        assert_wrvu(credit["credited_wrvu"], 4.85)  # 9.70 x 0.5
        assert credit["source_capture_id"] == capture["id"]
        sup_captures, sup_meta = validate_paginated(api.list_captures(
            scenario["agr_sups"][0]["id"], ANALYST, params={"credit_status": "CREDITED"}
        ))
        assert credit["id"] in {c["id"] for c in sup_captures}, (
            "the system-created credit is discoverable from the supervisor agreement too"
        )
