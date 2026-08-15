"""Cooperative foundation: creation defaults, system fields, share ledger,
pagination, the logical clock default, and structural request errors."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_cooperative,
    assert_shareholder,
    assert_unit,
    create_cooperative,
    create_cooperative_payload,
    create_unit_payload,
    is_iso8601_millis,
    is_valid_uuid,
    OFFICER,
    parse_iso,
    validate_error,
    validate_paginated,
    validate_success,
)

# Exact startup instant mandated for a fresh cooperative's logical clock.
CLOCK_START_PREFIX = "2026-08-01T00:00:00"


class TestCooperativeCreation:
    def test_cooperative_creation_applies_defaults(self, api):
        """PRD §3.1: "Policy knobs may be set at creation or left to
        their defaults: `flip_tax_policy` (either `GROSS_PERCENT` or `PER_SHARE`,
        defaulting to `GROSS_PERCENT`), `flip_tax_percent_bps` (default 200,
        i.e., two percent of the gross sale price), `flip_tax_per_share_cents`
        (default 50000, i.e., $500 per share), `sublet_policy_years_max`
        (default 2 consecutive years), `sublet_policy_gap_years` (default 1 year
        of owner occupancy between sublets), `arrears_late_fee_flat_cents`
        (default 5000, a $50 flat late fee), `arrears_interest_rate_bps`
        (default 600, a six percent annual rate), `arrears_grace_days` (default
        10 days after the due date), `arrears_termination_threshold_cents`
        (default 1000000, i.e., $10,000 of arrears), and
        `annual_meeting_quorum_percent_bps` (default 5000, i.e., 50.00% of all
        shares)."
        PRD §3.1: "The new cooperative starts with `total_shares` of zero
        and its logical clock at the startup instant described in §2.5."

        Design: Corner/entities/cooperative_creation_applies_defaults
        """
        resp = api.create_cooperative(create_cooperative_payload(name="Default Coop"),
                                      ADMIN)
        coop = validate_success(resp, 201)
        assert_cooperative(coop)
        assert coop["flip_tax_policy"] == "GROSS_PERCENT"
        assert coop["flip_tax_percent_bps"] == 200
        assert coop["flip_tax_per_share_cents"] == 50000
        assert coop["sublet_policy_years_max"] == 2
        assert coop["sublet_policy_gap_years"] == 1
        assert coop["arrears_late_fee_flat_cents"] == 5000
        assert coop["arrears_interest_rate_bps"] == 600
        assert coop["arrears_grace_days"] == 10
        assert coop["arrears_termination_threshold_cents"] == 1000000
        assert coop["annual_meeting_quorum_percent_bps"] == 5000
        assert coop["total_shares"] == 0

        fetched = validate_success(api.get_cooperative(coop["id"], ADMIN))
        assert fetched["flip_tax_policy"] == "GROSS_PERCENT"
        assert fetched["total_shares"] == 0

    def test_cooperative_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "a request body missing a required field or failing
        a type check is rejected with `ERR_INVALID_REQUEST` (HTTP 400)"
        PRD §3.1: "A `PlatformAdmin` brings a cooperative into existence
        by supplying its legal `name` and street `address`, together with the
        building's underlying permanent mortgage:
        `underlying_mortgage_principal_cents` for the outstanding principal and
        `underlying_mortgage_rate_bps` for the annual interest rate in basis
        points."

        Design: Corner/entities/cooperative_missing_required_field_returns_invalid_request
        """
        resp = api.create_cooperative(
            {"address": "X St", "underlying_mortgage_principal_cents": 100,
             "underlying_mortgage_rate_bps": 500},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_get_nonexistent_cooperative_returns_404(self, api):
        """PRD §2.4: "Path parameters are validated left to right: each
        segment must identify an existing resource, and each child must belong
        to the scope established by its parent segments. Any failure along this
        chain is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_cooperative_returns_404
        """
        resp = api.get_cooperative(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_cooperative_system_fields_server_generated(self, api):
        """PRD §2.4: "The `id` is a server-minted UUID with no type
        prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC
        values rendered with three fractional digits. The `version` is an
        integer that increments on every mutation of the resource. No entity in
        this API is exempt from these common fields."

        Design: Corner/entities/system_fields_id_created_at_updated_at_version
        """
        coop = validate_success(
            api.create_cooperative(create_cooperative_payload(name="SysCoop"), ADMIN),
            201)
        assert is_valid_uuid(coop["id"]), "id is a server-minted UUID"
        assert is_iso8601_millis(coop["created_at"]), \
            "created_at rendered with three fractional digits"
        assert is_iso8601_millis(coop["updated_at"]), \
            "updated_at rendered with three fractional digits"
        assert isinstance(coop["version"], int), "version is an integer"

    def test_clock_defaults_to_startup_instant(self, api):
        """PRD §2.5: "When a cooperative is created, `current_utc`
        initializes to 2026-08-01T00:00:00Z, and it thereafter advances only
        when a `PlatformAdmin` explicitly sets it through the clock-advance
        capability, passing the target instant as `to_iso8601`."

        Design: Corner/endpoints/clock_set_default_startup_time
        """
        coop = validate_success(
            api.create_cooperative(create_cooperative_payload(name="ClockCoop"), ADMIN),
            201)
        assert coop["current_utc"].startswith(CLOCK_START_PREFIX), (
            f"current_utc must initialize to the 2026-08-01T00:00:00Z startup "
            f"instant, got {coop['current_utc']}")
        assert parse_iso(coop["current_utc"]) == parse_iso("2026-08-01T00:00:00Z")

    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.9: "a value outside the declared set of an enum field
        is rejected with `ERR_INVALID_ENUM` (HTTP 400)."
        PRD §3.1: "`flip_tax_policy` (either `GROSS_PERCENT` or
        `PER_SHARE`, defaulting to `GROSS_PERCENT`)".

        Design: Corner/errors/error_invalid_enum_value
        """
        resp = api.create_cooperative(
            create_cooperative_payload(name="Enum Coop",
                                       flip_tax_policy="BOGUS_VALUE"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)


class TestUnitsAndLedger:
    def test_unit_creation_updates_total_shares(self, api):
        """PRD §2.7: "the cooperative's `total_shares` must always equal
        the sum of `shares_allocated` over all of its units, and the shares
        assigned to a unit through the share ledger must in turn reconcile
        exactly with that unit's allocation. Creating a unit adds its
        `shares_allocated` to the cooperative's `total_shares` and increments
        the cooperative's `version`."

        Design: Corner/entities/unit_total_shares_computed_field
        """
        coop = create_cooperative(name="Computed Coop")
        assert coop["total_shares"] == 0
        api.create_unit(coop["id"],
                        create_unit_payload(unit_label="1A", shares_allocated=150),
                        ADMIN)
        api.create_unit(coop["id"],
                        create_unit_payload(unit_label="1B", shares_allocated=250),
                        ADMIN)
        fetched = validate_success(api.get_cooperative(coop["id"], ADMIN))
        assert fetched["total_shares"] == 400, (
            f"total_shares must equal the sum of shares_allocated "
            f"(150 + 250 = 400), got {fetched['total_shares']}")

    def test_unit_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the
        four pagination fields `limit`, `offset`, `total_count`, and `has_more`,
        where `total_count` reports the full size of the filtered result set and
        `has_more` indicates whether further pages exist beyond the returned
        window."

        Design: Corner/entities/unit_list_pagination_envelope
        """
        coop = create_cooperative(name="Page Coop")
        for label in ("A", "B", "C"):
            validate_success(api.create_unit(
                coop["id"], create_unit_payload(unit_label=label, shares_allocated=100),
                ADMIN), 201)
        resp = api.list_units(coop["id"], ADMIN, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must return 2 units, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for unit in data:
            assert_unit(unit)

    def test_shareholder_email_unique_within_cooperative(self, api):
        """PRD §3.1: "Shareholders are registered by a `PlatformAdmin`,
        `BoardOfficer`, or `ManagingAgent` with a `full_name` and a contact
        `email`; the email must be unique within the cooperative, and a
        duplicate is rejected with `ERR_BUSINESS_CONSTRAINT`."

        Design: Corner/entities/shareholder_email_unique_within_cooperative
        """
        coop = create_cooperative(name="Dup Coop")
        first = validate_success(api.create_shareholder(
            coop["id"], {"full_name": "A", "email": "dup@example.com"}, OFFICER), 201)
        assert_shareholder(first)
        resp = api.create_shareholder(
            coop["id"], {"full_name": "B", "email": "dup@example.com"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_BUSINESS_CONSTRAINT, expected_status=422)

    def test_share_ledger_sum_must_equal_unit_allocation(self, api):
        """PRD §3.1: "After every insertion the server revalidates the
        conservation rule: the sum of `shares_held` over the unit's `ACTIVE`
        entries must equal that unit's `shares_allocated` exactly, or the write
        is rejected with `ERR_SHARES_MISMATCH` (HTTP 422)."

        Design: Corner/validations/share_conservation_constraint
        """
        coop = create_cooperative(name="ShareMis")
        unit = validate_success(api.create_unit(
            coop["id"], create_unit_payload(unit_label="1A", shares_allocated=100),
            ADMIN), 201)
        owner_a = validate_success(api.create_shareholder(
            coop["id"], {"full_name": "A", "email": "a@example.com"}, OFFICER), 201)
        owner_b = validate_success(api.create_shareholder(
            coop["id"], {"full_name": "B", "email": "b@example.com"}, OFFICER), 201)
        validate_success(api.create_share_ledger_entry(
            coop["id"],
            {"unit_id": unit["id"], "shareholder_id": owner_a["id"],
             "shares_held": 100},
            OFFICER), 201)
        # 100 already assigned; one more share breaks the exact reconciliation.
        resp = api.create_share_ledger_entry(
            coop["id"],
            {"unit_id": unit["id"], "shareholder_id": owner_b["id"],
             "shares_held": 1},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_SHARES_MISMATCH, expected_status=422)
