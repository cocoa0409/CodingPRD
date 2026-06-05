"""Corner — entities section.

Creation, retrieval, default-field, and pagination claims for the persisted
entities (PRD §2.4, §3).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_marina_payload,
    create_slip_payload,
    create_tenant_payload,
    create_marina,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)


class TestMarinaCreateReturnsExpectedFields:

    def test_create_marina_returns_201_with_zero_liveaboard_count(self, api):
        """PRD §3.1: "On creation the marina's `liveaboard_current_count` is initialised to zero and tracks the live count of tenants whose `liveaboard_status` is `APPROVED` and whose active lease's `marina_id` equals this marina"

        Design: Corner/entities/marina_create_returns_201_with_all_required_fields
        """
        res = api.create_marina(
            create_marina_payload(name="MA", liveaboard_cap=5),
            TEST_USERS["harbor_master_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["liveaboard_current_count"] == 0
        # PRD §2.4: version begins at 1 on creation.
        assert data["version"] == 1, f"version must start at 1, got {data['version']}"


class TestMarinaGetNonexistentReturnsNotFound:

    def test_get_nonexistent_marina_returns_404(self, api):
        """PRD §2.5: "The first identifier in the path that does not resolve to a stored row yields `ERR_NOT_FOUND` with HTTP 404, regardless of what would have failed further along."

        Design: Corner/entities/marina_get_nonexistent_returns_not_found
        """
        res = api.get_marina(NON_EXISTENT_UUID, TEST_USERS["harbor_master_headers"])
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestMarinaCreateMissingRequiredReturnsInvalidRequest:

    def test_create_marina_without_harbor_code_returns_invalid_request(self, api):
        """PRD §2.7: "Schema-level violations of the request body — missing required fields, wrong types, invalid enum values — surface as `ERR_INVALID_REQUEST` with HTTP 400 only when no higher-priority rejection applies."
        PRD §3.1: "A `HarborMaster` creates one by supplying a `name`, a three-letter uppercase `harbor_code` that is unique across the system (for example `SFO`, `NYC`), and a `liveaboard_cap` — a non-negative integer expressing how many tenants may simultaneously hold approved liveaboard status while leasing a slip within this marina."

        Design: Corner/entities/marina_create_missing_required_returns_invalid_request
        """
        res = api.create_marina(
            {"name": "Missing Code", "liveaboard_cap": 1},
            TEST_USERS["harbor_master_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestSlipCreateDefaultsStatusToAvailable:

    def test_new_slip_defaults_to_available_and_no_pumpout_no_liveaboard(self, api):
        """PRD §3.1: "A new slip enters service in `AVAILABLE` state; its `marina_id` is inherited from the path."
        PRD §3.1: "The body may also supply `pumpout_available` (defaulting to false) indicating whether the slip pedestal has an integrated pump-out connection, and `liveaboard_allowed` (defaulting to false) indicating whether the slip is permitted to host liveaboard tenants."

        Design: Corner/entities/slip_create_defaults_status_to_available
        """
        marina = create_marina(liveaboard_cap=1)
        res = api.create_slip(
            marina["id"],
            create_slip_payload(
                slip_number="D-1",
                length_ft=30, beam_ft=10,
                power_amp="A30",
                base_daily_rate_cents=2000,
            ),
            TEST_USERS["harbor_master_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "AVAILABLE"
        assert data["pumpout_available"] is False
        assert data["liveaboard_allowed"] is False


class TestTenantInitialLiveaboardStatusIsNone:

    def test_new_tenant_liveaboard_status_defaults_to_none(self, api):
        """PRD §3.2: "A new tenant's `liveaboard_status` defaults to `NONE` and their `liveaboard_approved_at` is null."

        Design: Corner/entities/tenant_initial_liveaboard_status_is_none
        """
        res = api.create_tenant(
            create_tenant_payload(email="newtenant@x.com", full_name="New T"),
            TEST_USERS["harbor_master_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["liveaboard_status"] == "NONE"


class TestSlipStatusIsComputedNotWritable:

    def test_new_slip_status_is_available_regardless_of_input(self, api):
        """PRD §3.1: "A new slip enters service in `AVAILABLE` state; its `marina_id` is inherited from the path."

        Design: Corner/entities/slip_status_is_computed_not_writable
        """
        marina = create_marina(liveaboard_cap=1)
        res = api.create_slip(
            marina["id"],
            create_slip_payload(
                slip_number="C-1",
                length_ft=30, beam_ft=10,
                power_amp="A30",
                base_daily_rate_cents=2000,
            ),
            TEST_USERS["harbor_master_headers"],
        )
        data = validate_success(res, expected_status=201)
        # Server pins status to AVAILABLE — independent of any client supply.
        assert data["status"] == "AVAILABLE"


class TestListMarinasReturnsPaginationEnvelope:

    def test_list_marinas_response_includes_pagination_meta(self, api):
        """PRD §2.3: "The `meta` block of every list response carries `limit`, `offset`, `total_count` (the total matching rows across the entire result set), and `has_more` (true when additional pages remain after the current `offset` + `limit` window)."

        Design: Corner/entities/list_marinas_returns_pagination_envelope
        """
        create_marina(liveaboard_cap=1, name="L1")
        create_marina(liveaboard_cap=1, name="L2")
        res = api.list_marinas(TEST_USERS["harbor_master_headers"])
        data, meta = validate_paginated(res)
        # Pagination fields must be present.
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta
        assert isinstance(data, list)
