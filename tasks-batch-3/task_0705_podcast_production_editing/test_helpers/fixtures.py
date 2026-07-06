"""Composite setup helpers.

These encapsulate the multi-step preambles that most tests need to reach an
interesting state. The harness restarts the server (empty DB) before every
test, so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a
broken setup surfaces as a clear "Setup failed" rather than a confusing
assertion deep inside a test.

Identity threading: ShowOwner ops use make_show_owner_headers(show_id);
ProducerEng session ops use make_producer_eng_headers(engineer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_platform_admin_headers,
    make_ad_ops_headers,
    make_show_owner_headers,
    make_producer_eng_headers,
)
from .factories import (
    create_show_payload,
    create_contract_payload,
    create_retainer_cycle_payload,
    create_engineer_payload,
    create_episode_payload,
    create_session_payload,
    create_deliverable_payload,
    create_asset_version_payload,
    create_ad_campaign_payload,
    create_ad_slot_payload,
)

ADMIN = make_platform_admin_headers()
ADOPS = make_ad_ops_headers()


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------
def set_clock(iso8601):
    """Advance the logical clock to a fixed instant."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


def create_show(billing_model="PER_EPISODE", fmt="SOLO", target_loudness_lufs=None,
                title="Test Show"):
    overrides = {"title": title, "format": fmt, "billing_model": billing_model}
    if target_loudness_lufs is not None:
        overrides["target_loudness_lufs"] = target_loudness_lufs
    return get_success_data(api_client.create_show(create_show_payload(**overrides), ADMIN))


def create_engineer(name="Eng", remote_buffer_minutes=None, active=None):
    overrides = {"name": name}
    if remote_buffer_minutes is not None:
        overrides["remote_buffer_minutes"] = remote_buffer_minutes
    if active is not None:
        overrides["active"] = active
    return get_success_data(api_client.create_engineer(create_engineer_payload(**overrides), ADMIN))


def create_contract(show_id, tier="STANDARD", engagement_type="PER_EPISODE",
                    monthly_included_episodes=None, loyalty_discount_pct=None):
    overrides = {"tier": tier, "engagement_type": engagement_type}
    if monthly_included_episodes is not None:
        overrides["monthly_included_episodes"] = monthly_included_episodes
    if loyalty_discount_pct is not None:
        overrides["loyalty_discount_pct"] = loyalty_discount_pct
    return get_success_data(
        api_client.create_contract(create_contract_payload(show_id, **overrides), ADMIN))


def create_active_contract(show_id, tier="STANDARD", engagement_type="PER_EPISODE",
                           monthly_included_episodes=None, loyalty_discount_pct=None):
    """Create a contract and activate it. Returns the activated contract."""
    contract = create_contract(show_id, tier, engagement_type,
                               monthly_included_episodes, loyalty_discount_pct)
    return get_success_data(api_client.activate_contract(contract["id"], ADMIN))


def create_show_with_active_contract(tier="STANDARD", engagement_type="PER_EPISODE",
                                     billing_model="PER_EPISODE", fmt="SOLO",
                                     target_loudness_lufs=None,
                                     monthly_included_episodes=None,
                                     loyalty_discount_pct=None,
                                     title="Test Show"):
    """Show + activated contract (posture ACTIVE). Returns (show, contract)."""
    show = create_show(billing_model=billing_model, fmt=fmt,
                       target_loudness_lufs=target_loudness_lufs, title=title)
    contract = create_active_contract(
        show["id"], tier=tier, engagement_type=engagement_type,
        monthly_included_episodes=monthly_included_episodes,
        loyalty_discount_pct=loyalty_discount_pct)
    return show, contract


def create_episode(show_id, contract_id, planned_track_count=1,
                   transcript_requested=None, title="Test Episode"):
    owner = make_show_owner_headers(show_id)
    overrides = {"title": title, "planned_track_count": planned_track_count}
    if transcript_requested is not None:
        overrides["transcript_requested"] = transcript_requested
    return get_success_data(
        api_client.create_episode(create_episode_payload(show_id, contract_id, **overrides), owner))


