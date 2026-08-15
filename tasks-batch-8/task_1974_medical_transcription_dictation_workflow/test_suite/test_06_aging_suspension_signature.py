"""Unsigned-report aging, provider suspension, and the signature queue."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_workgroup, setup_provider, setup_unsigned_delivered_transcripts,
    deliver_job,
    create_job, claim_job, submit_job, review_job, set_clock,
    get_job, get_editor, get_provider, get_clinic, get_job_transcripts,
    create_dictation_job_payload,
    make_provider_headers, make_editor_headers, TEST_USERS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]
CLIENT = TEST_USERS["client_admin_headers"]


def test_clock_sweep_suspends_provider_and_counts_clinic(api):
    """PRD §3.7: "When the aged count reaches the clinic's
    `unsigned_report_threshold`, the provider is suspended from either
    `ACTIVE` or `WARNING`: the status becomes `SUSPENDED`, `suspension_reason`
    is set to `UNSIGNED_REPORT_AGING`, and the clinic's
    `suspended_provider_count` is recomputed."
    PRD §3.7: "Its `aging_tier` becomes `TIER_2` once that age reaches the
    clinic's `aging_tier2_hours`, `TIER_1` once it reaches `aging_tier1_hours`,
    and `NONE` before that; the boundary is inclusive, so a transcript aged to
    exactly a threshold crosses into that tier."

    Design: Difficulty/transitive_cascade/clock_sweep_aging_suspension_cascade
    """
    fx = setup_unsigned_delivered_transcripts(n=3, with_billing_period=True)
    set_clock("2026-08-16T00:00:00Z")  # 360h after T0 delivery
    for transcript in fx["transcripts"]:
        current = validate_success(api.get_transcript(transcript["id"], VENDOR))
        assert current["aging_tier"] == "TIER_2", "Link 1: 360h >= 72h -> TIER_2"
    provider = get_provider(fx["provider"]["id"])
    assert provider["unsigned_aged_count"] == 3, "Link 2: all three aged"
    assert provider["status"] == "SUSPENDED", "3 >= threshold 3"
    assert provider["suspension_reason"] == "UNSIGNED_REPORT_AGING"
    clinic = get_clinic(fx["clinic"]["id"])
    assert clinic["suspended_provider_count"] == 1, "Link 3: clinic counter recomputed"


def test_clock_sweep_sets_billing_hold_after_grace(api):
    """PRD §3.9: "`billing_hold` is true exactly when the clinic has a
    `FINALIZED` period whose payment window has lapsed — the current logical
    time at or after that period's `finalized_at` plus `payment_grace_days`
    days, each day counted as 86,400 seconds, with the exact boundary counting
    as overdue."

    Design: Difficulty/transitive_cascade/clock_sweep_aging_suspension_cascade
    """
    fx = setup_unsigned_delivered_transcripts(n=3, with_billing_period=True)
    # finalized_at == T0 (2026-08-01); grace 14d -> hold from 2026-08-15 on.
    set_clock("2026-08-16T00:00:00Z")
    clinic = get_clinic(fx["clinic"]["id"])
    assert clinic["billing_hold"] is True, (
        "finalized 2026-08-01 + 14d grace <= 2026-08-16")


def test_provider_warning_at_tier1_boundary_and_recovery_on_sign(api):
    """PRD §3.7: "When the two unsigned counts sum to at least one but the
    suspension threshold is not met, the provider moves from `ACTIVE` to
    `WARNING`, which is advisory and leaves clinic counters untouched."
    PRD §3.8: "The transcript moves from `DELIVERED` to `SIGNED`, its
    `signed_at` is stamped, and its `aging_tier` freezes — a signed transcript
    stops aging immediately. The provider's unsigned counters are recomputed
    right away, which is how a provider in `WARNING` earns an immediate return
    to `ACTIVE` without waiting for the next sweep."

    Design: Corner/state_machines/provider_warning_at_tier1_boundary_and_recovery_on_sign
    """
    fx = setup_unsigned_delivered_transcripts(n=1)
    transcript = fx["transcripts"][0]
    provider = fx["provider"]
    set_clock("2026-08-02T00:00:00Z")  # exactly +24h — boundary is inclusive
    aged = validate_success(api.get_transcript(transcript["id"], VENDOR))
    assert aged["aging_tier"] == "TIER_1"
    warned = get_provider(provider["id"])
    assert warned["unsigned_tier1_count"] == 1
    assert warned["status"] == "WARNING"
    signed = validate_success(api.sign_transcript(
        transcript["id"], make_provider_headers(provider["id"])))
    assert signed["status"] == "SIGNED"
    assert signed["signed_at"] is not None
    recovered = get_provider(provider["id"])
    assert recovered["unsigned_tier1_count"] == 0
    assert recovered["unsigned_aged_count"] == 0
    assert recovered["status"] == "ACTIVE", (
        "auto-recovery from WARNING on sign, no reinstate call needed")


def test_provider_reinstate_blocked_until_aged_reports_signed(api):
    """PRD §3.7: "Suspension, by contrast, never lifts itself: signing down the
    backlog reduces the counts but leaves a `SUSPENDED` provider suspended
    until a `ClientAdmin` reinstates them, and reinstatement is refused while
    any aged unsigned report remains — `unsigned_aged_count` must be zero,
    otherwise `ERR_UNSIGNED_REPORTS_REMAIN`. A successful reinstatement returns
    the provider to `ACTIVE`, clears `suspension_reason` to null, and
    recomputes the clinic's `suspended_provider_count`."

    Design: Corner/state_machines/provider_reinstate_blocked_until_aged_reports_signed
    """
    fx = setup_unsigned_delivered_transcripts(n=3)
    provider = fx["provider"]
    set_clock("2026-08-04T00:00:00Z")  # exactly +72h -> all three TIER_2
    assert get_provider(provider["id"])["status"] == "SUSPENDED"
    blocked = api.reinstate_provider(provider["id"], CLIENT)
    validate_error(blocked, ApiErrorId.ERR_UNSIGNED_REPORTS_REMAIN)
    # Signing is the cure path: still allowed while SUSPENDED.
    for transcript in fx["transcripts"]:
        validate_success(api.sign_transcript(
            transcript["id"], make_provider_headers(provider["id"])))
    reinstated = validate_success(api.reinstate_provider(provider["id"], CLIENT))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert get_clinic(fx["clinic"]["id"])["suspended_provider_count"] == 0


def test_suspended_provider_upload_rejected(api):
    """PRD §3.3: "A provider whose `status` is `SUSPENDED` cannot upload at all
    and is rejected with `ERR_PROVIDER_SUSPENDED`."
    PRD §3.7: "Its `aging_tier` becomes `TIER_2` once that age reaches the
    clinic's `aging_tier2_hours`, `TIER_1` once it reaches `aging_tier1_hours`,
    and `NONE` before that; the boundary is inclusive, so a transcript aged to
    exactly a threshold crosses into that tier."

    Design: Difficulty/cross_entity_state_dependency/upload_gated_by_provider_standing
    """
    fx = setup_unsigned_delivered_transcripts(n=3)
    provider = fx["provider"]
    set_clock("2026-08-04T00:00:00Z")  # exactly +72h, inclusive boundary
    assert get_provider(provider["id"])["status"] == "SUSPENDED"
    resp = api.create_dictation_job(
        create_dictation_job_payload(provider["id"]),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SUSPENDED)


def test_warning_provider_upload_still_allowed(api):
    """PRD §3.7: "When the two unsigned counts sum to at least one but the
    suspension threshold is not met, the provider moves from `ACTIVE` to
    `WARNING`, which is advisory and leaves clinic counters untouched."
    PRD §3.3: "A provider whose `status` is `SUSPENDED` cannot upload at all
    and is rejected with `ERR_PROVIDER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/upload_gated_by_provider_standing
    """
    fx = setup_unsigned_delivered_transcripts(n=1)
    provider = fx["provider"]
    set_clock("2026-08-02T00:00:00Z")  # +24h -> TIER_1 -> WARNING (1 < 3)
    assert get_provider(provider["id"])["status"] == "WARNING"
    resp = api.create_dictation_job(
        create_dictation_job_payload(provider["id"]),
        make_provider_headers(provider["id"]))
    job = validate_success(resp, 201)
    assert job["workflow_status"] == "QUEUED", (
        "the upload gate fires only at SUSPENDED, not WARNING")


def test_aging_tiers_at_exact_hour_boundaries(api):
    """PRD §3.7: "Its `aging_tier` becomes `TIER_2` once that age reaches the
    clinic's `aging_tier2_hours`, `TIER_1` once it reaches `aging_tier1_hours`,
    and `NONE` before that; the boundary is inclusive, so a transcript aged to
    exactly a threshold crosses into that tier."

    Design: Corner/calculations/aging_tiers_at_exact_hour_boundaries
    """
    fx = setup_unsigned_delivered_transcripts(n=1)
    transcript = fx["transcripts"][0]

    def tier_at(instant):
        set_clock(instant)
        return validate_success(
            api.get_transcript(transcript["id"], VENDOR))["aging_tier"]

    assert tier_at("2026-08-01T23:59:00Z") == "NONE"
    assert tier_at("2026-08-02T00:00:00Z") == "TIER_1"   # +24:00 inclusive
    assert tier_at("2026-08-03T23:59:00Z") == "TIER_1"   # +71:59
    assert tier_at("2026-08-04T00:00:00Z") == "TIER_2"   # +72:00 inclusive
    # Threshold 3 with a single transcript: WARNING but never SUSPENDED.
    assert get_provider(fx["provider"]["id"])["status"] == "WARNING"


def test_provider_return_reopens_job_to_original_editor(api):
    """PRD §3.8: "The provider sends a `DELIVERED` transcript back, moving it
    to `RETURNED`, which is terminal for that version, and the provider's
    unsigned counters are recomputed. The parent job reopens in step: it moves
    from `DELIVERED` back to `EDITING`, its `rework_count` is incremented, and
    the system re-claims it to the transcript's authoring `editor_id` with a
    fresh `claimed_at`. This system re-claim deliberately bypasses the capacity
    ceiling and the shift-window gate, and it does not trigger any preemption;
    the re-claimed editor's `active_claim_count` is simply incremented."

    Design: Corner/state_machines/provider_return_reopens_job_to_original_editor
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    delivered = deliver_job(provider, editor)
    job = delivered["job"]
    t1 = delivered["transcript"]
    assert get_editor(editor["id"])["active_claim_count"] == 0

    returned = validate_success(api.return_transcript(
        t1["id"], make_provider_headers(provider["id"])))
    assert returned["status"] == "RETURNED"
    reopened = get_job(job["id"])
    assert reopened["workflow_status"] == "EDITING"
    assert reopened["rework_count"] == 1
    assert reopened["claimed_by_editor_id"] == editor["id"], (
        "system re-claim to the transcript's authoring editor")
    assert get_editor(editor["id"])["active_claim_count"] == 1
    # The reopened job accepts a new submission, burning a new version.
    submit_job(job["id"], editor)
    review_job(job["id"], 0, 0, 0)
    versions = {(t["version_number"], t["status"])
                for t in get_job_transcripts(job["id"])}
    assert versions == {(1, "RETURNED"), (2, "DELIVERED")}
    assert get_editor(editor["id"])["active_claim_count"] == 0


def test_provider_cannot_sign_other_providers_transcript(api):
    """PRD §2.1: "When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of
    the acting Provider; ownership checks on any resource that references a
    Provider compare the resource's foreign-key field to `X-User-ID`, and for
    transcript-level actions the comparison is made against the owning job's
    provider."
    PRD §3.8: "The provider whose job owns the transcript signs it; the
    transcript must be `DELIVERED` (`ERR_TRANSCRIPT_NOT_DELIVERED`), and the
    caller must be that provider (`ERR_FORBIDDEN_OWNERSHIP`)."

    Design: Corner/rbac/provider_cannot_sign_other_providers_transcript
    """
    wg = setup_workgroup()
    p1 = wg["provider"]
    p2 = setup_provider(wg["clinic"]["id"], full_name="P Two")
    delivered = deliver_job(p1, wg["editor"])
    transcript = delivered["transcript"]
    resp = api.sign_transcript(transcript["id"], make_provider_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    current = validate_success(api.get_transcript(transcript["id"], VENDOR))
    assert current["status"] == "DELIVERED"
    assert current["signed_at"] is None
