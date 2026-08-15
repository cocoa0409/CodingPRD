"""Phase packages: submission fees, the zero-ready boundary, error precedence
on the evaluation ladder, segregation of duties, withdrawal refunds, and the
optimistic/conservative level projections (PRD §3.4, §3.5, §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    begin_review,
    build_user_headers,
    create_attempt,
    create_credit_entry,
    create_members,
    create_project,
    drive_attempt_ready,
    get_attempt,
    get_project,
    get_success_data,
    lock_strategy,
    make_project_administrator_headers,
    post_comment,
    setup_submitted_design_package,
    submit_phase,
    validate_error,
    validate_success,
    withdraw_phase,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


def _prereq_entry(points=0):
    return create_credit_entry(
        credit_code="EAp1", title="Fundamental Commissioning",
        category="ENERGY_ATMOSPHERE", points_possible=points,
        is_prerequisite=True, phase_eligibility="BOTH", requires_energy_model=False)


def _locked_project_with_attempt(api, project_name="Tower", budget=5000000,
                                 entry_points=0, ready=True):
    """Project + prerequisite attempt + strategy locked; the attempt is driven
    to READY_FOR_SUBMITTAL unless ready=False (left in SELECTED)."""
    members = create_members()
    entry = _prereq_entry(points=entry_points)
    project = create_project(
        members["admin"]["id"], project_name=project_name, fee_budget_cents=budget)
    attempt = create_attempt(
        project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
    lock_strategy(project["id"], members["admin"]["id"])
    if ready:
        drive_attempt_ready(attempt["id"], members["spec"]["id"], members["admin"]["id"])
    return members, entry, project, attempt


class TestEmptyPackageBoundary:
    def test_submit_phase_with_zero_ready_attempts_rejected(self, api):
        """PRD §3.4: "A package containing zero ready attempts is rejected with `ERR_EMPTY_SUBMISSION_PACKAGE` (HTTP 422); the zero-count boundary is enforced."

        Design: Difficulty/boundary_precision_check/empty_submission_package_zero_ready
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="Tower L", ready=False)
        resp = api.submit_phase(
            project["id"], "DESIGN",
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EMPTY_SUBMISSION_PACKAGE)

        after = get_project(project["id"])
        assert after["status"] == "STRATEGY_LOCKED"
        assert after["fee_balance_cents"] == 5000000, "no fee may be debited"

    def test_submit_phase_with_one_ready_attempt_passes(self, api):
        """PRD §3.4: "A package containing zero ready attempts is rejected with `ERR_EMPTY_SUBMISSION_PACKAGE` (HTTP 422); the zero-count boundary is enforced."
        PRD §3.4: "On success, every included attempt transitions `READY_FOR_SUBMITTAL → SUBMITTED` with its `submission_round` incremented by one, the fee is debited, the projected and conservative levels are recomputed against the new input set, and the project's `version` increments by one."

        Design: Difficulty/boundary_precision_check/empty_submission_package_zero_ready
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="Tower L2", ready=True)
        submitted = validate_success(
            api.submit_phase(
                project["id"], "DESIGN",
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert submitted["status"] == "DESIGN_SUBMITTED"
        assert submitted["fee_balance_cents"] == 4150000, (
            "5000000 - (250000 + 5000*ceil(120000/1000)) = 5000000 - 850000")
        after = get_attempt(attempt["id"])
        assert after["status"] == "SUBMITTED"
        assert after["submission_round"] == 1


class TestErrorPrecedenceOnSubmit:
    def test_state_error_precedes_fiscal_error(self, api):
        """PRD §2.7: "When a request violates several rules at once, the returned error is the one belonging to the earliest stage of a fixed evaluation ladder:"
        PRD §2.7: "7. State validity — the target resource must be in a from-state the requested transition allows, and the creation-time parent-state gates apply at this stage as well; violations yield the `ERR_INVALID_PROJECT_STATE` / `ERR_INVALID_CREDIT_ATTEMPT_STATE` / `ERR_INVALID_MODEL_STATE` / `ERR_INVALID_COMMENT_STATE` / `ERR_INVALID_TASK_STATE` / `ERR_INVALID_INCENTIVE_STATE` / `ERR_INVALID_REPORT_STATE` family (HTTP 409)."
        PRD §2.7: "11. Fiscal gates — submission funds and certification-gated incentive money (HTTP 402, 409, or 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_submit_phase
        """
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="Tower I", fee_budget_cents=100000)
        resp = api.submit_phase(
            project["id"], "DESIGN",
            make_project_administrator_headers(members["admin"]["id"]))
        # Both the from-state (REGISTERED) and the funds (100000 < 850000) fail;
        # the state stage of the ladder is earlier, so the state error answers.
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATE)
        assert resp.json()["data"]["error_id"] != "ERR_INSUFFICIENT_SUBMISSION_FUNDS"
        assert get_project(project["id"])["status"] == "REGISTERED"

    def test_state_error_isolated_when_funds_sufficient(self, api):
        """PRD §2.7: "7. State validity — the target resource must be in a from-state the requested transition allows, and the creation-time parent-state gates apply at this stage as well; violations yield the `ERR_INVALID_PROJECT_STATE` / `ERR_INVALID_CREDIT_ATTEMPT_STATE` / `ERR_INVALID_MODEL_STATE` / `ERR_INVALID_COMMENT_STATE` / `ERR_INVALID_TASK_STATE` / `ERR_INVALID_INCENTIVE_STATE` / `ERR_INVALID_REPORT_STATE` family (HTTP 409)."
        PRD §3.4: "Design submission moves the project `STRATEGY_LOCKED → DESIGN_SUBMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_submit_phase
        """
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="Tower I2", fee_budget_cents=5000000)
        resp = api.submit_phase(
            project["id"], "DESIGN",
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATE)
        assert get_project(project["id"])["status"] == "REGISTERED"

    def test_submit_phase_with_insufficient_funds_blocked(self, api):
        """PRD §3.4: "Submission debits the fee from `fee_balance_cents`, and when the balance does not cover it the submission fails with `ERR_INSUFFICIENT_SUBMISSION_FUNDS` (HTTP 402)."

        Design: Corner/validations/insufficient_submission_funds_blocked
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="Broke Tower", budget=100000, ready=True)
        resp = api.submit_phase(
            project["id"], "DESIGN",
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUBMISSION_FUNDS)
        after = get_project(project["id"])
        assert after["status"] == "STRATEGY_LOCKED"
        assert after["fee_balance_cents"] == 100000