def book_session(episode_id, engineer_id, start_utc, end_utc, capture_mode="STUDIO"):
    eng = make_producer_eng_headers(engineer_id)
    return get_success_data(api_client.create_session(
        create_session_payload(episode_id, engineer_id, start_utc, end_utc,
                               capture_mode=capture_mode), eng))


# ---------------------------------------------------------------------------
# Tier 1 — state progression on Episode
# ---------------------------------------------------------------------------
def record_session_to_completion(episode_id, engineer_id, start_utc, end_utc,
                                 complete_at=None, capture_mode="STUDIO"):
    """Book -> start -> (optional clock) -> complete a session, bubbling the
    episode RECORDING -> EDITING. Returns the completed session."""
    eng = make_producer_eng_headers(engineer_id)
    session = book_session(episode_id, engineer_id, start_utc, end_utc, capture_mode)
    get_success_data(api_client.start_session(session["id"], eng))
    if complete_at is not None:
        set_clock(complete_at)
    completed = get_success_data(api_client.complete_session(session["id"], eng))
    return completed


def lock_assets(episode_id, engineer_id, raw_track_count, lock_at=None):
    """Optionally advance clock, then lock assets. Returns the episode."""
    eng = make_producer_eng_headers(engineer_id)
    if lock_at is not None:
        set_clock(lock_at)
    return get_success_data(api_client.lock_assets(
        episode_id, {"raw_track_count": raw_track_count}, eng))


def add_accepted_master_audio(episode_id, engineer_id, integrated_loudness_lufs=-16.0):
    """Create a MASTER_AUDIO deliverable + submit an in-spec version + accept it.
    Returns (deliverable, asset_version)."""
    eng = make_producer_eng_headers(engineer_id)
    deliverable = get_success_data(api_client.create_deliverable(
        create_deliverable_payload(episode_id, "MASTER_AUDIO"), eng))
    version = get_success_data(api_client.create_asset_version(
        create_asset_version_payload(deliverable["id"],
                                     integrated_loudness_lufs=integrated_loudness_lufs), eng))
    get_success_data(api_client.accept_asset_version(version["id"], eng))
    return deliverable, version


def add_accepted_transcript(episode_id, engineer_id):
    """Create a TRANSCRIPT deliverable + submit a version + accept it.
    Returns (deliverable, asset_version)."""
    eng = make_producer_eng_headers(engineer_id)
    deliverable = get_success_data(api_client.create_deliverable(
        create_deliverable_payload(episode_id, "TRANSCRIPT"), eng))
    version = get_success_data(api_client.create_asset_version(
        create_asset_version_payload(deliverable["id"]), eng))
    get_success_data(api_client.accept_asset_version(version["id"], eng))
    return deliverable, version


def submit_and_approve_edit(episode_id, show_id, engineer_id, approve_at=None):
    """submit-edit (ProducerEng) then approve-edit (ShowOwner). Optionally set
    the clock before approval to control delivered_late. Returns the episode."""
    eng = make_producer_eng_headers(engineer_id)
    owner = make_show_owner_headers(show_id)
    get_success_data(api_client.submit_edit(episode_id, eng))
    if approve_at is not None:
        set_clock(approve_at)
    return get_success_data(api_client.approve_edit(episode_id, owner))


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts (Episode -> PUBLISHED)
# ---------------------------------------------------------------------------
def drive_episode_to_scheduled(show, contract, engineer, *,
                               planned_track_count=1, raw_track_count=1,
                               transcript_requested=False,
                               loudness=-16.0,
                               record_start="2026-03-02T08:00:00Z",
                               record_end="2026-03-02T09:00:00Z",
                               complete_at=None, lock_at=None, approve_at=None,
                               title="Ep"):
    """Create an episode and walk it from INTAKE to SCHEDULED.

    Pipeline: create episode -> record session to completion (-> EDITING) ->
    lock assets -> accept MASTER_AUDIO (and TRANSCRIPT if requested) ->
    submit-edit -> approve-edit (-> MASTERED) -> schedule. Returns the episode.
    """
    eng = make_producer_eng_headers(engineer["id"])
    episode = create_episode(show["id"], contract["id"],
                             planned_track_count=planned_track_count,
                             transcript_requested=transcript_requested, title=title)
    record_session_to_completion(episode["id"], engineer["id"], record_start, record_end,
                                 complete_at=complete_at)
    lock_assets(episode["id"], engineer["id"], raw_track_count, lock_at=lock_at)
    add_accepted_master_audio(episode["id"], engineer["id"], integrated_loudness_lufs=loudness)
    if transcript_requested:
        add_accepted_transcript(episode["id"], engineer["id"])
    submit_and_approve_edit(episode["id"], show["id"], engineer["id"], approve_at=approve_at)
    scheduled = get_success_data(api_client.schedule_episode(episode["id"], eng))
    return scheduled


