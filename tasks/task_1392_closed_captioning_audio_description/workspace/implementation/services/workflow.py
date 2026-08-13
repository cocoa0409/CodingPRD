"""Cross-entity workflows: coverage bubble-up, delivery cascade, complaint
cascades, archive helpers, offer cascade, and the ops sweep."""
from datetime import timedelta

from db import DB, now, stamp_new, touch
from serialize import order_active_complaint_count
from services import livelog
from util import ceil_div

# Retention days per class (archive_purge_eligibility).
RETENTION_DAYS = {
    "REGULATED_BROADCAST": 2555,
    "STANDARD": 1095,
    "LIVE_ONLY": 90,
}

ESCALATION_THRESHOLD_HOURS = {
    "FCC_CRITICAL": 24,
    "MAJOR": 48,
    "MINOR": 72,
}

# Track states superseded when a new caption version is created.
SUPERSEDABLE_STATES = {"AUTHORING", "INTERNAL_REVIEW", "QC_QUEUED", "QC_PASSED", "QC_FAILED"}


# --- Work order coverage bubble-up (PRD §3.2) -------------------------------

def recompute_bubble(order):
    """IN_PRODUCTION -> READY_FOR_DELIVERY when required coverage is complete:
    CAPTIONS needs a current CONFORMED caption track, AUDIO_DESCRIPTION needs a
    CONFORMED AD track, BUNDLE needs both."""
    if order["order_status"] != "IN_PRODUCTION":
        return
    caption_ok = False
    if order["service_type"] in ("CAPTIONS", "BUNDLE"):
        for t in DB.caption_tracks.values():
            if t["work_order_id"] != order["id"]:
                continue
            if t["track_status"] in ("SUPERSEDED", "ARCHIVED", "QC_FAILED_PERMANENT"):
                continue
            if t["track_status"] == "CONFORMED":
                caption_ok = True
                break
    ad_ok = False
    if order["service_type"] in ("AUDIO_DESCRIPTION", "BUNDLE"):
        for t in DB.ad_tracks.values():
            if t["work_order_id"] == order["id"] and t["ad_status"] == "CONFORMED":
                ad_ok = True
                break
    complete = {
        "CAPTIONS": caption_ok,
        "AUDIO_DESCRIPTION": ad_ok,
        "BUNDLE": caption_ok and ad_ok,
    }[order["service_type"]]
    if complete:
        order["order_status"] = "READY_FOR_DELIVERY"
        touch(order)


# --- Archive helpers (PRD §3.9) ----------------------------------------------

def retention_class_for_client(client):
    return "REGULATED_BROADCAST" if client["compliance_standard"] == "FCC_BROADCAST" else "STANDARD"


def create_archive_item(caption_track_id=None, ad_track_id=None, live_event_id=None, client=None):
    if live_event_id is not None:
        retention_class = "LIVE_ONLY"
    else:
        retention_class = retention_class_for_client(client)
    rec = {
        "caption_track_id": caption_track_id,
        "audio_description_track_id": ad_track_id,
        "live_event_id": live_event_id,
        "retention_class": retention_class,
        "archive_status": "ACTIVE_HOLD",
        "archived_at": None,
        "purge_after": None,
        "legal_hold": False,
        "dispute_freeze": False,
    }
    stamp_new(rec)
    DB.archive_items[rec["id"]] = rec
    return rec


def _archive_items_for_subject(caption_track_id=None, ad_track_id=None, live_event_id=None):
    out = []
    for item in DB.archive_items.values():
        if caption_track_id and item["caption_track_id"] == caption_track_id:
            out.append(item)
        elif ad_track_id and item["audio_description_track_id"] == ad_track_id:
            out.append(item)
        elif live_event_id and item["live_event_id"] == live_event_id:
            out.append(item)
    return out


def set_dispute_freeze(value, caption_track_id=None, ad_track_id=None, live_event_id=None):
    for item in _archive_items_for_subject(caption_track_id, ad_track_id, live_event_id):
        if item["dispute_freeze"] != value:
            item["dispute_freeze"] = value
            touch(item)


def has_open_complaint(caption_track_id=None, ad_track_id=None, live_event_id=None):
    for c in DB.complaints.values():
        if c["complaint_status"] not in ("OPEN", "TRIAGED", "REMEDIATING", "REOPENED"):
            continue
        if caption_track_id and c["caption_track_id"] == caption_track_id:
            return True
        if ad_track_id and c["audio_description_track_id"] == ad_track_id:
            return True
        if live_event_id and c["live_event_id"] == live_event_id:
            return True
    return False


# --- Delivery cascade (PRD §3.2) ----------------------------------------------

