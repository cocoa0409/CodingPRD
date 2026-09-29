"""Gates that live on one entity but are enforced from the state of another.

Device activation reads the hosting site's secure print release state, and
period close reads the exception backlog of the readings assigned to it.  In
both suites the blocked call is unblocked only by a write on the *other*
entity, with no call against the blocked resource in between.
"""

from test_helpers import (
    ApiErrorId,
    assert_fields,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_site,
    list_reads_for_device,
    make_billing_analyst_headers,
    make_customer_admin_headers,
    make_fleet_ops_headers,
    meter_read_payload,
    resolve_exception_payload,
    run_sweep,
    secure_release_config_payload,
    set_clock,
    setup_print_environment,
    validate_error,
    validate_success,
)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
FLAT_MONO_TIERS = ((1, 1, None, 9_375),)
VLAN_TAG = 2001

OPS_HEADERS = make_fleet_ops_headers("ops-1")
SECOND_OPS_HEADERS = make_fleet_ops_headers("ops-2")
BILLING_HEADERS = make_billing_analyst_headers("ba-1")


def _networked_device_behind_a_deferred_site_probe():
    """An ACTIVE contract whose site probe deferred, leaving one NETWORKED device.

    The site sits in PENDING_VALIDATION with a `PIN` release method and a VLAN
    tag, so the device is exactly one legal transition away from ACTIVE and only
    the site's state stands in the way.
    """
    return setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=1,
        release_method="PIN",
        probe_result="DEFERRED",
        vlan_tag=VLAN_TAG,
        device_stage="NETWORKED",
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-16T00:00:00Z",
    )


def _intake_payload(device_id, period_id):
    return meter_read_payload(
        device_id,
        period_id,
        mono_meter=1_000,
        color_meter=0,
        toner_level_pct=80,
        coverage_start=PERIOD_START,
        coverage_end="2026-08-10T00:00:00Z",
    )


class TestDeviceActivationGatedOnTheSiteReleaseState:
    """The Device transition is legal on its own machine yet the Site row refuses it."""

    def test_activation_is_refused_while_the_hosting_site_is_pending_validation(self, api):
        """A NETWORKED device cannot enter service behind a deferred release probe.

        PRD: "Two guards apply here and they report different codes: the hosting site's `secure_release_state` must be exactly `CONFIGURED` — a site still `UNCONFIGURED`, still `PENDING_VALIDATION`, or sitting in `FAILED` blocks activation with `ERR_SECURE_RELEASE_NOT_CONFIGURED` — and the governing contract must be `ACTIVE`, failing which the report is `ERR_CONTRACT_NOT_ACTIVE`."
        PRD: "It writes `release_method`, writes `network_vlan_tag` only when one was supplied, sets `secure_release_state` to `PENDING_VALIDATION`, and increments the site's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_on_site_secure_release_state
        """
        env = _networked_device_behind_a_deferred_site_probe()
        assert_fields(
            fetch_site(env["site_id"]),
            secure_release_state="PENDING_VALIDATION",
            release_method="PIN",
            network_vlan_tag=VLAN_TAG,
        )

        response = api.activate_device(env["device_id"], OPS_HEADERS)

        validate_error(response, ApiErrorId.ERR_SECURE_RELEASE_NOT_CONFIGURED)
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="NETWORKED")

    def test_meter_intake_is_refused_for_the_device_the_site_gate_left_networked(self, api):
        """The refusal propagates one entity further: the device is not yet meterable.

        PRD: "The device's `lifecycle_state` is `ACTIVE` or `SERVICE_HOLD` — otherwise `ERR_DEVICE_NOT_METERABLE` (409). Applies to both meter-reading intake endpoints."
        PRD: "Only once a device reaches `ACTIVE` does meter-read intake become possible."

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_on_site_secure_release_state
        """
        env = _networked_device_behind_a_deferred_site_probe()

        response = api.submit_automated_meter_read(
            _intake_payload(env["device_id"], env["period_id"]), OPS_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_METERABLE)
        assert list_reads_for_device(env["device_id"]) == [], (
            "a refused intake must not persist a reading"
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_passing_the_site_probe_unblocks_the_device_transition(self, api):
        """A write on the Site alone is what lets the Device reach ACTIVE.

        PRD: "`probe_result` of `PASS` drives the site to `CONFIGURED`."
        PRD: "It also cascades onto the fleet: every device at that site whose `lifecycle_state` is `NETWORKED` has `secure_release_enrolled` set to true and its own `version` incremented by 1."
        PRD: "Finally a `FleetOpsController` brings the asset into billable service, driving `NETWORKED → ACTIVE` and incrementing `version`."

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_on_site_secure_release_state
        """
        env = _networked_device_behind_a_deferred_site_probe()
        validate_error(
            api.activate_device(env["device_id"], OPS_HEADERS),
            ApiErrorId.ERR_SECURE_RELEASE_NOT_CONFIGURED,
        )

        site = validate_success(
            api.configure_secure_release(
                env["site_id"],
                secure_release_config_payload(
                    release_method="PIN", probe_result="PASS", network_vlan_tag=VLAN_TAG
                ),
                make_customer_admin_headers(env["site_id"]),
            )
        )
        device = validate_success(api.activate_device(env["device_id"], OPS_HEADERS))

        assert_fields(site, secure_release_state="CONFIGURED", release_method="PIN")
        assert_fields(device, lifecycle_state="ACTIVE", secure_release_enrolled=True)

    def test_the_unblocked_device_accepts_the_same_reading_that_was_just_refused(self, api):
        """The identical intake payload validates once the site gate has opened.

        PRD: "The device's `lifecycle_state` is `ACTIVE` or `SERVICE_HOLD` — otherwise `ERR_DEVICE_NOT_METERABLE` (409). Applies to both meter-reading intake endpoints."
        PRD: "Otherwise the reading is `ACCEPTED`, and `mono_delta` and `color_delta` are written with the two candidate values."

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_on_site_secure_release_state
        """
        env = _networked_device_behind_a_deferred_site_probe()
        payload = _intake_payload(env["device_id"], env["period_id"])
        validate_error(
            api.submit_automated_meter_read(payload, OPS_HEADERS),
            ApiErrorId.ERR_DEVICE_NOT_METERABLE,
        )

        validate_success(
            api.configure_secure_release(
                env["site_id"],
                secure_release_config_payload(
                    release_method="PIN", probe_result="PASS", network_vlan_tag=VLAN_TAG
                ),
                make_customer_admin_headers(env["site_id"]),
            )
        )
        validate_success(api.activate_device(env["device_id"], OPS_HEADERS))
        read = validate_success(api.submit_automated_meter_read(payload, OPS_HEADERS), 201)

        assert_fields(read, status="ACCEPTED", exception_reason="NONE", mono_delta=1_000)
        assert_fields(fetch_device(env["device_id"]), last_accepted_mono_meter=1_000)
        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 1, f"exactly one reading should have persisted, got {len(reads)}"
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)


