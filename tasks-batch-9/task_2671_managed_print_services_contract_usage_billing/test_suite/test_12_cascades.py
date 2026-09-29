"""Multi-hop cascades: one call, four rows moved.

Both suites drive a single request and then walk the whole chain of rows it is
required to touch — the reading and its device, the device's supply dimension
and the cartridge order that dimension mints, and the site and contract
consumables counters that order commits — plus the mirror-image chain that a
sanitization runs in the opposite direction.
"""

from datetime import datetime

from test_helpers import (
    FLEET_OPS_USER_ID,
    api_client,
    assert_consumable_order,
    assert_device_dimensions,
    assert_fields,
    assert_meter_read,
    assert_removal_order,
    fetch_billing_period,
    fetch_consumable_order,
    fetch_contract,
    fetch_device,
    fetch_site,
    get_success_data,
    list_orders_for_device,
    make_fleet_ops_headers,
    meter_read_payload,
    sanitize_payload,
    set_clock,
    setup_environment_with_auto_toner_order,
    setup_print_environment,
    setup_removal_order,
    validate_success,
)

# One FULL-scope contract, a flat MONO ladder at 9,375 micro-dollars, a single
# mono device rated at 20,000 pages a month hosted at a site capped at four
# open cartridge units, and an OPEN August billing period.
CONTRACT = {"included_service_scope": "FULL", "monthly_service_fee_cents": 70_000}
SITE = {"name": "Plant 1", "toner_unit_cap": 4}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
READ_CLOCK = "2026-08-10T00:00:00Z"
COVERAGE_END = "2026-08-09T00:00:00Z"
COLLECTION_DUE = "2026-08-20T00:00:00Z"

MONO_METER = 4_000
LOW_TONER_PCT = 12
AUTO_UNIT_PRICE_CENTS = 8_900
CERTIFICATE_REF = "CERT-OW3-77"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp so two spellings of one instant compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _active_mono_device_with_open_period():
    """An ACTIVE mono device in SUPPLY_OK at 100 percent toner, clock mid-period."""
    return setup_print_environment(
        contract=CONTRACT,
        site=SITE,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock=READ_CLOCK,
    )


def _submit_low_toner_read(env):
    """The reading under test: 4,000 mono pages and 12 percent toner remaining."""
    return validate_success(
        api_client.submit_automated_meter_read(
            meter_read_payload(
                env["device_id"],
                env["period_id"],
                mono_meter=MONO_METER,
                color_meter=0,
                toner_level_pct=LOW_TONER_PCT,
                coverage_start=PERIOD_START,
                coverage_end=COVERAGE_END,
            ),
            make_fleet_ops_headers(FLEET_OPS_USER_ID),
        ),
        201,
    )


