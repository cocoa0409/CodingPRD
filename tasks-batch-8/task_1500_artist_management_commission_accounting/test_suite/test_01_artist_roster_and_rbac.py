"""Artist roster basics, auth validation order, and role-based access control."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_team_member,
    assert_artist,
    create_agreement_payload,
    create_artist_payload,
    create_expense_payload,
    create_opportunity_payload,
    generate_statement_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_agent_headers,
    make_artist_headers,
    make_publicist_headers,
    report_event,
    setup_artist_team,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestArtistCreation:
    def test_artist_create_applies_defaults_and_system_fields(self, api):
        """PRD: "A `FirmAdmin` onboards an artist by supplying `stage_name`,
        `legal_name`, and `primary_genre`; `home_currency` is optional and defaults
        to `USD`. The artist is born `ACTIVE` with `version` 1, and
        `current_agreement_id` stays null until an agreement activates."
        PRD: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/artist_create_applies_defaults_and_system_fields
        """
        resp = api.create_artist(
            create_artist_payload(stage_name="Solo Act", legal_name="Solo Act LLC",
                                  primary_genre="jazz"),
            ADMIN,
        )
        artist = validate_success(resp, 201)
        assert_artist(artist)
        assert artist["status"] == "ACTIVE", "A new artist is born ACTIVE"
        assert artist["home_currency"] == "USD", "home_currency defaults to USD"
        assert artist["version"] == 1, "A new artist is born with version 1"
        assert artist["current_agreement_id"] is None
        assert artist["unrecouped_advance_balance_cents"] == 0
        assert artist["lifetime_gross_cents"] == 0
        assert artist["lifetime_commission_cents"] == 0
        assert artist["lifetime_disbursed_cents"] == 0
        assert is_valid_uuid(artist["id"]), "id is a bare UUID"
        assert is_iso8601_timestamp(artist["created_at"])

        fetched = validate_success(api.get_artist(artist["id"], ADMIN))
        assert fetched["status"] == "ACTIVE"
        assert fetched["home_currency"] == "USD"
        assert fetched["version"] == 1


class TestAuthValidation:
    def test_request_missing_auth_headers_rejected(self, api):
        """PRD: "A request missing either header, or carrying an empty value, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`"

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.create_artist(
            create_artist_payload(stage_name="NoHdr", legal_name="NoHdr LLC"),
            {},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_missing_required_field_returns_invalid_request(self, api):
        """PRD: "Request-body shape — required fields present, types valid, enum
        values in range, amounts positive where required, window end later than
        start (`ERR_INVALID_REQUEST`)."
        PRD: "A `FirmAdmin` onboards an artist by supplying `stage_name`,
        `legal_name`, and `primary_genre`"

        Design: Corner/validations/missing_required_field_returns_invalid_request
        """
        payload = create_artist_payload(stage_name="NoLegal", primary_genre="pop")
        del payload["legal_name"]
        resp = api.create_artist(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api.list_artists(ADMIN))
        assert meta["total_count"] == 0, "No artist may be persisted by the rejected create"

    def test_body_foreign_key_unresolvable_returns_invalid_reference(self, api):
        """PRD: "Body references — body-supplied foreign keys such as `artist_id`,
        `agreement_id`, `statement_id`, `linked_engagement_id`, `parent_event_id`,
        `opportunity_id`, `source_opportunity_id`, and `engagement_id` resolve to
        existing resources (`ERR_INVALID_REFERENCE`)."

        Design: Corner/validations/body_foreign_key_unresolvable_returns_invalid_reference
        """
        artist = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Ref Act", legal_name="Ref Act LLC"),
            ADMIN))
        payload = create_agreement_payload(
            NON_EXISTENT_UUID, artist["version"],
            term_start_date="2026-01-01", term_end_date="2027-12-31",
        )
        resp = api.create_agreement(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)
        after = validate_success(api.get_artist(artist["id"], ADMIN))
        assert after["version"] == artist["version"], (
            "The real artist is untouched by the rejected create"
        )

    def test_get_missing_agreement_returns_not_found(self, api):
        """PRD: "Path existence — every path identifier resolves to an existing
        resource (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_missing_agreement_returns_not_found
        """
        resp = api.get_agreement(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestArchivalAndTeamStatus:
    def test_artist_archive_cascades_team_end(self, api):
        """PRD: "Archiving also cascades downward — every team member of the artist
        in `ACTIVE` or `SUSPENDED` status is moved to `ENDED`."
        PRD: "Team-backed callers must additionally be in `ACTIVE` status: a
        `SUSPENDED` or `ENDED` member may not act, and attempts are rejected with
        `ERR_TEAM_MEMBER_INACTIVE`."

        Design: Corner/state_machines/artist_archive_cascades_team_end
        """
        artist = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Arch Act", legal_name="Arch Act LLC"),
            ADMIN))
        member = add_team_member(artist["id"], "AGENT", "Agent Ar")
        validate_success(api.patch_artist(artist["id"], {"status": "ARCHIVED"}, ADMIN))

        ended = validate_success(api.get_team_member(member["id"], ADMIN))
        assert ended["status"] == "ENDED", "Archive cascade ends ACTIVE team members"

        resp = api.create_expense(
            create_expense_payload(artist["id"], category="TRAVEL",
                                   amount_cents=5000, description="Taxi"),
            make_agent_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEAM_MEMBER_INACTIVE)

    def test_suspended_team_member_cannot_act(self, api):
        """PRD: "Team-backed callers must additionally be in `ACTIVE` status: a
        `SUSPENDED` or `ENDED` member may not act, and attempts are rejected with
        `ERR_TEAM_MEMBER_INACTIVE`."

        Design: Corner/validations/suspended_team_member_cannot_act
        """
        sc = setup_artist_team(stage_name="Susp Act")
        event = report_event(sc, gross_amount_cents=100000,
                             recognition_date="2026-03-10", source_name="PSu")
        get_success_data(api.suspend_team_member(sc["bm"]["id"], ADMIN))

        resp = api.verify_income_event(event["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_TEAM_MEMBER_INACTIVE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "REPORTED", "The rejected verify leaves the event untouched"

    def test_archived_artist_blocks_new_business_writes(self, api):
        """PRD: "Archiving is a hard stop for new business: for an `ARCHIVED`
        artist, the system rejects new income events, expenses, opportunities,
        engagements, options, agreements, advances, and statement generation with
        `ERR_ARTIST_ARCHIVED`."

        Design: Corner/validations/archived_artist_blocks_new_business_writes
        """
        artist = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Cold Act", legal_name="Cold Act LLC"),
            ADMIN))
        validate_success(api.patch_artist(artist["id"], {"status": "ARCHIVED"}, ADMIN))
        # Team assignment is not on the archived-artist blocked list, so the
        # new member stays ACTIVE and the write below reaches the archive gate.
        member = add_team_member(artist["id"], "AGENT", "Agent Cd")

        resp = api.create_opportunity(
            create_opportunity_payload(artist["id"], fit_score=50),
            make_agent_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ARTIST_ARCHIVED)
        _data, meta = validate_paginated(
            api.list_opportunities(ADMIN, params={"artist_id": artist["id"]}))
        assert meta["total_count"] == 0, "No opportunity may be persisted"


