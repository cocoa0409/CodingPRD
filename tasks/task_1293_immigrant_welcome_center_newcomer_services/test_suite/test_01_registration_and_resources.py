"""Registration, base resources, and list pagination (PRD §2.3, §2.5, §3.1)."""

from test_helpers import (
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId,
    create_client_payload, create_staff_payload, create_room_payload,
    create_case_payload,
    register_client, create_staff_member, open_case, staff_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


class TestClientRegistration:
    def test_client_creation_applies_defaults_and_system_fields(self):
        """PRD §3.1: "`household_size` (persons in the household including the
        client, at least 1) defaults to 1, while `country_of_origin` and
        `arrival_date` — the date the newcomer arrived in the municipality — may
        be left null. A new client's `status` is `REGISTERED` and its `reportable`
        flag is false."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."

        Design: Corner/entities/client_creation_applies_defaults_and_system_fields
        """
        resp = api_client.create_client(
            {"full_name": "Solo Client", "preferred_language": "es",
             "date_of_birth": "1999-01-01"}, INTAKE)
        data = validate_success(resp, expected_status=201)
        assert data["household_size"] == 1, "omitted household_size must default to 1"
        assert data["status"] == "REGISTERED"
        assert data["reportable"] is False
        assert is_valid_uuid(str(data["id"])), "id must be a server-minted UUID"
        # No case opened, so the client remains REGISTERED (auto-ACTIVE fires on
        # the first case only).
        fetched = validate_success(api_client.get_client(data["id"], INTAKE))
        assert fetched["status"] == "REGISTERED"

    def test_client_creation_missing_required_field(self):
        """PRD §3.1: "An `IntakeSpecialist` or `CenterAdmin` registers a newcomer
        with the client's `full_name`, an ISO 639-1 `preferred_language`, and a
        `date_of_birth` in `YYYY-MM-DD` form".
        PRD §2.8: "7. **Structural well-formedness** — required fields present,
        enum membership, score ranges, note length, end-after-start ordering,
        funding shares summing to one hundred, an acyclic household graph, one
        draft assessment per case, no duplicate live enrollments, and
        non-overlapping report periods; the generic failure is
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/client_creation_missing_required_field
        """
        resp = api_client.create_client(
            {"preferred_language": "es", "date_of_birth": "1999-01-01"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExistenceAndShape:
    def test_case_get_unknown_id_returns_not_found(self):
        """PRD §2.8: "3. **Existence** — path identifiers ... are resolved first,
        then identifiers referenced in the body ...; the first unknown id yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/case_get_unknown_id_returns_not_found
        """
        mgr = create_staff_member()
        resp = api_client.get_case(NON_EXISTENT_UUID, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_room_immutable_resource_shape(self):
        """PRD §2.5: "The one exception is the bookable `Room`: rooms carry `id`
        and `created_at` only. Both `updated_at` and `version` are absent from a
        room, because a room never mutates after creation."

        Design: Corner/entities/room_immutable_resource_shape
        """
        resp = api_client.create_room(
            create_room_payload(name="Room I", capacity=12), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(str(data["id"]))
        assert "created_at" in data
        assert "version" not in data, "rooms carry no version"
        assert "updated_at" not in data, "rooms carry no updated_at"


class TestHouseholdGraph:
    def test_household_head_self_reference_cycle(self):
        """PRD §3.1: "The household graph must stay acyclic — naming the client
        itself, or any descendant of the client in the household chain, as
        `household_head_id` is rejected with `ERR_HOUSEHOLD_HEAD_CYCLE`."

        Design: Corner/entities/household_head_self_reference_cycle
        """
        mgr = create_staff_member()
        head = register_client(full_name="Head A", household_size=2)
        member = register_client(full_name="Member B", household_size=2)
        # Valid linkage: member -> head.
        ok = validate_success(api_client.update_client(
            member["id"], {"household_head_id": head["id"]}, staff_headers(mgr)))
        assert ok["household_head_id"] == head["id"]
        # Closing a 2-cycle (head -> member) is rejected.
        resp = api_client.update_client(
            head["id"], {"household_head_id": member["id"]}, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_HEAD_CYCLE)

    def test_household_head_self_reference_rejected(self):
        """PRD §3.1: "The household graph must stay acyclic — naming the client
        itself, or any descendant of the client in the household chain, as
        `household_head_id` is rejected with `ERR_HOUSEHOLD_HEAD_CYCLE`."

        Design: Corner/entities/household_head_self_reference_cycle
        """
        mgr = create_staff_member()
        client = register_client(full_name="Self Head")
        resp = api_client.update_client(
            client["id"], {"household_head_id": client["id"]}, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_HEAD_CYCLE)


class TestClientListPagination:
    def test_clients_list_pagination_defaults_and_has_more(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter states how many items to skip and
        defaults to 0."
        PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/clients_list_pagination_defaults_and_has_more
        """
        for i in range(12):
            register_client(full_name=f"Page C{i + 1:02d}", date_of_birth=f"1990-01-{i + 1:02d}")
        first, meta1 = validate_paginated(api_client.list_clients(INTAKE))
        assert len(first) == 10, f"default limit must return 10 rows, got {len(first)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        second, meta2 = validate_paginated(
            api_client.list_clients(INTAKE, params={"limit": 10, "offset": 10}))
        assert len(second) == 2
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12
