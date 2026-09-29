"""Contract formation, fleet registration and the shape of a freshly stored row.

Every test here builds its own contract, site and devices from scratch and then
inspects exactly what the platform stored: the echoed inputs, the server-minted
identity fields, the declared defaults, the derived counters that start at zero,
and the rejections that leave nothing behind.
"""

import re

import pytest

from test_helpers import (
    TEST_USERS,
    activate_contract,
    add_cost_tier,
    assert_append_only_record,
    assert_device,
    assert_fields,
    assert_lines_sum_to_usage_subtotal,
    assert_service_contract,
    assert_site,
    assert_statement_line,
    assert_statement_total_is_consistent,
    assert_technician,
    close_period,
    create_contract,
    create_device,
    create_site,
    device_payload,
    fetch_contract,
    fetch_device,
    fetch_site,
    is_valid_uuid,
    make_customer_admin_headers,
    run_sweep,
    set_clock,
    setup_print_environment,
    submit_automated_read,
    suspend_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
OPS = TEST_USERS["fleet_ops_headers"]

# A contract creation body that supplies every input, optional ones included.
FULL_CONTRACT_INPUT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 20_000,
    "minimum_color_pages_per_period": 2_000,
    "monthly_service_fee_cents": 48_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 480_000,
}

# The six mandatory contract inputs, with every optional one deliberately absent.
MINIMAL_CONTRACT_INPUT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 48_000,
}

DEVICE_INPUT = {
    "asset_tag": "MPS-0001",
    "model_code": "XR-M4200",
    "rated_monthly_duty_cycle": 20_000,
    "assessed_monthly_mono_pages": 9_000,
    "assessed_monthly_color_pages": 0,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
    "color_capable": False,
}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-20T00:00:00Z"
COVERAGE_END = "2026-08-15T00:00:00Z"

_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(?:Z|\+00:00)$"
)


