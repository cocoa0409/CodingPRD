"""Auth context, RBAC denials, ownership scoping, envelope shape, listing
filters, and draw-creation OCC (PRD §2.1, §2.2, §2.8, §2.9, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_participant,
    api_client,
    assert_borrower,
    commit_participant,
    create_borrower,
    create_borrower_payload,
    create_draw,
    create_draw_payload,
    create_facility,
    create_facility_payload,
    create_modification,
    create_payment,
    facility_version,
    get_success_data,
    make_agent_headers,
    make_borrower_headers,
    make_participant_headers,
    settlement_for_participant,
    setup_committed_facility,
    setup_funded_facility,
    solicit_modification,
    validate_error,
    validate_paginated,
    validate_success,
    wire_and_confirm_due,
)

AGENT = make_agent_headers()


class TestAuthContextAndExistence:
    def test_missing_auth_header_returns_400(self):
        """PRD §2.1: "Every request must carry `X-User-ID`, identifying the
        acting party, and `X-User-Role`, naming the capacity in which that party
        acts. A request in which either header is missing or empty is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/missing_auth_header_returns_400
        """
        resp = api_client.create_borrower(
            create_borrower_payload(legal_name="NoHdr"), headers={}
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )
        # Also with a role but no user id.
        resp2 = api_client.create_borrower(
            create_borrower_payload(legal_name="NoHdr2"),
            headers={"X-User-Role": "AgentBank"},
        )
        validate_error(
            resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )

    def test_unknown_draw_id_returns_not_found(self):
        """PRD §2.9: "4. Existence: every id in the path and every `*_id`
        reference in the body resolves to an existing resource — otherwise
        `ERR_NOT_FOUND`."

        Design: Corner/errors/unknown_draw_id_returns_not_found
        """
        resp = api_client.get_draw(NON_EXISTENT_UUID, AGENT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestRbacDenials:
    def test_participant_cannot_create_facility_forbidden(self):
        """PRD §2.1: "Every endpoint declares the roles permitted to call it
        (§4). A request whose role is valid but not permitted on the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/facilities is authorized for AgentBank only.

        Design: Corner/rbac/participant_cannot_create_facility_forbidden
        """
        resp = api_client.create_facility(
            create_facility_payload(NON_EXISTENT_UUID, facility_name="X"),
            make_participant_headers(NON_EXISTENT_UUID),
        )
        # Role check (priority 2) precedes existence (priority 4).
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_borrower_cannot_confirm_wire_forbidden(self):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/funding_settlements/{settlementId}/confirm is
        authorized for AgentBank only.

        Design: Corner/rbac/borrower_cannot_confirm_wire_forbidden
        """
        setup = setup_committed_facility([("CP", 5_000_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]
        draw = create_draw(facility["id"], 1_000_000)
        settlement = settlement_for_participant(participant["id"], draw["id"])
        get_success_data(
            api_client.report_wire(
                settlement["id"], {"amount_cents": settlement["due_cents"]},
                make_participant_headers(participant["id"]),
            )
        )

        resp = api_client.confirm_settlement(
            settlement["id"], {}, make_borrower_headers(setup["borrower"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_agent_cannot_cast_vote_forbidden(self):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/modification_requests/{modificationId}/votes is
        authorized for ParticipantLender only.

        Design: Corner/rbac/agent_cannot_cast_vote_forbidden
        """
        setup = setup_funded_facility(
            [("VP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        mod = create_modification(
            setup["facility"]["id"], setup["borrower"]["id"],
            "COVENANT_WAIVER", {"waiver_text": "T"},
        )
        solicit_modification(mod["id"])

        resp = api_client.cast_consent_vote(mod["id"], {"vote": "APPROVE"}, AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_participant_cannot_wire_others_settlement_forbidden(self):
        """PRD §2.1: "Reporting a wire on another participant's settlement,
        recasting another participant's vote, cancelling another participant's
        transfer, or rescinding another participant's demand is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/participant_cannot_wire_others_settlement_forbidden
        """
        setup = setup_committed_facility([("P1", 3_000_000), ("P2", 2_000_000)])
        facility = setup["facility"]
        p1, p2 = setup["participants"]
        draw = create_draw(facility["id"], 1_000_000)
        s2 = settlement_for_participant(p2["id"], draw["id"])

        resp = api_client.report_wire(
            s2["id"], {"amount_cents": 400_000}, make_participant_headers(p1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    def test_borrower_cannot_pay_for_foreign_facility_forbidden(self):
        """PRD §2.1: "Recording a payment against a facility whose `borrower_id`
        does not equal the caller's `X-User-ID` is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)".

        Design: Corner/rbac/borrower_cannot_pay_for_foreign_facility_forbidden
        """
        b1 = create_borrower(legal_name="B1")
        b2 = create_borrower(legal_name="B2", sector="ENERGY", risk_rating="SPECULATIVE")
        facility = create_facility(b1["id"], total_commitment_cents=5_000_000)
        participant = add_participant(facility["id"], "FP", 5_000_000)
        commit_participant(participant["id"])
        draw = create_draw(facility["id"], 1_000_000)
        wire_and_confirm_due(settlement_for_participant(participant["id"], draw["id"]))

        resp = api_client.create_payment(
            {
                "facility_id": facility["id"],
                "payment_type": "REGULAR",
                "amount_cents": 10_000,
                "value_date": "2026-08-31",
            },
            make_borrower_headers(b2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)


class TestListingAndEnvelope:
    def test_participant_list_filter_by_status(self):
        """PRD §4: "List endpoints paginate per §2.3 and accept the optional
        filters named here: facilities filter by `borrower_id` and `status`;
        participants by `facility_id` and `status`;".

        Design: Corner/endpoints/participant_list_filter_by_status
        """
        setup = setup_committed_facility([("FP1", 3_000_000), ("FP2", 2_000_000)])
        facility = setup["facility"]
        p1, p2 = setup["participants"]
        draw = create_draw(facility["id"], 1_000_000)
        # Only P1 funds: draw stays FUNDING, P1 bubbles to FUNDED, P2 stays
        # COMMITTED.
        wire_and_confirm_due(settlement_for_participant(p1["id"], draw["id"]))

        funded, meta_funded = validate_paginated(
            api_client.list_participants(
                AGENT, params={"facility_id": facility["id"], "status": "FUNDED"}
            )
        )
        assert meta_funded["total_count"] == 1
        assert [p["id"] for p in funded] == [p1["id"]]

        committed, meta_committed = validate_paginated(
            api_client.list_participants(
                AGENT, params={"facility_id": facility["id"], "status": "COMMITTED"}
            )
        )
        assert meta_committed["total_count"] == 1
        assert [p["id"] for p in committed] == [p2["id"]]

    def test_response_envelope_shape_and_immediate_readback(self):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with meta
        carrying `api_request_id` and `api_request_timestamp`, plus
        `response_type` and `data`.
        PRD §2.1: "All read endpoints are shared by `AgentBank`, `Borrower`, and
        `ParticipantLender`."

        Design: Corner/endpoints/response_envelope_shape_and_immediate_readback
        """
        resp = api_client.create_borrower(
            create_borrower_payload(legal_name="Env B", sector="ENERGY"), AGENT
        )
        body = resp.json()
        assert resp.status_code == 201
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"
        created = body["data"]
        assert_borrower(created)

        # Reads are role-agnostic; a ParticipantLender read echoes immediately.
        fetched = validate_success(
            api_client.get_borrower(created["id"], make_participant_headers(created["id"]))
        )
        assert fetched["legal_name"] == "Env B"
        assert fetched["status"] == created["status"]
        assert fetched["version"] == created["version"]


class TestDrawOcc:
    def test_occ_draw_create_stale_version_rejected(self):
        """PRD §2.8: "Creating a draw requires `expected_facility_version`,
        carrying the client's last observed `version` of the target Facility.
        Because every participant commit and every draw creation advances the
        facility's version, a stale value means the client's picture of
        subscription headroom is out of date, and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "These are stale-view rejections, not race arbitration: they
        fire whenever the client's last observed version is behind the entity's
        current version, regardless of timing."

        Design: Corner/cross_cutting_layers/occ_draw_create_stale_version_rejected
        """
        setup = setup_committed_facility([("OP", 10_000_000)])
        facility = setup["facility"]
        # A behind-current expected version is stale; the facility is still
        # COMMITTED so the OCC check (§2.9 priority 8) is the one reached.
        stale_version = facility["version"] - 1

        resp = api_client.create_draw(
            create_draw_payload(
                facility["id"],
                expected_facility_version=stale_version,
                draw_amount_cents=1_000_000,
                accrual_start_date="2026-08-01",
                accrual_end_date="2026-09-01",
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # The current version is accepted.
        validate_success(
            api_client.create_draw(
                create_draw_payload(
                    facility["id"],
                    expected_facility_version=facility_version(facility["id"]),
                    draw_amount_cents=1_000_000,
                    accrual_start_date="2026-08-01",
                    accrual_end_date="2026-09-01",
                ),
                AGENT,
            ),
            expected_status=201,
        )
