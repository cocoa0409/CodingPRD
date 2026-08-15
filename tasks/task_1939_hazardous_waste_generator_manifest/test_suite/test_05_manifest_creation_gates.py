"""Manifest drafting: referential integrity, partner vetting, staging, permit,
LDR, tracking-number, and tonnage-fee gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, manifest_line_item,
    create_site, create_stream, create_active_stream, create_area,
    create_container, create_staged_container, get_container,
    create_partner, approve_partner, audit_partner, create_vetted_partner,
    create_manifest, get_manifest, attach_ldr, sign_manifest_generator,
    label_container, inspect_container, stage_container,
    create_manifest_partners,
    setup_site_stream_areas, setup_shippable_site, create_manifest_chain,
    ehs_headers, wc_headers, ca_headers, assert_manifest,
)


class TestManifestExistence:
    def test_manifest_get_not_found_returns_404(self, api):
        """PRD §2.9: "fourth, existence of every path- and body-referenced
        identifier, validated left to right — site, then stream, then area, then
        container, then partner, then manifest, then report (`ERR_NOT_FOUND`)".

        Design: Corner/entities/manifest_get_not_found_returns_404
        """
        res = api.get_manifest(NON_EXISTENT_UUID, ehs_headers())
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestContainerStagingGate:
    def test_manifest_create_requires_containers_staged(self, api):
        """PRD §3.6: "every line-item container must currently be
        `STAGED_FOR_SHIPMENT` (`ERR_CONTAINER_NOT_STAGED`)".

        Design: Difficulty/cross_entity_state_dependency/manifest_create_requires_containers_staged
        """
        env = setup_shippable_site()
        container = env["container"]
        # Unstage the scenario: build a fresh central container that is labeled
        # and inspected but NOT staged.
        raw = create_container(env["stream"]["id"], env["central"]["id"], 10,
                               100.0, "wc-1")
        label_container(raw, labeler="wc-1")
        inspect_container(raw["id"], "PASS", inspector="wc-2")
        line = manifest_line_item(env["stream"]["id"], raw["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"], "transporter_id": env["transporter"]["id"],
             "tsdf_id": env["tsdf"]["id"], "manifest_tracking_number": "MT-900",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_CONTAINER_NOT_STAGED)
        # After staging, the identical create succeeds.
        stage_container(raw["id"], stager="wc-1")
        manifest = create_manifest(
            env["site"]["id"], env["transporter"]["id"], env["tsdf"]["id"],
            [line], "MT-900")
        assert manifest["status"] == "DRAFT"

    def test_manifest_create_rejects_satellite_container(self, api):
        """PRD §3.6: "every line-item container must currently be
        `STAGED_FOR_SHIPMENT` (`ERR_CONTAINER_NOT_STAGED`)". A container still
        accumulating at a satellite area has never been staged.

        Design: Difficulty/cross_entity_state_dependency/manifest_create_requires_containers_staged
        """
        env = setup_site_stream_areas(with_satellite=True, with_central=False)
        transporter, tsdf = create_manifest_partners(["D001"])
        container = create_container(env["stream"]["id"], env["satellite"]["id"],
                                     10, 100.0, "wc-1")
        assert container["status"] == "ACCUMULATING_AT_SATELLITE"
        line = manifest_line_item(env["stream"]["id"], container["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"], "transporter_id": transporter["id"],
             "tsdf_id": tsdf["id"], "manifest_tracking_number": "MT-901",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_CONTAINER_NOT_STAGED)


class TestPartnerVettingGates:
    def test_tsdf_permit_gap_returns_waste_code_not_permitted(self, api):
        """PRD §3.6: "the TSDF's `permitted_waste_codes` must cover every waste
        code of every line's stream (`ERR_TSDF_WASTE_CODE_NOT_PERMITTED`)".

        Design: Corner/validations/tsdf_permit_gap_returns_waste_code_not_permitted
        """
        env = setup_shippable_site(waste_codes=["D001", "F003"],
                                   quantity_kg=100.0)
        # env's partners permit both codes; register a TSDF permitting only D001.
        weak_tsdf = create_vetted_partner("TSDF", "EPA-TS-WEAK", ["D001"], "NarrowCo")
        line = manifest_line_item(env["stream"]["id"], env["container"]["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"],
             "transporter_id": env["transporter"]["id"],
             "tsdf_id": weak_tsdf["id"], "manifest_tracking_number": "MT-210",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_TSDF_WASTE_CODE_NOT_PERMITTED)

    def test_partner_type_mismatch_rejected(self, api):
        """PRD §3.6: "a `transporter_id` referencing a partner of type
        `TRANSPORTER`, a `tsdf_id` referencing a partner of type `TSDF` (a
        wrong-typed reference in either slot is `ERR_PARTNER_TYPE_MISMATCH`)".

        Design: Corner/validations/partner_type_mismatch_rejected
        """
        env = setup_shippable_site()
        line = manifest_line_item(env["stream"]["id"], env["container"]["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"],
             "transporter_id": env["tsdf"]["id"],  # TSDF-typed partner in the
             "tsdf_id": env["tsdf"]["id"],          # transporter slot
             "manifest_tracking_number": "MT-220", "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_PARTNER_TYPE_MISMATCH)

    def test_manifest_create_with_unapproved_partner_rejected(self, api):
        """PRD §3.6: "both partners must be `APPROVED`
        (`ERR_PARTNER_NOT_APPROVED`)". The PENDING transporter also lacks audit
        coverage; per PRD §2.9 the fixed order runs "eighth and onward, the
        business, segregation-of-duties, referential, and temporal rules", so the
        approval gate reports first.

        Design: Corner/errors/manifest_create_with_unapproved_partner_rejected
        """
        env = setup_shippable_site()
        pending = create_partner("TRANSPORTER", "HaulCo2", "EPA-TR-2", ["D001"])
        line = manifest_line_item(env["stream"]["id"], env["container"]["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"], "transporter_id": pending["id"],
             "tsdf_id": env["tsdf"]["id"], "manifest_tracking_number": "MT-260",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_PARTNER_NOT_APPROVED)

    def test_manifest_create_without_audit_returns_audit_stale(self, api):
        """PRD §3.6: "both partners must be audit-current
        (`ERR_PARTNER_AUDIT_STALE`)". Both partners are APPROVED but hold no audit
        coverage, so only the audit-currency gate can fail.

        Design: Corner/errors/manifest_create_without_audit_returns_audit_stale
        """
        env = setup_site_stream_areas()
        container = create_staged_container(env["stream"]["id"],
                                            env["central"]["id"], 10, 100.0)
        transporter = create_partner("TRANSPORTER", "HaulCo", "EPA-TR-1", ["D001"])
        approve_partner(transporter)
        tsdf = create_partner("TSDF", "DispCo", "EPA-TS-1", ["D001"])
        approve_partner(tsdf)
        line = manifest_line_item(env["stream"]["id"], container["id"], 100.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"], "transporter_id": transporter["id"],
             "tsdf_id": tsdf["id"], "manifest_tracking_number": "MT-270",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_PARTNER_AUDIT_STALE)


class TestReferentialIntegrity:
    def test_duplicate_tracking_number_rejected(self, api):
        """PRD §3.6: "a generator-assigned `manifest_tracking_number` unique
        within the site (duplicates are `ERR_DUPLICATE_TRACKING_NUMBER`)" — the
        same number on another site is allowed.

        Design: Corner/errors/duplicate_tracking_number_rejected
        """
        env = create_manifest_chain(tracking_number="MT-300", through="DRAFT")
        second = create_staged_container(env["stream"]["id"],
                                         env["central"]["id"], 10, 50.0)
        line = manifest_line_item(env["stream"]["id"], second["id"], 50.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"],
             "transporter_id": env["transporter"]["id"],
             "tsdf_id": env["tsdf"]["id"], "manifest_tracking_number": "MT-300",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_TRACKING_NUMBER)
        # The number is scoped to the site: another site may use it.
        other = create_manifest_chain(tracking_number="MT-300",
                                      epa_id_number="EPA-SITE-B",
                                      transporter_epa="EPA-TR-B",
                                      tsdf_epa="EPA-TS-B", through="DRAFT")
        assert other["manifest"]["manifest_tracking_number"] == "MT-300"

    def test_line_container_stream_mismatch_rejected(self, api):
        """PRD §2.7: "manifest line items require each referenced container to
        belong to the manifest's site and to carry the line's declared stream. A
        violation of any of these is rejected with `ERR_CROSS_SITE_REFERENCE`
        (HTTP 409), except the line-item stream check, which is a malformed-line
        rejection carrying `ERR_LINE_CONTAINER_MISMATCH` (HTTP 400)."

        Design: Corner/validations/line_container_stream_mismatch_rejected
        """
        site = create_site()
        s1 = create_active_stream(site["id"], "solvent", ["D001"], "LIQUID")
        s2 = create_active_stream(site["id"], "sludge", ["F003"], "SLUDGE",
                                  ldr_treatment_standard="TLV-02",
                                  flash_point_c=61.0)
        area = create_area(site["id"])
        transporter, tsdf = create_manifest_partners(["D001", "F003"])
        container = create_staged_container(s2["id"], area["id"], 10, 100.0,
                                            label_text="Hazardous Waste — F003")
        # The line claims stream s1 but the container was filled from s2.
        line = manifest_line_item(s1["id"], container["id"], 100.0)
        res = api.create_manifest(
            {"site_id": site["id"], "transporter_id": transporter["id"],
             "tsdf_id": tsdf["id"], "manifest_tracking_number": "MT-230",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_LINE_CONTAINER_MISMATCH)


class TestCrossSiteBeatsStaleAudit:
    def _setup(self):
        """Site B holds the ACTIVE stream and a STAGED container; site A is the
        manifest's site. Returns (site_a, stream_b, container_b)."""
        site_a = create_site("Site A", "EPA-SITE-A")
        site_b = create_site("Site B", "EPA-SITE-B")
        stream_b = create_active_stream(site_b["id"])
        area_b = create_area(site_b["id"], "Central B")
        container_b = create_staged_container(stream_b["id"], area_b["id"], 10, 100.0)
        return site_a, stream_b, container_b

    def test_cross_site_reference_beats_stale_transporter_audit(self, api):
        """PRD §2.9: "the system evaluates checks in a fixed priority order and
        returns the first failure" — "seventh, state-machine legality
        (`ERR_INVALID_STATE` or the more specific state errors); eighth and
        onward, the business, segregation-of-duties, referential, and temporal
        rules described throughout §3". PRD §3.6 lists the line-item site check
        (`ERR_CROSS_SITE_REFERENCE`) before the audit-currency check
        (`ERR_PARTNER_AUDIT_STALE`).

        Design: Difficulty/priority_pair_validation_conflict/manifest_create_referential_beats_temporal
        """
        site_a, stream_b, container_b = self._setup()
        transporter = create_vetted_partner(
            "TRANSPORTER", "EPA-TR-1", ["D001"], "HaulCo",
            coverage_from="2026-01-01T00:00:00Z", coverage_to="2026-06-01T00:00:00Z")
        tsdf = create_vetted_partner("TSDF", "EPA-TS-1", ["D001"], "DispCo")
        line = manifest_line_item(stream_b["id"], container_b["id"], 100.0)
        res = api.create_manifest(
            {"site_id": site_a["id"], "transporter_id": transporter["id"],
             "tsdf_id": tsdf["id"], "manifest_tracking_number": "MT-700",
             "line_items": [line]},
            wc_headers("wc-1"))
        # The transporter's audit ended 2026-06-01 (stale at the 2026-08-01
        # clock); the referential failure is reported first.
        validate_error(res, ApiErrorId.ERR_CROSS_SITE_REFERENCE)
        _, meta = validate_paginated(
            api.list_manifests(ehs_headers(), params={"site_id": site_a["id"]}))
        assert meta["total_count"] == 0

    def test_cross_site_reference_beats_stale_tsdf_audit(self, api):
        """PRD §2.9: "the system evaluates checks in a fixed priority order and
        returns the first failure" — "eighth and onward, the business,
        segregation-of-duties, referential, and temporal rules described
        throughout §3". PRD §3.6: "every line-item container must belong to the
        manifest's site (`ERR_CROSS_SITE_REFERENCE`)".

        Design: Difficulty/priority_pair_validation_conflict/manifest_create_referential_beats_temporal
        """
        site_a, stream_b, container_b = self._setup()
        transporter = create_vetted_partner("TRANSPORTER", "EPA-TR-1", ["D001"],
                                            "HaulCo")
        tsdf = create_vetted_partner(
            "TSDF", "EPA-TS-1", ["D001"], "DispCo",
            coverage_from="2026-01-01T00:00:00Z", coverage_to="2026-06-01T00:00:00Z")
        line = manifest_line_item(stream_b["id"], container_b["id"], 100.0)
        res = api.create_manifest(
            {"site_id": site_a["id"], "transporter_id": transporter["id"],
             "tsdf_id": tsdf["id"], "manifest_tracking_number": "MT-701",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_CROSS_SITE_REFERENCE)


class TestLdrGate:
    def test_sign_generator_without_ldr_returns_ldr_missing(self, api):
        """PRD §3.6: "at least one LDRNotification must exist for the manifest
        (otherwise `ERR_LDR_NOTICE_MISSING`)".

        Design: Corner/validations/sign_generator_without_ldr_returns_ldr_missing
        """
        env = create_manifest_chain(tracking_number="MT-200", through="DRAFT")
        res = api.sign_manifest_generator(env["manifest"]["id"], ehs_headers("mgr-9"))
        validate_error(res, ApiErrorId.ERR_LDR_NOTICE_MISSING)
        assert get_manifest(env["manifest"]["id"])["status"] == "DRAFT"


class TestTonnageFeeRounding:
    def test_manifest_tonnage_fee_per_line_rounding(self, api):
        """PRD §2.10: "The rounding order is pinned: round each line first, then
        sum. The alternative order (sum quantities across lines, multiply by the
        rate, then round) is a rejected implementation, because it produces
        different totals — two lines of 1.0 kilogram each yield 11 + 11 = 22 cents
        under the pinned order but a single rounded 21 cents under sum-first."

        Design: Difficulty/combinatorial_formula/manifest_tonnage_fee_per_line_rounding
        """
        env = setup_shippable_site(quantity_kg=1.0, quantity_gallons=1)
        second = create_staged_container(env["stream"]["id"], env["central"]["id"],
                                         1, 1.0)
        lines = [manifest_line_item(env["stream"]["id"], env["container"]["id"], 1.0),
                 manifest_line_item(env["stream"]["id"], second["id"], 1.0)]
        manifest = create_manifest(
            env["site"]["id"], env["transporter"]["id"], env["tsdf"]["id"],
            lines, "MT-200")
        assert_manifest(manifest)
        assert manifest["tonnage_fee_cents"] == 22, (
            "round_half_up(1.0 * 10.5) = 11 per line, then 11 + 11; "
            "sum-first would give 21")
        assert manifest["total_quantity_kg"] == 2.0

    def test_tonnage_fee_single_line_rounds_half_up(self, api):
        """PRD §2.10: "each line's `quantity_kg` is multiplied by a rate of 10.5
        cents per kilogram and the result is rounded half-up to a whole cent, and
        only then are the per-line amounts summed into the manifest's
        `tonnage_fee_cents`."

        Design: Difficulty/combinatorial_formula/manifest_tonnage_fee_per_line_rounding
        """
        env = setup_shippable_site(quantity_kg=1.0, quantity_gallons=1)
        line = manifest_line_item(env["stream"]["id"], env["container"]["id"], 1.0)
        manifest = create_manifest(
            env["site"]["id"], env["transporter"]["id"], env["tsdf"]["id"],
            [line], "MT-201")
        assert manifest["tonnage_fee_cents"] == 11, (
            "round_half_up(1.0 * 10.5) = 11, not 10")
        assert isinstance(manifest["tonnage_fee_cents"], int)
