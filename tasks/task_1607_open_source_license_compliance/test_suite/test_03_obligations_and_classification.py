"""License obligations and classification: the distribution-model-dependent
obligation variants, the multi-input determination formula, and the
cross-aggregate override cascade."""
from test_helpers import (
    TEST_USERS,
    create_component,
    get_success_data,
    list_bom_entries,
    get_bom,
    manifest_component_spec,
    override_classification_payload,
    setup_product_with_completed_scan,
    validate_success,
)

LEGAL = TEST_USERS["legal_headers"]


def _entry_for_purl(api, ctx, purl):
    """The BOM entry whose component carries `purl` (entries join to the
    catalogue through `component_id`). Entries are re-read so callers observe
    recomputations."""
    components = get_success_data(
        api.list_components(ctx["analyst_headers"], params={"package_url": purl}))
    assert len(components) == 1, f"expected one catalogue component for {purl}"
    entries = list_bom_entries(ctx["product"]["id"], ctx["bom"]["id"],
                               ctx["analyst_headers"])
    matches = [e for e in entries if e["component_id"] == components[0]["id"]]
    assert len(matches) == 1, f"expected one BOM entry for {purl}"
    return matches[0]


class TestObligationDualVariant:
    def test_weak_copyleft_saas_vs_onpremise(self, api):
        """PRD §3.4: "A `WEAK_COPYLEFT` component owes `ATTRIBUTION_ONLY`
        inside a `SaaS` product and a source offer everywhere else — the
        product must stand ready to provide the library's corresponding
        source, tracked through a ticket of type `SOURCE_OFFER`."

        Design: Difficulty/dual_variant_calc/obligation_determination_saas_vs_onpremise_agpl
        """
        spec = manifest_component_spec(package_url="pkg:npm/lgpl-lib@1.0.0",
                                       declared_license_spdx="LGPL-2.1")
        saas = setup_product_with_completed_scan(
            "SaaS", manifest=[spec],
            product_overrides={"product_code": "DUAL-SAAS"})
        onprem = setup_product_with_completed_scan(
            "ON_PREMISE", manifest=[spec],
            product_overrides={"product_code": "DUAL-ONPREM"})
        entry_saas = _entry_for_purl(api, saas, "pkg:npm/lgpl-lib@1.0.0")
        entry_onprem = _entry_for_purl(api, onprem, "pkg:npm/lgpl-lib@1.0.0")
        assert entry_saas["obligation_determination"] == "ATTRIBUTION_ONLY"
        assert entry_onprem["obligation_determination"] == "SOURCE_OFFER"
        assert (entry_saas["obligation_determination"]
                != entry_onprem["obligation_determination"])

    def test_strong_copyleft_mobile_app_vs_onpremise(self, api):
        """PRD §3.4: "A `STRONG_COPYLEFT` component owes
        `FULL_SOURCE_DISCLOSURE` when it is AGPL-3.0 inside a `SaaS` product
        or whenever the product is a `MOBILE_APP`, and `SOURCE_DISCLOSURE`
        under `ON_PREMISE` or `EMBEDDED` distribution".

        Design: Difficulty/dual_variant_calc/obligation_determination_saas_vs_onpremise_agpl
        """
        spec = manifest_component_spec(package_url="pkg:npm/gpl-lib@2.0.0",
                                       declared_license_spdx="GPL-3.0")
        mobile = setup_product_with_completed_scan(
            "MOBILE_APP", manifest=[spec],
            product_overrides={"product_code": "DUAL-MOBILE"})
        onprem = setup_product_with_completed_scan(
            "ON_PREMISE", manifest=[spec],
            product_overrides={"product_code": "DUAL-ONPREM-2"})
        entry_mobile = _entry_for_purl(api, mobile, "pkg:npm/gpl-lib@2.0.0")
        entry_onprem = _entry_for_purl(api, onprem, "pkg:npm/gpl-lib@2.0.0")
        assert entry_mobile["obligation_determination"] == "FULL_SOURCE_DISCLOSURE"
        assert entry_onprem["obligation_determination"] == "SOURCE_DISCLOSURE"


