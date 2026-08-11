"""Grant assets: useful-life service credit and the two disposal-payback variants
(PRD §2.4, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_grant_asset, assert_money, assert_asset_value_conserved,
    register_asset, request_disposal,
    setup_active_grant, set_clock,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestDisposalPaybackVariants:
    def _setup_two_assets(self):
        """ACTIVE grant (federal pct 0.90) with an EQUIPMENT asset and a LAND asset, both
        share 100,000 / life 10 / in service 2020-05-01, both DISPOSAL_REQUESTED."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        eq = register_asset(grant_id, asset_kind="EQUIPMENT", description="Sweeper",
                            acquisition_federal_share=100_000, useful_life_years=10,
                            in_service_date="2020-05-01T00:00:00Z")
        lnd = register_asset(grant_id, asset_kind="LAND", description="Parcel 7",
                             acquisition_federal_share=100_000, useful_life_years=10,
                             in_service_date="2020-05-01T00:00:00Z")
        request_disposal(eq["id"])
        request_disposal(lnd["id"])
        return ctx, eq, lnd

    def test_disposal_payback_equipment_straight_line(self):
        """PRD §3.9: "For `EQUIPMENT`, the straight-line variant sets `payback_due` to
        `acquisition_federal_share` prorated by the remaining years over `useful_life_years`,
        rounded half-up to two decimal places — book-value amortization of the original
        federal share."
        Elapsed 6 of 10 years -> remaining 4 -> payback 100,000 x 4/10 = 40,000.00.

        Design: Difficulty/dual_variant_calc/disposal_payback_straightline_vs_fmv
        """
        _, eq, _ = self._setup_two_assets()
        disposed = validate_success(api_client.approve_disposal(eq["id"], FAA), 200)
        assert_grant_asset(disposed)
        assert disposed["status"] == "DISPOSED"
        assert_money(disposed["payback_due"], 40_000.00, "payback_due")

    def test_disposal_payback_land_fair_market(self):
        """PRD §3.9: "For `LAND`, the fair-market variant sets `payback_due` to the supplied
        `fair_market_value` multiplied by the grant's current `federal_share_pct` and
        prorated by the remaining years over `useful_life_years`, rounded half-up to two
        decimal places — so the payback tracks current market value rather than original
        cost whenever the two diverge."
        300,000 x 0.90 x 4/10 = 108,000.00 — diverging from the 40,000.00 book value of the
        identical EQUIPMENT asset.

        Design: Difficulty/dual_variant_calc/disposal_payback_straightline_vs_fmv
        """
        _, _, lnd = self._setup_two_assets()
        disposed = validate_success(api_client.approve_disposal(
            lnd["id"], FAA, {"fair_market_value": 300_000}), 200)
        assert disposed["status"] == "DISPOSED"
        assert_money(disposed["payback_due"], 108_000.00, "payback_due")


class TestDisposalBoundary:
    def test_disposal_at_full_useful_life_zero_payback(self):
        """PRD §3.9: "In both variants the remaining years are `useful_life_years` minus the
        capped elapsed years, and once no useful life remains the payback is exactly 0.00."

        Design: Difficulty/boundary_precision_check/disposal_at_full_useful_life
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Old sweeper",
                               acquisition_federal_share=100_000, useful_life_years=10,
                               in_service_date="2016-05-01T00:00:00Z")
        request_disposal(asset["id"])
        disposed = validate_success(api_client.approve_disposal(asset["id"], FAA), 200)
        assert disposed["status"] == "DISPOSED"
        assert_money(disposed["payback_due"], 0.00, "payback_due")

    def test_disposal_at_full_useful_life_full_credit(self):
        """PRD §3.9: "elapsed service is the whole days between `in_service_date` and the
        clock, divided by 365 and rounded down to whole years, capped at `useful_life_years`;
        `service_credit_value` is `acquisition_federal_share` prorated by elapsed years over
        `useful_life_years`, rounded half-up to two decimal places".
        3,652 days floor to 10 years = the full life -> the entire 100,000.00 share is
        credited and nothing remains restricted.

        Design: Difficulty/boundary_precision_check/disposal_at_full_useful_life
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Old sweeper",
                               acquisition_federal_share=100_000, useful_life_years=10,
                               in_service_date="2016-05-01T00:00:00Z")
        request_disposal(asset["id"])
        disposed = validate_success(api_client.approve_disposal(asset["id"], FAA), 200)
        assert_money(disposed["service_credit_value"], 100_000.00, "service_credit_value")
        assert_money(disposed["remaining_restricted_value"], 0.00,
                     "remaining_restricted_value")