def drive_episode_to_published(show, contract, engineer, **kwargs):
    """drive_episode_to_scheduled then publish. Returns the published episode."""
    eng = make_producer_eng_headers(engineer["id"])
    scheduled = drive_episode_to_scheduled(show, contract, engineer, **kwargs)
    return get_success_data(api_client.publish_episode(scheduled["id"], eng))


def publish_one_episode(billing_model="PER_EPISODE", tier="STANDARD",
                        loyalty_discount_pct=None, **drive_kwargs):
    """One-shot: show + active PER_EPISODE/RETAINER contract + engineer +
    one PUBLISHED episode. Returns (show, contract, engineer, episode)."""
    set_clock("2026-03-02T00:00:00Z")
    show, contract = create_show_with_active_contract(
        tier=tier, engagement_type="PER_EPISODE", billing_model=billing_model,
        loyalty_discount_pct=loyalty_discount_pct)
    engineer = create_engineer(name="Eng Pub")
    episode = drive_episode_to_published(show, contract, engineer, **drive_kwargs)
    return show, contract, engineer, episode


def get_episode_invoice(episode_id):
    """Return the single invoice for an episode (first match), or None."""
    data = get_success_data(api_client.list_invoices(ADMIN, params={"episode_id": episode_id}))
    return data[0] if data else None


# ---------------------------------------------------------------------------
# Retainer-cycle setup
# ---------------------------------------------------------------------------
def setup_retainer_cycle(monthly_included_episodes=2, tier="STANDARD",
                         cycle_start="2026-03-01T00:00:00Z",
                         cycle_end="2026-04-01T00:00:00Z"):
    """Show (RETAINER) + active RETAINER contract + one OPEN cycle + engineer.
    Returns (show, contract, cycle, engineer)."""
    show, contract = create_show_with_active_contract(
        tier=tier, engagement_type="RETAINER", billing_model="RETAINER",
        monthly_included_episodes=monthly_included_episodes)
    cycle = get_success_data(api_client.create_retainer_cycle(
        create_retainer_cycle_payload(contract["id"], cycle_start, cycle_end), ADMIN))
    engineer = create_engineer(name="Eng Ret")
    return show, contract, cycle, engineer


def publish_episode_in_show(show, contract, engineer, record_start, record_end,
                            planned_track_count=1, raw_track_count=1, title="Ep"):
    """Publish one more episode within an already-built show/contract.
    Returns the published episode."""
    return drive_episode_to_published(
        show, contract, engineer,
        planned_track_count=planned_track_count, raw_track_count=raw_track_count,
        record_start=record_start, record_end=record_end, title=title)


