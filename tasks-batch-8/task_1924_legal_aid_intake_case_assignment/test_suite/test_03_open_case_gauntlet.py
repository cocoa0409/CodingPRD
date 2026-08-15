"""The open-case validation gauntlet: state gating, SoD, conflict gates,
duplicates, service-level permission, capacity pool, and grant gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_client,
    create_application,
    create_eligible_application,
    create_openable_application,
    screen_application,
    decide_application,
    conflict_check,
    open_case_from_application,
    create_grant_program,
    set_clock,
    make_intake_specialist_headers,
    make_supervising_attorney_headers,
    make_ethics_officer_headers,
)


class TestApplicationStateGate:
    def test_open_case_requires_application_eligible_state(self, api):
        """PRD §3.5: "Only a `SupervisingAttorney` may open a case, and only
        from an application in `ELIGIBLE`."
        PRD §2.7: "State-machine legality: the target entity must currently be
        in a from-state of the requested transition, else the request fails
        with the entity's invalid-state error — `ERR_INVALID_APPLICATION_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_REFERRAL_STATE`,
        `ERR_INVALID_GRANT_STATE`, or `ERR_INVALID_REPORT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/open_case_requires_application_eligible_state
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Dep")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord LLC")
        screen_application(app["id"], intake["id"])  # computed ELIGIBLE but undecided
        conflict_check(app["id"], intake["id"], result="CLEAR")

        bad = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                            make_supervising_attorney_headers(sup["id"]))
        validate_error(bad, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

        decide_application(app["id"], "ELIGIBLE", intake["id"])
        good = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        case = validate_success(good, expected_status=201)
        assert case["application_id"] == app["id"]

    def test_open_case_from_waitlisted_state_rejected(self, api):
        """PRD §3.5: "Only a `SupervisingAttorney` may open a case, and only
        from an application in `ELIGIBLE`."
        PRD §3.2: "`OPENED` and `WITHDRAWN` are terminal, and any attempted
        transition from a state that is not a from-state of the requested
        action is rejected with `ERR_INVALID_APPLICATION_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/open_case_requires_application_eligible_state
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli WL2")
        app = create_eligible_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE",
                                          opposing_party_name="Landlord LLC")
        conflict_check(app["id"], intake["id"], result="CLEAR")
        validate_success(api.enqueue_waitlist(
            app["id"], make_intake_specialist_headers(intake["id"])))
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

    def test_open_case_state_error_beats_grant_fiscal_error(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed cascade of
        checks, and the first failing check determines the rejection — later
        checks are not consulted."
        PRD §2.7: "State-machine legality: the target entity must currently be
        in a from-state of the requested transition, else the request fails
        with the entity's invalid-state error — `ERR_INVALID_APPLICATION_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_REFERRAL_STATE`,
        `ERR_INVALID_GRANT_STATE`, or `ERR_INVALID_REPORT_STATE`."
        PRD §2.7: "Fiscal checks: the extended-capacity pool
        (`ERR_NO_EXTENDED_CAPACITY`), caseload ceilings
        (`ERR_CASELOAD_CAPACITY_EXCEEDED`), grant budget sufficiency
        (`ERR_GRANT_BUDGET_EXHAUSTED`), panel capacity
        (`ERR_PANEL_CAPACITY_REACHED`), and reservation drain at grant close
        (`ERR_GRANT_HAS_RESERVED_FUNDS`)."

        Design: Difficulty/priority_pair_validation_conflict/open_case_state_error_beats_grant_fiscal_error
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        grant = create_grant_program(name="Tiny", allowed_case_types=["EVICTION_DEFENSE"],
                                     income_cap_percentage=200.00, total_budget_cents=1)
        client = create_client(intake["id"], full_name="Cli Rich",
                               annual_gross_income_cents=2_000_000)
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord LLC")
        screen_application(app["id"], intake["id"])
        decide_application(app["id"], "INELIGIBLE", intake["id"])

        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY",
                                         "grant_program_id": grant["id"]},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        g = validate_success(api.get_grant_program(grant["id"],
                                                   make_supervising_attorney_headers(sup["id"])))
        assert g["reserved_cents"] == 0

    def test_open_case_state_error_beats_fiscal_on_submitted_application(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed cascade of
        checks, and the first failing check determines the rejection — later
        checks are not consulted."
        PRD §2.7: "State-machine legality: the target entity must currently be
        in a from-state of the requested transition, else the request fails
        with the entity's invalid-state error — `ERR_INVALID_APPLICATION_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_REFERRAL_STATE`,
        `ERR_INVALID_GRANT_STATE`, or `ERR_INVALID_REPORT_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/open_case_state_error_beats_grant_fiscal_error
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        grant = create_grant_program(name="Tiny2", allowed_case_types=["EVICTION_DEFENSE"],
                                     income_cap_percentage=200.00, total_budget_cents=1)
        client = create_client(intake["id"], full_name="Cli Sub")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord LLC")
        # application still SUBMITTED (never screened): state gate fails; grant
        # budget of 1 cent would fail the fiscal gate too if it were reached
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY",
                                         "grant_program_id": grant["id"]},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)


class TestConflictGates:
    def test_open_case_safety_error_beats_duplicate_constraint_error(self, api):
        """PRD §3.5: "Before anything is created, the request runs a gauntlet
        whose order is pinned; the first failure wins:"
        PRD §3.5: "Conflict resolution: the application's latest conflict
        check — the one with the greatest `created_at` — must exist and hold
        a `result` of `CLEAR` or `WAIVED`. A missing check, a
        `POTENTIAL_CONFLICT`, or a `CONFIRMED_CONFLICT` is rejected with
        `ERR_CONFLICT_UNRESOLVED` (HTTP 409)."
        PRD §3.5: "Duplicates: no other case may exist for the same client
        and the same `case_type` in `PENDING_ASSIGNMENT`, `OPEN`, or
        `ON_HOLD`, else `ERR_DUPLICATE_OPEN_CASE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/open_case_safety_error_beats_duplicate_constraint_error
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Dup")
        app1 = create_openable_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord LLC")
        open_case_from_application(app1["id"], sup["id"])  # PENDING_ASSIGNMENT
        app2 = create_eligible_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord LLC")
        conflict_check(app2["id"], intake["id"], result="POTENTIAL_CONFLICT",
                       notes="opposing party is a former client")

        resp = api.open_case(app2["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFLICT_UNRESOLVED)
        cases, meta = validate_paginated(
            api.list_cases(make_supervising_attorney_headers(sup["id"]),
                           params={"application_id": app2["id"]})
        )
        assert meta["total_count"] == 0

    def test_open_case_confirmed_conflict_also_blocked_by_safety_gate(self, api):
        """PRD §3.5: "Before anything is created, the request runs a gauntlet
        whose order is pinned; the first failure wins:"
        PRD §3.5: "Conflict resolution: the application's latest conflict
        check — the one with the greatest `created_at` — must exist and hold
        a `result` of `CLEAR` or `WAIVED`. A missing check, a
        `POTENTIAL_CONFLICT`, or a `CONFIRMED_CONFLICT` is rejected with
        `ERR_CONFLICT_UNRESOLVED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/open_case_safety_error_beats_duplicate_constraint_error
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        ethics = create_attorney(full_name="Ethics Eve", max_units=10)
        client = create_client(intake["id"], full_name="Cli Dup3")
        # first case open for the same client + case_type -> duplicate gate armed
        app1 = create_openable_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord LLC")
        open_case_from_application(app1["id"], sup["id"])
        app2 = create_eligible_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord LLC")
        cc = conflict_check(app2["id"], intake["id"], result="POTENTIAL_CONFLICT")
        validate_success(api.resolve_conflict_check(
            cc["id"], {"resolution": "CONFIRMED_CONFLICT"},
            make_ethics_officer_headers(ethics["id"])))
        resp = api.open_case(app2["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFLICT_UNRESOLVED)

    def test_state_error_precedes_safety_error(self, api):
        """PRD §3.5: "Only a `SupervisingAttorney` may open a case, and only
        from an application in `ELIGIBLE`."
        PRD §2.7: "Every request is evaluated against a fixed cascade of
        checks, and the first failing check determines the rejection — later
        checks are not consulted."

        Design: Corner/validations/state_error_precedes_safety_error
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Ord")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        screen_application(app["id"], intake["id"])  # SCREENED, no conflict check
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

    def test_open_case_with_stale_conflict_check_rejected(self, api):
        """PRD §3.5: "Conflict recency: that latest check's `valid_until` must
        not lie in the past relative to the logical clock; a stale clearance
        is rejected with `ERR_CONFLICT_CHECK_STALE` (HTTP 409)."
        PRD §3.3: "Every check is born with a validity window: `valid_until`
        is exactly 45 days after `checked_at`."

        Design: Corner/validations/open_case_with_stale_conflict_check_rejected
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Stale")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE",
                                          opposing_party_name="Landlord")
        # check born at default clock 2026-08-01 -> valid_until 2026-09-15
        set_clock("2026-09-16T00:00:00Z")
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFLICT_CHECK_STALE)


class TestSelfScreeningSoD:
    def test_self_screening_approval_sod_rejected(self, api):
        """PRD §3.5: "Self-screening segregation: the acting attorney's
        `X-User-ID` must differ from the application's `screened_by_staff_id`,
        else the request is rejected with `ERR_SELF_SCREENING_APPROVAL`
        (HTTP 403)."

        Design: Corner/validations/self_screening_approval_sod_rejected
        """
        create_venue_rule()
        sup1 = create_supervisor(full_name="Sup Screen")
        sup2 = create_supervisor(full_name="Sup Other")
        # sup1 acts as the intake specialist identity who screens
        client = create_client(sup1["id"], full_name="Cli SoD2")
        app = create_application(sup1["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        screen_application(app["id"], sup1["id"])
        decide_application(app["id"], "ELIGIBLE", sup1["id"])
        conflict_check(app["id"], sup1["id"], result="CLEAR")

        bad = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                            make_supervising_attorney_headers(sup1["id"]))
        validate_error(bad, ApiErrorId.ERR_SELF_SCREENING_APPROVAL)
        good = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup2["id"]))
        validate_success(good, expected_status=201)


class TestDuplicateAndServiceLevel:
    def test_duplicate_open_case_rejected(self, api):
        """PRD §3.5: "Duplicates: no other case may exist for the same client
        and the same `case_type` in `PENDING_ASSIGNMENT`, `OPEN`, or `ON_HOLD`,
        else `ERR_DUPLICATE_OPEN_CASE` (HTTP 409)."

        Design: Corner/validations/duplicate_open_case_rejected
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Dup2")
        app1 = create_openable_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord")
        open_case_from_application(app1["id"], sup["id"])
        app2 = create_openable_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord")
        resp = api.open_case(app2["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CASE)

    def test_extended_gate_low_priority_rejected(self, api):
        """PRD §3.5: "Service-level permission: the gate reads the
        application's stored `priority_score` — it does not recompute it. An
        `EXTENDED` request requires that score to be at least 60.00, with
        60.00 itself qualifying, and requires the matching venue rule's
        `extended_eligible` to be true; otherwise the request fails with
        `ERR_EXTENDED_REP_NOT_PERMITTED` (HTTP 422)."

        Design: Corner/validations/extended_gate_low_priority_rejected
        """
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["BENEFITS_APPEAL"])
        sup = create_supervisor(practice_areas=["BENEFITS_APPEAL"])
        client = create_client(intake["id"], full_name="Cli Gate")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="BENEFITS_APPEAL",
                                          opposing_party_name="Agency")
        # priority 50.00 < 60.00 and extended_eligible false
        resp = api.open_case(app["id"], {"service_level": "EXTENDED"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_EXTENDED_REP_NOT_PERMITTED)


class TestExtendedCapacityPool:
    def test_service_level_gate_pinned_evaluation_order(self, api):
        """PRD §3.5: "Extended-capacity pool: computed from pre-opening state,
        since the case being opened contributes nothing yet — the pool is the
        sum of `available_units` across staff members whose `staff_type` is
        `ATTORNEY` and whose `status` is `ACTIVE`. An `EXTENDED` request
        requires at least one such attorney with `available_units` of at least
        5, else `ERR_NO_EXTENDED_CAPACITY` (HTTP 409). `ADVICE_ONLY` imposes
        no pool check at open time; the assignment-time ceiling in §3.6 still
        applies later."

        Design: Difficulty/combinatorial_formula/service_level_gate_pinned_evaluation_order
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor(max_units=4)  # supervisor's own capacity < 5
        att_full = create_attorney(full_name="Att Full", max_units=5)
        headers_sup = make_supervising_attorney_headers(sup["id"])
        # Load att_full completely with one EXTENDED case (5 units on max 5)
        c1 = create_client(intake["id"], full_name="Cli One")
        app1 = create_openable_application(intake["id"], c1["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord A")
        case1 = open_case_from_application(app1["id"], sup["id"], service_level="EXTENDED")
        validate_success(api.assign_case(
            case1["id"], {"attorney_id": att_full["id"],
                          "expected_case_version": case1["version"]}, headers_sup))

        c2 = create_client(intake["id"], full_name="Cli Two")
        app2 = create_openable_application(intake["id"], c2["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord B")
        # priority 70.00 passes gates (1)-(2); pool exhausted for EXTENDED
        bad = api.open_case(app2["id"], {"service_level": "EXTENDED"}, headers_sup)
        validate_error(bad, ApiErrorId.ERR_NO_EXTENDED_CAPACITY)
        still = validate_success(api.get_application(
            app2["id"], make_intake_specialist_headers(intake["id"])))
        assert still["status"] == "ELIGIBLE"
        # ADVICE_ONLY on the SAME application succeeds — pool check is EXTENDED-scoped
        good = api.open_case(app2["id"], {"service_level": "ADVICE_ONLY"}, headers_sup)
        case2 = validate_success(good, expected_status=201)
        assert case2["service_level"] == "ADVICE_ONLY"

    def test_extended_open_succeeds_with_available_capacity(self, api):
        """PRD §3.5: "An `EXTENDED` request requires at least one such attorney
        with `available_units` of at least 5, else `ERR_NO_EXTENDED_CAPACITY`
        (HTTP 409)."

        Design: Difficulty/combinatorial_formula/service_level_gate_pinned_evaluation_order
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"])
        create_attorney(full_name="Att Free", practice_areas=["FAMILY_DV"], max_units=10)
        client = create_client(intake["id"], full_name="Cli OK", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        resp = api.open_case(app["id"], {"service_level": "EXTENDED"},
                             make_supervising_attorney_headers(sup["id"]))
        case = validate_success(resp, expected_status=201)
        assert case["service_level"] == "EXTENDED"
        assert case["case_weight"] == 5

    def test_extended_gate_uses_stored_priority_not_recompute(self, api):
        """PRD §3.5: "Service-level permission: the gate reads the
        application's stored `priority_score` — it does not recompute it. An
        `EXTENDED` request requires that score to be at least 60.00, with
        60.00 itself qualifying, and requires the matching venue rule's
        `extended_eligible` to be true; otherwise the request fails with
        `ERR_EXTENDED_REP_NOT_PERMITTED` (HTTP 422)."
        PRD §3.5: "Extended-capacity pool: computed from pre-opening state,
        since the case being opened contributes nothing yet — the pool is the
        sum of `available_units` across staff members whose `staff_type` is
        `ATTORNEY` and whose `status` is `ACTIVE`."

        Design: Difficulty/combinatorial_formula/service_level_gate_pinned_evaluation_order
        """
        # base 60 + urgency 20 = 80.00 >= 60.00 and extended_eligible true;
        # an idle attorney guarantees the pool check passes
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"])
        create_attorney(full_name="Att Pool", practice_areas=["FAMILY_DV"], max_units=5)
        client = create_client(intake["id"], full_name="Cli Stored", household_size=1)
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        # stored priority: 60 * 1.00 + 20 = 80.00
        resp = api.open_case(app["id"], {"service_level": "EXTENDED"},
                             make_supervising_attorney_headers(sup["id"]))
        case = validate_success(resp, expected_status=201)
        assert case["status"] == "PENDING_ASSIGNMENT"
        assert case["service_level"] == "EXTENDED"


class TestGrantGates:
    def test_grant_period_inactive_rejected(self, api):
        """PRD §3.5: "Grant gates, evaluated only when a `grant_program_id`
        was supplied: the logical clock's date must fall within the program's
        closed interval from `period_start` through `period_end`, both ends
        inclusive, else `ERR_GRANT_PERIOD_INACTIVE` (HTTP 409);"

        Design: Corner/validations/grant_period_inactive_rejected
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        grant = create_grant_program(name="June Fund", period_start="2026-06-01",
                                     period_end="2026-06-30")
        client = create_client(intake["id"], full_name="Cli Per")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        # default clock 2026-08-01 lies outside [2026-06-01, 2026-06-30]
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY",
                                         "grant_program_id": grant["id"]},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_GRANT_PERIOD_INACTIVE)

    def test_grant_coverage_exclusions_rejected(self, api):
        """PRD §3.5: "the application's `case_type` must appear in the
        program's `allowed_case_types`, else `ERR_GRANT_CASE_TYPE_EXCLUDED`
        (HTTP 422); the application's `incident_county` must appear in
        `allowed_counties`, else `ERR_GRANT_COUNTY_EXCLUDED` (HTTP 422);"

        Design: Corner/validations/grant_coverage_exclusions_rejected
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["EVICTION_DEFENSE"])
        sup = create_supervisor()
        grant = create_grant_program(name="CountyB Benefits",
                                     allowed_case_types=["BENEFITS_APPEAL"],
                                     allowed_counties=["CountyB"])
        client = create_client(intake["id"], full_name="Cli Cov")
        app1 = create_openable_application(intake["id"], client["id"],
                                           case_type="EVICTION_DEFENSE",
                                           opposing_party_name="Landlord")
        app2 = create_openable_application(intake["id"], client["id"],
                                           case_type="BENEFITS_APPEAL",
                                           opposing_party_name="Agency")
        headers_sup = make_supervising_attorney_headers(sup["id"])
        r1 = api.open_case(app1["id"], {"service_level": "ADVICE_ONLY",
                                        "grant_program_id": grant["id"]}, headers_sup)
        validate_error(r1, ApiErrorId.ERR_GRANT_CASE_TYPE_EXCLUDED)
        r2 = api.open_case(app2["id"], {"service_level": "ADVICE_ONLY",
                                        "grant_program_id": grant["id"]}, headers_sup)
        validate_error(r2, ApiErrorId.ERR_GRANT_COUNTY_EXCLUDED)

    def test_grant_income_over_cap_uses_countable_variant(self, api):
        """PRD §3.5: "the application's `countable_poverty_percentage` — the
        grant-screen variant, with no benefits auto-pass — must be at most the
        program's `income_cap_percentage`, else `ERR_GRANT_INCOME_OVER_CAP`
        (HTTP 422);"

        Design: Corner/validations/grant_income_over_cap_uses_countable_variant
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        grant = create_grant_program(name="Strict Cap", income_cap_percentage=60.00)
        client = create_client(intake["id"], full_name="Cli Cap",
                               annual_gross_income_cents=1_000_000,
                               annual_countable_income_cents=1_000_000)
        app = create_application(intake["id"], client["id"], case_type="CONSUMER_DEBT",
                                 opposing_party_name="Collector")
        screened = screen_application(app["id"], intake["id"])
        assert screened["countable_poverty_percentage"] == pytest.approx(66.40, abs=0.001)
        decide_application(app["id"], "ELIGIBLE", intake["id"])
        conflict_check(app["id"], intake["id"], result="CLEAR")
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY",
                                         "grant_program_id": grant["id"]},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_GRANT_INCOME_OVER_CAP)

    def test_grant_budget_exhausted_rejected(self, api):
        """PRD §3.5: "and the program's `available_cents` must cover this
        case's reservation, else `ERR_GRANT_BUDGET_EXHAUSTED` (HTTP 409)."

        Design: Corner/validations/grant_budget_exhausted_rejected
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        grant = create_grant_program(name="Nearly Empty", total_budget_cents=13_332)
        client = create_client(intake["id"], full_name="Cli Bud")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY",
                                         "grant_program_id": grant["id"]},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_GRANT_BUDGET_EXHAUSTED)
