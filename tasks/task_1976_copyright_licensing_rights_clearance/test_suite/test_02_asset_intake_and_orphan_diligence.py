"""Asset intake defaults, orphan-work diligence certification, and posture defaults."""
from test_helpers import (
    ApiErrorId,
    assert_asset,
    create_asset,
    create_asset_payload,
    create_clearance_request,
    create_diligence_log_payload,
    create_rights_holder,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_curator_headers,
    make_officer_headers,
    make_requester_headers,
    setup_orphan_certified_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAssetCreateDefaults:
    def test_asset_without_holder_orphan_pending_posture_encumbered(self, api):
        """PRD §3.1: "its `orphan_status` is set to `NOT_ORPHAN` when a
        `rights_holder_id` is supplied at registration and to `DILIGENCE_PENDING`
        otherwise."

        Design: Corner/entities/asset_create_defaults_orphan_pending_when_holderless

        Note: creation-time posture for a holderless (DILIGENCE_PENDING) asset is
        deliberately NOT asserted. PRD §3.1 states verbatim "A newly registered
        asset enters with posture `CLEAR`" while §2.9 chain rule 4 ("If the asset's
        `orphan_status` is `DILIGENCE_PENDING`, the posture is `ENCUMBERED`") would
        derive ENCUMBERED, and the §2.9 trigger list does not name asset creation.
        Two faithful PRD-only readers diverge, so unique derivability fails; only
        the uniquely derivable assertions (orphan_status values, held-asset CLEAR)
        are kept.
        """
        curator = make_curator_headers("cur_a_1")
        holder = get_success_data(
            api.create_rights_holder(
                {
                    "legal_name": "Default House",
                    "holder_kind": "LABEL",
                    "mfn_floor_cents": 100,
                    "contact_verified": True,
                },
                curator,
            )
        )
        orphan_asset = get_success_data(
            api.create_asset(
                {
                    "title": "No Holder",
                    "work_kind": "STILL_IMAGE",
                    "permitted_media": ["PRINT"],
                },
                curator,
            )
        )
        held_asset = get_success_data(
            api.create_asset(
                {
                    "title": "Has Holder",
                    "work_kind": "STILL_IMAGE",
                    "permitted_media": ["PRINT"],
                    "rights_holder_id": holder["id"],
                },
                curator,
            )
        )
        assert orphan_asset["orphan_status"] == "DILIGENCE_PENDING"
        assert held_asset["orphan_status"] == "NOT_ORPHAN"
        assert held_asset["posture"] == "CLEAR"

    def test_asset_with_holder_posture_clear(self, api):
        """PRD §3.1: "A newly registered asset enters with posture `CLEAR` and
        `retired_at` null; its `orphan_status` is set to `NOT_ORPHAN` when a
        `rights_holder_id` is supplied at registration and to `DILIGENCE_PENDING`
        otherwise."

        Design: Corner/entities/asset_create_defaults_orphan_pending_when_holderless
        """
        holder = create_rights_holder(legal_name="HH")
        asset = create_asset(rights_holder_id=holder["id"], permitted_media=["PRINT"])
        assert_asset(asset)
        assert asset["orphan_status"] == "NOT_ORPHAN"
        assert asset["posture"] == "CLEAR"
        assert asset.get("retired_at") is None


class TestAssetNotFound:
    def test_get_asset_unknown_id_returns_404(self, api):
        """PRD §2.8 step 4: "Path existence — path resources exist, validated left
        to right; failure is `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/asset_get_not_found_returns_404
        """
        curator = make_curator_headers("cur_a_2")
        resp = api.get_asset("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", curator)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestDiligenceLogImmutability:
    def test_diligence_log_is_append_only_no_version_field(self, api):
        """PRD §2.4: "Rights diligence logs, negotiation rounds, usage events,
        and license payments carry only `id` and `created_at`; both `updated_at`
        and `version` are absent from these records, because they are never
        modified after creation — later activity appends new rows rather than
        rewriting history."

        Design: Corner/entities/diligence_log_immutable_no_update_endpoint
        """
        curator = make_curator_headers("cur_a_3")
        asset = get_success_data(
            api.create_asset(
                {
                    "title": "Diligence Asset",
                    "work_kind": "STILL_IMAGE",
                    "permitted_media": ["PRINT"],
                },
                curator,
            )
        )
        log = get_success_data(
            api.append_diligence_log(
                asset["id"],
                {
                    "search_channel": "COPYRIGHT_OFFICE",
                    "outcome": "NO_RESULT",
                    "notes": "first pass",
                },
                curator,
            )
        )
        assert is_valid_uuid(log["id"])
        assert is_iso8601_timestamp(log["created_at"])
        assert "version" not in log, "append-only log must not carry version"
        assert "updated_at" not in log, "append-only log must not carry updated_at"

        rows, meta = validate_paginated(api.list_diligence_logs(asset["id"], curator))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == log["id"]
        assert "version" not in rows[0]
        assert "updated_at" not in rows[0]


class TestOrphanCertification:
    def test_three_distinct_channels_and_thirty_day_span_certifies(self, api):
        """PRD §3.1: "Orphan certification is mechanical: when the asset's
        `rights_holder_id` is null, at least three diligence logs exist with
        pairwise distinct `search_channel` values, every one of those logs has
        `outcome` `NO_RESULT`, and the span between the first and last qualifying
        log's `created_at` is at least thirty days, the asset's `orphan_status`
        becomes `ORPHAN_CERTIFIED`, and that change triggers a posture recompute
        under §2.9."

        Design: Corner/calculations/orphan_certification_rule_three_channels_thirty_days
        """
        curator = make_curator_headers("cur_o_1")
        asset = get_success_data(
            api.create_asset(
                {
                    "title": "Orphan Work",
                    "work_kind": "STILL_IMAGE",
                    "permitted_media": ["PRINT"],
                },
                curator,
            )
        )
        # Log 1 at default clock 2026-08-01.
        api.append_diligence_log(
            asset["id"],
            {"search_channel": "COPYRIGHT_OFFICE", "outcome": "NO_RESULT", "notes": "l1"},
            curator,
        )
        # Move clock 19 days; add second log (span is still 19 days).
        api.set_clock("2026-08-20T00:00:00Z", curator)
        api.append_diligence_log(
            asset["id"],
            {"search_channel": "PERFORMING_RIGHTS_ORG", "outcome": "NO_RESULT", "notes": "l2"},
            curator,
        )
        mid = get_success_data(api.get_asset(asset["id"], curator))
        assert mid["orphan_status"] == "DILIGENCE_PENDING", (
            f"span of 19 days must not certify: {mid}"
        )
        # Move to exactly 30 days after log 1; add third distinct channel.
        api.set_clock("2026-08-31T00:00:00Z", curator)
        api.append_diligence_log(
            asset["id"],
            {"search_channel": "UNION_GUILD", "outcome": "NO_RESULT", "notes": "l3"},
            curator,
        )
        final = get_success_data(api.get_asset(asset["id"], curator))
        assert final["orphan_status"] == "ORPHAN_CERTIFIED"
        assert final["posture"] == "CLEAR"

    def test_orphan_certified_asset_advances_through_negotiating(self, api):
        """PRD §3.2: "The second step, from `HOLDER_REVIEW` into `NEGOTIATING`,
        requires that someone is there to negotiate with: the asset's
        `rights_holder_id` must be set, or the asset must be `ORPHAN_CERTIFIED` —
        otherwise `ERR_RIGHTS_HOLDER_UNIDENTIFIED`."

        Design: Corner/calculations/orphan_certified_asset_can_advance_without_holder
        """
        cert_asset = setup_orphan_certified_asset()
        # Certified asset passes HOLDER_REVIEW -> NEGOTIATING with null holder.
        req, _rid = create_clearance_request(
            cert_asset["id"],
            media="PRINT",
            use_start_at="2026-10-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
        )
        officer = make_officer_headers("off_o_1")
        step1 = get_success_data(
            api.advance_clearance_request(req["id"], req["version"], officer)
        )
        step2 = get_success_data(
            api.advance_clearance_request(req["id"], step1["version"], officer)
        )
        assert step2["status"] == "NEGOTIATING"

    def test_diligence_pending_asset_first_advance_rejected(self, api):
        """PRD §3.2: "The orphan-diligence gate comes first: an `orphan_status`
        of `DILIGENCE_PENDING` rejects with `ERR_ORPHAN_DILIGENCE_INCOMPLETE`"

        Design: Corner/calculations/orphan_certified_asset_can_advance_without_holder
        """
        curator = make_curator_headers("cur_o_2")
        pend_asset = get_success_data(
            api.create_asset(
                {
                    "title": "Pend Orphan",
                    "work_kind": "STILL_IMAGE",
                    "permitted_media": ["PRINT"],
                },
                curator,
            )
        )
        # One log only — not enough.
        api.append_diligence_log(
            pend_asset["id"],
            {"search_channel": "COPYRIGHT_OFFICE", "outcome": "NO_RESULT", "notes": "only one"},
            curator,
        )
        req, _rid = create_clearance_request(
            pend_asset["id"],
            media="PRINT",
            use_start_at="2026-10-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
        )
        officer = make_officer_headers("off_o_2")
        resp = api.advance_clearance_request(req["id"], req["version"], officer)
        validate_error(resp, ApiErrorId.ERR_ORPHAN_DILIGENCE_INCOMPLETE)