class TestRbacMatrix:
    def test_agent_cannot_verify_income(self, api):
        """PRD: "a request whose role is not in the endpoint's declared role list
        is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD endpoint table: verify is authorized for BusinessManager only.

        Design: Corner/rbac/agent_cannot_verify_income
        """
        sc = setup_artist_team(stage_name="Rbac Act")
        event = report_event(sc, gross_amount_cents=100000,
                             recognition_date="2026-03-10", source_name="PRb")

        resp = api.verify_income_event(event["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        after = validate_success(api.get_income_event(event["id"], ADMIN))
        assert after["status"] == "REPORTED"

    def test_publicist_can_file_expense_but_not_generate_statement(self, api):
        """PRD: "Any member of the artist's working team — `Agent`,
        `BusinessManager`, or `Publicist` — may file a reimbursable expense"
        PRD endpoint table: statement generation is authorized for
        BusinessManager only, and "a request whose role is not in the endpoint's
        declared role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/publicist_can_file_expense_but_not_generate_statement
        """
        artist = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Pub Act", legal_name="Pub Act LLC"),
            ADMIN))
        publicist = add_team_member(artist["id"], "PUBLICIST", "Pub List")
        pub_headers = make_publicist_headers(publicist["id"])

        expense = validate_success(api.create_expense(
            create_expense_payload(artist["id"], category="MARKETING",
                                   amount_cents=8000, description="PR campaign"),
            pub_headers), 201)
        assert expense["status"] == "PENDING_APPROVAL"

        resp = api.generate_statement(
            generate_statement_payload(artist["id"], period_start_date="2026-06-01",
                                       period_end_date="2026-06-30", basis="ACCRUAL"),
            pub_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_cross_artist_scope_denied_for_team_member(self, api):
        """PRD: "ownership checks on any artist-scoped resource compare the
        resource's artist chain against that `artist_id`, and a mismatch is
        rejected with `ERR_ARTIST_ACCESS_DENIED`."

        Design: Corner/rbac/cross_artist_scope_denied_for_team_member
        """
        artist_a = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Act A", legal_name="Act A LLC"), ADMIN))
        artist_b = get_success_data(api.create_artist(
            create_artist_payload(stage_name="Act B", legal_name="Act B LLC",
                                  primary_genre="rock"), ADMIN))
        member_b = add_team_member(artist_b["id"], "AGENT", "Agent B-only")

        resp = api.get_artist(artist_a["id"], make_agent_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_ARTIST_ACCESS_DENIED)

    def test_auditor_read_only_plus_audit_actions(self, api):
        """PRD: "a request whose role is not in the endpoint's declared role list
        is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD endpoint table: artist creation is authorized for FirmAdmin only.

        Design: Corner/rbac/auditor_read_only_plus_audit_actions
        """
        resp = api.create_artist(
            create_artist_payload(stage_name="Nope Act", legal_name="Nope Act LLC"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        _data, meta = validate_paginated(api.list_artists(ADMIN))
        assert meta["total_count"] == 0, "No artist may be persisted"
