"""
State machines that are not lines: the panel review loop that re-enters states it
has already occupied, and the order that carries two independent status columns.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PANEL_REVISION_LIMIT
from test_helpers.assertions import expected_estimated_freight, expected_final_freight
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    SALES_REP,
)


class TestSamplePanelRevisionCycle:
    """
    Section 3.6: "The review cycle is a loop rather than a line", and "That loop is
    capped at three rounds: the request that would take revision_round from 3 to 4
    is rejected with ERR_PANEL_REVISION_LIMIT."
    """

    def _panel_env(self, api):
        env = fx.build_fired_lot(api, clock=None)
        env["order"] = fx.build_assigned_order(api, requires_panel_approval=True)
        env["panel"] = fx.create_sample_panel(
            api,
            env["order"]["id"],
            env["formulation"]["id"],
            env["fired_lot"]["id"],
            52.18,
        )
        return env

    def test_the_loop_runs_three_rounds_and_the_fourth_request_is_refused(
        self, api, clock
    ):
        """
        Three submit/send-back rounds are legal; the fourth send-back is refused.

        Section 3.6: a panel moves "DRAFT to SUBMITTED (or REVISION_REQUESTED to
        SUBMITTED on a later round)", the architect's send-back moves it "SUBMITTED
        to REVISION_REQUESTED, recording a revision_note, incrementing
        revision_round by 1", and the cap rejects the round-4 request. Section 2.5
        adds that a rejected request persists nothing.

        Design: Difficulty/non_linear_state_machine/sample_panel_revision_cycle_capped_at_three_rounds
        """
        env = self._panel_env(api)
        panel_id = env["panel"]["id"]
        assert env["panel"]["status"] == "DRAFT"
        assert env["panel"]["revision_round"] == 0

        rounds = []
        for _ in range(3):
            submitted = validate_success(api.submit_panel(panel_id, BLEND_TECHNICIAN))
            assert submitted["status"] == "SUBMITTED"
            sent_back = validate_success(
                api.request_panel_revision(
                    panel_id, F.revision_payload("Tighten the range"), ARCHITECT_REVIEWER
                )
            )
            assert sent_back["status"] == "REVISION_REQUESTED"
            rounds.append(sent_back["revision_round"])

        assert rounds == [1, 2, 3]

        resubmitted = validate_success(api.submit_panel(panel_id, BLEND_TECHNICIAN))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == 3

        refused = api.request_panel_revision(
            panel_id, F.revision_payload("Round 4 - one more look"), ARCHITECT_REVIEWER
        )
        validate_error(refused, ERR_PANEL_REVISION_LIMIT, 409)

        unchanged = validate_success(api.get_sample_panel(panel_id, PLANT_ADMIN))
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["revision_round"] == 3
        assert unchanged["version"] == resubmitted["version"]

    def test_a_panel_at_the_revision_cap_is_still_approvable(self, api, clock):
        """
        Hitting the cap does not strand the panel: the architect can still approve it.

        Section 3.6: approval requires only that "the panel must be SUBMITTED, the
        acting X-User-ID must differ from submitted_by_user_id, the panel's body
        formulation must still be QUALIFIED, and the panel's fired lot must not be
        QUARANTINED" - revision_round is not one of the four conditions.

        Design: Difficulty/non_linear_state_machine/sample_panel_revision_cycle_capped_at_three_rounds
        """
        env = self._panel_env(api)
        panel_id = env["panel"]["id"]
        for _ in range(3):
            validate_success(api.submit_panel(panel_id, BLEND_TECHNICIAN))
            validate_success(
                api.request_panel_revision(
                    panel_id, F.revision_payload("Again please"), ARCHITECT_REVIEWER
                )
            )
        submitted = validate_success(api.submit_panel(panel_id, BLEND_TECHNICIAN))
        assert submitted["revision_round"] == 3

        approved = validate_success(api.approve_panel(panel_id, ARCHITECT_REVIEWER))
        assert approved["status"] == "APPROVED"
        assert approved["revision_round"] == 3
        assert approved["approved_color_index"] == 52.18
        assert approved["approved_at"] == "2026-08-01T00:00:00Z"
        assert approved["expires_at"] == "2027-01-28T00:00:00Z"


class TestOrderTwoLifecycleDimensions:
    """
    Section 3.5: an order "carries two independent lifecycle dimensions on the same
    record", which "advance on different triggers, and a given request may move
    one, the other, or both."
    """

    def test_blending_moves_fulfillment_alone_and_packaging_moves_both(self, api, clock):
        """
        Three blend-side calls leave freight_status at ESTIMATED; packaging moves both.

        Section 3.5: "opening a shipped blend on an assigned order advances
        fulfillment_status from ASSIGNED to IN_BLENDING and leaves freight_status
        exactly where it stood." Section 3.8: packaging "advances
        fulfillment_status IN_BLENDING to PACKAGED, advances freight_status
        ESTIMATED to FINALIZED in the same request".

        Design: Difficulty/non_linear_state_machine/order_fulfillment_and_freight_dimensions_advance_independently
        """
        env = fx.build_fired_lot(api, clock=None)
        order = fx.build_assigned_order(api)
        assert order["fulfillment_status"] == "ASSIGNED"
        assert order["freight_status"] == "ESTIMATED"
        assert order["estimated_freight_cents"] == 56881

        blend = fx.create_blend(api, order["id"], 9600)
        after_open = validate_success(api.get_order(order["id"], SALES_REP))
        assert after_open["fulfillment_status"] == "IN_BLENDING"
        assert after_open["freight_status"] == "ESTIMATED"

        fx.add_blend_component(api, blend, env["fired_lot"]["id"], 9600)
        composed = fx.compose_blend(api, blend["id"])
        certified = fx.certify_blend(api, blend["id"])
        assert certified["status"] == "CERTIFIED"

        after_certify = validate_success(api.get_order(order["id"], SALES_REP))
        assert after_certify["fulfillment_status"] == "IN_BLENDING"
        assert after_certify["freight_status"] == "ESTIMATED"

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(20, 40), LOGISTICS_COORDINATOR)
        )
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["freight_status"] == "FINALIZED"
        assert packaged["final_freight_cents"] == 58619
        assert packaged["freight_variance_cents"] == 1738

        assert composed["weighted_color_index"] == 52.18
        assert composed["color_range_span"] == 0.00
        assert composed["dye_lot_count"] == 1

    def test_delivery_moves_both_dimensions_to_their_terminal_states(self, api, clock):
        """
        Delivery advances fulfillment to DELIVERED and freight to INVOICED at once.

        Section 3.8: delivery "advances fulfillment_status PACKAGED to DELIVERED and
        freight_status FINALIZED to INVOICED in the same request", and "Both
        DELIVERED and INVOICED are terminal". The freight figures written at
        packaging do not move again.

        Design: Difficulty/non_linear_state_machine/order_fulfillment_and_freight_dimensions_advance_independently
        """
        env = fx.build_fired_lot(api, clock=None)
        order = fx.build_assigned_order(api)
        fx.build_certified_blend(api, order, [(env["fired_lot"]["id"], 9600)])
        packaged = fx.package_order(api, order["id"], 20, 40)
        estimate = expected_estimated_freight(9600, 60, 42)
        final = expected_final_freight(9600, 20, 40, "STEEL", 60, 42)
        assert packaged["final_freight_cents"] == final["final_freight_cents"]

        delivered = validate_success(
            api.deliver_order(order["id"], F.deliver_payload(), LOGISTICS_COORDINATOR)
        )
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["freight_status"] == "INVOICED"
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z"
        assert delivered["invoiced_at"] == "2026-08-01T00:00:00Z"
        assert delivered["final_freight_cents"] == final["final_freight_cents"]
        assert delivered["estimated_freight_cents"] == estimate["estimated_freight_cents"]
        assert delivered["freight_variance_cents"] == (
            final["final_freight_cents"] - estimate["estimated_freight_cents"]
        )
