"""Coding queue: creation defaults, credential gating, priority scoring,
auto-assignment, DNFB sweep boost."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_assignment,
    get_success_data,
    make_account,
    make_chart,
    make_coder,
    discharge_account,
    make_deficiency,
    setup_assigned,
    setup_ready_chart,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQueuePriorityTieredScore:
    def test_priority_score_combines_tier_amount_acuity(self, api, manager_headers):
        """PRD §3.2: "The aging tier contributes 10 points when the account was
        discharged two days ago or less, 40 points for three to five days, 70
        points for six to ten days, and 100 points once eleven days or more
        have elapsed. The charge component adds one point per whole 100000-cent
        block of the account's `total_charges_cents`, capped at 30 points.
        Acuity contributes 0 points for `MEDICAL_LOW`, 10 for `MEDICAL_HIGH`,
        and 20 for `SURGICAL`."

        Discharged exactly 6 days before the default clock (2026-05-01T00:00:00Z),
        charges 2000000, acuity MEDICAL_HIGH, no DNFB flag: 70 + 20 + 10 + 0 = 100.

        Design: Difficulty/combinatorial_formula/queue_priority_tiered_score
        """
        coder = make_coder("E-CF1", credential="RHIA", full_name="Prio Rita")
        account, chart = setup_ready_chart(
            "MRN-CF1",
            acuity="MEDICAL_HIGH",
            total_charges_cents=2000000,
            discharge_at="2026-04-25T00:00:00Z",
            financial_class="COMMERCIAL",
        )
        res = api.create_assignment(
            {
                "chart_id": chart["id"],
                "coder_id": coder["id"],
                "due_at": "2026-05-10T00:00:00Z",
            },
            manager_headers,
        )
        assignment = validate_success(res, 201)
        assert_assignment(assignment)
        assert assignment["priority_score"] == 100, (
            f"expected 70 (tier) + 20 (amount) + 10 (acuity) + 0 (boost) == 100, "
            f"got {assignment['priority_score']}"
        )

    def test_priority_score_persisted_on_get(self, api, manager_headers):
        """PRD §3.2: "The `priority_score` is the sum of these four components,
        capped at 150, and is always an integer."

        Same scenario as the sibling test; the score must be identical when the
        assignment is re-fetched.

        Design: Difficulty/combinatorial_formula/queue_priority_tiered_score
        """
        coder = make_coder("E-CF1B", credential="RHIA")
        account, chart = setup_ready_chart(
            "MRN-CF1B",
            acuity="MEDICAL_HIGH",
            total_charges_cents=2000000,
            discharge_at="2026-04-25T00:00:00Z",
            financial_class="COMMERCIAL",
        )
        created = get_success_data(
            api.create_assignment(
                {
                    "chart_id": chart["id"],
                    "coder_id": coder["id"],
                    "due_at": "2026-05-10T00:00:00Z",
                },
                manager_headers,
            )
        )
        fetched = validate_success(
            api.get_assignment(created["id"], manager_headers), 200
        )
        assert fetched["priority_score"] == 100
        assert isinstance(fetched["priority_score"], int)


class TestAssignmentCreation:
    def test_assignment_initial_state_assigned(self, api, manager_headers):
        """PRD §3.2: "A new assignment starts life `ASSIGNED`, with the coder
        attached and `assigned_at` stamped from the logical clock. Creation
        debits the assigned coder's `workload_units` by the chart's acuity
        weight — one unit for `MEDICAL_LOW`, two for `MEDICAL_HIGH`, three for
        `SURGICAL` — and computes the assignment's `priority_score`."

        Design: Corner/state_machines/assignment_initial_state_assigned
        """
        ctx = setup_assigned(
            "MRN-SM5", "E-SM5", acuity="MEDICAL_HIGH", credential="CCS"
        )
        assignment = ctx["assignment"]
        assert_assignment(assignment)
        assert assignment["status"] == "ASSIGNED"
        assert assignment["coder_id"] == ctx["coder"]["id"]
        assert assignment["returned_count"] == 0
        coder_after = get_success_data(api.get_coder(ctx["coder"]["id"], manager_headers))
        assert coder_after["workload_units"] == 2

    def test_assignment_on_incomplete_chart_rejected(self, api, manager_headers):
        """PRD §3.2: "Two guards fire first: the chart must actually be
        `READY_FOR_CODING` (otherwise `ERR_CHART_NOT_READY`)".

        Design: Corner/validations/assignment_on_incomplete_chart_rejected
        """
        coder = make_coder("E-VA6", credential="CCS", full_name="Not Ready")
        account = make_account("MRN-VA6")
        chart = make_chart(account["id"], acuity="MEDICAL_LOW")
        make_deficiency(chart["id"], type="MISSING_H_AND_P")
        discharge_account(account["id"])
        res = api.create_assignment(
            {
                "chart_id": chart["id"],
                "coder_id": coder["id"],
                "due_at": "2026-05-10T00:00:00Z",
            },
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_CHART_NOT_READY, expected_status=409)

    def test_assign_with_unknown_coder_not_found(self, api, manager_headers):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_CODER_NOT_FOUND` for coders".

        Design: Corner/validations/assign_with_unknown_coder_not_found
        """
        account, chart = setup_ready_chart("MRN-VA5", acuity="MEDICAL_LOW")
        res = api.create_assignment(
            {
                "chart_id": chart["id"],
                "coder_id": NON_EXISTENT_UUID,
                "due_at": "2026-05-10T00:00:00Z",
            },
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_CODER_NOT_FOUND, expected_status=404)

    def test_second_assignment_on_same_chart_rejected(self, api, manager_headers):
        """PRD §3.2: "the chart may have at most one non-terminal assignment —
        that is, one in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or
        `RETURNED` — with a second attempt rejected as `ERR_ASSIGNMENT_EXISTS`."

        Design: Corner/validations/second_assignment_on_same_chart_rejected
        """
        ctx = setup_assigned("MRN-VAC", "E-VAC", acuity="MEDICAL_LOW")
        res = api.create_assignment(
            {
                "chart_id": ctx["chart"]["id"],
                "coder_id": ctx["coder"]["id"],
                "due_at": "2026-05-12T00:00:00Z",
            },
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_ASSIGNMENT_EXISTS, expected_status=409)

    def test_auto_assign_without_eligible_coder_rejected(self, api, manager_headers):
        """PRD §3.2: "If `coder_id` is omitted, the system auto-selects from
        the pool of `ACTIVE` coders who meet the chart's credential
        requirement, ... an empty pool yields `ERR_NO_ELIGIBLE_CODER`."

        Design: Corner/validations/auto_assign_without_eligible_coder_rejected
        """
        make_coder("E-VAD", credential="CCA", full_name="Entry Level")
        account, chart = setup_ready_chart(
            "MRN-VAD", acuity="SURGICAL", financial_class="COMMERCIAL"
        )
        res = api.create_assignment(
            {"chart_id": chart["id"], "due_at": "2026-05-10T00:00:00Z"},
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_CODER, expected_status=422)
        data, meta = validate_paginated(
            api.list_assignments(manager_headers, params={"chart_id": chart["id"]})
        )
        assert data == [] and meta["total_count"] == 0


