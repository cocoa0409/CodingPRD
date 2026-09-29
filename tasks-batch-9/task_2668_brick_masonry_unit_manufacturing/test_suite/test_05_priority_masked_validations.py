"""
Requests that break two rules at once. The precedence ladder of section 2.5 decides
which rejection the client is told about, and the masked rule must still be there
once the higher one is satisfied.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BAND_COUNT_INSUFFICIENT,
    ERR_BLEND_NOT_CERTIFIED,
    ERR_BLEND_NOT_COMPOSED,
    ERR_PALLET_COUNT_INSUFFICIENT,
    ERR_PANEL_NOT_APPROVED,
)
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    LOGISTICS_COORDINATOR,
    QUALITY_MANAGER,
    SALES_REP,
)


class TestCertifyBlendStateMasksPanelApproval:
    """
    Section 3.7 rejects certification of a blend that "is not COMPOSED" with
    ERR_BLEND_NOT_COMPOSED, and only a COMPOSED blend reaches the panel checks that
    raise ERR_PANEL_NOT_APPROVED. Section 2.5 ranks the state check above the panel
    check, so a draft blend on an unapproved panel reports the state.
    """

    def _draft_blend_env(self, api):
        env = fx.build_fired_lot(api, clock=None)
        env["order"] = fx.build_assigned_order(api, requires_panel_approval=True)
        env["blend"] = fx.build_draft_blend_with_allocation(
            api, env["order"], [(env["fired_lot"]["id"], 9600)]
        )
        return env

    def test_the_state_error_wins_then_the_panel_error_surfaces(self, api, clock):
        """
        Certify walks the ladder: state first, then the panel, then success.

        Section 3.7: "Certifying a blend that is not COMPOSED is rejected with
        ERR_BLEND_NOT_COMPOSED", and certification requires "when the order's
        requires_panel_approval is true, that the order have a panel that is
        APPROVED (ERR_PANEL_NOT_APPROVED)". Section 3.6 sets expires_at to
        approved_at "advanced by 180 whole days".

        Design: Difficulty/priority_pair_validation_conflict/certify_on_draft_blend_returns_blend_not_composed_masking_panel_not_approved
        """
        env = self._draft_blend_env(api)
        blend = env["blend"]
        panel = fx.create_sample_panel(
            api, env["order"]["id"], env["formulation"]["id"], env["fired_lot"]["id"], 52.18
        )
        assert blend["status"] == "DRAFT"
        assert panel["status"] == "DRAFT"

        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER), ERR_BLEND_NOT_COMPOSED, 409
        )
        still_draft = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["version"] == blend["version"]

        composed = fx.compose_blend(api, blend["id"])
        assert composed["status"] == "COMPOSED"

        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER), ERR_PANEL_NOT_APPROVED, 422
        )
        still_composed = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert still_composed["status"] == "COMPOSED"
        assert still_composed["version"] == composed["version"]

        validate_success(api.submit_panel(panel["id"], BLEND_TECHNICIAN))
        approved = validate_success(api.approve_panel(panel["id"], ARCHITECT_REVIEWER))
        assert approved["status"] == "APPROVED"
        assert approved["expires_at"] == "2027-01-28T00:00:00Z"

        certified = validate_success(api.certify_blend(blend["id"], QUALITY_MANAGER))
        assert certified["status"] == "CERTIFIED"
        assert certified["panel_delta_e"] == 0.00

    def test_the_state_error_wins_even_when_the_order_has_no_panel_at_all(
        self, api, clock
    ):
        """
        With no panel on file the draft blend still reports the state error first.

        Section 3.7 pins the order of the two conditions: the blend must be
        COMPOSED, and only then must "the order have a panel that is APPROVED".
        With zero panels the panel condition is violated as plainly as it can be,
        and it still does not surface until the blend is composed.

        Design: Difficulty/priority_pair_validation_conflict/certify_on_draft_blend_returns_blend_not_composed_masking_panel_not_approved
        """
        env = self._draft_blend_env(api)
        blend = env["blend"]
        panels = validate_success(
            api.list_sample_panels(SALES_REP, params={"order_id": env["order"]["id"]})
        )
        assert panels == []

        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER), ERR_BLEND_NOT_COMPOSED, 409
        )

        fx.compose_blend(api, blend["id"])
        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER), ERR_PANEL_NOT_APPROVED, 422
        )
        order = validate_success(api.get_order(env["order"]["id"], SALES_REP))
        assert order["fulfillment_status"] == "IN_BLENDING"
        assert order["freight_status"] == "ESTIMATED"


class TestPackagingBlendStateMasksFiscalChecks:
    """
    Section 3.8 orders the packaging conditions: the order must be IN_BLENDING, its
    blend must be CERTIFIED (ERR_BLEND_NOT_CERTIFIED), and only then are the pallet
    and band counts checked.
    """

    def _composed_env(self, api):
        env = fx.build_fired_lot(api, clock=None)
        env["order"] = fx.build_assigned_order(api)
        env["blend"] = fx.build_composed_blend(
            api, env["order"], [(env["fired_lot"]["id"], 9600)]
        )
        return env

    def test_blend_not_certified_masks_the_pallet_shortfall(self, api, clock):
        """
        One pallet for 9600 units is short, but the uncertified blend is reported first.

        Section 3.8: "its shipped blend must be CERTIFIED (otherwise
        ERR_BLEND_NOT_CERTIFIED). A pallet holds 500 masonry units, so pallet_count
        multiplied by 500 must be at least the certified blend's allocated_units, or
        the request is rejected with ERR_PALLET_COUNT_INSUFFICIENT."

        Design: Difficulty/priority_pair_validation_conflict/package_with_uncertified_blend_returns_blend_not_certified_masking_pallet_shortfall
        """
        env = self._composed_env(api)
        order_id = env["order"]["id"]
        assert env["blend"]["status"] == "COMPOSED"
        assert env["blend"]["allocated_units"] == 9600

        validate_error(
            api.package_order(order_id, F.package_payload(1, 1), LOGISTICS_COORDINATOR),
            ERR_BLEND_NOT_CERTIFIED,
            409,
        )

        certified = fx.certify_blend(api, env["blend"]["id"])
        assert certified["status"] == "CERTIFIED"

        validate_error(
            api.package_order(order_id, F.package_payload(1, 1), LOGISTICS_COORDINATOR),
            ERR_PALLET_COUNT_INSUFFICIENT,
            422,
        )
        blocked = validate_success(api.get_order(order_id, SALES_REP))
        assert blocked["fulfillment_status"] == "IN_BLENDING"
        assert blocked["freight_status"] == "ESTIMATED"
        assert blocked["pallet_count"] is None

        packaged = validate_success(
            api.package_order(order_id, F.package_payload(20, 40), LOGISTICS_COORDINATOR)
        )
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["freight_status"] == "FINALIZED"
        assert packaged["final_billable_tons"] == 22.26
        assert packaged["final_base_freight_cents"] == 56095
        assert packaged["final_fuel_surcharge_cents"] == 2524
        assert packaged["final_freight_cents"] == 58619

    def test_blend_not_certified_masks_the_band_shortfall_too(self, api, clock):
        """
        Enough pallets but too few bands: the uncertified blend is still reported first.

        Section 3.8: "each pallet needs at least one band, so band_count must be at
        least pallet_count, or the request is rejected with
        ERR_BAND_COUNT_INSUFFICIENT" - a check that sits below the blend-state
        check and only surfaces once the blend is CERTIFIED.

        Design: Difficulty/priority_pair_validation_conflict/package_with_uncertified_blend_returns_blend_not_certified_masking_pallet_shortfall
        """
        env = self._composed_env(api)
        order_id = env["order"]["id"]

        validate_error(
            api.package_order(order_id, F.package_payload(20, 19), LOGISTICS_COORDINATOR),
            ERR_BLEND_NOT_CERTIFIED,
            409,
        )

        fx.certify_blend(api, env["blend"]["id"])
        validate_error(
            api.package_order(order_id, F.package_payload(20, 19), LOGISTICS_COORDINATOR),
            ERR_BAND_COUNT_INSUFFICIENT,
            422,
        )

        packaged = validate_success(
            api.package_order(order_id, F.package_payload(20, 20), LOGISTICS_COORDINATOR)
        )
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["band_count"] == 20
        assert packaged["final_billable_tons"] == 22.23
