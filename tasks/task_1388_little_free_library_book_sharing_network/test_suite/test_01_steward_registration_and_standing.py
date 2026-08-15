"""Steward registration, defaults, uniqueness, pagination, and lifecycle gates."""
from test_helpers import (
    ApiErrorId,
    assert_steward,
    assert_timestamp_equals,
    create_active_steward,
    create_steward_payload,
    ensure_orientation_module,
    is_valid_uuid,
    make_steward_headers,
    pin_clock,
    register_steward,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStewardRegistration:
    def test_steward_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "Registration — open to the public and to administrators —
        captures the applicant's `full_name`, `email`, and the two-letter
        `region_code` (for example OR or WA) in which they will operate, and
        creates a Steward in `APPLIED` status with every computed counter at zero."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time."

        Design: Corner/entities/steward_create_applies_defaults_and_system_fields
        """
        pin_clock()
        res = api.create_steward(
            create_steward_payload(
                full_name="New Steward",
                email="new-steward-defaults@example.org",
                region_code="OR",
            ),
            {},
        )
        steward = validate_success(res, 201)
        assert_steward(steward)
        assert steward["status"] == "APPLIED"
        assert steward["training_level"] == 0
        assert steward["lifetime_points"] == 0
        assert steward["rolling_points"] == 0
        assert steward["recognition_tier"] == "NONE"
        assert steward["strike_count"] == 0
        assert steward["version"] == 1
        assert_timestamp_equals(steward["created_at"], "2026-08-01T00:00:00Z")
        assert is_valid_uuid(steward["id"])

    def test_steward_create_rejected_missing_required_email(self, api):
        """PRD §2.8: "Required fields are present, enum members are valid, and
        numeric ranges hold — failure is `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: "Registration — open to the public and to administrators —
        captures the applicant's `full_name`, `email`, and the two-letter
        `region_code` (for example OR or WA) in which they will operate."

        Design: Corner/entities/steward_create_rejected_missing_required_email
        """
        pin_clock()
        res = api.create_steward(
            {"full_name": "No Email", "region_code": "OR"}, {}
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    def test_steward_create_rejected_duplicate_email(self, api):
        """PRD §3.1: "Email addresses are unique across all stewards regardless
        of status: a registration or update that reuses an existing steward's
        address is rejected with `ERR_EMAIL_TAKEN`."

        Design: Corner/entities/steward_create_rejected_duplicate_email
        """
        pin_clock()
        register_steward(full_name="First", email="dup@example.org",
                         region_code="OR")
        res = api.create_steward(
            create_steward_payload(
                full_name="Second", email="dup@example.org", region_code="WA"
            ),
            {},
        )
        validate_error(res, ApiErrorId.ERR_EMAIL_TAKEN.value, expected_status=422)

    def test_steward_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a
        client can always tell how many records exist in total and whether
        further pages remain."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, accepts a minimum of 1, and is clamped at a maximum of
        100. The `offset` parameter says how many items to skip and defaults
        to 0."

        Design: Corner/entities/steward_list_pagination_envelope
        """
        pin_clock()
        register_steward(full_name="P One", email="p1@example.org")
        register_steward(full_name="P Two", email="p2@example.org")
        register_steward(full_name="P Three", email="p3@example.org",
                         region_code="WA")

        from test_helpers import TEST_USERS

        admin = TEST_USERS["admin_headers"]
        page1, meta1 = validate_paginated(
            api.list_stewards(admin, params={"limit": 2})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_stewards(admin, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestStewardLifecycle:
    def test_steward_activation_rejected_without_orientation(self, api):
        """PRD §3.1: "Activation is the gateway from applicant to steward: a
        `NetworkAdmin` activates an `APPLIED` steward only when that steward
        holds a `PASSED` completion in the `ORIENTATION` module, failing with
        `ERR_ORIENTATION_REQUIRED` when the pass is missing and
        `ERR_INVALID_STATE` when the steward is not `APPLIED`."

        Design: Corner/state_machines/steward_activation_rejected_without_orientation
        """
        pin_clock()
        ensure_orientation_module()
        steward = register_steward(full_name="Untrained",
                                   email="untrained@example.org")

        from test_helpers import TEST_USERS

        res = api.activate_steward(steward["id"], TEST_USERS["admin_headers"])
        validate_error(res, ApiErrorId.ERR_ORIENTATION_REQUIRED.value,
                       expected_status=409)
        after = validate_success(
            api.get_steward(steward["id"], TEST_USERS["admin_headers"]), 200
        )
        assert after["status"] == "APPLIED"

    def test_steward_retire_terminal_lockdown(self, api):
        """PRD §3.1: "Retirement is terminal: a steward may retire themselves,
        or be retired by a `NetworkAdmin`, from either `ACTIVE` or `SUSPENDED`
        into `RETIRED`; a steward attempting to retire someone else's record is
        rejected with `ERR_FORBIDDEN_OWNERSHIP`, and any retire attempt from a
        state other than `ACTIVE` or `SUSPENDED` fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/steward_retire_terminal_lockdown
        """
        pin_clock()
        steward = create_active_steward(full_name="Retiring",
                                        email="ret@example.org")

        from test_helpers import TEST_USERS

        retired = validate_success(
            api.retire_steward(steward["id"],
                               make_steward_headers(steward["id"])),
            200,
        )
        assert retired["status"] == "RETIRED"

        res = api.suspend_steward(steward["id"], TEST_USERS["admin_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)
        after = validate_success(
            api.get_steward(steward["id"], TEST_USERS["admin_headers"]), 200
        )
        assert after["status"] == "RETIRED"
