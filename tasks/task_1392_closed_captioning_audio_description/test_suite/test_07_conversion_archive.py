"""Format conversion and the archive: source-track finality gate, same-format
and embed rules, the ±250ms fidelity band, retry ceiling, retention-clock
pinning, purge gates, and the dispute freeze (PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_archive_item,
    assert_same_instant,
    create_track,
    file_complaint,
    get_success_data,
    make_client_headers,
    set_clock,
    setup_conformed_caption_track,
    setup_delivered_captions_order,
    setup_settled_event,
    setup_track_in_qc_queue,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import EDITOR, OPS

MONDAY = "2026-08-03T10:00:00Z"


class TestConversionSourceGate:
    """Difficulty pair ConversionJob x CaptionTrack: creation is gated on the
    source track's lifecycle."""

    def test_queued_track_source_rejected(self, api):
        """PRD §3.9: "The source track must be in `CONFORMED`, `DELIVERED`,
        `SUPERSEDED`, or `ARCHIVED` (else `ERR_SOURCE_TRACK_NOT_FINAL`,
        HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/conversion_requires_source_track_final
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="FCC_BROADCAST",
                                      caption_format="SCC",
                                      frame_rate="FPS_29_97_DF",
                                      client_name="FCC Client")
        resp = api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "WEBVTT"}, OPS)
        validate_error(resp, ApiErrorId.ERR_SOURCE_TRACK_NOT_FINAL)

    def test_conformed_source_accepted(self, api):
        """PRD §3.9: "The source track must be in `CONFORMED`, `DELIVERED`,
        `SUPERSEDED`, or `ARCHIVED` (else `ERR_SOURCE_TRACK_NOT_FINAL`,
        HTTP 409)".
        PRD §3.9: "A new job lands `QUEUED` with `attempt_count` zero".

        Design: Difficulty/cross_entity_state_dependency/conversion_requires_source_track_final
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="FCC_BROADCAST",
                                            caption_format="SCC",
                                            frame_rate="FPS_29_97_DF",
                                            client_name="FCC Client")
        job = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "WEBVTT"}, OPS),
            expected_status=201)
        assert job["job_status"] == "QUEUED"
        assert job["attempt_count"] == 0


class TestConversionValidation:
    def test_conversion_same_format_rejected(self, api):
        """PRD §3.9: "the `target_format` must differ from the source track's
        `caption_format` (else `ERR_CONVERSION_SAME_FORMAT`, HTTP 422)".

        Design: Corner/validations/conversion_same_format_rejected
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="INTERNAL",
                                            caption_format="SCC",
                                            frame_rate="FPS_29_97_DF")
        resp = api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "SCC"}, OPS)
        validate_error(resp, ApiErrorId.ERR_CONVERSION_SAME_FORMAT)
        jobs = get_success_data(api.list_conversion_jobs(
            OPS, params={"source_track_id": ctx["track"]["id"]}))
        assert isinstance(jobs, list) and len(jobs) == 0

    def test_conversion_embed_nonscc_rejected(self, api):
        """PRD §3.9: "`embed` is only supported when the target is `SCC` (else
        `ERR_EMBED_NOT_SUPPORTED`, HTTP 422)."

        Design: Corner/validations/conversion_embed_nonscc_rejected
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="INTERNAL",
                                            caption_format="WEBVTT",
                                            frame_rate="FPS_29_97_DF")
        resp = api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "TTML",
             "embed": True}, OPS)
        validate_error(resp, ApiErrorId.ERR_EMBED_NOT_SUPPORTED)
        job = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "SCC",
             "embed": True}, OPS), expected_status=201)
        assert job["job_status"] == "QUEUED"


