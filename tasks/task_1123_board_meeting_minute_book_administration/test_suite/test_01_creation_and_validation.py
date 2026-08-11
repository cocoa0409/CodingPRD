"""Entity creation, required-field, type-constraint, not-found, computed-field,
and system-field immutability claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_committee,
    assert_corporation,
    assert_director,
    create_corporation,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers import SECRETARY


class TestCorporationCreation:
    def test_corporation_creation_applies_defaults_version(self, api):
        """PRD §2.5: "A corporation is created with `version` at 1."

        Design: Corner/entities/corporation_creation_applies_defaults
        """
        resp = api.create_corporation({"name": "Corp E1", "incorporation_state": "DE"}, SECRETARY)
        data = validate_success(resp, expected_status=201)
        assert_corporation(data)
        assert data["version"] == 1, f"expected version 1, got {data['version']}"
        assert data["active_director_count"] == 0
        assert data["current_bylaws_id"] is None

    def test_corporation_creation_uses_default_logical_clock(self, api):
        """PRD §2.4: "At server startup, before any administrative action, the
        clock reads 2026-05-01T00:00:00Z."

        Design: Corner/entities/corporation_creation_applies_defaults
        """
        resp = api.create_corporation({"name": "Corp E1b", "incorporation_state": "DE"}, SECRETARY)
        data = validate_success(resp, expected_status=201)
        # The default logical clock is the creation timestamp source.
        assert data["created_at"].startswith("2026-05-01T00:00:00"), (
            f"expected created_at at the default logical clock, got {data['created_at']}"
        )


class TestDirectorRequiredFields:
    def test_director_missing_email_returns_validation(self, api):
        """PRD §2.11: "**Schema** — required fields are present and well-formed,
        enum fields carry declared members, and date ranges within a body are
        internally consistent."

        Design: Corner/entities/director_missing_required_field_returns_validation
        """
        corp = create_corporation(name="Corp E2")
        resp = api.create_director(
            {
                "corporation_id": corp["id"],
                "full_name": "NoMail",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_director_missing_email_creates_no_row(self, api):
        """PRD §2.11: "A request failing an earlier tier never reaches a later
        one." A schema-failing appointment must not persist a director row.

        Design: Corner/entities/director_missing_required_field_returns_validation
        """
        corp = create_corporation(name="Corp E2b")
        api.create_director(
            {
                "corporation_id": corp["id"],
                "full_name": "NoMail",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
            },
            SECRETARY,
        )
        resp = api.list_directors(SECRETARY, params={"corporation_id": corp["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, f"expected 0 directors, got {meta['total_count']}"
        assert data == []


class TestMeetingEnumValidation:
    def test_meeting_invalid_enum_returns_validation(self, api):
        """PRD §2.11: "required fields are present and well-formed, enum fields
        carry declared members, and date ranges within a body are internally
        consistent."

        Design: Corner/entities/meeting_invalid_enum_returns_validation
        """
        corp = create_corporation(name="Corp E3")
        d1_resp = api.create_director(
            {
                "corporation_id": corp["id"],
                "full_name": "D1",
                "email": "d1@x.com",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
            },
            SECRETARY,
        )
        d1 = get_success_data(d1_resp)
        resp = api.create_meeting(
            {
                "corporation_id": corp["id"],
                "meeting_type": "EMERGENCY",
                "scheduled_start": "2026-06-20T10:00:00Z",
                "duration_minutes": 60,
                "location_or_medium": "Boardroom",
                "chair_director_id": d1["id"],
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFound:
    def test_get_nonexistent_director_returns_not_found(self, api):
        """PRD §2.11: "Existence — every identifier in the path and every
        referenced id in the body resolves to an existing row (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_nonexistent_director_returns_not_found
        """
        resp = api.get_director(NON_EXISTENT_UUID, SECRETARY)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestCommitteeComputedFields:
    def test_committee_computed_member_count_correct(self, api):
        """PRD §3.3: "On a successful add the committee's `active_member_count`
        rises by one, `chair_vacant` is recomputed."

        Design: Corner/entities/committee_computed_member_count_correct
        """
        corp = create_corporation(name="Corp E5")
        d1 = get_success_data(
            api.create_director(
                {
                    "corporation_id": corp["id"],
                    "full_name": "D1",
                    "email": "d1@x.com",
                    "term_start": "2026-01-01T00:00:00Z",
                    "term_end": "2029-01-01T00:00:00Z",
                },
                SECRETARY,
            )
        )
        d2 = get_success_data(
            api.create_director(
                {
                    "corporation_id": corp["id"],
                    "full_name": "D2",
                    "email": "d2@x.com",
                    "term_start": "2026-01-01T00:00:00Z",
                    "term_end": "2029-01-01T00:00:00Z",
                },
                SECRETARY,
            )
        )
        cm = get_success_data(
            api.create_committee(
                {
                    "corporation_id": corp["id"],
                    "name": "Audit",
                    "committee_type": "NOMINATING",
                    "charter_text": "c",
                    "quorum_fixed_count": 1,
                },
                SECRETARY,
            )
        )
        # Memberships added while the committee is in CHARTER_DRAFT (the PRD
        # does not gate the add on committee status; activation is a separate
        # secretary act).
        api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "CHAIR",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2028-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d2["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2028-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        assert_committee(after)
        assert after["active_member_count"] == 2, (
            f"expected 2 active members, got {after['active_member_count']}"
        )
        assert after["chair_vacant"] is False

    def test_committee_membership_add_does_not_activate_charter(self, api):
        """PRD §3.3: "A committee is born in `CHARTER_DRAFT`. Activation, a
        secretary act, ..." — membership adds do not substitute for activation.

        Design: Corner/entities/committee_computed_member_count_correct
        """
        corp = create_corporation(name="Corp E5b")
        d1 = get_success_data(
            api.create_director(
                {
                    "corporation_id": corp["id"],
                    "full_name": "D1",
                    "email": "d1@x.com",
                    "term_start": "2026-01-01T00:00:00Z",
                    "term_end": "2029-01-01T00:00:00Z",
                },
                SECRETARY,
            )
        )
        cm = get_success_data(
            api.create_committee(
                {
                    "corporation_id": corp["id"],
                    "name": "C",
                    "committee_type": "NOMINATING",
                    "charter_text": "c",
                    "quorum_fixed_count": 1,
                },
                SECRETARY,
            )
        )
        api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "CHAIR",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2028-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        assert after["status"] == "CHARTER_DRAFT", (
            f"expected CHARTER_DRAFT, got {after['status']}"
        )


class TestDirectorSystemFields:
    def test_director_system_fields_input_ignored(self, api):
        """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
        assigned at creation." PRD §3.2: "A newly appointed director begins in
        `ACTIVE` status with `independence_status` preset to `PENDING_REVIEW`."

        Design: Corner/entities/director_system_fields_input_ignored
        """
        corp = create_corporation(name="Corp E6")
        forged_id = "11111111-2222-3333-4444-555555555555"
        resp = api.create_director(
            {
                "corporation_id": corp["id"],
                "full_name": "Spoofer",
                "email": "sp@x.com",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
                "id": forged_id,
                "version": 99,
                "status": "RESIGNED",
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"] != forged_id, "client-supplied id must be ignored"
        assert data["version"] == 1, f"client-supplied version must be ignored, got {data['version']}"
        assert data["status"] == "ACTIVE", (
            f"client-supplied lifecycle status must be ignored, got {data['status']}"
        )
