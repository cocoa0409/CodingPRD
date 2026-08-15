"""Media ingest, batch lifecycle, storage accounting, and asset registration."""

from test_helpers import (
    ApiErrorId, TEST_DEFAULTS, assert_media_asset, assert_media_batch,
    create_asset, create_batch, create_project, finish_ingest,
    proxy_complete, set_clock, setup_active_project, setup_batch_ingesting,
    setup_batch_proxying, setup_batch_ready, start_ingest,
    validate_error, validate_success,
)
from test_helpers.test_users import (
    make_media_manager_headers, make_post_supervisor_headers,
)

PS = make_post_supervisor_headers()
MM = make_media_manager_headers()
GIB = TEST_DEFAULTS["GIB"]


class TestBatchShape:
    def test_media_batch_create_end_before_start_returns_invalid_request(self, api):
        """PRD §3.2: "a declared ingest window bounded by `ingest_window_start`
        and `ingest_window_end`, both ISO 8601 UTC datetimes, where the end must
        be strictly later than the start."
        PRD §2.9: "Required fields must be present, types must match, enum values
        must be members of their declared enumerations, and numeric ranges must
        be respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/media_batch_create_end_before_start_returns_invalid_request
        """
        project = create_project(title="P", client_code="CL103",
                                 storage_quota_gb=10)
        resp = api.create_batch(project["id"], {
            "batch_label": "DAYX",
            "ingest_window_start": "2026-08-10T17:00:00Z",
            "ingest_window_end": "2026-08-10T09:00:00Z",
        }, MM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_initial_state_media_batch_is_declared(self, api):
        """PRD §3.2: "A declared batch sits in `DECLARED` until ingest begins;
        its lifecycle is `DECLARED` → `INGESTING` → `PROXYING` → `READY`."

        Design: Corner/state_machines/initial_state_media_batch_is_declared
        """
        project = create_project(title="P", client_code="CL202",
                                 storage_quota_gb=10)
        resp = api.create_batch(project["id"], {
            "batch_label": "D1",
            "ingest_window_start": "2026-08-01T00:00:00Z",
            "ingest_window_end": "2026-08-31T23:59:59Z",
        }, MM)
        batch = validate_success(resp, expected_status=201)
        assert_media_batch(batch)
        assert batch["status"] == "DECLARED"


class TestAssetCreationDefaults:
    def test_media_asset_create_computed_proxy_status_pending(self, api):
        """PRD §3.2: "A registered asset starts in `INGESTED` with `proxy_status`
        `PENDING` and `proxy_bytes` zero; the batch's `asset_count` and the
        project's `storage_used_gb` are recomputed immediately."

        Design: Corner/entities/media_asset_create_computed_proxy_status_pending
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL104", "storage_quota_gb": 10})
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        resp = api.create_asset(project["id"], {
            "batch_id": batch["id"], "reel_name": "A001", "clip_name": "C001",
            "source_bytes": 1000, "duration_frames": 100}, MM)
        asset = validate_success(resp, expected_status=201)
        assert_media_asset(asset)
        assert asset["proxy_status"] == "PENDING"
        assert asset["proxy_bytes"] == 0
        assert asset["status"] == "INGESTED"


class TestProxyProgress:
    def test_proxy_progress_pct_floor(self, api):
        """PRD §3.2: "The batch's `proxy_progress_pct` is the whole-number floor
        of one hundred times the number of assets in the batch whose
        `proxy_status` is `DONE`, divided by the batch's `asset_count`."

        Design: Corner/calculations/proxy_progress_pct_floor
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL300", "storage_quota_gb": 10})
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        a1 = create_asset(project["id"], batch["id"], clip_name="C001",
                          source_bytes=1000, duration_frames=100)
        create_asset(project["id"], batch["id"], clip_name="C002",
                     source_bytes=1000, duration_frames=100)
        create_asset(project["id"], batch["id"], clip_name="C003",
                     source_bytes=1000, duration_frames=100)
        finish_ingest(project["id"], batch["id"])
        proxy_complete(project["id"], a1["id"], 500)
        resp = api.get_batch(project["id"], batch["id"], MM)
        batch_after = validate_success(resp)
        assert batch_after["proxy_progress_pct"] == 33, (
            f"floor(100*1/3) should be 33, got {batch_after['proxy_progress_pct']}")


class TestStorageAccounting:
    def test_storage_used_provisional_variant(self, api):
        """PRD §3.2: "a provisional reading computed during ingest, while proxies
        are still rendering and `proxy_bytes` is still zero, which therefore
        reflects source media only."
        PRD §3.2: "The project's `storage_used_gb` is the sum, over every asset
        of the project whose status is not `PURGED`, of each asset's
        `source_bytes` plus its `proxy_bytes`, converted to gibibytes and rounded
        half-up to three decimal places as specified in §2.8."

        Design: Difficulty/dual_variant_calc/storage_used_provisional_vs_final
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P1", "client_code": "CL001", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        create_asset(project["id"], batch["id"], clip_name="C001",
                     source_bytes=GIB, duration_frames=2400)
        finish_ingest(project["id"], batch["id"])
        proj = validate_success(api.get_project(project["id"], PS))
        assert proj["storage_used_gb"] == 1.0, (
            f"Provisional storage should reflect source bytes only: "
            f"expected 1.0, got {proj['storage_used_gb']}")

    def test_storage_used_final_variant_differs_from_provisional(self, api):
        """PRD §3.2: "the final reading, reached once the batch is `READY` or
        after a purge, which includes the proxy bytes of completed assets."
        PRD §3.2: "It is recomputed on asset creation, on each proxy completion,
        and on batch purge."

        Design: Difficulty/dual_variant_calc/storage_used_provisional_vs_final
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P1", "client_code": "CL001", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        asset = create_asset(project["id"], batch["id"], clip_name="C001",
                             source_bytes=GIB, duration_frames=2400)
        finish_ingest(project["id"], batch["id"])
        before = validate_success(api.get_project(project["id"], PS))
        proxy_complete(project["id"], asset["id"], GIB // 2)
        after = validate_success(api.get_project(project["id"], PS))
        assert before["storage_used_gb"] == 1.0
        assert after["storage_used_gb"] == 1.5, (
            f"Final storage should include proxy bytes: expected 1.5, "
            f"got {after['storage_used_gb']}")
        assert before["storage_used_gb"] != after["storage_used_gb"]

    def test_storage_used_rounding_order(self, api):
        """PRD §2.8: "byte sums are converted by dividing by 1,073,741,824 (that
        is, 1024 cubed) and the result is rounded half-up to exactly 3 decimal
        places."
        PRD §3.2: "The project's `storage_used_gb` is the sum, over every asset
        of the project whose status is not `PURGED`, of each asset's
        `source_bytes` plus its `proxy_bytes`, converted to gibibytes and rounded
        half-up to three decimal places as specified in §2.8."

        Design: Difficulty/combinatorial_formula/storage_used_rounding_order
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PR", "client_code": "CL004", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        for clip in ("C001", "C002", "C003"):
            create_asset(project["id"], batch["id"], clip_name=clip,
                         source_bytes=400000000, duration_frames=100)
        proj = validate_success(api.get_project(project["id"], PS))
        # Sum-then-divide-then-round: 1200000000 / 1024^3 = 1.117587... → 1.118
        assert proj["storage_used_gb"] == 1.118, (
            f"Expected round-half-up(1200000000/1024^3, 3) == 1.118, "
            f"got {proj['storage_used_gb']}")

    def test_storage_used_rounding_order_per_asset_would_differ(self, api):
        """PRD §2.8: "byte sums are converted by dividing by 1,073,741,824 (that
        is, 1024 cubed) and the result is rounded half-up to exactly 3 decimal
        places."
        PRD §3.2: "The project's `storage_used_gb` is the sum, over every asset
        of the project whose status is not `PURGED`, of each asset's
        `source_bytes` plus its `proxy_bytes`, converted to gibibytes and rounded
        half-up to three decimal places as specified in §2.8."

        Design: Difficulty/combinatorial_formula/storage_used_rounding_order
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PR2", "client_code": "CL004", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="DAY02")
        start_ingest(project["id"], batch["id"])
        # Two sub-GiB assets whose per-asset GiB values would round UP:
        # per-asset round-then-sum gives 2 * 0.373 = 0.746; the pinned
        # sum-then-divide-then-round gives round_half_up(800000000/1024^3, 3)
        # = round_half_up(0.745058..., 3) = 0.745.
        for clip in ("C001", "C002"):
            create_asset(project["id"], batch["id"], clip_name=clip,
                         source_bytes=400000000, duration_frames=100)
        proj = validate_success(api.get_project(project["id"], PS))
        assert proj["storage_used_gb"] == 0.745, (
            f"Sum-first rounding must yield 0.745 (not per-asset 0.746); "
            f"got {proj['storage_used_gb']}")

    def test_derived_field_reconciliation_storage(self, api):
        """PRD §3.2: "It is recomputed on asset creation, on each proxy
        completion, and on batch purge."
        PRD §3.2: "Purging from either state moves the batch to `PURGED`,
        transitions every child asset to `PURGED`, and recomputes the project's
        `storage_used_gb`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_storage
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL801", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        asset = create_asset(project["id"], batch["id"], clip_name="C001",
                             source_bytes=GIB, duration_frames=100)
        s1 = validate_success(api.get_project(project["id"], PS))["storage_used_gb"]
        finish_ingest(project["id"], batch["id"])
        proxy_complete(project["id"], asset["id"], GIB // 2)
        s2 = validate_success(api.get_project(project["id"], PS))["storage_used_gb"]
        api.purge_batch(project["id"], batch["id"], MM)
        s3 = validate_success(api.get_project(project["id"], PS))["storage_used_gb"]
        assert s1 == 1.0, f"after asset create expected 1.0, got {s1}"
        assert s2 == 1.5, f"after proxy complete expected 1.5, got {s2}"
        assert s3 == 0.0, f"after purge expected 0.0, got {s3}"

    def test_immediate_consistency_derived_fields_in_response(self, api):
        """PRD §2.10: "These automatic reconciliations keep the hierarchy aligned
        at all times; the consistency model is immediate, with no deferred or
        eventual settlement."
        PRD §3.2: "the batch's `asset_count` and the project's `storage_used_gb`
        are recomputed immediately."

        Design: Corner/consistency_model/immediate_consistency_derived_fields_in_response
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL1000", "storage_quota_gb": 100})
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        create_asset(project["id"], batch["id"], clip_name="C001",
                     source_bytes=GIB, duration_frames=100)
        proj = validate_success(api.get_project(project["id"], PS))
        assert proj["storage_used_gb"] == 1.0, (
            f"storage_used_gb must be visible immediately after the POST that "
            f"caused it; got {proj['storage_used_gb']}")

    def test_storage_conservation_across_purge(self, api):
        """PRD §3.2: "Purging from either state moves the batch to `PURGED`,
        transitions every child asset to `PURGED`, and recomputes the project's
        `storage_used_gb`."
        PRD §3.2: "The project's `storage_used_gb` is the sum, over every asset
        of the project whose status is not `PURGED`, of each asset's
        `source_bytes` plus its `proxy_bytes`."

        Design: Difficulty/compensating_invariant/storage_conservation_across_purge
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PInv2", "client_code": "CL018", "storage_quota_gb": 100})
        before = validate_success(api.get_project(project["id"], PS))
        assert before["storage_used_gb"] == 0.0
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        a1 = create_asset(project["id"], batch["id"], clip_name="C001",
                          source_bytes=GIB, duration_frames=100)
        a2 = create_asset(project["id"], batch["id"], clip_name="C002",
                          source_bytes=GIB // 2, duration_frames=100)
        finish_ingest(project["id"], batch["id"])
        proxy_complete(project["id"], a1["id"], GIB // 4)
        proxy_complete(project["id"], a2["id"], GIB // 8)
        api.purge_batch(project["id"], batch["id"], MM)
        after = validate_success(api.get_project(project["id"], PS))
        assert after["storage_used_gb"] == 0.0, (
            f"Purge must restore storage_used_gb to its pre-asset value 0.0; "
            f"got {after['storage_used_gb']}")
        assert after["storage_used_gb"] == before["storage_used_gb"]

    def test_storage_conservation_batch_children_purged(self, api):
        """PRD §3.2: "Purging from either state moves the batch to `PURGED`,
        transitions every child asset to `PURGED`, and recomputes the project's
        `storage_used_gb`."

        Design: Difficulty/compensating_invariant/storage_conservation_across_purge
        """
        project, batch, assets = setup_batch_ready(
            project_overrides={"title": "PInv2", "client_code": "CL018",
                               "storage_quota_gb": 100},
            asset_specs=[{"clip_name": "C001", "source_bytes": GIB,
                          "duration_frames": 100}],
            proxy_bytes=GIB // 4)
        api.purge_batch(project["id"], batch["id"], MM)
        batch_after = validate_success(api.get_batch(project["id"], batch["id"], MM))
        asset_after = validate_success(api.get_asset(project["id"], assets[0]["id"], MM))
        assert batch_after["status"] == "PURGED"
        assert asset_after["status"] == "PURGED"
        proj = validate_success(api.get_project(project["id"], PS))
        assert proj["storage_used_gb"] == 0.0


class TestStorageQuota:
    def test_storage_quota_exceeded_boundary(self, api):
        """PRD §3.2: "the project's current `storage_used_gb` plus the incoming
        asset's bytes must remain at or below `storage_quota_gb`, or the
        registration is rejected with `ERR_STORAGE_QUOTA_EXCEEDED`."

        Design: Corner/validations/storage_quota_exceeded_boundary
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "P", "client_code": "CL401", "storage_quota_gb": 1})
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        create_asset(project["id"], batch["id"], clip_name="C001",
                     source_bytes=GIB, duration_frames=100)
        resp = api.create_asset(project["id"], {
            "batch_id": batch["id"], "reel_name": "A001", "clip_name": "C002",
            "source_bytes": 1, "duration_frames": 100}, MM)
        validate_error(resp, ApiErrorId.ERR_STORAGE_QUOTA_EXCEEDED)

    def test_asset_duplicate_beats_quota(self, api):
        """PRD §2.9 item 11: "The composite of project, reel, and clip must be
        unique among non-purged assets; otherwise `ERR_DUPLICATE_ASSET`
        (HTTP 409). Applies to asset registration."
        PRD §2.9 item 14: "Storage quota. ... Applies to asset registration,
        evaluated after the uniqueness check."

        Design: Difficulty/priority_pair_validation_conflict/asset_duplicate_beats_quota
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PD", "client_code": "CL010", "storage_quota_gb": 1})
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        create_asset(project["id"], batch["id"], clip_name="C001",
                     source_bytes=GIB, duration_frames=100)
        # Second asset both duplicates (reel, clip) and overflows the 1 GiB quota;
        # the uniqueness check is evaluated first, so DUPLICATE wins.
        resp = api.create_asset(project["id"], {
            "batch_id": batch["id"], "reel_name": "A001", "clip_name": "C001",
            "source_bytes": GIB, "duration_frames": 100}, MM)
        data = validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET)
        assert data["error_id"] != "ERR_STORAGE_QUOTA_EXCEEDED"

    def test_asset_duplicate_alone_still_rejected(self, api):
        """PRD §3.2: "The composite of project, `reel_name`, and `clip_name` must
        be unique among the project's assets that have not been purged; a
        duplicate is rejected with `ERR_DUPLICATE_ASSET`."
        PRD §2.9 item 11: "The composite of project, reel, and clip must be
        unique among non-purged assets; otherwise `ERR_DUPLICATE_ASSET`
        (HTTP 409). Applies to asset registration."

        Design: Difficulty/priority_pair_validation_conflict/asset_duplicate_beats_quota
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "title": "PD", "client_code": "CL010", "storage_quota_gb": 1})
        batch = create_batch(project["id"], batch_label="DAY01")
        start_ingest(project["id"], batch["id"])
        create_asset(project["id"], batch["id"], clip_name="C001",
                     source_bytes=1000, duration_frames=100)
        # Duplicate (reel, clip) but well under quota — uniqueness alone fires.
        resp = api.create_asset(project["id"], {
            "batch_id": batch["id"], "reel_name": "A001", "clip_name": "C001",
            "source_bytes": 1000, "duration_frames": 100}, MM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET)


