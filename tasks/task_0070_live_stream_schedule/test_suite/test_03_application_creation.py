"""Application creation and interval validation.

PRD §3.4 — ScheduleApplication creation; §2.6 — body id resolution.
"""

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    ADMIN_HEADERS,
    make_streamer_headers,
    create_application_payload,
    create_streamer,
    create_studio,
    setup_active_streamer,
    setup_open_studio,
    DEFAULT_BASE_TIME,
    set_clock,
    iso,
    assert_application,
    ERR_INVALID_INTERVAL,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_AUTH_REQUIRED,
)


class TestApplicationInitialState:
    """PRD §3.4: "The fresh application carries review_status DRAFT and
    operational_status NOT_SCHEDULED."
    """

    def test_create_application_initializes_draft_and_not_scheduled(self, api):
        """PRD §3.4: "The fresh application carries review_status DRAFT and
        operational_status NOT_SCHEDULED."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        studio = setup_open_studio()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        payload = create_application_payload(streamer["id"], studio["id"], starts, ends)
        headers = make_streamer_headers(streamer["id"])
        resp = api.create_application(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert_application(data)
        assert data["review_status"] == "DRAFT"
        assert data["operational_status"] == "NOT_SCHEDULED"


class TestIntervalValidation:
    """PRD §3.4: 'The interval must satisfy ends_at > starts_at and the
    difference between ends_at and starts_at must be at least 30 minutes and at
    most 8 hours — outside that range the create is rejected with
    ERR_INVALID_INTERVAL (HTTP 422).'
    """

    @pytest.fixture
    def fresh_streamer_studio(self):
        set_clock(DEFAULT_BASE_TIME)
        return setup_active_streamer(), setup_open_studio()

    def test_ends_at_equal_starts_at_rejected(self, api, fresh_streamer_studio):
        """PRD §3.4: "The interval must satisfy ends_at > starts_at and the
        difference between ends_at and starts_at must be at least 30 minutes
        and at most 8 hours — outside that range the create is rejected with
        ERR_INVALID_INTERVAL (HTTP 422)."
        """
        streamer, studio = fresh_streamer_studio
        t = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        payload = create_application_payload(streamer["id"], studio["id"], t, t)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_INTERVAL, expected_status=422)

    def test_duration_under_30_minutes_rejected(self, api, fresh_streamer_studio):
        """PRD §3.4: "The interval must satisfy ends_at > starts_at and the
        difference between ends_at and starts_at must be at least 30 minutes
        and at most 8 hours — outside that range the create is rejected with
        ERR_INVALID_INTERVAL (HTTP 422)."
        """
        streamer, studio = fresh_streamer_studio
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(minutes=29)
        payload = create_application_payload(streamer["id"], studio["id"], starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_INTERVAL, expected_status=422)

    def test_duration_exactly_30_minutes_accepted(self, api, fresh_streamer_studio):
        """PRD §3.4: "the difference between ends_at and starts_at must be at
        least 30 minutes and at most 8 hours" — boundary X (30 minutes) accepted.
        """
        streamer, studio = fresh_streamer_studio
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(minutes=30)
        payload = create_application_payload(streamer["id"], studio["id"], starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_success(resp, expected_status=201)

    def test_duration_exactly_8_hours_accepted(self, api, fresh_streamer_studio):
        """PRD §3.4: "the difference between ends_at and starts_at must be at
        least 30 minutes and at most 8 hours" — boundary X (8 hours) accepted.
        """
        streamer, studio = fresh_streamer_studio
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=10)
        ends = starts + timedelta(hours=8)
        payload = create_application_payload(streamer["id"], studio["id"], starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_success(resp, expected_status=201)

    def test_duration_over_8_hours_rejected(self, api, fresh_streamer_studio):
        """PRD §3.4: "the difference between ends_at and starts_at must be at
        least 30 minutes and at most 8 hours — outside that range the create
        is rejected with ERR_INVALID_INTERVAL (HTTP 422)."
        """
        streamer, studio = fresh_streamer_studio
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=8)
        ends = starts + timedelta(hours=8, minutes=1)
        payload = create_application_payload(streamer["id"], studio["id"], starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_INTERVAL, expected_status=422)


class TestBodyIdResolution:
    """PRD §2.6: 'Body-referenced ids on creation endpoints (notably studio_id,
    streamer_id, product_id, and application_id) are likewise verified to
    resolve to live entities before any business logic runs; an unresolved body
    id also yields ERR_NOT_FOUND.'
    """

    def test_unknown_studio_id_returns_not_found(self, api):
        """PRD §2.6: "Body-referenced ids on creation endpoints (notably
        studio_id, streamer_id, product_id, and application_id) are likewise
        verified to resolve to live entities before any business logic runs;
        an unresolved body id also yields ERR_NOT_FOUND."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        payload = create_application_payload(streamer["id"], NON_EXISTENT_UUID, starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_NOT_FOUND, expected_status=404)


class TestOwnershipOnCreate:
    """PRD §2.1: 'a Streamer reading or mutating another streamer's resource is
    rejected with ERR_FORBIDDEN.'
    """

    def test_streamer_creating_application_with_other_streamer_id_rejected(self, api):
        """PRD §2.1: "When X-User-Role is Streamer, X-User-ID is the id of the
        acting Streamer entity. Every ownership check on a resource that
        references a streamer compares the resource's streamer_id field to
        X-User-ID; a Streamer reading or mutating another streamer's resource
        is rejected with ERR_FORBIDDEN."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer_a = setup_active_streamer()
        streamer_b = setup_active_streamer()
        studio = setup_open_studio()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        # Pass streamer_b's id in the payload but make the call as streamer_a
        payload = create_application_payload(streamer_b["id"], studio["id"], starts, ends)
        resp = api.create_application(payload, make_streamer_headers(streamer_a["id"]))
        validate_error(resp, ERR_FORBIDDEN, expected_status=403)