class TestReturnToService:
    def _setup_returned_asset(self):
        """EQUIPMENT asset (share 50,000, life 8, in service 2024-05-01) taken through
        request-disposal and back to service."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Mower", acquisition_federal_share=50_000,
                               useful_life_years=8,
                               in_service_date="2024-05-01T00:00:00Z")
        requested = request_disposal(asset["id"])
        assert requested["status"] == "DISPOSAL_REQUESTED"
        returned = validate_success(api_client.return_to_service(asset["id"], SPONSOR), 200)
        return returned

    def test_asset_return_to_service_restores_in_service(self):
        """PRD §3.9: "A sponsor that thinks better of a pending disposal instead returns the
        asset to service, moving `DISPOSAL_REQUESTED` back to `IN_SERVICE`; `payback_due`
        stays 0 and the federal restriction simply continues to run."

        Design: Difficulty/non_linear_state_machine/asset_disposal_return_to_service_cycle
        """
        asset = self._setup_returned_asset()
        assert asset["status"] == "IN_SERVICE"
        assert_money(asset["payback_due"], 0.00, "payback_due")

    def test_asset_return_to_service_keeps_restriction_ledger(self):
        """PRD §3.9: "elapsed service is the whole days between `in_service_date` and the
        clock, divided by 365 and rounded down to whole years, capped at
        `useful_life_years`".
        731 days floor to 2 of 8 years -> credit 12,500.00 and remaining 37,500.00 survive
        the disposal loop untouched.

        Design: Difficulty/non_linear_state_machine/asset_disposal_return_to_service_cycle
        """
        asset = self._setup_returned_asset()
        assert_money(asset["service_credit_value"], 12_500.00, "service_credit_value")
        assert_money(asset["remaining_restricted_value"], 37_500.00,
                     "remaining_restricted_value")
        assert_asset_value_conserved(asset)


class TestAssetValueConservation:
    def test_asset_value_conservation_in_service(self):
        """PRD §3.9: "`remaining_restricted_value` is the exact remainder of
        `acquisition_federal_share` minus `service_credit_value`".
        At the 2026-05-01 clock, 2,191 days floor to 6 of 10 years: credit 60,000.00 +
        remaining 40,000.00 == share 100,000.00.

        Design: Difficulty/compensating_invariant/asset_value_conservation
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Sweeper", acquisition_federal_share=100_000,
                               useful_life_years=10,
                               in_service_date="2020-05-01T00:00:00Z")
        assert_grant_asset(asset)
        assert_money(asset["service_credit_value"], 60_000.00, "service_credit_value")
        assert_money(asset["remaining_restricted_value"], 40_000.00,
                     "remaining_restricted_value")
        assert_asset_value_conserved(asset)

    def test_asset_value_conservation_at_disposal(self):
        """PRD §3.9: "Approval fixes `payback_due` by variant and zeroes
        `remaining_restricted_value` as the asset moves to the terminal `DISPOSED`."
        The EQUIPMENT straight-line payback equals the pre-disposal restricted remainder:
        credit 60,000.00 + payback 40,000.00 == share 100,000.00, with no drift.

        Design: Difficulty/compensating_invariant/asset_value_conservation
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Sweeper", acquisition_federal_share=100_000,
                               useful_life_years=10,
                               in_service_date="2020-05-01T00:00:00Z")
        remaining_before = asset["remaining_restricted_value"]
        request_disposal(asset["id"])
        disposed = validate_success(api_client.approve_disposal(asset["id"], FAA), 200)
        assert_money(disposed["payback_due"], remaining_before,
                     "payback_due == pre-disposal remaining_restricted_value")
        assert_money(disposed["remaining_restricted_value"], 0.00,
                     "remaining_restricted_value")
        assert disposed["service_credit_value"] + disposed["payback_due"] == pytest.approx(
            disposed["acquisition_federal_share"], abs=0.005)


class TestDisposalGuards:
    def test_land_disposal_without_fmv_rejected(self):
        """PRD §3.9: "for a `LAND` asset the request must carry a `fair_market_value`, and
        its absence is rejected with `ERR_FMV_REQUIRED` (HTTP 422)."
        The EQUIPMENT variant needs no market input and disposes cleanly.

        Design: Corner/validations/land_disposal_without_fmv_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        lnd = register_asset(grant_id, asset_kind="LAND", description="Parcel 7",
                             acquisition_federal_share=100_000, useful_life_years=10,
                             in_service_date="2020-05-01T00:00:00Z")
        eq = register_asset(grant_id, asset_kind="EQUIPMENT", description="Sweeper",
                            acquisition_federal_share=100_000, useful_life_years=10,
                            in_service_date="2020-05-01T00:00:00Z")
        request_disposal(lnd["id"])
        request_disposal(eq["id"])

        res = api_client.approve_disposal(lnd["id"], FAA)
        validate_error(res, ApiErrorId.ERR_FMV_REQUIRED, expected_status=422)

        disposed = validate_success(api_client.approve_disposal(eq["id"], FAA), 200)
        assert disposed["status"] == "DISPOSED"
        assert_money(disposed["payback_due"], 40_000.00, "payback_due")


class TestServiceCreditComputation:
    def test_asset_credit_floor_semantics(self):
        """PRD §3.9: "elapsed service is the whole days between `in_service_date` and the
        clock, divided by 365 and rounded down to whole years, capped at
        `useful_life_years`; `service_credit_value` is `acquisition_federal_share` prorated
        by elapsed years over `useful_life_years`, rounded half-up to two decimal places".
        1,795 days (2021-06-01 -> 2026-05-01) floor to 4 years, not 5: 80,000 x 4/8 =
        40,000.00.

        Design: Corner/calculations/asset_credit_floor_semantics
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_active_grant()
        asset = register_asset(ctx["grant"]["id"], asset_kind="EQUIPMENT",
                               description="Loader", acquisition_federal_share=80_000,
                               useful_life_years=8,
                               in_service_date="2021-06-01T00:00:00Z")
        assert_money(asset["service_credit_value"], 40_000.00, "service_credit_value")
        assert_money(asset["remaining_restricted_value"], 40_000.00,
                     "remaining_restricted_value")
