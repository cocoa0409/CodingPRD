"""Pricing agreements: activation, optimistic concurrency, window overlap,
and supersession (PRD §3.2, §2.8)."""
from test_helpers import (
    ApiErrorId,
    assert_pricing_agreement,
    create_customer,
    create_pricing_agreement,
    validate_error,
    validate_success,
)


class TestAgreementActivationOcc:
    def test_activate_with_stale_version_rejected(self, api,
                                                  quality_manager_headers):
        """PRD §2.8: "Activating a pricing agreement requires the request to
        carry `expected_pricing_agreement_version` with the same semantics:
        a mismatch against the agreement's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412), covering the case where another writer
        has terminated the agreement or otherwise modified it since the
        client last read it."

        Design: Corner/errors/occ_stale_version_explicit_stale_returns_412
        """
        customer = create_customer("Stale Co")
        agreement = create_pricing_agreement(customer["id"])
        assert agreement["version"] == 1

        resp = api.activate_pricing_agreement(
            customer["id"], agreement["id"], agreement["version"] - 1,
            quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestWindowOverlapAndSupersession:
    def test_full_coverage_activation_supersedes_existing(
            self, api, quality_manager_headers):
        """PRD §3.2: "When the incoming window fully covers the existing
        agreement's window, the existing agreement is cascaded to
        `SUPERSEDED` — its `version` increments and `updated_at` refreshes —
        and the activation proceeds."

        Design: Difficulty/resource_temporal_overlap/pricing_agreement_window_overlap_supersede_semantics
        """
        customer = create_customer("Omicron Paints")
        old = create_pricing_agreement(
            customer["id"], activate=True,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z")
        assert old["status"] == "ACTIVE"

        new = create_pricing_agreement(
            customer["id"], pricing_mode="FORMULATED_PRICE",
            tolling_base_fee_cents=0, tolling_per_kg_cents=0,
            formulated_price_per_kg_cents=250, over_yield_split_pct=50,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")
        resp = api.activate_pricing_agreement(
            customer["id"], new["id"], new["version"], quality_manager_headers)
        activated = validate_success(resp)
        assert_pricing_agreement(activated)
        assert activated["status"] == "ACTIVE"

        old_after = validate_success(api.get_pricing_agreement(
            customer["id"], old["id"], quality_manager_headers))
        assert old_after["status"] == "SUPERSEDED", (
            f"Fully covered agreement must cascade to SUPERSEDED, got "
            f"{old_after['status']}")

    def test_supersede_cascade_increments_old_agreement_version(
            self, api, quality_manager_headers):
        """PRD §3.2: "the existing agreement is cascaded to `SUPERSEDED` — its
        `version` increments and `updated_at` refreshes — and the activation
        proceeds."

        Design: Corner/cross_cutting_layers/supersede_cascade_increments_version
        """
        customer = create_customer("Supersede Co")
        old = create_pricing_agreement(
            customer["id"], activate=True,
            tolling_base_fee_cents=1, tolling_per_kg_cents=1,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z")
        version_after_activation = old["version"]

        new = create_pricing_agreement(
            customer["id"], tolling_base_fee_cents=2, tolling_per_kg_cents=2,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")
        validate_success(api.activate_pricing_agreement(
            customer["id"], new["id"], new["version"], quality_manager_headers))

        old_after = validate_success(api.get_pricing_agreement(
            customer["id"], old["id"], quality_manager_headers))
        assert old_after["status"] == "SUPERSEDED"
        assert old_after["version"] == version_after_activation + 1, (
            f"Supersede cascade must bump version by exactly 1: "
            f"{version_after_activation} -> {old_after['version']}")

    def test_superseded_agreement_version_advances_from_activate(
            self, api, quality_manager_headers):
        """PRD §3.2: "When the incoming window fully covers the existing
        agreement's window, the existing agreement is cascaded to
        `SUPERSEDED` — its `version` increments and `updated_at` refreshes —
        and the activation proceeds." The new agreement ends `ACTIVE` with its
        own single activation increment.

        Design: Difficulty/resource_temporal_overlap/pricing_agreement_window_overlap_supersede_semantics
        """
        customer = create_customer("Omicron Paints II")
        old = create_pricing_agreement(
            customer["id"], activate=True,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z")
        new = create_pricing_agreement(
            customer["id"], effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")
        new_version_before = new["version"]

        activated = validate_success(api.activate_pricing_agreement(
            customer["id"], new["id"], new["version"], quality_manager_headers))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == new_version_before + 1

        old_after = validate_success(api.get_pricing_agreement(
            customer["id"], old["id"], quality_manager_headers))
        assert old_after["status"] == "SUPERSEDED"
        assert old_after["version"] == old["version"] + 1

    def test_partial_overlap_rejected(self, api, quality_manager_headers):
        """PRD §3.2: "When the overlap is only partial, the activation is
        rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Corner/cross_cutting_layers/partial_overlap_pricing_window_rejected
        """
        customer = create_customer("Overlap Co")
        pa1 = create_pricing_agreement(
            customer["id"], activate=True,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-30T00:00:00Z")
        pa2 = create_pricing_agreement(
            customer["id"], tolling_base_fee_cents=2, tolling_per_kg_cents=2,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-10-31T00:00:00Z")

        resp = api.activate_pricing_agreement(
            customer["id"], pa2["id"], pa2["version"], quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

        pa1_after = validate_success(api.get_pricing_agreement(
            customer["id"], pa1["id"], quality_manager_headers))
        assert pa1_after["status"] == "ACTIVE", "Partial overlap must not supersede"
        pa2_after = validate_success(api.get_pricing_agreement(
            customer["id"], pa2["id"], quality_manager_headers))
        assert pa2_after["status"] == "DRAFT", "Rejected activation leaves DRAFT"