def deliver_order(order):
    """READY_FOR_DELIVERY -> DELIVERED with the full fan-out of effects."""
    t = now()
    media = DB.media_assets[order["media_asset_id"]]
    client = DB.clients[order["client_id"]]
    order["order_status"] = "DELIVERED"
    order["delivered_at"] = t
    order["sla_breached"] = t > order["due_at"]
    touch(order)
    for track in DB.caption_tracks.values():
        if track["work_order_id"] == order["id"] and track["track_status"] == "CONFORMED":
            track["track_status"] = "DELIVERED"
            touch(track)
            create_archive_item(caption_track_id=track["id"], client=client)
    for track in DB.ad_tracks.values():
        if track["work_order_id"] == order["id"] and track["ad_status"] == "CONFORMED":
            track["ad_status"] = "DELIVERED"
            touch(track)
            create_archive_item(ad_track_id=track["id"], client=client)
    client["ytd_completed_minutes"] += ceil_div(media["duration_seconds"], 60)
    touch(client)


# --- Complaint cascades (PRD §3.8) --------------------------------------------

def cancel_queued_conversion_jobs_for_order(order_id):
    """Entering remediation freezes in-flight conversion work: QUEUED jobs
    referencing any track of this order -> CANCELLED."""
    for job in DB.conversion_jobs.values():
        if job["job_status"] != "QUEUED":
            continue
        src = DB.caption_tracks.get(job["source_track_id"])
        if src is not None and src["work_order_id"] == order_id:
            job["job_status"] = "CANCELLED"
            touch(job)


def dispute_cascade(complaint):
    """On complaint create/reopen against a track: the subject moves DELIVERED
    -> DISPUTED, its archive item freezes, the order goes DELIVERED ->
    REMEDIATION, and QUEUED conversion jobs of the order are cancelled."""
    ct_id = complaint["caption_track_id"]
    ad_id = complaint["audio_description_track_id"]
    if ct_id:
        track = DB.caption_tracks[ct_id]
        if track["track_status"] == "DELIVERED":
            track["track_status"] = "DISPUTED"
            touch(track)
        set_dispute_freeze(True, caption_track_id=ct_id)
        order = DB.work_orders[track["work_order_id"]]
    elif ad_id:
        track = DB.ad_tracks[ad_id]
        if track["ad_status"] == "DELIVERED":
            track["ad_status"] = "DISPUTED"
            touch(track)
        set_dispute_freeze(True, ad_track_id=ad_id)
        order = DB.work_orders[track["work_order_id"]]
    else:
        return  # live-event subjects: no work order, no track cascade
    if order["order_status"] == "DELIVERED":
        order["order_status"] = "REMEDIATION"
        touch(order)
    cancel_queued_conversion_jobs_for_order(order["id"])


def current_artifact(complaint):
    """The remediation track when remediation_track_id is set, otherwise the
    original subject track. Returns (kind, record) or (None, None) for live
    events."""
    if complaint["caption_track_id"]:
        if complaint["remediation_track_id"]:
            return "caption", DB.caption_tracks[complaint["remediation_track_id"]]
        return "caption", DB.caption_tracks[complaint["caption_track_id"]]
    if complaint["audio_description_track_id"]:
        return "ad", DB.ad_tracks[complaint["audio_description_track_id"]]
    return None, None


def dismiss_cascade(complaint):
    """Dismissal unwinds the dispute: the subject track returns DISPUTED ->
    DELIVERED, the archive freeze lifts, and the order returns REMEDIATION ->
    DELIVERED once no active complaints remain."""
    kind, track = current_artifact(complaint)
    if kind is None:
        return
    status_field = "track_status" if kind == "caption" else "ad_status"
    if track[status_field] == "DISPUTED":
        track[status_field] = "DELIVERED"
        touch(track)
    if kind == "caption":
        set_dispute_freeze(False, caption_track_id=track["id"])
    else:
        set_dispute_freeze(False, ad_track_id=track["id"])
    order = DB.work_orders[track["work_order_id"]]
    if order["order_status"] == "REMEDIATION" and order_active_complaint_count(order["id"]) == 0:
        order["order_status"] = "DELIVERED"
        touch(order)


def create_remediation_caption_track(complaint, acting_user_id):
    """begin-remediation on a caption subject: new version_no = disputed + 1,
    AUTHORING, supersedes the disputed track, author is the acting user."""
    disputed = DB.caption_tracks[complaint["caption_track_id"]]
    order = DB.work_orders[disputed["work_order_id"]]
    rec = {
        "work_order_id": order["id"],
        "supersedes_track_id": disputed["id"],
        "version_no": disputed["version_no"] + 1,
        "language": disputed["language"],
        "caption_format": disputed["caption_format"],
        "speaker_id_style": disputed["speaker_id_style"],
        "track_status": "AUTHORING",
        "author_user_id": acting_user_id,
        "qc_attempts": 0,
        "last_accuracy_pct": None,
    }
    stamp_new(rec)
    DB.caption_tracks[rec["id"]] = rec
    disputed["track_status"] = "SUPERSEDED"
    touch(disputed)
    # A new version for the same work order supersedes any in-flight version.
    for t in DB.caption_tracks.values():
        if t["work_order_id"] == order["id"] and t["id"] != rec["id"] and t["track_status"] in SUPERSEDABLE_STATES:
            t["track_status"] = "SUPERSEDED"
            touch(t)
    complaint["remediation_track_id"] = rec["id"]
    if order["order_status"] == "REMEDIATION":
        order["order_status"] = "IN_PRODUCTION"
        touch(order)
    return rec


