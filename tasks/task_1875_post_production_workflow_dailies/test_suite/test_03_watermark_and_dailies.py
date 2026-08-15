"""Watermark compliance scoring, tier gates, and dailies publish/revoke."""

from test_helpers import (
    ApiErrorId, assert_dailies_package, create_batch, create_dailies_package,
    create_watermark_profile, activate_watermark_profile, finish_ingest,
    proxy_complete, setup_active_project, setup_batch_proxying,
    setup_batch_ready, setup_published_dailies, start_ingest, create_asset,
    validate_error, validate_success,
)
from test_helpers.test_users import (
    make_dailies_coordinator_headers, make_media_manager_headers,
    make_post_supervisor_headers,
)

PS = make_post_supervisor_headers()
MM = make_media_manager_headers()
DC = make_dailies_coordinator_headers()


def _ready_batch_with_profiles(security_tier, profiles):
    """ACTIVE project + READY batch + the given profiles each ACTIVE.

    profiles: list of (name, payload-overrides). Returns (project, batch,
    {name: profile}).
    """
    project, _wm0, _bay = setup_active_project(project_overrides={
        "storage_quota_gb": 100, "security_tier": security_tier})
    batch = create_batch(project["id"])
    start_ingest(project["id"], batch["id"])
    asset = create_asset(project["id"], batch["id"], clip_name="C001",
                         source_bytes=1000, duration_frames=100)
    finish_ingest(project["id"], batch["id"])
    proxy_complete(project["id"], asset["id"], 500)
    out = {}
    for name, ov in profiles:
        p = create_watermark_profile(project["id"], profile_name=name, **ov)
        activate_watermark_profile(project["id"], p["id"])
        out[name] = p
    return project, batch, out


class TestWatermarkScoring:
    def test_watermark_score_weighted_multi_input_failing_profile(self, api):
        """PRD §3.3: "The score starts at zero and accumulates: fifty points if
        `forensic_enabled` is true; the smaller of forty and the integer half of
        `opacity_pct` ... ten points if `includes_recipient_email` is true; and a
        further ten-point bonus if `position` is `DIAGONAL_TILE`."
        PRD §3.3: "under `ELEVATED` the score must be at least 60 and
        `includes_recipient_email` must be true ... A profile that is not
        `ACTIVE`, or whose score fails the tier gate, causes the publish to be
        rejected with `ERR_WATERMARK_NONCOMPLIANT`."

        Design: Difficulty/combinatorial_formula/watermark_score_weighted_multi_input
        """
        project, batch, profiles = _ready_batch_with_profiles("ELEVATED", [
            ("wfail", {"opacity_pct": 1, "position": "TOP_LEFT",
                       "includes_recipient_email": False,
                       "forensic_enabled": True}),
        ])
        # wfail: 50 (forensic) + min(40, 1//2)=0 + 0 (no email) + 0 = 50 < 60
        pkg = create_dailies_package(project["id"], batch["id"],
                                     profiles["wfail"]["id"])
        resp = api.publish_dailies_package(project["id"], pkg["id"], DC)
        validate_error(resp, ApiErrorId.ERR_WATERMARK_NONCOMPLIANT)

    def test_watermark_score_weighted_multi_input_passing_profile(self, api):
        """PRD §3.3: "The score starts at zero and accumulates: fifty points if
        `forensic_enabled` is true; the smaller of forty and the integer half of
        `opacity_pct` ... ten points if `includes_recipient_email` is true."
        PRD §3.3: "under `ELEVATED` the score must be at least 60 and
        `includes_recipient_email` must be true."

        Design: Difficulty/combinatorial_formula/watermark_score_weighted_multi_input
        """
        project, batch, profiles = _ready_batch_with_profiles("ELEVATED", [
            ("wpass", {"opacity_pct": 20, "position": "TOP_LEFT",
                       "includes_recipient_email": True,
                       "forensic_enabled": True}),
        ])
        # wpass: 50 + min(40, 20//2)=10 + 10 = 70 >= 60, email present
        pkg = create_dailies_package(project["id"], batch["id"],
                                     profiles["wpass"]["id"])
        resp = api.publish_dailies_package(project["id"], pkg["id"], DC)
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED"

    def test_watermark_score_at_elevated_boundary(self, api):
        """PRD §3.3: "under `ELEVATED` the score must be at least 60 and
        `includes_recipient_email` must be true."
        PRD §3.3: "fifty points if `forensic_enabled` is true; the smaller of
        forty and the integer half of `opacity_pct` (that is, the opacity divided
        by two with any fractional half discarded), contributing between zero and
        forty points; ten points if `includes_recipient_email` is true."

        Design: Difficulty/boundary_precision_check/watermark_score_at_elevated_boundary
        """
        project, batch, profiles = _ready_batch_with_profiles("ELEVATED", [
            ("w60", {"opacity_pct": 1, "position": "TOP_LEFT",
                     "includes_recipient_email": True, "forensic_enabled": True}),
        ])
        # 50 + min(40, 1//2)=0 + 10 + 0 = 60 — exactly at the >= 60 gate.
        pkg = create_dailies_package(project["id"], batch["id"],
                                     profiles["w60"]["id"])
        resp = api.publish_dailies_package(project["id"], pkg["id"], DC)
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED"

    def test_watermark_score_below_elevated_boundary_rejected(self, api):
        """PRD §3.3: "under `ELEVATED` the score must be at least 60 and
        `includes_recipient_email` must be true; ... A profile that is not
        `ACTIVE`, or whose score fails the tier gate, causes the publish to be
        rejected with `ERR_WATERMARK_NONCOMPLIANT`."
        PRD §3.3: "fifty points if `forensic_enabled` is true; the smaller of
        forty and the integer half of `opacity_pct` (that is, the opacity divided
        by two with any fractional half discarded), contributing between zero and
        forty points; ten points if `includes_recipient_email` is true."

        Design: Difficulty/boundary_precision_check/watermark_score_at_elevated_boundary
        """
        # opacity_pct=0 is below the 1..100 input range, so the closest
        # sub-60 profile with email+forensic is opacity_pct=1 -> score 60.
        # Instead drop forensic: 0 + 0 + 10 + 0 = 10 < 60 -> rejected.
        project, batch, profiles = _ready_batch_with_profiles("ELEVATED", [
            ("w59", {"opacity_pct": 1, "position": "TOP_LEFT",
                     "includes_recipient_email": True,
                     "forensic_enabled": False}),
        ])
        pkg = create_dailies_package(project["id"], batch["id"],
                                     profiles["w59"]["id"])
        resp = api.publish_dailies_package(project["id"], pkg["id"], DC)
        validate_error(resp, ApiErrorId.ERR_WATERMARK_NONCOMPLIANT)


