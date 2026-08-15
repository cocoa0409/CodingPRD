"""Effort cycles and statements: fan-out, certify, reopen/recertify, variance
thresholds, the 100% conservation gate, and fringe true-up (PRD §3.4)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    make_sponsor, make_person, create_active_award, make_commitment,
    post_salary_expenditure, make_cycle, open_cycle,
    find_award_statement, find_nonsponsored_statement, certify_statement,
    create_effort_cycle_payload, setup_salary_award,
    setup_certifying_cycle_with_award_statement,
    make_pi_headers, make_research_staff_headers,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


class TestEffortCycleHalfOpenAdjacency:
    """Difficulty instance: half-open windows; boundary instant is exclusive."""

    def test_adjacent_cycle_created(self, api):
        """PRD §3.4: "Cycle windows are half-open — the window includes
        `period_start` and excludes `period_end` — and a new cycle's window
        must not overlap any existing cycle's window, where overlap means the
        new start falls before the other's end and the new end falls after the
        other's start; adjacency is allowed, and a violation returns
        `ERR_CYCLE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/effort_cycle_half_open_adjacency
        """
        make_cycle(cycle_code="2026-H1")
        created = validate_success(api.create_effort_cycle(
            create_effort_cycle_payload(
                cycle_code="2026-H2", period_start="2026-07-01T00:00:00Z",
                period_end="2027-01-01T00:00:00Z"), GA), 201)
        assert created["cycle_code"] == "2026-H2"

    def test_one_day_intrusion_rejected(self, api):
        """PRD §3.4: "a new cycle's window must not overlap any existing
        cycle's window, where overlap means the new start falls before the
        other's end and the new end falls after the other's start; adjacency is
        allowed, and a violation returns `ERR_CYCLE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/effort_cycle_half_open_adjacency
        """
        make_cycle(cycle_code="2026-H1")
        validate_success(api.create_effort_cycle(
            create_effort_cycle_payload(
                cycle_code="2026-H2", period_start="2026-07-01T00:00:00Z",
                period_end="2027-01-01T00:00:00Z"), GA), 201)
        res = api.create_effort_cycle(
            create_effort_cycle_payload(
                cycle_code="2026-X", period_start="2026-06-30T00:00:00Z",
                period_end="2026-12-31T00:00:00Z"), GA)
        validate_error(res, ApiErrorId.ERR_CYCLE_PERIOD_OVERLAP.value)


class TestSecondCycleOpenWhileCertifying:
    def test_second_cycle_open_while_certifying_rejected(self, api):
        """PRD §3.4: "Opening the cycle moves it `SCHEDULED → CERTIFYING` and
        is gated twice: the logical clock must have reached `period_start`
        (`ERR_CYCLE_NOT_YET_OPENABLE`), and no other cycle may already be
        `CERTIFYING` (`ERR_CYCLE_ALREADY_CERTIFYING`)."

        Design: Corner/errors/second_cycle_open_while_certifying_rejected
        """
        c1 = make_cycle(cycle_code="2026-H1")
        c2 = make_cycle(cycle_code="2026-H2",
                        period_start="2026-07-01T00:00:00Z",
                        period_end="2027-01-01T00:00:00Z")
        open_cycle(c1["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, ADMIN))
        res = api.open_effort_cycle(c2["id"], GA)
        validate_error(res, ApiErrorId.ERR_CYCLE_ALREADY_CERTIFYING.value)
        c2_after = validate_success(api.get_effort_cycle(c2["id"], GA), 200)
        assert c2_after["status"] == "SCHEDULED"


class TestEffortStatementReopenRecertifyCycle:
    """Difficulty instance: PENDING -> CERTIFIED -> REOPENED -> RECERTIFIED
    with the OCC version advancing at each hop."""

    def _setup(self, api, award_number="K-001"):
        sponsor, person, award, sal, _fr = setup_salary_award(award_number)
        post_salary_expenditure(award["id"], sal["id"], person["id"],
                                25.0, 1, "2026-03-01T00:00:00Z")
        cycle, statement = setup_certifying_cycle_with_award_statement(
            award, person)
        return person, cycle, statement

    def test_certify_then_reopen_states_and_versions(self, api):
        """PRD §3.4: "Certification moves `PENDING → CERTIFIED`, bumps the
        statement's `version`, and records the variance and flag."
        PRD §3.4: "an accountant may reopen a `CERTIFIED` statement while the
        cycle is still `CERTIFYING` (`ERR_STATEMENT_NOT_CERTIFIABLE`
        otherwise), moving it to `REOPENED`: the charged figure is recomputed,
        the certified value and variance are cleared, and the version bumps."

        Design: Difficulty/non_linear_state_machine/effort_statement_reopen_recertify_cycle
        """
        person, cycle, statement = self._setup(api)
        # charged = 100 * 416667 / (2000000 * 6) = 3.47
        assert statement["charged_effort_pct"] == 3.47
        certified = validate_success(certify_statement(
            statement, 3.47, person["id"]), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["version"] == 2
        reopened = validate_success(api.reopen_effort_statement(
            statement["id"], {"reason": "late payroll adjustment posted"}, GA), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["version"] == 3

    def test_recertify_with_new_occ_token(self, api):
        """PRD §3.4: "The certifier then re-certifies through the same path —
        same preconditions, same OCC field, same variance and floor
        computations — moving `REOPENED → RECERTIFIED`."

        Design: Difficulty/non_linear_state_machine/effort_statement_reopen_recertify_cycle
        """
        person, cycle, statement = self._setup(api)
        certified = validate_success(certify_statement(statement, 3.47, person["id"]), 200)
        reopened = validate_success(api.reopen_effort_statement(
            statement["id"], {"reason": "late payroll adjustment posted"}, GA), 200)
        recertified = validate_success(certify_statement(reopened, 3.47, person["id"]), 200)
        assert recertified["status"] == "RECERTIFIED"
        assert recertified["version"] == 4


class TestCertifyVarianceThreshold:
    """Corner calculations instance: variance note over 5.00 pp; key-personnel
    floor."""

    def _setup(self, api):
        sponsor, person, award, sal, _fr = setup_salary_award("K3-001")
        post_salary_expenditure(award["id"], sal["id"], person["id"],
                                25.0, 1, "2026-03-01T00:00:00Z")
        cycle, statement = setup_certifying_cycle_with_award_statement(award, person)
        return person, statement

    def test_over_variance_without_note_rejected(self, api):
        """PRD §3.4: "when the absolute variance exceeds 5.00 percentage
        points, a `payroll_adjustment_note` of at least 20 characters is
        required (`ERR_VARIANCE_NOTE_REQUIRED`)."

        Design: Corner/calculations/certify_over_variance_without_note_rejected
        """
        person, statement = self._setup(api)
        res = certify_statement(statement, 10.0, person["id"])
        validate_error(res, ApiErrorId.ERR_VARIANCE_NOTE_REQUIRED.value)

    def test_note_passes_and_key_floor_flagged(self, api):
        """PRD §3.4: "The system then computes `variance_pp` as the
        certified value minus the charged value, rounded half-up to two
        decimals; when the absolute variance exceeds 5.00 percentage points, a
        `payroll_adjustment_note` of at least 20 characters is required
        (`ERR_VARIANCE_NOTE_REQUIRED`)."
        PRD §3.4: "when the underlying commitment's `is_key_personnel` is true
        and the certified percentage falls below three quarters of the
        committed percentage, `key_reduction_flag` becomes true — a sponsor
        prior-approval situation observable on the statement."

        Design: Corner/calculations/certify_over_variance_without_note_rejected
        """
        person, statement = self._setup(api)
        res = certify_statement(statement, 10.0, person["id"])
        validate_error(res, ApiErrorId.ERR_VARIANCE_NOTE_REQUIRED.value)
        fresh = validate_success(api.get_effort_statement(statement["id"], GA), 200)
        certified = validate_success(certify_statement(
            fresh, 10.0, person["id"],
            payroll_adjustment_note="payroll reallocation journal pending"), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["variance_pp"] == 6.53       # 10.00 - 3.47
        # 10.00 < 0.75 * 50.00 = 37.50 -> key-personnel reduction floor crossed
        assert certified["key_reduction_flag"] is True


class TestOwnershipOnCertify:
    def test_ownership_beats_state_on_certify(self, api):
        """PRD §2.7: "(3) ownership scoping for entity-backed roles
        (`ERR_FORBIDDEN_OWNERSHIP`)" precedes "(6) state-machine transition
        validity...".
        PRD §3.4: "an `X-User-ID` other than the statement's `person_id` is
        rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/validations/ownership_beats_state_on_certify
        """
        sp = make_sponsor()
        pb = make_person(full_name="P. Beta")   # PI-B (owner)
        pa = make_person(full_name="P. Alpha")  # PI-A (intruder)
        award, _lines = create_active_award(
            sp["id"], pb["id"], "V-002",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        make_commitment(award["id"], pb["id"], 50.0, True)
        cycle = open_cycle(make_cycle()["id"])
        statement = find_award_statement(cycle["id"], award["id"])
        # PI-B certifies (statement now CERTIFIED).
        validate_success(certify_statement(statement, 0.0, pb["id"]), 200)
        # PI-A attempts to certify PI-B's statement: ownership fails even
        # though the state would also fail.
        res = certify_statement(statement, 0.0, pa["id"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

    def test_pi_certifies_own_statement_allowed(self, api):
        """PRD §3.4: "a `PrincipalInvestigator` or `ResearchStaff` certifies
        their own statement, and only their own — an `X-User-ID` other than the
        statement's `person_id` is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/pi_certifies_own_statement_allowed
        """
        sponsor, person, award, sal, _fr = setup_salary_award("RB-902")
        cycle, statement = setup_certifying_cycle_with_award_statement(award, person)
        certified = validate_success(certify_statement(statement, 0.0, person["id"]), 200)
        assert certified["status"] == "CERTIFIED"


class TestCycleCloseGates:
    def test_close_with_uncertified_statements_rejected(self, api):
        """PRD §3.4: "Every generated statement must sit in `CERTIFIED` or
        `RECERTIFIED` (`ERR_CYCLE_HAS_UNCERTIFIED_STATEMENTS`), and for each
        person the sum of `certified_effort_pct` across all their statements —
        award and non-sponsored together — must equal exactly 100.00
        (`ERR_EFFORT_TOTAL_NOT_100`)."

        Design: Corner/state_machines/cycle_close_with_uncertified_statements_rejected
        """
        sponsor, person, award, sal, _fr = setup_salary_award(
            "SM-006", salary_line=5_100_000, fringe_line=0,
            obligated=7_650_000, fringe_rate_bps=0)
        cycle = open_cycle(make_cycle()["id"])
        res = api.close_effort_cycle(cycle["id"], {"actual_fringe_rate_bps": 0}, GA)
        validate_error(res, ApiErrorId.ERR_CYCLE_HAS_UNCERTIFIED_STATEMENTS.value)
        cycle_after = validate_success(api.get_effort_cycle(cycle["id"], GA), 200)
        assert cycle_after["status"] == "CERTIFYING"


class TestEffortCertificationTotal100Invariant:
    """Difficulty instance: the per-person 100.00 conservation gate at close."""

    def _setup(self, api):
        sp1 = make_sponsor(name="NSF-LOC")
        sp2 = make_sponsor(name="FDN", payment_method="COST_REIMBURSABLE_INVOICE",
                           sponsor_type="FOUNDATION", f_and_a_rate_bps=2000,
                           salary_cap_annual_cents=None)
        pa = make_person(ibs=24_000_000, appointment_months=12, full_name="P. Alpha")
        w1, l1 = create_active_award(
            sp1["id"], pa["id"], "W1-001",
            [{"category": "PERSONNEL_SALARIES", "authorized_cents": 5_100_000}],
            7_650_000, fringe_rate_bps=0)
        w2, l2 = create_active_award(
            sp2["id"], pa["id"], "W2-001",
            [{"category": "PERSONNEL_SALARIES", "authorized_cents": 6_000_000}],
            7_200_000, fringe_rate_bps=0)
        make_commitment(w1["id"], pa["id"], 50.0, True)
        make_commitment(w2["id"], pa["id"], 50.0, False)
        post_salary_expenditure(w1["id"], l1["PERSONNEL_SALARIES"]["id"], pa["id"],
                                50.0, 6, "2026-03-01T00:00:00Z")
        post_salary_expenditure(w2["id"], l2["PERSONNEL_SALARIES"]["id"], pa["id"],
                                50.0, 6, "2026-03-01T00:00:00Z")
        cycle = open_cycle(make_cycle()["id"])
        s1 = find_award_statement(cycle["id"], w1["id"])
        s2 = find_award_statement(cycle["id"], w2["id"])
        sn = find_nonsponsored_statement(cycle["id"], pa["id"])
        return pa, cycle, s1, s2, sn

    def test_charged_figures_reflect_cap_interaction(self, api):
        """PRD §3.4: "the denominator always uses full uncapped IBS while the
        numerator only ever contains the capped charge, so an over-cap person
        cannot reach their nominal effort percentage on that award — the gap
        lands in institutional effort instead."

        Design: Difficulty/compensating_invariant/effort_certification_total_100_invariant
        """
        pa, cycle, s1, s2, sn = self._setup(api)
        # W1 capped: charge = round(1666667 * 0.5 * 6) = 5000001 ->
        # 5000001/12000000 = 41.67. W2 uncapped: 6000000/12000000 = 50.00.
        assert s1["charged_effort_pct"] == 41.67
        assert s2["charged_effort_pct"] == 50.0

    def test_close_fails_at_99_99_and_succeeds_at_100(self, api):
        """PRD §2.8: "effort certification distributes a fixed 100% of
        institutional effort per person per cycle: at cycle close, the sum of
        `certified_effort_pct` over all of a person's statements (AWARD and
        NON_SPONSORED together) must equal exactly 100.00."
        PRD §3.4: "for each person the sum of `certified_effort_pct` across all
        their statements — award and non-sponsored together — must equal
        exactly 100.00 (`ERR_EFFORT_TOTAL_NOT_100`)."

        Design: Difficulty/compensating_invariant/effort_certification_total_100_invariant
        """
        pa, cycle, s1, s2, sn = self._setup(api)
        validate_success(certify_statement(s1, 41.67, pa["id"]), 200)
        validate_success(certify_statement(s2, 50.0, pa["id"]), 200)
        validate_success(certify_statement(
            sn, 8.32, pa["id"],
            payroll_adjustment_note="residual institutional effort allocation"), 200)
        res = api.close_effort_cycle(cycle["id"], {"actual_fringe_rate_bps": 0}, GA)
        validate_error(res, ApiErrorId.ERR_EFFORT_TOTAL_NOT_100.value)
        cycle_after = validate_success(api.get_effort_cycle(cycle["id"], GA), 200)
        assert cycle_after["status"] == "CERTIFYING"
        # Compensating re-certification of the NON_SPONSORED statement to 8.33.
        reopened = validate_success(api.reopen_effort_statement(
            sn["id"], {"reason": "correct institutional split"}, GA), 200)
        validate_success(certify_statement(
            reopened, 8.33, pa["id"],
            payroll_adjustment_note="residual institutional effort allocation"), 200)
        closed = validate_success(api.close_effort_cycle(
            cycle["id"], {"actual_fringe_rate_bps": 0}, GA), 200)
        assert closed["status"] == "CLOSED"


class TestFringeProvisionalVsActualTrueup:
    """Difficulty instance: provisional fringe at post, true-up at cycle close."""

    def _setup(self, api):
        sp = make_sponsor()
        rnd = make_person(role_type="RESEARCH_STAFF", ibs=13_333_332,
                          appointment_months=12, full_name="R. Nd")
        pi = make_person()
        award, lines = create_active_award(
            sp["id"], pi["id"], "F-001",
            [
                {"category": "PERSONNEL_SALARIES", "authorized_cents": 500_000},
                {"category": "FRINGE_BENEFITS", "authorized_cents": 150_000},
            ],
            975_000, fringe_rate_bps=2795)
        make_commitment(award["id"], rnd["id"], 40.0, False)
        post_salary_expenditure(award["id"], lines["PERSONNEL_SALARIES"]["id"],
                                rnd["id"], 30.0, 1, "2026-02-01T00:00:00Z")
        post_salary_expenditure(award["id"], lines["PERSONNEL_SALARIES"]["id"],
                                rnd["id"], 10.0, 1, "2026-03-01T00:00:00Z")
        cycle = open_cycle(make_cycle()["id"])
        st_a = find_award_statement(cycle["id"], award["id"])
        st_n = find_nonsponsored_statement(cycle["id"], rnd["id"])
        validate_success(certify_statement(
            st_a, 6.67, rnd["id"], role="ResearchStaff"), 200)
        validate_success(certify_statement(
            st_n, 93.33, rnd["id"], role="ResearchStaff",
            payroll_adjustment_note="institutional teaching and administration allocation"), 200)
        return cycle, lines["FRINGE_BENEFITS"]

    def test_provisional_fringe_total_before_close(self, api):
        """PRD §3.2: "a salary expenditure additionally computes
        `fringe_cents` as `amount_cents` times the award's provisional
        `fringe_rate_bps` over ten thousand, rounded half-up per line, and adds
        that to the `FRINGE_BENEFITS` line's `spent_cents` (when `fringe_cents`
        is zero this debit is a no-op and no `FRINGE_BENEFITS` line need
        exist)."

        Design: Difficulty/dual_variant_calc/fringe_provisional_vs_actual_trueup
        """
        cycle, fr = self._setup(api)
        fr_line = validate_success(api.get_budget_line(fr["id"], GA), 200)
        # round(333333*0.2795)=93167 + round(111111*0.2795)=31056
        assert fr_line["spent_cents"] == 124_223

    def test_trueup_adjustment_posts_at_cycle_close(self, api):
        """PRD §3.4: "For each such award the base is the sum of `amount_cents`
        over those salary expenditures (excluding `TRANSFERRED_OUT` sources);
        the adjustment is that base multiplied by the difference between the
        cycle's actual rate and the award's provisional `fringe_rate_bps`, in
        basis points over ten thousand, rounded half-up to cents; a nonzero
        adjustment is added to the award's `FRINGE_BENEFITS` line
        `spent_cents`."

        Design: Difficulty/dual_variant_calc/fringe_provisional_vs_actual_trueup
        """
        cycle, fr = self._setup(api)
        fr_before = validate_success(api.get_budget_line(fr["id"], GA), 200)["spent_cents"]
        closed = validate_success(api.close_effort_cycle(
            cycle["id"], {"actual_fringe_rate_bps": 2800}, GA), 200)
        assert closed["status"] == "CLOSED"
        fr_after = validate_success(api.get_budget_line(fr["id"], GA), 200)["spent_cents"]
        # true-up: + round(444444 * 5 / 10000) = +222
        assert fr_before == 124_223
        assert fr_after == 124_445
        assert fr_after - fr_before == 222
