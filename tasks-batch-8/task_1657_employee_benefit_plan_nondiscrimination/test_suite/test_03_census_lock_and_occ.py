"""Census lifecycle, lock completeness, OCC guards, and attribution (PRD §2.7, §3.4-§3.5)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_employer_payload,
    create_plan_version_payload,
    create_census_employee_payload,
    create_compensation_record_payload,
    create_contribution_payload,
    create_regulatory_limit_payload,
    create_employer,
    create_plan_for,
    create_adopted_version,
    create_plan_year_for,
    open_census,
    add_employee,
    add_compensation,
    add_contribution,
    lock_census,
    current_plan_year_version,
    queue_and_execute_run,
    setup_employer_plan_version_year,
    setup_locked_census_401k,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCensusEmployeeFields:
    def test_census_employee_defaults_applied(self):
        """PRD §3.4: "plus optional `date_of_termination` (null while still employed),
        `ownership_pct_direct` (default 0, a percentage between 0 and 100), `is_officer`
        (default false), and `family_member_of_ssn`."

        Design: Corner/entities/census_employee_defaults_applied
        """
        employer = create_employer(legal_name="Uniform Corp")
        plan = create_plan_for(employer["id"], plan_name="Uniform 401k")
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        emp = validate_success(
            api_client.create_census_employee(
                py["id"],
                create_census_employee_payload(
                    ssn="200000002", full_name="Uma", date_of_birth="1990-01-01",
                    date_of_hire="2021-01-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert emp["ownership_pct_direct"] == 0
        assert emp["is_officer"] is False
        assert emp["date_of_termination"] is None
        assert emp["family_member_of_ssn"] is None


class TestCensusLockCompleteness:
    def test_lock_census_incomplete_missing_regulatory_limit(self):
        """PRD §3.5: "it is guarded by completeness preconditions evaluated before
        anything is derived — any shortfall is rejected with `ERR_CENSUS_INCOMPLETE`
        (HTTP 422)."
        PRD §3.3: "Locking a census requires an `ACTIVE` row for the plan year's
        `year_label` to exist (§3.5)."

        Design: Corner/validations/lock_census_incomplete_missing_regulatory_limit
        """
        parts = setup_employer_plan_version_year(
            legal_name="Papa2 Corp", plan_name="Papa2 401k", publish_limits_first=False
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="500000601", full_name="Pat")
        add_compensation(emp["id"], 9000000)

        version = current_plan_year_version(py_id)
        resp = api_client.lock_census(
            py_id, {"expected_plan_year_version": version}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_CENSUS_INCOMPLETE, expected_status=422)

    def test_census_employee_patch_in_locked_year_rejected(self):
        """PRD §3.4: "Editing an employee's input fields later is permitted only while
        the year remains `CENSUS_COLLECTING` — any census write outside that state is
        rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/endpoints/census_employee_patch_in_locked_year_rejected
        """
        parts = setup_locked_census_401k(
            legal_name="Tango2 Corp", nhce_specs=((9000000, 0),), hce_spec=(30000000, 0, 6)
        )
        emp_id = parts["nhces"][0]["id"]
        resp = api_client.patch_census_employee(emp_id, {"is_officer": True}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestContributionGuards:
    def test_contribution_date_outside_plan_year_rejected(self):
        """PRD §3.4: "a `contribution_date` that must fall inside the plan year's
        `year_start`-to-`year_end` window inclusive, otherwise `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/contribution_date_outside_plan_year_rejected
        """
        employer = create_employer(legal_name="Mike2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Mike2 401k")
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        emp = add_employee(py["id"], ssn="500000301", full_name="Mia",
                           date_of_birth="1990-01-01", date_of_hire="2021-01-01")
        resp = api_client.create_contribution(
            emp["id"],
            create_contribution_payload(amount_cents=100000, contribution_date="2027-01-05"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)

    def test_deferral_over_402g_limit_rejected(self):
        """PRD §3.4: "One statutory guard applies at posting time: an employee's total
        `ELECTIVE_DEFERRAL` contributions in `POSTED` or `PENDING_DISTRIBUTION` status
        for the year must not exceed the year's `sec402g_limit_cents`, or the post is
        rejected with `ERR_LIMIT_EXCEEDED`."

        Design: Corner/validations/deferral_over_402g_limit_rejected
        """
        parts = setup_employer_plan_version_year(legal_name="Nov2 Corp", plan_name="Nov2 401k")
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="500000401", full_name="Ned", date_of_birth="1985-01-01")
        add_compensation(emp["id"], 40000000)
        add_contribution(emp["id"], "ELECTIVE_DEFERRAL", 2000000, "2026-03-31")

        resp = api_client.create_contribution(
            emp["id"],
            create_contribution_payload(amount_cents=400000, contribution_date="2026-06-30"),
            ADMIN,
        )
        # 2000000 + 400000 = 2400000 > 2350000 sec402g limit
        validate_error(resp, ApiErrorId.ERR_LIMIT_EXCEEDED, expected_status=422)

    def test_deferral_exactly_at_402g_limit_allowed(self):
        """PRD §3.4: "an employee's total `ELECTIVE_DEFERRAL` contributions in `POSTED`
        or `PENDING_DISTRIBUTION` status for the year must not exceed the year's
        `sec402g_limit_cents`, or the post is rejected with `ERR_LIMIT_EXCEEDED`."

        Design: Corner/validations/deferral_exactly_at_402g_limit_allowed
        """
        parts = setup_employer_plan_version_year(
            legal_name="Oscar2 Corp", plan_name="Oscar2 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="500000501", full_name="Olive",
                           date_of_birth="1985-01-01")
        add_compensation(emp["id"], 40000000)
        add_contribution(emp["id"], "ELECTIVE_DEFERRAL", 2000000, "2026-03-31")

        # 2000000 + 350000 = 2350000 == limit exactly: "must not exceed" permits it
        resp = api_client.create_contribution(
            emp["id"],
            create_contribution_payload(amount_cents=350000, contribution_date="2026-06-30"),
            ADMIN,
        )
        validate_success(resp, expected_status=201)


class TestPlanYearStateMachine:
    def test_plan_year_invalid_transition_file_from_draft(self):
        """PRD §3.9: "Filing closes the year: a `PlanAdministrator` files a plan year in
        `CORRECTING`, moving it `CORRECTING` → `FILED` and incrementing its `version`."

        Design: Corner/state_machines/plan_year_invalid_transition_file_from_draft
        """
        employer = create_employer(legal_name="Whiskey Corp")
        plan = create_plan_for(employer["id"], plan_name="Whiskey 401k")
        py = create_plan_year_for(plan["id"])

        resp = api_client.file_plan_year(py["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_plan_year(py["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_plan_year_terminal_lockdown_terminated(self):
        """PRD §3.9: "`FILED` and `TERMINATED` are the terminal states of a plan year;
        once reached, no further workflow transitions apply."
        PRD §3.9: "moving it to `TERMINATED`, cascading the parent plan's `status` to
        `TERMINATED`"

        Design: Corner/state_machines/plan_year_terminal_lockdown_terminated
        """
        employer = create_employer(legal_name="Xray Corp")
        plan = create_plan_for(employer["id"], plan_name="Xray 401k")
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        validate_success(api_client.terminate_plan_year(py["id"], ADMIN))

        for call in (
            lambda: api_client.open_census(py["id"], ADMIN),
            lambda: api_client.file_plan_year(py["id"], ADMIN),
            lambda: api_client.terminate_plan_year(py["id"], ADMIN),
        ):
            validate_error(call(), ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(api_client.get_plan_year(py["id"], ADMIN))
        assert after["status"] == "TERMINATED"
        plan_after = validate_success(api_client.get_plan(plan["id"], AUDITOR))
        assert plan_after["status"] == "TERMINATED"


class TestOptimisticConcurrency:
    def test_occ_lock_census_stale_version_rejected(self):
        """PRD §2.7: "Locking a census requires the request to carry
        `expected_plan_year_version` holding the plan year's `version` as the client last
        observed it. If another writer has advanced the plan year since — for example by
        adding a census employee or recording a compensation row, each of which bumps the
        plan year's `version` — the caller's snapshot view is stale and the lock is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_lock_census_stale_version
        """
        parts = setup_employer_plan_version_year(
            legal_name="Foxtrot3 Corp", plan_name="Foxtrot3 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="900000101", full_name="Finn")
        stale_version = current_plan_year_version(py_id)
        # Recording a compensation row bumps the plan year's version
        add_compensation(emp["id"], 9000000)

        stale = api_client.lock_census(
            py_id, {"expected_plan_year_version": stale_version}, ADMIN
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_lock_census_current_version_succeeds(self):
        """PRD §2.7: "Locking a census requires the request to carry
        `expected_plan_year_version` holding the plan year's `version` as the client last
        observed it."
        PRD §3.5: "Locking the census is the pivot of the whole cycle: it moves the year
        `CENSUS_COLLECTING` → `CENSUS_LOCKED`, freezes the snapshot, and derives every
        classification the tests consume."

        Design: Corner/cross_cutting_layers/occ_lock_census_stale_version
        """
        parts = setup_employer_plan_version_year(
            legal_name="Foxtrot3b Corp", plan_name="Foxtrot3b 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="900000102", full_name="Finn B")
        stale_version = current_plan_year_version(py_id)
        add_compensation(emp["id"], 9000000)

        validate_error(
            api_client.lock_census(
                py_id, {"expected_plan_year_version": stale_version}, ADMIN
            ),
            ApiErrorId.ERR_STALE_VERSION,
            expected_status=412,
        )
        locked = lock_census(py_id)
        assert locked["status"] == "CENSUS_LOCKED"


class TestAttributionAndClassification:
    def test_family_attribution_rollup_computed(self):
        """PRD §3.5: "The rollup starts from the employee's `ownership_pct_direct`, adds
        the direct ownership of every employee in the same plan year who names this
        employee as their family member, and adds the direct ownership of the employee
        this employee names as their family member — attribution flows in both
        directions along the declared link, but only one hop: a chain from A to B to C
        does not attribute A's ownership to C."
        PRD §3.5: "An employee is `HCE` when any of three prongs holds: their
        `attributed_ownership_pct` is strictly greater than 5 percent"

        Design: Corner/entities/family_attribution_rollup_computed
        """
        parts = setup_employer_plan_version_year(
            legal_name="Victor Corp", plan_name="Victor 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        a = add_employee(py_id, ssn="200000101", full_name="Alex A",
                         date_of_birth="1978-01-01", date_of_hire="2015-01-01",
                         ownership_pct_direct=3)
        b = add_employee(py_id, ssn="200000102", full_name="Blair B",
                         date_of_birth="1979-01-01", date_of_hire="2016-01-01",
                         ownership_pct_direct=4, family_member_of_ssn="200000101")
        add_compensation(a["id"], 8000000)
        add_compensation(b["id"], 8000000)
        lock_census(py_id)

        a_after = validate_success(api_client.get_census_employee(a["id"], ANALYST))
        b_after = validate_success(api_client.get_census_employee(b["id"], ANALYST))
        assert a_after["attributed_ownership_pct"] == 7
        assert b_after["attributed_ownership_pct"] == 7
        assert a_after["hce_status"] == "HCE"
        assert b_after["hce_status"] == "HCE"

    def test_hce_ownership_exactly_5pct_not_hce(self):
        """PRD §3.5: "An employee is `HCE` when any of three prongs holds: their
        `attributed_ownership_pct` is strictly greater than 5 percent; their prior-year
        compensation is strictly greater than the year's `hce_comp_threshold_cents`; or
        they are flagged `is_officer` and their prior-year compensation is strictly
        greater than `key_officer_comp_threshold_cents`. Failing all three, the employee
        is `NHCE`."

        Design: Difficulty/boundary_precision_check/hce_ownership_exactly_5pct_not_hce
        """
        parts = setup_employer_plan_version_year(legal_name="Lima Corp", plan_name="Lima 401k")
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        exact = add_employee(py_id, ssn="333330101", full_name="Five Exact",
                             date_of_birth="1975-01-01", date_of_hire="2015-01-01",
                             ownership_pct_direct=5.0)
        over = add_employee(py_id, ssn="333330102", full_name="Five Over",
                            date_of_birth="1975-01-01", date_of_hire="2015-01-01",
                            ownership_pct_direct=5.0001)
        for emp in (exact, over):
            add_compensation(emp["id"], 10000000, period="CURRENT_YEAR")
            add_compensation(emp["id"], 10000000, period="PRIOR_YEAR")
        lock_census(py_id)

        exact_after = validate_success(api_client.get_census_employee(exact["id"], ANALYST))
        over_after = validate_success(api_client.get_census_employee(over["id"], ANALYST))
        # 5.0 is NOT strictly greater than 5.0
        assert exact_after["hce_status"] == "NHCE"
        assert exact_after["attributed_ownership_pct"] == 5.0
        # 5.0001 > 5.0
        assert over_after["hce_status"] == "HCE"

    def test_hce_determination_uses_prior_year_comp_only(self):
        """PRD §3.5: "Current-year compensation never enters this determination — the
        lookback-year basis is unconditional"

        Design: Difficulty/boundary_precision_check/hce_ownership_exactly_5pct_not_hce
        """
        parts = setup_employer_plan_version_year(
            legal_name="Lima Lookback Corp", plan_name="Lima Lookback 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        # Current-year comp far above the threshold, prior-year comp below it, no
        # ownership, not an officer -> NHCE because the lookback basis is unconditional.
        emp = add_employee(py_id, ssn="333330103", full_name="Lookback Lynn",
                           date_of_birth="1975-01-01", date_of_hire="2015-01-01")
        add_compensation(emp["id"], 90000000, period="CURRENT_YEAR")
        add_compensation(emp["id"], 10000000, period="PRIOR_YEAR")
        lock_census(py_id)

        after = validate_success(api_client.get_census_employee(emp["id"], ANALYST))
        assert after["hce_status"] == "NHCE"


class TestImmediateConsistency:
    def test_immediate_consistency_lock_results_visible_same_request(self):
        """PRD §3.5: "When the lock succeeds, the covering version's `id` is pinned into
        the plan year's `adopted_version_id`, `census_lock_version` increments by one,
        the plan year's `version` increments by one, and four determinations sweep the
        census."

        Design: Corner/consistency_model/immediate_consistency_lock_results_visible_same_request
        """
        parts = setup_employer_plan_version_year(
            legal_name="Juliet3 Corp", plan_name="Juliet3 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="910000101", full_name="Jae", ownership_pct_direct=6)
        add_compensation(emp["id"], 9000000)

        version = current_plan_year_version(py_id)
        locked = validate_success(
            api_client.lock_census(py_id, {"expected_plan_year_version": version}, ADMIN)
        )
        assert locked["status"] == "CENSUS_LOCKED"
        assert locked["census_lock_version"] == 1
        assert locked["adopted_version_id"] == parts["version"]["id"]

        fetched = validate_success(api_client.get_plan_year(py_id, AUDITOR))
        assert fetched["status"] == "CENSUS_LOCKED"
        assert fetched["census_lock_version"] == locked["census_lock_version"]
        assert fetched["adopted_version_id"] == locked["adopted_version_id"]

        emp_after = validate_success(api_client.get_census_employee(emp["id"], AUDITOR))
        assert emp_after["hce_status"] == "HCE"
        assert emp_after["attributed_ownership_pct"] == 6


class TestUnlockRelockCycle:
    def test_lock_unlock_cycle_supersedes_terminal_runs(self):
        """PRD §3.5: "Unlocking is the reverse path, `CENSUS_LOCKED` →
        `CENSUS_COLLECTING`, for when the census turns out to be wrong."
        PRD §3.5: "A successful unlock marks every test run of the year in `PASSED` or
        `FAILED` status `SUPERSEDED` (the cascade moves each such run from its terminal
        state into `SUPERSEDED`) and increments the plan year's `version`."

        Design: Difficulty/non_linear_state_machine/plan_year_census_lock_unlock_cycle
        """
        parts = setup_locked_census_401k(
            legal_name="Echo Corp",
            nhce_specs=((10000000, 500000), (9000000, 450000)),
            hce_spec=(30000000, 1500000, 6),
            plan_name="Echo 401k",
        )
        py_id = parts["plan_year"]["id"]
        run = queue_and_execute_run(py_id, "COVERAGE_410B", "FINAL")
        assert run["status"] in ("PASSED", "FAILED")

        unlocked = validate_success(api_client.unlock_census(py_id, ADMIN))
        assert unlocked["status"] == "CENSUS_COLLECTING"
        run_after = validate_success(api_client.get_test_run(run["id"], ANALYST))
        assert run_after["status"] == "SUPERSEDED"

    def test_relock_increments_census_lock_version_without_resurrecting_runs(self):
        """PRD §3.4: "it also tracks a `census_lock_version` counter starting at 0"
        PRD §3.5: "When the lock succeeds, the covering version's `id` is pinned into the
        plan year's `adopted_version_id`, `census_lock_version` increments by one"

        Design: Difficulty/non_linear_state_machine/plan_year_census_lock_unlock_cycle
        """
        parts = setup_locked_census_401k(
            legal_name="Echo Relock Corp",
            nhce_specs=((10000000, 500000), (9000000, 450000)),
            hce_spec=(30000000, 1500000, 6),
            plan_name="Echo Relock 401k",
        )
        py_id = parts["plan_year"]["id"]
        run = queue_and_execute_run(py_id, "COVERAGE_410B", "FINAL")

        validate_success(api_client.unlock_census(py_id, ADMIN))
        relocked = lock_census(py_id)
        assert relocked["status"] == "CENSUS_LOCKED"
        assert relocked["census_lock_version"] == 2
        run_after = validate_success(api_client.get_test_run(run["id"], ANALYST))
        assert run_after["status"] == "SUPERSEDED"

    def test_relock_reruns_determination_with_identical_output(self):
        """PRD §3.5: "When the lock succeeds, the covering version's `id` is pinned into
        the plan year's `adopted_version_id`, `census_lock_version` increments by one,
        the plan year's `version` increments by one, and four determinations sweep the
        census."

        A re-lock with unchanged census inputs re-runs the sweep and reproduces
        identical key_employee_status on the owner, while the lock counter advances.

        Design: Difficulty/compensating_invariant/unlock_relock_conserves_census_snapshot_integrity
        """
        parts = setup_locked_census_401k(
            legal_name="Romeo Sweep Corp",
            nhce_specs=((10000000, 0), (9000000, 0)),
            hce_spec=(30000000, 0, 6),
            plan_name="Romeo Sweep 401k",
        )
        py_id = parts["plan_year"]["id"]
        hce_id = parts["hce"]["id"]
        first_lock_version = validate_success(api_client.get_plan_year(py_id, ADMIN))[
            "census_lock_version"
        ]
        assert first_lock_version == 1

        validate_success(api_client.unlock_census(py_id, ADMIN))
        relocked = lock_census(py_id)
        assert relocked["census_lock_version"] == first_lock_version + 1

        hce_after = validate_success(api_client.get_census_employee(hce_id, ANALYST))
        assert hce_after["key_employee_status"] == "KEY"
        assert hce_after["hce_status"] == "HCE"

    def test_unlock_relock_conserves_census_snapshot_integrity(self):
        """PRD §3.5: "Locking the census is the pivot of the whole cycle: it moves the
        year `CENSUS_COLLECTING` → `CENSUS_LOCKED`, freezes the snapshot, and derives
        every classification the tests consume."
        PRD §3.5: "`census_lock_version` increments by one"

        Design: Difficulty/compensating_invariant/unlock_relock_conserves_census_snapshot_integrity
        """
        parts = setup_locked_census_401k(
            legal_name="Romeo Corp",
            nhce_specs=((10000000, 0), (9000000, 0)),
            hce_spec=(30000000, 0, 6),
            plan_name="Romeo 401k",
        )
        py_id = parts["plan_year"]["id"]
        hce_id = parts["hce"]["id"]
        nhce_id = parts["nhces"][0]["id"]

        before_h = validate_success(api_client.get_census_employee(hce_id, ANALYST))
        before_n = validate_success(api_client.get_census_employee(nhce_id, ANALYST))

        validate_success(api_client.unlock_census(py_id, ADMIN))
        relocked = lock_census(py_id)
        assert relocked["census_lock_version"] == 2

        after_h = validate_success(api_client.get_census_employee(hce_id, ANALYST))
        after_n = validate_success(api_client.get_census_employee(nhce_id, ANALYST))
        assert after_h["hce_status"] == before_h["hce_status"] == "HCE"
        assert after_h["attributed_ownership_pct"] == before_h["attributed_ownership_pct"] == 6
        assert after_n["hce_status"] == before_n["hce_status"] == "NHCE"
        assert after_n["key_employee_status"] == before_n["key_employee_status"] == "NON_KEY"
