"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints. Setup calls use the lenient get_success_data() so
that a setup failure surfaces as a clear "Setup failed" message rather than a
confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    apply_change_list_payload, change_list_entry, create_archive_job_payload,
    create_asset_payload, create_batch_payload, create_bay_payload,
    create_booking_payload, create_change_list_payload,
    create_dailies_package_payload, create_deliverable_payload,
    create_project_payload, create_qc_report_payload,
    create_review_note_payload, create_review_round_payload,
    create_turnover_payload, create_vendor_bid_payload, create_vendor_payload,
    create_watermark_profile_payload, proxy_complete_payload,
    render_deliverable_payload, set_clock_payload,
)
from .test_users import (
    make_conform_editor_headers, make_dailies_coordinator_headers,
    make_facility_admin_headers, make_media_manager_headers,
    make_post_supervisor_headers, make_qc_operator_headers,
    make_reviewer_lead_headers, make_vendor_rep_headers,
)

PS = make_post_supervisor_headers()
MM = make_media_manager_headers()
DC = make_dailies_coordinator_headers()
CE = make_conform_editor_headers()
RL = make_reviewer_lead_headers()
QC = make_qc_operator_headers()
FA = make_facility_admin_headers()


def _ok(resp, step: str):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}") from exc


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Drive the server logical clock to the given instant (PRD §2.4)."""
    resp = api_client.set_current_utc(set_clock_payload(to_iso8601), FA)
    return _ok(resp, "set_clock")


# ---------------------------------------------------------------------------
# Tier 1: project creation / activation
# ---------------------------------------------------------------------------

def create_project(**overrides):
    resp = api_client.create_project(create_project_payload(**overrides), PS)
    return _ok(resp, "create_project")


def create_watermark_profile(project_id, **overrides):
    resp = api_client.create_watermark_profile(
        project_id, create_watermark_profile_payload(**overrides), PS)
    return _ok(resp, "create_watermark_profile")


def activate_watermark_profile(project_id, profile_id):
    resp = api_client.activate_watermark_profile(project_id, profile_id, PS)
    return _ok(resp, "activate_watermark_profile")


def create_bay(project_id, **overrides):
    resp = api_client.create_bay(project_id, create_bay_payload(**overrides), PS)
    return _ok(resp, "create_bay")


def activate_project(project_id):
    resp = api_client.activate_project(project_id, PS)
    return _ok(resp, "activate_project")


def setup_active_project(project_overrides=None, profile_overrides=None,
                         bay_overrides=None, clock=DEFAULT_CLOCK):
    """Project with one ACTIVE watermark profile and one AVAILABLE bay,
    advanced to ACTIVE. Returns (project, wm_profile, bay)."""
    set_clock(clock)
    project = create_project(**(project_overrides or {}))
    wm = create_watermark_profile(project["id"], **(profile_overrides or {}))
    activate_watermark_profile(project["id"], wm["id"])
    bay = create_bay(project["id"], **(bay_overrides or {}))
    project = activate_project(project["id"])
    return project, wm, bay


# ---------------------------------------------------------------------------
# Tier 2: media ingest chain
# ---------------------------------------------------------------------------

def create_batch(project_id, **overrides):
    resp = api_client.create_batch(project_id, create_batch_payload(**overrides), MM)
    return _ok(resp, "create_batch")


def start_ingest(project_id, batch_id):
    resp = api_client.start_ingest(project_id, batch_id, MM)
    return _ok(resp, "start_ingest")


def create_asset(project_id, batch_id, **overrides):
    resp = api_client.create_asset(
        project_id, create_asset_payload(batch_id, **overrides), MM)
    return _ok(resp, "create_asset")


def finish_ingest(project_id, batch_id):
    resp = api_client.finish_ingest(project_id, batch_id, MM)
    return _ok(resp, "finish_ingest")


def proxy_complete(project_id, asset_id, proxy_bytes=500):
    resp = api_client.proxy_complete(
        project_id, asset_id, proxy_complete_payload(proxy_bytes), MM)
    return _ok(resp, "proxy_complete")


def verify_asset(project_id, asset_id):
    resp = api_client.verify_asset(project_id, asset_id, MM)
    return _ok(resp, "verify_asset")


def conform_asset(project_id, asset_id):
    resp = api_client.conform_asset(project_id, asset_id, CE)
    return _ok(resp, "conform_asset")


def lock_asset(project_id, asset_id):
    resp = api_client.lock_asset(project_id, asset_id, CE)
    return _ok(resp, "lock_asset")


def setup_batch_ingesting(project=None, asset_specs=None, **project_kwargs):
    """ACTIVE project + batch in INGESTING with assets registered.
    asset_specs: list of per-asset overrides (default: one 1000-byte asset).
    Returns (project, batch, [assets])."""
    if project is None:
        project, _wm, _bay = setup_active_project(project_overrides=project_kwargs or None)
    batch = create_batch(project["id"])
    start_ingest(project["id"], batch["id"])
    specs = asset_specs if asset_specs is not None else [{}]
    assets = []
    for i, spec in enumerate(specs):
        spec.setdefault("clip_name", f"C{i + 1:03d}")
        assets.append(create_asset(project["id"], batch["id"], **spec))
    return project, batch, assets


def setup_batch_proxying(project=None, asset_specs=None, **project_kwargs):
    """ACTIVE project + batch in PROXYING (ingest finished; proxies RUNNING).
    Returns (project, batch, [assets])."""
    project, batch, assets = setup_batch_ingesting(project, asset_specs, **project_kwargs)
    finish_ingest(project["id"], batch["id"])
    return project, batch, assets


def setup_batch_ready(project=None, asset_specs=None, proxy_bytes=500, **project_kwargs):
    """ACTIVE project + batch in READY (all proxies DONE).
    Returns (project, batch, [assets])."""
    project, batch, assets = setup_batch_proxying(project, asset_specs, **project_kwargs)
    for asset in assets:
        proxy_complete(project["id"], asset["id"], proxy_bytes)
    batch = _ok(api_client.get_batch(project["id"], batch["id"], MM), "get_batch")
    assert batch["status"] == "READY", f"Setup failed: batch is {batch['status']}, expected READY"
    return project, batch, assets


def setup_verified_asset(**project_kwargs):
    """ACTIVE project + one VERIFIED asset in a READY batch.
    Returns (project, batch, asset)."""
    project, batch, assets = setup_batch_ready(**project_kwargs)
    asset = verify_asset(project["id"], assets[0]["id"])
    return project, batch, asset


# ---------------------------------------------------------------------------
# Tier 2/3: vendor + turnover chain
# ---------------------------------------------------------------------------

def create_vendor(**overrides):
    resp = api_client.create_vendor(create_vendor_payload(**overrides), FA)
    return _ok(resp, "create_vendor")


def create_turnover(project_id, **overrides):
    resp = api_client.create_turnover(project_id, create_turnover_payload(**overrides), CE)
    return _ok(resp, "create_turnover")


def stage_turnover(project_id, turnover_id):
    resp = api_client.stage_turnover(project_id, turnover_id, CE)
    return _ok(resp, "stage_turnover")


def create_vendor_bid(project_id, turnover_id, vendor_id, **overrides):
    """Submit a bid; VendorRep identity is threaded as the vendor's own id."""
    resp = api_client.create_vendor_bid(
        project_id, create_vendor_bid_payload(turnover_id, vendor_id, **overrides),
        make_vendor_rep_headers(vendor_id))
    return _ok(resp, "create_vendor_bid")