# ---------------------------------------------------------------------------
# Episode in REVIEW (for revision-loop / approval-error tests)
# ---------------------------------------------------------------------------
def setup_episode_in_review(*, with_master_audio=True, transcript_requested=False,
                            loudness=-16.0, planned_track_count=1, raw_track_count=1,
                            target_loudness_lufs=None):
    """Show + active contract + engineer + episode driven to REVIEW.

    Pipeline: episode -> record to completion (EDITING) -> lock assets ->
    (optionally accept MASTER_AUDIO) -> submit-edit (-> REVIEW).
    Returns (show, contract, engineer, episode).
    """
    set_clock("2026-03-02T00:00:00Z")
    show, contract = create_show_with_active_contract(
        target_loudness_lufs=target_loudness_lufs)
    engineer = create_engineer(name="Eng Rev")
    eng = make_producer_eng_headers(engineer["id"])
    episode = create_episode(show["id"], contract["id"],
                             planned_track_count=planned_track_count,
                             transcript_requested=transcript_requested, title="Ep Rev")
    record_session_to_completion(episode["id"], engineer["id"],
                                 "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z")
    lock_assets(episode["id"], engineer["id"], raw_track_count)
    if with_master_audio:
        add_accepted_master_audio(episode["id"], engineer["id"], integrated_loudness_lufs=loudness)
    get_success_data(api_client.submit_edit(episode["id"], eng))
    return show, contract, engineer, episode


def setup_episode_in_editing(*, target_loudness_lufs=None, planned_track_count=1):
    """Show + active contract + engineer + episode in EDITING (recording
    completed, assets NOT locked). Returns (show, contract, engineer, episode)."""
    set_clock("2026-03-02T00:00:00Z")
    show, contract = create_show_with_active_contract(target_loudness_lufs=target_loudness_lufs)
    engineer = create_engineer(name="Eng Edit")
    episode = create_episode(show["id"], contract["id"],
                             planned_track_count=planned_track_count, title="Ep Edit")
    record_session_to_completion(episode["id"], engineer["id"],
                                 "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z")
    return show, contract, engineer, episode


# ---------------------------------------------------------------------------
# Published episode with invoice in a chosen state
# ---------------------------------------------------------------------------
def setup_published_with_disputed_invoice():
    """Show + active contract + one PUBLISHED episode whose invoice is DISPUTED.
    Returns (show, contract, engineer, episode, invoice)."""
    show, contract, engineer, episode = publish_one_episode()
    owner = make_show_owner_headers(show["id"])
    invoice = get_episode_invoice(episode["id"])
    get_success_data(api_client.dispute_invoice(invoice["id"], owner))
    return show, contract, engineer, episode, invoice


# ---------------------------------------------------------------------------
# AdCampaign setup
# ---------------------------------------------------------------------------
def setup_approved_campaign_with_slots(slots, platform_fee_pct=0.30, all_published=True,
                                       sponsor="Sponsor"):
    """Show + active contract + engineer + published episode(s) + an APPROVED
    AdCampaign with the given slots.

    `slots` is a list of dicts: {"gross_cents": int, "placement": str,
    "published": bool (default True)}. One episode is created per slot.

    Returns (show, contract, engineer, campaign, episodes) where episodes is the
    list aligned with slots.
    """
    set_clock("2026-03-02T00:00:00Z")
    show, contract = create_show_with_active_contract()
    engineer = create_engineer(name="Eng Camp")
    eng = make_producer_eng_headers(engineer["id"])

    episodes = []
    base_day = 2
    for i, spec in enumerate(slots):
        published = spec.get("published", True)
        start = f"2026-03-{base_day + i:02d}T08:00:00Z"
        end = f"2026-03-{base_day + i:02d}T09:00:00Z"
        scheduled = drive_episode_to_scheduled(
            show, contract, engineer, record_start=start, record_end=end,
            title=f"Camp Ep {i}")
        if published:
            scheduled = get_success_data(api_client.publish_episode(scheduled["id"], eng))
        episodes.append(scheduled)

    campaign = get_success_data(api_client.create_ad_campaign(
        create_ad_campaign_payload(show["id"], sponsor_name=sponsor,
                                   platform_fee_pct=platform_fee_pct), ADOPS))
    for i, spec in enumerate(slots):
        get_success_data(api_client.create_ad_slot(
            create_ad_slot_payload(campaign["id"], episodes[i]["id"],
                                   spec["gross_cents"],
                                   placement=spec.get("placement", "MID_ROLL")), ADOPS))
    approved = get_success_data(api_client.approve_ad_campaign(campaign["id"], ADOPS))
    return show, contract, engineer, approved, episodes
