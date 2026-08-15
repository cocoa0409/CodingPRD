"""Units, lease files, rent roll: shape, uniqueness, supersession, lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_unit,
    assert_lease_file,
    assert_rent_roll_entry,
    assert_unit,
    create_acquisition,
    create_acquisition_payload,
    create_kicked_off_acquisition,
    create_lease_file_payload,
    create_rent_roll_entry_payload,
    create_unit_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]


class TestUnitListing:
    def test_list_units_paginates_with_limit_offset(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        sets the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_units_paginates_with_limit_offset
        """
        acq = create_acquisition(property_name="Paging Deal")
        for number, plan, sqft, rent in (("1A", "1BR", 700, 160000),
                                         ("2B", "2BR", 900, 180000),
                                         ("3C", "3BR", 1100, 200000)):
            add_unit(acq["id"], unit_number=number, floor_plan=plan,
                     sqft=sqft, market_rent_cents=rent)
        other = create_acquisition(property_name="Other Deal")
        add_unit(other["id"], unit_number="9Z")

        page1, meta1 = validate_paginated(api.list_units(
            ANALYST, params={"acquisition_id": acq["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_units(
            ANALYST, params={"acquisition_id": acq["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        for row in page1 + page2:
            assert row["acquisition_id"] == acq["id"], (
                "the acquisition_id filter excludes other acquisitions' units"
            )


class TestRequestShape:
    def test_create_unit_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.2: "Units are registered against an acquisition by an
        `AcquisitionsAnalyst` supplying `unit_number`, `floor_plan`, `sqft`,
        and `market_rent_cents` along with the owning `acquisition_id`."
        PRD §5: `ERR_INVALID_REQUEST` is HTTP 400.

        Design: Corner/entities/create_unit_missing_required_field_returns_invalid_request
        """
        acq = create_acquisition(property_name="Req Deal")
        payload = create_unit_payload(acq["id"])
        del payload["sqft"]
        resp = api.create_unit(payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_acquisition_invalid_enum_rejected(self, api):
        """PRD §3.1: "`interest_accrual_method` defaults to `DAILY_ACCRUAL`
        (the alternative being `SIMPLE_ANNUAL`) and governs deposit interest."
        PRD §2.4: "then request shape (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, `ERR_INVALID_DATE_RANGE`)"

        Design: Corner/entities/create_acquisition_invalid_enum_rejected
        """
        resp = api.create_acquisition(
            create_acquisition_payload(property_name="Enum Deal",
                                       interest_accrual_method="WEEKLY"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, 400)

    def test_invalid_walk_window_returns_date_range_error(self, api):
        """PRD §2.4: "then request shape (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, `ERR_INVALID_DATE_RANGE`)"
        PRD §5: `ERR_INVALID_DATE_RANGE` is HTTP 400.

        Design: Corner/validations/invalid_walk_window_returns_date_range_error
        """
        acq = create_acquisition(property_name="Range Deal")
        unit = add_unit(acq["id"])
        resp = api.create_inspection(
            {"unit_id": unit["id"], "inspector_ref": "insp-1",
             "walk_start": "2026-08-10T10:00:00Z",
             "walk_end": "2026-08-10T09:00:00Z"},
            TEST_USERS["property_ops_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, 400)


class TestLeaseSupersession:
    def test_supersede_retires_prior_lease(self, api):
        """PRD §3.3: "A unit has at most one current lease; uploading a second
        lease for a unit that already has a current one is rejected with
        `ERR_ACTIVE_LEASE_EXISTS` unless the payload supplies
        `supersedes_lease_id` naming that current lease, in which case the
        named lease moves to `SUPERSEDED` as the new one is accepted."

        Design: Corner/entities/supersede_retires_prior_lease
        """
        acq = create_kicked_off_acquisition(property_name="Sup Deal")
        unit = add_unit(acq["id"])
        lease1 = get_success_data(api.create_lease_file(
            create_lease_file_payload(unit["id"], lease_end_date="2026-08-31T00:00:00Z"),
            ANALYST), 201)

        lease2_resp = api.create_lease_file(
            create_lease_file_payload(
                unit["id"], lease_start_date="2026-09-01T00:00:00Z",
                contract_rent_cents=152000, supersedes_lease_id=lease1["id"]),
            ANALYST)
        lease2 = validate_success(lease2_resp, 201)
        assert_lease_file(lease2)
        assert lease2["status"] == "UPLOADED"

        lease1_after = get_success_data(api.get_lease_file(lease1["id"], ANALYST))
        assert lease1_after["status"] == "SUPERSEDED"

        rows, _ = validate_paginated(api.list_unit_lease_files(unit["id"], ANALYST))
        non_superseded = [r for r in rows if r["status"] != "SUPERSEDED"]
        assert len(rows) == 2, "the unit's collection lists both leases"
        assert len(non_superseded) == 1 and non_superseded[0]["id"] == lease2["id"], (
            "exactly one current lease remains"
        )

    def test_supersede_stale_target_rejected(self, api):
        """PRD §3.3: "A `supersedes_lease_id` that names anything other than
        the unit's current non-`SUPERSEDED` lease is rejected with
        `ERR_SUPERSEDE_TARGET_NOT_CURRENT`."

        Design: Corner/entities/supersede_stale_target_rejected
        """
        acq = create_kicked_off_acquisition(property_name="Sup Two")
        unit = add_unit(acq["id"])
        lease1 = get_success_data(api.create_lease_file(
            create_lease_file_payload(unit["id"], lease_end_date="2026-08-31T00:00:00Z"),
            ANALYST), 201)
        get_success_data(api.create_lease_file(
            create_lease_file_payload(
                unit["id"], lease_start_date="2026-09-01T00:00:00Z",
                contract_rent_cents=152000, supersedes_lease_id=lease1["id"]),
            ANALYST), 201)

        resp = api.create_lease_file(
            create_lease_file_payload(
                unit["id"], lease_start_date="2026-09-01T00:00:00Z",
                contract_rent_cents=153000, supersedes_lease_id=lease1["id"]),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_NOT_CURRENT, 409)

    def test_duplicate_current_lease_rejected(self, api):
        """PRD §3.3: "A unit has at most one current lease; uploading a second
        lease for a unit that already has a current one is rejected with
        `ERR_ACTIVE_LEASE_EXISTS` unless the payload supplies
        `supersedes_lease_id` naming that current lease..."

        Design: Corner/entities/duplicate_current_lease_rejected
        """
        acq = create_kicked_off_acquisition(property_name="Dup Lease")
        unit = add_unit(acq["id"])
        get_success_data(api.create_lease_file(
            create_lease_file_payload(unit["id"]), ANALYST), 201)

        resp = api.create_lease_file(
            create_lease_file_payload(
                unit["id"], resident_name="R Two",
                lease_start_date="2026-01-01T00:00:00Z",
                lease_end_date="2027-12-31T00:00:00Z",
                contract_rent_cents=155000, term_months=24,
                deposit_amount_cents=155000),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_LEASE_EXISTS, 409)


class TestRentRollEntryShape:
    def test_rent_roll_entry_carries_no_version_field(self, api):
        """PRD §2.5: "Two resource kinds are deliberately leaner: a rent roll
        entry and a proration line carry only `id` and `created_at`; they have
        no `updated_at` and no `version`, because entries on the seller's rent
        roll and lines inside a statement are never mutated in place —
        corrections flow through the owning lease or statement instead."
        PRD §3.3: "A new entry's `verification_status` is `UNVERIFIED` and
        changes only as a side effect of lease audit activity — no endpoint
        writes it directly."

        Design: Corner/entities/rent_roll_entry_carries_no_version_field
        """
        acq = create_acquisition(property_name="Imm Deal")
        unit = add_unit(acq["id"])
        resp = api.create_rent_roll_entry(
            create_rent_roll_entry_payload(unit["id"]), ANALYST)
        entry = validate_success(resp, 201)
        assert_rent_roll_entry(entry)
        assert "version" not in entry, "rent roll entries carry no version"
        assert "updated_at" not in entry, "rent roll entries carry no updated_at"
        assert entry["verification_status"] == "UNVERIFIED"


class TestUnitTerminalLockdown:
    def test_excluded_unit_is_terminal_and_out_of_scope(self, api):
        """PRD §3.2: "An `AcquisitionsAnalyst` may exclude a unit in
        `REGISTERED` or `CLEARING`; exclusion lands in the terminal `EXCLUDED`
        state and removes the unit from audit scope, from the rent proration
        input set, and from posture derivation, so the unit's leases and
        findings no longer count anywhere. There is no path out of `EXCLUDED`."
        PRD §2.4: "then state-machine legality (the 409 state family including
        `ERR_INVALID_STATE_TRANSITION`, ...)"

        Design: Corner/entities/excluded_unit_is_terminal_and_out_of_scope
        """
        acq = create_kicked_off_acquisition(property_name="Excl Deal")
        unit = add_unit(acq["id"])

        first = validate_success(api.exclude_unit(unit["id"], ANALYST), 200)
        assert_unit(first)
        assert first["status"] == "EXCLUDED"

        resp = api.exclude_unit(unit["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


class TestUnitNumberUniqueness:
    def test_duplicate_unit_number_rejected(self, api):
        """PRD §3.2: "The `unit_number` must be unique within its acquisition;
        a duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER`."

        Design: Corner/entities/duplicate_unit_number_rejected
        """
        acq_a = create_acquisition(property_name="Dup A")
        add_unit(acq_a["id"], unit_number="1A")
        acq_b = create_acquisition(property_name="Dup B")

        resp = api.create_unit(
            create_unit_payload(acq_a["id"], unit_number="1A", sqft=720,
                                market_rent_cents=161000),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER, 409)

        other = validate_success(api.create_unit(
            create_unit_payload(acq_b["id"], unit_number="1A"), ANALYST), 201)
        assert other["unit_number"] == "1A", (
            "uniqueness is acquisition-scoped: the same number is fine elsewhere"
        )