def award_bid(project_id, bid_id):
    resp = api_client.award_bid(project_id, bid_id, PS)
    return _ok(resp, "award_bid")


def issue_turnover(project_id, turnover_id):
    resp = api_client.issue_turnover(project_id, turnover_id, PS)
    return _ok(resp, "issue_turnover")


def ack_turnover(project_id, turnover_id, vendor_id):
    resp = api_client.ack_turnover(project_id, turnover_id, make_vendor_rep_headers(vendor_id))
    return _ok(resp, "ack_turnover")


def return_turnover(project_id, turnover_id, vendor_id):
    resp = api_client.return_turnover(project_id, turnover_id, make_vendor_rep_headers(vendor_id))
    return _ok(resp, "return_turnover")


def close_turnover(project_id, turnover_id):
    resp = api_client.close_turnover(project_id, turnover_id, PS)
    return _ok(resp, "close_turnover")


def setup_staged_turnover_with_bid(project=None, vendor_overrides=None,
                                   turnover_overrides=None, **project_kwargs):
    """ACTIVE project + STAGED turnover + one SUBMITTED bid from an ONBOARDED
    vendor whose capabilities cover the turnover kind.
    Returns (project, turnover, vendor, bid)."""
    if project is None:
        project, _wm, _bay = setup_active_project(project_overrides=project_kwargs or None)
    turnover = create_turnover(project["id"], **(turnover_overrides or {}))
    stage_turnover(project["id"], turnover["id"])
    kind = turnover["turnover_kind"]
    vendor = create_vendor(**(vendor_overrides or {"capabilities": [kind]}))
    bid = create_vendor_bid(project["id"], turnover["id"], vendor["id"])
    return project, turnover, vendor, bid


