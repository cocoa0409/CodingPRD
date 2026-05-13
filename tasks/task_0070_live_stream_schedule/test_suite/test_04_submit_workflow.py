"""Submit transition — qualification, studio status, available window, overlap.

PRD §3.4 — submit preconditions (priority order from §2.9).
"""

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    iso,
    setup_active_streamer,
    setup_open_studio,
    setup_studio_with_window,
    setup_draft_application,
    attach_compatible_product,
    submit_application,
    create_application_payload,
    create_studio,
    create_time_slot_payload,
    add_time_slot,
    ERR_STREAMER_NOT_ACTIVE,
    ERR_QUALIFICATION_MISSING,
    ERR_OUT_OF_AVAILABLE_WINDOW,
    ERR_STUDIO_INTERVAL_CONFLICT,
    ERR_INVALID_STATE,
)


class TestSubmitHappyPath:
    """PRD §3.4: 'On success the server computes the provisional slot fee
    (described below) and writes it to provisional_fee_cents, persists the
    application...'
    """

    def test_submit_transitions_draft_to_ops_pending(self, api):
        """PRD §3.4: "After attaching products, the streamer advances the
        application from DRAFT to OPS_PENDING."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        result = submit_application(streamer, app)
        assert result["review_status"] == "OPS_PENDING", \
            f"expected OPS_PENDING, got {result['review_status']}"

    def test_submit_writes_provisional_fee_cents(self, api):
        """PRD §3.4: "On success the server computes the provisional slot fee
        (described below) and writes it to provisional_fee_cents, persists the
        application, and emits an audit record."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        result = submit_application(streamer, app)
        assert "provisional_fee_cents" in result, "PRD requires provisional_fee_cents"
        assert isinstance(result["provisional_fee_cents"], int) and result["provisional_fee_cents"] > 0


class TestSubmitOwnership:
    def test_submit_by_non_owner_streamer_rejected(self, api):
        """PRD §3.4: "the acting streamer owns the application (otherwise
        ERR_FORBIDDEN)..."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer_a, studio, app = setup_draft_application()
        streamer_b = setup_active_streamer()
        resp = api.submit_application(app["id"], make_streamer_headers(streamer_b["id"]))
        validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


class TestSubmitQualification:
    """PRD §3.4: 'the streamer's real_name_verified is true and the streamer's
    health_cert_expires_at is strictly later than the application's ends_at
    (otherwise ERR_QUALIFICATION_MISSING, HTTP 422)'.
    """

    def test_unverified_real_name_blocks_submit(self, api):
        """PRD §3.4: "the streamer's real_name_verified is true and the
        streamer's health_cert_expires_at is strictly later than the
        application's ends_at (otherwise ERR_QUALIFICATION_MISSING, HTTP 422)"
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer(real_name_verified=False)
        studio = setup_open_studio()
        _, _, app = setup_draft_application(streamer=streamer, studio=studio)
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_QUALIFICATION_MISSING, expected_status=422)

    def test_expired_health_cert_blocks_submit(self, api):
        """PRD §3.4: "the streamer's real_name_verified is true and the
        streamer's health_cert_expires_at is strictly later than the
        application's ends_at (otherwise ERR_QUALIFICATION_MISSING, HTTP 422)"
        """
        set_clock(DEFAULT_BASE_TIME)
        # Health cert expires before the application ends_at
        bad_health_cert = DEFAULT_BASE_TIME + timedelta(days=5)
        streamer = setup_active_streamer(health_cert_expires_at=iso(bad_health_cert))
        # Application runs 10 days from base => after expiry
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio, starts_at=starts, ends_at=ends
        )
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_QUALIFICATION_MISSING, expected_status=422)


