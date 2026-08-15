"""Domestic content determination and claim certification (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_operation_spec,
    add_trim_requirement,
    api_client,
    approve_tech_pack,
    create_draft_tech_pack,
    create_production_order,
    create_style,
    create_trim_item,
    get_style,
    get_success_data,
    submit_tech_pack,
    validate_error,
)

MERCH = TEST_USERS["merchandiser_headers"]
PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ANY = TEST_USERS["any_headers"]


def _content_style_with_bom():
    """Style ST-CC1 + trims BTN-US (10c) / ZIP-CN (200c) + approved pack v1
    (labor 800, fabric 500) with both trims at 1/garment, wastage 0."""
    style = create_style(
        style_code="ST-CC1", size_run=["M"], declared_fabric_domestic=True,
        target_content_claim="NONE",
    )
    ti_btn = create_trim_item(sku_code="BTN-US", description="button",
                              origin_country="US", unit_cost_cents=10)
    ti_zip = create_trim_item(sku_code="ZIP-CN", description="zipper",
                              origin_country="CN", unit_cost_cents=200)
    pack = create_draft_tech_pack(style["id"], MERCH)
    add_operation_spec(pack["id"], MERCH)
    add_trim_requirement(pack["id"], ti_btn["id"], MERCH, units_per_garment=1, wastage_pct=0)
    add_trim_requirement(pack["id"], ti_zip["id"], MERCH, units_per_garment=1, wastage_pct=0)
    pack = approve_tech_pack(pack["id"], PM)
    return get_style(style["id"]), pack


class TestDomesticContentDualBasis:
    def test_domestic_content_cost_basis_vs_unit_basis_values(self):
        """PRD §3.2: "`domestic_content_pct_cost` is the domestic cost divided
        by the total cost, rounded half up to four decimal places" and
        "`domestic_component_ratio` is that quotient, rounded half up to four
        decimal places."

        Design: Difficulty/dual_variant_calc/domestic_content_cost_basis_vs_unit_basis
        """
        style, _pack = _content_style_with_bom()
        # cost basis: domestic = 10 (button) + 500 (fabric) + 800 (labor) = 1310;
        # total = 1310 + 200 (zipper) = 1510 -> 1310/1510 = 0.8675
        assert style["domestic_content_pct_cost"] == pytest.approx(0.8675, abs=1e-9)
        # unit basis: 2 domestic components (button + fabric) of 3 -> 0.6667
        assert style["domestic_component_ratio"] == pytest.approx(0.6667, abs=1e-9)

    def test_domestic_content_qualification_and_certify_rejection(self):
        """PRD §3.2: "the style is `QUALIFIED_STRICT` when
        `domestic_component_ratio` is exactly 1.0; otherwise it is
        `QUALIFIED_COST_ONLY` when `domestic_content_pct_cost` is at least
        0.70; otherwise `NOT_QUALIFIED`." and "the recomputed
        `content_qualification` must be `QUALIFIED_STRICT`, or the attempt is
        rejected with `ERR_NOT_CERTIFIABLE` (HTTP 409)."

        Design: Difficulty/dual_variant_calc/domestic_content_cost_basis_vs_unit_basis
        """
        style, _pack = _content_style_with_bom()
        assert style["content_qualification"] == "QUALIFIED_COST_ONLY"
        resp = api_client.certify_content_claim(style["id"], PM)
        validate_error(resp, ApiErrorId.ERR_NOT_CERTIFIABLE)

    def test_certification_success_when_qualified_strict(self):
        """PRD §3.2: "A successful certification sets `certification_status`
        to `CERTIFIED`, stamps `certified_by_user_id` from the caller, and
        increments the style's `version`."

        Design: Corner/state_machines/certification_revoked_on_pack_supersede
        """
        style = create_style(
            style_code="ST-S10", declared_fabric_domestic=True,
            target_content_claim="MADE_IN_USA",
        )
        ti_btn = create_trim_item(sku_code="BTN-US", description="button",
                                  origin_country="US", unit_cost_cents=10)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti_btn["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        approve_tech_pack(pack["id"], PM)
        style = get_style(style["id"])
        assert style["content_qualification"] == "QUALIFIED_STRICT"
        style = get_success_data(api_client.certify_content_claim(style["id"], PM))
        assert style["certification_status"] == "CERTIFIED"
        assert style["certified_by_user_id"] == "u-pm1"


class TestCertificationRevokedOnPackSupersede:
    def _certified_style_then_supersede_with_foreign_zip(self):
        style = create_style(
            style_code="ST-S10", declared_fabric_domestic=True,
            target_content_claim="MADE_IN_USA",
        )
        ti_btn = create_trim_item(sku_code="BTN-US", description="button",
                                  origin_country="US", unit_cost_cents=10)
        ti_zip = create_trim_item(sku_code="ZIP-CN", description="zipper",
                                  origin_country="CN", unit_cost_cents=200)
        pack_a = create_draft_tech_pack(style["id"], MERCH, version_no=1)
        add_operation_spec(pack_a["id"], MERCH)
        add_trim_requirement(pack_a["id"], ti_btn["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        approve_tech_pack(pack_a["id"], PM)
        get_success_data(api_client.certify_content_claim(style["id"], PM))
        pack_b = create_draft_tech_pack(style["id"], MERCH, version_no=2)
        add_operation_spec(pack_b["id"], MERCH)
        add_trim_requirement(pack_b["id"], ti_btn["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        add_trim_requirement(pack_b["id"], ti_zip["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        submit_tech_pack(pack_b["id"], MERCH)
        style_now = get_style(style["id"])
        assert style_now["certification_status"] == "CERTIFIED"
        return style_now, pack_b

    def test_certification_revoked_when_new_pack_breaks_strict_qualification(self):
        """PRD §3.2: "When a pack approval re-points `active_tech_pack_id` and
        the recomputed `content_qualification` is not `QUALIFIED_STRICT`, a
        style that was `CERTIFIED` automatically transitions to `REVOKED`:
        `certified_by_user_id` is cleared to null".

        Design: Corner/state_machines/certification_revoked_on_pack_supersede
        """
        style_now, pack_b = self._certified_style_then_supersede_with_foreign_zip()
        get_success_data(api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": style_now["version"]},
            PM,
        ))
        style_after = get_style(style_now["id"])
        assert style_after["certification_status"] == "REVOKED"
        assert style_after["certified_by_user_id"] is None
        assert style_after["active_tech_pack_id"] == pack_b["id"]
        assert style_after["domestic_component_ratio"] == pytest.approx(0.6667, abs=1e-9)
        assert style_after["content_qualification"] == "QUALIFIED_COST_ONLY"

    def test_recertify_after_revocation_rejected_until_strict(self):
        """PRD §3.2: "the recomputed `content_qualification` must be
        `QUALIFIED_STRICT`, or the attempt is rejected with
        `ERR_NOT_CERTIFIABLE` (HTTP 409)."

        Design: Corner/state_machines/certification_revoked_on_pack_supersede
        """
        style_now, pack_b = self._certified_style_then_supersede_with_foreign_zip()
        get_success_data(api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": style_now["version"]},
            PM,
        ))
        resp = api_client.certify_content_claim(style_now["id"], PM)
        validate_error(resp, ApiErrorId.ERR_NOT_CERTIFIABLE)


class TestPlanContentClaimSafety:
    def test_plan_claim_safety_beats_pack_referential(self):
        """PRD §2.6: "Planning an order runs the content-claim safety check
        (step 7) before the candidate pack's approval check (step 8), so a
        violation surfaces as `ERR_CONTENT_CLAIM_VIOLATION` even when the
        candidate pack has never been approved."

        Design: Difficulty/priority_pair_validation_conflict/plan_claim_safety_beats_pack_referential
        """
        style = create_style(
            style_code="ST-PV2", declared_fabric_domestic=False,
            target_content_claim="MADE_IN_USA",
        )
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        submit_tech_pack(pack["id"], MERCH)
        get_success_data(api_client.review_tech_pack(
            pack["id"],
            {"decision": "REJECT", "expected_style_version": style["version"]},
            PM,
        ))
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        resp = api_client.plan_production_order(
            order["id"], {"tech_pack_id": pack["id"]}, PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTENT_CLAIM_VIOLATION)
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["tech_pack_id"] is None
        assert order_after["trim_hold_status"] == "MATERIALS_OK"

    def test_plan_under_made_in_usa_style_with_foreign_trim_rejected(self):
        """PRD §3.4: "when the style's `target_content_claim` is `MADE_IN_USA`,
        the style's `declared_fabric_domestic` must be true and every trim
        requirement of the candidate pack must reference a `TrimItem` whose
        `origin_country` is `US` ... a violation is rejected with
        `ERR_CONTENT_CLAIM_VIOLATION` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/plan_claim_safety_beats_pack_referential
        """
        style = create_style(
            style_code="ST-PV3", declared_fabric_domestic=True,
            target_content_claim="MADE_IN_USA",
        )
        ti_zip = create_trim_item(sku_code="ZIP-CN", description="zipper",
                                  origin_country="CN", unit_cost_cents=200)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti_zip["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        approve_tech_pack(pack["id"], PM)
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        resp = api_client.plan_production_order(
            order["id"], {"tech_pack_id": pack["id"]}, PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTENT_CLAIM_VIOLATION)
