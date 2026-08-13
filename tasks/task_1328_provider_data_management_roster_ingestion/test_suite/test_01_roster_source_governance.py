"""Roster source governance: creation defaults, enum/rank constraints, inflight
guards, and the source-ACTIVE gate on file registration (PRD §3.1, §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_roster_source,
    create_roster_file_payload,
    create_roster_source_payload,
    create_source,
    make_intake_operator_headers,
    register_file,
    set_clock,
    validate_error,
    validate_success,
)

STEWARD = TEST_USERS["data_steward_headers"]


class TestSourceCreation:
    def test_roster_source_created_active(self, api, data_steward_headers):
        """PRD §3.1: "A new source starts life with `status` `ACTIVE`."

        Design: Corner/entities/roster_source_creation_defaults_active
        """
        set_clock()
        res = api.create_roster_source(
            create_roster_source_payload(
                source_code="E1", display_name="E1", precedence_rank=1
            ),
            data_steward_headers,
        )
        source = validate_success(res, 201)
        assert_roster_source(source)
        assert source["status"] == "ACTIVE", (
            f"New source must start ACTIVE, got {source['status']}"
        )
        assert isinstance(source["version"], int)

    def test_roster_source_invalid_format_rejected(self, api, data_steward_headers):
        """PRD §3.1: "the feed's `format` — one of `CSV`, `XLSX`, `JSON`, `FHIR`, or
        `FIXED_WIDTH`".
        PRD §2.6: "Syntactic body validation — malformed payloads, missing required
        fields, invalid enum values, out-of-range integers — is evaluated last, after
        every applicable business rule, and surfaces as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/roster_source_enum_format_invalid_rejected
        """
        set_clock()
        res = api.create_roster_source(
            create_roster_source_payload(
                source_code="E3", display_name="E3", format="YAML", precedence_rank=1
            ),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_precedence_rank_conflict_rejected(self, api, data_steward_headers):
        """PRD §3.1: "The rank must be unique across all non-`RETIRED` sources, both at
        registration and when a source is later patched; a colliding rank is rejected
        with `ERR_PRECEDENCE_RANK_CONFLICT` (HTTP 409)."

        Design: Corner/validations/precedence_rank_conflict_rejected
        """
        set_clock()
        validate_success(
            api.create_roster_source(
                create_roster_source_payload(
                    source_code="V3A", display_name="A", precedence_rank=1
                ),
                data_steward_headers,
            ),
            201,
        )
        res = api.create_roster_source(
            create_roster_source_payload(
                source_code="V3B", display_name="B", precedence_rank=1
            ),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRECEDENCE_RANK_CONFLICT)


class TestSourceInflightGuard:
    def test_suspend_blocked_by_inflight_file(self, api, data_steward_headers):
        """PRD §3.1: "Suspension (`ACTIVE` → `SUSPENDED`) and retirement (`ACTIVE` →
        `RETIRED`) share a guard: neither may proceed while the source has a file
        anywhere in the inflight states `RECEIVED`, `PARSED`, `NORMALIZED`, or
        `VALIDATED`, and an attempt under those conditions is rejected with
        `ERR_SOURCE_HAS_INFLIGHT_FILE` (HTTP 409)."

        Design: Corner/state_machines/roster_source_inflight_suspend_blocked
        """
        set_clock()
        source = create_source(source_code="S5", precedence_rank=1)
        register_file(source["id"])
        res = api.suspend_roster_source(source["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_SOURCE_HAS_INFLIGHT_FILE)
        after = validate_success(api.get_roster_source(source["id"], data_steward_headers))
        assert after["status"] == "ACTIVE", (
            f"Source must remain ACTIVE after a blocked suspend, got {after['status']}"
        )


class TestSourceActiveGateForFiles:
    def test_register_file_on_suspended_source_rejected(self, api):
        """PRD §3.1: "A source that is not `ACTIVE` may not accept new file
        registrations, a rule enforced with `ERR_SOURCE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/roster_file_parse_depends_on_source_active
        """
        set_clock()
        source = create_source(source_code="SRC_X", precedence_rank=1)
        # The inflight guard blocks suspension while a file is RECEIVED; reject the
        # file first so the source can be suspended (reject from RECEIVED is allowed
        # from any pre-commit state, PRD §3.2).
        f = register_file(source["id"], external_file_ref="xf1", checksum="x001")
        validate_success(api.reject_roster_file(f["id"], make_intake_operator_headers("op_intake_1")))
        validate_success(api.suspend_roster_source(source["id"], STEWARD))
        res = api.create_roster_file(
            create_roster_file_payload(
                source["id"], external_file_ref="xf2", checksum="x002"
            ),
            make_intake_operator_headers("op_intake_1"),
        )
        validate_error(res, ApiErrorId.ERR_SOURCE_NOT_ACTIVE)

    def test_register_file_on_retired_source_rejected(self, api, data_steward_headers):
        """PRD §3.1: "A source that is not `ACTIVE` may not accept new file
        registrations, a rule enforced with `ERR_SOURCE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/roster_file_parse_depends_on_source_active
        """
        set_clock()
        source = create_source(source_code="SRC_Y", precedence_rank=1)
        validate_success(api.retire_roster_source(source["id"], data_steward_headers))
        res = api.create_roster_file(
            create_roster_file_payload(
                source["id"], external_file_ref="yf1", checksum="y001"
            ),
            make_intake_operator_headers("op_intake_1"),
        )
        validate_error(res, ApiErrorId.ERR_SOURCE_NOT_ACTIVE)


class TestFileRegistrationUniqueness:
    def test_duplicate_checksum_same_source_rejected(self, api):
        """PRD §3.2: "Two uniqueness rules guard registration, and both yield
        `ERR_DUPLICATE_FILE` (HTTP 409): the pair of `external_file_ref` and
        `roster_source_id` must be unique, and the `checksum` must be unique within
        the same source."

        Design: Corner/validations/duplicate_file_checksum_rejected
        """
        set_clock()
        source = create_source(source_code="V4", precedence_rank=1)
        headers = make_intake_operator_headers("op_intake_1")
        validate_success(
            api.create_roster_file(
                create_roster_file_payload(
                    source["id"], external_file_ref="v4a", checksum="dupc"
                ),
                headers,
            ),
            201,
        )
        res = api.create_roster_file(
            create_roster_file_payload(
                source["id"], external_file_ref="v4b", checksum="dupc"
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FILE)