class TestObligationMultiInput:
    def test_scope_short_circuits_strong_copyleft_mobile(self, api):
        """PRD §3.4: "Entries in `TEST` or `DEV` scope carry no obligation at
        all — `NONE` — regardless of license." PRD §3.4: "A `STRONG_COPYLEFT`
        component owes `FULL_SOURCE_DISCLOSURE` when it is AGPL-3.0 inside a
        `SaaS` product or whenever the product is a `MOBILE_APP`".

        Design: Difficulty/combinatorial_formula/obligation_determination_multi_input
        """
        ctx = setup_product_with_completed_scan(
            "MOBILE_APP",
            product_overrides={"product_code": "MOBILE-APP"},
            manifest=[
                manifest_component_spec(
                    package_url="pkg:npm/gpl-runtime@2.0.0",
                    declared_license_spdx="GPL-3.0",
                    dependency_scope="RUNTIME"),
                manifest_component_spec(
                    package_url="pkg:npm/gpl-test@2.0.0",
                    declared_license_spdx="GPL-3.0",
                    dependency_scope="TEST"),
            ])
        runtime_entry = _entry_for_purl(api, ctx, "pkg:npm/gpl-runtime@2.0.0")
        test_entry = _entry_for_purl(api, ctx, "pkg:npm/gpl-test@2.0.0")
        # Same license and same distribution model; only the scope differs.
        assert runtime_entry["obligation_determination"] == "FULL_SOURCE_DISCLOSURE"
        assert test_entry["obligation_determination"] == "NONE"

    def test_scope_short_circuits_weak_copyleft_embedded(self, api):
        """PRD §3.4: "Entries in `TEST` or `DEV` scope carry no obligation at
        all — `NONE` — regardless of license." PRD §3.4: "A `WEAK_COPYLEFT`
        component owes `ATTRIBUTION_ONLY` inside a `SaaS` product and a source
        offer everywhere else".

        Design: Difficulty/combinatorial_formula/obligation_determination_multi_input
        """
        ctx = setup_product_with_completed_scan(
            "EMBEDDED",
            product_overrides={"product_code": "EMBED-SCOPE"},
            manifest=[
                manifest_component_spec(
                    package_url="pkg:npm/lgpl-rt@1.0.0",
                    declared_license_spdx="LGPL-2.1",
                    dependency_scope="RUNTIME"),
                manifest_component_spec(
                    package_url="pkg:npm/lgpl-dev@1.0.0",
                    declared_license_spdx="LGPL-2.1",
                    dependency_scope="DEV"),
            ])
        runtime_entry = _entry_for_purl(api, ctx, "pkg:npm/lgpl-rt@1.0.0")
        dev_entry = _entry_for_purl(api, ctx, "pkg:npm/lgpl-dev@1.0.0")
        assert runtime_entry["obligation_determination"] == "SOURCE_OFFER"
        assert dev_entry["obligation_determination"] == "NONE"


class TestLicenseOverrideCascade:
    def _setup_green_bom(self):
        component = create_component(
            package_url="pkg:npm/mit-lib@1.0.0", component_name="mit-lib",
            version="1.0.0", declared_license_spdx="MIT")
        ctx = setup_product_with_completed_scan(
            "ON_PREMISE",
            product_overrides={"product_code": "CASCADE-2"},
            manifest=[manifest_component_spec(
                package_url="pkg:npm/mit-lib@1.0.0",
                declared_license_spdx="MIT")])
        assert ctx["bom"]["bom_posture"] == "GREEN"
        ctx["component"] = component
        return ctx

    def test_override_recomputes_entry_and_bom(self, api):
        """PRD §3.2: "An override is a cross-aggregate event: every BOM entry
        referencing the component has its `obligation_determination`
        recomputed, every bill of materials containing the component has its
        `bom_posture` recomputed, and every product shipping the component has
        its counts updated and its posture re-evaluated." PRD §3.2: "The
        `effective_classification` reported everywhere downstream is the
        override when one is set and the computed `license_policy_classification`
        otherwise."

        Design: Difficulty/transitive_cascade/license_override_cascade_depth_2
        """
        ctx = self._setup_green_bom()
        product_id = ctx["product"]["id"]
        component = get_success_data(api.get_component(
            ctx["component"]["id"], ctx["analyst_headers"]))
        assert component["license_policy_classification"] == "PERMISSIVE"

        validate_success(api.override_classification(
            component["id"],
            override_classification_payload(
                "STRONG_COPYLEFT",
                "Discovered additional GPL-licensed code in repository"),
            LEGAL))

        component = get_success_data(
            api.get_component(component["id"], ctx["analyst_headers"]))
        assert component["effective_classification"] == "STRONG_COPYLEFT"
        # ON_PREMISE + STRONG_COPYLEFT -> SOURCE_DISCLOSURE (PRD §3.4).
        entry = _entry_for_purl(api, ctx, "pkg:npm/mit-lib@1.0.0")
        assert entry["obligation_determination"] == "SOURCE_DISCLOSURE"
        # No PROHIBITED/RESTRICTED entries and no high-severity findings: the
        # recomputed posture stays GREEN (PRD §3.3).
        bom = get_bom(product_id, ctx["bom"]["id"])
        assert bom["bom_posture"] == "GREEN"

    def test_override_to_prohibited_blocks_product(self, api):
        """PRD §3.4: "A `PROHIBITED` classification always yields
        `PROHIBITED_USE`." PRD §3.3: "`RED` as soon as any entry is
        `PROHIBITED`" and "a `RED` BOM leaves its product `BLOCKED`".

        Design: Difficulty/transitive_cascade/license_override_cascade_depth_2
        """
        ctx = self._setup_green_bom()
        product_id = ctx["product"]["id"]
        validate_success(api.override_classification(
            ctx["component"]["id"],
            override_classification_payload(
                "PROHIBITED", "Licence grant could not be evidenced"),
            LEGAL))

        entry = _entry_for_purl(api, ctx, "pkg:npm/mit-lib@1.0.0")
        assert entry["obligation_determination"] == "PROHIBITED_USE"
        bom = get_bom(product_id, ctx["bom"]["id"])
        assert bom["bom_posture"] == "RED"
        product = get_success_data(
            api.get_product(product_id, ctx["analyst_headers"]))
        assert product["compliance_posture"] == "BLOCKED"