class TestAutoAssignSelectorDeterminism:
    def test_auto_assign_tie_broken_by_created_at_then_workload(self, api, manager_headers):
        """PRD §3.2: "the system auto-selects from the pool of `ACTIVE` coders
        who meet the chart's credential requirement, ranking candidates by
        their current `workload_units` ascending and breaking ties by the
        coder's `created_at` ascending".

        Design: Corner/cross_cutting_layers/auto_assign_selector_determinism
        """
        api.set_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, manager_headers)
        c1 = make_coder("E-XC3A", credential="CCS", full_name="Older Coder")
        api.set_clock({"to_iso8601": "2026-04-02T00:00:00Z"}, manager_headers)
        c2 = make_coder("E-XC3B", credential="CCS", full_name="Newer Coder")
        api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, manager_headers)

        account_a, chart_a = setup_ready_chart("MRN-XC3A", acuity="MEDICAL_HIGH")
        account_b, chart_b = setup_ready_chart("MRN-XC3B", acuity="MEDICAL_HIGH")

        pick1 = validate_success(
            api.create_assignment(
                {"chart_id": chart_a["id"], "due_at": "2026-05-10T00:00:00Z"},
                manager_headers,
            ),
            201,
        )
        pick2 = validate_success(
            api.create_assignment(
                {"chart_id": chart_b["id"], "due_at": "2026-05-10T00:00:00Z"},
                manager_headers,
            ),
            201,
        )
        assert pick1["coder_id"] == c1["id"], (
            "workload tie 0 == 0 must be broken by created_at ascending "
            "(2026-04-01 < 2026-04-02)"
        )
        assert pick2["coder_id"] == c2["id"], (
            "after the first assign, c1 carries workload 2 > c2's 0, so c2 wins"
        )


