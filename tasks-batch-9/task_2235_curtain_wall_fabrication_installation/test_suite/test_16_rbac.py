"""Authorisation: the role gate runs ahead of every lookup and state check, the
shared writes really are shared, segregation of duties keys on identity rather
than role, and the embed-versus-field handoff is a role boundary."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import USER_IDS
from test_helpers.test_users import (
    TEST_USERS,
    headers_without_user,
    make_architect_of_record_headers,
    make_cw_detailer_headers,
    make_qc_inspector_headers,
)

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
ENGINEER = TEST_USERS["delegated_engineer_headers"]
ARCHITECT = TEST_USERS["architect_of_record_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestExclusiveOperationsRefuseForeignRoles:
    """Five single-role writes, each attempted by a role that owns a different
    part of the same workflow."""

    def test_the_role_gate_answers_before_any_state_or_lookup_would_have(self):
        """A detailer's system decision, a detailer's review, an architect's seal, an
        inspector's certification and a superintendent's breakage draw are all
        refused for the role — even though the package has left design assist, the
        submittal is terminal, the seal is already applied, the zone is only planned
        and the named lot does not exist at all.

        PRD: "When the role is present but is not one of the roles the addressed operation permits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role_unauthorized
        """
        ctx = fx.setup_ready_for_release()
        zone_id = ctx["zone_ids"][0]
        package_before = fx.refresh_package(ctx)
        order_before = fx.refresh_glass_order(ctx)

        validate_error(
            api_client.decide_system(
                ctx["package_id"], f.system_decision_payload("STICK_BUILT"), DETAILER
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.review_submittal(
                ctx["submittal_id"],
                f.review_payload("APPROVED"),
                make_cw_detailer_headers(USER_IDS["DETAILER"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.seal_submittal(
                ctx["submittal_id"],
                f.seal_payload("PE-00000"),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.certify_weather_tight(
                zone_id, f.certify_weather_tight_payload(), QC
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.create_breakage_draw(
                f.create_breakage_draw_payload(
                    ctx["glass_order_id"], zone_id, 3, order_before["version"]
                ),
                SUPERINTENDENT,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        package_after = fx.refresh_package(ctx)
        assert package_after["version"] == package_before["version"]
        assert package_after["system_type"] == "UNITIZED"
        submittal = get_success_data(api_client.get_submittal(ctx["submittal_id"], PM))
        assert submittal["state"] == "APPROVED"
        assert submittal["sealed_by_user_id"] == USER_IDS["ENGINEER"]
        assert (
            get_success_data(api_client.get_installation_zone(zone_id, PM))["weather_status"]
            == "NOT_TIGHT"
        )
        assert fx.refresh_glass_order(ctx)["version"] == order_before["version"]
        assert get_success_data(api_client.list_breakage_draws(PROCUREMENT)) == []

    def test_the_owning_roles_reach_the_business_rule_the_gate_had_masked(self):
        """Repeated under their owning roles the same five calls get past the role
        check: the project manager's decision reports a package past design assist,
        the architect's review reports a terminal submittal, the engineer's seal lands
        on a fresh set, the manager's certification reports a zone that has not been
        hung, and procurement's draw reports a panel lot that does not exist.

        PRD: "`X-User-Role` not among the roles the endpoint permits — `ERR_UNAUTHORIZED` (403). Applies to every endpoint that declares a role list."

        Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role_unauthorized
        """
        ctx = fx.setup_ready_for_release()
        zone_id = ctx["zone_ids"][0]
        approved_submittal_id = ctx["submittal_id"]
        order = fx.refresh_glass_order(ctx)

        validate_error(
            api_client.decide_system(
                ctx["package_id"], f.system_decision_payload("STICK_BUILT"), PM
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.review_submittal(
                approved_submittal_id, f.review_payload("APPROVED"), ARCHITECT
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )

        fresh = fx.create_submittal(
            ctx, title="curtain wall corner detail", drawing_set_ref="SD-500"
        )
        sealed = validate_success(
            api_client.seal_submittal(fresh["id"], f.seal_payload("PE-77120"), ENGINEER),
            expected_status=200,
        )
        assert sealed["seal_license_no"] == "PE-77120"
        assert sealed["sealed_by_user_id"] == USER_IDS["ENGINEER"]

        validate_error(
            api_client.certify_weather_tight(
                zone_id, f.certify_weather_tight_payload(), PM
            ),
            ApiErrorId.ERR_ZONE_SEQUENCE_VIOLATION.value,
            expected_status=409,
        )
        validate_error(
            api_client.create_breakage_draw(
                f.create_breakage_draw_payload(
                    ctx["glass_order_id"], zone_id, 3, order["version"]
                ),
                PROCUREMENT,
            ),
            ApiErrorId.ERR_LOT_NOT_FOUND.value,
            expected_status=404,
        )


class TestSharedOperationsAcceptEveryDeclaredRole:
    """Three writes name two roles each, and every read names all eight."""

    def test_two_roles_book_mockups_two_rescore_the_order_two_raise_defects(self):
        """A mockup booked by the inspector and one booked by the project manager are
        both scheduled on the same laboratory, the risk rescoring answers to the
        project manager and to procurement with the same 48.11, the architect raises a
        punch-list item under her own identity, the structural contractor may read the
        order — and procurement, which owns neither booking role, is still refused.

        PRD: "A `QCInspector` or an `ArchitectOfRecord` raises one against a package by `package_id`, optionally naming a `zone_id` (left null for package-level mockup defects), optionally naming the `field_test_id` or `mockup_test_id` that raised it according to `origin`, and supplying an `origin` of `MOCKUP_TEST`, `FIELD_TEST` or `PUNCH_LIST`, a `severity` of `CRITICAL`, `MAJOR` or `MINOR`, and a free-text `description`."

        Design: Corner/rbac/shared_operations_accept_every_declared_role
        """
        ctx = fx.setup_lab_with_capacity(chamber_capacity=2)
        fx.add_zone_a(ctx)
        fx.create_glass_order(ctx)
        zone_id = ctx["zone_ids"][0]

        by_inspector = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(ctx["package_id"], ctx["lab_id"]), QC
            ),
            expected_status=201,
        )
        by_manager = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-07T06:00:00Z",
                    window_end="2026-08-07T20:00:00Z",
                ),
                PM,
            ),
            expected_status=201,
        )
        assert by_inspector["state"] == "SCHEDULED"
        assert by_manager["state"] == "SCHEDULED"
        assert by_inspector["test_lab_id"] == by_manager["test_lab_id"] == ctx["lab_id"]
        assert by_inspector["id"] != by_manager["id"]

        by_pm = validate_success(
            api_client.recompute_glass_risk(
                ctx["glass_order_id"], f.recompute_risk_payload(), PM
            ),
            expected_status=200,
        )
        by_procurement = validate_success(
            api_client.recompute_glass_risk(
                ctx["glass_order_id"], f.recompute_risk_payload(), PROCUREMENT
            ),
            expected_status=200,
        )
        assert by_pm["risk_score"] == pytest.approx(48.11, abs=0.01)
        assert by_procurement["risk_score"] == pytest.approx(48.11, abs=0.01)

        by_architect = validate_success(
            api_client.create_defect_item(
                f.create_defect_item_payload(
                    ctx["package_id"],
                    zone_id=zone_id,
                    description="reveal shadow line inconsistent with the approved mockup",
                ),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            expected_status=201,
        )
        assert by_architect["status"] == "OPEN"
        assert by_architect["raised_by_user_id"] == USER_IDS["ARCHITECT"]

        validate_success(
            api_client.get_glass_order(ctx["glass_order_id"], TEST_USERS["structural_contractor_headers"]),
            expected_status=200,
        )
        validate_error(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-09T06:00:00Z",
                    window_end="2026-08-09T20:00:00Z",
                ),
                PROCUREMENT,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )


class TestReinspectionSegregationKeysOnIdentity:
    """Two callers, one role, opposite outcomes."""

    def test_the_raiser_is_refused_while_a_second_inspector_closes_the_item(self):
        """The inspector who raised the item cannot re-inspect it and the item stays
        with its remediation submitted, a header-less attempt is refused earlier still
        for the missing operator, and a second inspector carrying the identical role
        closes the item under her own name while the raiser's name survives on the
        row.

        PRD: "When the acting `X-User-ID` equals the item's `raised_by_user_id`, the request is refused with `ERR_INSPECTOR_CONFLICT`."

        Design: Corner/rbac/reinspection_by_the_raiser_is_rejected_by_segregation_of_duties
        """
        ctx = fx.new_project()
        fx.add_zone_a(ctx)
        defect = fx.raise_defect(
            ctx,
            user_id=USER_IDS["QC_1"],
            zone_id=ctx["zone_ids"][0],
            severity="MAJOR",
            description="unseated gasket at the head receiver",
        )
        fx.submit_remediation(ctx, defect["id"])
        assert defect["raised_by_user_id"] == USER_IDS["QC_1"]

        validate_error(
            api_client.reinspect_defect(
                defect["id"],
                f.reinspect_payload("PASS"),
                make_qc_inspector_headers(USER_IDS["QC_1"]),
            ),
            ApiErrorId.ERR_INSPECTOR_CONFLICT.value,
            expected_status=422,
        )
        held = get_success_data(api_client.get_defect_item(defect["id"], PM))
        assert held["status"] == "REMEDIATION_SUBMITTED"
        assert held["reinspected_by_user_id"] is None

        validate_error(
            api_client.reinspect_defect(
                defect["id"], f.reinspect_payload("PASS"), headers_without_user("QCInspector")
            ),
            ApiErrorId.ERR_MISSING_USER.value,
            expected_status=401,
        )

        closed = validate_success(
            api_client.reinspect_defect(
                defect["id"],
                f.reinspect_payload("PASS"),
                make_qc_inspector_headers(USER_IDS["QC_2"]),
            ),
            expected_status=200,
        )
        assert closed["status"] == "CLOSED"
        assert closed["reinspected_by_user_id"] == USER_IDS["QC_2"]
        assert closed["closed_at"] == "2026-08-03T08:00:00.000Z"
        assert closed["raised_by_user_id"] == USER_IDS["QC_1"]


class TestEmbedAndFieldRolesStayOnTheirOwnSideOfTheHandoff:
    """The trade boundary between the concrete contractor and the glazing crew."""

    @staticmethod
    def _zone_with_an_accepted_but_unpoured_survey():
        ctx = fx.setup_qualified_package()
        fx.add_zone_a(ctx)
        zone_id = ctx["zone_ids"][0]
        fx.open_embed_survey(ctx, zone_id)
        survey = fx.record_survey(ctx, zone_id)
        assert survey["state"] == "ACCEPTED"
        return ctx, zone_id, survey

    def test_neither_trade_may_take_the_others_step(self):
        """The superintendent can neither confirm the pour nor open a survey, the
        structural contractor can neither set the anchors nor register a hoist, and
        after all four refusals the survey is still merely accepted, the zone still
        merely planned and no second survey or rig exists.

        PRD: "Anchor embeds must be surveyed and poured before a single panel bracket can be set, and that survey belongs to the `StructuralContractor` rather than to the curtain wall trade — the detailer lays the embeds out, the concrete contractor confirms where they actually ended up."

        Design: Corner/rbac/embed_and_field_roles_cannot_perform_each_others_steps_unauthorized
        """
        ctx, zone_id, survey = self._zone_with_an_accepted_but_unpoured_survey()

        validate_error(
            api_client.confirm_pour(
                survey["id"], f.confirm_pour_payload("2026-08-06T12:00:00Z"), SUPERINTENDENT
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.create_embed_survey(
                zone_id,
                f.create_embed_survey_payload(embed_layout_ref="EL-05-S"),
                SUPERINTENDENT,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), STRUCTURAL),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api_client.create_hoist_rig(
                f.create_hoist_rig_payload(ctx["package_id"], rig_code="HR-9"), STRUCTURAL
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        assert (
            get_success_data(api_client.get_embed_survey(survey["id"], PM))["state"]
            == "ACCEPTED"
        )
        assert (
            get_success_data(api_client.get_installation_zone(zone_id, PM))["install_status"]
            == "PLANNED"
        )
        assert (
            len(get_success_data(api_client.list_embed_surveys(PM, params={"zone_id": zone_id})))
            == 1
        )
        assert get_success_data(api_client.list_hoist_rigs(PM)) == []

    def test_each_step_succeeds_under_the_trade_that_owns_it(self):
        """The contractor pours, the superintendent then sets the anchors and
        registers the hoist: the same four endpoints that refused the wrong trade all
        answer their own.

        PRD: "With embeds poured, the `FieldSuperintendent` sets a zone's anchors, advancing `install_status` `PLANNED` → `ANCHORS_SET`."

        Design: Corner/rbac/embed_and_field_roles_cannot_perform_each_others_steps_unauthorized
        """
        ctx, zone_id, survey = self._zone_with_an_accepted_but_unpoured_survey()

        poured = validate_success(
            api_client.confirm_pour(
                survey["id"], f.confirm_pour_payload("2026-08-06T12:00:00Z"), STRUCTURAL
            ),
            expected_status=200,
        )
        assert poured["state"] == "POURED"
        assert poured["poured_at"] == "2026-08-06T12:00:00.000Z"

        anchored = validate_success(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT),
            expected_status=200,
        )
        assert anchored["install_status"] == "ANCHORS_SET"

        rig = validate_success(
            api_client.create_hoist_rig(
                f.create_hoist_rig_payload(ctx["package_id"], rig_code="HR-9"), SUPERINTENDENT
            ),
            expected_status=201,
        )
        assert rig["status"] == "ACTIVE"
        assert rig["changeover_buffer_minutes"] == 45
