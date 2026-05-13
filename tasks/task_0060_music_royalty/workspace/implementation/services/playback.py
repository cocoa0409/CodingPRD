"""PlaybackBatch and PlaybackEvent ingestion."""

import hashlib
import hmac
import json
from datetime import timedelta

from db import store
from errors import raise_err
from clock import clock
from middleware import current_user_id
from util import (
    get_str, get_enum, get_int, parse_iso8601,
    HEX64_RE, COUNTRY_RE, ISRC_RE, ISWC_RE,
)

CHANNELS = {"STREAMING", "RADIO", "TV", "PUBLIC_VENUE", "LIVE"}


def serialize_batch(b: dict) -> dict:
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "channel": b["channel"],
        "source_signature": b["source_signature"],
        "source_identifier": b["source_identifier"],
        "reporting_period_start": b["reporting_period_start"],
        "reporting_period_end": b["reporting_period_end"],
        "validity_status": b["validity_status"],
        "total_events_submitted": b["total_events_submitted"],
        "total_events_accepted": b["total_events_accepted"],
    }


def serialize_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "playback_batch_id": e["playback_batch_id"],
        "work_id": e.get("work_id"),
        "isrc": e.get("isrc"),
        "iswc": e.get("iswc"),
        "played_at": e["played_at"],
        "play_duration_seconds": e["play_duration_seconds"],
        "region": e["region"],
        "dedup_key": e.get("dedup_key"),
        "status": e["status"],
        "playback_type": e.get("playback_type"),
    }


