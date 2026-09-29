"""
Writes that are refused because of the state of an entity the payload only points
at: a body that is not yet qualified, and a panel approval that has run out.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FORMULATION_NOT_QUALIFIED,
    ERR_PANEL_APPROVAL_EXPIRED,
)
from test_helpers.test_users import (
    BODY_ENGINEER,
    PLANT_ADMIN,
    QUALITY_MANAGER,
)


class TestQualifiedBodyGatesTheProductionSide:
    """
    Section 3.3 rejects a production run whose body is not QUALIFIED "at this
    moment" with ERR_FORMULATION_NOT_QUALIFIED, and section 3.4 rejects a kiln run
    on the same grounds - one parent state, two unrelated child endpoints.
    """

    def _draft_body_env(self, api):
        plant = fx.create_plant(api)
        clay = fx.create_clay_pit(api, plant["id"])
        shale = fx.create_shale_pit(api, plant["id"])
        kiln = fx.create_kiln(api, plant["id"])
        car = fx.create_kiln_car(api, plant["id"])
        draft = fx.create_draft_formulation(api, plant["id"])
        draft = fx.add_components(
            api, draft, [(clay["id"], 50.00), (shale["id"], 50.00)]
        )
        return {
            "plant": plant,
            "kiln": kiln,
            "kiln_car": car,
            "formulation": draft,
            "operator": fx.make_plant_operator_headers(plant["id"]),
        }

    def test_a_complete_but_unqualified_body_blocks_both_child_creations(
        self, api, clock
    ):
        """
        The same payloads that fail on a DRAFT body succeed once it is QUALIFIED.

        Section 3.3: "The named formulation must be QUALIFIED at this moment - a
        DRAFT or RETIRED body is rejected with ERR_FORMULATION_NOT_QUALIFIED."
        Section 3.4 repeats the requirement for a kiln run. Section 3.3 also makes
        clear the clay commitment only happens on a successful run, so a rejected
        run leaves the pits at 0.00 committed.

        Design: Difficulty/cross_entity_state_dependency/production_run_and_kiln_run_creation_require_qualified_formulation
        """
        env = self._draft_body_env(api)
        body = env["formulation"]
        assert body["status"] == "DRAFT"
        assert body["component_share_total_pct"] == 100.00

        run_payload = F.production_run_payload(
            env["plant"]["id"], body["id"], env["kiln_car"]["id"]
        )
        kiln_payload = F.kiln_run_payload(env["kiln"]["id"], body["id"])

        validate_error(
            api.create_production_run(run_payload, env["operator"]),
            ERR_FORMULATION_NOT_QUALIFIED,
            409,
        )
        validate_error(
            api.create_kiln_run(kiln_payload, env["operator"]),
            ERR_FORMULATION_NOT_QUALIFIED,
            409,
        )

        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == [0.00, 0.00]
        assert [p["available_tons"] for p in pits] == [5000.00, 5000.00]

        qualified = validate_success(api.qualify_formulation(body["id"], BODY_ENGINEER))
        assert qualified["status"] == "QUALIFIED"
        assert qualified["qualified_at"] == "2026-08-01T00:00:00Z"

        run = validate_success(
            api.create_production_run(run_payload, env["operator"]), 201
        )
        assert run["status"] == "SETTING"
        assert run["clay_tons_committed"] == 32.00

        kiln_run = validate_success(api.create_kiln_run(kiln_payload, env["operator"]), 201)
        assert kiln_run["status"] == "SCHEDULED"
        assert kiln_run["loaded_units"] == 0

    def test_the_gate_is_read_per_body_not_per_plant(self, api, clock):
        """
        At a plant holding one QUALIFIED and one DRAFT body, only the draft is refused.

        Section 3.3 and section 3.4 both key the check on "the named formulation",
        not on the plant: the plant here is ACTIVE and has a perfectly usable body,
        so the only difference between the refused and the accepted call is which
        formulation_id the payload names.

        Design: Difficulty/cross_entity_state_dependency/production_run_and_kiln_run_creation_require_qualified_formulation
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        good_body = env["formulation"]
        assert good_body["status"] == "QUALIFIED"

        draft_body = fx.create_draft_formulation(api, plant_id)
        draft_body = fx.add_components(
            api,
            draft_body,
            [(env["clay_pit"]["id"], 50.00), (env["shale_pit"]["id"], 50.00)],
        )
        assert draft_body["status"] == "DRAFT"
        assert draft_body["component_share_total_pct"] == 100.00

        operator = env["operator"]
        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    plant_id, draft_body["id"], env["kiln_car"]["id"]
                ),
                operator,
            ),
            ERR_FORMULATION_NOT_QUALIFIED,
            409,
        )
        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(env["kiln"]["id"], draft_body["id"]), operator
            ),
            ERR_FORMULATION_NOT_QUALIFIED,
            409,
        )

        run = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    plant_id, good_body["id"], env["kiln_car"]["id"]
                ),
                operator,
            ),
            201,
        )
        assert run["status"] == "SETTING"
        assert run["formulation_id"] == good_body["id"]

        kiln_run = validate_success(
            api.create_kiln_run(
                F.kiln_run_payload(env["kiln"]["id"], good_body["id"]), operator
            ),
            201,
        )
        assert kiln_run["status"] == "SCHEDULED"

        pits = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == [16.00, 16.00]