def _swept_period_with_one_open_offline_exception():
    """A SWEPT period holding a single DEVICE_OFFLINE exception, with the clock past period_end.

    The sweep is run by ``ops-1`` at 2026-08-28 against one ACTIVE device that
    submitted no readings, so exactly one SWEEP_ESTIMATE placeholder is minted.
    The clock then moves to ``period_end`` so the temporal close gate is already
    satisfied and only the exception backlog is left standing.
    """
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=1,
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-28T00:00:00Z",
    )
    run_sweep(env["period_id"], user_id="ops-1")
    exceptions = list_reads_for_device(env["device_id"], status="EXCEPTION")
    assert len(exceptions) == 1, f"the sweep should mint exactly one placeholder, got {exceptions}"
    env["exception_read"] = exceptions[0]
    set_clock(PERIOD_END)
    return env


class TestPeriodCloseGatedOnTheMeterReadExceptionBacklog:
    """The period's own machine permits CLOSED; one exception child forbids it."""

    def test_close_is_refused_while_one_swept_exception_remains_open(self, api):
        """The SWEPT period is past its end yet still carries an open exception.

        PRD: "The period's `exception_open_count` must be exactly 0 — no reading of the period may still be `PENDING_VALIDATION` or `EXCEPTION` — failing which the request reports `ERR_PERIOD_HAS_OPEN_EXCEPTIONS`."
        PRD: "`exception_open_count` is derived: it is the number of readings assigned to that period whose `status` is `PENDING_VALIDATION` or `EXCEPTION`."

        Design: Difficulty/cross_entity_state_dependency/period_close_gated_on_meter_read_exception_backlog
        """
        env = _swept_period_with_one_open_offline_exception()

        response = api.close_billing_period(env["period_id"], BILLING_HEADERS)

        validate_error(response, ApiErrorId.ERR_PERIOD_HAS_OPEN_EXCEPTIONS)
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="SWEPT",
            final_total_cents=None,
            exception_open_count=1,
            sweep_run_count=1,
        )

    def test_the_sweep_placeholder_is_a_sweep_estimate_in_device_offline_exception(self):
        """The blocking child is the sweep's own manufactured reading.

        PRD: "The sweep walks every device of the contract whose `lifecycle_state` is `ACTIVE` or `SERVICE_HOLD` and which has no `ACCEPTED` reading whose `coverage_end` falls inside the period window, and manufactures one placeholder reading per such device: `source` `SWEEP_ESTIMATE`, `status` `EXCEPTION`, `exception_reason` `DEVICE_OFFLINE`, `mono_meter` and `color_meter` copied from the device's current watermarks, `toner_level_pct` copied from the device's current level, `coverage_start` set to the period's `period_start` and `coverage_end` set to the logical clock value at sweep time."
        PRD: "The period then moves `OPEN → SWEPT` (or `SWEPT → SWEPT` on a re-run), its `sweep_run_count` increases by 1 and its `version` increments."

        Design: Difficulty/cross_entity_state_dependency/period_close_gated_on_meter_read_exception_backlog
        """
        env = _swept_period_with_one_open_offline_exception()

        assert_fields(
            fetch_meter_read(env["exception_read"]["id"]),
            source="SWEEP_ESTIMATE",
            status="EXCEPTION",
            exception_reason="DEVICE_OFFLINE",
            mono_delta=0,
            color_delta=0,
        )
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="SWEPT",
            sweep_run_count=1,
            exception_open_count=1,
        )

    def test_resolving_the_exception_by_a_second_operator_drives_the_backlog_to_zero(self, api):
        """A write on the reading — not on the period — is what clears the gate.

        PRD: "Resolution overwrites the reading's `mono_meter`, `color_meter` and `toner_level_pct` with the three corrected values, records the `resolution_note`, stamps `resolved_by_user_id` with the acting `X-User-ID`, increments the reading's `version`, and moves it `EXCEPTION → PENDING_VALIDATION` — after which **exactly the same validation runs again** and lands the reading either in `ACCEPTED`, with the full four-hop cascade above, or right back in `EXCEPTION`."
        PRD: "Independently of all of this, the target period's `exception_open_count` is recomputed — upward when the reading lands in `EXCEPTION`, and back down when a previously open reading becomes `ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/period_close_gated_on_meter_read_exception_backlog
        """
        env = _swept_period_with_one_open_offline_exception()

        read = validate_success(
            api.resolve_meter_read_exception(
                env["exception_read"]["id"],
                resolve_exception_payload(
                    corrected_mono_meter=5_000,
                    corrected_color_meter=0,
                    corrected_toner_level_pct=60,
                ),
                SECOND_OPS_HEADERS,
            )
        )

        assert_fields(
            read,
            status="ACCEPTED",
            exception_reason="NONE",
            source="SWEEP_ESTIMATE",
            mono_delta=5_000,
            color_delta=0,
            resolved_by_user_id="ops-2",
        )
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=5_000,
            lifetime_mono_pages=5_000,
            toner_level_pct=60,
        )
        assert_fields(
            fetch_billing_period(env["period_id"]), status="SWEPT", exception_open_count=0
        )

    def test_close_succeeds_once_the_backlog_is_clear_and_prices_the_corrected_pages(self, api):
        """The same close call now issues the FINAL statement over 5,000 corrected pages.

        PRD: "On the **FINAL** variant, the device's billable pages for each meter are exactly those actual sums."
        PRD: "Each `StatementLine` records its parent `statement_id`, the `device_id` it prices, the `page_class`, the `pages` it covers, the `rate_micro_dollars_per_page` copied from the statement's selected rate for that class, and an `amount_cents` computed as the pages multiplied by that rate, divided by 10,000, and rounded half up to a whole cent."

        Design: Difficulty/cross_entity_state_dependency/period_close_gated_on_meter_read_exception_backlog
        """
        env = _swept_period_with_one_open_offline_exception()
        validate_error(
            api.close_billing_period(env["period_id"], BILLING_HEADERS),
            ApiErrorId.ERR_PERIOD_HAS_OPEN_EXCEPTIONS,
        )
        validate_success(
            api.resolve_meter_read_exception(
                env["exception_read"]["id"],
                resolve_exception_payload(
                    corrected_mono_meter=5_000,
                    corrected_color_meter=0,
                    corrected_toner_level_pct=60,
                ),
                SECOND_OPS_HEADERS,
            )
        )

        statement = validate_success(
            api.close_billing_period(env["period_id"], BILLING_HEADERS), 201
        )

        assert_fields(
            statement,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=5_000,
            color_pages_billed=0,
            usage_subtotal_cents=4_688,
            shortfall_cents=0,
            service_labor_cents=0,
            sla_credit_cents=0,
            waste_penalty_cents=0,
            total_cents=4_688,
        )
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="CLOSED",
            final_total_cents=4_688,
            exception_open_count=0,
            sweep_run_count=1,
        )

    def test_the_unblocked_close_cascades_onto_the_contract_ledger(self, api):
        """A period that never carried a projection contributes nothing to the true-up.

        PRD: "Closing creates the final statement, sets `status` to `CLOSED` and `final_total_cents` to the statement's `total_cents`, and then cascades onto the contract: `lifetime_billed_cents` grows by the statement's `total_cents`, and `true_up_balance_cents` grows by the period's `final_total_cents` less its `provisional_total_cents` — treating a null `provisional_total_cents` as equal to the final total, so that a period which never carried a projection contributes exactly zero to the true-up."

        Design: Difficulty/cross_entity_state_dependency/period_close_gated_on_meter_read_exception_backlog
        """
        env = _swept_period_with_one_open_offline_exception()
        validate_success(
            api.resolve_meter_read_exception(
                env["exception_read"]["id"],
                resolve_exception_payload(
                    corrected_mono_meter=5_000,
                    corrected_color_meter=0,
                    corrected_toner_level_pct=60,
                ),
                SECOND_OPS_HEADERS,
            )
        )

        validate_success(api.close_billing_period(env["period_id"], BILLING_HEADERS), 201)

        assert_fields(
            fetch_contract(env["contract_id"]),
            lifetime_billed_cents=4_688,
            true_up_balance_cents=0,
        )
