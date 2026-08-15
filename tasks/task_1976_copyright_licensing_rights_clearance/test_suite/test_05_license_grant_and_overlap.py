"""License grant gates: fee match, posture, window overlap (half-open + WORLD)."""
from test_helpers import (
    ApiErrorId,
    advance_request,
    create_asset,
    create_clearance_request,
    get_success_data,
    grant_license,
    make_curator_headers,
    make_officer_headers,
    make_requester_headers,
    post_round,
    setup_approved_request,
    setup_holder_asset,
    setup_license,
    setup_request_in_negotiating,
    validate_error,
    validate_success,
)


class TestGrantGates:
    def test_grant_fee_mismatch_rejected(self, api):
        """PRD §3.4: "The supplied `grant_fee_cents` must equal the request's
        `agreed_fee_cents` exactly — any drift is `ERR_FEE_MISMATCH`."

        Design: Corner/validations/fee_mismatch_at_grant_rejected
        """
        holder, asset, req, _rid = setup_approved_request(
            offered_fee_cents=200000,
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        officer = make_officer_headers("off_g_1")
        resp = api.grant_license(req["id"], 199999, officer)
        validate_error(resp, ApiErrorId.ERR_FEE_MISMATCH)

    def test_grant_blocked_when_posture_not_clear(self, api):
        """PRD §3.4: "The asset's posture must be `CLEAR`, else
        `ERR_ASSET_POSTURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/clearance_advance_gated_by_asset_posture
        """
        holder, asset, req, _rid = setup_approved_request(
            offered_fee_cents=200000,
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        # File a PENDING takedown — posture flips to ENCUMBERED.
        curator = make_curator_headers("cur_g_2")
        api.file_takedown_notice(asset["id"], {"claimant_name": "Watcher"}, curator)
        officer = make_officer_headers("off_g_2")
        resp = api.grant_license(req["id"], 200000, officer)
        validate_error(resp, ApiErrorId.ERR_ASSET_POSTURE_BLOCKED)


class TestWindowOverlap:
    def test_adjacent_half_open_window_grant_allowed(self, api):
        """PRD §3.4: "Term intersection uses half-open windows: the existing
        term must start strictly before the new term's end, and the new term
        must start strictly before the existing term's end; a merely adjacent
        window, where the existing `term_end_at` is exactly the new
        `term_start_at`, does not conflict because term ends are exclusive."

        Design: Difficulty/resource_temporal_overlap/license_term_half_open_adjacency_allowed_overlap_rejected
        """
        # L1: STREAMING/NA [2026-08-10, 2026-10-10)
        holder, asset, req1, lic1, _ = setup_license(
            fee_cents=200000,
            media="STREAMING",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            permitted_media=["STREAMING"],
        )
        # Adjacent: [2026-10-10, 2026-12-10) — no overlap.
        holder2 = holder
        req_adj, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="NA",
            use_start_at="2026-10-10T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
            requested_units=3,
        )
        req_adj = advance_request(req_adj["id"], req_adj["version"])
        req_adj = advance_request(req_adj["id"], req_adj["version"])
        post_round(req_adj["id"], 150000, accept=True, role="Negotiator", user_id="neg_adj")
        lic_adj = grant_license(req_adj["id"], 150000)
        assert lic_adj["lifecycle"] == "ACTIVE"

    def test_overlapping_window_grant_rejected(self, api):
        """PRD §3.4: "the grant is rejected with `ERR_LICENSE_WINDOW_OVERLAP`
        when any other license on the same asset has `lifecycle` `ACTIVE`,
        the same `media`, an overlapping territory, and an intersecting term."

        Design: Difficulty/resource_temporal_overlap/license_term_half_open_adjacency_allowed_overlap_rejected
        """
        holder, asset, req1, lic1, _ = setup_license(
            fee_cents=200000,
            media="STREAMING",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            permitted_media=["STREAMING"],
        )
        # Overlapping: [2026-10-09, 2026-12-10) intersects L1.
        req_ovl, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="NA",
            use_start_at="2026-10-09T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
            requested_units=3,
        )
        req_ovl = advance_request(req_ovl["id"], req_ovl["version"])
        req_ovl = advance_request(req_ovl["id"], req_ovl["version"])
        post_round(req_ovl["id"], 150000, accept=True, role="Negotiator", user_id="neg_ovl")
        officer = make_officer_headers("off_ovl")
        resp = api.grant_license(req_ovl["id"], 150000, officer)
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP)


class TestWorldTerritorySuperset:
    def test_active_na_blocks_world_grant(self, api):
        """PRD §3.4: "Territory overlap follows superset semantics — `WORLD`
        contains every territory, so it overlaps all of them, and two
        non-`WORLD` territories overlap only when equal."

        Design: Corner/calculations/world_territory_superset_overlap_blocks_grant
        """
        # L1: STREAMING/NA ACTIVE [2026-08-10, 2027-08-10).
        holder, asset, req1, lic1, _ = setup_license(
            fee_cents=900000,
            media="STREAMING",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2027-08-10T00:00:00Z",
            requested_units=5,
            permitted_media=["STREAMING"],
        )
        # R2 WORLD overlaps NA via superset semantics.
        req2, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="WORLD",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2027-01-01T00:00:00Z",
            requested_units=2,
        )
        req2 = advance_request(req2["id"], req2["version"])
        req2 = advance_request(req2["id"], req2["version"])
        post_round(req2["id"], 500000, accept=True, role="Negotiator", user_id="neg_w_1")
        officer = make_officer_headers("off_w_1")
        resp = api.grant_license(req2["id"], 500000, officer)
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP)


class TestLicenseComputedFields:
    def test_license_grant_response_zero_counters_unpaid_active(self, api):
        """PRD §3.4: "It is born with `lifecycle` `ACTIVE` and `fee_status`
        `UNPAID`, and its consumption counters `units_reserved`,
        `units_consumed_net`, and `units_consumed_gross` are computed fields
        that derive from its reservations and events per §3.5."

        Design: Corner/entities/license_computed_fields_ignore_client_input
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=4,
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
        )
        assert lic["units_reserved"] == 0
        assert lic["units_consumed_gross"] == 0
        assert lic["units_consumed_net"] == 0
        assert lic["fee_status"] == "UNPAID"
        assert lic["lifecycle"] == "ACTIVE"