class TestSegregationOfDuties:
    def test_documentation_owner_cannot_submit_own_package(self, api):
        """PRD §3.4: "And segregation of duties forbids the submitter from vouching for their own paperwork: if the calling administrator is the `documentation_owner_id` of any attempt included in the package, the submission is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/segregation_owner_submit_phase_blocked
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="SoD Tower", ready=True)
        # The caller acts in the ProjectAdministrator role but IS the
        # documentation owner of the included attempt.
        resp = api.submit_phase(
            project["id"], "DESIGN",
            build_user_headers(members["spec"]["id"], "ProjectAdministrator"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        after = get_project(project["id"])
        assert after["status"] == "STRATEGY_LOCKED"
        assert after["fee_balance_cents"] == 5000000


class TestWithdrawal:
    def test_withdraw_after_review_started_blocked(self, api):
        """PRD §3.4: "If any review comment exists on any `SUBMITTED` attempt of that phase, withdrawal is rejected with `ERR_REVIEW_ALREADY_STARTED` (HTTP 409)."

        Design: Corner/validations/withdraw_after_review_started_blocked
        """
        ctx = setup_submitted_design_package(
            [{"code": "EAp1", "points": 0, "is_prerequisite": True,
              "phase_eligibility": "BOTH"}],
            project_overrides={"project_name": "Withdraw Tower"},
        )
        attempt = ctx["attempts"]["EAp1"]
        begin_review(attempt["id"])
        post_comment(attempt["id"], comment_text="confirm scope")

        resp = api.withdraw_phase(
            ctx["project"]["id"], "DESIGN",
            make_project_administrator_headers(ctx["members"]["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_STARTED)
        after = get_project(ctx["project"]["id"])
        assert after["status"] == "DESIGN_SUBMITTED"
        assert after["fee_balance_cents"] == 4150000, "no refund on a rejected withdrawal"

    def test_submit_debits_design_fee(self, api):
        """PRD §3.4: "The certification fee for a phase is its base — 250,000 cents for `DESIGN`, 350,000 cents for `CONSTRUCTION` — plus 5,000 cents for every whole-or-partial thousand square feet of `gross_floor_area_sqft`, the area being divided by one thousand and rounded up to a whole number before multiplying; the total is capped at 2,000,000 cents, so the charged fee is the smaller of the computed amount and the cap."
        PRD §3.4: "Submission debits the fee from `fee_balance_cents`, and when the balance does not cover it the submission fails with `ERR_INSUFFICIENT_SUBMISSION_FUNDS` (HTTP 402)."

        Design: Difficulty/compensating_invariant/fee_submit_withdraw_balance_conserved
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="Tower R", ready=True)
        submitted = validate_success(
            api.submit_phase(
                project["id"], "DESIGN",
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert submitted["fee_balance_cents"] == 4150000, (
            "5000000 - min(250000 + 5000*120, 2000000) = 5000000 - 850000")

    def test_withdraw_refunds_fee_and_reverts_states(self, api):
        """PRD §3.4: "A successful withdrawal moves every `SUBMITTED` attempt of the phase back to `READY_FOR_SUBMITTAL`, refunds the phase fee computed by the same formula from the same inputs — so a submission followed by a withdrawal leaves `fee_balance_cents` exactly where it started — recomputes the projected level, and increments the project's `version` by one."

        Design: Difficulty/compensating_invariant/fee_submit_withdraw_balance_conserved
        """
        members, entry, project, attempt = _locked_project_with_attempt(
            api, project_name="Tower R2", ready=True)
        submit_phase(project["id"], "DESIGN", members["admin"]["id"])
        assert get_project(project["id"])["fee_balance_cents"] == 4150000

        reverted = validate_success(
            api.withdraw_phase(
                project["id"], "DESIGN",
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert reverted["fee_balance_cents"] == 5000000, (
            "submit + withdraw leaves fee_balance_cents unchanged")
        assert reverted["status"] == "STRATEGY_LOCKED"
        assert get_attempt(attempt["id"])["status"] == "READY_FOR_SUBMITTAL"


class TestFeeFormulaConstants:
    def test_fee_ceil_per_thousand_and_cap(self, api):
        """PRD §3.4: "The certification fee for a phase is its base — 250,000 cents for `DESIGN`, 350,000 cents for `CONSTRUCTION` — plus 5,000 cents for every whole-or-partial thousand square feet of `gross_floor_area_sqft`, the area being divided by one thousand and rounded up to a whole number before multiplying; the total is capped at 2,000,000 cents, so the charged fee is the smaller of the computed amount and the cap."

        Design: Corner/calculations/certification_fee_ceil_and_cap
        """
        members = create_members()
        entry = _prereq_entry()

        def project_with_ready_attempt(name, sqft, budget):
            project = create_project(
                members["admin"]["id"], project_name=name,
                gross_floor_area_sqft=sqft, fee_budget_cents=budget)
            attempt = create_attempt(
                project["id"], entry["id"], members["spec"]["id"],
                members["admin"]["id"])
            lock_strategy(project["id"], members["admin"]["id"])
            drive_attempt_ready(attempt["id"], members["spec"]["id"], members["admin"]["id"])
            return project

        p1 = project_with_ready_attempt("Ceil Tower", 120001, 5000000)
        p2 = project_with_ready_attempt("Cap Tower", 999999, 10000000)

        submitted1 = validate_success(
            api.submit_phase(
                p1["id"], "DESIGN",
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert submitted1["fee_balance_cents"] == 4145000, (
            "ceil(120001/1000)=121 -> fee 250000 + 5000*121 = 855000")

        submitted2 = validate_success(
            api.submit_phase(
                p2["id"], "DESIGN",
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert submitted2["fee_balance_cents"] == 8000000, (
            "min(250000 + 5000*1000, 2000000) = 2000000: the cap binds")


class TestCreationGatesDuringSubmission:
    def test_attempt_create_during_submission_blocked(self, api):
        """PRD §3.2: "Attempt creation requires the project to be `REGISTERED` or `STRATEGY_LOCKED`; at any other project state it fails with `ERR_INVALID_PROJECT_STATE`."

        Design: Corner/validations/attempt_create_during_submission_blocked
        """
        ctx = setup_submitted_design_package(
            [{"code": "EAp1", "points": 0, "is_prerequisite": True,
              "phase_eligibility": "BOTH"}],
            project_overrides={"project_name": "MidStream2 Tower"},
        )
        entry = create_credit_entry(
            credit_code="WEc1", title="Water Efficiency", category="WATER",
            points_possible=2, is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=False)
        resp = api.create_credit_attempt(
            {"project_id": ctx["project"]["id"],
             "credit_library_entry_id": entry["id"],
             "phase": "DESIGN",
             "documentation_owner_id": ctx["members"]["spec"]["id"]},
            make_project_administrator_headers(ctx["members"]["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATE)


class TestLevelProjections:
    def _three_submitted_20pt_attempts(self, api):
        specs = [
            {"code": "EAp1", "points": 20, "is_prerequisite": True,
             "phase_eligibility": "BOTH", "title": "Fundamental Commissioning"},
            {"code": "WEc1", "points": 20, "category": "WATER", "title": "Water Efficiency"},
            {"code": "MRc1", "points": 20, "category": "MATERIALS", "title": "Materials Reuse"},
        ]
        return setup_submitted_design_package(
            specs, project_overrides={"project_name": "Tower B", "target_level": "GOLD"})

    def test_submitted_package_projects_optimistic_level(self, api):
        """PRD §3.5: "The `projected_level` is the optimistic reading — attempts in `SUBMITTED`, `UNDER_REVIEW`, or `RESUBMITTED` count at face value (`points_possible`) on top of the awarded total — while the `conservative_level` counts awarded points only."
        PRD §3.5: "Those totals feed two published levels through a single threshold table: 80 or more points is `PLATINUM`, 60 or more is `GOLD`, 50 or more is `SILVER`, 40 or more is `CERTIFIED`, and below 40 is `NONE`, all boundaries inclusive."

        Design: Difficulty/dual_variant_calc/project_optimistic_vs_conservative_level
        """
        ctx = self._three_submitted_20pt_attempts(api)
        project = get_project(ctx["project"]["id"])
        assert project["points_pursued_total"] == 60
        assert project["points_awarded_total"] == 0
        assert project["projected_level"] == "GOLD", (
            "optimistic: 3 x 20 at face value = 60 >= 60")
        assert project["conservative_level"] == "NONE", (
            "conservative: nothing awarded, 0 < 40")
        assert project["projected_level"] != project["conservative_level"]

    def test_clarification_pending_attempt_leaves_optimistic_set(self, api):
        """PRD §3.5: "Posting stamps the comment `OPEN`, copies the attempt's current `submission_round` into the comment's `round`, and moves the attempt `UNDER_REVIEW → CLARIFICATION_REQUESTED`; because a clarification-pending attempt no longer counts toward the optimistic projection, the projected level is recomputed at that moment."

        Design: Difficulty/dual_variant_calc/project_optimistic_vs_conservative_level
        """
        ctx = self._three_submitted_20pt_attempts(api)
        attempt = ctx["attempts"]["WEc1"]
        begin_review(attempt["id"])
        post_comment(attempt["id"], comment_text="confirm fixture schedule")

        project = get_project(ctx["project"]["id"])
        assert project["projected_level"] == "CERTIFIED", (
            "optimistic set now counts only the two SUBMITTED attempts: 2 x 20 = 40")
        assert project["conservative_level"] == "NONE"