class TestDailiesBatchGate:
    def test_dailies_publish_requires_batch_ready(self, api):
        """PRD §3.3: "the referenced batch must be `READY` ... a reference to a
        batch that is not `READY`, is rejected with `ERR_DISTRIBUTION_INVALID`."
        PRD §2.9 item 10: "The package's `distribution_list` must be non-empty
        with unique lowercase addresses, and the referenced batch must be
        `READY`; otherwise `ERR_DISTRIBUTION_INVALID` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/dailies_publish_requires_batch_ready
        """
        project, _wm, _bay = setup_active_project(project_overrides={
            "storage_quota_gb": 100, "security_tier": "STANDARD"})
        wm = api.list_watermark_profiles(project["id"], PS)
        from test_helpers import get_success_data
        wm_id = get_success_data(wm)[0]["id"]
        # Batch reaches PROXYING (proxies still rendering), not READY.
        project, batch, _assets = setup_batch_proxying(project=project)
        pkg = create_dailies_package(project["id"], batch["id"], wm_id)
        resp = api.publish_dailies_package(project["id"], pkg["id"], DC)
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_INVALID)
        pkg_after = validate_success(api.get_dailies_package(project["id"], pkg["id"], DC))
        assert pkg_after["status"] == "DRAFT"

    def test_dailies_publish_succeeds_when_batch_ready(self, api):
        """PRD §3.3: "Publishing moves it from `DRAFT` to `PUBLISHED` ... A
        successful publish stamps `published_at` from the logical clock;
        `revoked_at` stays null."

        Design: Difficulty/cross_entity_state_dependency/dailies_publish_requires_batch_ready
        """
        project, batch, _assets, pkg = setup_published_dailies(
            project_overrides={"storage_quota_gb": 100})
        assert pkg["status"] == "PUBLISHED"
        assert pkg["published_at"] is not None
        assert pkg.get("revoked_at") is None
