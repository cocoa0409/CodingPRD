"""Priority-score dual variants, the selection sweep, and selection OCC (PRD §2.7, §3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_cip_project, assert_money,
    create_sponsor, create_draft_program, add_project, submit_program, accept_program,
    apply_selection, setup_accepted_program_with_selection,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestPriorityScoreVariants:
    def test_priority_score_sponsor_variant(self):
        """PRD §3.2: "Its base score is a weighted sum of the five components — thirty percent
        of the effective safety component, twenty percent of `preservation_score`, twenty
        percent of `capacity_score`, fifteen percent of `security_score`, and fifteen percent
        of `environmental_score`, the five weights summing to one — where the effective safety
        component is the raw `safety_score` doubled when `runway_safety_noncompliant` is true
        and taken as-is otherwise."
        Scores 20/10/10/10/10 without flags: 6 + 2 + 2 + 1.5 + 1.5 = 13.00.

        Design: Difficulty/dual_variant_calc/priority_score_sponsor_vs_federal
        """
        ctx = setup_accepted_program_with_selection()
        project = validate_success(api_client.get_project(ctx["project"]["id"], SPONSOR), 200)
        assert_cip_project(project)
        assert_money(project["priority_score_sponsor"], 13.00, "priority_score_sponsor")
        assert project["status"] == "SELECTED"

    def test_priority_score_federal_variant(self):
        """PRD §3.2: "Its base uses a different weighting — forty percent of `safety_score`,
        twenty-five percent of `capacity_score`, fifteen percent of `preservation_score`, ten
        percent of `security_score`, and ten percent of `environmental_score` — grants no
        multi-airport bonus, and instead subtracts a ten-point penalty when
        `runway_safety_noncompliant` is true."
        Scores 20/10/10/10/10 without flags: 8 + 2.5 + 1.5 + 1 + 1 = 14.00.

        Design: Difficulty/dual_variant_calc/priority_score_sponsor_vs_federal
        """
        ctx = setup_accepted_program_with_selection()
        project = validate_success(api_client.get_project(ctx["project"]["id"], SPONSOR), 200)
        assert_money(project["priority_score_federal"], 14.00, "priority_score_federal")

    def test_noncompliant_flag_and_bonus_diverge_variants(self):
        """PRD §3.2: "A flat five-point bonus is added when `multi_airport_system` is true."
        With both flags set the sponsor variant doubles safety and adds the bonus
        (12 + 2 + 2 + 1.5 + 1.5 + 5 = 24.00), while the federal variant subtracts the
        ten-point penalty (14.00 - 10 = 4.00).

        Design: Corner/calculations/noncompliant_flag_and_bonus_diverge_variants
        """
        ctx = setup_accepted_program_with_selection(project_overrides={
            "title": "RSA fix", "project_type": "RUNWAY_SAFETY",
            "runway_safety_noncompliant": True, "multi_airport_system": True,
        })
        project = validate_success(api_client.get_project(ctx["project"]["id"], SPONSOR), 200)
        assert_money(project["priority_score_sponsor"], 24.00, "priority_score_sponsor")
        assert_money(project["priority_score_federal"], 4.00, "priority_score_federal")


class TestSelectionSweep:
    def test_selection_ranking_budget_sweep_and_tiebreak(self):
        """PRD §3.2: "projects are ordered by `priority_score_sponsor` descending, with ties
        broken by `created_at` ascending — never by identifier — producing each project's
        `selection_rank`."
        PRD §3.2: "a project becomes `SELECTED` exactly when its own `estimated_cost`, added
        to the cumulative `estimated_cost` of all projects ranked above it, does not exceed
        `selection_budget`; a project that would breach the ceiling becomes `DEFERRED`, as
        does everything ranked below the first breach."
        PRD §3.2: "a later application with a larger budget moves formerly `DEFERRED` projects
        back to `SELECTED`".

        Design: Corner/calculations/selection_ranking_budget_sweep_and_tiebreak
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        # Identical scores on both projects -> sponsor score ties; created_at breaks the tie.
        p1 = add_project(program["id"], title="First", project_type="PRESERVATION",
                         estimated_cost=600_000)
        p2 = add_project(program["id"], title="Second", project_type="CAPACITY",
                         estimated_cost=600_000)
        submit_program(program["id"])
        accepted = accept_program(program["id"])

        program = apply_selection(program["id"], 1_100_000, accepted["version"])
        p1_after = validate_success(api_client.get_project(p1["id"], SPONSOR), 200)
        p2_after = validate_success(api_client.get_project(p2["id"], SPONSOR), 200)
        assert p1_after["selection_rank"] == 1
        assert p1_after["status"] == "SELECTED"
        assert p2_after["selection_rank"] == 2
        # 600,000 + 600,000 would breach the 1,100,000 ceiling.
        assert p2_after["status"] == "DEFERRED"
        assert_money(program["selected_total_cost"], 600_000.00, "selected_total_cost")

        # Re-applying with a larger budget promotes the deferred project.
        program = apply_selection(program["id"], 2_000_000, program["version"])
        p2_after = validate_success(api_client.get_project(p2["id"], SPONSOR), 200)
        assert p2_after["status"] == "SELECTED"
        assert_money(program["selected_total_cost"], 1_200_000.00, "selected_total_cost")

    def test_selection_apply_stale_version_occ(self):
        """PRD §2.7: "Applying project selection to a capital program likewise requires a
        non-optional `expected_program_version` matching the program's current `version`, with
        a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/selection_apply_stale_version_occ
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        add_project(program["id"], title="Apron", project_type="CAPACITY",
                    estimated_cost=250_000, safety_score=5, capacity_score=5,
                    preservation_score=5, security_score=5, environmental_score=5)
        submit_program(program["id"])
        accepted = accept_program(program["id"])
        observed_version = accepted["version"]

        # The first apply succeeds and advances the program version.
        swept = apply_selection(program["id"], 2_000_000, observed_version)
        assert swept["version"] == observed_version + 1

        # Replaying with the pre-sweep version is stale.
        res = api_client.apply_selection(program["id"], {
            "selection_budget": 3_000_000,
            "expected_program_version": observed_version,
        }, SPONSOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
