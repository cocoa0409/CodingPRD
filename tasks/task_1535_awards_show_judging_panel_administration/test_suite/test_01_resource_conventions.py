"""Resource conventions: creation defaults, required fields, payload shape,
reference integrity, pagination, and read-after-write (PRD §2.2-§2.4, §3.1-§3.2).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_material,
    assert_season,
    create_category_payload,
    create_entry_payload,
    create_material_payload,
    create_season_payload,
    is_valid_uuid,
    make_entrant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestCreationDefaults:
    def test_season_create_applies_defaults(self, api):
        """PRD §3.1: "Optional creation parameters include `ceremony_scheduled_at`
        (which must be set before the ceremony can go live), `max_appeals_per_entry`
        (default 2), `refund_policy` (`FLAT_FEE` by default, or `EARLY_BIRD_FREE`),
        `ack_window_hours` (default 72), and `go_live_lead_minutes` (default 30).
        A season is born `DRAFT`, with `active_entries_count` at zero and
        `integrity_flag` `CLEAN`"
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/season_create_defaults_applied
        """
        payload = create_season_payload(include_optional=False, code="GALA-DEF")
        resp = api.create_season(payload, ADMIN)
        season = validate_success(resp, expected_status=201)
        assert_season(season)
        assert season["status"] == "DRAFT"
        assert season["refund_policy"] == "FLAT_FEE"
        assert season["max_appeals_per_entry"] == 2
        assert season["ack_window_hours"] == 72
        assert season["go_live_lead_minutes"] == 30
        assert season["integrity_flag"] == "CLEAN"
        assert season["active_entries_count"] == 0
        assert is_valid_uuid(season["id"])

    def test_entrant_create_requires_contact_email(self, api):
        """PRD §3.2: "`ProgramAdmin` registers each submitting organization as an
        entrant with a `legal_name`, a unique `contact_email`, and a `country_code`
        given as an ISO 3166-1 alpha-2 code."
        PRD §2.5: "Payload well-formedness: required fields present, types correct,
        enum members valid, datetimes parseable, otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/entrant_create_required_fields
        """
        payload = {"legal_name": "No Email Co", "country_code": "US"}
        resp = api.create_entrant(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_entry_material_is_evidence_record_without_version(self, api):
        """PRD §2.4: "Four evidence-style record types — `EntryMaterial`,
        `ConflictDeclaration`, `Score`, and `AuditLog` — carry only `id` and
        `created_at`; both `updated_at` and `version` are absent on these four
        resources."
        PRD §3.2: "Materials are born `PENDING`"

        Design: Corner/entities/entry_material_immutable_no_version
        """
        bundle = fx.setup_submitted_entry("GALA-MAT", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        resp = api.create_material(
            entry["id"],
            create_material_payload(uri="s3://im.pdf", checksum_sha256=f"{99:064x}"),
            make_entrant_headers(entrant["id"]),
        )
        material = validate_success(resp, expected_status=201)
        assert_material(material)
        assert material["status"] == "PENDING"

    def test_active_entries_count_starts_at_zero(self, api):
        """PRD §3.1: "A season is born `DRAFT`, with `active_entries_count` at
        zero and `integrity_flag` `CLEAN`; `active_entries_count` is a derived
        count of the season's entries that are neither `WITHDRAWN` nor
        `DISQUALIFIED`, recomputed on every entry status change."

        Design: Corner/entities/computed_field_active_entries_count_ignores_input
        """
        season = fx.create_season("GALA-CMP")
        fx.create_category(season["id"], code="CAT-CMP")
        fetched = validate_success(api.get_season(season["id"], ADMIN))
        assert fetched["active_entries_count"] == 0

    def test_get_nonexistent_season_returns_404(self, api):
        """PRD §2.5: "Path existence: path resources exist, validated left to
        right (§2.7), otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api.get_season(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_entrant_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0. Unless otherwise
        specified, every list endpoint returns resources sorted by `created_at`
        in ascending order. List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_pagination_envelope
        """
        for i in range(3):
            fx.register_entrant(f"e{i + 1}@x.com", f"Entrant {i + 1}")
        resp = api.list_entrants(ADMIN)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_material_invalid_enum_rejected(self, api):
        """PRD §3.2: "Each material names its `material_type` — one of `VIDEO`,
        `AUDIO`, `PDF`, `IMAGE`, or `URL`"
        PRD §2.5: "Payload well-formedness: required fields present, types correct,
        enum members valid, datetimes parseable, otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/enum_constraint_rejected
        """
        bundle = fx.setup_submitted_entry("GALA-ENUM", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        resp = api.create_material(
            entry["id"],
            create_material_payload(material_type="EXE"),
            make_entrant_headers(entrant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_entry_create_with_unknown_entrant_rejected(self, api):
        """PRD §3.2: "Creation is gated on the parent category being `PUBLISHED`
        and the season being `DRAFT` or `OPEN` (otherwise `ERR_INVALID_STATE`),
        and the referenced entrant and category must exist
        (`ERR_REFERENCE_NOT_FOUND`)."

        Design: Corner/entities/fk_reference_must_exist
        """
        season, category = fx.setup_open_season_with_category("GALA-FK")
        payload = create_entry_payload(
            entrant_id=NON_EXISTENT_UUID, title="Orphan"
        )
        resp = api.create_entry(
            category["id"], payload, make_entrant_headers(NON_EXISTENT_UUID)
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_duplicate_category_code_rejected(self, api):
        """PRD §3.1: "Each carries a `code` unique within its season"
        PRD §2.5: "Uniqueness: `ERR_DUPLICATE` (409)."

        Design: Corner/validations/duplicate_category_code_rejected
        """
        season = fx.create_season("GALA-DUP")
        fx.create_category(season["id"], code="DUP-CAT")
        resp = api.create_category(
            season["id"], create_category_payload(code="DUP-CAT", name="Second"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_malformed_datetime_rejected(self, api):
        """PRD §2.5: "Payload well-formedness: required fields present, types
        correct, enum members valid, datetimes parseable, otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/all_error_codes_triggerable_sample
        """
        payload = create_season_payload(
            include_optional=False, code="BAD", submission_opens_at="not-a-date"
        )
        resp = api.create_season(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_created_season_immediately_readable(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency/immediate_read_after_write
        """
        season = fx.create_season("GALA-IMM")
        fetched = validate_success(api.get_season(season["id"], ADMIN))
        assert_season(fetched)
        assert fetched["id"] == season["id"]
        assert fetched["code"] == "GALA-IMM"
