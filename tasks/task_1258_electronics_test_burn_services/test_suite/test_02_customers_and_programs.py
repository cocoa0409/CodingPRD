"""Customer accounts and test-program lifecycle: defaults, suspension gate,
validate/release preconditions, and the OCC-guarded revision mint (PRD §3.1–§3.2)."""
from test_helpers import (
    assert_customer,
    create_customer,
    create_fixture_payload,
    create_lot_payload,
    create_test_program_payload,
    setup_released_program_with_fixture,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS


class TestCustomerOnboarding:
    def test_customer_creation_applies_defaults(self, api):
        """PRD §3.1: "An `OperationsManager` onboards a customer by registering its
        legal `name`, commercial `tier` — one of `STANDARD` or `STRATEGIC` — and,
        optionally, the `requires_esd_certification` flag, which defaults to false
        when omitted."
        PRD §3.1: "New accounts begin with `account_status` set to `ACTIVE`."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        res = api.create_customer({"name": "DefaultCo", "tier": "STANDARD"}, OPS)
        created = validate_success(res, 201)
        customer = validate_success(api.get_customer(created["id"], OPS), 200)
        assert_customer(customer)
        assert customer["requires_esd_certification"] is False, (
            "omitted flag must default to false"
        )
        assert customer["account_status"] == "ACTIVE", "new accounts begin ACTIVE"

    def test_customer_missing_required_name_returns_invalid_request(self, api):
        """PRD §3.1: "An `OperationsManager` onboards a customer by registering its
        legal `name`, commercial `tier` — one of `STANDARD` or `STRATEGIC` — and,
        optionally, the `requires_esd_certification` flag, which defaults to false
        when omitted." (Only the flag is optional; a registration without the legal
        name is not a valid registration and is rejected with the catalogue's 400
        identifier `ERR_INVALID_REQUEST`.)

        Design: Corner/entities/customer_missing_required_name_returns_invalid_request
        """
        res = api.create_customer({"tier": "STANDARD"}, OPS)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_customer_suspended_blocks_lot_create(self, api):
        """PRD §3.1: "A suspended account blocks new lot creation: any attempt by
        that customer's representative to create a lot while the account is
        `SUSPENDED` is rejected with `ERR_CUSTOMER_SUSPENDED`."

        Design: Corner/validations/customer_suspended_blocks_lot_create
        """
        ctx = setup_released_program_with_fixture(part_number="PN-226")
        cust_id = ctx["customer"]["id"]
        suspended = validate_success(
            api.patch_customer(cust_id, {"account_status": "SUSPENDED"}, OPS), 200
        )
        assert suspended["account_status"] == "SUSPENDED"
        res = api.create_lot(
            create_lot_payload(cust_id, ctx["program"]["id"], part_number="PN-226"),
            ctx["rep_headers"],
        )
        validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


class TestProgramLifecycleGates:
    def test_program_validate_requires_available_fixture(self, api):
        """PRD §3.2: "Validation advances a program from `DRAFT` to `VALIDATED` and
        is permitted only while at least one fixture belonging to the program is
        `AVAILABLE`; attempting validation without one is rejected with
        `ERR_NO_AVAILABLE_FIXTURE`."

        Design: Corner/state_machines/program_validate_requires_available_fixture
        """
        customer = create_customer(name="ValCo")
        program = validate_success(
            api.create_test_program(
                create_test_program_payload(
                    customer["id"], part_number="PN-205", bin_map={"1": "PASS"},
                    max_retests_per_unit=1,
                ),
                ENG1,
            ),
            201,
        )
        # Fixture exists but is never commissioned, so none is AVAILABLE.
        validate_success(
            api.create_fixture(
                create_fixture_payload(program["id"], serial_number="FX-V"), ENG1
            ),
            201,
        )
        res = api.validate_program(program["id"], ENG1)
        validate_error(res, "ERR_NO_AVAILABLE_FIXTURE", expected_status=422)
        program_after = validate_success(api.get_test_program(program["id"], ENG1), 200)
        assert program_after["status"] == "DRAFT", "rejected validate must change nothing"

    def test_program_release_from_draft_returns_invalid_state(self, api):
        """PRD §3.2: "Release then advances the program from `VALIDATED` to
        `RELEASED`, incrementing its `version` again, and fires the supersession
        cascade." (A `DRAFT` program has no release transition.)
        PRD §2.11: "the target resource's own state permits the operation — a lot `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a review `PENDING` for a decision, an audit `OPEN` for close, a reservation `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED` for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/program_release_from_draft_returns_invalid_state
        """
        customer = create_customer(name="DraftCo")
        program = validate_success(
            api.create_test_program(
                create_test_program_payload(
                    customer["id"], part_number="PN-206", bin_map={"1": "PASS"},
                    max_retests_per_unit=1,
                ),
                ENG1,
            ),
            201,
        )
        res = api.release_program(program["id"], ENG1)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        program_after = validate_success(api.get_test_program(program["id"], ENG1), 200)
        assert program_after["status"] == "DRAFT", "rejected release must change nothing"


class TestProgramRevisionOcc:
    def test_first_revision_mint_succeeds_and_copies_lineage(self, api):
        """PRD §3.2: "The mint creates an entirely new program row: its `revision`
        is the source's revision plus one, its status is `DRAFT`, its
        `supersedes_program_id` is the source program's `id`, and its `customer_id`,
        `part_number`, `bin_map`, `max_retests_per_unit`, and `burn_profile` are
        copied from the source."
        PRD §2.6: "Minting a successor revision of a test program requires the
        request to carry `expected_test_program_version`, a non-optional field
        holding the source program's `version` as the client last observed it."

        Design: Corner/cross_cutting_layers/occ_revision_create_stale_version_returns_412
        """
        ctx = setup_released_program_with_fixture(part_number="PN-238")
        program = ctx["program"]
        source = validate_success(api.get_test_program(program["id"], ENG1), 200)
        observed_version = source["version"]

        rev2 = validate_success(
            api.create_program_revision(
                program["id"], {"expected_test_program_version": observed_version}, ENG1
            ),
            201,
        )
        assert rev2["id"] != program["id"], "the mint creates an entirely new row"
        assert rev2["revision"] == source["revision"] + 1
        assert rev2["status"] == "DRAFT"
        assert rev2["supersedes_program_id"] == program["id"]
        assert rev2["customer_id"] == source["customer_id"]
        assert rev2["part_number"] == source["part_number"]
        assert rev2["bin_map"] == source["bin_map"]
        assert rev2["max_retests_per_unit"] == source["max_retests_per_unit"]
        assert rev2["burn_profile"] == source["burn_profile"]

        successors, meta = validate_paginated(
            api.list_test_programs(ENG1, params={"supersedes_program_id": program["id"]})
        )
        assert len(successors) == 1 and meta["total_count"] == 1, (
            "exactly one revision-2 row may exist after a single mint"
        )

    def test_replayed_observed_version_rejected_stale(self, api):
        """PRD §2.6: "If the source program's current `version` has advanced beyond
        that value since the client last read it, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from minting a revision
        against a lineage it has not observed."
        PRD §3.2: "The source program's own `version` increments by one even though
        its status is unchanged, which is precisely what the OCC guard keys on."

        Design: Corner/cross_cutting_layers/occ_revision_create_stale_version_returns_412
        """
        ctx = setup_released_program_with_fixture(part_number="PN-238")
        program = ctx["program"]
        observed_version = validate_success(
            api.get_test_program(program["id"], ENG1), 200
        )["version"]

        # First mint with the observed version succeeds and advances the source.
        rev2 = validate_success(
            api.create_program_revision(
                program["id"], {"expected_test_program_version": observed_version}, ENG1
            ),
            201,
        )
        assert rev2["revision"] == 2

        # Replaying the same observed version is deterministically stale.
        res = api.create_program_revision(
            program["id"], {"expected_test_program_version": observed_version}, ENG1
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)

        successors, _meta = validate_paginated(
            api.list_test_programs(ENG1, params={"supersedes_program_id": program["id"]})
        )
        assert len(successors) == 1, "the rejected mint must not create another row"
