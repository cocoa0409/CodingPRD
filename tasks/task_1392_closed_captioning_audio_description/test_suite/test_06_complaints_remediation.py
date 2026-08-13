"""Error complaints and remediation: the depth-4 dispute cascade, the
resolve/reopen cycle with its 14-day window, subject cardinality, complaint
windows, escalation sweep, and the dismissal unwind (PRD §3.2, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_order,
    conform_track,
    create_cleared_media,
    create_client,
    create_live_event,
    create_track,
    create_work_order,
    deliver_order,
    file_complaint,
    finalize_qc,
    get_success_data,
    make_client_headers,
    make_editor_headers,
    make_ops_headers,
    quote_order,
    remediate_and_redeliver,
    resolve_complaint,
    run_sweep,
    set_clock,
    setup_confirmed_event,
    setup_delivered_captions_order,
    setup_in_production_order,
    setup_open_complaint,
    start_production,
    track_submit_and_enqueue,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import EDITOR, INTAKE, OPS, SCHED

MONDAY = "2026-08-03T10:00:00Z"


class TestComplaintCreateCascade:
    """Difficulty depth-4 chain: complaint OPEN -> track DISPUTED -> archive
    freeze + work order REMEDIATION -> QUEUED conversion job CANCELLED."""

    def _setup(self, api):
        set_clock(MONDAY)
        ctx = setup_delivered_captions_order(compliance_standard="FCC_BROADCAST",
                                             turnaround_tier="RUSH",
                                             caption_format="SCC",
                                             frame_rate="FPS_29_97_DF",
                                             client_name="FCC Client")
        job = validate_success(api.create_conversion_job(
            {"source_track_id": ctx["track"]["id"], "target_format": "WEBVTT"}, OPS),
            expected_status=201)
        items = get_success_data(api.list_archive_items(
            OPS, params={"caption_track_id": ctx["track"]["id"]}))
        assert len(items) == 1
        return ctx, job, items[0]

    def test_cascade_disputes_track_freezes_archive_bubbles_order(self, api):
        """PRD §3.8: "Filing against a track cascades: the subject track moves
        `DELIVERED` → `DISPUTED`, its archive item (if any) sets
        `dispute_freeze` true, the owning work order moves `DELIVERED` →
        `REMEDIATION` with `active_complaint_count` raised by one, and any
        `QUEUED` conversion jobs referencing the order's tracks are cancelled."

        Design: Difficulty/transitive_cascade/complaint_create_depth4_cascade
        """
        ctx, job, archive = self._setup(api)
        comp = file_complaint(ctx["client"]["id"], severity="FCC_CRITICAL",
                              description="dropped caption during breaking news",
                              caption_track_id=ctx["track"]["id"])
        assert comp["complaint_status"] == "OPEN"
        track = validate_success(api.get_caption_track(ctx["track"]["id"], EDITOR))
        assert track["track_status"] == "DISPUTED"
        item = validate_success(api.get_archive_item(archive["id"], OPS))
        assert item["dispute_freeze"] is True
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], OPS))
        assert wo["order_status"] == "REMEDIATION"
        assert wo["active_complaint_count"] == 1

    def test_cascade_cancels_queued_conversion_job(self, api):
        """PRD §3.2: "entering remediation also cancels every `QUEUED`
        conversion job referencing any track of the order, freezing in-flight
        conversion work."

        Design: Difficulty/transitive_cascade/complaint_create_depth4_cascade
        """
        ctx, job, _ = self._setup(api)
        file_complaint(ctx["client"]["id"], severity="FCC_CRITICAL",
                       description="dropped caption during breaking news",
                       caption_track_id=ctx["track"]["id"])
        after = validate_success(api.get_conversion_job(job["id"], OPS))
        assert after["job_status"] == "CANCELLED"


class TestComplaintLifecycle:
    def test_complaint_double_open_rejected(self, api):
        """PRD §3.8: "A subject with an existing complaint in `OPEN`, `TRIAGED`,
        `REMEDIATING`, or `REOPENED` rejects a second filing with
        `ERR_COMPLAINT_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/state_machines/complaint_double_open_rejected
        """
        set_clock(MONDAY)
        ctx = setup_open_complaint(severity="MINOR", description="first")
        resp = api.create_complaint(
            {"severity": "MAJOR", "description": "second",
             "caption_track_id": ctx["track"]["id"]},
            make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_ALREADY_OPEN)
        rows = get_success_data(api.list_complaints(
            OPS, params={"caption_track_id": ctx["track"]["id"]}))
        assert len(rows) == 1

    def test_complaint_subject_cardinality_rejected(self, api):
        """PRD §3.8: "a body with zero or multiple subjects non-null is rejected
        with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/complaint_subject_cardinality_rejected
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        track = create_track(ctx["work_order"]["id"], author="editor-1")
        event = create_live_event(ctx["client"]["id"])
        cid = ctx["client"]["id"]
        resp_none = api.create_complaint(
            {"severity": "MINOR", "description": "no subject"},
            make_client_headers(cid))
        validate_error(resp_none, ApiErrorId.ERR_VALIDATION)
        resp_two = api.create_complaint(
            {"severity": "MINOR", "description": "two subjects",
             "caption_track_id": track["id"], "live_event_id": event["id"]},
            make_client_headers(cid))
        validate_error(resp_two, ApiErrorId.ERR_VALIDATION)

    def test_complaint_window_30d_boundary(self, api):
        """PRD §3.8: "the complaint must be opened within thirty days inclusive
        of the subject's completion — for tracks, the work order's most recent
        `delivered_at`; for live events, the event's `end_at` — otherwise the
        filing is rejected with `ERR_COMPLAINT_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/validations/complaint_window_30d_boundary
        """
        set_clock(MONDAY)
        ctx_a = setup_delivered_captions_order(compliance_standard="INTERNAL")
        client = ctx_a["client"]
        # Second delivered order for the same client.
        m_b = create_cleared_media(client["id"], title="B", duration_seconds=3600)
        wo_b = create_work_order(client["id"], m_b["id"], turnaround_tier="STANDARD")
        quote_order(wo_b["id"])
        confirm_order(wo_b["id"], client["id"])
        start_production(wo_b["id"])
        t_b = create_track(wo_b["id"], author="editor-1")
        track_submit_and_enqueue(t_b["id"], author="editor-1")
        finalize_qc(t_b["id"], minor_errors=100)
        conform_track(t_b["id"], author="editor-1")
        deliver_order(wo_b["id"])

        set_clock("2026-09-02T10:00:00Z")  # exactly delivered_at + 30 days
        ok = validate_success(api.create_complaint(
            {"severity": "MINOR", "description": "edge-ok",
             "caption_track_id": ctx_a["track"]["id"]},
            make_client_headers(client["id"])), expected_status=201)
        assert ok["complaint_status"] == "OPEN"

        set_clock("2026-09-02T10:00:01Z")  # one second past the window
        resp = api.create_complaint(
            {"severity": "MINOR", "description": "edge-late",
             "caption_track_id": t_b["id"]},
            make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_WINDOW_CLOSED)


class TestResolveReopenCycle:
    """Difficulty cyclic machine on Complaint: RESOLVED -> REOPENED -> TRIAGED,
    with escalation on reopen and re-dispute of the current artifact."""

    def _resolved_ctx(self, api):
        set_clock(MONDAY)
        ctx = setup_open_complaint(compliance_standard="INTERNAL", severity="MAJOR",
                                   description="misspelled name at 00:12")
        remediate_and_redeliver(ctx, resolver="ops-1")
        set_clock("2026-08-10T09:00:00Z")
        resolve_complaint(ctx["complaint"]["id"], resolver="ops-1")
        return ctx

    def test_reopen_at_inclusive_window_edge_succeeds(self, api):
        """PRD §3.8: "A client may reopen a `RESOLVED` complaint within fourteen
        days inclusive of `resolved_at`; later attempts are rejected with
        `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409), and the caller must own the
        complaint."
        PRD §3.8: "Reopening moves `RESOLVED` → `REOPENED`, increments
        `escalation_level` by one".

        Design: Difficulty/non_linear_state_machine/complaint_resolve_reopen_cycle
        """
        ctx = self._resolved_ctx(api)
        set_clock("2026-08-24T09:00:00Z")  # resolved_at + 14 days exactly
        reopened = validate_success(api.reopen_complaint(
            ctx["complaint"]["id"], make_client_headers(ctx["client"]["id"])))
        assert reopened["complaint_status"] == "REOPENED"
        assert reopened["escalation_level"] == 1

    def test_reopen_redisputes_current_artifact_and_bubbles_order(self, api):
        """PRD §3.8: "re-disputes the current artifact — the remediation track
        when `remediation_track_id` is set, otherwise the original subject track
        — moving it `DELIVERED` → `DISPUTED` with `dispute_freeze` re-applied,
        and pushes the work order back `DELIVERED` → `REMEDIATION` with the
        count raised again. From `REOPENED`, triage moves `REOPENED` →
        `TRIAGED` and restarts the cycle."

        Design: Difficulty/non_linear_state_machine/complaint_resolve_reopen_cycle
        """
        ctx = self._resolved_ctx(api)
        set_clock("2026-08-24T09:00:00Z")
        get_success_data(api.reopen_complaint(
            ctx["complaint"]["id"], make_client_headers(ctx["client"]["id"])))
        artifact = validate_success(
            api.get_caption_track(ctx["remediation_track_id"], EDITOR))
        assert artifact["track_status"] == "DISPUTED", (
            "the remediation artifact is re-disputed, not the SUPERSEDED v1"
        )
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], OPS))
        assert wo["order_status"] == "REMEDIATION"
        assert wo["active_complaint_count"] == 1
        triaged = validate_success(api.triage_complaint(ctx["complaint"]["id"], OPS))
        assert triaged["complaint_status"] == "TRIAGED"
        assert triaged["escalation_level"] == 1


class TestReopenWindowClosed:
    def test_reopen_after_window_closed(self, api):
        """PRD §3.8: "A client may reopen a `RESOLVED` complaint within fourteen
        days inclusive of `resolved_at`; later attempts are rejected with
        `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409), and the caller must own the
        complaint."

        Design: Corner/state_machines/complaint_reopen_after_window_closed
        """
        set_clock(MONDAY)
        ctx = setup_open_complaint(compliance_standard="INTERNAL", severity="MAJOR",
                                   description="timing drift")
        remediate_and_redeliver(ctx, resolver="ops-1")
        set_clock("2026-08-10T09:00:00Z")
        resolve_complaint(ctx["complaint"]["id"], resolver="ops-1")
        resolved = validate_success(api.get_complaint(ctx["complaint"]["id"], OPS))
        assert resolved["complaint_status"] == "RESOLVED"
        set_clock("2026-08-24T09:00:01Z")  # resolved_at + 14d + 1s
        resp = api.reopen_complaint(
            ctx["complaint"]["id"], make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED)
        after = validate_success(api.get_complaint(ctx["complaint"]["id"], OPS))
        assert after["complaint_status"] == "RESOLVED"
        artifact = validate_success(
            api.get_caption_track(ctx["remediation_track_id"], EDITOR))
        assert artifact["track_status"] == "DELIVERED"
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], OPS))
        assert wo["order_status"] == "DELIVERED"


class TestResolveGates:
    def test_resolve_without_delivered_artifact_rejected(self, api):
        """PRD §3.8: "For a caption or AD subject (`REMEDIATING` → `RESOLVED`),
        the remediation artifact — the `remediation_track_id` track for
        captions, the reopened AD track itself for audio description — must be
        `DELIVERED`, else the resolve is rejected with
        `ERR_RESOLUTION_ARTIFACT_INCOMPLETE` (HTTP 409)".

        Design: Corner/state_machines/resolve_without_delivered_artifact_rejected
        """
        set_clock(MONDAY)
        ctx = setup_open_complaint(severity="MINOR", description="typo")
        get_success_data(api.triage_complaint(ctx["complaint"]["id"], OPS))
        comp = get_success_data(
            api.begin_remediation(ctx["complaint"]["id"], make_ops_headers("ops-1")))
        assert comp["remediation_track_id"], "remediation track must exist"
        resp = api.resolve_complaint(comp["id"], make_ops_headers("ops-1"))
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_ARTIFACT_INCOMPLETE)
        after = validate_success(api.get_complaint(comp["id"], OPS))
        assert after["complaint_status"] == "REMEDIATING"
        assert after["resolved_at"] is None


class TestLiveComplaint:
    def test_live_complaint_resolves_without_remediation(self, api):
        """PRD §3.8: "Beginning remediation moves `TRIAGED` → `REMEDIATING` and
        is only defined for track subjects — a live-event subject is rejected
        with `ERR_INVALID_TRANSITION`, since live events have no remediation
        artifact."
        PRD §3.8: "For a live-event subject (`TRIAGED` → `RESOLVED`), no
        artifact exists and a `resolution_note` is required instead."

        Design: Corner/state_machines/live_complaint_resolves_without_remediation
        """
        set_clock("2026-08-10T08:00:00Z")
        ctx = setup_confirmed_event()
        get_success_data(api.go_on_air(ctx["event"]["id"], SCHED))
        set_clock("2026-08-10T15:00:00Z")
        get_success_data(api.wrap_event(ctx["event"]["id"], SCHED))
        comp = file_complaint(ctx["client"]["id"], severity="FCC_CRITICAL",
                              description="30s caption outage at 14:22",
                              live_event_id=ctx["event"]["id"])
        get_success_data(api.triage_complaint(comp["id"], OPS))
        resp = api.begin_remediation(comp["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        resolved = validate_success(api.resolve_complaint(
            comp["id"], make_ops_headers("ops-1"),
            payload={"resolution_note": "station notified; outage logged"}))
        assert resolved["complaint_status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None


class TestAcceptDeliveryGate:
    def test_accept_delivery_blocked_by_open_complaint(self, api):
        """PRD §3.2: "After delivery, the client accepts by moving `DELIVERED` →
        `CLIENT_ACCEPTED`, which requires the order's `active_complaint_count`
        to be zero — otherwise the acceptance is rejected with
        `ERR_COMPLAINTS_STILL_OPEN` (HTTP 409)."
        PRD §3.8: "Dismissal — from `OPEN` or `TRIAGED`, with a `rationale`
        required — moves the complaint to its terminal `DISMISSED` state and
        unwinds the cascade: the subject track returns `DISPUTED` → `DELIVERED`,
        the archive item's `dispute_freeze` clears, and `active_complaint_count`
        drops by one; when it reaches zero the order returns `REMEDIATION` →
        `DELIVERED`."

        Design: Corner/validations/accept_delivery_blocked_by_open_complaint
        """
        set_clock(MONDAY)
        ctx = setup_open_complaint(severity="MINOR", description="typo")
        wo_id = ctx["work_order"]["id"]
        resp = api.accept_delivery(wo_id, make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINTS_STILL_OPEN)

        dismissed = validate_success(api.dismiss_complaint(
            ctx["complaint"]["id"], {"rationale": "client error"}, OPS))
        assert dismissed["complaint_status"] == "DISMISSED"
        track = validate_success(api.get_caption_track(ctx["track"]["id"], EDITOR))
        assert track["track_status"] == "DELIVERED"
        wo = validate_success(api.get_work_order(wo_id, OPS))
        assert wo["active_complaint_count"] == 0
        assert wo["order_status"] == "DELIVERED"

        accepted = validate_success(
            api.accept_delivery(wo_id, make_client_headers(ctx["client"]["id"])))
        assert accepted["order_status"] == "CLIENT_ACCEPTED"


class TestComplaintEscalation:
    def test_escalation_threshold_edges(self, api):
        """PRD §3.8: "For every complaint in `OPEN`, `TRIAGED`, `REMEDIATING`,
        or `REOPENED` — `RESOLVED` and `DISMISSED` complaints do not escalate —
        the age in whole hours is measured from the complaint's `updated_at` to
        the current instant, and when that age reaches the severity's threshold
        the `escalation_level` increments by one: twenty-four hours for
        `FCC_CRITICAL`, forty-eight for `MAJOR`, seventy-two for `MINOR`, with
        the threshold inclusive. Because escalation is itself a mutation,
        `updated_at` refreshes and the next escalation requires another full
        threshold period."

        Design: Corner/calculations/complaint_escalation_threshold_edges
        """
        set_clock(MONDAY)
        ctx = setup_open_complaint(compliance_standard="FCC_BROADCAST",
                                   severity="FCC_CRITICAL",
                                   description="dropped captions")
        comp_id = ctx["complaint"]["id"]

        set_clock("2026-08-04T09:59:59Z")  # age 23:59:59
        sweep0 = run_sweep()
        assert sweep0["escalated_complaint_count"] == 0

        set_clock("2026-08-04T10:00:00Z")  # age exactly 24h -> inclusive
        sweep1 = run_sweep()
        assert sweep1["escalated_complaint_count"] == 1
        comp = validate_success(api.get_complaint(comp_id, OPS))
        assert comp["escalation_level"] == 1

        set_clock("2026-08-05T10:00:00Z")  # another full 24h after the refresh
        sweep2 = run_sweep()
        assert sweep2["escalated_complaint_count"] == 1
        comp = validate_success(api.get_complaint(comp_id, OPS))
        assert comp["escalation_level"] == 2
