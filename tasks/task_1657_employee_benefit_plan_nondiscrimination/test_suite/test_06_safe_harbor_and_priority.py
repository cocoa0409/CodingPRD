"""Safe harbor elections/notices and validation precedence pairs (PRD §2.8, §3.8)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
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
    current_plan_year_version,
    queue_and_execute_run,
    set_clock,
    setup_employer_plan_version_year,
    create_census_employee_payload,
    create_contribution_payload,
    get_result_lines,
    get_result_line,
    assert_pct,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _setup_year_with_election(
    legal_name,
    design="QNEC_3PCT",
    elected_on="2025-10-15",
    notice_window=("2025-11-01", "2025-11-30"),
    open_first=False,
):
    """Plan year (DRAFT) with a PROPOSED election and a DRAFT notice."""
    parts = setup_employer_plan_version_year(legal_name=legal_name, plan_name=f"{legal_name} 401k")
    py_id = parts["plan_year"]["id"]
    if open_first:
        open_census(py_id)
    election = validate_success(
        api_client.create_safe_harbor_election(
            py_id, {"design": design, "elected_on": elected_on}, ADMIN
        ),
        expected_status=201,
    )
    notice = validate_success(
        api_client.create_safe_harbor_notice(
            election["id"],
            {"notice_period_start": notice_window[0], "notice_period_end": notice_window[1]},
            ADMIN,
        ),
        expected_status=201,
    )
    parts["election"] = election
    parts["notice"] = notice
    return parts


class TestNoticeClock:
    def test_notice_lapsed_on_clock_advance(self):
        """PRD §2.5: "Advancing the clock re-evaluates notice lapse: any safe harbor
        notice still in `DRAFT` whose `notice_period_end` is earlier than the new "now"
        transitions to `LAPSED` at that moment."

        Design: Corner/state_machines/notice_lapsed_on_clock_advance
        """
        parts = _setup_year_with_election(
            "Bravo Corp", elected_on="2026-09-01",
            notice_window=("2026-10-01", "2026-10-31"), open_first=True,
        )
        notice_id = parts["notice"]["id"]
        set_clock("2026-11-02T00:00:00Z")
        notice = validate_success(api_client.get_safe_harbor_notice(notice_id, AUDITOR))
        assert notice["status"] == "LAPSED"
        assert notice["distributed_at"] is None

    def test_clock_default_is_fixed_startup_time(self):
        """PRD §2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and before any explicit adjustment it continues to read
        that default; it never falls back to wall-clock time."
        PRD §3.8: "A successful distribution stamps `distributed_at` from the logical
        clock"

        Design: Corner/endpoints/clock_default_is_fixed_startup_time
        """
        parts = _setup_year_with_election(
            "Whiskey2 Corp", elected_on="2026-07-01",
            notice_window=("2026-07-15", "2026-08-15"), open_first=True,
        )
        distributed = validate_success(
            api_client.distribute_safe_harbor_notice(parts["notice"]["id"], ADMIN)
        )
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["distributed_at"] == "2026-08-01T00:00:00Z"


class TestNoticeGatesElection:
    def test_notice_state_gates_election_effectiveness(self):
        """PRD §3.8: "a lapsed notice can never carry its election to `EFFECTIVE`, since
        the election's notice precondition fails."
        PRD §3.8: "it becomes `EFFECTIVE` only by a system event: the plan year must
        have reached `CENSUS_LOCKED`, the election's linked notice must be `DISTRIBUTED`
        or `ACKNOWLEDGED`, and the notice's `distributed_at` must fall within the
        declared notice window inclusive of both ends."

        Design: Difficulty/cross_entity_state_dependency/notice_state_gates_election_effectiveness
        """
        parts = _setup_year_with_election("Mike Corp")
        py_id = parts["plan_year"]["id"]
        # Clock advances past the notice window while the notice is still DRAFT
        set_clock("2025-12-05T00:00:00Z")
        notice = validate_success(api_client.get_safe_harbor_notice(parts["notice"]["id"], AUDITOR))
        assert notice["status"] == "LAPSED"

        open_census(py_id)
        emp = add_employee(py_id, ssn="434340001", full_name="Nell")
        add_compensation(emp["id"], 10000000)
        lock_census(py_id)

        election = validate_success(
            api_client.get_safe_harbor_election(parts["election"]["id"], ADMIN)
        )
        assert election["status"] == "PROPOSED"

    def test_lapsed_notice_leaves_governing_design_unchanged(self):
        """PRD §3.8: "When those conditions align — including at the moment a notice is
        distributed into an already-locked year — the election flips to `EFFECTIVE` and
        the governing plan version's `safe_harbor_design` is set to the elected design,
        a ledger sync that keeps the version's provisions truthful."

        When the notice lapses, the flip never happens and the governing version's
        design stays `NONE`.

        Design: Difficulty/cross_entity_state_dependency/notice_state_gates_election_effectiveness
        """
        parts = _setup_year_with_election("Mike Ledger Corp")
        py_id = parts["plan_year"]["id"]
        set_clock("2025-12-05T00:00:00Z")
        open_census(py_id)
        emp = add_employee(py_id, ssn="434340002", full_name="Nell B")
        add_compensation(emp["id"], 10000000)
        lock_census(py_id)

        version = validate_success(api_client.get_plan_version(parts["version"]["id"], AUDITOR))
        assert version["safe_harbor_design"] == "NONE"
        election = validate_success(
            api_client.get_safe_harbor_election(parts["election"]["id"], ADMIN)
        )
        assert election["status"] == "PROPOSED"


class TestElectionSuspendCascade:
    def _setup_effective_election_with_terminal_run(self, legal_name="Golf Corp"):
        """EFFECTIVE election: notice distributed in-window before lock, then census
        locked (election flips EFFECTIVE), then a terminal FINAL ADP run."""
        employer = create_employer(legal_name=legal_name)
        publish_limits(2026)
        plan = create_plan_for(employer["id"], plan_name=f"{legal_name} SH")
        version = create_adopted_version(
            plan["id"], safe_harbor_design="BASIC_MATCH",
            sh_match_formula="100% of first 3% + 50% of next 2%",
        )
        py = create_plan_year_for(plan["id"])
        py_id = py["id"]
        election = validate_success(
            api_client.create_safe_harbor_election(
                py_id, {"design": "BASIC_MATCH", "elected_on": "2025-10-15"}, ADMIN
            ),
            expected_status=201,
        )
        notice = validate_success(
            api_client.create_safe_harbor_notice(
                election["id"],
                {"notice_period_start": "2025-11-01", "notice_period_end": "2025-11-30"},
                ADMIN,
            ),
            expected_status=201,
        )
        set_clock("2025-11-15T12:00:00Z")
        validate_success(api_client.distribute_safe_harbor_notice(notice["id"], ADMIN))
        open_census(py_id)
        h = add_employee(py_id, ssn="777770001", full_name="Hiro",
                         date_of_birth="1975-01-01", date_of_hire="2015-01-01",
                         ownership_pct_direct=6)
        n = add_employee(py_id, ssn="777770002", full_name="Iris",
                         date_of_birth="1985-01-01", date_of_hire="2019-01-01")
        add_compensation(h["id"], 30000000)
        add_compensation(n["id"], 10000000)
        lock_census(py_id)
        election_locked = validate_success(
            api_client.get_safe_harbor_election(election["id"], ADMIN)
        )
        assert election_locked["status"] == "EFFECTIVE", (
            f"election must be EFFECTIVE after lock with a distributed notice, "
            f"got {election_locked['status']}"
        )
        run = queue_and_execute_run(py_id, "ADP_401K", "FINAL")
        return {
            "employer": employer, "plan": plan, "version": version,
            "plan_year_id": py_id, "election": election_locked, "run": run,
        }

    def test_election_suspend_cascade_depth3(self):
        """PRD §3.8: "Suspension strips the design — the governing plan version's
        `safe_harbor_design` resets to `NONE`, so the plan loses safe harbor for the
        year and becomes subject to ADP/ACP testing — marks every `PASSED` or `FAILED`
        test run of the year `SUPERSEDED`, and increments the election's `version`"

        Design: Difficulty/transitive_cascade/election_suspend_cascade_depth3
        """
        ctx = self._setup_effective_election_with_terminal_run("Golf Corp")
        election = ctx["election"]
        suspended = validate_success(
            api_client.suspend_safe_harbor_election(
                election["id"],
                {"suspension_reason": "business downturn",
                 "expected_election_version": election["version"]},
                ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        version_after = validate_success(
            api_client.get_plan_version(ctx["version"]["id"], AUDITOR)
        )
        assert version_after["safe_harbor_design"] == "NONE"

        run_after = validate_success(api_client.get_test_run(ctx["run"]["id"], ANALYST))
        assert run_after["status"] == "SUPERSEDED"

    def test_fresh_run_after_suspension_evaluates_adp_formula(self):
        """PRD §3.8: "the plan loses safe harbor for the year and becomes subject to
        ADP/ACP testing"
        PRD §3.6: "Note that a passing `FINAL` run never reinstates anything: a safe
        harbor election sitting in `SUSPENDED` stays `SUSPENDED`."

        Design: Difficulty/transitive_cascade/election_suspend_cascade_depth3
        """
        ctx = self._setup_effective_election_with_terminal_run("Golf Fresh Corp")
        election = ctx["election"]
        validate_success(
            api_client.suspend_safe_harbor_election(
                election["id"],
                {"suspension_reason": "business downturn",
                 "expected_election_version": election["version"]},
                ADMIN,
            )
        )
        fresh = queue_and_execute_run(ctx["plan_year_id"], "ADP_401K", "FINAL")
        lines = get_result_lines(fresh["id"])
        hce_line = get_result_line(lines, "ADP_HCE_PCT")
        # Formula-evaluated (no deferrals posted): 0.0000, an inclusive-boundary PASS
        assert_pct(hce_line["value_pct"], 0.0)
        election_after = validate_success(
            api_client.get_safe_harbor_election(election["id"], ADMIN)
        )
        assert election_after["status"] == "SUSPENDED"


class TestNoticeWindowGap:
    def test_notice_window_30day_aggregate_gap_rule(self):
        """PRD §3.8: "For a mid-year amendment — the plan year already in
        `CENSUS_COLLECTING` — the notice must complete at least thirty days before the
        plan year ends: `notice_period_end` on or before `year_end` minus 30 days."
        PRD §3.8: "a distribution attempted outside the window, or against a window
        that fails the thirty-day rule, is rejected with `ERR_NOTICE_WINDOW_CLOSED`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/notice_window_30day_aggregate_gap_rule
        """
        parts = setup_employer_plan_version_year(legal_name="Papa Corp", plan_name="Papa 401k")
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        election_a = validate_success(
            api_client.create_safe_harbor_election(
                py_id, {"design": "ENHANCED_MATCH", "elected_on": "2026-10-01"}, ADMIN
            ),
            expected_status=201,
        )
        notice_a = validate_success(
            api_client.create_safe_harbor_notice(
                election_a["id"],
                {"notice_period_start": "2026-10-15", "notice_period_end": "2026-11-15"},
                ADMIN,
            ),
            expected_status=201,
        )
        # A second election while one sits in PROPOSED is rejected (PRD §3.8)
        dup = api_client.create_safe_harbor_election(
            py_id, {"design": "QACA", "elected_on": "2026-11-20"}, ADMIN
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE, expected_status=409)

        # Window ending 2026-11-15 leaves 46 days before year-end (>= 30): distributes
        set_clock("2026-11-01T00:00:00Z")
        distributed = validate_success(
            api_client.distribute_safe_harbor_notice(notice_a["id"], ADMIN)
        )
        assert distributed["status"] == "DISTRIBUTED"

        # Revoke the first election, then a window ending 2026-12-15 (16 days before
        # year-end, < 30) must fail the thirty-day rule at distribution time.
        validate_success(api_client.revoke_safe_harbor_election(election_a["id"], ADMIN))
        election_b = validate_success(
            api_client.create_safe_harbor_election(
                py_id, {"design": "QACA", "elected_on": "2026-11-20"}, ADMIN
            ),
            expected_status=201,
        )
        notice_b = validate_success(
            api_client.create_safe_harbor_notice(
                election_b["id"],
                {"notice_period_start": "2026-11-15", "notice_period_end": "2026-12-15"},
                ADMIN,
            ),
            expected_status=201,
        )
        set_clock("2026-11-20T00:00:00Z")
        resp = api_client.distribute_safe_harbor_notice(notice_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_CLOSED, expected_status=422)

    def test_notice_window_boundary_exactly_30_days_passes(self):
        """PRD §3.8: "`notice_period_end` on or before `year_end` minus 30 days."

        A window ending exactly 2026-12-01 (year_end 2026-12-31 minus 30 days) satisfies
        the rule; distribution inside the window succeeds.

        Design: Difficulty/resource_temporal_overlap/notice_window_30day_aggregate_gap_rule
        """
        parts = setup_employer_plan_version_year(
            legal_name="Papa Boundary Corp", plan_name="Papa Boundary 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        election = validate_success(
            api_client.create_safe_harbor_election(
                py_id, {"design": "ENHANCED_MATCH", "elected_on": "2026-10-01"}, ADMIN
            ),
            expected_status=201,
        )
        notice = validate_success(
            api_client.create_safe_harbor_notice(
                election["id"],
                {"notice_period_start": "2026-10-15", "notice_period_end": "2026-12-01"},
                ADMIN,
            ),
            expected_status=201,
        )
        set_clock("2026-11-15T00:00:00Z")
        distributed = validate_success(
            api_client.distribute_safe_harbor_notice(notice["id"], ADMIN)
        )
        assert distributed["status"] == "DISTRIBUTED"


class TestValidationPrecedencePairs:
    def test_state_beats_fiscal_on_contribution_over_limit_in_locked_year(self):
        """PRD §2.8: "the error surfaced is always the earliest applicable failure
        rather than an arbitrary one. The sequence runs as follows. ... Next come the
        lifecycle-state gates: child creation under an archived employer, version or
        plan-year creation under a terminated plan, then the plan-year workflow-state
        gate that decides which mutations the plan year currently permits ... The
        remaining business rules close the sequence in this order: ... contribution and
        compensation limit checks"
        PRD §3.4: "Posting is accepted in any workflow state from `CENSUS_COLLECTING`
        through `CORRECTING`"

        A contribution posted against a TERMINATED year violates the workflow-state gate
        and (being over the 402(g) limit) the limit check; the state gate is earlier.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_contribution_over_limit_in_locked_year
        """
        parts = setup_employer_plan_version_year(legal_name="India Corp", plan_name="India 401k")
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="999990001", full_name="Ned")
        validate_success(api_client.terminate_plan_year(py_id, ADMIN))

        resp = api_client.create_contribution(
            emp["id"],
            create_contribution_payload(amount_cents=9999999, contribution_date="2026-06-30"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_state_gate_fires_regardless_of_limit_overage_magnitude(self):
        """PRD §2.8: "a request that fails an earlier check never reaches a later one,
        so the error surfaced is always the earliest applicable failure rather than an
        arbitrary one."
        PRD §3.9: "once reached, no further workflow transitions apply."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_contribution_over_limit_in_locked_year
        """
        parts = setup_employer_plan_version_year(
            legal_name="India Magnitude Corp", plan_name="India Magnitude 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        emp = add_employee(py_id, ssn="999990002", full_name="Ned B")
        validate_success(api_client.terminate_plan_year(py_id, ADMIN))

        # Even a within-limit amount is rejected by the state gate on a TERMINATED year
        resp = api_client.create_contribution(
            emp["id"],
            create_contribution_payload(amount_cents=100000, contribution_date="2026-06-30"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_referential_beats_temporal_on_bad_family_link_and_bad_window(self):
        """PRD §2.8: "Referential integrity comes next, then uniqueness constraints,
        then payload shape — required fields present, enum members declared, conditional
        fields honored. Temporal checks follow: date-interval sanity, then the safe
        harbor notice window."
        PRD §3.4: "it must reference the `ssn` of an existing employee in the same plan
        year, and a dangling or cross-year reference is rejected with `ERR_FK_INTEGRITY`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_bad_family_link_and_bad_window
        """
        parts = setup_employer_plan_version_year(
            legal_name="Juliet Corp", plan_name="Juliet 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        add_employee(py_id, ssn="121210001", full_name="Kai")

        resp = api_client.create_census_employee(
            py_id,
            create_census_employee_payload(
                ssn="121210002", full_name="Liv", date_of_birth="1982-01-01",
                date_of_hire="2026-05-01", date_of_termination="2026-03-01",
                employment_status="TERMINATED", family_member_of_ssn="999999999",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FK_INTEGRITY, expected_status=422)

    def test_dangling_family_reference_rejected(self):
        """PRD §3.4: "A `family_member_of_ssn` entry, null when the employee has no
        family link in the census, declares that this employee is the spouse, child,
        parent, or grandparent of the referenced employee for family attribution; it
        must reference the `ssn` of an existing employee in the same plan year, and a
        dangling or cross-year reference is rejected with `ERR_FK_INTEGRITY`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_bad_family_link_and_bad_window
        """
        parts = setup_employer_plan_version_year(
            legal_name="Juliet Pure Corp", plan_name="Juliet Pure 401k"
        )
        py_id = parts["plan_year"]["id"]
        open_census(py_id)
        add_employee(py_id, ssn="121210003", full_name="Kai Pure")

        resp = api_client.create_census_employee(
            py_id,
            create_census_employee_payload(
                ssn="121210004", full_name="Liv Pure",
                family_member_of_ssn="999999999",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FK_INTEGRITY, expected_status=422)