def setup_issued_turnover(project=None, vendor_overrides=None,
                          turnover_overrides=None, **project_kwargs):
    """ACTIVE project + turnover ISSUED to an ONBOARDED vendor.
    Returns (project, turnover, vendor, bid)."""
    project, turnover, vendor, bid = setup_staged_turnover_with_bid(
        project, vendor_overrides, turnover_overrides, **project_kwargs)
    award_bid(project["id"], bid["id"])
    turnover = issue_turnover(project["id"], turnover["id"])
    return project, turnover, vendor, bid


# ---------------------------------------------------------------------------
# Tier 4: conform-ready project + deliverable
# ---------------------------------------------------------------------------

def setup_conform_ready_project(**project_kwargs):
    """ACTIVE project where conform_ready == true: the single asset is LOCKED
    and one turnover is ISSUED. Returns (project, batch, asset, turnover,
    vendor, bid)."""
    project, batch, asset = setup_verified_asset(**project_kwargs)
    turnover = create_turnover(project["id"], turnover_kind="CONFORM",
                               sequence_label="SEQ-01")
    stage_turnover(project["id"], turnover["id"])
    vendor = create_vendor(capabilities=["CONFORM"])
    bid = create_vendor_bid(project["id"], turnover["id"], vendor["id"])
    award_bid(project["id"], bid["id"])
    turnover = issue_turnover(project["id"], turnover["id"])
    asset = conform_asset(project["id"], asset["id"])
    asset = lock_asset(project["id"], asset["id"])
    project = _ok(api_client.get_project(project["id"], PS), "get_project")
    assert project["conform_ready"] is True, (
        f"Setup failed: conform_ready is {project['conform_ready']}")
    return project, batch, asset, turnover, vendor, bid


def create_deliverable(project_id, **overrides):
    resp = api_client.create_deliverable(
        project_id, create_deliverable_payload(**overrides), CE)
    return _ok(resp, "create_deliverable")


def render_deliverable(project_id, deliverable_id):
    """Render with the project's CURRENT version (re-fetched each call)."""
    project = _ok(api_client.get_project(project_id, PS), "get_project")
    resp = api_client.render_deliverable(
        project_id, deliverable_id,
        render_deliverable_payload(project["version"]), CE)
    return _ok(resp, "render_deliverable")


def render_complete(project_id, deliverable_id):
    resp = api_client.render_complete_deliverable(project_id, deliverable_id, CE)
    return _ok(resp, "render_complete_deliverable")


def enqueue_qc(project_id, deliverable_id):
    resp = api_client.enqueue_qc(project_id, deliverable_id, QC)
    return _ok(resp, "enqueue_qc")


def create_qc_report(project_id, deliverable_id, verdict="FAIL", **overrides):
    resp = api_client.create_qc_report(
        project_id, deliverable_id,
        create_qc_report_payload(verdict, **overrides), QC)
    return _ok(resp, "create_qc_report")


def setup_qc_failed_deliverable(fail_count=1, **project_kwargs):
    """conform_ready project + deliverable (requires_qc=True) driven through
    render → render-complete → enqueue-qc → FAIL report(s), cycling
    QC_FAILED → RENDERING between attempts.
    Returns (project, deliverable, asset, turnover, vendor)."""
    project, batch, asset, turnover, vendor, bid = setup_conform_ready_project(**project_kwargs)
    deliverable = create_deliverable(project["id"])
    for attempt in range(fail_count):
        render_deliverable(project["id"], deliverable["id"])
        render_complete(project["id"], deliverable["id"])
        enqueue_qc(project["id"], deliverable["id"])
        create_qc_report(project["id"], deliverable["id"], verdict="FAIL")
    deliverable = _ok(
        api_client.get_deliverable(project["id"], deliverable["id"], CE),
        "get_deliverable")
    assert deliverable["status"] == "QC_FAILED"
    assert deliverable["qc_attempt_count"] == fail_count
    return project, deliverable, asset, turnover, vendor


