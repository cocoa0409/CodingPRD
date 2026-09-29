"""Business-rule validations: uniqueness scopes, window arithmetic, temporal gates,
site-level aggregates, parts-driven branch legality and the settlement precondition.

Every rejection here proves two things at once: the exact `error_id` the contract
names, and that the refused write left no row and moved no counter.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    add_cost_tier,
    adjust_part_stock,
    api_client,
    assert_fields,
    assert_settlement_waterfall,
    billing_period_payload,
    cancel_order_payload,
    close_period,
    consumable_order_payload,
    create_billing_period,
    create_contract,
    create_device,
    create_quarterly_review,
    create_site,
    create_ticket,
    device_payload,
    dispatch_ticket,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_part_stock,
    fetch_removal_order,
    fetch_service_ticket,
    fetch_site,
    generate_provisional_statement,
    get_success_data,
    is_iso8601_timestamp,
    list_orders_for_device,
    make_field_technician_headers,
    open_order_for_device,
    quarterly_review_payload,
    set_clock,
    setup_print_environment,
    setup_removal_order,
    submit_automated_read,
    validate_error,
    validate_success,
)

ACCOUNT_MANAGER = TEST_USERS["account_manager_headers"]
BILLING_ANALYST = TEST_USERS["billing_analyst_headers"]
FLEET_OPS = TEST_USERS["fleet_ops_headers"]

AUGUST_START = "2026-08-01T00:00:00Z"
SEPTEMBER_START = "2026-09-01T00:00:00Z"
OCTOBER_START = "2026-10-01T00:00:00Z"
STRADDLING_START = "2026-08-15T00:00:00Z"
STRADDLING_END = "2026-09-15T00:00:00Z"

MONO_RATE_MICRO_DOLLARS = 9_375
SECOND_CONTRACT = {
    "customer_name": "Vantage Health",
    "term_months": 24,
    "included_service_scope": "FULL",
    "monthly_service_fee_cents": 32_000,
}


# ---------------------------------------------------------------------------
# Uniqueness family — one contract already holding one of each unique thing
# ---------------------------------------------------------------------------
def _uniqueness_environment():
    """Contract A holding one device, one MONO band and one quarterly review,
    plus an untouched contract B with its own site."""
    contract_a = create_contract(customer_name="Larkin Mfg")
    add_cost_tier(
        contract_a["id"],
        page_class="MONO",
        tier_index=1,
        from_page=1,
        to_page=20_000,
        rate_micro_dollars_per_page=MONO_RATE_MICRO_DOLLARS,
    )
    site_a = create_site(contract_a["id"], name="Plant 1", address_region="NE-01")
    device_a = create_device(contract_a["id"], site_a["id"], asset_tag="MPS-0001")
    review_a = create_quarterly_review(contract_a["id"], quarter_label="2026-Q3")

    contract_b = create_contract(**SECOND_CONTRACT)
    site_b = create_site(
        contract_b["id"], name="Clinic A", address_region="NE-02", network_vlan_tag=2101
    )
    return {
        "contract_a_id": contract_a["id"],
        "site_a_id": site_a["id"],
        "device_a_id": device_a["id"],
        "review_a_id": review_a["id"],
        "contract_b_id": contract_b["id"],
        "site_b_id": site_b["id"],
    }


def _uniqueness_census(env):
    """Every row count and contract counter a refused uniqueness write could disturb."""
    contract_id = env["contract_a_id"]
    devices = get_success_data(
        api_client.list_devices(FLEET_OPS, params={"contract_id": contract_id, "limit": 100})
    )
    tiers = get_success_data(
        api_client.list_cost_tiers(contract_id, ACCOUNT_MANAGER, params={"limit": 100})
    )
    reviews = get_success_data(
        api_client.list_contract_quarterly_reviews(
            contract_id, ACCOUNT_MANAGER, params={"limit": 100}
        )
    )
    contract = fetch_contract(contract_id)
    return {
        "device_count": len(devices),
        "device_ids": sorted(row["id"] for row in devices),
        "tier_count": len(tiers),
        "review_count": len(reviews),
        "review_ids": sorted(row["id"] for row in reviews),
        "active_device_count": contract["active_device_count"],
        "contract_version": contract["version"],
    }


def _repeat_asset_tag_inside_contract_a(env):
    return api_client.create_device(
        device_payload(
            env["contract_a_id"],
            env["site_a_id"],
            asset_tag="MPS-0001",
            model_code="XR-M2100",
            rated_monthly_duty_cycle=8_000,
            assessed_monthly_mono_pages=3_000,
            baseline_cost_micro_dollars_per_page=19_000,
            baseline_overhead_cents_per_month=3_000,
        ),
        FLEET_OPS,
    )


def _band_that_intersects_the_existing_mono_band(env):
    return api_client.create_cost_tier(
        env["contract_a_id"],
        {
            "page_class": "MONO",
            "tier_index": 2,
            "from_page": 15_000,
            "to_page": 30_000,
            "rate_micro_dollars_per_page": 7_333,
        },
        ACCOUNT_MANAGER,
    )


def _repeat_quarter_label_inside_contract_a(env):
    return api_client.create_quarterly_review(
        quarterly_review_payload(env["contract_a_id"], quarter_label="2026-Q3"),
        ACCOUNT_MANAGER,
    )


UNIQUENESS_FAMILIES = [
    ("duplicate_asset_tag", _repeat_asset_tag_inside_contract_a, ApiErrorId.ERR_ASSET_TAG_DUPLICATE.value),
    ("intersecting_tier_band", _band_that_intersects_the_existing_mono_band, ApiErrorId.ERR_TIER_BAND_CONFLICT.value),
    ("duplicate_quarter_label", _repeat_quarter_label_inside_contract_a, ApiErrorId.ERR_QUARTER_DUPLICATE.value),
]


class TestPerContractUniquenessScopes:
    """Asset tags, rate-card bands and quarter labels are unique per contract."""

    @pytest.mark.parametrize(
        "family,attempt,expected_error_id",
        UNIQUENESS_FAMILIES,
        ids=[row[0] for row in UNIQUENESS_FAMILIES],
    )
    def test_repeat_inside_the_same_contract_is_rejected_and_writes_nothing(
        self, family, attempt, expected_error_id
    ):
        """Each of the three uniqueness scopes rejects its repeat and leaves the row set alone.

        PRD: "`asset_tag` is unique within a contract (`ERR_ASSET_TAG_DUPLICATE`); a
        rate-card row must not duplicate the combination of contract, `page_class` and
        `tier_index`, nor may its page band intersect an existing band of the same
        contract and `page_class` (`ERR_TIER_BAND_CONFLICT`); `quarter_label` is unique
        within a contract (`ERR_QUARTER_DUPLICATE`)."
        PRD: "Appending a row that duplicates an existing combination of contract,
        `page_class` and `tier_index`, or whose band intersects an existing band of the
        same contract and `page_class`, is rejected with `ERR_TIER_BAND_CONFLICT`."
        PRD: "Creating one takes just the `contract_id` and a `quarter_label` matching
        the four-digit-year-then-quarter form such as `2026-Q3`, unique within the
        contract on pain of `ERR_QUARTER_DUPLICATE`."

        Design: Corner/validations/violation_to_error_uniqueness_family_rejects_duplicate_tag_band_and_quarter
        """
        env = _uniqueness_environment()
        before = _uniqueness_census(env)
        assert before["device_count"] == 1, f"setup should hold one device: {before}"
        assert before["tier_count"] == 1, f"setup should hold one rate-card row: {before}"
        assert before["review_count"] == 1, f"setup should hold one review: {before}"

        validate_error(attempt(env), expected_error_id)

        after = _uniqueness_census(env)
        assert after == before, (
            f"the refused {family} write must leave no trace: expected {before}, got {after}"
        )

    def test_the_same_asset_tag_is_accepted_under_a_different_contract(self):
        """Asset-tag uniqueness is scoped to one contract, so contract B may reuse the tag.

        PRD: "`asset_tag` is unique within a contract (`ERR_ASSET_TAG_DUPLICATE`); a
        rate-card row must not duplicate the combination of contract, `page_class` and
        `tier_index`, nor may its page band intersect an existing band of the same
        contract and `page_class` (`ERR_TIER_BAND_CONFLICT`); `quarter_label` is unique
        within a contract (`ERR_QUARTER_DUPLICATE`)."

        Design: Corner/validations/violation_to_error_uniqueness_family_rejects_duplicate_tag_band_and_quarter
        """
        env = _uniqueness_environment()

        response = api_client.create_device(
            device_payload(
                env["contract_b_id"],
                env["site_b_id"],
                asset_tag="MPS-0001",
                model_code="XR-M2100",
                rated_monthly_duty_cycle=8_000,
            ),
            FLEET_OPS,
        )

        device = validate_success(response, 201)
        assert_fields(device, asset_tag="MPS-0001", lifecycle_state="ASSESSED")
        contract_b_devices = get_success_data(
            api_client.list_devices(
                FLEET_OPS, params={"contract_id": env["contract_b_id"], "limit": 100}
            )
        )
        assert len(contract_b_devices) == 1, (
            f"contract B should now hold exactly one device, got {len(contract_b_devices)}"
        )
        contract_a_devices = get_success_data(
            api_client.list_devices(
                FLEET_OPS, params={"contract_id": env["contract_a_id"], "limit": 100}
            )
        )
        assert len(contract_a_devices) == 1, (
            f"contract A must be untouched, got {len(contract_a_devices)} devices"
        )


# ---------------------------------------------------------------------------
# Billing-period window arithmetic — one August period already open
# ---------------------------------------------------------------------------
def _august_period_on_one_of_two_contracts():
    """Two active contracts; only the first one already owns the August window."""
    contract_a = create_contract(customer_name="Larkin Mfg")
    add_cost_tier(contract_a["id"], rate_micro_dollars_per_page=MONO_RATE_MICRO_DOLLARS)
    activate_contract(contract_a["id"])
    period_a = create_billing_period(contract_a["id"], AUGUST_START, SEPTEMBER_START)

    contract_b = create_contract(**SECOND_CONTRACT)
    add_cost_tier(contract_b["id"], rate_micro_dollars_per_page=MONO_RATE_MICRO_DOLLARS)
    activate_contract(contract_b["id"])
    return {
        "contract_a_id": contract_a["id"],
        "period_a_id": period_a["id"],
        "contract_b_id": contract_b["id"],
    }


def _period_census(contract_id):
    """The period row set of one contract plus every version those rows carry."""
    periods = get_success_data(
        api_client.list_billing_periods(
            BILLING_ANALYST, params={"contract_id": contract_id, "limit": 100}
        )
    )
    return {
        "count": len(periods),
        "windows": sorted((row["period_start"], row["period_end"]) for row in periods),
        "versions": sorted((row["id"], row["version"]) for row in periods),
    }


class TestBillingPeriodWindowArithmetic:
    """Touching period windows open; intersecting ones are refused."""

    def test_a_window_starting_exactly_where_august_ends_opens_a_fresh_period(self):
        """September may begin on the instant August ends, and opens with null totals.

        PRD: "`period_start` must be strictly earlier than `period_end`, and the window
        must not intersect another period of the same contract — touching endpoints are
        fine, so a January period ending exactly where a February period begins is legal
        — with any violation reporting `ERR_PERIOD_WINDOW_OVERLAP`."
        PRD: "A new period has `status` `OPEN`, a `sweep_run_count` of 0, an
        `exception_open_count` of 0, and both `provisional_total_cents` and
        `final_total_cents` null."

        Design: Corner/validations/satisfaction_to_pass_touching_period_windows_pass_while_overlapping_windows_error
        """
        env = _august_period_on_one_of_two_contracts()

        response = api_client.create_billing_period(
            billing_period_payload(
                env["contract_a_id"],
                period_start=SEPTEMBER_START,
                period_end=OCTOBER_START,
            ),
            BILLING_ANALYST,
        )

        period = validate_success(response, 201)
        assert_fields(
            period,
            contract_id=env["contract_a_id"],
            period_start=SEPTEMBER_START,
            period_end=OCTOBER_START,
            status="OPEN",
            sweep_run_count=0,
            exception_open_count=0,
            provisional_total_cents=None,
            final_total_cents=None,
        )
        census = _period_census(env["contract_a_id"])
        assert census["count"] == 2, f"the contract should now own two periods: {census}"
        assert_fields(fetch_billing_period(env["period_a_id"]), status="OPEN", version=1)

    def test_a_window_straddling_august_is_rejected_and_opens_nothing(self):
        """A mid-August to mid-September window genuinely intersects, so nothing is written.

        PRD: "The practical consequence is that two windows which merely touch — where
        the earlier window's upper bound equals the later window's lower bound — do
        **not** overlap and are always allowed; only genuinely intersecting windows are
        rejected."
        PRD: "`period_start` must be strictly earlier than `period_end`, and the window
        must not intersect another period of the same contract — touching endpoints are
        fine, so a January period ending exactly where a February period begins is legal
        — with any violation reporting `ERR_PERIOD_WINDOW_OVERLAP`."

        Design: Corner/validations/satisfaction_to_pass_touching_period_windows_pass_while_overlapping_windows_error
        """
        env = _august_period_on_one_of_two_contracts()
        before = _period_census(env["contract_a_id"])
        assert before["count"] == 1, f"setup should own exactly one period: {before}"

        response = api_client.create_billing_period(
            billing_period_payload(
                env["contract_a_id"],
                period_start=STRADDLING_START,
                period_end=STRADDLING_END,
            ),
            BILLING_ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_PERIOD_WINDOW_OVERLAP.value)
        after = _period_census(env["contract_a_id"])
        assert after == before, (
            f"the refused window must leave no period behind: expected {before}, got {after}"
        )

    def test_the_same_august_window_is_free_under_a_different_contract(self):
        """Window exclusivity is scoped to one contract, so contract B may open August too.

        PRD: "`period_start` must be strictly earlier than `period_end`, and the window
        must not intersect another period of the same contract — touching endpoints are
        fine, so a January period ending exactly where a February period begins is legal
        — with any violation reporting `ERR_PERIOD_WINDOW_OVERLAP`."

        Design: Corner/validations/satisfaction_to_pass_touching_period_windows_pass_while_overlapping_windows_error
        """
        env = _august_period_on_one_of_two_contracts()

        response = api_client.create_billing_period(
            billing_period_payload(
                env["contract_b_id"],
                period_start=AUGUST_START,
                period_end=SEPTEMBER_START,
            ),
            BILLING_ANALYST,
        )

        period = validate_success(response, 201)
        assert_fields(
            period,
            contract_id=env["contract_b_id"],
            period_start=AUGUST_START,
            period_end=SEPTEMBER_START,
            status="OPEN",
        )
        assert _period_census(env["contract_a_id"])["count"] == 1, (
            "contract A must still own exactly one period"
        )


# ---------------------------------------------------------------------------
# Temporal gate — a scheduled collection that is not yet due
# ---------------------------------------------------------------------------
CLOCK_BEFORE_COLLECTION = "2026-09-02T00:00:00Z"
COLLECTION_MOMENT = "2026-09-03T00:00:00Z"


def _removal_order_scheduled_for_tomorrow():
    """One active device covered by a removal order due a day after the clock."""
    env = setup_print_environment(
        contract={"customer_name": "Larkin Mfg"},
        site={"name": "Plant 1"},
        devices=1,
        clock=CLOCK_BEFORE_COLLECTION,
    )
    env["order"] = setup_removal_order(
        env["contract_id"],
        COLLECTION_MOMENT,
        stage="SCHEDULED",
        technician_id=env["technician_id"],
    )
    env["order_id"] = env["order"]["id"]
    return env


class TestCollectionIsRefusedBeforeItIsDue:
    """The collection gate compares the logical clock against `scheduled_for`."""

    def test_collecting_a_day_early_is_refused_and_moves_no_hardware(self):
        """A clock short of `scheduled_for` blocks collection and leaves every row as it was.

        PRD: "Collection requires the logical clock to have reached `scheduled_for`, with
        equality sufficient, failing which it reports `ERR_COLLECTION_NOT_DUE`; and it
        requires that no covered device has a service ticket still in `DISPATCHED`,
        `PARTS_HOLD` or `ONSITE`, because hardware cannot be carted away while an engineer
        is working on it."

        Design: Corner/validations/temporal_validation_collection_before_the_scheduled_moment_is_rejected
        """
        env = _removal_order_scheduled_for_tomorrow()
        order_before = fetch_removal_order(env["order_id"])
        device_before = fetch_device(env["device_id"])
        contract_before = fetch_contract(env["contract_id"])
        assert_fields(order_before, status="SCHEDULED", scheduled_for=COLLECTION_MOMENT)

        response = api_client.collect_removal_order(
            env["order_id"], make_field_technician_headers(env["technician_id"])
        )

        validate_error(response, ApiErrorId.ERR_COLLECTION_NOT_DUE.value)
        assert_fields(
            fetch_removal_order(env["order_id"]),
            status="SCHEDULED",
            version=order_before["version"],
            device_count=order_before["device_count"],
            settled_at=None,
        )
        assert_fields(
            fetch_device(env["device_id"]),
            lifecycle_state="ACTIVE",
            version=device_before["version"],
            removal_order_id=env["order_id"],
        )
        assert_fields(
            fetch_contract(env["contract_id"]),
            status="TERMINATING",
            version=contract_before["version"],
            active_device_count=contract_before["active_device_count"],
        )

    def test_collecting_on_the_scheduled_instant_retrieves_the_covered_device(self):
        """Equality is sufficient, so the collection lands the moment the clock arrives.

        PRD: "A `FieldTechnician` then records physical collection, driving `SCHEDULED →
        COLLECTED`."
        PRD: "Collection transitions every covered device to `RETRIEVED` — `PLACED →
        RETRIEVED`, `NETWORKED → RETRIEVED`, `ACTIVE → RETRIEVED` or `SERVICE_HOLD →
        RETRIEVED`, each incrementing that device's `version`, with the `SERVICE_HOLD`
        case additionally requiring that no in-flight ticket remains for that device —
        recomputes the order's `device_count`, and increments the order's `version`."

        Design: Corner/validations/temporal_validation_collection_before_the_scheduled_moment_is_rejected
        """
        env = _removal_order_scheduled_for_tomorrow()
        device_before = fetch_device(env["device_id"])
        set_clock(COLLECTION_MOMENT)

        response = api_client.collect_removal_order(
            env["order_id"], make_field_technician_headers(env["technician_id"])
        )

        order = validate_success(response, 200)
        assert_fields(order, status="COLLECTED", device_count=1, settled_at=None)
        device_after = fetch_device(env["device_id"])
        assert_fields(
            device_after, lifecycle_state="RETRIEVED", removal_order_id=env["order_id"]
        )
        assert device_after["version"] == device_before["version"] + 1, (
            "the retrieved device's version must increment exactly once: "
            f"{device_before['version']} -> {device_after['version']}"
        )


# ---------------------------------------------------------------------------
# Site aggregate — a one-unit toner cap already spent by the first device
# ---------------------------------------------------------------------------
MID_AUGUST_CLOCK = "2026-08-15T00:00:00Z"
READ_COVERAGE_END = "2026-08-08T00:00:00Z"
AUTO_TONER_PRICE_CENTS = 8_900


def _site_at_its_toner_unit_cap():
    """Two devices under a `toner_unit_cap` of 1: the first spends it, the second is blocked."""
    env = setup_print_environment(
        contract={"customer_name": "Larkin Mfg"},
        site={"name": "Plant 1", "toner_unit_cap": 1},
        devices=2,
        period=(AUGUST_START, SEPTEMBER_START),
        clock=MID_AUGUST_CLOCK,
    )
    first_device_id, second_device_id = env["device_ids"]
    for device_id in (first_device_id, second_device_id):
        submit_automated_read(
            device_id,
            env["period_id"],
            mono_meter=4_000,
            toner_level_pct=10,
            coverage_start=AUGUST_START,
            coverage_end=READ_COVERAGE_END,
        )
    env["first_device_id"] = first_device_id
    env["second_device_id"] = second_device_id
    env["first_order"] = open_order_for_device(first_device_id)
    return env


class TestSiteTonerUnitCap:
    """The site-wide open-cartridge tally, not the device, decides a manual order."""

    def test_a_second_manual_order_breaching_the_site_cap_is_refused_outright(self):
        """The first device's automatic unit fills the cap, so the second device is refused.

        PRD: "Because a manual order **supersedes** whatever the device already has open,
        the hoarding check nets out the superseded units: the site's current
        `open_toner_units`, minus the `quantity` of the single existing order for that
        device in `ORDERED` status (zero when there is none), plus the requested
        `quantity`, must not exceed the site's `toner_unit_cap`, and a breach reports
        `ERR_TONER_CAP_EXCEEDED`."
        PRD: "When either condition fails — an open order already exists, or one more unit
        would breach the site cap — replenishment is **suppressed** rather than forced
        through: the supply dimension moves `SUPPLY_LOW → SUPPLY_BLOCKED`, no cartridge
        order is created at all, and the device's `version` increments."

        Design: Corner/validations/aggregate_validation_second_toner_order_breaches_the_site_unit_cap
        """
        env = _site_at_its_toner_unit_cap()
        blocked_device = fetch_device(env["second_device_id"])
        assert_fields(blocked_device, supply_state="SUPPLY_BLOCKED")
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1, toner_unit_cap=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_TONER_PRICE_CENTS,
        )

        response = api_client.create_consumable_order(
            consumable_order_payload(
                env["second_device_id"],
                blocked_device["version"],
                part_type="TONER_BLACK",
                unit_price_cents=AUTO_TONER_PRICE_CENTS,
                quantity=1,
            ),
            FLEET_OPS,
        )

        validate_error(response, ApiErrorId.ERR_TONER_CAP_EXCEEDED.value)
        assert list_orders_for_device(env["second_device_id"]) == [], (
            "the refused order must leave the blocked device with no order at all"
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_TONER_PRICE_CENTS,
        )
        assert_fields(
            fetch_device(env["second_device_id"]),
            supply_state="SUPPLY_BLOCKED",
            version=blocked_device["version"],
        )

    def test_releasing_the_first_unit_frees_the_cap_for_the_manual_order(self):
        """Cancelling the first cartridge returns the unit, and the manual order then lands.

        PRD: "The site's `open_toner_units` falls by the order's `quantity` and the
        contract's `consumables_committed_cents` falls by its `committed_cents`, so that
        both counters land back exactly on their pre-creation values, and the order's
        `version` increments."
        PRD: "The order is created with `trigger_source` `MANUAL` and a `status` of
        `ORDERED`; its `committed_cents` is derived as the `quantity` multiplied by the
        `unit_price_cents`."

        Design: Corner/validations/aggregate_validation_second_toner_order_breaches_the_site_unit_cap
        """
        env = _site_at_its_toner_unit_cap()
        get_success_data(
            api_client.cancel_consumable_order(
                env["first_order"]["id"], cancel_order_payload("WRONG_PART"), FLEET_OPS
            )
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)
        assert_fields(fetch_device(env["first_device_id"]), supply_state="SUPPLY_LOW")
        blocked_device = fetch_device(env["second_device_id"])

        response = api_client.create_consumable_order(
            consumable_order_payload(
                env["second_device_id"],
                blocked_device["version"],
                part_type="TONER_BLACK",
                unit_price_cents=AUTO_TONER_PRICE_CENTS,
                quantity=1,
            ),
            FLEET_OPS,
        )

        order = validate_success(response, 201)
        assert_fields(
            order,
            device_id=env["second_device_id"],
            trigger_source="MANUAL",
            status="ORDERED",
            quantity=1,
            unit_price_cents=AUTO_TONER_PRICE_CENTS,
            committed_cents=AUTO_TONER_PRICE_CENTS,
            waste_flagged=False,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_TONER_PRICE_CENTS,
        )
        assert_fields(fetch_device(env["second_device_id"]), supply_state="SUPPLY_ORDERED")


# ---------------------------------------------------------------------------
# Conditional branch — one stocked SKU and one absent SKU, two dispatches
# ---------------------------------------------------------------------------
DISPATCH_CLOCK = "2026-08-10T08:00:00Z"
STOCKED_SKU = "FUSER-9"
ABSENT_SKU = "DRUM-4"
FIRST_WINDOW = ("2026-08-11T09:00:00Z", "2026-08-11T13:00:00Z")
SECOND_WINDOW = ("2026-08-11T15:00:00Z", "2026-08-11T18:00:00Z")


def _two_dispatched_tickets_one_stocked_part():
    """Two dispatched tickets at one site: one needs a stocked SKU, one an absent SKU."""
    env = setup_print_environment(
        contract={"customer_name": "Larkin Mfg"},
        site={"name": "Plant 1"},
        devices=2,
        clock=DISPATCH_CLOCK,
    )
    adjust_part_stock(env["site_id"], STOCKED_SKU, 1)
    stocked_device_id, absent_device_id = env["device_ids"]

    stocked_ticket = create_ticket(
        stocked_device_id, env["site_id"], severity="STANDARD", part_sku=STOCKED_SKU
    )
    absent_ticket = create_ticket(
        absent_device_id, env["site_id"], severity="STANDARD", part_sku=ABSENT_SKU
    )
    dispatch_ticket(stocked_ticket["id"], env["technician_id"], *FIRST_WINDOW)
    dispatch_ticket(absent_ticket["id"], env["technician_id"], *SECOND_WINDOW)

    env["stocked_ticket_id"] = stocked_ticket["id"]
    env["absent_ticket_id"] = absent_ticket["id"]
    env["tech_headers"] = make_field_technician_headers(env["technician_id"])
    return env


class TestPartsAvailabilityDecidesTheLegalBranch:
    """The locker decides which of the two post-dispatch branches a ticket may take."""

    def test_declaring_a_hold_while_the_part_sits_on_the_shelf_is_refused(self):
        """A stocked SKU makes the hold branch illegal and consumes nothing.

        PRD: "A hold is only legitimate when the ticket actually names a `part_sku` and
        the locker row for that site and SKU is genuinely missing or sitting at an
        `on_hand_qty` of exactly 0; declaring a hold while the part is in fact available
        reports `ERR_PART_IS_AVAILABLE`."

        Design: Corner/validations/conditional_validation_parts_availability_decides_which_ticket_path_is_legal
        """
        env = _two_dispatched_tickets_one_stocked_part()
        ticket_before = fetch_service_ticket(env["stocked_ticket_id"])
        stock_before = fetch_part_stock(env["site_id"], STOCKED_SKU)
        assert_fields(ticket_before, status="DISPATCHED", hold_started_at=None)
        assert_fields(stock_before, part_sku=STOCKED_SKU, on_hand_qty=1)

        response = api_client.put_service_ticket_on_parts_hold(
            env["stocked_ticket_id"], env["tech_headers"]
        )

        validate_error(response, ApiErrorId.ERR_PART_IS_AVAILABLE.value)
        assert_fields(
            fetch_service_ticket(env["stocked_ticket_id"]),
            status="DISPATCHED",
            hold_started_at=None,
            parts_hold_hours=0,
            version=ticket_before["version"],
        )
        assert_fields(
            fetch_part_stock(env["site_id"], STOCKED_SKU),
            on_hand_qty=1,
            version=stock_before["version"],
        )

    def test_arriving_on_the_stocked_ticket_consumes_exactly_one_unit(self):
        """The available part makes the direct-arrival branch legal, and it takes one unit.

        PRD: "Arrival requires either a null `part_sku` or a locker row for the device's
        `site_id` and that SKU with `on_hand_qty` of at least 1; a missing row or a row at
        zero reports `ERR_PART_NOT_AVAILABLE`."
        PRD: "When a part is required, arrival consumes exactly one unit — the locker
        row's `on_hand_qty` falls by 1 and its `version` increments — and the ticket's
        `version` increments."
        PRD: "On this branch no hold time accrues and `parts_hold_hours` remains 0."

        Design: Corner/validations/conditional_validation_parts_availability_decides_which_ticket_path_is_legal
        """
        env = _two_dispatched_tickets_one_stocked_part()

        response = api_client.arrive_onsite(env["stocked_ticket_id"], env["tech_headers"])

        ticket = validate_success(response, 200)
        assert_fields(ticket, status="ONSITE", parts_hold_hours=0, hold_started_at=None)
        assert_fields(fetch_part_stock(env["site_id"], STOCKED_SKU), on_hand_qty=0)

    def test_arriving_on_the_ticket_whose_sku_is_absent_is_refused(self):
        """With no locker row at all the direct-arrival branch is illegal.

        PRD: "Arrival requires either a null `part_sku` or a locker row for the device's
        `site_id` and that SKU with `on_hand_qty` of at least 1; a missing row or a row at
        zero reports `ERR_PART_NOT_AVAILABLE`."

        Design: Corner/validations/conditional_validation_parts_availability_decides_which_ticket_path_is_legal
        """
        env = _two_dispatched_tickets_one_stocked_part()
        ticket_before = fetch_service_ticket(env["absent_ticket_id"])
        assert fetch_part_stock(env["site_id"], ABSENT_SKU) is None, (
            f"{ABSENT_SKU} must have no locker row before the attempt"
        )

        response = api_client.arrive_onsite(env["absent_ticket_id"], env["tech_headers"])

        validate_error(response, ApiErrorId.ERR_PART_NOT_AVAILABLE.value)
        assert_fields(
            fetch_service_ticket(env["absent_ticket_id"]),
            status="DISPATCHED",
            parts_hold_hours=0,
            hold_started_at=None,
            version=ticket_before["version"],
        )
        assert fetch_part_stock(env["site_id"], ABSENT_SKU) is None, (
            "the refused arrival must not conjure a locker row"
        )

    def test_declaring_a_hold_on_the_absent_sku_is_the_legal_branch(self):
        """The missing SKU makes the hold branch the legal one, and it stamps the clock.

        PRD: "The hold stamps `hold_started_at` with the logical clock and increments the
        ticket's `version`."

        Design: Corner/validations/conditional_validation_parts_availability_decides_which_ticket_path_is_legal
        """
        env = _two_dispatched_tickets_one_stocked_part()
        ticket_before = fetch_service_ticket(env["absent_ticket_id"])

        response = api_client.put_service_ticket_on_parts_hold(
            env["absent_ticket_id"], env["tech_headers"]
        )

        ticket = validate_success(response, 200)
        assert_fields(ticket, status="PARTS_HOLD", parts_hold_hours=0)
        assert ticket["hold_started_at"] is not None, (
            f"a parts hold must stamp hold_started_at: {ticket}"
        )
        assert is_iso8601_timestamp(ticket["hold_started_at"]), (
            f"hold_started_at must be an ISO 8601 instant: {ticket['hold_started_at']!r}"
        )
        assert ticket["version"] == ticket_before["version"] + 1, (
            "the hold must increment the ticket version exactly once: "
            f"{ticket_before['version']} -> {ticket['version']}"
        )
        assert fetch_part_stock(env["site_id"], STOCKED_SKU)["on_hand_qty"] == 1, (
            "a parts hold consumes no locker stock"
        )


# ---------------------------------------------------------------------------
# Cascading precondition — a sanitized order whose August period is still open
# ---------------------------------------------------------------------------
CLOCK_AFTER_PERIOD = "2026-09-02T00:00:00Z"
EARLY_TERMINATION_FEE_CENTS = 250_000
RESIDUAL_CREDIT_CENTS = 12_000
GROSS_SETTLEMENT_CENTS = 238_000
SANITIZATION_FEE_CENTS = 7_500
NET_SETTLEMENT_CENTS = 245_500
SANITIZATION_CERTIFICATE = "CERT-2026-0901"


def _sanitized_order_with_a_due_period_still_open():
    """One retired device, one August period left `PROVISIONAL` past its own end."""
    env = setup_print_environment(
        contract={
            "customer_name": "Larkin Mfg",
            "early_termination_fee_cents": EARLY_TERMINATION_FEE_CENTS,
        },
        site={"name": "Plant 1"},
        devices=1,
        period=(AUGUST_START, SEPTEMBER_START),
        clock=CLOCK_AFTER_PERIOD,
    )
    generate_provisional_statement(env["period_id"])
    env["order"] = setup_removal_order(
        env["contract_id"],
        CLOCK_AFTER_PERIOD,
        stage="SANITIZED",
        technician_id=env["technician_id"],
        sanitization_method="CRYPTO_ERASE",
        sanitization_certificate_ref=SANITIZATION_CERTIFICATE,
    )
    env["order_id"] = env["order"]["id"]
    return env


class TestSettlementWaitsForEveryDuePeriodToClose:
    """A period whose end has passed must be `CLOSED` before the settlement posts."""

    def test_settling_over_an_unclosed_august_period_is_refused_and_posts_nothing(self):
        """The `PROVISIONAL` August period blocks settlement and no money field moves.

        PRD: "It requires the contract to be in `TERMINATING`, and it requires that every
        billing period of the contract whose `period_end` is at or before the logical clock
        has `status` `CLOSED` — a period that is still genuinely running may remain `OPEN`,
        and its accepted pages settle as unbilled — failing which the request reports
        `ERR_SETTLEMENT_PERIOD_OPEN`."
        PRD: "Every billing period of the contract whose `period_end` is at or before the
        logical clock must be `CLOSED` — otherwise `ERR_SETTLEMENT_PERIOD_OPEN` (409)."

        Design: Corner/validations/cascading_validation_settlement_waits_for_every_due_period_to_close
        """
        env = _sanitized_order_with_a_due_period_still_open()
        order_before = fetch_removal_order(env["order_id"])
        contract_before = fetch_contract(env["contract_id"])
        period_before = fetch_billing_period(env["period_id"])
        assert_fields(order_before, status="SANITIZED", settled_at=None)
        assert_fields(period_before, status="PROVISIONAL", period_end=SEPTEMBER_START)

        response = api_client.settle_removal_order(env["order_id"], BILLING_ANALYST)

        validate_error(response, ApiErrorId.ERR_SETTLEMENT_PERIOD_OPEN.value)
        assert_fields(
            fetch_removal_order(env["order_id"]),
            status="SANITIZED",
            version=order_before["version"],
            settled_at=None,
            unbilled_pages_charge_cents=0,
            early_termination_fee_applied_cents=0,
            device_residual_credit_cents=0,
            gross_settlement_cents=0,
            sanitization_fee_cents=0,
            net_settlement_cents=0,
        )
        assert_fields(
            fetch_contract(env["contract_id"]),
            status="TERMINATING",
            version=contract_before["version"],
        )
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="PROVISIONAL",
            version=period_before["version"],
        )

    def test_closing_the_period_unblocks_the_pinned_settlement_waterfall(self):
        """Once August is `CLOSED` the settlement posts its waterfall and closes the contract.

        PRD: "`early_termination_fee_applied_cents` is the contract's
        `early_termination_fee_cents` when the logical clock is strictly earlier than the
        contract's `created_at` advanced by `term_months` calendar months, and 0 otherwise
        — a contract that has run its full term pays nothing to leave."
        PRD: "`device_residual_credit_cents` is 0 when the `sanitization_method` is
        `PHYSICAL_DESTRUCTION`, because destroyed hardware has no residual value; otherwise
        it is 12,000 cents — a $120 residual credit per returned asset — multiplied by the
        order's `device_count`."
        PRD: "The undiscounted sanitization base is 7,500 cents — $75 per asset —
        multiplied by the order's `device_count`."
        PRD: "`net_settlement_cents` is `gross_settlement_cents` plus
        `sanitization_fee_cents`, and it is the amount invoiced at settlement."
        PRD: "Settlement stamps `settled_at` from the logical clock, increments the order's
        `version`, and cascades the contract `TERMINATING → CLOSED` with a contract
        `version` increment."

        Design: Corner/validations/cascading_validation_settlement_waits_for_every_due_period_to_close
        """
        env = _sanitized_order_with_a_due_period_still_open()
        final_statement = close_period(env["period_id"])
        assert_fields(final_statement, variant="FINAL", total_cents=0)
        assert_fields(fetch_billing_period(env["period_id"]), status="CLOSED")

        response = api_client.settle_removal_order(env["order_id"], BILLING_ANALYST)

        order = validate_success(response, 200)
        assert_fields(
            order,
            status="SETTLED",
            device_count=1,
            unbilled_pages_charge_cents=0,
            early_termination_fee_applied_cents=EARLY_TERMINATION_FEE_CENTS,
            device_residual_credit_cents=RESIDUAL_CREDIT_CENTS,
            gross_settlement_cents=GROSS_SETTLEMENT_CENTS,
            sanitization_fee_cents=SANITIZATION_FEE_CENTS,
            net_settlement_cents=NET_SETTLEMENT_CENTS,
        )
        assert_settlement_waterfall(order)
        assert is_iso8601_timestamp(order["settled_at"]), (
            f"settled_at must be an ISO 8601 instant: {order['settled_at']!r}"
        )
        assert_fields(fetch_contract(env["contract_id"]), status="CLOSED")
