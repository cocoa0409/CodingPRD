"""Storage tiering: migration lifecycle, OCC pinning, supersede invariant, cost math."""
from test_helpers import (
    api_client, validate_paginated,
    validate_success, validate_error, ApiErrorId,
    create_asset, create_migration_job, get_asset, set_clock,
    create_migration_job_payload,
    make_archivist_lead_headers, make_legal_counsel_headers,
    create_legal_hold,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
LAB = TEST_USERS["lab_technician_headers"]


def _run_job(job_id, complete_at=None, checksum="ok"):
    validate_success(api_client.start_migration_job(job_id, LAB), 200)
    if complete_at is not None:
        set_clock(complete_at)
    return validate_success(api_client.complete_migration_job(
        job_id, {"checksum_sha256": checksum}, LAB), 200)


# ─── dual-variant storage cost (Difficulty x2) ────────

def _setup_mid_month_migration():
    """100 GB asset created at the default clock (ONLINE); migration ONLINE->NEARLINE
    completed 2026-08-06T00:00:00Z; clock then at 2026-08-11T00:00:00Z."""
    asset = create_asset(size_gb=100)
    job = create_migration_job(asset["id"], "NEARLINE",
                               expected_asset_version=asset["version"])
    _run_job(job["id"], complete_at="2026-08-06T00:00:00Z")
    set_clock("2026-08-11T00:00:00Z")
    return asset


def test_storage_cost_projected_vs_actual_values(api):
    """PRD §3.8: "The days remaining count today inclusively — the number of days in the
    month minus the current day of the month plus one — and the projected cost is
    `size_gb` times the current tier's rate times the days remaining, rounded half up
    once to integer cents."
    (Projected: 100 GB x 1.5 x (31 - 11 + 1 = 21) = 3150.)
    PRD §3.8: "Each interval is priced independently: its length in hours (the interval
    span in seconds divided by 3,600), multiplied by `size_gb` and the interval tier's
    daily rate divided by 24, rounded half up to integer cents per interval."
    (Actual: ONLINE [08-01, 08-06) 120h -> 2000; NEARLINE [08-06, 08-11) 120h -> 750;
    total 2750.)

    Design: Difficulty/dual_variant_calc/storage_cost_projected_vs_actual
    """
    asset = _setup_mid_month_migration()
    assert get_asset(asset["id"])["storage_tier"] == "NEARLINE"

    cost = validate_success(api.get_storage_cost(asset["id"], FINANCE), 200)
    assert cost["projected_cost_cents"] == 3150
    assert cost["actual_cost_cents"] == 2750
    assert "currency" in cost, "PRD §2.9: the storage-cost read returns a currency label"


def test_storage_cost_variants_diverge_after_mid_month_migration(api):
    """PRD §3.8: "The two variants diverge precisely when a migration changed the
    asset's tier partway through the month."
    PRD §3.8: "The projected variant is forward-looking and ignores migration history".

    Design: Difficulty/dual_variant_calc/storage_cost_projected_vs_actual
    """
    asset = _setup_mid_month_migration()
    cost = validate_success(api.get_storage_cost(asset["id"], FINANCE), 200)
    assert cost["projected_cost_cents"] != cost["actual_cost_cents"]
    assert cost["projected_cost_cents"] == 3150
    assert cost["actual_cost_cents"] == 2750


# ─── per-interval rounding order (Difficulty x2) ──────

def _setup_three_interval_asset():
    """1 GB asset: ONLINE [00:00, 09:36), NEARLINE [09:36, 19:12), ONLINE [19:12, 24:00);
    clock then at 2026-08-02T00:00:00Z."""
    asset = create_asset(size_gb=1, media_type="AUDIO")
    j1 = create_migration_job(asset["id"], "NEARLINE",
                              expected_asset_version=asset["version"])
    _run_job(j1["id"], complete_at="2026-08-01T09:36:00Z")
    j2 = create_migration_job(asset["id"], "ONLINE")  # version re-read inside fixture
    _run_job(j2["id"], complete_at="2026-08-01T19:12:00Z")
    set_clock("2026-08-02T00:00:00Z")
    return asset


def test_storage_actual_rounds_per_interval_then_sums(api):
    """PRD §3.8: "The actual cost is the sum of those per-interval figures — each
    interval rounded before any summation."
    (ONLINE 9.6h: 1 GB x 4 x 9.6/24 = 1.6 -> 2; NEARLINE 9.6h: 1 x 1.5 x 9.6/24 = 0.6
    -> 1; ONLINE 4.8h: 1 x 4 x 4.8/24 = 0.8 -> 1; actual = 2 + 1 + 1 = 4.)

    Design: Difficulty/combinatorial_formula/storage_actual_round_per_interval_then_sum
    """
    asset = _setup_three_interval_asset()
    cost = validate_success(api.get_storage_cost(asset["id"], FINANCE), 200)
    assert cost["actual_cost_cents"] == 4, (
        "per-interval round-half-up (2 + 1 + 1); sum-then-round would give 3")


def test_storage_projected_after_return_to_online(api):
    """PRD §3.8: "The days remaining count today inclusively — the number of days in the
    month minus the current day of the month plus one — and the projected cost is
    `size_gb` times the current tier's rate times the days remaining, rounded half up
    once to integer cents."
    (At 2026-08-02 with the asset back at ONLINE: 1 GB x 4 x (31 - 2 + 1 = 30) = 120.)

    Design: Difficulty/combinatorial_formula/storage_actual_round_per_interval_then_sum
    """
    asset = _setup_three_interval_asset()
    assert get_asset(asset["id"])["storage_tier"] == "ONLINE"
    cost = validate_success(api.get_storage_cost(asset["id"], FINANCE), 200)
    assert cost["projected_cost_cents"] == 120
    assert cost["actual_cost_cents"] == 4


# ─── supersede / cancel invariant (Difficulty x2) ─────

def test_migration_supersede_then_cancel_conserves_tier_and_queue(api):
    """PRD §3.8: "Creating a job also supersedes the queue: any existing `QUEUED`
    migration job for the same asset moves to the terminal `SUPERSEDED` state".
    PRD §3.8: "An `ArchivistLead` may cancel a job while it is `QUEUED` or
    `HOLD_PAUSED` — from any other state, `ERR_JOB_NOT_CANCELLABLE` (HTTP 409) — moving
    it to the terminal `CANCELLED` state".

    Design: Difficulty/compensating_invariant/migration_supersede_cancel_conserves_tier_and_queue
    """
    asset = create_asset()
    job_a = create_migration_job(asset["id"], "NEARLINE",
                                 expected_asset_version=asset["version"])
    v2 = get_asset(asset["id"])["version"]
    job_b = create_migration_job(asset["id"], "DEEP_ARCHIVE", expected_asset_version=v2)

    superseded = validate_success(api.get_migration_job(job_a["id"], ARCHIVIST), 200)
    assert superseded["status"] == "SUPERSEDED"

    cancelled = validate_success(api.cancel_migration_job(job_b["id"], ARCHIVIST), 200)
    assert cancelled["status"] == "CANCELLED"

    assert get_asset(asset["id"])["storage_tier"] == "ONLINE", (
        "invariant: supersede+cancel must leave the tier unchanged")

    queued, _ = validate_paginated(api.list_migration_jobs(
        ARCHIVIST, params={"asset_id": asset["id"], "status": "QUEUED"}))
    assert len(queued) == 0, "no non-terminal QUEUED jobs may survive the pair"


def test_migration_create_bumps_asset_version_and_supersedes(api):
    """PRD §3.8: "Creating a job also supersedes the queue: any existing `QUEUED`
    migration job for the same asset moves to the terminal `SUPERSEDED` state, and the
    asset's `version` increments by one as part of the create."
    PRD §2.5: "The `version` is an integer that increments by exactly one on every
    mutation of the resource".

    Design: Difficulty/compensating_invariant/migration_supersede_cancel_conserves_tier_and_queue
    """
    asset = create_asset()
    v1 = asset["version"]
    job_a = create_migration_job(asset["id"], "NEARLINE", expected_asset_version=v1)
    assert get_asset(asset["id"])["version"] == v1 + 1
    job_b = create_migration_job(asset["id"], "DEEP_ARCHIVE")
    assert get_asset(asset["id"])["version"] == v1 + 2, (
        "exactly one version increment per pinned create")

    a_after = validate_success(api.get_migration_job(job_a["id"], ARCHIVIST), 200)
    b_after = validate_success(api.get_migration_job(job_b["id"], ARCHIVIST), 200)
    assert a_after["status"] == "SUPERSEDED"
    assert b_after["status"] == "QUEUED"
    assert get_asset(asset["id"])["storage_tier"] == "ONLINE"


# ─── retry budget, HOLD_PAUSED start, IN_PROGRESS gate ──

def test_migration_retry_budget_and_start_from_hold_paused(api):
    """PRD §3.8: "the migration retry budget is capped at 2, and a retry at the cap is
    rejected with `ERR_RETRY_BUDGET_EXHAUSTED` (HTTP 409)."
    PRD §3.8: "Starting moves `QUEUED` to `IN_PROGRESS` (from any other state,
    `ERR_JOB_NOT_QUEUED`, HTTP 409)."
    PRD §3.4: "Any migration job for the asset sitting in `QUEUED` is paused to
    `HOLD_PAUSED`."

    Design: Corner/state_machines/migration_retry_budget_and_start_from_hold_paused
    """
    a1 = create_asset(title="T")
    j1 = create_migration_job(a1["id"], "NEARLINE",
                              expected_asset_version=a1["version"])
    for round_no in (1, 2):
        validate_success(api.start_migration_job(j1["id"], LAB), 200)
        validate_success(api.fail_migration_job(j1["id"], {"reason": "x"}, LAB), 200)
        retried = validate_success(api.retry_migration_job(j1["id"], LAB), 200)
        assert retried["retry_count"] == round_no
    validate_success(api.start_migration_job(j1["id"], LAB), 200)
    validate_success(api.fail_migration_job(j1["id"], {"reason": "x"}, LAB), 200)

    res1 = api.retry_migration_job(j1["id"], LAB)
    validate_error(res1, ApiErrorId.ERR_RETRY_BUDGET_EXHAUSTED)

    a2 = create_asset(title="U")
    j2 = create_migration_job(a2["id"], "DEEP_ARCHIVE",
                              expected_asset_version=a2["version"])
    create_legal_hold(a2["id"], user_id="lc-1")
    paused = validate_success(api.get_migration_job(j2["id"], ARCHIVIST), 200)
    assert paused["status"] == "HOLD_PAUSED"

    res2 = api.start_migration_job(j2["id"], LAB)
    validate_error(res2, ApiErrorId.ERR_JOB_NOT_QUEUED)


def test_migration_create_while_in_progress_rejected(api):
    """PRD §3.8: "The asset must not be `DISPOSED` (`ERR_ASSET_DISPOSED`, HTTP 409),
    must be clear of legal holds (`ERR_LEGAL_HOLD_ACTIVE`, HTTP 409), and must not
    already have another migration job `IN_PROGRESS` (`ERR_JOB_IN_PROGRESS_EXISTS`,
    HTTP 409)."

    Design: Corner/errors/same_tier_and_in_progress_migration_rejected
    """
    asset = create_asset()
    j1 = create_migration_job(asset["id"], "NEARLINE",
                              expected_asset_version=asset["version"])
    validate_success(api.start_migration_job(j1["id"], LAB), 200)

    v_now = get_asset(asset["id"])["version"]
    res = api.create_migration_job(
        create_migration_job_payload(asset["id"], v_now, target_tier="NEARLINE"),
        ARCHIVIST)
    validate_error(res, ApiErrorId.ERR_JOB_IN_PROGRESS_EXISTS)


def test_occ_migration_create_stale_version_rejected(api):
    """PRD §2.7: "If the asset's current `version` no longer equals the supplied value —
    because another writer edited the asset's metadata, placed a hold on it, or created
    another pinned write against it in the meantime — the request is rejected with
    `ERR_STALE_ASSET_VERSION` (HTTP 412)."
    PRD §3.1: "each successful edit increments the asset's `version`".
    PRD §3.8: "the asset's `version` increments by one as part of the create."

    Design: Corner/cross_cutting_layers/occ_migration_create_stale_version_rejected
    """
    asset = create_asset()
    v1 = asset["version"]
    validate_success(api.patch_asset(asset["id"], {"title": "T2"},
                                     TEST_USERS["metadata_cataloger_headers"]), 200)

    stale = api.create_migration_job(
        create_migration_job_payload(asset["id"], v1, target_tier="NEARLINE"),
        ARCHIVIST)
    validate_error(stale, ApiErrorId.ERR_STALE_ASSET_VERSION)

    job = validate_success(api.create_migration_job(
        create_migration_job_payload(asset["id"], v1 + 1, target_tier="NEARLINE"),
        ARCHIVIST), 201)
    assert job["status"] == "QUEUED"

    v_after = get_asset(asset["id"])["version"]
    assert v_after == v1 + 2, "PATCH (+1) then job create (+1)"