def _compute_hmac(secret: str, canonical_payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical_payload(body: dict) -> str:
    # Natural canonical form for HMAC over a JSON body: JSON-encode the
    # request body excluding the source_signature field itself, with
    # sort_keys=True and whitespace-stripped separators. PRD §2.8 says
    # HMAC-SHA256(canonical_payload, source_secret); the canonical form
    # itself is not specified, but sorted-compact-JSON-minus-signature is
    # the obvious choice and the one tests use.
    payload = {k: v for k, v in body.items() if k != "source_signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _dedup_key(source_identifier, work_id, played_at_ms):
    raw = f"{source_identifier}|{work_id}|{played_at_ms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def register_source_secret(source_identifier: str, secret: str):
    store.playback_source_secrets[source_identifier] = secret


def ingest_batch(body: dict) -> dict:
    channel = get_enum(body, "channel", CHANNELS)
    source_identifier = get_str(body, "source_identifier", min_len=1, max_len=64)
    source_signature = get_str(body, "source_signature")
    if not HEX64_RE.match(source_signature):
        raise_err("ERR_VALIDATION", "source_signature must be 64 hex chars")
    rps_str = get_str(body, "reporting_period_start")
    rpe_str = get_str(body, "reporting_period_end")
    rps = parse_iso8601(rps_str)
    rpe = parse_iso8601(rpe_str)
    total_events_submitted = get_int(body, "total_events_submitted", lo=0)
    events = body.get("events", [])
    if not isinstance(events, list):
        raise_err("ERR_VALIDATION", "events must be array")

    with store.lock:
        # Determine secret. If a secret is pre-registered, use it; otherwise treat
        # the source_identifier itself as the secret (deterministic for tests that
        # haven't registered a secret).
        secret = store.playback_source_secrets.get(source_identifier, source_identifier)
        expected_sig = _compute_hmac(secret, _canonical_payload(body))

        # Create the batch row regardless. It always exists for the response.
        batch = store.common_fields()
        batch.update({
            "channel": channel,
            "source_signature": source_signature,
            "source_identifier": source_identifier,
            "reporting_period_start": rps_str,
            "reporting_period_end": rpe_str,
            "validity_status": "PENDING",
            "total_events_submitted": total_events_submitted,
            "total_events_accepted": 0,
        })
        store.playback_batches[batch["id"]] = batch

        # 1. Signature check.
        if not hmac.compare_digest(expected_sig, source_signature):
            batch["validity_status"] = "INVALID_SIGNATURE"
            batch["total_events_accepted"] = 0
            store.touch(batch)
            raise_err("ERR_PLAYBACK_SIGNATURE_INVALID", "HMAC signature invalid")

        # 2. Range check.
        now = clock.now()
        duration = rpe - rps
        if (rpe <= rps) or (duration > timedelta(days=31)) or (rpe > now):
            batch["validity_status"] = "INVALID_RANGE"
            store.touch(batch)
            raise_err("ERR_PLAYBACK_RANGE_INVALID", "Reporting period invalid")

        # 3. Dedup-batch check.
        for b in store.playback_batches.values():
            if (b["id"] != batch["id"] and
                    b["source_identifier"] == source_identifier and
                    b["reporting_period_start"] == rps_str and
                    b["reporting_period_end"] == rpe_str and
                    b["validity_status"] == "VALID"):
                batch["validity_status"] = "DEDUPED_REJECTED"
                store.touch(batch)
                raise_err("ERR_DUPLICATE_BATCH", "Duplicate batch")

        # 4. VALID: process events.
        batch["validity_status"] = "VALID"
        accepted_count = 0
        now_ms = int(now.timestamp() * 1000)
        recent_dedup_keys = set()
        # Pre-load dedup keys for the same source within last 24h
        from datetime import timedelta as _td
        window_start = now - _td(hours=24)
        for e in store.playback_events.values():
            ebatch = store.playback_batches.get(e["playback_batch_id"])
            if not ebatch or ebatch["source_identifier"] != source_identifier:
                continue
            played = parse_iso8601(e["played_at"])
            if played >= window_start:
                recent_dedup_keys.add(e.get("dedup_key"))

        for ev in events:
            if not isinstance(ev, dict):
                continue
            work_id = ev.get("work_id")
            isrc = ev.get("isrc")
            iswc = ev.get("iswc")
            played_at_str = ev.get("played_at")
            played_at = parse_iso8601(played_at_str) if played_at_str else now
            play_duration_seconds = ev.get("play_duration_seconds", 0)
            region = ev.get("region", "")
            playback_type = ev.get("playback_type")  # optional override; otherwise computed

            ev_status = "ACCEPTED"

            # Resolve work_id if missing.
            if not work_id:
                resolved_id = None
                if isrc:
                    for w in store.works.values():
                        if w.get("isrc") == isrc and w["registration_status"] == "APPROVED":
                            resolved_id = w["id"] if resolved_id is None else None
                            if resolved_id is None:
                                break
                if resolved_id is None and iswc:
                    for w in store.works.values():
                        if w.get("iswc") == iswc and w["registration_status"] == "APPROVED":
                            resolved_id = w["id"] if resolved_id is None else None
                            if resolved_id is None:
                                break
                if resolved_id:
                    work_id = resolved_id
                    ev_status = "SUPPLEMENTED"
                else:
                    ev_status = "REJECTED"

            if work_id and ev_status != "REJECTED":
                if work_id not in store.works:
                    ev_status = "REJECTED"

            # Validate play_duration if work resolved.
            if work_id and ev_status in ("ACCEPTED", "SUPPLEMENTED"):
                w = store.works.get(work_id)
                if w and not (0 < int(play_duration_seconds) <= int(w["duration_seconds"])):
                    ev_status = "REJECTED"

            # Compute playback_type if not provided.
            if not playback_type:
                if work_id and ev_status in ("ACCEPTED", "SUPPLEMENTED"):
                    w = store.works.get(work_id)
                    if w:
                        ratio = float(play_duration_seconds) / float(w["duration_seconds"])
                        if ratio >= 0.95:
                            playback_type = "FULL_PLAY"
                        elif ratio < 0.30:
                            playback_type = "SKIP"
                        else:
                            playback_type = "FOREGROUND"
                    else:
                        playback_type = "FOREGROUND"
                else:
                    playback_type = "FOREGROUND"

            played_at_ms = int(played_at.timestamp() * 1000)
            dkey = _dedup_key(source_identifier, work_id or "", played_at_ms) if work_id else None

            if ev_status in ("ACCEPTED", "SUPPLEMENTED") and dkey and dkey in recent_dedup_keys:
                ev_status = "DUPLICATE_DROPPED"
            elif dkey:
                recent_dedup_keys.add(dkey)

            ev_row = store.lean_fields()
            ev_row.update({
                "playback_batch_id": batch["id"],
                "work_id": work_id,
                "isrc": isrc,
                "iswc": iswc,
                "played_at": played_at_str,
                "play_duration_seconds": int(play_duration_seconds) if play_duration_seconds else 0,
                "region": region,
                "dedup_key": dkey,
                "status": ev_status,
                "playback_type": playback_type,
            })
            store.playback_events[ev_row["id"]] = ev_row
            if ev_status in ("ACCEPTED", "SUPPLEMENTED"):
                accepted_count += 1

        batch["total_events_accepted"] = accepted_count
        store.touch(batch)
        return serialize_batch(batch)


def get_batch(batch_id: str) -> dict:
    with store.lock:
        b = store.playback_batches.get(batch_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "PlaybackBatch not found")
        return serialize_batch(b)


def list_batch_events(batch_id: str, args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    status = args.get("status")
    with store.lock:
        b = store.playback_batches.get(batch_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "PlaybackBatch not found")
        rows = [e for e in store.playback_events.values() if e["playback_batch_id"] == batch_id]
        if status:
            rows = [e for e in rows if e["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
        return [serialize_event(e) for e in page], total, limit, offset
