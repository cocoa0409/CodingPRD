"""Registry creation defaults, field-format errors, reference resolution,
uniqueness, and list pagination (PRD §2.2, §2.3, §2.7, §3.1–§3.4)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp, NON_EXISTENT_UUID, TEST_USERS,
    create_user_payload, create_instrument_payload,
    create_training_record_payload, create_grant_payload,
    create_publication_payload,
    make_researcher_headers, assert_user, assert_instrument, assert_grant,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestUserCreation:
    def test_user_create_defaults_and_envelope(self, api):
        """PRD §3.1: "New users start `ACTIVE`." and "`is_pi` marks a principal
        investigator who may own grants and defaults to false."
        PRD §2.4: "On fresh startup, before any explicit adjustment, the logical
        clock reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/user_create_defaults_and_envelope
        """
        res = api.create_user(
            {"full_name": "Rita Rao", "email": "r1@uni.edu", "affiliation": "INTERNAL"},
            ADMIN,
        )
        assert res.status_code == 201, res.text
        user = validate_success(res, 201)
        assert_user(user)
        assert user["status"] == "ACTIVE", f"new user must start ACTIVE: {user}"
        assert user["is_pi"] is False, f"is_pi must default to false: {user}"
        assert user["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must be minted from the logical clock default: {user}"
        )
        body = res.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)

    def test_user_create_without_email_yields_400(self, api):
        """PRD §2.9: "Field formats (`ERR_INVALID_REQUEST`): required fields
        present, enums valid, `end_at` after `start_at`, positive amounts where
        required, email format; unknown or system/computed-sourced fields in
        request bodies are rejected here as malformed."
        PRD §3.1: "The `email` must be unique across users and non-empty."

        Design: Corner/entities/user_create_without_email_yields_400
        """
        res = api.create_user(
            {"full_name": "No Email", "affiliation": "INTERNAL"}, ADMIN
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
        _, meta = validate_paginated(api.list_users(ADMIN))
        assert meta["total_count"] == 0, "no user may be persisted after a 400"

    def test_user_create_with_bad_enum_yields_400(self, api):
        """PRD §2.9: "Field formats (`ERR_INVALID_REQUEST`): required fields
        present, enums valid, `end_at` after `start_at`, positive amounts where
        required, email format; unknown or system/computed-sourced fields in
        request bodies are rejected here as malformed."

        Design: Corner/entities/user_create_with_bad_enum_yields_400
        """
        res = api.create_user(
            {"full_name": "Bad Enum", "email": "be@uni.edu", "affiliation": "OTHER"},
            ADMIN,
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_user_get_unknown_id_yields_404(self, api):
        """PRD §2.7: "Path identifiers are resolved first, in path order; the
        first identifier that does not resolve to an existing resource is
        rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/user_get_unknown_id_yields_404
        """
        validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL"}, ADMIN),
            201,
        )
        res = api.get_user(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestInstrumentDefaults:
    def test_instrument_create_applies_policy_defaults(self, api):
        """PRD §3.2: "A `FacilityAdmin` registers each instrument with `name`,
        `model`, `location`, and a policy bundle: `requires_training` (default
        true), `booking_buffer_minutes` (default 0, never negative),
        `min_booking_minutes` (strictly positive), `max_booking_minutes` (at
        least the minimum), `cancellation_free_notice_hours` (never negative),
        `late_cancel_penalty_pct`, and `no_show_penalty_pct` (each a fraction
        between 0 and 1 inclusive)." and "New instruments start `AVAILABLE`."

        Design: Corner/entities/instrument_create_applies_policy_defaults
        """
        res = api.create_instrument(
            {
                "name": "Confocal-1", "model": "Zeiss LSM", "location": "Lab 2",
                "min_booking_minutes": 30, "max_booking_minutes": 240,
                "cancellation_free_notice_hours": 12,
                "late_cancel_penalty_pct": 0.25, "no_show_penalty_pct": 1.0,
            },
            ADMIN,
        )
        instrument = validate_success(res, 201)
        assert_instrument(instrument)
        assert instrument["requires_training"] is True, "default true"
        assert instrument["booking_buffer_minutes"] == 0, "default 0"
        assert instrument["status"] == "AVAILABLE"


class TestGrantAndTrainingCreation:
    def test_grant_computed_fields_zero_at_create(self, api):
        """PRD §2.10: "`budget_encumbered_cents` is the sum of
        `encumbered_cents` over the grant's bookings in `APPROVED` or
        `IN_PROGRESS` status. `budget_used_cents` is the sum of
        `net_amount_cents` over the grant's recharge entries of kind `USAGE`
        or `PENALTY` whose status is `PENDING`, `BILLED`, `PAID`, or
        `DISPUTED`" and "`budget_available_cents` is `budget_total_cents`
        minus the encumbered and used sums".

        Design: Corner/entities/grant_computed_fields_zero_at_create
        """
        u1 = validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL", "is_pi": True}, ADMIN),
            201,
        )
        grant = validate_success(
            api.create_grant(
                create_grant_payload(u1["id"], budget_total_cents=100000),
                FINANCE,
            ),
            201,
        )
        assert_grant(grant)
        assert grant["budget_encumbered_cents"] == 0
        assert grant["budget_used_cents"] == 0
        assert grant["budget_available_cents"] == 100000
        assert grant["status"] == "ACTIVE"

    def test_grant_duplicate_code(self, api):
        """PRD §2.9: "Uniqueness (`ERR_UNIQUE_CONSTRAINT`): user `email`,
        `grant_code`, `fiscal_year`, the batch (`period_year`, `period_month`)
        pair, one `EFFECTIVE` rate set per fiscal year, one non-`REVOKED`
        `TrainingRecord` per (user, instrument), and rate-set lines unique per
        instrument."

        Design: Corner/errors/grant_duplicate_code
        """
        u1 = validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL", "is_pi": True}, ADMIN),
            201,
        )
        validate_success(
            api.create_grant(
                create_grant_payload(u1["id"], grant_code="NIH-1", title="First"),
                FINANCE,
            ),
            201,
        )
        res = api.create_grant(
            create_grant_payload(
                u1["id"], grant_code="NIH-1", title="Second",
                budget_total_cents=5000,
            ),
            FINANCE,
        )
        validate_error(res, "ERR_UNIQUE_CONSTRAINT", expected_status=409)

    def test_training_record_unique_pair(self, api):
        """PRD §3.3: "At most one record with status `ENROLLED`, `CERTIFIED`,
        or `EXPIRED` may exist per (user, instrument) pair; `REVOKED` records
        do not block a fresh enrollment."

        Design: Corner/entities/training_record_unique_pair
        """
        u1 = validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL"}, ADMIN),
            201,
        )
        i1 = validate_success(
            api.create_instrument(create_instrument_payload(), ADMIN), 201
        )
        validate_success(
            api.create_training_record(
                create_training_record_payload(u1["id"], i1["id"]), STAFF
            ),
            201,
        )
        res = api.create_training_record(
            create_training_record_payload(u1["id"], i1["id"]), STAFF
        )
        validate_error(res, "ERR_UNIQUE_CONSTRAINT", expected_status=409)


class TestPublicationReferences:
    def test_publication_with_unknown_instrument_yields_404(self, api):
        """PRD §2.7: "Body foreign-key references — `instrument_id`,
        `grant_id`, `user_id`, `booking_id`, `application_id`,
        `maintenance_contract_id`, and every element of an `instrument_ids`
        array — must each reference an existing resource; any failure is
        likewise `ERR_NOT_FOUND`."

        Design: Corner/entities/publication_with_unknown_instrument_yields_404
        """
        u1 = validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL"}, ADMIN),
            201,
        )
        res = api.create_publication(
            create_publication_payload(
                u1["id"], [NON_EXISTENT_UUID], title="Paper",
            ),
            make_researcher_headers(u1["id"]),
        )
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestListPagination:
    def test_list_pagination_defaults_and_offsets(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items returned; when omitted it defaults to 10, and it is clamped to a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0." and "List responses carry
        `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
        object of the envelope."

        Design: Corner/endpoints/list_pagination_defaults_and_offsets
        """
        for n in range(1, 12):
            validate_success(
                api.create_user(
                    {"full_name": f"U{n:02d}", "email": f"u{n:02d}@uni.edu",
                     "affiliation": "INTERNAL"}, ADMIN),
                201,
            )
        data, meta = validate_paginated(api.list_users(ADMIN))
        assert len(data) == 10, f"default page must hold 10 rows, got {len(data)}"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_users(ADMIN, params={"limit": 10, "offset": 10})
        )
        assert len(data2) == 1, f"offset=10 must yield the last row: {data2!r}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11
