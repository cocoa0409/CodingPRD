"""Catalog onboarding: writer creation defaults, computed-field protection,
enum membership, 404s, derivative works, pagination, and work retrieval."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_work,
    assert_writer,
    create_work,
    create_work_payload,
    create_writer,
    create_writer_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


class TestWriterCreation:
    def test_create_writer_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "A new writer starts with `status` set to `ACTIVE`, `version` at 1, and all three computed balances — `payable_balance_cents`, `advance_outstanding_cents`, and `lifetime_earned_cents` — at zero; any client-supplied values for these computed fields are ignored."
        PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix of any kind."

        Design: Corner/entities/create_writer_applies_defaults_and_system_fields
        """
        payload = create_writer_payload(legal_name="Default Writer",
                                        pro_affiliation="PRS")
        data = validate_success(api.create_writer(payload, ADMIN), 201)
        assert_writer(data)
        assert data["status"] == "ACTIVE"
        assert data["payable_balance_cents"] == 0
        assert data["advance_outstanding_cents"] == 0
        assert data["lifetime_earned_cents"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), "id must be a bare server-minted UUID"

    def test_create_writer_computed_input_ignored(self, api):
        """PRD §3.1: "A new writer starts with `status` set to `ACTIVE`, `version` at 1, and all three computed balances — `payable_balance_cents`, `advance_outstanding_cents`, and `lifetime_earned_cents` — at zero; any client-supplied values for these computed fields are ignored."

        Design: Corner/entities/create_writer_computed_input_ignored
        """
        payload = create_writer_payload(legal_name="Sneaky",
                                        payable_balance_cents=99999)
        data = validate_success(api.create_writer(payload, ADMIN), 201)
        assert data["payable_balance_cents"] == 0, (
            "client-supplied computed field must be ignored, "
            f"got {data['payable_balance_cents']}")

    def test_invalid_enum_value_rejected(self, api):
        """PRD §3.1: "their `pro_affiliation`, one of `ASCAP`, `BMI`, `SESAC`, `PRS`, `GEMA`, `SACEM`, or `NONE`."
        PRD §2.8: "4. **Request shape** — required fields present, enum membership, integer ranges, date-range shape (`effective_from` strictly before `effective_to`, `period_end` on or after `period_start`), `line_number` unique within a statement, and participant fields consistent with `participant_type`, else `ERR_VALIDATION` or `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/invalid_enum_value_rejected
        """
        payload = create_writer_payload(legal_name="Bad Enum",
                                        pro_affiliation="BOGUS")
        resp = api.create_writer(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_writer_not_found_returns_404(self, api):
        """PRD §2.8: "Path identifiers are validated left to right, and the first identifier that does not correspond to an existing resource ends the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_writer_not_found_returns_404
        """
        resp = api.get_writer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWorks:
    def test_work_derivative_parent_reference_checked(self, api):
        """PRD §3.1: "Derivative works (samples, arrangements) are registered by supplying `parent_work_id`, which must reference an existing Work and is absent for originals; because no endpoint ever updates this field, derivative chains are acyclic by construction."
        PRD §3.1: "The works list accepts optional `parent_work_id`, `registration_status`, and `copyright_status` filters."

        Design: Corner/entities/work_derivative_parent_reference_checked
        """
        original = create_work(title="Original")
        derivative = validate_success(
            api.create_work(
                create_work_payload(title="Remix",
                                    grant_date="2020-01-01T00:00:00Z",
                                    parent_work_id=original["id"]),
                ADMIN),
            201)
        assert derivative["parent_work_id"] == original["id"], (
            "derivative link must be stored")

        resp = api.create_work(
            create_work_payload(title="Orphan Remix",
                                grant_date="2020-01-01T00:00:00Z",
                                parent_work_id=NON_EXISTENT_UUID),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        children, meta = validate_paginated(
            api.list_works(ADMIN, params={"parent_work_id": original["id"]}))
        assert meta["total_count"] == 1
        assert len(children) == 1 and children[0]["id"] == derivative["id"]

    def test_work_retrieval_roundtrip(self, api):
        """PRD §3.1: "At creation the server mints the `work_code`, a sequential publisher work number in the format `W-000001`, `W-000002`, and so on, unique across works. The work starts with `registration_status` set to `UNREGISTERED` and `copyright_status` set to `UNFILED` — two parallel status dimensions that evolve independently — and with `total_collected_cents` and `total_distributed_cents` at zero."

        Design: Corner/endpoints/work_retrieval_roundtrip
        """
        created = create_work(title="Roundtrip Song",
                              alternate_titles=["Roundtrip (Alt)"])
        fetched = validate_success(api.get_work(created["id"], ADMIN))
        assert_work(fetched)
        assert fetched["title"] == "Roundtrip Song"
        assert fetched["alternate_titles"] == ["Roundtrip (Alt)"]
        assert fetched["registration_status"] == "UNREGISTERED"
        assert fetched["copyright_status"] == "UNFILED"
        assert fetched["total_collected_cents"] == 0
        assert fetched["total_distributed_cents"] == 0
        assert fetched["work_code"] == "W-000001", (
            "first work on an empty catalog must mint W-000001, "
            f"got {fetched['work_code']}")


class TestWriterListing:
    def test_writers_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order."
        PRD §2.3: "List responses carry the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/writers_list_pagination_envelope
        """
        p1 = create_writer(legal_name="P1")
        create_writer(legal_name="P2", pro_affiliation="BMI")
        p3 = create_writer(legal_name="P3", pro_affiliation="SESAC")

        page1, meta1 = validate_paginated(
            api.list_writers(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert page1[0]["id"] == p1["id"], "order must be created_at ASC"

        page2, meta2 = validate_paginated(
            api.list_writers(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert page2[0]["id"] == p3["id"]
        assert meta2["has_more"] is False

        all_writers, meta3 = validate_paginated(api.list_writers(ADMIN))
        assert len(all_writers) == 3, "default limit 10 must return all 3"
        assert meta3["total_count"] == 3
        assert meta3["has_more"] is False
