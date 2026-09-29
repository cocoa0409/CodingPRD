"""Right-to-repair pricing parity and the activation gate it guards.

Covers the two parity bases, the behaviour of the index exactly on the 1.15
ceiling and one ten-thousandth over it, and the dependency of license
activation on the granting manufacturer's stored parity verdict.
"""

import pytest

from test_helpers import (
    PARITY_MAX_INDEX,
    ApiErrorId,
    LicenseModel,
    LicenseStatus,
    ParityBasis,
    ParityStatus,
    Region,
    assert_license,
    assert_manufacturer,
    assert_parity_report,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

OVERPRICED_OEM = {
    "name": "Overprice Motors",
    "oem_code": "OVRP",
    "region": Region.EU,
    "independent_list_monthly_cents": 150000,
    "independent_covered_system_count": 4,
    "oem_dealer_monthly_cents": 100000,
    "oem_dealer_covered_system_count": 4,
}


def _license_row(api, manufacturer_id, license_id, headers):
    rows, _meta = validate_paginated(
        api.list_manufacturer_licenses(manufacturer_id, headers, {"limit": 100})
    )
    return next(row for row in rows if row["id"] == license_id)


class TestParityBasisDivergence:
    """The persisted list-basis verdict versus the report-only effective basis."""

    def test_list_basis_report_lands_exactly_on_the_ceiling_and_is_compliant(self, api):
        """The list basis divides the two monthly prices and rounds to four places.

        PRD 3.1: "the index is the independent monthly price divided by the
        dealer monthly price, with the quotient rounded half up to four decimal
        places"; with 115,000 against 100,000 the index is 1.1500, and "an index
        landing exactly on 1.1500 is compliant". The report also echoes "the
        `threshold` against which the index was judged, which is 1.15".

        Design: Difficulty/dual_variant_calc/parity_index_list_basis_vs_effective_basis_divergence
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        manufacturer_id = ctx["manufacturer"]["id"]

        report = validate_success(
            api.get_parity_report(
                manufacturer_id,
                make_compliance_officer_headers(),
                {"basis": ParityBasis.LIST_BASIS},
            )
        )

        assert_parity_report(report)
        assert report["manufacturer_id"] == manufacturer_id
        assert report["basis"] == ParityBasis.LIST_BASIS
        assert report["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert report["parity_status"] == ParityStatus.COMPLIANT
        assert report["threshold"] == pytest.approx(PARITY_MAX_INDEX, abs=1e-9)

    def test_effective_basis_report_is_non_compliant_and_never_persisted(self, api):
        """The effective basis normalises by covered systems and 30 days.

        PRD 3.1: "the independent figure is its monthly price divided by the
        product of its covered system count and 30 days"; 115,000 over three
        systems against 100,000 over four gives 1.5333 and a `NON_COMPLIANT`
        verdict, yet "Only the list-basis verdict is ever persisted." and "The
        effective-basis verdict is report-only and is never written to the row."

        Design: Difficulty/dual_variant_calc/parity_index_list_basis_vs_effective_basis_divergence
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        manufacturer_id = ctx["manufacturer"]["id"]

        report = validate_success(
            api.get_parity_report(
                manufacturer_id,
                make_compliance_officer_headers(),
                {"basis": ParityBasis.EFFECTIVE_BASIS},
            )
        )

        assert_parity_report(report)
        assert report["basis"] == ParityBasis.EFFECTIVE_BASIS
        assert report["parity_index"] == pytest.approx(1.5333, abs=5e-5)
        assert report["parity_status"] == ParityStatus.NON_COMPLIANT
        assert report["independent_effective_cents_per_system_day"] == pytest.approx(
            115000 / (3 * 30), abs=1e-3
        )
        assert report["oem_effective_cents_per_system_day"] == pytest.approx(
            100000 / (4 * 30), abs=1e-3
        )

        stored = validate_success(
            api.get_manufacturer(manufacturer_id, make_platform_admin_headers())
        )
        assert_manufacturer(stored)
        assert stored["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert stored["parity_status"] == ParityStatus.COMPLIANT


class TestParityCeilingPrecision:
    """One ten-thousandth over the ceiling changes the verdict."""

    def test_index_exactly_on_the_ceiling_lets_a_license_activate(self, api):
        """1.1500 satisfies the less-than-or-equal comparison.

        PRD 3.1: "the verdict is `COMPLIANT` when the rounded index is less than
        or equal to 1.15 and `NON_COMPLIANT` when it exceeds 1.15 — an index
        landing exactly on 1.1500 is compliant." PRD 3.2 makes activation depend
        on that verdict: "the granting OEM's stored `parity_status` must read
        `COMPLIANT`".

        Design: Difficulty/boundary_precision_check/parity_index_exactly_at_threshold_is_compliant_and_one_tenth_basis_point_over_is_not
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        assert ctx["manufacturer"]["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert ctx["manufacturer"]["parity_status"] == ParityStatus.COMPLIANT

        fixtures.add_license(api, ctx, activate=False)
        activated = validate_success(
            api.activate_license(ctx["license"]["id"], make_platform_admin_headers())
        )

        assert_license(activated)
        assert activated["status"] == LicenseStatus.ACTIVE

    def test_one_ten_thousandth_over_the_ceiling_blocks_a_new_activation(self, api):
        """Restating to 115,100 flips the verdict without touching live licenses.

        PRD 3.1: "Restating the independent price to 115,100 cents pushes even
        the list-basis index to 1.1510 and flips the stored verdict to
        `NON_COMPLIANT`." PRD 3.2 adds that "an OEM that drifts into
        non-compliance keeps its active licenses, because the parity gate fires
        only at activation time", while a fresh activation is refused with
        `ERR_PARITY_NON_COMPLIANT`.

        Design: Difficulty/boundary_precision_check/parity_index_exactly_at_threshold_is_compliant_and_one_tenth_basis_point_over_is_not
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        admin = make_platform_admin_headers()
        manufacturer_id = ctx["manufacturer"]["id"]

        fixtures.add_license(api, ctx, activate=True)
        license_a_id = ctx["license"]["id"]
        license_b = validate_success(
            api.create_license(
                factories.license_payload(
                    manufacturer_id,
                    fixtures.area_ids(ctx, ("POWERTRAIN",)),
                    license_model=LicenseModel.PER_VEHICLE,
                ),
                admin,
            ),
            201,
        )

        fixtures.restate_pricing(api, ctx, independent_list_monthly_cents=115100)
        restated = ctx["manufacturer"]
        assert restated["parity_index"] == pytest.approx(1.1510, abs=5e-5)
        assert restated["parity_status"] == ParityStatus.NON_COMPLIANT

        still_live = _license_row(api, manufacturer_id, license_a_id, admin)
        assert still_live["status"] == LicenseStatus.ACTIVE

        validate_error(
            api.activate_license(license_b["id"], admin),
            ApiErrorId.PARITY_NON_COMPLIANT,
            409,
        )

        refused = _license_row(api, manufacturer_id, license_b["id"], admin)
        assert refused["status"] == LicenseStatus.DRAFT


class TestActivationDependsOnParityState:
    """The activation gate reads the manufacturer row, not the license row."""

    def test_activation_is_refused_while_the_manufacturer_is_non_compliant(self, api):
        """A 1.5000 index blocks activation and leaves the license in DRAFT.

        PRD 3.2: "Every activation, first-time or reinstating, re-runs the
        right-to-repair parity gate: the granting OEM's stored `parity_status`
        must read `COMPLIANT`, or the request is refused with
        `ERR_PARITY_NON_COMPLIANT` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/license_activation_depends_on_manufacturer_parity_state
        """
        ctx = fixtures.build_catalogue(
            api, area_codes=("POWERTRAIN",), manufacturer_overrides=dict(OVERPRICED_OEM)
        )
        admin = make_platform_admin_headers()
        manufacturer = ctx["manufacturer"]
        assert manufacturer["parity_index"] == pytest.approx(1.5000, abs=5e-5)
        assert manufacturer["parity_status"] == ParityStatus.NON_COMPLIANT

        fixtures.add_license(
            api, ctx, activate=False, license_model=LicenseModel.EITHER
        )
        license_id = ctx["license"]["id"]

        validate_error(
            api.activate_license(license_id, admin),
            ApiErrorId.PARITY_NON_COMPLIANT,
            409,
        )

        assert (
            _license_row(api, manufacturer["id"], license_id, admin)["status"]
            == LicenseStatus.DRAFT
        )

    def test_restating_the_manufacturer_price_unblocks_the_identical_activation(
        self, api
    ):
        """Only the OEM row changes, and the same activation then succeeds.

        PRD 3.1: "A pricing restatement lets a `PlatformAdmin` supply any subset
        of the four pricing figures" and "re-runs the list-basis computation,
        restamping both derived fields and advancing the OEM's `version` by 1".
        Once the verdict reads `COMPLIANT` the parity gate of PRD 3.2 passes and
        the license reaches `ACTIVE`.

        Design: Difficulty/cross_entity_state_dependency/license_activation_depends_on_manufacturer_parity_state
        """
        ctx = fixtures.build_catalogue(
            api, area_codes=("POWERTRAIN",), manufacturer_overrides=dict(OVERPRICED_OEM)
        )
        admin = make_platform_admin_headers()
        fixtures.add_license(
            api, ctx, activate=False, license_model=LicenseModel.EITHER
        )
        license_id = ctx["license"]["id"]
        validate_error(
            api.activate_license(license_id, admin),
            ApiErrorId.PARITY_NON_COMPLIANT,
            409,
        )

        fixtures.restate_pricing(api, ctx, independent_list_monthly_cents=100000)
        restated = ctx["manufacturer"]
        assert restated["parity_index"] == pytest.approx(1.0000, abs=5e-5)
        assert restated["parity_status"] == ParityStatus.COMPLIANT

        activated = validate_success(api.activate_license(license_id, admin))
        assert_license(activated)
        assert activated["status"] == LicenseStatus.ACTIVE