def _assert_utc_with_three_fractional_digits(value, label):
    """ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and _THREE_FRACTIONAL_DIGITS.match(value), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def _contract_with_site(**site_overrides):
    """A DRAFT contract and one site under it."""
    contract = create_contract(**MINIMAL_CONTRACT_INPUT)
    site = create_site(contract["id"], **site_overrides)
    return contract, site


class TestContractCreation:
    """A brand-new managed-print contract: echoed inputs and zeroed ledgers."""

    def test_new_contract_echoes_every_supplied_input_and_starts_in_draft(self, api):
        """Creation returns 201 and every commercial term exactly as supplied.

        PRD: "An `AccountManager` opens one by supplying the customer's legal name in
        `customer_name` (non-empty, at most 120 characters), the term length in
        `term_months` (at least 12 and at most 60), the service envelope in
        `included_service_scope`, the two contracted minimum volumes
        `minimum_mono_pages_per_period` and `minimum_color_pages_per_period` (each zero
        or greater), and the fixed `monthly_service_fee_cents` (zero or greater), which
        doubles as the base amount for response-time credits."
        PRD: "Four further inputs are optional and default when omitted:
        `response_sla_hours_critical` defaults to 4 hours and must lie between 1 and 72;
        `response_sla_hours_standard` defaults to a full day at 24 hours and must lie
        between 1 and 168; `labor_rate_cents_per_hour` defaults to 9,500 cents — $95 an
        hour — and must be zero or greater; and `early_termination_fee_cents` defaults to
        0 and must be zero or greater. A newly created contract's `status` is `DRAFT`."

        Design: Corner/entities/creation_service_contract_starts_draft_with_zeroed_ledgers
        """
        response = api.create_service_contract(dict(FULL_CONTRACT_INPUT), AM)

        data = validate_success(response, 201)
        assert_fields(data, **FULL_CONTRACT_INPUT, status="DRAFT")
        assert_service_contract(data)

    def test_new_contract_starts_with_every_derived_counter_at_zero(self, api):
        """No ledger may start null: all five derived counters read exactly 0.

        PRD: "Six counters on the contract are derived, never supplied, and all start at
        zero on creation."
        PRD: "Alongside those, `suspension_reason` is a system-maintained enumeration
        that begins at `NONE` and thereafter takes one of `NONPAYMENT`, `DISPUTE` or
        `CUSTOMER_REQUEST`."
        PRD: "Alongside `id`, most resources expose `created_at` and `updated_at` as ISO
        8601 UTC timestamps with three fractional digits, plus an integer `version` that
        starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/creation_service_contract_starts_draft_with_zeroed_ledgers
        """
        response = api.create_service_contract(dict(FULL_CONTRACT_INPUT), AM)

        data = validate_success(response, 201)
        assert_fields(
            data,
            active_device_count=0,
            consumables_committed_cents=0,
            true_up_balance_cents=0,
            lifetime_billed_cents=0,
            suspension_count=0,
            suspension_reason="NONE",
            version=1,
        )
        for ledger in (
            "active_device_count",
            "consumables_committed_cents",
            "true_up_balance_cents",
            "lifetime_billed_cents",
            "suspension_count",
        ):
            assert data[ledger] is not None, f"{ledger} must start at 0, not null"


class TestDeviceRegistrationAndRetrieval:
    """A device registered from the fleet assessment and never yet placed."""

    def test_get_device_returns_the_stored_row_and_its_initialised_meters(self, api):
        """The assessment inputs come back verbatim beside an empty metering history.

        PRD: "That inventory becomes the device population, and a `FleetOpsController`
        records each asset with its owning `contract_id`, its hosting `site_id`, the
        customer's own `asset_tag` (non-empty, and unique within the contract — a repeat
        reports `ERR_ASSET_TAG_DUPLICATE`), the manufacturer's `model_code` (non-empty),
        the manufacturer's `rated_monthly_duty_cycle` (at least 1, and later the
        denominator of the right-sizing utilization ratio), and four
        total-cost-of-ownership baseline figures captured during the assessment:
        `assessed_monthly_mono_pages` and `assessed_monthly_color_pages` (each zero or
        greater) describing the volume the asset was running before the contract,
        `baseline_cost_micro_dollars_per_page` (at least 1) describing the customer's
        pre-contract cost per page, and `baseline_overhead_cents_per_month` (zero or
        greater) describing the fixed help-desk, storage and administration overhead
        allocated to that asset each month."
        PRD: "A freshly recorded asset lands at `lifecycle_state` `ASSESSED` and
        `supply_state` `SUPPLY_OK`, with `toner_level_pct` at 100."
        PRD: "Its metering history is empty: `last_accepted_mono_meter` and
        `last_accepted_color_meter` are 0, `last_read_at` is null, `lifetime_mono_pages`,
        `lifetime_color_pages`, `pages_since_last_cartridge`, `offline_exception_count`
        and `waste_event_count` are all 0, `secure_release_enrolled` is false,
        `right_sizing_action` is `NONE`, `refresh_due` is false, and both
        `replaced_by_device_id` and `removal_order_id` are null."

        Design: Corner/entities/retrieval_device_returns_stored_and_system_initialised_fields
        """
        contract, site = _contract_with_site()
        device = create_device(contract["id"], site["id"], **DEVICE_INPUT)

        response = api.get_device(device["id"], OPS)

        data = validate_success(response)
        assert_device(data)
        assert_fields(
            data,
            contract_id=contract["id"],
            site_id=site["id"],
            **DEVICE_INPUT,
            lifecycle_state="ASSESSED",
            supply_state="SUPPLY_OK",
            toner_level_pct=100,
            last_accepted_mono_meter=0,
            last_accepted_color_meter=0,
            lifetime_mono_pages=0,
            lifetime_color_pages=0,
            pages_since_last_cartridge=0,
            offline_exception_count=0,
            waste_event_count=0,
            secure_release_enrolled=False,
            right_sizing_action="NONE",
            refresh_due=False,
        )
        assert data["last_read_at"] is None, "last_read_at is null before any reading"
        assert data["replaced_by_device_id"] is None, "replaced_by_device_id starts null"
        assert data["removal_order_id"] is None, "removal_order_id starts null"

    def test_device_create_without_asset_tag_is_rejected_and_persists_nothing(self, api):
        """asset_tag has no default, so omitting it is a request-shape failure.

        PRD: "**Request shape.** Every required body field is present, every field has
        its declared type, every enum field carries a declared member, and every numeric
        field respects its declared range — including `limit` between 1 and 100 and a
        non-negative `offset` on list endpoints. Otherwise `ERR_INVALID_REQUEST` (422).
        Applies to every endpoint."
        PRD: "That inventory becomes the device population, and a `FleetOpsController`
        records each asset with its owning `contract_id`, its hosting `site_id`, the
        customer's own `asset_tag` (non-empty, and unique within the contract — a repeat
        reports `ERR_ASSET_TAG_DUPLICATE`), the manufacturer's `model_code` (non-empty),
        the manufacturer's `rated_monthly_duty_cycle` (at least 1, and later the
        denominator of the right-sizing utilization ratio), and four
        total-cost-of-ownership baseline figures captured during the assessment:
        `assessed_monthly_mono_pages` and `assessed_monthly_color_pages` (each zero or
        greater) describing the volume the asset was running before the contract,
        `baseline_cost_micro_dollars_per_page` (at least 1) describing the customer's
        pre-contract cost per page, and `baseline_overhead_cents_per_month` (zero or
        greater) describing the fixed help-desk, storage and administration overhead
        allocated to that asset each month."

        Design: Corner/entities/required_fields_device_create_without_asset_tag_is_rejected
        """
        contract, site = _contract_with_site()
        payload = device_payload(contract["id"], site["id"])
        payload.pop("asset_tag")

        response = api.create_device(payload, OPS)

        validate_error(response, "ERR_INVALID_REQUEST", 422)
        rows, meta = validate_paginated(
            api.list_devices(OPS, params={"contract_id": contract["id"], "limit": 100})
        )
        assert rows == [], f"a rejected registration must persist nothing, got {rows}"
        assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


class TestDeviceListing:
    """The device list endpoint as a reverse lookup on Device.contract_id."""

    def test_contract_filter_and_page_size_report_the_unpaginated_total(self, api):
        """Two of three matching rows come back, but the total counts all three.

        PRD: "Device listings accept `contract_id`, `site_id`,
        `replaced_by_device_id`, `removal_order_id`, `lifecycle_state` and
        `supply_state`."
        PRD: "`limit` controls page size: it defaults to 10, may be no smaller than 1
        and no larger than 100."
        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` (the number of rows matching the filters before pagination) and
        `has_more` (true when more rows remain beyond the returned page)."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/listing_devices_filters_by_contract_and_reports_pagination_totals
        """
        first_contract, first_site = _contract_with_site()
        mine = [
            create_device(first_contract["id"], first_site["id"], asset_tag=f"MPS-100{n}")["id"]
            for n in (1, 2, 3)
        ]
        other_contract, other_site = _contract_with_site()
        stranger = create_device(other_contract["id"], other_site["id"], asset_tag="MPS-2001")

        response = api.list_devices(
            OPS, params={"contract_id": first_contract["id"], "limit": 2, "offset": 0}
        )

        rows, meta = validate_paginated(response)
        assert [row["id"] for row in rows] == mine[:2], (
            f"expected the first two devices of the contract in created_at order, got "
            f"{[row['id'] for row in rows]}"
        )
        assert_fields(meta, limit=2, offset=0, total_count=3, has_more=True)
        assert stranger["id"] not in [row["id"] for row in rows], (
            "a device of another contract must never appear under this filter"
        )


class TestResourceNotFound:
    """A well-formed but unknown path identifier on each single-row read."""

    @pytest.mark.parametrize(
        ("reader", "unknown_id", "error_id", "role"),
        [
            pytest.param(
                "get_device", "11111111-1111-4111-8111-111111111111",
                "ERR_DEVICE_NOT_FOUND", "OPS", id="device",
            ),
            pytest.param(
                "get_site", "22222222-2222-4222-8222-222222222222",
                "ERR_SITE_NOT_FOUND", "AM", id="site",
            ),
            pytest.param(
                "get_service_contract", "33333333-3333-4333-8333-333333333333",
                "ERR_CONTRACT_NOT_FOUND", "AM", id="contract",
            ),
            pytest.param(
                "get_billing_period", "44444444-4444-4444-8444-444444444444",
                "ERR_PERIOD_NOT_FOUND", "BA", id="billing_period",
            ),
            pytest.param(
                "get_meter_read", "55555555-5555-4555-8555-555555555555",
                "ERR_METER_READ_NOT_FOUND", "OPS", id="meter_read",
            ),
            pytest.param(
                "get_billing_statement", "66666666-6666-4666-8666-666666666666",
                "ERR_STATEMENT_NOT_FOUND", "BA", id="statement",
            ),
            pytest.param(
                "get_consumable_order", "77777777-7777-4777-8777-777777777777",
                "ERR_ORDER_NOT_FOUND", "OPS", id="consumable_order",
            ),
            pytest.param(
                "get_service_ticket", "88888888-8888-4888-8888-888888888888",
                "ERR_TICKET_NOT_FOUND", "OPS", id="service_ticket",
            ),
            pytest.param(
                "get_quarterly_review", "99999999-9999-4999-8999-999999999999",
                "ERR_REVIEW_NOT_FOUND", "AM", id="quarterly_review",
            ),
            pytest.param(
                "get_removal_order", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "ERR_REMOVAL_ORDER_NOT_FOUND", "AM", id="removal_order",
            ),
        ],
    )
    def test_unknown_path_id_answers_with_the_error_of_its_own_resource_type(
        self, api, reader, unknown_id, error_id, role
    ):
        """Each read reports the 404 code of the type it addresses, never a generic one.

        PRD: "When a path names a parent and a child, the parent must resolve before the
        child is looked at, and the first identifier that fails to resolve determines the
        error."
        PRD: "Every failure of this kind carries HTTP 404 with the code specific to the
        missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_METER_READ_NOT_FOUND`,
        `ERR_PERIOD_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_TICKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or
        `ERR_REMOVAL_ORDER_NOT_FOUND`."
        PRD: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/not_found_unknown_path_ids_return_the_resource_specific_404
        """
        headers = {"AM": AM, "BA": BA, "OPS": OPS}[role]

        response = getattr(api, reader)(unknown_id, headers)

        error = validate_error(response, error_id, 404)
        assert error["message"].strip(), (
            f"{error_id} must carry a human-readable message, got {error!r}"
        )


class TestDeclaredDefaults:
    """Optional inputs left out of the body come back at their declared defaults."""

    def test_contract_optional_terms_default_when_omitted(self, api):
        """Four omitted commercial options land on 4, 24, 9,500 and 0.

        PRD: "Four further inputs are optional and default when omitted:
        `response_sla_hours_critical` defaults to 4 hours and must lie between 1 and 72;
        `response_sla_hours_standard` defaults to a full day at 24 hours and must lie
        between 1 and 168; `labor_rate_cents_per_hour` defaults to 9,500 cents — $95 an
        hour — and must be zero or greater; and `early_termination_fee_cents` defaults to
        0 and must be zero or greater. A newly created contract's `status` is `DRAFT`."

        Design: Corner/entities/defaults_omitted_optional_inputs_take_their_declared_defaults
        """
        response = api.create_service_contract(dict(MINIMAL_CONTRACT_INPUT), AM)

        data = validate_success(response, 201)
        assert_fields(
            data,
            response_sla_hours_critical=4,
            response_sla_hours_standard=24,
            labor_rate_cents_per_hour=9_500,
            early_termination_fee_cents=0,
            status="DRAFT",
        )
        assert_fields(fetch_contract(data["id"]), response_sla_hours_critical=4,
                      response_sla_hours_standard=24, labor_rate_cents_per_hour=9_500,
                      early_termination_fee_cents=0)

    def test_site_optional_inputs_default_and_secure_release_starts_unconfigured(self, api):
        """toner_unit_cap falls back to 4 while network_vlan_tag stays null.

        PRD: "Two optional inputs shape the site's consumables behaviour and its network:
        `toner_unit_cap` defaults to 4 and must be at least 1, and `network_vlan_tag`
        defaults to null and, when supplied, must lie between 1 and 4094."
        PRD: "A new site starts with `secure_release_state` at `UNCONFIGURED`,
        `release_method` at `NONE` and `open_toner_units` at 0."

        Design: Corner/entities/defaults_omitted_optional_inputs_take_their_declared_defaults
        """
        contract = create_contract(**MINIMAL_CONTRACT_INPUT)

        response = api.create_site(
            {"contract_id": contract["id"], "name": "Plant 1", "address_region": "NE-01"}, AM
        )

        data = validate_success(response, 201)
        assert_site(data)
        assert_fields(
            data,
            toner_unit_cap=4,
            secure_release_state="UNCONFIGURED",
            release_method="NONE",
            open_toner_units=0,
        )
        assert data["network_vlan_tag"] is None, (
            f"an omitted network_vlan_tag must stay null, got {data['network_vlan_tag']!r}"
        )
        assert fetch_site(data["id"])["network_vlan_tag"] is None, (
            "the stored site must also keep network_vlan_tag null"
        )

    def test_technician_travel_buffer_defaults_to_thirty_minutes(self, api):
        """An omitted travel buffer becomes 30, with no dispatches yet counted.

        PRD: "Field service is delivered by technicians the `AccountManager` registers
        with a `full_name` (non-empty), a `home_region` (non-empty, upper-case) that must
        match a site's `address_region` for that technician to be dispatchable there, a
        `skill_level` of `L1`, `L2` or `L3`, and optionally a `travel_buffer_minutes` that
        defaults to 30 and must lie between 0 and 120."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of
        tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or
        `ONSITE`."

        Design: Corner/entities/defaults_omitted_optional_inputs_take_their_declared_defaults
        """
        response = api.create_technician(
            {"full_name": "Tess Rowan", "home_region": "NE-01", "skill_level": "L3"}, AM
        )

        data = validate_success(response, 201)
        assert_technician(data)
        assert_fields(data, travel_buffer_minutes=30, open_dispatch_count=0)

    def test_device_color_capable_defaults_to_false(self, api):
        """The single optional registration input defaults to a monochrome asset.

        PRD: "That inventory becomes the device population, and a `FleetOpsController`
        records each asset with its owning `contract_id`, its hosting `site_id`, the
        customer's own `asset_tag` (non-empty, and unique within the contract — a repeat
        reports `ERR_ASSET_TAG_DUPLICATE`), the manufacturer's `model_code` (non-empty),
        the manufacturer's `rated_monthly_duty_cycle` (at least 1, and later the
        denominator of the right-sizing utilization ratio), and four
        total-cost-of-ownership baseline figures captured during the assessment:
        `assessed_monthly_mono_pages` and `assessed_monthly_color_pages` (each zero or
        greater) describing the volume the asset was running before the contract,
        `baseline_cost_micro_dollars_per_page` (at least 1) describing the customer's
        pre-contract cost per page, and `baseline_overhead_cents_per_month` (zero or
        greater) describing the fixed help-desk, storage and administration overhead
        allocated to that asset each month. One optional input, `color_capable`, defaults
        to false."

        Design: Corner/entities/defaults_omitted_optional_inputs_take_their_declared_defaults
        """
        contract, site = _contract_with_site()
        payload = device_payload(contract["id"], site["id"])
        payload.pop("color_capable")

        response = api.create_device(payload, OPS)

        data = validate_success(response, 201)
        assert_fields(data, color_capable=False, pages_since_last_cartridge=0)
        assert_fields(fetch_device(data["id"]), color_capable=False)


class TestActiveDeviceCountTracksPlacement:
    """The derived headcount follows physical installation, not registration."""

    def test_active_device_count_rises_only_when_each_asset_is_placed(self, api):
        """Two registered but unplaced assets count for nothing until placement.

        PRD: "`active_device_count` is the number of that contract's devices whose
        `lifecycle_state` is `PLACED`, `NETWORKED`, `ACTIVE` or `SERVICE_HOLD` —
        assessed-but-unplaced, retrieved and removed assets are excluded."
        PRD: "A `FieldTechnician` records physical installation, driving `ASSESSED →
        PLACED`; this requires the governing contract to be `ACTIVE` (otherwise
        `ERR_CONTRACT_NOT_ACTIVE`) and, on success, adds 1 to the contract's
        `active_device_count` and increments the device's `version`."

        Design: Corner/entities/computed_fields_active_device_count_tracks_placement_not_registration
        """
        env = setup_print_environment(devices=2, device_stage="ASSESSED")
        first, second = env["device_ids"]
        tech = env["tech_headers"]

        assert_fields(fetch_contract(env["contract_id"]), active_device_count=0)

        placed = validate_success(api.place_device(first, tech))
        assert_fields(placed, lifecycle_state="PLACED", version=2)
        assert_fields(fetch_contract(env["contract_id"]), active_device_count=1)

        validate_success(api.place_device(second, tech))
        assert_fields(fetch_contract(env["contract_id"]), active_device_count=2)


class TestServerMintedSystemFields:
    """Identity, timestamps and the optimistic-concurrency version are the server's.

    None of these four fields may be supplied by a client, and `version` advances
    by exactly one per mutation of the row.
    """

    def test_id_timestamps_and_version_are_minted_and_advanced_by_the_server(self, api):
        """A UUID id, three-digit UTC timestamps, and version 1 then 2 then 3.

        PRD: "Every resource is addressed by an `id` that the server mints as a UUID."
        PRD: "Identifiers carry no type prefix, and clients must never construct or
        predict one."
        PRD: "Alongside `id`, most resources expose `created_at` and `updated_at` as ISO
        8601 UTC timestamps with three fractional digits, plus an integer `version` that
        starts at 1 on creation and increases by exactly 1 on every mutation of that row."
        PRD: "On success the contract's `version` increases by 1."
        PRD: "The move `ACTIVE → SUSPENDED` copies that reason into `suspension_reason`,
        adds 1 to `suspension_count` and increments the contract's `version`."

        Design: Corner/entities/system_fields_id_timestamps_and_version_are_server_minted
        """
        created = validate_success(api.create_service_contract(dict(FULL_CONTRACT_INPUT), AM), 201)

        assert is_valid_uuid(created["id"]), f"id must be a bare UUID, got {created['id']!r}"
        assert ":" not in created["id"] and "_" not in created["id"], (
            f"identifiers carry no type prefix, got {created['id']!r}"
        )
        _assert_utc_with_three_fractional_digits(created["created_at"], "created_at")
        _assert_utc_with_three_fractional_digits(created["updated_at"], "updated_at")
        assert_fields(created, version=1)

        add_cost_tier(created["id"])
        activated = activate_contract(created["id"])
        assert_fields(activated, status="ACTIVE", version=2)

        suspended = validate_success(
            api.suspend_service_contract(created["id"], suspend_payload(reason="DISPUTE"), AM)
        )
        assert_fields(
            suspended,
            status="SUSPENDED",
            suspension_reason="DISPUTE",
            suspension_count=1,
            version=3,
        )
        _assert_utc_with_three_fractional_digits(suspended["updated_at"], "updated_at")
        assert_service_contract(suspended)
        assert_fields(fetch_contract(created["id"]), version=3, suspension_count=1)


class TestRequestShapeConstraints:
    """Enum members outside the declared set and numbers outside the declared range."""

    def test_unknown_release_method_is_rejected_and_leaves_the_site_untouched(self, api):
        """FACE_ID is not a declared release method, so nothing is configured.

        PRD: "**Request shape.** Every required body field is present, every field has
        its declared type, every enum field carries a declared member, and every numeric
        field respects its declared range — including `limit` between 1 and 100 and a
        non-negative `offset` on list endpoints. Otherwise `ERR_INVALID_REQUEST` (422).
        Applies to every endpoint."
        PRD: "A `CustomerAdmin` whose `X-User-ID` equals the site's own identifier submits
        a `release_method` (`BADGE` or `PIN` for a real configuration; `NONE` is the
        unconfigured default the field starts at), a `probe_result`, and optionally a
        `network_vlan_tag`."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_numbers_are_rejected
        """
        _contract, site = _contract_with_site(network_vlan_tag=2_001)

        response = api.configure_secure_release(
            site["id"],
            {"release_method": "FACE_ID", "probe_result": "PASS", "network_vlan_tag": 2_001},
            make_customer_admin_headers(site["id"]),
        )

        validate_error(response, "ERR_INVALID_REQUEST", 422)
        assert_fields(
            fetch_site(site["id"]),
            secure_release_state="UNCONFIGURED",
            release_method="NONE",
            network_vlan_tag=2_001,
        )

    def test_vlan_tag_above_the_declared_ceiling_is_rejected(self, api):
        """9,000 sits outside 1 through 4,094, so the probe never runs.

        PRD: "**Request shape.** Every required body field is present, every field has
        its declared type, every enum field carries a declared member, and every numeric
        field respects its declared range — including `limit` between 1 and 100 and a
        non-negative `offset` on list endpoints. Otherwise `ERR_INVALID_REQUEST` (422).
        Applies to every endpoint."
        PRD: "Two optional inputs shape the site's consumables behaviour and its network:
        `toner_unit_cap` defaults to 4 and must be at least 1, and `network_vlan_tag`
        defaults to null and, when supplied, must lie between 1 and 4094."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_numbers_are_rejected
        """
        _contract, site = _contract_with_site(network_vlan_tag=2_001)

        response = api.configure_secure_release(
            site["id"],
            {"release_method": "PIN", "probe_result": "PASS", "network_vlan_tag": 9_000},
            make_customer_admin_headers(site["id"]),
        )

        validate_error(response, "ERR_INVALID_REQUEST", 422)
        assert_fields(
            fetch_site(site["id"]),
            secure_release_state="UNCONFIGURED",
            release_method="NONE",
            network_vlan_tag=2_001,
        )

    def test_term_shorter_than_the_declared_minimum_is_rejected(self, api):
        """A six-month term is below the twelve-month floor.

        PRD: "**Request shape.** Every required body field is present, every field has
        its declared type, every enum field carries a declared member, and every numeric
        field respects its declared range — including `limit` between 1 and 100 and a
        non-negative `offset` on list endpoints. Otherwise `ERR_INVALID_REQUEST` (422).
        Applies to every endpoint."
        PRD: "An `AccountManager` opens one by supplying the customer's legal name in
        `customer_name` (non-empty, at most 120 characters), the term length in
        `term_months` (at least 12 and at most 60), the service envelope in
        `included_service_scope`, the two contracted minimum volumes
        `minimum_mono_pages_per_period` and `minimum_color_pages_per_period` (each zero
        or greater), and the fixed `monthly_service_fee_cents` (zero or greater), which
        doubles as the base amount for response-time credits."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_numbers_are_rejected
        """
        payload = dict(MINIMAL_CONTRACT_INPUT, customer_name="Too Short", term_months=6,
                       monthly_service_fee_cents=1_000)

        response = api.create_service_contract(payload, AM)

        validate_error(response, "ERR_INVALID_REQUEST", 422)

    def test_page_size_above_one_hundred_is_rejected(self, api):
        """A limit of 500 is a request-shape failure, not a silently clamped page.

        PRD: "A `limit` outside the range 1 through 100, or a negative `offset`, is a
        request-shape failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_numbers_are_rejected
        """
        contract, site = _contract_with_site()
        create_device(contract["id"], site["id"])

        response = api.list_devices(OPS, params={"contract_id": contract["id"], "limit": 500})

        validate_error(response, "ERR_INVALID_REQUEST", 422)


class TestRateCardImmutability:
    """Rate-card rows are appended evidence, not editable records."""

    def test_cost_tier_rows_expose_only_an_id_and_a_created_at(self, api):
        """Two appended MONO bands carry neither updated_at nor version.

        PRD: "A `CostTier` row and a `StatementLine` row carry only `id` and
        `created_at`: both `updated_at` and `version` are absent from those two resource
        shapes, because rate-card rows are appended rather than edited and statement lines
        are immutable evidence of a completed pricing run."
        PRD: "Rate-card rows are append-only evidence: each carries an `id` and a
        `created_at` and nothing else from the common property set."
        PRD: "Two structural rules govern the ladder: the row at `tier_index` 1 must have
        a `from_page` of exactly 1, and at most one row per contract and `page_class` may
        carry a null `to_page`."

        Design: Corner/entities/immutability_cost_tier_rows_carry_no_version_and_no_update_endpoint
        """
        contract = create_contract(**MINIMAL_CONTRACT_INPUT)
        add_cost_tier(contract["id"], tier_index=1, from_page=1, to_page=20_000,
                      rate_micro_dollars_per_page=9_375)
        add_cost_tier(contract["id"], tier_index=2, from_page=20_001, to_page=None,
                      rate_micro_dollars_per_page=7_333)

        rows, meta = validate_paginated(api.list_cost_tiers(contract["id"], AM))

        assert meta["total_count"] == 2, f"expected both appended rows, got {rows}"
        for row in rows:
            assert_append_only_record(row)
            assert "updated_at" not in row, f"a rate-card row must not expose updated_at: {row}"
            assert "version" not in row, f"a rate-card row must not expose version: {row}"
        assert_fields(rows[0], tier_index=1, from_page=1, to_page=20_000,
                      rate_micro_dollars_per_page=9_375, page_class="MONO")
        assert_fields(rows[1], tier_index=2, from_page=20_001,
                      rate_micro_dollars_per_page=7_333, page_class="MONO")
        assert rows[1]["to_page"] is None, "the unbounded top band keeps a null to_page"
        # The owning contract, by contrast, carries the full common quartet.
        parent = fetch_contract(contract["id"])
        assert "updated_at" in parent and "version" in parent, (
            f"a contract must still expose updated_at and version: {parent}"
        )


class TestParentResolution:
    """A child may only be created under parents that already exist."""

    def test_cost_tier_under_an_unknown_contract_path_id_is_a_contract_404(self, api):
        """The path contract resolves first, so an unknown one wins the error.

        PRD: "When a path names a parent and a child, the parent must resolve before the
        child is looked at, and the first identifier that fails to resolve determines the
        error."
        PRD: "Every failure of this kind carries HTTP 404 with the code specific to the
        missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_METER_READ_NOT_FOUND`,
        `ERR_PERIOD_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_TICKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or
        `ERR_REMOVAL_ORDER_NOT_FOUND`."

        Design: Corner/entities/parent_relationships_child_creation_requires_existing_parent_ids
        """
        response = api.create_cost_tier(
            "33333333-3333-4333-8333-333333333333",
            {
                "page_class": "MONO",
                "tier_index": 1,
                "from_page": 1,
                "to_page": None,
                "rate_micro_dollars_per_page": 9_375,
            },
            AM,
        )

        validate_error(response, "ERR_CONTRACT_NOT_FOUND", 404)

    def test_device_naming_an_unknown_site_in_the_body_is_a_site_404(self, api):
        """A body-supplied parent identifier is resolved exactly like a path one.

        PRD: "The same catalogue applies to identifiers supplied inside a request body
        rather than in the path."
        PRD: "A `contract_id`, `site_id`, `device_id`, `billing_period_id`,
        `technician_id` or successor device identifier that names no existing row produces
        the corresponding not-found code with HTTP 404 — a body-supplied successor device
        that does not exist reports `ERR_DEVICE_NOT_FOUND`, exactly as a path-supplied
        device would."

        Design: Corner/entities/parent_relationships_child_creation_requires_existing_parent_ids
        """
        contract = create_contract(**MINIMAL_CONTRACT_INPUT)
        payload = device_payload(contract["id"], "22222222-2222-4222-8222-222222222222")

        response = api.create_device(payload, OPS)

        validate_error(response, "ERR_SITE_NOT_FOUND", 404)
        rows, meta = validate_paginated(
            api.list_devices(OPS, params={"contract_id": contract["id"], "limit": 100})
        )
        assert rows == [], f"an unresolvable parent must persist no device, got {rows}"
        assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


def _closed_period_with_two_priced_devices():
    """Two mono devices, one accepted reading each, then a closed period.

    The period is made closeable by sweeping it rather than by publishing a
    provisional projection, so the contract's only statement is the FINAL one.
    A provisional statement is not deleted at close — PRD deletes it only when a
    later provisional supersedes it — so publishing one here would leave each
    device owning two historical lines and defeat the reverse-lookup assertion.
    Both devices already hold an accepted reading covering the period, so the
    sweep manufactures no placeholder and leaves exception_open_count at 0.
    """
    env = setup_print_environment(
        contract=dict(MINIMAL_CONTRACT_INPUT),
        mono_tiers=((1, 1, None, 9_375),),
        devices=2,
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    first, second = env["device_ids"]
    submit_automated_read(first, env["period_id"], mono_meter=5_000,
                          coverage_start=PERIOD_START, coverage_end=COVERAGE_END)
    submit_automated_read(second, env["period_id"], mono_meter=1_000,
                          coverage_start=PERIOD_START, coverage_end=COVERAGE_END)
    set_clock(PERIOD_END)
    run_sweep(env["period_id"])
    env["statement"] = close_period(env["period_id"])
    return env


class TestPerDeviceStatementLines:
    """A device's historical statement lines, reached through the device itself."""

    def test_each_device_reverse_lookup_returns_only_its_own_priced_line(self, api):
        """5,000 pages price to 4,688 cents and 1,000 pages to 938 cents.

        PRD: "Sub-resource listings — a contract's rate-card rows, a contract's quarterly
        reviews, a site's parts-locker rows, a statement's lines and a device's historical
        statement lines — exist purely as reverse lookups."
        PRD: "They read the child collection filtered to the parent named in the path and
        never create or modify anything."
        PRD: "Each `StatementLine` records its parent `statement_id`, the `device_id` it
        prices, the `page_class`, the `pages` it covers, the `rate_micro_dollars_per_page`
        copied from the statement's selected rate for that class, and an `amount_cents`
        computed as the pages multiplied by that rate, divided by 10,000, and rounded half
        up to a whole cent."

        Design: Corner/entities/foreign_key_validation_statement_lines_reachable_from_their_device
        """
        env = _closed_period_with_two_priced_devices()
        statement = env["statement"]
        first, second = env["device_ids"]

        expected = {first: (5_000, 4_688), second: (1_000, 938)}
        for device_id, (pages, amount_cents) in expected.items():
            rows, meta = validate_paginated(api.list_device_statement_lines(device_id, BA))

            assert meta["total_count"] == 1, (
                f"device {device_id} must own exactly one monochrome line, got {rows}"
            )
            assert_statement_line(rows[0])
            assert_fields(
                rows[0],
                statement_id=statement["id"],
                device_id=device_id,
                page_class="MONO",
                pages=pages,
                rate_micro_dollars_per_page=9_375,
                amount_cents=amount_cents,
            )

    def test_the_two_device_lines_sum_to_the_statement_usage_subtotal(self, api):
        """4,688 plus 938 is 5,626, and that is both the subtotal and the total.

        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted lines'
        `amount_cents`."
        PRD: "Lines are emitted device by device in ascending order of the device's
        `created_at`, and within each device the monochrome line comes before the colour
        line."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents` plus
        `service_labor_cents` plus `waste_penalty_cents`, **minus** `sla_credit_cents`."

        Design: Corner/entities/foreign_key_validation_statement_lines_reachable_from_their_device
        """
        env = _closed_period_with_two_priced_devices()
        statement = env["statement"]
        first, second = env["device_ids"]

        rows, meta = validate_paginated(api.list_statement_lines(statement["id"], BA))

        assert meta["total_count"] == 2, f"expected one line per device, got {rows}"
        assert [row["device_id"] for row in rows] == [first, second], (
            f"lines are emitted in device created_at order, got "
            f"{[row['device_id'] for row in rows]}"
        )
        assert [row["amount_cents"] for row in rows] == [4_688, 938], (
            f"each line rounds to whole cents before summation, got "
            f"{[row['amount_cents'] for row in rows]}"
        )
        assert_lines_sum_to_usage_subtotal(rows, statement)
        assert_fields(
            statement,
            variant="FINAL",
            usage_subtotal_cents=5_626,
            shortfall_cents=0,
            waste_penalty_cents=0,
            sla_credit_cents=0,
            total_cents=5_626,
        )
        assert_statement_total_is_consistent(statement)
