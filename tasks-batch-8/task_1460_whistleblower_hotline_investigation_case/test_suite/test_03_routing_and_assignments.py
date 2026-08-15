"""Investigator routing, selector policy, override path, OCC, screening, waiver, activation."""
from test_helpers import (
    ApiErrorId,
    activate_assignment,
    create_assignment_payload,
    create_case,
    create_staff,
    create_triage_payload,
    get_case,
    make_intake_headers,
    make_investigator_headers,
    make_officer_headers,
    propose_assignment_auto,
    propose_assignment_override,
    screen_clear,
    setup_case_triaged,
    setup_standard_staff,
    setup_case_assigned,
    triage_case,
    validate_error,
    validate_success,
    get_success_data,
    api_client,
)


class TestSelectorWeightedVsCount:
    """Difficulty: routing_workload_count_vs_weighted_selector (2 tests)."""

    def _setup_pool(self, api):
        """invA: 1 ACTIVE CRITICAL (weighted 8, count 1); invB: 3 ACTIVE LOW (weighted 3, count 3).

        NOTE: builds intake/officer pair only — no third INVESTIGATION staff — so
        the auto-selector pool is exactly {invA, invB}.
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        staff = {
            "s_int": s_int, "s_off": s_off,
            "h_int": make_intake_headers(s_int["id"]),
            "h_off": make_officer_headers(s_off["id"]),
        }
        invA = create_staff("Alice A", "a@corp.example", ["INVESTIGATION"], max_active_cases=5)
        invB = create_staff("Bob B", "b@corp.example", ["INVESTIGATION"], max_active_cases=5)

        # invA gets one CRITICAL case (FRAUD/EXECUTIVE/HIGH_1M/NONE = 75 -> CRITICAL)
        ca, _ = create_case(description="Allegation of expense fraud in Q2")
        ca_t = triage_case(ca["id"], staff["h_int"], confirmed_category="FRAUD",
                           subject_seniority="EXECUTIVE", financial_exposure_band="HIGH_1M")
        a_a = propose_assignment_override(ca["id"], ca_t["version"], invA["id"], staff["h_off"],
                                          reason="Language coverage")
        screen_clear(a_a["id"], staff["h_int"])
        activate_assignment(a_a["id"], staff["h_off"])

        # invB gets three LOW cases (OTHER/STAFF/NONE/NONE = 15 -> LOW)
        for i, ch in enumerate(["PHONE", "EMAIL", "MAIL"]):
            cb, _ = create_case(channel=ch, category="OTHER",
                                description=f"Allegation of minor policy lapse number {i}",
                                region=["EAST", "EAST", "WEST"][i])
            cb_t = triage_case(cb["id"], staff["h_int"], confirmed_category="OTHER")
            a_b = propose_assignment_override(cb["id"], cb_t["version"], invB["id"], staff["h_off"],
                                              reason="Rotation")
            screen_clear(a_b["id"], staff["h_int"])
            activate_assignment(a_b["id"], staff["h_off"])
        return staff, invA, invB

    def test_selector_picks_least_weighted_not_least_count(self, api):
        """PRD §3.4: "The eligible pool is ranked by `weighted_caseload` ascending,
        ties broken by `active_case_count` ascending". PRD §3.1: "a `CRITICAL` case
        weighs 8, `HIGH` weighs 4, `MEDIUM` weighs 2, and `LOW` weighs 1".

        Design: Difficulty/dual_variant_calc/routing_workload_count_vs_weighted_selector
        """
        staff, invA, invB = self._setup_pool(api)
        target, _ = create_case(description="Allegation of vendor kickback scheme", region="EAST")
        t_triaged = triage_case(target["id"], staff["h_int"], confirmed_category="FRAUD")
        resp = api.create_assignment(target["id"], {"expected_case_version": t_triaged["version"]},
                                     staff["h_int"])
        data = validate_success(resp, expected_status=201)
        # invA: count 1 < invB: count 3 — count ranking would pick invA
        # invA: weighted 8 > invB: weighted 3 — weighted ranking picks invB
        assert data["investigator_id"] == invB["id"], (
            "selector must rank by weighted_caseload (3 < 8), not active_case_count (1 < 3)"
        )
        assert data["selection_mode"] == "AUTO"

    def test_staff_counters_reflect_active_assignment_sets(self, api):
        """PRD §3.1: "`active_case_count` is the plain count of that person's
        assignments in `ACTIVE` status ... `weighted_caseload` sums a per-case
        severity weight over exactly the same set of active assignments".

        Design: Difficulty/dual_variant_calc/routing_workload_count_vs_weighted_selector
        """
        staff, invA, invB = self._setup_pool(api)
        resp_a = api.list_staff_members(staff["h_off"], params={"capability": "INVESTIGATION"})
        rows, _ = get_success_data(resp_a), None
        data_a = resp_a.json()["data"]
        by_id = {r["id"]: r for r in data_a}
        assert by_id[invA["id"]]["active_case_count"] == 1
        assert by_id[invA["id"]]["weighted_caseload"] == 8
        assert by_id[invB["id"]]["active_case_count"] == 3
        assert by_id[invB["id"]]["weighted_caseload"] == 3


class TestSelectorTieBreak:
    def test_earlier_registered_investigator_wins_tie(self, api):
        """PRD §3.4: "ties broken by `active_case_count` ascending, remaining ties
        broken by the staff member's `created_at` ascending, and the top-ranked
        member wins".

        Design: Corner/cross_cutting_layers/selector_tiebreak_created_at_order
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        s_old = create_staff("Olive Old", "old@corp.example", ["INVESTIGATION"])
        s_new = create_staff("Ned New", "new@corp.example", ["INVESTIGATION"])
        case, _ = create_case()
        triaged = triage_case(case["id"], make_intake_headers(s_int["id"]))
        resp = api.create_assignment(case["id"], {"expected_case_version": triaged["version"]},
                                     make_intake_headers(s_int["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["investigator_id"] == s_old["id"], (
            "equal weights (0) and counts (0) tie-break on created_at ASC — earlier staff wins"
        )


class TestEmptyPoolAndEligibility:
    def test_auto_route_empty_pool_rejected(self, api):
        """PRD §3.4: "An empty pool is rejected with `ERR_NO_ELIGIBLE_INVESTIGATOR`."

        Design: Corner/errors/auto_route_empty_pool_rejected
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        case, _ = create_case()
        triaged = triage_case(case["id"], make_intake_headers(s_int["id"]))
        resp = api.create_assignment(case["id"], {"expected_case_version": triaged["version"]},
                                     make_intake_headers(s_int["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INVESTIGATOR)
        after = get_case(case["id"], make_intake_headers(s_int["id"]))
        assert after["status"] == "TRIAGED"

    def test_assignment_create_on_received_case_rejected(self, api):
        """PRD §3.4: "A proposal in a case state other than `TRIAGED`, `REOPENED`,
        or the supersede-eligible form of `ASSIGNED` described below is rejected
        with `ERR_CASE_NOT_TRIAGED_OR_REOPENED`."

        Design: Corner/errors/assignment_create_on_received_case_rejected
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        create_staff("Ian Vest", "investigator@corp.example", ["INVESTIGATION"])
        case, _ = create_case()
        resp = api.create_assignment(case["id"], {"expected_case_version": case["version"]},
                                     make_intake_headers(s_int["id"]))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_TRIAGED_OR_REOPENED)


class TestOverridePath:
    def test_override_by_intake_returns_unauthorized(self, api):
        """PRD §3.4: "Both `IntakeSpecialist` and `ComplianceOfficer` callers may
        propose, but only a `ComplianceOfficer` may steer the proposal to a specific
        person." PRD §2.1: ERR_INSUFFICIENT_PERMISSIONS (HTTP 403).

        Design: Corner/validations/override_by_intake_returns_unauthorized
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        resp = api.create_assignment(
            ctx["case"]["id"],
            {"expected_case_version": ctx["case"]["version"],
             "investigator_id": staff["s_inv"]["id"], "override_reason": "Intake attempting override"},
            staff["h_int"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_override_subject_named_as_investigator_rejected(self, api):
        """PRD §3.4: "naming a person whose `email` or `display_name` appears in
        `subject_employee_ids` fails with `ERR_SUBJECT_NAMED_AS_INVESTIGATOR`".

        Design: Corner/errors/override_subject_named_as_investigator_rejected
        """
        staff = setup_standard_staff()
        case, _ = create_case(description="Allegation naming the investigator as subject",
                              subject_employee_ids=["investigator@corp.example"])
        triaged = triage_case(case["id"], staff["h_int"])
        resp = api.create_assignment(
            case["id"],
            {"expected_case_version": triaged["version"],
             "investigator_id": staff["s_inv"]["id"],
             "override_reason": "Attempt to assign named subject"},
            staff["h_off"],
        )
        validate_error(resp, ApiErrorId.ERR_SUBJECT_NAMED_AS_INVESTIGATOR)


class TestOCC:
    def test_second_proposal_with_stale_version_returns_412(self, api):
        """PRD §2.8: "if the supplied value does not match the case's current
        `version` ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_assignment_propose_stale_version_returns_412
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        v = ctx["case"]["version"]
        resp1 = api.create_assignment(ctx["case"]["id"], {"expected_case_version": v}, staff["h_int"])
        validate_success(resp1, expected_status=201)
        resp2 = api.create_assignment(ctx["case"]["id"], {"expected_case_version": v}, staff["h_int"])
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)

    def test_retry_with_fresh_version_succeeds(self, api):
        """PRD §2.8: "the payload must carry `expected_case_version` matching the
        case's current `version`". PRD §3.4: supersede path is legal while ASSIGNED
        with a non-terminal prior assignment.

        Design: Corner/validations/occ_assignment_propose_stale_version_returns_412
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        resp1 = api.create_assignment(ctx["case"]["id"],
                                      {"expected_case_version": ctx["case"]["version"]}, staff["h_int"])
        a1 = validate_success(resp1, expected_status=201)
        fresh = get_case(ctx["case"]["id"], staff["h_off"])
        resp2 = api.create_assignment(ctx["case"]["id"],
                                      {"expected_case_version": fresh["version"]}, staff["h_int"])
        a2 = validate_success(resp2, expected_status=201)
        assert a2["id"] != a1["id"]
        # prior assignment superseded
        resp_list = api.list_assignments(ctx["case"]["id"], staff["h_off"])
        rows = resp_list.json()["data"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[a1["id"]]["status"] == "SUPERSEDED"
        assert by_id[a2["id"]]["status"] == "PROPOSED"


class TestScreeningAndWaiver:
    def test_conflict_found_requires_waiver_then_clears(self, api):
        """PRD §3.4: "An outcome of `CONFLICT_FOUND` moves it to `CONFLICT_PENDING`"
        and "A `ComplianceOfficer` may waive it, moving the assignment from
        `CONFLICT_PENDING` to `CLEARED`".

        Design: Corner/state_machines/conflict_screening_waiver_fork
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_override(ctx["case"]["id"], ctx["case"]["version"],
                                         staff["s_inv"]["id"], staff["h_off"])
        resp = api.screen_assignment(a1["id"], {"outcome": "CONFLICT_FOUND",
                                                "conflict_type": "PERSONAL_RELATIONSHIP",
                                                "notes": "College roommate of subject"},
                                     staff["h_int"])
        scr = validate_success(resp)
        assert scr["status"] == "CONFLICT_PENDING"
        assert scr["conflict_type"] == "PERSONAL_RELATIONSHIP"
        resp2 = api.waive_assignment(a1["id"],
                                     {"waiver_justification": "Conflict is remote and documented; monitoring added."},
                                     staff["h_off2"])
        wav = validate_success(resp2)
        assert wav["status"] == "CLEARED"
        assert wav["waived_by_id"] == staff["s_off2"]["id"]

    def test_waived_assignment_can_activate(self, api):
        """PRD §3.4: "Activation, by a `ComplianceOfficer`, turns a `CLEARED`
        assignment into the working assignment" and "the case moves to
        `UNDER_INVESTIGATION`".

        Design: Corner/state_machines/conflict_screening_waiver_fork
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_override(ctx["case"]["id"], ctx["case"]["version"],
                                         staff["s_inv"]["id"], staff["h_off"])
        api.screen_assignment(a1["id"], {"outcome": "CONFLICT_FOUND",
                                         "conflict_type": "PERSONAL_RELATIONSHIP"},
                              staff["h_int"])
        api.waive_assignment(a1["id"],
                             {"waiver_justification": "Conflict is remote and documented; monitoring added."},
                             staff["h_off2"])
        resp = api.activate_assignment(a1["id"], staff["h_off"])
        act = validate_success(resp)
        assert act["status"] == "ACTIVE"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "UNDER_INVESTIGATION"

    def test_self_screen_rejected(self, api):
        """PRD §3.4: "performed by an `IntakeSpecialist` or `ComplianceOfficer` other
        than the candidate (self-screening fails with `ERR_SOD_SELF_SCREEN`)".

        Design: Corner/state_machines/screen_by_candidate_returns_sod_self_screen
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_override(ctx["case"]["id"], ctx["case"]["version"],
                                         staff["s_inv"]["id"], staff["h_off"])
        resp = api.screen_assignment(a1["id"], {"outcome": "CLEAR"},
                                     make_investigator_headers(staff["s_inv"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_SCREEN)

    def test_waiver_by_screening_officer_rejected(self, api):
        """PRD §2.6 rule 3: "The officer waiving a conflict must differ from both the
        screener who found it and the candidate investigator: `ERR_SOD_SELF_WAIVER`."

        Design: Corner/state_machines/waive_by_screening_officer_returns_sod_self_waiver
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_override(ctx["case"]["id"], ctx["case"]["version"],
                                         staff["s_inv"]["id"], staff["h_off"])
        # off1 screens with CONFLICT_FOUND
        api.screen_assignment(a1["id"], {"outcome": "CONFLICT_FOUND",
                                         "conflict_type": "FINANCIAL_INTEREST",
                                         "notes": "Holds vendor stock"},
                              staff["h_off"])
        # off1 attempts to waive own finding
        resp = api.waive_assignment(a1["id"],
                                    {"waiver_justification": "Attempting to waive my own finding."},
                                    staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_WAIVER)

    def test_activate_proposed_rejected(self, api):
        """PRD §3.4: "activating from any other state fails with
        `ERR_ASSIGNMENT_NOT_CLEARED`".

        Design: Corner/errors/activate_proposed_assignment_rejected
        """
        ctx = setup_case_assigned()
        staff = ctx["staff"]
        resp = api.activate_assignment(ctx["assignment"]["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CLEARED)

    def test_waive_proposed_rejected(self, api):
        """PRD §3.4: "waiving an assignment in any other state fails with
        `ERR_ASSIGNMENT_NOT_CONFLICT_PENDING`".

        Design: Corner/errors/waive_proposed_assignment_rejected
        """
        ctx = setup_case_assigned()
        staff = ctx["staff"]
        resp = api.waive_assignment(ctx["assignment"]["id"],
                                    {"waiver_justification": "Nothing to waive yet, premature action."},
                                    staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFLICT_PENDING)

    def test_release_superseded_rejected(self, api):
        """PRD §3.4: "Releasing an assignment already in a terminal state (`RELEASED`
        or `SUPERSEDED`) fails with `ERR_ASSIGNMENT_NOT_RELEASABLE`."

        Design: Corner/errors/release_superseded_assignment_rejected
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_auto(ctx["case"]["id"], ctx["case"]["version"], staff["h_int"])
        fresh = get_case(ctx["case"]["id"], staff["h_off"])
        propose_assignment_auto(ctx["case"]["id"], fresh["version"], staff["h_int"])
        resp = api.release_assignment(a1["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_RELEASABLE)


class TestCapacityBoundary:
    """Difficulty: capacity_boundary_at_max (2 tests)."""

    def _setup_at_capacity(self, api):
        staff = setup_standard_staff()
        inv = create_staff("Solo Vest", "solo@corp.example", ["INVESTIGATION"], max_active_cases=1)
        c1, _ = create_case(description="Allegation of expense fraud in Q2")
        c1_t = triage_case(c1["id"], staff["h_int"])
        a1 = propose_assignment_override(c1["id"], c1_t["version"], inv["id"], staff["h_off"],
                                         reason="Only investigator")
        screen_clear(a1["id"], staff["h_int"])
        activate_assignment(a1["id"], staff["h_off"])
        return staff, inv

    def test_activate_at_max_capacity_rejected(self, api):
        """PRD §3.4: "the candidate's `active_case_count` must currently be below
        their `max_active_cases`, otherwise the activation fails with
        `ERR_INVESTIGATOR_CAPACITY_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/capacity_boundary_at_max
        """
        staff, inv = self._setup_at_capacity(api)
        c2, _ = create_case(channel="EMAIL", category="SAFETY",
                            description="Allegation of unsafe warehouse practice", region="SOUTH")
        c2_t = triage_case(c2["id"], staff["h_int"], confirmed_category="SAFETY")
        a2 = propose_assignment_override(c2["id"], c2_t["version"], inv["id"], staff["h_off"],
                                         reason="Override despite load")
        screen_clear(a2["id"], staff["h_int"])
        resp = api.activate_assignment(a2["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_CAPACITY_EXCEEDED)

    def test_rejected_activation_leaves_state_unchanged(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it" — the rejected activate changes nothing.

        Design: Difficulty/boundary_precision_check/capacity_boundary_at_max
        """
        staff, inv = self._setup_at_capacity(api)
        c2, _ = create_case(channel="EMAIL", category="SAFETY",
                            description="Allegation of unsafe warehouse practice", region="SOUTH")
        c2_t = triage_case(c2["id"], staff["h_int"], confirmed_category="SAFETY")
        a2 = propose_assignment_override(c2["id"], c2_t["version"], inv["id"], staff["h_off"],
                                         reason="Override despite load")
        screen_clear(a2["id"], staff["h_int"])
        api.activate_assignment(a2["id"], staff["h_off"])  # rejected
        rows = api.list_staff_members(staff["h_off"], params={"capability": "INVESTIGATION"}).json()["data"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[inv["id"]]["active_case_count"] == 1
        asg_rows = api.list_assignments(c2["id"], staff["h_off"]).json()["data"]
        assert by_id and asg_rows[0]["status"] == "CLEARED"


class TestExistenceBeforeState:
    def test_screen_nonexistent_assignment_404(self, api):
        """PRD §2.11: "Fifth, path resource existence, validated left to right along
        the URL hierarchy (`ERR_NOT_FOUND`)." This precedes "Eighth, target-entity
        state preconditions".

        Design: Corner/validations/existence_before_state_on_screen
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        resp = api.screen_assignment("11111111-1111-1111-1111-111111111111",
                                     {"outcome": "CLEAR"}, make_officer_headers(s_off["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