# ---------------------------------------------------------------------------
# Tier 3: dailies chain
# ---------------------------------------------------------------------------

def create_dailies_package(project_id, batch_id, watermark_profile_id, **overrides):
    resp = api_client.create_dailies_package(
        project_id,
        create_dailies_package_payload(batch_id, watermark_profile_id, **overrides),
        DC)
    return _ok(resp, "create_dailies_package")


def publish_dailies_package(project_id, package_id):
    resp = api_client.publish_dailies_package(project_id, package_id, DC)
    return _ok(resp, "publish_dailies_package")


def setup_published_dailies(**project_kwargs):
    """ACTIVE project + READY batch + PUBLISHED dailies package.
    Returns (project, batch, assets, package)."""
    project, batch, assets = setup_batch_ready(**project_kwargs)
    wm = _ok(api_client.list_watermark_profiles(project["id"], PS),
             "list_watermark_profiles")[0]
    package = create_dailies_package(project["id"], batch["id"], wm["id"])
    package = publish_dailies_package(project["id"], package["id"])
    return project, batch, assets, package


# ---------------------------------------------------------------------------
# Review rounds / notes
# ---------------------------------------------------------------------------

def create_review_round(project_id, target_kind, target_ref_id, **overrides):
    resp = api_client.create_review_round(
        project_id, create_review_round_payload(target_kind, target_ref_id, **overrides), RL)
    return _ok(resp, "create_review_round")


def create_review_note(project_id, round_id, **overrides):
    resp = api_client.create_review_note(
        project_id, create_review_note_payload(round_id, **overrides), RL)
    return _ok(resp, "create_review_note")


def close_round_notes(project_id, round_id):
    resp = api_client.close_round_notes(project_id, round_id, RL)
    return _ok(resp, "close_round_notes")


def approve_review_round(project_id, round_id):
    resp = api_client.approve_review_round(project_id, round_id, RL)
    return _ok(resp, "approve_review_round")


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def create_booking(project_id, bay_id, expected_bay_version, **overrides):
    resp = api_client.create_booking(
        project_id,
        create_booking_payload(bay_id, expected_bay_version, **overrides),
        PS)
    return _ok(resp, "create_booking")


def current_bay_version(project_id, bay_id):
    """Re-read a bay's version via the project bay list."""
    bays = _ok(api_client.list_bays(project_id, PS), "list_bays")
    for bay in bays:
        if bay["id"] == bay_id:
            return bay["version"]
    raise AssertionError(f"Setup failed: bay {bay_id} not found in list")


# ---------------------------------------------------------------------------
# Archive jobs
# ---------------------------------------------------------------------------

def create_archive_job(project_id, **overrides):
    resp = api_client.create_archive_job(
        project_id, create_archive_job_payload(**overrides), MM)
    return _ok(resp, "create_archive_job")


def seal_archive_job(project_id, job_id):
    """Drive QUEUED -> WRITING -> VERIFYING -> SEALED. Returns the SEALED job."""
    _ok(api_client.start_archive_job(project_id, job_id, MM), "start_archive_job")
    _ok(api_client.verify_archive_job(project_id, job_id, MM), "verify_archive_job")
    return _ok(api_client.seal_archive_job(project_id, job_id, MM), "seal_archive_job")


def setup_sealed_archive_job(project, **overrides):
    job = create_archive_job(project["id"], **overrides)
    return seal_archive_job(project["id"], job["id"])


# ---------------------------------------------------------------------------
# Change lists
# ---------------------------------------------------------------------------

def create_change_list(project_id, turnover_id, entries, **overrides):
    resp = api_client.create_change_list(
        project_id, create_change_list_payload(turnover_id, entries, **overrides), CE)
    return _ok(resp, "create_change_list")


def current_turnover_version(project_id, turnover_id):
    turnover = _ok(api_client.get_turnover(project_id, turnover_id, CE),
                   "get_turnover")
    return turnover["version"]
