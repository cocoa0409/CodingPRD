"""Directory: household and member CRUD, guardian rules, not-found."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    set_clock, create_household, create_adult_member,
    create_household_payload, create_member_payload,
)


class TestHouseholdCreate:
    def test_create_returns_active_and_null_archived_at(self, api):
        """PRD §3.1: "Households start in status ACTIVE."
        PRD §3.1: "while a household is ACTIVE, its archived_at is null."

        Design: Corner/entities/household_create_returns_all_declared_fields
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_household(
            create_household_payload(name="Test Household",
                                     address_line1="1 Main St",
                                     postal_code="10001"),
            TEST_USERS["registrar_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data.get("archived_at") is None


class TestHouseholdGet:
    def test_get_nonexistent_returns_not_found(self, api):
        """PRD §2.8 rung 3: "Every path or body identifier must reference an
        existing resource, validated left-to-right in the URL and then across
        the body; otherwise ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/household_get_nonexistent_returns_not_found
        """
        resp = api.get_household(NON_EXISTENT_UUID,
                                 TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMemberCreateRequired:
    def test_create_without_household_id_rejected(self, api):
        """PRD §2.8 rung 14: "Structural request validity — required fields
        present, types correct, enum values in their declared set, integers
        non-negative where declared, datetimes ISO 8601; otherwise
        ERR_INVALID_REQUEST (HTTP 400)."
        PRD §3.1: "A member is created against a specific `household_id` and carries `full_name`, `date_of_birth`..."

        Design: Corner/entities/member_create_missing_required_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_member(
            {"full_name": "M X", "date_of_birth": "1990-01-01",
             "member_type": "ADULT", "email": "mx@example.com"},
            TEST_USERS["registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_child_without_guardian_rejected(self, api):
        """PRD §3.1: "a CHILD create that leaves guardian_member_ids empty,
        or that lists any non-ADULT guardian, or any guardian from a
        different household, is rejected with ERR_CHILD_MUST_HAVE_GUARDIAN."

        Design: Corner/entities/child_member_without_guardian_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        resp = api.create_member(
            create_member_payload(household_id=h["id"], full_name="K1",
                                  date_of_birth="2020-01-01",
                                  member_type="CHILD",
                                  guardian_member_ids=[],
                                  email=None),
            TEST_USERS["registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CHILD_MUST_HAVE_GUARDIAN)
