"""License position gap analysis: dual exposure variants, severity ladder, ratio
boundaries, and the non-production input filter (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_license_position,
    confirm_deployment,
    create_confirmed_deployment,
    create_deployment,
    create_entitlement,
    create_product,
    create_vendor,
    create_vendor_and_product,
    get_license_position,
    list_product_alerts,
    recalculate_position,
    setup_product_with_gap,
    validate_error,
    validate_success,
)


class TestDualExposureVariants:
    def test_position_self_audit_exposure_priced_at_bare_list(self, api,
                                                              sam_manager_headers):
        """PRD §3.4: "`self_audit_exposure_cents` is the provisional, customer-side
        basis used before and during vendor engagement: the positive part of the gap
        (zero when the gap is not positive) multiplied by `unit_list_price_cents`,
        with no maintenance uplift."
        PRD §3.4: "The gap itself is `gap_quantity`, the deployed quantity minus the
        entitled quantity; a positive value means over-deployment."

        Design: Difficulty/dual_variant_calc/position_exposure_self_audit_vs_vendor_list
        """
        ctx = setup_product_with_gap(entitled=100, deployed=130,
                                     unit_list_price_cents=10000,
                                     support_rate_pct=0.22)
        position = recalculate_position(ctx["position"]["id"])
        assert_license_position(position)
        assert position["gap_quantity"] == 30, "130 deployed minus 100 entitled"
        assert position["self_audit_exposure_cents"] == 300000, \
            "30 missing units priced at the bare 10000-cent list price"

    def test_position_vendor_list_exposure_includes_support_uplift(
            self, api, sam_manager_headers):
        """PRD §3.4: "`vendor_list_exposure_cents` is the pessimistic basis used for
        worst-case planning while no vendor finding is recorded: the per-unit factor
        is first computed as `unit_list_price_cents` increased by the
        `support_rate_pct` fraction of itself — one year of back-support per missing
        unit — rounded half up to whole cents, and that rounded factor is then
        multiplied by the positive part of the gap."

        Design: Difficulty/dual_variant_calc/position_exposure_self_audit_vs_vendor_list
        """
        ctx = setup_product_with_gap(entitled=100, deployed=130,
                                     unit_list_price_cents=10000,
                                     support_rate_pct=0.22)
        position = recalculate_position(ctx["position"]["id"])
        assert_license_position(position)
        # round_half_up(10000 * 1.22) = 12200 per unit; 12200 * 30 = 366000.
        assert position["vendor_list_exposure_cents"] == 366000
        assert position["gap_severity"] == "CRITICAL", \
            "deployed/entitled ratio 1.3 is at least 1.25"
        assert position["position_basis"] == "SELF_AUDIT", \
            "no vendor finding has been recorded"


class TestGapSeverityTiering:
    def test_gap_severity_material_below_mission_critical_quantity(
            self, api, sam_manager_headers):
        """PRD §3.4: "Severity is assigned by evaluating the following ladder in
        order and stopping at the first matching rung: if the gap is zero or
        negative, `gap_severity` is `COMPLIANT`; otherwise, if the entitled quantity
        is zero, `CRITICAL`; otherwise, if the product is `mission_critical` and the
        gap is at least 25 units, `CRITICAL`; otherwise, if the ratio of deployed to
        entitled is at least 1.25 or the gap is at least 100 units, `CRITICAL`;
        otherwise, if the ratio of deployed to entitled is strictly greater than
        1.05 or the gap is at least 10 units, `MATERIAL`; otherwise `MINOR`."

        Design: Difficulty/combinatorial_formula/gap_severity_three_input_tiering
        """
        ctx = setup_product_with_gap(
            entitled=200, unit_list_price_cents=10000, support_rate_pct=0.22,
            license_metric="PER_CORE", mission_critical=True,
            deployment_quantities=[(124, "PRODUCTION"), (100, "PRODUCTION")])
        position = ctx["position"]
        assert position["gap_quantity"] == 24
        assert position["gap_severity"] == "MATERIAL", \
            "gap 24 with ratio 1.12: mission-critical CRITICAL rung needs gap >= 25; " \
            "ratio 1.12 > 1.05 lands on MATERIAL"

    def test_gap_severity_mission_critical_fires_at_25(self, api, sam_manager_headers):
        """PRD §3.4: "otherwise, if the product is `mission_critical` and the gap is
        at least 25 units, `CRITICAL`"
        PRD §3.4: "Ratio comparisons use exact decimal arithmetic with no
        floating-point drift, so a ratio of exactly 1.05 is not material — the
        comparison there is strictly greater — while a ratio of exactly 1.25 is
        critical."

        Design: Difficulty/combinatorial_formula/gap_severity_three_input_tiering
        """
        ctx = setup_product_with_gap(
            entitled=200, unit_list_price_cents=10000, support_rate_pct=0.22,
            license_metric="PER_CORE", mission_critical=True,
            deployment_quantities=[(124, "PRODUCTION"), (100, "PRODUCTION")])
        assert ctx["position"]["gap_severity"] == "MATERIAL"

        extra = create_deployment(ctx["product"]["id"], measured_quantity=1,
                                  measurement_method="MANUAL_DECLARATION",
                                  measured_on="2026-07-16T00:00:00Z")
        confirm_deployment(extra["id"])
        position = recalculate_position(ctx["position"]["id"])
        assert position["deployed_quantity"] == 225
        assert position["gap_quantity"] == 25
        assert position["gap_severity"] == "CRITICAL", \
            "mission_critical with gap 25 fires CRITICAL although ratio 1.125 < 1.25"


class TestGapRatioGraceBoundary:
    def test_gap_ratio_exactly_at_grace_boundary_stays_minor(self, api,
                                                             sam_manager_headers):
        """PRD §3.4: "Ratio comparisons use exact decimal arithmetic with no
        floating-point drift, so a ratio of exactly 1.05 is not material — the
        comparison there is strictly greater — while a ratio of exactly 1.25 is
        critical."

        Design: Difficulty/boundary_precision_check/gap_ratio_grace_boundary_105
        """
        ctx = setup_product_with_gap(entitled=100, deployed=105)
        position = ctx["position"]
        assert position["gap_quantity"] == 5
        assert position["gap_severity"] == "MINOR", \
            "ratio exactly 1.05 is not strictly greater than 1.05, and gap 5 < 10"

    def test_gap_ratio_one_tick_above_grace_boundary_is_material(
            self, api, sam_manager_headers):
        """PRD §3.4: "otherwise, if the ratio of deployed to entitled is strictly
        greater than 1.05 or the gap is at least 10 units, `MATERIAL`"
        PRD §3.4: "Ratio comparisons use exact decimal arithmetic with no
        floating-point drift, so a ratio of exactly 1.05 is not material — the
        comparison there is strictly greater — while a ratio of exactly 1.25 is
        critical."

        Design: Difficulty/boundary_precision_check/gap_ratio_grace_boundary_105
        """
        ctx = setup_product_with_gap(entitled=100, deployed=105)
        assert ctx["position"]["gap_severity"] == "MINOR"

        extra = create_deployment(ctx["product"]["id"], measured_quantity=1,
                                  measurement_method="MANUAL_DECLARATION",
                                  measured_on="2026-07-16T00:00:00Z")
        confirm_deployment(extra["id"])
        position = recalculate_position(ctx["position"]["id"])
        assert position["deployed_quantity"] == 106
        assert position["gap_severity"] == "MATERIAL", "ratio 1.06 > 1.05"


class TestDeployedQuantityInputSet:
    def test_non_production_excluded_unless_product_flag(self, api, admin_headers,
                                                         sam_manager_headers):
        """PRD §3.4: "Its `deployed_quantity` is the sum of `measured_quantity` over
        the product's deployment records in `CONFIRMED` status whose `environment`
        is `PRODUCTION`, plus the `CONFIRMED` records whose `environment` is
        `NON_PRODUCTION` only when the product's `counts_non_production` flag is
        true; `REPORTED`, `REJECTED`, and `EXCLUDED` records never contribute."
        PRD §3.1: "A `SAMPlatformAdmin` may update a product's `name`,
        `unit_list_price_cents`, `support_rate_pct`, `mission_critical`, or
        `counts_non_production`; because exposures are priced from these fields,
        such an update recomputes the product's position, the rollups of every audit
        case scoping the product, and the product's monitoring alerts, following the
        cascade rules of §2.8."

        Design: Corner/calculations/non_production_excluded_unless_product_flag
        """
        ctx = setup_product_with_gap(
            entitled=100, unit_list_price_cents=5000, support_rate_pct=0.2,
            license_metric="PER_USER",
            deployment_quantities=[(100, "PRODUCTION"), (50, "NON_PRODUCTION")])
        position = ctx["position"]
        assert position["deployed_quantity"] == 100, \
            "the NON_PRODUCTION 50 are excluded while counts_non_production is false"
        assert position["gap_quantity"] == 0

        patched = validate_success(
            api.patch_product(ctx["product"]["id"], {"counts_non_production": True},
                              admin_headers), 200)
        assert patched["counts_non_production"] is True

        recomputed = recalculate_position(position["id"])
        assert recomputed["deployed_quantity"] == 150, \
            "flipping the flag recomputes the input set"
        assert recomputed["gap_quantity"] == 50


class TestZeroGap:
    def test_over_deployment_alert_not_raised_at_zero_gap(self, api,
                                                          sam_manager_headers):
        """PRD §3.9: "`OVER_DEPLOYMENT` fires whenever a position recompute finds
        `gap_quantity` strictly greater than zero — a gap of exactly zero does not
        trigger it — and its `severity` mirrors the position's `gap_severity`:
        `MINOR` maps to `INFO`, `MATERIAL` to `WARNING`, and `CRITICAL` to
        `CRITICAL`."
        PRD §3.4: "Severity is assigned by evaluating the following ladder in order
        and stopping at the first matching rung: if the gap is zero or negative,
        `gap_severity` is `COMPLIANT`"

        Design: Corner/calculations/over_deployment_alert_not_raised_at_zero_gap
        """
        ctx = setup_product_with_gap(entitled=100, deployed=100)
        position = ctx["position"]
        assert position["gap_quantity"] == 0
        assert position["gap_severity"] == "COMPLIANT"

        alerts = list_product_alerts(ctx["product"]["id"])
        assert alerts == [], "no OVER_DEPLOYMENT row exists at gap == 0"


class TestPositionReadErrors:
    def test_license_position_not_found_on_recalculate(self, api, sam_manager_headers):
        """PRD §3.4: "Reading a product's position returns an array of length zero
        or one, since exactly one position exists per product; unknown position
        identifiers surface as `ERR_LICENSE_POSITION_NOT_FOUND`."

        Design: Corner/errors/license_position_not_found_on_recalculate
        """
        resp = api.recalculate_license_position(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LICENSE_POSITION_NOT_FOUND)

    def test_vendor_auditor_cannot_read_license_positions(self, api,
                                                          vendor_auditor_headers):
        """PRD §2.1: "The `VendorAuditor` is an external party with a narrower
        window: it may read audit cases, scope items, and settlement offers, and it
        sees only `RELEASED` rows when listing a case's data submissions through a
        server-side filter; every other read attempted by the auditor is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/vendor_auditor_cannot_read_license_positions
        """
        _vendor, product = create_vendor_and_product()
        resp = api.list_license_positions(product["id"], vendor_auditor_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
