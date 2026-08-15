"""The certification decision and certification-gated incentive money
(PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    apply_incentive,
    approve_incentive,
    create_incentive_program,
    create_members,
    create_project,
    get_project,
    get_success_data,
    make_project_administrator_headers,
    setup_certified_project,
    setup_submitted_design_package,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


class TestDecisionStateGate:
    def test_decision_from_wrong_state_blocked(self, api):
        """PRD §3.7: "Once the construction phase has bubbled up to `CONSTRUCTION_REVIEWED`, the `CertificationReviewer` issues the decision by supplying a `decision` of `CERTIFY` or `DENY`."
        PRD §2.7: "7. State validity — the target resource must be in a from-state the requested transition allows, and the creation-time parent-state gates apply at this stage as well; violations yield the `ERR_INVALID_PROJECT_STATE` / `ERR_INVALID_CREDIT_ATTEMPT_STATE` / `ERR_INVALID_MODEL_STATE` / `ERR_INVALID_COMMENT_STATE` / `ERR_INVALID_TASK_STATE` / `ERR_INVALID_INCENTIVE_STATE` / `ERR_INVALID_REPORT_STATE` family (HTTP 409)."

        Design: Corner/state_machines/decision_from_wrong_state_blocked
        """
        ctx = setup_submitted_design_package(
            [{"code": "EAp1", "points": 20, "is_prerequisite": True,
              "phase_eligibility": "BOTH", "title": "Fundamental Commissioning"}],
            project_overrides={"project_name": "Early Tower"},
        )
        resp = api.issue_decision(ctx["project"]["id"], "CERTIFY", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATE)
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "DESIGN_SUBMITTED"
        assert project["certified_level"] is None


class TestCertifyGates:
    def test_certify_with_denied_prerequisite_blocked(self, api):
        """PRD §3.7: "Certification is gated twice: `prerequisites_satisfied` must be true, otherwise `ERR_PREREQUISITE_NOT_AWARDED` (HTTP 409); and `points_awarded_total` must reach the 40-point floor, otherwise `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

        Design: Corner/validations/certify_with_denied_prerequisite_blocked
        """
        ctx = setup_certified_project(
            design_credits=[
                {"code": "EAp1", "points": 20, "is_prerequisite": True,
                 "phase_eligibility": "BOTH", "deny": True},
                {"code": "WEc1", "points": 20, "category": "WATER", "award": 20},
            ],
            construction_credits=[
                {"code": "MRc1", "points": 20, "category": "MATERIALS",
                 "phase_eligibility": "CONSTRUCTION", "award": 20},
            ],
            project_overrides={"project_name": "DeniedPrereq Tower"},
            certify=False,
        )
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "CONSTRUCTION_REVIEWED"
        assert project["points_awarded_total"] == 40, "the points floor is met"
        assert project["prerequisites_satisfied"] is False

        resp = api.issue_decision(ctx["project"]["id"], "CERTIFY", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_AWARDED)
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "CONSTRUCTION_REVIEWED"
        assert project["certified_level"] is None

    def test_certify_below_40_points_blocked(self, api):
        """PRD §3.7: "Certification is gated twice: `prerequisites_satisfied` must be true, otherwise `ERR_PREREQUISITE_NOT_AWARDED` (HTTP 409); and `points_awarded_total` must reach the 40-point floor, otherwise `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

        Design: Corner/validations/certify_below_40_points_blocked
        """
        ctx = setup_certified_project(
            design_credits=[
                {"code": "EAp1", "points": 20, "is_prerequisite": True,
                 "phase_eligibility": "BOTH", "award": 20},
                {"code": "WEc1", "points": 18, "category": "WATER", "award": 18},
            ],
            construction_credits=[
                {"code": "MRc1", "points": 10, "category": "MATERIALS",
                 "phase_eligibility": "CONSTRUCTION", "award": 0},
            ],
            project_overrides={"project_name": "Short Tower"},
            certify=False,
        )
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "CONSTRUCTION_REVIEWED"
        assert project["points_awarded_total"] == 38
        assert project["prerequisites_satisfied"] is True, (
            "only the points floor fails")

        resp = api.issue_decision(ctx["project"]["id"], "CERTIFY", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS)
        assert get_project(ctx["project"]["id"])["status"] == "CONSTRUCTION_REVIEWED"


class TestCertifyOutcome:
    def test_certify_at_exactly_60_fixes_gold(self, api):
        """PRD §3.5: "Those totals feed two published levels through a single threshold table: 80 or more points is `PLATINUM`, 60 or more is `GOLD`, 50 or more is `SILVER`, 40 or more is `CERTIFIED`, and below 40 is `NONE`, all boundaries inclusive."
        PRD §3.7: "A `CERTIFY` decision fixes `certified_level` from the threshold table of §3.5 applied to `points_awarded_total`, stamps `certified_at` from the logical clock, sets `plaque_marketing_rights_granted` to true — plaque and marketing rights, granted at this moment and never revoked, retained even if the certification later lapses — and moves the project to `CERTIFIED`."

        Design: Corner/calculations/certification_level_boundary_60_gold
        """
        ctx = setup_certified_project(
            design_credits=[
                {"code": "EAp1", "points": 20, "is_prerequisite": True,
                 "phase_eligibility": "BOTH", "award": 20},
                {"code": "WEc1", "points": 20, "category": "WATER", "award": 20},
            ],
            construction_credits=[
                {"code": "MRc1", "points": 20, "category": "MATERIALS",
                 "phase_eligibility": "CONSTRUCTION", "award": 20},
            ],
            project_overrides={"project_name": "Gold Tower", "target_level": "GOLD"},
            certify_clock="2027-03-01T00:00:00Z",
        )
        project = ctx["project"]
        assert project["status"] == "CERTIFIED"
        assert project["points_awarded_total"] == 60
        assert project["certified_level"] == "GOLD", "60 >= 60 inclusive"
        assert project["certified_at"] == "2027-03-01T00:00:00Z", (
            "certified_at is stamped from the logical clock")
        assert project["plaque_marketing_rights_granted"] is True


class TestIncentiveLifecycle:
    def _project_with_application(self, api, project_name="Incentive Tower"):
        members = create_members()
        project = create_project(members["admin"]["id"], project_name=project_name)
        program = create_incentive_program()
        application = apply_incentive(project["id"], program["id"], members["admin"]["id"])
        return members, project, program, application

    def test_disburse_before_approve_rejected(self, api):
        """PRD §3.7: "Disbursement moves an approved application `APPROVED → DISBURSED`, the application's terminal state. Approving or disbursing from the wrong state answers `ERR_INVALID_INCENTIVE_STATE` (HTTP 409)."

        Design: Corner/state_machines/incentive_disburse_before_approve_rejected
        """
        members, project, program, application = self._project_with_application(api)
        resp = api.disburse_project_incentive(application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_INCENTIVE_STATE)
        after = validate_success(api.get_project_incentive(application["id"], ANY))
        assert after["status"] == "APPLIED"
        assert after["claimed_amount_cents"] == 0

    def test_duplicate_incentive_application_rejected(self, api):
        """PRD §3.7: "A second live application — one in `APPLIED`, `APPROVED`, or `DISBURSED` — for the same program on the same project is rejected with `ERR_DUPLICATE_INCENTIVE_APPLICATION` (HTTP 409)."

        Design: Corner/validations/duplicate_incentive_application_rejected
        """
        members, project, program, application = self._project_with_application(
            api, project_name="DupInc Tower")
        resp = api.create_project_incentive(
            {"project_id": project["id"], "incentive_program_id": program["id"]},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INCENTIVE_APPLICATION)

    def test_approve_incentive_project_not_certified_rejected(self, api):
        """PRD §3.7: "Approval belongs to the `ProgramAdmin` and is certification-gated. The project must be `CERTIFIED`, otherwise `ERR_PROJECT_NOT_CERTIFIED` (HTTP 409), and its `certified_level` must be at least the program's `minimum_certification_level` on the ordering `CERTIFIED`, `SILVER`, `GOLD`, `PLATINUM` — a gold-level project qualifies for a silver-floor program but not for a platinum-floor one — otherwise `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/approve_incentive_project_not_certified_rejected
        """
        members, project, program, application = self._project_with_application(
            api, project_name="EarlyInc Tower")
        assert get_project(project["id"])["status"] == "REGISTERED"
        resp = api.approve_project_incentive(application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CERTIFIED)

    def test_approve_incentive_level_insufficient_blocked(self, api):
        """PRD §3.7: "Approval belongs to the `ProgramAdmin` and is certification-gated. The project must be `CERTIFIED`, otherwise `ERR_PROJECT_NOT_CERTIFIED` (HTTP 409), and its `certified_level` must be at least the program's `minimum_certification_level` on the ordering `CERTIFIED`, `SILVER`, `GOLD`, `PLATINUM` — a gold-level project qualifies for a silver-floor program but not for a platinum-floor one — otherwise `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/approve_incentive_level_insufficient_blocked
        """
        ctx = setup_certified_project(
            design_credits=[
                {"code": "EAp1", "points": 20, "is_prerequisite": True,
                 "phase_eligibility": "BOTH", "award": 20},
                {"code": "WEc1", "points": 10, "category": "WATER", "award": 10},
            ],
            construction_credits=[
                {"code": "MRc1", "points": 10, "category": "MATERIALS",
                 "phase_eligibility": "CONSTRUCTION", "award": 10},
            ],
            project_overrides={"project_name": "LevelInc Tower"},
        )
        assert ctx["project"]["certified_level"] == "CERTIFIED"

        gold_program = create_incentive_program(
            program_name="Gold Grant", minimum_certification_level="GOLD")
        application = apply_incentive(
            ctx["project"]["id"], gold_program["id"], ctx["members"]["admin"]["id"])

        resp = api.approve_project_incentive(application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_LEVEL_INSUFFICIENT)
        after = validate_success(api.get_project_incentive(application["id"], ANY))
        assert after["status"] == "APPLIED"
        assert after["claimed_amount_cents"] == 0