class TestAcceptedReadingCascade:
    """One automated intake call, four hops: reading, device, supply, commitments."""

    def test_first_two_hops_write_the_reading_and_the_device_watermarks(self):
        """The reading is ACCEPTED and every device counter it feeds moves with it.

        PRD: "The primary path is automated: a data-collection agent runs out of band on the customer's network and pushes absolute counter values, and because that agent is not itself an API client, the provider exposes a test-driving intake capability under a reserved internal namespace that a `FleetOpsController` uses to emit exactly the payload the agent would have sent, stamping `source` as `AUTOMATED`."
        PRD: "The candidate monochrome delta is the submitted `mono_meter` less the device's `last_accepted_mono_meter`, and the candidate colour delta is the submitted `color_meter` less the device's `last_accepted_color_meter`."
        PRD: "The first hop writes the reading: `status` `ACCEPTED`, the two deltas, `exception_reason` back to `NONE`."
        PRD: "The second hop writes the device: `last_accepted_mono_meter` and `last_accepted_color_meter` take the submitted absolute values, `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`, `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge` grows by the sum of the two deltas, and the device's `version` increments."

        Design: Difficulty/transitive_cascade/read_acceptance_cascades_to_device_counters_auto_order_and_site_commitment
        """
        env = _active_mono_device_with_open_period()

        read = _submit_low_toner_read(env)

        assert_meter_read(read)
        assert_fields(
            read,
            status="ACCEPTED",
            source="AUTOMATED",
            exception_reason="NONE",
            mono_delta=MONO_METER,
            color_delta=0,
        )
        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=MONO_METER,
            last_accepted_color_meter=0,
            toner_level_pct=LOW_TONER_PCT,
            lifetime_mono_pages=MONO_METER,
            lifetime_color_pages=0,
            pages_since_last_cartridge=MONO_METER,
        )
        assert _instant(device["last_read_at"]) == _instant(COVERAGE_END), (
            f"last_read_at should be the reading's coverage_end {COVERAGE_END}, "
            f"got {device['last_read_at']}"
        )

    def test_third_hop_moves_the_supply_dimension_and_mints_one_automatic_order(self):
        """Twelve percent toner drives SUPPLY_OK to SUPPLY_ORDERED and raises the cartridge.

        PRD: "When an accepted reading leaves a device's `toner_level_pct` at or below 15 and the device's `supply_state` is `SUPPLY_OK`, the supply dimension moves `SUPPLY_OK → SUPPLY_LOW` and the device's `version` increments."
        PRD: "When both hold, the supply dimension moves `SUPPLY_LOW → SUPPLY_ORDERED` and a cartridge order is created with `trigger_source` `AUTO_THRESHOLD`, a `quantity` of exactly 1, a `unit_price_cents` of 8,900 — the provider's standard automatic-replenishment unit price of $89 per cartridge — and a `part_type` chosen from the device and the reading: `TONER_COLOR` when the device is `color_capable` **and** the accepted reading's `color_delta` is greater than zero, and `TONER_BLACK` in every other case."
        PRD: "Neither dimension gates the other: a device on `SERVICE_HOLD` can still cycle its supply dimension, and a device in `SUPPLY_BLOCKED` is still meterable."

        Design: Difficulty/transitive_cascade/read_acceptance_cascades_to_device_counters_auto_order_and_site_commitment
        """
        env = _active_mono_device_with_open_period()

        _submit_low_toner_read(env)

        assert_device_dimensions(
            fetch_device(env["device_id"]), lifecycle_state="ACTIVE", supply_state="SUPPLY_ORDERED"
        )
        orders = list_orders_for_device(env["device_id"])
        assert len(orders) == 1, f"expected exactly one cartridge order, got {orders}"
        order = orders[0]
        assert_consumable_order(order)
        assert_fields(
            order,
            device_id=env["device_id"],
            trigger_source="AUTO_THRESHOLD",
            part_type="TONER_BLACK",
            quantity=1,
            unit_price_cents=AUTO_UNIT_PRICE_CENTS,
        )

    def test_the_minted_order_snapshots_the_cartridge_page_count_without_flagging_waste(self):
        """A first cartridge at 4,000 pages snapshots the count and is never waste.

        PRD: "At the moment any order is created — automatic or manual — the device's current `pages_since_last_cartridge` is snapshotted into the order's `pages_since_last_cartridge_at_order`."
        PRD: "The order is then flagged as waste, in the derived `waste_flagged` field, exactly when two things hold together: the device has at least one earlier cartridge order that reached `DELIVERED`, and the snapshotted page count is **strictly less than 3,000 pages**."
        PRD: "A device's very first cartridge is therefore never a waste event however few pages it has printed, and a snapshot of exactly 3,000 pages is not waste either — the comparison is strict."
        PRD: "Each device exposes a derived `waste_event_count`: the number of its orders that are flagged as waste and have not been cancelled."

        Design: Difficulty/transitive_cascade/read_acceptance_cascades_to_device_counters_auto_order_and_site_commitment
        """
        env = _active_mono_device_with_open_period()

        _submit_low_toner_read(env)

        order = list_orders_for_device(env["device_id"])[0]
        assert_fields(
            order,
            pages_since_last_cartridge_at_order=MONO_METER,
            waste_flagged=False,
        )
        assert_fields(fetch_device(env["device_id"]), waste_event_count=0)

    def test_fourth_hop_commits_the_units_on_the_hosting_site_and_the_contract(self):
        """The order's own creation is what raises the site tally and the committed spend.

        PRD: "The fourth hop is caused by the third: if a cartridge order was created, the hosting site's `open_toner_units` grows by that order's `quantity` and the contract's `consumables_committed_cents` grows by that order's committed value."
        PRD: "That last field is derived rather than supplied: it is the total quantity across every still-open cartridge order — orders whose `status` is `ORDERED` — destined for a device at that site, and it is the quantity that `toner_unit_cap` bounds."
        PRD: "`consumables_committed_cents` is the total committed value of the contract's cartridge orders that are still open, that is, whose `status` is `ORDERED`."
        PRD: "The order is created with `trigger_source` `MANUAL` and a `status` of `ORDERED`; its `committed_cents` is derived as the `quantity` multiplied by the `unit_price_cents`."

        Design: Difficulty/transitive_cascade/read_acceptance_cascades_to_device_counters_auto_order_and_site_commitment
        """
        env = _active_mono_device_with_open_period()
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

        _submit_low_toner_read(env)

        order = list_orders_for_device(env["device_id"])[0]
        assert_fields(order, status="ORDERED", committed_cents=AUTO_UNIT_PRICE_CENTS)
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]), consumables_committed_cents=AUTO_UNIT_PRICE_CENTS
        )

    def test_an_accepted_reading_leaves_the_period_exception_counter_at_zero(self):
        """The counter recomputation runs alongside the cascade, and finds nothing open.

        PRD: "Independently of all of this, the target period's `exception_open_count` is recomputed — upward when the reading lands in `EXCEPTION`, and back down when a previously open reading becomes `ACCEPTED`."
        PRD: "`exception_open_count` is derived: it is the number of readings assigned to that period whose `status` is `PENDING_VALIDATION` or `EXCEPTION`."

        Design: Difficulty/transitive_cascade/read_acceptance_cascades_to_device_counters_auto_order_and_site_commitment
        """
        env = _active_mono_device_with_open_period()

        _submit_low_toner_read(env)

        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)


