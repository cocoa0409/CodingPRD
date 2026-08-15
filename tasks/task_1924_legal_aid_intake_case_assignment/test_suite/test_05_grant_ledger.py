"""Grant program ledger: per-case rounding order, conservation invariant,
close-time conversion vs release, suspend/resume cascades, period overlap,
close precondition, and report aggregation."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_grant_ledger_invariants,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_client,
    create_openable_application,
    open_case_from_application,
    create_grant_program,
    make_supervising_attorney_headers,
    make_staff_attorney_headers,
    make_grants_manager_headers,
    make_program_director_headers,
)


def _open_funded_advice_case(api, grant_id, case_type="CONSUMER_DEBT"):
    """Venue rule + intake + sup + client + ELIGIBLE app + CLEAR check +
    grant-funded ADVICE_ONLY open. Returns (case, app, intake, sup)."""
    create_venue_rule(county="CountyA", case_type=case_type, venue="MUNICIPAL_COURT",
                      priority_base_weight=30, extended_eligible=False)
    intake = create_intake_specialist(practice_areas=[case_type])
    sup = create_supervisor(practice_areas=[case_type])
    client = create_client(intake["id"], full_name="Cli Funded")
    app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                      opposing_party_name="Collector")
    case = open_case_from_application(app["id"], sup["id"], service_level="ADVICE_ONLY",
                                      grant_program_id=grant_id)
    return case, app, intake, sup


class TestRoundingOrder:
    def test_grant_reservation_rounding_order_per_case(self, api):
        """PRD §3.5: "The rounding order is pinned: each case's reservation is
        rounded individually to whole cents, and the program's `reserved_cents`
        is the sum of those whole-cent integers; summing unrounded reservations
        and rounding once at the program level is forbidden. With a rate of
        33,333 cents, for instance, each advice-only case reserves the rate
        multiplied by two-fifths — 13,333.20 cents before rounding, 13,333
        after — so three advice-only cases tie up 39,999 cents of program
        budget, not 40,000."

        Design: Difficulty/combinatorial_formula/grant_reservation_rounding_order_per_case
        """
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="EXPUNGEMENT",
                          venue="SUPERIOR_COURT", priority_base_weight=25,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["BENEFITS_APPEAL"])
        sup = create_supervisor(practice_areas=["BENEFITS_APPEAL"])
        grant = create_grant_program(name="LSC General",
                                     allowed_case_types=["BENEFITS_APPEAL", "CONSUMER_DEBT",
                                                         "EXPUNGEMENT"])
        client = create_client(intake["id"], full_name="Cli Round")
        plans = [("BENEFITS_APPEAL", "Agency"), ("CONSUMER_DEBT", "Collector"),
                 ("EXPUNGEMENT", "State")]
        case3 = None
        for case_type, opposing in plans:
            app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                              opposing_party_name=opposing)
            case3 = open_case_from_application(app["id"], sup["id"],
                                               service_level="ADVICE_ONLY",
                                               grant_program_id=grant["id"])
        assert case3["reserved_cents"] == 13_333  # round_half_up(33,333 * 2 / 5)
        g = validate_success(api.get_grant_program(grant["id"],
                                                   make_program_director_headers()))
        assert g["reserved_cents"] == 39_999  # 3 x 13,333, NOT round(39,999.6) = 40,000
        assert g["available_cents"] == 60_001
        assert g["spent_cents"] == 0

    def test_grant_reservation_extended_case_full_rate(self, api):
        """PRD §3.5: "The funding axis initializes alongside: when a grant was
        named, the case's `funding_status` becomes `GRANT_RESERVED` and its
        reservation is computed at open time — the program's
        `per_case_rate_cents` multiplied by the case's `case_weight` and
        divided by 5, rounded half-up to a whole cent, stored on the case as
        `reserved_cents`."
        PRD §2.11: "The ledger conserves funds at all times:
        `reserved_cents` plus `spent_cents` plus `available_cents` always
        equals `total_budget_cents`, with `available_cents` defined as the
        budget minus reserved minus spent."

        Design: Difficulty/combinatorial_formula/grant_reservation_rounding_order_per_case
        """
        grant = create_grant_program(name="Ext Fund", funder="DOJ",
                                     allowed_case_types=["FAMILY_DV"])
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"])
        create_attorney(full_name="Att Pool", practice_areas=["FAMILY_DV"], max_units=10)
        client = create_client(intake["id"], full_name="Cli Ext", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        case = open_case_from_application(app["id"], sup["id"], service_level="EXTENDED",
                                          grant_program_id=grant["id"])
        # weight 5: round_half_up(33,333 * 5 / 5) = 33,333
        assert case["reserved_cents"] == 33_333
        assert case["funding_status"] == "GRANT_RESERVED"
        g = validate_success(api.get_grant_program(grant["id"],
                                                   make_program_director_headers()))
        assert_grant_ledger_invariants(g)
        assert g["reserved_cents"] == 33_333

    def test_grant_cents_conserved_reserve_then_release(self, api):
        """PRD §2.11: "The ledger conserves funds at all times:
        `reserved_cents` plus `spent_cents` plus `available_cents` always
        equals `total_budget_cents`, with `available_cents` defined as the
        budget minus reserved minus spent."
        PRD §3.8: "a non-billable outcome — `REFERRED_OUT`,
        `WITHDRAWN_BY_CLIENT`, or `ADMINISTRATIVE` — releases the reservation,
        decreasing `reserved_cents` and moving the case to `GRANT_RELEASED`
        so the funds return to availability."

        Design: Difficulty/compensating_invariant/grant_cents_conserved_reserve_then_release
        """
        grant = create_grant_program(name="Debt Fund")
        case, app, intake, sup = _open_funded_advice_case(api, grant["id"])
        pd = make_program_director_headers()

        mid = validate_success(api.get_grant_utilization(grant["id"], pd))
        assert mid["reserved_cents"] == 13_333
        assert mid["spent_cents"] == 0
        assert mid["available_cents"] == 86_667
        assert mid["reserved_cents"] + mid["spent_cents"] + mid["available_cents"] == 100_000

        validate_success(api.close_case(
            case["id"], {"outcome_code": "REFERRED_OUT",
                         "closure_reason": "sent to pro bono"},
            make_supervising_attorney_headers(sup["id"])))
        end = validate_success(api.get_grant_utilization(grant["id"], pd))
        assert end["reserved_cents"] == 0
        assert end["spent_cents"] == 0
        assert end["available_cents"] == 100_000
        closed = validate_success(api.get_case(case["id"], pd))
        assert closed["funding_status"] == "GRANT_RELEASED"

    def test_billable_close_converts_reservation_to_spent(self, api):
        """PRD §3.8: "for a case whose `funding_status` is `GRANT_RESERVED` or
        `GRANT_FROZEN`, a billable outcome — `FULL_WIN`, `PARTIAL_WIN`,
        `SETTLEMENT`, or `ADVICE_GIVEN` — converts the reservation, decreasing
        the program's `reserved_cents` by the case's `reserved_cents`,
        increasing its `spent_cents` by the same amount, and moving the case
        to `GRANT_SPENT`;"

        Design: Difficulty/compensating_invariant/grant_cents_conserved_reserve_then_release
        """
        grant = create_grant_program(name="Debt Fund 2")
        case, app, intake, sup = _open_funded_advice_case(api, grant["id"])
        pd = make_program_director_headers()
        validate_success(api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                                        make_supervising_attorney_headers(sup["id"])))
        end = validate_success(api.get_grant_utilization(grant["id"], pd))
        assert end["reserved_cents"] == 0
        assert end["spent_cents"] == 13_333
        assert end["available_cents"] == 86_667
        closed = validate_success(api.get_case(case["id"], pd))
        assert closed["funding_status"] == "GRANT_SPENT"


class TestSuspendResumeCascade:
    def _setup_funded_extended_open_case(self, api):
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"], max_units=4)
        att = create_attorney(full_name="Att One", practice_areas=["FAMILY_DV"], max_units=40)
        grant = create_grant_program(name="DV Fund", funder="DOJ",
                                     allowed_case_types=["FAMILY_DV"])
        client = create_client(intake["id"], full_name="Cli Cas", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        case = open_case_from_application(app["id"], sup["id"], service_level="EXTENDED",
                                          grant_program_id=grant["id"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        validate_success(api.assign_case(
            case["id"], {"attorney_id": att["id"],
                         "expected_case_version": case["version"]}, headers_sup))
        return grant, case, intake, sup, att

    def test_grant_suspend_depth3_transitive_cascade(self, api):
        """PRD §3.9: "Suspension propagates through three cascade links. When
        a `ProgramDirector` suspends an `ACTIVE` program, every case funded by
        that program whose `funding_status` is `GRANT_RESERVED` moves to
        `GRANT_FROZEN` — link one. The freeze then forces each such case from
        `OPEN` to `ON_HOLD` — link two — and each forced hold releases the
        assigned attorney's `weighted_open_units` by that case's `case_weight`,
        the capacity release attributed to the freeze cascade rather than to
        the original suspension call — link three."
        PRD §2.11: "A case's reservation counts toward its program's
        `reserved_cents` while the case's `funding_status` is `GRANT_RESERVED`
        or `GRANT_FROZEN` — a freeze never releases the reservation."

        Design: Difficulty/transitive_cascade/grant_suspend_depth3_transitive_cascade
        """
        grant, case, intake, sup, att = self._setup_funded_extended_open_case(api)
        pd = make_program_director_headers()
        before = validate_success(api.get_caseload(att["id"], pd))
        assert before["weighted_open_units"] == 5

        validate_success(api.suspend_grant_program(grant["id"], pd))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["funding_status"] == "GRANT_FROZEN"  # link 1
        assert c["status"] == "ON_HOLD"  # link 2, caused by link 1
        load = validate_success(api.get_caseload(att["id"], pd))
        assert load["weighted_open_units"] == 0  # link 3, caused by link 2
        g = validate_success(api.get_grant_program(grant["id"], pd))
        assert g["reserved_cents"] == 33_333  # freeze preserves the reservation

    def test_grant_suspend_leaves_unfunded_cases_untouched(self, api):
        """PRD §3.9: "When a `ProgramDirector` suspends an `ACTIVE` program,
        every case funded by that program whose `funding_status` is
        `GRANT_RESERVED` moves to `GRANT_FROZEN` — link one. The freeze then
        forces each such case from `OPEN` to `ON_HOLD` — link two — and each
        forced hold releases the assigned attorney's `weighted_open_units` by
        that case's `case_weight`, the capacity release attributed to the
        freeze cascade rather than to the original suspension call — link
        three."
        PRD §3.5: "When no grant was named, the case is `UNFUNDED` with a
        `reserved_cents` of 0 and touches no ledger."

        Design: Difficulty/transitive_cascade/grant_suspend_depth3_transitive_cascade
        """
        grant, case, intake, sup, att = self._setup_funded_extended_open_case(api)
        pd = make_program_director_headers()
        # second, UNFUNDED advice case assigned to the same attorney (load 5 + 2)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        client2 = create_client(intake["id"], full_name="Cli Unf")
        app2 = create_openable_application(intake["id"], client2["id"],
                                           case_type="CONSUMER_DEBT",
                                           opposing_party_name="Collector")
        case2 = open_case_from_application(app2["id"], sup["id"], service_level="ADVICE_ONLY")
        headers_sup = make_supervising_attorney_headers(sup["id"])
        # attorney covers FAMILY_DV only; give them CONSUMER_DEBT coverage for this assign
        validate_success(api.update_staff_member(
            att["id"], {"practice_areas": ["FAMILY_DV", "CONSUMER_DEBT"]}, pd))
        validate_success(api.assign_case(
            case2["id"], {"attorney_id": att["id"],
                          "expected_case_version": case2["version"]}, headers_sup))
        before = validate_success(api.get_caseload(att["id"], pd))
        assert before["weighted_open_units"] == 7

        validate_success(api.suspend_grant_program(grant["id"], pd))
        # unfunded case keeps its posture and still counts toward load
        c2 = validate_success(api.get_case(case2["id"], pd))
        assert c2["status"] == "OPEN"
        assert c2["funding_status"] == "UNFUNDED"
        after = validate_success(api.get_caseload(att["id"], pd))
        assert after["weighted_open_units"] == 2  # only the frozen 5 units released

    def test_case_parallel_status_funding_axes_evolve_independently(self, api):
        """PRD §3.9: "Resuming a `SUSPENDED` program returns it to `ACTIVE`
        and restores each frozen case's `funding_status` to `GRANT_RESERVED`,
        but the cases themselves stay `ON_HOLD`: each must be resumed
        individually under the capacity re-check of §3.6."
        PRD §3.8: "for a case whose `funding_status` is `GRANT_RESERVED` or
        `GRANT_FROZEN`, a billable outcome — `FULL_WIN`, `PARTIAL_WIN`,
        `SETTLEMENT`, or `ADVICE_GIVEN` — converts the reservation, decreasing
        the program's `reserved_cents` by the case's `reserved_cents`,
        increasing its `spent_cents` by the same amount, and moving the case
        to `GRANT_SPENT`;"

        Design: Difficulty/non_linear_state_machine/case_parallel_status_funding_axes_evolve_independently
        """
        grant, case, intake, sup, att = self._setup_funded_extended_open_case(api)
        pd = make_program_director_headers()
        headers_sup = make_supervising_attorney_headers(sup["id"])

        validate_success(api.suspend_grant_program(grant["id"], pd))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["status"] == "ON_HOLD"
        assert c["funding_status"] == "GRANT_FROZEN"

        validate_success(api.resume_grant_program(grant["id"], pd))
        c = validate_success(api.get_case(case["id"], pd))
        # funding axis restored while the status axis stays ON_HOLD — axes independent
        assert c["funding_status"] == "GRANT_RESERVED"
        assert c["status"] == "ON_HOLD"

        validate_success(api.resume_case(case["id"], headers_sup))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["status"] == "OPEN"
        assert c["funding_status"] == "GRANT_RESERVED"

        validate_success(api.close_case(case["id"], {"outcome_code": "FULL_WIN",
                                                     "closure_reason": "prevailed"},
                                        headers_sup))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["status"] == "CLOSED"
        assert c["funding_status"] == "GRANT_SPENT"

    def test_frozen_case_close_converts_reservation(self, api):
        """PRD §3.9: "Suspension propagates through three cascade links. When
        a `ProgramDirector` suspends an `ACTIVE` program, every case funded by
        that program whose `funding_status` is `GRANT_RESERVED` moves to
        `GRANT_FROZEN` — link one. The freeze then forces each such case from
        `OPEN` to `ON_HOLD` — link two — and each forced hold releases the
        assigned attorney's `weighted_open_units` by that case's
        `case_weight`, the capacity release attributed to the freeze cascade
        rather than to the original suspension call — link three."
        PRD §3.8: "for a case whose `funding_status` is `GRANT_RESERVED` or
        `GRANT_FROZEN`, a billable outcome — `FULL_WIN`, `PARTIAL_WIN`,
        `SETTLEMENT`, or `ADVICE_GIVEN` — converts the reservation, decreasing
        the program's `reserved_cents` by the case's `reserved_cents`,
        increasing its `spent_cents` by the same amount, and moving the case
        to `GRANT_SPENT`;"

        Design: Difficulty/non_linear_state_machine/case_parallel_status_funding_axes_evolve_independently
        """
        grant, case, intake, sup, att = self._setup_funded_extended_open_case(api)
        pd = make_program_director_headers()
        headers_sup = make_supervising_attorney_headers(sup["id"])
        validate_success(api.suspend_grant_program(grant["id"], pd))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["status"] == "ON_HOLD" and c["funding_status"] == "GRANT_FROZEN"
        # close from ON_HOLD while still frozen: billable outcome converts
        validate_success(api.close_case(case["id"], {"outcome_code": "FULL_WIN"},
                                        headers_sup))
        c = validate_success(api.get_case(case["id"], pd))
        assert c["status"] == "CLOSED" and c["funding_status"] == "GRANT_SPENT"
        g = validate_success(api.get_grant_program(grant["id"], pd))
        assert g["reserved_cents"] == 0
        assert g["spent_cents"] == 33_333
        assert_grant_ledger_invariants(g)

    def test_grant_program_suspend_resume_cycle(self, api):
        """PRD §3.9: "When a `ProgramDirector` suspends an `ACTIVE` program,
        every case funded by that program whose `funding_status` is
        `GRANT_RESERVED` moves to `GRANT_FROZEN` — link one."
        PRD §3.9: "Resuming a `SUSPENDED` program returns it to `ACTIVE` and
        restores each frozen case's `funding_status` to `GRANT_RESERVED`, but
        the cases themselves stay `ON_HOLD`: each must be resumed individually
        under the capacity re-check of §3.6. A program may be closed from
        `ACTIVE` or from `SUSPENDED`, but only when its `reserved_cents` is
        zero — frozen cases still reserve — else `ERR_GRANT_HAS_RESERVED_FUNDS`
        (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/grant_program_suspend_resume_cycle
        """
        grant = create_grant_program(name="Cyc", funder="STATE_BAR",
                                     total_budget_cents=50_000)
        pd = make_program_director_headers()
        s1 = validate_success(api.suspend_grant_program(grant["id"], pd))
        assert s1["status"] == "SUSPENDED"
        s2 = validate_success(api.resume_grant_program(grant["id"], pd))
        assert s2["status"] == "ACTIVE"
        s3 = validate_success(api.close_grant_program(grant["id"], pd))
        assert s3["status"] == "CLOSED"

    def test_grant_program_close_from_suspended_state(self, api):
        """PRD §3.9: "A program may be closed from `ACTIVE` or from
        `SUSPENDED`, but only when its `reserved_cents` is zero — frozen cases
        still reserve — else `ERR_GRANT_HAS_RESERVED_FUNDS` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/grant_program_suspend_resume_cycle
        """
        grant = create_grant_program(name="Cyc2", funder="STATE_BAR",
                                     total_budget_cents=50_000)
        pd = make_program_director_headers()
        validate_success(api.suspend_grant_program(grant["id"], pd))
        closed = validate_success(api.close_grant_program(grant["id"], pd))
        assert closed["status"] == "CLOSED"  # SUSPENDED -> CLOSED is a valid path

    def test_grant_close_with_reserved_funds_rejected(self, api):
        """PRD §3.9: "A program may be closed from `ACTIVE` or from
        `SUSPENDED`, but only when its `reserved_cents` is zero — frozen cases
        still reserve — else `ERR_GRANT_HAS_RESERVED_FUNDS` (HTTP 409)."

        Design: Corner/state_machines/grant_close_with_reserved_funds_rejected
        """
        grant = create_grant_program(name="Debt Fund")
        case, app, intake, sup = _open_funded_advice_case(api, grant["id"])
        pd = make_program_director_headers()
        bad = api.close_grant_program(grant["id"], pd)
        validate_error(bad, ApiErrorId.ERR_GRANT_HAS_RESERVED_FUNDS)
        validate_success(api.close_case(case["id"], {"outcome_code": "REFERRED_OUT"},
                                        make_supervising_attorney_headers(sup["id"])))
        good = validate_success(api.close_grant_program(grant["id"], pd))
        assert good["status"] == "CLOSED"

    def test_grant_suspend_on_closed_rejected(self, api):
        """PRD §3.9: "Grant actions from impermissible states fail with
        `ERR_INVALID_GRANT_STATE` (HTTP 409)."

        Design: Corner/validations/grant_suspend_on_closed_rejected
        """
        grant = create_grant_program(name="Done Fund", total_budget_cents=50_000)
        pd = make_program_director_headers()
        validate_success(api.close_grant_program(grant["id"], pd))
        resp = api.suspend_grant_program(grant["id"], pd)
        validate_error(resp, ApiErrorId.ERR_INVALID_GRANT_STATE)


class TestGrantPeriodOverlap:
    def test_grant_period_closed_interval_boundary_overlap(self, api):
        """PRD §3.9: "Two programs from the same `funder` may not have
        overlapping closed periods, and boundary-touching counts: one
        program's `period_end` equal to another's `period_start` is an
        overlap, rejected with `ERR_GRANT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/grant_period_closed_interval_boundary_overlap
        """
        pd = make_program_director_headers()
        create_grant_program(name="LSC 2026", funder="LSC", period_start="2026-01-01",
                             period_end="2026-12-31", income_cap_percentage=125.00,
                             per_case_rate_cents=10_000, total_budget_cents=50_000)
        # same funder, boundary touch 2026-12-31 belongs to both closed intervals
        bad = api.create_grant_program(
            {"name": "LSC 2027", "funder": "LSC", "period_start": "2026-12-31",
             "period_end": "2027-06-30", "allowed_case_types": ["EVICTION_DEFENSE"],
             "allowed_counties": ["CountyA"], "income_cap_percentage": 125.00,
             "per_case_rate_cents": 10_000, "total_budget_cents": 50_000}, pd)
        validate_error(bad, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP)
        # identical dates under a different funder succeed (overlap is per funder)
        ok = api.create_grant_program(
            {"name": "OTHER 2027", "funder": "OTHER", "period_start": "2026-12-31",
             "period_end": "2027-06-30", "allowed_case_types": ["EVICTION_DEFENSE"],
             "allowed_counties": ["CountyA"], "income_cap_percentage": 125.00,
             "per_case_rate_cents": 10_000, "total_budget_cents": 50_000}, pd)
        validate_success(ok, expected_status=201)

    def test_grant_period_strict_intersection_overlap(self, api):
        """PRD §3.9: "Two programs from the same `funder` may not have
        overlapping closed periods, and boundary-touching counts: one
        program's `period_end` equal to another's `period_start` is an
        overlap, rejected with `ERR_GRANT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/grant_period_closed_interval_boundary_overlap
        """
        pd = make_program_director_headers()
        create_grant_program(name="LSC 2026", funder="LSC", period_start="2026-01-01",
                             period_end="2026-12-31", income_cap_percentage=125.00,
                             per_case_rate_cents=10_000, total_budget_cents=50_000)
        # strictly intersecting same-funder window
        bad = api.create_grant_program(
            {"name": "LSC Mid", "funder": "LSC", "period_start": "2026-06-01",
             "period_end": "2027-05-31", "allowed_case_types": ["EVICTION_DEFENSE"],
             "allowed_counties": ["CountyA"], "income_cap_percentage": 125.00,
             "per_case_rate_cents": 10_000, "total_budget_cents": 50_000}, pd)
        validate_error(bad, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP)
        # disjoint same-funder window succeeds (2027-01-01 is past 2026-12-31)
        ok = api.create_grant_program(
            {"name": "LSC 2027", "funder": "LSC", "period_start": "2027-01-01",
             "period_end": "2027-12-31", "allowed_case_types": ["EVICTION_DEFENSE"],
             "allowed_counties": ["CountyA"], "income_cap_percentage": 125.00,
             "per_case_rate_cents": 10_000, "total_budget_cents": 50_000}, pd)
        validate_success(ok, expected_status=201)


class TestGrantReports:
    def test_report_generate_with_active_draft_rejected(self, api):
        """PRD §3.9: "A `GrantsManager` generates a report for a program by
        supplying a `period_label`; at most one report per program may be live
        in `DRAFT` or `SUBMITTED`, and generating while one exists is rejected
        with `ERR_INVALID_REPORT_STATE` (HTTP 409)."

        Design: Corner/validations/report_generate_with_active_draft_rejected
        """
        grant = create_grant_program(name="Rep Fund")
        gm = make_grants_manager_headers()
        validate_success(api.create_grant_report(grant["id"], {"period_label": "2026-Q3"}, gm),
                         expected_status=201)
        resp = api.create_grant_report(grant["id"], {"period_label": "2026-Q3-dup"}, gm)
        validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_STATE)

    def test_grant_report_aggregation_correctness(self, api):
        """PRD §3.9: "Generation freezes a snapshot: `cases_opened_count`
        counts the program's cases whose `opened_at` is set,
        `cases_closed_count` counts those in `CLOSED`, `total_hours` sums the
        `hours` of every time entry across the program's cases rounded half-up
        to two decimal places, and `reserved_cents_snapshot` and
        `spent_cents_snapshot` capture the ledger as it stands."

        Design: Corner/calculations/grant_report_aggregation_correctness
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        att = create_attorney(full_name="Att One", practice_areas=["FAMILY_DV"], max_units=40)
        grant = create_grant_program(name="DV Fund", funder="DOJ",
                                     allowed_case_types=["FAMILY_DV"])
        client = create_client(intake["id"], full_name="Cli Agg", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        headers_sup = make_supervising_attorney_headers(att["id"])
        case = open_case_from_application(app["id"], att["id"], service_level="EXTENDED",
                                          grant_program_id=grant["id"])
        validate_success(api.assign_case(case["id"], {"attorney_id": att["id"],
                                                      "expected_case_version": case["version"]},
                                         headers_sup))
        att_headers = make_staff_attorney_headers(att["id"])
        api.create_time_entry(case["id"], {"hours": 1.50, "activity_code": "RESEARCH",
                                           "work_date": "2026-08-05"}, att_headers)
        api.create_time_entry(case["id"], {"hours": 2.25, "activity_code": "DRAFTING",
                                           "work_date": "2026-08-06"}, att_headers)
        validate_success(api.close_case(case["id"], {"outcome_code": "FULL_WIN"}, att_headers))

        report = validate_success(
            api.create_grant_report(grant["id"], {"period_label": "2026-Q3"},
                                    make_grants_manager_headers()),
            expected_status=201)
        assert report["cases_opened_count"] == 1
        assert report["cases_closed_count"] == 1
        assert report["total_hours"] == pytest.approx(3.75, abs=0.001)
        assert report["spent_cents_snapshot"] == 33_333
        assert report["reserved_cents_snapshot"] == 0

    def test_report_return_revise_cycle_recomputes_aggregates(self, api):
        """PRD §3.9: "Later case activity never mutates an existing draft;
        only an explicit revision recomputes. The report lifecycle walks
        `DRAFT` to `SUBMITTED` by the grants manager, then to terminal
        `ACCEPTED` by the `ProgramDirector`, or back to `RETURNED` when the
        director supplies a non-empty `return_reason` — its absence fails with
        `ERR_INVALID_REQUEST` — and a returned report is revised by the grants
        manager back to `DRAFT`, recomputing every aggregate at that moment."

        Design: Corner/state_machines/report_return_revise_cycle_recomputes_aggregates
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"], max_units=4)
        att = create_attorney(full_name="Att One", practice_areas=["FAMILY_DV"], max_units=40)
        grant = create_grant_program(name="DV Fund", funder="DOJ",
                                     allowed_case_types=["FAMILY_DV"])
        client = create_client(intake["id"], full_name="Cli Rep", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        headers_sup = make_supervising_attorney_headers(sup["id"])
        case = open_case_from_application(app["id"], sup["id"], service_level="EXTENDED",
                                          grant_program_id=grant["id"])
        validate_success(api.assign_case(case["id"], {"attorney_id": att["id"],
                                                      "expected_case_version": case["version"]},
                                         headers_sup))
        gm = make_grants_manager_headers()
        pd = make_program_director_headers()
        draft = validate_success(
            api.create_grant_report(grant["id"], {"period_label": "2026-Q3"}, gm),
            expected_status=201)
        assert draft["cases_opened_count"] == 1
        assert draft["cases_closed_count"] == 0
        assert draft["total_hours"] == pytest.approx(0.00, abs=0.001)
        validate_success(api.submit_grant_report(draft["id"], gm))
        validate_success(api.return_grant_report(draft["id"],
                                                 {"return_reason": "missing closures"}, pd))

        att_headers = make_staff_attorney_headers(att["id"])
        api.create_time_entry(case["id"], {"hours": 1.50, "activity_code": "COURT_APPEARANCE",
                                           "work_date": "2026-08-10"}, att_headers)
        validate_success(api.close_case(case["id"], {"outcome_code": "FULL_WIN"}, att_headers))

        revised = validate_success(api.revise_grant_report(draft["id"], gm))
        assert revised["status"] == "DRAFT"
        assert revised["cases_closed_count"] == 1
        assert revised["total_hours"] == pytest.approx(1.50, abs=0.001)
        assert revised["spent_cents_snapshot"] == 33_333