class TestSweepBoostRecomputesPriority:
    def test_sweep_boost_recomputes_priority(self, api, manager_headers):
        """PRD §3.7: "The sweep also feeds back into the coding queue: every
        non-terminal assignment sitting on a flagged account's chart has its
        `priority_score` recomputed under the §3.2 formula, so the 25-point
        DNFB boost now applies to those charts."

        Design: Corner/cross_cutting_layers/sweep_boost_recomputes_priority
        """
        ctx = setup_assigned(
            "MRN-XC4",
            "E-XC4",
            acuity="MEDICAL_LOW",
            credential="CCS",
            total_charges_cents=1000000,
            discharge_at="2026-04-27T00:00:00Z",
            financial_class="MEDICAID",
        )
        assert ctx["assignment"]["priority_score"] == 50, (
            f"pre-sweep: tier 40 + amount 10 + acuity 0 + boost 0 == 50, "
            f"got {ctx['assignment']['priority_score']}"
        )

        sweep = validate_success(
            api.create_dnfb_sweep({"threshold_days": 3}, manager_headers), 201
        )
        assert sweep["flagged_count"] == 1

        after = validate_success(
            api.get_assignment(ctx["assignment"]["id"], manager_headers), 200
        )
        assert after["priority_score"] == 75, (
            f"post-sweep: 50 + 25 DNFB boost == 75, got {after['priority_score']}"
        )


class TestDnfbThresholdExactly3Days:
    def test_discharged_exactly_threshold_days_is_flagged(self, api, manager_headers):
        """PRD §3.7: "Each candidate's age is the exact, fractional number of
        days between its `discharge_at` and the sweep's `as_of`; the account is
        flagged when that age is at least `threshold_days`, and an age landing
        exactly on the threshold is flagged."

        Design: Difficulty/boundary_precision_check/dnfb_threshold_exactly_3_days
        """
        acct_a = make_account("MRN-BP1A", admit_at="2026-04-20T08:00:00Z")
        acct_b = make_account("MRN-BP1B", admit_at="2026-04-22T08:00:00Z")
        discharge_account(acct_a["id"], discharge_at="2026-04-28T00:00:00Z")
        discharge_account(acct_b["id"], discharge_at="2026-04-30T00:00:00Z")

        sweep = validate_success(
            api.create_dnfb_sweep({"threshold_days": 3}, manager_headers), 201
        )
        a_after = validate_success(api.get_patient_account(acct_a["id"], manager_headers), 200)
        b_after = validate_success(api.get_patient_account(acct_b["id"], manager_headers), 200)
        assert a_after["dnfb_flag"] is True, "3.000 days >= 3 must be flagged"
        assert b_after["dnfb_flag"] is False, "1 day < 3 must not be flagged"
        assert sweep["flagged_count"] == 1
        assert sweep["flagged_account_ids"] == [acct_a["id"]]

    def test_below_threshold_account_keeps_flag_false(self, api, manager_headers):
        """PRD §3.7: "an age landing exactly on the threshold is flagged" — the
        comparison is `>=`, so a strictly younger account stays unflagged.
        PRD §2.10: "An account's `dnfb_flag` and `dnfb_flagged_at` are written
        only by DNFB sweeps."

        Design: Difficulty/boundary_precision_check/dnfb_threshold_exactly_3_days
        """
        acct = make_account("MRN-BP1C", admit_at="2026-04-22T08:00:00Z")
        discharge_account(acct["id"], discharge_at="2026-04-30T00:00:00Z")
        sweep = validate_success(
            api.create_dnfb_sweep({"threshold_days": 3}, manager_headers), 201
        )
        after = validate_success(api.get_patient_account(acct["id"], manager_headers), 200)
        assert after["dnfb_flag"] is False
        assert after["dnfb_flagged_at"] is None
        assert sweep["flagged_count"] == 0
        assert sweep["flagged_account_ids"] == []