def _collected_removal_order_over_a_device_with_an_open_cartridge():
    """A COLLECTED removal order whose one RETRIEVED device still owns an open order.

    The device's accepted reading left it at 12 percent toner, so the automatic
    replenishment path already minted one open cartridge order: the site carries
    one open unit and the contract carries 8,900 cents of committed spend.
    """
    env = setup_environment_with_auto_toner_order(
        contract=CONTRACT,
        site=SITE,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        toner_level_pct=LOW_TONER_PCT,
        mono_meter=MONO_METER,
        coverage_start=PERIOD_START,
        coverage_end=COVERAGE_END,
        clock=READ_CLOCK,
    )
    removal_order = setup_removal_order(env["contract_id"], COLLECTION_DUE, stage="SCHEDULED")
    set_clock(COLLECTION_DUE)
    env["removal_order"] = get_success_data(
        api_client.collect_removal_order(removal_order["id"], env["tech_headers"])
    )
    return env


def _sanitize(env):
    """The call under test: record 3-pass overwrite with its certificate."""
    return validate_success(
        api_client.sanitize_removal_order(
            env["removal_order"]["id"],
            sanitize_payload("OVERWRITE_3PASS", CERTIFICATE_REF),
            env["tech_headers"],
        )
    )


class TestSanitizationCascade:
    """One sanitization call, four hops: order, devices, commitments unwound."""

    def test_first_hop_writes_the_evidence_and_moves_the_order_to_sanitized(self):
        """COLLECTED becomes SANITIZED and both evidence fields land on the order.

        PRD: "A `FieldTechnician` records it by supplying a `sanitization_method` of `CRYPTO_ERASE`, `OVERWRITE_3PASS` or `PHYSICAL_DESTRUCTION` — the placeholder value `NONE` is not an acceptable method — together with a non-empty `sanitization_certificate_ref`; a missing method or missing certificate reports `ERR_SANITIZATION_EVIDENCE_MISSING`."
        PRD: "Sanitization writes both values onto the order and drives `COLLECTED → SANITIZED`; attempting it from any other state reports `ERR_REMOVAL_INVALID_STATE`."
        PRD: "Those stamped devices are the order's **covered devices**, and `device_count` is derived as the number of devices carrying that order's identifier."

        Design: Difficulty/transitive_cascade/sanitize_cascades_device_removal_order_cancellation_and_commitment_release
        """
        env = _collected_removal_order_over_a_device_with_an_open_cartridge()

        order = _sanitize(env)

        assert_removal_order(order)
        assert_fields(
            order,
            status="SANITIZED",
            sanitization_method="OVERWRITE_3PASS",
            sanitization_certificate_ref=CERTIFICATE_REF,
            device_count=1,
        )

    def test_second_hop_removes_every_covered_device_and_unenrols_it(self):
        """The retrieved device reaches the terminal REMOVED state and loses enrolment.

        PRD: "The second hop transitions every covered device `RETRIEVED → REMOVED`, setting `secure_release_enrolled` back to false and incrementing each device's `version`; `REMOVED` is the terminal lifecycle state."

        Design: Difficulty/transitive_cascade/sanitize_cascades_device_removal_order_cancellation_and_commitment_release
        """
        env = _collected_removal_order_over_a_device_with_an_open_cartridge()
        before = fetch_device(env["device_id"])
        assert_fields(before, lifecycle_state="RETRIEVED", secure_release_enrolled=True)

        _sanitize(env)

        assert_fields(
            fetch_device(env["device_id"]),
            lifecycle_state="REMOVED",
            secure_release_enrolled=False,
        )

    def test_third_hop_recomputes_the_device_count_and_cancels_the_open_cartridge(self):
        """The removals are what drop active_device_count and cancel the toner order.

        PRD: "The third hop follows from the removals: the contract's `active_device_count` is recomputed downward from the resulting device set, and every cartridge order of every removed device that is still in `ORDERED` status is transitioned to `CANCELLED` with `cancel_reason` `DEVICE_REMOVED`."
        PRD: "`active_device_count` is the number of that contract's devices whose `lifecycle_state` is `PLACED`, `NETWORKED`, `ACTIVE` or `SERVICE_HOLD` — assessed-but-unplaced, retrieved and removed assets are excluded."

        Design: Difficulty/transitive_cascade/sanitize_cascades_device_removal_order_cancellation_and_commitment_release
        """
        env = _collected_removal_order_over_a_device_with_an_open_cartridge()
        order_id = env["order"]["id"]
        assert_fields(fetch_consumable_order(order_id), status="ORDERED")

        _sanitize(env)

        assert_fields(fetch_contract(env["contract_id"]), active_device_count=0)
        assert_fields(
            fetch_consumable_order(order_id),
            status="CANCELLED",
            cancel_reason="DEVICE_REMOVED",
        )

    def test_fourth_hop_releases_the_site_and_contract_consumables_commitments(self):
        """The cancellation is what returns both counters to their pre-order values.

        PRD: "The fourth hop follows from those cancellations: each affected site's `open_toner_units` and the contract's `consumables_committed_cents` are recomputed downward by the cancelled orders' quantities and committed amounts."
        PRD: "It simultaneously drives the contract `ACTIVE → TERMINATING` with a contract `version` increment, and stamps `removal_order_id` onto every device of that contract whose `lifecycle_state` is `PLACED`, `NETWORKED`, `ACTIVE` or `SERVICE_HOLD`."

        Design: Difficulty/transitive_cascade/sanitize_cascades_device_removal_order_cancellation_and_commitment_release
        """
        env = _collected_removal_order_over_a_device_with_an_open_cartridge()
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]), consumables_committed_cents=AUTO_UNIT_PRICE_CENTS
        )

        _sanitize(env)

        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=0,
            status="TERMINATING",
        )
