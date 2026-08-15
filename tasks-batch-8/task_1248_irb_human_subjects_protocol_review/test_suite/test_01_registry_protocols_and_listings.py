"""Registry onboarding, protocol creation shape, listings, and 404 handling.

Covers PRD §2.1 (roles/identity), §2.3 (pagination), §2.4 (logical clock),
§2.6 (nested resolution), §2.9 (request-shape validation), §3.1 and §3.2.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_timestamp_equals,
    create_protocol_payload,
    get_success_data,
    make_chair_headers,
    make_pi_headers,
    make_reviewer_headers,
    register_investigator,
    register_member,
    schedule_meeting,
    upload_consent,
    create_draft_protocol,
    submit_protocol_ok,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProtocolCreationValidation:
    def test_protocol_create_missing_title_returns_400(self, api, coordinator_headers):
        """PRD §3.2: "A `PrincipalInvestigator` drafts a protocol by supplying
        a `title`, a `claimed_review_level` of `EXEMPT`, `EXPEDITED`, or
        `FULL_BOARD`, a `risk_level` of `MINIMAL` or `GREATER_THAN_MINIMAL`".
        PRD §2.9: "Request shape — required fields present, values well-typed,
        enum values valid (`ERR_VALIDATION`)."

        Design: Corner/entities/protocol_create_missing_title_returns_400
        """
        inv = register_investigator()
        payload = {"claimed_review_level": "EXEMPT", "risk_level": "MINIMAL"}
        resp = api.create_protocol(payload, make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        rows, meta = validate_paginated(
            api.list_protocols(coordinator_headers, params={"pi_id": inv["id"]})
        )
        assert rows == [], f"Failed creation must not persist a row, got {rows}"
        assert meta["total_count"] == 0

    def test_protocol_create_invalid_review_level_rejected(self, api):
        """PRD §3.2: "a `claimed_review_level` of `EXEMPT`, `EXPEDITED`, or
        `FULL_BOARD`". PRD §2.9: "Request shape — required fields present,
        values well-typed, enum values valid (`ERR_VALIDATION`)."

        Design: Corner/entities/protocol_create_invalid_review_level_rejected
        """
        inv = register_investigator()
        payload = create_protocol_payload(claimed_review_level="LIGHTSPEED")
        resp = api.create_protocol(payload, make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestConsentDocumentSequencing:
    def test_consent_document_version_seq_increments_per_protocol(self, api):
        """PRD §3.3: "The server assigns each upload a `version_seq` equal to
        one more than the highest existing sequence number on that protocol,
        and the document begins life in `SUBMITTED`."

        Design: Corner/entities/consent_document_version_seq_increments_per_protocol
        """
        inv = register_investigator()
        proto = create_draft_protocol(inv["id"], title="Seq Study")
        cd1 = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/a.pdf")
        cd2 = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/b.pdf")

        assert cd1["version_seq"] == 1, f"First upload must be version_seq 1, got {cd1['version_seq']}"
        assert cd2["version_seq"] == 2, f"Second upload must be version_seq 2, got {cd2['version_seq']}"
        assert cd1["status"] == "SUBMITTED"
        assert cd2["status"] == "SUBMITTED"


class TestProtocolListing:
    def test_list_protocols_filtered_by_pi_with_pagination_envelope(self, api, coordinator_headers):
        """PRD §3.2: "The protocol collection supports listing with optional
        `pi_id` and `status` filters." PRD §2.3: "Every paginated list response
        carries `limit`, `offset`, `total_count`, and `has_more` in the `meta`
        object of the envelope."

        Design: Corner/entities/list_protocols_filtered_by_pi_with_pagination_envelope
        """
        inv_a = register_investigator()
        inv_b = register_investigator()
        create_draft_protocol(inv_a["id"], title="A1", claimed_review_level="EXEMPT")
        create_draft_protocol(inv_a["id"], title="A2", claimed_review_level="EXEMPT")
        create_draft_protocol(inv_b["id"], title="B1", claimed_review_level="EXEMPT")

        page1, meta1 = validate_paginated(
            api.list_protocols(
                coordinator_headers,
                params={"pi_id": inv_a["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1, f"limit=1 must return exactly 1 row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["pi_id"] == inv_a["id"]

        page2, meta2 = validate_paginated(
            api.list_protocols(
                coordinator_headers,
                params={"pi_id": inv_a["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["pi_id"] == inv_a["id"]
        assert page2[0]["id"] != page1[0]["id"], "Second page must return the other row"
        assert all(row["pi_id"] != inv_b["id"] for row in page1 + page2)


class TestNotFoundErrors:
    def test_get_missing_top_level_entities_returns_404(self, api, admin_headers):
        """PRD §2.6: "The server resolves each path identifier in sequence and
        rejects the request at the first identifier that fails to resolve,
        returning the 404 error that names the missing resource kind". PRD
        §2.6 names "`ERR_INVESTIGATOR_NOT_FOUND` for an investigator,
        `ERR_MEMBER_NOT_FOUND` for a member, `ERR_PROTOCOL_NOT_FOUND` for a
        protocol, `ERR_CONSENT_DOC_NOT_FOUND` for a consent document" and
        "`ERR_MEETING_NOT_FOUND` for a board meeting" and
        "`ERR_RELIANCE_NOT_FOUND` for a reliance agreement".

        Design: Corner/entities/get_missing_top_level_entities_returns_404
        """
        register_investigator()  # anchor row
        expectations = [
            (api.get_investigator(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_INVESTIGATOR_NOT_FOUND),
            (api.get_member(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api.get_protocol(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_PROTOCOL_NOT_FOUND),
            (api.get_consent_document(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CONSENT_DOC_NOT_FOUND),
            (api.get_board_meeting(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_MEETING_NOT_FOUND),
            (api.get_reliance_agreement(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_RELIANCE_NOT_FOUND),
        ]
        for resp, error_id in expectations:
            validate_error(resp, error_id)

    def test_get_missing_review_workflow_entities_returns_404(self, api, admin_headers):
        """PRD §2.6 names "`ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_DECLARATION_NOT_FOUND` for a conflict declaration,
        `ERR_MEETING_NOT_FOUND` for a board meeting, `ERR_AGENDA_ITEM_NOT_FOUND`
        for an agenda item, `ERR_MODIFICATION_NOT_FOUND` for a modification
        request, `ERR_CR_NOT_FOUND` for a continuing review, `ERR_AE_NOT_FOUND`
        for an adverse-event report, `ERR_CASE_NOT_FOUND` for a non-compliance
        case".

        Design: Corner/entities/get_missing_review_workflow_entities_returns_404
        """
        register_investigator()  # anchor row
        expectations = [
            (api.get_review_assignment(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_conflict_declaration(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_DECLARATION_NOT_FOUND),
            (api.get_agenda_item(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_AGENDA_ITEM_NOT_FOUND),
            (api.get_modification(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_MODIFICATION_NOT_FOUND),
            (api.get_continuing_review(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CR_NOT_FOUND),
            (api.get_adverse_event(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_AE_NOT_FOUND),
            (api.get_non_compliance_case(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CASE_NOT_FOUND),
        ]
        for resp, error_id in expectations:
            validate_error(resp, error_id)


class TestRoleEnforcement:
    def test_reviewer_cannot_create_board_meeting(self, api):
        """PRD §2.1: "Attempting an operation outside the caller's designated
        role is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists
        `POST /irb/board-meetings` under IrbCoordinator only.

        Design: Corner/rbac/reviewer_cannot_create_board_meeting
        """
        member = register_member("SCIENTIST")
        resp = api.create_board_meeting(
            {
                "room_id": "R-RB",
                "scheduled_at": "2026-06-01T10:00:00Z",
                "duration_minutes": 60,
            },
            make_reviewer_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_pi_cannot_submit_others_protocol(self, api, coordinator_headers):
        """PRD §3.2: "Ownership comes first — a caller whose `X-User-ID` does
        not match the protocol's `pi_id` is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/pi_cannot_submit_others_protocol
        """
        inv_a = register_investigator()
        inv_b = register_investigator()
        proto = create_draft_protocol(inv_a["id"], title="Owned by A")
        upload_consent(proto["id"], inv_a["id"])

        resp = api.submit_protocol(proto["id"], make_pi_headers(inv_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        current = get_success_data(api.get_protocol(proto["id"], coordinator_headers))
        assert current["status"] == "DRAFT", (
            f"Rejected submit must not move the protocol, got {current['status']}"
        )

    def test_non_chair_member_cannot_convene(self, api):
        """PRD §2.1: "that member's `is_chair` flag must be true. A member
        whose `is_chair` is false acting in the `IrbChair` capacity is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/non_chair_member_cannot_convene
        """
        plain = register_member("SCIENTIST")
        meeting = schedule_meeting(room_id="R-NC")
        resp = api.convene_meeting(
            meeting["id"],
            {"attendee_member_ids": [plain["id"]]},
            make_chair_headers(plain["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        register_investigator()  # anchor row
        resp = api._request("GET", f"/irb/protocols/{NON_EXISTENT_UUID}", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestLogicalClock:
    def test_clock_set_echoes_time_and_reports_zero_sweeps(self, api, admin_headers):
        """PRD §2.4: "The capability's response reports the new clock reading
        as `current_utc` together with three sweep counters:
        `lapsed_continuing_reviews`, `failed_quorum_meetings`, and
        `expired_assignments`."

        Design: Corner/endpoints/clock_set_echoes_time_and_reports_zero_sweeps
        """
        register_investigator()  # anchor row; no CRs, meetings, or offers
        resp = api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, admin_headers)
        data = validate_success(resp)
        # PRD pins the echoed instant, not its string rendering.
        assert_timestamp_equals(data["current_utc"], "2026-05-10T00:00:00Z")
        assert data["lapsed_continuing_reviews"] == 0
        assert data["failed_quorum_meetings"] == 0
        assert data["expired_assignments"] == 0
