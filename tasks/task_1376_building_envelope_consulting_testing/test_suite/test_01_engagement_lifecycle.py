"""Engagement stand-up, listing, lifecycle endgame, and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_engagement,
    api_client,
    assert_engagement,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_engagement,
    create_engagement_payload,
    get_engagement,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestEngagementCreation:

    def test_engagement_creation_defaults_and_system_fields(self):
        """PRD §3.1: "The new engagement starts in `SETUP` with `risk_score` at
        100, `posture` derived as `OPEN`, `recognized_fees_cents` and
        `invoiced_cents` at 0, `litigation_hold_active` false, and `version` 1."
        PRD §2.10: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/engagement_creation_defaults_and_system_fields
        """
        resp = api_client.create_engagement(
            create_engagement_payload(name="NE", client_name="NC",
                                      fee_cap_cents=1_000_000,
                                      labor_rate_cents_per_hour=12_000),
            P,
        )
        data = validate_success(resp, 201)
        assert_engagement(data)
        assert is_valid_uuid(data["id"])
        assert data["status"] == "SETUP"
        assert data["risk_score"] == 100
        assert data["posture"] == "OPEN"
        assert data["recognized_fees_cents"] == 0
        assert data["invoiced_cents"] == 0
        assert data["version"] == 1
        assert data["litigation_hold_active"] is False
        assert data["fee_headroom_cents"] == 1_000_000

    def test_engagement_not_found_returns_404(self):
        """PRD §2.10: "The server first confirms the existence of the engagement
        named by the path, then the existence of the child resource within that
        engagement, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not resolve."

        Design: Corner/entities/engagement_not_found_returns_404
        """
        resp = api_client.get_engagement(NON_EXISTENT_UUID, P)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_engagement_list_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when omitted it defaults to 10, and it accepts a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses include the fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/engagement_list_pagination_envelope
        """
        create_engagement(name="P1")
        create_engagement(name="P2")
        resp = api_client.list_engagements(
            C, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_engagement_missing_required_field(self):
        """PRD §2.11: "Request-body shape: required fields present, enum fields
        within their declared sets, numeric ranges respected (the fee cap at
        least 1, a slot's end date strictly later than its start date, a
        visit's window end not earlier than its window start, and so on), and
        the anomaly parentage rule that exactly one of its two parent
        references is set — otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "A `Principal` opens a new commission by creating an
        Engagement with a `name`, the `client_name` of the commissioning
        organization, the `fee_cap_cents` hard cap, and the
        `labor_rate_cents_per_hour` billing rate."

        Design: Corner/entities/engagement_missing_required_field
        """
        resp = api_client.create_engagement(
            {"name": "BAD", "client_name": "C",
             "labor_rate_cents_per_hour": 12_000},
            P,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestEngagementLifecycleEndgame:

    def test_engagement_terminal_close_lockdown(self):
        """PRD §3.1: "Activation by a `Principal` moves the engagement from
        `SETUP` to `IN_PROGRESS`; attempting activation from any other state is
        rejected with `ERR_ENGAGEMENT_NOT_IN_SETUP` (HTTP 409)."
        PRD §3.9: "Final closure, again a `Principal` act, moves the engagement
        from `CLOSE_OUT` to `CLOSED`; ... `CLOSED` is terminal."

        Design: Corner/state_machines/engagement_terminal_close_lockdown
        """
        eng = create_active_engagement(name="ET")
        resp = api_client.begin_close_out(eng["id"], P)
        closed_out = validate_success(resp, 200)
        assert closed_out["status"] == "CLOSE_OUT"
        resp = api_client.close_engagement(eng["id"], P)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"

        resp = api_client.activate_engagement(eng["id"], P)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_IN_SETUP)
        assert get_engagement(eng["id"])["status"] == "CLOSED"

    def test_begin_close_out_blocked_by_open_anomalies(self):
        """PRD §3.9: "Beginning close-out, a `Principal` act, moves the
        engagement from `IN_PROGRESS` to `CLOSE_OUT` and enforces three
        clean-slate conditions: no anomaly of the engagement remains in `OPEN`
        or `VERIFIED` (otherwise `ERR_OPEN_ANOMALIES_REMAIN`, HTTP 409)..."
        PRD §3.6: "Dismissal is the `Principal`'s prerogative: it moves the
        anomaly from `OPEN` to `DISMISSED`..."

        Design: Corner/validations/begin_close_out_blocked_by_open_anomalies
        """
        eng = create_active_engagement(name="EBC")
        asm = create_assembly(eng["id"], tag="ABC", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        an = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                            severity="LOW", description="open",
                            survey_id=srv["id"])

        resp = api_client.begin_close_out(eng["id"], P)
        validate_error(resp, ApiErrorId.ERR_OPEN_ANOMALIES_REMAIN)

        resp = api_client.dismiss_anomaly(eng["id"], an["id"], P)
        validate_success(resp, 200)
        resp = api_client.begin_close_out(eng["id"], P)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSE_OUT"
