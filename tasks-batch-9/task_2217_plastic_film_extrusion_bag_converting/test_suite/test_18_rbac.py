"""Authorization: role exclusives, peer roles and the two duty separations."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    ISSUING_MANAGER,
    QUALITY,
    SEAL_OPERATOR,
    ApiErrorId,
    append_seal_specimens,
    build_non_food_recipe_draft,
    create_compliance_dossier_payload,
    create_seal_test_payload,
    get_success_data,
    make_blend_engineer_headers,
    make_quality_manager_headers,
    setup_bag_lot_converting,
    setup_draft_dossier,
    setup_food_run_completed,
    setup_non_food_catalog,
    validate_error,
    validate_success,
)

SECOND_MANAGER = make_quality_manager_headers("u-qm-2")
SUBMITTING_MANAGER = make_blend_engineer_headers("u-qm-1")
TESTING_MANAGER = make_quality_manager_headers("u-qm-1")

FOOD_PANEL = ((1, 26.0), (2, 25.0), (3, 24.0))


class TestApprovalIsAQualityExclusive:
    """The role that drafts and submits a blend can never sign it off."""

    @staticmethod
    def _submitted_recipe(api):
        world = setup_non_food_catalog(api)
        recipe = build_non_food_recipe_draft(api, world, recipe_code="R-NF-0")
        world["recipe"] = get_success_data(
            api.submit_blend_recipe(recipe["id"], ENGINEER))
        return world

    def test_a_blend_engineer_is_refused_on_approve(self, api):
        """The engineer's own role is not on the approve endpoint.

        PRD: "| POST | `/blend-recipes/{id}/approve` | Approve a SUBMITTED recipe
        | QualityManager |"

        Design: Corner/rbac/blend_engineer_cannot_approve_a_recipe
        """
        world = self._submitted_recipe(api)

        validate_error(api.approve_blend_recipe(world["recipe"]["id"], ENGINEER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_the_refused_approval_leaves_the_recipe_awaiting_review(self, api):
        """Authorization is screened before the recipe's own state is read.

        PRD: "If the headers are well-formed but the declared role is not among
        the roles authorized for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/blend_engineer_cannot_approve_a_recipe
        """
        world = self._submitted_recipe(api)
        validate_error(api.approve_blend_recipe(world["recipe"]["id"], ENGINEER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["status"] == "SUBMITTED"
        assert recipe["approved_by_user_id"] is None


class TestRollReleaseIsAQualityExclusive:
    """A downstream role cannot self-serve the film it is waiting for."""

    def test_a_converting_operator_is_refused_on_roll_release(self, api):
        """The roll is releasable; the caller is not entitled to release it.

        PRD: "| POST | `/film-rolls/{id}/release` | Release a WOUND roll for
        printing | QualityManager |"

        Design: Corner/rbac/converting_operator_cannot_release_a_film_roll
        """
        world = setup_food_run_completed(api, roll_specs=((1, 600.0),))
        roll_id = world["rolls"][1]["id"]

        validate_error(api.release_film_roll(roll_id, CONVERTER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        roll = get_success_data(api.get_film_roll(roll_id, QUALITY))
        assert roll["status"] == "WOUND"

    def test_the_quality_manager_can_still_release_the_same_roll(self, api):
        """The refusal was about the caller, not about the roll.

        PRD: "A wound roll is not printable until quality releases it. A
        `QualityManager` moves a roll `WOUND → RELEASED` subject to four
        conditions".

        Design: Corner/rbac/converting_operator_cannot_release_a_film_roll
        """
        world = setup_food_run_completed(api, roll_specs=((1, 600.0),))
        roll_id = world["rolls"][1]["id"]
        validate_error(api.release_film_roll(roll_id, CONVERTER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        released = validate_success(api.release_film_roll(roll_id, QUALITY), 200)
        assert released["status"] == "RELEASED"


class TestDossierIssueIsAQualityExclusive:
    """Compliance issuance is the narrowest exclusive in the model."""

    def test_an_extrusion_operator_is_refused_on_dossier_issue(self, api):
        """A conforming DRAFT claim does not widen the endpoint's role list.

        PRD: "| POST | `/compliance-dossiers/{id}/issue` | Issue a DRAFT dossier,
        freezing and checking the claim | QualityManager |"

        Design: Corner/rbac/extrusion_operator_cannot_issue_a_compliance_dossier
        """
        world = setup_draft_dossier(api)

        validate_error(
            api.issue_compliance_dossier(world["dossier"]["id"], EXTRUDER),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        dossier = get_success_data(
            api.get_compliance_dossier(world["dossier"]["id"], QUALITY))
        assert dossier["status"] == "DRAFT"
        assert dossier["issued_at"] is None
        assert dossier["issued_by_user_id"] is None


class TestPlantAdminHasNoQualityOverride:
    """The role model is segregation of duties, not a hierarchy."""

    def test_the_admin_role_is_refused_on_roll_release(self, api):
        """PlantAdmin owns reference data and shipping, not the quality gates.

        PRD: "The first is **segregation of duties** — the engineer who submits a
        blend may not approve it, and the technician who pulled a seal specimen
        may not issue the dossier that certifies the lot."

        Design: Corner/rbac/plant_admin_cannot_release_a_film_roll_despite_being_the_admin_role
        """
        world = setup_food_run_completed(api, roll_specs=((1, 600.0),))
        roll_id = world["rolls"][1]["id"]

        validate_error(api.release_film_roll(roll_id, ADMIN),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        roll = get_success_data(api.get_film_roll(roll_id, QUALITY))
        assert roll["status"] == "WOUND"
        assert roll["release_blocked_reason"] is None


class TestSealTestingHasTwoFirstClassRoles:
    """The seal panel accepts specimens from either converting or quality."""

    @staticmethod
    def _lot_with_one_converting_specimen(api):
        world = setup_bag_lot_converting(api)
        append_seal_specimens(api, world["bag_lot"]["id"], ((1, 26.0),),
                              SEAL_OPERATOR)
        return world

    def test_both_roles_may_append_to_the_same_panel(self, api):
        """A quality append and a converting append are both accepted.

        PRD: "Both a `ConvertingOperator` and a `QualityManager` may append
        specimens."

        Design: Corner/rbac/seal_testing_is_shared_between_the_converting_operator_and_the_quality_manager
        """
        world = self._lot_with_one_converting_specimen(api)
        lot_id = world["bag_lot"]["id"]

        validate_success(api.add_seal_test(lot_id, create_seal_test_payload(2, 25.0),
                                           SECOND_MANAGER), 201)
        validate_success(api.add_seal_test(lot_id, create_seal_test_payload(3, 24.0),
                                           SEAL_OPERATOR), 201)

        lot = get_success_data(api.get_bag_lot(lot_id, CONVERTER))
        assert lot["status"] == "TESTING"
        assert lot["seal_provisional_mean_n"] == pytest.approx(25.00, abs=0.01)
        assert lot["seal_provisional_verdict"] == "PASS"

    def test_each_row_records_the_operator_that_entered_it(self, api):
        """Three rows, attributed to two different acting identities.

        PRD: "records `entered_by_user_id` from the acting `X-User-ID` — which is
        what later feeds the dossier segregation-of-duties rule".

        Design: Corner/rbac/seal_testing_is_shared_between_the_converting_operator_and_the_quality_manager
        """
        world = self._lot_with_one_converting_specimen(api)
        lot_id = world["bag_lot"]["id"]
        get_success_data(api.add_seal_test(lot_id, create_seal_test_payload(2, 25.0),
                                           SECOND_MANAGER))
        get_success_data(api.add_seal_test(lot_id, create_seal_test_payload(3, 24.0),
                                           SEAL_OPERATOR))

        lot = get_success_data(api.get_bag_lot(lot_id, CONVERTER))
        assert len(lot["seal_specimens"]) == 3
        by_index = {row["specimen_index"]: row["entered_by_user_id"]
                    for row in lot["seal_specimens"]}
        assert by_index == {1: "u-co-1", 2: "u-qm-2", 3: "u-co-1"}


class TestTheSubmitterMayNotApprove:
    """Role and state are both correct; only the acting identity is wrong."""

    @staticmethod
    def _recipe_submitted_by_the_first_manager(api):
        world = setup_non_food_catalog(api)
        recipe = build_non_food_recipe_draft(api, world, recipe_code="R-NF-Q")
        world["recipe"] = get_success_data(
            api.submit_blend_recipe(recipe["id"], SUBMITTING_MANAGER))
        assert world["recipe"]["submitted_by_user_id"] == "u-qm-1"
        return world

    def test_the_submitting_identity_is_refused_on_approve(self, api):
        """u-qm-1 submitted this recipe, so u-qm-1 may not sign it off.

        PRD: "First, the operator who most recently submitted a blend recipe may
        neither approve nor reject it. On both of those transitions, the acting
        `X-User-ID` must differ from the recipe's stored `submitted_by_user_id`."

        Design: Corner/rbac/the_user_who_submitted_a_recipe_may_not_approve_it
        """
        world = self._recipe_submitted_by_the_first_manager(api)

        validate_error(
            api.approve_blend_recipe(world["recipe"]["id"], TESTING_MANAGER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["status"] == "SUBMITTED"
        assert recipe["approved_by_user_id"] is None

    def test_any_other_quality_identity_may_approve_it(self, api):
        """The very same call from u-qm-2 is a legitimate approval.

        PRD: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`, which
        carries HTTP 403 even though it sits in the compliance band of the
        screening order."

        Design: Corner/rbac/the_user_who_submitted_a_recipe_may_not_approve_it
        """
        world = self._recipe_submitted_by_the_first_manager(api)
        validate_error(
            api.approve_blend_recipe(world["recipe"]["id"], TESTING_MANAGER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        approved = validate_success(
            api.approve_blend_recipe(world["recipe"]["id"], SECOND_MANAGER), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-qm-2"


class TestTheSpecimenEntrantMayNotIssue:
    """The second duty separation reaches through the whole specimen log."""

    @staticmethod
    def _lot_tested_and_documented_by_two_managers(api):
        world = setup_bag_lot_converting(api)
        append_seal_specimens(api, world["bag_lot"]["id"], FOOD_PANEL,
                              TESTING_MANAGER)
        world["bag_lot"] = get_success_data(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER))
        world["dossier"] = get_success_data(api.create_compliance_dossier(
            create_compliance_dossier_payload(world["bag_lot"]["id"],
                                              dossier_code="CD-6",
                                              food_contact_declared=True,
                                              recycled_content_claim_pct=0.0),
            SECOND_MANAGER))
        return world

    def test_the_entrant_of_the_panel_is_refused_on_issue(self, api):
        """u-qm-1 entered every specimen, so u-qm-1 cannot certify the lot.

        PRD: "Second, the operator who entered any seal specimen for a bag lot may
        not issue that lot's compliance dossier: on issue, the acting `X-User-ID`
        must not appear as `entered_by_user_id` on any row of the lot's specimen
        log".

        Design: Corner/rbac/the_user_who_entered_a_seal_specimen_may_not_issue_the_lots_dossier
        """
        world = self._lot_tested_and_documented_by_two_managers(api)
        assert world["bag_lot"]["status"] == "QUALIFIED"
        assert world["bag_lot"]["seal_final_verdict"] == "PASS"

        validate_error(
            api.issue_compliance_dossier(world["dossier"]["id"], TESTING_MANAGER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        dossier = get_success_data(
            api.get_compliance_dossier(world["dossier"]["id"], QUALITY))
        assert dossier["status"] == "DRAFT"
        assert dossier["issued_at"] is None

    def test_an_untainted_quality_identity_may_issue_it(self, api):
        """u-qm-2 never touched the panel, so its signature is accepted.

        PRD: "Issue also stamps `issued_by_user_id` with the acting `X-User-ID`
        and `issued_at` from the logical clock."

        Design: Corner/rbac/the_user_who_entered_a_seal_specimen_may_not_issue_the_lots_dossier
        """
        world = self._lot_tested_and_documented_by_two_managers(api)
        validate_error(
            api.issue_compliance_dossier(world["dossier"]["id"], TESTING_MANAGER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        issued = validate_success(
            api.issue_compliance_dossier(world["dossier"]["id"], SECOND_MANAGER), 200)
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == "u-qm-2"
        assert issued["claim_conformance"] == "CONFORMING"
        assert issued["claim_variance_pct"] == pytest.approx(0.000, abs=0.001)
