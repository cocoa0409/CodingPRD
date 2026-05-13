"""CRUD coverage for Streamer, Studio, TimeSlotConfig, and Product.

PRD §3.1–§3.3 describe the catalog entities and their input fields.
"""

import pytest

from test_helpers import (
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    ADMIN_HEADERS,
    OPS_HEADERS,
    NON_EXISTENT_UUID,
    create_streamer_payload,
    create_studio_payload,
    create_time_slot_payload,
    create_product_payload,
    assert_streamer,
    assert_studio,
    assert_time_slot,
    assert_product,
    create_streamer,
    create_studio,
    add_time_slot,
    create_product,
    iso,
    ERR_NOT_FOUND,
)
from datetime import datetime, timezone, timedelta


class TestStreamerCreation:
    """PRD §3.1: streamer creation by PlatformAdmin."""

    def test_create_streamer_initializes_defaults(self, api):
        """PRD §3.1: "On creation the server initializes tier to BRONZE,
        violation_score to 0, lifetime_gmv_cents to 0, completed_broadcast_count
        to 0, status to ACTIVE, and leaves suspension_until null."
        """
        payload = create_streamer_payload(
            legal_name="Alice",
            professional_cert_categories=["FOOD"],
            content_category_tags=["FOOD"],
        )
        resp = api.create_streamer(payload, ADMIN_HEADERS)
        data = validate_success(resp, expected_status=201)
        assert_streamer(data)
        assert data["tier"] == "BRONZE", "tier must initialize to BRONZE"
        assert data["violation_score"] == 0
        assert data["lifetime_gmv_cents"] == 0
        assert data["completed_broadcast_count"] == 0
        assert data["status"] == "ACTIVE"
        assert data.get("suspension_until") is None, "suspension_until must be null"

    def test_create_streamer_with_duplicate_id_card_rejected(self, api):
        """PRD §3.1: "The id_card_number is unique across active streamers —
        re-registering an id_card_number that is already attached to an active
        record is rejected."
        """
        payload = create_streamer_payload(id_card_number="ID-DUP-001")
        validate_success(api.create_streamer(payload, ADMIN_HEADERS), expected_status=201)
        # Duplicate
        resp = api.create_streamer(payload, ADMIN_HEADERS)
        assert resp.status_code >= 400, (
            "PRD §3.1: duplicate active id_card_number must be rejected"
        )


class TestStudioCreation:
    """PRD §3.2: studio creation and PATCH update."""

    def test_create_studio_initializes_status_open(self, api):
        """PRD §3.2: "The studio starts in status OPEN."""
        payload = create_studio_payload(name="Studio Alpha")
        resp = api.create_studio(payload, ADMIN_HEADERS)
        data = validate_success(resp, expected_status=201)
        assert_studio(data)
        assert data["status"] == "OPEN"
        assert data["version"] == 1

    def test_update_studio_with_stale_version_returns_conflict(self, api):
        """PRD §2.4: "When present, the value must equal the entity's current
        version integer; a mismatch is rejected with ERR_VERSION_CONFLICT
        (HTTP 409)."
        """
        studio = create_studio()
        # First update — must succeed and bump version to 2
        validate_success(
            api.update_studio(studio["id"], {"status": "RESTRICTED", "version": 1}, ADMIN_HEADERS)
        )
        # Replay with stale version — must fail
        resp = api.update_studio(studio["id"], {"status": "CLOSED", "version": 1}, ADMIN_HEADERS)
        validate_error(resp, "ERR_VERSION_CONFLICT", expected_status=409)


class TestTimeSlotCreation:
    """PRD §3.2: TimeSlotConfig as append-only window."""

    def test_create_available_window_returns_201(self, api):
        """PRD §3.2: "Each studio's bookable calendar is built from
        TimeSlotConfig rows attached to it. Each row carries a kind of either
        AVAILABLE or MAINTENANCE..."
        """
        studio = create_studio()
        payload = create_time_slot_payload(kind="AVAILABLE")
        resp = api.create_time_slot(studio["id"], payload, ADMIN_HEADERS)
        data = validate_success(resp, expected_status=201)
        assert_time_slot(data)
        assert data["kind"] == "AVAILABLE"

    def test_time_slot_does_not_carry_version_or_updated_at(self, api):
        """PRD §2.4: "The lightweight log-style entities TimeSlotConfig,
        ApprovalRecord, ExternalEvent, and AuditLog carry only id and
        created_at; they have neither updated_at nor version because they are
        append-only and never mutated after their initial write."
        """
        studio = create_studio()
        data = add_time_slot(studio["id"])
        # PRD says these append-only entities 'have neither' — they MUST NOT
        # appear on the response.
        assert "updated_at" not in data, "TimeSlotConfig must not carry updated_at"
        assert "version" not in data, "TimeSlotConfig must not carry version"


class TestProductCreation:
    """PRD §3.3: product catalog."""

    def test_create_product_initializes_on_shelf_and_zero_reserved(self, api):
        """PRD §3.3: "On creation the server sets status to ON_SHELF and
        reserved_stock to 0."
        """
        payload = create_product_payload(name="Widget A", category="FOOD", available_stock=50)
        resp = api.create_product(payload, ADMIN_HEADERS)
        data = validate_success(resp, expected_status=201)
        assert_product(data)
        assert data["status"] == "ON_SHELF"
        assert data["reserved_stock"] == 0
        assert data["available_stock"] == 50


class TestNotFoundResolution:
    """PRD §2.6: path-id resolution."""

    def test_get_streamer_with_unknown_id_returns_404(self, api):
        """PRD §2.6: "If a path segment names an entity that does not exist (a
        streamer id, application id, studio id, product id, settlement id,
        violation id, or appeal id), the request is rejected with ERR_NOT_FOUND
        (HTTP 404) at the first unresolved segment."
        """
        resp = api.get_streamer(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ERR_NOT_FOUND, expected_status=404)

    def test_update_studio_with_unknown_id_returns_404(self, api):
        """PRD §2.6: "If a path segment names an entity that does not exist ...
        the request is rejected with ERR_NOT_FOUND (HTTP 404) at the first
        unresolved segment."
        """
        resp = api.update_studio(NON_EXISTENT_UUID, {"status": "OPEN"}, ADMIN_HEADERS)
        validate_error(resp, ERR_NOT_FOUND, expected_status=404)


class TestStreamerList:
    """PRD §4: list streamers (paginated, filterable)."""

    def test_list_streamers_is_paginated_and_ascending(self, api):
        """PRD §2.3: "List endpoints return their items in ascending created_at
        order."
        """
        s1 = create_streamer(legal_name="A")
        s2 = create_streamer(legal_name="B")
        resp = api.list_streamers(ADMIN_HEADERS, params={"limit": 100})
        from test_helpers import validate_paginated
        items, meta = validate_paginated(resp)
        ids = [it["id"] for it in items]
        assert s1["id"] in ids and s2["id"] in ids
        # ascending by created_at
        creations = [it["created_at"] for it in items]
        assert creations == sorted(creations), "list must be ascending by created_at"