class TestSubmitStudioStatus:
    """PRD §3.4: 'the studio's status is OPEN'. PRD §3.2 reinforces: 'if not, the
    submit is rejected with ERR_INVALID_STATE'.
    """

    def test_studio_under_maintenance_blocks_submit(self, api):
        """# difficulty: cross_entity_state_dependency/application_submit_requires_studio_open_pair_application_studio
        PRD §3.2: "When a streamer requests an interval, the server first
        verifies the studio's overall status is OPEN; if not, the submit is
        rejected with ERR_INVALID_STATE."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        studio = setup_open_studio()
        # Move studio to UNDER_MAINTENANCE
        validate_success(
            api.update_studio(studio["id"], {"status": "UNDER_MAINTENANCE", "version": studio["version"]}, ADMIN_HEADERS)
        )
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio, starts_at=starts, ends_at=ends
        )
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)


class TestSubmitTimeWindow:
    """PRD §3.2 + §3.4: AVAILABLE coverage and MAINTENANCE disjointness."""

    def test_interval_outside_available_window_rejected(self, api):
        """PRD §3.2: "every minute of the requested half-open interval is
        covered by at least one AVAILABLE TimeSlotConfig and intersects no
        MAINTENANCE TimeSlotConfig; a violation yields
        ERR_OUT_OF_AVAILABLE_WINDOW (HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        # Studio available only days 1-5; request a slot on day 10
        avail_start = DEFAULT_BASE_TIME + timedelta(days=1)
        avail_end = DEFAULT_BASE_TIME + timedelta(days=5)
        studio = setup_studio_with_window(available_start=avail_start, available_end=avail_end)
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio, starts_at=starts, ends_at=ends
        )
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_OUT_OF_AVAILABLE_WINDOW, expected_status=409)

    def test_interval_intersecting_maintenance_rejected(self, api):
        """# difficulty: resource_temporal_overlap/studio_maintenance_window_blocks_overlap
        PRD §3.2: "every minute of the requested half-open interval is
        covered by at least one AVAILABLE TimeSlotConfig and intersects no
        MAINTENANCE TimeSlotConfig; a violation yields
        ERR_OUT_OF_AVAILABLE_WINDOW (HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        avail_start = DEFAULT_BASE_TIME + timedelta(days=1)
        avail_end = DEFAULT_BASE_TIME + timedelta(days=30)
        # Maintenance overlaps the application interval
        maint_start = DEFAULT_BASE_TIME + timedelta(days=10, hours=11, minutes=30)
        maint_end = DEFAULT_BASE_TIME + timedelta(days=10, hours=12)
        studio = setup_studio_with_window(
            available_start=avail_start,
            available_end=avail_end,
            maintenance=(maint_start, maint_end),
        )
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio, starts_at=starts, ends_at=ends
        )
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_OUT_OF_AVAILABLE_WINDOW, expected_status=409)


class TestSubmitStudioOverlap:
    """PRD §3.4: 'the interval does not overlap any existing application of the
    same Studio whose review_status is APPROVED or whose operational_status is
    SCHEDULED or LIVE (otherwise ERR_STUDIO_INTERVAL_CONFLICT, HTTP 409).'
    """

    def test_overlapping_approved_application_blocks_submit(self, api):
        """PRD §3.4: "the interval does not overlap any existing application of
        the same Studio whose review_status is APPROVED or whose
        operational_status is SCHEDULED or LIVE (otherwise
        ERR_STUDIO_INTERVAL_CONFLICT, HTTP 409)."
        """
        from test_helpers import setup_scheduled_application
        set_clock(DEFAULT_BASE_TIME)
        # First application fully approved -> SCHEDULED on studio
        bundle = setup_scheduled_application()
        studio = bundle["studio"]
        app_a = bundle["application"]
        # Second streamer wants the same studio at an overlapping window
        streamer_b = setup_active_streamer()
        # Use a slot that overlaps app_a
        from test_helpers.fixtures import _parse_iso
        a_starts = _parse_iso(app_a["starts_at"])
        a_ends = _parse_iso(app_a["ends_at"])
        overlap_starts = a_starts + timedelta(minutes=30)
        overlap_ends = a_ends + timedelta(hours=1)
        _, _, app_b = setup_draft_application(
            streamer=streamer_b, studio=studio,
            starts_at=overlap_starts, ends_at=overlap_ends,
        )
        resp = api.submit_application(app_b["id"], make_streamer_headers(streamer_b["id"]))
        validate_error(resp, ERR_STUDIO_INTERVAL_CONFLICT, expected_status=409)


class TestSubmitFromInvalidState:
    """PRD §2.9: 'state precondition (ERR_INVALID_STATE)' — also covered by
    difficulty-design Rule 5 instance state_vs_business_temporal_on_submit.
    """

    def test_resubmit_already_ops_pending_application_returns_invalid_state(self, api):
        """PRD §2.9: "Resource is in a state that allows the requested transition
        (see §1.2)" — submit only legal from DRAFT. The PRD's validation table
        names ERR_INVALID_STATE for state-precondition failures.
        PRD §3.4: "After attaching products, the streamer advances the
        application from DRAFT to OPS_PENDING." — only DRAFT may submit.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        submit_application(streamer, app)  # OPS_PENDING
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
