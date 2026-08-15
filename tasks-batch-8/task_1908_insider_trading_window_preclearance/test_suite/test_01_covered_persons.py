"""Covered person onboarding, system defaults, pagination, and currency flags."""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
    admin_headers,
    api_client,
    assert_covered_person,
    complete_attestation_for,
    create_covered_person_payload,
    create_person,
    get_person,
    set_logical_clock,
)
from test_helpers import ApiErrorId


class TestCoveredPersonOnboarding:
    def test_create_covered_person_without_designation_rejected(self, api):
        """PRD §3.1: "A `LegalAdmin` onboards one by supplying a `full_name`, a work
        `email` that must be unique across all covered persons, a `designation` of
        `SECTION_16_OFFICER`, `DIRECTOR`, `EMPLOYEE`, or `CONSULTANT`, and a `department`."
        PRD §2.9: "`ERR_INVALID_REQUEST` (400) covers a missing required field or
        malformed value such as a bad datetime or a non-positive quantity".

        Design: Corner/entities/create_covered_person_missing_required_designation
        """
        payload = create_covered_person_payload(
            full_name="No Desig", email="nodesig@x.com", department="Ops"
        )
        del payload["designation"]
        resp = api.create_covered_person(payload, admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(api.list_covered_persons(admin_headers()))
        assert meta["total_count"] == 0, "rejected creation must not persist a person"

    def test_covered_person_created_with_system_defaults(self, api):
        """PRD §3.1: "A freshly created person starts with `status` `ACTIVE`, both
        currency flags false, and `version` 1."

        Design: Corner/entities/covered_person_creation_applies_system_defaults
        """
        resp = api.create_covered_person(
            create_covered_person_payload(
                full_name="Fresh Person",
                email="fresh@x.com",
                designation="CONSULTANT",
                department="Advisory",
            ),
            admin_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_covered_person(data)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["policy_ack_current"] is False
        assert data["training_current"] is False
        assert data["compliance_hold"] is False
        assert data["suspended_until"] is None

    def test_covered_person_invalid_designation_rejected(self, api):
        """PRD §3.1: "a `designation` of `SECTION_16_OFFICER`, `DIRECTOR`, `EMPLOYEE`,
        or `CONSULTANT`". PRD §2.9: "`ERR_INVALID_ENUM` (400) covers an enum field
        carrying a value outside its declared set."

        Design: Corner/entities/covered_person_invalid_enum_rejected
        """
        resp = api.create_covered_person(
            create_covered_person_payload(
                full_name="Bad Enum",
                email="badenum@x.com",
                designation="CEO",
                department="Exec",
            ),
            admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_get_unknown_covered_person_not_found(self, api):
        """PRD §2.9: "path-template resource ids are validated left to right, then
        foreign keys referenced in the request body (`covered_person_id`,
        `exception_id`, `trade_confirmation_id`) are validated; a missing resource
        yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_nonexistent_person_not_found
        """
        resp = api.get_covered_person(NON_EXISTENT_UUID, admin_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCoveredPersonListing:
    def test_list_covered_persons_paginates_with_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter sets how many items are skipped and
        defaults to 0." PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_covered_persons_pagination_envelope
        """
        for i in range(3):
            create_person(f"Pg {i}", f"pg{i}@x.com")

        data, meta = validate_paginated(
            api.list_covered_persons(admin_headers(), params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"limit=2 should return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_covered_persons(admin_headers(), params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1, f"offset=2 over 3 rows should return 1 row"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestCurrencyFlags:
    def test_currency_flags_flip_after_completing_attestations(self, api):
        """PRD §3.1: "`policy_ack_current` is true exactly when the person has a
        `COMPLETED` attestation of kind `POLICY_ACK` whose `completed_at` falls within
        the trailing 365 days of now. `training_current` is true exactly when the
        person has a `COMPLETED` attestation of kind `ANNUAL_TRAINING` within the same
        trailing 365-day window **and** no `OVERDUE` `ANNUAL_TRAINING` attestation
        exists for them — an overdue training assignment poisons training currency
        even if an older completion would otherwise still count."

        Design: Corner/entities/computed_currency_flags_after_attestation_completion
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        person = create_person("Compute Me", "compute@x.com")
        complete_attestation_for(person, "POLICY_ACK")
        complete_attestation_for(person, "ANNUAL_TRAINING")

        fresh = get_person(person["id"])
        assert fresh["policy_ack_current"] is True
        assert fresh["training_current"] is True

    def test_created_person_immediately_readable_with_identical_state(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.1: "A freshly created person starts with `status` `ACTIVE`, both
        currency flags false, and `version` 1."

        Design: Corner/consistency_model/create_then_get_returns_identical_state
        """
        created = validate_success(
            api.create_covered_person(
                create_covered_person_payload(
                    full_name="Consistent C",
                    email="consistent@x.com",
                    designation="EMPLOYEE",
                    department="Ops",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        fetched = validate_success(api.get_covered_person(created["id"], admin_headers()))
        assert created["status"] == fetched["status"] == "ACTIVE"
        assert fetched["version"] == 1
        assert fetched["email"] == "consistent@x.com"