class TestIngestWindow:
    def test_ingest_window_rejects_before_and_after(self, api):
        """PRD §3.2: "Starting ingest moves the batch from `DECLARED` to
        `INGESTING` and is permitted only while the project is `ACTIVE` and the
        logical clock reads a moment inside the declared window, both endpoints
        inclusive; an attempt outside the window is rejected with
        `ERR_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/ingest_window_closed_interval
        """
        set_clock("2026-08-10T08:59:59Z")
        project, _wm, _bay = setup_active_project(
            project_overrides={"title": "PIW", "client_code": "CL016",
                               "storage_quota_gb": 100},
            clock="2026-08-10T08:59:59Z")
        window = {"ingest_window_start": "2026-08-10T09:00:00Z",
                  "ingest_window_end": "2026-08-10T17:00:00Z"}
        b1 = create_batch(project["id"], batch_label="DAY01", **window)
        b3 = create_batch(project["id"], batch_label="DAY03", **window)
        resp_before = api.start_ingest(project["id"], b1["id"], MM)
        validate_error(resp_before, ApiErrorId.ERR_WINDOW_CLOSED)
        set_clock("2026-08-10T17:00:01Z")
        resp_after = api.start_ingest(project["id"], b3["id"], MM)
        validate_error(resp_after, ApiErrorId.ERR_WINDOW_CLOSED)

    def test_ingest_window_accepts_both_endpoints(self, api):
        """PRD §3.2: "Starting ingest moves the batch from `DECLARED` to
        `INGESTING` and is permitted only while the project is `ACTIVE` and the
        logical clock reads a moment inside the declared window, both endpoints
        inclusive."

        Design: Difficulty/resource_temporal_overlap/ingest_window_closed_interval
        """
        set_clock("2026-08-10T08:59:59Z")
        project, _wm, _bay = setup_active_project(
            project_overrides={"title": "PIW", "client_code": "CL016",
                               "storage_quota_gb": 100},
            clock="2026-08-10T08:59:59Z")
        window = {"ingest_window_start": "2026-08-10T09:00:00Z",
                  "ingest_window_end": "2026-08-10T17:00:00Z"}
        b1 = create_batch(project["id"], batch_label="DAY01", **window)
        b2 = create_batch(project["id"], batch_label="DAY02", **window)
        set_clock("2026-08-10T09:00:00Z")
        at_start = validate_success(api.start_ingest(project["id"], b1["id"], MM))
        assert at_start["status"] == "INGESTING"
        set_clock("2026-08-10T17:00:00Z")
        at_end = validate_success(api.start_ingest(project["id"], b2["id"], MM))
        assert at_end["status"] == "INGESTING"
