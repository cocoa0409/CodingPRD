"""Nondiscrimination testing engine: ADP/ACP/top-heavy/dependent-care (PRD §3.6)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_pct,
    get_result_line,
    create_employer,
    create_plan_for,
    create_adopted_version,
    create_plan_year_for,
    publish_limits,
    open_census,
    add_employee,
    add_compensation,
    add_contribution,
    lock_census,
    queue_and_execute_run,
    get_result_lines,
    setup_employer_plan_version_year,
    setup_locked_census_401k,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAdp:
    def test_adp_ceiling_three_prong_min_max(self):
        """PRD §3.6: "The statutory ceiling reported as `ADP_CEILING_PCT` is the greater
        of one and a quarter times the NHCE average, and the lesser of the NHCE average
        plus two percentage points and twice the NHCE average."

        NHCE ADRs 4.0000 and 6.0000 -> average 5.0000; prongs are 1.25*5 = 6.2500 and
        min(5+2, 2*5) = 7.0000; the greater is 7.0000.

        Design: Difficulty/combinatorial_formula/adp_ceiling_three_prong_min_max
        """
        parts = setup_locked_census_401k(legal_name="Gamma Inc", plan_name="Gamma 401k")
        run = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "FINAL")
        lines = get_result_lines(run["id"])
        nhce = get_result_line(lines, "ADP_NHCE_PCT")
        ceiling = get_result_line(lines, "ADP_CEILING_PCT")
        assert_pct(nhce["value_pct"], 5.0000)
        assert_pct(ceiling["value_pct"], 7.0000)

    def test_adp_hce_over_ceiling_fails_inclusive_boundary(self):
        """PRD §3.6: "The test passes when the HCE average is no greater than the
        ceiling — again an inclusive boundary."

        HCE ADR = 3000000/30000000 = 10.0000 > 7.0000 ceiling -> FAIL.

        Design: Difficulty/combinatorial_formula/adp_ceiling_three_prong_min_max
        """
        parts = setup_locked_census_401k(legal_name="Gamma B Inc", plan_name="Gamma B 401k")
        run = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "FINAL")
        lines = get_result_lines(run["id"])
        hce = get_result_line(lines, "ADP_HCE_PCT")
        assert_pct(hce["value_pct"], 10.0000)
        assert hce["outcome"] == "FAIL"
        fetched = validate_success(api_client.get_test_run(run["id"], ANALYST))
        assert fetched["status"] == "FAILED"
        assert fetched["overall_result"] == "FAIL"

    def test_adp_provisional_and_final_agree_before_distribution(self):
        """PRD §3.6: "a `PROVISIONAL` run treats pending and already-distributed
        deferrals as if still posted, while a `FINAL` run excludes `DISTRIBUTED` and
        `RECHARACTERIZED` amounts"

        With no distributions executed yet, both modes see the same POSTED deferrals.

        Design: Difficulty/dual_variant_calc/adp_provisional_vs_final_after_distribution
        """
        parts = setup_locked_census_401k(legal_name="Acme Corp", plan_name="Acme 401k")
        prov = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "PROVISIONAL")
        final = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "FINAL")
        prov_hce = get_result_line(get_result_lines(prov["id"]), "ADP_HCE_PCT")
        final_hce = get_result_line(get_result_lines(final["id"]), "ADP_HCE_PCT")
        assert_pct(prov_hce["value_pct"], 10.0000)
        assert_pct(final_hce["value_pct"], 10.0000)

    def test_adp_provisional_mode_includes_pending_deferrals(self):
        """PRD §3.6: "The deferral numerator sums `ELECTIVE_DEFERRAL` contributions in
        `POSTED` or `PENDING_DISTRIBUTION` status; the two run modes diverge here, since
        a `PROVISIONAL` run treats pending and already-distributed deferrals as if still
        posted, while a `FINAL` run excludes `DISTRIBUTED` and `RECHARACTERIZED`
        amounts"

        PROVISIONAL HCE ADP reads the posted 3000000 deferral against 30000000 comp:
        10.0000 — identical to FINAL while no distributions have executed.

        Design: Difficulty/dual_variant_calc/adp_provisional_vs_final_after_distribution
        """
        parts = setup_locked_census_401k(legal_name="Acme Prov Corp", plan_name="Acme Prov 401k")
        prov = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "PROVISIONAL")
        lines = get_result_lines(prov["id"])
        assert_pct(get_result_line(lines, "ADP_HCE_PCT")["value_pct"], 10.0000)
        assert_pct(get_result_line(lines, "ADP_NHCE_PCT")["value_pct"], 5.0000)
        assert_pct(get_result_line(lines, "ADP_CEILING_PCT")["value_pct"], 7.0000)


class TestAcp:
    def test_acp_test_correct_result(self):
        """PRD §3.6: "The same cohort, structure, ceiling logic, rounding discipline,
        and provisional-versus-final divergence as the ADP test, applied to a different
        numerator: each member's actual contribution ratio sums `MATCH` and `QMAC`
        contributions in `POSTED` or `PENDING_DISTRIBUTION` status against current-year
        compensation, producing the `ACP_HCE_PCT`, `ACP_NHCE_PCT`, and `ACP_CEILING_PCT`
        lines."

        NHCE ACRs 2.0000/4.0000 -> avg 3.0000; ceiling max(3.75, min(5.0, 6.0)) = 5.0000;
        HCE ACR 6.0000 > 5.0000 -> FAIL.

        Design: Corner/calculations/acp_test_correct_result
        """
        parts = setup_employer_plan_version_year(
            legal_name="Charlie Corp", plan_name="Charlie 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        n1 = add_employee(py_id, ssn="400000101", full_name="N1")
        n2 = add_employee(py_id, ssn="400000102", full_name="N2", date_of_birth="1982-01-01")
        h = add_employee(py_id, ssn="400000103", full_name="H1", date_of_birth="1975-01-01",
                         date_of_hire="2015-01-01", ownership_pct_direct=6)
        for emp, comp in ((n1, 10000000), (n2, 10000000), (h, 30000000)):
            add_compensation(emp["id"], comp)
        add_contribution(n1["id"], "MATCH", 200000)
        add_contribution(n2["id"], "MATCH", 400000)
        add_contribution(h["id"], "MATCH", 1800000)
        lock_census(py_id)

        run = queue_and_execute_run(py_id, "ACP_401M", "FINAL")
        lines = get_result_lines(run["id"])
        assert_pct(get_result_line(lines, "ACP_NHCE_PCT")["value_pct"], 3.0000)
        assert_pct(get_result_line(lines, "ACP_CEILING_PCT")["value_pct"], 5.0000)
        hce_line = get_result_line(lines, "ACP_HCE_PCT")
        assert_pct(hce_line["value_pct"], 6.0000)
        assert hce_line["outcome"] == "FAIL"

    def test_derived_field_reconciliation_after_forfeit(self):
        """PRD §3.4: "an administrator may forfeit an employer-source contribution — one
        of `MATCH`, `PROFIT_SHARING`, `QNEC`, or `QMAC` in `POSTED` status — moving it
        `POSTED` → `FORFEITED`, incrementing the contribution's `version`, and marking
        every `PASSED` or `FAILED` test run for the plan year `SUPERSEDED`, since the
        forfeiture changes the balances those runs measured."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_forfeit
        """
        parts = setup_employer_plan_version_year(
            legal_name="India3 Corp", plan_name="India3 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        n = add_employee(py_id, ssn="900000401", full_name="Nia")
        h = add_employee(py_id, ssn="900000402", full_name="Hank",
                         date_of_birth="1975-01-01", date_of_hire="2015-01-01",
                         ownership_pct_direct=6)
        add_compensation(n["id"], 10000000)
        add_compensation(h["id"], 30000000)
        match = add_contribution(n["id"], "MATCH", 300000)
        add_contribution(h["id"], "MATCH", 600000)
        lock_census(py_id)

        run1 = queue_and_execute_run(py_id, "ACP_401M", "FINAL")
        line1 = get_result_line(get_result_lines(run1["id"]), "ACP_NHCE_PCT")
        assert_pct(line1["value_pct"], 3.0000)
        assert line1["outcome"] == "PASS"

        forfeited = validate_success(api_client.forfeit_contribution(match["id"], ADMIN))
        assert forfeited["status"] == "FORFEITED"
        run1_after = validate_success(api_client.get_test_run(run1["id"], ANALYST))
        assert run1_after["status"] == "SUPERSEDED"

        run2 = queue_and_execute_run(py_id, "ACP_401M", "FINAL")
        line2 = get_result_line(get_result_lines(run2["id"]), "ACP_NHCE_PCT")
        assert_pct(line2["value_pct"], 0.0000)


class TestAdpInputSet:
    def test_adp_input_set_excludes_terminated_before_year(self):
        """PRD §3.5: "An employee whose `employment_status` is `TERMINATED` and whose
        termination predates the plan year's `year_start` is marked
        `EXCLUDED_FROM_TESTING` and skipped."
        PRD §3.6: "The cohort is employees with `hce_status` of `HCE` or `NHCE` whose
        `covered_status` is `BENEFITING` or `ELIGIBLE_NOT_BENEFITING`."

        Design: Corner/calculations/adp_input_set_excludes_terminated_before_year
        """
        parts = setup_employer_plan_version_year(
            legal_name="Echo2 Corp", plan_name="Echo2 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        active = add_employee(py_id, ssn="400000201", full_name="Active Ann")
        termed = add_employee(
            py_id, ssn="400000202", full_name="Term Tom", date_of_birth="1970-01-01",
            date_of_hire="2010-01-01", employment_status="TERMINATED",
            date_of_termination="2025-12-15", ownership_pct_direct=10,
        )
        add_compensation(active["id"], 10000000)
        add_compensation(termed["id"], 50000000)
        add_contribution(active["id"], "ELECTIVE_DEFERRAL", 500000)
        add_contribution(termed["id"], "ELECTIVE_DEFERRAL", 2300000, "2026-01-15")
        lock_census(py_id)

        termed_after = validate_success(api_client.get_census_employee(termed["id"], ANALYST))
        assert termed_after["hce_status"] == "EXCLUDED_FROM_TESTING"

        run = queue_and_execute_run(py_id, "ADP_401K", "FINAL")
        nhce_line = get_result_line(get_result_lines(run["id"]), "ADP_NHCE_PCT")
        # Only Active Ann counts: 500000 / 10000000 * 100 = 5.0000
        assert_pct(nhce_line["value_pct"], 5.0000)


class TestTopHeavy:
    def test_top_heavy_first_year_forward_looking(self):
        """PRD §3.6: "The determination date is the last day of the prior plan year, and
        balances measured are prior-year balances; for the plan's first year — one with
        a null `prior_year_py_id` — the determination is forward-looking, measured as of
        the last day of the current year and including current-year accruals."

        First-year 2025: key 5000000 / total 5500000 = 90.9091% -> top-heavy FAIL.

        Design: Difficulty/dual_variant_calc/top_heavy_first_year_forward_looking_vs_lookback
        """
        employer = create_employer(legal_name="Beta LLC", entity_type="LLC")
        publish_limits(2025)
        plan = create_plan_for(employer["id"], plan_name="Beta 401k")
        create_adopted_version(
            plan["id"], effective_start="2025-01-01", effective_end="2026-12-31"
        )
        py = create_plan_year_for(
            plan["id"], year_label=2025, year_start="2025-01-01", year_end="2025-12-31"
        )
        open_census(py["id"])
        key = add_employee(py["id"], ssn="222220001", full_name="Kay Owner",
                           date_of_birth="1970-01-01", date_of_hire="2010-01-01",
                           ownership_pct_direct=60)
        nonkey = add_employee(py["id"], ssn="222220002", full_name="Nora Staff",
                              date_of_birth="1990-01-01")
        add_compensation(key["id"], 40000000)
        add_compensation(nonkey["id"], 10000000)
        add_contribution(key["id"], "PROFIT_SHARING", 5000000, "2025-12-15")
        add_contribution(nonkey["id"], "PROFIT_SHARING", 500000, "2025-12-15")
        lock_census(py["id"])

        run = queue_and_execute_run(py["id"], "TOP_HEAVY_416", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "TOP_HEAVY_RATIO_PCT")
        assert_pct(line["value_pct"], 90.9091)
        assert line["outcome"] == "FAIL"

    def test_top_heavy_strictly_greater_than_60_boundary(self):
        """PRD §3.6: "the plan is top-heavy (the line fails) when the ratio is strictly
        greater than 60.0000"

        Design: Difficulty/dual_variant_calc/top_heavy_first_year_forward_looking_vs_lookback
        """
        employer = create_employer(legal_name="Beta Boundary LLC", entity_type="LLC")
        publish_limits(2025)
        plan = create_plan_for(employer["id"], plan_name="Beta Boundary 401k")
        create_adopted_version(
            plan["id"], effective_start="2025-01-01", effective_end="2026-12-31"
        )
        py = create_plan_year_for(
            plan["id"], year_label=2025, year_start="2025-01-01", year_end="2025-12-31"
        )
        open_census(py["id"])
        key = add_employee(py["id"], ssn="222220003", full_name="Kay Boundary",
                           date_of_birth="1970-01-01", date_of_hire="2010-01-01",
                           ownership_pct_direct=60)
        nonkey = add_employee(py["id"], ssn="222220004", full_name="Nick Boundary",
                              date_of_birth="1990-01-01")
        add_compensation(key["id"], 40000000)
        add_compensation(nonkey["id"], 10000000)
        # exactly 60.0000: 600000 / 1000000
        add_contribution(key["id"], "PROFIT_SHARING", 600000, "2025-12-15")
        add_contribution(nonkey["id"], "PROFIT_SHARING", 400000, "2025-12-15")
        lock_census(py["id"])

        run = queue_and_execute_run(py["id"], "TOP_HEAVY_416", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "TOP_HEAVY_RATIO_PCT")
        assert_pct(line["value_pct"], 60.0000)
        # 60.0000 is NOT strictly greater than 60.0000
        assert line["outcome"] == "PASS"

    def test_top_heavy_boundary_exactly_60_passes(self):
        """PRD §3.6: "The top-heavy ratio is one hundred times key balance divided by
        total balance — zero when the total is zero — rounded to 4 decimals half up onto
        the `TOP_HEAVY_RATIO_PCT` line, and the plan is top-heavy (the line fails) when
        the ratio is strictly greater than 60.0000."

        Design: Corner/calculations/top_heavy_boundary_exactly_60_passes
        """
        parts = setup_employer_plan_version_year(
            legal_name="Foxtrot2 Corp", plan_name="Foxtrot2 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        key = add_employee(py_id, ssn="400000301", full_name="Key Kate",
                           date_of_birth="1970-01-01", date_of_hire="2010-01-01",
                           ownership_pct_direct=60)
        nonkey = add_employee(py_id, ssn="400000302", full_name="Non Nick",
                              date_of_birth="1990-01-01")
        add_compensation(key["id"], 40000000)
        add_compensation(nonkey["id"], 10000000)
        add_contribution(key["id"], "PROFIT_SHARING", 600000, "2026-12-15")
        add_contribution(nonkey["id"], "PROFIT_SHARING", 400000, "2026-12-15")
        lock_census(py_id)

        run = queue_and_execute_run(py_id, "TOP_HEAVY_416", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "TOP_HEAVY_RATIO_PCT")
        assert_pct(line["value_pct"], 60.0000)
        assert line["outcome"] == "PASS"

    def test_top_heavy_minimum_contribution_waterfall(self):
        """PRD §3.6: "When a `FINAL` run fails this test, a minimum-contribution figure
        is derived and surfaced as `min_contribution_cents` in the line's `detail`: take
        the highest contribution rate among `KEY` employees (each key employee's own
        contributions as a percentage of compensation), set the floor to the lesser of 3
        percent and that highest key rate, then for each `BENEFITING` NHCE compute the
        owed amount — the floor percentage of that employee's compensation, rounded to
        whole cents half up — subtract the employer-source amounts already funded for
        them (`MATCH`, `QNEC`, `QMAC`, and `PROFIT_SHARING` contributions in `POSTED` or
        `PENDING_DISTRIBUTION` status), and keep the shortfall where positive."

        Key rate = 700000/40000000 = 1.75%; floor = min(3, 1.75) = 1.75%; NHCE comp
        10000000 with no employer-source funding -> shortfall 175000.

        Design: Corner/calculations/top_heavy_minimum_contribution_waterfall
        """
        parts = setup_employer_plan_version_year(
            legal_name="Golf2 Corp", plan_name="Golf2 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        key = add_employee(py_id, ssn="400000401", full_name="Key Kim",
                           date_of_birth="1970-01-01", date_of_hire="2010-01-01",
                           ownership_pct_direct=60)
        nonkey = add_employee(py_id, ssn="400000402", full_name="Non Noah",
                              date_of_birth="1990-01-01")
        add_compensation(key["id"], 40000000)
        add_compensation(nonkey["id"], 10000000)
        add_contribution(key["id"], "PROFIT_SHARING", 700000, "2026-12-15")
        add_contribution(nonkey["id"], "ELECTIVE_DEFERRAL", 400000, "2026-12-15")
        lock_census(py_id)

        run = queue_and_execute_run(py_id, "TOP_HEAVY_416", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "TOP_HEAVY_RATIO_PCT")
        # 700000 / 1100000 = 63.6364
        assert_pct(line["value_pct"], 63.6364)
        assert line["outcome"] == "FAIL"
        assert line["detail"]["min_contribution_cents"] == 175000


class TestDependentCare:
    def test_dependent_care_cap_applied_per_person_before_averaging(self):
        """PRD §3.6: "For each non-excludable employee, the benefit is the sum of
        `DEPENDENT_CARE_ELECTIVE` contributions in `POSTED` status, capped per person at
        the year's `dependent_care_limit_cents` before any averaging; each person's
        ratio of capped benefit to current-year compensation (zero when compensation is
        zero) is rounded to 4 decimals half up before averaging."

        NHCE ratios: min(600000, 500000)/5000000 = 10.0000 and 200000/10000000 = 2.0000
        -> avg 6.0000; HCE 500000/30000000 = 1.6667; value = 100*1.6667/6.0000 = 27.7783.

        Design: Difficulty/combinatorial_formula/dependent_care_per_person_cap_then_average_rounding
        """
        employer = create_employer(legal_name="Delta Co")
        publish_limits(2026)
        plan = create_plan_for(employer["id"], plan_name="Delta DCFSA",
                               plan_type="DEPENDENT_CARE_FSA", plan_number="002")
        create_adopted_version(plan["id"])
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        d = add_employee(py["id"], ssn="444440001", full_name="Dee Four",
                         date_of_birth="1988-01-01", date_of_hire="2021-01-01")
        e = add_employee(py["id"], ssn="444440002", full_name="Eli Five",
                         date_of_birth="1985-01-01", date_of_hire="2021-01-01")
        f = add_employee(py["id"], ssn="444440003", full_name="Fran Six",
                         date_of_birth="1972-01-01", date_of_hire="2012-01-01",
                         ownership_pct_direct=6)
        add_compensation(d["id"], 5000000)
        add_compensation(e["id"], 10000000)
        add_compensation(f["id"], 30000000)
        add_contribution(d["id"], "DEPENDENT_CARE_ELECTIVE", 600000)
        add_contribution(e["id"], "DEPENDENT_CARE_ELECTIVE", 200000)
        add_contribution(f["id"], "DEPENDENT_CARE_ELECTIVE", 500000)
        lock_census(py["id"])

        run = queue_and_execute_run(py["id"], "DEPENDENT_CARE_129", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "DEPENDENT_CARE_55PCT_AVG_PCT")
        # 100 * 1.6667 / 6.0000 = 27.7783 (cap-before-average ordering pinned)
        assert_pct(line["value_pct"], 27.7783)

    def test_dependent_care_55pct_average_passes(self):
        """PRD §3.6: "The test compares the HCE average against the NHCE average and
        passes when the HCE average is no greater than 55 percent of the NHCE average."

        HCE avg 1.6667 <= 0.55 * 6.0000 = 3.3000 -> PASS.

        Design: Difficulty/combinatorial_formula/dependent_care_per_person_cap_then_average_rounding
        """
        employer = create_employer(legal_name="Delta Pass Co")
        publish_limits(2026)
        plan = create_plan_for(employer["id"], plan_name="Delta Pass DCFSA",
                               plan_type="DEPENDENT_CARE_FSA", plan_number="002")
        create_adopted_version(plan["id"])
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        d = add_employee(py["id"], ssn="444440011", full_name="Dee Pass",
                         date_of_birth="1988-01-01", date_of_hire="2021-01-01")
        e = add_employee(py["id"], ssn="444440012", full_name="Eli Pass",
                         date_of_birth="1985-01-01", date_of_hire="2021-01-01")
        f = add_employee(py["id"], ssn="444440013", full_name="Fran Pass",
                         date_of_birth="1972-01-01", date_of_hire="2012-01-01",
                         ownership_pct_direct=6)
        add_compensation(d["id"], 5000000)
        add_compensation(e["id"], 10000000)
        add_compensation(f["id"], 30000000)
        add_contribution(d["id"], "DEPENDENT_CARE_ELECTIVE", 600000)
        add_contribution(e["id"], "DEPENDENT_CARE_ELECTIVE", 200000)
        add_contribution(f["id"], "DEPENDENT_CARE_ELECTIVE", 500000)
        lock_census(py["id"])

        run = queue_and_execute_run(py["id"], "DEPENDENT_CARE_129", "FINAL")
        line = get_result_line(get_result_lines(run["id"]), "DEPENDENT_CARE_55PCT_AVG_PCT")
        assert line["outcome"] == "PASS"
        fetched = validate_success(api_client.get_test_run(run["id"], ANALYST))
        assert fetched["overall_result"] == "PASS"


class TestForfeit:
    def test_forfeit_rejects_elective_deferral(self):
        """PRD §3.4: "While the plan year sits in `CENSUS_LOCKED`, `TESTING`,
        `RESULTS_REVIEW`, or `CORRECTING`, an administrator may forfeit an
        employer-source contribution — one of `MATCH`, `PROFIT_SHARING`, `QNEC`, or
        `QMAC` in `POSTED` status — moving it `POSTED` → `FORFEITED`, incrementing the
        contribution's `version`, and marking every `PASSED` or `FAILED` test run for
        the plan year `SUPERSEDED`, since the forfeiture changes the balances those runs
        measured."

        An ELECTIVE_DEFERRAL is not in the forfeitable employer-source set, so the
        forfeit is rejected; a MATCH forfeit succeeds.

        Design: Corner/endpoints/forfeit_rejects_elective_deferral
        """
        parts = setup_employer_plan_version_year(
            legal_name="Uniform2 Corp", plan_name="Uniform2 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="600000201", full_name="Uli")
        add_compensation(emp["id"], 9000000)
        deferral = add_contribution(emp["id"], "ELECTIVE_DEFERRAL", 400000)
        match = add_contribution(emp["id"], "MATCH", 200000)
        lock_census(py_id)

        resp = api_client.forfeit_contribution(deferral["id"], ADMIN)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_REQUEST, ApiErrorId.ERR_INVALID_STATE]
        )

        forfeited = validate_success(api_client.forfeit_contribution(match["id"], ADMIN))
        assert forfeited["status"] == "FORFEITED"


class TestRunLifecycleAndListing:
    def test_testrun_idempotent_void_second_call_rejected(self):
        """PRD §3.6: "A queued run an analyst no longer wants can be voided `QUEUED` →
        `VOID`."

        Design: Corner/state_machines/testrun_idempotent_void_second_call_rejected
        """
        parts = setup_locked_census_401k(
            legal_name="Yankee Corp", nhce_specs=((9000000, 0),), hce_spec=(30000000, 0, 6)
        )
        py_id = parts["plan_year"]["id"]
        run = validate_success(
            api_client.create_test_run(py_id, {"test_scope": "ADP_401K", "run_mode": "FINAL"},
                                       ANALYST),
            expected_status=201,
        )
        voided = validate_success(api_client.void_test_run(run["id"], ANALYST))
        assert voided["status"] == "VOID"
        second = api_client.void_test_run(run["id"], ANALYST)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_unlock_blocked_by_pending_work(self):
        """PRD §3.5: "It is refused while any test run for the year is `QUEUED` or
        `RUNNING`, or any correction is `PROPOSED` or `APPROVED` — pending work must
        drain first, and a blocked unlock is rejected with `ERR_PENDING_WORK`
        (HTTP 409)."

        Design: Corner/state_machines/unlock_blocked_by_pending_work
        """
        parts = setup_locked_census_401k(
            legal_name="Alpha Corp", nhce_specs=((9000000, 0),), hce_spec=(30000000, 0, 6),
            plan_name="Alpha 401k",
        )
        py_id = parts["plan_year"]["id"]
        validate_success(
            api_client.create_test_run(
                py_id, {"test_scope": "COVERAGE_410B", "run_mode": "FINAL"}, ANALYST
            ),
            expected_status=201,
        )
        resp = api_client.unlock_census(py_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PENDING_WORK, expected_status=409)
        after = validate_success(api_client.get_plan_year(py_id, ADMIN))
        assert after["status"] in ("CENSUS_LOCKED", "TESTING")

    def test_result_lines_filtered_by_metric(self):
        """PRD §3.6: "Execution creates one test result line per applicable metric"
        PRD §3.6: "the result-line list filters by `metric` and `outcome`."

        An ADP battery produces exactly the ADP_HCE_PCT, ADP_NHCE_PCT, ADP_CEILING_PCT
        lines; filtering by metric returns the single matching line.

        Design: Corner/endpoints/computed_read_result_lines_filtered_by_metric
        """
        parts = setup_locked_census_401k(
            legal_name="Victor2 Corp", nhce_specs=((9000000, 450000),),
            hce_spec=(30000000, 0, 6), plan_name="Victor2 401k",
        )
        run = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "FINAL")

        filtered, _ = validate_paginated(
            api_client.list_result_lines(run["id"], AUDITOR, params={"metric": "ADP_HCE_PCT"})
        )
        assert len(filtered) == 1
        assert filtered[0]["metric"] == "ADP_HCE_PCT"

        unfiltered, _ = validate_paginated(api_client.list_result_lines(run["id"], AUDITOR))
        assert len(unfiltered) == 3
        assert {line["metric"] for line in unfiltered} == {
            "ADP_HCE_PCT", "ADP_NHCE_PCT", "ADP_CEILING_PCT"
        }

    def test_pagination_filter_interaction_test_runs(self):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside its `meta` object so a client can page deterministically
        through the result set."
        PRD §3.6: "The run list filters by `status`, `test_scope`, and `run_mode`."

        Design: Corner/cross_cutting_layers/pagination_filter_interaction_test_runs
        """
        parts = setup_locked_census_401k(
            legal_name="Hotel3 Corp", nhce_specs=((9000000, 450000),),
            hce_spec=(30000000, 0, 5), plan_name="Hotel3 401k",
        )
        py_id = parts["plan_year"]["id"]
        # No eligible HCE (the 5%-owner fails the strictly-greater-than-5
        # ownership prong and has no prior-year comp): coverage line is
        # NOT_APPLICABLE -> PASSED
        queue_and_execute_run(py_id, "COVERAGE_410B", "FINAL")
        queue_and_execute_run(py_id, "COVERAGE_410B", "FINAL")
        queued = validate_success(
            api_client.create_test_run(py_id, {"test_scope": "ADP_401K", "run_mode": "FINAL"},
                                       ANALYST),
            expected_status=201,
        )
        validate_success(api_client.void_test_run(queued["id"], ANALYST))

        page1, meta1 = validate_paginated(
            api_client.list_test_runs(
                py_id, AUDITOR, params={"status": "PASSED", "run_mode": "FINAL",
                                        "limit": 1, "offset": 0}
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_test_runs(
                py_id, AUDITOR, params={"status": "PASSED", "run_mode": "FINAL",
                                        "limit": 1, "offset": 1}
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