class TestPanelApprovalWindowGatesCertification:
    """
    Section 3.6: "An approval is good for that 180-day window and no longer. When a
    certification looks at an APPROVED panel and finds the logical clock at or past
    expires_at, the panel moves APPROVED to EXPIRED and the certification that
    observed the expiry is rejected with ERR_PANEL_APPROVAL_EXPIRED."
    """

    def _composed_blend_on_approved_panel(self, api):
        env = fx.build_fired_lot(api, clock=None)
        order = fx.build_assigned_order(api, requires_panel_approval=True)
        panel = fx.build_approved_panel(
            api, order["id"], env["formulation"]["id"], env["fired_lot"]["id"], 52.00
        )
        blend = fx.build_composed_blend(api, order, [(env["fired_lot"]["id"], 9600)])
        env["order"] = order
        env["panel"] = panel
        env["blend"] = blend
        return env

    def test_the_clock_exactly_on_expires_at_is_already_too_late(self, api, clock):
        """
        A clock standing on expires_at expires the panel and refuses the certification.

        Section 3.6: "The boundary is inclusive: a clock reading exactly expires_at
        expires the panel, while a clock one second earlier does not", and section
        3.7 requires a panel "whose expires_at is strictly after the current logical
        clock (ERR_PANEL_APPROVAL_EXPIRED)". The panel's own tolerance is not the
        cause: at 52.00 approved against a 52.18 blend, panel_delta_e is 0.18,
        inside the 1.00 tolerance.

        Design: Difficulty/cross_entity_state_dependency/blend_certify_blocked_by_expired_panel_approval_despite_approved_status
        """
        env = self._composed_blend_on_approved_panel(api)
        assert env["panel"]["status"] == "APPROVED"
        assert env["panel"]["approved_at"] == "2026-08-01T00:00:00Z"
        assert env["panel"]["expires_at"] == "2027-01-28T00:00:00Z"
        assert env["blend"]["status"] == "COMPOSED"
        assert env["blend"]["weighted_color_index"] == 52.18

        fx.set_clock(api, "2027-01-28T00:00:00Z")
        validate_error(
            api.certify_blend(env["blend"]["id"], QUALITY_MANAGER),
            ERR_PANEL_APPROVAL_EXPIRED,
            422,
        )

        expired = validate_success(
            api.get_sample_panel(env["panel"]["id"], QUALITY_MANAGER)
        )
        assert expired["status"] == "EXPIRED"

        blend_after = validate_success(api.get_blend(env["blend"]["id"], QUALITY_MANAGER))
        assert blend_after["status"] == "COMPOSED"
        assert blend_after["certified_at"] is None

    def test_one_second_before_expiry_the_same_certification_succeeds(self, api, clock):
        """
        At 2027-01-27T23:59:59Z the approval still stands and the blend certifies.

        Section 3.6: "a clock one second earlier does not" expire the panel. Section
        3.7 stamps `certified_at` from the logical clock and writes `panel_delta_e`
        as "the absolute difference between the blend's weighted_color_index and the
        panel's approved_color_index, rounded half up to two decimal places".

        Design: Difficulty/cross_entity_state_dependency/blend_certify_blocked_by_expired_panel_approval_despite_approved_status
        """
        env = self._composed_blend_on_approved_panel(api)

        fx.set_clock(api, "2027-01-27T23:59:59Z")
        certified = validate_success(
            api.certify_blend(env["blend"]["id"], QUALITY_MANAGER)
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] == "2027-01-27T23:59:59Z"
        assert certified["panel_delta_e"] == 0.18

        still_approved = validate_success(
            api.get_sample_panel(env["panel"]["id"], QUALITY_MANAGER)
        )
        assert still_approved["status"] == "APPROVED"
