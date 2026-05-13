"""Playback batch ingest: HMAC, range, dedup, classification (PRD §2.8,
§3.6, §2.10 priorities 12, 21, 22)."""
from __future__ import annotations
from datetime import timedelta

import pytest

from test_helpers import (
    DEFAULT_PLAYBACK_SECRET,
    ApiErrorId,
    PSRC,
    assert_playback_batch,
    compute_hmac_signature,
    create_playback_batch_payload,
    invalid_hmac_signature,
    iso,
    make_playback_event,
    now_utc,
    setup_approved_recording_work,
    unique_source_identifier,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSignature:

    def test_invalid_signature_records_invalid_signature(self, api):
        """PRD §2.8 / §3.6 / §2.10 priority 12: 'A mismatch yields
        ERR_PLAYBACK_SIGNATURE_INVALID (HTTP 403); the batch is recorded
        with validity_status set to INVALID_SIGNATURE and
        total_events_accepted of 0.'

        Claim: ingest with a known-bad source_signature →
        ERR_PLAYBACK_SIGNATURE_INVALID (403).
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(hours=25))
        payload = create_playback_batch_payload(
            events=[],
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
            source_signature=invalid_hmac_signature(),
        )
        resp = api.create_playback_batch(payload, PSRC)
        validate_error(resp, ApiErrorId.ERR_PLAYBACK_SIGNATURE_INVALID.value,
                       403)


class TestRangeValidation:

    def test_end_before_start_rejected(self, api):
        """PRD §3.6 / §2.10 priority 21: 'the reporting window must
        satisfy reporting_period_end strictly greater than
        reporting_period_start, reporting_period_end at or before the
        current server time, and a duration of at most 31 days;
        otherwise ERR_PLAYBACK_RANGE_INVALID (422).'

        Claim: reporting_period_end <= reporting_period_start →
        ERR_PLAYBACK_RANGE_INVALID (422).
        """
        now = now_utc()
        period_start = iso(now - timedelta(hours=1))
        period_end = iso(now - timedelta(hours=10))  # before start
        payload = create_playback_batch_payload(
            events=[],
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        resp = api.create_playback_batch(payload, PSRC)
        validate_error(resp, ApiErrorId.ERR_PLAYBACK_RANGE_INVALID.value, 422)

    def test_window_in_future_rejected(self, api):
        """PRD §2.10 priority 21: 'reporting_period_end at or before
        the current server time ... otherwise
        ERR_PLAYBACK_RANGE_INVALID (422).'

        Claim: reporting_period_end strictly in the future →
        ERR_PLAYBACK_RANGE_INVALID (422).
        """
        now = now_utc()
        period_start = iso(now + timedelta(hours=1))
        period_end = iso(now + timedelta(hours=2))  # both future
        payload = create_playback_batch_payload(
            events=[],
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        resp = api.create_playback_batch(payload, PSRC)
        validate_error(resp, ApiErrorId.ERR_PLAYBACK_RANGE_INVALID.value, 422)

    def test_window_longer_than_31_days_rejected(self, api):
        """PRD §2.10 priority 21: 'a duration of at most 31 days;
        otherwise ERR_PLAYBACK_RANGE_INVALID (422).'

        Claim: a 60-day window → ERR_PLAYBACK_RANGE_INVALID (422).
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=60))
        payload = create_playback_batch_payload(
            events=[],
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        resp = api.create_playback_batch(payload, PSRC)
        validate_error(resp, ApiErrorId.ERR_PLAYBACK_RANGE_INVALID.value, 422)


class TestDedup:

    def test_duplicate_window_rejected(self, api):
        """PRD §3.6 / §2.10 priority 22: 'On playback ingest, a batch
        from the same source_identifier covering exactly the same
        [reporting_period_start, reporting_period_end) window that
        already exists in the system with validity_status of VALID
        yields ERR_DUPLICATE_BATCH (409).'

        Claim: second ingest with identical (source_identifier, window)
        → ERR_DUPLICATE_BATCH (409).
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        src = unique_source_identifier()
        first = create_playback_batch_payload(
            events=[],
            source_identifier=src,
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        validate_success(api.create_playback_batch(first, PSRC), 201)
        # Repeat with identical window — must reject.
        second = create_playback_batch_payload(
            events=[],
            source_identifier=src,
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        resp = api.create_playback_batch(second, PSRC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BATCH.value, 409)


class TestValidIngest:

    def test_valid_ingest_returns_201_and_valid_status(self, api):
        """PRD §3.6: 'Only when signature, range, and uniqueness all
        pass does the batch transition PENDING → VALID.'

        Claim: a well-formed playback batch on an APPROVED work returns
        201 with validity_status==VALID.
        """
        _h, work, _share = setup_approved_recording_work()
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        events = [make_playback_event(
            work_id=work["id"], play_duration_seconds=300,
            played_at=iso(now - timedelta(hours=24)), region="US",
        )]
        payload = create_playback_batch_payload(
            events=events,
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        resp = api.create_playback_batch(payload, PSRC)
        data = validate_success(resp, 201)
        assert_playback_batch(data)
        assert data["validity_status"] == "VALID"


class TestEventClassification:

    def test_supplemented_event_when_work_id_resolves_via_isrc(self, api):
        """PRD §3.6: 'An event whose work_id is null but whose isrc or
        iswc uniquely resolves an APPROVED work has its work_id filled
        in and is marked SUPPLEMENTED.'

        Claim: ingest event without work_id but with the approved
        work's isrc → event status SUPPLEMENTED.
        """
        _h, work, _share = setup_approved_recording_work()
        isrc = work["isrc"]
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        events = [{
            "isrc": isrc,
            "play_duration_seconds": 300,
            "played_at": iso(now - timedelta(hours=24)),
            "region": "US",
        }]
        payload = create_playback_batch_payload(
            events=events,
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        batch = validate_success(api.create_playback_batch(payload, PSRC), 201)
        resp = api.list_playback_events(
            batch["id"],
            {"X-User-ID": "platform-admin-001", "X-User-Role": "PlatformAdmin"},
            params={"limit": 10},
        )
        evs, _ = validate_paginated(resp)
        assert len(evs) == 1
        assert evs[0]["status"] == "SUPPLEMENTED"

    def test_event_with_unresolvable_work_marked_rejected(self, api):
        """PRD §3.6: 'An event whose work_id cannot be resolved at all
        is marked REJECTED.'

        Claim: event with no work_id and no isrc/iswc that resolves an
        approved work → event status REJECTED.
        """
        now = now_utc()
        period_end = iso(now - timedelta(hours=1))
        period_start = iso(now - timedelta(days=5))
        events = [{
            "isrc": "ZZZZZZZZZZZZ",  # 12-char string that maps to no work
            "play_duration_seconds": 30,
            "played_at": iso(now - timedelta(hours=24)),
            "region": "US",
        }]
        payload = create_playback_batch_payload(
            events=events,
            source_identifier=unique_source_identifier(),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
        )
        batch = validate_success(api.create_playback_batch(payload, PSRC), 201)
        resp = api.list_playback_events(
            batch["id"],
            {"X-User-ID": "platform-admin-001", "X-User-Role": "PlatformAdmin"},
            params={"limit": 10},
        )
        evs, _ = validate_paginated(resp)
        assert len(evs) == 1
        assert evs[0]["status"] == "REJECTED"
