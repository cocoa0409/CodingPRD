"""Auth, RBAC, and existence checks (PRD §2.1, §2.7, §2.12, §5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_event_payload,
    create_referee_payload,
    create_referee,
    event_completed,
    event_open_for_registration,
    file_dispute_payload,
    list_audit_logs,
    open_sample_payload,
    register_n_distinct_participants,
    register_participant_payload,
    submit_result_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# 2.1 / 2.12 P1 — auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        values are otherwise unrecognized, is rejected with ERR_AUTH.'"""
        # Build headers with role only.
        bad_headers = {"X-User-Role": "Organizer"}
        res = api.create_event(create_event_payload(), bad_headers)
        validate_error(res, "ERR_AUTH")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        values are otherwise unrecognized, is rejected with ERR_AUTH.'"""
        bad_headers = {"X-User-ID": "organizer-001"}
        res = api.create_event(create_event_payload(), bad_headers)
        validate_error(res, "ERR_AUTH")

    def test_unrecognized_role_value_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        values are otherwise unrecognized, is rejected with ERR_AUTH.'"""
        bad_headers = build_user_headers("op-1", "PlatformOverlord")
        res = api.create_event(create_event_payload(), bad_headers)
        validate_error(res, "ERR_AUTH")


# ===========================================================================
# 2.1 / 2.12 P2 — RBAC
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["Referee", "Participant", "DisciplinaryOfficer",
         "DopingOfficer", "AppealsBoard"],
    )
    def test_create_event_requires_organizer(self, api, role):
        """PRD §4: 'POST /events ... Authorized Role(s): Organizer.'
        PRD §2.1: 'A request whose role is not authorized for the endpoint
        it is calling is rejected with ERR_FORBIDDEN.'"""
        headers = build_user_headers(f"some-{role}", role)
        res = api.create_event(create_event_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_referee_requires_organizer(self, api):
        """PRD §4: 'POST /referees ... Authorized Role(s): Organizer.'"""
        headers = build_user_headers("some-Referee", "Referee")
        res = api.create_referee(create_referee_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_dispute_filing_requires_participant(self, api, organizer_headers):
        """PRD §4: 'POST /matches/{match_id}/disputes ... Authorized
        Role(s): Participant.'"""
        # Forge a path; the role check must precede the existence check.
        res = api.file_dispute(
            NON_EXISTENT_UUID,
            file_dispute_payload(filed_by_participant_id=NON_EXISTENT_UUID),
            organizer_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_appeal_decide_requires_appeals_board(self, api, disciplinary_headers):
        """PRD §4: 'POST /appeals/{appeal_id}/decide ... Authorized
        Role(s): AppealsBoard.'"""
        from test_helpers import decide_appeal_payload
        res = api.decide_appeal(
            NON_EXISTENT_UUID,
            decide_appeal_payload(uphold=True),
            disciplinary_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# 2.7 / 2.12 P3 — URL path existence
# ===========================================================================
class TestPathExistence:
    def test_get_unknown_event_returns_not_found(self, api, organizer_headers):
        """PRD §2.12 priority 3: 'a non-existent identifier in the URL path
        returns ERR_NOT_FOUND, evaluated left-to-right.'"""
        res = api.get_event(NON_EXISTENT_UUID, organizer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_open_unknown_event_returns_not_found(self, api, organizer_headers):
        """PRD §2.12 priority 3: 'a non-existent identifier in the URL path
        returns ERR_NOT_FOUND, evaluated left-to-right.'"""
        res = api.open_event(NON_EXISTENT_UUID, organizer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_register_under_unknown_event_returns_not_found(
        self, api, organizer_headers
    ):
        """PRD §2.12 priority 3 + §2.7: hierarchical path validation
        rejects unknown event_id in the URL before body checks."""
        res = api.register_participant(
            NON_EXISTENT_UUID,
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# 2.7 / 2.12 P4 — body foreign-key existence
# ===========================================================================
class TestBodyForeignKeyExistence:
    def test_assign_referee_with_unknown_referee_id(
        self, api, organizer_headers
    ):
        """PRD §2.7: 'A request whose URL identifiers all resolve, but
        whose body references a foreign key to a non-existent row (for
        example, a referee_id in a RefereeAssignment body, a participant_id
        in a doping-sample body, or a sanction_id in an appeal body), is
        rejected with ERR_REFERENCE_NOT_FOUND.'"""
        # Build a real event with one drawn match so the URL identifier
        # resolves.
        from test_helpers import event_drawn, list_matches
        event, _ = event_drawn(n_participants=2)
        matches = list_matches(event["id"])
        match = matches[0]
        # Body payload references a non-existent referee_id.
        bad_body = {
            "referee_id": NON_EXISTENT_UUID,
            "role": "HEAD",
        }
        res = api.assign_referee(match["id"], bad_body, organizer_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_open_doping_sample_with_unknown_participant_id(
        self, api, organizer_headers, doping_headers
    ):
        """PRD §2.7: body-referenced participant_id naming non-existent row
        → ERR_REFERENCE_NOT_FOUND."""
        # Build a real event so the URL path resolves.
        event = event_open_for_registration()
        bad_body = open_sample_payload(participant_id=NON_EXISTENT_UUID)
        res = api.open_sample(event["id"], bad_body, doping_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# 2.2 — envelope shape and api_request_id format
# ===========================================================================
class TestResponseEnvelope:
    def test_success_envelope_has_required_meta(self, api, organizer_headers):
        """PRD §2.2: success envelope carries meta.api_request_id starting
        with 'req_' and meta.api_request_timestamp as ISO 8601 UTC with
        three fractional digits."""
        res = api.create_event(create_event_payload(), organizer_headers)
        body = res.json()
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with 'req_'"
        )
        assert isinstance(meta["api_request_timestamp"], str)

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: error envelope's data carries error_id and message."""
        res = api.create_event(create_event_payload(), {})
        body = res.json()
        assert body["response_type"] == "error"
        data = body["data"]
        assert isinstance(data["error_id"], str) and len(data["error_id"]) > 0
        assert isinstance(data["message"], str) and len(data["message"]) > 0


# ===========================================================================
# 2.3 — pagination
# ===========================================================================
class TestPagination:
    def test_list_events_default_pagination(self, api, organizer_headers):
        """PRD §2.3: 'The `limit` parameter specifies the maximum number
        of items to return; if not provided it defaults to 10, with a
        minimum of 1 and a maximum of 100.'"""
        # Create at least 2 events so the result list is non-trivial.
        for _ in range(2):
            api.create_event(create_event_payload(), organizer_headers)
        data, meta = validate_paginated(api.list_events(organizer_headers))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_list_events_limit_one(self, api, organizer_headers):
        """PRD §2.3 explicit limit/offset are honored on list endpoints."""
        for _ in range(3):
            api.create_event(create_event_payload(), organizer_headers)
        data, meta = validate_paginated(
            api.list_events(organizer_headers, params={"limit": 1})
        )
        assert len(data) == 1
        assert meta["limit"] == 1
