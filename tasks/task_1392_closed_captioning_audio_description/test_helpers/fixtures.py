"""Composite setup helpers: multi-step PRD workflows distilled into fixtures.

Every helper builds its preconditions from scratch via the public endpoints and
returns plain dicts (validated with the lenient get_success_data so setup
failures surface as clear "Setup failed" errors).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_ad_track_payload,
    create_caption_track_payload,
    create_client_payload,
    create_complaint_payload,
    create_live_event_payload,
    create_media_asset_payload,
    create_qc_review_payload,
    create_stenographer_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_ad_producer_headers,
    make_client_headers,
    make_editor_headers,
    make_ops_headers,
    make_qc_headers,
    make_stenographer_headers,
)

OPS = TEST_USERS["operations_manager_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
EDITOR = TEST_USERS["caption_editor_headers"]
AD_PRODUCER = TEST_USERS["ad_producer_headers"]
QC = TEST_USERS["qc_specialist_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + leaf creators
# ---------------------------------------------------------------------------

def set_clock(iso: str):
    resp = api_client.set_clock(iso, OPS)
    get_success_data(resp)


def run_sweep() -> dict:
    resp = api_client.run_sweep(OPS)
    return get_success_data(resp)


def create_client(name="Acme", compliance_standard="INTERNAL", **overrides) -> dict:
    payload = create_client_payload(name=name, compliance_standard=compliance_standard, **overrides)
    resp = api_client.create_client(payload, OPS)
    return get_success_data(resp)


def create_media(client_id, title="Prog", duration_seconds=3600, frame_rate="FPS_30",
                 media_kind="FILE_BASED") -> dict:
    payload = create_media_asset_payload(
        client_id=client_id, title=title, duration_seconds=duration_seconds,
        frame_rate=frame_rate, media_kind=media_kind,
    )
    resp = api_client.create_media_asset(payload, INTAKE)
    return get_success_data(resp)


def create_cleared_media(client_id, title="Prog", duration_seconds=3600,
                         frame_rate="FPS_30", media_kind="FILE_BASED") -> dict:
    asset = create_media(client_id, title, duration_seconds, frame_rate, media_kind)
    get_success_data(api_client.begin_inspection(asset["id"], INTAKE))
    return get_success_data(api_client.clear_media(asset["id"], INTAKE))


def create_work_order(client_id, media_asset_id, service_type="CAPTIONS",
                      turnaround_tier="STANDARD", language="en-US") -> dict:
    payload = create_work_order_payload(
        client_id=client_id, media_asset_id=media_asset_id,
        service_type=service_type, turnaround_tier=turnaround_tier, language=language,
    )
    resp = api_client.create_work_order(payload, INTAKE)
    return get_success_data(resp)


def quote_order(work_order_id) -> dict:
    return get_success_data(api_client.quote_work_order(work_order_id, INTAKE))


def confirm_order(work_order_id, client_id) -> dict:
    return get_success_data(api_client.confirm_work_order(
        work_order_id, make_client_headers(client_id)))


def start_production(work_order_id) -> dict:
    return get_success_data(api_client.start_production(work_order_id, EDITOR))


def create_track(work_order_id, author="editor-1", caption_format="SRT",
                 speaker_id_style="DASH", language="en-US", supersedes_track_id=None) -> dict:
    wo = get_success_data(api_client.get_work_order(work_order_id, EDITOR))
    payload = create_caption_track_payload(
        language=language, caption_format=caption_format,
        speaker_id_style=speaker_id_style,
        expected_work_order_version=wo["version"],
    )
    if supersedes_track_id:
        payload["supersedes_track_id"] = supersedes_track_id
    resp = api_client.create_caption_track(work_order_id, payload, make_editor_headers(author))
    return get_success_data(resp)


def track_submit_and_enqueue(track_id, author="editor-1"):
    get_success_data(api_client.submit_review(track_id, make_editor_headers(author)))
    get_success_data(api_client.enqueue_qc(track_id, make_editor_headers(author)))


def finalize_qc(track_id, reviewer="qc-1", review_mode="FULL_REVIEW", total_words=10000,
                minor_errors=100, major_errors=0, critical_errors=0, sampled_words=None) -> dict:
    payload = create_qc_review_payload(
        review_mode=review_mode, total_words=total_words, minor_errors=minor_errors,
        major_errors=major_errors, critical_errors=critical_errors,
    )
    if sampled_words is not None:
        payload["sampled_words"] = sampled_words
    resp = api_client.create_qc_review(track_id, payload, make_qc_headers(reviewer))
    return get_success_data(resp)


def conform_track(track_id, author="editor-1") -> dict:
    return get_success_data(api_client.mark_conformed(track_id, make_editor_headers(author)))


def deliver_order(work_order_id) -> dict:
    return get_success_data(api_client.deliver_work_order(work_order_id, OPS))


# ---------------------------------------------------------------------------
# Tier 1: state progression — work order and caption track
# ---------------------------------------------------------------------------

def setup_in_production_order(compliance_standard="INTERNAL", turnaround_tier="STANDARD",
                              duration_seconds=3600, service_type="CAPTIONS",
                              frame_rate="FPS_30", language="en-US",
                              client_name="Acme", clear_media=True) -> dict:
    """Client + cleared media + order walked to IN_PRODUCTION. Returns context."""
    client = create_client(name=client_name, compliance_standard=compliance_standard)
    if clear_media:
        media = create_cleared_media(client["id"], duration_seconds=duration_seconds,
                                     frame_rate=frame_rate)
    else:
        media = create_media(client["id"], duration_seconds=duration_seconds,
                             frame_rate=frame_rate)
    wo = create_work_order(client["id"], media["id"], service_type=service_type,
                           turnaround_tier=turnaround_tier, language=language)
    quote_order(wo["id"])
    confirm_order(wo["id"], client["id"])
    wo = start_production(wo["id"])
    return {"client": client, "media": media, "work_order": wo}


def setup_track_in_qc_queue(compliance_standard="INTERNAL", author="editor-1",
                            caption_format="SRT", **order_overrides) -> dict:
    """IN_PRODUCTION order with one caption track driven AUTHORING -> QC_QUEUED."""
    ctx = setup_in_production_order(compliance_standard=compliance_standard, **order_overrides)
    track = create_track(ctx["work_order"]["id"], author=author, caption_format=caption_format)
    track_submit_and_enqueue(track["id"], author=author)
    track = get_success_data(api_client.get_caption_track(track["id"], EDITOR))
    ctx["track"] = track
    ctx["author"] = author
    return ctx


def setup_conformed_caption_track(compliance_standard="INTERNAL", author="editor-1",
                                  caption_format="SRT", qc_minor_errors=100,
                                  qc_total_words=10000, **order_overrides) -> dict:
    """Track driven all the way to CONFORMED (QC PASS by an independent reviewer)."""
    ctx = setup_track_in_qc_queue(compliance_standard=compliance_standard, author=author,
                                  caption_format=caption_format, **order_overrides)
    finalize_qc(ctx["track"]["id"], minor_errors=qc_minor_errors, total_words=qc_total_words)
    conform_track(ctx["track"]["id"], author=author)
    ctx["track"] = get_success_data(api_client.get_caption_track(ctx["track"]["id"], EDITOR))
    return ctx


def setup_delivered_captions_order(compliance_standard="INTERNAL", author="editor-1",
                                   caption_format="SRT", **order_overrides) -> dict:
    """Full caption pipeline through delivery. Order DELIVERED, track DELIVERED."""
    ctx = setup_conformed_caption_track(compliance_standard=compliance_standard,
                                        author=author, caption_format=caption_format,
                                        **order_overrides)
    ctx["work_order"] = deliver_order(ctx["work_order"]["id"])
    ctx["track"] = get_success_data(api_client.get_caption_track(ctx["track"]["id"], EDITOR))
    return ctx


def get_archive_item_for(**params) -> dict:
    """Return the single ArchiveItem matching the given filters."""
    data = get_success_data(api_client.list_archive_items(OPS, params=params))
    items = data if isinstance(data, list) else data.get("items", data)
    assert isinstance(items, list) and len(items) == 1, (
        f"Setup failed: expected exactly one archive item for {params}, got {items!r}"
    )
    return items[0]


# ---------------------------------------------------------------------------
# Tier 2: audio description pipeline
# ---------------------------------------------------------------------------

def create_ad_track(work_order_id, author="ad-1", gaps=None, segments=None,
                    narrator_name="Narrator One", language="en-US") -> dict:
    overrides = {}
    if gaps is not None:
        overrides["gaps"] = gaps
    if segments is not None:
        overrides["segments"] = segments
    payload = create_ad_track_payload(language=language, narrator_name=narrator_name, **overrides)
    resp = api_client.create_ad_track(work_order_id, payload, make_ad_producer_headers(author))
    return get_success_data(resp)


def setup_ad_track_in_recording(author="ad-1", approver="qc-1", gaps=None,
                                segments=None, **order_overrides) -> dict:
    """AD order IN_PRODUCTION with a track driven SCRIPTING -> RECORDING."""
    ctx = setup_in_production_order(service_type="AUDIO_DESCRIPTION", **order_overrides)
    ad = create_ad_track(ctx["work_order"]["id"], author=author, gaps=gaps, segments=segments)
    get_success_data(api_client.submit_script(ad["id"], make_ad_producer_headers(author)))
    ad = get_success_data(api_client.approve_script(ad["id"], make_qc_headers(approver)))
    ctx["ad_track"] = ad
    ctx["ad_author"] = author
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: live event pipeline
# ---------------------------------------------------------------------------

def create_stenographer(display_name="S1", certification="CERT_CBC",
                        certified_since="2020-01-01T00:00:00Z",
                        cert_valid_until="2027-01-01T00:00:00Z",
                        **overrides) -> dict:
    payload = create_stenographer_payload(
        display_name=display_name, certification=certification,
        certified_since=certified_since, cert_valid_until=cert_valid_until, **overrides)
    resp = api_client.create_stenographer(payload, SCHED)
    return get_success_data(resp)


def create_live_event(client_id, start_at="2026-08-10T14:00:00Z", end_at="2026-08-10T15:00:00Z",
                      required_certification="CERT_CBC", title="E", channel_id="CH1",
                      prep_minutes=None, wrap_minutes=None) -> dict:
    overrides = {}
    if prep_minutes is not None:
        overrides["prep_minutes"] = prep_minutes
    if wrap_minutes is not None:
        overrides["wrap_minutes"] = wrap_minutes
    payload = create_live_event_payload(
        client_id=client_id, title=title, channel_id=channel_id, start_at=start_at,
        end_at=end_at, required_certification=required_certification, **overrides)
    resp = api_client.create_live_event(payload, SCHED)
    return get_success_data(resp)


def create_offer(live_event_id, stenographer_id=None) -> dict:
    event = get_success_data(api_client.get_live_event(live_event_id, SCHED))
    payload = {"expected_live_event_version": event["version"]}
    if stenographer_id:
        payload["stenographer_id"] = stenographer_id
    resp = api_client.create_assignment(live_event_id, payload, SCHED)
    return get_success_data(resp)


def accept_offer(assignment_id, stenographer_id) -> dict:
    return get_success_data(api_client.accept_assignment(
        assignment_id, make_stenographer_headers(stenographer_id)))


def check_in(assignment_id, stenographer_id) -> dict:
    return get_success_data(api_client.check_in_assignment(
        assignment_id, make_stenographer_headers(stenographer_id)))


def setup_accepted_assignment(start_at="2026-08-10T14:00:00Z", end_at="2026-08-10T15:00:00Z",
                              certification="CERT_CBC", prep_minutes=None, wrap_minutes=None,
                              client_name="Live Co") -> dict:
    """Client + event + stenographer with an ACCEPTED assignment."""
    client = create_client(name=client_name, compliance_standard="FCC_BROADCAST")
    steno = create_stenographer(certification=certification)
    event = create_live_event(client["id"], start_at=start_at, end_at=end_at,
                              required_certification=certification,
                              prep_minutes=prep_minutes, wrap_minutes=wrap_minutes)
    asg = create_offer(event["id"], steno["id"])
    asg = accept_offer(asg["id"], steno["id"])
    return {"client": client, "stenographer": steno, "event": event, "assignment": asg}


def setup_confirmed_event(start_at="2026-08-10T14:00:00Z", end_at="2026-08-10T15:00:00Z",
                          checkin_at="2026-08-10T13:40:00Z", certification="CERT_CBC") -> dict:
    """Event with one CONFIRMED assignment (event BRIEFED)."""
    ctx = setup_accepted_assignment(start_at=start_at, end_at=end_at,
                                    certification=certification)
    set_clock(checkin_at)
    ctx["assignment"] = check_in(ctx["assignment"]["id"], ctx["stenographer"]["id"])
    ctx["event"] = get_success_data(api_client.get_live_event(ctx["event"]["id"], SCHED))
    return ctx


def setup_settled_event() -> dict:
    """Full live lifecycle through SETTLED; returns context incl. the ArchiveItem."""
    ctx = setup_confirmed_event()
    get_success_data(api_client.go_on_air(ctx["event"]["id"], SCHED))
    set_clock("2026-08-10T15:00:00Z")
    get_success_data(api_client.wrap_event(ctx["event"]["id"], SCHED))
    event = get_success_data(api_client.settle_event(ctx["event"]["id"], SCHED))
    ctx["event"] = event
    ctx["archive_item"] = get_archive_item_for(live_event_id=event["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: complaints / remediation
# ---------------------------------------------------------------------------

def file_complaint(client_id, severity="MINOR", description="caption error",
                   caption_track_id=None, audio_description_track_id=None,
                   live_event_id=None) -> dict:
    payload = create_complaint_payload(severity=severity, description=description)
    if caption_track_id:
        payload["caption_track_id"] = caption_track_id
    if audio_description_track_id:
        payload["audio_description_track_id"] = audio_description_track_id
    if live_event_id:
        payload["live_event_id"] = live_event_id
    resp = api_client.create_complaint(payload, make_client_headers(client_id))
    return get_success_data(resp)


def setup_open_complaint(compliance_standard="INTERNAL", severity="MINOR",
                         description="caption error",
                         author="editor-1", **order_overrides) -> dict:
    """DELIVERED captions order plus one OPEN complaint on its track."""
    ctx = setup_delivered_captions_order(compliance_standard=compliance_standard,
                                         author=author, **order_overrides)
    complaint = file_complaint(ctx["client"]["id"], severity=severity,
                               description=description,
                               caption_track_id=ctx["track"]["id"])
    ctx["complaint"] = complaint
    return ctx


def remediate_and_redeliver(ctx, resolver="ops-1") -> dict:
    """From an OPEN caption-track complaint: triage, begin remediation, and flow
    the remediation track through QC/conform/re-delivery (artifact DELIVERED).
    The caller controls the clock before resolving."""
    comp_id = ctx["complaint"]["id"]
    get_success_data(api_client.triage_complaint(comp_id, OPS))
    resp = api_client.begin_remediation(comp_id, make_ops_headers(resolver))
    comp = get_success_data(resp)
    remediation_track_id = comp["remediation_track_id"]
    track_submit_and_enqueue(remediation_track_id, author=resolver)
    finalize_qc(remediation_track_id, minor_errors=50)
    conform_track(remediation_track_id, author=resolver)
    deliver_order(ctx["work_order"]["id"])
    ctx["complaint"] = get_success_data(api_client.get_complaint(comp_id, OPS))
    ctx["remediation_track_id"] = remediation_track_id
    return ctx


def resolve_complaint(comp_id, resolver="ops-1", payload=None) -> dict:
    return get_success_data(
        api_client.resolve_complaint(comp_id, make_ops_headers(resolver), payload=payload))