class TestConversionRun:
    def test_duration_tolerance_boundary(self, api):
        """PRD §3.9: "The job's `last_delta_ms` is the signed difference between
        `output_duration_ms` and the source media's `duration_seconds` expressed
        in milliseconds. When the absolute value of that delta is at most 250
        milliseconds the pass ends `VALIDATING` → `COMPLETED`; when it exceeds
        250 milliseconds the pass ends `VALIDATING` → `FAILED_VALIDATION`,
        `attempt_count` increments by one, and both `output_duration_ms` and
        `last_delta_ms` are stored either way."

        Design: Corner/calculations/conversion_duration_tolerance_boundary
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="INTERNAL",
                                            caption_format="SCC",
                                            frame_rate="FPS_29_97_DF")
        cj_1 = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "WEBVTT"}, OPS),
            expected_status=201)
        cj_2 = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "TTML"}, OPS),
            expected_status=201)
        # Source is 3600s -> 3_600_000 ms.
        run1 = validate_success(api.run_conversion_job(
            cj_1["id"], {"output_duration_ms": 3600250}, OPS))
        assert run1["job_status"] == "COMPLETED"
        assert run1["last_delta_ms"] == 250
        run2 = validate_success(api.run_conversion_job(
            cj_2["id"], {"output_duration_ms": 3600251}, OPS))
        assert run2["job_status"] == "FAILED_VALIDATION"
        assert run2["attempt_count"] == 1
        get_success_data(api.retry_conversion_job(cj_2["id"], OPS))
        run2b = validate_success(api.run_conversion_job(
            cj_2["id"], {"output_duration_ms": 3600000}, OPS))
        assert run2b["job_status"] == "COMPLETED"
        assert run2b["last_delta_ms"] == 0

    def test_retry_limit_three(self, api):
        """PRD §3.9: "A failed job may be requeued — moving `FAILED_VALIDATION`
        → `QUEUED` — only while `attempt_count` is below three; at three the
        retry is rejected with `ERR_RETRY_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/validations/conversion_retry_limit_three
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="INTERNAL",
                                            caption_format="SCC")
        job = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "WEBVTT"}, OPS),
            expected_status=201)
        for _ in range(3):
            run = validate_success(api.run_conversion_job(
                job["id"], {"output_duration_ms": 3601000}, OPS))
            assert run["job_status"] == "FAILED_VALIDATION"
            if run["attempt_count"] < 3:
                requeued = get_success_data(api.retry_conversion_job(job["id"], OPS))
                assert requeued["job_status"] == "QUEUED"
        after = validate_success(api.get_conversion_job(job["id"], OPS))
        assert after["attempt_count"] == 3
        assert after["job_status"] == "FAILED_VALIDATION"
        resp = api.retry_conversion_job(job["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_RETRY_LIMIT_REACHED)


class TestArchiveRetention:
    def test_rearchive_keeps_retention_clock(self, api):
        """PRD §3.9: "Restore moves `COLD_STORE` → `RESTORE_PENDING` →
        `RESTORED_HOT`, and rearchiving returns `RESTORED_HOT` → `COLD_STORE`
        **without** recomputing `archived_at` or `purge_after` — the retention
        clock keeps running from the original cold-store instant."
        PRD §3.9: "`LIVE_ONLY`, retaining 90 days, for live-event subjects".

        Design: Corner/state_machines/archive_rearchive_keeps_retention_clock
        """
        set_clock("2026-08-10T08:00:00Z")
        ctx = setup_settled_event()
        ai_id = ctx["archive_item"]["id"]
        cold = validate_success(api.cold_store(ai_id, OPS))
        assert_same_instant(cold["archived_at"], "2026-08-10T15:00:00Z")
        assert_same_instant(cold["purge_after"], "2026-11-08T15:00:00Z")
        get_success_data(api.request_restore(ai_id, OPS))
        get_success_data(api.complete_restore(ai_id, OPS))
        set_clock("2026-09-01T00:00:00Z")
        rearchived = validate_success(api.rearchive(ai_id, OPS))
        assert rearchived["archive_status"] == "COLD_STORE"
        assert_same_instant(rearchived["archived_at"], "2026-08-10T15:00:00Z")
        assert_same_instant(rearchived["purge_after"], "2026-11-08T15:00:00Z")

    def test_purge_retention_boundary(self, api):
        """PRD §3.9: "the current instant must be at or past `purge_after` —
        purging exactly at `purge_after` succeeds, earlier attempts are rejected
        with `ERR_RETENTION_NOT_ELAPSED` (HTTP 409)".

        Design: Corner/calculations/archive_purge_retention_boundary
        """
        set_clock("2026-08-10T08:00:00Z")
        ctx = setup_settled_event()
        ai_id = ctx["archive_item"]["id"]
        cold = validate_success(api.cold_store(ai_id, OPS))
        assert_same_instant(cold["purge_after"], "2026-11-08T15:00:00Z")

        set_clock("2026-11-08T14:59:59Z")  # one second before purge_after
        resp = api.purge(ai_id, OPS)
        validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_ELAPSED)

        set_clock("2026-11-08T15:00:00Z")  # exactly purge_after (inclusive)
        purged = validate_success(api.purge(ai_id, OPS))
        assert purged["archive_status"] == "PURGED"

    def test_purge_blocked_by_legal_hold(self, api):
        """PRD §3.9: "`legal_hold` must be false — purging under a legal hold is
        rejected with `ERR_ARCHIVE_LEGAL_HOLD` (HTTP 409)".
        PRD §3.9: "The `legal_hold` flag itself is managed through a dedicated
        capability that sets or clears it on demand".

        Design: Corner/validations/purge_blocked_by_legal_hold
        """
        set_clock("2026-08-10T08:00:00Z")
        ctx = setup_settled_event()
        ai_id = ctx["archive_item"]["id"]
        get_success_data(api.cold_store(ai_id, OPS))
        get_success_data(api.set_legal_hold(ai_id, {"legal_hold": True}, OPS))
        set_clock("2026-11-08T15:00:00Z")  # retention elapsed
        resp = api.purge(ai_id, OPS)
        validate_error(resp, ApiErrorId.ERR_ARCHIVE_LEGAL_HOLD)
        get_success_data(api.set_legal_hold(ai_id, {"legal_hold": False}, OPS))
        purged = validate_success(api.purge(ai_id, OPS))
        assert purged["archive_status"] == "PURGED"


class TestDisputeFreeze:
    def test_dispute_freeze_blocks_cold_store(self, api):
        """PRD §3.9: "Cold storage moves `ACTIVE_HOLD` → `COLD_STORE`, is
        blocked while `dispute_freeze` is true (rejected with
        `ERR_INVALID_TRANSITION`), and pins the retention clock: `archived_at`
        is stamped with the current instant and `purge_after` is computed once
        as `archived_at` plus the retention class's days, never recomputed
        afterward."
        PRD §3.9: "`STANDARD`, retaining 1095 days, otherwise."

        Design: Corner/cross_cutting_layers/dispute_freeze_blocks_cold_store
        """
        set_clock(MONDAY)
        ctx = setup_delivered_captions_order(compliance_standard="INTERNAL")
        items = get_success_data(api.list_archive_items(
            OPS, params={"caption_track_id": ctx["track"]["id"]}))
        assert len(items) == 1
        ai_id = items[0]["id"]
        comp = file_complaint(ctx["client"]["id"], severity="MAJOR",
                              description="timing drift",
                              caption_track_id=ctx["track"]["id"])
        resp = api.cold_store(ai_id, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        get_success_data(api.dismiss_complaint(
            comp["id"], {"rationale": "not a defect"}, OPS))
        cold = validate_success(api.cold_store(ai_id, OPS))
        assert cold["archive_status"] == "COLD_STORE"
        assert_same_instant(cold["purge_after"], "2029-08-02T10:00:00Z")