def begin_remediation_ad(complaint):
    """AD remediation does not version: the disputed track reopens DISPUTED ->
    SCRIPTING, its studio booking is cleared, and the order resumes
    IN_PRODUCTION."""
    track = DB.ad_tracks[complaint["audio_description_track_id"]]
    order = DB.work_orders[track["work_order_id"]]
    track["ad_status"] = "SCRIPTING"
    track["studio_id"] = None
    track["record_start_at"] = None
    track["record_end_at"] = None
    touch(track)
    if order["order_status"] == "REMEDIATION":
        order["order_status"] = "IN_PRODUCTION"
        touch(order)
    return track


# --- Offer cascade (PRD §3.7) -------------------------------------------------

def create_offer(event, stenographer_id, origin):
    t = now()
    rec = {
        "live_event_id": event["id"],
        "stenographer_id": stenographer_id,
        "assignment_status": "OFFERED",
        "origin": origin,
        "offered_at": t,
        "offer_expires_at": min(t + timedelta(hours=4), event["start_at"]),
        "booked_minutes": livelog.booked_minutes(event),
        "preemption_reason": None,
    }
    stamp_new(rec)
    DB.assignments[rec["id"]] = rec
    # Each offer creation advances the event version.
    touch(event)
    return rec


def run_auto_offer_cascade(event):
    """Decline/preemption cascade: one AUTO_OFFER to the next-ranked eligible
    stenographer, or a silent no-op when the pool is empty."""
    winner = livelog.auto_offer_select(event)
    if winner is None:
        return None
    return create_offer(event, winner["id"], "AUTO_OFFER")


def confirmed_assignment_exists(event_id):
    return any(
        a["live_event_id"] == event_id and a["assignment_status"] == "CONFIRMED"
        for a in DB.assignments.values()
    )


def maybe_debrief_event(event):
    """BRIEFED -> SCHEDULED when no CONFIRMED assignments remain."""
    if event["event_status"] == "BRIEFED" and not confirmed_assignment_exists(event["id"]):
        event["event_status"] = "SCHEDULED"
        touch(event)


# --- Ops sweep (PRD §2.7) -------------------------------------------------------

def run_sweep():
    t = now()
    counts = {
        "expired_offer_count": 0,
        "expired_quote_count": 0,
        "sla_breach_count": 0,
        "escalated_complaint_count": 0,
        "lapsed_certification_count": 0,
        "archived_track_count": 0,
    }
    for a in DB.assignments.values():
        if a["assignment_status"] == "OFFERED" and t >= a["offer_expires_at"]:
            a["assignment_status"] = "OFFER_EXPIRED"
            touch(a)
            counts["expired_offer_count"] += 1
    for o in DB.work_orders.values():
        if o["order_status"] == "QUOTED" and o["quote_expires_at"] is not None and t >= o["quote_expires_at"]:
            o["order_status"] = "QUOTE_EXPIRED"
            touch(o)
            counts["expired_quote_count"] += 1
    for o in DB.work_orders.values():
        if (
            o["due_at"] is not None
            and not o["sla_breached"]
            and o["order_status"] in ("CONFIRMED", "IN_PRODUCTION", "READY_FOR_DELIVERY")
            and o["due_at"] < t
        ):
            o["sla_breached"] = True
            touch(o)
            counts["sla_breach_count"] += 1
    for c in DB.complaints.values():
        if c["complaint_status"] not in ("OPEN", "TRIAGED", "REMEDIATING", "REOPENED"):
            continue
        threshold = timedelta(hours=ESCALATION_THRESHOLD_HOURS[c["severity"]])
        if t - c["updated_at"] >= threshold:
            c["escalation_level"] += 1
            touch(c)  # escalation refreshes updated_at; the next escalation needs a full period
            counts["escalated_complaint_count"] += 1
    for s in DB.stenographers.values():
        if s["steno_status"] == "ACTIVE" and t > s["cert_valid_until"]:
            s["steno_status"] = "CERTIFICATION_LAPSED"
            touch(s)
            counts["lapsed_certification_count"] += 1
    archive_cutoff = t - timedelta(days=30)
    for order in DB.work_orders.values():
        if order["order_status"] != "CLIENT_ACCEPTED":
            continue
        if order["delivered_at"] is None or order["delivered_at"] > archive_cutoff:
            continue
        for track in DB.caption_tracks.values():
            if track["work_order_id"] == order["id"] and track["track_status"] == "DELIVERED":
                track["track_status"] = "ARCHIVED"
                touch(track)
                counts["archived_track_count"] += 1
        for track in DB.ad_tracks.values():
            if track["work_order_id"] == order["id"] and track["ad_status"] == "DELIVERED":
                track["ad_status"] = "ARCHIVED"
                touch(track)
                counts["archived_track_count"] += 1
    return counts
